"""
Scraper for Xing Jobs.

Xing is a JS-rendered single-page app, so this drives Playwright/Chromium.

VERIFIED 2026-08-11 against the live site: `[data-testid='job-search-result']`
is the correct card selector (20 cards per search page, which is Xing's page
size), and job links are `/jobs/<city>-<slug>-<id>`. The other selectors
below are kept as fallbacks.

DO NOT add `--disable-http2` to this browser's launch args. StepStone needs
that flag, but on Xing it breaks the CDN fetch of the SPA runtime manifest --
the page loads to a bare "Failed to load manifestMap" error with zero cards,
which looks exactly like a selector problem but is not. Each scraper
launches its own browser precisely so these flag sets stay separate.

If the Actions log shows "Xing: 0 jobs found" every run, inspect the live
page source and update CARD_SELECTOR_CANDIDATES below.

Requires Playwright with Chromium installed (see requirements.txt / the
workflow's `playwright install chromium` step).
"""
import re
import time

import config
from scrapers.common import (
    get_logger,
    make_job,
    passes_company_filter,
    passes_permanent_filter,
    passes_seniority_filter,
)

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

AGE_RE = re.compile(
    r"vor\s+(\d+)\s+(Minuten?|Stunden?|Tag(?:en)?|Wochen?)|vor\s+1\s+Woche|heute",
    re.IGNORECASE,
)


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
    return 0 if ("Minute" in unit or "Stunde" in unit) else num


def _clean(text):
    """Collapse whitespace (incl. the non-breaking spaces Xing sprinkles in)."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


# Xing appends "+ 3 weitere" to the location when a job has several sites.
_MORE_LOCATIONS_RE = re.compile(r"\s*\+\s*\d+\s*weitere\s*$", re.IGNORECASE)


def _card_fields(card, text):
    """Pull (title, company, city) out of one result card.

    Reads the card's STRUCTURE, not its line order. Taking lines[0..2] was
    wrong whenever Xing prefixed a badge such as "Dringend gesucht" to the
    card -- every field then shifted by one, so the badge became the title,
    the title became the company and the company became the city. That also
    quietly defeated the defense-employer filter, which only ever sees the
    `company` field.
    """
    title = company = city = ""

    title_el = (card.query_selector("[data-testid='job-teaser-list-title']")
                or card.query_selector("h2")
                or card.query_selector("h3"))
    if title_el:
        title = _clean(title_el.inner_text())

    # company is the first <p>, location the second
    paragraphs = [_clean(p.inner_text()) for p in card.query_selector_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if paragraphs:
        company = paragraphs[0]
    if len(paragraphs) > 1:
        city = _MORE_LOCATIONS_RE.sub("", paragraphs[1])

    if title and company:
        return title, company, city

    # Fallback: line order, skipping any leading badge line that the
    # structured lookup already told us is not the title.
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if title and title in lines:
        lines = lines[lines.index(title):]
    return (
        title or (lines[0] if lines else ""),
        company or (lines[1] if len(lines) > 1 else ""),
        city or _MORE_LOCATIONS_RE.sub("", lines[2] if len(lines) > 2 else ""),
    )


def _search_one(page, keyword, location=None):
    from urllib.parse import urlencode

    params = {"keywords": keyword}
    if location:
        # Verified: location=Wien returns 21 cards, all in Vienna.
        params["location"] = location
    url = config.XING_SEARCH_URL + "?" + urlencode(params)
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

            title, company, city = _card_fields(card, text)

            # The <time> element repeats itself ("Vor 4 Tagen Vor 4 Tagen
            # veröffentlicht" -- visible label plus screen-reader text), so
            # take just the first age phrase out of it.
            age_el = card.query_selector("time")
            age_source = _clean(age_el.inner_text()) if age_el else text
            age_match = AGE_RE.search(age_source) or AGE_RE.search(text)
            raw_age = age_match.group(0) if age_match else ""

            results.append(
                {
                    "title": title,
                    "company": company,
                    "city": city,
                    "url": href,
                    "raw_age_text": raw_age,
                    "age_days": _age_to_days(raw_age),
                    "context_text": text,  # full card text, may mention contract type
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

            # Default (nationwide/Germany) uses the full keyword list; the
            # explicit Austrian/Swiss locations use the shorter DACH subset.
            searches = [
                (location, keyword)
                for location in config.XING_LOCATIONS
                for keyword in (config.KEYWORDS if location is None
                                else config.DACH_KEYWORDS)
            ]

            for location, keyword in searches:
                try:
                    results = _search_one(page, keyword, location)
                except Exception as exc:
                    log.warning(
                        "Xing search failed for %r (location=%s): %s",
                        keyword, location or "default", exc,
                    )
                    continue

                for item in results:
                    url = item["url"]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title = item["title"]
                    if not title or not passes_seniority_filter(title):
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
