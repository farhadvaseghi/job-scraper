"""
Scraper for Indeed Germany.

Uses the `python-jobspy` library (https://github.com/speedyapply/JobSpy)
instead of hand-rolled HTML scraping. JobSpy talks to Indeed's own internal
GraphQL search API and is actively maintained against Indeed's markup/API
changes, which is far more robust than guessing CSS selectors.
"""
import time

import config
from scrapers.common import get_logger, make_job, passes_seniority_filter

log = get_logger("indeed")


def _search_one(keyword):
    from jobspy import scrape_jobs  # imported lazily so other scrapers don't need it

    df = scrape_jobs(
        site_name=["indeed"],
        search_term=keyword,
        location="Germany",
        country_indeed="Germany",
        results_wanted=50,
        hours_old=config.MAX_AGE_DAYS * 24,
        verbose=0,
    )
    if df is None or df.empty:
        return []
    return df.to_dict("records")


def scrape():
    jobs = []
    seen_urls = set()

    for keyword in config.KEYWORDS:
        try:
            results = _search_one(keyword)
        except Exception as exc:
            log.warning("Indeed search failed for %r: %s", keyword, exc)
            continue

        for item in results:
            url = item.get("job_url") or item.get("job_url_direct") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = item.get("title", "")
            if not passes_seniority_filter(title):
                continue

            city = item.get("location", "") or ""
            date_posted = item.get("date_posted")  # date object or NaT/None
            posted_iso = None
            try:
                if date_posted and str(date_posted) != "NaT":
                    posted_iso = str(date_posted)[:10]
            except Exception:
                posted_iso = None

            jobs.append(
                make_job(
                    source="Indeed",
                    title=title,
                    company=item.get("company", ""),
                    city=city,
                    url=url,
                    posted_iso_date=posted_iso,
                    raw_age_text=posted_iso or "",
                )
            )

        time.sleep(config.REQUEST_DELAY_SECONDS)

    log.info("Indeed: collected %d unique jobs", len(jobs))
    return jobs
