# Measurement — 2026-07-28

Answering the review's Phase 5 question: does the knowledge model improve calibration beyond
the injected policy alone? The eval was designed, the corpus was mined, and the corpus itself
produced the first substantive result.

## The finding

**5 of 101 concept-touching turns are knowledge-state-discriminating.**

From 1455 transcripts: 32,432 entries of `type: user`, of which 29,699 are tool results and
2,733 carry real text; ~1,025 fall in a prompt-shaped length range. Of those, 101 mention a
concept the model holds. A classifier asking

> would the ideal answer be materially different if the reader were expert in this concept,
> rather than meeting it for the first time?

keeps 5. Roughly **0.5% of real turns** are ones the knowledge model can change.

## Why this is a result and not an obstacle

Laconic has two halves with very different economics.

The **injected policy** — lead with the outcome, keep modes separate, say what a change does
not handle — applies to every turn and costs what it costs.

The **knowledge model** — the stateful, auditable, synced half that this repo is mostly made
of — applies to about one turn in twenty *of those that even mention a concept*, while
costing roughly 512 tokens with an empty model and 756 with the current live model (character
count divided by four, a deliberately rough proxy) in every session regardless of relevance.
Nothing about that ratio was known before; it was assumed favourable.

This does not show the model is worthless. It shows its theatre of operation is narrow, and
that the case for it has to be made on the value of those rare turns rather than on breadth.

## What the drops look like

