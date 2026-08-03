"""The recorder's CLI contract: what it writes, what it refuses, and what it preserves."""

import subprocess
import sys
import unittest
from unittest import mock

from helpers import RECORD, TOOLS, ModelTestCase, requires_git
import laconic_record


class TestCreate(ModelTestCase):
    def test_creates_schema_correct_file(self):
        self.create("tezos-finality", domain="consensus", evidence="asked what it means")
        self.assertEqual(self.field("tezos-finality", "id"), "tezos-finality")
        self.assertEqual(self.field("tezos-finality", "type"), "concept")
        self.assertEqual(self.field("tezos-finality", "domain"), "consensus")
        self.assertEqual(self.field("tezos-finality", "state"), "exposed")
        self.assertEqual(self.field("tezos-finality", "confidence"), "0.30")

    def test_evidence_is_dated(self):
        self.create("thing", evidence="saw it happen")
        lines = self.evidence_lines("thing")
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^\d{4}-\d{2}-\d{2}: \[term\] saw it happen$")

    def test_body_scaffold_has_both_headings(self):
        self.create("thing")
        self.assertIn("## What the user understands about it", self.read("thing"))
        self.assertIn("## What has not been established", self.read("thing"))

    def test_summary_becomes_the_one_liner(self):
        self.create("thing", "--summary", "Thing: a test concept.")
        self.assertIn("Thing: a test concept.", self.read("thing"))

    def test_records_observing_project(self):
        self.create("thing")
        self.assertIsNotNone(self.field("thing", "projects"))

    def test_caller_supplied_date_prefix_is_stripped(self):
        """The tool owns the date, so a date the caller pasted in is removed rather than
        duplicated -- and it is the tool's date that survives, not the caller's."""
        self.create("thing", evidence="2026-01-01: saw it", state="exposed")
        line = self.evidence_lines("thing")[0]
        self.assertNotIn("2026-01-01", line)
        self.assertRegex(line, r"^\d{4}-\d{2}-\d{2}: \[term\] saw it$")

    def test_rejects_non_kebab_id(self):
        # "-leading" is excluded: argparse claims it as an option before the tool sees it,
        # so it cannot reach the id check. Covered by test_rejects_leading_dash_id.
        for bad in ("Thing", "thing_two", "thing!", "thing space"):
            r = self.record(bad, "--state", "exposed", "--domain", "d", "--evidence", "x")
            self.assertEqual(r.code, 2, f"{bad} should be rejected")
            self.assertIn("kebab-case", r.text)

    def test_rejects_leading_dash_id(self):
        r = self.record("--state", "exposed", "--domain", "d", "--evidence", "x",
                        "--", "-leading")
        self.assertEqual(r.code, 2)
        self.assertIn("kebab-case", r.text)

    def test_rejects_bad_date(self):
        r = self.record(
            "thing", "--state", "exposed", "--domain", "d", "--evidence", "x",
            "--date", "01-01-2026",
        )
        self.assertEqual(r.code, 2)
        self.assertIn("YYYY-MM-DD", r.text)


