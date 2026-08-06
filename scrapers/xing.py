"""
Scraper for Xing Jobs.

IMPORTANT CAVEAT: Xing is a JS-rendered single-page app, and unlike the other
three sources, I (the assistant that wrote this) was never able to actually
load Xing's job search page during development -- it's blocklisted in my own
tool environment for policy reasons, so this scraper is written from general
knowledge of how modern job-search SPAs structure their markup (data-testid
attributes on job cards), NOT verified against Xing's real DOM.

It is very likely the CSS selectors below need adjustment after your first
live run. Check the Actions log: if you see "Xing: 0 jobs found, selectors
may need updating" every run, that's the signal to inspect Xing's actual
page source (e.g. via browser devtools) and update SELECTORS below.

Requires Playwright with Chromium installed (see requirements.txt / the
workflow's `playwright install chromium` step).
"""
import re
import time

import config
from scrapers.common import get_logger, make_job, passes_seniority_filter

log = get_logger("xing")

# Best-effort candidate selectors for job result cards. Tried in order;
# first one that matches >0 elements is used.
CARD_SELECTOR_CANDIDATES = [
    "[data-testid='job-search-result']",
    "[data-testid='job-teaser']",
    "article[data-testid]",
    "li[data-testid*='job']",
    "article",
]

AGE_RE = re.compile(r"vor\s+(\d+)\s+(Stunden?|Tag(?:en)?|Wochen?)|vor\s+1\s+Woche|heute", re.IGNORECASE)


def _age_to_days(text):
    if not text:
        return None
    if re.search(r"heute", text, re.IGNORECASE):
        return 0
    m = AGE_RE.search(text)
    if not m:
        return None
    if "Woche" in text:
        num = re.search(r"(\d+)\s+Woche", text)
        return (int(num.group(1)) if num else 1) * 7
    num, unit = m.group(1), m.group(2) or ""
    if not num:
        return None
    num = int(num)
    return 0 if "Stunde" in unit else num


def _search_one(page, keyword):
    from urllib.parse import urlencode

    url = config.XING_SEARCH_URL + "?" + urlencode({"keywords": keyword})
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    time.sleep(2)  # let client-side rendering settle

    cards = []
    for selector in CARD_SELECTOR_CANDIDATES:
        found = page.query_selector_all(selector)
        if found:
            cards = found
            break

    results = []
    for card in cards:
        try:
            text = card.inner_text()
            link_el = card.query_selector("a[href*='/jobs/']")
            href = link_el.get_attribute("href") if link_el else None
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.xing.com" + href

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            title = lines[0] if lines else ""
            company = lines[1] if len(lines) > 1 else ""
            city = lines[2] if len(lines) > 2 else ""

            age_match = AGE_RE.search(text)
            raw_age = age_match.group(0) if age_match else ""

            results.append(
                {
                    "title": title,
                    "company": company,
                    "city": city,
                    "url": href,
                    "raw_age_text": raw_age,
                    "age_days": _age_to_days(raw_age),
                }
            )
        except Exception:
            continue

    return results


def scrape():
    jobs = []
    seen_urls = set()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright not installed -- skipping Xing (see requirements.txt)")
        return jobs

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=config.USER_AGENT, locale="de-DE")

            for keyword in config.KEYWORDS:
                try:
                    results = _search_one(page, keyword)
                except Exception as exc:
                    log.warning("Xing search failed for %r: %s", keyword, exc)
                    continue

                for item in results:
                    url = item["url"]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title = item["title"]
                    if not title or not passes_seniority_filter(title):
                        continue

                    age_days = item.get("age_days")
                    if age_days is not None and age_days > config.MAX_AGE_DAYS:
                        continue

                    jobs.append(
                        make_job(
                            source="Xing",
                            title=title,
                            company=item.get("company", ""),
                            city=item.get("city", ""),
                            url=url,
                            posted_iso_date=None,
                            raw_age_text=item.get("raw_age_text", ""),
                        )
                    )

                time.sleep(config.REQUEST_DELAY_SECONDS)

            browser.close()
    except Exception as exc:
        log.error("Xing scraper crashed: %s", exc)

    if not jobs:
        log.warning(
            "Xing: 0 jobs found -- selectors in scrapers/xing.py likely need "
            "updating against Xing's current page markup."
        )
    log.info("Xing: collected %d unique jobs", len(jobs))
    return jobs
