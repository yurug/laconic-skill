"""High-precision gating for the silent post-turn model-maintenance pass."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import laconic_maintenance as M


class MaintenanceTest(unittest.TestCase):
    def transcript(self, *events):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        with tmp:
            for event in events:
                tmp.write(json.dumps(event) + "\n")
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        return tmp.name

    @staticmethod
    def user(text):
        return {"type": "user", "message": {"content": text}}

    @staticmethod
    def assistant(text):
        return {"type": "assistant", "message": {"content": [
            {"type": "text", "text": text}
        ]}}

    def test_explicit_correction_triggers_review(self):
        path = self.transcript(self.user("Non, ce n'est pas le cache : l'invariant est faux."),
                               self.assistant("Corrigé."))
        self.assertEqual(M.should_review(path), "explicit correction")

    def test_substantial_justification_triggers_review(self):
        text = ("Il faut conserver ce verrou parce que la publication et la régénération "
                "de l'index doivent former une seule transition observable par les lecteurs. "
                "Sans cela ils peuvent charger un état incohérent.")
        self.assertEqual(M.should_review(self.transcript(self.user(text))),
                         "explicit justification")

    def test_ordinary_request_is_silent(self):
        path = self.transcript(self.user("Peux-tu corriger le test ?"), self.assistant("Oui."))
        self.assertEqual(M.should_review(path), "")

    def test_short_task_rationale_is_not_enough(self):
        self.assertEqual(M.should_review(self.transcript(
            self.user("Fais ceci parce que le test échoue."))), "")

    def test_existing_record_in_same_turn_suppresses_review(self):
        tool = {"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Bash",
            "input": {"command": "~/.laconic/bin/laconic-record thing --state familiar"},
        }]}}
        path = self.transcript(self.user("Actually, the invariant is the important part."), tool)
        self.assertEqual(M.should_review(path), "")

    def test_tool_results_do_not_replace_latest_real_prompt(self):
        tool_result = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "not a prompt"}
        ]}}
        path = self.transcript(self.user("Actually, preserve the invariant."), tool_result)
        self.assertEqual(M.should_review(path), "explicit correction")

    def test_detector_output_never_contains_prompt_text(self):
        secret = "counterparty-secret-7391"
        path = self.transcript(self.user(f"Actually, preserve {secret}."))
        reason = M.should_review(path)
        self.assertEqual(reason, "explicit correction")
        self.assertNotIn(secret, reason)

    def test_opted_in_begin_and_resolve_store_no_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior_home = os.environ.get("LACONIC_HOME")
            prior_telemetry = os.environ.get("LACONIC_TELEMETRY")
            os.environ["LACONIC_HOME"] = tmp
            os.environ["LACONIC_TELEMETRY"] = "1"
            try:
                secret = "private-invariant-8821"
                path = self.transcript(self.user(f"Actually, preserve {secret}."))
                self.assertEqual(M.begin(path, "session-private"), "explicit correction")
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"type": "assistant", "message": {"content": [{
                        "type": "tool_use", "input": {"command":
                            "~/.laconic/bin/laconic-record invariant --state familiar"},
                    }]}}) + "\n")
                M.resolve(path, "session-private")
                log = (Path(tmp) / "maintenance-telemetry.jsonl").read_text()
                self.assertNotIn(secret, log)
                self.assertNotIn("session-private", log)
                row = json.loads(log)
                self.assertTrue(row["recorded"])
                self.assertEqual(row["signal"], "explicit correction")
            finally:
                if prior_home is None:
                    os.environ.pop("LACONIC_HOME", None)
                else:
                    os.environ["LACONIC_HOME"] = prior_home
                if prior_telemetry is None:
                    os.environ.pop("LACONIC_TELEMETRY", None)
                else:
                    os.environ["LACONIC_TELEMETRY"] = prior_telemetry


if __name__ == "__main__":
    unittest.main()
