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
from scrapers.common import get_logger, to_text

log = get_logger("telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LEN = 4000  # Telegram's limit is 4096; leave margin


def _escape_html(text):
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_attr(url):
    """Escape a URL for use inside an href="..." attribute.

    Telegram parses the message as HTML, so an unescaped '&' -- which nearly
    every Indeed URL has (?jk=...&from=...) -- can be read as a broken entity
    and a '"' terminates the attribute outright. Either way Telegram answers
    400 "can't parse entities", which is NOT retryable: the source was marked
    undelivered forever and its jobs were re-fetched and re-failed every run.
    """
    return _escape_html(url).replace('"', "&quot;").replace("'", "&#39;")


# Longest a single job line may be. Telegram rejects an over-long message
# outright, and _pack cannot split a line, so an absurd title must be cut
# here rather than poisoning the whole message.
MAX_LINE_LEN = 900


def _clip(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _job_lines(job):
    """The lines for one job. Returned as a group so _pack never splits a
    title away from its company/city line."""
    title = _escape_html(_clip(to_text(job.get("title")) or "(untitled)", 200))
    company = _escape_html(_clip(to_text(job.get("company")), 120))
    city = _escape_html(_clip(to_text(job.get("city")), 80))
    meta = " - ".join(p for p in [company, city] if p)
    raw_age = to_text(job.get("raw_age_text"))
    age = f" ({_escape_html(_clip(raw_age, 40))})" if raw_age else ""

    url = to_text(job.get("url"))
    if url.startswith("http"):
        head = f'• <a href="{_escape_attr(url)}">{title}</a>{age}'
    else:
        # No usable link -- still worth sending, just not as an anchor.
        head = f"• {title}{age}"

    out = [_clip(head, MAX_LINE_LEN)]
    if meta:
        out.append(_clip(f"  {meta}", MAX_LINE_LEN))
    return out


def _pack(header, line_groups):
    """Combine a header with groups of body lines into messages under
    Telegram's length limit. The header is repeated (with a "cont." marker)
    when a source's jobs overflow into multiple messages.

    Takes GROUPS rather than flat lines so one job's title and its
    company/city line are never split across two messages.
    """
    messages = []
    current = header
    for group in line_groups:
        block = "\n".join(group)
        if len(current) + len(block) + 1 > MAX_MESSAGE_LEN and current != header:
            messages.append(current)
            current = header + " (cont.)\n" + block
        else:
            current = current + "\n" + block
    messages.append(current)
    return messages


def format_source_messages(source, jobs):
    """Build the message list for a single source."""
    header = f"<b>{_escape_html(source)}</b> — {len(jobs)} new job(s)"
    return _pack(header, [_job_lines(job) for job in jobs])


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

        if resp.status_code >= 500:
            # Telegram-side hiccup, not our message -- worth another go.
            log.warning(
                "Telegram server error %s (attempt %d/%d) -- retrying",
                resp.status_code, attempt, config.TELEGRAM_MAX_RETRIES,
            )
            time.sleep(config.TELEGRAM_SEND_DELAY_SECONDS * attempt)
            continue

        # Any other error (bad HTML, message too long, etc.) won't be fixed
        # by retrying.
        log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        return False

    log.error("Telegram send gave up after %d attempts", config.TELEGRAM_MAX_RETRIES)
    return False


def send_note(text):
    """Send a one-off operational note (e.g. "source X returned nothing").

    Deliberately separate from send_digest and its return value: a note that
    fails to send must never influence which job sources count as delivered,
    or invariant #1 would be back in play.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN)
    return _send_message(url, _clip(text, MAX_MESSAGE_LEN))


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
