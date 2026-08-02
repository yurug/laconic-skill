"""The theory-indexed applicability experiment is local, deterministic, and auditable."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helpers import REPO

SCRIPT = REPO / "eval" / "theory_relevance.py"
SPEC = importlib.util.spec_from_file_location("theory_relevance", SCRIPT)
theory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(theory)

EVIDENCE_SCRIPT = REPO / "eval" / "classify_evidence.py"
EVIDENCE_SPEC = importlib.util.spec_from_file_location(
    "classify_evidence_v2", EVIDENCE_SCRIPT
)
evidence_classifier = importlib.util.module_from_spec(EVIDENCE_SPEC)
EVIDENCE_SPEC.loader.exec_module(evidence_classifier)


class TheoryRelevanceTest(unittest.TestCase):
    def test_evidence_kind_distinguishes_theory_from_unclassified(self):
        self.assertEqual(
            theory.evidence_kind(
                "2026-07-29: [modification] rejected a change that broke the invariant"
            ),
            ("modification", "rejected a change that broke the invariant"),
        )
        self.assertEqual(
            theory.evidence_kind("2026-07-20: used the word correctly"),
            (None, "used the word correctly"),
        )

    def test_profiles_exclude_terms_and_rank_behavior_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            concepts = home / "concepts"
            concepts.mkdir()
            (concepts / "settlement-design.md").write_text(
                """---
id: settlement-design
type: concept
domain: finance
projects: [/work/ledger]
state: verified
confidence: 0.90
last-updated: 2026-07-29
evidence:
  - 2026-07-27: [world] mapped the cutoff to the market deadline
  - 2026-07-28: [term] used settlement correctly
  - 2026-07-29: [modification] rejected a retry that violated finality
---

Settlement design.
""",
                encoding="utf-8",
            )
            profiles = theory.collect_profiles(home)
            entries = profiles["-work-ledger"]
            self.assertEqual(
                [entry["kind"] for entry in entries], ["modification", "world"]
            )

    def test_evidence_classifier_keys_exact_unclassified_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            concepts = home / "concepts"
            concepts.mkdir()
            path = concepts / "retry-policy.md"
            path.write_text(
                """---
id: retry-policy
type: concept
domain: reliability
projects: [/work/service]
state: familiar
confidence: 0.60
last-updated: 2026-07-29
evidence:
  - 2026-07-29: rejected an unsafe retry
  - 2026-07-30: [term] used retry correctly
---

Retry policy.
""",
                encoding="utf-8",
            )
            rows = evidence_classifier.collect(home)
            self.assertEqual(len(rows), 1, "already marked evidence was reclassified")
            expected = __import__("hashlib").sha256(
                b"retry-policy\0rejected an unsafe retry"
            ).hexdigest()
            self.assertEqual(rows[0]["key"], expected)
            self.assertEqual(rows[0]["projects"], ["/work/service"])

    def test_mining_uses_project_not_keyword_cooccurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "-work-ledger"
            project.mkdir()
            prompt = (
                "Should we reject this retry or preserve the current settlement "
                "behavior for compatibility?"
            )
            transcript = project / "one.jsonl"
            transcript.write_text(
                "\n".join([
                    json.dumps({
                        "type": "user", "timestamp": "2026-07-30T10:00:00Z",
                        "message": {"content": prompt}
                    }),
                    json.dumps({
                        "type": "user", "timestamp": "2026-07-31T10:00:00Z",
                        "message": {"content": prompt}
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            rows = theory.mine(root, {
                "-work-ledger": [{
                    "concept": "settlement-design",
                    "kind": "modification",
                    "observation": "rejected a retry that violated finality",
                    "observed_on": "2026-07-29",
                }]
            })
            self.assertEqual(len(rows), 1, "duplicate prompt was not removed")
            self.assertEqual(rows[0]["prompt"], prompt)
            self.assertEqual(rows[0]["timestamp"], "2026-07-30T10:00:00Z")

    def test_mining_excludes_future_and_same_day_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "-work-ledger"
            project.mkdir()
            transcript = project / "one.jsonl"
            prompt = "Should we preserve the compatibility behavior in this release?"
            transcript.write_text(
                json.dumps({
                    "type": "user",
                    "timestamp": "2026-07-29T20:00:00Z",
                    "message": {"content": prompt},
                }) + "\n",
                encoding="utf-8",
            )
            profile = [{
                "concept": "compatibility-contract",
                "kind": "justification",
                "observation": "explained why old clients remain supported",
                "observed_on": "2026-07-29",
            }]
            self.assertEqual(theory.mine(root, {"-work-ledger": profile}), [])

    def test_cached_classification_does_not_rewrite_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "model"
            cache = root / "cache"
            (home / "concepts").mkdir(parents=True)
            cache.mkdir()
            path = home / "concepts" / "retry-policy.md"
            original = """---
id: retry-policy
type: concept
domain: reliability
projects: [/work/service]
state: familiar
confidence: 0.60
last-updated: 2026-07-29
evidence:
  - 2026-07-29: rejected an unsafe retry
