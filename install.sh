#!/usr/bin/env bash
# Install laconic without the plugin marketplace: symlink the skill and print the
# hook configuration to add. Idempotent.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"
LACONIC_HOME="${LACONIC_HOME:-${HOME}/.laconic}"

mkdir -p "$SKILLS_DIR" "$LACONIC_HOME/concepts"

link="${SKILLS_DIR}/laconic"
target="${REPO}/skills/laconic"

if [ -L "$link" ]; then
  current="$(readlink "$link")"
  if [ "$current" != "$target" ]; then
    ln -sfn "$target" "$link"
    echo "updated symlink: $link -> $target (was $current)"
  else
    echo "symlink already correct: $link -> $target"
  fi
elif [ -e "$link" ]; then
  echo "ERROR: $link exists and is not a symlink. Move it aside and re-run." >&2
  exit 1
else
  ln -s "$target" "$link"
  echo "linked: $link -> $target"
fi

# Verify the link actually resolves, rather than trusting ln's exit code.
if [ ! -f "${link}/SKILL.md" ]; then
  echo "ERROR: ${link}/SKILL.md is not readable through the symlink." >&2
  exit 1
fi

# Stable command names, so SKILL.md can reference one path that works whether laconic was
# installed as a plugin or as a bare skill. Without this, the skill's mandatory
# laconic_record.py command is unresolvable from an arbitrary working directory.
if command -v python3 >/dev/null 2>&1; then
  BINDIR="$(LACONIC_HOME="$LACONIC_HOME" python3 "${REPO}/tools/laconic_index.py" --ensure-bin)"
  echo "commands: ${BINDIR}/laconic-record, laconic-lint, laconic-index, laconic-console, laconic-candidates"
else
  echo "WARNING: python3 not found; the laconic commands could not be created." >&2
fi

echo "model directory: ${LACONIC_HOME}/concepts"
echo
echo "The skill is installed. To get the always-on policy (recommended -- the skill alone"
echo "only fires when a task matches its description), install as a plugin instead:"
echo
echo "  /plugin marketplace add ${REPO}"
echo "  /plugin install laconic@nomadic-labs"
echo
echo "Then check the model with:  ${LACONIC_HOME}/bin/laconic-lint"
