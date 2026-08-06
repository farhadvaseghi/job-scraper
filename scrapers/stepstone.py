"""
Scraper for StepStone.de.

StepStone has no public API, so this scrapes their server-rendered search
results page (confirmed to be server-rendered HTML, not JS-only, by manual
inspection). Job detail links reliably match the pattern
`/stellenangebote--...html`, and each result card includes a relative
freshness string like "vor 2 Tagen" / "vor 1 Woche" / "vor 3 Stunden" -- we
use both the `age_7` server-side filter AND a client-side re-check since the
server filter's exact boundary behavior isn't publicly documented.

NOTE: parsing company name / precise date relies on text-proximity
heuristics rather than exact CSS class names (which can change without
notice). If StepStone changes their markup, this scraper may start
returning fewer/no results -- it's wrapped in try/except per item and per
keyword so a parsing failure here never breaks the other sources or the
overall run.
"""
import re
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

import config
from scrapers.common import (
    get_logger,
    make_job,
    passes_company_filter,
    passes_permanent_filter,
    passes_seniority_filter,
)

log = get_logger("stepstone")

JOB_LINK_RE = re.compile(r"/stellenangebote--[^\"'\s]+\.html")
AGE_RE = re.compile(r"vor\s+(\d+)\s+(Stunden?|Tag(?:en)?|Wochen?)|vor\s+1\s+Woche", re.IGNORECASE)


def _slugify(keyword):
    text = unicodedata.normalize("NFKD", keyword)
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "job"


def _age_to_days(age_text):
    if not age_text:
        return None
    m = AGE_RE.search(age_text)
    if not m:
        return None
    if "Woche" in age_text:
        num = re.search(r"(\d+)\s+Woche", age_text)
        weeks = int(num.group(1)) if num else 1
        return weeks * 7
    num, unit = m.group(1), m.group(2) or ""
    if not num:
        return 0
    num = int(num)
    if "Stunde" in unit:
        return 0
    if "Tag" in unit:
        return num
    return None


def _find_container(anchor):
    node = anchor
    for _ in range(6):
        if node.parent is None:
            break
        node = node.parent
        text = node.get_text(" | ", strip=True)
        if AGE_RE.search(text):
            return node
    return anchor.parent or anchor


def _search_one(keyword):
    slug = _slugify(keyword)
    url = config.STEPSTONE_SEARCH_URL.format(slug=slug)
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"}
    params = {"action": "facet_selected;age;age_7", "ag": "age_7"}

    resp = requests.get(url, headers=headers, params=params, timeout=config.REQUEST_TIMEOUT)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    seen_hrefs = set()

    for a in soup.find_all("a", href=True):
        if not JOB_LINK_RE.search(a["href"]):
            continue
        href = a["href"]
        if href.startswith("/"):
            href = "https://www.stepstone.de" + href
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        title = a.get_text(strip=True)
        if not title:
            continue

        try:
            container = _find_container(a)
            container_text = container.get_text(" | ", strip=True)
        except Exception:
            container_text = ""

        age_match = AGE_RE.search(container_text)
        raw_age = age_match.group(0) if age_match else ""

        company = ""
        city = ""
        star_match = re.search(r"([^|]+?)\s+\*\s+([^|*]+)", container_text)
        if star_match:
            company = star_match.group(1).strip()
            city = star_match.group(2).strip()

        results.append(
            {
                "title": title,
                "url": href,
                "company": company,
                "city": city,
                "raw_age_text": raw_age,
                "age_days": _age_to_days(raw_age),
                "context_text": container_text,  # carries "Befristung: ..." if present
            }
        )

    return results


def scrape():
    jobs = []
    seen_urls = set()

    for keyword in config.KEYWORDS:
        try:
            results = _search_one(keyword)
        except Exception as exc:
            log.warning("StepStone search failed for %r: %s", keyword, exc)
            continue

        for item in results:
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = item["title"]
            if not passes_seniority_filter(title):
                continue
            check_text = f"{title} {item.get('company', '')} {item.get('context_text', '')}"
            if not passes_permanent_filter(check_text):
                continue
            if not passes_company_filter(item.get("company", "")):
                continue

            age_days = item.get("age_days")
            if age_days is not None and age_days > config.MAX_AGE_DAYS:
                continue

            jobs.append(
                make_job(
                    source="StepStone",
                    title=title,
                    company=item.get("company", ""),
                    city=item.get("city", ""),
                    url=url,
                    posted_iso_date=None,
                    raw_age_text=item.get("raw_age_text", ""),
                )
            )

        time.sleep(config.REQUEST_DELAY_SECONDS)

    log.info("StepStone: collected %d unique jobs", len(jobs))
    return jobs
