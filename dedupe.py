"""
Dedup store: tracks which job postings have already been sent to Telegram,
so reruns don't repost. Persisted as a JSON file that the GitHub Actions
workflow commits back to the repo after each run (see the workflow file).

Entries older than config.SEEN_RETENTION_DAYS are pruned automatically so the
file doesn't grow forever. Keys use the NORMALIZED job URL (see
scrapers/common.normalize_url) so a posting isn't re-sent just because its
tracking (utm_*) params changed between runs.
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


def filter_new_and_update(jobs, seen):
    """Returns (new_jobs, updated_seen_dict). Also prunes stale entries."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=config.SEEN_RETENTION_DAYS)

    # prune
    pruned = {}
    for key, seen_at in seen.items():
        try:
            ts = datetime.fromisoformat(seen_at)
        except Exception:
            continue
        if ts >= cutoff:
            pruned[key] = seen_at

    new_jobs = []
    for job in jobs:
        key = dedupe_key(job)
        if key in pruned:
            continue
        pruned[key] = now.isoformat()
        new_jobs.append(job)

    return new_jobs, pruned
