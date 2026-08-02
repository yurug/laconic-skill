# Laconic — design specification (v2, revised after review)

*Synthesises [research passes 1–5](../research/). Yann's remarks on v1 and their resolutions
are in [`03-review-notes.md`](03-review-notes.md).*

## What this is

A Claude Code plugin that makes an agent communicate with less noise, in **any** interaction
with its user — by maintaining a persistent, behaviourally inferred model of what that user
already understands, and using it to decide what to leave out.

## Positioning: subtractive first

**Minimising noise is the point. The mental model is a means.** *(Confirmed by Yann, R2.)*

The best-evidenced levers are **subtractive**:

| Lever | Evidence |
|---|---|
| Cut verbiage, task-first structure | Carroll: 40% less learning time, 2.7× task completion |
| Reduce extraneous load | Cognitive load theory; even CLT's critics endorse it |
| Give 1–2 causes, not a full account | Miller's selection property |
| Treat detail as a cost curve | Bansal X3: past a point, more detail is counterproductive |
| Omit what the reader knows | Miller's epistemic selection |

Whereas *additive* personalization has a weak record: across 15 controlled studies, adaptivity
reliably moved satisfaction but rarely objective understanding; adaptive systems tied with the
best fixed baseline; 29% of naive personalization attempts underperformed generic responses.

So the headline is *"stop producing noise,"* and the user model earns its place by **avoiding
documented harm** — the cost of mismatch (expertise reversal: d = −0.428 for over-scaffolding
experts, d = 0.505 for under-scaffolding novices) — not by promising a comprehension boost.

**Guard against drift**: later revisions will be tempted to re-frame this as "personalised
explanations." That framing is not supported by the evidence and is not what this is.

## Scope

**All communication from the agent to the user.** Not a document class, not a task type, not a
mode. Interactive turns, produced documents, PR and commit narrative, error reports,
explanations of code when asked. Full rationale and the two calibration notes (specs/design
are the highest-value target; adapt code presentation less readily than prose) in
[`01-scope.md`](01-scope.md).

**Subject**: one model, for the single operator. No audience profiles in v1.

## The knowledge model

### Source: purely emergent

Start empty. Build only from what surfaces in conversation. **No declared expertise levels, no
onboarding questionnaire.** This is what the evidence requires, not a convenience choice:
self-rated expertise had *no predictive power* for understanding (CHI 2024, N=149), and the
academic systems that underperform (ProfiLLM, TARS) fail precisely by relying on static
self-report.

### Storage: user-global

