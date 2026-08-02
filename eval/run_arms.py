#!/usr/bin/env python3
"""Run the corpus through each arm and save the raw outputs.

Arms differ only in what the SessionStart hook finds in LACONIC_HOME, so the injection under
test is the real one rather than a reimplementation of it:

  policy      the policy with an empty model -- "assume nothing about what the user knows"
  model       the policy with a populated model, the thing whose value is in question

The decisive comparison is exactly these two. A third arm with no laconic at all needs
`--bare`, which skips keychain reads and so requires ANTHROPIC_API_KEY; it is not the
question the review poses, so it is left out rather than half-done.

The model arm runs against a *copy*. The Stop hook fires in -p mode as well, so an eval
against the live model could record evidence into the model it is measuring -- the outputs
would then depend on how far through the run you were.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REAL_MODEL = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")

# Long enough for a substantive answer, short enough that one stuck call cannot stall a run.
CALL_TIMEOUT = 300


def load_prompts(paths):
    rows = []
    for path in paths:
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("provenance", "mined")
            row["id"] = f"{path.stem}-{i:03d}"
            rows.append(row)
    return rows


def build_arms(workdir):
    """An empty model directory and a frozen copy of the real one."""
    empty = workdir / "model-empty" / "concepts"
    empty.mkdir(parents=True, exist_ok=True)

    populated = workdir / "model-real"
    if populated.exists():
        shutil.rmtree(populated)
    populated.mkdir(parents=True)
    (populated / "concepts").mkdir()
    for f in (REAL_MODEL / "concepts").glob("*.md"):
        shutil.copy2(f, populated / "concepts" / f.name)
    # No .git in the copy: git_commit() would lazily init one and the Stop hook's lint stamp
    # would start writing into it. The copy is read-only input to the experiment.
    return {"policy": empty.parent, "model": populated}


def run_one(prompt, home, cwd):
    env = dict(os.environ)
    env["LACONIC_HOME"] = str(home)
    env["LACONIC_NO_PUSH"] = "1"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, env=env, cwd=str(cwd),
            timeout=CALL_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "seconds": CALL_TIMEOUT, "output": ""}
    return {
        "ok": proc.returncode == 0,
        "error": None if proc.returncode == 0 else proc.stderr[-500:],
        "seconds": round(time.monotonic() - started, 1),
        "output": proc.stdout.strip(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(EVAL / "runs" / "latest"))
    ap.add_argument("--limit", type=int, default=None, help="first N prompts (smoke runs)")
    ap.add_argument("--arms", default="policy,model")
    ap.add_argument("--dry-run", action="store_true", help="report the plan and cost, run nothing")
    args = ap.parse_args()

    # Prefer the relevance-filtered corpus. Running against raw mined candidates measures
    # nothing -- the first smoke run scored `mentions: 0` on every output, because a prompt
    # that merely name-drops a concept gets the same answer from every arm.
    mined = EVAL / "corpus-final.jsonl"
    if not mined.exists():
        mined = EVAL / "corpus.jsonl"
        print(f"warning: {EVAL / 'corpus-final.jsonl'} absent — using unfiltered candidates, "
              f"which are known to produce no signal. Run classify.py first.", file=sys.stderr)
    prompts = load_prompts([mined, EVAL / "probes.jsonl"])
    if args.limit:
        prompts = prompts[: args.limit]
    arms = [a for a in args.arms.split(",") if a]
    if not prompts:
        print("no prompts — run mine_corpus.py first", file=sys.stderr)
        return 1

    out = Path(args.out)
    calls = len(prompts) * len(arms)
    print(f"{len(prompts)} prompts x {len(arms)} arms = {calls} calls")
    if args.dry_run:
        # Each call is a full agent turn against the user's own subscription; saying the
        # size out loud before spending it is cheaper than discovering it afterwards.
        print(f"est. {calls * 20 / 60:.0f}-{calls * 45 / 60:.0f} minutes at 20-45s per call")
        print(f"would write to {out}")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    homes = build_arms(out)
    (out / "prompts.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prompts), encoding="utf-8"
    )

    done = failed = skipped = 0
    for arm in arms:
        arm_dir = out / arm
        arm_dir.mkdir(exist_ok=True)
        for i, row in enumerate(prompts, 1):
            dest = arm_dir / f"{row['id']}.json"
            if dest.exists():
                skipped += 1
                continue
            result = run_one(row["prompt"], homes[arm], EVAL)
            result.update(id=row["id"], arm=arm, state=row["state"],
                          concepts=row["concepts"], provenance=row["provenance"])
            dest.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            done += 1
            if not result["ok"]:
                failed += 1
            print(f"  [{arm} {i}/{len(prompts)}] {row['id']} "
                  f"{'ok' if result['ok'] else 'FAIL'} {result['seconds']}s "
                  f"{len(result['output'])} chars", flush=True)

    print(f"\n{done} run, {skipped} already present, {failed} failed -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
