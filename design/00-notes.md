# Design notes (accumulating — not yet a spec)

## The enforcement architecture, borrowed from agentic-loop-kit

`/path/to/agentic-loop-kit/GETTING-STARTED.md` states the load-bearing lesson: instructions
alone do not guarantee a KB gets read or maintained. Three mechanisms, in increasing order of
hardness:

| Mechanism | Channel | What it buys |
|---|---|---|
| `CLAUDE.md` routing protocol at top of file | presence → instruction | every session is told, per task, to load the bundle and update the KB in the same commit |
| SessionStart hook injecting `kb/INDEX.md` | presence | routing table is in context before the first token — compliance not required |
| `tools/kb-lint.py` in pre-commit + CI | mechanical | the only hard guarantee |

**Direct transfer to the laconic skill.** A user-model KB has the same failure mode — the
agent is told to consult and update it, and quietly doesn't. So the skill needs the same
three layers:

1. **SKILL.md** — the explanation policy and update protocol (instruction layer).
2. **SessionStart hook injecting the user model** — so what the user knows is in context
   *before the first token*, not fetched on demand. This is the critical one: an explanation
   policy that requires the agent to remember to look something up will fail exactly when
   it's needed (mid-explanation).
3. **A lint** — mechanical validation of the user-model files (schema, staleness, evidence
   fields present, no orphan concepts).

Open question for the design: what is the mechanical check for a *user model*? Unlike a
project KB, there is no build to fail. Candidates: a pre-commit lint on schema integrity, and
a periodic "staleness audit" (concepts whose mastery estimate hasn't been touched in N
sessions get downgraded in confidence, per the confidence-decay question from pass 1).

## KB file schema, borrowed and adapted

`agentic-loop-kit/templates/kb/_TEMPLATE.md` frontmatter is a good starting point — stable
`id`, `type`, one-sentence `summary`, `last-updated`, and crucially **`depends-on`** ("what
this file assumes"). That dependency edge is exactly the prerequisite graph pass 1's EDGE
protocol needs for inference: *if a concept is believed known, its prerequisites are probably
known too*.

So the concept files in the user model should carry:
- `mastery:` — the overlay-model estimate (pass 1, finding G)
- `evidence:` — why we believe it (our extension beyond classical overlay)
- `depends-on:` — prerequisite edges that make conceptual structure inspectable; they guide
  what to check or explain but do not propagate reader state without direct evidence
- `last-updated:` / confidence decay

Note the distinction pass 1 flagged: **verified/practiced** knowledge (schema, working-memory
free) vs **exposed once** (not equivalent). The `mastery` field needs at least those two
levels plus "unknown", not a boolean.

## Packaging

`agentic-loop-kit` distributes via a git clone + `sync-skills.sh` that symlinks each
`skills/<name>/` into `~/.claude/skills/`. Whether the laconic skill should follow that
pattern or ship as a proper Claude Code **plugin** (marketplace-installable) depends on the
ecosystem findings — pending.
