"""
Pure-logic tests -- no network, no scraping.

Live scraping can't be exercised from CI or a sandbox (the sites block it),
so this covers the parts that HAVE broken in production: the filter regexes,
URL normalization, the seen-store, and Telegram delivery accounting.

Run with:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import dedupe
import telegram_notify
from scrapers.common import (
    content_key,
    dedupe_key,
    make_job,
    normalize_url,
    passes_city_filter,
    passes_company_filter,
    passes_permanent_filter,
    passes_relevance_filter,
    passes_seniority_filter,
    to_text,
)


class ToText(unittest.TestCase):
    def test_none_and_blank(self):
        self.assertEqual(to_text(None), "")
        self.assertEqual(to_text("  padded  "), "padded")

    def test_pandas_nan_float(self):
        """Invariant #2: jobspy hands back NaN floats for empty cells."""
        nan = float("nan")
        self.assertEqual(to_text(nan), "")

    def test_non_string_scalars(self):
        self.assertEqual(to_text(42), "42")
        self.assertEqual(to_text(3.5), "3.5")


class MakeJob(unittest.TestCase):
    def test_nan_fields_do_not_crash(self):
        """`(title or '').strip()` used to blow up here: NaN is truthy."""
        nan = float("nan")
        job = make_job("Indeed", nan, nan, nan, "https://x.test/j", None, nan)
        self.assertEqual(job["title"], "")
        self.assertEqual(job["company"], "")
        self.assertEqual(job["city"], "")
        self.assertEqual(job["raw_age_text"], "")

    def test_normal_fields(self):
        job = make_job("Xing", " Dev ", " ACME ", " Berlin ", " https://x.test/j ")
        self.assertEqual(job["title"], "Dev")
        self.assertEqual(job["company"], "ACME")
        self.assertEqual(job["city"], "Berlin")
        self.assertEqual(job["url"], "https://x.test/j")


class NormalizeUrl(unittest.TestCase):
    def test_strips_utm_but_keeps_identity_params(self):
        """Invariant #4."""
        a = normalize_url("https://X.test/job?jk=abc&utm_source=news&utm_campaign=q3")
        b = normalize_url("https://x.test/job?jk=abc&utm_source=other")
        self.assertEqual(a, b)
        self.assertIn("jk=abc", a)

    def test_drops_fragment_and_trailing_slash_and_lowercases_host(self):
        self.assertEqual(
            normalize_url("https://WWW.Xing.com/jobs/berlin-dev-1/#apply"),
            "https://www.xing.com/jobs/berlin-dev-1",
        )

    def test_blank_and_garbage(self):
        self.assertEqual(normalize_url(None), "")
        self.assertEqual(normalize_url(float("nan")), "")

    def test_dedupe_key_is_source_scoped(self):
        j1 = make_job("Indeed", "Dev", "A", "Berlin", "https://x.test/j?utm_source=a")
        j2 = make_job("Indeed", "Dev", "A", "Berlin", "https://x.test/j?utm_source=b")
        j3 = make_job("Xing", "Dev", "A", "Berlin", "https://x.test/j")
        self.assertEqual(dedupe_key(j1), dedupe_key(j2))
        self.assertNotEqual(dedupe_key(j1), dedupe_key(j3))


class PermanentFilter(unittest.TestCase):
    def test_unbefristet_survives(self):
        """Invariant #3 -- the one that would silently drop EVERY good job."""
        self.assertTrue(passes_permanent_filter("Entwickler unbefristet Vollzeit"))
        self.assertTrue(passes_permanent_filter("UNBEFRISTETE Festanstellung"))

    def test_befristet_forms_are_dropped(self):
        for text in (
            "Entwickler befristet",
            "befristete Elternzeitvertretung",
            "Stelle ist befristeter Natur",
            "befristetes Arbeitsverhältnis",
        ):
            self.assertFalse(passes_permanent_filter(text), text)

    def test_temp_agency_terms(self):
        self.assertFalse(passes_permanent_filter("Dev bei XY Zeitarbeit GmbH"))
        self.assertFalse(passes_permanent_filter("Randstad Deutschland"))
        self.assertFalse(passes_permanent_filter("DEKRA Arbeit GmbH"))

    def test_empty_passes(self):
        self.assertTrue(passes_permanent_filter(""))


