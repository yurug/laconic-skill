#!/usr/bin/env python3
"""Measure whether demonstrated project theory would materially change real answers.

The concept corpus asks whether a prompt names a modeled term. This experiment tests the
alternative suggested by design/06-measurement.md: index the user's demonstrated theory of
a system -- world mapping, justification, and modification -- by the project where it was
observed, then ask whether that theory changes the ideal answer to later prompts from the
same project.

Mining is deterministic and local. Classification is explicit because it sends real prompt
text and recorded evidence through the configured Claude CLI. Run without --classify first
to inspect the corpus and cost. Outputs are gitignored.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from math import sqrt
from collections import Counter, defaultdict
from pathlib import Path

EVAL = Path(__file__).resolve().parent
TOOLS = EVAL.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(EVAL))

from laconic_index import parse_frontmatter  # noqa: E402
from laconic_lint import read_evidence  # noqa: E402
from laconic_record import KIND_RE, THEORY_KINDS  # noqa: E402
from mine_corpus import TRANSCRIPTS, user_turn_records, user_turns  # noqa: E402

BATCH = 5
CALL_TIMEOUT = 600
PROFILE_LIMIT = 8
KIND_RANK = {"modification": 0, "justification": 1, "world": 2}

INSTRUCTION = """\
Each item contains:
1. a real user prompt from a software project; and
2. observations showing parts of the theory this reader has previously demonstrated for
   that project.

Apply this counterfactual:

  If the same reader had NOT demonstrated the listed understanding, but the request and
  available project artifacts were identical, would the ideal answer need materially
  different explanation, rationale, warnings, or checks?

Say yes only when the answer can safely rely on a SPECIFIC listed observation. Project
co-location, general expertise, a familiar term, and mere topical relevance are not enough.
A task order whose execution is unchanged is no. Be strict.

Reply with one line of JSON per item and nothing else:
{"n": <number>, "theory_discriminating": true|false,
 "evidence": [<observation numbers actually relied on>], "why": "<12 words max>"}
"""


def encoded_project(path):
    """Claude's transcript directory name for an absolute project path."""
    return "-" + str(path).strip("/").replace("/", "-")


def evidence_kind(line):
    """Return (kind, observation) for marked theory evidence, otherwise (None, body)."""
    body = line.split(":", 1)[-1].strip()
    match = KIND_RE.match(body)
    if not match:
        return None, body
    kind = match.group(1)
    return kind, KIND_RE.sub("", body).strip()


def evidence_date(line):
    """The recorder's YYYY-MM-DD prefix, or None for malformed legacy evidence."""
    prefix = line.split(":", 1)[0].strip()
    return prefix if re.fullmatch(r"\d{4}-\d{2}-\d{2}", prefix) else None


def collect_profiles(model_home):
    """Theory observations grouped by the project in which they were made."""
    profiles = defaultdict(list)
    for path in sorted((model_home / "concepts").glob("*.md")):
        meta = parse_frontmatter(path)
        if not meta:
            continue
        projects = meta.get("projects")
        if not isinstance(projects, list):
            continue
        for line in read_evidence(path.read_text(encoding="utf-8")):
            kind, observation = evidence_kind(line)
            if kind not in THEORY_KINDS:
                continue
            entry = {
                "concept": meta.get("id", path.stem),
                "kind": kind,
                "observation": observation,
                "observed_on": evidence_date(line),
            }
            for project in projects:
                profiles[encoded_project(project)].append(entry)

    # Exact duplicates arise when a concept lists the same evidence for several encounters
    # in one project. Rank strong behavioral evidence first, then make ordering stable.
    for project, entries in profiles.items():
        unique = {
            (e["concept"], e["kind"], e["observation"]): e for e in entries
        }
        profiles[project] = sorted(
            unique.values(),
            key=lambda e: (KIND_RANK[e["kind"]], e["concept"], e["observation"]),
        )
    return profiles


