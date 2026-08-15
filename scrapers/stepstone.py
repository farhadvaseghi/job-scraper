r"""
Scraper for StepStone.de.

StepStone has no public API. It is ALSO aggressive about blocking datacenter
IPs: a plain `requests.get` from a GitHub Actions runner just hangs until it
read-times-out (that's why this source returned 0 results for every keyword).
So, like the Xing scraper, this drives a real headless Chromium via Playwright
-- a genuine browser gets a real response where raw requests get stonewalled.

The page is server-rendered HTML, so once we have the rendered content we parse
it with BeautifulSoup. Result cards carry stable `data-at` hooks --
`job-item`, `job-item-title`, `job-item-company-name`, `job-item-location`,
`job-item-timeago` -- which are used first; the older
"scan every /stellenangebote--*.html anchor" heuristic is kept as a fallback
in case those attributes disappear.

TWO BUGS FIXED HERE (both verified live 2026-08-11):

1. The search URL carried `?action=facet_selected%3Bage%3Bage_7&ag=age_7`.
   That exact query string makes StepStone black-hole the request -- it never
   responds and every keyword died on a 45s timeout, which is why this source
   reported 0 jobs for every keyword. `?ag=age_7` ALONE works fine and still
   applies the 7-day filter (2050 hits vs 5181 unfiltered on a test query).

2. Company and city were parsed with a regex expecting a `*` separator
   (`([^|]+?)\s+\*\s+([^|*]+)`), but the card text is `|`-separated, so both
   fields came out empty on every single result. That also silently disabled
   the defense-employer filter for this source, since
   passes_company_filter("") is always True -- a Rheinmetall posting was the
   top hit on the test query and would have gone straight to the channel.

Everything is wrapped in try/except per item and per keyword so a parsing
failure or a single blocked keyword never breaks the other sources or the
overall run. Requires Playwright with Chromium (installed by the workflow's
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

# Stop hammering StepStone once this many searches in a row come back empty.
# See the circuit breaker in scrape() for why.
ABORT_AFTER_BARREN_SEARCHES = 6

JOB_LINK_RE = re.compile(r"/stellenangebote--[^\"'\s]+\.html")
# "Minuten" matters: the freshest cards say "vor 34 Minuten", which used to
# fall through as an unknown age.
AGE_RE = re.compile(
    r"vor\s+(\d+)\s+(Minuten?|Stunden?|Tag(?:en)?|Wochen?)|vor\s+1\s+Woche",
    re.IGNORECASE,
)


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
    if "Minute" in unit or "Stunde" in unit:
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


def _absolute(href, base):
    if href.startswith("/"):
        return base + href
    return href


def _card_text(node, sub):
    el = node.select_one("[data-at='%s']" % sub)
    return el.get_text(" ", strip=True) if el else ""


def _parse_cards(soup, base):
    """Preferred parser: StepStone's `data-at` result cards."""
    results = []
    seen_hrefs = set()

    for card in soup.select("[data-at='job-item']"):
        try:
            link = card.select_one("[data-at='job-item-title']")
            if link is None:
                continue
            href = link.get("href") or ""
            if not href:
                anchor = link.find("a", href=True) or link.find_parent("a", href=True)
                href = anchor["href"] if anchor else ""
            if not href or not JOB_LINK_RE.search(href):
                continue
            href = _absolute(href, base)
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            title = link.get_text(" ", strip=True)
            if not title:
                continue

            raw_age = _card_text(card, "job-item-timeago")
            # snippet text is kept so passes_permanent_filter can still see a
            # "befristet auf 2 Jahre" buried in the ad body
            context = " | ".join(
                p for p in (
                    title,
                    _card_text(card, "job-item-company-name"),
                    _card_text(card, "job-item-location"),
                    _card_text(card, "jobcard-content"),
                    raw_age,
                ) if p
            )

            results.append(
                {
                    "title": title,
                    "url": href,
                    "company": _card_text(card, "job-item-company-name"),
                    "city": _card_text(card, "job-item-location"),
                    "raw_age_text": raw_age,
                    "age_days": _age_to_days(raw_age),
                    "context_text": context,
                }
            )
        except Exception:
            continue

    return results


