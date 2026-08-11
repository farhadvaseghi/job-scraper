"""
Dedup store: tracks which job postings have already been sent to Telegram,
so reruns don't repost. Persisted as a JSON file that the GitHub Actions
workflow commits back to the repo after each run (see the workflow file).

Entries older than config.SEEN_RETENTION_DAYS are pruned automatically so the
file doesn't grow forever. Keys use the NORMALIZED job URL (see
scrapers/common.normalize_url) so a posting isn't re-sent just because its
tracking (utm_*) params changed between runs.

IMPORTANT: a job is only recorded as "seen" AFTER it was actually delivered
to Telegram (see main.py). Marking on discovery instead of on delivery meant
that when a send failed -- e.g. Telegram rate-limiting us with HTTP 429 --
the jobs were remembered as sent and silently never reached the channel.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import config
from scrapers.common import dedupe_key, get_logger

log = get_logger("dedupe")


def load_seen():
    if not os.path.exists(config.SEEN_JOBS_FILE):
        return {}
    try:
        with open(config.SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read seen-jobs store, starting fresh: %s", exc)
        return {}


def save_seen(seen):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(config.SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2, sort_keys=True)


def prune(seen):
    """Drop entries older than the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.SEEN_RETENTION_DAYS)
    kept = {}
    for key, seen_at in seen.items():
        try:
            ts = datetime.fromisoformat(seen_at)
        except Exception:
            continue
        if ts >= cutoff:
            kept[key] = seen_at
    return kept


def filter_new(jobs, seen):
    """Return only jobs not already in the seen store. Does NOT mark anything
    as seen -- call mark_seen() after the jobs are actually delivered."""
    new_jobs = []
    batch_keys = set()  # also dedupes within this run
    for job in jobs:
        key = dedupe_key(job)
        if key in seen or key in batch_keys:
            continue
        batch_keys.add(key)
        new_jobs.append(job)
    return new_jobs


def mark_seen(seen, jobs):
    """Record jobs as sent. Returns the updated dict."""
    now = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        seen[dedupe_key(job)] = now
    return seen
