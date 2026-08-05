"""Reports maintenance yield without requiring prompt or response content."""

import json

from helpers import ModelTestCase, TOOLS


class StatsTest(ModelTestCase):
    def test_maintenance_report_distinguishes_records_and_noops(self):
        rows = [
            {"date": "2026-08-04", "signal": "explicit correction", "recorded": True},
            {"date": "2026-08-04", "signal": "explicit justification", "recorded": False},
        ]
        (self.home / "maintenance-telemetry.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        result = self.run_tool(TOOLS / "laconic_stats.py", "--maintenance")
        self.assertEqual(result.code, 0, result.text)
        self.assertIn("2 silent maintenance passes", result.out)
        self.assertIn("50.0%", result.out)
        self.assertIn("not recall", result.out)

    def test_routing_report_shows_frequency_cost_and_domains(self):
        rows = [
            {"date": "2026-08-04", "domains": ["rocq"], "chars": 420,
             "answer_domains": ["rocq"], "missed_domains": [], "routing_version": 2},
            {"date": "2026-08-04", "domains": [], "chars": 0,
             "answer_domains": [], "missed_domains": ["databases"], "routing_version": 2},
        ]
        (self.home / "routing-telemetry.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        result = self.run_tool(TOOLS / "laconic_stats.py", "--routing")
        self.assertEqual(result.code, 0, result.text)
        self.assertIn("2 prompts observed", result.out)
        self.assertIn("50.0%", result.out)
        self.assertIn("210 chars", result.out)
        self.assertIn("'rocq': 1", result.out)
        self.assertIn("1/1 (100.0%)", result.out)
        self.assertIn("possible missed domains: {'databases': 1}", result.out)