def collect_cached_profiles(model_home, cache_dir):
    """Theory profiles from classify_evidence.py's keyed, unapplied judge verdicts.

    Historical observations were classified for measurement but deliberately not rewritten
    in the live model. Consuming the raw cached verdicts keeps that boundary intact: the
    experiment can test the hypothesis without turning a judge's label into user history.
    """
    current = {}
    for path in sorted((model_home / "concepts").glob("*.md")):
        meta = parse_frontmatter(path)
        if not meta:
            continue
        projects = meta.get("projects")
        projects = projects if isinstance(projects, list) else []
        for line in read_evidence(path.read_text(encoding="utf-8")):
            kind, observation = evidence_kind(line)
            if kind is None:
                cid = meta.get("id", path.stem)
                key = hashlib.sha256(f"{cid}\0{observation}".encode("utf-8")).hexdigest()
                current[key] = {
                    "concept": meta.get("id", path.stem),
                    "observation": observation,
                    "projects": projects,
                    "observed_on": evidence_date(line),
                }

    profiles = defaultdict(list)
    total_theory = indexed_theory = 0
    verdict_path = cache_dir / "verdicts.jsonl"
    if not verdict_path.exists():
        return profiles, total_theory, indexed_theory
    for line in verdict_path.read_text(encoding="utf-8").splitlines():
        try:
            verdict = json.loads(line)
        except ValueError:
            continue
        kind = verdict.get("kind")
        row = current.get(verdict.get("key"))
        if kind not in THEORY_KINDS or not row:
            continue
        total_theory += 1
        if not row["projects"]:
            continue
        indexed_theory += 1
        entry = {
            "concept": row["concept"],
            "kind": kind,
            "observation": row["observation"],
            "classification": "cached-judge",
            "observed_on": row["observed_on"],
        }
        for project in row["projects"]:
            profiles[encoded_project(project)].append(entry)
    return profiles, total_theory, indexed_theory


def merge_profiles(*sources):
    merged = defaultdict(list)
    for source in sources:
        for project, entries in source.items():
            merged[project].extend(entries)
    for project, entries in merged.items():
        unique = {
            (e["concept"], e["kind"], e["observation"]): e for e in entries
        }
        merged[project] = sorted(
            unique.values(),
            key=lambda e: (KIND_RANK[e["kind"]], e["concept"], e["observation"]),
        )
    return merged


def mine(transcripts, profiles):
    """Later prompt-shaped turns from projects with already-demonstrated theory.

    Evidence dates have day precision, so only a prompt on a strictly later date is
    provably subsequent. Same-day prompts are excluded rather than ordered by guesswork.
    """
    candidates = []
    if not transcripts.is_dir():
        return rows
    for project_dir in sorted(p for p in transcripts.iterdir() if p.is_dir()):
        profile = profiles.get(project_dir.name)
        if not profile:
            continue
        for transcript in sorted(project_dir.rglob("*.jsonl")):
            for record in user_turn_records(transcript):
                prompt = record["text"]
                timestamp = record.get("timestamp")
                prompt_date = timestamp[:10] if isinstance(timestamp, str) else None
                prior = [
                    item for item in profile
                    if item.get("observed_on") and prompt_date
                    and item["observed_on"] < prompt_date
                ]
                if not prior:
                    continue
                digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                candidates.append({
                    "prompt": prompt,
                    "project": project_dir.name,
                    "source": str(transcript.relative_to(transcripts)),
                    "timestamp": timestamp,
                    "digest": digest,
                    "theory": prior[:PROFILE_LIMIT],
                })
    # A repeated prompt can appear in retried sessions. Keep its earliest provably eligible
    # occurrence, independent of filesystem traversal order.
    rows_by_digest = {}
    for row in sorted(candidates, key=lambda r: (r["timestamp"], r["source"])):
        rows_by_digest.setdefault(row.pop("digest"), row)
    rows = list(rows_by_digest.values())
    # Hash order is deterministic without preferring terse or verbose prompts.
    rows.sort(key=lambda r: hashlib.sha256(r["prompt"].encode("utf-8")).hexdigest())
    return rows


def prompt_universe_size(transcripts):
    """Distinct prompt-shaped turns across every project: the comparison denominator."""
    seen = set()
    if not transcripts.is_dir():
        return 0
    for transcript in sorted(transcripts.rglob("*.jsonl")):
        for prompt in user_turns(transcript):
            seen.add(hashlib.sha256(prompt.encode("utf-8")).hexdigest())
    return len(seen)


def wilson(successes, total, z=1.96):
    """95% Wilson interval, stable for the small positive counts expected here."""
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z * sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def build_batch(rows):
    parts = []
    for number, row in enumerate(rows, 1):
        observations = "\n".join(
            f'      {i}. [{e["kind"]}] {e["concept"]}: '
            f'{e["observation"][:180]}'
            for i, e in enumerate(row["theory"], 1)
        )
        prompt = " ".join(row["prompt"].split())[:700]
        parts.append(f'{number}. prompt: "{prompt}"\n   demonstrated theory:\n{observations}')
    return INSTRUCTION + "\n\n" + "\n\n".join(parts)


