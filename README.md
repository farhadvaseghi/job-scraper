# Job Scraper -> Telegram (DE / NL / AT / CH)

Searches Arbeitsagentur, Indeed, StepStone, and Xing for new job postings
(junior/entry-level, full-time, permanent only -- fixed-term contracts and
temp-staffing agency postings are filtered out, and defense/military employers
are excluded) matching a curated set of keywords, and posts a digest of
anything new (posted within the last 7 days, not already sent before) to a
Telegram channel. Runs when you trigger it manually from the Actions tab --
no server of your own required.

## Coverage

**Currently Germany only.** `ACTIVE_COUNTRIES` in `config.py` is the single
switch — it drives the accepted city list, which Indeed domains are queried,
which StepStone site is used and which Xing locations are searched.

Netherlands, Austria and Switzerland are already built and verified; add them
to `ACTIVE_COUNTRIES` to turn them back on. What each board reaches:

| Source | DE | NL | AT | CH |
|---|:--:|:--:|:--:|:--:|
| Indeed (jobspy) | ✅ | ✅ | ✅ | ✅ |
| StepStone | ✅ | — | ✅ (`stepstone.at`) | — |
| Xing | ✅ | — | ✅ | ✅ |
| Arbeitsagentur | ✅ | — | — | — |

Results are then filtered to the cities of the active countries in
`config.CITIES_BY_COUNTRY` (remote/hybrid postings and postings with no
stated city are always kept).

## What's included

- `config.py` -- keywords, cities, freshness window, filters. Edit this to change what's searched for.
- `scrapers/arbeitsagentur.py` -- uses the official public Jobsuche API (Germany only). Note it serves the **v6** schema; the field names differ completely from v4.
- `scrapers/indeed.py` -- uses the `python-jobspy` library against Indeed DE/NL/AT/CH.
- `scrapers/stepstone.py` -- scrapes StepStone via a real headless browser (Playwright). StepStone hangs plain HTTP requests from datacenter IPs, so a real browser is needed to get results.
- `scrapers/xing.py` -- Playwright-driven scraper for Xing (JS-rendered site). Check the Actions log after a run; if it reports 0 Xing jobs every time, the selectors likely need a small update.
- `dedupe.py` -- tracks which postings were already sent, so you don't get duplicates. Job URLs are normalized (tracking `utm_*` params stripped) so the same posting isn't re-sent when its tracking tags change, and postings are remembered for `SEEN_RETENTION_DAYS` (60) so long-lived listings aren't re-sent.
- `telegram_notify.py` -- sends the digest to your Telegram channel via the Bot API, as one message per source (Arbeitsagentur, Indeed, StepStone, Xing each arrive separately).
- `main.py` -- runs everything, with each source isolated so one breaking doesn't stop the others. Also applies the relevance and city filters, and posts a health note if any source returned nothing.
- `tests/test_logic.py` -- offline tests for the filters, dedup store and Telegram formatting. Run with `python -m unittest discover -s tests -v`.
- `.github/workflows/job_scraper.yml` -- runs the scraper. Manual trigger only (no automatic schedule); re-add a `schedule:` block here if you want automatic runs.

## Automotive priority

`PRIORITIZE_AUTOMOTIVE` (default **on**) sorts automotive roles to the front
of each source *before* the per-run cap trims it, so ADAS/vehicle jobs are
never the ones discarded. They're marked with 🚗 in the digest. Nothing is
dropped for being non-automotive — this only changes ordering and what waits
for the next run. Tune via `AUTOMOTIVE_TITLE_TERMS` and
`AUTOMOTIVE_COMPANIES`.

## Cutting down the volume

Four knobs in `config.py`, in rough order of impact:

- `RESTRICT_TO_CITIES` (default **on**) -- drop postings outside `CITIES_BY_COUNTRY`. Remote/hybrid and unknown-location postings are kept.
- `REQUIRE_RELEVANT_TITLE` (default **on**) -- the title must contain an engineering stem from `RELEVANCE_TERMS`, and must not contain anything from `TITLE_EXCLUDE_TERMS`. The boards match loosely; a "Softwareentwickler" search happily returns "Technical Consultant".
- `TITLE_EXCLUDE_TERMS` -- hard opt-outs, checked before the positive terms. Data engineering / data science roles are excluded here; removing their search keyword alone doesn't work, because they also come back from the ML/AI and general-software queries. `TITLE_EXCLUDE_OVERRIDE_TERMS` rescues in-scope hybrids like "Data Engineer / Machine Learning Engineer".
- `DEDUPE_ACROSS_SOURCES` (default **on**) -- the same posting listed on several boards under different URLs is sent once, not four times.
- `MAX_AGE_DAYS` (7) and `MAX_JOBS_PER_SOURCE_PER_RUN` (60) -- narrow the window, or spread a big backlog over more runs.

## One-time setup

1. **Create a GitHub repository** (private is fine) and push all these files to it, preserving the folder structure (including the `.github/workflows/` folder).

2. **Add two repo secrets** (Settings -> Secrets and variables -> Actions -> New repository secret):
   - `TELEGRAM_BOT_TOKEN` -- your bot's token (the one from @BotFather, looks like `123456:AAE...`)
   - `TELEGRAM_CHAT_ID` -- your channel's numeric ID (e.g. `-1004301040327` for your "JobsToApply" channel)

3. **Make sure your bot is an admin of the Telegram channel** (you've already done this).

4. That's it. Trigger a run whenever you want from the repo's **Actions** tab -> "Germany Job Scraper" -> **Run workflow**.

## Adjusting things later

- **Keywords / cities**: edit the lists in `config.py`, commit, push. `KEYWORDS` is used for the German searches; `DACH_KEYWORDS` (Austria/Switzerland) and `INTERNATIONAL_KEYWORDS` (Netherlands) are smaller subsets, kept short so the run doesn't hit the workflow timeout.
- **Countries**: `INDEED_COUNTRIES`, `STEPSTONE_SEARCHES` and `XING_LOCATIONS` in `config.py`.
- **Automatic runs**: the workflow is manual-trigger only. To run it on a schedule, add a `schedule:` block with a `cron` line to `.github/workflows/job_scraper.yml` (times are UTC).
- **Freshness window**: change `MAX_AGE_DAYS` in `config.py`.
- **Permanent-only filter**: edit `TEMP_AGENCY_TERMS` in `config.py` to add more staffing-agency names you keep seeing slip through. The fixed-term ("befristet") exclusion is handled separately in `scrapers/common.py` and doesn't need editing.
- **Defense/military exclusion**: edit `DEFENSE_COMPANIES` in `config.py` to add employers you want excluded.
- **If a source stops returning results**: check the Actions run log first -- each source logs its own count and any error, so you can see exactly which one failed and why.

## Costs

Free. GitHub Actions' free tier includes 2,000 minutes/month for private repos (unlimited for public repos). A full run is ~215 searches across four sources and four countries and takes roughly 20-30 minutes, so budget accordingly on a private repo.
