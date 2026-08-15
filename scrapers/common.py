"""Shared helpers for all scrapers."""
import logging
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Matches "befristet", "befristete", "befristeter", "befristetes", etc. as a
# standalone word. Deliberately does NOT match inside "unbefristet" -- there
# is no word boundary between the "n" of "un" and the "b" of "befristet"
# since both are word characters, so \b correctly refuses to match there.
_BEFRISTET_RE = re.compile(r"\bbefristet\w*", re.IGNORECASE)

# Word-boundary regex per defense-company term, built once at import time.
# \b boundaries stop short tokens like "renk" or "kmw" from matching inside
# an unrelated longer word.
_DEFENSE_RE = [
    re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
    for term in config.DEFENSE_COMPANIES
]

# config.SENIORITY_EXCLUDE stays substring-matched (German compounds need it:
# "leiter" must catch "Teamleiter"). Only the terms in
# config.SENIORITY_EXCLUDE_WORDS get word boundaries -- see the comments there.
_SENIORITY_WORD_RE = [
    re.compile(r"\b" + re.escape(term.strip()) + r"\b", re.IGNORECASE)
    for term in config.SENIORITY_EXCLUDE_WORDS
]

# Narrow false-positive guard: "Leiterplatte" (printed circuit board) starts
# with "leiter" (manager/head) but is a hardware term, and PCB roles are
# squarely in scope for an embedded/FPGA search. Checked before the seniority
# terms so a "Leiterplattenentwickler" posting is not dropped as management.
_SENIORITY_ALLOW_RE = re.compile(r"\bleiterplatt\w*", re.IGNORECASE)

# Word-boundary regex per automotive employer, same reasoning as the defense
# list: "audi" must not fire inside an unrelated longer word.
_AUTOMOTIVE_COMPANY_RE = [
    re.compile(r"\b" + re.escape(term.strip()) + r"\b", re.IGNORECASE)
    for term in config.AUTOMOTIVE_COMPANIES
]


# Punctuation/decoration that differs between boards for the same posting:
# "(m/w/d)", "(all genders)", extra whitespace, etc.
_GENDER_TAG_RE = re.compile(
    r"\((?:[mwdfxgn*/\s.:;+-]|all\s+genders?|divers|welcome)*\)", re.IGNORECASE
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def get_logger(name):
    return logging.getLogger(name)


def _slug(text):
    """Fold a string to a comparable slug: lowercase, umlauts expanded
    (ü -> ue, so "Zürich" and "Zuerich" agree), gender tags dropped, and
    everything else collapsed to single hyphens."""
    text = str(text if text is not None else "").strip().lower()
    text = (text.replace("ä", "ae").replace("ö", "oe")
                .replace("ü", "ue").replace("ß", "ss"))
    text = _GENDER_TAG_RE.sub(" ", text)
    return _NON_ALNUM_RE.sub("-", text).strip("-")


def to_text(value):
    """Coerce any scraper field to a clean string. Guards against pandas
    NaN (a float) and None, which otherwise blow up on .lower()/.strip()
    -- this is exactly what crashed the Indeed source before (jobspy returns
    a DataFrame whose empty cells are NaN floats, not empty strings)."""
    if value is None:
        return ""
    # pandas NaN is a float that is not equal to itself
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()


# Query-string parameters that are pure tracking noise -- they vary run to
# run (or by referrer) without changing which job the URL points to. We strip
# them before building the dedupe key so the same posting isn't re-sent just
# because its utm_* tags changed. Anything NOT listed here (e.g. Indeed's
# `jk=` job key, which IS the identity) is preserved.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {
    "layer", "ref", "referrer", "source", "campaign", "content", "term",
    "medium", "gh_src", "gh_jid", "trk", "trackingid", "recommended",
    "utm", "at_medium", "at_campaign", "wt_mc", "cid",
}