class CompanyFilter(unittest.TestCase):
    def test_defense_employers_dropped(self):
        for name in ("Rheinmetall Electronics GmbH", "HENSOLDT Sensors GmbH", "KNDS"):
            self.assertFalse(passes_company_filter(name), name)

    def test_civilian_employer_kept(self):
        for name in ("Bosch", "Siemens AG", "Airbus Operations GmbH", "Renkforce"):
            self.assertTrue(passes_company_filter(name), name)

    def test_word_boundaries(self):
        """Short tokens like 'renk'/'kmw' must not match inside longer words."""
        self.assertTrue(passes_company_filter("Renkenberger Software GmbH"))

    def test_empty_passes(self):
        self.assertTrue(passes_company_filter(""))


class SeniorityFilter(unittest.TestCase):
    def test_junior_and_plain_titles_kept(self):
        for t in ("Junior Software Engineer", "Softwareentwickler (m/w/d)",
                  "Embedded Systems Engineer"):
            self.assertTrue(passes_seniority_filter(t), t)

    def test_senior_titles_dropped(self):
        for t in ("Senior Developer", "Lead Engineer", "Head of Engineering",
                  "Teamleiter Software", "Principal Engineer"):
            self.assertFalse(passes_seniority_filter(t), t)

    def test_trailing_lead_is_dropped(self):
        """'lead ' with a trailing space missed any title ENDING in it."""
        self.assertFalse(passes_seniority_filter("Tech Lead"))
        self.assertFalse(passes_seniority_filter("Team Lead"))

    def test_lead_inside_a_word_is_not_a_match(self):
        self.assertTrue(passes_seniority_filter("Misleading Job Title"))

    def test_leiterplatte_is_not_management(self):
        """'Leiterplatte' = PCB; it starts with 'leiter' but is in scope."""
        self.assertTrue(passes_seniority_filter("Entwickler Leiterplattendesign"))

    def test_nan_title(self):
        self.assertTrue(passes_seniority_filter(float("nan")))


class RelevanceFilter(unittest.TestCase):
    def test_engineering_titles_kept(self):
        for t in ("Softwareentwickler (m/w/d)", "Embedded Software Engineer",
                  "FPGA Entwickler", "Test Automation Engineer",
                  "Automatisierungsingenieur"):
            self.assertTrue(passes_relevance_filter(t), t)

    def test_off_topic_titles_dropped(self):
        for t in ("Technical Consultant", "Vertriebsmitarbeiter",
                  "Pflegefachkraft", "Bürokauffrau", "LKW Fahrer"):
            self.assertFalse(passes_relevance_filter(t), t)

    def test_can_be_switched_off(self):
        original = config.REQUIRE_RELEVANT_TITLE
        config.REQUIRE_RELEVANT_TITLE = False
        try:
            self.assertTrue(passes_relevance_filter("Vertriebsmitarbeiter"))
        finally:
            config.REQUIRE_RELEVANT_TITLE = original

    def test_data_roles_are_excluded(self):
        """Out of scope by request -- and they leak in via the ML/AI and
        general-software searches, not just their own keyword."""
        for t in ("Data Scientist", "Senior Data Scientist (m/w/d)",
                  "Data Engineer", "Data Engineer (Python)",
                  "Analytics Engineer", "Big Data Engineer",
                  "Data Analyst", "Business Intelligence Developer",
                  "Werkstudent Data Science"):
            self.assertFalse(passes_relevance_filter(t), t)

    def test_adjacent_ml_roles_are_kept(self):
        """The exclusion must not swallow the ML/CV roles that are in scope."""
        for t in ("Machine Learning Engineer", "Deep Learning Engineer",
                  "Computer Vision Engineer", "MLOps Engineer",
                  "AI Engineer (m/w/d)", "Sensor Fusion Engineer"):
            self.assertTrue(passes_relevance_filter(t), t)

    def test_data_scientist_is_no_longer_a_search_keyword(self):
        for kw_list in (config.KEYWORDS, config.DACH_KEYWORDS,
                        config.INTERNATIONAL_KEYWORDS):
            self.assertNotIn("Data Scientist", kw_list)