class TestPromotionLadder(ModelTestCase):
    def test_one_observation_moves_one_step(self):
        # unknown -> familiar is two steps; must be capped at exposed.
        r = self.create("thing", state="familiar")
        self.assertEqual(self.field("thing", "state"), "exposed")
        self.assertIn("capped", r.text)

    def test_verified_needs_two_observations(self):
        self.create("thing", state="familiar")
        r = self.record("thing", "--state", "verified", "--evidence", "productive use")
        self.assertEqual(r.code, 0)
        # One step from exposed, and verified needs a second observation anyway.
        self.assertEqual(self.field("thing", "state"), "familiar")
        self.assertIn("familiar", r.text)

    def test_confirmed_reaches_verified_in_one_step(self):
        self.create("thing", "--confirmed", state="verified", evidence="confirmed outright")
        self.assertEqual(self.field("thing", "state"), "verified")
        self.assertIn("[basis: confirmation]", self.evidence_lines("thing")[0])

    def test_confirmation_basis_reaches_verified_without_legacy_flag(self):
        self.create(
            "thing", "--basis", "confirmation", state="verified",
            evidence="explicitly confirmed mastery",
        )
        self.assertEqual(self.field("thing", "state"), "verified")

    def test_inference_is_logged_but_cannot_promote_or_change_confidence(self):
        self.create("thing", state="exposed")
        before = self.field("thing", "confidence")
        r = self.record(
            "thing", "--state", "verified", "--basis", "inference",
            "--evidence", "did not ask when asking might have been natural",
        )
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.field("thing", "state"), "exposed")
        self.assertEqual(self.field("thing", "confidence"), before)
        self.assertIn("[basis: inference]", self.evidence_lines("thing")[-1])

    def test_inference_may_omit_state_and_preserves_it(self):
        self.create("thing", state="exposed")
        r = self.record("thing", "--basis", "inference", "--evidence", "possibly knew it")
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.field("thing", "state"), "exposed")

    def test_inference_without_state_creates_unknown(self):
        r = self.record(
            "thing", "--domain", "testing", "--basis", "inference",
            "--evidence", "possibly knew it",
        )
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.field("thing", "state"), "unknown")

    def test_inference_cannot_demote(self):
        self.create("thing", "--basis", "confirmation", state="verified")
        self.record(
            "thing", "--state", "unknown", "--basis", "inference",
            "--evidence", "possibly hesitated",
        )
        self.assertEqual(self.field("thing", "state"), "verified")

    def test_inference_cannot_set_confidence(self):
        r = self.record(
            "thing", "--domain", "testing",
            "--basis", "inference", "--confidence", "0.8", "--evidence", "maybe knew it",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("cannot set confidence", r.text)

    def test_inference_does_not_count_toward_verified(self):
        self.create(
            "thing", "--basis", "inference", state="unknown", evidence="might know it"
        )
        self.record("thing", "--state", "verified", "--evidence", "used it directly")
        self.assertEqual(self.field("thing", "state"), "exposed")

    def test_confirmed_rejects_a_conflicting_basis(self):
        r = self.record(
            "thing", "--state", "verified", "--domain", "testing", "--confirmed",
            "--basis", "inference", "--evidence", "contradictory provenance",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("conflicts", r.text)

    def test_two_observations_then_verified(self):
        self.create("thing", state="exposed")
        self.record("thing", "--state", "familiar", "--evidence", "used the term")
        self.record("thing", "--state", "verified", "--evidence", "corrected me on it")
        self.assertEqual(self.field("thing", "state"), "verified")

    def test_demotion_is_immediate(self):
        """Promotion is slow, demotion is fast: a question drops the state at once."""
        self.create("thing", state="exposed")
        self.record("thing", "--state", "familiar", "--evidence", "used it")
        self.assertEqual(self.field("thing", "state"), "familiar")
        self.record("thing", "--state", "exposed", "--evidence", "asked something basic")
        self.assertEqual(self.field("thing", "state"), "exposed")

    def test_confidence_tracks_state(self):
        self.create("thing", state="exposed")
        self.assertEqual(self.field("thing", "confidence"), "0.30")
        self.record("thing", "--state", "familiar", "--evidence", "used it")
        self.assertEqual(self.field("thing", "confidence"), "0.55")

    def test_explicit_confidence_is_clamped(self):
        self.create("thing", "--confidence", "5.0")
        self.assertEqual(self.field("thing", "confidence"), "1.00")


class TestDomainRule(ModelTestCase):
    def test_required_on_create(self):
        r = self.record("thing", "--state", "exposed", "--evidence", "seen")
        self.assertEqual(r.code, 2)
        self.assertIn("--domain is required", r.text)

    def test_refusal_leaves_no_file(self):
        self.record("thing", "--state", "exposed", "--evidence", "seen")
        self.assertFalse(self.path("thing").exists())

    def test_preserved_on_update(self):
        self.create("thing", domain="ocaml")
        r = self.record("thing", "--state", "familiar", "--evidence", "used it")
        self.assertEqual(r.code, 0)
        self.assertEqual(self.field("thing", "domain"), "ocaml")

    def test_changed_when_passed_again(self):
        self.create("thing", domain="ocaml")
        self.record("thing", "--state", "familiar", "--domain", "rust", "--evidence", "x")
        self.assertEqual(self.field("thing", "domain"), "rust")

    def test_rejects_domain_frontmatter_injection(self):
        r = self.record(
            "thing", "--state", "exposed", "--domain", "safe\nstate: verified",
            "--evidence", "seen",
        )
        self.assertEqual(r.code, 2)
        self.assertFalse(self.path("thing").exists())

    def test_exempt_for_distillation(self):
        self.create("thing", domain="ocaml")
        r = self.record("thing", "--not-established", "the gap")
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.field("thing", "domain"), "ocaml")


class TestDistillation(ModelTestCase):
    def test_writes_both_sections(self):
        self.create("thing")
        self.record("thing", "--understands", "grasps it", "--not-established", "the edges")
        self.assertEqual(self.section("thing", "What the user understands about it"), "grasps it")
        self.assertEqual(self.section("thing", "What has not been established"), "the edges")

    def test_replaces_rather_than_appends(self):
        """The sections are a standing distillation, not a second evidence log."""
        self.create("thing")
        self.record("thing", "--not-established", "first")
        self.record("thing", "--not-established", "second")
        gap = self.section("thing", "What has not been established")
        self.assertEqual(gap, "second")
        self.assertNotIn("first", gap)

    def test_needs_no_state_or_evidence(self):
        self.create("thing", state="exposed")
        r = self.record("thing", "--not-established", "the gap")
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.field("thing", "state"), "exposed")

    def test_adds_no_evidence_line(self):
        """A summary is not an observation."""
        self.create("thing")
        before = self.evidence_lines("thing")
        self.record("thing", "--not-established", "the gap")
        self.assertEqual(self.evidence_lines("thing"), before)

    def test_preserves_confidence_and_timestamp(self):
        """Distilling must not reset the staleness clock or discard a tuned confidence."""
        self.create("thing", "--confidence", "0.42", "--date", "2026-01-01")
        self.record("thing", "--not-established", "the gap")
        self.assertEqual(self.field("thing", "confidence"), "0.42")
        self.assertEqual(self.field("thing", "last-updated"), "2026-01-01")

    def test_observation_does_bump_timestamp(self):
        self.create("thing", "--date", "2026-01-01")
        self.record("thing", "--state", "exposed", "--evidence", "again", "--date", "2026-02-02")
        self.assertEqual(self.field("thing", "last-updated"), "2026-02-02")

    def test_refuses_on_nonexistent_concept(self):
        r = self.record("never-seen", "--not-established", "the gap")
        self.assertEqual(r.code, 2)
        self.assertIn("does not exist", r.text)

    def test_nudges_once_evidence_accumulates(self):
        self.create("thing")
        self.record("thing", "--state", "exposed", "--evidence", "two")
        r = self.record("thing", "--state", "exposed", "--evidence", "three")
        self.assertIn("What has not been established", r.text)

    def test_no_nudge_when_gap_already_written(self):
        self.create("thing")
        self.record("thing", "--state", "exposed", "--evidence", "two")
        self.record("thing", "--not-established", "the gap")
        r = self.record("thing", "--state", "exposed", "--evidence", "three")
        self.assertNotIn("no 'What has not been established' section", r.text)

    def test_preserves_hand_written_multiline_body(self):
        self.create("thing")
        self.record("thing", "--understands", "line one\nline two", "--not-established", "gap")
        self.record("thing", "--state", "exposed", "--evidence", "another observation")
        self.assertEqual(
            self.section("thing", "What the user understands about it"), "line one\nline two"
        )


