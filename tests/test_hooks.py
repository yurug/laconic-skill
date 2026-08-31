"""The hook contracts: JSON envelopes, and when the Stop hook speaks.

These run the shell handlers as the harness does -- payload on stdin, JSON on stdout -- so a
quoting or exit-code regression shows up here rather than as a broken session.
"""

import json
import os
import subprocess
import time
import unittest
from unittest import mock

from helpers import REPO, ModelTestCase
from laconic_lint import INDEX_BUDGET

INJECT = REPO / "hooks-handlers" / "inject-policy.sh"
STOP = REPO / "hooks-handlers" / "stop-check.sh"
ROUTE = REPO / "hooks-handlers" / "route-knowledge.sh"

class HookTestCase(ModelTestCase):
    def hook(self, script, *args, payload="{}", env=None):
        e = env or self.env()
        e["CLAUDE_PLUGIN_ROOT"] = str(REPO)
        proc = subprocess.run(
            ["bash", str(script), *args],
            input=payload,
            capture_output=True,
            text=True,
            env=e,
            check=False,
        )
        return proc

    def envelope(self, *args, **kw):
        proc = self.hook(INJECT, *args, **kw)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

class TestInjectPolicy(HookTestCase):
    EMPTY_CONTEXT_BUDGET = 2800
    TOTAL_CONTEXT_BUDGET = 8000

    def test_session_start_envelope(self):
        env = self.envelope("SessionStart")
        self.assertEqual(env["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", env["hookSpecificOutput"])

    def test_carries_the_policy(self):
        ctx = self.envelope("SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Laconic (always on)", ctx)
        self.assertIn("Lead with the outcome", ctx)

    def test_compact_tail_preserves_model_safety_rules(self):
        ctx = self.envelope("SessionStart")["hookSpecificOutput"]["additionalContext"]
        for rule in (
            "--basis inference",
            "Never infer prerequisites",
            "Strong --kind values",
            "facet question becomes a gap",
            "never store secrets or confidential text",
            "both an origin and LACONIC_PUSH=1",
        ):
            self.assertIn(rule, ctx)

    def test_empty_and_worst_case_context_are_bounded(self):
        ctx = self.envelope("SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(ctx), self.EMPTY_CONTEXT_BUDGET)
        marker = "\n\n## What the user knows\n\n"
        self.assertIn(marker, ctx)
        static_chars = len(ctx.split(marker, 1)[0] + marker)
        self.assertLessEqual(static_chars + INDEX_BUDGET + 1, self.TOTAL_CONTEXT_BUDGET)

    def test_empty_model_is_stated_not_faked(self):
        ctx = self.envelope("SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("assume nothing", ctx.lower())

    def test_defaults_to_session_start(self):
        env = self.envelope()
        self.assertEqual(env["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_fresh_install_defaults_home_when_laconic_home_is_unset(self):
        environment = self.env()
        environment.pop("LACONIC_HOME")
        environment["HOME"] = str(self.home.parent)
        proc = self.hook(INJECT, "SessionStart", env=environment)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(self.home.parent / ".laconic" / "bin" / "laconic-record"), context)

    def test_lists_recorded_concepts(self):
        self.create("tezos-finality", domain="consensus")
        ctx = self.envelope("SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("domain routes: consensus", ctx)
        self.assertIn("tezos-finality", (self.home / "indexes" / "domains" /
                                         "consensus.md").read_text())

    def test_injects_established_gaps(self):
        self.create("thing", domain="d")
        self.record("thing", "--state", "exposed", "--evidence", "two")
        self.record("thing", "--state", "exposed", "--evidence", "three")
        self.record("thing", "--not-established", "the failure modes")
        ctx = self.envelope(
            "SessionStart", payload=json.dumps({"cwd": str(REPO)})
        )["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Established gaps", ctx)
        self.assertIn("the failure modes", ctx)

    def test_forwards_cwd_for_relevance_scoping(self):
        """The cwd arrives on stdin; without it the index cannot keep this project inline."""
        proc = self.hook(INJECT, "SessionStart", payload=json.dumps({"cwd": str(REPO)}))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        json.loads(proc.stdout)

    def test_opt_in_holdback_omits_semantic_claims_only(self):
        self.create("thing", "--kind", "world", domain="testing", evidence="explained it")
        self.record("thing", "--claim", "Understands the mechanism", "--claim-from", "1")
        from laconic_experiment import arm
        environment = self.env(LACONIC_TELEMETRY="1", LACONIC_EXPERIMENT="1")
        with mock.patch.dict(os.environ, environment):
            session = next(f"holdback-{i}" for i in range(100) if arm(f"holdback-{i}") == "holdback")
        proc = self.hook(INJECT, "SessionStart", env=environment, payload=json.dumps({
            "cwd": str(REPO), "session_id": session,
        }))
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("thing", context)
        self.assertNotIn("Understands the mechanism", context)

    def test_survives_garbage_stdin(self):
        """A broken hook would degrade every session, so it must never fail loudly."""
        proc = self.hook(INJECT, "SessionStart", payload="not json at all {{{")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        json.loads(proc.stdout)

    def test_survives_empty_stdin(self):
        proc = self.hook(INJECT, "SessionStart", payload="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        json.loads(proc.stdout)

    def test_missing_python_degrades_to_valid_conservative_context(self):
        environment = self.env(PATH="")
        environment["CLAUDE_PLUGIN_ROOT"] = str(REPO)
        proc = subprocess.run(
            ["/bin/bash", str(INJECT), "SessionStart"], input="{}", capture_output=True,
            text=True, env=environment, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("python3 is required", context)
        self.assertIn("Assume nothing", context)

    def test_unknown_event_cannot_corrupt_the_envelope(self):
        environment = self.env(PATH="")
        environment["CLAUDE_PLUGIN_ROOT"] = str(REPO)
        proc = subprocess.run(
            ["/bin/bash", str(INJECT), 'bad"event'], input="{}", capture_output=True,
            text=True, env=environment, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_quotes_in_a_concept_id_cannot_corrupt_the_envelope(self):
        """Ids are kebab-case, but the envelope is built by hand and must stay well-formed
        even if a stray file appears in the model directory."""
        (self.concepts / "odd.md").write_text(
            '---\nid: odd\ntype: concept\ndomain: "a\\"b"\nstate: exposed\n'
            'confidence: 0.30\nlast-updated: 2026-07-28\nevidence:\n  - 2026-07-28: x\n---\n\n'
            'odd.\n',
            encoding="utf-8",
        )
        env = self.envelope("SessionStart")
        self.assertIn("additionalContext", env["hookSpecificOutput"])

class TestSubagentPolicy(HookTestCase):
    def test_subagent_envelope(self):
        env = self.envelope("SubagentStart")
        self.assertEqual(env["hookSpecificOutput"]["hookEventName"], "SubagentStart")

    def test_forbids_writing_to_the_model(self):
        """A subagent sees a task prompt, not the user's words, so it has no first-hand
        evidence and must not record any."""
        ctx = self.envelope("SubagentStart")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Do NOT write", ctx)

    def test_withholds_the_recording_command(self):
        ctx = self.envelope("SubagentStart")["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("laconic_record.py", ctx)
        self.assertNotIn("--not-established", ctx)

    def test_still_receives_the_policy_and_the_model(self):
        self.create("tezos-finality", domain="consensus")
        ctx = self.envelope("SubagentStart")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Lead with the outcome", ctx)
        self.assertIn("domain routes: consensus", ctx)


class TestPromptRouting(HookTestCase):
    def test_holdback_also_omits_claims_from_prompt_routes(self):
        self.create("thing", "--kind", "world", domain="testing", evidence="explained it")
        self.record("thing", "--claim", "Understands the mechanism", "--claim-from", "1",
                    "--claim-scope", "domain")
        from laconic_experiment import arm
        environment = self.env(LACONIC_TELEMETRY="1", LACONIC_EXPERIMENT="1")
        with mock.patch.dict(os.environ, environment):
            session = next(f"route-holdback-{i}" for i in range(100)
                           if arm(f"route-holdback-{i}") == "holdback")
        proc = self.hook(ROUTE, env=environment, payload=json.dumps({
            "prompt": "Tell me about the testing thing", "session_id": session,
        }))
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("thing", context)
        self.assertNotIn("Understands the mechanism", context)

    def test_correction_requests_private_in_turn_maintenance(self):
        proc = self.hook(ROUTE, payload=json.dumps({
            "prompt": "Non, ce n'est pas le cache : cet invariant est nécessaire.",
            "session_id": "s",
        }))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Silent Laconic maintenance", context)
        self.assertNotIn("decision", json.loads(proc.stdout))

    def test_relevant_domain_is_loaded_without_user_action(self):
        self.create("rocq-proof-obligations", domain="formal-verification")
        proc = self.hook(ROUTE, payload=json.dumps({
            "prompt": "Can we discharge these Rocq obligations?", "cwd": str(REPO),
        }))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Laconic automatic routes", context)
        self.assertIn("formal-verification", context)
        self.assertIn("rocq-proof-obligations", context)
        self.assertLessEqual(len(context), 2800)

    def test_unrelated_prompt_is_silent(self):
        self.create("rocq-proof-obligations", domain="formal-verification")
        proc = self.hook(ROUTE, payload=json.dumps({"prompt": "Hello there"}))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_malformed_payload_is_silent(self):
        proc = self.hook(ROUTE, payload="not json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_opted_in_routing_telemetry_contains_no_prompt(self):
        self.create("rocq-proof-obligations", domain="formal-verification")
        secret = "private-proof-7719"
        env = self.env(LACONIC_TELEMETRY="1")
        proc = self.hook(ROUTE, payload=json.dumps({
            "prompt": f"Check these Rocq obligations {secret}",
            "session_id": "raw-session-id",
        }), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pending = next((self.home / ".routing-pending").glob("*.json"))
        log = pending.read_text(encoding="utf-8")
        self.assertNotIn(secret, log)
        self.assertNotIn("raw-session-id", log)
        row = json.loads(log)
        self.assertEqual(row["domains"], ["formal-verification"])
        self.assertGreater(row["chars"], 0)

    def test_routing_telemetry_is_opt_in(self):
        self.create("rocq-proof-obligations", domain="formal-verification")
        self.hook(ROUTE, payload=json.dumps({"prompt": "Rocq obligations"}))
        self.assertFalse((self.home / "routing-telemetry.jsonl").exists())

class TestStopCheck(HookTestCase):
    def transcript(self, user_turns):
        path = self.home / "transcript.jsonl"
        lines = []
        for i in range(user_turns):
            lines.append(json.dumps({
                "type": "user", "message": {"content": f"turn {i}"}}))
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "reply"}]},
            }))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def payload(self, turns=6, stop_active=False, session="sess-1"):
        return json.dumps({
            "stop_hook_active": stop_active,
            "session_id": session,
            "transcript_path": str(self.transcript(turns)),
        })

    def test_short_circuits_when_already_continuing(self):
        """Never stack a second block on top of a stop-hook continuation."""
        self.path("broken").write_text("not frontmatter\n", encoding="utf-8")
        proc = self.hook(STOP, payload=self.payload(stop_active=True))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_blocks_on_a_malformed_model(self):
        """A file the index cannot parse is invisible: the model looks empty while the file
        sits there, so this is worth interrupting for."""
        self.path("broken").write_text("not frontmatter at all\n", encoding="utf-8")
        proc = self.hook(STOP, payload=self.payload())
        self.assertEqual(proc.returncode, 0)
        decision = json.loads(proc.stdout)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("malformed", decision["reason"])

    def test_silent_on_a_short_clean_session(self):
        self.create("thing", domain="d")
        proc = self.hook(STOP, payload=self.payload(turns=1))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_stop_hook_does_not_observe_without_opt_in(self):
        self.create("reply-concept", state="familiar", domain="testing")
        self.hook(STOP, payload=self.payload(turns=1))
        time.sleep(0.05)
        self.assertFalse((self.home / "telemetry.jsonl").exists())

    def test_stop_hook_observes_with_explicit_opt_in(self):
        self.create("reply-concept", state="familiar", domain="testing")
        env = self.env(LACONIC_TELEMETRY="1")
        proc = self.hook(STOP, payload=self.payload(turns=1), env=env)
        self.assertEqual(proc.returncode, 0)
        log = self.home / "telemetry.jsonl"
        for _ in range(20):
            if log.exists():
                break
            time.sleep(0.01)
        self.assertTrue(log.exists())

    def test_silent_when_the_model_was_touched_this_session(self):
        self.create("thing", domain="d")
        proc = self.hook(STOP, payload=self.payload(turns=8))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_long_clean_session_without_evidence_is_silent(self):
        self.create("thing", domain="d")
        old = time.time() - 7200
        for p in self.concepts.glob("*.md"):
            os.utime(p, (old, old))
        proc = self.hook(STOP, payload=self.payload(turns=8, session="clean-session"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_silent_without_a_transcript(self):
        proc = self.hook(STOP, payload=json.dumps(
            {"stop_hook_active": False, "session_id": "s", "transcript_path": "/nonexistent"}
        ))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_correction_never_blocks_stop_or_surfaces_as_hook_error(self):
        path = self.transcript(1)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[-2] = json.dumps({
            "type": "user", "message": {"content":
                "Non, ce n'est pas un problème de cache : cet invariant est nécessaire."}
        })
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        payload = json.dumps({
            "stop_hook_active": False, "session_id": "s", "transcript_path": str(path),
        })
        proc = self.hook(STOP, payload=payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_maintenance_continuation_cannot_loop(self):
        path = self.transcript(1)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[-2] = json.dumps({
            "type": "user", "message": {"content": "Actually, preserve the invariant."}
        })
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        proc = self.hook(STOP, payload=json.dumps({
            "stop_hook_active": True, "session_id": "s", "transcript_path": str(path),
        }))
        self.assertEqual(proc.stdout, "")

    def test_stop_only_completes_reconciliation_without_blocking(self):
        self.create("theory", "--kind", "world", domain="testing")
        # UserPromptSubmit begins the private in-turn review.
        routed = self.hook(ROUTE, payload=json.dumps({
            "prompt": "Review the theory", "session_id": "reconcile",
        }))
        self.assertIn("Silent Laconic reconciliation", json.loads(routed.stdout)
                      ["hookSpecificOutput"]["additionalContext"])
        self.assertTrue((self.home / ".reconciliation-pending").exists())
        proc = self.hook(STOP, payload=self.payload(turns=1, session="reconcile"))
        self.assertEqual(proc.stdout, "")
        self.assertTrue((self.home / ".reconciled-at").exists())
        self.assertFalse((self.home / ".reconciliation-pending").exists())

if __name__ == "__main__":
    unittest.main()
