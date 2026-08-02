# Communication frameworks and folklore screening (pass 2)

*Deep-research run, 2026-07-20. 22 sources fetched, 89 claims extracted, 25 adversarially
verified, 25 confirmed, 0 refuted. Scope: documentation science, human-AI interaction
guidelines, folklore screening. Complements [pass 1](01-state-of-the-art.md) (cognitive
science + user modeling). Two commissioned strands came back empty — see
[Still open](#still-open).*

## Executive summary

Pass 1 established *why* to model the user. Pass 2 supplies *how to shape the output*:

- **Diátaxis** gives a mode-classification scheme: four documentation modes, each keyed to a
  distinct user question. The skill can classify each turn and switch form accordingly.
- **Microsoft's 18 Guidelines for Human-AI Interaction** (Amershi et al., CHI 2019) give a
  four-phase temporal scaffold, and its "over time" guidelines (G12–G14) prescribe almost
  exactly the persistent, cautiously-updated user model this skill targets.
- **Miller's four properties of explanation** (contrastive, selective, social, Gricean) yield
  a directly encodable explanation template — including *epistemic selection*: omit causes
  the explainee already knows. This is hypothesis 1 restated from the XAI side.
- **Google PAIR** supplies expectation-setting structure and the just-in-time disclosure rule.
- **Bansal et al. 2024, "Challenges in Human-Agent Communication"** is the single most
  on-point source: agent-native, grounded in Clark & Brennan's communication grounding, and
  it warns from the inside that the 2019 guidelines only *partially* transfer to autonomous
  tool-using agents.
- **Folklore screen**: learning styles is a myth and must not be encoded; Mayer's multimedia
  principles survive meta-analysis and are safe — with uneven effect sizes worth respecting.

## A. Documentation structure

### Diátaxis: a 2D map, not a list (high confidence, 3-0)

[diataxis.fr/map](https://diataxis.fr/map/) — two axes (practical vs theoretical ×
acquisition vs application) yield four modes, each keyed to a user question:

| Mode | User question | Orientation |
|---|---|---|
| Tutorial | "Can you teach me to…?" | learning |
| How-to | "How do I…?" | goals |
| Reference | "What is…?" | information |
| Explanation | "Why…?" | understanding |

Verbatim: *"One reason Diátaxis is effective as a guide to organising documentation is that it
describes a two-dimensional structure, rather than a list."* Being a map is why it *shapes*
content rather than merely categorising it. Known critiques target rigidity at scale, not the
intent→form mapping.

**Design implication**: classify each user turn into one of the four modes and generate the
matching form. Never blend a "why" explanation into a "how-to" — that is the single most
common noise source in agent output.

## B. Human-AI interaction guidelines

### The 18 guidelines: a temporal scaffold (high confidence, 3-0)

[Amershi et al., CHI 2019](https://dl.acm.org/doi/10.1145/3290605.3300233) /
[Microsoft HAX Toolkit](https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/) —
18 guidelines distilled from 168 collected recommendations, validated by 49 design
practitioners against 20 AI products, grouped by **when** they apply:

- **Initially** (G1–G2) — set expectations
- **During interaction** (G3–G6)
- **When wrong** (G7–G11) — recovery
- **Over time** (G12–G18) — adaptation

*Honesty caveat to encode*: "evidence-based / 20 years of research" is Microsoft's own
framing; the method is heuristic affinity-clustering plus one user study, not a controlled
outcome experiment.

### The guidelines that matter most here (high confidence, 3-0)

- **G1** "Make clear what the system can do."
- **G2** "Make clear how well the system can do what it can do" — help the user understand
  how often it may make mistakes.
- **G11** "Make clear why the system did what it did" — **user-initiated, on-demand** access
  to a rationale. Hard in general, but easy for a verbalizing LLM agent.
- **G12** "Remember recent interactions" — memory the user can efficiently reference.
- **G13** "Learn from user behavior" — personalize over time.
- **G14** "Update and adapt cautiously" — limit disruptive changes when adapting.

**G12 + G13 + G14 are the skill's user model, prescribed by an authoritative source**: an
incrementally-updated expertise estimate that changes *conservatively* rather than lurching.
Abrupt verbosity shifts disorient users.

### Miller's four properties → the explanation template (high confidence, 3-0)

[Miller 2019, *Explanation in AI: Insights from the Social Sciences*](https://arxiv.org/abs/1706.07269),
Artificial Intelligence 267:

1. **Contrastive** — people ask why P *instead of* a foil Q. Answer the implicit contrast;
   don't enumerate all causes.
2. **Selected** — people expect one or two relevant causes, not a complete causal account.
3. **Social** — explanation is a knowledge transfer *presented relative to the explainer's
   beliefs about the explainee's beliefs*. (Hypothesis 1, arrived at independently.)
4. **Gricean / epistemic selection** — follow Grice's maxims (quality, quantity, relation,
   manner); **omit causes the explainer believes the explainee already knows.**

**Design implication — the core explanation template**: (a) infer the foil, (b) give 1–2
causes that resolve it, (c) subtract what the tracked expertise implies they already know.
Property 4 is the most directly encodable rule in either research pass.

### Google PAIR: expectation-setting and just-in-time disclosure (high confidence; the
just-in-time claim 2-1)

[PAIR Guidebook v2, Mental Models](https://pair.withgoogle.com/guidebook-v2/chapters/mental-models/):
mismatched mental models cause unmet expectations, frustration, misuse, and abandonment —
often because creators *under-explain how the product works*. Remedy: a five-move onboarding
template (name the product; core benefits; primary limitations; that it changes over time;
how the user can improve it) plus **just-in-time progressive disclosure**: *"People learn
better when short, explicit information appears right when they need it"* — aim to introduce
at the moment it is relevant; avoid a long introductory list.

*Caveat*: PAIR asserts the just-in-time principle as design guidance with **no cited study**
(hence the 2-1 vote), though it converges with the progressive-disclosure and cognitive-load
literature from pass 1.

### Bansal et al. 2024 — the agent-native source (high confidence, 3-0)

["Challenges in Human-Agent Communication"](https://arxiv.org/pdf/2412.10380), Microsoft
Research + Allen Institute for AI, Dec 2024, informed by Clark & Brennan's communication
grounding. Twelve challenges in three groups:

- **Agent → user** (A1–A5): what it can do / what it's about to do / what it's currently
  doing / side effects / whether the goal was achieved.
- **User → agent** (U1–U3): goal / preferences / feedback.
- **Overarching** (X1–X4): verification / consistency / **level of detail** / which past
  context to use.

Two things make this the keystone source:

1. **Written by co-authors of the 2019 guidelines** (Amershi, Horvitz, Weld), it states
   in-house that existing HAI guidelines only **partially transfer** to autonomous tool-using
   agents, and calls for new patterns. The skill cannot just port Amershi/PAIR wholesale.
2. It prescribes **user-model-driven verbosity control** directly:
   - **X3 (level of detail)**: more detail becomes *counterproductive* past a point —
     burdensome instruction, cognitively taxing review, an overconstrained agent. Detail has
     a **cost curve, not monotonic benefit**.
   - An ideal agent **uses memory to skip clarification for familiar scenarios**.
   - **A2 (about-to-do)**: **compress steps the user already expects; surface surprising
     steps saliently before execution** — modeling uncertainty about the user's mental model
     (predicted surprise) to decide when to reach out.

**This is the verbosity engine**: gate detail on predicted user surprise plus memory of prior
interactions.

## C. Folklore screen

### Learning styles: do NOT encode (high confidence, 3-0)

[Pashler, McDaniel, Rohrer & Bjork 2008/2009](https://journals.sagepub.com/doi/full/10.1111/j.1539-6053.2009.01038.x),
*Psychological Science in the Public Interest* — the "meshing hypothesis" (instruction works
best when its format matches the learner's preferred style) has **virtually no evidence** for
the crossover interaction that would validate it. Validating it requires a demanding design
(classify by style, randomly assign method, same test for all, show a crossover) that the
evidence does not clear. The finding has only strengthened since 2009.

**Critical guardrail**: adapt on **expertise / prior knowledge** (supported — pass 1's
expertise reversal effect, Miller's social property, Bansal's memory-driven detail), **never**
on sensory or "learning-style" preference (visual/auditory/kinesthetic). Do not offer or infer
a "learning style" setting. Note the contrast: the crossover interaction that is *absent* for
learning styles is exactly the one that is *present and quantified* for prior knowledge.

### Mayer / CTML: safe to use, with calibrated weight (high confidence, 3-0)

[Noetel et al. 2022, *Multimedia Design for Learning: An Overview of Reviews With
Meta-Meta-Analysis*](https://journals.sagepub.com/doi/abs/10.3102/00346543211052329),
Review of Educational Research 92(3) — 29 systematic reviews, 1,189 studies, 78,177
participants: 11 design principles with significant positive effects on learning, 5 more
improving cognitive-load management.

**Important caveat**: pooled effect sizes are uneven. Temporal/spatial **contiguity g≈0.74
(large)**; **signaling g<0.2 (small)** — signaling's placement among "largest benefits"
reflects abstract framing, not a uniformly large effect.

**Design implication**: encode **contiguity heavily** (keep related code, explanation, and
labels adjacent — never split an explanation from the code it describes), and **signaling
lightly** (cue what matters, but don't build the skill around it).

## Design rules extracted (adding to pass 1's ten)

11. **Classify the turn into a Diátaxis mode** and generate the matching form; never blend
    "why" into "how-to" (A).
12. **Explanation template**: infer the foil → 1–2 causes → subtract known concepts (Miller).
13. **Epistemic selection is the join point**: the tracked expertise model's *only* job at
    generation time is deciding what to omit (Miller property 4 + pass 1 finding C).
14. **Gate verbosity on predicted surprise**: compress expected steps, surface surprising
    ones before execution (Bansal A2).
15. **Detail has a cost curve** — past a point, more detail is actively counterproductive
    (Bansal X3). There is no "safely verbose" default.
16. **Use memory to skip familiar clarifications** (Bansal + G12).
17. **Adapt cautiously** — no lurching verbosity changes (G14).
18. **On-demand rationale**: a collapsible "why I did this" rather than inline justification
    (G11 + pass 1 finding E on separable redundancy).
19. **State capability and reliability up front** (G1, G2, PAIR's five-move template).
20. **Contiguity**: keep explanation adjacent to the code it explains (Mayer, g≈0.74).
21. **Never adapt on learning styles** — expertise only (Pashler).

## Still open

Two commissioned strands produced **zero verified claims** and are being covered by a
targeted follow-up:

- **(D) Coding-agent ecosystem prior art** — Claude Code output styles, the
  learning-output-style plugin, CLAUDE.md/AGENTS.md conventions, Cursor rules and memory-bank
  patterns, aider. The competitive gap analysis is unanswered.
- **(E) Empirical LLM adaptive-explanation evaluations** — SNAPE-PM (Frontiers 2026, n=199)
  failed verification **in both passes** due to DNS timeouts. *The core empirical question —
  does adaptive explanation actually beat a fixed style? — remains unconfirmed.*
- Sub-strands not reached: Gentner's structure-mapping / when analogies mislead; Carroll's
  minimalism; plain-language standards; readability-formula validity limits.

## Caveats

- **Infrastructure fragility**: nearly every direct WebFetch timed out (getaddrinfo ETIMEOUT
  on arxiv.org, dl.acm.org, microsoft.com, sagepub). Most quotes were recovered via search
  index snippets and independent corroboration rather than read from canonical PDFs. Quotes
  are well corroborated but should be spot-checked before publication.
- **Transfer gap**: Diátaxis, Miller, Amershi/HAX and PAIR are documentation and general-HCI
  theory — none tested on coding-agent explanation. The one agent-native source (Bansal) is a
  design-agenda paper, not an outcome evaluation, and itself warns the general guidelines
  only partially transfer.
- Miller 2019 is a single (excellent) survey. PAIR's just-in-time principle cites no study.
