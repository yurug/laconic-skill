#!/usr/bin/env python3
"""One status line proving laconic is live, and showing what it routed for this prompt.

The plugin was built to be silent: every hook emits nothing on success, and the injected
policy tells the agent not to mention it. After several weeks that is indistinguishable
from a plugin that never loaded. This is the missing surface -- the only component that
addresses the user rather than the agent.

Claude Code runs this on every render, so it must stay cheap and must never fail loudly:
a statusline that throws leaves the user staring at an error where the reassurance was
supposed to be. Every lookup below is a stat or a bounded tail, and any failure degrades
to a shorter line rather than an exception. It deliberately does not import
laconic_index: loading and parsing 99 concept files is far too much work for a line
redrawn this often.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

HOME = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
CONCEPTS = HOME / "concepts"
# Keep the line honest about scale without listing everything: past three domains the
# line is wider than the terminal and stops being glanceable.
MAX_DOMAINS = 3
# Only the tail of the telemetry can hold the current session's most recent row, and the
# file grows without bound. 256 KiB covers days of routing at ~150 bytes a row.
TAIL_BYTES = 256 * 1024
# Transcripts open with a handful of untimestamped metadata records before the first
# real event; this is generous enough to clear them without scanning the file.
HEADER_LINES = 20


def concept_count():
    try:
        return sum(1 for _ in CONCEPTS.glob("*.md"))
    except OSError:
        return None


def model_is_clean():
    """True if lint passed since the last concept edit, False if a file changed after.

    Mirrors the stamp check in stop-check.sh rather than running the lint: this renders
    far too often to afford a Python process, and a stale stamp only ever understates
    health -- the Stop hook still blocks on a genuinely malformed model.
    """
    stamp = HOME / ".lint-ok"
    try:
        ok_at = stamp.stat().st_mtime
    except OSError:
        return None
    try:
        newest = max((p.stat().st_mtime for p in CONCEPTS.glob("*.md")), default=0)
    except OSError:
        return None
    return newest <= ok_at


def session_hash(session_id):
    """The same truncated digest route-knowledge.sh writes, so rows can be matched back."""
    import hashlib

    return hashlib.sha256(session_id.encode()).hexdigest()[:20] if session_id else ""


def routed_domains(session_id):
    """Domains selected for the most recent prompt of this session.

    Two sources, because they cover different halves of a turn: the pending file exists
    while the turn is in flight, and the telemetry row lands when Stop resolves it. Read
    the pending file first so the line updates as soon as the prompt is submitted.
    """
    digest = session_hash(session_id)
    if not digest:
        return None
    pending = HOME / ".routing-pending" / f"{digest}.json"
    try:
        return json.loads(pending.read_text(encoding="utf-8")).get("domains") or []
    except (OSError, ValueError):
        pass
    log = HOME / "routing-telemetry.jsonl"
    try:
        with log.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("session") == digest:
            return row.get("domains") or []
    return None


def policy_is_stale(session_id):
    """True when this session started before the plugin config last changed.

    The policy is injected once, at SessionStart. A session left open across a plugin
    change keeps the text it started with, so an approved fix can sit unapplied for days
    without anything saying so -- the failure this line exists to make visible.
    """
    settings = Path.home() / ".claude" / "settings.json"
    try:
        changed_at = settings.stat().st_mtime
    except OSError:
        return False
    if not session_id:
        return False
    started = session_started(session_id)
    return bool(started and started < changed_at)


def session_started(session_id):
    """When this session began, as an epoch float, from its first transcript record.

    Not taken from the file's stat: the transcript is appended to all session long, so
    mtime is always "now", and on Linux ctime tracks every write too. Both would report
    a nine-day-old session as fresh -- exactly the case this needs to catch. Only the
    first line is read.
    """
    projects = Path.home() / ".claude" / "projects"
    try:
        matches = list(projects.glob(f"*/{session_id}.jsonl"))
    except OSError:
        return None
    if not matches:
        return None
    stamp = None
    try:
        with matches[0].open(encoding="utf-8", errors="replace") as handle:
            # The file opens with untimestamped metadata records (last-prompt, mode,
            # permission-mode), so the first line is not the first event. Scan a bounded
            # prefix rather than the whole transcript, which runs to hundreds of MB.
            for _ in range(HEADER_LINES):
                line = handle.readline()
                if not line:
                    break
                try:
                    stamp = json.loads(line).get("timestamp")
                except ValueError:
                    continue
                if stamp:
                    break
    except OSError:
        return None
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def render(session_id):
    parts = []
    count = concept_count()
    parts.append(f"laconic {count}c" if count is not None else "laconic")

    domains = routed_domains(session_id)
    if domains:
        shown = ", ".join(domains[:MAX_DOMAINS])
        if len(domains) > MAX_DOMAINS:
            shown += f" +{len(domains) - MAX_DOMAINS}"
        parts.append(shown)

    if policy_is_stale(session_id):
        parts.append("! policy stale — /clear to refresh")
    elif model_is_clean() is False:
        parts.append("! model unlinted")

    return "▸ " + " · ".join(parts)


def main():
    session_id = ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        # Valid JSON is not necessarily an object: a bare list parses fine and then has
        # no .get, which would take the whole line down over malformed input.
        if isinstance(payload, dict):
            session_id = payload.get("session_id") or ""
    except (ValueError, OSError):
        pass
    try:
        print(render(session_id))
    except Exception:
        # Never let this component be the thing that breaks the terminal.
        print("▸ laconic")
    return 0


if __name__ == "__main__":
    sys.exit(main())
