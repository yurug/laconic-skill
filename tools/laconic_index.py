#!/usr/bin/env python3
"""Build the compact concept index injected at session start.

Token discipline is a first-order constraint here: this text is prepended to every
session whether or not it turns out to be relevant. Above INLINE_LIMIT concepts the
index stops enumerating ids and summarises by domain, so cost grows sub-linearly.
"""

import argparse
import hashlib
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

# Above this many concepts in a state, summarise by domain instead of listing ids.
INLINE_LIMIT = 25

# Once summarized, keep a smaller active-project working set beside the domain summary.
# The full list remains in INDEX.md; this cap leaves room for capabilities and gaps.
PROJECT_INLINE_LIMIT = 25

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
CAPABILITIES = "Established capabilities"
CAPABILITY_KINDS = ("world", "justification", "modification")
CAPABILITY_SCOPES = ("project", "domain", "general")
CAPABILITY_RE = re.compile(
    r"^- \[(world|justification|modification)\] (.+?) "
    r"\(evidence: (\d{4}-\d{2}-\d{2})\)"
    r"(?: \[scope: (project|domain|general)\])?"
    r"(?: \[when: ([^\]]+)\])?$"
)
CAPABILITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CAPABILITY_EXTENDED_RE = re.compile(
    CAPABILITY_RE.pattern[:-1]
    + r"(?: \[valid-until: (\d{4}-\d{2}-\d{2})\])?"
      r"(?: \[id: ([a-z0-9][a-z0-9-]*)\])?"
      r"(?: \[requires: ([^\]]+)\])?"
      r"(?: \[supersedes: ([^\]]+)\])?"
      r"(?: \[contradicts: ([^\]]+)\])?"
      r"(?: \[source-evidence: ([1-9][0-9]*)\])?"
      r"(?: \[retracted: (\d{4}-\d{2}-\d{2})\])?"
      r"(?: \[retraction-reason: ([^\]]+)\])?$"
)
CAPABILITY_REF_RE = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")

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
CAPABILITY_LIMIT = 4
CAPABILITY_CHARS = 140
CAPABILITY_BUDGET = 250
CANDIDATE_LIMIT = 2
ROUTER_DOMAIN_LIMIT = 40
ROUTER_STRONG_LIMIT = 12
PROMPT_DOMAIN_LIMIT = 2
PROMPT_ROUTE_BUDGET = 2800
ROUTE_STOPWORDS = {
    "about", "after", "also", "avec", "dans", "does", "faire", "from", "have",
    "just", "mais", "more", "pour", "that", "this", "tout", "une", "vous", "what",
    "when", "with", "your",
}


