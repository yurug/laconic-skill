#!/usr/bin/env python3
"""Resolve prompt-route telemetry against the final answer without retaining either text."""

import hashlib
import json
import os
import sys
from pathlib import Path

from laconic_index import load_concepts, route_tokens
from laconic_observe import last_assistant_text

GENERIC_ROUTE_TERMS = {
    "architecture", "concept", "data", "index", "indexes", "model", "project",
    "system", "test", "testing",
}


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def session_key(session_id):
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:20]


def pending_path(session_id):
    return home() / ".routing-pending" / f"{session_key(session_id)}.json"


def answer_domains(text, selected, concepts, strict=False):
    """Domains strongly evidenced by vocabulary in the final assistant turn.

    One exact domain token is enough; concept ids require two tokens to avoid treating a
    generic word such as `architecture`, `model`, or `index` as a domain use.
    """
    answer = route_tokens(text)
    matched = []
    for domain in selected:
        domain_tokens = route_tokens(domain)
        concept_tokens = [
            route_tokens(concept.get("id", ""))
            for concept in concepts if concept.get("domain") == domain
        ]
        overlaps = [len(answer & tokens) for tokens in concept_tokens]
        domain_hit = bool(answer & domain_tokens)
        if strict:
            # Miss detection must be substantially stricter than checking whether selected
            # context surfaced. Require two independent lexical signals: a full multi-token
            # domain name, two terms from one concept, or a single-token domain plus a
            # different term from one of its concepts.
            multi_domain = len(domain_tokens) >= 2 and domain_tokens <= answer
            domain_plus_concept = (
                len(domain_tokens) == 1 and domain_hit
                and any((answer & tokens) - domain_tokens for tokens in concept_tokens)
            )
            hit = multi_domain or domain_plus_concept or max(overlaps, default=0) >= 2
        else:
            distinctive = any((answer & tokens) - GENERIC_ROUTE_TERMS
                              for tokens in concept_tokens)
            hit = domain_hit or distinctive or max(overlaps, default=0) >= 2
        if hit:
            matched.append(domain)
    return matched


def resolve(transcript, session_id):
    if os.environ.get("LACONIC_TELEMETRY") != "1" or not session_id:
        return
    pending = pending_path(session_id)
    try:
        row = json.loads(pending.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    text = last_assistant_text(transcript) or ""
    concepts = load_concepts()
    selected = row.get("domains", [])
    row["answer_domains"] = answer_domains(text, selected, concepts)
    all_domains = sorted({concept.get("domain") for concept in concepts if concept.get("domain")})
    surfaced = answer_domains(text, all_domains, concepts, strict=True)
    row["missed_domains"] = [domain for domain in surfaced if domain not in selected]
    try:
        with (home() / "routing-telemetry.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        pending.unlink(missing_ok=True)
    except OSError:
        pass


def main():
    if len(sys.argv) == 3:
        resolve(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(0)