def normalize_url(url):
    """Normalize a job URL for stable deduplication: lowercase scheme/host,
    drop tracking query params, drop the fragment, and strip a trailing
    slash. Meaningful query params (like Indeed's ?jk=) are kept."""
    url = to_text(url)
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        kept = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not (k.lower() in _TRACKING_PARAM_NAMES
                    or k.lower().startswith(_TRACKING_PARAM_PREFIXES))
        ]
        query = urlencode(kept)
        path = parts.path.rstrip("/") or "/"
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), path, query, "")
        )
    except Exception:
        return url


def make_job(source, title, company, city, url, posted_iso_date=None, raw_age_text=""):
    """Normalized job record used across all scrapers.

    Every field goes through to_text() -- this is the single chokepoint that
    enforces invariant #2. `(title or "").strip()` was NOT enough: a pandas
    NaN is a float and is *truthy*, so `nan or ""` yields nan and .strip()
    raises 'float object has no attribute strip'."""
    return {
        "source": to_text(source),
        "title": to_text(title),
        "company": to_text(company),
        "city": to_text(city),
        "url": to_text(url),
        "posted_date": posted_iso_date,  # ISO date string 'YYYY-MM-DD' or None
        "raw_age_text": to_text(raw_age_text),
    }


def passes_seniority_filter(title):
    """Drop postings that look senior/lead/management based on title text."""
    title = to_text(title)
    if not title:
        return True
    lowered = _SENIORITY_ALLOW_RE.sub("", title.lower())
    if any(term in lowered for term in config.SENIORITY_EXCLUDE):
        return False
    return not any(rx.search(lowered) for rx in _SENIORITY_WORD_RE)


def passes_permanent_filter(text):
    """Drop postings that look like fixed-term contracts or temp-staffing
    agency placements, based on free text (title, company name, and/or any
    extra snippet a scraper has available). Safe against "unbefristet"
    (permanent) -- see the comment on _BEFRISTET_RE above."""
    if not text:
        return True
    lowered = text.lower()
    if any(term in lowered for term in config.TEMP_AGENCY_TERMS):
        return False
    if _BEFRISTET_RE.search(lowered):
        return False
    return True


def passes_company_filter(company_name):
    """Drop postings from employers in the defense/military industry
    exclusion list (config.DEFENSE_COMPANIES). Matched against the
    company/employer name only -- never against title or job description
    text -- so a civilian-sector posting that merely mentions a defense
    contractor (e.g. as a client) is never wrongly excluded."""
    if not company_name:
        return True
    lowered = company_name.lower()
    return not any(rx.search(lowered) for rx in _DEFENSE_RE)


def passes_relevance_filter(title):
    """Keep only titles that actually look like an engineering role.

    The boards match loosely -- a "Softwareentwickler" search returns things
    like "Technical Consultant" -- so without this the digest carries a lot of
    postings that were never relevant. Stem matching, because German compounds
    words together ("entwickl" covers Entwickler / Softwareentwicklung / ...).
    """
    if not config.REQUIRE_RELEVANT_TITLE:
        return True
    title = to_text(title)
    if not title:
        return False
    lowered = title.lower()
    # Explicit opt-outs win over the positive terms: a "Data Scientist"
    # posting matches nothing in RELEVANCE_TERMS any more, but a
    # "Data Engineer (Python)" would still match "python". An in-scope
    # override (e.g. "Data Engineer / Machine Learning Engineer") rescues it.
    if any(term in lowered for term in config.TITLE_EXCLUDE_TERMS):
        if not any(ok in lowered for ok in config.TITLE_EXCLUDE_OVERRIDE_TERMS):
            return False
    return any(term in lowered for term in config.RELEVANCE_TERMS)


_city_cache = {"key": None, "targets": frozenset(), "country_only": frozenset()}