# Stable command names under ~/.laconic/bin, mapped to the scripts they run.
SHIMS = {
    "laconic-record": "laconic_record.py",
    "laconic-index": "laconic_index.py",
    "laconic-lint": "laconic_lint.py",
    "laconic-console": "laconic_console.py",
    "laconic-status": "laconic_status.py",
    "laconic-candidates": "laconic_candidates.py",
    "laconic-bootstrap": "laconic_bootstrap.py",
    "laconic-review": "laconic_review.py",
    "laconic-review-web": "laconic_review_web.py",
    "laconic-apply-review": "laconic_apply_review.py",
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


def parse_capabilities(body):
    """Read auditable capability claims from their backward-compatible body section."""
    out = []
    for line in get_section(body, CAPABILITIES).splitlines():
        match = CAPABILITY_EXTENDED_RE.fullmatch(line.strip())
        if match:
            claim = match.group(2)
            capability_id = match.group(7) or capability_id_from_claim(claim)
            out.append({
                "kind": match.group(1), "claim": claim, "date": match.group(3),
                "scope": match.group(4) or "project", "condition": match.group(5) or "",
                "valid_until": match.group(6) or "",
                "capability_id": capability_id,
                "requires": parse_capability_refs(match.group(8)),
                "supersedes": parse_capability_refs(match.group(9)),
                "contradicts": parse_capability_refs(match.group(10)),
                "source_evidence": int(match.group(11)) if match.group(11) else None,
                "retracted": match.group(12) or "",
                "retraction_reason": match.group(13) or "",
            })
    return out


def capability_id_from_claim(claim):
    """Stable readable id for legacy claims and new claims without an explicit id."""
    value = re.sub(r"[^a-z0-9]+", "-", claim.lower()).strip("-")[:48].rstrip("-")
    return value or "capability"


def parse_capability_refs(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


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
    strong_evidence = []
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            # The only list-item lines in this schema are evidence entries
            # (depends-on and projects use the inline [a, b] form).
            evidence_count += 1
            evidence = line[2:].strip()
            match = re.match(
                r"^(\d{4}-\d{2}-\d{2}): \[(world|justification|modification)\] "
                r"(?:\[basis: (direct|confirmation|inference)\] )?"
                r"(?:\[sources: ([^\]]+)\] )?(.+)$",
                evidence,
            )
            if match:
                strong_evidence.append({
                    "index": evidence_count, "date": match.group(1),
                    "kind": match.group(2), "basis": match.group(3) or "direct",
                    "source_refs": [x.strip() for x in (match.group(4) or "").split(",")
                                    if x.strip()],
                    "text": match.group(5),
                })
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
    meta["_strong-evidence"] = strong_evidence
    # Read the gap section here rather than in a second pass: the file is already loaded,
    # and this runs on every concept at every session start.
    body = text[end + 4 :]
    meta["_gap"] = " ".join(get_section(body, NOT_ESTABLISHED).split())
    meta["_capabilities"] = parse_capabilities(body)
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
                "capabilities": meta.get("_capabilities", []),
                "strong_evidence": meta.get("_strong-evidence", []),
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


def select_capabilities(concepts, cwd, today=None):
    """Flatten and rank established abilities, preferring this project and stronger proof."""
    strength = {"modification": 0, "justification": 1, "world": 2}
    relevant_domains = {c["domain"] for c in concepts if is_relevant(c, cwd)}
    out = []
    for concept in concepts:
        for capability in concept.get("capabilities", ()):
            if capability.get("retracted"):
                continue
            valid_until = capability.get("valid_until")
            if today is not None and valid_until:
                try:
                    if today > date.fromisoformat(valid_until):
                        continue
                except ValueError:
                    continue
            scope = capability.get("scope", "project")
            capability_id = capability.get("capability_id") or capability_id_from_claim(
                capability["claim"]
            )
            relevant = is_relevant(concept, cwd)
            if scope == "project" and not relevant:
                continue
            if scope == "domain" and concept["domain"] not in relevant_domains:
                continue
            out.append({**capability, "scope": scope, "capability_id": capability_id,
                        "id": concept["id"], "ref": f"{concept['id']}/{capability_id}",
                        "relevant": relevant})
    # Prerequisites are applicability gates. Resolve to a fixed point because a missing
    # prerequisite can itself invalidate another capability transitively.
    while True:
        active = {capability["ref"] for capability in out}
        kept = [capability for capability in out
                if all(required in active for required in capability.get("requires", ()))]
        if len(kept) == len(out):
            break
        out = kept
    superseded = {target for capability in out for target in capability.get("supersedes", ())}
    out = [capability for capability in out if capability["ref"] not in superseded]
    out.sort(key=lambda c: (not c["relevant"], strength[c["kind"]], c["id"], c["claim"]))
    return out


def render_capabilities(capabilities):
    if not capabilities:
        return ""
    lines = ["", "", "## Established capabilities", "",
             "Rely on these demonstrated abilities; do not re-teach their stated content.", ""]
    spent, shown = 0, 0
    for capability in capabilities:
        claim = truncate(capability["claim"], CAPABILITY_CHARS)
        label = f"{capability['kind']}, {capability['scope']}"
        condition = f"; when {capability['condition']}" if capability.get("condition") else ""
        relations = []
        for relation in ("requires", "supersedes", "contradicts"):
            if capability.get(relation):
                relations.append(f"{relation} {', '.join(capability[relation])}")
        relation_suffix = f"; {'; '.join(relations)}" if relations else ""
        entry = f"- {capability['id']}/{capability['capability_id']} [{label}]: " \
                f"{claim}{condition}{relation_suffix}"
        if shown >= CAPABILITY_LIMIT or spent + len(entry) > CAPABILITY_BUDGET:
            continue
        lines.append(entry)
        spent += len(entry)
        shown += 1
    dropped = len(capabilities) - shown
    if dropped:
        noun = "capability" if dropped == 1 else "capabilities"
        lines.append(f"- (+{dropped} more {noun} over budget — see ~/.laconic/concepts/)")
    return "\n".join(lines)


def select_capability_candidates(concepts, cwd):
    """Strong observations not yet distilled, limited to the active project."""
    candidates = []
    for concept in concepts:
        if not is_relevant(concept, cwd):
            continue
        exact = {item["source_evidence"] for item in concept.get("capabilities", ())
                 if item.get("source_evidence") is not None}
        legacy = {(item["date"], item["kind"])
                  for item in concept.get("capabilities", ())
                  if item.get("source_evidence") is None}
        for evidence in concept.get("strong_evidence", ()):
            if (evidence.get("basis", "direct") != "inference"
                    and evidence["index"] not in exact
                    and (evidence["date"], evidence["kind"]) not in legacy):
                candidates.append({**evidence, "id": concept["id"]})
    return sorted(candidates, key=lambda item: (item["id"], item["index"]))


def render_capability_candidates(candidates):
    if not candidates:
        return ""
    shown = candidates[:CANDIDATE_LIMIT]
    lines = ["", "", "## Capability candidates", "",
             "Review strong evidence; distil only a reusable demonstrated ability.", ""]
    lines.extend(
        f"- {item['id']} evidence #{item['index']} [{item['kind']}]"
        for item in shown
    )
    if len(candidates) > len(shown):
        lines.append(f"- (+{len(candidates) - len(shown)} more — run laconic-candidates)")
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
        inline = sorted(e["id"] for e in entries if is_relevant(e, cwd))[
            :PROJECT_INLINE_LIMIT
        ]
        if inline:
            rest = [e for e in entries if e["id"] not in set(inline)]
            lines.append(
                f"- {state} (this project): {', '.join(inline)};"
                f" elsewhere {summarize(rest)}"
            )
        else:
            lines.append(f"- {state}: {summarize(entries)}")
    return ("\n".join(lines)
            + render_capabilities(select_capabilities(surviving, cwd, today))
            + render_gaps(select_gaps(surviving, cwd))
            + render_capability_candidates(select_capability_candidates(surviving, cwd)))


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


def recorded_projects(concepts):
    return sorted({project for concept in concepts for project in concept.get("projects", ())})


def active_project(cwd, projects):
    """Choose the most specific recorded project containing cwd.

    A broad workspace remains the fallback for its own sessions but cannot eclipse a nested
    repository with a more precise model. This preserves subdirectory relevance without
    treating `/home/user` as the active project for every repository below it.
    """
    if not cwd:
        return None
    cwd = cwd.rstrip("/") or "/"
    normalized = [project.rstrip("/") or "/" for project in projects]
    matches = [project for project in normalized
               if cwd == project or project == "/" or cwd.startswith(project + "/")]
    return max(matches, key=len) if matches else None


def project_key(project):
    return hashlib.sha256(project.encode("utf-8")).hexdigest()[:16]


def project_concepts(concepts, project):
    return [concept for concept in concepts if project in concept.get("projects", ())]


def render_router(concepts, cwd=None, today=None):
    projects = recorded_projects(concepts)
    current = active_project(cwd, projects)
    domains = sorted({concept["domain"] for concept in concepts})
    surviving = []
    for concept in concepts:
        state = concept["state"]
        if today is not None:
            state = effective_state(
                state, days_since(concept.get("last-updated"), today),
                concept.get("observations", 0),
            )
        if state:
            surviving.append({**concept, "state": state})
    strong = [concept for concept in surviving
              if concept["state"] in ("verified", "familiar")]
    by_state = defaultdict(list)
    for concept in strong:
        by_state[concept["state"]].append(concept["id"])
    lines = [
        "# Knowledge router",
        "",
        "Load the active project index below. When the request crosses projects or depends "
        "on another subject, read `~/.laconic/indexes/domains/<domain>.md`; read concept "
        "files only for evidence or detail.",
        "",
    ]
    for state in ("verified", "familiar"):
        ids = sorted(by_state[state])
        if ids:
            shown_ids = ids[:ROUTER_STRONG_LIMIT]
            suffix = f", +{len(ids) - len(shown_ids)} via domain indexes" \
                if len(ids) > len(shown_ids) else ""
            lines.append(f"- {state}: {', '.join(shown_ids)}{suffix}")
    shown = domains[:ROUTER_DOMAIN_LIMIT]
    suffix = f", +{len(domains) - len(shown)} more in ROOT.md" if len(domains) > len(shown) else ""
    lines.append(f"- domain routes: {', '.join(shown)}{suffix}")
    if current:
        lines.append(
            f"- active project: `{current}` → "
            f"`~/.laconic/indexes/projects/{project_key(current)}.md`"
        )
    else:
        lines.append("- active project: none; route by domain or `~/.laconic/indexes/ROOT.md`")
    strong_gaps = select_gaps(strong, current)
    return "\n".join(lines) + render_gaps(strong_gaps), current


def render_hierarchy(concepts, cwd=None, today=None):
    """Always-small router plus the complete leaf for the most specific active project."""
    if not concepts:
        return render([])
    router, current = render_router(concepts, cwd, today)
    if not current:
        return router
    local = project_concepts(concepts, current)
    leaf = render(local, cwd=current, today=today)
    return f"{router}\n\n## Active project knowledge\n\n{leaf}"


def route_tokens(text):
    """Stable lexical features for zero-service, privacy-preserving prompt routing."""
    return {
        token for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) >= 3 and token not in ROUTE_STOPWORDS
    }


def select_prompt_domains(concepts, prompt, limit=PROMPT_DOMAIN_LIMIT):
    """Select domain leaves implicated by a prompt without reading transcript history.

    Domain and concept names are intentionally the only routing vocabulary. Evidence may
    contain private prose and capabilities may contain broad claims; neither needs to be
    copied into a routing table merely to decide which generated leaf to load.
    """
    prompt_tokens = route_tokens(prompt)
    if not prompt_tokens:
        return []
    by_domain = defaultdict(set)
    for concept in concepts:
        by_domain[concept["domain"]].update(route_tokens(concept["id"]))
        by_domain[concept["domain"]].update(route_tokens(concept["domain"]))
    ranked = []
    for domain, vocabulary in by_domain.items():
        overlap = prompt_tokens & vocabulary
        if overlap:
            # Exact domain words outrank incidental concept-id matches; deterministic
            # tie-breaking keeps hook output stable across filesystem orderings.
            domain_overlap = prompt_tokens & route_tokens(domain)
            ranked.append((len(overlap) + 2 * len(domain_overlap), domain))
    return [domain for _, domain in sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]]


