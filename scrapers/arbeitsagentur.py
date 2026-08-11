"""
Scraper for the official Bundesagentur fuer Arbeit (Arbeitsagentur) Jobsuche
API. This is a genuine public API (not scraping) -- see
https://jobsuche.api.bund.dev/ and https://github.com/bundesAPI/jobsuche-api

Confirmed field names against the published openapi.yaml:
  stellenangebote[].beruf, .refnr, .arbeitgeber,
  .aktuelleVeroeffentlichungsdatum, .arbeitsort.ort, .arbeitsort.plz
The `veroeffentlichtseit` param filters server-side by days-since-published,
so we don't need to compute freshness client-side for this source.
"""
import time

import requests

import config
from scrapers.common import (
    get_logger,
    make_job,
    passes_company_filter,
    passes_permanent_filter,
    passes_seniority_filter,
    to_text,
)

log = get_logger("arbeitsagentur")

HEADERS = {
    "User-Agent": (
        "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; "
        "iOS 15.1.0) Alamofire/5.4.4"
    ),
    "X-API-Key": config.ARBEITSAGENTUR_CLIENT_ID,
}


# Base params that are always safe. The "was" (keyword) is added per call.
_BASE_PARAMS = {
    "wo": "Deutschland",
    "angebotsart": 1,  # ARBEIT (excludes Ausbildung/Praktikum/Selbstaendigkeit)
    "veroeffentlichtseit": config.MAX_AGE_DAYS,
    "arbeitszeit": "vz",  # Vollzeit (full-time)
    "size": 100,
    "page": 1,
}

# Extra server-side filter for permanent roles. Applied ON TOP of the base
# params when possible; if the request fails we retry WITHOUT it and let the
# client-side passes_permanent_filter / passes_company_filter do the work.
#
# We deliberately do NOT send a `zeitarbeit` param here: it was the exact
# param that triggered "403 No match found" and made Arbeitsagentur return 0
# results, so it's dropped entirely (per user request). Temp-staffing agency
# postings are instead excluded client-side via config.TEMP_AGENCY_TERMS
# (matched against the employer name in passes_permanent_filter).
_STRICT_PARAMS = {
    "befristung": 2,  # 2 = unbefristet (permanent) only
}


def _request(params):
    resp = requests.get(
        config.ARBEITSAGENTUR_API_URL,
        headers=HEADERS,
        params=params,
        timeout=config.REQUEST_TIMEOUT,
    )
    return resp


def _search_one(keyword):
    base = dict(_BASE_PARAMS, was=keyword)

    # Attempt 1: with the strict server-side permanent filter.
    strict = dict(base, **_STRICT_PARAMS)
    resp = _request(strict)
    if resp.status_code == 200:
        return resp.json().get("stellenangebote", []) or []

    # Attempt 2 (fallback): the plain, well-known call without the strict
    # filter. Permanent/temp/defense filtering still happens client-side.
    log.info(
        "Arbeitsagentur %r: strict query returned %s, retrying without "
        "the befristung param", keyword, resp.status_code,
    )
    resp = _request(base)
    resp.raise_for_status()
    return resp.json().get("stellenangebote", []) or []


def scrape():
    """Returns a list of normalized job dicts. Never raises -- logs and
    returns whatever it managed to collect if a keyword search fails."""
    jobs = []
    seen_refnr = set()

    for keyword in config.KEYWORDS:
        try:
            results = _search_one(keyword)
        except Exception as exc:
            log.warning("Arbeitsagentur search failed for %r: %s", keyword, exc)
            continue

        for item in results:
            refnr = item.get("refnr") or item.get("referenznummer")
            if not refnr or refnr in seen_refnr:
                continue
            seen_refnr.add(refnr)

            title = to_text(item.get("beruf"))
            employer = to_text(item.get("arbeitgeber"))
            if not passes_seniority_filter(title):
                continue
            # belt-and-suspenders on top of the befristung API param -- catches
            # temp-agency employer names the server filter itself might miss
            if not passes_permanent_filter(f"{title} {employer}"):
                continue
            if not passes_company_filter(employer):
                continue

            arbeitsort = item.get("arbeitsort") or {}
            city = to_text(arbeitsort.get("ort"))
            posted = item.get("aktuelleVeroeffentlichungsdatum")  # 'YYYY-MM-DD'

            url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

            jobs.append(
                make_job(
                    source="Arbeitsagentur",
                    title=title,
                    company=employer,
                    city=city,
                    url=url,
                    posted_iso_date=posted,
                    raw_age_text=posted or "",
                )
            )

        time.sleep(config.REQUEST_DELAY_SECONDS)

    log.info("Arbeitsagentur: collected %d unique jobs", len(jobs))
    return jobs
