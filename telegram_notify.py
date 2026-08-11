"""
Sends the job digest to a Telegram channel via the Bot API directly
(requests.post) -- reachable fine from GitHub Actions runners, which have
normal unrestricted internet access.
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


def format_digest(jobs_by_source):
    """jobs_by_source: dict[str, list[job_dict]] -> list of message chunks.

    Each SOURCE becomes its own Telegram message (or several, if one source
    has too many jobs to fit in one message), so results arrive grouped by
    source -- Indeed in one message, Xing in another, etc. -- rather than one
    giant mixed digest."""
    messages = []
    for source, jobs in jobs_by_source.items():
        if not jobs:
            continue
        header = f"<b>{_escape_html(source)}</b> — {len(jobs)} new job(s)"
        body = []
        for job in jobs:
            body.extend(_job_lines(job))
        messages.extend(_pack(header, body))
    return messages


def send_digest(jobs_by_source):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set -- cannot send")
        return False

    chunks = format_digest(jobs_by_source)
    if not chunks:
        log.info("No new jobs this run -- nothing to send")
        return True

    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN)
    ok = True
    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=config.REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
                ok = False
            time.sleep(1)
        except Exception as exc:
            log.error("Telegram send raised: %s", exc)
            ok = False

    return ok
