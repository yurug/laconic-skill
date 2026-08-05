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
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

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
concepts = module.load_concepts()
context = module.render_prompt_routes(concepts, prompt)
if os.environ.get("LACONIC_TELEMETRY") == "1":
    # Recompute only the bounded route names; never retain the prompt or its tokens.
    domains = module.select_prompt_domains(concepts, prompt)
    model_home = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    session = str(payload.get("session_id", ""))
    row = {
        "date": date.today().isoformat(),
        "session": hashlib.sha256(session.encode()).hexdigest()[:20] if session else "",
        "domains": domains,
        "chars": len(context),
        "routing_version": 2,
    }
    try:
        if session:
            pending = model_home / ".routing-pending" / f"{row['session']}.json"
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            # Some harnesses omit session_id. Keep aggregate selection/cost measurable,
            # but make the unavailable answer-use proxy explicit.
            row["answer_domains"] = None
            with (model_home / "routing-telemetry.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
if context:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context,
    }}))
PY