`~/.laconic/concepts/` — **not** per-project. Knowledge belongs to the person and travels
across repositories and machines. (Claude Code's auto-memory is per-git-repo and machine-local:
correct for project facts, wrong for this. Copilot Memory chose the right axis — *"across
repositories"* — and pointed it at work style rather than knowledge.)

Cross-machine sync is optional: local Git history is always used for auditability, while a
push requires both a configured `origin` and explicit `LACONIC_PUSH=1` consent.

### Schema

One markdown file per concept, domain-agnostic — anything the agent might assume: a protocol,
a library, a build tool, a business term, a maths idea.

```markdown
---
id: tezos-finality
type: concept
domain: consensus
state: verified | familiar | exposed | unknown
confidence: 0.0–1.0
evidence:
  - 2026-07-20: used the term unprompted while correcting my summary
  - 2026-07-14: asked what it means for rollups
depends-on: [block-validation, consensus-tenderbake]
last-updated: 2026-07-20
---

One-sentence statement of what the concept is.

## What the user understands about it
## What has not been established
```

Four design points, each traceable to evidence:

1. **`state` is not boolean.** Pass 1 established that *verified/practiced* knowledge is
   working-memory-free (a schema loads as one chunk) while *exposed once* is not equivalent.
   Only `verified` earns full omission.
2. **`evidence` is required.** Our extension beyond the classical overlay model, and what makes
   the model auditable — an open learner model (Bull & Kay) the user can read, correct, delete.
   All three are tool-backed: `INDEX.md` to read, `--state`/`--understands` to correct,
   `--forget` to delete. Deletion takes a required reason, recorded in the commit — the
   auditability argument applies to removals as much as to entries, and a model whose
   deletions are unexplained is not inspectable in any useful sense.
3. **`depends-on` is the prerequisite graph.** It makes conceptual structure inspectable and
   helps a writer identify background that may matter. It does **not** propagate knowledge
   state: a prerequisite relation is a hypothesis about what is likely, not evidence about
   this reader. Only a direct observation may change a concept's state.
4. **The two prose sections are a distillation, not a log.** `evidence` says what was
   observed; these say what it amounts to, so they are written with replace semantics
   (`--understands` / `--not-established`) once a concept has ~3 observations. Only
   `What has not been established` is injected: `state` already carries the other half in
   one word, whereas a recorded gap *contradicts* the state and so cannot be derived from
   it — a `verified` concept with a named gap is the case the state alone gets wrong.

   The sections shipped as empty headings for a while, because the scaffold was written on
   file creation and nothing could ever fill it: the tool had no flags for them, and the
   policy (correctly) forbids hand-editing these files. Neither the index nor the lint read
   below the frontmatter, so nothing complained. A schema with no write path is not a
   schema, it is a comment.

### Update protocol (EDGE, 1993, transposed)

Update after each exchange, from direct evidence:

1. **Direct interaction** — a question about X implies X is not `verified`; using X correctly
   and unprompted is positive evidence.
2. **Prerequisites guide attention, not state.** A verified dependent may make a prerequisite
   likely, but likelihood is not a dated observation. Explain when uncertain and wait for
   direct evidence.
3. **Revision is concept-local.** A basic question demotes the concept it actually bears on;
   it does not demote a surrounding domain wholesale. Domain-wide revision creates claims
   about unrelated concepts and amplifies one noisy observation.

Plus **confidence decay** for untouched concepts, and **cautious updating** (Amershi G14): a
single data point moves confidence, not state. Abrupt verbosity changes disorient.

### What the model must never do

- **Never record misconceptions as a bug library.** The "perturbation models enable better
  remediation" claim was refuted (1-2 vote). Record uncertainty, not diagnosed errors.
- **Never adapt on learning styles.** Pashler et al.: the meshing hypothesis has virtually no
  support. Expertise only. No visual/auditory/kinesthetic setting, ever.
- **Never optimise for stated preference.** Silva et al.'s preference-maximizing agent produced
  significantly *more inappropriate compliance*. "Was that helpful?" must not drive policy.

## The explanation policy

### The core template (Miller)

1. **Infer the foil** — what is the user asking *instead of*? Answer the contrast; don't
   enumerate causes.
2. **Give 1–2 causes** that resolve it.
3. **Subtract** what the model marks `verified`. *This is the single join point between the
   knowledge model and generation* — the model's only job at write time is deciding what to
   omit.

### Mode separation (Diátaxis)

Classify the turn — "can you teach me" / "how do I" / "what is" / "why" — and produce the
matching form. **Never blend a "why" explanation into a "how-to."**

### Verbosity gating (Bansal)

- **Compress steps the user expects; surface surprising ones saliently before execution.** Gate
  detail on *predicted surprise*, not on a global level.
- Use the model to **skip clarifications already established**.
- Detail has a **cost curve**. There is no safely-verbose default.

### Unverified-assumption check

Before asserting anything that depends on a concept whose state is `unknown` or `exposed`:
either define it in one clause, or link it — **not both, and never inline for a concept marked
`verified`**. Pass 1 finding E: inline redundancy costs experts working memory *even when they
recognise it and try to ignore it*; separated, skippable redundancy costs far less.

### Analogy discipline

- **Relation test**: state the mapping as `A does X to B, causing C`. If only appearance can be
  articulated, drop it — Gentner's mere-appearance matches actively interfere with learning.
- **A caveat is not a fix.** Spiro et al.: *"The analogical core is what is retained."* Either
  pair with a second analogy repairing the first's defect, or state the mechanism plainly
  alongside it.
- Watch failure type #7 — everyday connotations of technical terms — endemic wherever
  technical vocabulary meets ordinary language.

### Document and message structure (Carroll, ISO 24495-1)

Applies to any produced text, from a one-paragraph status update to an RFC:

- **Open with the outcome or the task, not a concept inventory.**
- **Budget space for error recognition and recovery**: what this does *not* handle, what breaks
  if the assumption fails. Carroll's largest single differentiator (60% more successful
  recoveries).
