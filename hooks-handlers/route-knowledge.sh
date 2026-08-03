#!/usr/bin/env bash
# Select and inject relevant domain leaves for each user prompt. Silent on no match/error.

set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INDEX_SCRIPT="${PLUGIN_ROOT}/tools/laconic_index.py"
command -v python3 >/dev/null 2>&1 || exit 0
[ -f "$INDEX_SCRIPT" ] || exit 0
INPUT="$(cat 2>/dev/null || true)"

# Parse and render in one process: prompts may contain newlines, quotes, or shell syntax and
# must never pass through shell interpolation or argv.
LACONIC_HOOK_INPUT="$INPUT" python3 - "$INDEX_SCRIPT" 2>/dev/null <<'PY'
import importlib.util
import json
import os
import sys

try:
    payload = json.loads(os.environ.get("LACONIC_HOOK_INPUT", ""))
except Exception:
    raise SystemExit(0)
prompt = payload.get("prompt", "")
if not isinstance(prompt, str) or not prompt:
    raise SystemExit(0)
spec = importlib.util.spec_from_file_location("laconic_index", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
context = module.render_prompt_routes(module.load_concepts(), prompt)
if context:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context,
    }}))
PY
