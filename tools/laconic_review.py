#!/usr/bin/env python3
"""Validate and render transcript-derived model proposals without applying them."""

import argparse
import hashlib
import json
import re
import shlex
import sys
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path

from laconic_lint import SECRET_PATTERNS
from laconic_record import (EVIDENCE_BASES, EVIDENCE_KINDS, ID_RE, STATES, THEORY_KINDS,
                            home)

TOP_KEYS = {"schema_version", "purpose", "review_id", "proposals"}
PROPOSAL_KEYS = {
    "concept_id", "domain", "state", "basis", "kind", "evidence", "source_refs",
    "attribution", "attribution_rationale", "capability", "not_established", "rationale",
}
CAPABILITY_KEYS = {"claim", "condition", "scope"}


def load_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc


def one_line(value, label, required=True):
    if value is None and not required:
        return
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{label} must be one non-empty line")
    for secret, pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{label} looks like a {secret}")


def proposal_id(proposal):
    payload = json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalized(value):
    return " ".join(re.findall(r"[\w-]+", value.casefold()))


def existing_observations(model_home):
    sources, evidence = set(), {}
    concepts = model_home / "concepts"
    for path in concepts.glob("*.md") if concepts.is_dir() else []:
        text = path.read_text(encoding="utf-8", errors="ignore")
        sources.update(re.findall(r"transcript:([0-9a-f]{64})", text))
        rows = []
        for line in re.findall(r"^  - \d{4}-\d{2}-\d{2}: (.*)$", text, re.M):
            description = re.split(r" \[(?:basis|kind|sources):", line, maxsplit=1)[0]
            rows.append(description)
        evidence[path.stem] = rows
    return sources, evidence


def duplicate_warnings(proposal, evidence):
    candidate = normalized(proposal["evidence"])
    warnings = []
    for concept, rows in evidence.items():
        for prior in rows:
            old = normalized(prior)
            if candidate == old and concept == proposal["concept_id"]:
                raise ValueError("proposal duplicates existing evidence exactly")
            if min(len(candidate.split()), len(old.split())) >= 5 \
                    and SequenceMatcher(None, candidate, old).ratio() >= 0.72:
                warnings.append(
                    f"possible semantic duplicate in {concept}: {prior}"
                )
    return warnings


def verify_bundle_binding(bundle):
    if bundle.get("review_binding") != "sha256-projects-since-turns-v1":
        return
    payload = {
        "projects": bundle.get("projects"),
        "since": bundle.get("since"),
        "turns": bundle.get("turns"),
    }
    expected = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if bundle.get("review_id") != expected:
        raise ValueError("bootstrap bundle content does not match its review_id")


