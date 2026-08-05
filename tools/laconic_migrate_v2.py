#!/usr/bin/env python3
"""Export, validate, review, and transactionally apply semantic-model v2 claims."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from laconic_index import KNOWLEDGE_KINDS, KNOWLEDGE_SCOPES, atomic_write_text, get_section, UNDERSTANDS, write_index_file
from laconic_lint import read_evidence
from laconic_record import (acquire_model_lock, add_knowledge_claim, ensure_repo, git_commit,
                            git_push_async, home, parse_existing, render)


def model_digest(model_home):
    digest = hashlib.sha256()
    for path in sorted((model_home / "concepts").glob("*.md")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def export_bundle(model_home):
    concepts = []
    for path in sorted((model_home / "concepts").glob("*.md")):
        meta, evidence, body = parse_existing(path)
        if meta is None:
            continue
        rows = []
        for number, value in enumerate(evidence, 1):
            rows.append({"index": number, "text": value,
                         "inference": "[basis: inference]" in value})
        concepts.append({
            "concept_id": meta.get("id", path.stem), "domain": meta.get("domain", "general"),
            "projects": meta.get("projects", []), "state": meta.get("state", "unknown"),
            "evidence": rows, "legacy_understanding": get_section(body, UNDERSTANDS),
        })
    digest = model_digest(model_home)
    migration_id = hashlib.sha256(("laconic-v2\0" + digest).encode()).hexdigest()
    return {
        "schema_version": 1, "purpose": "laconic-v2-migration-bundle",
        "migration_id": migration_id, "model_hash": digest, "concepts": concepts,
        "proposal_contract": {
            "purpose": "laconic-v2-proposals", "schema_version": 1,
            "fields": ["concept_id", "kind", "claim", "evidence", "scope", "condition"],
            "rules": [
                "cite only exact evidence indexes from the same concept",
                "never cite inference", "do not turn a topic label into a semantic claim",
                "default scope to project; widen only when evidence demonstrates transfer",
                "prefer no proposal over a plausible but unsupported claim",
            ],
        },
    }


def one_line(value, label, optional=False):
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n]"):
        raise ValueError(f"{label} must be one non-empty line without ']'")
    return " ".join(value.split())


def validate(bundle, document):
    if bundle.get("purpose") != "laconic-v2-migration-bundle" or bundle.get("schema_version") != 1:
        raise ValueError("unsupported migration bundle")
    if document.get("purpose") != "laconic-v2-proposals" or document.get("schema_version") != 1:
        raise ValueError("unsupported proposal document")
    if document.get("migration_id") != bundle.get("migration_id"):
        raise ValueError("proposal migration_id does not match bundle")
    known = {item["concept_id"]: item for item in bundle["concepts"]}
    validated = []
    allowed = {"concept_id", "kind", "claim", "evidence", "scope", "condition"}
    for number, proposal in enumerate(document.get("proposals", []), 1):
        if not isinstance(proposal, dict) or set(proposal) - allowed:
            raise ValueError(f"proposal #{number} has unknown fields or is not an object")
        concept_id = proposal.get("concept_id")
        if concept_id not in known:
            raise ValueError(f"proposal #{number} names unknown concept")
        kind, scope = proposal.get("kind"), proposal.get("scope", "project")
        if kind not in KNOWLEDGE_KINDS or scope not in KNOWLEDGE_SCOPES:
            raise ValueError(f"proposal #{number} has invalid kind or scope")
        claim = one_line(proposal.get("claim"), f"proposal #{number} claim")
        condition = one_line(proposal.get("condition"), f"proposal #{number} condition", True)
        sources = proposal.get("evidence")
        if not isinstance(sources, list) or not sources or any(type(x) is not int for x in sources) \
                or len(sources) != len(set(sources)):
            raise ValueError(f"proposal #{number} needs unique evidence indexes")
        evidence = {row["index"]: row for row in known[concept_id]["evidence"]}
        if any(index not in evidence for index in sources):
            raise ValueError(f"proposal #{number} cites missing evidence")
        if any(evidence[index]["inference"] for index in sources):
            raise ValueError(f"proposal #{number} cites inferred evidence")
        normalized = {**proposal, "claim": claim, "condition": condition, "scope": scope}
        proposal_id = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()[:16]
        validated.append({**normalized, "proposal_id": proposal_id})
    return validated


def decisions(document, migration_id, proposals):
    if document.get("purpose") != "laconic-v2-decisions" or document.get("schema_version") != 1 \
            or document.get("migration_id") != migration_id:
        raise ValueError("unsupported or mismatched decisions")
    rows = document.get("decisions")
    expected = {item["proposal_id"] for item in proposals}
    found = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or set(row) != {"proposal_id", "decision"} \
                or row.get("decision") not in ("accept", "reject") or row.get("proposal_id") in found:
            raise ValueError("decisions must uniquely accept or reject each proposal")
        found[row["proposal_id"]] = row["decision"]
    if set(found) != expected:
        raise ValueError("decisions must cover every proposal exactly once")
    return found


def stage(model_home, accepted):
    temporary = tempfile.TemporaryDirectory(prefix="laconic-v2-")
    staged = Path(temporary.name) / "model"
    shutil.copytree(model_home / "concepts", staged / "concepts")
    for proposal in accepted:
        path = staged / "concepts" / f"{proposal['concept_id']}.md"
        meta, evidence, body = parse_existing(path)
        body = add_knowledge_claim(body, proposal["kind"], proposal["claim"],
                                   proposal["evidence"], proposal["scope"],
                                   proposal.get("condition", ""))
        atomic_write_text(path, render(meta, evidence, body))
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("laconic_lint.py")),
         "--home", str(staged), "--quiet"], capture_output=True, text=True, check=False,
        env={**os.environ, "LACONIC_HOME": str(staged)},
    )
    if result.returncode:
        temporary.cleanup()
        raise ValueError("preflight lint failed: " + (result.stdout + result.stderr).strip())
    return temporary, staged


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--out", required=True, type=Path)
    review = sub.add_parser("review")
    review.add_argument("--bundle", required=True, type=Path)
    review.add_argument("--proposals", required=True, type=Path)
    review.add_argument("--out", required=True, type=Path)
    review.add_argument("--decisions-out", required=True, type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("--bundle", required=True, type=Path)
    apply.add_argument("--proposals", required=True, type=Path)
    apply.add_argument("--decisions", required=True, type=Path)
    apply.add_argument("--confirm-migration-id", required=True)
    args = parser.parse_args()
    model_home = home()
    if args.command == "export":
        bundle = export_bundle(model_home)
        atomic_write_text(args.out, json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
        print(f"Exported {len(bundle['concepts'])} concepts; model unchanged. Migration: {bundle['migration_id']}")
        return 0
    if args.command == "review":
        try:
            bundle = load(args.bundle)
            proposals = validate(bundle, load(args.proposals))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        lines = ["# Laconic semantic-model v2 migration", "",
                 f"Migration: `{bundle['migration_id']}`", "",
                 "Nothing below has been applied. Accept or reject every stable id.", ""]
        for item in proposals:
            condition = f"; when {item['condition']}" if item.get("condition") else ""
            lines += [f"## [ ] {item['concept_id']} — `{item['proposal_id']}`", "",
                      f"- `{item['kind']}` / `{item['scope']}`{condition}",
                      f"- Claim: {item['claim']}",
                      f"- Evidence: {', '.join('#' + str(x) for x in item['evidence'])}", ""]
        atomic_write_text(args.out, "\n".join(lines).rstrip() + "\n")
        atomic_write_text(args.decisions_out, json.dumps({
            "schema_version": 1, "purpose": "laconic-v2-decisions",
            "migration_id": bundle["migration_id"],
            "decisions": [{"proposal_id": item["proposal_id"], "decision": None}
                          for item in proposals],
        }, indent=2) + "\n")
        print(f"Rendered {len(proposals)} proposal(s); model unchanged.")
        return 0
    try:
        bundle = load(args.bundle)
        if args.confirm_migration_id != bundle.get("migration_id"):
            raise ValueError("--confirm-migration-id does not match")
        proposals = validate(bundle, load(args.proposals))
        choices = decisions(load(args.decisions), bundle["migration_id"], proposals)
        if model_digest(model_home) != bundle.get("model_hash"):
            raise ValueError("model changed since export; create a fresh migration bundle")
        accepted = [item for item in proposals if choices[item["proposal_id"]] == "accept"]
        if not accepted:
            print("No proposals accepted; model unchanged.")
            return 0
        temporary, staged = stage(model_home, accepted)
        ensure_repo(model_home)
        lock = acquire_model_lock(model_home)
        if lock is None or model_digest(model_home) != bundle["model_hash"]:
            temporary.cleanup()
            raise ValueError("model changed or lock is busy; nothing applied")
        for concept_id in sorted({item["concept_id"] for item in accepted}):
            source = staged / "concepts" / f"{concept_id}.md"
            atomic_write_text(model_home / "concepts" / source.name, source.read_text())
        temporary.cleanup()
        write_index_file(date.today())
        git_commit(model_home, f"migrate semantic model v2 ({len(accepted)} claims)")
        git_push_async(model_home)
        print(f"Applied {len(accepted)} reviewed semantic claim(s).")
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