class CityFilter(unittest.TestCase):
    def setUp(self):
        self._orig = config.RESTRICT_TO_CITIES
        config.RESTRICT_TO_CITIES = True

    def tearDown(self):
        config.RESTRICT_TO_CITIES = self._orig

    def test_noop_when_disabled(self):
        config.RESTRICT_TO_CITIES = False
        self.assertTrue(passes_city_filter("Kleinkleckersdorf"))

    def test_german_targets(self):
        for c in ("Berlin", "Berlin, BE, DE", "München, Bayern",
                  "Frankfurt am Main, HE, DE", "Frankfurt"):
            self.assertTrue(passes_city_filter(c), c)

    def test_remote_and_unknown_are_kept(self):
        self.assertTrue(passes_city_filter("Remote"))
        self.assertTrue(passes_city_filter("Hybrid - Deutschlandweit"))
        self.assertTrue(passes_city_filter(""), "unknown city must be kept")

    def test_non_target_cities_dropped(self):
        for c in ("Kirchdorf an der Iller", "Ulm, Donau", "Bargteheide"):
            self.assertFalse(passes_city_filter(c), c)

    def test_international_targets(self):
        for c in ("Amsterdam, Noord-Holland", "Rotterdam", "Eindhoven",
                  "Wien", "Graz", "Zürich, ZH", "Basel", "Zug", "Lausanne"):
            self.assertTrue(passes_city_filter(c), c)

    def test_alias_spellings(self):
        """Boards disagree on language: Zurich/Zürich, Vienna/Wien, ..."""
        for c in ("Zurich", "Vienna", "Munich, BY", "Cologne", "Geneva",
                  "Genève", "The Hague", "Den Haag", "Nuremberg"):
            self.assertTrue(passes_city_filter(c), c)

    def test_substring_lookalikes_are_not_matched(self):
        """'Bernburg' is not Bern; 'Essendorf' is not Essen."""
        for c in ("Bernburg", "Essendorf", "Grazerfeld-Nowhere"):
            self.assertFalse(passes_city_filter(c), c)

    def test_token_inside_a_longer_place_still_counts(self):
        """'Bernau bei Berlin' genuinely is in the Berlin area."""
        self.assertTrue(passes_city_filter("Bernau bei Berlin"))

    def test_country_only_location_is_treated_as_unknown(self):
        """Indeed returns a bare 'NL' for nationwide postings."""
        for c in ("NL", "DE", "Deutschland", "Nederland", "Switzerland"):
            self.assertTrue(passes_city_filter(c), c)


class DutchTempAgencyTerms(unittest.TestCase):
    def test_dutch_staffing_terms_are_dropped(self):
        for text in ("Software Engineer via uitzendbureau",
                     "Detachering bij een mooie klant",
                     "Contract voor bepaalde tijd"):
            self.assertFalse(passes_permanent_filter(text), text)

    def test_normal_dutch_posting_survives(self):
        self.assertTrue(passes_permanent_filter(
            "Embedded Software Engineer, vast contract, Eindhoven"))


class ContentKey(unittest.TestCase):
    def test_same_posting_on_two_boards_collapses(self):
        a = make_job("Indeed", "Softwareentwickler (m/w/d)", "ACME GmbH",
                     "Berlin", "https://indeed.test/1")
        b = make_job("Xing", "Softwareentwickler (w/m/d)", "ACME GmbH",
                     "Berlin", "https://xing.test/2")
        self.assertEqual(content_key(a), content_key(b))

    def test_different_city_stays_distinct(self):
        a = make_job("Indeed", "Softwareentwickler", "ACME GmbH", "Berlin",
                     "https://indeed.test/1")
        b = make_job("Indeed", "Softwareentwickler", "ACME GmbH", "Hamburg",
                     "https://indeed.test/2")
        self.assertNotEqual(content_key(a), content_key(b))

    def test_cross_source_duplicate_is_filtered(self):
        a = make_job("Indeed", "FPGA Engineer (m/w/d)", "ACME GmbH", "Berlin",
                     "https://indeed.test/1")
        b = make_job("StepStone", "FPGA Engineer (all genders)", "ACME GmbH",
                     "Berlin", "https://stepstone.test/2")
        self.assertEqual(len(dedupe.filter_new([a, b], {})), 1)

    def test_marking_one_source_blocks_the_other(self):
        a = make_job("Indeed", "FPGA Engineer", "ACME GmbH", "Berlin",
                     "https://indeed.test/1")
        b = make_job("Xing", "FPGA Engineer", "ACME GmbH", "Berlin",
                     "https://xing.test/2")
        seen = dedupe.mark_seen({}, [a])
        self.assertEqual(dedupe.filter_new([b], seen), [])


