# Laconic

A Claude Code plugin that cuts the noise out of what your agent tells you, by keeping an
auditable record of what you have already shown you understand.

Coding agents communicate badly. They re-explain what you know, bury the answer under
preamble, blend rationale into instructions, and reach for analogies that quietly mislead.
Once you see it, the fix is almost arithmetic: subtract what the engineer already holds, add
the context they are missing. Laconic is a standing instruction against the noise, plus the
one piece of state that makes the subtraction possible.

## Try it

Requires Bash and Python 3.9 or newer; the runtime otherwise uses only the Python standard
library. The plugin has been validated with Claude Code 2.1.220 and relies on plugin
marketplace, `SessionStart`, `UserPromptSubmit`, `SubagentStart`, and `Stop` hook support.
If Python disappears after installation, the universal hook degrades to a valid conservative
context instead of breaking session startup, but model loading and maintenance are unavailable.

As a plugin, which is what gives you the always-on policy:

```
/plugin marketplace add https://github.com/yurug/laconic-skill
/plugin install laconic@nomadic-labs
```

Or as a bare skill, without the always-on layer:

```bash
./install.sh
```

The difference matters. A skill fires when a task matches its description; the plugin's
`SessionStart` hook runs regardless of the task, which is what governing all communication
requires.

However you installed it, the commands live at one stable path. `~/.laconic/bin/` holds
wrappers that are regenerated on every session start, so they follow the checkout rather than
depending on whether laconic is a plugin or a bare skill:

```bash
~/.laconic/bin/laconic-status    # is laconic doing anything at all?
~/.laconic/bin/laconic-console   # web console, http://127.0.0.1:7642/
~/.laconic/bin/laconic-lint      # validate the model
~/.laconic/bin/laconic-candidates # review strong evidence awaiting distillation
~/.laconic/bin/laconic-bootstrap  # prepare a consented transcript review bundle
~/.laconic/bin/laconic-review     # validate and render agent proposals; never apply them
~/.laconic/bin/laconic-review-web # review proposals and persist accept/reject decisions
~/.laconic/bin/laconic-apply-review # apply explicitly accepted proposals after preflight
```

Transcript bootstrap can consolidate repeated `--project` roots, collapses exact duplicate
turns, and quarantines obvious non-user evidence. External disclosure requires its own
consent and an external-privacy export; no bootstrap proposal writes the model before review.

`laconic-status` answers the first question everyone asks: it reports what is installed, what
the hooks fired, and how big the model has become.

Then just work. The model starts empty and accumulates evidence as the agent observes your
work; nothing is promoted without a dated observation you can inspect. Ordinary routing,
recording, and opportunistic distillation are agent responsibilities: after installation,
you do not need to run a command, curate an index, or answer maintenance prompts.

Two privacy boundaries deliberately remain explicit. A deep bootstrap must obtain scoped
consent before reading historical transcripts, and any external disclosure needs separate
consent. Applying a reviewed bootstrap also remains an explicit decision because it can
rewrite many model entries at once. These are authorization boundaries, not routine upkeep.

## What you get

- **A communication policy, injected before the first token of every session.** Lead with the
  outcome. Answer the contrast actually being asked. Keep "why" out of "how-to". Say what a
  change does *not* handle. Treat detail as having a cost rather than as free.
- **A model of what you know**, one readable markdown file per concept under
  `~/.laconic/`, each carrying dated evidence for why the agent believes what it believes.
  Demonstrated capabilities record what you can explain, justify, map to the world, or modify;
  concept states remain a conservative fallback. The agent relies on the narrow capability
  without extrapolating mastery of the entire topic.
- **Hierarchical retrieval.** Session start injects a compact router and the most-specific
  project leaf; every prompt automatically selects up to two matching domain leaves. Full
  concept evidence loads only when needed. The model can grow without turning every session
  into a flat concept dump or making you operate the index.
- **No guessing.** There is no onboarding questionnaire, because self-reported expertise has
  no predictive power for understanding. Evidence comes from questions you ask, terms you use
  correctly, and corrections you make.
- **A console to correct it.** The model is a set of inferences about you, so you can read
  them, promote what it underrates, demote what it overrates, and delete a bad guess:

  ```bash
  ~/.laconic/bin/laconic-console     # http://127.0.0.1:7642/, localhost only
  ```
- **Local by default.** Every model update is committed to a Git repository under
  `~/.laconic/` so it is inspectable and revertible. Laconic never creates a remote. If
  you explicitly configure an `origin` **and** launch Claude Code with `LACONIC_PUSH=1`,
  writes also trigger a background push to that remote; the current branch is pushed as
  `HEAD`, without assuming it is named `main`.

## What it does not claim

It does not claim to improve your comprehension, and the evidence is why. Across fifteen
controlled studies of adaptive explanation, adaptivity reliably moved *satisfaction* and
rarely moved *measured understanding*, and roughly 29% of naive personalisation attempts did
worse than a generic response.

So the knowledge model has a narrower and more defensible job: avoiding the documented cost
of mismatch. Heavy scaffolding measurably harms people who already know the material,
while too little measurably harms those who do not. What laconic aims at is less noise, fewer
unverified assumptions, verbosity that fits, and a record you can audit.

Three things it deliberately will not do, each because the evidence says so: no learning
styles, no misconception library, and no optimising for "was that helpful?". The reasoning,
including the claims that failed verification, is in [`docs/evidence.md`](docs/evidence.md)
and the `research/` directory.

## Where it fits

Laconic is the first working piece of *engineer engineering*, the fourth discipline in
[Keep the engineer in the loop](https://yann.regis-gianas.org/en/posts/keep-the-engineer-in-the-loop/):
the persistent model at the centre of the loop, the one the other activities consult so that
the human who signs off still understands what they are signing. It is usable on its own, and
it is also the component
[agentic-loop-kit](https://github.com/yurug/agentic-loop-kit) leans on for calibration.

For the file format, the four knowledge states, the promotion ladder, and the lint rules, see
[`docs/knowledge-model.md`](docs/knowledge-model.md).

For the local trust boundary, stored-data risks, and vulnerability reporting, see
[`SECURITY.md`](SECURITY.md).

## Status

Experimental. I use it every day, it changes often, and the hardest open question is how to
tell a genuinely calibrated brief from one that merely feels shorter.

Verify a checkout with `./check.sh` — tests, Python compilation, shell syntax, ShellCheck,
a consistency check between the decay docs and the constants they describe, and a lint of
your own model. No third-party dependencies; ShellCheck is used when installed and reported
as skipped when not. CI runs the portable checks on Python 3.9 through 3.13 and validates the
manifest JSON; the Claude CLI performs its additional manifest validation when available.

Optional local telemetry can measure how often the knowledge model changes the writing. It
is disabled by default. Set `LACONIC_TELEMETRY=1` in the environment that launches Claude
Code to enable it, then run `~/.laconic/bin/laconic-stats`. The log contains concept ids,
states, booleans and response lengths—never prompt or response text—and remains outside the
synced model at `~/.laconic/telemetry.jsonl`.

If you try it, tell me what broke: issues, pull requests, and a plain "this made no sense to
me" are all welcome.

## License

MIT
