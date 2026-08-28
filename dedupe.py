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
from scrapers.common import (
    content_key,
    dedupe_key,
    get_logger,
    job_id_key,
    normalize_city_for_key,
)

log = get_logger("dedupe")


def load_seen():
    if not os.path.exists(config.SEEN_JOBS_FILE):
        return {}
    try:
        with open(config.SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            return migrate(json.load(f))
    except Exception as exc:
        log.warning("Could not read seen-jobs store, starting fresh: %s", exc)
        return {}


def save_seen(seen):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(config.SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2, sort_keys=True)


def prune(seen):
    """Drop entries older than the retention window.

    Two failure modes this guards against, both of which end in a job being
    re-sent (or the run dying outright):

    * A naive (timezone-less) timestamp -- from an older version of this file
      or a hand-edit -- raised TypeError on the `ts >= cutoff` comparison,
      which used to sit OUTSIDE the try and so killed the whole run before
      anything was scraped. Naive values are now assumed to be UTC.
    * An unparseable timestamp used to be silently dropped, which forgets a
      job and reposts it. We now KEEP it (re-stamped as of now); erring
      toward a stale entry is strictly better than spamming the channel.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=config.SEEN_RETENTION_DAYS)
    kept = {}
    for key, seen_at in seen.items():
        try:
            ts = datetime.fromisoformat(str(seen_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            log.warning(
                "Unparseable seen-timestamp %r for %s -- keeping the entry so "
                "the job is not re-sent", seen_at, key,
            )
            kept[key] = now.isoformat()
            continue
        if ts >= cutoff:
            kept[key] = seen_at
    return kept


def _keys_for(job):
    """Every key a job should be remembered under.

    Three of them, because no single one is sufficient:
      * the per-source URL      -- exact match, the historical key
      * the board's posting id  -- survives the URL slug changing, which it
        does: Xing re-lists the same posting under a different city slug and
        StepStone under a different address slug, both keeping the same id
      * title+company+city      -- catches the same posting on another board,
        where the id is different by definition
    """
    keys = [dedupe_key(job)]
    ident = job_id_key(job)
    if ident:
        keys.append(ident)
    if config.DEDUPE_ACROSS_SOURCES:
        keys.append(content_key(job))
    return keys


# Country/region tails that Indeed appends to a city ("Berlin, BE, DE" ->
# "berlin-be-de"). Only used to upgrade keys already in the store; new keys
# never contain them, because normalize_city_for_key cuts at the first comma.
_GEO_TAILS = ("-de", "-nl", "-at", "-ch")


def _upgraded_content_key(key):
    """Rewrite a stored content key to the current, city-normalised form."""
    body = key[len("content::"):]
    parts = body.split("|")
    if len(parts) != 3:
        return None
    city = parts[2]
    for tail in _GEO_TAILS:
        if city.endswith(tail):
            city = city[: -len(tail)]
            head, _, last = city.rpartition("-")
            if head and len(last) == 2:  # drop a region code like "-be"
                city = head
            break
    if city == parts[2]:
        return None
    return "content::" + "|".join([parts[0], parts[1], city])


def migrate(seen):
    """Add current-format keys for everything already in the store.

    Changing how a key is derived silently re-sends the entire backlog, which
    is the one outcome this store exists to prevent. So whenever the format
    changes, old entries are upgraded IN ADDITION to being kept -- never
    replaced -- and the run that does it commits the upgraded store.
    Idempotent: a second pass adds nothing.
    """
    added = 0
    for key, seen_at in list(seen.items()):
        if key.startswith("id::"):
            continue
        if key.startswith("content::"):
            upgraded = _upgraded_content_key(key)
            if upgraded and upgraded not in seen:
                seen[upgraded] = seen_at
                added += 1
            continue
        source, _, url = key.partition("::")
        if not url:
            continue
        ident = job_id_key({"source": source, "url": url})
        if ident and ident not in seen:
            seen[ident] = seen_at
            added += 1
    if added:
        log.info("Upgraded seen-store with %d additional dedup key(s)", added)
    return seen


def filter_new(jobs, seen):
    """Return only jobs not already in the seen store. Does NOT mark anything
    as seen -- call mark_seen() after the jobs are actually delivered."""
    new_jobs = []
    batch_keys = set()  # also dedupes within this run
    for job in jobs:
        keys = _keys_for(job)
        if any(k in seen or k in batch_keys for k in keys):
            continue
        batch_keys.update(keys)
        new_jobs.append(job)
    return new_jobs


def mark_seen(seen, jobs):
    """Record jobs as sent. Returns the updated dict."""
    now = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        for key in _keys_for(job):
            seen[key] = now
    return seen
