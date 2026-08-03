# The knowledge model

Technical reference for the state laconic keeps about you. Everything lives under
`~/.laconic/`, in plain markdown, under git.

## One file per concept

```markdown
---
id: tezos-finality
type: concept
domain: consensus
projects: [/home/user/work/protocol]
state: verified          # verified | familiar | exposed | unknown
confidence: 0.9
evidence:
  - 2026-07-20: [justification] derived the threshold from the failure model
depends-on: [consensus-tenderbake]
last-updated: 2026-07-20
---

Tezos finality.

## Established capabilities
- [justification] Can justify the finality threshold from the failure model (evidence: 2026-07-20) [scope: project]
```

`~/.laconic/INDEX.md` is regenerated from the concept files and is what gets injected into a
session; it groups concepts by domain so the policy can be applied without reading every
file.

## Four states, not a boolean

Only *practiced* knowledge is genuinely free to assume: having seen a term once is not the
same as having a schema for it.

| State | What it means | How the agent writes |
|---|---|---|
| `verified` | Used productively where being wrong would have shown | Used freely, never defined |
| `familiar` | Recognised, not yet demonstrated under load | A short gloss on first use |
| `exposed` | Encountered in this project or a past session | One clause, or a link, not both |
| `unknown` | No evidence either way | Explain, and prefer explaining too much |

## Promotion is slow; demotion follows the scope of the evidence

Reaching `verified` takes productive use in a context where getting it wrong would have been
visible. A question about one facet records that facet under `What has not been established`
and leaves the concept state alone. Demote only when the question shows uncertainty about
the concept's central mechanism. Promotion remains deliberately slower than demotion:
under-explaining is the more expensive mistake, but whole-concept demotion for a narrow
question creates a different mismatch.

## Recording evidence

Never hand-write these files; they have a schema, and the tool enforces it.

```bash
~/.laconic/bin/laconic-record <id> --state <unknown|exposed|familiar|verified> \
    --domain <subject> --evidence "what you saw"
```

`--domain` is required when creating a concept so the index can group it; later updates
preserve the recorded domain. Every state above `unknown` must cite a dated observation.

Evidence can be marked `term`, `world`, `justification`, or `modification`. The last
three record Peter Naur's criteria for possessing the theory of a system; they are retained
separately because repeating vocabulary is weaker evidence than mapping a design to the
world, explaining why it exists, or modifying it coherently.

Evidence also records provenance. `direct` is the backward-compatible default;
`confirmation` means the user explicitly confirmed the claim; `inference` marks a useful
but indirect signal. Inference is audit-only: it cannot change state or confidence, count
toward `verified`, become a capability, or appear as a capability candidate. Use
`--basis confirmation` or `--basis inference`; direct evidence carries no extra marker.
Inference may omit `--state`, preserving the current value or using `unknown` on creation.

A strong observation can establish a reusable capability in the same write:

```bash
~/.laconic/bin/laconic-record tezos-finality --state familiar --domain consensus \
  --kind justification --evidence "derived the threshold from the failure model" \
  --capability "Can justify the finality threshold from the failure model" \
  --capability-condition "the stated fault bounds still apply"
```

Strong evidence recorded without a capability remains a review candidate. The agent reviews
these opportunistically and silently; the user is not responsible for an inbox. For manual
diagnosis, `~/.laconic/bin/laconic-candidates` lists candidates relevant to the current
project. The agent can then distil one without fabricating or duplicating an observation:

```bash
~/.laconic/bin/laconic-record tezos-finality --capability-from 2 \
  --capability "Can justify the finality threshold from the failure model"
```

The evidence number is one-based. The recorder derives the capability's kind and date from
that exact line and leaves state, confidence, last-update time, and the evidence log intact.
The lint verifies that the stored source index remains in range, matches that kind and date,
and does not point to inferred evidence.

