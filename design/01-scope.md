# Scope: any agent↔user communication

*Revised 2026-07-20 after Yann's review. Supersedes the earlier narrow scope, which was my
error.*

## The decision

> "J'aimerais un skill qui marche dans toute situation d'interaction entre l'agent et un
> utilisateur, parce que je trouve que d'une manière générale, il faut essayer d'améliorer la
> clarté de la communication entre un agent et un utilisateur."

**The skill governs all communication from the agent to the user.** Not a document class, not
a task type, not a mode you switch on.

## How the earlier narrowing happened, and why it was wrong

Yann said code comprehension was not his worry, *"as long as they have a prior understanding
of specifications, designs, and product."* I read that as a scope boundary and excluded
everything but spec/design/product documents. It was a statement about **where the value
concentrates**, not a restriction — and the restriction it produced was incoherent: noise in a
status update, a plan, a findings summary, or an error report is the same defect, from the
same cause, fixed by the same policy.

Recording it because the failure mode is instructive: I turned an emphasis into an exclusion,
and the resulting spec would have shipped a skill that sat idle during most of the
interactions it was built to fix.

## What is in scope

Everything the agent says or writes to the user:

- Interactive turns — intent, plans, findings, status, questions, disagreement
- Produced documents — specs, RFCs, design docs, ADRs, product rationale, READMEs
- Narrative around work — PR and commit messages, summaries, handoffs
- Error and failure reporting — what broke, what it means, what to do
- Explanations of code, when asked (see calibration below)

## Calibration, not exclusion

Two research findings shape *how hard* to adapt, without carving anything out:

1. **Specs, design and product rationale are the highest-value target.** This is where Yann's
   attention is, and where Miller's epistemic selection bites hardest — the temptation to
   re-derive established context is strongest in rationale.
2. **Adapt code presentation less readily than prose and terminology.** Two independent
   controlled studies found expertise-adaptation helps for terminology and prose but **not for
   code**, where novice-targeting mainly produced verbosity that cost more than it gained
   ([pass 3b](../research/04-adaptive-explanation-evidence.md)). So the skill still explains
   code when asked; it just does not inflate code explanations for a presumed novice.

## Consequences

Universal scope forces three design changes:

1. **The concept model must be domain-agnostic.** Not a domain/product ontology — any concept
   that could be assumed: a protocol, a library, a build tool, a business term, a maths idea.
2. **The model must be user-global, not per-project.** Knowledge belongs to the person and
   travels with them across repositories and machines. Claude Code's own auto-memory is
   per-git-repo and machine-local, which is right for project facts and wrong for this. (This
   is exactly the axis Copilot Memory got right — *"across repositories"* — while pointing it
   at the wrong content.)
3. **The always-on layer becomes the backbone, not a supporting act.** A skill that
   auto-invokes on description matching cannot govern *all* communication, because "any
   communication" is not a trigger condition. The SessionStart hook, which is present before
   the first token regardless of task, has to carry the policy. See
   [`02-spec.md`](02-spec.md#architecture).
