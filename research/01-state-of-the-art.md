# State of the art — grounding the laconic skill (pass 1)

*Deep-research run, 2026-07-20. 24 sources fetched, 118 claims extracted, 25 adversarially
verified (3-vote panels), 20 confirmed, 2 refuted, 3 unverified due to infrastructure errors.
Scope of this pass: cognitive science of explanation + user-knowledge modeling. See
[Coverage gaps](#coverage-gaps) for what still needs a second pass.*

## Executive summary

Both founding hypotheses of the skill are **validated by established science**:

1. **Modeling the user's knowledge state** is not optional polish — it is entailed by the
   *expertise reversal effect*: instructional techniques that help novices lose effectiveness
   or become actively harmful for knowledgeable recipients. A 2025 meta-analysis (60
   experiments, N=5,924) confirms the crossover: high-assistance explanation helps novices
   (d = 0.505) and *harms* experts (d = −0.428). A single fixed explanation style cannot be
   optimal; without a model of the recipient, effectiveness is unpredictable.

2. **Optimizing for working memory** has a precise mechanism: knowledge already organized as
   schemas in long-term memory costs almost nothing in working memory (a schema loads as one
   chunk), while unverified prerequisites and redundant explanation impose measurable load —
   even on experts who recognize the redundancy and try to ignore it. So "minimize extraneous
   load" can only be executed *relative to a model of what the user already knows* — hypothesis
   2 collapses into hypothesis 1.

Three decades of intelligent-tutoring-systems research supply directly reusable design
patterns: **overlay models** (per-concept mastery as the KB schema), **open learner models**
(user-inspectable model — an established, studied practice), and **Cawsey's EDGE system
(1993)** whose dialogic update protocol maps almost verbatim onto a KB update protocol.
Published LLM-era practice (TELL-ME, CHI 2025) stops at three coarse user levels — a
fine-grained persistent per-user model would go *beyond* published art, which is both the
opportunity and the risk.

## Confirmed findings

### A. The expertise reversal effect (high confidence, 3-0 votes)

The effect — coined by Kalyuga, Ayres, Chandler & Sweller (2003) — is established science,
not folklore. It is predicted by cognitive load theory, replicates the prior-knowledge strand
of 1960s Aptitude-Treatment Interaction research, and is confirmed as a genuine crossover
interaction by Tetzlaff, Simonsmeier, Peters & Brod (2025; PRISMA meta-analysis, no
publication-bias evidence).

- Kalyuga et al. 2003: techniques "highly effective with inexperienced learners can lose
  their effectiveness and even have negative consequences when used with more experienced
  learners." ([Educational Psychologist](https://www.tandfonline.com/doi/abs/10.1207/S15326985EP3801_4))
- Tetzlaff et al. 2025: novices learn better with high assistance (**d = 0.505**); experts
  learn better with LOW assistance (**d = −0.428**, 95% CI [−0.647, −0.209]) — heavy
  scaffolding actively harms experts, it doesn't merely waste their time.
  ([Learning and Instruction](https://www.sciencedirect.com/science/article/pii/S0959475225000660))
- **The asymmetry yields the skill's default rule**: assisting novices helps more than
  withholding assistance from experts hurts. When the user's knowledge state is uncertain,
  err toward more scaffolding — over-explaining to an expert is the lesser error, *but still
  an error*.
- Qualifications: effect is weaker for younger learners and humanities/language domains;
  many underlying studies use subjective load measures; the meta-analysis measures learning
  outcomes, so the rule ignores non-learning costs (time, annoyance, trust) that matter in
  agent contexts.

### B. Guidance must fade as expertise grows (high confidence, 3-0)

Paas & van Merriënboer (2020): worked examples "essential to lower cognitive load" for
novices "may become redundant and even impose an unnecessary cognitive load because they
interfere with already available schemas" for advanced learners.
([Current Directions in Psychological Science](https://journals.sagepub.com/doi/10.1177/0963721420922183))
Kalyuga et al. 2003's conclusion is the direct grounding for hypothesis 1: "instructional
design should be tailored to the level of experience of intended learners."

### C. Schemas make known concepts nearly free (high confidence, 3-0)

Working-memory limits "may not be relevant when dealing with … familiar information that is
already well organized in cognitive schemas in long-term memory"; "only one element must be
processed when a schema is brought from LTM to WM" (Paas & van Merriënboer 2020, resting on
50+ years of chunking research: Miller 1956, Chase & Simon 1973, Cowan 2001, Ericsson &
Kintsch 1995).

Design consequences:
- The real cognitive cost of an explanation is determined by *what the user verifiably
  knows*: known concepts ≈ free, unverified prerequisites = expensive.
- Chunking and abstraction reduce load **only when the chunks map onto schemas the user
  already possesses** — chunking around unfamiliar abstractions *adds* load.
- The KB must distinguish **verified/practiced knowledge** (schema, WM-free) from concepts
  the user has **merely seen once** (not equivalent; still costs a WM slot).

### D. Minimize extraneous load — relative to the user (high confidence, 3-0)

Intrinsic and extraneous cognitive load are additive; extraneous load (redundancy, split
attention, decorative structure) should be minimized to free working memory for the actual
content. Even CLT's sharpest critic (de Jong 2010) endorses this maxim. The twist: what
counts as "extraneous" is learner-dependent (per the expertise reversal effect), so the maxim
itself entails a user model.

### E. Redundancy actively costs experts (medium confidence, 2-1)

Redundant explanation imposes working-memory load on knowledgeable users *even when they
recognize it as redundant and try to ignore it* (Kalyuga et al. 2003; performance reversals
measured in Yeung et al. 1998, Kalyuga et al. 1998/2000). Crucially: the harm is strongest
for **inline/interleaved redundancy** (definitions woven into prose) and much weaker for
**physically separated, skippable redundancy** — a direct empirical argument for progressive
disclosure (collapsible or clearly separated background sections rather than inline
explanation). One verifier dissented on the categorical phrasing (source hedges with "may be
imposed"); extension to AI-agent prose is an extrapolation.

### F. Adaptive, learner-modeled instruction is implemented practice (high confidence, 3-0)

By 2007, adaptive learning environments dynamically selected guidance level from rapid
online expertise measures, with effect sizes 0.46–0.69 (Kalyuga & Sweller 2004/2005; Salden
et al. 2004/2006). **Open learner models** (Bull & Kay's SMILI framework,
[IJAIED 2007](https://journals.sagepub.com/doi/10.3233/IRG-2007-17%282%2902)) made the
system's model of the learner visible to the learner — direct precedent for a
user-inspectable markdown KB. Caveat: OLMs live in educational settings; "precedent for a
coding-agent KB" is analogical.

### G. The overlay model is the KB schema (high confidence)

Represent the user's knowledge as a **subset of an expert domain model**: per concept, a
Boolean known/not-known flag or (modern form) a graded/probabilistic mastery estimate —
`concept → mastery level`. Overlay models dominate ITS practice (Chrysafiadi & Virvou 2013,
[Expert Systems with Applications](https://www.sciencedirect.com/science/article/abs/pii/S095741741300122X);
canonical since Carr & Goldstein 1977; Bayesian knowledge tracing is overlay-family).
Known limitation: overlay models **cannot represent misconceptions** — see refuted claims
below before deciding to record them.

### H. Cawsey's EDGE (1993): the update protocol, ready to transfer (high confidence, 3-0)

EDGE's user-knowledge model is *simultaneously consulted and revised within the explanatory
dialogue* — not fixed up front — updated from three evidence sources
([Cawsey 1993](https://link.springer.com/article/10.1007/BF01257890),
[AAAI-91](https://cdn.aaai.org/AAAI/1991/AAAI91-014.pdf)):

1. **Direct interactions** — a user question about X implies X unknown; "the user model is
   updated after each exchange."
2. **Inference across concept relationships** — "if a concept is believed known then
   prerequisite concepts may also be believed probably known."
3. **A revisable global expertise level** — "if a user asks a question about something very
   basic the system may revise their assumed level of expertise."

Caveat: Cawsey *argued*, but never experimentally proved, that model-informed explanations
are more understandable (Chin 2001: only ~25% of UMUAI articles reported significant
empirical evaluations). Present the premise as argued, not proven.

### I. Current LLM practice stops at coarse buckets (medium confidence, 2-0)

TELL-ME ([CHI EA 2025](https://dl.acm.org/doi/10.1145/3706599.3719982)) tailors explanations
to three discrete groups — beginners, advanced users, experts — with no per-user model. The
skill's persistent concept-level KB would exceed published art. (Single source, lightly
reviewed venue, verified from abstract only.)

## Refuted — do NOT echo these

1. **"Working memory holds 5–9 elements for ~20 seconds"** (0-3 vote). Do not cite Miller's
   7±2 uncritically; modern estimates are lower — **~4 chunks** (Cowan 2001). The skill's
   docs should use the modern figure or, better, avoid magic numbers.
2. **"Perturbation bug libraries enable better remediation"** (1-2 vote). The descriptive
   half is sound (overlay = subset of expert knowledge, cannot encode misconceptions;
   perturbation adds a bug library), but the causal remediation benefit is unsupported.
   Record user misconceptions cautiously, without claiming validated benefits.

## Unverified leads (infrastructure errors — promising, not evidence)

- **SNAPE-PM / Frontiers 2026** (n=199): a continuously updated Bayesian partner model of
  listener expertise significantly improved user understanding vs a non-adaptive baseline
  (general understanding p=0.028, deep understanding p=0.036). *The single strongest piece of
  modern empirical support for the skill's premise* — verify before citing.
  ([Frontiers in Computer Science](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2026.1558674/full))
- **Cawsey's mutual-reinforcement argument**: user modeling and interactive dialogue need
  each other — a static KB alone is insufficient; pair it with interactive checking during
  explanations.
- **TELL-ME's n=6 effectiveness result** (weak anyway).

## Design rules extracted (for the skill's spec)

1. **One explanation style cannot fit all users** — the skill must calibrate against a
   tracked knowledge state (A, B).
2. **Uncertainty rule**: unknown knowledge state → scaffold more; it's the cheaper error,
   but still an error, so update the model instead of staying uncertain (A).
3. **KB schema**: overlay model — `concept → mastery` with graded levels, plus an
   `evidence` field (our extension beyond classical overlay) (G).
4. **Distinguish "verified/schematized" from "exposed once"** — only the former is
   WM-free (C).
5. **Update protocol** (from EDGE): update after each exchange; questions imply gaps;
   known concepts propagate "probably known" to prerequisites; basic questions trigger
   global downward revision (H).
6. **Make the model user-inspectable and editable** — open-learner-model precedent (F);
   markdown files satisfy this natively.
7. **Progressive disclosure over inline definition**: put background in separated,
   skippable sections; never weave definitions of possibly-known concepts into load-bearing
   prose (E).
8. **Chunk onto existing schemas**: analogies and abstractions must be anchored in concepts
   the KB marks as known, else they add load (C).
9. **No magic numbers** in the skill's own docs: ~4 chunks (Cowan), not 7±2 (refuted).
10. **Pair the KB with dialogue**: brief comprehension checks let the model be verified and
    repaired (unverified lead, but low-cost and consistent with everything above).

## Coverage gaps

This pass is strong on cognitive science and user modeling but **silent** on research areas
the brief requested — they produced no claims that survived verification and need a
follow-up pass:

- (b) Technical-writing/documentation science: Diátaxis, Carroll's minimalism,
  plain-language standards, readability research.
- (c) Most of HCI/XAI: Microsoft HAX guidelines, Google PAIR, Clark's grounding theory,
  XAI explanation guidelines.
- (d) Agent-ecosystem art: CLAUDE.md conventions, output styles, verbosity settings,
  memory-bank patterns in Cursor/aider, existing "explain at my level" tools.
- Gentner's analogy research and the learning-styles-myth discussion.

## Caveats on the whole report

- **Every confirmed result comes from instructional/learning contexts** — classrooms,
  tutorials, tutoring systems — not AI code-agent communication. The transfer is repeatedly
  drawn and plausible, but no surviving claim tests it in coding-agent workflows.
- Kalyuga 2003's "effectiveness is likely to be random" is interpretive framing; the 2025
  meta-analysis supports "unpredictable / interaction-dependent."
- Time-sensitivity is low (2025 meta-analysis + stable decades-old literatures), except
  finding I (LLM ecosystem), which will date quickly.

## Primary sources

| Source | Role |
|---|---|
| [Kalyuga, Ayres, Chandler & Sweller 2003](https://www.tandfonline.com/doi/abs/10.1207/S15326985EP3801_4) | Expertise reversal effect (coining paper) |
| [Kalyuga 2007](https://link.springer.com/article/10.1007/s10648-007-9054-3) | ERE mechanism + adaptive implementations |
| [Tetzlaff et al. 2025](https://www.sciencedirect.com/science/article/pii/S0959475225000660) | Meta-analysis quantifying the crossover |
| [Paas & van Merriënboer 2020](https://journals.sagepub.com/doi/10.1177/0963721420922183) | CLT state of the art, schemas/chunking |
| [Bull & Kay 2007 (SMILI)](https://journals.sagepub.com/doi/10.3233/IRG-2007-17%282%2902) | Open learner models |
| [Chrysafiadi & Virvou 2013](https://www.sciencedirect.com/science/article/abs/pii/S095741741300122X) | Overlay-model dominance survey |
| [Cawsey 1993 (EDGE)](https://link.springer.com/article/10.1007/BF01257890) + [AAAI-91](https://cdn.aaai.org/AAAI/1991/AAAI91-014.pdf) | Dialogic user-model update protocol |
| [TELL-ME, CHI EA 2025](https://dl.acm.org/doi/10.1145/3706599.3719982) | Current LLM-explanation practice |
| [SNAPE-PM, Frontiers 2026](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2026.1558674/full) | Modern adaptive-explanation RCT (unverified) |
