import json
from pathlib import Path

from helpers import MIGRATE_V2, ModelTestCase


class TestV2Migration(ModelTestCase):
    def export(self):
        path = Path(self._tmp.name) / "bundle.json"
        result = self.run_tool(MIGRATE_V2, "export", "--out", path)
        self.assertEqual(result.code, 0, result.text)
        return path, json.loads(path.read_text())

    def test_export_is_deterministic_and_contains_no_mutation(self):
        self.create("cache", evidence="explained why the cache is bounded")
        before = self.read("cache")
        first_path, first = self.export()
        second_path, second = self.export()
        self.assertEqual(first["migration_id"], second["migration_id"])
        self.assertEqual(first["concepts"][0]["evidence"][0]["index"], 1)
        self.assertEqual(self.read("cache"), before)
        self.assertEqual(first_path, second_path)

    def test_hash_bound_review_applies_only_accepted_claim(self):
        self.create("cache", evidence="explained why the cache is bounded")
        bundle_path, bundle = self.export()
        proposal_path = Path(self._tmp.name) / "proposals.json"
        proposal = {
            "schema_version": 1, "purpose": "laconic-v2-proposals",
            "migration_id": bundle["migration_id"], "proposals": [{
                "concept_id": "cache", "kind": "principle",
                "claim": "Treats boundedness as a cache invariant", "evidence": [1],
                "scope": "project", "condition": "",
            }],
        }
        proposal_path.write_text(json.dumps(proposal))
        # Proposal ids are derived by the validator; importing it keeps the fixture honest.
        import laconic_migrate_v2
        proposal_id = laconic_migrate_v2.validate(bundle, proposal)[0]["proposal_id"]
        decision_path = Path(self._tmp.name) / "decisions.json"
        review_path = Path(self._tmp.name) / "review.md"
        reviewed = self.run_tool(MIGRATE_V2, "review", "--bundle", bundle_path,
                                 "--proposals", proposal_path, "--out", review_path,
                                 "--decisions-out", decision_path)
        self.assertEqual(reviewed.code, 0, reviewed.text)
        self.assertIn(proposal_id, review_path.read_text())
        decision_doc = json.loads(decision_path.read_text())
        decision_doc["decisions"][0]["decision"] = "accept"
        decision_path.write_text(json.dumps(decision_doc))
        result = self.run_tool(
            MIGRATE_V2, "apply", "--bundle", bundle_path, "--proposals", proposal_path,
            "--decisions", decision_path, "--confirm-migration-id", bundle["migration_id"],
        )
        self.assertEqual(result.code, 0, result.text)
        self.assertIn("Treats boundedness as a cache invariant", self.read("cache"))
        self.assertEqual(self.lint("--quiet").code, 0)

    def test_rejects_inference_and_stale_model_hash(self):
        self.create("cache", "--basis", "inference", state="unknown", evidence="might know it")
        bundle_path, bundle = self.export()
        proposal = {
            "schema_version": 1, "purpose": "laconic-v2-proposals",
            "migration_id": bundle["migration_id"], "proposals": [{
                "concept_id": "cache", "kind": "understanding", "claim": "Knows it",
                "evidence": [1], "scope": "project",
            }],
        }
        import laconic_migrate_v2
        with self.assertRaisesRegex(ValueError, "inferred"):
            laconic_migrate_v2.validate(bundle, proposal)
