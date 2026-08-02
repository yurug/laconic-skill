# Ecosystem prior art and the packaging story (pass 3, strand 3 of 3)

*Verified 2026-07-20 against live docs via `curl`, the local plugin marketplace cache at
`~/.claude/plugins/marketplaces/`, and web search. WebFetch timed out throughout.*

## Headline

**The gap is real.** Across an 18-product sweep, *nothing ships a persistent model of what the
user knows*, and nothing routes such a model to explanation depth. Every surveyed tool models
**the project**; the one tool with genuine per-user cross-repo memory (GitHub Copilot) points
it at **work style**, not knowledge.

And the packaging question has a clean answer: **a plugin can bundle a skill, a SessionStart
hook, and an output style at once** — which is exactly the three-layer enforcement
architecture from [`design/00-notes.md`](../design/00-notes.md).

## What exists

### Output styles — powerful placement, unstable footing

[Docs](https://docs.claude.com/en/docs/claude-code/output-styles.md): *"Output styles change
how Claude responds, not what Claude knows. They modify the system prompt to set role, tone,
and output format."*

- Markdown at `~/.claude/output-styles` (user) or `.claude/output-styles` (project); selected
  via `/config`, saved as `outputStyle` in settings.
- **Session-bound**: *"Output style is part of the system prompt, which Claude Code reads once
  at session start. Changes take effect after `/clear` or a new session."*
- **Main conversation only** — *"a subagent runs its own system prompt."*
- Frontmatter includes `keep-coding-instructions` (default `false` — custom styles **drop**
  built-in software-engineering instructions unless set true).
- Four built-ins: Default, Proactive, Explanatory ("educational 'Insights'"), Learning
  (`TODO(human)` markers).

⚠️ **Stability warning.** The official marketplace catalog describes these same styles as gone
— Explanatory "mimics the **deprecated** Explanatory output style", Learning "mimics the
**unshipped** Learning output style" — while the live docs present them as current. Two
current Anthropic sources disagree. The standalone `/output-style` command was deprecated in
v2.1.73 and removed in v2.1.91. **Do not build on the assumption that output styles are
stable.**

### The learning-output-style plugin — the architectural precedent

Despite the name, it is **not an output style**. It is a `SessionStart` hook that echoes JSON
with `hookSpecificOutput.additionalContext` carrying ~2,500 characters of static instructions.
Its README states the point plainly:

> *"This SessionStart hook pattern is roughly equivalent to CLAUDE.md, but it is more flexible
> and allows for distribution through plugins."*

And the sibling plugin clarifies the trade-off: *"Subagents change the system prompt while
SessionStart hooks add to the default system prompt."*

Its content is a fixed teaching policy (request 5–10 line contributions at decision points;
never for boilerplate; emit `★ Insight ────` blocks) with **zero user modeling** — identical
instructions every session, no adaptation, no state. Its own README warns: *"Do not install
this plugin unless you are fine with incurring the token cost."*

**This is the closest existing thing to our skill, and the contrast defines our contribution**:
same delivery mechanism, but static where we would be evidence-driven.

### CLAUDE.md — weaker placement, known unreliability

CLAUDE.md *"Adds a user message after the system prompt"* — weaker than an output style's
system-prompt placement. Practitioners are direct about the failure mode
([HumanLayer](https://www.humanlayer.dev/blog/writing-a-good-claude-md)): *"Claude will ignore
the contents of your CLAUDE.md if it decides that content is not relevant to its current task,
and the more information that's not universally applicable, the more likely Claude ignores
your instructions."*

Reported working pattern: **specificity over adjectives** — "Keep explanations under three
sentences unless I ask for more detail" beats "be concise" — plus length discipline (<200
lines). One guide reports that vague verbosity requests lose to built-in efficiency
instructions while explicit overrides win; *reported as a practitioner finding, not adopted
here.*

**AGENTS.md** is a real standard ([agents.md](https://agents.md/), stewarded by the Agentic AI
Foundation under the Linux Foundation, 60k+ projects, adopted by Codex, Cursor, Gemini CLI,
Devin, Windsurf, Copilot, aider, Zed) — but scoped to *"build steps, tests, and conventions"*,
not communication style, and **Claude Code does not read it natively**: *"Claude Code reads
`CLAUDE.md`, not `AGENTS.md`."*

### Other agents: all model the project, none model the user

| Tool | Mechanism | Models |
|---|---|---|
| **Cursor** | `.cursor/rules/*.mdc`, frontmatter `description`/`globs`/`alwaysApply` | project. Modes were **renamed** (the widely-cited "Agent Requested / Auto Attached" quartet is gone); `.cursorrules` no longer documented |
| **Cline Memory Bank** | six markdown files (`projectbrief`, `productContext`, `activeContext`, `systemPatterns`, `techContext`, `progress`) | **project, never the user**. A prompt pattern, not an engine |
| **aider** | `CONVENTIONS.md`, read-only via `/read` | naming conventions only, no memory |
| **Windsurf/Devin** | auto-generated Memories | workspace-jailed — *"Memories generated in one workspace are not available in another"*; contents undocumented |
| **Cursor, Augment** | — | **have removed their Memories features.** Blog posts claiming Cursor "learns your style" describe a dead feature |

### The nearest miss: Copilot Memory

[GitHub Copilot Memory](https://docs.github.com/en/copilot/concepts/agents/copilot-memory)
(public preview) stores *"User-level preferences — Implied or stated personal preferences…
Available only to that user's Copilot interactions **across repositories**"*, learned rather
than declared, with 28-day decay. But a grep for `expert|novice|senior|beginner|verbosity|
explanation depth` returns **zero hits**. It models *how you like to work*, not *what you
know*.

**Claude Code's own auto memory** (`~/.claude/projects/<project>/memory/`) saves build
commands, debugging insights, architecture notes and workflow habits — project facts. It is
per-git-repo, machine-local, not shared across machines, and **not loaded into subagents**.

## The packaging answer

Distribution ladder, in increasing ceremony:

1. Bare skill directory — `~/.claude/skills/<name>/SKILL.md` (personal) or `.claude/skills/`
2. Skill + `.claude-plugin/plugin.json` — loads as `name@skills-dir`, *"no marketplace or
   install step"*
3. Full plugin — `skills/`, `hooks/`, `agents/`, `output-styles/` at plugin root, only
   `plugin.json` inside `.claude-plugin/`
4. Marketplace repo with `.claude-plugin/marketplace.json`, added via
   `/plugin marketplace add`

**The decisive fact: a plugin can ship all four surfaces at once.** That maps exactly onto the
three-layer enforcement architecture — SKILL.md (instruction), SessionStart hook (injection),
plus whatever mechanical validation we add.

Skill frontmatter worth noting: `description` drives auto-invocation and is **truncated at
1,536 chars** combined with `when_to_use`; `paths` allows glob-gated auto-activation;
`context: fork`, `agent`, `hooks`, `model`, `effort` are all available.

## The skeptical counterweight — take seriously

Two findings argue against naive personalization, and they reinforce
[pass 3b](04-adaptive-explanation-evidence.md):

- **CHI 2024** ([arXiv 2403.00137](https://arxiv.org/abs/2403.00137), N=149): self-rated
  expertise had **no predictive power** for understanding or trust; the authors ask whether
  personalization for AI explanations *"may lead to a rabbit hole."*
- **PrefDisco** ([arXiv 2510.00177](https://arxiv.org/abs/2510.00177)): *"29.0% of naive
  personalization attempts produce worse preference alignment than generic responses."*

Academic work also confirms the gap while illustrating the wrong way to fill it: ProfiLLM
([2506.13980](https://arxiv.org/abs/2506.13980)) notes existing approaches *"rely on static
user categories or explicit self-reported information"*; TARS
([2607.15948](https://arxiv.org/abs/2607.15948)) observes *"most LLM-based assistants produce
explanations that ignore who is asking"* but sources its profile from a **one-time
questionnaire**.

**The defensible reading**: static, self-reported expertise levels demonstrably fail. That is
an argument *for* behaviourally-inferred, per-topic modelling — the thing nobody has built —
and *against* asking the user to declare a level. It converges precisely with the decision to
build the model purely from conversation.

## Gap analysis

**Already exists — do not rebuild:**
- Static session-wide tone/format shaping (output styles, CLAUDE.md, SessionStart hooks,
  `~/.claude/rules/`)
- Two hand-built teaching modes (Explanatory insights, Learning `TODO(human)`) — fixed,
  one-size-fits-all, token-expensive by their own README's warning
- Persistent *project* memory (auto memory, Memory Bank, AGENTS.md, CONVENTIONS.md)
- Auto-inferred *user workflow* memory, cross-repo (Copilot Memory only)
- Mature distribution (skill → `@skills-dir` plugin → marketplace)

**Genuinely missing — our contribution:**
1. **A persistent model of what the user knows**, distinct from project state and from
   workflow preference.
2. **Routing that model to explanation depth.** No product connects a user model to how much
   to explain; the shipping high-water mark is a manual global toggle.
3. **Evidence-based updating.** Existing memory records what the user *said*; nothing infers
   understanding from what the user *did* — questions asked, corrections made, terms used.
4. **Per-topic granularity.** The same engineer is expert in OCaml and novice in Rust; output
   styles are one global switch. (Skill `paths` frontmatter offers only crude glob gating.)

## Could not verify

- Whether Explanatory/Learning are currently shipping built-ins or removed — **two current
  Anthropic sources conflict**.
- Copilot Memory's storage format; Windsurf memory contents.
- The third-party claim that `.cursorrules` is silently ignored.
