# Skill review — 2026-07-28

The skill has a strong, distinctive thesis and a thoughtful knowledge model, but its
packaging and enforcement contracts are inconsistent enough that it is not yet reliably
installable. The highest-priority work is operational correctness, not more communication
theory.

## Findings

### 1. Bare-skill installation breaks the tool path

`SKILL.md` requires writes through `tools/laconic_record.py`, but `install.sh` only links
`skills/laconic/` into the skills directory. The sibling `tools/` directory does not
accompany it. An agent using the bare skill from an arbitrary working directory therefore
cannot resolve the mandatory command.

Plugin installation works because the injected policy uses `${PLUGIN_ROOT}`. The bare skill
and plugin consequently expose different operational contracts.

**Recommendation:** make the skill self-contained:

```text
skills/laconic/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
│   ├── laconic_record.py
│   ├── laconic_index.py
│   └── laconic_lint.py
└── references/
    └── knowledge-model.md
```

Have the plugin hooks call those same scripts so there is one implementation location.

### 2. “Always pass `--domain`” is not enforced

The skill and documentation call `--domain` mandatory. The CLI accepts its omission and
files the concept under `general`. The Stop hook's remediation command also omits
`--domain`, so the enforcement mechanism teaches a command that violates the policy.

**Recommendation:**

- require `--domain` when creating a concept;
- preserve the existing domain when updating one;
- permit omission only for distillation and forgetting;
- include `--domain` in every example and hook message;
- warn or error on legacy `general` concepts.

### 3. Documentation contradicts implemented decay

The README, `docs/knowledge-model.md`, and `SESSION_STATE.md` say decay is inert. The
implementation now softens stale `familiar` concepts to `exposed`, drops thinly evidenced
stale `exposed` concepts, and preserves `verified` and `unknown`.

**Recommendation:** update every user-facing description and avoid restating implementation
status in several documents. Keep thresholds in one executable source of truth.

### 4. The trigger scope is too broad

The description triggers on “any document or explanation for a person.” This can load the
full 213-line skill for nearly every substantive writing task, even when the always-on hook
has already injected the core policy. It also risks colliding with specialized writing
skills whose format requirements should dominate.

**Recommendation:** let the hook govern ordinary communication and trigger the full skill
for substantial technical writing, explicit editing or compression work, and
knowledge-model inspection.

A narrower description could be:

> Improve or review substantial technical writing by removing redundant explanation,
> separating procedural and explanatory modes, and calibrating terminology to an auditable
> knowledge model. Use for specs, RFCs, design documents, findings, handoffs, or when asked
> to make writing clearer or more concise. Also use to inspect or correct `~/.laconic/`.
> Do not trigger for short conversational replies already governed by the always-on policy.

### 5. `SKILL.md` mixes three responsibilities

The file contains writing guidance, research-derived rationale, and a detailed persistent
model operations manual. An agent tightening an RFC does not need deletion semantics,
dependency repair, promotion mechanics, and distillation internals in context.

**Recommendation:**

- keep the concise writing workflow and routing instructions in `SKILL.md`;
- move model maintenance to `references/knowledge-model.md`;
- encode schema, promotion, deletion, and validation rules in scripts;
- keep the evidence audit in repository documentation, outside normal runtime context.

This should reduce normal skill context by roughly half without removing capability.

### 6. Some behavioral rules are too absolute

Examples include “steps, no rationale,” “rationale, no steps,” “verified: never define or
re-derive,” and “a question about X drops it to at most exposed.” These are useful defaults
but brittle invariants. A how-to may need one sentence explaining a destructive step; a
question about one facet of a concept does not necessarily disprove broad competence in it.
The later “established gaps” mechanism already recognizes this granularity problem.

**Recommendation:**

- keep the requested mode primary and add another only for safety or successful execution;
- do not explain a verified concept unless the task depends on an unestablished facet;
- record a questioned facet as a gap, demoting the whole concept only when the evidence
  reveals concept-wide uncertainty;
- consider smaller concept identifiers or facet-level evidence before expanding the schema.

### 7. Persistent writes need an explicit privacy and consent policy

Recording expertise creates durable files, Git history, absolute project paths, and
potentially an asynchronous push. The skill explains auditability and deletion but does not
clearly disclose those effects or constrain sensitive evidence.

**Recommendation:**

- disclose the stored data and lifecycle;
- prohibit secrets, personal data, and verbatim sensitive material in evidence;
- make synchronization explicitly opt-in;
- default to local-only operation;
- decide and document whether automatic recording itself requires opt-in.

### 8. The Stop hook can manufacture noise and low-quality evidence

After four turns without a write, the hook blocks completion and asks the agent to record
something. Although it forbids invention, that pressure conflicts with “after an exchange
that produced evidence — not every turn.” A substantial session can legitimately reveal no
stable expertise signal.

**Recommendation:**

- never block solely because no concept was recorded;
- use a non-blocking reminder, or block only for malformed state;
- prompt only when the transcript contains a plausible evidence event;
- measure the false-positive nudge rate during evaluation.

