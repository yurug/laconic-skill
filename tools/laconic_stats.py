#!/usr/bin/env python3
"""Report what the live instrumentation has measured.

The question design/06-measurement.md leaves open: is the knowledge model applicable often
enough, in real use, to pay for the ~430 tokens it costs in every session?

The headline number is the share of turns where the model says do *not* explain something
the no-model default would have explained — `verified` or `familiar`, minus any concept
carrying a recorded gap, since a gap reinstates the explanation.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def load(path):
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def evidence_kinds():
    """Count recorded evidence by kind across the model.

    The other half of the applicability question. The live telemetry measures how often the
    model *could* change an answer; this measures what kind of observation the model is
    actually built from. If nearly all of it is term-use, then on Naur's argument the model
    records vocabulary rather than theory — and a model of vocabulary is expected to be
    applicable rarely, which is what the telemetry found.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from laconic_index import load_concepts  # noqa: PLC0415
    from laconic_lint import read_evidence  # noqa: PLC0415
    from laconic_record import EVIDENCE_KINDS, KIND_RE, THEORY_KINDS  # noqa: PLC0415

    counts = Counter()
    per_concept = Counter()
    for c in load_concepts():
        path = home() / "concepts" / f"{c['id']}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in read_evidence(text):
            m = KIND_RE.match(line.split(":", 1)[-1].strip())
            kind = m.group(1) if m and m.group(1) in EVIDENCE_KINDS else "unclassified"
            counts[kind] += 1
            if kind in THEORY_KINDS:
                per_concept[c["id"]] += 1
    return counts, per_concept, THEORY_KINDS


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=None)
    ap.add_argument("--since", default=None, help="ISO date, inclusive")
    ap.add_argument("--evidence", action="store_true", help="report evidence kinds and exit")
    args = ap.parse_args()

    if args.evidence:
        counts, per_concept, theory = evidence_kinds()
        total = sum(counts.values())
        if not total:
            print("no evidence recorded")
            return 0
        print(f"{total} evidence lines across the model\n")
        for kind, n in counts.most_common():
            mark = "  (theory)" if kind in theory else ""
            print(f"  {kind:<14} {n:5}  {100 * n / total:5.1f}%{mark}")
        theory_n = sum(n for k, n in counts.items() if k in theory)
        print(f"\n  theory-evidence total: {theory_n} ({100 * theory_n / total:.1f}%)")
        print(f"  concepts with any theory-evidence: {len(per_concept)}")
        if counts.get("unclassified"):
            print(f"\n  {counts['unclassified']} lines predate the distinction and are")
            print("  unclassified, not `term` — conflating them would fabricate a baseline.")
        return 0

    path = Path(args.log) if args.log else home() / "telemetry.jsonl"
    rows = load(path)
    if args.since:
        rows = [r for r in rows if r.get("date", "") >= args.since]
    if not rows:
        print(f"no observations yet at {path}")
        print("laconic_observe.py runs from the Stop hook; give it some sessions.")
        return 0

    turns = len(rows)
    touching = [r for r in rows if r.get("touched")]
    discriminating = [r for r in rows if r.get("discriminating", 0) > 0]

    print(f"{turns} turns observed across {len({r.get('session') for r in rows})} sessions"
          f", {rows[0].get('date')} to {rows[-1].get('date')}\n")

    def pct(n):
        return f"{100 * n / turns:5.1f}%"

    print(f"  touched a modeled concept        {len(touching):5}  {pct(len(touching))}")
    print(f"  model would change the writing   {len(discriminating):5}  {pct(len(discriminating))}")
    print("     (verified/familiar, no recorded gap — where the model says do NOT explain,")
    print("      against a no-model default of explaining)\n")

    # The failure the model exists to prevent: explaining something the reader has.
    redundant = sum(
        1 for r in rows
        for t in r.get("touched", [])
        if t["state"] in ("verified", "familiar") and t["defined"] and not t["gap"]
    )
    print(f"  defined a verified/familiar concept anyway: {redundant}")
    print("     (the failure the model exists to prevent; nonzero means it is not landing)\n")

    states = Counter(t["state"] for r in rows for t in r.get("touched", []))
    if states:
        print("  concept touches by state:", dict(states.most_common()))
    hot = Counter(t["id"] for r in rows for t in r.get("touched", []))
    if hot:
        print("  most-touched concepts:", dict(hot.most_common(5)))

    print(f"\ncompare: the historical corpus put the discriminating rate at ~5% of "
          f"concept-touching turns (design/06-measurement.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
