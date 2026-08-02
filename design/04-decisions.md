# Resolved open questions

## Q1 — How is `verified` earned from conversation alone?

**Decision: a promotion ladder with asymmetric demotion.**

| Transition | Requires |
|---|---|
| `unknown` → `exposed` | the concept merely appeared — I used it, or it was in something the user read. No evidence of understanding. |
| `exposed` → `familiar` | the user used the term themselves, or asked a question that presupposes it, or conspicuously did *not* ask when asking would have been natural. |
| `familiar` → `verified` | **productive use**: the user employed the concept where misuse would have been visible — correcting me, making a decision that depends on it, constraining a design, explaining it to someone else. Needs two independent instances, or one plus explicit confirmation. |

**Never** promoted by prerequisite inference. A prerequisite edge guides what the writer
checks or explains; it does not change state at all. Earlier drafts allowed propagation to
`familiar`, but that fabricated reader evidence and biased toward the costlier error,
under-explanation.

**Demotion is fast and asymmetric**: a question about X drops X to at most `exposed`,
regardless of prior state or confidence.

*Why asymmetric*: over-promotion causes under-explanation, which the meta-analysis puts at
d = 0.505 — the expensive direction. Over-explaining an expert costs d = −0.428, real but
smaller. So the ladder is slow upward and fast downward.

*Why "productive use" rather than mere recognition*: pass 1 established that only
schematized, practiced knowledge is working-memory-free; recognition is not the same thing.
`verified` is the only state that earns full omission, so it must mean the strong thing.

## Q2 — What does the lint mechanically check?

There is no build to fail, so the lint is the only hard guarantee. It checks:

1. **Schema**: required frontmatter keys present; `state` in the enum; `confidence` a float
   in [0,1]; `last-updated` a valid ISO date.
2. **Evidence**: any concept above `unknown` must carry at least one dated evidence line.
   This is what keeps the model auditable rather than asserted.
3. **Graph integrity**: every `depends-on` target exists. No cycles.
4. **Id hygiene**: `id` matches filename stem; no duplicates.
5. **Staleness**: flag concepts whose `last-updated` exceeds a threshold, for confidence
   decay.
6. **Budget**: the rendered index must stay under a character ceiling — the token-discipline
   constraint made mechanical, so it cannot silently regress.

Exit non-zero on 1–4, warn on 5–6.

## Q3 — What do we evaluate?

Comprehension gains are off the table as a claim, so we measure what we can honestly observe:

- **Index cost** — characters injected per session, tracked over time. Regression is a bug.
- **Model precision via correction rate** — an open learner model gives free ground truth:
  every time Yann edits or deletes an entry, that is a recorded miss. Ratio of corrections to
  entries is the accuracy signal.
- **Assumption-check rate** — how often the agent defines-or-links an `exposed`/`unknown`
  concept rather than assuming it.
- **Yann's judgement** on whether output got less noisy. Subjective, and the honest primary
  outcome given the evidence.

Explicitly *not* measured: comprehension, satisfaction scores. Satisfaction is the metric the
literature shows moving when understanding does not — tracking it would invite exactly the
overclaim the positioning avoids.

## From the first trial (2026-07-20) — implementation status

The plugin was installed and A/B tested against itself disabled. Two refinements surfaced
that are worth folding in:

1. **Implemented: decay is state-dependent.** Uniform decay manufactures false novices out of the
   most expert users: a concept used so fluently it stops generating explicit signals looks
   identical to one being forgotten. `exposed` genuinely fades and should decay. `verified`
   reflects consolidated knowledge — let its `confidence` number drift, but require actual
   evidence (a question, a misuse) to move the `state`. This is the existing "one data point
   moves confidence, not state" rule applied to time, which is an especially weak data point.
   The lint and injected effective state now share checked thresholds.
2. **Deferred: volatile referents are a legitimate decay case.** A concept can be stable in the user's
   head while the thing it names has changed (an API, a codebase area). Decaying those tracks
   reality rather than the user, so a `volatile: true` tag would capture the benefit without
   the reversal cost.
3. **Not adopted: consider `summary:` from the agentic-loop-kit template.** Recall decides
   relevance from a one-liner; right now that gloss lives in the body where the index cannot
   reach it cheaply.

## Q4 — Does the always-on hook waste tokens on irrelevant sessions?

**Accepted risk, bounded by measurement.** The full empty-model SessionStart context is 2,046
characters in the current checkout, versus ~2,500 for `learning-output-style`; the live
76-concept model renders at 3,023 characters. Tests cap the empty context at 2,500 and the
policy-plus-index worst case at 4,200; lint independently caps the index at 1,700. If this
proves wasteful in practice, the fallback is `paths`-gated activation or a leaner core — but
gating would reintroduce the trigger problem that made the hook the backbone, so progressive
disclosure and brevity are the preferred levers.

## Q5 — What gets enforced mechanically rather than written down?

**Anything this repo states as a rule, and the default response is to build the checker.** A
"must", "always" or "required" that only exists in prose is not enforced, it is asserted —
and the two drift apart silently, because code changes and paragraphs do not.

This was rediscovered three times before it was named:

1. `laconic_record.py` exists because telling an agent to "maintain `~/.laconic/`" without
   the schema produced freeform notes the index silently ignored. A command that *cannot*
   emit a malformed file replaced a paragraph asking for a well-formed one.
2. `stop-check.sh` exists because reading the model was enforced by injection while writing
   it was left to instruction, and instruction lost to whatever the user actually asked for.
3. `laconic_lint.py` turns the evidence guarantee into a failure rather than a convention:
   a state above `unknown` with no dated observation is an error, not a lapse.

And it was violated twice, both caught by external review rather than by us:

- **`--domain`.** The docs called it mandatory; the CLI filed undomained concepts under
  `general`. Worse, the Stop hook's own remediation command omitted the flag, so the
  enforcement mechanism taught the violation. Now enforced at creation.
- **Decay.** Implementing `effective_state()` falsified three documents that described it as
  inert, and nothing noticed. `check.sh` now has a docs-vs-constants stage.

The rule applied to itself: `check.sh` fails on a doc that states a rule with no
corresponding guard, so this decision is enforced by the thing it describes rather than by
this paragraph. The check is necessarily crude — it matches modal phrasing near a claim and
looks for a test or CLI guard naming the same subject — so it carries an explicit allowlist
for rules that are genuinely social rather than mechanical ("never invent evidence" cannot
be checked by a program, and pretending otherwise would be worse than admitting it).

Scope: this governs how laconic itself is built. It is deliberately *not* in `SKILL.md` —
laconic advises on communication, and "build a checker for your rule" is engineering-process
advice that belongs to a tool about engineering process, not to one about what to leave out
of a sentence.