def parse_verdicts(text, size):
    out = {}
    for match in re.finditer(r'\{[^{}]*"n"\s*:\s*(\d+)[^{}]*\}', text):
        try:
            obj = json.loads(match.group(0))
        except ValueError:
            continue
        number = obj.get("n")
        evidence = obj.get("evidence")
        if not isinstance(number, int) or not 1 <= number <= size:
            continue
        if not isinstance(evidence, list) or not all(isinstance(x, int) for x in evidence):
            continue
        obj["theory_discriminating"] = bool(obj.get("theory_discriminating"))
        out[number] = obj
    return out


def validated_verdicts(text, rows):
    """Parsed rulings whose positive citations point into the supplied profile."""
    parsed = parse_verdicts(text, len(rows))
    for number, verdict in list(parsed.items()):
        citations = verdict["evidence"]
        if verdict["theory_discriminating"] and not citations:
            parsed.pop(number)
            continue
        if any(index < 1 or index > len(rows[number - 1]["theory"]) for index in citations):
            parsed.pop(number)
    return parsed


def batch_paths(run_dir, batch_number, batch):
    payload = build_batch(batch)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    stem = f"batch-{batch_number:03d}-{digest}"
    return run_dir / f"{stem}.txt", run_dir / f"{stem}.input.jsonl"


def write_batch_manifest(path, batch):
    write_jsonl(path, ({
        "n": number,
        "key": hashlib.sha256(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest(),
        "prompt": row["prompt"],
        "theory": row["theory"],
    } for number, row in enumerate(batch, 1)))


def promote_verified_legacy_cache(rows, run_dir):
    """Bind this run's positional raw files when its structured output proves identity.

    The first completed run wrote exact prompt/profile inputs into verdicts.jsonl but named
    raw batches positionally. Promotion is allowed only when every structured row equals the
    current deterministic sample and every raw ruling reproduces that structured row.
    """
    result_path = run_dir / "verdicts.jsonl"
    if not result_path.exists():
        return 0
    try:
        prior = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError):
        return 0
    if len(prior) != len(rows) or any(
        old.get("prompt") != new["prompt"] or old.get("theory") != new["theory"]
        or not old.get("ruled")
        for old, new in zip(prior, rows)
    ):
        return 0

    promoted = 0
    for offset in range(0, len(rows), BATCH):
        number = offset // BATCH + 1
        batch = rows[offset:offset + BATCH]
        legacy = run_dir / f"batch-{number:03d}.txt"
        raw_path, manifest = batch_paths(run_dir, number, batch)
        if raw_path.exists() or not legacy.exists():
            continue
        text = legacy.read_text(encoding="utf-8")
        parsed = validated_verdicts(text, batch)
        expected = prior[offset:offset + len(batch)]
        if len(parsed) != len(batch) or any(
            parsed[i].get("theory_discriminating") != old.get("theory_discriminating")
            or parsed[i].get("evidence") != old.get("relied_on")
            or parsed[i].get("why") != old.get("why")
            for i, old in enumerate(expected, 1)
        ):
            continue
        write_batch_manifest(manifest, batch)
        raw_path.write_text(text, encoding="utf-8")
        promoted += 1
    return promoted


