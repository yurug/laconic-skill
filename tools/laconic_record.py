#!/usr/bin/env python3
"""Record evidence about what the user knows, in schema-correct form.

This exists because instructing an agent to "maintain ~/.laconic/concepts/" without
giving it the schema produced freeform notes the index silently ignored. One command
that cannot emit a malformed file is cheaper, in tokens and in failure modes, than
restating the schema in every session.

Examples:
  laconic_record.py tezos-finality --state familiar --domain consensus \\
      --evidence "used the term unprompted while correcting my summary"
  laconic_record.py rust-lifetimes --state exposed --domain rust \\
      --evidence "asked what they are"
  laconic_record.py tezos-finality --not-established "the rollup interaction"
  laconic_record.py some-concept --forget "test pollution, not a real observation"
"""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from laconic_index import (  # noqa: E402
    CAPABILITIES,
    CAPABILITY_KINDS,
    CAPABILITY_SCOPES,
    CAPABILITY_REF_RE,
    CAPABILITY_EXTENDED_RE,
    ESTABLISHED_KNOWLEDGE,
    KNOWLEDGE_KINDS,
    KNOWLEDGE_SCOPES,
    NOT_ESTABLISHED,
    SUMMARY_AFTER,
    UNDERSTANDS,
    atomic_write_text,
    capability_id_from_claim,
    get_section,
    heading_re,
    load_concepts,
    write_index_file,
)

# How long to wait for the model lock before spooling. laconic-sync.sh holds it across a
# network fetch and merge, so this is a wait, not a timeout on a stuck process.
# LACONIC_LOCK_WAIT shortens it for tests, which would otherwise sit out the full wait on
# every contended case.
LOCK_WAIT_SECONDS = float(os.environ.get("LACONIC_LOCK_WAIT") or 15)

STATES = ["unknown", "exposed", "familiar", "verified"]
RANK = {s: i for i, s in enumerate(STATES)}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
LEADING_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}:?\s+")

# Evidence kinds, after Naur's three criteria for possessing the theory of a program
# ("Programming as Theory Building", 1985, p.231) plus the term-use evidence laconic
# collected before them:
#
#   term           used the term correctly and unprompted where misuse would have shown
#   world          explained how a solution relates to the affairs of the world it handles
#   justification  explained or challenged why a part is what it is
#   modification   responded constructively to a demand for modification
#
# The last three are theory-evidence. Naur's Case 1 is the argument for ranking them above
# term use: group B held the full annotated program text and still proposed extensions "in
# the form of patches that effectively destroyed its power and simplicity", which group A
# "were able to spot instantly". The difference showed up in a modification proposal, not in
# vocabulary.
#
# An unmarked line is *unclassified*, not `term` -- it predates this distinction, and
# conflating the two would fabricate a baseline for the very measurement this exists to make.
EVIDENCE_KINDS = ["term", "world", "justification", "modification"]
THEORY_KINDS = {"world", "justification", "modification"}
KIND_RE = re.compile(r"^\[([a-z]+)\]\s*")
BASIS_RE = re.compile(r"^\[basis: (direct|confirmation|inference)\]\s*")
SOURCE_RE = re.compile(r"^\[sources: ([^\]]+)\]\s*")
EVIDENCE_BASES = ("direct", "confirmation", "inference")

DEFAULT_CONFIDENCE = {"unknown": 0.1, "exposed": 0.3, "familiar": 0.55, "verified": 0.85}


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def observed_project():
    """The project the observation happened in: git toplevel of the cwd, else the cwd.
    Recorded so the index can keep this project's concepts inline once the model
    outgrows the inline limit."""
    if shutil.which("git"):
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return str(Path.cwd())


def merge_project(meta):
    """Append the current project to the concept's `projects` list, without duplicates.
    The raw frontmatter value is a '[a, b]' string; paths containing commas would split
    wrongly and are not supported."""
    raw = meta.get("projects", "")
    items = []
    if raw.startswith("[") and raw.endswith("]"):
        items = [p.strip() for p in raw[1:-1].split(",") if p.strip()]
    proj = observed_project()
    if proj and proj not in items:
        items.append(proj)
    if items:
        meta["projects"] = "[" + ", ".join(items) + "]"


