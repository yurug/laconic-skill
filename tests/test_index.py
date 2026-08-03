"""Decay, relevance, gap selection and the injection budget.

These are import-level tests: the functions are pure enough to call directly, and the
injected text is what actually reaches a session, so it is worth asserting on precisely.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ModelTestCase

import laconic_index as L


class TestAtomicWrite(unittest.TestCase):
    def test_replaces_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.md"
            path.write_text("old", encoding="utf-8")
            L.atomic_write_text(path, "new\ncomplete")
            self.assertEqual(path.read_text(encoding="utf-8"), "new\ncomplete")

    def test_failed_replace_preserves_original_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.md"
            path.write_text("original", encoding="utf-8")
            with mock.patch.object(L.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    L.atomic_write_text(path, "partial replacement")
            self.assertEqual(path.read_text(encoding="utf-8"), "original")
            self.assertEqual(sorted(Path(directory).iterdir()), [path])


def concept(cid, state="exposed", domain="testing", observations=1, gap="", projects=(),
            last_updated="2026-07-28", capabilities=(), strong_evidence=()):
    return {
        "id": cid,
        "state": state,
        "domain": domain,
        "observations": observations,
        "gap": gap,
        "projects": list(projects),
        "last-updated": last_updated,
        "capabilities": list(capabilities),
        "strong_evidence": list(strong_evidence),
    }


class TestDecay(unittest.TestCase):
    """The table in docs/knowledge-model.md, asserted."""

    def test_verified_never_decays(self):
        self.assertEqual(L.effective_state("verified", 10_000, 2), "verified")

    def test_familiar_softens_after_the_threshold(self):
        self.assertEqual(L.effective_state("familiar", L.FAMILIAR_DECAY_DAYS + 1, 2), "exposed")

    def test_familiar_survives_up_to_the_threshold(self):
        self.assertEqual(L.effective_state("familiar", L.FAMILIAR_DECAY_DAYS, 2), "familiar")

    def test_thin_exposed_drops_after_the_threshold(self):
        self.assertIsNone(L.effective_state("exposed", L.EXPOSED_DROP_DAYS + 1, 1))

    def test_thin_exposed_survives_up_to_the_threshold(self):
        self.assertEqual(L.effective_state("exposed", L.EXPOSED_DROP_DAYS, 1), "exposed")

    def test_well_evidenced_exposed_never_drops(self):
        self.assertEqual(L.effective_state("exposed", 10_000, 2), "exposed")

    def test_unknown_persists(self):
        self.assertEqual(L.effective_state("unknown", 10_000, 0), "unknown")

    def test_thin_familiar_fades_all_the_way_out(self):
        """Softening then dropping must chain, or a thinly-evidenced familiar concept would
        rest at exposed forever."""
        self.assertIsNone(L.effective_state("familiar", 10_000, 1))

    def test_missing_date_is_no_information_not_staleness(self):
        self.assertEqual(L.effective_state("familiar", None, 1), "familiar")
        self.assertEqual(L.effective_state("exposed", None, 1), "exposed")

    def test_decay_threshold_matches_the_lint_warning(self):
        """Docs promise these agree; drift would make the lint warn about something the
        injection had not yet acted on, or vice versa."""
        from laconic_lint import STALE_DAYS

        self.assertEqual(L.FAMILIAR_DECAY_DAYS, STALE_DAYS)


class TestRelevance(unittest.TestCase):
    def test_session_inside_project(self):
        c = concept("x", projects=["/home/y/work/proj"])
        self.assertTrue(L.is_relevant(c, "/home/y/work/proj/src"))

    def test_exact_match(self):
        c = concept("x", projects=["/home/y/work/proj"])
        self.assertTrue(L.is_relevant(c, "/home/y/work/proj"))

    def test_broad_session_does_not_claim_every_child_project(self):
        c = concept("x", projects=["/home/y/work/proj"])
        self.assertFalse(L.is_relevant(c, "/home/y/work"))

    def test_unrelated(self):
        c = concept("x", projects=["/home/y/work/proj"])
        self.assertFalse(L.is_relevant(c, "/home/y/other"))

    def test_no_cwd_means_nothing_is_relevant(self):
        self.assertFalse(L.is_relevant(concept("x", projects=["/a"]), None))

    def test_sibling_prefix_is_not_a_match(self):
        """/a/proj must not match /a/proj-two on a bare string prefix."""
        c = concept("x", projects=["/home/y/proj"])
        self.assertFalse(L.is_relevant(c, "/home/y/proj-two"))


class TestGapSelection(unittest.TestCase):
    def test_requires_accumulated_evidence(self):
        thin = concept("thin", gap="a gap", observations=L.SUMMARY_AFTER - 1)
        self.assertEqual(L.select_gaps([thin], None), [])

    def test_requires_gap_text(self):
        silent = concept("silent", gap="", observations=5)
        self.assertEqual(L.select_gaps([silent], None), [])

    def test_admits_qualifying_concept(self):
        ok = concept("ok", gap="a gap", observations=L.SUMMARY_AFTER)
        self.assertEqual([c["id"] for c in L.select_gaps([ok], None)], ["ok"])

    def test_ranks_contradiction_first(self):
        """A gap on a verified concept contradicts 'use freely' -- the one thing the state
        alone cannot express -- so it outranks a gap on an exposed one."""
        cs = [
            concept("low", state="exposed", gap="g", observations=3),
            concept("high", state="verified", gap="g", observations=3),
            concept("mid", state="familiar", gap="g", observations=3),
        ]
        self.assertEqual([c["id"] for c in L.select_gaps(cs, None)], ["high", "mid", "low"])

    def test_relevance_outranks_state(self):
        cs = [
            concept("elsewhere", state="verified", gap="g", observations=3),
            concept("here", state="exposed", gap="g", observations=3, projects=["/p"]),
        ]
        self.assertEqual([c["id"] for c in L.select_gaps(cs, "/p")][0], "here")

    def test_ties_break_on_id_for_stable_output(self):
        cs = [
            concept("b", state="familiar", gap="g", observations=3),
            concept("a", state="familiar", gap="g", observations=3),
        ]
        self.assertEqual([c["id"] for c in L.select_gaps(cs, None)], ["a", "b"])


class TestGapRendering(unittest.TestCase):
    def test_empty_renders_nothing(self):
        self.assertEqual(L.render_gaps([]), "")

    def test_truncates_a_long_gap(self):
        long_gap = "word " * 200
        out = L.render_gaps([concept("x", gap=long_gap, observations=3)])
        self.assertIn("…", out)
        self.assertLess(len(out), len(long_gap))

    def test_respects_the_section_budget(self):
        cs = [concept(f"c{i}", gap="g " * 80, observations=3) for i in range(10)]
        out = L.render_gaps(cs)
        entry_chars = sum(len(ln) for ln in out.splitlines() if ln.startswith("- c"))
        self.assertLessEqual(entry_chars, L.GAP_BUDGET)

    def test_respects_the_count_limit(self):
        cs = [concept(f"c{i}", gap="g", observations=3) for i in range(L.GAP_LIMIT + 4)]
        out = L.render_gaps(cs)
        shown = [ln for ln in out.splitlines() if ln.startswith("- c")]
        self.assertLessEqual(len(shown), L.GAP_LIMIT)

    def test_discloses_everything_it_dropped(self):
        """Silent truncation would make a partial gap block read as complete."""
        n = L.GAP_LIMIT + 4
        cs = [concept(f"c{i}", gap="g", observations=3) for i in range(n)]
        out = L.render_gaps(cs)
        shown = len([ln for ln in out.splitlines() if ln.startswith("- c")])
        self.assertIn(f"+{n - shown} more", out)

    def test_singular_and_plural_agree(self):
        one_over = [concept(f"c{i}", gap="g " * 90, observations=3) for i in range(2)]
        out = L.render_gaps(one_over)
        if "+1 more" in out:
            self.assertIn("+1 more gap ", out)
            self.assertNotIn("+1 more gaps", out)


class TestCapabilityRendering(unittest.TestCase):
    def capability(self, kind, claim, scope="general", condition="", capability_id=None,
                   requires=(), supersedes=(), contradicts=(), valid_until="",
                   retracted="", retraction_reason=""):
        return {"kind": kind, "claim": claim, "date": "2026-07-28",
                "scope": scope, "condition": condition,
                "capability_id": capability_id or L.capability_id_from_claim(claim),
                "requires": list(requires), "supersedes": list(supersedes),
                "contradicts": list(contradicts), "valid_until": valid_until,
                "retracted": retracted, "retraction_reason": retraction_reason}

    def test_injects_demonstrated_ability(self):
        c = concept("design", capabilities=[self.capability(
            "justification", "Can explain why the boundary exists"
        )])
        out = L.render([c])
        self.assertIn("Established capabilities", out)
        self.assertIn(
            "design/can-explain-why-the-boundary-exists [justification, general]",
            out,
        )

    def test_project_relevance_outranks_kind(self):
        elsewhere = concept("elsewhere", projects=["/other"], capabilities=[
            self.capability("modification", "Can modify the unrelated system", "project")
        ])
        here = concept("here", projects=["/project"], capabilities=[
            self.capability("world", "Can map this system to its domain", "project")
        ])
        selected = L.select_capabilities([elsewhere, here], "/project")
        self.assertEqual(selected[0]["id"], "here")

    def test_capability_block_is_bounded_and_discloses_drops(self):
        cs = [concept(f"c{i}", capabilities=[self.capability(
            "world", "Can explain " + "detail " * 40
        )]) for i in range(L.CAPABILITY_LIMIT + 3)]
        out = L.render_capabilities(L.select_capabilities(cs, None))
        shown = [line for line in out.splitlines() if line.startswith("- c")]
        self.assertLessEqual(len(shown), L.CAPABILITY_LIMIT)
        self.assertIn("more capabilities over budget", out)

    def test_legacy_concept_without_capabilities_still_renders(self):
        out = L.render([concept("legacy")])
        self.assertIn("legacy", out)
        self.assertNotIn("Established capabilities", out)

    def test_project_capability_does_not_transfer_to_another_project(self):
        c = concept("local", projects=["/project-a"], capabilities=[
            self.capability("world", "Can apply the local mechanism", "project")
        ])
        self.assertEqual(L.select_capabilities([c], "/project-b"), [])

    def test_condition_reaches_the_injection(self):
        c = concept("conditional", capabilities=[self.capability(
            "modification", "Can change the scheduler", condition="the queue remains FIFO"
        )])
        out = L.render([c])
        self.assertIn("when the queue remains FIFO", out)

    def test_old_capability_line_defaults_to_project_scope(self):
        body = ("## Established capabilities\n"
                "- [world] Can map it (evidence: 2026-07-28)\n")
        parsed = L.parse_capabilities(body)
        self.assertEqual(parsed[0]["scope"], "project")
        self.assertEqual(parsed[0]["condition"], "")

    def test_missing_active_prerequisite_suppresses_dependent_capability(self):
        prerequisite = concept("base", projects=["/elsewhere"], capabilities=[
            self.capability("world", "Can establish the base", "project", capability_id="base")
        ])
        dependent = concept("advanced", capabilities=[self.capability(
            "modification", "Can change the advanced system", capability_id="advanced",
            requires=["base/base"],
        )])
        selected = L.select_capabilities([prerequisite, dependent], "/here")
        self.assertEqual(selected, [])

    def test_active_superseder_removes_replaced_capability(self):
        old = concept("model", capabilities=[self.capability(
            "world", "Can use the old model", capability_id="old"
        )])
        new = concept("model", capabilities=[self.capability(
            "modification", "Can use the new model", capability_id="new",
            supersedes=["model/old"],
        )])
        selected = L.select_capabilities([old, new], None)
        self.assertEqual([item["capability_id"] for item in selected], ["new"])

    def test_contradiction_is_visible(self):
        a = concept("model", capabilities=[self.capability(
            "world", "Can reason under model A", capability_id="a",
            contradicts=["model/b"],
        )])
        b = concept("model", capabilities=[self.capability(
            "world", "Can reason under model B", capability_id="b",
        )])
        out = L.render([a, b])
        self.assertIn("contradicts model/b", out)

    def test_expired_capability_is_not_selected(self):
        import datetime

        c = concept("old", capabilities=[self.capability(
            "world", "Can use the old API", valid_until="2026-07-31"
        )])
        self.assertEqual(L.select_capabilities(
            [c], None, datetime.date(2026, 8, 1)
        ), [])

    def test_valid_until_date_is_inclusive(self):
        import datetime

        c = concept("current", capabilities=[self.capability(
            "world", "Can use the current API", valid_until="2026-08-01"
        )])
        self.assertEqual(len(L.select_capabilities(
            [c], None, datetime.date(2026, 8, 1)
        )), 1)

    def test_retracted_capability_and_its_dependent_are_not_selected(self):
        base = concept("base", capabilities=[self.capability(
            "world", "Can do base", capability_id="base", retracted="2026-08-01",
            retraction_reason="system changed",
        )])
        dependent = concept("next", capabilities=[self.capability(
            "modification", "Can do next", capability_id="next", requires=["base/base"]
        )])
        self.assertEqual(L.select_capabilities([base, dependent], None), [])


class TestRender(ModelTestCase):
    def test_empty_model_says_so(self):
        mod = self.fresh_index_module()
        self.assertIn("assume nothing", mod.render([]))

    def test_states_are_listed_in_policy_order(self):
        out = L.render([
            concept("u", state="unknown"),
            concept("v", state="verified"),
        ], today=None)
        self.assertLess(out.index("verified:"), out.index("unknown:"))

    def test_gap_block_follows_the_states(self):
        out = L.render([concept("v", state="verified", gap="a gap", observations=3)], today=None)
        self.assertLess(out.index("verified:"), out.index("Established gaps"))

    def test_decay_removes_a_concept_from_the_injection(self):
        import datetime

        stale = concept("stale", state="exposed", observations=1, last_updated="2020-01-01")
        out = L.render([stale], today=datetime.date(2026, 7, 28))
        self.assertNotIn("stale", out)

    def test_decayed_concept_cannot_leak_back_through_its_gap(self):
        import datetime

        stale = concept("stale", state="exposed", observations=1, gap="a gap",
                        last_updated="2020-01-01")
        out = L.render([stale], today=datetime.date(2026, 7, 28))
        self.assertNotIn("stale", out)


class TestIndexFile(ModelTestCase):
    def test_regenerated_on_every_record(self):
        self.create("thing", domain="ocaml")
        text = (self.home / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("thing", text)
        self.assertIn("ocaml", text)

    def test_reflects_a_forget(self):
        self.create("thing", domain="ocaml")
        self.record("thing", "--forget", "cruft")
        text = (self.home / "INDEX.md").read_text(encoding="utf-8")
        self.assertNotIn("thing", text)

    def test_says_not_to_hand_edit(self):
        self.create("thing")
        self.assertIn("Do not hand-edit", (self.home / "INDEX.md").read_text(encoding="utf-8"))


class TestBudgetCheck(ModelTestCase):
    def test_combined_capabilities_and_gaps_fit_the_index_budget(self):
        from laconic_lint import INDEX_BUDGET

        abilities = [{"kind": "modification", "claim": "Can modify " + "detail " * 40,
                      "date": "2026-07-28", "scope": "general", "condition": ""}]
        evidence = [{"index": i + 1, "date": "2026-07-28", "kind": "world",
                     "text": "mapped a difficult system"} for i in range(3)]
        concepts = [
            concept(f"long-concept-{i}", state="verified", observations=3,
                    gap="gap " * 60, capabilities=abilities,
                    strong_evidence=evidence if i == 0 else ())
            for i in range(30)
        ]
        self.assertLessEqual(len(L.render(concepts, cwd="/project")), INDEX_BUDGET)

    def test_lint_measures_the_worst_case_across_projects(self):
        """A cwd-less render is smaller than a project-scoped one, so measuring without a
        cwd would hide a real overage."""
        for i in range(40):
            self.create(f"concept-number-{i}", domain=f"domain{i % 3}")
        r = self.lint()
        self.assertEqual(r.code, 0, r.text)
        mod = self.fresh_index_module()
        cs = mod.load_concepts()
        bare = len(mod.render(cs))
        scoped = max(
            len(mod.render(cs, cwd=p)) for c in cs for p in c["projects"]
        )
        self.assertGreaterEqual(scoped, bare)

    def test_warns_when_over_budget(self):
        from laconic_lint import INDEX_BUDGET

        self.assertGreater(INDEX_BUDGET, 0)
        for i in range(60):
            self.create(f"a-rather-long-concept-identifier-number-{i}", domain=f"d{i}")
        r = self.lint()
        mod = self.fresh_index_module()
        cs = mod.load_concepts()
        worst = max([len(mod.render(cs))] + [
            len(mod.render(cs, cwd=p)) for c in cs for p in c["projects"]
        ])
        if worst > INDEX_BUDGET:
            self.assertIn("over the", r.text)


class TestStableCommandPath(ModelTestCase):
    """SKILL.md has to name a command that resolves, but the scripts sit at a path that
    depends on the install mode. LACONIC_HOME is the location both modes share."""

    def test_ensure_bin_creates_the_wrappers(self):
        r = self.index("--ensure-bin")
        self.assertEqual(r.code, 0, r.text)
        for name in ("laconic-record", "laconic-lint", "laconic-index",
                     "laconic-candidates"):
            self.assertTrue((self.home / "bin" / name).exists(), name)

    def test_wrappers_are_executable(self):
        self.index("--ensure-bin")
        self.assertTrue(os.access(self.home / "bin" / "laconic-record", os.X_OK))

    def test_recording_through_the_wrapper_works(self):
        """The wrapper must not break __file__-relative imports inside the scripts."""
        self.index("--ensure-bin")
        proc = subprocess.run(
            [str(self.home / "bin" / "laconic-record"), "shim-thing",
             "--state", "exposed", "--domain", "testing", "--evidence", "via the shim"],
            capture_output=True, text=True, env=self.env(), check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.concepts / "shim-thing.md").exists())

    def test_created_on_an_ordinary_index_render(self):
        """Session start renders the index; that is the moment the path must come alive."""
        self.index()
        self.assertTrue((self.home / "bin" / "laconic-record").exists())

    def test_heals_when_the_checkout_moves(self):
        wrapper = self.home / "bin" / "laconic-record"
        self.index("--ensure-bin")
        wrapper.write_text("#!/usr/bin/env sh\nexec python3 /gone/laconic_record.py \"$@\"\n",
                           encoding="utf-8")
        self.index("--ensure-bin")
        self.assertIn("tools/laconic_record.py", wrapper.read_text(encoding="utf-8"))

    def test_bin_is_not_committed(self):
        """The wrappers hold this machine's absolute checkout path; syncing them would point
        the other machine at a directory that does not exist there."""
        self.create("thing")
        self.index("--ensure-bin")
        self.record("thing", "--state", "exposed", "--evidence", "again")
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=str(self.home),
            capture_output=True, text=True, check=False,
        ).stdout
        self.assertNotIn("bin/", tracked)


class TestSections(unittest.TestCase):
    def test_reads_a_section(self):
        body = "One liner.\n\n## A\nalpha\n\n## B\nbeta\n"
        self.assertEqual(L.get_section(body, "A"), "alpha")
        self.assertEqual(L.get_section(body, "B"), "beta")

    def test_missing_section_is_empty(self):
        self.assertEqual(L.get_section("## A\nalpha\n", "Z"), "")

    def test_empty_section_is_empty(self):
        self.assertEqual(L.get_section("## A\n\n## B\nbeta\n", "A"), "")

    def test_blank_lines_do_not_swallow_the_next_section(self):
        """Regression: a `\\s*$` heading pattern crosses blank lines under re.M and would
        report B's text as A's."""
        body = "## A\n\n\n## B\nbeta\n"
        self.assertEqual(L.get_section(body, "A"), "")
        self.assertEqual(L.get_section(body, "B"), "beta")

    def test_multiline_section_is_read_whole(self):
        body = "## A\nline one\nline two\n\n## B\nbeta\n"
        self.assertEqual(L.get_section(body, "A"), "line one\nline two")


if __name__ == "__main__":
    unittest.main()