- **Acceptance criteria**: relevant, findable, understandable, usable — reader outcome, not
  text metrics.
- **Never target a readability score.** Longer sentences are explicitly permitted when the
  extra words are connective tissue showing relationships. A bad score is a one-way smoke
  alarm only.
- **Contiguity** (Mayer, g≈0.74): keep explanation adjacent to what it explains.

## Architecture

Three layers, because instructions alone demonstrably do not hold — the lesson from
`agentic-loop-kit`, confirmed by practitioners reporting that CLAUDE.md gets ignored when the
agent judges it irrelevant.

| Layer | Mechanism | Buys |
|---|---|---|
| **Injection** (backbone) | SessionStart hook → `hookSpecificOutput.additionalContext` | the policy and the model index are in context *before the first token*, every session, regardless of task |
| **Instruction** (depth) | `skills/laconic/SKILL.md` | the full policy, for document-writing and explicit `/laconic` invocation |
| **Mechanical** | `laconic-lint` on `~/.laconic/` | schema integrity, orphan concepts, staleness, evidence present |

**Universal scope inverts the layer priority.** In v1 the skill was primary and the hook
supporting. That cannot work: skills auto-invoke by matching a `description` against the task,
and *"any communication"* is not a matchable trigger condition. The hook — present before the
first token whatever the user is doing — has to carry the policy. The skill becomes the
depth layer, loaded when the work is explanation-heavy or explicitly requested.

**Token discipline is now a first-order constraint**, because the hook fires every session
regardless of relevance. Inject a compact policy core plus a concept *index* (ids + states),
never full concept files. The `learning-output-style` plugin injects ~2,500 chars every session
and its own README warns users about the cost. Laconic's empty-model context must stay below
that; the complete policy plus model is capped at 4,200 characters and scales with concept
count sub-linearly. If the index cannot stay small, it gets summarised by domain rather than
enumerated.

## Packaging

Ship as a **plugin** — it can bundle the hook, the skill and (optionally) an output style
together. Distribute via a marketplace repo on GitHub (`/plugin marketplace add`), with the
bare-skill path documented as a zero-ceremony fallback.

⚠️ **Do not depend on output styles.** Two current Anthropic sources disagree on whether the
built-in Explanatory/Learning styles ship or are removed, and `/output-style` was removed in
v2.1.91. The plugin must be fully functional with hook + SKILL.md alone.

## Honest claims for the README

Supported: less noise, fewer unverified assumptions, better-calibrated verbosity, an auditable
record of what has been established, improved perceived quality and control.

**Not claimed**: measured comprehension gains. Distributing this with claims of improved
understanding would misrepresent the evidence, which is null-to-weak on exactly that point.

## Open questions

1. **How is `verified` ever earned from conversation alone?** Using a term correctly is
   evidence; is it sufficient? Over-promotion causes under-explanation — the expensive error
   direction (d = 0.505).
2. **What does the lint mechanically check**, given there is no build to fail?
3. **Evaluation**: with comprehension gains off the table as a claim, what do we measure —
   noise reduction, assumption-check hit rate, or nothing beyond Yann's judgement?
4. **New**: does the always-on hook risk the failure mode the `learning-output-style` README
   warns about — paying tokens every session for a policy that is irrelevant to the current
   turn? Mitigation is brevity, but the tension is real and should be measured early.
