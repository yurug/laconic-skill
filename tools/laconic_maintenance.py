#!/usr/bin/env python3
"""Detect when the latest direct user turn merits a silent knowledge review.

This tool never writes the model and never interprets a concept. It only gates the costly
semantic pass performed by the main agent: explicit corrections and explanations are strong
enough signals to inspect, while ordinary requests remain on the zero-cost path.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

CORRECTION_RE = re.compile(
    r"\b(?:actually|correction|instead|no|not exactly|rather|"
    r"en fait|non|pas exactement|plut[oô]t|ce n['’]est pas)\b",
    re.IGNORECASE,
)
RATIONALE_RE = re.compile(
    r"\b(?:because|the reason|so that|therefore|"
    r"parce que|la raison|afin de|donc|c['’]est pourquoi)\b",
    re.IGNORECASE,
)
RECORDER_MARKERS = ("laconic-record", "laconic_record.py")


def text_content(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block.get("text", "") for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def latest_turn(path):
    """Return the latest real user prompt and subsequent raw events."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return "", []
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except (TypeError, ValueError):
            continue
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.get("type") != "user" or event.get("isMeta"):
            continue
        text = text_content(event.get("message", {}).get("content"))
        if text.strip():
            return text.strip(), events[index + 1:]
    return "", []


def recorder_used(events):
    """Conservative raw scan: if this turn already recorded, never request another pass."""
    return any(
        marker in json.dumps(event, ensure_ascii=False)
        for event in events for marker in RECORDER_MARKERS
    )


def review_reason(text):
    if CORRECTION_RE.search(text):
        return "explicit correction"
    # A short command containing “because” is often just task rationale. Requiring some
    # substance keeps the maintenance loop for explanations that can establish knowledge.
    if len(text) >= 120 and RATIONALE_RE.search(text):
        return "explicit justification"
    return ""


def should_review(path):
    text, subsequent = latest_turn(path)
    if not text or recorder_used(subsequent):
        return ""
    return review_reason(text)


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def session_key(session_id):
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:20]


def pending_path(session_id):
    return home() / ".maintenance-pending" / f"{session_key(session_id)}.json"


def begin(path, session_id):
    """Return the review reason and, with telemetry consent, remember the trigger."""
    reason = should_review(path)
    if reason and os.environ.get("LACONIC_TELEMETRY") == "1":
        pending = pending_path(session_id)
        try:
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text(json.dumps({
                "date": date.today().isoformat(), "signal": reason,
            }) + "\n", encoding="utf-8")
        except OSError:
            pass
    return reason


def begin_text(text, session_id):
    """Prompt-hook variant: gate the current user text before the assistant turn."""
    reason = review_reason(text)
    if reason and os.environ.get("LACONIC_TELEMETRY") == "1" and session_id:
        pending = pending_path(session_id)
        try:
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text(json.dumps({
                "date": date.today().isoformat(), "signal": reason,
            }) + "\n", encoding="utf-8")
        except OSError:
            pass
    return reason


def resolve(path, session_id):
    """Record whether the agent used the recorder during its one continuation."""
    if os.environ.get("LACONIC_TELEMETRY") != "1":
        return
    pending = pending_path(session_id)
    try:
        row = json.loads(pending.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    _, events = latest_turn(path)
    row.update({
        "session": session_key(session_id),
        "recorded": recorder_used(events),
    })
    log = home() / "maintenance-telemetry.jsonl"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        pending.unlink(missing_ok=True)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript")
    parser.add_argument("--begin", metavar="SESSION")
    parser.add_argument("--resolve", metavar="SESSION")
    args = parser.parse_args()
    if args.resolve:
        resolve(args.transcript, args.resolve)
        return 0
    reason = begin(args.transcript, args.begin) if args.begin else should_review(args.transcript)
    if reason:
        print(reason)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Called from Stop: maintenance must never break or delay an ordinary answer.
        raise SystemExit(0)