### 9. Codex-facing metadata and validation are missing

The skill lacks `agents/openai.yaml`. The repository is packaged primarily as a Claude Code
plugin even though the underlying skill is agent-independent.

**Recommendation:** make the skill the self-contained core and treat Claude hooks as an
adapter. Add generated interface metadata and run the standard skill validator.

### 10. Consequential behavior has no regression suite

The Python files compile, shell syntax checks pass, ShellCheck reports clean, and a basic
temporary-model smoke test succeeds. The smoke test also confirms that requesting
`familiar` on a first observation is capped to `exposed`.

There are no regression tests for:

- promotion and demotion;
- distillation-only updates preserving confidence and timestamps;
- malformed frontmatter recovery;
- dependent deletion and `--force`;
- decay thresholds;
- project relevance and gap ranking;
- gap and index budgets;
- hook JSON envelopes and Stop behavior;
- concurrency and Git failure handling.

For a tool whose promise is auditability, this is the largest engineering-quality gap after
packaging.

## Strengths to preserve

- A clear point of view rather than generic “write clearly” advice.
- Dated, inspectable, user-correctable evidence.
- Promotion slower than demotion.
- Distillation correctly separated from new evidence.
- Established gaps as a correction to coarse knowledge states.
- Explicit injection-size bounds.
- Recoverable deletion with dependency-integrity checks.
- No third-party runtime dependencies.
- Separate subagent handling that forbids second-hand model writes.
- Clean basic Python, shell syntax, and ShellCheck results.

## Improvement plan

### Phase 1 — Restore contract correctness

1. Make the skill self-contained or resolve tools through a guaranteed installation root.
2. Enforce the documented domain rule in the CLI.
3. Fix the Stop hook command.
4. Update stale decay documentation.
5. Add `agents/openai.yaml`.
6. Run formal skill validation.

**Acceptance criteria:**

- every command copied from `SKILL.md` works from an unrelated directory;
- bare-skill and plugin installations use the same implementation;
- documentation, hooks, and CLI agree on required arguments and decay.

### Phase 2 — Add mechanical confidence

Build an isolated test suite with temporary `LACONIC_HOME` directories and pushes disabled.
Prioritize recording and transitions, distillation invariants, dependency-safe deletion,
decay boundaries at 90 and 180 days, hook envelopes, concurrency, and budget checks.

Add one local verification command covering tests, ShellCheck, Python compilation, and skill
validation.

### Phase 3 — Reduce runtime context

1. Cut `SKILL.md` to the core writing workflow.
2. Move model maintenance into a directly linked reference.
3. Remove research statistics from operational instructions unless they change a decision.
4. Narrow the trigger description.
5. Remove duplication between the injected policy and skill body.

Target approximately 80–120 lines for `SKILL.md`, with model details loaded only for
model-related work.

### Phase 4 — Refine inference safety

1. Prefer gap recording over whole-concept demotion where appropriate.
2. Define evidence-quality examples and counterexamples.
3. Distinguish direct observation, explicit confirmation, and weak inference mechanically.
4. Prevent sensitive content from entering evidence.
5. Make synchronization opt-in and disclose stored project metadata.

### Phase 5 — Evaluate the product claim

Compare a baseline agent, the lightweight injected policy, the full skill, and the policy
with a populated knowledge model on a corpus of realistic prompts.

Measure:

- answer-first behavior;
- redundant definitions;
- omitted necessary context;
- mode mixing;
- unsupported knowledge assumptions;
- output length;
- user correction rate.

The decisive question is not merely whether the output is shorter, but whether the
knowledge model improves calibration beyond the lightweight policy alone.

## Overall assessment

Laconic has an excellent product thesis, promising model design, and good implementation
instincts. It remains an experimental prototype with several contract mismatches. Packaging,
enforcement consistency, documentation drift, and tests should be fixed before expanding
the theory or adding features.

## Follow-up — 2026-07-31

The initial engineering gaps are substantially closed: stable command wrappers now make
plugin and bare-skill operation agree; domains are enforced; decay documentation is checked
against the implementation; model operations use progressive disclosure; and the repository
has a comprehensive test and verification gate.

Two remaining policy defects were closed after the broader harness argument was reviewed:

- A clean Stop event no longer blocks merely because a long session recorded no concept.
  Absence of a write is not evidence that evidence was missed, and pressuring the agent there
  selects for weak or invented inferences.
- Behavioral telemetry is now explicit opt-in through `LACONIC_TELEMETRY=1`. Keeping the
  log local and content-free reduces its sensitivity; it does not turn installation of a
  writing policy into consent to observation.
- Model synchronization now requires both a user-configured `origin` and
  `LACONIC_PUSH=1`. Local Git history provides auditability without silently authorizing
  network transfer, and the documentation discloses the absolute project paths stored for
  relevance ranking.

