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
from scrapers.common import get_logger
from scrapers import arbeitsagentur, indeed, stepstone, xing

log = get_logger("main")

SOURCES = [
    ("Arbeitsagentur", arbeitsagentur.scrape),
    ("Indeed", indeed.scrape),
    ("StepStone", stepstone.scrape),
    ("Xing", xing.scrape),
]


def run():
    all_jobs = []
    failed_sources = []

    for name, scrape_fn in SOURCES:
        log.info("Running scraper: %s", name)
        try:
            jobs = scrape_fn()
            all_jobs.extend(jobs)
        except Exception as exc:
            log.error("Source %s crashed entirely: %s", name, exc)
            failed_sources.append(name)

    log.info("Total jobs collected across all sources: %d", len(all_jobs))

    seen = dedupe.prune(dedupe.load_seen())
    new_jobs = dedupe.filter_new(all_jobs, seen)
    log.info("New (unseen) jobs this run: %d", len(new_jobs))

    # group by source, applying the per-run cap so a huge batch doesn't flood
    # the channel / trip Telegram's rate limit. Uncapped leftovers stay unseen
    # and come through on the next run.
    jobs_by_source = {name: [] for name, _ in SOURCES}
    for job in new_jobs:
        jobs_by_source.setdefault(job["source"], []).append(job)

    cap = config.MAX_JOBS_PER_SOURCE_PER_RUN
    if cap:
        for source, jobs in jobs_by_source.items():
            if len(jobs) > cap:
                log.info(
                    "%s: capping %d jobs to %d this run (rest come next run)",
                    source, len(jobs), cap,
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

    if not ok:
        log.error("Telegram send reported failures -- check logs above")
        sys.exit(1)


if __name__ == "__main__":
    run()
