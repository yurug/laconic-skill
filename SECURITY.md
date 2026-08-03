# Security and privacy

Laconic stores an inferred model of one person's technical knowledge. Treat that model as
private even when its evidence contains no source text.

## Trust boundary

- Concept files, absolute project paths, evidence summaries, Git history, and optional
  telemetry are stored under `~/.laconic/` (or `LACONIC_HOME`). File permissions and access
  to that account are the primary boundary.
- The console binds only to `127.0.0.1`. It rejects unexpected hosts and cross-origin writes,
  requires JSON for mutations, limits request size, and sends restrictive browser headers.
  It has no authentication; do not proxy it, expose its port, or run it on an untrusted shared
  account.
- Laconic never creates a Git remote. Synchronization occurs only when the user configures an
  `origin` and starts Claude Code with `LACONIC_PUSH=1`. The configured remote then receives
  the model and its full Git history.
- Telemetry is disabled by default. With `LACONIC_TELEMETRY=1`, it records concept identifiers,
  states, booleans, and response lengths in `~/.laconic/telemetry.jsonl`; it does not record
  prompt or response text and is not pushed by Laconic.

Evidence must summarize an observation without credentials, secrets, personal data, or
verbatim confidential material. `laconic-lint` detects common secret shapes, but it cannot
prove that stored evidence is safe to disclose.

## Reporting a vulnerability

Open a GitHub security advisory for `yurug/laconic-skill` when private reporting is available.
If it is not, contact the maintainer privately rather than filing an issue containing an
exploit, model data, project paths, or credentials. Include the affected version, impact, and
a minimal reproduction with synthetic data.

Public issues are appropriate for non-sensitive hardening suggestions. Do not attach a real
`~/.laconic/` directory to a report.
