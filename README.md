# Germany Job Scraper -> Telegram

Searches Arbeitsagentur, Indeed, StepStone, and Xing for new job postings
across Germany (junior/entry-level, full-time) matching a curated set of
keywords, and posts a digest of anything new (posted within the last 7
days, not already sent before) to a Telegram channel. Runs automatically
4x/day via GitHub Actions -- no server of your own required.

## What's included

- `config.py` -- keywords, cities, freshness window, filters. Edit this to change what's searched for.
- `scrapers/arbeitsagentur.py` -- uses the official public Jobsuche API. Most reliable source.
- `scrapers/indeed.py` -- uses the `python-jobspy` library against Indeed Germany.
- `scrapers/stepstone.py` -- scrapes StepStone's server-rendered search results.
- `scrapers/xing.py` -- Playwright-driven scraper for Xing (JS-rendered site). **Best-effort / unverified** -- see the warning at the top of that file. Check the Actions log after your first run; if it reports 0 Xing jobs every time, the selectors likely need a small update.
- `dedupe.py` -- tracks which postings were already sent, so you don't get duplicates.
- `telegram_notify.py` -- sends the digest to your Telegram channel via the Bot API.
- `main.py` -- runs everything, with each source isolated so one breaking doesn't stop the others.
- `.github/workflows/job_scraper.yml` -- the schedule (4x/day, edit the cron lines to change timing).

## One-time setup

1. **Create a GitHub repository** (private is fine) and push all these files to it, preserving the folder structure (including the `.github/workflows/` folder).

2. **Add two repo secrets** (Settings -> Secrets and variables -> Actions -> New repository secret):
   - `TELEGRAM_BOT_TOKEN` -- your bot's token (the one from @BotFather, looks like `123456:AAE...`)
   - `TELEGRAM_CHAT_ID` -- your channel's numeric ID (e.g. `-1004301040327` for your "JobsToApply" channel)

3. **Make sure your bot is an admin of the Telegram channel** (you've already done this).

4. That's it. The workflow will start running on its schedule automatically. You can also trigger a run manually anytime from the repo's **Actions** tab -> "Germany Job Scraper" -> **Run workflow** -- useful for testing before waiting on the schedule.

## Adjusting things later

- **Keywords / cities**: edit the lists in `config.py`, commit, push.
- **Schedule**: edit the `cron` lines in `.github/workflows/job_scraper.yml` (times are UTC).
- **Freshness window**: change `MAX_AGE_DAYS` in `config.py`.
- **If Xing or StepStone stop returning results**: check the Actions run log first -- it'll show which source failed and why. These two scrape HTML directly (no official API), so they're the ones most likely to need occasional small fixes if the sites redesign their pages.

## Costs

Free. GitHub Actions' free tier includes 2,000 minutes/month for private repos (unlimited for public repos) -- this workflow takes a few minutes per run, 4x/day, well within that.
