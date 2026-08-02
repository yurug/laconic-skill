#!/usr/bin/env python3
"""Build the compact concept index injected at session start.

Token discipline is a first-order constraint here: this text is prepended to every
session whether or not it turns out to be relevant. Above INLINE_LIMIT concepts the
index stops enumerating ids and summarises by domain, so cost grows sub-linearly.
"""

import argparse
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

# Above this many concepts in a state, summarise by domain instead of listing ids.
INLINE_LIMIT = 25

# Cap on domains named in a summary, so the index is bounded rather than merely sub-linear.
DOMAIN_LIMIT = 8

# Order matters: this is how states are presented to the reader.
STATES = ["verified", "familiar", "exposed", "unknown"]

# Decay thresholds, in days of silence. FAMILIAR_DECAY_DAYS matches laconic_lint.py's
# STALE_DAYS deliberately: the lint warns at the same point the injection softens, so the
# warning and the behaviour cannot drift apart.
FAMILIAR_DECAY_DAYS = 180
EXPOSED_DROP_DAYS = 90

# The body's two prose sections. Named here rather than in laconic_record.py because
# this module is the lower one -- the writer imports these, and an import the other way
# would be circular.
UNDERSTANDS = "What the user understands about it"
NOT_ESTABLISHED = "What has not been established"

# Observations after which an empty distillation is worth prompting for, and after which
# an existing one is worth injecting. One threshold for writing and reading, so the two
# stay in step.
SUMMARY_AFTER = 3


def atomic_write_text(path, text):
    """Replace a text file atomically so unlocked readers never see a partial model."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A process killed between creation and replacement can leave this file behind. The
    # model repo ignores this stable prefix, so a later `git add -A` cannot publish debris.
    fd, temporary = tempfile.mkstemp(prefix=".laconic-tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass

# Only the gap half is injected: `state` already compresses "what they understand" into
# one word, so the prose that adds information beyond the frontmatter is the gap.
#
# Bounded twice over, because per-item caps alone do not bound a block: GAP_CHARS trims
# one gap, GAP_BUDGET trims the section. Without the second, GAP_LIMIT x GAP_CHARS would on
# its own consume most of laconic_lint.py's INDEX_BUDGET for the whole injection. These two
# constants are coupled to that one -- raise INDEX_BUDGET first if you want more gap prose.
GAP_LIMIT = 6
GAP_CHARS = 180
GAP_BUDGET = 420


# Stable command names under ~/.laconic/bin, mapped to the scripts they run.
SHIMS = {
    "laconic-record": "laconic_record.py",
    "laconic-index": "laconic_index.py",
    "laconic-lint": "laconic_lint.py",
    "laconic-console": "laconic_console.py",
    "laconic-status": "laconic_status.py",
}


def concepts_dir():
    """Resolve the active model at call time so --home and test isolation are real."""
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic") / "concepts"


def ensure_bin(home_dir=None):
    """Keep ~/.laconic/bin/ holding wrappers for the tools, and return that directory.

    The problem this solves: SKILL.md has to name a command that works, but the scripts live
    at a path that depends on how laconic was installed -- ${PLUGIN_ROOT}/tools for a plugin,
    an arbitrary checkout for a bare skill symlinked into ~/.claude/skills. LACONIC_HOME is
    the one location both modes already agree on, so the stable command lives there.

    Wrappers rather than symlinks: a symlinked script keeps the symlink's directory in
    __file__, so `from laconic_index import ...` would look in bin/ instead of tools/. A
    wrapper execs the real absolute path and sidesteps that entirely.

    Rewritten whenever the target path changes, so moving the checkout heals on next run.
    Called from main() because that runs on every session start, which is the only moment
    guaranteed to happen before the first recording.
    """
    home_dir = Path(home_dir or os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    tools = Path(__file__).resolve().parent
    bindir = home_dir / "bin"
    try:
        bindir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    for name, script in SHIMS.items():
        target = tools / script
        if not target.exists():
            continue
        wrapper = bindir / name
        want = f'#!/usr/bin/env sh\n# Generated by laconic; edits are overwritten.\nexec python3 "{target}" "$@"\n'
        try:
            if not wrapper.exists() or wrapper.read_text(encoding="utf-8") != want:
                wrapper.write_text(want, encoding="utf-8")
                wrapper.chmod(0o755)
        except OSError:
            continue
    return bindir


def heading_re(heading):
    """`[ \\t]*$` rather than `\\s*$`: with re.M, `\\s*` would cross blank lines and
    swallow the very section it is meant to delimit."""
    return re.compile(rf"^## {re.escape(heading)}[ \t]*$", re.M)


def get_section(body, heading):
    """Text under `## {heading}`, up to the next `## ` or the end of the body."""
    m = heading_re(heading).search(body)
    if not m:
        return ""
    rest = body[m.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def parse_frontmatter(path):
    """Minimal YAML-subset frontmatter reader.

    Deliberately not using PyYAML: the hook must run on a bare machine with no
    pip installs. Only the scalar keys and the one list form this schema uses
    are supported.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None

    meta = {}
    evidence_count = 0
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            # The only list-item lines in this schema are evidence entries
            # (depends-on and projects use the inline [a, b] form).
            evidence_count += 1
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key.strip()] = [v.strip() for v in inner.split(",") if v.strip()]
        elif value:
            meta[key.strip()] = value
    meta["_evidence-count"] = evidence_count
    # Read the gap section here rather than in a second pass: the file is already loaded,
    # and this runs on every concept at every session start.
    meta["_gap"] = " ".join(get_section(text[end + 4 :], NOT_ESTABLISHED).split())
    return meta


