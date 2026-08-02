"""The human-review artifact stays blinded and imports complete judgments."""

import importlib.util
import unittest

from helpers import REPO

SCRIPT = REPO / "eval" / "human_review.py"
SPEC = importlib.util.spec_from_file_location("human_review", SCRIPT)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def output():
    return {
        "key": "a" * 64,
        "prompt": "Should this preserve compatibility for existing clients?",
        "profile": [{"kind": "justification", "observation": "explained the client contract"}],
        "theory_label": "A",
        "policy_output": "First candidate answer.",
        "theory_output": "Second candidate answer.",
    }


class HumanReviewTest(unittest.TestCase):
    def test_bundle_has_blind_labels_without_identity_metadata(self):
        page = review.render([output()])
        self.assertIn("Answer A", page)
        self.assertIn("Answer B", page)
        self.assertNotIn("theory_label", page)
        self.assertNotIn("policy_output", page)

    def test_import_maps_blind_winner_to_arm(self):
        row = output()
        result = review.import_results([row], [{
            "key": row["key"], "winner": "A", "material_loss": [],
            "unsupported_assumption": [], "why": "better calibrated",
        }])
        self.assertEqual(result[0]["winner"], "theory")

    def test_import_requires_complete_key_coverage(self):
        with self.assertRaises(ValueError):
            review.import_results([output()], [])


if __name__ == "__main__":
    unittest.main()
