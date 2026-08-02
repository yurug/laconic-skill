# What the evidence supports, and what it does not

Laconic's positioning is derived from the literature rather than from intuition, and the
audit that reshaped it is in the `research/` directory. This page is the summary.

## The claim that did not survive

Adaptive explanation does not reliably improve comprehension. Across fifteen controlled
studies, adaptivity moved *satisfaction* and rarely moved *measured understanding*; adaptive
systems typically tied with simply using the best fixed style, and roughly 29% of naive
personalisation attempts did worse than generic responses.

So laconic does not sell the knowledge model as a comprehension booster. That would
misrepresent what is known.

## The claim that did survive

Mismatch has a measured cost in both directions. Heavy scaffolding harms people who already
know the material (d = -0.428, the expertise-reversal effect), and too little scaffolding
harms those who do not (d = 0.505). Avoiding both is a narrower goal than "explains better",
and it is one the evidence actually supports.

What laconic therefore aims at: less noise, fewer unverified assumptions, verbosity that
fits the reader, and a record of what has been established that the reader can inspect and
correct.

## Three deliberate refusals

- **No learning styles.** The meshing hypothesis has virtually no empirical support.
  Adaptation is on expertise only.
- **No misconception library.** The model records uncertainty, never diagnosed errors: the
  claim that bug libraries improve remediation did not survive verification.
- **No optimising for "was that helpful?"** An agent tuned to stated preference produced
  significantly more inappropriate compliance. Preference is not the target.

## Where the reasoning lives

| | |
|---|---|
| [`research/01`](../research/01-state-of-the-art.md) | Cognitive load, expertise reversal, overlay and open learner models |
| [`research/02`](../research/02-communication-frameworks.md) | Diátaxis, human-AI interaction guidelines, Miller's explanation properties |
| [`research/03`](../research/03-analogy-and-writing.md) | Why analogy caveats fail; Carroll's minimalism; why readability scores mislead |
| [`research/04`](../research/04-adaptive-explanation-evidence.md) | The evidence audit that reshaped the positioning |
| [`research/05`](../research/05-ecosystem-prior-art.md) | What already exists, and the gap this fills |
| [`design/`](../design/) | Scope, specification, resolved questions, review notes |

Claims that failed adversarial verification are recorded as failed, including the convenient
ones. Miller's "7±2" is not used anywhere in the design; the modern estimate is about four
chunks.