def load_concepts():
    directory = concepts_dir()
    if not directory.is_dir():
        return []
    concepts = []
    for path in sorted(directory.glob("*.md")):
        meta = parse_frontmatter(path)
        if not meta:
            continue
        state = meta.get("state", "unknown")
        if state not in STATES:
            state = "unknown"
        projects = meta.get("projects")
        concepts.append(
            {
                "id": meta.get("id", path.stem),
                "state": state,
                "domain": meta.get("domain", "general"),
                "projects": projects if isinstance(projects, list) else [],
                "last-updated": meta.get("last-updated"),
                "observations": meta.get("_evidence-count", 0),
                "gap": meta.get("_gap", ""),
            }
        )
    return concepts


def effective_state(state, days_since_seen, observations):
    """Decay policy: the state the injection presents, given how long ago the concept
    was last observed and how many observations back it. Returns a state name, or None
    to drop the concept from the injection entirely. Decay applies only to the
    injected view -- the concept file and INDEX.md keep everything, and fresh evidence
    resurrects a dropped concept through the normal recording path.

    days_since_seen is None when the concept has no parseable last-updated date:
    treat that as no information, not as stale.

    Tiered rather than uniform, because the tiers are not equally durable. `verified`
    never decays: it took two instances of productive use to earn, it is the expensive
    tier to re-establish, and practised knowledge does not evaporate on a quiet stretch
    -- uniform decay would erode real expertise for no observed reason. `familiar` is a
    single inference away from `exposed` and softens to it. A single-observation
    `exposed` is the fast-fading tier: one sighting months ago is close to no evidence,
    so it leaves the injection rather than claiming space. `unknown` persists; it costs
    almost nothing and its whole job is to be a standing warning.
    """
    if days_since_seen is None:
        return state
    if state == "familiar" and days_since_seen > FAMILIAR_DECAY_DAYS:
        state = "exposed"
    # Applied after the softening above, so a thinly-evidenced `familiar` fades the whole
    # way out rather than resting at `exposed` forever.
    if state == "exposed" and observations <= 1 and days_since_seen > EXPOSED_DROP_DAYS:
        return None
    return state