class Prune(unittest.TestCase):
    def _iso(self, days_ago):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    def test_old_entries_dropped_recent_kept(self):
        seen = {"a": self._iso(1), "b": self._iso(config.SEEN_RETENTION_DAYS + 5)}
        kept = dedupe.prune(seen)
        self.assertIn("a", kept)
        self.assertNotIn("b", kept)

    def test_naive_timestamp_does_not_raise(self):
        """A tz-less timestamp used to raise TypeError and kill the run."""
        from datetime import datetime, timedelta
        naive = (datetime.utcnow() - timedelta(days=1)).isoformat()
        kept = dedupe.prune({"a": naive})
        self.assertIn("a", kept)

    def test_unparseable_timestamp_is_kept_not_dropped(self):
        """Dropping it would forget the job and re-post it."""
        kept = dedupe.prune({"a": "not-a-date"})
        self.assertIn("a", kept)


class FilterNew(unittest.TestCase):
    def test_does_not_mutate_the_store(self):
        """Invariant #1: filter_new must never mark anything seen."""
        seen = {}
        jobs = [make_job("Indeed", "Dev", "A", "Berlin", "https://x.test/1")]
        dedupe.filter_new(jobs, seen)
        self.assertEqual(seen, {}, "filter_new mutated the seen store")

    def test_filters_already_seen_and_intra_batch_duplicates(self):
        j1 = make_job("Indeed", "Dev", "A", "Berlin", "https://x.test/1")
        j2 = make_job("Indeed", "Dev", "A", "Berlin", "https://x.test/1?utm_source=z")
        j3 = make_job("Indeed", "Dev2", "A", "Berlin", "https://x.test/2")
        new = dedupe.filter_new([j1, j2, j3], {})
        self.assertEqual(len(new), 2)

        seen = dedupe.mark_seen({}, [j1])
        self.assertEqual(len(dedupe.filter_new([j1, j3], seen)), 1)


