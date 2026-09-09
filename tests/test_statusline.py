"""The statusline is the only component that addresses the user rather than the agent.

Its contract is therefore unusual: it must always print exactly one line, and it must
never fail. A traceback here replaces the reassurance it exists to give.
"""

import hashlib
import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from helpers import TOOLS, ModelTestCase

import laconic_statusline as S

STATUSLINE = TOOLS / "laconic_statusline.py"


class StatuslineTestCase(ModelTestCase):
    def line(self, session_id=""):
        """Render in-process against this test's isolated model."""
        with mock.patch.object(S, "HOME", self.home), \
             mock.patch.object(S, "CONCEPTS", self.concepts):
            return S.render(session_id)

    def concept(self, name):
        (self.concepts / f"{name}.md").write_text("---\nid: x\n---\n", encoding="utf-8")

    def route_row(self, session_id, domains, pending=False):
        digest = hashlib.sha256(session_id.encode()).hexdigest()[:20]
        row = {"date": "2026-09-09", "session": digest, "domains": domains}
        if pending:
            directory = self.home / ".routing-pending"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{digest}.json").write_text(json.dumps(row), encoding="utf-8")
        else:
            with (self.home / "routing-telemetry.jsonl").open("a", encoding="utf-8") as h:
                h.write(json.dumps(row) + "\n")


class TestContent(StatuslineTestCase):
    def test_reports_the_concept_count(self):
        for name in ("a", "b", "c"):
            self.concept(name)
        self.assertIn("laconic 3c", self.line())

    def test_shows_domains_routed_for_this_prompt(self):
        self.route_row("sess", ["droit-social", "management"])
        self.assertIn("droit-social, management", self.line("sess"))

    def test_prefers_the_in_flight_pending_row(self):
        """The pending file is the current turn; the log row is the previous one. Showing
        the stale answer while a new prompt is running is the one wrong order here."""
        self.route_row("sess", ["old-domain"])
        self.route_row("sess", ["new-domain"], pending=True)
        self.assertIn("new-domain", self.line("sess"))
        self.assertNotIn("old-domain", self.line("sess"))

    def test_ignores_another_sessions_rows(self):
        self.route_row("other", ["not-mine"])
        self.assertNotIn("not-mine", self.line("sess"))

    def test_truncates_a_long_domain_list(self):
        self.route_row("sess", ["one", "two", "three", "four", "five"])
        out = self.line("sess")
        self.assertIn("one, two, three +2", out)

    def test_unrouted_prompt_still_reports_liveness(self):
        """A prompt that matched no domain is normal, not a fault: the line must still
        say the plugin is there, or silence reads as absence again."""
        self.route_row("sess", [])
        out = self.line("sess")
        self.assertTrue(out.startswith("▸ laconic"))
        self.assertNotIn("·", out.replace("▸ laconic", "", 1))


class TestWarnings(StatuslineTestCase):
    def test_flags_a_session_older_than_the_config(self):
        with mock.patch.object(S, "session_started", return_value=1.0), \
             mock.patch.object(Path, "stat", autospec=True) as stat:
            stat.return_value = mock.Mock(st_mtime=2.0)
            self.assertTrue(S.policy_is_stale("sess"))

    def test_does_not_flag_a_session_newer_than_the_config(self):
        with mock.patch.object(S, "session_started", return_value=3.0), \
             mock.patch.object(Path, "stat", autospec=True) as stat:
            stat.return_value = mock.Mock(st_mtime=2.0)
            self.assertFalse(S.policy_is_stale("sess"))

    def test_no_session_id_is_not_stale(self):
        self.assertFalse(S.policy_is_stale(""))

    def test_flags_an_unlinted_model(self):
        self.concept("a")
        stamp = self.home / ".lint-ok"
        stamp.touch()
        import os
        os.utime(stamp, (0, 0))  # lint ran before the concept was written
        with mock.patch.object(S, "HOME", self.home), \
             mock.patch.object(S, "CONCEPTS", self.concepts), \
             mock.patch.object(S, "policy_is_stale", return_value=False):
            self.assertIn("unlinted", S.render(""))

    def test_clean_model_says_nothing(self):
        self.concept("a")
        (self.home / ".lint-ok").touch()
        with mock.patch.object(S, "HOME", self.home), \
             mock.patch.object(S, "CONCEPTS", self.concepts), \
             mock.patch.object(S, "policy_is_stale", return_value=False):
            self.assertNotIn("!", S.render(""))


class TestSessionStart(StatuslineTestCase):
    def test_reads_past_untimestamped_header_records(self):
        """Transcripts open with last-prompt/mode/permission-mode records that carry no
        timestamp. Taking the first line alone would make every session look unknown."""
        fake_home = self.home.parent
        projects = fake_home / ".claude" / "projects" / "proj"
        projects.mkdir(parents=True)
        (projects / "abc.jsonl").write_text(
            json.dumps({"type": "last-prompt", "leafUuid": "x"}) + "\n"
            + json.dumps({"type": "mode", "mode": "normal"}) + "\n"
            + json.dumps({"type": "user", "timestamp": "2026-08-31T08:25:23.205Z"}) + "\n",
            encoding="utf-8",
        )
        with mock.patch.object(Path, "home", return_value=fake_home):
            started = S.session_started("abc")
        self.assertIsNotNone(started)
        self.assertEqual(
            datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
            "2026-08-31T08:25:23.205000+00:00",
        )

    def test_unknown_session_has_no_start_time(self):
        with mock.patch.object(Path, "home", return_value=self.home.parent):
            self.assertIsNone(S.session_started("nope"))


class TestRobustness(StatuslineTestCase):
    """It runs on every render. Anything it cannot read must cost a field, not the line."""

    def run_line(self, stdin):
        proc = subprocess.run(
            [sys.executable, str(STATUSLINE)],
            input=stdin, capture_output=True, text=True,
            env=self.env(), check=False,
        )
        return proc

    def test_missing_model_still_prints_one_line(self):
        import shutil
        shutil.rmtree(self.concepts)
        proc = self.run_line('{"session_id":"sess"}')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
        self.assertIn("laconic", proc.stdout)

    def test_garbage_stdin_still_prints_one_line(self):
        for junk in ("", "not json", "[]", '{"session_id":null}'):
            proc = self.run_line(junk)
            self.assertEqual(proc.returncode, 0, junk)
            self.assertIn("laconic", proc.stdout, junk)
            self.assertEqual(proc.stderr, "", junk)

    def test_corrupt_telemetry_line_is_skipped(self):
        with (self.home / "routing-telemetry.jsonl").open("w", encoding="utf-8") as h:
            h.write("{not json\n")
        self.route_row("sess", ["good"])
        self.assertIn("good", self.line("sess"))


if __name__ == "__main__":
    unittest.main()