Capabilities are narrower than concept states. Each records what the user demonstrated, its
evidence kind, the date of matching evidence, a `project`, `domain`, or `general` scope, and
an optional validity condition. Scope defaults to `project`; wider transfer must be directly
demonstrated. Relevant capabilities are injected so the agent can omit exactly what was
established without assuming mastery of the entire concept.

Capabilities may have stable kebab-case ids and qualified relations such as
`consensus/can-justify-threshold`. `requires` gates applicability, `supersedes` replaces an
older active claim, and `contradicts` exposes an incompatibility without choosing a winner.
The lint rejects dangling references, self-relations, duplicate ids, and prerequisite cycles.

Temporary capabilities can carry `valid-until`; the date is inclusive. Obsolete or disproved
capabilities are marked with `--retract-capability <id> --reason "why"`, retained for audit,
and excluded from injection. In both cases, capabilities that require the inactive claim are
also excluded. A later matching strong observation can reactivate the same id.

## Transcript bootstrap

Bootstrap is a review workflow, not an automatic model import. First inspect the scope
without reading transcript content:

```bash
~/.laconic/bin/laconic-bootstrap --project ~/work/service --since 2026-01-01
```

The command reports only candidate file count and bytes. To create a private local bundle,
repeat with explicit consent and an output path:

```bash
~/.laconic/bin/laconic-bootstrap --project ~/work/service --since 2026-01-01 \
  --consent-to-read --out /private/path/laconic-review.json
```

Repeat `--project` to produce one review across several project roots. Exact duplicate turns
are collapsed into one observation while their opaque source aliases remain recorded.

The exporter keeps only human user turns in the selected projects and period, caps their
length and total count, removes high-signal credential shapes, and assigns each an opaque,
stable source hash. It quarantines obvious third-party material, pasted agent output, and
evaluation instructions: those turns remain auditable but cannot support a proposal.
It never writes the knowledge model and refuses to overwrite a prior review.

The default `--privacy local` bundle still contains ordinary personal and work data. Before
disclosure, obtain separate consent and create a new bundle with `--privacy external
--consent-to-disclose`; this additionally masks common person-name, email, phone, URL,
IP-address, and home-path shapes. This is risk reduction, not anonymization. Transcript text is untrusted
evidence data, never agent instructions. An agent may turn eligible material into proposed concepts, evidence,
capabilities, gaps, or corrections, but the user must review those proposals before they are
applied through `laconic-record`.

The bundle embeds the proposal contract an agent must follow. Validate and render its output
without applying anything:

```bash
~/.laconic/bin/laconic-review --bundle laconic-review.json \
  --proposals agent-proposals.json --out proposed-model.md \
  --decisions-template decisions.json
```

The validator binds proposals to the bundle's `review_id` and source hashes, requires a
one-line justification that the observation is attributable to the user, rejects quarantined
and already-applied sources, and flags evidence similar to an existing observation. It also
rejects unknown fields and secret-shaped evidence, prevents inference-driven state or
capability claims, and allows `verified` only for explicit confirmation. The Markdown output contains unchecked
items, source previews, stable proposal ids, and exact commands for inspection—not execution.
For a larger review, open the decision-only local interface instead:

```bash
~/.laconic/bin/laconic-review-web --bundle laconic-review.json \
  --proposals agent-proposals.json --decisions decisions.json
```

It compares proposals with existing concepts, surfaces duplicate warnings, filters pending
and decided items, supports keyboard decisions, and persists after every action. It cannot
modify or apply the model.
Set every generated decision to `accept` or `reject`, then type the reviewed id explicitly
to apply the accepted subset:

```bash
~/.laconic/bin/laconic-apply-review --bundle laconic-review.json \
  --proposals agent-proposals.json --decisions decisions.json \
  --confirm-review-id <review-id>
```

Application first replays every accepted proposal against an isolated copy and lints the
result. It then locks the real model, aborts if it changed during preflight, publishes the
accepted concept files, records an anti-replay marker, regenerates the index, and creates one
model commit. Rejected proposals never reach the model; incomplete decisions are refused.

