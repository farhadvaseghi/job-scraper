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
)

log = get_logger("arbeitsagentur")

HEADERS = {
    "User-Agent": (
        "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; "
        "iOS 15.1.0) Alamofire/5.4.4"
    ),
    "X-API-Key": config.ARBEITSAGENTUR_CLIENT_ID,
}


def _search_one(keyword):
    params = {
        "was": keyword,
        "wo": "Deutschland",
        "angebotsart": 1,  # ARBEIT (excludes Ausbildung/Praktikum/Selbstaendigkeit)
        "veroeffentlichtseit": config.MAX_AGE_DAYS,
        "arbeitszeit": "vz",  # Vollzeit (full-time)
        "befristung": 2,  # 2 = unbefristet (permanent) only, excludes befristet (fixed-term)
        "zeitarbeit": False,  # excludes postings from temp-staffing agencies
        "size": 100,
        "page": 1,
    }
    resp = requests.get(
        config.ARBEITSAGENTUR_API_URL,
        headers=HEADERS,
        params=params,
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
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
            refnr = item.get("refnr")
            if not refnr or refnr in seen_refnr:
                continue
            seen_refnr.add(refnr)

            title = item.get("beruf", "")
            employer = item.get("arbeitgeber", "")
            if not passes_seniority_filter(title):
                continue
            # belt-and-suspenders on top of the befristung/zeitarbeit API params --
            # catches agency employer names the API filter itself might miss
            if not passes_permanent_filter(f"{title} {employer}"):
                continue
            if not passes_company_filter(employer):
                continue

            arbeitsort = item.get("arbeitsort") or {}
            city = arbeitsort.get("ort", "")
            posted = item.get("aktuelleVeroeffentlichungsdatum")  # 'YYYY-MM-DD'

            url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

            jobs.append(
                make_job(
                    source="Arbeitsagentur",
                    title=title,
                    company=item.get("arbeitgeber", ""),
                    city=city,
                    url=url,
                    posted_iso_date=posted,
                    raw_age_text=posted or "",
                )
            )

        time.sleep(config.REQUEST_DELAY_SECONDS)

    log.info("Arbeitsagentur: collected %d unique jobs", len(jobs))
    return jobs