def git_commit(home_dir, message):
    """Version the model so a wrong inference is visible and revertible. Lazy-inits the
    repo on first write. Identity is passed per-commit so it needs no global git config.
    Silently a no-op if git is unavailable -- versioning is a bonus, not a dependency.
    """
    if not shutil.which("git"):
        return
    subprocess.run(["git", "add", "-A"], cwd=home_dir, check=False)
    subprocess.run(
        [
            "git", "-c", "user.name=laconic", "-c", "user.email=laconic@localhost",
            "commit", "-q", "-m", message,
        ],
        cwd=home_dir,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# Local scratch files that must never be committed: they are per-machine and per-session, so
# syncing them would push one machine's transient state onto the other. `bin/` matters most
# -- its wrappers hold this machine's absolute checkout path, which is wrong on the other.
IGNORED = [
    ".lint-ok",
    ".nudged-*",
    ".session-*",
    ".laconic-tmp-*",
    "laconic.lock",
    "bin/",
    "indexes/",
]


def ensure_repo(home_dir):
    """Create the model repo if absent, and keep .gitignore covering the scratch files.

    Split out of git_commit so it runs *before* the lock is taken: the lock lives inside
    .git (the path laconic-sync.sh shares), so that directory has to exist before there is
    anything to lock.

    The ignore list is reconciled on every call, not just at init. git_commit stages with
    `git add -A`, so a pattern added later would otherwise never reach a model that already
    exists -- and the first symptom would be one machine's session markers syncing to the
    other. Missing lines are appended, so anything the user added is left alone.
    """
    if not shutil.which("git"):
        return
    if not (home_dir / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=home_dir, check=False)

    path = home_dir / ".gitignore"
    try:
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:
        return
    missing = [p for p in IGNORED if p not in existing]
    if missing:
        lines = existing + missing
        atomic_write_text(path, "\n".join(lines) + "\n")


def acquire_model_lock(home_dir):
    """Hold the flock laconic-sync.sh takes, so a record cannot land inside the sync
    script's merge window -- that interleaving corrupted a rebase in practice. Returns
    the open handle (lock lives as long as this short process). Best effort: after ~15s we
    proceed anyway, because recording evidence must never fail on a stuck lock.

    Must be held across the whole read-modify-write cycle, not merely the write. Two
    recorders that each parsed the file before either wrote would both append to the same
    base, and the second write would silently drop the first's observation -- a real lost
    update, since laconic runs on every session and sessions overlap.

    Falls back to a lock beside the model when git is unavailable, so concurrency safety
    does not depend on versioning; the .git path is kept when it exists because
    laconic-sync.sh locks exactly that file.

    Returns None when the wait elapses. Callers must spool rather than proceed: an earlier
    version returned the handle unlocked so that recording "never fails on a stuck lock",
    which traded a loud failure for a silent lost update -- reproducible by holding the lock
    past the wait and firing two recorders. laconic-sync.sh holds this lock across a network
    fetch and merge, so exceeding the wait is a routine event, not a pathological one.
    """
    git_dir = home_dir / ".git"
    lock_dir = git_dir if git_dir.is_dir() else home_dir
    handle = open(lock_dir / "laconic.lock", "w")
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                return None
            time.sleep(0.5)


def push_command(home_dir):
    """The push command authorized by this model repo, or None when none is authorized."""
    if os.environ.get("LACONIC_NO_PUSH") or os.environ.get("LACONIC_PUSH") != "1":
        return None
    if not shutil.which("git") or not (home_dir / ".git").exists():
        return None
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=home_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        return None
    return ["git", "push", "--quiet", "origin", "HEAD"]


def git_push_async(home_dir):
    """Fire-and-forget push so the other machine can pick up new evidence on its next
    sync rather than a timer cycle later. Failures are silent and safe -- the
    laconic-sync.sh timer path is the reliable one; this only shortens the delay. Must
    never block: recording happens inside interactive sessions.

    Both `LACONIC_PUSH=1` and a user-configured `origin` are required. The recorder
    initializes a local git repository for auditability but never creates a remote; without
    both forms of consent, nothing leaves the machine. LACONIC_NO_PUSH disables the path for
    deterministic tests.
    """
    command = push_command(home_dir)
    if command is None:
        return
    subprocess.Popen(
        command,
        cwd=home_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def spool_dir():
    return home() / "spool"


def spool(args, today):
    """Park an observation the lock was not free for, to be folded in by the next run that
    holds it.

    One file per entry rather than one shared append-only file: unique names mean the spool
    itself needs no lock, and a writer that dies mid-entry cannot corrupt a neighbour's. The
    write is published by rename, which is atomic, so a draining reader never sees a
    half-written entry.

    `today` is stored rather than recomputed at drain time -- an observation spooled tonight
    and drained tomorrow must keep the date it was actually observed.
    """
    payload = dict(vars(args))
    payload["_today"] = today
    directory = spool_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    path = directory / f"{stamp}-{os.getpid()}.json"
    tmp = path.with_suffix(".writing")
    atomic_write_text(tmp, json.dumps(payload))
    tmp.rename(path)
    return path


def drain_spool():
    """Fold parked observations into the model, oldest first. The caller must hold the lock.

    Filename order is chronological by construction, which keeps replay in observation
    order. An entry that cannot be parsed or applied is set aside as `.bad` rather than
    retried forever -- one poisoned entry must not block every later record.
    """
    directory = spool_dir()
    if not directory.is_dir():
        return 0
    drained = 0
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            when = payload.pop("_today")
            rc = apply_record(argparse.Namespace(**payload), when, quiet=True)
        except Exception as exc:  # noqa: BLE001 -- a bad entry must not stop the drain
            print(f"  spool: setting aside {path.name} ({exc})", file=sys.stderr)
            path.rename(path.with_suffix(".bad"))
            continue
        if rc != 0:
            path.rename(path.with_suffix(".bad"))
            continue
        path.unlink()
        drained += 1
    return drained


def parse_existing(path):
    """Return (frontmatter_lines, evidence_list, body) from an existing concept file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, [], text
    end = text.find("\n---", 3)
    if end == -1:
        return None, [], text
    fm_block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")

    meta, evidence, in_ev = {}, [], False
    for line in fm_block.splitlines():
        if re.match(r"^evidence:\s*$", line):
            in_ev = True
            continue
        if in_ev:
            if line.startswith("  - ") or line.startswith("- "):
                evidence.append(line.strip()[2:].strip())
                continue
            in_ev = False
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, evidence, body


def find_dependents(concepts_dir, target, exclude):
    """Concept ids whose `depends-on` names `target`, as {id: path}.

    Read with a regex over the raw text rather than through parse_existing, so a file too
    malformed to parse still cannot hide a reference.
    """
    out = {}
    for path in sorted(concepts_dir.glob("*.md")):
        if path == exclude:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = re.search(r"^depends-on:\s*\[(.*?)\]\s*$", text, re.M)
        if m and target in [d.strip() for d in m.group(1).split(",")]:
            out[path.stem] = path
    return out


def dependency_ids(path):
    """Read the narrow inline dependency field without trusting the rest of the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    match = re.search(r"^depends-on:\s*\[(.*?)\]\s*$", text, re.M)
    if not match:
        return []
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def dependency_reaches(concepts_dir, start, target):
    """Whether the existing graph has a path from start to target."""
    pending, seen = [start], set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(dependency_ids(concepts_dir / f"{current}.md"))
    return False


def strip_dependency(path, target):
    """Remove `target` from a file's depends-on list, dropping the key when it empties.

    A dangling `depends-on` is not a cosmetic problem: laconic_lint.py errors on it and
    stop-check.sh blocks on lint errors, so leaving one would turn a deletion into a
    blocked turn on every subsequent stop.
    """
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^depends-on:\s*\[(.*?)\]\s*$", text, re.M)
    if not m:
        return False
    kept = [d.strip() for d in m.group(1).split(",") if d.strip() and d.strip() != target]
    if kept:
        replacement = "depends-on: [" + ", ".join(kept) + "]"
        atomic_write_text(path, text[: m.start()] + replacement + text[m.end() :])
    else:
        # Drop the whole line, including its newline, rather than leave `depends-on: []`
        # -- the index reads that as an empty list, but render() would not emit the key.
        end = m.end() + 1 if text[m.end() : m.end() + 1] == "\n" else m.end()
        atomic_write_text(path, text[: m.start()] + text[end:])
    return True


def forget(concept_id, reason, force, today):
    """Delete a concept and version the deletion, with its reason in the commit message.

    Deletion is part of the contract: an open learner model the user cannot correct or
    delete is just surveillance. The reason is required for the same auditability that
    makes `evidence` required -- an unexplained hole in the history is worse than no
    history. Recoverable either way, since every write is a commit.

    The caller holds the model lock, taken before the existence check so a concurrent
    recorder cannot add a depends-on pointing at this concept between the scan and the
    deletion.
    """
    concepts = home() / "concepts"
    path = concepts / f"{concept_id}.md"
    if not path.exists():
        print(f"error: {concept_id} does not exist — nothing to forget", file=sys.stderr)
        return 2

    dependents = find_dependents(concepts, concept_id, exclude=path)
    if dependents and not force:
        names = ", ".join(sorted(dependents))
        print(
            f"error: {len(dependents)} concept(s) depend on '{concept_id}': {names}\n"
            f"       Forgetting it would leave a dangling depends-on, which makes the lint "
            f"error and blocks turns.\n"
            f"       Re-run with --force to forget it and strip those references.",
            file=sys.stderr,
        )
        return 2

    meta, evidence, _ = parse_existing(path)
    was = (meta or {}).get("state", "unparseable")

    path.unlink()
    for dep_id, dep_path in sorted(dependents.items()):
        if strip_dependency(dep_path, concept_id):
            print(f"  stripped depends-on '{concept_id}' from {dep_id}")

    write_index_file(today)
    git_commit(home(), f"forget {concept_id} ({was}, {len(evidence)} observations) — {reason}")
    git_push_async(home())
    print(f"forgot {concept_id}.md: was {was}, {len(evidence)} observations discarded")
    print(f"  reason recorded in git: {reason}")
    print("  recover with: git -C ~/.laconic revert --no-edit HEAD")
    return 0


def set_section(body, heading, text):
    """Replace the text under `## {heading}`, creating the heading if it is absent.

    Replace, not append. These sections are a standing distillation of the evidence; an
    append-only summary would just rebuild the evidence log in prose, which is what the
    dated `evidence:` list already does better.
    """
    text = text.strip()
    m = heading_re(heading).search(body)
    if not m:
        block = f"## {heading}\n{text}\n"
        return block if not body.strip() else f"{body.rstrip()}\n\n{block}"
    rest = body[m.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    tail = rest[nxt.start() :] if nxt else ""
    head = body[: m.end()]
    return f"{head}\n{text}\n\n{tail}" if tail else f"{head}\n{text}\n"


def add_capability(body, kind, claim, today, scope="project", condition="",
                   capability_id=None, requires=(), supersedes=(), contradicts=(),
                   valid_until="", source_evidence=None):
    """Append one deduplicated capability claim tied to the observation date."""
    claim = " ".join(claim.split())
    condition_suffix = f" [when: {condition}]" if condition else ""
    validity_suffix = f" [valid-until: {valid_until}]" if valid_until else ""
    capability_id = capability_id or capability_id_from_claim(claim)
    relation_suffix = "".join(
        f" [{name}: {', '.join(values)}]" for name, values in (
            ("requires", requires), ("supersedes", supersedes), ("contradicts", contradicts)
        ) if values
    )
    source_suffix = f" [source-evidence: {source_evidence}]" if source_evidence else ""
    line = (f"- [{kind}] {claim} (evidence: {today}) [scope: {scope}]"
            f"{condition_suffix}{validity_suffix} [id: {capability_id}]"
            f"{relation_suffix}{source_suffix}")
    current = get_section(body, CAPABILITIES)
    lines = current.splitlines() if current else []
    prefix = f"- [{kind}] {claim} (evidence: "
    lines = [existing for existing in lines if not existing.startswith(prefix)]
    lines.append(line)
    return set_section(body, CAPABILITIES, "\n".join(lines))


def add_knowledge_claim(body, kind, claim, evidence_numbers, scope="project", condition=""):
    """Append a semantic claim whose provenance is exact and mechanically checkable."""
    claim = " ".join(claim.split())
    sources = ", ".join(str(number) for number in evidence_numbers)
    condition_suffix = f" [when: {condition}]" if condition else ""
    line = f"- [{kind}] {claim} (evidence: {sources}) [scope: {scope}]{condition_suffix}"
    current = get_section(body, ESTABLISHED_KNOWLEDGE)
    lines = current.splitlines() if current else []
    prefix = f"- [{kind}] {claim} (evidence: "
    lines = [existing for existing in lines if not existing.startswith(prefix)]
    lines.append(line)
    return set_section(body, ESTABLISHED_KNOWLEDGE, "\n".join(lines))


def retract_capability(concept_id, capability_id, reason, today):
    """Retain an invalid claim for audit while removing it from future injections."""
    path = home() / "concepts" / f"{concept_id}.md"
    if not path.is_file():
        print(f"error: {concept_id} does not exist", file=sys.stderr)
        return 2
    meta, evidence, body = parse_existing(path)
    if meta is None:
        print(f"error: {path} has malformed frontmatter", file=sys.stderr)
        return 2
    lines = get_section(body, CAPABILITIES).splitlines()
    found = False
    for index, line in enumerate(lines):
        match = CAPABILITY_EXTENDED_RE.fullmatch(line.strip())
        if not match:
            continue
        line_id = match.group(7) or capability_id_from_claim(match.group(2))
        if line_id != capability_id:
            continue
        found = True
        if match.group(12):
            print(f"error: capability '{concept_id}/{capability_id}' is already retracted",
                  file=sys.stderr)
            return 2
        lines[index] = (line.rstrip() + f" [retracted: {today}]"
                        f" [retraction-reason: {reason}]")
        break
    if not found:
        print(f"error: capability '{concept_id}/{capability_id}' does not exist", file=sys.stderr)
        return 2
    body = set_section(body, CAPABILITIES, "\n".join(lines))
    atomic_write_text(path, render(meta, evidence, body))
    write_index_file(today)
    git_commit(home(), f"retract {concept_id}/{capability_id} — {reason}")
    git_push_async(home())
    print(f"retracted {concept_id}/{capability_id}: {reason}")
    return 0


def render(meta, evidence, body):
    order = [
        "id", "type", "domain", "projects", "state", "confidence",
        "depends-on", "last-updated",
    ]
    lines = ["---"]
    for key in order:
        if key in meta and meta[key] not in (None, ""):
            lines.append(f"{key}: {meta[key]}")
    lines.append("evidence:")
    for e in evidence:
        lines.append(f"  - {e}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("concept_id", help="kebab-case id, e.g. tezos-finality")
    # Neither is required when the call only writes a distillation. A summary of evidence
    # is not itself an observation, and forcing --evidence to write one would have made
    # inventing an observation the only way to comply -- the one thing the policy forbids.
    ap.add_argument("--state", choices=STATES, default=None)
    ap.add_argument("--evidence", default=None, help="what you observed, without the date")
    ap.add_argument(
        "--kind",
        choices=EVIDENCE_KINDS,
        default="term",
        help="what kind of evidence this is; the last three are Naur's theory criteria",
    )
    ap.add_argument(
        "--basis", choices=EVIDENCE_BASES, default=None,
        help="how the claim was obtained; weak inference is logged but cannot change state",
    )
    ap.add_argument("--source-ref", default=None,
                    help="comma-separated transcript:<sha256> audit references")
    ap.add_argument(
        "--capability",
        default=None,
        help="ability demonstrated by this evidence; requires world, justification, or modification",
    )
    ap.add_argument(
        "--capability-scope", choices=CAPABILITY_SCOPES, default="project",
        help="where the demonstrated ability transfers; defaults conservatively to project",
    )
    ap.add_argument(
        "--capability-condition", default=None,
        help="condition under which the capability remains valid",
    )
    ap.add_argument("--capability-id", default=None, help="stable kebab-case capability id")
    ap.add_argument("--capability-requires", default=None,
                    help="comma-separated concept/capability prerequisites")
    ap.add_argument("--capability-supersedes", default=None,
                    help="comma-separated concept/capability claims this replaces")
    ap.add_argument("--capability-contradicts", default=None,
                    help="comma-separated concept/capability claims incompatible with this one")
    ap.add_argument("--capability-valid-until", default=None,
                    help="ISO date after which the capability is no longer injected")
    ap.add_argument("--capability-from", type=int, default=None, metavar="EVIDENCE_NUMBER",
                    help="distil an existing numbered strong observation without duplicating it")
    ap.add_argument("--claim", default=None,
                    help="established semantic knowledge distilled from existing evidence")
    ap.add_argument("--claim-kind", choices=KNOWLEDGE_KINDS, default="understanding")
    ap.add_argument("--claim-from", default=None, metavar="EVIDENCE_NUMBERS",
                    help="comma-separated one-based evidence numbers supporting --claim")
    ap.add_argument("--claim-scope", choices=KNOWLEDGE_SCOPES, default="project")
    ap.add_argument("--claim-condition", default=None)
    ap.add_argument("--retract-capability", default=None,
                    help="retract this local capability id without deleting its history")
    ap.add_argument("--reason", default=None,
                    help="required audit reason for --retract-capability")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--confidence", type=float, default=None)
    ap.add_argument("--depends-on", default=None, help="comma-separated concept ids")
    ap.add_argument("--summary", default=None, help="one line on what the concept is (new files only)")
    ap.add_argument(
        "--understands",
        default=None,
        help=f"replace the '{UNDERSTANDS}' section with this distillation of the evidence",
    )
    ap.add_argument(
        "--not-established",
        dest="not_established",
        default=None,
        help=f"replace the '{NOT_ESTABLISHED}' section; this is the half that gets injected",
    )
    ap.add_argument(
        "--confirmed",
        action="store_true",
        help="explicit user confirmation; lets a single observation reach 'verified'",
    )
    ap.add_argument(
        "--forget",
        metavar="REASON",
        default=None,
        help="delete the concept; REASON is recorded in the git commit",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="with --forget, also strip the dangling depends-on from dependent concepts",
    )
    ap.add_argument("--date", default=None, help="ISO date; defaults to today")
    args = ap.parse_args()

    if args.confirmed and args.basis not in (None, "confirmation"):
        ap.error("--confirmed conflicts with --basis direct or inference")
    if args.confirmed:
        args.basis = "confirmation"
    args.basis = args.basis or "direct"

    if args.forget is not None:
        # Forgetting is the one operation that asserts nothing, so it combines with
        # nothing: a call that both deleted a concept and recorded evidence about it
        # would have an unreadable outcome.
        conflicts = {
            "--state": args.state,
            "--evidence": args.evidence,
            "--capability": args.capability,
            "--capability-scope": (
                args.capability_scope if args.capability_scope != "project" else None
            ),
            "--capability-condition": args.capability_condition,
            "--capability-id": args.capability_id,
            "--capability-requires": args.capability_requires,
            "--capability-supersedes": args.capability_supersedes,
            "--capability-contradicts": args.capability_contradicts,
            "--capability-valid-until": args.capability_valid_until,
            "--capability-from": args.capability_from,
            "--claim": args.claim, "--claim-from": args.claim_from,
            "--claim-kind": args.claim_kind if args.claim_kind != "understanding" else None,
            "--claim-scope": args.claim_scope if args.claim_scope != "project" else None,
            "--claim-condition": args.claim_condition,
            "--retract-capability": args.retract_capability,
            "--reason": args.reason,
            "--understands": args.understands,
            "--not-established": args.not_established,
            "--domain": args.domain,
            "--confidence": args.confidence,
            "--depends-on": args.depends_on,
            "--summary": args.summary,
            "--basis": args.basis if args.basis != "direct" else None,
            "--confirmed": args.confirmed or None,
            "--source-ref": args.source_ref,
        }
        used = sorted(k for k, v in conflicts.items() if v is not None)
        if used:
            ap.error(f"--forget cannot be combined with {', '.join(used)}")
        if not args.forget.strip():
            ap.error("--forget needs a reason; it is recorded in the git commit")
    elif args.force:
        ap.error("--force only applies to --forget")

    if args.retract_capability is not None:
        conflicts = {
            "--state": args.state, "--evidence": args.evidence,
            "--capability": args.capability, "--understands": args.understands,
            "--not-established": args.not_established, "--domain": args.domain,
            "--confidence": args.confidence, "--depends-on": args.depends_on,
            "--summary": args.summary,
            "--capability-scope": (
                args.capability_scope if args.capability_scope != "project" else None
            ),
            "--capability-condition": args.capability_condition,
            "--capability-id": args.capability_id,
            "--capability-requires": args.capability_requires,
            "--capability-supersedes": args.capability_supersedes,
            "--capability-contradicts": args.capability_contradicts,
            "--capability-valid-until": args.capability_valid_until,
            "--capability-from": args.capability_from,
            "--claim": args.claim, "--claim-from": args.claim_from,
            "--claim-kind": args.claim_kind if args.claim_kind != "understanding" else None,
            "--claim-scope": args.claim_scope if args.claim_scope != "project" else None,
            "--claim-condition": args.claim_condition,
            "--basis": args.basis if args.basis != "direct" else None,
            "--confirmed": args.confirmed or None,
            "--source-ref": args.source_ref,
        }
        used = sorted(key for key, value in conflicts.items() if value is not None)
        if used:
            ap.error(f"--retract-capability cannot be combined with {', '.join(used)}")
        if not ID_RE.fullmatch(args.retract_capability):
            ap.error("--retract-capability must be a lowercase kebab-case id")
        if args.reason is None or not args.reason.strip():
            ap.error("--retract-capability requires --reason")
        if any(char in args.reason for char in ("\n", "\r", "]")):
            ap.error("--reason must be one line and cannot contain ']'")
    elif args.reason is not None:
        ap.error("--reason only applies to --retract-capability")

    if args.basis == "inference" and args.capability is not None:
        ap.error("--basis inference cannot establish a capability")
    if args.basis == "inference" and args.claim is not None:
        ap.error("--basis inference cannot establish knowledge")
    if args.basis == "inference" and args.confidence is not None:
        ap.error("--basis inference cannot set confidence")
    if args.source_ref is not None:
        refs = [item.strip() for item in args.source_ref.split(",") if item.strip()]
        if not refs or len(refs) != len(set(refs)) or any(
                not re.fullmatch(r"transcript:[0-9a-f]{64}", item) for item in refs):
            ap.error("--source-ref expects unique transcript:<sha256> references")
        if args.evidence is None:
            ap.error("--source-ref requires --evidence")

    distil_only = args.forget is None and args.evidence is None
    if (distil_only and args.understands is None and args.not_established is None
            and args.capability is None and args.claim is None
            and args.retract_capability is None):
        ap.error("--evidence is required unless you pass --understands or --not-established")
    if (args.state is None and args.basis != "inference" and not distil_only and args.forget is None
            and args.retract_capability is None):
        ap.error("--state is required for direct or confirmed observations")
    if args.capability is not None:
        if args.evidence is None and args.capability_from is None:
            ap.error("--capability requires --evidence or --capability-from")
        if args.evidence is not None and args.capability_from is not None:
            ap.error("--capability-from cannot be combined with --evidence")
        if args.capability_from is not None and args.capability_from < 1:
            ap.error("--capability-from is a one-based evidence number")
        if args.capability_from is None and args.kind not in CAPABILITY_KINDS:
            ap.error("--capability requires --kind world, justification, or modification")
        if not args.capability.strip() or "\n" in args.capability or "\r" in args.capability:
            ap.error("--capability must be one non-empty line")
        for label, value in (("--capability", args.capability),
                             ("--capability-condition", args.capability_condition)):
            if value is not None and "]" in value:
                ap.error(f"{label} cannot contain ']' (reserved by the on-disk format)")
        if args.capability_condition is not None and not args.capability_condition.strip():
            ap.error("--capability-condition must not be empty")
        if args.capability_id is not None and not ID_RE.fullmatch(args.capability_id):
            ap.error("--capability-id must be lowercase kebab-case")
        for label, value in (
            ("--capability-requires", args.capability_requires),
            ("--capability-supersedes", args.capability_supersedes),
            ("--capability-contradicts", args.capability_contradicts),
        ):
            invalid = [ref for ref in (value or "").split(",")
                       if ref.strip() and not CAPABILITY_REF_RE.fullmatch(ref.strip())]
            if invalid:
                ap.error(f"{label} expects concept/capability references")
        if (args.capability_valid_until is not None
                and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.capability_valid_until)):
            ap.error("--capability-valid-until must be ISO YYYY-MM-DD")
    elif (args.capability_condition is not None or args.capability_scope != "project"
          or args.capability_id is not None or args.capability_requires is not None
          or args.capability_supersedes is not None or args.capability_contradicts is not None
          or args.capability_valid_until is not None or args.capability_from is not None):
        ap.error("capability metadata and relations require --capability")

    if args.claim is not None:
        if args.evidence is not None:
            ap.error("--claim distils existing evidence; it cannot be combined with --evidence")
        if args.claim_from is None:
            ap.error("--claim requires --claim-from")
        if not args.claim.strip() or any(char in args.claim for char in ("\n", "\r", "]")):
            ap.error("--claim must be one non-empty line without ']'")
        if args.claim_condition is not None and (
                not args.claim_condition.strip() or "]" in args.claim_condition):
            ap.error("--claim-condition must be non-empty and cannot contain ']'")
        try:
            claim_sources = [int(value.strip()) for value in args.claim_from.split(",")]
        except (TypeError, ValueError):
            ap.error("--claim-from expects comma-separated one-based evidence numbers")
        if any(number < 1 for number in claim_sources) or len(set(claim_sources)) != len(claim_sources):
            ap.error("--claim-from expects unique one-based evidence numbers")
    elif (args.claim_from is not None or args.claim_kind != "understanding"
          or args.claim_scope != "project" or args.claim_condition is not None):
        ap.error("claim metadata requires --claim")

    if not ID_RE.match(args.concept_id):
        print(f"error: id '{args.concept_id}' must be lowercase kebab-case", file=sys.stderr)
        return 2
    if args.domain is not None and not ID_RE.match(args.domain):
        print(f"error: domain '{args.domain}' must be lowercase kebab-case", file=sys.stderr)
        return 2
    if args.depends_on is not None:
        dependencies = [d.strip() for d in args.depends_on.split(",") if d.strip()]
        invalid = [d for d in dependencies if not ID_RE.match(d)]
        if invalid:
            print(
                "error: every --depends-on id must be lowercase kebab-case: "
                + ", ".join(invalid),
                file=sys.stderr,
            )
            return 2

    today = args.date or date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        print(f"error: --date '{today}' is not YYYY-MM-DD", file=sys.stderr)
        return 2
    if args.capability_valid_until is not None:
        try:
            expiry = date.fromisoformat(args.capability_valid_until)
            observed = date.fromisoformat(today)
        except ValueError:
            print("error: --capability-valid-until is not a real date", file=sys.stderr)
            return 2
        if expiry < observed:
            print("error: --capability-valid-until cannot precede the evidence date",
                  file=sys.stderr)
            return 2

    # Held from before the file is parsed through the write, index regen and commit, as one
    # unit neither a concurrent recorder nor laconic-sync.sh can interleave with.
    ensure_repo(home())
    lock = acquire_model_lock(home())

    if lock is None:
        if args.forget is not None or args.retract_capability is not None:
            # Not spoolable: forgetting is interactive, rare and destructive. Parking a
            # deletion to run later, against a model that has moved on since, is worse
            # than saying so now.
            print(
                f"error: could not acquire the model lock in {LOCK_WAIT_SECONDS}s — "
                f"laconic-sync.sh may be mid-merge. Nothing changed; re-run to retry.",
                file=sys.stderr,
            )
            return 1
        parked = spool(args, today)
        print(f"spooled {args.concept_id}: model lock busy, parked as {parked.name}")
        print("  the next record that gets the lock folds it in — nothing is lost")
        return 0

    # Before either operation, and in particular before a deletion: a spooled observation
    # is older than whatever is being asked for now, and replaying it after a forget would
    # resurrect the concept.
    drained = drain_spool()
    if drained:
        print(f"folded in {drained} spooled observation(s)")

    if args.forget is not None:
        return forget(args.concept_id, args.forget.strip(), args.force, today)
    if args.retract_capability is not None:
        return retract_capability(
            args.concept_id, args.retract_capability, args.reason.strip(), today
        )
    return apply_record(args, today)


def apply_record(args, today, quiet=False):
    """Apply one observation or distillation. The caller must hold the model lock.

    Split out of main() so drain_spool() replays through exactly this path -- a separate
    replay implementation would be a second way to write the model, free to drift from the
    first.
    """
    # Spool entries survive upgrades. `getattr` keeps entries written before the
    # capability field existed replayable instead of setting them aside as malformed.
    capability = getattr(args, "capability", None)
    capability_scope = getattr(args, "capability_scope", "project")
    capability_condition = getattr(args, "capability_condition", None) or ""
    capability_valid_until = getattr(args, "capability_valid_until", None) or ""
    capability_from = getattr(args, "capability_from", None)
    knowledge_claim = getattr(args, "claim", None)
    claim_sources = [int(value.strip()) for value in
                     (getattr(args, "claim_from", None) or "").split(",") if value.strip()]
    claim_kind = getattr(args, "claim_kind", "understanding")
    claim_scope = getattr(args, "claim_scope", "project")
    claim_condition = getattr(args, "claim_condition", None) or ""
    basis = getattr(args, "basis", None) or (
        "confirmation" if getattr(args, "confirmed", False) else "direct"
    )
    source_refs = [item.strip() for item in
                   (getattr(args, "source_ref", None) or "").split(",") if item.strip()]
    capability_id = getattr(args, "capability_id", None)
    capability_relations = {
        name: [ref.strip() for ref in (getattr(args, f"capability_{name}", None) or "").split(",")
               if ref.strip()]
        for name in ("requires", "supersedes", "contradicts")
    }
    distil_only = args.forget is None and args.evidence is None
    concepts = home() / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    path = concepts / f"{args.concept_id}.md"

    if args.depends_on:
        deps = list(dict.fromkeys(d.strip() for d in args.depends_on.split(",") if d.strip()))
        if args.concept_id in deps:
            print("error: a concept cannot depend on itself", file=sys.stderr)
            return 2
        missing = [d for d in deps if not (concepts / f"{d}.md").is_file()]
        if missing:
            print(
                "error: --depends-on names unknown concept(s): " + ", ".join(missing),
                file=sys.stderr,
            )
            return 2
        cyclic = [d for d in deps if dependency_reaches(concepts, d, args.concept_id)]
        if cyclic:
            print(
                "error: --depends-on would create a dependency cycle through: "
                + ", ".join(cyclic),
                file=sys.stderr,
            )
            return 2

    # The tool prepends the date; strip one the caller accidentally included, so evidence
    # does not read "2026-07-21: 2026-07-21 ...".
    evidence_text = None if distil_only else LEADING_DATE.sub("", args.evidence.strip())
    if evidence_text is not None:
        # Strip a kind the caller wrote by hand, so `--kind` stays the single source and the
        # line cannot end up marked twice.
        evidence_text = KIND_RE.sub("", evidence_text)
        evidence_text = BASIS_RE.sub("", evidence_text)
        evidence_text = SOURCE_RE.sub("", evidence_text)
        basis_marker = f"[basis: {basis}] " if basis != "direct" else ""
        source_marker = f"[sources: {', '.join(source_refs)}] " if source_refs else ""
        evidence_text = f"[{args.kind}] {basis_marker}{source_marker}{evidence_text}"

    if path.exists():
        meta, evidence, body = parse_existing(path)
        if meta is None:
            print(
                f"error: {path} has malformed frontmatter; refusing to overwrite it.\n"
                "       Run laconic-lint, repair or explicitly forget the concept, then retry.",
                file=sys.stderr,
            )
            return 2
        prior = meta.get("state", "unknown")
        prior = prior if prior in STATES else "unknown"
        if evidence_text is not None:
            evidence.append(f"{today}: {evidence_text}")
    elif distil_only:
        print(
            f"error: {args.concept_id} does not exist — a distillation summarises recorded "
            f"evidence, so record an observation for it first",
            file=sys.stderr,
        )
        return 2
    elif args.domain is None:
        # Required at creation, not at update: an undomained concept lands in an
        # undifferentiated bucket the index cannot group, and the only moment anyone knows
        # the subject area is when the concept is first recorded. Enforced here rather than
        # in argparse so updates, distillations and forgets stay exempt.
        print(
            f"error: --domain is required when creating '{args.concept_id}' — without it the "
            f"index cannot group the concept.\n"
            f"       Pass the subject area, e.g. --domain ocaml, --domain etf, "
            f"--domain consensus.",
            file=sys.stderr,
        )
        return 2
    else:
        meta, evidence, body, prior = {}, [f"{today}: {evidence_text}"], "", "unknown"

    # A distil-only call asserts nothing new about the state, so it inherits it.
    requested = args.state or prior
    if basis == "inference" and not distil_only:
        requested = prior

    # Promotion is slow, demotion is fast. Under-explaining is the costlier error, so
    # reaching 'verified' takes repeated evidence unless the user confirmed outright.
    final = requested
    note = ""
    if RANK[requested] > RANK[prior]:
        qualifying = sum("[basis: inference]" not in item for item in evidence)
        confirmed = basis == "confirmation"
        if requested == "verified" and qualifying < 2 and not confirmed:
            final = "familiar"
            note = (
                "  note: held at 'familiar' — 'verified' needs a second independent "
                "observation, or --confirmed"
            )
        if RANK[requested] - RANK[prior] > 1 and not confirmed:
            capped = STATES[RANK[prior] + 1]
            if RANK[capped] < RANK[final]:
                final = capped
                note = f"  note: capped at '{capped}' — one observation moves one step"

    meta["id"] = args.concept_id
    meta.setdefault("type", "concept")
    merge_project(meta)
    if args.domain:
        meta["domain"] = args.domain
    meta.setdefault("domain", "general")
    meta["state"] = final
    # A distillation is not evidence, so on its own it moves neither confidence nor
    # last-updated: resetting confidence would discard a tuned value, and bumping the date
    # would reset the staleness clock without a new observation behind it.
    conf = args.confidence
    if conf is None and not distil_only and basis != "inference":
        conf = DEFAULT_CONFIDENCE[final]
    if conf is not None:
        meta["confidence"] = f"{max(0.0, min(1.0, conf)):.2f}"
    meta.setdefault("confidence", f"{DEFAULT_CONFIDENCE[final]:.2f}")
    if args.depends_on:
        if deps:
            meta["depends-on"] = "[" + ", ".join(deps) + "]"
    if not distil_only:
        meta["last-updated"] = today
    meta.setdefault("last-updated", today)

    if not body.strip():
        summary = args.summary or f"{args.concept_id.replace('-', ' ')}."
        body = (f"{summary}\n\n## {CAPABILITIES}\n\n"
                f"## {ESTABLISHED_KNOWLEDGE}\n\n"
                f"## {UNDERSTANDS}\n\n## {NOT_ESTABLISHED}\n")

    if args.understands is not None:
        body = set_section(body, UNDERSTANDS, args.understands)
    if args.not_established is not None:
        body = set_section(body, NOT_ESTABLISHED, args.not_established)
    if knowledge_claim is not None:
        missing_sources = [number for number in claim_sources if number > len(evidence)]
        if missing_sources:
            print(
                f"error: --claim-from references evidence beyond the {len(evidence)} "
                f"recorded observation(s): {', '.join(map(str, missing_sources))}",
                file=sys.stderr,
            )
            return 2
        inferred = []
        for number in claim_sources:
            if re.search(r"\[basis: inference\]", evidence[number - 1]):
                inferred.append(number)
        if inferred:
            print(
                "error: inferred evidence cannot establish knowledge (evidence "
                + ", ".join(f"#{number}" for number in inferred) + ")",
                file=sys.stderr,
            )
            return 2
        body = add_knowledge_claim(
            body, claim_kind, knowledge_claim, claim_sources, claim_scope,
            claim_condition.strip(),
        )
    if capability is not None:
        capability_kind, capability_date = args.kind, today
        if capability_from is not None:
            if capability_from > len(evidence):
                print(
                    f"error: --capability-from {capability_from} exceeds the "
                    f"{len(evidence)} recorded observation(s)",
                    file=sys.stderr,
                )
                return 2
            source = evidence[capability_from - 1]
            source_match = re.match(
                r"^(\d{4}-\d{2}-\d{2}): \[(world|justification|modification)\] "
                r"(?:\[basis: (direct|confirmation|inference)\] )?"
                r"(?:\[sources: [^\]]+\] )?", source
            )
            if not source_match:
                print(
                    f"error: evidence #{capability_from} is not a strong world, "
                    "justification, or modification observation",
                    file=sys.stderr,
                )
                return 2
            capability_date, capability_kind, source_basis = source_match.groups()
            if source_basis == "inference":
                print("error: inferred evidence cannot establish a capability", file=sys.stderr)
                return 2
            if capability_valid_until and capability_valid_until < capability_date:
                print("error: capability expiry precedes its source evidence", file=sys.stderr)
                return 2
        resolved_id = capability_id or capability_id_from_claim(capability)
        new_ref = f"{args.concept_id}/{resolved_id}"
        existing = {
            f"{concept['id']}/{item['capability_id']}": item
            for concept in load_concepts() for item in concept.get("capabilities", ())
        }
        if new_ref in existing and existing[new_ref]["claim"] != " ".join(capability.split()):
            print(
                f"error: capability id '{new_ref}' already names a different claim; "
                "pass a distinct --capability-id",
                file=sys.stderr,
            )
            return 2
        targets = {ref for values in capability_relations.values() for ref in values}
        relation_count = sum(len(values) for values in capability_relations.values())
        if len(targets) != relation_count:
            print("error: the same capability target cannot have multiple relation types",
                  file=sys.stderr)
            return 2
        missing = sorted(targets - existing.keys())
        if missing:
            print("error: capability relation names unknown target(s): "
                  + ", ".join(missing), file=sys.stderr)
            return 2
        if new_ref in targets:
            print(f"error: capability '{new_ref}' cannot relate to itself", file=sys.stderr)
            return 2

        def reaches(start, target, seen=None):
            if start == target:
                return True
            seen = set() if seen is None else seen
            if start in seen or start not in existing:
                return False
            seen.add(start)
            return any(reaches(required, target, seen)
                       for required in existing[start].get("requires", ()))

        cyclic = [required for required in capability_relations["requires"]
                  if reaches(required, new_ref)]
        if cyclic:
            print("error: --capability-requires would create a cycle through: "
                  + ", ".join(cyclic), file=sys.stderr)
            return 2
        body = add_capability(
            body, capability_kind, capability, capability_date, capability_scope,
            capability_condition.strip(),
            resolved_id, valid_until=capability_valid_until,
            source_evidence=capability_from, **capability_relations,
        )

    atomic_write_text(path, render(meta, evidence, body))

    # Regenerate the human-readable index, then version the change so it is auditable.
    write_index_file(today)
    if distil_only:
        subject = f"{args.concept_id}: distilled ({final}, {len(evidence)} observations)"
    else:
        subject = f"{args.concept_id}: {prior} -> {final} — {(evidence_text or '')[:60]}"
    git_commit(home(), subject)
    git_push_async(home())

    # A replayed entry reports nothing: its caller already said how many it folded in, and
    # the nudges below are addressed to whoever is recording right now.
    if quiet:
        return 0

    if distil_only:
        action = "distilled"
    else:
        action = "updated" if prior != "unknown" or len(evidence) > 1 else "created"
    print(f"{action} {path.name}: {prior} -> {final} ({len(evidence)} observations)")
    if note:
        print(note)
    # Creation now requires --domain, so reaching `general` means a file predating that rule
    # or one rebuilt from unparseable frontmatter. Either way it is fixable in place.
    if meta.get("domain", "general") == "general":
        print(
            f"  note: {args.concept_id} is filed under 'general', which the index cannot "
            f"group. Re-run with --domain <subject> to fix it."
        )
    # Prompt for the distillation at the moment the evidence justifies one, which is the
    # moment the caller is already looking at this concept. Nudging earlier would ask for
    # a summary shorter than the lines it summarises.
    if len(evidence) >= SUMMARY_AFTER and not get_section(body, NOT_ESTABLISHED):
        print(
            f"  note: {len(evidence)} observations, no '{NOT_ESTABLISHED}' section yet. "
            f"Distil it with --not-established — that half is injected next session."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