class TestGuards(ModelTestCase):
    def test_evidence_required_without_distillation(self):
        r = self.record("thing", "--state", "exposed", "--domain", "d")
        self.assertNotEqual(r.code, 0)
        self.assertIn("--evidence is required", r.text)

    def test_state_required_with_evidence(self):
        self.create("thing")
        r = self.record("thing", "--evidence", "seen")
        self.assertNotEqual(r.code, 0)
        self.assertIn("--state is required", r.text)

    def test_forget_conflicts_with_recording_flags(self):
        self.create("thing")
        for flag, value in (
            ("--state", "familiar"),
            ("--evidence", "x"),
            ("--understands", "x"),
            ("--not-established", "x"),
            ("--domain", "x"),
            ("--summary", "x"),
        ):
            r = self.record("thing", "--forget", "reason", flag, value)
            self.assertNotEqual(r.code, 0, f"{flag} should conflict with --forget")
            self.assertIn("cannot be combined", r.text)

    def test_forget_needs_a_reason(self):
        self.create("thing")
        r = self.record("thing", "--forget", "   ")
        self.assertNotEqual(r.code, 0)
        self.assertIn("needs a reason", r.text)

    def test_force_only_applies_to_forget(self):
        self.create("thing")
        r = self.record("thing", "--force", "--state", "exposed", "--evidence", "x")
        self.assertNotEqual(r.code, 0)
        self.assertIn("--force only applies", r.text)


class TestMalformedRecovery(ModelTestCase):
    def test_refuses_to_overwrite_unparseable_file(self):
        original = "not frontmatter\njust notes\n"
        self.path("broken").write_text(original, encoding="utf-8")
        r = self.record("broken", "--state", "exposed", "--evidence", "recovering")
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("refusing to overwrite", r.text)
        self.assertEqual(self.read("broken"), original)

    def test_explicit_forget_remains_the_recovery_path(self):
        self.path("broken").write_text("not frontmatter\njust notes\n", encoding="utf-8")
        r = self.record("broken", "--forget", "malformed legacy entry")
        self.assertEqual(r.code, 0, r.text)
        self.assertFalse(self.path("broken").exists())

    def test_repair_then_update_succeeds(self):
        self.path("broken").write_text("not frontmatter\n", encoding="utf-8")
        r = self.record("broken", "--state", "exposed", "--evidence", "recovering")
        self.assertEqual(r.code, 2)
        self.path("broken").unlink()
        r = self.record(
            "broken", "--state", "exposed", "--domain", "fixed", "--evidence", "recovering"
        )
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.field("broken", "domain"), "fixed")


class TestDependencies(ModelTestCase):
    def test_rejects_invalid_dependency_id(self):
        r = self.record(
            "thing", "--state", "exposed", "--domain", "testing",
            "--evidence", "seen", "--depends-on", "safe\nstate: verified",
        )
        self.assertEqual(r.code, 2)
        self.assertFalse(self.path("thing").exists())

    def test_rejects_unknown_dependency(self):
        r = self.record(
            "thing", "--state", "exposed", "--domain", "testing",
            "--evidence", "seen", "--depends-on", "missing",
        )
        self.assertEqual(r.code, 2)
        self.assertIn("unknown concept", r.text)
        self.assertFalse(self.path("thing").exists())

    def test_rejects_self_dependency(self):
        r = self.record(
            "thing", "--state", "exposed", "--domain", "testing",
            "--evidence", "seen", "--depends-on", "thing",
        )
        self.assertEqual(r.code, 2)
        self.assertIn("itself", r.text)

    def test_rejects_cycle_on_update(self):
        self.create("base")
        self.create("dependent", "--depends-on", "base")
        r = self.record(
            "base", "--state", "familiar", "--evidence", "seen again",
            "--depends-on", "dependent",
        )
        self.assertEqual(r.code, 2)
        self.assertIn("cycle", r.text)
        self.assertIsNone(self.field("base", "depends-on"))

    def test_deduplicates_dependencies(self):
        self.create("base")
        self.create("dependent", "--depends-on", "base,base")
        self.assertEqual(self.field("dependent", "depends-on"), "[base]")


