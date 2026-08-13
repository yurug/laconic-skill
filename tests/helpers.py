"""Shared fixtures for the laconic regression suite.

stdlib unittest on purpose: the repo's runtime has no third-party dependencies, and a test
suite that needed pip would undercut the claim that you can install this on a bare machine.

Every test gets its own LACONIC_HOME under a temp dir and runs with LACONIC_NO_PUSH=1, so
nothing here can reach the real model or a git remote.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
RECORD = TOOLS / "laconic_record.py"
INDEX = TOOLS / "laconic_index.py"
LINT = TOOLS / "laconic_lint.py"
CANDIDATES = TOOLS / "laconic_candidates.py"
BOOTSTRAP = TOOLS / "laconic_bootstrap.py"
REVIEW = TOOLS / "laconic_review.py"
REVIEW_WEB = TOOLS / "laconic_review_web.py"
APPLY_REVIEW = TOOLS / "laconic_apply_review.py"
MAINTENANCE = TOOLS / "laconic_maintenance.py"
ROUTE_OBSERVE = TOOLS / "laconic_route_observe.py"
MIGRATE_V2 = TOOLS / "laconic_migrate_v2.py"

sys.path.insert(0, str(TOOLS))


class Result:
    def __init__(self, proc):
        self.code = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr

    @property
    def text(self):
        return self.out + self.err


class ModelTestCase(unittest.TestCase):
    """A test case with an isolated model directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "laconic"
        (self.home / "concepts").mkdir(parents=True)
        self.concepts = self.home / "concepts"

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **extra):
        e = dict(os.environ)
        # The suite often runs inside a session that has opted into telemetry or the
        # experiment; inheriting those would flip opt-in behaviour on for every test.
        # Tests that want them state so through `extra`.
        for opt_in in ("LACONIC_TELEMETRY", "LACONIC_EXPERIMENT", "LACONIC_PUSH"):
            e.pop(opt_in, None)
        e["LACONIC_HOME"] = str(self.home)
        e["LACONIC_NO_PUSH"] = "1"
        # Git may start automatic maintenance after a commit and outlive the recorder.
        # Production repositories should keep that maintenance; isolated test repositories
        # are deleted immediately, so a background pack races TemporaryDirectory cleanup.
        e["GIT_CONFIG_COUNT"] = "2"
        e["GIT_CONFIG_KEY_0"] = "gc.auto"
        e["GIT_CONFIG_VALUE_0"] = "0"
        e["GIT_CONFIG_KEY_1"] = "maintenance.auto"
        e["GIT_CONFIG_VALUE_1"] = "false"
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def run_tool(self, script, *args, env=None, cwd=None):
        proc = subprocess.run(
            [sys.executable, str(script), *[str(a) for a in args]],
            capture_output=True,
            text=True,
            env=env or self.env(),
            cwd=str(cwd) if cwd else str(REPO),
            check=False,
        )
        return Result(proc)

    def record(self, *args, **kw):
        return self.run_tool(RECORD, *args, **kw)

    def lint(self, *args, **kw):
        return self.run_tool(LINT, *args, **kw)

    def index(self, *args, **kw):
        return self.run_tool(INDEX, *args, **kw)

    # -- assertions and readers -------------------------------------------------

    def create(self, cid, *extra, state="exposed", domain="testing", evidence="seen"):
        """Create a concept the ordinary way, asserting it worked.

        Extra CLI arguments are positional; the common fields are keyword-only so a stray
        positional cannot silently land in `state`.
        """
        r = self.record(cid, "--state", state, "--domain", domain, "--evidence", evidence, *extra)
        self.assertEqual(r.code, 0, f"create {cid} failed: {r.text}")
        return r

    def path(self, cid):
        return self.concepts / f"{cid}.md"

    def read(self, cid):
        return self.path(cid).read_text(encoding="utf-8")

    def field(self, cid, key):
        """A scalar frontmatter value, or None."""
        m = re.search(rf"^{re.escape(key)}:\s*(.*)$", self.read(cid), re.M)
        return m.group(1).strip() if m else None

    def section(self, cid, heading):
        from laconic_index import get_section

        text = self.read(cid)
        end = text.find("\n---", 3)
        return get_section(text[end + 4 :], heading)

    def evidence_lines(self, cid):
        return re.findall(r"^  - (.*)$", self.read(cid), re.M)

    def git_log(self):
        if not (self.home / ".git").is_dir():
            return []
        proc = subprocess.run(
            ["git", "log", "--format=%s"],
            cwd=str(self.home),
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout.strip().splitlines()

    def fresh_index_module(self):
        """Return laconic_index with this test's model selected in the environment."""
        import importlib

        import laconic_index

        os.environ["LACONIC_HOME"] = str(self.home)
        importlib.reload(laconic_index)
        return laconic_index


def have_git():
    return shutil.which("git") is not None


requires_git = unittest.skipUnless(have_git(), "git not available")
