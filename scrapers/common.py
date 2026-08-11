"""Shared helpers for all scrapers."""
import logging
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

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


def to_text(value):
    """Coerce any scraper field to a clean string. Guards against pandas
    NaN (a float) and None, which otherwise blow up on .lower()/.strip()
    -- this is exactly what crashed the Indeed source before (jobspy returns
    a DataFrame whose empty cells are NaN floats, not empty strings)."""
    if value is None:
        return ""
    # pandas NaN is a float that is not equal to itself
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()


# Query-string parameters that are pure tracking noise -- they vary run to
# run (or by referrer) without changing which job the URL points to. We strip
# them before building the dedupe key so the same posting isn't re-sent just
# because its utm_* tags changed. Anything NOT listed here (e.g. Indeed's
# `jk=` job key, which IS the identity) is preserved.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {
    "layer", "ref", "referrer", "source", "campaign", "content", "term",
    "medium", "gh_src", "gh_jid", "trk", "trackingid", "recommended",
    "utm", "at_medium", "at_campaign", "wt_mc", "cid",
}


def normalize_url(url):
    """Normalize a job URL for stable deduplication: lowercase scheme/host,
    drop tracking query params, drop the fragment, and strip a trailing
    slash. Meaningful query params (like Indeed's ?jk=) are kept."""
    url = to_text(url)
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        kept = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not (k.lower() in _TRACKING_PARAM_NAMES
                    or k.lower().startswith(_TRACKING_PARAM_PREFIXES))
        ]
        query = urlencode(kept)
        path = parts.path.rstrip("/") or "/"
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), path, query, "")
        )
    except Exception:
        return url


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
    """Stable identifier for a job posting, used for the seen-jobs store.
    Uses the normalized URL so tracking-param variations don't defeat it."""
    return f"{job['source']}::{normalize_url(job['url'])}"
