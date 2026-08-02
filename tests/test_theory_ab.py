"""The response A/B is paired, blinded, hash-bound, and local by default."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from helpers import REPO

SCRIPT = REPO / "eval" / "theory_ab.py"
SPEC = importlib.util.spec_from_file_location("theory_ab", SCRIPT)
ab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ab)


def case(key="00" + "a" * 62):
    return {
        "key": key,
        "theory_label": "A",
        "prompt": "Should this preserve compatibility for existing clients?",
        "theory": [{
            "concept": "compatibility-contract",
            "kind": "justification",
            "observation": "explained why old clients remain supported",
            "observed_on": "2026-07-30",
        }],
    }


class TheoryABTest(unittest.TestCase):
    def test_compact_policy_is_extracted_from_shipped_hook(self):
        policy = ab.compact_policy()
        self.assertIn("Lead with the outcome", policy)
        self.assertNotIn("Record evidence with the tool", policy)

    def test_recovers_last_answer_before_next_real_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "-work-project"
            project.mkdir()
            source = project / "session.jsonl"
            prompt = "Should this preserve compatibility for existing clients?"
            next_prompt = "Can you now summarize the migration risks for the release?"
            events = [
                {"type": "user", "message": {"content": prompt}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Working."}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "data"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Final grounded answer."}]}},
                {"type": "user", "message": {"content": next_prompt}},
            ]
            source.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
            row = {"source": "-work-project/session.jsonl", "prompt": prompt}
            self.assertEqual(ab.recover_draft(row, root), "Final grounded answer.")

    def test_blind_order_is_deterministic_and_hides_arm_names(self):
        row = case()
        row.update(
            profile=row.pop("theory"),
            policy_output="policy output",
            theory_output="theory output",
        )
        labels, a, b = ab.blind_pair(row)
        self.assertEqual((labels, a, b), ab.blind_pair(row))
        payload = ab.judge_prompt([row])
        answer_section = payload.split("ANSWER A:", 1)[1]
        self.assertIn("ANSWER B:", answer_section)
        self.assertNotIn("theory output", payload.split("ANSWER A:", 1)[0])

    def test_swapped_judge_reverses_labels_without_changing_outputs(self):
        row = case()
        row.update(
            profile=row.pop("theory"),
            policy_output="policy output",
            theory_output="theory output",
        )
        _, normal_a, normal_b = ab.blind_pair(row)
        _, swapped_a, swapped_b = ab.blind_pair(row, swapped=True)
        self.assertEqual((normal_a, normal_b), (swapped_b, swapped_a))
        normal = ab.judge_prompt([row])
        swapped = ab.judge_prompt([row], swapped=True)
        self.assertIn("ANSWER A:\ntheory output", normal)
        self.assertIn("ANSWER A:\npolicy output", swapped)

    def test_judge_parser_requires_guardrail_arrays(self):
        good = (
            '{"n":1,"winner":"A","material_loss":[], '
            '"unsupported_assumption":["B"],"why":"better calibrated"}'
        )
        self.assertEqual(ab.parse_judgments(good, 1)[1]["winner"], "A")
        bad = '{"n":1,"winner":"A","why":"missing guards"}'
        self.assertEqual(ab.parse_judgments(bad, 1), {})

    def test_theory_context_states_the_inference_boundary(self):
        text = ab.theory_context(case())
        self.assertIn("infer nothing else", text)
        self.assertIn("justification", text)


if __name__ == "__main__":
    unittest.main()