The open research question is now the model's unit of retrieval. Measurement found that only
five of 101 concept-touching historical turns were knowledge-state-discriminating. An early
classification suggested that 59% of recorded observations describe world mapping,
justification, or modification rather than mere term use, but that figure is **provisional**:
the legacy batch cache did not bind verdicts to the exact concept and observation inputs.
The replacement classifier stores an input manifest, hashes every item, and writes structured
verdicts; no historical verdict is reused unless its hash matches. Do not redesign the schema
until the hash-bound rerun and theory-indexed counterfactual experiment show higher
applicability without more false assumptions.

### Hardening follow-up — 2026-07-31

A hostile review of the local correction console and recorder found a second class of risks:
the UI was loopback-only but did not defend against browser cross-origin requests or DNS
rebinding; direct metadata edits bypassed the model lock and dependency-safe deletion; and
the recorder accepted frontmatter-shaped domain/dependency values. Those are integrity
failures, not cosmetic concerns, because a poisoned model is injected into later sessions.

The implementation now:

- validates `Host`, `Origin`, JSON content type, and request size, and sends restrictive
  browser security headers;
- validates concept ids, domains, one-line summaries, and secret-shaped summary content;
- routes deletion through the recorder and holds the shared model lock across metadata
  read-modify-write operations;
- rejects invalid, dangling, self-referential, duplicate, and cycle-creating dependency
  updates at the recorder boundary;
- resolves `LACONIC_HOME` dynamically, preventing the console from editing one model while
  regenerating the index from another.

The remaining product-level blocker is empirical, not mechanical. The local validation gate
can establish packaging, integrity, privacy defaults, and regression safety. The hash-bound
retrieval experiment has now established that demonstrated theory is materially applicable
more often than term-indexed state, but it cannot prove that retrieving it improves answers
enough to justify its context and maintenance cost. That claim is now gated on the
response-level A/B specified by the result in `design/06-measurement.md`.

### Completion audit — 2026-07-31

Passing tests were audited against the product contract rather than treated as proof by
themselves. This exposed and closed three additional gaps:

| Contract area | Authoritative evidence | Status |
|---|---|---|
| Durable, auditable model writes | atomic same-filesystem replacement with file and directory flush; failure-injection test preserves the prior file | mechanically established |
| Malformed user data | recorder refuses to overwrite it; explicit, reasoned `--forget` remains available | mechanically established |
| Bare-skill fallback | isolated-home install test covers first install, idempotence, executable wrapper, real record, and collision preservation | mechanically established |
| Evidence-local inference | prerequisite and domain-wide propagation removed from current policy; graph edges guide attention but cannot manufacture state | contract aligned |
| Plugin manifests and hook envelopes | CLI manifest validation plus hook regression tests | mechanically established when the Claude CLI is available |
| Theory retrieval applicability | preregistered, hash-bound relevance/counterfactual experiment | established at projected 6.83% (95% interval 4.75%–9.46%) |
| Knowledge-model benefit over the policy alone | blinded 24-pair response A/B | **inconclusive**: 8 theory wins, 10 policy wins, 6 ties; 95% interval 24.6%–66.3% |

Atomic replacement matters even though writers already share a lock: the SessionStart hook,
console, and human readers do not take that lock. In-place truncation could therefore inject
or display a half-written model after a crash. Temporary replacement files use a stable
gitignored prefix so even a process killed before cleanup cannot cause persistence debris to
be committed on the next write.

The inference correction resolves a deeper inconsistency. Earlier design text transposed
EDGE into automatic prerequisite promotion and domain-wide demotion, while the shipped
system promised that every non-unknown state was backed by an observation. A graph relation
is not an observation of this reader, and one question is not evidence about every concept
sharing a domain. The safer rule is now uniform: state changes are concept-local and require
direct evidence; dependency edges only help locate background worth checking or explaining.

### Runtime-surface follow-up — 2026-07-31

Executing SessionStart with `LACONIC_HOME` genuinely unset found an unbound-variable crash:
the hook's tests had always supplied the variable, masking the normal fresh-install path.
Home resolution now defaults to `~/.laconic`, and a regression test runs that exact
environment and validates the JSON envelope and command path.

The same runtime capture invalidated the old ~430-token cost estimate. Before compression,
the empty-model context was 3,107 characters (~777 rough tokens). Duplicated maintenance and
analogy guidance was moved out of the universal layer and left in the full skill. The measured
surface is now 2,046 characters empty and 3,023 with the current 76-concept model. Executable
budgets cap those dimensions at 2,500 characters empty and 4,200 characters at the index's
worst allowed size; contract tests also assert that compression retained the evidence,
privacy, facet-gap, evidence-kind, and push-consent rules.

Python is now stated as a runtime requirement rather than hidden behind the phrase "no
third-party dependencies." If it is absent, SessionStart emits a valid conservative JSON
envelope using shell builtins only: it says the model is unavailable and defaults toward
explanation. Unknown event names are normalized before that non-Python JSON path, preventing
an argument from corrupting the envelope.