def is_relevant(concept, cwd):
    """A concept is relevant when the session is at or inside a recorded project.

    The inverse is intentionally false. A session at /home/user is not simultaneously
    relevant to every project below it; treating containment symmetrically made a broad cwd
    inline the whole model and defeated both relevance ranking and the injection budget.
    """
    if not cwd:
        return False
    cwd = cwd.rstrip("/")
    for p in concept.get("projects", ()):
        p = p.rstrip("/")
        if p and (cwd == p or cwd.startswith(p + "/")):
            return True
    return False


def days_since(last_updated, today):
    try:
        return (today - date.fromisoformat(last_updated)).days
    except (TypeError, ValueError):
        return None


def truncate(text, limit=GAP_CHARS):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def select_gaps(concepts, cwd):
    """Every injectable gap, ranked by significance. Applying the caps is render_gaps's
    job, so that one place counts everything it omits.

    Ranked by how far the gap contradicts the state, because that is where its
    information is. A gap on a `verified` concept carves an exception out of "use freely,
    never re-derive" -- without it the policy is confidently wrong, which is the one case
    the state alone cannot express. A gap on an `exposed` or `unknown` one mostly restates
    what the state already implies ("define on use"), so it earns its space last. Project
    relevance outranks state: a gap that can actually come up this session beats a sharper
    one that cannot.

    Chosen over freshest-first, which would let a fresh trivial gap crowd out a
    long-standing one on a verified concept. Staleness is handled upstream instead --
    effective_state drops thinly-evidenced concepts before they reach here.
    """
    eligible = [
        c
        for c in concepts
        if c.get("gap") and c.get("observations", 0) >= SUMMARY_AFTER
    ]
    eligible.sort(key=lambda c: (not is_relevant(c, cwd), STATES.index(c["state"]), c["id"]))
    return eligible


def render_gaps(gaps):
    """The gap half of the model, as exceptions to the states above. Kept separate from
    the state lines because it overrides them: a concept can read `verified` and still
    have a part that must be explained."""
    if not gaps:
        return ""
    lines = [
        "",
        "",
        "## Established gaps",
        "",
        "Not established for these — explain these parts even where the state says otherwise.",
        "",
    ]
    spent, shown = 0, 0
    for c in gaps:
        entry = f"- {c['id']} ({c['state']}): {truncate(c['gap'])}"
        # Rank order is significance order, so hitting either cap drops the least
        # significant gaps rather than arbitrary ones.
        if shown >= GAP_LIMIT or spent + len(entry) > GAP_BUDGET:
            continue
        spent += len(entry)
        shown += 1
        lines.append(entry)
    dropped = len(gaps) - shown
    if dropped:
        # Never silently truncate: a gap block that looks complete but is not would make
        # the model read as fully surfaced when it is not.
        noun = "gap" if dropped == 1 else "gaps"
        lines.append(f"- (+{dropped} more {noun} over budget — see ~/.laconic/concepts/)")
    return "\n".join(lines)


def render(concepts, cwd=None, today=None):
    if not concepts:
        return (
            "No concepts recorded yet. The model is empty: assume nothing about what "
            "the user knows, and start recording evidence as it appears."
        )

    by_state = defaultdict(list)
    # Concepts that survived decay, at their decayed state. Gap selection reads this
    # rather than `concepts`, so a concept dropped from the states above cannot leak
    # back in through its gap.
    surviving = []
    for c in concepts:
        state = c["state"]
        if today is not None:
            decayed = effective_state(
                state, days_since(c.get("last-updated"), today), c.get("observations", 0)
            )
            if decayed is None:
                continue
            # A malformed return from the policy ignores decay rather than dropping
            # the concept: presenting a stale state is the recoverable error.
            state = decayed if decayed in STATES else state
        by_state[state].append(c)
        surviving.append({**c, "state": state})

    lines = []
    for state in STATES:
        entries = by_state.get(state)
        if not entries:
            continue
        # State handling (define/gloss/skip) lives in the policy bullet injected just
        # above this index -- not repeated here, so there is one source of truth.
        if len(entries) <= INLINE_LIMIT:
            ids = ", ".join(sorted(e["id"] for e in entries))
            lines.append(f"- {state}: {ids}")
            continue
        # Over the limit, degrade by relevance rather than cliff: the ids this session
        # can actually hit (recorded in this project) stay inline; only the rest
        # collapses to domain counts.
        inline = sorted(e["id"] for e in entries if is_relevant(e, cwd))[:INLINE_LIMIT]
        if inline:
            rest = [e for e in entries if e["id"] not in set(inline)]
            lines.append(
                f"- {state} (this project): {', '.join(inline)};"
                f" elsewhere {summarize(rest)}"
            )
        else:
            lines.append(f"- {state}: {summarize(entries)}")
    return "\n".join(lines) + render_gaps(select_gaps(surviving, cwd))


