#!/usr/bin/env python3
"""Apply explicitly accepted bootstrap proposals after isolated preflight."""

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

from laconic_index import atomic_write_text, write_index_file
from laconic_record import (acquire_model_lock, ensure_repo, git_commit, git_push_async, home)
from laconic_review import load_json, record_args, validate


def digest_model(model_home):
    digest = hashlib.sha256()
    concepts = model_home / "concepts"
    for path in sorted(concepts.glob("*.md")) if concepts.is_dir() else []:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_decisions(document, review_id, proposals):
    if document.get("schema_version") != 1 \
            or document.get("purpose") != "laconic-bootstrap-decisions":
        raise ValueError("unsupported decision document")
    if document.get("review_id") != review_id:
        raise ValueError("decision review_id does not match")
    rows = document.get("decisions")
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list")
    expected = {proposal["proposal_id"] for proposal in proposals}
    found = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"proposal_id", "decision"}:
            raise ValueError("each decision needs only proposal_id and decision")
        if row["decision"] not in ("accept", "reject"):
            raise ValueError("decision must be accept or reject")
        if row["proposal_id"] in found:
            raise ValueError("duplicate proposal decision")
        found[row["proposal_id"]] = row["decision"]
    if set(found) != expected:
        raise ValueError("decisions must cover every proposal exactly once")
    return found


def preflight(model_home, accepted, sources, default_project=None):
    temporary = tempfile.TemporaryDirectory(prefix="laconic-review-")
    staged = Path(temporary.name) / "model"
    concepts = model_home / "concepts"
    if concepts.is_dir():
        shutil.copytree(concepts, staged / "concepts")
    else:
        (staged / "concepts").mkdir(parents=True)
    env = {**os.environ, "LACONIC_HOME": str(staged), "LACONIC_NO_PUSH": "1"}
    recorder = Path(__file__).with_name("laconic_record.py")
    for proposal in accepted:
        project_value = sources[proposal["source_refs"][0]].get("project") or default_project
        if not project_value:
            temporary.cleanup()
            raise ValueError("proposal source has no project")
        project = Path(project_value)
        if not project.is_dir():
            temporary.cleanup()
            raise ValueError(f"reviewed project no longer exists: {project}")
        result = subprocess.run(
            [sys.executable, str(recorder), *record_args(proposal, sources)],
            cwd=project, env=env, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            temporary.cleanup()
            raise ValueError(f"preflight failed for {proposal['proposal_id']}: "
                             f"{(result.stdout + result.stderr).strip()}")
    lint = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("laconic_lint.py")),
         "--home", str(staged), "--quiet"],
        env=env, capture_output=True, text=True, check=False,
    )
    if lint.returncode != 0:
        temporary.cleanup()
        raise ValueError(f"preflight lint failed: {(lint.stdout + lint.stderr).strip()}")
    return temporary, staged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--proposals", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--confirm-review-id", required=True)
    args = parser.parse_args()
    try:
        bundle = load_json(args.bundle, "bundle")
        proposal_doc = load_json(args.proposals, "proposals")
        decision_doc = load_json(args.decisions, "decisions")
        if args.confirm_review_id != bundle["review_id"]:
            raise ValueError("--confirm-review-id does not match the reviewed bundle")
        model_home = home()
        marker = model_home / "reviews" / "applied" / f"{bundle['review_id']}.json"
        if marker.exists():
            raise ValueError("this review was already applied")
        proposals, sources = validate(bundle, proposal_doc, model_home)
        decisions = validate_decisions(decision_doc, bundle["review_id"], proposals)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    accepted = [proposal for proposal in proposals
                if decisions[proposal["proposal_id"]] == "accept"]
    if not accepted:
        print("No proposals accepted; model unchanged.")
        return 0
    ensure_repo(model_home)
    before = digest_model(model_home)
    try:
        temporary, staged = preflight(model_home, accepted, sources, bundle.get("project"))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        lock = acquire_model_lock(model_home)
        if lock is None:
            print("error: model lock busy; nothing applied", file=sys.stderr)
            return 2
        if digest_model(model_home) != before:
            print("error: model changed during review preflight; nothing applied", file=sys.stderr)
            return 2
        marker = model_home / "reviews" / "applied" / f"{bundle['review_id']}.json"
        if marker.exists():
            print("error: this review was already applied", file=sys.stderr)
            return 2
        for concept_id in sorted({proposal["concept_id"] for proposal in accepted}):
            source = staged / "concepts" / f"{concept_id}.md"
            atomic_write_text(model_home / "concepts" / source.name,
                              source.read_text(encoding="utf-8"))
        marker.parent.mkdir(parents=True, exist_ok=True)
        decision_hash = hashlib.sha256(args.decisions.read_bytes()).hexdigest()
        atomic_write_text(marker, json.dumps({
            "review_id": bundle["review_id"], "applied_at": date.today().isoformat(),
            "decision_hash": decision_hash,
            "accepted": [proposal["proposal_id"] for proposal in accepted],
        }, sort_keys=True) + "\n")
        write_index_file(date.today())
        git_commit(model_home, f"apply bootstrap review {bundle['review_id'][:12]} "
                   f"({len(accepted)} accepted)")
        git_push_async(model_home)
        print(f"Applied {len(accepted)} accepted proposal(s) in one model commit.")
        return 0
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
