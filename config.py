"""
Central configuration for the Germany job scraper system.
Edit this file to change keywords, cities, or filters.

Secrets (Telegram bot token / chat id) come from environment variables,
which in production are injected by GitHub Actions from repo secrets.
See README.md for setup instructions.
"""
import os

# ---------------------------------------------------------------------------
# Keywords, grouped by role area. German-first since these are German job
# boards -- German terms surface far more results than English ones.
# ---------------------------------------------------------------------------
KEYWORD_GROUPS = {
    "Embedded / Hardware": [
        "Embedded Software Engineer",
        "Embedded Systems Engineer",
        "Firmware Engineer",
        "Embedded Softwareentwickler",
    ],
    "Robotics / Autonomous Systems": [
        "Robotics Engineer",
        "Robotics Software Engineer",
        "Autonomous Systems Engineer",
        "SLAM Engineer",
        "Robotik-Ingenieur",
        "Autonomes Fahren",
    ],
    "Computer Vision / ML / AI": [
        "Computer Vision Engineer",
        "Machine Learning Engineer",
        "Deep Learning Engineer",
        "KI-Ingenieur",
        "Data Scientist",
    ],
    "ADAS / Automotive": [
        "ADAS Engineer",
        "Automotive Software Engineer",
        "Sensor Fusion Engineer",
        "DSP Engineer",
    ],
    "Test Automation / QA": [
        "Test Automation Engineer",
        "Software Test Engineer",
        "QA Engineer",
        "Testautomatisierung",
    ],
    "FPGA / Digital Design": [
        "FPGA Engineer",
        "FPGA-Ingenieur",
        "RTL Design Engineer",
        "Digital Design Engineer",
    ],
    "General Software": [
        "Python Developer",
        "Software Engineer",
        "Full-Stack Developer",
        "Softwareentwickler",
    ],
    "Automation / Process Control": [
        "Automation Engineer",
        "Process Control Engineer",
        "PLC Engineer",
        "Automatisierungsingenieur",
    ],
}

KEYWORDS = [kw for group in KEYWORD_GROUPS.values() for kw in group]

# ---------------------------------------------------------------------------
# Cities -- main big German cities. Used to tag/filter results; searches
# themselves are run nationwide ("Deutschland") per keyword for efficiency,
# since every listing already carries its own city in the response.
# ---------------------------------------------------------------------------
CITIES = [
    "Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main", "Stuttgart",
    "Düsseldorf", "Dortmund", "Essen", "Leipzig", "Nürnberg", "Erlangen",
]

# ---------------------------------------------------------------------------
# Job type / seniority filter -- Junior / entry-level full-time.
# Applied client-side: postings whose title contains an EXCLUDE term are
# dropped. INCLUDE terms are informational only (most junior roles simply
# don't say "junior" in the title, so we don't require a match).
# ---------------------------------------------------------------------------
SENIORITY_EXCLUDE = [
    "senior", "lead ", "principal", "head of", "director", "manager",
    "leiter", "leitung", "erfahrung von mindestens", "expert",
]

# ---------------------------------------------------------------------------
# Permanent-only filter -- exclude fixed-term contracts and temp-staffing
# agency postings. "unbefristet" (permanent) is never matched by mistake --
# see passes_permanent_filter() in scrapers/common.py for why.
# Add more staffing-agency brand names here if you notice them slipping
# through (e.g. specific agencies you keep seeing).
# ---------------------------------------------------------------------------
TEMP_AGENCY_TERMS = [
    # generic German staffing terms -- these appear in the company name of most
    # temp agencies (e.g. "XY Zeitarbeit GmbH", "ABC Personaldienstleistungen")
    "zeitarbeit",
    "leiharbeit",
    "arbeitnehmerüberlassung",
    "personaldienstleistung",
    "personaldienstleister",
    "temporärarbeit",
    "temporary employment",
    "temp agency",
    "staffing agency",
    # distinctive staffing-agency brand names (safe as substrings). Since the
    # server-side zeitarbeit filter was removed, these catch the big agencies
    # by name. Add any others you keep seeing in results.
    "randstad",
    "adecco",
    "manpower",
    "tempton",
    "orizon",
    "trenkwalder",
    "piening",
    "hofmann personal",
    "dekra arbeit",
    "argo personal",
    "unique personal",
    "i.k. hofmann",
]