def classify(rows, run_dir):
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    empty_home = run_dir / "model-empty"
    (empty_home / "concepts").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LACONIC_HOME"] = str(empty_home)
    env["LACONIC_NO_PUSH"] = "1"
    verdicts = []

    for batch_number, batch in enumerate(batches, 1):
        raw_path, manifest_path = batch_paths(run_dir, batch_number, batch)
        write_batch_manifest(manifest_path, batch)
        text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
        parsed = validated_verdicts(text, batch) if text else {}
        if len(parsed) == len(batch):
            print(f"  [batch {batch_number}/{len(batches)}] cached")
        else:
            if raw_path.exists():
                print(
                    f"  [batch {batch_number}/{len(batches)}] ignoring incomplete cached "
                    f"response ({len(parsed)}/{len(batch)})"
                )
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    ["claude", "-p", build_batch(batch)],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=str(EVAL),
                    timeout=CALL_TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                print(f"  [batch {batch_number}/{len(batches)}] TIMEOUT")
                return None
            text = proc.stdout
            parsed = validated_verdicts(text, batch)
            print(
                f"  [batch {batch_number}/{len(batches)}] "
                f"{time.monotonic() - started:.0f}s"
            )
            if proc.returncode != 0 or len(parsed) != len(batch):
                diagnostic = (proc.stderr or proc.stdout).strip().splitlines()
                detail = diagnostic[0][:240] if diagnostic else "no diagnostic"
                print(
                    f"    error: judge returned {proc.returncode}; "
                    f"{len(parsed)}/{len(batch)} parsed — {detail}"
                )
                return None
            raw_path.write_text(text, encoding="utf-8")
        if len(parsed) != len(batch):
            print(f"    warning: {len(parsed)}/{len(batch)} verdicts parsed")
        for number, row in enumerate(batch, 1):
            verdict = parsed.get(number)
            verdicts.append({
                **row,
                "theory_discriminating": bool(
                    verdict and verdict["theory_discriminating"]
                ),
                "relied_on": (verdict or {}).get("evidence", []),
                "why": (verdict or {}).get("why", "unparsed"),
                "ruled": verdict is not None,
            })
    return verdicts


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model-home",
        default=os.environ.get("LACONIC_HOME", str(Path.home() / ".laconic")),
    )
    parser.add_argument("--transcripts", default=str(TRANSCRIPTS))
    parser.add_argument("--out", default=str(EVAL / "theory-corpus.jsonl"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--classify",
        action="store_true",
        help="send the sampled prompts and profiles to Claude for counterfactual judgement",
    )
    parser.add_argument(
        "--run-dir", default=str(EVAL / "runs" / "theory-relevance")
    )
    parser.add_argument(
        "--evidence-cache",
        default=str(EVAL / "runs" / "evidence-v2"),
        help="keyed classify_evidence.py verdicts; legacy positional caches are rejected",
    )
    parser.add_argument(
        "--marked-only",
        action="store_true",
        help="ignore cached historical classifications and use live evidence kinds only",
    )
    args = parser.parse_args()

    model_home = Path(args.model_home)
    marked_profiles = collect_profiles(model_home)
    cached_profiles, cached_theory, cached_indexed = ({}, 0, 0)
    if not args.marked_only:
        cached_profiles, cached_theory, cached_indexed = collect_cached_profiles(
            model_home, Path(args.evidence_cache)
        )
    profiles = merge_profiles(marked_profiles, cached_profiles)
    transcripts = Path(args.transcripts)
    rows = mine(transcripts, profiles)
    universe = prompt_universe_size(transcripts)
    sample = rows[:args.limit] if args.limit else rows
    write_jsonl(Path(args.out), sample)

    print(
        f"{len(profiles)} projects carry theory evidence "
        f"({cached_indexed}/{cached_theory} cached theory rulings project-indexable)"
    )
    print(
        f"{len(rows)} distinct eligible prompts of {universe} prompt-shaped turns; "
        f"deterministic sample {len(sample)}"
    )
    print(f"profile kinds: {dict(Counter(e['kind'] for r in sample for e in r['theory']))}")
    print(f"wrote local corpus to {args.out}")

    if not args.classify:
        calls = (len(sample) + BATCH - 1) // BATCH
        print(
            f"classification not run: --classify would make {calls} Claude calls "
            "containing real prompts and recorded evidence"
        )
        return 0

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    promoted = promote_verified_legacy_cache(sample, run_dir)
    if promoted:
        print(f"promoted {promoted} verified positional batches to hash-bound cache")
    verdicts = classify(sample, run_dir)
    if verdicts is None:
        return 1
    result_path = run_dir / "verdicts.jsonl"
    write_jsonl(result_path, verdicts)
    ruled = [row for row in verdicts if row["ruled"]]
    kept = [row for row in ruled if row["theory_discriminating"]]
    rate = 100 * len(kept) / len(ruled) if ruled else 0
    low, high = wilson(len(kept), len(ruled))
    coverage = len(rows) / universe if universe else 0
    overall = coverage * rate / 100
    print(f"\n{len(kept)}/{len(ruled)} ruled prompts theory-discriminating ({rate:.1f}%)")
    print(
        f"95% Wilson interval within eligible projects: {100 * low:.1f}%–"
        f"{100 * high:.1f}%"
    )
    print(
        f"projected share of all prompt-shaped turns: {100 * overall:.2f}% "
        f"(interval {100 * coverage * low:.2f}%–{100 * coverage * high:.2f}%)"
    )
    print(f"wrote {result_path}")
    return 0 if len(ruled) == len(sample) else 1


if __name__ == "__main__":
    sys.exit(main())