def _parse_anchors(html, base):
    """Fallback parser: scan every job-detail anchor and read its surrounding
    text. Used only if the `data-at` card structure is gone."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_hrefs = set()

    for a in soup.find_all("a", href=True):
        if not JOB_LINK_RE.search(a["href"]):
            continue
        href = _absolute(a["href"], base)
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

        # Card text reads "Title | Company | City | ...". The previous regex
        # looked for a "*" separator that the markup does not use, so company
        # and city came back empty on every result.
        company = ""
        city = ""
        fields = [f.strip() for f in container_text.split("|") if f.strip()]
        if fields and fields[0] == title and len(fields) > 1:
            fields = fields[1:]
        if fields:
            company = fields[0]
        if len(fields) > 1 and not AGE_RE.search(fields[1]):
            city = fields[1]

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


# Fingerprints of the usual bot walls. Purely for diagnostics -- knowing
# WHICH wall we hit is the difference between "fix the selectors" and "the
# runner's IP is blocked, no selector change will help".
_BLOCK_SIGNATURES = [
    ("cloudflare", "Cloudflare challenge"),
    ("captcha", "CAPTCHA"),
    ("are you a human", "human-check interstitial"),
    ("access denied", "access denied"),
    ("unusual traffic", "unusual-traffic block"),
    ("px-captcha", "PerimeterX"),
    ("datadome", "DataDome"),
    ("incapsula", "Imperva/Incapsula"),
    ("request blocked", "request blocked"),
]


def _block_hint(html):
    lowered = (html or "").lower()
    hits = [label for sig, label in _BLOCK_SIGNATURES if sig in lowered]
    return f" [looks like: {', '.join(hits)}]" if hits else ""


def _parse_html(html, base="https://www.stepstone.de"):
    """Structured `data-at` cards if present, anchor-scan heuristic if not."""
    soup = BeautifulSoup(html, "html.parser")
    results = _parse_cards(soup, base)
    if results:
        return results
    log.debug("StepStone: no data-at cards found, falling back to anchor scan")
    return _parse_anchors(html, base)


def _search_one(page, keyword, url_template, base):
    slug = _slugify(keyword)
    url = url_template.format(slug=slug)
    # ag=age_7 = only postings from the last 7 days (server-side filter).
    # Do NOT add `action=facet_selected;age;age_7` alongside it -- that exact
    # combination makes StepStone stop responding entirely (verified: two
    # 30s timeouts in a row, while `?ag=age_7` answered in 4s).
    full_url = url + "?ag=age_7"

    # StepStone sometimes kills the first connection outright
    # (ERR_HTTP2_PROTOCOL_ERROR / ERR_CONNECTION_RESET) as an anti-bot
    # measure; a retry after a short pause usually goes through.
    last_exc = None
    response = None
    for attempt in range(1, 4):
        try:
            response = page.goto(full_url, timeout=45000, wait_until="domcontentloaded")
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
    results = _parse_html(html, base)

    # A 200 that parses to nothing is the signature of an anti-bot
    # interstitial rather than a genuinely empty result page, and the two are
    # indistinguishable in the log without this. StepStone works fine from a
    # residential IP but blocks datacenter ranges, which is exactly what a
    # GitHub Actions runner is -- so record enough to tell them apart.
    if not results:
        status = response.status if response is not None else "?"
        title = ""
        try:
            title = (page.title() or "")[:80]
        except Exception:
            pass
        log.warning(
            "StepStone: 0 cards for %r -- HTTP %s, %d bytes, title=%r%s",
            keyword, status, len(html), title,
            _block_hint(html),
        )

    return results


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

            # Germany gets the full keyword list; Austria (same markup, same
            # language, separate domain) gets the shorter DACH subset so the
            # extra country doesn't double the run time.
            searches = [
                (label, url_tpl, base, keyword)
                for label, url_tpl, base in config.STEPSTONE_SEARCHES
                for keyword in (config.KEYWORDS if label == "de"
                                else config.DACH_KEYWORDS)
            ]

            barren = 0  # consecutive searches that yielded nothing

            for label, url_tpl, base, keyword in searches:
                # Circuit breaker. When StepStone blocks us it blocks every
                # request, and each keyword then burns up to 3 x 45s of
                # retries -- 34 keywords of that would outlast the whole
                # workflow timeout and take the other sources down with it.
                if barren >= ABORT_AFTER_BARREN_SEARCHES:
                    log.error(
                        "StepStone: %d searches in a row returned nothing -- "
                        "giving up on this source for this run. This is what a "
                        "datacenter-IP block looks like; StepStone serves "
                        "residential IPs fine. Remaining searches skipped: %d",
                        barren, len(searches) - searches.index(
                            (label, url_tpl, base, keyword)),
                    )
                    break

                try:
                    results = _search_one(page, keyword, url_tpl, base)
                except Exception as exc:
                    log.warning(
                        "StepStone[%s] search failed for %r: %s", label, keyword, exc
                    )
                    barren += 1
                    continue

                barren = 0 if results else barren + 1

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
