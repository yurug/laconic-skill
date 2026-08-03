"""The bootstrap web review persists decisions but cannot apply model changes."""

import hashlib
import json

from helpers import ModelTestCase
from laconic_review_web import ReviewState, load_decisions, save_decision


class TestReviewWeb(ModelTestCase):
    def setUp(self):
        super().setUp()
        self.source = "a" * 64
        self.bundle = self.home.parent / "bundle.json"
        self.proposals = self.home.parent / "proposals.json"
        self.decisions = self.home.parent / "decisions.json"
        turns = [{
            "source_ref": self.source, "timestamp": "2026-08-01T10:00:00Z",
            "project": str(self.home.parent), "text": "I preserved FIFO ordering.",
            "analysis_eligible": True, "attribution": "self-candidate",
        }]
        payload = {"projects": [str(self.home.parent)], "since": "2026-01-01",
                   "turns": turns}
        review_id = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        self.review_id = review_id
        self.bundle.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-bootstrap-review",
            "review_id": review_id,
            "review_binding": "sha256-projects-since-turns-v1", **payload,
        }), encoding="utf-8")
        self.proposals.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-bootstrap-proposals",
            "review_id": review_id, "proposals": [{
                "concept_id": "fifo-ordering", "domain": "distributed-systems",
                "state": "exposed", "basis": "direct", "kind": "term",
                "evidence": "Used FIFO ordering correctly as a design constraint",
                "source_refs": [self.source], "attribution": "self",
                "attribution_rationale": "The user states their own constraint",
            }],
        }), encoding="utf-8")

    def test_state_exposes_review_without_writing_model(self):
        state = ReviewState(self.bundle, self.proposals, self.decisions)
        payload = state.payload()
        self.assertEqual(len(payload["proposals"]), 1)
        self.assertIsNone(payload["proposals"][0]["decision"])
        self.assertFalse(self.decisions.exists())
        self.assertEqual(list(self.concepts.iterdir()), [])

    def test_each_decision_is_persisted_atomically(self):
        state = ReviewState(self.bundle, self.proposals, self.decisions)
        proposal_id = state.proposals[0]["proposal_id"]
        state.decide(proposal_id, "accept")
        saved = json.loads(self.decisions.read_text(encoding="utf-8"))
        self.assertEqual(saved["decisions"], [{
            "proposal_id": proposal_id, "decision": "accept",
        }])
        again = ReviewState(self.bundle, self.proposals, self.decisions)
        self.assertEqual(again.payload()["proposals"][0]["decision"], "accept")
        self.assertEqual(list(self.concepts.iterdir()), [])

    def test_unknown_proposal_and_invalid_decision_are_refused(self):
        state = ReviewState(self.bundle, self.proposals, self.decisions)
        with self.assertRaisesRegex(ValueError, "unknown proposal"):
            save_decision(self.decisions, state.decisions, "missing", "accept")
        with self.assertRaisesRegex(ValueError, "accept, reject"):
            save_decision(self.decisions, state.decisions,
                          state.proposals[0]["proposal_id"], "maybe")

    def test_mismatched_decision_file_is_refused(self):
        self.decisions.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-bootstrap-decisions",
            "review_id": "other", "decisions": [],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            load_decisions(self.decisions, self.review_id, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
