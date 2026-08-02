"""The bare-skill fallback installs a usable, repeatable command surface."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO


class TestBareInstall(unittest.TestCase):
    def run_install(self, root):
        user_home = root / "user"
        model_home = root / "model"
        user_home.mkdir(exist_ok=True)
        environment = dict(os.environ)
        environment.update({"HOME": str(user_home), "LACONIC_HOME": str(model_home)})
        result = subprocess.run(
            ["bash", str(REPO / "install.sh")],
            cwd=str(REPO),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, user_home, model_home

    def test_install_is_idempotent_and_commands_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, user_home, model_home = self.run_install(root)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            second, _, _ = self.run_install(root)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

            skill = user_home / ".claude" / "skills" / "laconic"
            self.assertTrue(skill.is_symlink())
            self.assertTrue((skill / "SKILL.md").is_file())
            recorder = model_home / "bin" / "laconic-record"
            self.assertTrue(os.access(recorder, os.X_OK))

            environment = dict(os.environ)
            environment.update({
                "HOME": str(user_home),
                "LACONIC_HOME": str(model_home),
                "LACONIC_NO_PUSH": "1",
            })
            recorded = subprocess.run(
                [
                    str(recorder), "installed-concept", "--state", "exposed",
                    "--domain", "testing", "--evidence", "installed command worked",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            self.assertTrue((model_home / "concepts" / "installed-concept.md").is_file())

    def test_existing_non_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collision = root / "user" / ".claude" / "skills" / "laconic"
            collision.mkdir(parents=True)
            marker = collision / "owned-by-user"
            marker.write_text("keep", encoding="utf-8")

            result, _, _ = self.run_install(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exists and is not a symlink", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
