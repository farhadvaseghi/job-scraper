"""
Scraper for Indeed Germany.

Uses the `python-jobspy` library (https://github.com/speedyapply/JobSpy)
instead of hand-rolled HTML scraping. JobSpy talks to Indeed's own internal
GraphQL search API and is actively maintained against Indeed's markup/API
changes, which is far more robust than guessing CSS selectors.
"""
import time

import config
from scrapers.common import (
    get_logger,
    make_job,
    passes_company_filter,
    passes_permanent_filter,
    passes_seniority_filter,
    to_text,
)

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
            # NB: jobspy returns a pandas DataFrame -> dict, so empty cells are
            # NaN floats, not "". to_text() normalizes those; the per-item
            # try/except means one malformed row can never crash the whole
            # source (which is exactly the 'float has no attribute lower' bug
            # that used to take Indeed down entirely).
            try:
                url = to_text(item.get("job_url")) or to_text(item.get("job_url_direct"))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = to_text(item.get("title"))
                company = to_text(item.get("company"))
                if not title or not passes_seniority_filter(title):
                    continue
                if not passes_permanent_filter(f"{title} {company}"):
                    continue
                if not passes_company_filter(company):
                    continue
                # JobSpy's structured job_type field ('fulltime', 'contract', etc.)
                # -- 'contract'/'temporary' is Indeed's closest equivalent to
                # "befristet"/fixed-term, so treat it the same as the text filter
                job_type = to_text(item.get("job_type")).lower()
                if "contract" in job_type or "temporary" in job_type:
                    continue

                city = to_text(item.get("location"))
                posted_iso = None
                date_posted = to_text(item.get("date_posted"))  # '' if NaN/NaT
                if date_posted and date_posted != "NaT":
                    posted_iso = date_posted[:10]

                jobs.append(
                    make_job(
                        source="Indeed",
                        title=title,
                        company=company,
                        city=city,
                        url=url,
                        posted_iso_date=posted_iso,
                        raw_age_text=posted_iso or "",
                    )
                )
            except Exception as exc:
                log.warning("Indeed: skipped a malformed record: %s", exc)
                continue

        time.sleep(config.REQUEST_DELAY_SECONDS)

    log.info("Indeed: collected %d unique jobs", len(jobs))
    return jobs
