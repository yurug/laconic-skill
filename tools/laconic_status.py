#!/usr/bin/env python3
"""Answer "is laconic actually doing anything?" — the question the plugin could not answer.

Checks the three things that can independently be false: the plugin is enabled, the
running session actually received the policy (it is injected at session start, so a
session older than the install never gets it), and the model is growing.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from laconic_index import load_concepts  # noqa: E402

HOME = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
PROJECTS = Path.home() / ".claude" / "projects"


def check_enabled():
    settings = Path.home() / ".claude" / "settings.json"
    try:
        d = json.loads(settings.read_text())
    except Exception:
        return None, None
    enabled = [k for k, v in d.get("enabledPlugins", {}).items() if "laconic" in k and v]
    return (enabled[0] if enabled else None), settings.stat().st_mtime


def live_sessions(install_mtime, limit=8):
    """Sessions touched in the last 12h, and whether their transcript shows the policy."""
    if not PROJECTS.is_dir():
        return []
    cutoff = datetime.now() - timedelta(hours=12)
    rows = []
    for f in PROJECTS.glob("*/[0-9a-f]*.jsonl"):
        try:
            st = f.stat()
        except OSError:
            continue
        last = datetime.fromtimestamp(st.st_mtime)
        if last < cutoff:
            continue
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        started = None
        for line in txt.splitlines():
            if '"timestamp"' in line:
                try:
                    ts = json.loads(line).get("timestamp")
                except Exception:
                    continue
                if ts:
                    started = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                    break
        rows.append(
            {
                "project": f.parent.name,
                "started": started,
                "last": last,
                "policy": "Laconic (always on)" in txt,
                "current": "laconic_record.py" in txt,
                "stale": bool(started and install_mtime and started.timestamp() < install_mtime),
            }
        )
    rows.sort(key=lambda r: r["last"], reverse=True)
    return rows[:limit]


def main():
    print("laconic status\n" + "=" * 60)

    plugin, install_mtime = check_enabled()
    if plugin:
        when = (
            datetime.fromtimestamp(install_mtime).strftime("%Y-%m-%d %H:%M")
            if install_mtime
            else "unknown"
        )
        print(f"plugin      {plugin}  (config last changed {when})")
    else:
        print("plugin      NOT ENABLED — run: claude plugin install laconic@nomadic-labs")

    concepts = load_concepts()
    print(f"model       {len(concepts)} concepts at {HOME}/concepts")
    if concepts:
        recent = sorted(
            ((c, (HOME / "concepts" / f"{c['id']}.md").stat().st_mtime) for c in concepts),
            key=lambda t: -t[1],
        )[:3]
        for c, m in recent:
            print(f"              {datetime.fromtimestamp(m).strftime('%m-%d %H:%M')}  "
                  f"{c['id']} ({c['state']})")
    else:
        print("              empty — it fills as evidence appears, not on a schedule")

    lint = Path(__file__).parent / "laconic_lint.py"
    r = subprocess.run([sys.executable, str(lint), "--quiet"], capture_output=True, text=True)
    print(f"lint        {'clean' if r.returncode == 0 else 'ERRORS — run laconic_lint.py'}")

    rows = live_sessions(install_mtime)
    if rows:
        print("\nsessions active in the last 12h:")
        for r_ in rows:
            started = r_["started"].strftime("%H:%M") if r_["started"] else "?"
            if not r_["policy"]:
                verdict = "NO POLICY — started before install; restart it"
            elif not r_["current"]:
                verdict = "older policy — restart to pick up changes"
            else:
                verdict = "ok"
            print(f"  {r_['project'][:38]:38} started {started}  {verdict}")

    print(
        "\nThe policy is injected once, at session start. A session that was already "
        "running\nwhen the plugin changed keeps whatever it started with until you "
        "restart it or /clear."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
