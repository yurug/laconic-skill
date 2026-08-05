#!/usr/bin/env python3
"""Audit model lifecycle signals and gate an infrequent silent reconciliation pass."""

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from laconic_index import days_since, effective_state, load_concepts

DEFAULT_INTERVAL_DAYS = 30
URGENT_CANDIDATE_COUNT = 3


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def findings(concepts, today=None):
    today = today or date.today()
    out = {"stale": [], "expired": [], "contradictions": [], "undistilled": []}
    refs = {}
    for concept in concepts:
        cid = concept["id"]
        effective = effective_state(
            concept["state"], days_since(concept.get("last-updated"), today),
            concept.get("observations", 0),
        )
        if effective != concept["state"]:
            out["stale"].append({
                "concept": cid, "stored": concept["state"], "effective": effective or "dropped",
            })
        capabilities = concept.get("capabilities", ())
        exact = {item.get("source_evidence") for item in capabilities
                 if item.get("source_evidence") is not None}
        legacy = {(item.get("date"), item.get("kind")) for item in capabilities
                  if item.get("source_evidence") is None}
        for evidence in concept.get("strong_evidence", ()):
            if (evidence.get("basis", "direct") != "inference"
                    and evidence.get("index") not in exact
                    and (evidence.get("date"), evidence.get("kind")) not in legacy):
                out["undistilled"].append({
                    "concept": cid, "evidence": evidence["index"],
                    "kind": evidence.get("kind", "world"),
                })
        for capability in capabilities:
            cap_id = capability.get("capability_id", "capability")
            ref = f"{cid}/{cap_id}"
            refs[ref] = capability
            expiry = capability.get("valid_until")
            if expiry and not capability.get("retracted"):
                try:
                    if today > date.fromisoformat(expiry):
                        out["expired"].append({"capability": ref, "expired": expiry})
                except ValueError:
                    pass  # lint owns malformed dates
    seen = set()
    for ref, capability in refs.items():
        if capability.get("retracted"):
            continue
        for other in capability.get("contradicts", ()):
            if other in refs and not refs[other].get("retracted"):
                pair = tuple(sorted((ref, other)))
                if pair not in seen:
                    seen.add(pair)
                    out["contradictions"].append({"capabilities": list(pair)})
    return out


def count(result):
    return sum(len(items) for items in result.values())


def signature(result):
    """Stable identity of findings, so a reviewed unchanged backlog stays quiet."""
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reviewed_signature():
    try:
        return (home() / ".reconciled-signature").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def is_due(interval_days=DEFAULT_INTERVAL_DAYS, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        stamp = datetime.fromisoformat(
            (home() / ".reconciled-at").read_text(encoding="utf-8").strip()
        )
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return now - stamp >= timedelta(days=interval_days)
    except (OSError, ValueError):
        return True


def begin(interval_days=DEFAULT_INTERVAL_DAYS):
    result = findings(load_concepts())
    total = count(result)
    if not total:
        if is_due(interval_days):
            complete(signature(result))
        return 0
    current_signature = signature(result)
    urgent = (len(result["undistilled"]) >= URGENT_CANDIDATE_COUNT
              or bool(result["contradictions"]))
    if not is_due(interval_days) and not (
        urgent and current_signature != reviewed_signature()
    ):
        return 0
    try:
        (home() / ".reconciliation-pending").write_text(
            json.dumps({
                "counts": {key: len(value) for key, value in result.items()},
                "signature": current_signature,
            }) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return 0
    return total


def complete(current_signature=None):
    now = datetime.now(timezone.utc).isoformat()
    try:
        if current_signature is None:
            try:
                pending = json.loads(
                    (home() / ".reconciliation-pending").read_text(encoding="utf-8")
                )
                current_signature = pending.get("signature", "")
            except (OSError, ValueError):
                current_signature = ""
        (home() / ".reconciled-at").write_text(now + "\n", encoding="utf-8")
        (home() / ".reconciled-signature").write_text(
            (current_signature or "") + "\n", encoding="utf-8"
        )
        (home() / ".reconciliation-pending").unlink(missing_ok=True)
    except OSError:
        pass


def render(result):
    lines = ["Laconic reconciliation report (mechanical signals only):"]
    for item in result["stale"]:
        lines.append(f"- stale: {item['concept']} {item['stored']} -> {item['effective']}")
    for item in result["expired"]:
        lines.append(f"- expired: {item['capability']} after {item['expired']}")
    for item in result["contradictions"]:
        lines.append(f"- explicit contradiction: {' <> '.join(item['capabilities'])}")
    for item in result["undistilled"]:
        lines.append(
            f"- undistilled [{item['kind']}]: "
            f"{item['concept']} evidence #{item['evidence']}"
        )
    if len(lines) == 1:
        lines.append("- no lifecycle findings")
    lines.append(
        "Decay and expiry already affect retrieval. Change the model only when its stored "
        "claim is obsolete or evidence directly supports a distillation/retraction."
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--begin", action="store_true")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--interval-days", type=int, default=DEFAULT_INTERVAL_DAYS)
    args = parser.parse_args()
    if args.complete:
        complete()
    elif args.begin:
        total = begin(max(1, args.interval_days))
        if total:
            print(total)
    else:
        print(render(findings(load_concepts())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
