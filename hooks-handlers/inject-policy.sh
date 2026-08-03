#!/usr/bin/env bash
# Laconic: inject the communication policy and the user-knowledge index.
#
# Serves both SessionStart and SubagentStart, which take an identical
# hookSpecificOutput contract. Subagents do not inherit the main session's injected
# context, so without the SubagentStart wiring their output — which reaches the user
# through the parent — would ignore the policy entirely.
#
# Pass the event name as $1; defaults to SessionStart.
#
# This runs on every session and every subagent, so it must stay small and must never
# fail loudly — a broken hook would degrade everything. Any error yields a valid JSON
# envelope with an empty index rather than a crash.

set -uo pipefail

EVENT="${1:-SessionStart}"
case "$EVENT" in
  SessionStart|SubagentStart) ;;
  *) EVENT="SessionStart" ;;
esac

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INDEX_SCRIPT="${PLUGIN_ROOT}/tools/laconic_index.py"
MODEL_HOME="${LACONIC_HOME:-${HOME}/.laconic}"

# Python is the plugin's runtime. If it is unavailable, do not let the universal hook break
# session startup or pretend the knowledge model was loaded: emit a valid conservative
# envelope using shell builtins only.
if ! command -v python3 >/dev/null 2>&1; then
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"Laconic unavailable: python3 is required. Assume nothing about what the user knows; explain when uncertain."}}\n' "$EVENT"
  exit 0
fi

# The hook payload on stdin carries the session cwd. It lets the index keep this project's
# concepts inline once a state outgrows the inline limit. Manual runs must pipe something in
# (e.g. echo '{}' | ...) or stdin will block on the terminal.
INPUT="$(cat 2>/dev/null || true)"
SESSION_CWD=""
if [ -n "$INPUT" ] && command -v python3 >/dev/null 2>&1; then
  SESSION_CWD="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("cwd", ""))
except Exception:
    print("")
' 2>/dev/null)" || SESSION_CWD=""
fi

if command -v python3 >/dev/null 2>&1 && [ -f "$INDEX_SCRIPT" ]; then
  if [ -n "$SESSION_CWD" ]; then
    INDEX="$(python3 "$INDEX_SCRIPT" --cwd "$SESSION_CWD" 2>/dev/null)" || INDEX=""
  else
    INDEX="$(python3 "$INDEX_SCRIPT" 2>/dev/null)" || INDEX=""
  fi
else
  INDEX=""
fi

if [ -z "$INDEX" ]; then
  INDEX="No concepts recorded yet. Assume nothing about what the user knows."
fi

# The recording command. laconic_index.py (run just above) keeps ~/.laconic/bin/ populated,
# so prefer that stable path: it is the same in a plugin install and a bare skill install,
# and it is shorter than the plugin path in text injected into every session. Fall back to
# the plugin path when the shim is missing -- no python3, or a failed mkdir.
RECORD_CMD="${MODEL_HOME}/bin/laconic-record"
if [ ! -x "$RECORD_CMD" ]; then
  RECORD_CMD="python3 ${PLUGIN_ROOT}/tools/laconic_record.py"
fi

# Build the context, then JSON-encode it with python3 so quoting and newlines in
# concept ids can never corrupt the envelope.
read -r -d '' POLICY <<'POLICY_EOF'
# Laconic (always on)

Cutting noise is the point. The knowledge model below tells you what to leave out.

- Lead with the outcome. Answer the contrast actually asked, with 1-2 causes, not every
  cause.
- Detail has a cost curve: past a point, more is worse. No safely-verbose default.
- Compress steps the user expects; surface surprising ones before acting.
- Keep "why" out of "how-to". Say what a change does NOT handle and what breaks if an
  assumption fails.
- Never write to a readability target; extra words that show how things relate are fine.
- `verified`: use freely, never define or re-derive. `familiar`: a short gloss on first
  use only. `exposed`/`unknown`: define in one clause OR link, not both. Never define
  inline what the user knows -- redundancy costs an expert working memory even when they
  skip it.
- Uncertain? Explain more. Under-explaining is the costlier error; over-explaining is
  still an error. Adapt wording sooner than you adapt code. Never infer learning styles.
POLICY_EOF

# Only the main session observes the user directly. A subagent sees a task prompt, not
# the user's own words, so it has no first-hand evidence and must not write to the model
# -- the schema requires every entry to cite a dated observation.
if [ "$EVENT" = "SubagentStart" ]; then
  read -r -d '' TAIL <<'TAIL_EOF'
- Do NOT write to ~/.laconic/. You are not observing the user directly, so you have no
  first-hand evidence to record. Report what you found; the main session records it.
- Your output reaches the user through the parent agent. Apply the rules above to it.

## What the user knows
TAIL_EOF
else
  # The schema lives in the tool, not in this prose. Telling an agent to "maintain the
  # model" without the schema produced freeform notes the index silently dropped.
  read -r -d '' TAIL <<TAIL_EOF
- Record evidence with the tool -- never hand-write these files, they have a schema:
  ${RECORD_CMD} <id> --state <unknown|exposed|familiar|verified> --domain <subject> --evidence "what you saw"
  Basis defaults direct; --basis confirmation means explicit confirmation; --basis inference
  is weak and audit-only (no state/capability).
  Never infer prerequisites or invent observations. Strong --kind values are
  world, justification, or modification. If one proves a reusable ability, add --capability.
  For older proof, run ${MODEL_HOME}/bin/laconic-candidates and use --capability-from; never
  duplicate evidence. Scope defaults to this project; widen it only with transfer evidence.
  Record relations only when observed; retract obsolete abilities
  with --retract-capability and --reason. The default, term use, is weakest. A facet question becomes a gap via
  --not-established, not a whole-concept demotion. When the tool asks, distil with only
  --not-established (optionally --understands): a summary is not evidence. Describe rather
  than quote; never store secrets or confidential text. Writes are committed locally and
  pushed only with both an origin and LACONIC_PUSH=1.

Run the \`laconic\` skill for the full policy when writing a document or when asked.

## What the user knows
TAIL_EOF
fi

POLICY="${POLICY}
${TAIL}"

python3 - "$POLICY" "$INDEX" "$EVENT" <<'PY'
import json
import sys

policy, index, event = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": policy + "\n\n" + index + "\n",
    }
}))
PY

exit 0
