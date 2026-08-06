"""Shared helpers for all scrapers."""
import logging
import re

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Matches "befristet", "befristete", "befristeter", "befristetes", etc. as a
# standalone word. Deliberately does NOT match inside "unbefristet" -- there
# is no word boundary between the "n" of "un" and the "b" of "befristet"
# since both are word characters, so \b correctly refuses to match there.
_BEFRISTET_RE = re.compile(r"\bbefristet\w*", re.IGNORECASE)

# Word-boundary regex per defense-company term, built once at import time.
# \b boundaries stop short tokens like "renk" or "kmw" from matching inside
# an unrelated longer word.
_DEFENSE_RE = [
    re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
    for term in config.DEFENSE_COMPANIES
]


def get_logger(name):
    return logging.getLogger(name)


def make_job(source, title, company, city, url, posted_iso_date=None, raw_age_text=""):
    """Normalized job record used across all scrapers."""
    return {
        "source": source,
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "city": (city or "").strip(),
        "url": (url or "").strip(),
        "posted_date": posted_iso_date,  # ISO date string 'YYYY-MM-DD' or None
        "raw_age_text": raw_age_text,
    }


def passes_seniority_filter(title):
    """Drop postings that look senior/lead/management based on title text."""
    if not title:
        return True
    lowered = title.lower()
    return not any(term in lowered for term in config.SENIORITY_EXCLUDE)


def passes_permanent_filter(text):
    """Drop postings that look like fixed-term contracts or temp-staffing
    agency placements, based on free text (title, company name, and/or any
    extra snippet a scraper has available). Safe against "unbefristet"
    (permanent) -- see the comment on _BEFRISTET_RE above."""
    if not text:
        return True
    lowered = text.lower()
    if any(term in lowered for term in config.TEMP_AGENCY_TERMS):
        return False
    if _BEFRISTET_RE.search(lowered):
        return False
    return True


def passes_company_filter(company_name):
    """Drop postings from employers in the defense/military industry
    exclusion list (config.DEFENSE_COMPANIES). Matched against the
    company/employer name only -- never against title or job description
    text -- so a civilian-sector posting that merely mentions a defense
    contractor (e.g. as a client) is never wrongly excluded."""
    if not company_name:
        return True
    lowered = company_name.lower()
    return not any(rx.search(lowered) for rx in _DEFENSE_RE)


def dedupe_key(job):
    """Stable identifier for a job posting, used for the seen-jobs store."""
    return f"{job['source']}::{job['url']}"
