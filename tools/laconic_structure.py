#!/usr/bin/env python3
"""Audit and transactionally reconcile model domains, projects, and concept identity."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path

from laconic_index import (CAPABILITIES, ESTABLISHED_KNOWLEDGE, NOT_ESTABLISHED,
                           UNDERSTANDS, atomic_write_text, get_section, load_concepts,
                           write_index_file)
from laconic_record import (acquire_model_lock, ensure_repo, git_commit, git_push_async,
                            home, parse_existing, render, set_section)

ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KINDS = {"rename-domain", "set-domain", "remove-project", "replace-project",
         "rename-concept", "merge-concepts"}


def digest(model_home):
    h = hashlib.sha256()
    for path in sorted((model_home / "concepts").glob("*.md")):
        h.update(path.name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


def audit(model_home):
    concepts = load_concepts(model_home / "concepts")
    domains = {}
    projects = {}
    for concept in concepts:
        domains.setdefault(concept["domain"], []).append(concept["id"])
        for project in concept.get("projects", []):
            projects.setdefault(project, []).append(concept["id"])
    model_hash = digest(model_home)
    domain_names = sorted(domains)
    similar_domains = [
        {"a": left, "b": right, "score": round(SequenceMatcher(None, left, right).ratio(), 2)}
        for index, left in enumerate(domain_names) for right in domain_names[index + 1:]
        if SequenceMatcher(None, left, right).ratio() >= 0.72
    ]
    return {
        "schema_version": 1, "purpose": "laconic-structure-audit",
        "model_hash": model_hash,
        "review_id": hashlib.sha256(("structure\0" + model_hash).encode()).hexdigest(),
        "diagnostics": {
            "singleton_domains": {key: value for key, value in domains.items() if len(value) == 1},
            "missing_projects": {key: value for key, value in projects.items()
                                 if not Path(key).is_dir()},
            "broad_projects": {key: value for key, value in projects.items()
                               if key in (str(Path.home()), str(Path.home().parent), "/")},
            "domains": {key: len(value) for key, value in sorted(domains.items())},
            "similar_domains": similar_domains,
        },
        "plan_contract": {
            "purpose": "laconic-structure-plan", "schema_version": 1,
            "operations": sorted(KINDS),
            "rules": ["every operation is explicit", "merge preserves evidence and claims",
                      "apply is hash-bound, preflighted, locked, and committed"],
        },
    }


def validate(audit_doc, plan):
    if audit_doc.get("purpose") != "laconic-structure-audit" \
            or plan.get("purpose") != "laconic-structure-plan" \
            or plan.get("review_id") != audit_doc.get("review_id"):
        raise ValueError("mismatched structural audit and plan")
    operations = plan.get("operations")
    if not isinstance(operations, list):
        raise ValueError("operations must be a list")
    out = []
    for index, operation in enumerate(operations, 1):
        if not isinstance(operation, dict) or operation.get("kind") not in KINDS:
            raise ValueError(f"operation #{index} has invalid kind")
        kind = operation["kind"]
        required = {
            "rename-domain": ("from", "to"), "set-domain": ("concept", "to"),
            "remove-project": ("path",), "replace-project": ("from", "to"),
            "rename-concept": ("from", "to"), "merge-concepts": ("from", "into"),
        }[kind]
        if any(not isinstance(operation.get(key), str) or not operation[key].strip()
               for key in required):
            raise ValueError(f"operation #{index} misses {required}")
        for key in required:
            if key != "path" and (key in ("concept", "into") or "domain" in kind
                                  or kind in ("rename-concept", "merge-concepts")):
                if key not in ("from", "to") or kind not in ("remove-project", "replace-project"):
                    value = operation[key]
                    if (key in ("concept", "into") or "concept" in kind or "domain" in kind) \
                            and not ID.fullmatch(value):
                        raise ValueError(f"operation #{index} has invalid id")
        out.append(operation)
    return out


def scalar_list(value):
    return [item.strip() for item in str(value or "").strip("[]").split(",") if item.strip()]


def rewrite_all(concepts, old, new):
    for path in concepts.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        text = text.replace(f"{old}/", f"{new}/")
        lines = []
        for line in text.splitlines(keepends=True):
            if line.startswith("depends-on:"):
                line = re.sub(rf"(?<![a-z0-9-]){re.escape(old)}(?![a-z0-9-])", new, line)
            lines.append(line)
        text = "".join(lines)
        atomic_write_text(path, text)


def apply_operation(concepts, operation):
    kind = operation["kind"]
    if kind in ("rename-domain", "set-domain"):
        for path in concepts.glob("*.md"):
            meta, evidence, body = parse_existing(path)
            if kind == "rename-domain" and meta.get("domain") != operation["from"]:
                continue
            if kind == "set-domain" and meta.get("id", path.stem) != operation["concept"]:
                continue
            meta["domain"] = operation["to"]
            atomic_write_text(path, render(meta, evidence, body))
        return
    if kind in ("remove-project", "replace-project"):
        old, new = operation.get("path") or operation["from"], operation.get("to")
        for path in concepts.glob("*.md"):
            meta, evidence, body = parse_existing(path)
            projects = scalar_list(meta.get("projects"))
            if old not in projects:
                continue
            projects = [new if item == old and new else item for item in projects if item != old or new]
            meta["projects"] = "[" + ", ".join(dict.fromkeys(projects)) + "]" if projects else ""
            atomic_write_text(path, render(meta, evidence, body))
        return
    source = operation["from"]
    target = operation.get("to") or operation.get("into")
    source_path, target_path = concepts / f"{source}.md", concepts / f"{target}.md"
    if not source_path.exists():
        raise ValueError(f"unknown source concept {source}")
    if kind == "rename-concept":
        if target_path.exists():
            raise ValueError(f"target concept already exists: {target}")
        meta, evidence, body = parse_existing(source_path)
        meta["id"] = target
        aliases = scalar_list(meta.get("aliases"))
        meta["aliases"] = "[" + ", ".join(dict.fromkeys(aliases + [source])) + "]"
        atomic_write_text(target_path, render(meta, evidence, body))
        source_path.unlink()
        rewrite_all(concepts, source, target)
        return
    if not target_path.exists() or source == target:
        raise ValueError("merge needs two distinct existing concepts")
    sm, se, sb = parse_existing(source_path)
    tm, te, tb = parse_existing(target_path)
    offset = len(te)
    te.extend(se)
    source_knowledge = get_section(sb, ESTABLISHED_KNOWLEDGE)
    source_knowledge = re.sub(
        r"\(evidence: ([^)]+)\)",
        lambda match: "(evidence: " + ", ".join(
            str(int(value.strip()) + offset) for value in match.group(1).split(",")) + ")",
        source_knowledge,
    )
    knowledge = "\n".join(filter(None, [get_section(tb, ESTABLISHED_KNOWLEDGE), source_knowledge]))
    source_capabilities = re.sub(
        r"\[source-evidence: ([1-9][0-9]*)\]",
        lambda match: f"[source-evidence: {int(match.group(1)) + offset}]",
        get_section(sb, CAPABILITIES),
    )
    capabilities = "\n".join(filter(None, [get_section(tb, CAPABILITIES),
                                             source_capabilities]))
    tb = set_section(tb, ESTABLISHED_KNOWLEDGE, knowledge)
    tb = set_section(tb, CAPABILITIES, capabilities)
    for heading in (UNDERSTANDS, NOT_ESTABLISHED):
        combined = "\n\n".join(filter(None, [get_section(tb, heading),
                                               get_section(sb, heading)]))
        if combined:
            tb = set_section(tb, heading, combined)
    states = ["unknown", "exposed", "familiar", "verified"]
    tm["state"] = max((tm.get("state", "unknown"), sm.get("state", "unknown")), key=states.index)
    tm["confidence"] = str(max(float(tm.get("confidence", 0)), float(sm.get("confidence", 0))))
    tm["last-updated"] = max(tm.get("last-updated", ""), sm.get("last-updated", ""))
    projects = list(dict.fromkeys(scalar_list(tm.get("projects")) + scalar_list(sm.get("projects"))))
    tm["projects"] = "[" + ", ".join(projects) + "]" if projects else ""
    aliases = list(dict.fromkeys(scalar_list(tm.get("aliases")) +
                                 scalar_list(sm.get("aliases")) + [source]))
    tm["aliases"] = "[" + ", ".join(aliases) + "]"
    atomic_write_text(target_path, render(tm, te, tb))
    source_path.unlink()
    rewrite_all(concepts, source, target)


def preflight(model_home, operations):
    temporary = tempfile.TemporaryDirectory(prefix="laconic-structure-")
    staged = Path(temporary.name) / "model"
    shutil.copytree(model_home / "concepts", staged / "concepts")
    for operation in operations:
        apply_operation(staged / "concepts", operation)
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("laconic_lint.py")),
                             "--home", str(staged), "--quiet"], capture_output=True, text=True)
    if result.returncode:
        temporary.cleanup()
        raise ValueError("preflight lint failed: " + (result.stdout + result.stderr).strip())
    return temporary, staged


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit"); a.add_argument("--out", required=True, type=Path)
    r = sub.add_parser("review"); r.add_argument("--audit", required=True, type=Path); r.add_argument("--plan", required=True, type=Path); r.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("apply"); p.add_argument("--audit", required=True, type=Path); p.add_argument("--plan", required=True, type=Path); p.add_argument("--confirm-review-id", required=True)
    args = parser.parse_args(); model_home = home()
    try:
        if args.command == "audit":
            document = audit(model_home); atomic_write_text(args.out, json.dumps(document, indent=2) + "\n")
            print(f"Audited {len(load_concepts(model_home / 'concepts'))} concepts; model unchanged. Review: {document['review_id']}")
            return 0
        audit_doc, plan = load(args.audit), load(args.plan)
        operations = validate(audit_doc, plan)
        if args.command == "review":
            lines = ["# Laconic structural reconciliation", "", f"Review: `{audit_doc['review_id']}`", "",
                     "Nothing has been applied.", ""]
            lines.extend(f"- {json.dumps(operation, ensure_ascii=False, sort_keys=True)}" for operation in operations)
            atomic_write_text(args.out, "\n".join(lines) + "\n"); print(f"Rendered {len(operations)} operations; model unchanged."); return 0
        if args.confirm_review_id != audit_doc["review_id"] or digest(model_home) != audit_doc["model_hash"]:
            raise ValueError("review id mismatch or model changed since audit")
        temporary, staged = preflight(model_home, operations)
        ensure_repo(model_home); lock = acquire_model_lock(model_home)
        if lock is None or digest(model_home) != audit_doc["model_hash"]:
            temporary.cleanup(); raise ValueError("model lock busy or model changed")
        current = model_home / "concepts"
        expected = {path.name for path in (staged / "concepts").glob("*.md")}
        for path in current.glob("*.md"):
            if path.name not in expected: path.unlink()
        for source in (staged / "concepts").glob("*.md"):
            atomic_write_text(current / source.name, source.read_text())
        temporary.cleanup(); write_index_file(date.today()); git_commit(model_home, f"apply structural review {audit_doc['review_id'][:12]}"); git_push_async(model_home)
        print(f"Applied {len(operations)} structural operation(s).")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
