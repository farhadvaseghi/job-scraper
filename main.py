"""
Orchestrator: runs all four scrapers, filters/dedupes, and sends the digest
to Telegram. Designed to run from GitHub Actions (see
.github/workflows/job_scraper.yml).

Each source is isolated with try/except -- if one source breaks (site
redesign, temporary block, etc.) the others still run and the digest still
goes out with whatever succeeded, plus a note about what failed.

Jobs are marked as "seen" ONLY after Telegram confirms delivery, so a failed
or rate-limited send means those jobs are retried next run rather than being
silently dropped.
"""
import sys

import config
import dedupe
import telegram_notify
from scrapers.common import (
    automotive_score,
    get_logger,
    passes_city_filter,
    passes_relevance_filter,
    rank_jobs,
)
from scrapers import arbeitsagentur, indeed, stepstone, xing

log = get_logger("main")

ALL_SOURCES = [
    ("Arbeitsagentur", arbeitsagentur.scrape),
    ("Indeed", indeed.scrape),
    ("StepStone", stepstone.scrape),
    ("Xing", xing.scrape),
]

# A source switched off in config.DISABLED_SOURCES is dropped here rather than
# skipped later, so it is invisible to everything downstream -- including the
# "returned nothing" health note, which would otherwise fire for a source that
# was never meant to run.
SOURCES = [
    (name, fn) for name, fn in ALL_SOURCES
    if name not in config.DISABLED_SOURCES
]


def run():
    all_jobs = []
    failed_sources = []
    collected = {}

    disabled = [n for n, _ in ALL_SOURCES if n not in dict(SOURCES)]
    if disabled:
        log.info("Sources disabled in config: %s", ", ".join(disabled))

    for name, scrape_fn in SOURCES:
        log.info("Running scraper: %s", name)
        try:
            jobs = scrape_fn()
            collected[name] = len(jobs)
            all_jobs.extend(jobs)
        except Exception as exc:
            log.error("Source %s crashed entirely: %s", name, exc)
            collected[name] = 0
            failed_sources.append(name)

    log.info(
        "Collected per source: %s",
        ", ".join(f"{name}={collected.get(name, 0)}" for name, _ in SOURCES),
    )
    log.info("Total jobs collected across all sources: %d", len(all_jobs))

    # Relevance / location gates, applied here rather than in each scraper so
    # all four sources are filtered identically and the drop counts are
    # visible in one place. Both are configurable in config.py.
    relevant = [j for j in all_jobs if passes_relevance_filter(j["title"])]
    if len(relevant) != len(all_jobs):
        log.info(
            "Relevance filter dropped %d off-topic title(s), %d left",
            len(all_jobs) - len(relevant), len(relevant),
        )

    located = [j for j in relevant if passes_city_filter(j["city"])]
    if len(located) != len(relevant):
        log.info(
            "City filter dropped %d posting(s) outside the target cities, %d left",
            len(relevant) - len(located), len(located),
        )

    seen = dedupe.prune(dedupe.load_seen())
    new_jobs = dedupe.filter_new(located, seen)
    log.info("New (unseen) jobs this run: %d", len(new_jobs))

    # group by source, applying the per-run cap so a huge batch doesn't flood
    # the channel / trip Telegram's rate limit. Uncapped leftovers stay unseen
    # and come through on the next run.
    jobs_by_source = {name: [] for name, _ in SOURCES}
    for job in new_jobs:
        jobs_by_source.setdefault(job["source"], []).append(job)

    # Rank BEFORE capping, so the cap discards the least relevant postings
    # rather than whatever happened to be collected last. Ranking never drops
    # anything -- see rank_jobs.
    for source, jobs in jobs_by_source.items():
        jobs_by_source[source] = rank_jobs(jobs)

    for source, jobs in jobs_by_source.items():
        cap = config.cap_for(source)
        if cap and len(jobs) > cap:
            kept_priority = sum(1 for j in jobs[:cap] if automotive_score(j))
            dropped_priority = sum(1 for j in jobs[cap:] if automotive_score(j))
            log.info(
                "%s: capping %d jobs to %d this run (rest come next run); "
                "%d automotive kept, %d deferred",
                source, len(jobs), cap, kept_priority, dropped_priority,
            )
            jobs_by_source[source] = jobs[:cap]

    if failed_sources:
        log.warning("Sources that failed this run: %s", ", ".join(failed_sources))

    ok, delivered_sources = telegram_notify.send_digest(jobs_by_source)

    # Only remember what actually reached Telegram.
    sent_jobs = [
        job
        for source in delivered_sources
        for job in jobs_by_source.get(source, [])
    ]
    dedupe.mark_seen(seen, sent_jobs)
    dedupe.save_seen(seen)
    log.info("Marked %d delivered job(s) as seen", len(sent_jobs))

    # Tell the channel when a source produced nothing. A source that quietly
    # returns 0 looks identical to "no new jobs today" in the digest, which is
    # how the Arbeitsagentur scraper went on reading v4 field names against a
    # v6 response -- collecting zero on every run -- without anyone noticing.
    # Sent last and its result ignored, so it cannot affect dedup accounting.
    dead = [name for name, _ in SOURCES if not collected.get(name)]
    if dead:
        detail = ", ".join(
            f"{name}{' (crashed)' if name in failed_sources else ''}"
            for name in dead
        )
        log.warning("Sources that returned nothing this run: %s", detail)
        try:
            telegram_notify.send_note(
                f"⚠️ <b>Scraper health</b>: no results from {detail}. "
                f"Check the Actions log."
            )
        except Exception as exc:  # never let the note break the run
            log.warning("Could not send the health note: %s", exc)

    if not ok:
        log.error("Telegram send reported failures -- check logs above")
        sys.exit(1)


if __name__ == "__main__":
    run()
