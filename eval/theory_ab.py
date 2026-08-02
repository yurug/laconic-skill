#!/usr/bin/env python3
"""Blinded response A/B: compact policy alone versus policy plus prior project theory.

Both arms rewrite the same original project-grounded answer, isolating communication from
tool use and file discovery. Real prompts, answers, and observations are sent externally only
with --generate/--judge; the default is a local dry run. Outputs remain under eval/runs/.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(EVAL))
from mine_corpus import (  # noqa: E402
    HARNESS, MAX_CHARS, MIN_CHARS, SKIP_PREFIXES, TAG_HEAVY, TRANSCRIPTS,
)
from theory_relevance import wilson  # noqa: E402

CALL_TIMEOUT = 600
JUDGE_BATCH = 2
THEORY_LIMIT = 8

REWRITE = """\
Rewrite the draft as the final response to the user request. Preserve every material fact,
decision, warning, and completed action from the draft. Improve only communication: lead with
the outcome, remove redundant explanation, keep necessary recovery context, and calibrate
terminology to the reader. Do not mention the draft, this experiment, or reader-model evidence.

USER REQUEST
{prompt}

PROJECT-GROUNDED DRAFT
{draft}
"""

JUDGE = """\
You are judging two rewrites of the same project-grounded draft for the same reader. The
listed observations are the only demonstrated reader understanding you may assume.

Choose A, B, or tie using all four criteria:
1. preserves the draft's material facts, decisions, warnings, and completed actions;
2. calibrates to what the observations do and do not establish;
3. avoids redundant explanation and unsupported reader assumptions;
4. is direct and useful for the request.

Arm labels are blinded. Do not reward an answer merely for repeating the observations.
Separately flag either arm that loses material content or makes an unsupported assumption.

Reply with one JSON object per item and nothing else:
{"n": <number>, "winner": "A"|"B"|"tie",
 "material_loss": ["A"|"B"], "unsupported_assumption": ["A"|"B"],
 "why": "<16 words max>"}