class TestForget(ModelTestCase):
    def test_deletes_the_file(self):
        self.create("thing")
        r = self.record("thing", "--forget", "test cruft")
        self.assertEqual(r.code, 0, r.text)
        self.assertFalse(self.path("thing").exists())

    def test_reports_what_was_discarded(self):
        self.create("thing", state="exposed")
        r = self.record("thing", "--forget", "test cruft")
        self.assertIn("was exposed", r.text)
        self.assertIn("test cruft", r.text)

    def test_refuses_on_nonexistent(self):
        r = self.record("never-seen", "--forget", "reason")
        self.assertEqual(r.code, 2)
        self.assertIn("nothing to forget", r.text)

    def test_refuses_when_depended_upon(self):
        self.create("base")
        self.create("dependent", "--depends-on", "base")
        r = self.record("base", "--forget", "reason")
        self.assertEqual(r.code, 2)
        self.assertIn("dependent", r.text)
        self.assertTrue(self.path("base").exists(), "must not delete on refusal")

    def test_force_strips_the_reference(self):
        self.create("base")
        self.create("other")
        self.create("dependent", "--depends-on", "base,other")
        r = self.record("base", "--forget", "reason", "--force")
        self.assertEqual(r.code, 0, r.text)
        self.assertFalse(self.path("base").exists())
        self.assertEqual(self.field("dependent", "depends-on"), "[other]")

    def test_force_drops_the_key_when_it_empties(self):
        """`depends-on: []` would be a lie about the schema; the key should go."""
        self.create("base")
        self.create("dependent", "--depends-on", "base")
        self.record("base", "--forget", "reason", "--force")
        self.assertIsNone(self.field("dependent", "depends-on"))
        self.assertNotIn("depends-on", self.read("dependent"))

    def test_forced_forget_leaves_the_model_lintable(self):
        """A dangling depends-on makes lint error, and stop-check blocks on lint errors."""
        self.create("base")
        self.create("dependent", "--depends-on", "base")
        self.record("base", "--forget", "reason", "--force")
        self.assertEqual(self.lint("--quiet").code, 0, self.lint("--quiet").text)

    def test_finds_dependents_in_unparseable_files(self):
        """A file too malformed to parse must not be able to hide a reference."""
        self.create("base")
        self.path("broken").write_text(
            "garbage header\ndepends-on: [base]\nmore garbage\n", encoding="utf-8"
        )
        r = self.record("base", "--forget", "reason")
        self.assertEqual(r.code, 2)
        self.assertIn("broken", r.text)


@requires_git
class TestAuditability(ModelTestCase):
    def test_every_write_is_a_commit(self):
        self.create("thing")
        self.record("thing", "--state", "exposed", "--evidence", "again")
        self.assertGreaterEqual(len(self.git_log()), 2)

    def test_commit_message_carries_the_transition(self):
        self.create("thing", state="exposed")
        self.assertTrue(
            any("unknown -> exposed" in m for m in self.git_log()), self.git_log()
        )

    def test_forget_records_its_reason(self):
        self.create("thing")
        self.record("thing", "--forget", "backbrief test pollution")
        self.assertTrue(
            any("backbrief test pollution" in m for m in self.git_log()), self.git_log()
        )

    def test_forget_is_revertible(self):
        self.create("thing", evidence="the original observation")
        self.record("thing", "--forget", "mistake")
        self.assertFalse(self.path("thing").exists())
        subprocess.run(
            [
                "git", "-c", "user.name=laconic",
                "-c", "user.email=laconic@localhost",
                "revert", "--no-edit", "HEAD",
            ],
            cwd=str(self.home), capture_output=True, check=True,
        )
        self.assertTrue(self.path("thing").exists())
        self.assertIn("the original observation", self.read("thing"))

    def test_distillation_is_committed_distinctly(self):
        self.create("thing")
        self.record("thing", "--not-established", "the gap")
        self.assertTrue(any("distilled" in m for m in self.git_log()), self.git_log())


class TestEvidenceHygiene(ModelTestCase):
    """Evidence is committed and synced, so credentials in it are already disclosed."""

    def test_flags_a_private_key(self):
        self.create("thing", evidence="pasted -----BEGIN RSA PRIVATE KEY----- into the config")
        r = self.lint()
        self.assertEqual(r.code, 1)
        self.assertIn("private key", r.text)

    def test_flags_an_inline_password(self):
        self.create("thing", evidence="set password: hunter2 in the deploy script")
        self.assertEqual(self.lint().code, 1)

    def test_flags_a_github_token(self):
        self.create("thing", evidence="used ghp_" + "a" * 36 + " for the push")
        self.assertEqual(self.lint().code, 1)

    def test_does_not_cry_wolf_on_ordinary_evidence(self):
        """A check people learn to ignore is worse than no check."""
        benign = (
            "correctly reasoned about the repayment precondition",
            "asked how the commit hash 3f8a9c2b1d4e5f6a7b8c9d0e1f2a3b4c is derived",
            "discussed api-key rotation policy without naming one",
            "explained that secrets live in the GNOME keyring",
        )
        for i, evidence in enumerate(benign):
            self.create(f"thing-{i}", evidence=evidence)
        r = self.lint()
        self.assertEqual(r.code, 0, f"false positive among {benign}: {r.text}")

    def test_checks_the_prose_sections_too(self):
        self.create("thing")
        self.record("thing", "--not-established", "whether AKIA" + "A" * 16 + " still works")
        self.assertEqual(self.lint().code, 1)


