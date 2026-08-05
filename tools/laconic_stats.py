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
    ap.add_argument(
        "--maintenance", action="store_true",
        help="report silent-maintenance trigger yield and exit",
    )
    ap.add_argument(
        "--routing", action="store_true",
        help="report prompt routing frequency and context cost, then exit",
    )
    args = ap.parse_args()

    if args.routing:
        rows = load(home() / "routing-telemetry.jsonl")
        if args.since:
            rows = [row for row in rows if row.get("date", "") >= args.since]
        if not rows:
            print("no routing observations yet")
            return 0
        routed = [row for row in rows if row.get("domains")]
        counts = Counter(domain for row in routed for domain in row.get("domains", []))
        resolved = [row for row in routed if row.get("answer_domains") is not None]
        used = [row for row in resolved if row.get("answer_domains")]
        miss_resolved = [row for row in rows
                         if row.get("routing_version", 1) >= 2
                         and row.get("missed_domains") is not None]
        missed_rows = [row for row in miss_resolved if row.get("missed_domains")]
        missed = Counter(
            domain for row in missed_rows for domain in row.get("missed_domains", [])
        )
        chars = [int(row.get("chars", 0)) for row in rows]
        print(f"{len(rows)} prompts observed")
        print(f"  routed: {len(routed)} ({100 * len(routed) / len(rows):.1f}%)")
        print(f"  mean context per prompt: {sum(chars) / len(chars):.0f} chars")
        print(f"  maximum context: {max(chars)} chars")
        if resolved:
            print(f"  answer mentioned a selected domain: {len(used)}/{len(resolved)} "
                  f"({100 * len(used) / len(resolved):.1f}%)")
        if miss_resolved:
            print(f"  answer surfaced an unselected domain: "
                  f"{len(missed_rows)}/{len(miss_resolved)} "
                  f"({100 * len(missed_rows) / len(miss_resolved):.1f}%)")
        print(f"  selected domains: {dict(counts.most_common(10))}")
        if missed:
            print(f"  possible missed domains: {dict(missed.most_common(10))}")
        print("\nAnswer vocabulary is a routing proxy, not proof; inspect repeated misses before tuning.")
        return 0

    if args.maintenance:
        rows = load(home() / "maintenance-telemetry.jsonl")
        if args.since:
            rows = [row for row in rows if row.get("date", "") >= args.since]
        if not rows:
            print("no maintenance observations yet")
            return 0
        signals = Counter(row.get("signal", "unknown") for row in rows)
        recorded = sum(bool(row.get("recorded")) for row in rows)
        print(f"{len(rows)} silent maintenance passes")
        print(f"  produced a model record: {recorded} ({100 * recorded / len(rows):.1f}%)")
        print(f"  left unchanged: {len(rows) - recorded}")
        print(f"  trigger classes: {dict(signals.most_common())}")
        print("\nThis is trigger yield, not recall: missed knowledge-bearing turns are not observed.")
        return 0

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
