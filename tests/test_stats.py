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


class TestDigest(ModelTestCase):
    """The digest is read by someone who never opens ~/.laconic, so a quiet week must
    read as a quiet week and not as a broken tool."""

    def digest(self, days=7):
        import laconic_stats
        from unittest import mock
        with mock.patch.object(laconic_stats, "home", return_value=self.home):
            return laconic_stats.digest(days)

    def route_row(self, when, domains, missed=()):
        with (self.home / "routing-telemetry.jsonl").open("a", encoding="utf-8") as h:
            h.write(json.dumps({"date": when, "domains": list(domains),
                                "missed_domains": list(missed)}) + "\n")

    def test_empty_model_says_so_without_alarm(self):
        out = self.digest()
        self.assertIn("Nothing recorded", out)
        self.assertIn("normal outcome", out)

    def test_reports_routing_rate(self):
        from datetime import date
        today = date.today().isoformat()
        self.route_row(today, ["laconic"])
        self.route_row(today, [])
        self.assertIn("1/2 prompts routed (50%)", self.digest())

    def test_surfaces_repeated_misses_as_alias_candidates(self):
        """One miss is noise. The threshold is what makes this actionable rather than a
        list of everything the router ever failed to select."""
        from datetime import date
        today = date.today().isoformat()
        for _ in range(3):
            self.route_row(today, ["laconic"], missed=["writing"])
        self.route_row(today, ["laconic"], missed=["one-off"])
        out = self.digest()
        self.assertIn("writing (3x)", out)
        self.assertNotIn("one-off", out)

    def test_ignores_rows_outside_the_window(self):
        self.route_row("2020-01-01", ["ancient"])
        self.assertIn("no routing telemetry", self.digest())

    def test_distillations_are_not_reported_as_learning(self):
        """A distillation restates existing evidence; counting it would inflate the one
        number the reader uses to judge whether anything happened."""
        import laconic_stats
        from unittest import mock
        (self.home / ".git").mkdir()
        with mock.patch.object(laconic_stats, "home", return_value=self.home), \
             mock.patch.object(laconic_stats.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout=(
                "thing: distilled (exposed, 2 observations)\n"
                "other: exposed -> familiar — [world] saw it\n"
                "same: familiar -> familiar — [term] again\n"
            ))
            changes = laconic_stats.model_changes("2026-01-01")
        self.assertEqual(changes, ["`other` exposed → familiar"])