@requires_git
class TestScratchFilesStayLocal(ModelTestCase):
    """Session markers, lint stamps and the lock are per-machine. git_commit stages with
    `git add -A`, so anything unignored syncs to the other machine."""

    def test_gitignore_covers_the_scratch_files(self):
        self.create("thing")
        ignored = (self.home / ".gitignore").read_text(encoding="utf-8").split()
        for pattern in (".lint-ok", ".nudged-*", ".session-*", "laconic.lock"):
            self.assertIn(pattern, ignored)

    def test_patterns_reach_a_model_that_already_exists(self):
        """A pattern added after a model was created must still land, or the first symptom
        is one machine's transient state showing up on the other."""
        self.create("first")
        (self.home / ".gitignore").write_text(".lint-ok\n", encoding="utf-8")
        self.create("second")
        ignored = (self.home / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn(".session-*", ignored)

    def test_user_additions_are_preserved(self):
        self.create("first")
        path = self.home / ".gitignore"
        path.write_text(path.read_text(encoding="utf-8") + "my-own-thing\n", encoding="utf-8")
        self.create("second")
        self.assertIn("my-own-thing", path.read_text(encoding="utf-8").split())

    def test_markers_are_not_committed(self):
        self.create("thing")
        (self.home / ".session-abc").touch()
        (self.home / ".nudged-abc").touch()
        self.record("thing", "--state", "exposed", "--evidence", "again")
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=str(self.home),
            capture_output=True, text=True, check=False,
        ).stdout
        self.assertNotIn(".session-abc", tracked)
        self.assertNotIn(".nudged-abc", tracked)


class TestGitIsOptional(ModelTestCase):
    def test_recording_works_without_git(self):
        """Versioning is a bonus, not a dependency -- a bare machine must still record."""
        env = self.env(PATH="/nonexistent")
        r = self.record("thing", "--state", "exposed", "--domain", "d", "--evidence", "x", env=env)
        self.assertEqual(r.code, 0, r.text)
        self.assertTrue(self.path("thing").exists())
        self.assertFalse((self.home / ".git").exists())


@requires_git
class TestPushConsent(ModelTestCase):
    def test_no_remote_means_no_push(self):
        self.create("thing")
        with mock.patch.dict("os.environ", {"LACONIC_PUSH": "1"}):
            self.assertIsNone(laconic_record.push_command(self.home))

    def test_remote_without_explicit_flag_does_not_push(self):
        self.create("thing")
        subprocess.run(
            ["git", "remote", "add", "origin", "ssh://example.invalid/model.git"],
            cwd=self.home,
            check=True,
        )
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(laconic_record.push_command(self.home))

    def test_flag_and_origin_enable_branch_agnostic_push(self):
        self.create("thing")
        subprocess.run(
            ["git", "remote", "add", "origin", "ssh://example.invalid/model.git"],
            cwd=self.home,
            check=True,
        )
        with mock.patch.dict("os.environ", {"LACONIC_PUSH": "1"}):
            command = laconic_record.push_command(self.home)
        self.assertEqual(
            command,
            ["git", "push", "--quiet", "origin", "HEAD"],
        )