---

Retry policy.
"""
            path.write_text(original, encoding="utf-8")
            key = __import__("hashlib").sha256(
                b"retry-policy\0rejected an unsafe retry"
            ).hexdigest()
            (cache / "verdicts.jsonl").write_text(
                json.dumps({
                    "id": "retry-policy",
                    "index": 0,
                    "key": key,
                    "kind": "modification",
                }) + "\n",
                encoding="utf-8",
            )
            profiles, total, indexed = theory.collect_cached_profiles(home, cache)
            self.assertEqual((total, indexed), (1, 1))
            self.assertEqual(
                profiles["-work-service"][0]["kind"], "modification"
            )
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_legacy_positional_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model" / "concepts").mkdir(parents=True)
            (root / "cache").mkdir()
            (root / "cache" / "batch-001.txt").write_text(
                '{"n": 1, "kind": "modification"}\n', encoding="utf-8"
            )
            profiles, total, indexed = theory.collect_cached_profiles(
                root / "model", root / "cache"
            )
            self.assertEqual((dict(profiles), total, indexed), ({}, 0, 0))

    def test_batch_exposes_no_source_path_to_the_judge(self):
        row = {
            "prompt": "Should this change preserve the old behavior?",
            "project": "-secret-project",
            "source": "-secret-project/transcript.jsonl",
            "theory": [{
                "concept": "compatibility-contract",
                "kind": "justification",
                "observation": "explained why old clients remain supported",
            }],
        }
        prompt = theory.build_batch([row])
        self.assertNotIn("-secret-project", prompt)
        self.assertNotIn("transcript.jsonl", prompt)
        self.assertIn("old clients remain supported", prompt)

    def test_verdict_parser_requires_an_auditable_evidence_list(self):
        valid = (
            '{"n": 1, "theory_discriminating": true, '
            '"evidence": [2], "why": "relies on invariant"}'
        )
        self.assertTrue(theory.parse_verdicts(valid, 1)[1]["theory_discriminating"])
        invalid = '{"n": 1, "theory_discriminating": true, "why": "unsupported"}'
        self.assertEqual(theory.parse_verdicts(invalid, 1), {})

    def test_positive_verdict_requires_an_in_range_citation(self):
        row = {"theory": [{"observation": "one"}]}
        empty = (
            '{"n": 1, "theory_discriminating": true, "evidence": [], "why": "none"}'
        )
        outside = (
            '{"n": 1, "theory_discriminating": true, "evidence": [2], "why": "bad"}'
        )
        self.assertEqual(theory.validated_verdicts(empty, [row]), {})
        self.assertEqual(theory.validated_verdicts(outside, [row]), {})

    def test_verified_legacy_run_can_be_promoted_to_hash_bound_cache(self):
        row = {
            "prompt": "Should this preserve compatibility?",
            "project": "-work-service",
            "source": "one.jsonl",
            "timestamp": "2026-07-31T10:00:00Z",
            "theory": [{
                "concept": "compatibility-contract",
                "kind": "justification",
                "observation": "explained why old clients remain supported",
                "observed_on": "2026-07-30",
            }],
        }
        raw_text = (
            '{"n": 1, "theory_discriminating": true, "evidence": [1], '
            '"why": "specific contract"}\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "batch-001.txt").write_text(raw_text, encoding="utf-8")
            (run_dir / "verdicts.jsonl").write_text(json.dumps({
                **row,
                "theory_discriminating": True,
                "relied_on": [1],
                "why": "specific contract",
                "ruled": True,
            }) + "\n", encoding="utf-8")
            self.assertEqual(theory.promote_verified_legacy_cache([row], run_dir), 1)
            raw, manifest = theory.batch_paths(run_dir, 1, [row])
            self.assertEqual(raw.read_text(encoding="utf-8"), raw_text)
            self.assertTrue(manifest.is_file())

    def test_failed_judge_response_is_not_accepted_or_recached(self):
        row = {
            "prompt": "Should this preserve compatibility?",
            "project": "-work-service",
            "source": "one.jsonl",
            "theory": [{
                "concept": "compatibility-contract",
                "kind": "justification",
                "observation": "explained why old clients remain supported",
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            raw = run_dir / "batch-001.txt"
            raw.write_text("API Error: old failure", encoding="utf-8")
            failed = SimpleNamespace(
                returncode=1,
                stdout="API Error: current failure",
                stderr="",
            )
            with mock.patch.object(theory.subprocess, "run", return_value=failed):
                with redirect_stdout(io.StringIO()):
                    self.assertIsNone(theory.classify([row], run_dir))
            self.assertEqual(
                raw.read_text(encoding="utf-8"),
                "API Error: old failure",
                "a failed retry overwrote the diagnostic cache",
            )

    def test_wilson_interval_contains_the_observed_rate(self):
        low, high = theory.wilson(5, 100)
        self.assertLess(low, 0.05)
        self.assertGreater(high, 0.05)

    def test_empty_wilson_interval_is_defined(self):
        self.assertEqual(theory.wilson(0, 0), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