## Stored data and synchronization

Each concept stores its id, domain, state, confidence, dated evidence, dependencies,
last-update date, optional prose distillations, and the **absolute project paths** where
observations occurred. Project paths let the injected index keep the current project's
concepts salient. When recorded projects nest, the most-specific path wins, so a broad
workspace such as `/home/yann` does not pollute a nested repository.

The model has four navigation levels:

1. the always-injected root router, with durable states, domain routes, and critical gaps;
2. the complete leaf for the active project;
3. generated domain indexes for cross-project work;
4. concept files for evidence and detailed boundaries.

Generated routes live under `~/.laconic/indexes/`: `ROOT.md`, `domains/<domain>.md`, and
opaque project leaves named by a stable path hash. They are ignored local materializations,
rebuilt automatically, and never replace `concepts/` as the source of truth. The traditional
`INDEX.md` remains the complete human-readable overview.

The model is local by default. Every change is committed under `~/.laconic/` for inspection
and recovery, but Laconic never creates a remote. Background pushes require two explicit
conditions: an `origin` configured by the user and `LACONIC_PUSH=1` in the environment
that launches Claude Code. Remove the remote or unset the flag to keep subsequent commits
local. Evidence must never contain credentials, secrets, or verbatim confidential material
in either mode.

## Format compatibility

The current format is the `0.x` format: frontmatter plus optional markdown sections, with no
numeric schema field. Readers deliberately ignore unknown frontmatter keys and prose sections,
so additive changes remain backward compatible. They treat a missing or invalid knowledge
state conservatively as `unknown`.

Within the `0.x` line, releases must continue to read concept files written by earlier `0.x`
releases. A change that removes, renames, or reinterprets stored data requires all three of:

1. a migration command that preserves the original Git history;
2. a release note identifying the first incompatible version; and
3. a format-version field so readers can refuse data they cannot interpret safely.

Until those exist, destructive format changes are prohibited. If an upgrade produces an
unexpected lint error, stop writing, preserve `~/.laconic/.git`, and report the incompatibility
rather than editing concept files by hand.

## Checking the model

```bash
./check.sh                        # everything: tests, syntax, doc consistency, model lint
~/.laconic/bin/laconic-lint        # schema, evidence, secrets, graph, staleness, budget
~/.laconic/bin/laconic-console     # local web console at http://127.0.0.1:7642/
```

The lint errors when a state above `unknown` carries no dated evidence, when `depends-on`
points at a concept that does not exist, or when ids collide. It warns when a file has gone
stale, when a concept has accumulated evidence but no distillation, and when the hierarchical
startup view has grown past its budget — measured as the worst root-plus-project combination.

## Decay

Silence changes what the injection claims, tiered by state because the tiers are not equally
durable:

| State | After silence |
|---|---|
| `verified` | never decays — two instances of productive use, expensive to re-establish |
| `familiar` | softens to `exposed` at `FAMILIAR_DECAY_DAYS` (180, matching the lint's staleness warning) |
| `exposed`, one observation | leaves the injection at `EXPOSED_DROP_DAYS` (90) — one sighting months ago is close to no evidence |
| `exposed`, more | kept |
| `unknown` | kept — it costs almost nothing and its job is to stay a standing warning |

The thresholds live in `effective_state()` and the constants above it in
`tools/laconic_index.py`; that function is the source of truth, and this table will drift
before it does.

Decay only changes the *injected view*. The concept file and `INDEX.md` keep every
observation, and fresh evidence resurrects a dropped concept through the normal recording
path — nothing is deleted without `--forget`.

The console is an open learner model: it exists so you can correct specific inferences, not
so you can rate yourself. Every change it makes goes through the same schema, promotion
ladder, index regeneration, and git commit as an agent-recorded one.
