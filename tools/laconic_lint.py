#!/usr/bin/env python3
"""Validate the laconic knowledge model.

There is no build to fail here, so this is the only mechanical guarantee that the model
stays trustworthy. Errors (exit 1) mean the model is malformed or unfounded; warnings
mean it needs attention but is still usable.
"""

import argparse
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from laconic_index import (  # noqa: E402
    CAPABILITIES,
    CAPABILITY_EXTENDED_RE,
    CAPABILITY_REF_RE,
    NOT_ESTABLISHED,
    STATES,
    SUMMARY_AFTER,
    get_section,
    parse_frontmatter,
)
from laconic_record import EVIDENCE_BASES, EVIDENCE_KINDS, KIND_RE  # noqa: E402

REQUIRED = ["id", "type", "state", "confidence", "last-updated"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Credential shapes that should never appear in a committed model, especially when its user
# configured a sync remote. Deliberately only high-signal patterns: a heuristic that flagged
# "any long
# random-looking string" would cry wolf on hashes and identifiers, and a check people learn to
# ignore is worse than no check. The policy is broader than what can be detected -- the rule
# is to describe the observation, not the content -- so this is a backstop, not the boundary.
SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("inline password", re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key)\s*[:=]\s*\S+")),
]

# A concept untouched for this long has drifted from whatever evidence produced it.
STALE_DAYS = 180
# The rendered index is prepended to every session; keep it from silently growing.
#
# Sized to what the design actually renders in its worst project-scoped case, not to an
# aspiration. A broad cwd does not make every child project relevant: relevance is directional
# precisely so a session in ~/ cannot inline the whole model.
INDEX_BUDGET = 1850


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, path, msg):
        self.errors.append(f"{path.name}: {msg}")

    def warn(self, path, msg):
        self.warnings.append(f"{path.name}: {msg}")


def read_evidence(text):
    """Evidence lines are a YAML list under `evidence:`; parse_frontmatter skips them."""
    body = text.split("---")[1] if text.startswith("---") else ""
    out, in_block = [], False
    for line in body.splitlines():
        if re.match(r"^evidence:\s*$", line):
            in_block = True
            continue
        if in_block:
            if line.startswith("  - ") or line.startswith("- "):
                out.append(line.strip()[2:].strip())
            elif line.strip() and not line.startswith(" "):
                break
    return out


