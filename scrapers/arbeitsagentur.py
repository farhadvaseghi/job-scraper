"""
Scraper for the official Bundesagentur fuer Arbeit (Arbeitsagentur) Jobsuche
API. This is a genuine public API (not scraping) -- see
https://jobsuche.api.bund.dev/ and https://github.com/bundesAPI/jobsuche-api

Field names per the published openapi.yaml:
  stellenangebote[].beruf, .refnr (v6: .referenznummer), .arbeitgeber,
  .aktuelleVeroeffentlichungsdatum, .arbeitsort.ort, .arbeitsort.plz
The `veroeffentlichtseit` param filters server-side by days-since-published,
so we don't need to compute freshness client-side for this source.

ENDPOINT FALLBACK: `/pc/v4/app/jobs` began answering "403 No match found",
which is an API-gateway routing error (the path no longer resolves), not an
auth failure -- it happened even with no optional params at all. So we try the
endpoints in config.ARBEITSAGENTUR_API_URLS in order and remember whichever
one answers, instead of assuming a single fixed path.
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
    "Accept": "application/json",
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
# We deliberately do NOT send a `zeitarbeit` param here -- temp-staffing agency
# postings are excluded client-side via config.TEMP_AGENCY_TERMS instead.
_STRICT_PARAMS = {
    "befristung": 2,  # 2 = unbefristet (permanent) only
}

# Remembered across calls once we find an endpoint that answers.
_working_url = None


def _request(url, params):
    return requests.get(
        url, headers=HEADERS, params=params, timeout=config.REQUEST_TIMEOUT
    )


def _try_endpoints(params):
    """Try each configured endpoint until one returns 200. Returns the parsed
    JSON, or None if every endpoint refused."""
    global _working_url

    urls = list(config.ARBEITSAGENTUR_API_URLS)
    if _working_url:  # prefer the one that already worked this run
        urls.remove(_working_url)
        urls.insert(0, _working_url)

    for url in urls:
        try:
            resp = _request(url, params)
        except Exception as exc:
            log.debug("Arbeitsagentur endpoint %s raised: %s", url, exc)
            continue
        if resp.status_code == 200:
            if _working_url != url:
                log.info("Arbeitsagentur: using endpoint %s", url)
                _working_url = url
            try:
                return resp.json()
            except Exception as exc:
                log.warning("Arbeitsagentur: bad JSON from %s: %s", url, exc)
                return None
        log.debug("Arbeitsagentur endpoint %s -> %s", url, resp.status_code)
    return None


def _search_one(keyword):
    base = dict(_BASE_PARAMS, was=keyword)

    # Attempt 1: with the strict server-side permanent filter.
    data = _try_endpoints(dict(base, **_STRICT_PARAMS))
    if data is None:
        # Attempt 2: without it -- permanent/temp/defense filtering still
        # happens client-side, so we lose nothing but a little bandwidth.
        data = _try_endpoints(base)
    if data is None:
        raise RuntimeError("all Arbeitsagentur endpoints refused the request")

    return data.get("stellenangebote", []) or []


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
            # v4 calls it refnr, v6 calls it referenznummer
            refnr = item.get("refnr") or item.get("referenznummer")
            if not refnr or refnr in seen_refnr:
                continue
            seen_refnr.add(refnr)

            title = to_text(item.get("beruf")) or to_text(item.get("titel"))
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

    if not jobs:
        log.warning(
            "Arbeitsagentur: 0 jobs -- if every endpoint in "
            "config.ARBEITSAGENTUR_API_URLS refused, check "
            "https://jobsuche.api.bund.dev/ for the current API path."
        )
    log.info("Arbeitsagentur: collected %d unique jobs", len(jobs))
    return jobs
