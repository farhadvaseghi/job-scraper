"""
Sends the job digest to a Telegram channel via the Bot API directly
(requests.post) -- reachable fine from GitHub Actions runners, which have
normal unrestricted internet access.

Telegram rate-limits bots (roughly 20 messages/minute to a channel). A big
first run can easily produce dozens of messages, which previously came back
as HTTP 429 "Too Many Requests" and lost the whole digest. So we:
  * pace sends with config.TELEGRAM_SEND_DELAY_SECONDS between messages,
  * on 429, sleep for the exact `retry_after` Telegram tells us and retry,
  * report success PER SOURCE so main.py only marks delivered jobs as seen.
"""
import time

import requests

import config
from scrapers.common import get_logger

log = get_logger("telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LEN = 4000  # Telegram's limit is 4096; leave margin


def _escape_html(text):
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _job_lines(job):
    title = _escape_html(job["title"])
    company = _escape_html(job["company"])
    city = _escape_html(job["city"])
    meta = " - ".join(p for p in [company, city] if p)
    age = f" ({_escape_html(job['raw_age_text'])})" if job.get("raw_age_text") else ""
    out = [f'• <a href="{job["url"]}">{title}</a>{age}']
    if meta:
        out.append(f"  {meta}")
    return out


def _pack(header, body_lines):
    """Combine a header with body lines into one or more messages, each under
    Telegram's length limit. The header is repeated (with a "cont." marker) if
    a single source's jobs overflow into multiple messages."""
    messages = []
    current = header
    for line in body_lines:
        if len(current) + len(line) + 1 > MAX_MESSAGE_LEN:
            messages.append(current)
            current = header + " (cont.)\n" + line
        else:
            current = current + "\n" + line
    messages.append(current)
    return messages


def format_source_messages(source, jobs):
    """Build the message list for a single source."""
    header = f"<b>{_escape_html(source)}</b> — {len(jobs)} new job(s)"
    body = []
    for job in jobs:
        body.extend(_job_lines(job))
    return _pack(header, body)


def format_digest(jobs_by_source):
    """All messages across all sources (kept for testing/back-compat)."""
    messages = []
    for source, jobs in jobs_by_source.items():
        if jobs:
            messages.extend(format_source_messages(source, jobs))
    return messages


def _send_message(url, text):
    """Send one message, retrying on rate limits. Returns True if delivered."""
    for attempt in range(1, config.TELEGRAM_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=config.REQUEST_TIMEOUT,
            )
        except Exception as exc:
            log.warning("Telegram send raised (attempt %d): %s", attempt, exc)
            time.sleep(config.TELEGRAM_SEND_DELAY_SECONDS * attempt)
            continue

        if resp.status_code == 200:
            return True

        if resp.status_code == 429:
            # Telegram tells us exactly how long to wait -- respect it.
            wait = config.TELEGRAM_SEND_DELAY_SECONDS
            try:
                wait = int(resp.json()["parameters"]["retry_after"])
            except Exception:
                pass
            log.warning(
                "Telegram rate-limited (attempt %d/%d) -- waiting %ss",
                attempt, config.TELEGRAM_MAX_RETRIES, wait + 1,
            )
            time.sleep(wait + 1)
            continue

        # Any other error (bad HTML, message too long, etc.) won't be fixed
        # by retrying.
        log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        return False

    log.error("Telegram send gave up after %d attempts", config.TELEGRAM_MAX_RETRIES)
    return False


def send_digest(jobs_by_source):
    """Sends one message per source (more if a source is large).

    Returns (ok, delivered_sources): `delivered_sources` is the set of sources
    whose messages ALL went through -- main.py marks only those jobs as seen,
    so anything that failed is retried on the next run instead of being lost.
    """
    delivered = set()

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set -- cannot send")
        return False, delivered

    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN)
    ok = True
    first = True

    for source, jobs in jobs_by_source.items():
        if not jobs:
            continue
        messages = format_source_messages(source, jobs)
        source_ok = True
        for text in messages:
            if not first:
                time.sleep(config.TELEGRAM_SEND_DELAY_SECONDS)
            first = False
            if not _send_message(url, text):
                source_ok = False
                ok = False
        if source_ok:
            delivered.add(source)
            log.info("Telegram: delivered %d %s job(s)", len(jobs), source)
        else:
            log.error(
                "Telegram: %s not fully delivered -- its jobs stay unseen and "
                "will be retried next run", source,
            )

    if not any(jobs for jobs in jobs_by_source.values()):
        log.info("No new jobs this run -- nothing to send")

    return ok, delivered
