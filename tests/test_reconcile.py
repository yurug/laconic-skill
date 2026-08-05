"""Periodic reconciliation detects lifecycle signals without inventing corrections."""

import datetime
import os

from helpers import ModelTestCase, TOOLS
import laconic_reconcile as R


class ReconcileTest(ModelTestCase):
    def setUp(self):
        super().setUp()
        self.prior = os.environ.get("LACONIC_HOME")
        os.environ["LACONIC_HOME"] = str(self.home)

    def tearDown(self):
        if self.prior is None:
            os.environ.pop("LACONIC_HOME", None)
        else:
            os.environ["LACONIC_HOME"] = self.prior
        super().tearDown()

    def test_finds_stale_concept_and_expired_capability(self):
        concepts = [{
            "id": "old", "state": "familiar", "last-updated": "2020-01-01",
            "observations": 2, "strong_evidence": [],
            "capabilities": [{"capability_id": "use-old", "valid_until": "2025-01-01",
                              "retracted": "", "contradicts": []}],
        }]
        result = R.findings(concepts, datetime.date(2026, 8, 4))
        self.assertEqual(result["stale"][0]["effective"], "exposed")
        self.assertEqual(result["expired"][0]["capability"], "old/use-old")

    def test_finds_each_explicit_contradiction_once(self):
        cap_a = {"capability_id": "a", "contradicts": ["b/b"], "retracted": ""}
        cap_b = {"capability_id": "b", "contradicts": ["a/a"], "retracted": ""}
        base = {"state": "verified", "last-updated": "2026-08-04",
                "observations": 2, "strong_evidence": []}
        result = R.findings([
            {**base, "id": "a", "capabilities": [cap_a]},
            {**base, "id": "b", "capabilities": [cap_b]},
        ], datetime.date(2026, 8, 4))
        self.assertEqual(len(result["contradictions"]), 1)

    def test_begin_is_due_once_and_complete_sets_interval(self):
        self.create("thing", "--kind", "world", domain="testing")
        self.assertGreater(R.begin(), 0)
        self.assertTrue((self.home / ".reconciliation-pending").exists())
        R.complete()
        self.assertFalse(R.is_due())
        self.assertEqual(R.begin(), 0)

    def test_clean_model_marks_period_complete_without_agent_pass(self):
        self.assertEqual(R.begin(), 0)
        self.assertTrue((self.home / ".reconciled-at").exists())

    def test_three_new_candidates_trigger_before_interval_but_not_twice(self):
        for i in range(3):
            self.create(f"theory-{i}", "--kind", "world", domain="testing")
        # Pretend the periodic interval was just completed before these findings appeared.
        (self.home / ".reconciled-at").write_text(
            datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n"
        )
        self.assertEqual(R.begin(), 3)
        R.complete()
        self.assertEqual(R.begin(), 0, "unchanged reviewed backlog retriggered")

    def test_changed_urgent_backlog_retriggers_after_review(self):
        for i in range(3):
            self.create(f"theory-{i}", "--kind", "world", domain="testing")
        R.begin()
        R.complete()
        self.create("theory-new", "--kind", "world", domain="testing")
        self.assertEqual(R.begin(), 4)

    def test_report_warns_that_decay_already_protects_retrieval(self):
        result = self.run_tool(TOOLS / "laconic_reconcile.py")
        self.assertEqual(result.code, 0, result.text)
        self.assertIn("Decay and expiry already affect retrieval", result.out)

    def test_report_names_candidate_kind_for_semantic_decision(self):
        self.create("theory", "--kind", "justification", domain="testing")
        result = self.run_tool(TOOLS / "laconic_reconcile.py")
        self.assertIn("undistilled [justification]: theory evidence #1", result.out)