class TestConcurrency(ModelTestCase):
    def test_parallel_records_do_not_lose_observations(self):
        """laconic_record.py takes the flock laconic-sync.sh uses; concurrent writes to the
        same concept must serialize rather than clobber each other."""
        self.create("thing")
        procs = [
            subprocess.Popen(
                [sys.executable, str(RECORD), "thing", "--state", "exposed",
                 "--evidence", f"parallel observation {i}"],
                env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
            for i in range(5)
        ]
        failures = []
        for p in procs:
            err = p.communicate()[1]
            if p.returncode != 0:
                failures.append(err)
        self.assertEqual(failures, [])
        lines = self.evidence_lines("thing")
        self.assertEqual(len(lines), 6, f"lost writes: {lines}")


class TestSpool(ModelTestCase):
    """What happens when the lock is not free within LOCK_WAIT_SECONDS.

    laconic-sync.sh holds that lock across a network fetch and merge, so exceeding the wait
    is routine. An earlier version proceeded unlocked and silently dropped observations.
    """

    def hold_lock(self):
        """Take the model lock the way laconic-sync.sh does, and keep it until released."""
        import fcntl

        self.record("seed", "--state", "exposed", "--domain", "testing", "--evidence", "s")
        git_dir = self.home / ".git"
        lock_path = (git_dir if git_dir.is_dir() else self.home) / "laconic.lock"
        handle = open(lock_path, "w")
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle

    def spooled(self):
        directory = self.home / "spool"
        return sorted(p.name for p in directory.glob("*.json")) if directory.is_dir() else []

    def record_fast(self, *args):
        """Record with a 1s lock wait, so a contended test does not sit for the full 15."""
        return self.record(*args, env=self.env(LACONIC_LOCK_WAIT="1"))

    def test_busy_lock_spools_instead_of_losing_the_observation(self):
        handle = self.hold_lock()
        try:
            r = self.record_fast("thing", "--state", "exposed", "--domain", "testing",
                                 "--evidence", "observed while busy")
            self.assertEqual(r.code, 0, r.text)
            self.assertIn("spooled", r.text)
            self.assertEqual(len(self.spooled()), 1, "observation was not parked")
        finally:
            handle.close()

    def test_next_record_folds_in_the_spool(self):
        handle = self.hold_lock()
        try:
            self.record_fast("thing", "--state", "exposed", "--domain", "testing",
                             "--evidence", "parked one")
        finally:
            handle.close()
        r = self.record("thing", "--state", "exposed", "--evidence", "the live one")
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("folded in 1", r.text)
        self.assertEqual(self.spooled(), [], "spool not drained")
        lines = self.evidence_lines("thing")
        self.assertTrue(any("parked one" in ln for ln in lines), f"lost the parked entry: {lines}")
        self.assertTrue(any("the live one" in ln for ln in lines), lines)

    def test_spooled_entry_keeps_its_own_date(self):
        """An observation parked tonight and drained tomorrow must keep the date it was
        observed, or the staleness clock lies about when the evidence appeared."""
        handle = self.hold_lock()
        try:
            self.record_fast("thing", "--state", "exposed", "--domain", "testing",
                             "--evidence", "old news", "--date", "2020-01-01")
        finally:
            handle.close()
        self.record("thing", "--state", "exposed", "--evidence", "today")
        lines = self.evidence_lines("thing")
        self.assertTrue(any(ln.startswith("2020-01-01: [term] old news") for ln in lines), lines)

    def test_a_poisoned_entry_is_set_aside_not_retried_forever(self):
        directory = self.home / "spool"
        directory.mkdir(parents=True)
        (directory / "20200101T000000000000-1.json").write_text("{not json", encoding="utf-8")
        self.create("thing")
        self.assertEqual(self.spooled(), [], "bad entry left in the spool")
        self.assertTrue(list(directory.glob("*.bad")), "bad entry was not set aside")

    def test_forget_refuses_rather_than_spooling(self):
        """Parking a deletion to run later, against a model that has moved on, is worse
        than failing now."""
        self.create("doomed")
        handle = self.hold_lock()
        try:
            r = self.record_fast("doomed", "--forget", "no longer true")
            self.assertEqual(r.code, 1, r.text)
            self.assertIn("could not acquire", r.text)
            self.assertEqual(self.spooled(), [], "a forget must never be spooled")
        finally:
            handle.close()
        self.assertTrue(self.path("doomed").exists(), "concept deleted despite the failure")

    @requires_git
    def test_drain_precedes_a_forget(self):
        """A spooled observation is older than the forget; replaying it afterwards would
        resurrect the concept."""
        self.create("doomed")
        handle = self.hold_lock()
        try:
            self.record_fast("doomed", "--state", "exposed", "--evidence", "parked")
        finally:
            handle.close()
        r = self.record("doomed", "--forget", "decided against it")
        self.assertEqual(r.code, 0, r.text)
        self.assertFalse(self.path("doomed").exists(), "forget did not take effect")
        self.assertEqual(self.spooled(), [], "spool survived the forget")

    def test_spooled_distillation_replays(self):
        self.create("thing")
        self.record("thing", "--state", "exposed", "--evidence", "two")
        handle = self.hold_lock()
        try:
            self.record_fast("thing", "--not-established", "the parked gap")
        finally:
            handle.close()
        self.record("thing", "--state", "exposed", "--evidence", "three")
        self.assertEqual(self.section("thing", "What has not been established"),
                         "the parked gap")



class TestEvidenceKinds(ModelTestCase):
    """Naur's three criteria as evidence classes, alongside the term-use laconic had."""

    def kinds(self, cid):
        import re
        return re.findall(r"^  - \S+: \[(\w+)\]", self.read(cid), re.M)

    def test_defaults_to_term(self):
        self.create("thing")
        self.assertEqual(self.kinds("thing"), ["term"])

    def test_records_a_theory_kind(self):
        self.create("thing", "--kind", "modification",
                    evidence="proposed a change that fitted the existing design")
        self.assertEqual(self.kinds("thing"), ["modification"])

    def test_rejects_an_unknown_kind(self):
        r = self.record("thing", "--state", "exposed", "--domain", "testing",
                        "--evidence", "x", "--kind", "vibes")
        self.assertNotEqual(r.code, 0)
        self.assertIn("invalid choice", r.text)

    def test_does_not_double_mark(self):
        """A caller who writes the marker by hand must not end up with two."""
        self.create("thing", "--kind", "world", evidence="[world] explained the mapping")
        self.assertEqual(self.kinds("thing"), ["world"])
        self.assertNotIn("[world] [world]", self.read("thing"))

    def test_lint_errors_on_a_corrupted_kind(self):
        self.create("thing")
        text = self.read("thing").replace("[term]", "[nonsense]")
        self.path("thing").write_text(text, encoding="utf-8")
        r = self.lint()
        self.assertEqual(r.code, 1, r.text)
        self.assertIn("unknown evidence kind", r.text)

    def test_lint_errors_on_a_corrupted_basis(self):
        self.create("thing", "--basis", "inference", state="unknown")
        text = self.read("thing").replace("[basis: inference]", "[basis: hearsay]")
        self.path("thing").write_text(text, encoding="utf-8")
        r = self.lint()
        self.assertEqual(r.code, 1, r.text)
        self.assertIn("unknown evidence basis", r.text)

    def test_unmarked_evidence_stays_unclassified(self):
        """Legacy lines predate the distinction; calling them `term` would fabricate a
        baseline for the measurement the kinds exist to make."""
        self.create("thing")
        text = self.read("thing").replace("[term] ", "")
        self.path("thing").write_text(text, encoding="utf-8")
        r = self.run_tool(TOOLS / "laconic_stats.py", "--evidence", env=self.env())
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("unclassified", r.text)


class TestCapabilities(ModelTestCase):
    def test_inference_cannot_establish_a_capability(self):
        r = self.record(
            "thing", "--state", "unknown", "--domain", "testing",
            "--kind", "world", "--basis", "inference", "--evidence", "might map it",
            "--capability", "Can map it",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("cannot establish", r.text)

    def test_capability_from_rejects_inferred_evidence(self):
        self.create(
            "thing", "--kind", "world", "--basis", "inference", state="unknown",
            evidence="might map the system",
        )
        r = self.record(
            "thing", "--capability-from", "1", "--capability", "Can map the system",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("inferred evidence", r.text)

    def test_distils_an_existing_strong_observation_without_duplicating_it(self):
        self.create(
            "thing", "--kind", "justification", "--date", "2026-07-14",
            evidence="derived the boundary from the failure mode",
        )
        before = self.evidence_lines("thing")
        r = self.record(
            "thing", "--capability-from", "1",
            "--capability", "Can justify the boundary from the failure mode",
        )
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.evidence_lines("thing"), before)
        section = self.section("thing", "Established capabilities")
        self.assertIn("[justification]", section)
        self.assertIn("(evidence: 2026-07-14)", section)
        self.assertIn("[source-evidence: 1]", section)

    def test_capability_from_rejects_weak_or_missing_observations(self):
        self.create("thing", evidence="used the term")
        weak = self.record("thing", "--capability-from", "1", "--capability", "Can use it")
        self.assertEqual(weak.code, 2, weak.text)
        self.assertIn("not a strong", weak.text)
        missing = self.record("thing", "--capability-from", "2", "--capability", "Can use it")
        self.assertEqual(missing.code, 2, missing.text)
        self.assertIn("exceeds", missing.text)

    def test_capability_from_cannot_add_new_evidence(self):
        self.create("thing", "--kind", "world", evidence="mapped the system")
        r = self.record(
            "thing", "--state", "familiar", "--evidence", "mapped it again",
            "--kind", "world", "--capability-from", "1", "--capability", "Can map it",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("cannot be combined", r.text)

    def test_records_a_capability_with_its_evidence_date(self):
        self.create(
            "thing", "--kind", "justification",
            "--capability", "Can explain why the boundary exists",
            "--date", "2026-08-03",
            evidence="explained the boundary from the failure mode",
        )
        text = self.section("thing", "Established capabilities")
        self.assertEqual(
            text,
            "- [justification] Can explain why the boundary exists "
            "(evidence: 2026-08-03) [scope: project] "
            "[id: can-explain-why-the-boundary-exists]",
        )
        injected = self.index("--cwd", str(TOOLS.parent))
        self.assertEqual(injected.code, 0, injected.text)
        self.assertIn(
            "thing/can-explain-why-the-boundary-exists [justification, project]: "
            "Can explain why the boundary exists",
            injected.text,
        )

    def test_capability_requires_strong_evidence(self):
        r = self.record(
            "thing", "--state", "exposed", "--domain", "testing",
            "--evidence", "used a term", "--capability", "Can apply it",
        )
        self.assertNotEqual(r.code, 0)
        self.assertIn("requires --kind", r.text)

    def test_capability_requires_same_call_evidence(self):
        self.create("thing")
        r = self.record("thing", "--capability", "Can apply it", "--kind", "world")
        self.assertNotEqual(r.code, 0)
        self.assertIn("requires --evidence", r.text)

    def test_repeated_claim_replaces_its_evidence_date(self):
        self.create(
            "thing", "--kind", "world", "--capability", "Can map it to the domain",
            "--date", "2026-07-01", evidence="mapped it once",
        )
        self.record(
            "thing", "--state", "familiar", "--kind", "world",
            "--capability", "Can map it to the domain", "--date", "2026-08-03",
            "--evidence", "mapped it again",
        )
        section = self.section("thing", "Established capabilities")
        self.assertEqual(section.count("Can map it to the domain"), 1)
        self.assertIn("evidence: 2026-08-03", section)

    def test_records_scope_and_condition(self):
        self.create(
            "thing", "--kind", "modification", "--capability", "Can change the scheduler",
            "--capability-scope", "domain", "--capability-condition", "the queue remains FIFO",
            evidence="changed the scheduler while preserving FIFO order",
        )
        section = self.section("thing", "Established capabilities")
        self.assertIn("[scope: domain]", section)
        self.assertIn("[when: the queue remains FIFO]", section)

    def test_scope_and_condition_require_a_capability(self):
        self.create("thing")
        r = self.record("thing", "--understands", "summary", "--capability-scope", "general")
        self.assertNotEqual(r.code, 0)
        self.assertIn("require --capability", r.text)

    def test_lint_rejects_a_capability_without_matching_evidence(self):
        self.create("thing")
        text = self.read("thing").replace(
            "## Established capabilities\n\n",
            "## Established capabilities\n"
            "- [world] Can map it (evidence: 2026-08-03)\n\n",
        )
        self.path("thing").write_text(text, encoding="utf-8")
        r = self.lint()
        self.assertEqual(r.code, 1, r.text)
        self.assertIn("no matching evidence", r.text)

    def test_pre_capability_spool_entry_still_replays(self):
        import argparse
        import os
        import laconic_record

        legacy = argparse.Namespace(
            concept_id="legacy", state="exposed", evidence="older observation",
            kind="term", domain="testing", confidence=None, depends_on=None,
            summary=None, understands=None, not_established=None, confirmed=False,
            forget=None, force=False, date="2026-07-01",
        )
        with mock.patch.dict(os.environ, self.env()):
            laconic_record.ensure_repo(self.home)
            self.assertEqual(laconic_record.apply_record(legacy, "2026-07-01", quiet=True), 0)
        self.assertTrue(self.path("legacy").exists())

    def test_records_a_capability_prerequisite(self):
        self.create(
            "base", "--kind", "world", "--capability", "Can establish the base",
            "--capability-id", "base", evidence="established the base",
        )
        self.create(
            "advanced", "--kind", "modification", "--capability", "Can modify advanced",
            "--capability-id", "advanced", "--capability-requires", "base/base",
            evidence="modified advanced while relying on the base",
        )
        self.assertIn("[requires: base/base]", self.section(
            "advanced", "Established capabilities"
        ))

    def test_refuses_an_unknown_relation_target(self):
        r = self.record(
            "advanced", "--state", "exposed", "--domain", "testing",
            "--kind", "modification", "--evidence", "changed it",
            "--capability", "Can change it", "--capability-requires", "missing/base",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("unknown target", r.text)
        self.assertFalse(self.path("advanced").exists())

    def test_refuses_a_capability_prerequisite_cycle(self):
        self.create(
            "a", "--kind", "world", "--capability", "Can do A",
            "--capability-id", "a", evidence="did A",
        )
        self.create(
            "b", "--kind", "world", "--capability", "Can do B",
            "--capability-id", "b", "--capability-requires", "a/a", evidence="did B via A",
        )
        r = self.record(
            "a", "--state", "familiar", "--kind", "world", "--evidence", "did A again",
            "--capability", "Can do A", "--capability-id", "a",
            "--capability-requires", "b/b",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("create a cycle", r.text)

    def test_lint_rejects_a_dangling_capability_relation(self):
        self.create(
            "base", "--kind", "world", "--capability", "Can establish the base",
            "--capability-id", "base", evidence="established the base",
        )
        text = self.read("base").replace(
            "[id: base]", "[id: base] [requires: missing/base]"
        )
        self.path("base").write_text(text, encoding="utf-8")
        r = self.lint()
        self.assertEqual(r.code, 1, r.text)
        self.assertIn("does not exist", r.text)

    def test_refuses_reusing_an_id_for_a_different_claim(self):
        self.create(
            "thing", "--kind", "world", "--capability", "Can do the first thing",
            "--capability-id", "stable", evidence="did the first thing",
        )
        r = self.record(
            "thing", "--state", "familiar", "--kind", "world",
            "--capability", "Can do a different thing", "--capability-id", "stable",
            "--evidence", "did something different",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("already names a different claim", r.text)

    def test_refuses_multiple_relation_types_to_the_same_target(self):
        self.create(
            "base", "--kind", "world", "--capability", "Can do base",
            "--capability-id", "base", evidence="did base",
        )
        r = self.record(
            "next", "--state", "exposed", "--domain", "testing", "--kind", "world",
            "--capability", "Can do next", "--evidence", "did next",
            "--capability-requires", "base/base", "--capability-contradicts", "base/base",
        )
        self.assertEqual(r.code, 2, r.text)
        self.assertIn("multiple relation types", r.text)

    def test_records_a_capability_expiry(self):
        self.create(
            "api", "--kind", "world", "--capability", "Can use API v1",
            "--capability-id", "api-v1", "--capability-valid-until", "2026-12-31",
            "--date", "2026-08-03", evidence="used API v1",
        )
        self.assertIn("[valid-until: 2026-12-31]", self.section(
            "api", "Established capabilities"
        ))

    def test_retraction_preserves_history_but_removes_injection(self):
        self.create(
            "api", "--kind", "world", "--capability", "Can use API v1",
            "--capability-id", "api-v1", "--date", "2026-08-03", evidence="used API v1",
        )
        evidence = self.evidence_lines("api")
        r = self.record(
            "api", "--retract-capability", "api-v1", "--reason", "API v1 was removed",
            "--date", "2026-08-04",
        )
        self.assertEqual(r.code, 0, r.text)
        self.assertEqual(self.evidence_lines("api"), evidence)
        section = self.section("api", "Established capabilities")
        self.assertIn("[retracted: 2026-08-04]", section)
        self.assertIn("[retraction-reason: API v1 was removed]", section)
        injected = self.index("--cwd", str(TOOLS.parent))
        self.assertNotIn("api/api-v1", injected.text)

    def test_new_evidence_reactivates_a_retracted_capability(self):
        self.create(
            "api", "--kind", "world", "--capability", "Can use API v1",
            "--capability-id", "api-v1", evidence="used it",
        )
        self.record("api", "--retract-capability", "api-v1", "--reason", "temporarily gone")
        self.record(
            "api", "--state", "familiar", "--kind", "world", "--evidence", "used it again",
            "--capability", "Can use API v1", "--capability-id", "api-v1",
        )
        section = self.section("api", "Established capabilities")
        self.assertNotIn("retracted:", section)
        self.assertEqual(section.count("[id: api-v1]"), 1)

    def test_retraction_requires_a_reason(self):
        self.create("thing")
        r = self.record("thing", "--retract-capability", "anything")
        self.assertNotEqual(r.code, 0)
        self.assertIn("requires --reason", r.text)

if __name__ == "__main__":
    unittest.main()