"""


def compact_policy():
    source = (ROOT / "hooks-handlers" / "inject-policy.sh").read_text(encoding="utf-8")
    match = re.search(r"<<'POLICY_EOF'\n(.*?)\nPOLICY_EOF", source, re.S)
    if not match:
        raise RuntimeError("could not extract the SessionStart compact policy")
    return match.group(1)


def user_prompt(event):
    if event.get("type") != "user" or event.get("isMeta"):
        return None
    content = event.get("message", {}).get("content")
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not MIN_CHARS <= len(text) <= MAX_CHARS or text.startswith(SKIP_PREFIXES):
        return None
    if len(TAG_HEAVY.findall(text)) >= 3 or HARNESS.match(text):
        return None
    return text


def assistant_text(event):
    if event.get("type") != "assistant":
        return ""
    content = event.get("message", {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block.get("text", "").strip()
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
        and block.get("text", "").strip()
    )


def recover_draft(row, transcripts=TRANSCRIPTS):
    """Last assistant text before the next real prompt in the source transcript."""
    path = transcripts / row["source"]
    active, answers = False, []
    try:
        lines = path.open(errors="ignore")
    except OSError:
        return ""
    with lines:
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            prompt = user_prompt(event)
            if not active:
                if prompt == row["prompt"]:
                    active = True
                continue
            if prompt is not None:
                break
            answer = assistant_text(event)
            if answer:
                answers.append(answer)
    return answers[-1] if answers else ""


def load_cases(verdict_path, transcripts=TRANSCRIPTS):
    rows = [json.loads(line) for line in verdict_path.read_text(encoding="utf-8").splitlines()]
    cases = []
    for row in rows:
        if not row.get("ruled") or not row.get("theory_discriminating"):
            continue
        draft = recover_draft(row, transcripts)
        if not draft:
            continue
        theory = row["theory"][:THEORY_LIMIT]
        key = hashlib.sha256(json.dumps({
            "prompt": row["prompt"], "draft": draft, "theory": theory,
        }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        cases.append({**row, "draft": draft, "theory": theory, "key": key})
    cases.sort(key=lambda case: case["key"])
    for index, case in enumerate(cases):
        case["theory_label"] = "A" if index % 2 == 0 else "B"
    return cases


def theory_context(case):
    lines = ["Prior understanding demonstrated by this reader:"]
    for item in case["theory"]:
        lines.append(f'- [{item["kind"]}] {item["concept"]}: {item["observation"]}')
    lines.append("Use this only to omit or compress established background; infer nothing else.")
    return "\n".join(lines)


def call_claude(prompt, system, empty_home):
    env = dict(os.environ)
    env.update(LACONIC_HOME=str(empty_home), LACONIC_NO_PUSH="1")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["claude", "-p", "--safe-mode", "--tools", "", "--no-session-persistence",
             "--append-system-prompt", system, prompt],
            capture_output=True, text=True, env=env, cwd=str(EVAL),
            timeout=CALL_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if proc.returncode != 0 or not proc.stdout.strip():
        diagnostic = (proc.stderr or proc.stdout).strip().splitlines()
        return None, diagnostic[0][:240] if diagnostic else f"exit {proc.returncode}"
    return proc.stdout.strip(), f"{time.monotonic() - started:.0f}s"


def cached_call(run_dir, category, name, prompt, system, empty_home):
    payload = json.dumps({"prompt": prompt, "system": system}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    directory = run_dir / category
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / f"{name}-{digest}.txt"
    manifest = directory / f"{name}-{digest}.input.json"
    manifest.write_text(payload + "\n", encoding="utf-8")
    if raw.exists() and raw.read_text(encoding="utf-8").strip():
        return raw.read_text(encoding="utf-8").strip(), "cached"
    output, status = call_claude(prompt, system, empty_home)
    if output is not None:
        raw.write_text(output + "\n", encoding="utf-8")
    return output, status


def generate(cases, run_dir):
    empty_home = run_dir / "model-empty"
    (empty_home / "concepts").mkdir(parents=True, exist_ok=True)
    policy = compact_policy()
    outputs = []
    for number, case in enumerate(cases, 1):
        row = {
            "key": case["key"], "prompt": case["prompt"], "profile": case["theory"],
            "theory_label": case["theory_label"],
        }
        prompt = REWRITE.format(prompt=case["prompt"], draft=case["draft"])
        for arm, extra in (("policy", ""), ("theory", "\n\n" + theory_context(case))):
            output, status = cached_call(
                run_dir, "generation", f'{case["key"][:12]}-{arm}', prompt,
                policy + extra, empty_home,
            )
            print(f"  [generate {number}/{len(cases)} {arm}] {status}", flush=True)
            if output is None:
                return None
            row[f"{arm}_output"] = output
        outputs.append(row)
    write_jsonl(run_dir / "outputs.jsonl", outputs)
    return outputs


def blind_pair(row, swapped=False):
    theory_first = row["theory_label"] == "A"
    if swapped:
        theory_first = not theory_first
    labels = {"A": "theory" if theory_first else "policy",
              "B": "policy" if theory_first else "theory"}
    return labels, labels["A"], labels["B"]


def judge_prompt(batch, swapped=False):
    parts = [JUDGE]
    for number, row in enumerate(batch, 1):
        labels, arm_a, arm_b = blind_pair(row, swapped)
        evidence = "\n".join(
            f'      {i}. [{item["kind"]}] {item["concept"]}: {item["observation"]}'
            for i, item in enumerate(row["profile"], 1)
        )
        parts.append(
            f'ITEM {number}\nREQUEST:\n{row["prompt"]}\n\n'
            f'DEMONSTRATED UNDERSTANDING:\n{evidence}\n\n'
            f'ANSWER A:\n{row[f"{arm_a}_output"]}\n\n'
            f'ANSWER B:\n{row[f"{arm_b}_output"]}'
        )
    return "\n\n".join(parts)


def parse_judgments(text, size):
    out = {}
    for match in re.finditer(r'\{[^{}]*"n"\s*:\s*(\d+)[^{}]*\}', text):
        try:
            item = json.loads(match.group(0))
        except ValueError:
            continue
        n = item.get("n")
        if not isinstance(n, int) or not 1 <= n <= size or item.get("winner") not in {"A", "B", "tie"}:
            continue
        valid = True
        for field in ("material_loss", "unsupported_assumption"):
            values = item.get(field)
            if not isinstance(values, list) or any(v not in {"A", "B"} for v in values):
                valid = False
        if valid:
            out[n] = item
    return out


def judge(outputs, run_dir, swapped=False):
    empty_home = run_dir / "judge-empty"
    (empty_home / "concepts").mkdir(parents=True, exist_ok=True)
    rulings = []
    batches = [outputs[i:i + JUDGE_BATCH] for i in range(0, len(outputs), JUDGE_BATCH)]
    for number, batch in enumerate(batches, 1):
        prompt = judge_prompt(batch, swapped)
        result, status = cached_call(
            run_dir, "judge-swapped" if swapped else "judge", f"batch-{number:03d}", prompt,
            "Judge only by the supplied rubric. Do not use tools.", empty_home,
        )
        print(f"  [judge {number}/{len(batches)}] {status}", flush=True)
        if result is None:
            return None
        parsed = parse_judgments(result, len(batch))
        if len(parsed) != len(batch):
            print(f"error: judge batch parsed {len(parsed)}/{len(batch)}", file=sys.stderr)
            return None
        for i, row in enumerate(batch, 1):
            ruling = parsed[i]
            labels, _, _ = blind_pair(row, swapped)
            winner = "tie" if ruling["winner"] == "tie" else labels[ruling["winner"]]
            loss = [labels[label] for label in ruling["material_loss"]]
            unsupported = [labels[label] for label in ruling["unsupported_assumption"]]
            # A treatment answer with a guardrail failure cannot count as a treatment win.
            if winner == "theory" and ("theory" in loss or "theory" in unsupported):
                winner = "policy"
            rulings.append({
                "key": row["key"], "winner": winner, "material_loss": loss,
                "unsupported_assumption": unsupported, "why": ruling.get("why", ""),
            })
    write_jsonl(run_dir / ("judgments-swapped.jsonl" if swapped else "judgments.jsonl"), rulings)
    return rulings


def crossover_report(original, swapped):
    other = {row["key"]: row for row in swapped}
    stable = reversed_preference = tie_involved = 0
    for row in original:
        second = other.get(row["key"])
        if not second or "tie" in {row["winner"], second["winner"]}:
            tie_involved += 1
        elif row["winner"] == second["winner"]:
            stable += 1
        else:
            reversed_preference += 1
    print(
        f"cross-over stability: {stable} same-arm, {reversed_preference} flipped-arm, "
        f"{tie_involved} tie-involved"
    )


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def report(rulings, cases, diagnostic=False):
    wins = sum(row["winner"] == "theory" for row in rulings)
    losses = sum(row["winner"] == "policy" for row in rulings)
    ties = sum(row["winner"] == "tie" for row in rulings)
    low, high = wilson(wins, wins + losses)
    theory_unsupported = sum("theory" in row["unsupported_assumption"] for row in rulings)
    policy_unsupported = sum("policy" in row["unsupported_assumption"] for row in rulings)
    context_chars = [len(theory_context(case)) for case in cases]
    print(f"\ntheory wins {wins}, policy wins {losses}, ties {ties}")
    print(f"theory win probability among decisive pairs: {100*wins/(wins+losses):.1f}% "
          f"(95% Wilson {100*low:.1f}%–{100*high:.1f}%)" if wins + losses else "no decisive pairs")
    print(f"unsupported assumptions: theory {theory_unsupported}, policy {policy_unsupported}")
    print(f"mean treatment context: {sum(context_chars)//len(context_chars)} chars; "
          f"amortized at 6.83% applicability: {sum(context_chars)/len(context_chars)*0.0683:.0f} chars/turn")
    if diagnostic:
        print("decision: DIAGNOSTIC ONLY — primary result remains fixed")
    elif theory_unsupported > policy_unsupported:
        print("decision: BLOCK — treatment increased unsupported assumptions")
    elif low > 0.5:
        print("decision: ADVANCE to independent replication and implementation design")
    elif high <= 0.5:
        print("decision: FALSIFIED as a communication improvement")
    else:
        print("decision: INCONCLUSIVE — expand or independently judge; do not tune on this set")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=str(EVAL / "runs" / "theory-ab"))
    parser.add_argument("--source", default=str(EVAL / "runs" / "theory-relevance" / "verdicts.jsonl"))
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument(
        "--swap-judge", action="store_true",
        help="diagnostic rejudge with A/B labels reversed; cannot change the primary decision",
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    source, run_dir = Path(args.source), Path(args.run_dir)
    if not source.exists():
        print(f"missing relevance verdicts: {source}", file=sys.stderr)
        return 1
    cases = load_cases(source)
    if args.limit:
        cases = cases[:args.limit]
    write_jsonl(run_dir / "corpus.jsonl", cases)
    calls = len(cases) * 2 + (len(cases) + JUDGE_BATCH - 1) // JUDGE_BATCH
    requested_calls = (len(cases) * 2 if args.generate else 0) + (
        (len(cases) + JUDGE_BATCH - 1) // JUDGE_BATCH if args.judge or args.swap_judge else 0
    )
    print(f"{len(cases)} paired cases; {requested_calls} requested external calls")
    print(f"draft chars: {sum(len(c['draft']) for c in cases)}; "
          f"prompt chars: {sum(len(c['prompt']) for c in cases)}")
    if not args.generate and not args.judge and not args.swap_judge:
        print("dry run only; pass --generate, then --judge; --swap-judge is diagnostic")
        return 0
    outputs_path = run_dir / "outputs.jsonl"
    outputs = generate(cases, run_dir) if args.generate else (
        [json.loads(line) for line in outputs_path.read_text(encoding="utf-8").splitlines()]
        if outputs_path.exists() else None
    )
    if outputs is None:
        print("generation incomplete", file=sys.stderr)
        return 1
    rulings = judge(outputs, run_dir, swapped=args.swap_judge) if args.judge or args.swap_judge else None
    if (args.judge or args.swap_judge) and rulings is None:
        print("judging incomplete", file=sys.stderr)
        return 1
    if rulings is not None:
        report(rulings, cases, diagnostic=args.swap_judge)
        if args.swap_judge:
            original_path = run_dir / "judgments.jsonl"
            if original_path.exists():
                original = [json.loads(line) for line in original_path.read_text(encoding="utf-8").splitlines()]
                crossover_report(original, rulings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