def summarize(entries):
    """Domain-count summary for a state too large to enumerate, pointing at INDEX.md
    (one read) rather than concepts/ (one read per concept)."""
    by_domain = defaultdict(int)
    for e in entries:
        by_domain[e["domain"]] += 1
    ranked = sorted(by_domain.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ranked[:DOMAIN_LIMIT]
    summary = ", ".join(f"{d} ({n})" for d, n in shown)
    if len(ranked) > DOMAIN_LIMIT:
        # Hard cap: without this, a model with hundreds of one-off domains
        # would grow the index without bound.
        summary += f", +{len(ranked) - DOMAIN_LIMIT} more domains"
    return (
        f"{len(entries)} concepts across {summary}"
        f" -- full list in ~/.laconic/INDEX.md"
    )


def render_index_file(concepts, today):
    """Human-readable INDEX.md, grouped by domain. This is a materialized view of the
    concept files, not a second source of truth -- it is regenerated on every write and
    exists so the folder has a legible entry point (an open learner model the user can
    actually read).
    """
    header = [
        "# Laconic — what the user knows",
        "",
        f"*Generated view of `concepts/`, {len(concepts)} concepts, built {today}. "
        "Do not hand-edit — regenerate with `laconic_index.py --write-index`. "
        "Edit the concept files, not this.*",
        "",
        "States: **verified** assume known · **familiar** brief gloss ok · "
        "**exposed** seen once, define on use · **unknown** new, define before relying.",
        "",
    ]
    if not concepts:
        return "\n".join(header + ["_Empty — fills as evidence appears._", ""])

    by_domain = defaultdict(list)
    for c in concepts:
        by_domain[c.get("domain") or "general"].append(c)

    body = []
    for domain in sorted(by_domain, key=lambda d: (-len(by_domain[d]), d)):
        entries = by_domain[domain]
        body.append(f"## {domain} ({len(entries)})")
        by_state = defaultdict(list)
        for c in entries:
            by_state[c["state"]].append(c["id"])
        for state in STATES:
            ids = by_state.get(state)
            if ids:
                body.append(f"- **{state}** — {', '.join(sorted(ids))}")
        body.append("")
    return "\n".join(header + body)


def write_index_file(today):
    path = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic") / "INDEX.md"
    atomic_write_text(path, render_index_file(load_concepts(), today))
    return path


def main():
    ap = argparse.ArgumentParser(description="Render the injected concept index.")
    ap.add_argument("--write-index", action="store_true", help="regenerate INDEX.md")
    ap.add_argument(
        "--ensure-bin",
        action="store_true",
        help="create ~/.laconic/bin wrappers and print the directory, then exit",
    )
    ap.add_argument(
        "--cwd",
        default=None,
        help="session cwd; keeps this project's concepts inline past the inline limit",
    )
    args = ap.parse_args()

    if args.ensure_bin:
        bindir = ensure_bin()
        print(bindir if bindir else "could not create bin directory")
        return 0

    if args.write_index:
        path = write_index_file(date.today().isoformat())
        print(f"wrote {path}")
    else:
        # Side effect in a read path, deliberately: this is the one command that runs at
        # every session start, so it is where the stable command path can be kept alive.
        # Failures are swallowed inside ensure_bin -- the injection must never break.
        ensure_bin()
        print(render(load_concepts(), cwd=args.cwd, today=date.today()))


if __name__ == "__main__":
    sys.exit(main())
