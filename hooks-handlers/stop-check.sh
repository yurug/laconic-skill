#!/usr/bin/env bash
# Laconic: protect model integrity at the end of a turn.
#
# SILENT BY DEFAULT. It emits nothing unless there is something to say, so the token
# cost on an ordinary turn is zero. A malformed model is worth interrupting for because
# affected concepts otherwise disappear from the injected view.
#
# Absence of a write is deliberately not an error. A long session can reveal no stable
# evidence about the user, and forcing a write there creates exactly the invented or weak
# inference the model is designed to exclude.

set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LACONIC_HOME="${LACONIC_HOME:-${HOME}/.laconic}"
CONCEPTS="${LACONIC_HOME}/concepts"
LINT="${PLUGIN_ROOT}/tools/laconic_lint.py"

INPUT="$(cat)"

read -r STOP_ACTIVE SESSION_ID TRANSCRIPT <<<"$(
  printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
print(
    "1" if d.get("stop_hook_active") else "0",
    d.get("session_id", "nosession"),
    d.get("transcript_path", ""),
)
' 2>/dev/null || echo "1 nosession ")"

# Already continuing because of a stop hook: never stack another block.
[ "$STOP_ACTIVE" = "1" ] && exit 0

emit_block() {
  python3 -c '
import json, sys
print(json.dumps({"decision": "block", "reason": sys.argv[1]}))
' "$1"
  exit 0
}

# ── 0. Observe ────────────────────────────────────────────────────────
# Placed before every early exit below, so enabling it samples every turn rather than only
# malformed-model paths.
#
# Backgrounded and fully silenced: this is a measurement, and it must not add latency to
# the turn, emit anything the harness could read as hook output, or fail the hook.
OBSERVE="${PLUGIN_ROOT}/tools/laconic_observe.py"
if [ "${LACONIC_TELEMETRY:-}" = "1" ] && [ -f "$OBSERVE" ] && [ -n "$TRANSCRIPT" ]; then
  (python3 "$OBSERVE" "$TRANSCRIPT" "$SESSION_ID" >/dev/null 2>&1 &) || true
fi

# ── 1. Malformed model ────────────────────────────────────────────────
# A concept file the index cannot parse is invisible: the model looks empty while the
# file sits there. Worth interrupting for, every time, until it is fixed.
#
# The lint is a python startup, and this hook runs on every turn, so skip it when
# nothing has changed since the last clean run. Only a concept file newer than the
# stamp can have introduced an error.
STAMP="${LACONIC_HOME}/.lint-ok"
NEEDS_LINT=1
if [ -e "$STAMP" ] && [ -d "$CONCEPTS" ]; then
  [ -z "$(find "$CONCEPTS" -name '*.md' -newer "$STAMP" -print -quit 2>/dev/null)" ] && NEEDS_LINT=0
fi

if [ "$NEEDS_LINT" = "1" ] && command -v python3 >/dev/null 2>&1 && [ -f "$LINT" ]; then
  if LINT_OUT="$(python3 "$LINT" --quiet 2>&1)"; then
    touch "$STAMP" 2>/dev/null || true
  else
    ERRORS="$(printf '%s' "$LINT_OUT" | grep '^ERROR' | head -5)"
    [ -n "$ERRORS" ] && emit_block "The knowledge model is malformed and those concepts are invisible to the index. Fix with tools/laconic_record.py (it rewrites a file into schema-correct form), then continue:
${ERRORS}"
  fi
fi

exit 0