def check_concept(path, report, today):
    text = path.read_text(encoding="utf-8")
    meta = parse_frontmatter(path)
    if meta is None:
        report.error(path, "no parseable YAML frontmatter")
        return None

    for key in REQUIRED:
        if key not in meta:
            report.error(path, f"missing required key '{key}'")

    state = meta.get("state")
    if state and state not in STATES:
        report.error(path, f"state '{state}' not one of {STATES}")

    raw_conf = meta.get("confidence")
    if raw_conf is not None:
        try:
            conf = float(raw_conf)
            if not 0.0 <= conf <= 1.0:
                report.error(path, f"confidence {conf} outside [0,1]")
        except ValueError:
            report.error(path, f"confidence '{raw_conf}' is not a number")

    updated = meta.get("last-updated")
    if updated:
        if not DATE_RE.match(str(updated)):
            report.error(path, f"last-updated '{updated}' is not ISO YYYY-MM-DD")
        else:
            try:
                d = datetime.strptime(str(updated), "%Y-%m-%d").date()
                if d > today:
                    report.error(path, f"last-updated '{updated}' is in the future")
                elif (today - d).days > STALE_DAYS:
                    report.warn(
                        path,
                        f"not updated in {(today - d).days} days — decay confidence "
                        f"or re-establish",
                    )
            except ValueError:
                report.error(path, f"last-updated '{updated}' is not a real date")

    # The auditability guarantee: any asserted knowledge must cite an observation.
    evidence = read_evidence(text)
    if state and state != "unknown" and not evidence:
        report.error(
            path,
            f"state '{state}' asserted with no evidence — every claim above 'unknown' "
            f"needs a dated observation",
        )
    for line in evidence:
        if not DATE_RE.match(line.split(":")[0].strip()):
            report.warn(path, f"evidence line not dated 'YYYY-MM-DD: ...': {line[:40]}")
        # A mistyped kind would silently leave the line out of every kind-based count, so it
        # reads as unclassified rather than as the thing it was meant to be.
        m = KIND_RE.match(line.split(":", 1)[-1].strip())
        if m and m.group(1) not in EVIDENCE_KINDS:
            report.error(path, f"unknown evidence kind '[{m.group(1)}]', "
                               f"expected one of {EVIDENCE_KINDS}")
        basis = re.search(r"\[basis: ([^\]]+)\]", line)
        if basis and basis.group(1) not in EVIDENCE_BASES:
            report.error(path, f"unknown evidence basis '{basis.group(1)}', "
                               f"expected one of {EVIDENCE_BASES}")

    body = text.split("\n---", 1)[1] if "\n---" in text else ""
    capability_lines = [
        line.strip() for line in get_section(body, CAPABILITIES).splitlines() if line.strip()
    ]
    parsed_capabilities = []
    for line in capability_lines:
        match = CAPABILITY_EXTENDED_RE.fullmatch(line)
        if not match:
            report.error(path, f"malformed capability claim: {line[:60]}")
            continue
        parsed_capabilities.append(match.groups())
        kind, _, observed = match.group(1), match.group(2), match.group(3)
        if not any(item.startswith(f"{observed}: [{kind}]") for item in evidence):
            report.error(
                path,
                f"capability [{kind}] cites {observed}, but no matching evidence exists",
            )
        valid_until, retracted, reason = match.group(6), match.group(12), match.group(13)
        if valid_until:
            try:
                expiry = date.fromisoformat(valid_until)
                if expiry < date.fromisoformat(observed):
                    report.error(path,
                                 f"capability expires before its evidence date ({valid_until})")
            except ValueError:
                report.error(path, f"capability expiry '{valid_until}' is not a real date")
        if retracted:
            try:
                retraction_date = date.fromisoformat(retracted)
                if retraction_date > today:
                    report.error(path, f"capability retraction '{retracted}' is in the future")
            except ValueError:
                report.error(path, f"capability retraction '{retracted}' is not a real date")
            if not reason:
                report.error(path, "retracted capability has no retraction reason")
        elif reason:
            report.error(path, "capability has a retraction reason but no retraction date")

    # Credentials in a committed file. An error, not a warning: a configured remote could
    # sync it while someone decided what to do about it.
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            report.error(
                path,
                f"looks like a {label} — evidence is committed and may be synced. "
                f"Describe the observation, not the content, then rotate the credential",
            )

    # Accumulated evidence with no distillation. A warning, not an error: the concept is
    # still usable, it just carries less than it has earned. Only the gap half is checked
    # because only that half is injected -- `state` already carries the other one.
    if len(evidence) >= SUMMARY_AFTER and not meta.get("_gap"):
        report.warn(
            path,
            f"{len(evidence)} observations, no '{NOT_ESTABLISHED}' section — distil it "
            f"with laconic_record.py --not-established so the gap reaches the injection",
        )
    exact_covered = {int(groups[10]) for groups in parsed_capabilities if groups[10]}
    legacy_covered = {(groups[2], groups[0]) for groups in parsed_capabilities if not groups[10]}
    strong = []
    for index, line in enumerate(evidence, 1):
        match = re.match(
            r"^(\d{4}-\d{2}-\d{2}): \[(world|justification|modification)\] "
            r"(?!\[basis: inference\])", line
        )
        if (match and index not in exact_covered
                and match.groups() not in legacy_covered):
            strong.append(index)
    if strong:
        report.warn(
            path,
            f"{len(strong)} undistilled strong observation(s), including evidence "
            f"#{strong[0]} — review with laconic-candidates",
        )

    concept_id = meta.get("id")
    if concept_id and concept_id != path.stem:
        report.error(path, f"id '{concept_id}' does not match filename stem '{path.stem}'")

    return meta


def check_graph(metas, report, paths_by_id):
    ids = set(metas)
    for cid, meta in metas.items():
        for dep in meta.get("depends-on", []) or []:
            if dep not in ids:
                report.error(paths_by_id[cid], f"depends-on '{dep}' does not exist")

    # Cycles make the prerequisite structure incoherent and graph traversal unreliable.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {cid: WHITE for cid in ids}

    def visit(node, stack):
        if colour[node] == GREY:
            cycle = " -> ".join(stack[stack.index(node):] + [node])
            report.error(paths_by_id[node], f"dependency cycle: {cycle}")
            return
        if colour[node] == BLACK:
            return
        colour[node] = GREY
        for dep in metas[node].get("depends-on", []) or []:
            if dep in colour:
                visit(dep, stack + [node])
        colour[node] = BLACK

    for cid in sorted(ids):
        if colour[cid] == WHITE:
            visit(cid, [])


