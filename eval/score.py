#!/usr/bin/env python3
"""Score arm outputs on the metrics the knowledge model is supposed to move.

Only the mechanical half lives here: metrics that are objective *given the model*, so they
can be recomputed by anyone and cannot drift with a judge's mood. The judgement half
(answer-first, mode mixing, omitted necessary context) needs a rubric pass, and the whole
thing needs a blind spot-check against the user before any of it is believed.

The central asymmetry the review names:

  verified  explaining it is the failure  -- the reader already has it
  unknown   NOT explaining it is the failure -- the reader does not

An arm that is merely shorter wins on `defines` and loses on `introduces`. Reporting both,
per state, is what separates calibration from brevity. A single "quality score" would hide
exactly the tradeoff under test.
"""

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL.parent / "tools"))
from laconic_index import STATES  # noqa: E402

# Definitional forms, anchored on the concept's own words. Deliberately narrow: a broad
# pattern would count any sentence mentioning the term and the metric would saturate.
DEFINE_TEMPLATES = [
    r"{t}\s+(?:is|are|means|refers to|stands for)\b",
    r"{t}\s*[—:-]\s*(?:a|an|the)\b",
    r"{t}\s*\((?:i\.e\.|that is|short for|which)\b",
    r"(?:known as|called|termed)\s+{t}\b",
    r"\b(?:a|an|the)\s+{t}\s+is\b",
]


def concept_terms(cid):
    """The concept id as the words a writer would actually use."""
    words = [w for w in cid.split("-") if len(w) > 2]
    if not words:
        return []
    phrase = r"[\s\-_]+".join(re.escape(w[:8]) + r"\w*" for w in words)
    # Both the full phrase and the head noun: "settlement cycles" and "cycles" in context.
    return [phrase, re.escape(words[-1][:8]) + r"\w*"]


def defines(text, cid):
    for term in concept_terms(cid):
        for tpl in DEFINE_TEMPLATES:
            if re.search(tpl.format(t=term), text, re.I):
                return True
    return False


def mentions(text, cid):
    return any(re.search(rf"\b{t}\b", text, re.I) for t in concept_terms(cid))


def load(run_dir, arm):
    rows = []
    for path in sorted((run_dir / arm).glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("ok"):
            rows.append(row)
    return rows


def summarise(rows):
    """Per-state metrics. `defines` is a failure for verified, a success for unknown; the
    table reports raw rates and leaves the sign to the reader."""
    by_state = defaultdict(list)
    for r in rows:
        by_state[r["state"]].append(r)

    out = {}
    for state, group in by_state.items():
        lengths = [len(r["output"]) for r in group]
        # A concept is "handled" only if the answer engages it at all; defining something
        # never mentioned is not possible, and counting it would flatter a silent arm.
        defined = sum(
            1 for r in group
            if any(defines(r["output"], c) for c in r["concepts"])
        )
        mentioned = sum(
            1 for r in group
            if any(mentions(r["output"], c) for c in r["concepts"])
        )
        out[state] = {
            "n": len(group),
            "median_chars": int(statistics.median(lengths)) if lengths else 0,
            "mentions": mentioned,
            "defines": defined,
            "define_rate": round(defined / len(group), 2) if group else 0.0,
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=str(EVAL / "runs" / "latest"))
    ap.add_argument("--arms", default="policy,model")
    args = ap.parse_args()

    run_dir = Path(args.run)
    arms = [a for a in args.arms.split(",") if a]
    tables = {}
    for arm in arms:
        rows = load(run_dir, arm)
        if not rows:
            print(f"no successful outputs for arm '{arm}' in {run_dir}", file=sys.stderr)
            return 1
        tables[arm] = summarise(rows)

    print(f"run: {run_dir}\n")
    header = f"{'state':<10} {'arm':<8} {'n':>4} {'median':>7} {'mentions':>9} {'defines':>8} {'rate':>6}"
    print(header)
    print("-" * len(header))
    for state in STATES:
        for arm in arms:
            s = tables[arm].get(state)
            if not s:
                continue
            print(f"{state:<10} {arm:<8} {s['n']:>4} {s['median_chars']:>7} "
                  f"{s['mentions']:>9} {s['defines']:>8} {s['define_rate']:>6.2f}")
        print()

    print("reading it:")
    print("  verified — a LOWER define rate is better calibrated (they already know it)")
    print("  unknown  — a HIGHER define rate is better calibrated (they do not)")
    print("  a model arm that is lower on both is merely terser, not better calibrated")
    print("\nmechanical only. answer-first, mode mixing and omitted context need the rubric")
    print("pass, and the whole thing needs a blind spot-check before it is believed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
