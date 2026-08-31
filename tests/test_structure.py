import json
from pathlib import Path

from helpers import ModelTestCase, TOOLS
import laconic_structure as S

STRUCTURE = TOOLS / "laconic_structure.py"


class TestStructure(ModelTestCase):
    def test_audit_is_hash_bound_and_reports_taxonomy_pressure(self):
        self.create("one", domain="tiny")
        document = S.audit(self.home)
        self.assertEqual(document["model_hash"], S.digest(self.home))
        self.assertEqual(document["diagnostics"]["singleton_domains"], {"tiny": ["one"]})

    def test_rename_and_merge_preserve_evidence_and_claim_sources(self):
        self.create("source", domain="old", evidence="explained source")
        self.record("source", "--claim", "Understands source", "--claim-from", "1")
        self.create("target", domain="new", evidence="explained target")
        operation = {"kind": "merge-concepts", "from": "source", "into": "target"}
        temporary, staged = S.preflight(self.home, [operation])
        try:
            merged = (staged / "concepts" / "target.md").read_text()
            self.assertFalse((staged / "concepts" / "source.md").exists())
            self.assertIn("Understands source (evidence: 2)", merged)
            self.assertIn("aliases: [source]", merged)
        finally:
            temporary.cleanup()

    def test_review_renders_without_applying(self):
        self.create("one", domain="old")
        audit_path = Path(self._tmp.name) / "audit.json"
        plan_path = Path(self._tmp.name) / "plan.json"
        review_path = Path(self._tmp.name) / "review.md"
        audit = S.audit(self.home)
        audit_path.write_text(json.dumps(audit))
        plan_path.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-structure-plan",
            "review_id": audit["review_id"],
            "operations": [{"kind": "rename-domain", "from": "old", "to": "new"}],
        }))
        result = self.run_tool(STRUCTURE, "review", "--audit", audit_path,
                               "--plan", plan_path, "--out", review_path)
        self.assertEqual(result.code, 0, result.text)
        self.assertEqual(self.field("one", "domain"), "old")
        self.assertIn("rename-domain", review_path.read_text())

    def test_apply_is_transactional_and_hash_bound(self):
        self.create("one", domain="old")
        audit_path = Path(self._tmp.name) / "audit.json"
        plan_path = Path(self._tmp.name) / "plan.json"
        audit = S.audit(self.home)
        audit_path.write_text(json.dumps(audit))
        plan_path.write_text(json.dumps({
            "schema_version": 1, "purpose": "laconic-structure-plan",
            "review_id": audit["review_id"],
            "operations": [{"kind": "rename-domain", "from": "old", "to": "new"}],
        }))
        result = self.run_tool(STRUCTURE, "apply", "--audit", audit_path, "--plan", plan_path,
                               "--confirm-review-id", audit["review_id"])
        self.assertEqual(result.code, 0, result.text)
        self.assertEqual(self.field("one", "domain"), "new")
        self.assertEqual(self.lint("--quiet").code, 0)