The classifier was audited against the prompts rather than trusted. Dropped turns are task
orders ("clean up the git history"), structured extraction ("read this file and produce a
table"), lookups ("what is the github repo for X"), and editing feedback. None of these have
an answer that depends on what the reader knows.

One drop is subtly right and sharpens the claim: *"I've never used OCaml functors and don't
know what they are"* was dropped because **the prompt declares novice state**. Every arm
explains, so the model contributes nothing. The model's value exists only where the user does
*not* self-declare — which is a narrower target than "turns about concepts".

## What survived

| state | prompt |
|---|---|
| verified | a debugging question whose answer turns on knowing the plugin mechanism |
| familiar | a design question that hinges on knowing the expertise-reversal effect |
| exposed | recall plus provenance-calculus inspiration for a language design |
| exposed | whether the dev kit should adopt a laconic approach |
| unknown | "I work with Rust a lot but I've genuinely never understood what a `Pin<>` is" |

The last one is the observation that created the `rust-pin` concept, which is a good sign for
the mining: the corpus rediscovered the evidence the model was built from.

## Why the arms were not run

5 mined prompts plus 18 authored probes is 78% authored — which is what mining was chosen to
avoid, because a benchmark written by whoever built the system measures its author's
imagination. Running two arms over 23 prompts, at 75-250s per call, would produce a number
rather than evidence.

## What would actually settle it

The question has changed shape. "Does the model beat the policy?" is now downstream of "is
the model applicable often enough to pay for itself?" Three routes, in increasing cost:

1. **Cost-side first.** The applicable rate is measured; the per-session cost is measured
   (~512 rough tokens before model growth; ~756 on the current model). The remaining unknown
   is the *size* of the benefit on a discriminating
   turn. A handful of prompts is enough to establish whether the effect is large or marginal,
   and a large effect on 5% of turns is a different product than a marginal one.
2. **Deliberately author the rare case.** Accept an authored benchmark, but state plainly
   that it measures the model where it is designed to apply rather than where it typically
   lands. Honest if labelled; misleading if not.
3. **Instrument instead of sampling.** Log, in real sessions, how often an answer touches a
   concept whose state is `verified` or `unknown`. Slower, but it measures the live
   distribution rather than a historical one, and it needs no corpus at all.

Route 3 is the only one that answers the applicability question without a benchmark, and the
applicability question now dominates.

## Instrumentation (route 3, live)

With explicit opt-in, `tools/laconic_observe.py` runs from the Stop hook and appends one
line per turn to `~/.laconic/telemetry.jsonl`. `tools/laconic_stats.py` reports it.
Enable it by exporting `LACONIC_TELEMETRY=1` in the environment that launches Claude Code.

What it counts, and why it is not "turns mentioning a concept". With an empty model the
policy says *assume nothing about what the user knows*, whose safe default is to explain. So
the model only **changes** the writing where it says do *not* explain: `verified` (use
freely) and `familiar` (a short gloss on first use). A turn touching `exposed` or `unknown`
produces the same behaviour with or without the model, and is recorded but not counted. A
concept carrying a recorded gap is also not counted — the gap reinstates the explanation.

It also counts the failure the model exists to prevent: an answer that *defined* a
`verified` or `familiar` concept anyway. Nonzero means the model is being consulted and
ignored, which is a different problem from being inapplicable, and the two would otherwise
look identical in the headline rate.

Constraints it is built to: no prompt or response text ever reaches the log (concept ids,
states, booleans, lengths only); the log is gitignored so it never joins the synced model;
It is disabled by default: installing a communication policy is not consent to behavioral
measurement, even when the log is local and content-free. When enabled, it is backgrounded
and silenced so it cannot add latency or emit anything the harness could read as hook output;
and it runs before every early exit in the hook, so the sample is all turns rather than only
malformed-model paths.

13 tests, mutation-checked: counting `exposed` as discriminating, letting a gap through,
reading only the final assistant message, bypassing explicit opt-in, and leaking response
text each turn the suite red.

Cost measured at ~30ms per turn against a 1362-line transcript.

## Evidence kinds (2026-07-29)

Naur's *Programming as Theory Building* (1985) predicts the ~0.5% result. A theory in his
sense is the capacity to (1) map program to world in both directions, (2) justify why each
part is what it is, and (3) respond constructively to a demand for modification. None of
those are held *about a term*, so a model indexed on terms will find that terms are rarely
the operative thing.

`--kind` records which of these an observation is: `world`, `justification`, `modification`
for Naur's three, `term` for the vocabulary evidence laconic collected before.

The hash-bound rerun classified all 93 historical lines and found **54.8% theory-evidence**:

| kind | n | share |
|---|---|---|
| `term` | 42 | 45.2% |
| `modification` | 24 | 25.8% |
| `justification` | 14 | 15.1% |
| `world` | 13 | 14.0% |

They were classified by a judge against an empty model rather than by hand, since most lines
were written by the agent that would otherwise be grading them. The first harness cached
only positional batch outputs, however: it did not retain a hash-bound input manifest.
After the model changes, those outputs cannot be proved to refer to the same observations in
the same order. The old 59% result remains provisional evidence, not an auditable baseline.
`eval/classify_evidence.py` now keys every verdict to the hash of concept id plus exact
observation, retains the input manifest, and writes structured verdicts. Legacy positional
caches are rejected rather than silently reused. The rerun produced 93 unique matching keys
and complete valid verdicts; it was report-only and did not rewrite the learner model.

The keyed rerun reproduces the qualitative result. The recording practice was already
collecting theory evidence while the schema collapsed every observation into a state attached
to a term. This establishes the composition of the evidence store, not that retrieving it
improves an answer.

That reframes the applicability problem. The model is not short of theory-evidence; it is
indexed in a way that cannot use it. A concept-and-state model asks "does he know X"; the
evidence it holds actually answers "does he hold the theory of this system", which is a
different question with a different index.

What this does *not* yet establish: whether an index on theory rather than terms would raise
the applicability rate. The evidence kinds make that measurable — they do not measure it.
Nor does the promotion ladder yet weight kinds; a `modification` observation currently counts
exactly as much as someone repeating a word, which on Naur's argument is wrong.

## Theory-indexed retrieval experiment (registered 2026-07-31)

`eval/theory_relevance.py` tests that missing link without changing the production schema.
It groups marked evidence, plus only hash-bound cached verdicts from the classifier rerun, by
the project in which it was observed. It then mines later prompt-shaped turns from those
projects without requiring a concept-name match. The first positional cache is deliberately
ineligible.

A strict counterfactual judge sees the real prompt and at most eight recorded observations:

> If the same reader had not demonstrated this understanding, but the request and available
> project artifacts were identical, would the ideal answer need materially different
> explanation, rationale, warnings, or checks?

A yes verdict must cite the numbered observation it relies on. Project co-location, general
expertise, vocabulary, and topical resemblance are explicitly insufficient. The corpus,
profiles, raw rulings, and parsed verdicts stay gitignored; classification is opt-in because
it sends real prompt and evidence text through the configured Claude CLI.

The comparison denominator is every distinct prompt-shaped turn in the transcript corpus,
not only prompts from theory-bearing projects. The report projects the judged rate back onto
that denominator and gives a 95% Wilson interval.

The decision rule is registered before running the classifier:

- If the projected interval's **upper bound is at or below the concept model's observed
  ~0.5% applicability**, theory indexing is falsified as the remedy; do not redesign.
- If its **lower bound exceeds ~0.5%**, theory indexing has broadened applicability enough
  to justify a response-level A/B test. It still does not justify a schema migration.
- Otherwise, the result is inconclusive; increase the real sample rather than authoring
  favourable probes.

Even a positive result only advances to the next gate: measure whether the additional
context improves calibration enough to pay for its retrieval and injection cost. Production
schema work begins only after that comparison.

## Theory-indexed retrieval result (run 2026-07-31)

The first dry run exposed temporal leakage: it treated every prompt in a theory-bearing
project as eligible even when the observation was recorded later. The design had specified
*later* prompts, but the miner did not enforce it. Evidence is dated only to the day, so the
corrected miner admits an observation only when its date is strictly earlier than the prompt's
timestamp; same-day ordering is unknowable and is excluded. This reduced the eligible corpus
from 679 to 224 of 787 distinct prompt-shaped turns before any counterfactual verdicts were
seen.

The deterministic hash-ordered sample contained 100 of those 224 prompts. The strict judge
returned complete rulings for all 100:

| measure | result |
|---|---:|
| theory-discriminating within the eligible sample | 24/100 (24.0%) |
| 95% Wilson interval within eligible projects | 16.7%–33.2% |
| eligible coverage of all prompt-shaped turns | 224/787 (28.5%) |
| projected share of all prompt-shaped turns | **6.83%** |
| projected 95% interval | **4.75%–9.46%** |

Every positive ruling cited at least one in-range observation; all 100 structured inputs match
the regenerated corpus; there are no unruled or duplicate prompts. The 20 raw response batches
are keyed by a SHA-256 digest of the exact judge payload and retain input manifests. The
initial completed run used positional raw names, but promotion to the keyed cache was allowed
only because its structured verdict file embedded the exact current prompt/profile inputs and
every raw ruling reproduced the corresponding structured ruling. A cached replay then
reproduced the same 24/100 result without an external call.

### Registered decision

The projected interval's lower bound, 4.75%, exceeds the concept model's ~0.5% applicability
baseline by a wide margin. Under the preregistered rule, theory indexing is therefore **not
falsified** and advances to a response-level A/B test.

This is not evidence to migrate the production schema. One strict model judge supplied the
rulings, hash-order sampling is deterministic rather than a probability sample, and the
projection assumes the 100 judged eligible prompts represent all 224 eligible prompts. Most
importantly, applicability is not benefit: the next experiment must compare actual answers
with and without the retrieved theory and measure calibration gains against context cost.

## Response-level A/B protocol (registered before generation, 2026-07-31)

The next test isolates Laconic's actual intervention—how an answer is communicated—from
agentic task execution. For each of the 24 theory-discriminating prompts, recover the original
assistant answer from the same transcript. Both arms receive the real prompt and that same
project-grounded answer as a draft to rewrite. They use the exact compact policy extracted
from the SessionStart hook; the treatment arm additionally receives only the prior,
temporally valid theory observations already used by the relevance judge. Neither arm gets
tools or repository access. This holds task facts constant, prevents eval calls from editing
projects, and makes the difference attributable to reader calibration rather than different
file exploration.

Outputs are paired by prompt and blinded as A/B with hash-determined order. A strict judge
sees the prompt, demonstrated theory, and both rewrites, but not arm identity. It chooses
`A`, `B`, or `tie` on:

1. correctness and preservation of the draft's material content;
2. calibration to what the evidence does and does not establish;
3. absence of redundant explanation and unsupported reader assumptions;
4. usefulness and directness for the request.

The judge must separately flag material-content loss and unsupported assumptions. A theory
win with either flag is invalid, not a win. Every raw generation and ruling is keyed by the
SHA-256 digest of its exact payload and retains an input manifest. Failed or partial calls
are never cached.

### Decision rule

The primary statistic is the treatment win probability among valid decisive pairs, with a
95% Wilson interval; ties are reported separately. This 24-prompt run is a directional gate:

- If the interval's **lower bound exceeds 0.5**, theory retrieval advances to an independent
  replication and implementation design.
- If the interval's **upper bound is at or below 0.5**, it is falsified as a communication
  improvement; do not migrate the schema.
- Otherwise the result is inconclusive. Do not tune the prompt on these examples; obtain a
  larger later-prompt sample or independent human rulings.

Regardless of preference, any treatment increase in unsupported assumptions blocks
advancement. Context cost is reported per treatment call and projected across the observed
6.83% applicability rate; retrieval must be conditional, never a larger universal injection.

## Response-level A/B result (run 2026-08-01)

All 24 eligible pairs were generated and ruled. The arm order was deterministically balanced
12/12 before generation, all 48 generation payloads and 12 two-pair judge payloads have
hash-derived filenames and exact manifests, and every output/judgment key matches. No call
failed or required a retry.

| result | count |
|---|---:|
| theory wins | 8 |
| policy wins | 10 |
| ties | 6 |
| theory win rate among 18 decisive pairs | 44.4% |
| 95% Wilson interval | 24.6%–66.3% |
| unsupported assumptions, theory / policy | 0 / 0 |
| material-content loss, theory / policy | 1 / 2 |

The treatment answers were only slightly shorter: median 1,941 versus 1,987 characters, with
a mean treatment-minus-policy difference of −39 characters. The mean conditional theory
context was 1,107 characters; at the observed 6.83% applicability rate, conditional retrieval
would amortize to roughly 76 characters per ordinary turn. This is a projection, not a
production measurement.

### Registered decision

**Inconclusive.** The interval crosses 0.5, so the run neither advances theory retrieval nor
falsifies it. The treatment did not increase unsupported assumptions, but safety alone is not
benefit. Do not tune the retrieval prompt on these 24 examples and do not migrate the schema.

Two diagnostics limit interpretation further:

- The blind judge preferred position B 12 times and A 6 times among decisive pairs, despite
  balanced arm placement. Balanced placement protects the arm aggregate from systematic
  position assignment, but the imbalance increases uncertainty in this small sample.
- The common project-grounded drafts came from historical sessions in which Laconic may
  already have been active. Holding the draft fixed isolates rewriting, but it can also anchor
  both arms to an answer that already omitted established background, biasing the comparison
  toward no difference. No output pairs were textually identical, so the arms did perform
  distinct rewrites, but that does not remove the anchor.

The next valid evidence is independent blind judgment of these frozen pairs or a larger set
of later prompts with neutral project-grounded drafts created before either communication
arm. A label-swapped rerun with the same judge can diagnose position sensitivity, but it is
not an independent replication and cannot by itself advance the product claim.

### Position-sensitivity diagnostic (registered after the primary result)

Rejudge the frozen outputs with A/B labels reversed, using the unchanged rubric. This is a
diagnostic prompted by the observed 12-to-6 B-position preference, not a new primary test.
Report how many pairs retain the same arm winner, flip arm winner, or involve a tie across
orders. The primary 8/10/6 result and its inconclusive decision remain fixed regardless of
the diagnostic outcome; a same-judge cross-over cannot substitute for independent judgment.

The harness implements this as `theory_ab.py --swap-judge`, with a separate hash-bound cache
and output file. It requires 12 additional external calls. A run attempted on 2026-08-01
stopped before its first ruling because the configured Claude account had reached its weekly
limit (reported reset: 2026-08-03 08:00 Europe/Paris). The failure was not cached; only the
hash-bound input manifest exists, so a later run starts with no partial diagnostic result.

For genuinely independent assessment, `human_review.py --export` creates a self-contained,
gitignored `eval/runs/theory-ab/human-review.html`. It exposes only blinded A/B labels, the
request, demonstrated understanding, and frozen answers; it embeds no arm mapping and makes
no network requests. The page exports complete JSONL judgments, which
`human_review.py --import-results <file>` maps back to arms and scores under the same
guardrails. This avoids another model-as-judge pass and preserves the frozen evaluation set.
