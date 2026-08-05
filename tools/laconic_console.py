#!/usr/bin/env python3
"""A local console for the knowledge model: inspect it, and correct what it got wrong.

Why local and not an Artifact: the model lives on disk at ~/.laconic. A sandboxed web
page cannot touch it, so the only medium that closes laconic's loop -- read your input,
update the model, iterate -- is a server on your own machine.

The guardrail this UI is built around: it is for *correcting specific inferences*, not for
rating yourself. Self-rated expertise has no predictive power (the reason the model is
emergent from conversation, not a questionnaire). Correcting a wrong claim is negotiated
open-learner-model practice; grading yourself on a scale is the thing the evidence warns
against. So every action here answers "is this particular inference right?", never "how
much do you know?".

Binds to 127.0.0.1 only: it can write the model and run git, so it must never be exposed.

Run:  python3 laconic_console.py [--port 7642] [--home ~/.laconic]
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from laconic_index import (  # noqa: E402
    STATES,
    atomic_write_text,
    parse_frontmatter,
    parse_capabilities,
    parse_knowledge_claims,
    write_index_file,
)
from laconic_lint import SECRET_PATTERNS  # noqa: E402
from laconic_record import (  # noqa: E402
    ID_RE,
    acquire_model_lock,
    ensure_repo,
    git_commit,
    git_push_async,
)

UI_FILE = HERE / "console_ui.html"
DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_BODY = 64 * 1024
ACRONYMS = {
    "ap", "api", "bb", "ci", "cli", "dsar", "etf", "gdpr", "gui", "ir", "kb",
    "llm", "nav", "ocaml", "pbc", "pcm", "posix", "pty", "rcf", "rocq", "ssa",
    "toctou", "ui", "vp", "wtp", "x11",
}
HTML_CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self'; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def request_is_same_origin(headers, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if headers.get("Host", "") not in allowed_hosts:
        return False
    origin = headers.get("Origin")
    return origin is None or origin in {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }


def request_is_json(headers):
    return headers.get("Content-Type", "").split(";", 1)[0].strip().lower() == (
        "application/json"
    )


def home():
    return Path(os.environ.get("LACONIC_HOME") or Path.home() / ".laconic")


def concepts_dir():
    return home() / "concepts"


def human_label(concept_id):
    """Turn a storage key into a readable fallback, preserving common technical names."""
    words = concept_id.split("-")
    rendered = [word.upper() if word in ACRONYMS else word.capitalize() for word in words]
    # `pbc-prepared-by-client` carries both acronym and expansion. Present that relation
    # instead of a repetitive title, but keep ordinary names such as `rust-pin` intact.
    if words and words[0] in ACRONYMS and len(words) > 1:
        initials = "".join(word[0] for word in words[1:])
        if initials == words[0]:
            return f"{words[0].upper()} — {' '.join(w.capitalize() for w in words[1:])}"
    return " ".join(rendered)


def useful_summary(summary, concept_id):
    """Reject recorder fallbacks that merely spell the internal id with spaces."""
    normalized = lambda value: re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return summary if normalized(summary) != normalized(concept_id.replace("-", " ")) else ""


def read_concept(path):
    """Full view of one concept: frontmatter, dated evidence, and the summary line."""
    meta = parse_frontmatter(path) or {}
    text = path.read_text(encoding="utf-8")
    evidence, summary, in_ev = [], "", False
    body_started = False
    for line in text.splitlines():
        if line.strip() == "---":
            continue
        if line.startswith("evidence:"):
            in_ev = True
            continue
        if in_ev:
            if line.startswith("  - ") or line.startswith("- "):
                evidence.append(line.strip()[2:].strip())
                continue
            in_ev = False
        # First non-empty line after the closing frontmatter that is not a heading.
        if ":" in line and not body_started and not line.startswith("#") and line.split(":")[0] in (
            "id", "type", "domain", "state", "confidence", "depends-on", "last-updated"
        ):
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not summary and body_started:
            summary = stripped
        if stripped == "" and not body_started:
            body_started = True
    # simpler summary: first non-heading line of the body
    m = text.split("\n---", 1)
    body = m[1] if len(m) == 2 else ""
    if len(m) == 2:
        for line in body.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                summary = s
                break
    try:
        conf = float(meta.get("confidence", 0))
    except ValueError:
        conf = 0.0
    deps = meta.get("depends-on", [])
    if isinstance(deps, str):
        deps = [d.strip() for d in deps.strip("[]").split(",") if d.strip()]
    summary = useful_summary(summary, meta.get("id", path.stem))
    return {
        "id": meta.get("id", path.stem),
        "label": human_label(meta.get("id", path.stem)),
        "domain": meta.get("domain", "general"),
        "state": meta.get("state", "unknown"),
        "confidence": conf,
        "evidence": evidence,
        "capabilities": parse_capabilities(body),
        "knowledge": parse_knowledge_claims(body),
        "summary": summary,
        "depends_on": deps,
        "last_updated": meta.get("last-updated", ""),
        "mtime": path.stat().st_mtime,
    }


def load_model():
    d = concepts_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        try:
            out.append(read_concept(p))
        except Exception:
            continue
    return out


def run_record(cid, state, evidence, domain=None, confirmed=False):
    """Delegate a knowledge correction to the record tool, so promotion rules, index
    regeneration and the git commit all happen exactly as they do for the agent."""
    cmd = [sys.executable, str(HERE / "laconic_record.py"), cid,
           "--state", state, "--evidence", evidence]
    if domain:
        cmd += ["--domain", domain]
    if confirmed:
        cmd += ["--confirmed"]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ})
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def edit_metadata(cid, domain=None, summary=None):
    """Domain / summary are organisation, not knowledge -- so this path adds NO evidence
    (inventing an observation would violate the model's own rule)."""
    if not ID_RE.fullmatch(cid):
        return False, "invalid concept id"
    if domain is not None and not DOMAIN_RE.fullmatch(domain):
        return False, "domain must be lowercase kebab-case"
    if summary is not None:
        summary = summary.strip()
        if not summary or "\n" in summary or "\r" in summary or len(summary) > 300:
            return False, "summary must be one non-empty line of at most 300 characters"
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(summary):
                return False, f"summary looks like a {label}; do not store secrets"

    path = concepts_dir() / f"{cid}.md"
    ensure_repo(home())
    lock = acquire_model_lock(home())
    if lock is None:
        return False, "model is busy; retry after synchronization finishes"
    try:
        # Read only after acquiring the lock: another session may have changed this concept.
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, f"no such concept: {cid}"
        except OSError as error:
            return False, f"could not read {cid}: {error}"
        head, separator, body = text.partition("\n---\n")
        if not separator:
            return False, f"{cid} has malformed frontmatter; run laconic-lint"
        if domain is not None:
            lines = []
            seen = False
            for line in head.splitlines():
                if line.startswith("domain:"):
                    lines.append(f"domain: {domain}")
                    seen = True
                else:
                    lines.append(line)
            if not seen:
                lines.append(f"domain: {domain}")
            head = "\n".join(lines)
        if summary is not None:
            body_lines = body.splitlines()
            replaced = False
            for i, line in enumerate(body_lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    body_lines[i] = summary
                    replaced = True
                    break
            if not replaced:
                body_lines = [summary, ""] + body_lines
            body = "\n".join(body_lines)
        try:
            atomic_write_text(path, head + "\n---\n" + body)
        except OSError as error:
            return False, f"could not write {cid}: {error}"
        write_index_file(date.today().isoformat())
        git_commit(home(), f"{cid}: edit metadata")
    finally:
        lock.close()
    git_push_async(home())
    return True, f"edited {cid}"


def delete_concept(cid):
    if not ID_RE.fullmatch(cid):
        return False, "invalid concept id"
    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "laconic_record.py"),
            cid,
            "--forget",
            "console correction",
        ],
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep the console quiet

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", HTML_CSP)
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError as error:
            raise ValueError("invalid content length") from error
        if n < 0 or n > MAX_BODY:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _same_origin(self):
        return request_is_same_origin(self.headers, self.server.server_port)

    def do_GET(self):
        if not self._same_origin():
            return self._send(403, json.dumps({"error": "unexpected host"}))
        if self.path in ("/", "/index.html"):
            self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/model":
            model = load_model()
            self._send(200, json.dumps({"concepts": model, "states": STATES,
                                        "home": str(home())}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._same_origin():
            return self._send(403, json.dumps({"error": "cross-origin request refused"}))
        if not request_is_json(self.headers):
            return self._send(415, json.dumps({"error": "application/json required"}))
        try:
            body = self._json_body()
        except Exception:
            return self._send(400, json.dumps({"error": "bad json"}))
        try:
            if self.path == "/api/record":
                ok, msg = run_record(
                    body["id"], body["state"], body["evidence"],
                    body.get("domain"), body.get("confirmed", False),
                )
            elif self.path == "/api/edit":
                ok, msg = edit_metadata(body["id"], body.get("domain"), body.get("summary"))
            elif self.path == "/api/delete":
                ok, msg = delete_concept(body["id"])
            else:
                return self._send(404, json.dumps({"error": "not found"}))
        except KeyError as e:
            return self._send(400, json.dumps({"error": f"missing field {e}"}))
        except (TypeError, ValueError) as error:
            return self._send(400, json.dumps({"error": str(error)}))
        self._send(200 if ok else 409, json.dumps({"ok": ok, "message": msg}))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7642)
    ap.add_argument("--home", default=None, help="override LACONIC_HOME")
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = ap.parse_args()
    if args.home:
        os.environ["LACONIC_HOME"] = args.home

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"laconic console → {url}")
    print(f"model: {concepts_dir()}   ({len(load_model())} concepts)")
    print("Ctrl-C to stop.")
    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
