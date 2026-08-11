"""
Scraper for StepStone.de.

StepStone has no public API. It is ALSO aggressive about blocking datacenter
IPs: a plain `requests.get` from a GitHub Actions runner just hangs until it
read-times-out (that's why this source returned 0 results for every keyword).
So, like the Xing scraper, this drives a real headless Chromium via Playwright
-- a genuine browser gets a real response where raw requests get stonewalled.

The page is server-rendered HTML, so once we have the rendered content we parse
it with BeautifulSoup exactly as before: job detail links reliably match the
pattern `/stellenangebote--...html`, and each result card carries a relative
freshness string like "vor 2 Tagen" / "vor 1 Woche" / "vor 3 Stunden".

NOTE: parsing company name / precise date relies on text-proximity heuristics
rather than exact CSS class names (which can change without notice). Everything
is wrapped in try/except per item and per keyword so a parsing failure or a
single blocked keyword never breaks the other sources or the overall run.
Requires Playwright with Chromium (installed by the workflow's
`playwright install chromium` step).
"""
import re
import time
import unicodedata

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


def _parse_html(html):
    soup = BeautifulSoup(html, "html.parser")
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


def _search_one(page, keyword):
    slug = _slugify(keyword)
    url = config.STEPSTONE_SEARCH_URL.format(slug=slug)
    # age_7 = only postings from the last 7 days (server-side freshness filter)
    full_url = url + "?action=facet_selected%3Bage%3Bage_7&ag=age_7"

    # StepStone sometimes kills the first connection outright
    # (ERR_HTTP2_PROTOCOL_ERROR / ERR_CONNECTION_RESET) as an anti-bot
    # measure; a retry after a short pause usually goes through.
    last_exc = None
    for attempt in range(1, 4):
        try:
            page.goto(full_url, timeout=45000, wait_until="domcontentloaded")
            break
        except Exception as exc:
            last_exc = exc
            log.debug("StepStone goto attempt %d failed for %r: %s", attempt, keyword, exc)
            time.sleep(2 * attempt)
    else:
        raise last_exc

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    time.sleep(2)  # let any late-rendered results settle

    html = page.content()
    return _parse_html(html)


def scrape():
    jobs = []
    seen_urls = set()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright not installed -- skipping StepStone (see requirements.txt)")
        return jobs

    try:
        with sync_playwright() as p:
            # --disable-http2 is the important one: StepStone was tearing down
            # every request with ERR_HTTP2_PROTOCOL_ERROR within ~30ms, which
            # is a protocol-level bot rejection rather than a real network
            # fault. Forcing HTTP/1.1 sidesteps it. The other flags remove the
            # most obvious headless-automation tells.
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-http2",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=config.USER_AGENT,
                locale="de-DE",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,*/*;q=0.8"
                    ),
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            page = context.new_page()

            for keyword in config.KEYWORDS:
                try:
                    results = _search_one(page, keyword)
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

            browser.close()
    except Exception as exc:
        log.error("StepStone scraper crashed: %s", exc)

    log.info("StepStone: collected %d unique jobs", len(jobs))
    return jobs