def validate(bundle, document, model_home=None):
    if bundle.get("purpose") != "laconic-bootstrap-review" or bundle.get("schema_version") != 1:
        raise ValueError("unsupported bootstrap bundle")
    verify_bundle_binding(bundle)
    if set(document) - TOP_KEYS:
        raise ValueError("unknown proposal document field(s): "
                         + ", ".join(sorted(set(document) - TOP_KEYS)))
    if document.get("purpose") != "laconic-bootstrap-proposals" \
            or document.get("schema_version") != 1:
        raise ValueError("unsupported proposal document")
    if document.get("review_id") != bundle.get("review_id"):
        raise ValueError("proposal review_id does not match the bootstrap bundle")
    proposals = document.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("proposals must be a list")

    sources = {turn.get("source_ref"): turn for turn in bundle.get("turns", [])}
    known_sources, known_evidence = existing_observations(model_home) \
        if model_home is not None else (set(), {})
    validated = []
    observations = set()
    proposed_evidence = set()
    for number, proposal in enumerate(proposals, 1):
        label = f"proposal #{number}"
        if not isinstance(proposal, dict):
            raise ValueError(f"{label} must be an object")
        unknown = set(proposal) - PROPOSAL_KEYS
        if unknown:
            raise ValueError(f"{label} has unknown field(s): {', '.join(sorted(unknown))}")
        concept = proposal.get("concept_id")
        domain = proposal.get("domain")
        basis = proposal.get("basis", "direct")
        kind = proposal.get("kind", "term")
        state = proposal.get("state")
        if not isinstance(concept, str) or not ID_RE.fullmatch(concept):
            raise ValueError(f"{label} concept_id must be lowercase kebab-case")
        if not isinstance(domain, str) or not ID_RE.fullmatch(domain):
            raise ValueError(f"{label} domain must be lowercase kebab-case")
        if basis not in EVIDENCE_BASES:
            raise ValueError(f"{label} has unknown basis '{basis}'")
        if kind not in EVIDENCE_KINDS:
            raise ValueError(f"{label} has unknown kind '{kind}'")
        if state is not None and state not in STATES:
            raise ValueError(f"{label} has unknown state '{state}'")
        if basis == "inference" and state not in (None, "unknown"):
            raise ValueError(f"{label} inference cannot propose a state change")
        if basis != "inference" and state is None:
            raise ValueError(f"{label} direct or confirmation evidence requires state")
        if state == "verified" and basis != "confirmation":
            raise ValueError(f"{label} bootstrap may verify only explicit confirmation")
        one_line(proposal.get("evidence"), f"{label} evidence")
        one_line(proposal.get("not_established"), f"{label} not_established", required=False)
        one_line(proposal.get("rationale"), f"{label} rationale", required=False)

        refs = proposal.get("source_refs")
        if not isinstance(refs, list) or not refs or any(ref not in sources for ref in refs):
            raise ValueError(f"{label} source_refs must name bundle sources")
        if len(refs) != 1:
            raise ValueError(f"{label} must represent exactly one transcript observation")
        if len(refs) != len(set(refs)):
            raise ValueError(f"{label} repeats a source_ref")
        source = sources[refs[0]]
        if source.get("analysis_eligible") is False:
            raise ValueError(f"{label} source is quarantined as "
                             f"{source.get('attribution', 'attribution-risk')}")
        attribution_required = any(
            "analysis_eligible" in turn for turn in bundle.get("turns", [])
        )
        if attribution_required:
            if proposal.get("attribution") != "self":
                raise ValueError(f"{label} attribution must be self")
            one_line(proposal.get("attribution_rationale"),
                     f"{label} attribution_rationale")
        observation = (concept, refs[0])
        if observation in observations:
            raise ValueError(f"{label} duplicates a concept/source observation")
        observations.add(observation)
        evidence_key = (concept, normalized(proposal.get("evidence", "")))
        if evidence_key in proposed_evidence:
            raise ValueError(f"{label} duplicates proposed evidence for {concept}")
        proposed_evidence.add(evidence_key)
        if refs[0] in known_sources:
            raise ValueError(f"{label} source is already present in the model")
        timestamp = sources[refs[0]].get("timestamp") or ""
        try:
            date.fromisoformat(timestamp[:10])
        except ValueError as exc:
            raise ValueError(f"{label} source has no usable ISO timestamp") from exc

        capability = proposal.get("capability")
        if capability is not None:
            if not isinstance(capability, dict) or set(capability) - CAPABILITY_KEYS:
                raise ValueError(f"{label} capability has an invalid shape")
            if basis == "inference" or kind not in THEORY_KINDS:
                raise ValueError(f"{label} capability needs non-inferred strong evidence")
            if capability.get("scope", "project") != "project":
                raise ValueError(f"{label} bootstrap capability scope must be project")
            one_line(capability.get("claim"), f"{label} capability claim")
            one_line(capability.get("condition"), f"{label} capability condition",
                     required=False)
        warnings = duplicate_warnings(proposal, known_evidence) \
            if model_home is not None else []
        validated.append({**proposal, "proposal_id": proposal_id(proposal),
                          "duplicate_warnings": warnings})
    return validated, sources


