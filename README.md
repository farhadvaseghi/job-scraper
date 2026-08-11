# Germany Job Scraper -> Telegram

Searches Arbeitsagentur, Indeed, StepStone, and Xing for new job postings
across Germany (junior/entry-level, full-time, permanent only -- fixed-term
contracts and temp-staffing agency postings are filtered out, and
defense/military employers are excluded) matching a curated set of keywords,
and posts a digest of anything new (posted within the last 7 days, not
already sent before) to a Telegram channel. Runs when you trigger it manually
from the Actions tab -- no server of your own required.

## What's included

- `config.py` -- keywords, cities, freshness window, filters. Edit this to change what's searched for.
- `scrapers/arbeitsagentur.py` -- uses the official public Jobsuche API. Most reliable source.
- `scrapers/indeed.py` -- uses the `python-jobspy` library against Indeed Germany.
- `scrapers/stepstone.py` -- scrapes StepStone via a real headless browser (Playwright). StepStone hangs plain HTTP requests from datacenter IPs, so a real browser is needed to get results.
- `scrapers/xing.py` -- Playwright-driven scraper for Xing (JS-rendered site). Check the Actions log after a run; if it reports 0 Xing jobs every time, the selectors likely need a small update.
- `dedupe.py` -- tracks which postings were already sent, so you don't get duplicates. Job URLs are normalized (tracking `utm_*` params stripped) so the same posting isn't re-sent when its tracking tags change, and postings are remembered for `SEEN_RETENTION_DAYS` (60) so long-lived listings aren't re-sent.
- `telegram_notify.py` -- sends the digest to your Telegram channel via the Bot API, as one message per source (Arbeitsagentur, Indeed, StepStone, Xing each arrive separately).
- `main.py` -- runs everything, with each source isolated so one breaking doesn't stop the others.
- `.github/workflows/job_scraper.yml` -- runs the scraper. Manual trigger only (no automatic schedule); re-add a `schedule:` block here if you want automatic runs.

## One-time setup

1. **Create a GitHub repository** (private is fine) and push all these files to it, preserving the folder structure (including the `.github/workflows/` folder).

2. **Add two repo secrets** (Settings -> Secrets and variables -> Actions -> New repository secret):
   - `TELEGRAM_BOT_TOKEN` -- your bot's token (the one from @BotFather, looks like `123456:AAE...`)
   - `TELEGRAM_CHAT_ID` -- your channel's numeric ID (e.g. `-1004301040327` for your "JobsToApply" channel)

3. **Make sure your bot is an admin of the Telegram channel** (you've already done this).

4. That's it. Trigger a run whenever you want from the repo's **Actions** tab -> "Germany Job Scraper" -> **Run workflow**.

## Adjusting things later

- **Keywords / cities**: edit the lists in `config.py`, commit, push.
- **Automatic runs**: the workflow is manual-trigger only. To run it on a schedule, add a `schedule:` block with a `cron` line to `.github/workflows/job_scraper.yml` (times are UTC).
- **Freshness window**: change `MAX_AGE_DAYS` in `config.py`.
- **Permanent-only filter**: edit `TEMP_AGENCY_TERMS` in `config.py` to add more staffing-agency names you keep seeing slip through. The fixed-term ("befristet") exclusion is handled separately in `scrapers/common.py` and doesn't need editing.
- **Defense/military exclusion**: edit `DEFENSE_COMPANIES` in `config.py` to add employers you want excluded.
- **If a source stops returning results**: check the Actions run log first -- each source logs its own count and any error, so you can see exactly which one failed and why.

## Costs

Free. GitHub Actions' free tier includes 2,000 minutes/month for private repos (unlimited for public repos) -- each run takes a few minutes, well within that.
