#!/usr/bin/env python3
"""Mine real user turns that touch a modeled concept.

The decisive comparison is "injected policy alone" versus "policy plus a populated model".
Only prompts whose answer *should* change with the reader's knowledge state can separate
those two arms; a generic corpus measures brevity, which both arms already have. So the
corpus is filtered to turns that mention a concept the model knows, and stratified by that
concept's state -- the states are the independent variable.

Mined rather than authored on purpose: a benchmark written by whoever built the system
under test measures its author's imagination. These are the user's own words.

Output stays local (eval/corpus.jsonl, gitignored). Real transcripts contain work material.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from laconic_index import STATES, load_concepts  # noqa: E402

TRANSCRIPTS = Path.home() / ".claude" / "projects"

# A turn shorter than this is an acknowledgement ("yes", "go", "thanks"), not a prompt whose
# answer could be miscalibrated.
MIN_CHARS = 40

# Turns longer than this are usually pasted logs or files; the concept mention is incidental
# and the "prompt" is not really a question.
MAX_CHARS = 2000

# Slash commands, hook output and tool noise are not the user talking. The harness writes
# several of these into the transcript as `type: user`, so without the tag filters a
# task-notification counts as a prompt -- they were 3 of the first 6 exposed-state hits.
SKIP_PREFIXES = (
    "/", "<local-command", "<command-", "[Request interrupted", "Caveat:",
    "<task-notification>", "<system-reminder>", "<user-prompt-submit-hook>",
    "<bash-input>", "<bash-stdout>", "<attachment", "<ide_", "API Error",
)

# A turn that is mostly markup is machine output wearing a user turn's clothes.
TAG_HEAVY = re.compile(r"<[a-z][a-z0-9-]*>")

# Prompts from other projects' eval harnesses, which are typed by a script rather than a
# person. They pass every other filter -- real text, right length, concept words present --
# and their answers are fixed by a cited source, so knowledge state cannot change them.
HARNESS = re.compile(
    r"^(?:answer|reply|respond)\s+(?:using only|in exactly|with exactly|only from)|"
    r"^using only the knowledge base",
    re.I,
)


# Words too generic to identify a concept on their own. Without this, `reactor-inventory-
# model` matches any turn containing "model", which is most of them.
GENERIC = {
    "the", "and", "for", "with", "pattern", "model", "structure", "procedure",
    "dependency", "questions", "based", "into", "from", "that", "this", "using",
    "value", "values", "state", "states", "data", "file", "files", "code",
}


def concept_patterns(concepts):
    """Distinctive words of each concept id, matched with a prefix so "pseudonymization"
    also catches "pseudonymisation" and "pseudonymised".

    Requiring the id verbatim and contiguous ("rust pin") found 81 turns across 11 concepts;
    requiring two distinctive words anywhere found 229 across 33. The ids are agent-authored
    kebab-case summaries, not the user's phrasing, so contiguity was testing whether the
    recorder happened to name a concept the way the user says it. Two distinctive words is
    the loosest rule that still requires the *concept* to be in play rather than its domain.
    """
    out = {}
    skipped = []
    for c in concepts:
        # len > 2, not > 3: at the higher threshold `rust-pin` lost "pin" and degenerated to
        # matching every turn containing "rust", which alone produced 46 spurious `unknown`
        # hits against a model holding only two unknown concepts.
        words = [w for w in c["id"].split("-") if len(w) > 2 and w not in GENERIC]
        if len(words) < 2:
            # A concept that cannot be identified by two distinctive words cannot be
            # detected without guessing. Excluded and reported, never silently matched on
            # one word.
            skipped.append(c["id"])
            continue
        # Prefix match, capped: "pseudonymization" and "pseudonymisation" share a long stem,
        # while a short stem like "cost" would match "costume".
        out[c["id"]] = [
            re.compile(r"\b" + re.escape(w[:8]) + r"\w*\b", re.I) for w in words
        ]
    return out, skipped


def matches(patterns, text):
    """A hit needs two of the concept's distinctive words present."""
    return sum(1 for rx in patterns if rx.search(text)) >= 2


def user_turn_records(path):
    """Prompt-shaped user turns with their source timestamp when available."""
    try:
        with path.open(errors="ignore") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "user" or d.get("isMeta"):
                    continue
                content = d.get("message", {}).get("content")
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                if not isinstance(content, str):
                    continue
                text = content.strip()
                if not (MIN_CHARS <= len(text) <= MAX_CHARS):
                    continue
                if text.startswith(SKIP_PREFIXES):
                    continue
                if len(TAG_HEAVY.findall(text)) >= 3:
                    continue
                if HARNESS.match(text):
                    continue
                yield {"text": text, "timestamp": d.get("timestamp")}
    except OSError:
        return


def user_turns(path):
    """Backward-compatible text-only view used by the concept corpus."""
    for record in user_turn_records(path):
        yield record["text"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path(__file__).parent / "corpus.jsonl"))
    ap.add_argument("--per-state", type=int, default=15, help="cap per knowledge state")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = ap.parse_args()

    concepts = load_concepts()
    if not concepts:
        print("no model to mine against", file=sys.stderr)
        return 1
    state_of = {c["id"]: c["state"] for c in concepts}
    patterns, skipped = concept_patterns(concepts)
    if skipped:
        # Never a silent cap: a concept absent from the corpus is a concept the measurement
        # says nothing about.
        print(f"undetectable ({len(skipped)}, fewer than two distinctive words): "
              f"{', '.join(skipped)}\n")

    seen = set()
    by_state = defaultdict(list)
    scanned = 0
    for transcript in sorted(TRANSCRIPTS.rglob("*.jsonl")):
        scanned += 1
        for text in user_turns(transcript):
            key = text[:200]
            if key in seen:
                continue
            hits = sorted(cid for cid, rxs in patterns.items() if matches(rxs, text))
            if not hits:
                continue
            seen.add(key)
            # File under the strongest state in play: if a turn touches both a verified and
            # an unknown concept, the interesting question is whether the unknown one got
            # explained, so rank by the state that most constrains the answer.
            state = min((state_of[h] for h in hits), key=STATES.index)
            by_state[state].append(
                {"prompt": text, "concepts": hits, "state": state,
                 "source": str(transcript.relative_to(TRANSCRIPTS))}
            )

    print(f"scanned {scanned} transcripts, {len(seen)} distinct turns touching a concept")
    print()
    print(f"{'state':<10} {'found':>6}  {'sampled':>7}")
    corpus = []
    for state in STATES:
        found = by_state.get(state, [])
        # Deterministic sample: sort by length so the pick does not depend on filesystem
        # order, and take from the middle -- the shortest are terse, the longest are pastes.
        found.sort(key=lambda r: len(r["prompt"]))
        mid = len(found) // 2
        half = args.per_state // 2
        sample = found[max(0, mid - half) : max(0, mid - half) + args.per_state]
        corpus.extend(sample)
        print(f"{state:<10} {len(found):>6}  {len(sample):>7}")
    print(f"{'total':<10} {sum(len(v) for v in by_state.values()):>6}  {len(corpus):>7}")

    counts = Counter(c for r in corpus for c in r["concepts"])
    print(f"\ndistinct concepts represented: {len(counts)} of {len(concepts)}")

    if args.dry_run:
        print("\n(dry run, nothing written)")
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in corpus:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(corpus)} prompts to {out}")
    print("NOTE: real transcript text — local only, gitignored, never into evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
