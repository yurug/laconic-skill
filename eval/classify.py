#!/usr/bin/env python3
"""Keep only the mined prompts whose ideal answer depends on the reader's knowledge state.

Keyword co-occurrence is not explanatory dependence. "What is the github repo for the battle
test knowledge base?" mentions two verified concepts and would be answered identically by
every arm; a corpus of those measures nothing, which is exactly what the first smoke run
showed (`mentions: 0` on every scored output).

The criterion is counterfactual, not topical: *would the ideal answer differ if the reader
were an expert in this concept rather than a novice?* A lookup, a task order, or a piece of
feedback answers no. That question is the whole experiment, so a prompt that answers no
cannot separate the arms and does not belong in the corpus.

Classification runs against an EMPTY model: the judge decides whether knowledge state
matters in principle, and must not see what this particular user happens to know.

Batched because a `claude -p` call costs 75-250s regardless of how little it is asked to do;
ten verdicts per call turns hours into minutes.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parent
BATCH = 10
CALL_TIMEOUT = 600

INSTRUCTION = """\
For each numbered item below, decide ONE thing:

  Would the ideal answer to this prompt be MATERIALLY DIFFERENT depending on whether the
  reader is already expert in the named concept, versus meeting it for the first time?

Answer yes only when the answer's *content* would change — an expert needs no introduction
to the concept, a novice does. Answer no when the prompt is a lookup, a task order, a status
report, feedback, or anything whose good answer is the same either way.

The concept merely appearing in the prompt is NOT sufficient. Be strict: when unsure, say no.

Reply with one line of JSON per item and nothing else:
{"n": <item number>, "discriminating": true|false, "why": "<8 words max>"}
"""


def load_candidates(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def build_batch(rows):
    parts = []
    for i, r in enumerate(rows, 1):
        prompt = " ".join(r["prompt"].split())[:600]
        parts.append(f'{i}. concept: {", ".join(r["concepts"])}\n   prompt: "{prompt}"')
    return INSTRUCTION + "\n" + "\n\n".join(parts)


def parse_verdicts(text, size):
    """Take the JSON objects out of whatever the model wrapped them in."""
    out = {}
    for m in re.finditer(r'\{[^{}]*"n"\s*:\s*(\d+)[^{}]*\}', text):
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            continue
        n = obj.get("n")
        if isinstance(n, int) and 1 <= n <= size:
            out[n] = obj
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=str(EVAL / "corpus.jsonl"))
    ap.add_argument("--out", default=str(EVAL / "relevance.jsonl"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"no candidates at {src} — run mine_corpus.py first", file=sys.stderr)
        return 1
    rows = load_candidates(src)
    if args.limit:
        rows = rows[: args.limit]

    batches = [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]
    print(f"{len(rows)} candidates in {len(batches)} batches of {BATCH}")
    if args.dry_run:
        print(f"est. {len(batches) * 100 / 60:.0f}-{len(batches) * 250 / 60:.0f} minutes")
        print("\n--- first batch prompt ---")
        print(build_batch(batches[0])[:1200])
        return 0

    # Empty model: the judge rules on whether knowledge state matters in principle, so it
    # must not be shown what this user knows.
    workdir = EVAL / "runs" / "classify"
    (workdir / "model-empty" / "concepts").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LACONIC_HOME"] = str(workdir / "model-empty")
    env["LACONIC_NO_PUSH"] = "1"

    verdicts = []
    for bi, batch in enumerate(batches, 1):
        raw_path = workdir / f"batch-{bi:03d}.txt"
        if raw_path.exists():
            text = raw_path.read_text(encoding="utf-8")
            print(f"  [batch {bi}/{len(batches)}] cached")
        else:
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    ["claude", "-p", build_batch(batch)],
                    capture_output=True, text=True, env=env, cwd=str(EVAL),
                    timeout=CALL_TIMEOUT, check=False,
                )
            except subprocess.TimeoutExpired:
                print(f"  [batch {bi}/{len(batches)}] TIMEOUT, skipped", flush=True)
                continue
            text = proc.stdout
            raw_path.write_text(text, encoding="utf-8")
            print(f"  [batch {bi}/{len(batches)}] {time.monotonic() - started:.0f}s", flush=True)

        got = parse_verdicts(text, len(batch))
        if len(got) != len(batch):
            # Never silently drop: an unparsed verdict is a candidate with no ruling, and
            # treating that as "not discriminating" would quietly shrink the corpus.
            print(f"    warning: {len(got)}/{len(batch)} verdicts parsed", flush=True)
        for i, row in enumerate(batch, 1):
            v = got.get(i)
            verdicts.append({
                **row,
                "discriminating": bool(v and v.get("discriminating")),
                "why": (v or {}).get("why", "unparsed"),
                "ruled": v is not None,
            })

    out = Path(args.out)
    out.write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts), encoding="utf-8"
    )
    kept = [v for v in verdicts if v["discriminating"]]
    unruled = [v for v in verdicts if not v["ruled"]]

    # The corpus the arms actually run against. Every verdict is kept in relevance.jsonl so
    # a dropped prompt can be inspected rather than taken on trust.
    final = EVAL / "corpus-final.jsonl"
    final.write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in kept), encoding="utf-8"
    )
    print(f"\n{len(kept)}/{len(verdicts)} discriminating")
    if unruled:
        print(f"{len(unruled)} unruled (no verdict parsed) — counted as not discriminating")
    from collections import Counter
    print("by state:", dict(Counter(v["state"] for v in kept)))
    print(f"wrote {out} (all verdicts) and {final} (the corpus arms run against)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
