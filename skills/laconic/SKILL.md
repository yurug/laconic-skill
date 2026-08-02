---
name: laconic
description: "Cut redundant explanation from substantial technical writing, keeping procedural and explanatory modes separate and calibrating terminology to an auditable record of what the reader knows. Use for a spec, RFC, design doc, ADR, README, findings summary, or handoff; when asked to make writing clearer, shorter, or better explained; and to inspect or correct the knowledge model in ~/.laconic/. Not for short conversational replies — the always-on policy already governs those."
---

# Laconic

Noise is the defect. This skill cuts it, and uses a record of what the reader already knows
to decide what to leave out.

The knowledge model is a **means**, not the feature. Never describe output as
"personalised" — the evidence does not support claiming comprehension gains, and the point
is subtraction.

## The core move

Before writing anything, answer three questions:

1. **What is the foil?** People ask why P *instead of* some alternative Q. Answer the
   contrast, not the full causal history.
2. **Which 1–2 causes resolve it?** Not every cause. Selection is the job.
3. **What can be cut because the reader already knows it?** Read
   `~/.laconic/concepts/`. This is the only place the knowledge model touches generation.

## Structure

**Lead with the outcome.** The first sentence answers "what happened" or "what did you
find" — what the reader would ask for if they said "just give me the TLDR".

**Open with a task or a result, never a concept inventory.** Carroll's minimal manual beat
a conventional one by 40% on learning time and 2.7× on task completion, largely by refusing
to front-load background.

**Say what it does not handle.** What breaks if an assumption fails, what is out of scope,
where it will need revisiting. This was the single largest differentiator in Carroll's data
(60% more successful error recovery) and it is the thing most often missing.

**Keep modes separate.** Classify what is being asked and answer that:

| The reader is asking | Produce |
|---|---|
| "How do I…?" | steps, no rationale |
| "Why…?" | rationale, no steps |
| "What is…?" | reference |
| "Can you teach me…?" | a worked path |

Never blend "why" into a "how-to". Mixing modes is the most common structural noise.

**Keep explanation adjacent to what it explains** — the largest multimedia-design effect
(g≈0.74). Do not separate a caption from its figure, a comment from its code, a rationale
from the decision it justifies.

## Calibrating to the reader

Read the concept files. For each concept the text depends on:

- **`verified`** — use it freely. Do not define it, do not re-derive the context around it.
  Defining what the reader knows is not merely wasted words: inline redundancy consumes an
  expert's working memory *even when they recognise it and try to skip it*.
- **`familiar`** — use it, with at most a short gloss on first use.
- **`exposed` / `unknown`** — define in one clause **or** link. Not both. Prefer a
  separated, skippable form (a linked definition, a footnote, a clearly marked background
  section) over weaving it into load-bearing prose.

**When uncertain, explain more.** Under-explaining a novice costs d = 0.505; over-explaining
an expert costs d = −0.428. The first is worse, so uncertainty resolves toward explaining —
but the second is a real cost, not a free action. Do not treat verbosity as safe.

**Adapt wording sooner than you adapt code.** Expertise-adaptation has evidence for prose
and terminology, and does not have it for code presentation, where targeting a presumed
novice mainly produces costly verbosity.

**Never infer or act on learning styles.** The meshing hypothesis has virtually no
empirical support. Expertise only — never visual/auditory/kinesthetic preference.

## Verbosity

Detail has a **cost curve**: past a point more detail is worse, not neutral. There is no
safely-verbose default.

- **Compress what the reader expects.** Steps they would predict need a clause, not a
  paragraph.
- **Surface what would surprise them**, saliently, and *before* acting rather than after.
- **Skip clarifications already established.** If the model records it, do not re-ask.
- **Never write to a readability score.** Longer sentences are correct when the extra words
  show how things relate — the revision that most improves comprehension often *worsens*
  the formula score. A bad score is a smoke alarm, never a target.

## Analogies

Analogies are high-risk. Apply the discipline or omit them.

1. **Relation test.** State the mapping as a relation: *A does X to B, causing C*. If the
   only thing you can articulate is that two things look alike, drop it — appearance-only
   analogies actively impede understanding in non-experts.
2. **A caveat does not repair an analogy.** Warnings do not survive; the analogy does.
   Either add a second analogy that repairs the first one's specific defect, or state the
   mechanism plainly instead.
3. **Check the source is understood *as a relation*.** Knowing what a mailbox is does not
   mean knowing its queuing semantics.
4. **Watch for everyday connotations** of technical terms — "thread", "lock", "stream",
   "container" all drag their ordinary meaning along.

## Maintaining the model

The states above come from `~/.laconic/`, an evidence-backed record of what this reader has
demonstrated. Read it freely; write it only through the tool.

```bash
~/.laconic/bin/laconic-record <id> --state <unknown|exposed|familiar|verified> \
    --domain <subject> --evidence "what you saw"
```

Three rules matter often enough to state here:

- **A question about one facet is not evidence against the concept.** Record the facet as a
  gap (`--not-established`) and leave `state` alone. Demote only when the central mechanism
  is in doubt.
- **Never invent evidence.** No dated observation you can cite means the state is `unknown`.
- **Never put secrets or verbatim confidential material in evidence.** It is committed
  locally and is pushed only if the user configured an `origin` remote and enabled
  `LACONIC_PUSH=1`. Describe the observation, not the content.

For the schema, the promotion ladder, distillation, decay, forgetting, and the audit rules,
read [`references/maintaining-the-model.md`](references/maintaining-the-model.md). Load it
when you are doing model work, not when you are writing a document.

## Checking your work

Before shipping a document, check it against four outcomes: is it **relevant**, **findable**,
**understandable**, **usable**? Those are reader outcomes, not text metrics — the only
acceptance criteria that matter.

`~/.laconic/bin/laconic-lint` validates the model mechanically.
