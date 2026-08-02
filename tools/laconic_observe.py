#!/usr/bin/env python3
"""Record how often the knowledge model could have changed the answer.

design/06-measurement.md established that only ~5% of concept-touching turns are
knowledge-state-discriminating, from a historical corpus. This measures the live
distribution instead: every turn, in real sessions, with no corpus and no benchmark.

What counts as applicable. With an empty model the injected policy says "assume nothing
about what the user knows", whose safe default is to explain. So the model only *changes*
the writing when it says do **not** explain — that is `verified` (use freely, never define)
and `familiar` (a short gloss on first use only). A turn touching an `unknown` or `exposed`
concept produces the same behaviour with or without the model, so it is recorded but not
counted as discriminating.

Privacy. No prompt text, no response text, ever. Concept ids, states, booleans and lengths
only. The log is gitignored and stays on this machine: it is a measurement of usage, and the
rule that keeps confidential material out of `evidence` applies at least as hard here.

Runs inside the Stop hook only when `LACONIC_TELEMETRY=1`, so it must be fast and must
never raise. Telemetry is opt-in: local-only and content-free is still observation, and
installing a writing policy is not consent to behavioral measurement.
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from laconic_index import get_section, load_concepts  # noqa: E402

# States whose guidance differs from the no-model default of "explain it".
DISCRIMINATING = {"verified", "familiar"}

# Same definitional forms the offline scorer uses, so live and offline numbers are
# comparable rather than two different measurements wearing one name.
DEFINE_TEMPLATES = [
    r"{t}\s+(?:is|are|means|refers to|stands for)\b",
    r"{t}\s*[—:-]\s*(?:a|an|the)\b",
    r"{t}\s*\((?:i\.e\.|that is|short for|which)\b",
    r"(?:known as|called|termed)\s+{t}\b",
    r"\b(?:a|an|the)\s+{t}\s+is\b",
]

GENERIC = {
    "the", "and", "for", "with", "pattern", "model", "structure", "procedure",
    "dependency", "questions", "based", "into", "from", "that", "this", "using",
    "value", "values", "state", "states", "data", "file", "files", "code",
}


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def terms(cid):
    words = [w for w in cid.split("-") if len(w) > 2 and w not in GENERIC]
    if len(words) < 2:
        return []
    return [r"[\s\-_]+".join(re.escape(w[:8]) + r"\w*" for w in words)]


def last_assistant_text(transcript):
    """All assistant prose since the last real user message — one turn's answer.

    Not merely the final assistant message: an agentic turn interleaves short preambles with
    tool calls, so the answer is spread across several messages and the last one alone is
    often a one-line lead-in. Scanned backwards and stopped at the user message, because
    transcripts reach megabytes and this runs on every turn.
    """
    try:
        lines = Path(transcript).read_text(errors="ignore").splitlines()
    except OSError:
        return None
    chunks = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        kind = d.get("type")
        if kind == "user" and not d.get("isMeta"):
            content = d.get("message", {}).get("content")
            # Tool results are recorded as `user` entries; only a real prompt ends the turn.
            if isinstance(content, str) or (
                isinstance(content, list)
                and any(b.get("type") == "text" for b in content if isinstance(b, dict))
            ):
                break
            continue
        if kind != "assistant":
            continue
        content = d.get("message", {}).get("content")
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
            if text.strip():
                chunks.append(text)
    return "\n".join(reversed(chunks)) if chunks else None


def observe(transcript, session_id):
    text = last_assistant_text(transcript)
    if not text:
        return None
    concepts = load_concepts()
    if not concepts:
        return None

    touched = []
    for c in concepts:
        pats = terms(c["id"])
        if not pats:
            continue
        if not any(re.search(rf"\b{p}\b", text, re.I) for p in pats):
            continue
        defined = any(
            re.search(tpl.format(t=p), text, re.I)
            for p in pats for tpl in DEFINE_TEMPLATES
        )
        # A recorded gap overrides the state: the concept reads `verified` but a named part
        # of it is not established, so explaining that part is correct rather than redundant.
        gap = bool(get_section_of(c["id"]))
        touched.append({"id": c["id"], "state": c["state"], "defined": defined, "gap": gap})

    return {
        "date": date.today().isoformat(),
        "session": session_id,
        "chars": len(text),
        "touched": touched,
        "discriminating": sum(
            1 for t in touched if t["state"] in DISCRIMINATING and not t["gap"]
        ),
    }


def get_section_of(cid):
    path = home() / "concepts" / f"{cid}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    end = text.find("\n---", 3)
    return get_section(text[end + 4 :], "What has not been established") if end != -1 else ""


def main():
    if os.environ.get("LACONIC_TELEMETRY") != "1":
        return 0
    if len(sys.argv) < 3:
        return 0
    row = observe(sys.argv[1], sys.argv[2])
    if row is None:
        return 0
    log = home() / "telemetry.jsonl"
    try:
        # Append-only, one short line: concurrent turns cannot interleave a write this small,
        # and the log is never read back by anything on the hot path.
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # This runs in the Stop hook on every turn. A measurement must never break the thing
        # it measures.
        sys.exit(0)