class TelegramFormatting(unittest.TestCase):
    def test_ampersand_in_url_is_escaped(self):
        """An unescaped '&' makes Telegram answer 400 and kills the source."""
        job = make_job("Indeed", "Dev", "ACME", "Berlin",
                       "https://de.indeed.com/viewjob?jk=abc&from=serp&vjk=xyz")
        msgs = telegram_notify.format_source_messages("Indeed", [job])
        body = "\n".join(msgs)
        self.assertIn("&amp;from=serp", body)
        self.assertNotIn("&from=serp", body)

    def test_html_in_title_is_escaped(self):
        job = make_job("Xing", "Dev <script> & co", "A&B", "Berlin",
                       "https://x.test/j")
        body = "\n".join(telegram_notify.format_source_messages("Xing", [job]))
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>", body)

    def test_quote_in_url_cannot_break_the_attribute(self):
        job = make_job("Xing", "Dev", "A", "Berlin", 'https://x.test/j?q="evil"')
        body = "\n".join(telegram_notify.format_source_messages("Xing", [job]))
        self.assertNotIn('"evil"', body)
        self.assertIn("&quot;", body)

    def test_job_without_url_still_renders(self):
        job = make_job("Xing", "Dev", "A", "Berlin", "")
        body = "\n".join(telegram_notify.format_source_messages("Xing", [job]))
        self.assertIn("Dev", body)
        self.assertNotIn("<a href", body)

    def test_messages_stay_under_the_limit(self):
        jobs = [
            make_job("Indeed", f"Engineer number {i} " + "x" * 60,
                     f"Company {i}", "Berlin", f"https://x.test/{i}?a=1&b=2")
            for i in range(300)
        ]
        msgs = telegram_notify.format_source_messages("Indeed", jobs)
        self.assertGreater(len(msgs), 1)
        for m in msgs:
            self.assertLessEqual(len(m), telegram_notify.MAX_MESSAGE_LEN)

    def test_absurdly_long_title_is_clipped(self):
        job = make_job("Indeed", "T" * 50000, "C" * 5000, "Berlin", "https://x.test/j")
        for m in telegram_notify.format_source_messages("Indeed", [job]):
            self.assertLessEqual(len(m), telegram_notify.MAX_MESSAGE_LEN)

    def test_a_jobs_two_lines_are_never_split(self):
        jobs = [make_job("Indeed", f"Job {i}", f"Company {i}", "Berlin",
                         f"https://x.test/{i}") for i in range(400)]
        for m in telegram_notify.format_source_messages("Indeed", jobs):
            lines = m.split("\n")
            # every "  Company - City" line must follow a bullet line
            for idx, line in enumerate(lines):
                if line.startswith("  Company"):
                    self.assertTrue(lines[idx - 1].startswith("•"),
                                    "meta line orphaned from its title")


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class TelegramDelivery(unittest.TestCase):
    def setUp(self):
        self._token = config.TELEGRAM_BOT_TOKEN
        self._chat = config.TELEGRAM_CHAT_ID
        config.TELEGRAM_BOT_TOKEN = "test-token"
        config.TELEGRAM_CHAT_ID = "-100123"
        self._delay = config.TELEGRAM_SEND_DELAY_SECONDS
        config.TELEGRAM_SEND_DELAY_SECONDS = 0

    def tearDown(self):
        config.TELEGRAM_BOT_TOKEN = self._token
        config.TELEGRAM_CHAT_ID = self._chat
        config.TELEGRAM_SEND_DELAY_SECONDS = self._delay

    def _jobs(self, source, n=2):
        return [make_job(source, f"Dev {i}", "ACME", "Berlin",
                         f"https://x.test/{source}/{i}") for i in range(n)]

    def test_429_then_200_is_retried_and_counts_as_delivered(self):
        responses = [
            _Resp(429, {"parameters": {"retry_after": 0}}),
            _Resp(200),
        ]
        with mock.patch.object(telegram_notify, "requests") as rq, \
                mock.patch.object(telegram_notify.time, "sleep"):
            rq.post.side_effect = responses
            ok, delivered = telegram_notify.send_digest({"Indeed": self._jobs("Indeed")})
        self.assertTrue(ok)
        self.assertIn("Indeed", delivered)
        self.assertEqual(rq.post.call_count, 2)

    def test_hard_failure_keeps_source_out_of_delivered(self):
        """Invariant #1 -- the 513-lost-jobs bug. A failed source must NOT be
        marked delivered, or main.py records its jobs as seen forever."""
        with mock.patch.object(telegram_notify, "requests") as rq, \
                mock.patch.object(telegram_notify.time, "sleep"):
            rq.post.return_value = _Resp(400, text="Bad Request: can't parse entities")
            ok, delivered = telegram_notify.send_digest({"Indeed": self._jobs("Indeed")})
        self.assertFalse(ok)
        self.assertNotIn("Indeed", delivered)

    def test_one_source_failing_does_not_sink_the_others(self):
        def post(url, **kwargs):
            text = kwargs["json"]["text"]
            return _Resp(400, text="nope") if "Xing" in text else _Resp(200)

        with mock.patch.object(telegram_notify, "requests") as rq, \
                mock.patch.object(telegram_notify.time, "sleep"):
            rq.post.side_effect = post
            ok, delivered = telegram_notify.send_digest({
                "Indeed": self._jobs("Indeed"),
                "Xing": self._jobs("Xing"),
            })
        self.assertFalse(ok)
        self.assertIn("Indeed", delivered)
        self.assertNotIn("Xing", delivered)

    def test_5xx_is_retried(self):
        with mock.patch.object(telegram_notify, "requests") as rq, \
                mock.patch.object(telegram_notify.time, "sleep"):
            rq.post.side_effect = [_Resp(502), _Resp(200)]
            ok, delivered = telegram_notify.send_digest({"Indeed": self._jobs("Indeed", 1)})
        self.assertTrue(ok)
        self.assertIn("Indeed", delivered)

    def test_exhausting_retries_gives_up_and_reports_failure(self):
        with mock.patch.object(telegram_notify, "requests") as rq, \
                mock.patch.object(telegram_notify.time, "sleep"):
            rq.post.return_value = _Resp(429, {"parameters": {"retry_after": 0}})
            ok, delivered = telegram_notify.send_digest({"Indeed": self._jobs("Indeed", 1)})
        self.assertFalse(ok)
        self.assertEqual(delivered, set())
        self.assertEqual(rq.post.call_count, config.TELEGRAM_MAX_RETRIES)

    def test_missing_credentials_reports_nothing_delivered(self):
        config.TELEGRAM_BOT_TOKEN = ""
        ok, delivered = telegram_notify.send_digest({"Indeed": self._jobs("Indeed")})
        self.assertFalse(ok)
        self.assertEqual(delivered, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
