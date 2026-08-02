#!/usr/bin/env python3
"""Classify already-recorded evidence by Naur's criteria, to see what the model is made of.

The telemetry measures how often the model *could* change an answer (~0.5% of turns). This
asks the complementary question: what kind of observation is the model actually built from?

If it is nearly all term-use, then on Naur's argument laconic has been modelling vocabulary
rather than theory — and a model of vocabulary being rarely applicable is not a surprising
result, it is the expected one. If a real share is theory-evidence, then the recording
practice was already better than the schema, and marking it explicitly is worth doing.

Classified by a judge rather than by hand: most of these lines were written by the same agent
that would be grading them.

Report-only by default. `--apply` rewrites the evidence lines in place, which edits recorded
history on the strength of a judgement, so it is never the default.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL.parent / "tools"))
from laconic_index import parse_frontmatter  # noqa: E402
from laconic_lint import read_evidence  # noqa: E402
from laconic_record import KIND_RE  # noqa: E402

BATCH = 20
CALL_TIMEOUT = 600

INSTRUCTION = """\
Each item below is one recorded observation about what a software engineer understands.
Classify each into exactly one category:

  term          they used a term correctly and unprompted, where misuse would have shown
  world         they explained how a solution relates to the real-world affairs it handles
  justification they explained or challenged WHY a part is the way it is
  modification  they responded constructively to a demand for change — proposed, accepted or
                rejected a modification in a way that fitted the existing design

The last three are Peter Naur's criteria for possessing the "theory" of a system; the first
is mere vocabulary. Choose the STRONGEST category the observation actually supports. When an
observation only records that someone said a word, it is `term`. Be strict.

Reply with one line of JSON per item and nothing else:
{"n": <item number>, "kind": "term"|"world"|"justification"|"modification"}
"""


def collect(home):
    rows = []
    for path in sorted((home / "concepts").glob("*.md")):
        meta = parse_frontmatter(path)
        if not meta:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(read_evidence(text)):
            body = line.split(":", 1)[-1].strip()
            if KIND_RE.match(body):
                continue  # already classified
            cid = meta.get("id", path.stem)
            key = hashlib.sha256(f"{cid}\0{body}".encode("utf-8")).hexdigest()
            rows.append({
                "id": cid,
                "index": i,
                "text": body,
                "key": key,
                "projects": meta.get("projects", []),
                "path": path,
            })
    return rows


def parse(text, size):
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
    ap.add_argument("--apply", action="store_true", help="rewrite evidence lines in place")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workdir", default=str(EVAL / "runs" / "evidence-v2"))
    args = ap.parse_args()

    home = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    rows = collect(home)
    if not rows:
        print("nothing unclassified")
        return 0
    batches = [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]
    print(f"{len(rows)} unclassified lines in {len(batches)} batches")
    if args.dry_run:
        return 0

    workdir = Path(args.workdir)
    (workdir / "model-empty" / "concepts").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LACONIC_HOME"] = str(workdir / "model-empty")
    env["LACONIC_NO_PUSH"] = "1"

    verdicts = {}
    verdict_rows = []
    for bi, batch in enumerate(batches, 1):
        digest = hashlib.sha256(
            "\n".join(row["key"] for row in batch).encode("utf-8")
        ).hexdigest()[:12]
        stem = f"batch-{bi:03d}-{digest}"
        raw = workdir / f"{stem}.txt"
        manifest = workdir / f"{stem}.input.jsonl"
        manifest.write_text(
            "".join(
                json.dumps({
                    "n": i,
                    "id": row["id"],
                    "key": row["key"],
                    "text": row["text"],
                }, ensure_ascii=False) + "\n"
                for i, row in enumerate(batch, 1)
            ),
            encoding="utf-8",
        )
        text = raw.read_text(encoding="utf-8") if raw.exists() else ""
        got = parse(text, len(batch)) if text else {}
        if len(got) == len(batch):
            print(f"  [batch {bi}/{len(batches)}] cached", flush=True)
        else:
            if raw.exists():
                print(
                    f"  [batch {bi}/{len(batches)}] ignoring incomplete cached response "
                    f"({len(got)}/{len(batch)})",
                    flush=True,
                )
            body = "\n".join(f'{i}. "{r["text"][:400]}"' for i, r in enumerate(batch, 1))
            started = time.monotonic()
            proc = subprocess.run(
                ["claude", "-p", INSTRUCTION + "\n" + body],
                capture_output=True, text=True, env=env, cwd=str(EVAL),
                timeout=CALL_TIMEOUT, check=False,
            )
            text = proc.stdout
            print(f"  [batch {bi}/{len(batches)}] {time.monotonic() - started:.0f}s", flush=True)
            got = parse(text, len(batch))
            if proc.returncode != 0 or len(got) != len(batch):
                diagnostic = (proc.stderr or proc.stdout).strip().splitlines()
                detail = diagnostic[0][:240] if diagnostic else "no diagnostic"
                print(
                    f"    error: judge returned {proc.returncode}; "
                    f"{len(got)}/{len(batch)} parsed — {detail}",
                    file=sys.stderr,
                )
                return 1
            raw.write_text(text, encoding="utf-8")
        if len(got) != len(batch):
            print(f"    warning: {len(got)}/{len(batch)} parsed", flush=True)
        for i, row in enumerate(batch, 1):
            if i in got:
                kind = got[i].get("kind")
                if kind not in {"term", "world", "justification", "modification"}:
                    continue
                verdicts[(row["id"], row["index"])] = kind
                verdict_rows.append({
                    "id": row["id"],
                    "index": row["index"],
                    "key": row["key"],
                    "projects": row["projects"],
                    "kind": kind,
                })

    (workdir / "verdicts.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in verdict_rows),
        encoding="utf-8",
    )

    counts = Counter(verdicts.values())
    total = len(verdicts)
    print(f"\n{total} classified\n")
    for kind, n in counts.most_common():
        print(f"  {kind:<14} {n:4}  {100 * n / total:5.1f}%")
    theory = sum(n for k, n in counts.items() if k in {"world", "justification", "modification"})
    print(f"\n  theory-evidence: {theory}/{total} ({100 * theory / total:.1f}%)")

    if not args.apply:
        print("\n(report only — pass --apply to write these kinds into the model)")
        return 0

    by_path = {}
    for (cid, idx), kind in verdicts.items():
        by_path.setdefault(cid, {})[idx] = kind
    written = 0
    for cid, marks in by_path.items():
        path = home / "concepts" / f"{cid}.md"
        lines = path.read_text(encoding="utf-8").splitlines()
        seen = -1
        for li, line in enumerate(lines):
            if not line.startswith("  - "):
                continue
            seen += 1
            if seen not in marks:
                continue
            head, _, body = line.partition(": ")
            if KIND_RE.match(body.strip()):
                continue
            lines[li] = f"{head}: [{marks[seen]}] {body.strip()}"
            written += 1
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nmarked {written} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
