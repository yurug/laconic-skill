"""Accepted historical proposals apply only after complete, isolated preflight."""

import json

from helpers import APPLY_REVIEW, ModelTestCase
from laconic_review import proposal_id


class TestApplyReview(ModelTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.home.parent / "project"
        self.project.mkdir()
        self.source = "a" * 64
        self.bundle = self.home.parent / "bundle.json"
        self.proposals = self.home.parent / "proposals.json"
        self.decisions = self.home.parent / "decisions.json"
        self.bundle.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-bootstrap-review",
            "review_id": "r1", "project": str(self.project),
            "turns": [{"source_ref": self.source,
                       "timestamp": "2026-07-01T10:00:00Z",
                       "text": "Preserved FIFO while changing the scheduler."}],
        }), encoding="utf-8")

    def proposal(self, concept="fifo-scheduler"):
        return {
            "concept_id": concept, "domain": "distributed-systems",
            "state": "exposed", "basis": "direct", "kind": "modification",
            "evidence": "Modified the scheduler while preserving FIFO ordering",
            "source_refs": [self.source],
            "capability": {"claim": "Can preserve FIFO while modifying the scheduler",
                           "scope": "project"},
        }

    def write(self, proposals, decisions=None):
        self.proposals.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-bootstrap-proposals",
            "review_id": "r1", "proposals": proposals,
        }), encoding="utf-8")
        if decisions is None:
            decisions = [{"proposal_id": proposal_id(item), "decision": "accept"}
                         for item in proposals]
        self.decisions.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-bootstrap-decisions",
            "review_id": "r1", "decisions": decisions,
        }), encoding="utf-8")

    def apply(self, confirm="r1"):
        return self.run_tool(
            APPLY_REVIEW, "--bundle", self.bundle, "--proposals", self.proposals,
            "--decisions", self.decisions, "--confirm-review-id", confirm, env=self.env(),
        )

    def test_applies_accepted_proposal_with_source_in_one_commit(self):
        proposal = self.proposal()
        self.write([proposal])
        r = self.apply()
        self.assertEqual(r.code, 0, r.text)
        text = self.read("fifo-scheduler")
        self.assertIn(f"[sources: transcript:{self.source}]", text)
        self.assertIn("2026-07-01", text)
        self.assertIn("Can preserve FIFO", text)
        self.assertEqual(len(self.git_log()), 1)
        marker = self.home / "reviews" / "applied" / "r1.json"
        self.assertTrue(marker.is_file())

    def test_rejected_proposal_leaves_model_unchanged(self):
        proposal = self.proposal()
        self.write([proposal], [{"proposal_id": proposal_id(proposal), "decision": "reject"}])
        r = self.apply()
        self.assertEqual(r.code, 0, r.text)
        self.assertFalse(self.path("fifo-scheduler").exists())
        self.assertEqual(self.git_log(), [])

    def test_requires_decision_for_every_proposal(self):
        self.write([self.proposal()], [])
        r = self.apply()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("cover every proposal", r.text)

    def test_requires_typed_review_confirmation(self):
        self.write([self.proposal()])
        r = self.apply("wrong")
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("confirm-review-id", r.text)
        self.assertFalse(self.path("fifo-scheduler").exists())

    def test_preflight_failure_changes_nothing(self):
        self.path("fifo-scheduler").write_text("malformed", encoding="utf-8")
        before = self.path("fifo-scheduler").read_bytes()
        self.write([self.proposal()])
        r = self.apply()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("preflight failed", r.text)
        self.assertEqual(self.path("fifo-scheduler").read_bytes(), before)

    def test_review_cannot_be_applied_twice(self):
        self.write([self.proposal()])
        self.assertEqual(self.apply().code, 0)
        r = self.apply()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("already applied", r.text)