def _city_targets():
    """Accepted city spellings (umlaut-folded) and bare-country tokens.

    Rebuilt whenever the underlying config lists change rather than frozen at
    import, so flipping config.ACTIVE_COUNTRIES actually takes effect --
    including from tests.
    """
    key = (tuple(config.CITIES), tuple(config.COUNTRY_ONLY_LOCATIONS))
    if _city_cache["key"] != key:
        slugs = {_slug(city) for city in config.CITIES}
        active = {_slug(city) for city in config.CITIES}
        for canonical, aliases in config.CITY_ALIASES.items():
            # only pull in aliases for cities that are actually active
            if _slug(canonical) not in active:
                continue
            for alias in aliases:
                slugs.add(_slug(alias))
        _city_cache.update(
            key=key,
            targets=frozenset(s for s in slugs if s),
            country_only=frozenset(
                _slug(c) for c in config.COUNTRY_ONLY_LOCATIONS if _slug(c)
            ),
        )
    return _city_cache["targets"], _city_cache["country_only"]


def _slug_has_token(haystack, needle):
    """Whether `needle` appears in `haystack` on slug-token boundaries.

    Plain substring matching is wrong here: "Bernau" and "Bernburg" are not
    Bern, and "Essendorf" is not Essen. Boards return the city with extra
    parts attached ("Berlin, BE, DE", "Frankfurt am Main, HE"), so we need
    containment, just not mid-token containment.
    """
    return (
        haystack == needle
        or haystack.startswith(needle + "-")
        or haystack.endswith("-" + needle)
        or ("-" + needle + "-") in haystack
    )


def passes_city_filter(city):
    """Keep postings in one of the target cities (plus remote / unknown).

    No-ops unless config.RESTRICT_TO_CITIES is on. The city list existed for a
    long time without anything reading it, so searches were nationwide and
    every result was kept regardless of where it was.
    """
    if not config.RESTRICT_TO_CITIES:
        return True
    city = to_text(city)
    if not city:
        return True  # unknown location -- don't throw it away
    lowered = city.lower()
    if any(term in lowered for term in config.REMOTE_TERMS):
        return True
    targets, country_only = _city_targets()
    city_slug = _slug(city)
    # A bare ACTIVE country ("DE", "Deutschland") names no city at all --
    # treat it like an unknown location rather than a mismatch.
    if city_slug in country_only:
        return True
    return any(_slug_has_token(city_slug, target) for target in targets)


def automotive_score(job):
    """How strongly a posting looks automotive. 0 = not, higher = more.

    Used only for RANKING (see rank_jobs) -- never to drop anything.
    """
    if not config.PRIORITIZE_AUTOMOTIVE:
        return 0

    score = 0
    title = to_text(job.get("title")).lower()
    if any(term in title for term in config.AUTOMOTIVE_TITLE_TERMS):
        score += config.AUTOMOTIVE_TITLE_SCORE

    company = to_text(job.get("company")).lower()
    if company and any(rx.search(company) for rx in _AUTOMOTIVE_COMPANY_RE):
        score += config.AUTOMOTIVE_COMPANY_SCORE

    return score


def rank_jobs(jobs):
    """Highest-priority first, stable within a score.

    Python's sort is stable, so postings with the same score keep the order
    the scraper collected them in -- ranking only lifts automotive roles above
    the rest, it does not otherwise reshuffle the digest.
    """
    if not config.PRIORITIZE_AUTOMOTIVE:
        return list(jobs)
    return sorted(jobs, key=automotive_score, reverse=True)


def dedupe_key(job):
    """Stable identifier for a job posting, used for the seen-jobs store.
    Uses the normalized URL so tracking-param variations don't defeat it."""
    return f"{job['source']}::{normalize_url(job['url'])}"


def content_key(job):
    """Source-INDEPENDENT identity for a posting: title + company + city.

    The same job is routinely listed on all four boards under four different
    URLs, so dedupe_key alone lets it through four times. City is included so
    two genuinely different openings with the same title at the same big
    employer aren't collapsed into one.
    """
    return "content::" + "|".join(
        _slug(job.get(field)) for field in ("title", "company", "city")
    )