def check_capability_graph(metas, report, paths_by_id):
    """Validate capability identity and relations independently of concept dependencies."""
    capabilities = {}
    for concept_id, meta in metas.items():
        local = set()
        for capability in meta.get("_capabilities", ()):
            capability_id = capability["capability_id"]
            ref = f"{concept_id}/{capability_id}"
            if capability_id in local:
                report.error(paths_by_id[concept_id], f"duplicate capability id '{capability_id}'")
            local.add(capability_id)
            capabilities[ref] = (concept_id, capability)

    for ref, (concept_id, capability) in capabilities.items():
        relations = set()
        for relation in ("requires", "supersedes", "contradicts"):
            for target in capability.get(relation, ()):
                if not CAPABILITY_REF_RE.fullmatch(target):
                    report.error(paths_by_id[concept_id],
                                 f"{relation} has invalid capability reference '{target}'")
                elif target not in capabilities:
                    report.error(paths_by_id[concept_id],
                                 f"{relation} capability '{target}' does not exist")
                if target == ref:
                    report.error(paths_by_id[concept_id], f"capability '{ref}' {relation} itself")
                if target in relations:
                    report.error(paths_by_id[concept_id],
                                 f"capability '{ref}' relates to '{target}' in multiple ways")
                relations.add(target)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {ref: WHITE for ref in capabilities}

    def visit(ref, stack):
        if colour[ref] == GREY:
            cycle = " -> ".join(stack[stack.index(ref):] + [ref])
            concept_id = capabilities[ref][0]
            report.error(paths_by_id[concept_id], f"capability prerequisite cycle: {cycle}")
            return
        if colour[ref] == BLACK:
            return
        colour[ref] = GREY
        for required in capabilities[ref][1].get("requires", ()):
            if required in capabilities:
                visit(required, stack + [ref])
        colour[ref] = BLACK

    for ref in sorted(capabilities):
        if colour[ref] == WHITE:
            visit(ref, [])


def main():
    ap = argparse.ArgumentParser(description="Validate the laconic knowledge model.")
    ap.add_argument(
        "--home",
        default=os.environ.get("LACONIC_HOME") or str(Path.home() / ".laconic"),
        help="laconic home directory (default: ~/.laconic)",
    )
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args()

    concepts_dir = Path(args.home) / "concepts"
    report = Report()
    today = date.today()

    if not concepts_dir.is_dir():
        if not args.quiet:
            print(f"No model yet at {concepts_dir} — nothing to check.")
        return 0

    metas, paths_by_id, seen_ids = {}, {}, {}
    for path in sorted(concepts_dir.glob("*.md")):
        meta = check_concept(path, report, today)
        if not meta:
            continue
        cid = meta.get("id", path.stem)
        if cid in seen_ids:
            report.error(path, f"duplicate id '{cid}' (also in {seen_ids[cid].name})")
            continue
        seen_ids[cid] = path
        metas[cid] = meta
        paths_by_id[cid] = path

    check_graph(metas, report, paths_by_id)
    check_capability_graph(metas, report, paths_by_id)

    # Token discipline, made mechanical so it cannot regress unnoticed.
    os.environ["LACONIC_HOME"] = args.home
    import importlib

    import laconic_index

    importlib.reload(laconic_index)
    # What gets injected depends on the session's cwd -- this project's ids stay inline
    # past the inline limit, which makes a project-scoped session render *larger* than a
    # bare one -- and on decay. Measure the worst case over every project the model has
    # seen, with decay applied, so this checks the largest real injection rather than a
    # smaller hypothetical one.
    all_concepts = laconic_index.load_concepts()
    cwds = {p for c in all_concepts for p in c.get("projects", ())} | {None}
    index_size = max(
        len(laconic_index.render(all_concepts, cwd=cwd, today=today)) for cwd in cwds
    )
    if index_size > INDEX_BUDGET:
        report.warnings.append(
            f"index renders to {index_size} chars, over the {INDEX_BUDGET} budget — "
            f"it is injected into every session"
        )

    for err in report.errors:
        print(f"ERROR  {err}")
    for warn in report.warnings:
        print(f"WARN   {warn}")

    if not args.quiet or report.errors or report.warnings:
        print(
            f"\n{len(metas)} concepts, index {index_size} chars, "
            f"{len(report.errors)} errors, {len(report.warnings)} warnings"
        )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
