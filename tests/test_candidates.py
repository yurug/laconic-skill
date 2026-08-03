"""Candidate discovery keeps capability distillation evidence-bound and reviewable."""

from helpers import CANDIDATES, REPO, ModelTestCase


class TestCandidateSelection(ModelTestCase):
    def test_shows_relevant_undistilled_evidence_and_command(self):
        self.create(
            "scheduler", "--kind", "modification", "--date", "2026-08-01",
            evidence="changed the scheduler while preserving FIFO",
        )
        r = self.run_tool(CANDIDATES, "--cwd", str(REPO), env=self.env())
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("scheduler evidence #1 [modification, direct, 2026-08-01]", r.text)
        self.assertIn("changed the scheduler while preserving FIFO", r.text)
        self.assertIn("--capability-from 1", r.text)
        self.assertIn("<narrow reusable ability", r.text)

    def test_distilled_evidence_is_no_longer_a_candidate(self):
        self.create("thing", "--kind", "world", evidence="mapped the system")
        r = self.record(
            "thing", "--capability-from", "1", "--capability", "Can map the system",
        )
        self.assertEqual(r.code, 0, r.text)
        candidates = self.run_tool(CANDIDATES, "--cwd", str(REPO), env=self.env())
        self.assertEqual(candidates.code, 0, candidates.text)
        self.assertIn("No undistilled strong evidence", candidates.text)

    def test_does_not_show_another_projects_evidence(self):
        self.create("thing", "--kind", "world", evidence="mapped the system")
        r = self.run_tool(CANDIDATES, "--cwd", "/unrelated/project", env=self.env())
        self.assertEqual(r.code, 0, r.text)
        self.assertNotIn("thing evidence", r.text)

    def test_review_command_is_read_only(self):
        self.create("thing", "--kind", "world", evidence="mapped the system")
        before = self.path("thing").read_bytes()
        self.run_tool(CANDIDATES, "--cwd", str(REPO), env=self.env())
        self.assertEqual(self.path("thing").read_bytes(), before)

    def test_inferred_strong_evidence_is_not_a_candidate(self):
        self.create(
            "thing", "--kind", "world", "--basis", "inference", state="unknown",
            evidence="might map the system",
        )
        r = self.run_tool(CANDIDATES, "--cwd", str(REPO), env=self.env())
        self.assertEqual(r.code, 0, r.text)
        self.assertIn("No undistilled strong evidence", r.text)
