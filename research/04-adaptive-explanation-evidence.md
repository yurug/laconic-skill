# Does adaptive explanation actually work? (pass 3, strand 2 of 3)

*Targeted verification of the empirical question underpinning the whole skill. This is the
strand that failed twice in the deep-research passes; retrieved here via `curl` against the
open-access PDFs.*

> **Read this before designing anything.** The evidence does not support the strong version of
> the skill's premise. It supports a different, narrower, still-worthwhile version.

## Headline

**The empirical case that adapting explanations to a user model improves objective
understanding is weak, and the strongest evidence cuts against it.** Three findings replicate
across independent labs:

1. **Preference–performance dissociation** — adaptivity reliably moves *perception,
   satisfaction and engagement*; it moves *objective comprehension* rarely and weakly.
2. **Baseline choice determines the answer** — adaptive systems beat *degraded* baselines and
   tie with the *best fixed* format.
3. **Where adaptation helps, it helps the struggling tail** — not the population.

This does not invalidate the project. It repositions it. See
[What this means for the design](#what-this-means-for-the-design).

## SNAPE-PM: confirmed, and properly done — but the wrong domain

The study pass 1 flagged as "the single strongest piece of modern empirical support" is
**real, preregistered, and correctly analysed**. Every checkable detail holds
([Frontiers in Computer Science 8:1558674](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2026.1558674/full),
Robrecht-Hilbig, Kowalski & Kopp, Bielefeld / TRR 318, 19 Feb 2026).

- **n=199 confirmed**: *"The EX agent explains the board game Quarto! to 199 participants in an
  online study… equally distributed across three conditions in a between-subjects design,
  resulting in an overall statistical power of 0.888."*
- **Bayesian partner model confirmed**: *"the user's domain expertise, cognitive load,
  attentiveness, and cooperativeness are relevant factors… our model employs Bayesian
  probabilistic inference to dynamically form and update potentially uncertain beliefs about
  them, based on the listener's feedback."*
- **The statistics survive scrutiny.** *"Connected post-hoc t-tests with Bonferroni correction
  indicate that the general and deep understanding scores are significantly higher for the
  fully-adaptive condition than for the baseline (general: t = 2.636, p = 0.028; deep:
  t = 2.548, p = 0.036)."* Recomputation from the t-values (df≈130) gives raw p = 0.0094 and
  0.0120; ×3 comparisons = 0.028 and 0.036 exactly. The OSF preregistration (osf.io/htm5k,
  2025-04-01, prior to data creation) prespecifies adjusted p-values. **No p-hacking.**

**But five problems bound what it can support:**

1. **Not coding, and not an LLM.** The domain is the board game *Quarto!*. The paper's own
   limitation: *"It currently lacks a comparison to a fully LLM-driven agent."* SNAPE-PM is
   symbolic (MDP + Neo4j + MCTS) and explicitly argues *against* LLMs for this. Citing it as
   evidence about LLM explanation is a category error.
2. **The headline outruns the test.** The abstract claims positive effects of a broader partner
   model, but the contrast that would show this is null: *"The knowledge-adaptive agent… does
   not differ significantly from either the baseline or the fully-adaptive explanation."*
   That is the difference-in-significance fallacy.
3. **No effect sizes reported.** Derived: **d ≈ 0.46 / 0.44** — below the d = 0.5 the study was
   powered for, i.e. sitting at the detection floor.
4. **Baseline confound.** The baseline forbids feedback entirely — a fixed 80-turn monologue
   (std = 0) versus ~146 turns adaptive. Adaptivity is confounded with interactivity and dose.
5. **Perception mixed-to-negative.** Overall EXQ null (F = 0.417, p = 0.66), then 13 item-level
   tests with no stated correction. The **baseline was rated more consistent and more
   structured**; fully-adaptive was rated *less relevant* and *less structured*.

## Controlled studies in coding / CS-education contexts

Studies exist — the vacuum I expected isn't there — and **four of the six with objective
outcomes are null or negative.**

| Study | n | Manipulation | Result |
|---|---|---|---|
| Richards & Wessel, ICSME 2024 ([2408.04477](https://arxiv.org/abs/2408.04477)) | 14 | Theory-of-Mind agent vs single prompt | **NULL** — quiz p=0.606, time p=0.503, usefulness p=0.66. Only prior experience predicted scores |
| Bernstein et al., SIGCSE 2026 | **971** | Diverse vs generic explanations | **NULL** — MCQ n.s.; open-ended p=.095 Bonferroni. *Abstract claims "7.7% higher" without disclosing non-significance* |
| Hou et al., CodeTailor ([2401.12125](https://arxiv.org/abs/2401.12125)) | 18 | Parsons puzzle from student's own error | **NULL on posttest** (p=.789, CLES=0.51); preference/engagement favored it |
| FACET worksheets | **409** | Profile-matched vs standard exercises | **SUPPORTS, conditionally** — +18.2% for low-knowledge/low-motivation; **ceiling, no benefit, for high performers** |
| Santos & Becker, UKICER 2024 ([2409.18661](https://arxiv.org/abs/2409.18661)) | 106 | Stock / expert-written / GPT-4 error messages | **NEGATIVE** — GPT-4 beat stock in 1 of 6 tasks; **human-written beat both** |
| SE Problem-Solving Styles ([2503.11018](https://arxiv.org/abs/2503.11018)) | 53 professionals | Style-matched vs unadapted vs opposite | **MIXED** — improved 3 of 5 style types, **decreased 2**; mismatched adaptations sometimes helped as much |
| Zheng et al., SIGITE 2025 ⚠️ *snippet-only* | — | Knowledge-level personalization | Won for **term explanation**; **no significant advantage for code explanation** |

**Two independent studies converge on a pointed result for this project**: expertise-adaptation
helps for *prose and terminology* but **not for code**, with novice-targeting mainly producing
verbosity that costs more than it gains.

## Controlled studies in general / XAI contexts

| Study | n | Result |
|---|---|---|
| Fichtel et al., SIGDIAL 2025 ([2504.18483](https://arxiv.org/abs/2504.18483)) | **277** | **NULL** — *"this increased co-constructiveness, on average, did not translate into a higher objective understanding… This contradicts our expectations."* Perceived co-constructiveness rose (4.1 vs 3.7) |
| Silva et al., HRI 2024 ([2504.13856](https://arxiv.org/abs/2504.13856)) | 60 | **NULL vs best fixed baseline** — see below |
| Nimmo et al., CHI 2024 ([2403.00137](https://arxiv.org/abs/2403.00137)) | 149 | **Sweeping null.** Only age and openness mattered; authors urge the field to *"question the pursuit of personalized XAI"* |
| Rosenberger et al., ECIS 2025 ([2505.07100](https://arxiv.org/abs/2505.07100)) | 108 | **NULL on all 8 measures** (insight quality p=0.659). Personalization worked mechanically and changed nothing |
| Rong et al., I-CEE, AAAI 2024 ([2312.12102](https://arxiv.org/abs/2312.12102)) | 100 | **Partial** — +11.5% simulatability on traffic signs (p=0.007); **null on birds** |
| Yazan et al. | 380 | **Contextualization *reduced* persuasion**; reliance invariant |
| ExPerT, ACL 2026 | 40+16 | **Satisfaction only** (p<.001). A knowledge quiz *was* collected but **never used for the adaptive-vs-non-adaptive contrast** |
| Chung/Bastani ⚠️ *institutionally sourced* | **770**, 5 months | **+0.15 SD on unassisted exam** — but adapts *which problems*, holding explanation constant |

**Silva et al. is the cleanest test and deserves quoting**: *"We find no statistically
significant differences between the balanced-personalization agent and language-only agent
along the performance or preference metrics"* — and language-only was *"known to be best
before the study."* Adaptation beat *random* and *preference-maximizing* selection, but **tied
with simply giving everyone the single best fixed format.** Worse for the premise: their
preference-maximizing agent produced significantly **more inappropriate compliance**
(W=21, p=0.018). **Optimizing for stated preference measurably degraded decisions.**

## The three replicated findings

### 1. Preference–performance dissociation

Confirmed in at least five studies (Fichtel, CodeTailor, Silva, ExPerT, passive-expertise
personalization). Adaptivity moves perception, satisfaction and engagement reliably; objective
comprehension rarely and weakly. **ExPerT is the tell** — an objective quiz was administered
and simply never reported against the manipulation.

### 2. Baseline choice determines the answer

Silva is the clean demonstration. Many positive claims compare against degraded baselines. The
first question to ask of any such claim — including any we might later make about this skill —
is **"adaptive versus *what* fixed baseline?"**

### 3. Adaptation helps the struggling tail, not the population

FACET (+18.2% for low-knowledge/low-motivation, **ceiling for high performers**), I-CEE (one
domain of two), the TiiS recommender study (only for unfamiliar items). The honest claim is
**"adaptation is a scaffold for people who are stuck,"** not "adaptation improves explanation."

## Reconciling this with pass 1

Pass 1's expertise reversal effect is a **large, well-powered meta-analysis** (N=5,924) showing
that mismatched assistance level measurably harms. Pass 3 shows that **built adaptive systems
mostly fail to beat the best fixed baseline.** These are not contradictory:

- The expertise reversal effect says **mismatch is costly**. It does not say **any given
  adaptive mechanism recovers that cost** — inference error, latency, and the disruption of
  changing register can eat the gain.
- A well-chosen *fixed* style may already sit near the population optimum, leaving adaptation
  to fight for the tails — which is exactly what FACET found.
- Short-study "understanding" measures are noisy and may miss effects that matter over months
  of daily use. Several nulls are underpowered: Silva ran 12 per comparison against a stated
  need for >240; Richards n=14; CodeTailor n=18. **These are "no evidence of benefit," not
  "evidence of no benefit."**

**The most striking feature of this literature**: the single large, long, well-powered RCT with
a real learning outcome (Chung/Bastani, 770 students, 5 months, +0.15 SD) adapts *problem
sequencing* while holding explanation constant. **No study manipulates explanation adaptivity
at comparable scale or outcome quality.** The question is open, not settled against us — but we
may not claim it is settled for us.

## What this means for the design

**The inference "adaptive explanation demonstrably improves understanding, therefore it will
improve code comprehension" fails at both joints.** What is actually supported:

1. **Lead with noise reduction, not adaptation.** The best-evidenced levers in this whole
   research effort are *subtractive*: Carroll's minimalism (40% less learning time, 2.7× task
   completion — pass 3a), extraneous-load reduction (pass 1), Miller's selection (1–2 causes),
   and Bansal's cost curve on detail. **Cutting noise has better evidence than personalizing
   it.** The skill's primary value proposition should be "stop producing noise," with the user
   model as a *means* to that end rather than the headline.
2. **Adapt to avoid harm, not to chase gains.** The defensible framing: the user model exists
   to prevent the *documented harm* of mismatch (expertise reversal, d = −0.428 for
   over-scaffolding experts), not to deliver a hypothesized comprehension boost.
3. **Never optimize for stated preference.** Silva's preference-maximizing agent produced more
   inappropriate compliance. If the skill ever asks "was that helpful?", that signal must not
   drive the explanation policy on its own.
4. **Expect gains at the tails.** Adaptation should be most aggressive when the user is stuck
   or the concept is new to them, and should approach a good fixed default otherwise.
5. **The code/prose split points where the project is already headed.** Two studies found
   expertise-adaptation helps for terminology and prose but **not for code**, with
   novice-targeting producing costly verbosity. Yann's scope decision (2026-07-20) puts code
   comprehension out of scope entirely — engineers can read code, provided they understand
   the specifications, designs and product behind it. So the skill targets exactly the layer
   where the evidence says adaptation *does* pay: concepts, terminology, rationale and
   framing. See [`design/01-scope.md`](../design/01-scope.md).
6. **Be honest in the README.** Distributing this on GitHub with claims of comprehension gains
   would misrepresent the evidence. Claim what is supported: less noise, fewer unexplained
   assumptions, better-calibrated verbosity, and improved perceived quality and control.

## Needs re-verification before citing

- SIGITE 2025 (Zheng et al.) and ACM TiiS 10.1145/3779059 — Cloudflare-blocked, institutional
  access required.
- Chung/Bastani statistics are institutionally sourced, not paper-verified.
