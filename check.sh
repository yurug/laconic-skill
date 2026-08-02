#!/usr/bin/env bash
# One command to verify the repo: tests, Python compilation, shell syntax, ShellCheck, and
# a consistency check between the docs and the constants they describe.
#
# No third-party dependencies are required. ShellCheck is used when installed and reported as
# skipped when not, so this is runnable on a bare machine.
#
# Exits non-zero if anything fails, and prints a summary of every stage either way.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO" || exit 1

FAILED=()
SKIPPED=()

stage() {
  local name="$1"
  shift
  printf '\n\033[1m── %s\033[0m\n' "$name"
  if "$@"; then
    printf '\033[32mok\033[0m %s\n' "$name"
  else
    printf '\033[31mFAIL\033[0m %s\n' "$name"
    FAILED+=("$name")
  fi
}

# ── tests ───────────────────────────────────────────────────────────────
run_tests() {
  python3 -m unittest discover -s tests -t tests "$@"
}

# ── python compiles ─────────────────────────────────────────────────────
run_compile() {
  # eval/ included: it is not shipped in the plugin, but a measurement harness that does not
  # parse is a measurement that silently does not happen.
  python3 -m py_compile tools/*.py tests/*.py eval/*.py
}

# ── shell syntax ────────────────────────────────────────────────────────
run_shell_syntax() {
  local rc=0
  for f in hooks-handlers/*.sh install.sh check.sh; do
    bash -n "$f" || rc=1
  done
  return $rc
}

# ── shellcheck, when available ──────────────────────────────────────────
run_shellcheck() {
  if ! command -v shellcheck >/dev/null 2>&1; then
    echo "shellcheck not installed — skipping"
    SKIPPED+=("shellcheck")
    return 0
  fi
  shellcheck hooks-handlers/*.sh install.sh check.sh
}

# ── docs match the constants they describe ──────────────────────────────
# The decay table in docs/knowledge-model.md names its thresholds. Prose drifts; this makes
# the drift fail rather than mislead.
run_rules_enforced() {
  # design/04-decisions.md Q5: a rule that only exists in prose is asserted, not enforced,
  # and the two drift silently. This is that decision applied to itself.
  #
  # Deliberately narrow. "Find every rule and verify it" is not mechanisable; what is
  # mechanisable is the exact failure this repo actually shipped -- a CLI flag documented as
  # required with nothing asserting the refusal. Rules that are genuinely social are
  # allowlisted rather than pretended about.
  python3 - <<'PY'
import re
import sys
from pathlib import Path

DOCS = [Path("README.md"), *Path("docs").glob("*.md"), *Path("skills").rglob("*.md")]
MODAL = r"(?:required|mandatory|must|always)"
FLAG = r"`(--[a-z][a-z-]*)`"

# Rules a program cannot check. Naming them is the point: an allowlist that has to be
# edited is visible, whereas a check that quietly skips them is not.
SOCIAL = {
    "--confirmed",  # "explicit user confirmation" is a claim about a human, not a state
}

documented = {}
for doc in DOCS:
    if not doc.exists():
        continue
    text = doc.read_text(encoding="utf-8")
    for m in re.finditer(rf"{FLAG}[^.\n]{{0,80}}?{MODAL}|{MODAL}[^.\n]{{0,80}}?{FLAG}", text, re.I):
        flag = m.group(1) or m.group(2)
        documented.setdefault(flag, set()).add(doc.as_posix())

tests = "\n".join(p.read_text(encoding="utf-8") for p in Path("tests").glob("*.py"))
problems = []
for flag, where in sorted(documented.items()):
    if flag in SOCIAL:
        continue
    if flag not in tests:
        problems.append(f"{flag} is documented as required ({', '.join(sorted(where))}) "
                        f"but no test mentions it")
        continue
    # A test that merely passes the flag is not enforcement; something must assert that
    # omitting it is refused.
    window = "\n".join(
        blk for blk in tests.split("\n    def ") if flag in blk
    )
    if not re.search(r"assert\w*\((?:r\.code|result\.code)\s*,\s*[12]\b", window) and \
       not re.search(r"assertIn\(\s*[\"']error", window):
        problems.append(f"{flag} is documented as required but no test asserts the refusal")

for p in problems:
    print(f"  {p}")
sys.exit(1 if problems else 0)
PY
}

run_doc_consistency() {
  python3 - <<'PY'
import re
import sys
from pathlib import Path

sys.path.insert(0, "tools")
import laconic_index as L  # noqa: E402
import laconic_lint as Lint  # noqa: E402

doc = Path("docs/knowledge-model.md").read_text(encoding="utf-8")
problems = []

for name, value in (
    ("FAMILIAR_DECAY_DAYS", L.FAMILIAR_DECAY_DAYS),
    ("EXPOSED_DROP_DAYS", L.EXPOSED_DROP_DAYS),
):
    m = re.search(rf"{name}`?\s*\((\d+)", doc)
    if not m:
        problems.append(f"{name} is not named in docs/knowledge-model.md")
    elif int(m.group(1)) != value:
        problems.append(f"docs say {name}={m.group(1)}, code says {value}")

if L.FAMILIAR_DECAY_DAYS != Lint.STALE_DAYS:
    problems.append(
        f"FAMILIAR_DECAY_DAYS={L.FAMILIAR_DECAY_DAYS} but lint STALE_DAYS={Lint.STALE_DAYS}; "
        "the docs promise these agree"
    )

for p in problems:
    print(f"  {p}")
sys.exit(1 if problems else 0)
PY
}

# ── skill package ──────────────────────────────────────────────────────
run_skill_package() {
  python3 - <<'PY'
import re
import sys
from pathlib import Path

skill = Path("skills/laconic")
source = (skill / "SKILL.md").read_text(encoding="utf-8")
problems = []

if not source.startswith("---\n"):
    problems.append("SKILL.md has no opening YAML frontmatter")
else:
    end = source.find("\n---\n", 4)
    if end < 0:
        problems.append("SKILL.md frontmatter is not closed")
    else:
        fields = {}
        for line in source[4:end].splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip().strip('"')
        if set(fields) != {"name", "description"}:
            problems.append("SKILL.md frontmatter must contain only name and description")
        name = fields.get("name", "")
        if name != skill.name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            problems.append(f"skill name {name!r} is invalid or differs from its folder")
        if not fields.get("description"):
            problems.append("skill description is empty")

metadata = skill / "agents" / "openai.yaml"
if not metadata.is_file():
    problems.append("agents/openai.yaml is missing")
else:
    text = metadata.read_text(encoding="utf-8")
    values = dict(re.findall(r'^  ([a-z_]+):\s*"([^"]*)"\s*$', text, re.M))
    required = {"display_name", "short_description", "default_prompt"}
    missing = required - values.keys()
    if missing:
        problems.append(f"agents/openai.yaml lacks {', '.join(sorted(missing))}")
    short = values.get("short_description", "")
    if short and not 25 <= len(short) <= 64:
        problems.append("short_description must contain 25-64 characters")
    if "$laconic" not in values.get("default_prompt", ""):
        problems.append("default_prompt must mention $laconic")

for problem in problems:
    print(f"  {problem}")
sys.exit(1 if problems else 0)
PY
}

# ── plugin and marketplace manifests ────────────────────────────────────
run_manifests() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "claude CLI not available — skipping manifest validation"
    SKIPPED+=("manifest validation")
    return 0
  fi
  claude plugin validate . && claude plugin validate ./.claude-plugin/plugin.json
}

# ── the real model, if there is one ──────────────────────────────────────
run_model_lint() {
  local home="${LACONIC_HOME:-${HOME}/.laconic}"
  if [ ! -d "${home}/concepts" ]; then
    echo "no model at ${home}/concepts — skipping"
    SKIPPED+=("model lint")
    return 0
  fi
  python3 tools/laconic_lint.py
}

stage "tests"            run_tests
stage "python compile"   run_compile
stage "shell syntax"     run_shell_syntax
stage "shellcheck"       run_shellcheck
stage "docs consistency" run_doc_consistency
stage "rules enforced"   run_rules_enforced
stage "skill package"    run_skill_package
stage "manifests"        run_manifests
stage "model lint"       run_model_lint

printf '\n\033[1m── summary\033[0m\n'
if [ ${#SKIPPED[@]} -gt 0 ]; then
  printf 'skipped: %s\n' "${SKIPPED[*]}"
fi
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '\033[31m%d stage(s) failed:\033[0m %s\n' "${#FAILED[@]}" "${FAILED[*]}"
  exit 1
fi
printf '\033[32mall stages passed\033[0m\n'