def render_prompt_routes(concepts, prompt, today=None, budget=PROMPT_ROUTE_BUDGET):
    """Render bounded domain leaves selected for one user prompt."""
    domains = select_prompt_domains(concepts, prompt)
    if not domains:
        return ""
    today = today or date.today()
    header = (
        "# Laconic automatic routes\n\n"
        "Internal user-model context selected for this request. Apply it silently; do not "
        "ask the user to inspect, route, or maintain Laconic.\n\n"
    )
    out = header
    for domain in domains:
        block = render_domain_index(domain, concepts, today.isoformat())
        remaining = budget - len(out)
        if remaining <= 0:
            break
        out += block[:remaining]
    return out.rstrip()


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


def render_domain_index(domain, concepts, today):
    today_date = today if isinstance(today, date) else date.fromisoformat(today)
    entries = [concept for concept in concepts if concept["domain"] == domain]
    return (
        f"# Laconic domain — {domain}\n\n"
        f"*Generated {today}; {len(entries)} concepts. Do not hand-edit.*\n\n"
        + render(entries, today=today_date) + "\n"
    )


def render_project_index(project, concepts, today):
    today_date = today if isinstance(today, date) else date.fromisoformat(today)
    entries = project_concepts(concepts, project)
    return (
        f"# Laconic project — {project}\n\n"
        f"*Generated {today}; {len(entries)} concepts. Do not hand-edit.*\n\n"
        + render(entries, cwd=project, today=today_date) + "\n"
    )


