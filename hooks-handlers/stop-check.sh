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
MAINTENANCE="${PLUGIN_ROOT}/tools/laconic_maintenance.py"
ROUTE_OBSERVE="${PLUGIN_ROOT}/tools/laconic_route_observe.py"
RECONCILE="${PLUGIN_ROOT}/tools/laconic_reconcile.py"

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

# Resolve the route selected for this turn against the final answer before any Stop branch.
# This is content-free telemetry: the resolver stores only matched domain names and counts.
if [ "${LACONIC_TELEMETRY:-}" = "1" ] && [ -n "$TRANSCRIPT" ] \
    && command -v python3 >/dev/null 2>&1 && [ -f "$ROUTE_OBSERVE" ]; then
  python3 "$ROUTE_OBSERVE" "$TRANSCRIPT" "$SESSION_ID" >/dev/null 2>&1 || true
fi

# Already continuing because of a stop hook: resolve an opted-in maintenance measurement,
# then never stack another block. The resolver stores only signal class and whether the
# recorder appeared, never transcript text.
if [ "$STOP_ACTIVE" = "1" ]; then
  if [ "${LACONIC_TELEMETRY:-}" = "1" ] && [ -n "$TRANSCRIPT" ] \
      && command -v python3 >/dev/null 2>&1 && [ -f "$MAINTENANCE" ]; then
    python3 "$MAINTENANCE" "$TRANSCRIPT" --resolve "$SESSION_ID" >/dev/null 2>&1 || true
  fi
  if command -v python3 >/dev/null 2>&1 && [ -f "$RECONCILE" ] \
      && [ -f "${LACONIC_HOME}/.reconciliation-pending" ]; then
    python3 "$RECONCILE" --complete >/dev/null 2>&1 || true
  fi
  exit 0
fi

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

# ── 2. Silent semantic maintenance ───────────────────────────────────
# A deterministic hook cannot safely decide what the user knows. It can, however, detect a
# narrow class of high-value turns (explicit corrections and substantial justifications) and
# give the main agent one continuation in which to make that semantic decision. The second
# Stop carries stop_hook_active and exits at the top, so this can never loop.
if [ -n "$TRANSCRIPT" ] && command -v python3 >/dev/null 2>&1 && [ -f "$MAINTENANCE" ]; then
  REVIEW_REASON="$(python3 "$MAINTENANCE" "$TRANSCRIPT" --begin "$SESSION_ID" 2>/dev/null)" \
    || REVIEW_REASON=""
  if [ -n "$REVIEW_REASON" ]; then
    emit_block "Silent Laconic maintenance pass (${REVIEW_REASON}). Inspect only the latest direct user message. If it directly demonstrates stable knowledge, record one narrow paraphrased observation with laconic-record; add a capability only when demonstrated. If it does not, finish unchanged. Never mention this pass, ask the user to curate the model, duplicate evidence, or store secrets/confidential text."
  fi
fi

# ── 3. Periodic model reconciliation ────────────────────────────────
# At most once every 30 days, and only when mechanical lifecycle signals exist. Retrieval
# already applies decay/expiry, so this pass reviews stored claims without urgency or user
# interruption. The continuation completes the period even if conservative review changes
# nothing.
if command -v python3 >/dev/null 2>&1 && [ -f "$RECONCILE" ]; then
  RECONCILE_COUNT="$(python3 "$RECONCILE" --begin 2>/dev/null)" || RECONCILE_COUNT=""
  if [ -n "$RECONCILE_COUNT" ]; then
    emit_block "Silent periodic Laconic reconciliation (${RECONCILE_COUNT} mechanical findings). Run ${LACONIC_HOME}/bin/laconic-reconcile and inspect the report. Decay and expiry already protect retrieval. For every undistilled justification/modification, either distil its narrow reusable ability or deliberately classify it as only a preference/constraint; do not silently skip the decision. Modify only claims directly shown obsolete and leave ambiguous contradictions unchanged. Do not mention this pass or ask the user to maintain the model."
  fi
fi

exit 0
