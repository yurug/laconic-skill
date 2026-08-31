import json

from helpers import ModelTestCase, TOOLS
from laconic_experiment import arm

STATS = TOOLS / "laconic_stats.py"


class ExperimentTest(ModelTestCase):
    def test_assignment_requires_double_opt_in_and_is_stable(self):
        self.assertEqual(arm("session"), "semantic")
        import os
        old_t, old_e = os.environ.get("LACONIC_TELEMETRY"), os.environ.get("LACONIC_EXPERIMENT")
        try:
            os.environ["LACONIC_TELEMETRY"] = os.environ["LACONIC_EXPERIMENT"] = "1"
            self.assertEqual(arm("session"), arm("session"))
            self.assertIn(arm("session"), ("semantic", "holdback"))
        finally:
            for key, value in (("LACONIC_TELEMETRY", old_t), ("LACONIC_EXPERIMENT", old_e)):
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value

    def test_stats_compare_both_arms_without_content(self):
        rows = [
            {"date": "2026-08-05", "session": "a", "experiment_arm": "semantic",
             "chars": 100, "touched": []},
            {"date": "2026-08-05", "session": "b", "experiment_arm": "holdback",
             "chars": 140, "touched": []},
        ]
        (self.home / "telemetry.jsonl").write_text("\n".join(json.dumps(x) for x in rows))
        result = self.run_tool(STATS, "--experiment")
        self.assertEqual(result.code, 0, result.text)
        self.assertIn("semantic: 1 turns", result.text)
        self.assertIn("holdback: 1 turns", result.text)
        self.assertIn("provisional", result.text)