def record_args(proposal, sources):
    parts = [proposal["concept_id"]]
    basis = proposal.get("basis", "direct")
    if basis != "inference":
        parts += ["--state", proposal["state"]]
    parts += ["--domain", proposal["domain"], "--basis", basis,
              "--kind", proposal.get("kind", "term"),
              "--source-ref", ",".join(
                  f"transcript:{ref}" for ref in proposal["source_refs"]),
              "--date", sources[proposal["source_refs"][0]]["timestamp"][:10],
              "--evidence", proposal["evidence"]]
    capability = proposal.get("capability")
    if capability:
        parts += ["--capability", capability["claim"]]
        if capability.get("condition"):
            parts += ["--capability-condition", capability["condition"]]
    if proposal.get("not_established"):
        parts += ["--not-established", proposal["not_established"]]
    return parts


def command(proposal, sources):
    return " ".join(shlex.quote(value) for value in
                    ["~/.laconic/bin/laconic-record", *record_args(proposal, sources)])


def render(bundle, proposals, sources):
    lines = ["# Laconic bootstrap proposals", "", f"Review: `{bundle['review_id']}`",
             "Projects: " + ", ".join(
                 f"`{project}`" for project in bundle.get("projects")
                 or [bundle.get("project")]), "",
             "Nothing below has been applied. Accept, edit, or reject each proposal.", ""]
    for proposal in proposals:
        lines += [f"## [ ] {proposal['concept_id']} — `{proposal['proposal_id']}`", "",
                  f"- Basis/kind: `{proposal.get('basis', 'direct')}` / "
                  f"`{proposal.get('kind', 'term')}`",
                  f"- Proposed state: `{proposal.get('state') or 'unchanged'}`",
                  f"- Evidence description: {proposal['evidence']}"]
        if proposal.get("attribution"):
            lines.append(f"- Attribution: `self` — {proposal['attribution_rationale']}")
        for warning in proposal.get("duplicate_warnings", []):
            lines.append(f"- **Duplicate warning:** {warning}")
        if proposal.get("capability"):
            lines.append(f"- Capability: {proposal['capability']['claim']} (`project`)")
        if proposal.get("not_established"):
            lines.append(f"- Gap: {proposal['not_established']}")
        if proposal.get("rationale"):
            lines.append(f"- Rationale: {proposal['rationale']}")
        lines.append("- Sources:")
        for ref in proposal["source_refs"]:
            preview = " ".join(sources[ref]["text"].split())[:240]
            preview = preview.replace("`", "'").replace("<", "&lt;")
            lines.append(f"  - `{ref[:12]}` — {preview}")
        lines += ["", "```bash", command(proposal, sources), "```", ""]
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--proposals", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="private Markdown review; stdout if omitted")
    parser.add_argument("--decisions-template", type=Path,
                        help="JSON accept/reject template keyed by stable proposal ids")
    args = parser.parse_args()
    try:
        bundle = load_json(args.bundle, "bundle")
        document = load_json(args.proposals, "proposals")
        proposals, sources = validate(bundle, document, home())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output = render(bundle, proposals, sources)
    for path in (args.out, args.decisions_template):
        if path and path.exists():
            print(f"error: refusing to overwrite {path}", file=sys.stderr)
            return 2
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"Rendered {len(proposals)} proposal(s) to {args.out}; model unchanged.")
    else:
        print(output, end="")
    if args.decisions_template:
        args.decisions_template.parent.mkdir(parents=True, exist_ok=True)
        args.decisions_template.write_text(json.dumps({
            "schema_version": 1,
            "purpose": "laconic-bootstrap-decisions",
            "review_id": bundle["review_id"],
            "decisions": [{"proposal_id": item["proposal_id"], "decision": None}
                          for item in proposals],
        }, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote decision template to {args.decisions_template}; fill every decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
