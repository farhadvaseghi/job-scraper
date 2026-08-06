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
# Freshness window
# ---------------------------------------------------------------------------
MAX_AGE_DAYS = 7

# ---------------------------------------------------------------------------
# Telegram (from environment / GitHub Actions secrets)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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

# Arbeitsagentur Jobsuche API (official, public)
ARBEITSAGENTUR_API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs"
ARBEITSAGENTUR_CLIENT_ID = "jobboerse-jobsuche"

# Indeed / StepStone search bases
INDEED_SEARCH_URL = "https://de.indeed.com/jobs"
STEPSTONE_SEARCH_URL = "https://www.stepstone.de/jobs/{slug}/in-deutschland"

# Xing search base (Playwright-driven, best-effort -- see scrapers/xing.py)
XING_SEARCH_URL = "https://www.xing.com/jobs/search"
