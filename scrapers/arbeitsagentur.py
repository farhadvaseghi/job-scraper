"""
Scraper for the official Bundesagentur fuer Arbeit (Arbeitsagentur) Jobsuche
API. This is a genuine public API (not scraping) -- see
https://jobsuche.api.bund.dev/ and https://github.com/bundesAPI/jobsuche-api

ENDPOINT FALLBACK: every `/pc/v4*` and `/pc/v5` path now answers
"403 No match found", which is an API-gateway routing error (the path no
longer resolves), not an auth failure -- it happens even with no optional
params at all. Only `/pc/v6/jobs` still responds. We try the endpoints in
config.ARBEITSAGENTUR_API_URLS in order and remember whichever one answers.

SCHEMA: v6 renamed *every* field this scraper reads, and because the old
names simply came back missing the source silently collected 0 jobs on every
run while still logging success. Both shapes are handled via the _pick /
_v6_* helpers below:

  | meaning   | v4                             | v6                              |
  |-----------|--------------------------------|---------------------------------|
  | list      | stellenangebote                | ergebnisliste                   |
  | id        | refnr                          | referenznummer                  |
  | title     | beruf / titel                  | stellenangebotsTitel            |
  | employer  | arbeitgeber                    | firma                           |
  | city      | arbeitsort.ort                 | stellenlokationen[0].adresse.ort|
  | published | aktuelleVeroeffentlichungsdatum| datumErsteVeroeffentlichung     |

v6 also exposes `vertragsdauer` (UNBEFRISTET / BEFRISTET), which is a far
more reliable permanent-role signal than text matching, so it is used as an
extra gate when present.

The `veroeffentlichtseit` param filters server-side by days-since-published,
so we don't need to compute freshness client-side for this source. `size` is
capped at 100 by the API, so results are paginated up to
config.ARBEITSAGENTUR_MAX_PAGES.
"""
import time
from urllib.parse import quote

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
    "size": 100,  # API hard-caps this at 100 regardless of what we ask for
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

# Set to False for the rest of the run if the server rejects _STRICT_PARAMS,
# so we stop paying for a doomed extra request on every page of every keyword.
_strict_supported = True


def _pick(item, *names):
    """First non-empty value among `names`, so v4 and v6 field names can both
    be read without branching on which endpoint answered."""
    for name in names:
        value = to_text(item.get(name))
        if value:
            return value
    return ""


def _v6_city(item):
    """v6: stellenlokationen[0].adresse.ort -- v4: arbeitsort.ort."""
    for lokation in item.get("stellenlokationen") or []:
        if isinstance(lokation, dict):
            city = to_text((lokation.get("adresse") or {}).get("ort"))
            if city:
                return city
    return to_text((item.get("arbeitsort") or {}).get("ort"))


def _v6_published(item):
    """ISO 'YYYY-MM-DD' publication date across both schema versions."""
    direct = _pick(item, "datumErsteVeroeffentlichung",
                   "aktuelleVeroeffentlichungsdatum")
    if direct:
        return direct[:10]
    zeitraum = item.get("veroeffentlichungszeitraum") or {}
    return to_text(zeitraum.get("von"))[:10]


def _results_of(data):
    """v6 returns `ergebnisliste`, v4 returned `stellenangebote`."""
    for key in ("ergebnisliste", "stellenangebote"):
        results = data.get(key)
        if isinstance(results, list):
            return results
    return []


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


def _fetch_page(keyword, page):
    """One page of results, degrading to the non-strict param set if the
    server refuses the strict one."""
    global _strict_supported

    base = dict(_BASE_PARAMS, was=keyword, page=page)

    if _strict_supported:
        # Attempt 1: with the strict server-side permanent filter.
        data = _try_endpoints(dict(base, **_STRICT_PARAMS))
        if data is not None:
            return data
        log.info(
            "Arbeitsagentur: server refused the 'befristung' filter -- "
            "falling back to client-side permanent filtering for this run"
        )
        _strict_supported = False

    # Attempt 2: without it -- permanent/temp/defense filtering still happens
    # client-side, so we lose nothing but a little bandwidth.
    return _try_endpoints(base)


def _search_one(keyword):
    """All pages of results for one keyword, up to the page cap."""
    items = []

    for page in range(1, config.ARBEITSAGENTUR_MAX_PAGES + 1):
        data = _fetch_page(keyword, page)
        if data is None:
            if page == 1:
                raise RuntimeError("all Arbeitsagentur endpoints refused the request")
            log.debug("Arbeitsagentur: page %d of %r refused, keeping earlier pages",
                      page, keyword)
            break

        batch = _results_of(data)
        if not batch:
            break
        items.extend(batch)

        total = data.get("maxErgebnisse")
        if isinstance(total, int) and len(items) >= total:
            break
        if len(batch) < _BASE_PARAMS["size"]:
            break  # short page => that was the last one
        time.sleep(config.REQUEST_DELAY_SECONDS)

    return items


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
            if not isinstance(item, dict):
                continue

            # v4 called it refnr, v6 calls it referenznummer
            refnr = _pick(item, "referenznummer", "refnr")
            if not refnr or refnr in seen_refnr:
                continue
            seen_refnr.add(refnr)

            title = _pick(item, "stellenangebotsTitel", "beruf", "titel", "hauptberuf")
            employer = _pick(item, "firma", "arbeitgeber")
            if not title:
                continue
            if not passes_seniority_filter(title):
                continue
            # v6 states the contract duration outright -- trust it over text
            if _pick(item, "vertragsdauer").upper() == "BEFRISTET":
                continue
            # belt-and-suspenders on top of the befristung API param -- catches
            # temp-agency employer names the server filter itself might miss
            if not passes_permanent_filter(f"{title} {employer}"):
                continue
            if not passes_company_filter(employer):
                continue

            city = _v6_city(item)
            posted = _v6_published(item)  # 'YYYY-MM-DD' or ''

            # refnrs contain '.', '_' and '-'; quote so an odd one can't
            # break out of the path segment
            url = (
                "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
                + quote(refnr, safe="")
            )

            jobs.append(
                make_job(
                    source="Arbeitsagentur",
                    title=title,
                    company=employer,
                    city=city,
                    url=url,
                    posted_iso_date=posted or None,
                    raw_age_text=posted,
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
