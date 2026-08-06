"""
Orchestrator: runs all four scrapers, filters/dedupes, and sends the digest
to Telegram. Designed to run as a GitHub Actions cron job (see
.github/workflows/job_scraper.yml).

Each source is isolated with try/except -- if one source breaks (site
redesign, temporary block, etc.) the others still run and the digest still
goes out with whatever succeeded, plus a note about what failed.
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

    seen = dedupe.load_seen()
    new_jobs, updated_seen = dedupe.filter_new_and_update(all_jobs, seen)
    log.info("New (unseen) jobs this run: %d", len(new_jobs))

    jobs_by_source = {name: [] for name, _ in SOURCES}
    for job in new_jobs:
        jobs_by_source.setdefault(job["source"], []).append(job)

    if failed_sources:
        log.warning("Sources that failed this run: %s", ", ".join(failed_sources))

    ok = telegram_notify.send_digest(jobs_by_source)

    dedupe.save_seen(updated_seen)

    if not ok:
        log.error("Telegram send reported failures -- check logs above")
        sys.exit(1)


if __name__ == "__main__":
    run()
