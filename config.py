"""
Central configuration for the Germany job scraper system.
Edit this file to change keywords, cities, or filters.

Secrets (Telegram bot token / chat id) come from environment variables,
which in production are injected by GitHub Actions from repo secrets.
See README.md for setup instructions.
"""
import os

# ---------------------------------------------------------------------------
# THE geography switch. Everything geographic derives from it: which cities
# are accepted, which Indeed domains are queried, which StepStone site is
# used and which Xing locations are searched.
#
# Currently Germany-only (owner's request). To widen again, add any of
# "Netherlands", "Austria", "Switzerland" -- the city lists, the StepStone
# .at entry and the Xing locations for all of them are still defined below
# and are verified working, so re-enabling is a one-line change.
#
# Arbeitsagentur is unaffected either way: it is the German federal job API
# and has no other country.
# ---------------------------------------------------------------------------
ACTIVE_COUNTRIES = ["Germany"]

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
    # NB: no "Data Scientist" / "Data Engineer" here -- data roles are out of
    # scope on purpose, see TITLE_EXCLUDE_TERMS below.
    "Computer Vision / ML / AI": [
        "Computer Vision Engineer",
        "Machine Learning Engineer",
        "Deep Learning Engineer",
        "KI-Ingenieur",
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

# Keywords used OUTSIDE the German-speaking market. The German compound terms
# ("Automatisierungsingenieur", "Softwareentwickler", ...) return essentially
# nothing on Indeed Netherlands, and every extra keyword is another slow
# request -- 32 keywords x 4 countries would risk the workflow timeout. Dutch
# tech postings are overwhelmingly written in English, so the English subset
# is what actually pays off there.
INTERNATIONAL_KEYWORDS = [
    "Embedded Software Engineer",
    "Firmware Engineer",
    "Robotics Software Engineer",
    "Computer Vision Engineer",
    "Machine Learning Engineer",
    "Sensor Fusion Engineer",
    "Test Automation Engineer",
    "FPGA Engineer",
    "Software Engineer",
    "Python Developer",
    "Automation Engineer",
]

# Keywords for the SECONDARY German-speaking searches (Austria, Switzerland).
# German terms belong here -- unlike in the Netherlands, they are the
# highest-yield queries in AT/CH -- but the full 32 would multiply the run
# time past the workflow timeout, so this is the high-value subset.
DACH_KEYWORDS = [
    "Softwareentwickler",
    "Embedded Software Engineer",
    "Embedded Softwareentwickler",
    "Firmware Engineer",
    "Robotics Engineer",
    "Computer Vision Engineer",
    "Machine Learning Engineer",
    "Automotive Software Engineer",
    "Test Automation Engineer",
    "Testautomatisierung",
    "FPGA Engineer",
    "Software Engineer",
    "Python Developer",
    "Automatisierungsingenieur",
]

# Which Indeed country domains to search. jobspy resolves these to the right
# Indeed subdomain (de / nl / at / ch) -- verified present in its Country enum.
INDEED_COUNTRIES = [
    c for c in ["Germany", "Netherlands", "Austria", "Switzerland"]
    if c in ACTIVE_COUNTRIES
]

# Xing is a DACH network -- no meaningful Netherlands coverage, so it only
# ever covers the German-speaking countries. None = nationwide default
# (Germany); the named locations are verified to work as a `location` query
# param (location=Wien returned 21 cards, all in Vienna).
_XING_LOCATIONS_BY_COUNTRY = [
    (None, "Germany"),
    ("Wien", "Austria"),
    ("Zürich", "Switzerland"),
]
XING_LOCATIONS = [
    location for location, country in _XING_LOCATIONS_BY_COUNTRY
    if country in ACTIVE_COUNTRIES
]

# ---------------------------------------------------------------------------
# Cities -- main big German cities. Used to tag/filter results; searches
# themselves are run nationwide ("Deutschland") per keyword for efficiency,
# since every listing already carries its own city in the response.
# ---------------------------------------------------------------------------
CITIES_BY_COUNTRY = {
    "Germany": [
        "Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main",
        "Stuttgart", "Düsseldorf", "Dortmund", "Essen", "Leipzig",
        "Nürnberg", "Erlangen",
    ],
    "Netherlands": [
        "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven",
        "Delft", "Groningen",
    ],
    "Austria": [
        "Wien", "Graz", "Linz", "Salzburg", "Innsbruck",
    ],
    "Switzerland": [
        "Zürich", "Genf", "Basel", "Bern", "Lausanne", "Zug", "Winterthur",
    ],
}

CITIES = [
    city
    for country, cities in CITIES_BY_COUNTRY.items()
    if country in ACTIVE_COUNTRIES
    for city in cities
]

# Alternate spellings for the same place. Job boards disagree on language --
# Indeed Switzerland says "Zurich", Xing says "Zürich"; Dutch boards say
# "Den Haag", English ones "The Hague". Keys are the canonical entry above
# (matched after umlaut folding: ü->ue), values are extra spellings to accept.
CITY_ALIASES = {
    "München": ["Munich", "Muenchen"],
    "Köln": ["Cologne", "Koeln"],
    "Nürnberg": ["Nuremberg", "Nuernberg"],
    "Frankfurt am Main": ["Frankfurt"],
    "Wien": ["Vienna"],
    "Zürich": ["Zurich", "Zuerich"],
    "Genf": ["Geneva", "Genève", "Geneve"],
    "Den Haag": ["The Hague", "'s-Gravenhage", "s-Gravenhage"],
}

# Whether the city list is actually ENFORCED. For a long time it was not: the
# list existed but nothing read it, so a nationwide search returned every
# village in Germany. Postings with no city at all, or that look remote, are
# always kept regardless.
RESTRICT_TO_CITIES = True

REMOTE_TERMS = [
    "remote", "home office", "homeoffice", "hybrid",
    "deutschlandweit", "thuiswerken", "telearbeit",
]

# Location values that name a country rather than a city. Indeed returns a
# bare "NL" / "DE" for nationwide postings; for an ACTIVE country those are
# effectively unknown-location and are kept rather than dropped. A country
# that is NOT active is not listed here, so a nationwide Dutch posting is
# correctly dropped while Germany-only is in force.
_COUNTRY_ONLY_BY_COUNTRY = {
    "Germany": ["de", "deutschland", "germany"],
    "Netherlands": ["nl", "nederland", "netherlands", "the netherlands"],
    "Austria": ["at", "oesterreich", "österreich", "austria"],
    "Switzerland": ["ch", "schweiz", "switzerland", "suisse"],
}
COUNTRY_ONLY_LOCATIONS = [
    token
    for country, tokens in _COUNTRY_ONLY_BY_COUNTRY.items()
    if country in ACTIVE_COUNTRIES
    for token in tokens
]

# ---------------------------------------------------------------------------
# Job type / seniority filter -- Junior / entry-level full-time.
# Applied client-side: postings whose title contains an EXCLUDE term are
# dropped. INCLUDE terms are informational only (most junior roles simply
# don't say "junior" in the title, so we don't require a match).
# ---------------------------------------------------------------------------
# Matched as SUBSTRINGS. That is deliberate and necessary for German, which
# glues words together: "leiter" has to match "Teamleiter" / "Projektleiter"
# / "Abteilungsleiter", none of which have a word boundary before "leiter".
SENIORITY_EXCLUDE = [
    "senior", "principal", "head of", "director", "manager",
    "leiter", "leitung", "erfahrung von mindestens", "expert",
]

# Matched as WHOLE WORDS instead. Only for terms where substring matching
# would produce false positives: plain "lead" hits "misleading". This used to
# be written as "lead " (trailing space) in the list above, which dodged
# "misleading" but then missed every title ENDING in the word -- "Team Lead"
# and "Tech Lead" both sailed through the filter.
SENIORITY_EXCLUDE_WORDS = [
    "lead",
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
    # Dutch equivalents -- without these the permanent-only filter is a no-op
    # on Netherlands results, where staffing agencies are very common.
    "uitzendbureau",
    "uitzendkracht",
    "detachering",
    "detacheringsbureau",
    "payrolling",
    "tijdelijk contract",
    "bepaalde tijd",
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
# Relevance gate
#
# The job boards match loosely: searching "Softwareentwickler" also returns
# "Technical Consultant", "Vertriebsmitarbeiter", and similar. A posting is
# kept only if its TITLE contains at least one of these stems, which is the
# single biggest reduction in noise per line of code.
#
# Stems, not whole words -- German glues words together, so "entwickl"
# catches Entwickler / Entwicklerin / Softwareentwicklung / Entwicklungs-.
# Set REQUIRE_RELEVANT_TITLE = False to accept whatever the boards return.
# ---------------------------------------------------------------------------
REQUIRE_RELEVANT_TITLE = True

# Titles to drop even when they pass RELEVANCE_TERMS. Data engineering and
# data science are deliberately out of scope, but they leak in through the
# ML/AI and general-software searches -- a "Machine Learning Engineer" query
# happily returns "Data Scientist" -- so removing the search keyword alone is
# not enough. Checked BEFORE the positive relevance terms.
#
# Matched as substrings on the lowercased title. "machine learning",
# "deep learning" and "computer vision" are deliberately NOT here: those stay
# in scope.
TITLE_EXCLUDE_TERMS = [
    "data scientist",
    "data engineer",
    "data engineering",
    "data science",
    "datenwissenschaft",
    "dateningenieur",
    "data analyst",
    "datenanalyst",
    "datenanalyse",
    "data analytics",
    "analytics engineer",
    "big data",
    "data warehouse",
    "data platform",
    "business intelligence",
    "bi developer",
    "etl developer",

    # --- vocational / non-graduate / not-full-time -----------------------
    # The brief is junior-but-graduate, full-time, permanent. These slipped
    # through because German trade titles contain the same stems as the
    # engineering ones: "Mechatroniker" (a skilled trade) contains
    # "mechatronik" (the field), and "Testfahrer" contains "test". Note the
    # positive stems stay -- "Mechatronik-Ingenieur" is still in scope,
    # because exclusions are checked before the positive terms.
    "ausbildung",
    "auszubildende",
    "azubi",
    "werkstudent",
    "praktikum",
    "praktikant",
    "mechatroniker",
    "mechaniker",
    "testfahrer",
    "fahrzeugtester",
    "kraftfahrer",
    "berufskraftfahrer",
    "monteur",
    "quereinstieg",
    "umschulung",
]

# ...unless the title ALSO names one of these. Postings are routinely
# advertised as "Data Engineer* / Machine Learning Engineer*" -- that is an ML
# role and should still come through, while a plain "Data Engineer" should
# not. Checked after TITLE_EXCLUDE_TERMS and it wins.
# Keep this list narrow: "ai" is deliberately absent, or every
# "Data Scientist - AI & Experimentation" would be rescued too.
TITLE_EXCLUDE_OVERRIDE_TERMS = [
    "machine learning",
    "deep learning",
    "computer vision",
    "ml engineer",
    "mlops",
    "robotic",
    "embedded",
    "firmware",
    "fpga",
]

RELEVANCE_TERMS = [
    # generic engineering / dev
    "software", "entwickl", "developer", "engineer", "ingenieur", "informatik",
    "programmier", "coder",
    # the specific areas from the resume
    "embedded", "firmware", "hardware", "robot", "autonom", "slam",
    "computer vision", "machine learning", "deep learning", "ki-", " ai ",
    "adas", "sensor", "dsp", "signal",
    "fpga", "rtl", "vhdl", "verilog", "asic", "digital design",
    "test", "qa", "quality", "validierung", "verifikation",
    "automation", "automatisierung", "plc", "sps", "steuerung", "mechatronik",
    # common languages/stacks that identify a dev role
    "python", "c++", "java", "matlab", "linux", "devops", "backend",
    "frontend", "full-stack", "fullstack",
]

# ---------------------------------------------------------------------------
# Automotive priority
#
# Jobs are RANKED before MAX_JOBS_PER_SOURCE_PER_RUN trims each source, so
# automotive roles survive the cut and appear first in the digest. This is not
# a filter -- nothing is dropped for being non-automotive; it only decides
# what goes first and what gets pushed to the next run. That matters because
# the cap is doing real work: a recent run trimmed Xing from 301 to 60 and
# Indeed from 270 to 60, keeping whatever happened to be collected first.
#
# Scoring: a title hit is worth more than an employer hit, because an
# "Embedded Software Engineer" at Bosch may have nothing to do with vehicles,
# while an "ADAS Engineer" anywhere certainly does.
# ---------------------------------------------------------------------------
PRIORITIZE_AUTOMOTIVE = True

AUTOMOTIVE_TITLE_SCORE = 3
AUTOMOTIVE_COMPANY_SCORE = 1

# Matched as substrings against the lowercased title.
AUTOMOTIVE_TITLE_TERMS = [
    "automotive", "automobil", "fahrzeug", "kfz", "vehicle",
    "adas", "autonomes fahren", "autonomous driving", "self-driving",
    "autosar", "iso 26262", "functional safety", "funktionale sicherheit",
    "powertrain", "antriebsstrang", "chassis", "fahrwerk",
    "e-mobility", "emobility", "elektromobilit", "ladeinfrastruktur",
    "battery management", "batteriemanagement", "bms",
    "infotainment", "cockpit", "telematik", "telematics",
    "can-bus", "can bus", "canbus", "flexray", "lin-bus",
    "hardware-in-the-loop", "hardware in the loop", "hil-",
    "driver assistance", "fahrerassistenz", "sensor fusion", "sensorfusion",
    "lidar", "radar",
]

# Matched as whole words against the lowercased employer name. Deliberately
# distinctive names only -- a generic token would mislabel unrelated firms.
# Note the defense filter runs first and independently, so a defense arm of
# any of these is still excluded.
AUTOMOTIVE_COMPANIES = [
    # OEMs
    "volkswagen", "audi", "porsche", "bmw", "mercedes-benz", "daimler",
    "opel", "ford", "skoda", "seat", "cupra", "stellantis", "tesla",
    "rivian", "lucid motors", "nio", "polestar", "volvo cars",
    # tier 1 / tier 2 suppliers
    "bosch", "zf friedrichshafen", "continental", "schaeffler", "mahle",
    "hella", "valeo", "brose", "vitesco", "eberspächer", "eberspaecher",
    "webasto", "dräxlmaier", "draexlmaier", "leoni", "elringklinger",
    "knorr-bremse", "magna", "denso", "aptiv", "forvia", "faurecia",
    "marelli", "hyundai mobis", "borgwarner", "thyssenkrupp automotive",
    # engineering service providers / test houses
    "bertrandt", "edag", "iav ", "fev ", "avl ", "ika ", "akka",
    "alten", "assystem", "invenio", "in-tech", "umlaut",
    # commercial vehicles / mobility tech
    "daimler truck", "traton", "scania", "iveco", "zenseact", "mobileye",
    "luminar", "innoviz", "valeo schalter",
]

# ---------------------------------------------------------------------------
# Cross-source duplicates
#
# The same posting is routinely listed on all four boards under four
# different URLs, so URL-based dedup alone sends it up to four times. When
# this is on, a second sighting of the same (title, company, city) is
# suppressed no matter which source it came from.
# ---------------------------------------------------------------------------
DEDUPE_ACROSS_SOURCES = True

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
# reused for the rest of the run. Verified 2026-08-11: ONLY `/pc/v6/jobs`
# answers; every v4 and v5 path returns "403 No match found" (an API-gateway
# routing error, not an auth problem). The dead paths are kept as a fallback
# chain purely in case the gateway routing changes back.
# NOTE: v6 uses different field names than v4 -- see the table in
# scrapers/arbeitsagentur.py. Reading v4 names against v6 yields 0 jobs
# silently, which is exactly the bug that fallback chain was hiding.
ARBEITSAGENTUR_API_URLS = [
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v5/jobs",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs",
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs",
]
# kept for backwards compatibility / anything referencing the single URL
ARBEITSAGENTUR_API_URL = ARBEITSAGENTUR_API_URLS[0]
ARBEITSAGENTUR_CLIENT_ID = "jobboerse-jobsuche"

# The API hard-caps `size` at 100 results per page, and a broad keyword can
# match several hundred. Fetch up to this many pages per keyword before
# moving on (3 x 100 = 300, comfortably above the busiest keyword observed).
ARBEITSAGENTUR_MAX_PAGES = 3

# Indeed / StepStone search bases
INDEED_SEARCH_URL = "https://de.indeed.com/jobs"
STEPSTONE_SEARCH_URL = "https://www.stepstone.de/jobs/{slug}/in-deutschland"

# StepStone runs a separate domain per country. Austria was verified to behave
# exactly like Germany (same `data-at` card markup, same `?ag=age_7` filter,
# 25 cards in 4s). There is no StepStone Netherlands or Switzerland, so those
# two countries are covered by Indeed only.
# Each entry: (label, country, search-URL template, base URL for relative links)
_STEPSTONE_SEARCHES_ALL = [
    ("de", "Germany", "https://www.stepstone.de/jobs/{slug}/in-deutschland",
     "https://www.stepstone.de"),
    ("at", "Austria", "https://www.stepstone.at/jobs/{slug}/in-oesterreich",
     "https://www.stepstone.at"),
]
STEPSTONE_SEARCHES = [
    (label, url, base)
    for label, country, url, base in _STEPSTONE_SEARCHES_ALL
    if country in ACTIVE_COUNTRIES
]

# Xing search base (Playwright-driven, best-effort -- see scrapers/xing.py)
XING_SEARCH_URL = "https://www.xing.com/jobs/search"
