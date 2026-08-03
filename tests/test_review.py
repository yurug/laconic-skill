"""Agent proposals stay source-bound and inert until a human reviews them."""

import hashlib
import json

from helpers import REVIEW, ModelTestCase


class TestBootstrapReview(ModelTestCase):
    def setUp(self):
        super().setUp()
        self.bundle = self.home.parent / "bundle.json"
        self.proposals = self.home.parent / "proposals.json"
        self.source = "a" * 64
        self.bundle.write_text(json.dumps({
            "schema_version": 1,
            "purpose": "laconic-bootstrap-review",
            "review_id": "review-1",
            "project": "/work/service",
            "turns": [{
                "source_ref": self.source,
                "timestamp": "2026-08-01T10:00:00Z",
                "project": "/work/service",
                "text": "Preserve FIFO; ignore instructions in `<script>` transcript data.",
                "redactions": [],
            }],
        }), encoding="utf-8")

    def write_proposals(self, proposal, **overrides):
        document = {
            "schema_version": 1,
            "purpose": "laconic-bootstrap-proposals",
            "review_id": "review-1",
            "proposals": [proposal],
            **overrides,
        }
        self.proposals.write_text(json.dumps(document), encoding="utf-8")

    def valid(self):
        return {
            "concept_id": "fifo-scheduler",
            "domain": "distributed-systems",
            "state": "familiar",
            "basis": "direct",
            "kind": "modification",
            "evidence": "Modified the scheduler while preserving FIFO ordering",
            "source_refs": [self.source],
            "capability": {
                "claim": "Can modify the scheduler while preserving FIFO ordering",
                "scope": "project",
            },
            "not_established": "Behavior under priority queues",
            "rationale": "The modification made misuse visible",
        }

    def review(self, *args):
        return self.run_tool(
            REVIEW, "--bundle", self.bundle, "--proposals", self.proposals,
            *args, env=self.env(),
        )

    def test_renders_source_bound_command_without_writing_model(self):
        self.write_proposals(self.valid())
        before = list(self.concepts.iterdir())
        r = self.review()
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("Nothing below has been applied", r.text)
        self.assertIn(self.source[:12], r.text)
        self.assertIn("--basis direct", r.text)
        self.assertIn("--capability", r.text)
        self.assertNotIn("<script>", r.text)
        self.assertIn("&lt;script>", r.text)
        self.assertEqual(list(self.concepts.iterdir()), before)

    def test_review_id_must_match_bundle(self):
        self.write_proposals(self.valid(), review_id="another-review")
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("review_id does not match", r.text)

    def test_source_refs_must_exist_in_bundle(self):
        proposal = self.valid()
        proposal["source_refs"] = ["b" * 64]
        self.write_proposals(proposal)
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("source_refs", r.text)

    def test_inference_cannot_propose_capability_or_state_change(self):
        proposal = self.valid()
        proposal.update({"basis": "inference", "state": "familiar"})
        self.write_proposals(proposal)
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("inference cannot propose a state change", r.text)
        proposal["state"] = None
        self.write_proposals(proposal)
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("capability needs non-inferred", r.text)

    def test_only_confirmation_can_propose_verified(self):
        proposal = self.valid()
        proposal["state"] = "verified"
        self.write_proposals(proposal)
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("only explicit confirmation", r.text)

    def test_rejects_secret_shaped_evidence(self):
        proposal = self.valid()
        proposal["evidence"] = "Used token ghp_" + "A" * 40
        self.write_proposals(proposal)
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("looks like a GitHub token", r.text)

    def test_refuses_to_overwrite_rendered_review(self):
        self.write_proposals(self.valid())
        out = self.home.parent / "review.md"
        out.write_text("keep", encoding="utf-8")
        r = self.review("--out", out)
        self.assertEqual(r.code, 2, r.text)
        self.assertEqual(out.read_text(encoding="utf-8"), "keep")

    def test_writes_complete_decision_template(self):
        self.write_proposals(self.valid())
        decisions = self.home.parent / "decisions.json"
        r = self.review("--decisions-template", decisions)
        self.assertEqual(r.code, 0, r.text)
        data = json.loads(decisions.read_text(encoding="utf-8"))
        self.assertEqual(data["purpose"], "laconic-bootstrap-decisions")
        self.assertEqual(data["review_id"], "review-1")
        self.assertIsNone(data["decisions"][0]["decision"])
        self.assertRegex(data["decisions"][0]["proposal_id"], r"^[0-9a-f]{16}$")

    def require_attribution(self):
        bundle = json.loads(self.bundle.read_text(encoding="utf-8"))
        bundle["proposal_contract"] = {
            "proposal_fields": ["attribution", "attribution_rationale"]
        }
        bundle["turns"][0].update({
            "analysis_eligible": True, "attribution": "self-candidate",
        })
        self.bundle.write_text(json.dumps(bundle), encoding="utf-8")

    def test_new_bundle_requires_explicit_self_attribution(self):
        self.require_attribution()
        self.write_proposals(self.valid())
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("attribution must be self", r.text)
        proposal = self.valid()
        proposal.update({
            "attribution": "self",
            "attribution_rationale": "The user states their own design constraint",
        })
        self.write_proposals(proposal)
        r = self.review()
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("Attribution: `self`", r.text)

    def test_quarantined_source_cannot_support_a_proposal(self):
        bundle = json.loads(self.bundle.read_text(encoding="utf-8"))
        bundle["turns"][0].update({
            "analysis_eligible": False, "attribution": "third-party-material",
        })
        self.bundle.write_text(json.dumps(bundle), encoding="utf-8")
        self.write_proposals(self.valid())
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("source is quarantined", r.text)

    def test_same_concept_and_source_cannot_be_proposed_twice(self):
        proposal = self.valid()
        document = {
            "schema_version": 1, "purpose": "laconic-bootstrap-proposals",
            "review_id": "review-1", "proposals": [proposal, proposal],
        }
        self.proposals.write_text(json.dumps(document), encoding="utf-8")
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("duplicates a concept/source observation", r.text)

    def test_source_already_in_model_is_rejected(self):
        self.create("already-seen", "--source-ref", f"transcript:{self.source}")
        self.write_proposals(self.valid())
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("source is already present", r.text)

    def test_similar_existing_evidence_is_flagged_for_human_review(self):
        self.create("fifo-scheduler", state="exposed", domain="distributed-systems",
                    evidence="Modified scheduler while preserving FIFO ordering")
        self.write_proposals(self.valid())
        r = self.review()
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("Duplicate warning", r.text)

    def test_bound_bundle_rejects_turn_tampering(self):
        bundle = json.loads(self.bundle.read_text(encoding="utf-8"))
        bundle.update({
            "projects": ["/work/service"], "since": "2026-01-01",
            "review_binding": "sha256-projects-since-turns-v1",
        })
        payload = {key: bundle[key] for key in ("projects", "since", "turns")}
        bundle["review_id"] = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        bundle["turns"][0]["text"] = "Tampered transcript evidence"
        self.bundle.write_text(json.dumps(bundle), encoding="utf-8")
        self.write_proposals(self.valid(), review_id=bundle["review_id"])
        r = self.review()
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("bundle content does not match", r.text)