# ---------------------------------------------------------------------------
# Defense/military industry exclusion -- drop postings from employers whose
# primary business is defense/military equipment (weapons systems, military
# electronics, armored vehicles, etc.). Matched against the company/employer
# name field only (not the full job text), so a posting that merely mentions
# a defense contractor as a client isn't wrongly excluded. Deliberately
# excludes conglomerates whose main business is civilian (e.g. plain
# "Airbus" or "Rohde & Schwarz") -- only their defense-specific entities are
# listed, to avoid dropping legitimate civilian roles there.
# Add more names here if you notice a defense employer slipping through.
# ---------------------------------------------------------------------------
DEFENSE_COMPANIES = [
    "hensoldt",
    "rheinmetall",
    "diehl defence",
    "diehl defense",
    "krauss-maffei wegmann",
    "kmw",
    "knds",
    "thyssenkrupp marine systems",
    "tkms",
    "airbus defence and space",
    "airbus defence & space",
    "mbda",
    "renk",
    "heckler & koch",
    "heckler und koch",
    "german naval yards",
    "ffg flensburger fahrzeugbau",
    "atlas elektronik",
    "german propulsion systems",
    "oerlikon",
    "wehrtechnik",
    "rüstungsindustrie",
    "defence systems",
    "defense systems",
    "military systems",
]

# ---------------------------------------------------------------------------
# Freshness window
# ---------------------------------------------------------------------------
MAX_AGE_DAYS = 7

# How long a posting stays remembered in the dedup store (state/seen_jobs.json)
# before it's pruned. Must be comfortably LONGER than how long a real posting
# stays live, otherwise a still-open job gets forgotten and re-sent. 60 days
# covers virtually all postings while keeping the file from growing forever.
SEEN_RETENTION_DAYS = 60

# ---------------------------------------------------------------------------
# Telegram (from environment / GitHub Actions secrets)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Telegram rate-limits bots to roughly 20 messages/minute per channel. A large
# run can produce dozens of messages, so pace them out (4s ~= 15/min) and retry
# when Telegram explicitly asks us to wait (HTTP 429 retry_after).
TELEGRAM_SEND_DELAY_SECONDS = 4.0
TELEGRAM_MAX_RETRIES = 6

# Safety cap on how many jobs to send per source in a single run. The first run
# after a fix can surface hundreds of postings at once; sending them all would
# flood the channel and hit rate limits. Anything over the cap is simply left
# unseen and picked up on the next run. Set to 0 to disable the cap.
MAX_JOBS_PER_SOURCE_PER_RUN = 60

# ---------------------------------------------------------------------------
# HTTP behavior
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 2.0  # politeness delay between requests to one host
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Storage paths (relative to repo root)
# ---------------------------------------------------------------------------
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
SEEN_JOBS_FILE = os.path.join(STATE_DIR, "seen_jobs.json")

# Arbeitsagentur Jobsuche API (official, public).
# Tried in order until one responds 200 -- the endpoint that works is then
# reused for the rest of the run. `/pc/v4/app/jobs` started returning
# "403 No match found" (an API-gateway routing error, not an auth problem),
# so the currently-documented `/pc/v6/jobs` is tried first.
ARBEITSAGENTUR_API_URLS = [
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v5/jobs",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs",
]
# kept for backwards compatibility / anything referencing the single URL
ARBEITSAGENTUR_API_URL = ARBEITSAGENTUR_API_URLS[0]
ARBEITSAGENTUR_CLIENT_ID = "jobboerse-jobsuche"

# Indeed / StepStone search bases
INDEED_SEARCH_URL = "https://de.indeed.com/jobs"
STEPSTONE_SEARCH_URL = "https://www.stepstone.de/jobs/{slug}/in-deutschland"

# Xing search base (Playwright-driven, best-effort -- see scrapers/xing.py)
XING_SEARCH_URL = "https://www.xing.com/jobs/search"