def write_generated_set(directory, expected):
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob("*.md"):
        if path.name not in expected:
            path.unlink()
    for name, content in expected.items():
        atomic_write_text(directory / name, content)


def write_hierarchical_indexes(concepts, today, model_home=None):
    model_home = Path(model_home or os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    exclude = model_home / ".git" / "info" / "exclude"
    try:
        if not (model_home / ".git").is_dir():
            raise FileNotFoundError
        existing = exclude.read_text(encoding="utf-8").splitlines() \
            if exclude.exists() else []
        if "/indexes/" not in existing:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(exclude, "\n".join(existing + ["/indexes/"]) + "\n")
    except OSError:
        pass
    base = model_home / "indexes"
    domains = sorted({concept["domain"] for concept in concepts})
    projects = recorded_projects(concepts)
    domain_files = {
        f"{domain}.md": render_domain_index(domain, concepts, today) for domain in domains
    }
    project_files = {
        f"{project_key(project)}.md": render_project_index(project, concepts, today)
        for project in projects
    }
    write_generated_set(base / "domains", domain_files)
    write_generated_set(base / "projects", project_files)
    root = [
        "# Laconic knowledge routes", "",
        f"*Generated {today}; {len(concepts)} concepts, {len(domains)} domains, "
        f"{len(projects)} projects. Do not hand-edit.*", "",
        "## Domains", "",
    ]
    root.extend(f"- [{domain}](domains/{domain}.md)" for domain in domains)
    root.extend(["", "## Projects", ""])
    root.extend(
        f"- `{project}` → [index](projects/{project_key(project)}.md)"
        for project in projects
    )
    atomic_write_text(base / "ROOT.md", "\n".join(root) + "\n")
    return base


def ensure_hierarchical_indexes(today=None):
    """Refresh ignored materialized views only when concepts are newer than the router."""
    model_home = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    root = model_home / "indexes" / "ROOT.md"
    concepts_dir = model_home / "concepts"
    try:
        root_mtime = root.stat().st_mtime
        stale = any(path.stat().st_mtime > root_mtime for path in concepts_dir.glob("*.md"))
    except OSError:
        stale = True
    if stale:
        write_hierarchical_indexes(
            load_concepts(), (today or date.today()).isoformat(), model_home
        )


def write_index_file(today):
    model_home = Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")
    path = model_home / "INDEX.md"
    concepts = load_concepts()
    atomic_write_text(path, render_index_file(concepts, today))
    write_hierarchical_indexes(concepts, today, model_home)
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
    ap.add_argument(
        "--prompt",
        default=None,
        help="render bounded domain leaves relevant to this prompt",
    )
    args = ap.parse_args()

    if args.ensure_bin:
        bindir = ensure_bin()
        print(bindir if bindir else "could not create bin directory")
        return 0

    if args.prompt is not None:
        print(render_prompt_routes(load_concepts(), args.prompt, today=date.today()))
    elif args.write_index:
        path = write_index_file(date.today().isoformat())
        print(f"wrote {path}")
    else:
        # Side effect in a read path, deliberately: this is the one command that runs at
        # every session start, so it is where the stable command path can be kept alive.
        # Failures are swallowed inside ensure_bin -- the injection must never break.
        ensure_bin()
        ensure_hierarchical_indexes()
        print(render_hierarchy(load_concepts(), cwd=args.cwd, today=date.today()))


if __name__ == "__main__":
    sys.exit(main())
