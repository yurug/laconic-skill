"""Content-free proxy for whether routed domain knowledge surfaced in the answer."""

import json

from helpers import ModelTestCase, ROUTE_OBSERVE
from laconic_route_observe import session_key


class RouteObserveTest(ModelTestCase):
    def setUp(self):
        super().setUp()
        self.create("rocq-proof-obligations", domain="formal-verification")
        self.create("postgres-query-indexes", domain="databases")

    def pending(self, session="s1", domains=None):
        path = self.home / ".routing-pending" / f"{session_key(session)}.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "date": "2026-08-04", "session": session_key(session),
            "domains": domains if domains is not None else ["formal-verification"],
            "chars": 300, "routing_version": 2,
        }) + "\n", encoding="utf-8")
        return path

    def transcript(self, answer):
        path = self.home / "transcript.jsonl"
        path.write_text(
            json.dumps({"type": "user", "message": {"content": "secret prompt"}}) + "\n" +
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": answer}
            ]}}) + "\n", encoding="utf-8"
        )
        return path

    def test_resolves_matching_domain_without_storing_answer(self):
        self.pending()
        result = self.run_tool(
            ROUTE_OBSERVE, self.transcript("The Rocq obligation follows."), "s1",
            env=self.env(LACONIC_TELEMETRY="1"),
        )
        self.assertEqual(result.code, 0, result.text)
        raw = (self.home / "routing-telemetry.jsonl").read_text()
        self.assertNotIn("obligation follows", raw)
        self.assertEqual(json.loads(raw)["answer_domains"], ["formal-verification"])
        self.assertEqual(json.loads(raw)["missed_domains"], [])

    def test_records_no_match_and_consumes_pending(self):
        pending = self.pending()
        self.run_tool(
            ROUTE_OBSERVE, self.transcript("Done."), "s1",
            env=self.env(LACONIC_TELEMETRY="1"),
        )
        self.assertEqual(json.loads(
            (self.home / "routing-telemetry.jsonl").read_text()
        )["answer_domains"], [])
        self.assertFalse(pending.exists())

    def test_detects_strong_unselected_domain_as_possible_miss(self):
        self.pending(domains=[])
        self.run_tool(
            ROUTE_OBSERVE, self.transcript("Use the PostgreSQL query indexes."), "s1",
            env=self.env(LACONIC_TELEMETRY="1"),
        )
        row = json.loads((self.home / "routing-telemetry.jsonl").read_text())
        self.assertEqual(row["missed_domains"], ["databases"])

    def test_one_generic_concept_word_is_not_a_miss(self):
        self.pending(domains=[])
        self.run_tool(
            ROUTE_OBSERVE, self.transcript("The index is complete."), "s1",
            env=self.env(LACONIC_TELEMETRY="1"),
        )
        row = json.loads((self.home / "routing-telemetry.jsonl").read_text())
        self.assertEqual(row["missed_domains"], [])

    def test_single_domain_word_without_concept_support_is_not_a_miss(self):
        self.pending(domains=[])
        self.run_tool(
            ROUTE_OBSERVE, self.transcript("This concerns databases."), "s1",
            env=self.env(LACONIC_TELEMETRY="1"),
        )
        row = json.loads((self.home / "routing-telemetry.jsonl").read_text())
        self.assertEqual(row["missed_domains"], [])

    def test_requires_telemetry_consent(self):
        pending = self.pending()
        self.run_tool(ROUTE_OBSERVE, self.transcript("Rocq"), "s1", env=self.env())
        self.assertTrue(pending.exists())
        self.assertFalse((self.home / "routing-telemetry.jsonl").exists())
