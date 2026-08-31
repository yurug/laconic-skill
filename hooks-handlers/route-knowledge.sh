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
tools_dir = Path(sys.argv[1]).parent
sys.path.insert(0, str(tools_dir))

def load_tool(name):
    tool_spec = importlib.util.spec_from_file_location(name, tools_dir / f"{name}.py")
    tool = importlib.util.module_from_spec(tool_spec)
    tool_spec.loader.exec_module(tool)
    return tool

try:
    experiment = load_tool("laconic_experiment")
    experiment_arm = experiment.arm(str(payload.get("session_id", "")))
except Exception:
    experiment_arm = "semantic"
context = module.render_prompt_routes(
    concepts, prompt, include_knowledge=experiment_arm != "holdback"
)

# Maintenance belongs in private prompt context, not a Stop `decision: block`: Claude Code
# renders every Stop block as a visible hook error even when the continuation succeeds.
session = str(payload.get("session_id", ""))
try:
    maintenance = load_tool("laconic_maintenance")
    reason = maintenance.begin_text(prompt, session)
except Exception:
    reason = ""
if reason:
    context += ("\n\n# Silent Laconic maintenance\n\n"
                f"Signal: {reason}. Inspect this direct user message. Record at most one "
                "narrow, stable observation with laconic-record, or do nothing. When that "
                "same evidence establishes an understanding, principle, constraint, or "
                "preference, add --claim and --claim-kind atomically. "
                "Never mention maintenance or ask the user to curate the model.")
try:
    reconcile = load_tool("laconic_reconcile")
    reconcile_count = reconcile.begin()
except Exception:
    reconcile_count = 0
if reconcile_count:
    context += ("\n\n# Silent Laconic reconciliation\n\n"
                f"{reconcile_count} mechanical findings are due. Run laconic-reconcile and "
                "change only directly evidenced obsolescence, distillation, or retraction. "
                "Never mention this pass or make it a user task.")
if os.environ.get("LACONIC_TELEMETRY") == "1":
    # Recompute only the bounded route names; never retain the prompt or its tokens.
    domains = module.select_prompt_domains(concepts, prompt)
    model_home = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    row = {
        "date": date.today().isoformat(),
        "session": hashlib.sha256(session.encode()).hexdigest()[:20] if session else "",
        "domains": domains,
        "chars": len(context),
        "routing_version": 2,
        "experiment_arm": experiment_arm,
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
