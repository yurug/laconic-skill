"""Live instrumentation: what it counts, what it refuses to log, and what it costs."""

import json
import unittest

from helpers import TOOLS, ModelTestCase

OBSERVE = TOOLS / "laconic_observe.py"


class ObserveTestCase(ModelTestCase):
    def transcript(self, *entries):
        """A transcript in the harness's shape: assistant messages carry a content list,
        and tool results arrive as `user` entries, which must not end the turn."""
        path = self.home / "transcript.jsonl"
        lines = []
        for kind, text in entries:
            if kind == "user":
                lines.append({"type": "user", "message": {"content": text}})
            elif kind == "tool_result":
                lines.append({"type": "user", "message": {
                    "content": [{"type": "tool_result", "content": text}]}})
            else:
                lines.append({"type": "assistant", "message": {
                    "content": [{"type": "text", "text": text}]}})
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
        return path

    def observe(self, transcript, session="s1", **env):
        enabled = {"LACONIC_TELEMETRY": "1", **env}
        return self.run_tool(OBSERVE, transcript, session, env=self.env(**enabled))

    def rows(self):
        log = self.home / "telemetry.jsonl"
        if not log.exists():
            return []
        return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


class TestDetection(ObserveTestCase):
    def test_detects_a_touched_concept(self):
        self.create("cognitive-load-theory", state="familiar", domain="cognitive-science")
        t = self.transcript(("user", "how should I write this?"),
                            ("assistant", "Worth weighing cognitive load theory here."))
        self.assertEqual(self.observe(t).code, 0)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual([x["id"] for x in rows[0]["touched"]], ["cognitive-load-theory"])

    def test_ignores_a_concept_not_mentioned(self):
        self.create("cognitive-load-theory", state="familiar", domain="cognitive-science")
        t = self.transcript(("user", "hi"), ("assistant", "Nothing relevant here at all."))
        self.observe(t)
        self.assertEqual(self.rows()[0]["touched"], [])

    def test_counts_the_whole_turn_not_just_the_last_message(self):
        """An agentic turn interleaves preambles with tool calls; the answer is spread across
        several assistant messages and the last is often a one-line lead-in."""
        self.create("settlement-cycles", state="verified", domain="etf", evidence="a")
        t = self.transcript(
            ("user", "explain the flow"),
            ("assistant", "The settlement cycles drive the gap."),
            ("tool_result", "some tool output"),
            ("assistant", "Done."),
        )
        self.observe(t)
        self.assertEqual([x["id"] for x in self.rows()[0]["touched"]], ["settlement-cycles"])

    def test_stops_at_the_previous_user_message(self):
        self.create("settlement-cycles", state="verified", domain="etf", evidence="a")
        t = self.transcript(
            ("assistant", "Earlier answer about settlement cycles."),
            ("user", "new question"),
            ("assistant", "This answer mentions nothing modeled."),
        )
        self.observe(t)
        self.assertEqual(self.rows()[0]["touched"], [], "leaked across the turn boundary")


class TestDiscriminating(ObserveTestCase):
    """With an empty model the policy default is to explain, so only states that say do NOT
    explain change the writing."""

    def test_verified_counts(self):
        self.create("thing-one", state="verified", domain="testing", evidence="a")
        self.record("thing-one", "--state", "verified", "--evidence", "b")
        t = self.transcript(("user", "q"), ("assistant", "Depends on thing one entirely."))
        self.observe(t)
        self.assertEqual(self.rows()[0]["discriminating"], 1)

    def test_exposed_does_not_count(self):
        self.create("thing-one", state="exposed", domain="testing")
        t = self.transcript(("user", "q"), ("assistant", "Depends on thing one entirely."))
        self.observe(t)
        self.assertEqual(self.rows()[0]["discriminating"], 0,
                         "exposed matches the no-model default; it cannot discriminate")

    def test_a_recorded_gap_cancels_discrimination(self):
        """A gap reinstates the explanation: the concept reads verified but a named part of
        it is not established, so explaining that part is correct rather than redundant."""
        self.create("thing-one", state="verified", domain="testing", evidence="a")
        self.record("thing-one", "--state", "verified", "--evidence", "b")
        self.record("thing-one", "--not-established", "the error paths")
        t = self.transcript(("user", "q"), ("assistant", "Depends on thing one entirely."))
        self.observe(t)
        self.assertEqual(self.rows()[0]["discriminating"], 0)


class TestPrivacyAndSafety(ObserveTestCase):
    def test_never_logs_prompt_or_response_text(self):
        secret = "SUPERSECRETPHRASE-do-not-log"
        self.create("cognitive-load-theory", state="familiar", domain="cognitive-science")
        t = self.transcript(("user", secret),
                            ("assistant", f"{secret} and cognitive load theory."))
        self.observe(t)
        raw = (self.home / "telemetry.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(secret, raw, "response or prompt text reached the telemetry log")

    def test_hashes_session_identity(self):
        self.create("cognitive-load-theory", state="familiar", domain="cognitive-science")
        transcript = self.transcript(("user", "q"), ("assistant", "cognitive load theory"))
        self.observe(transcript, session="private-session-id")
        raw = (self.home / "telemetry.jsonl").read_text()
        self.assertNotIn("private-session-id", raw)

    def test_requires_explicit_opt_in(self):
        self.create("cognitive-load-theory", state="familiar", domain="cognitive-science")
        t = self.transcript(("user", "q"), ("assistant", "cognitive load theory"))
        self.observe(t, LACONIC_TELEMETRY="")
        self.assertEqual(self.rows(), [])

    def test_survives_a_corrupt_transcript(self):
        """It runs in the Stop hook on every turn. A measurement must never break the thing
        it measures."""
        path = self.home / "broken.jsonl"
        path.write_text("{not json\n\x00\x01garbage\n", encoding="utf-8")
        self.assertEqual(self.observe(path).code, 0)

    def test_survives_a_missing_transcript(self):
        self.assertEqual(self.observe(self.home / "nope.jsonl").code, 0)


class TestStats(ObserveTestCase):
    def test_reports_without_a_log(self):
        r = self.run_tool(TOOLS / "laconic_stats.py", env=self.env())
        self.assertEqual(r.code, 0)
        self.assertIn("no observations yet", r.text)

    def test_reports_rates(self):
        self.create("thing-one", state="verified", domain="testing", evidence="a")
        self.record("thing-one", "--state", "verified", "--evidence", "b")
        for _ in range(2):
            self.observe(self.transcript(("user", "q"),
                                         ("assistant", "About thing one, at length.")))
        self.observe(self.transcript(("user", "q"), ("assistant", "Unrelated answer.")))
        r = self.run_tool(TOOLS / "laconic_stats.py", env=self.env())
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("3 turns observed", r.text)


if __name__ == "__main__":
    unittest.main()
