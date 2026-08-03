#!/usr/bin/env python3
"""Local, decision-only web review for validated bootstrap proposals."""

import argparse
import json
import os
import shlex
import sys
import webbrowser
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from laconic_console import (  # noqa: E402
    HTML_CSP, MAX_BODY, SECURITY_HEADERS, read_concept, request_is_json,
    request_is_same_origin,
)
from laconic_index import atomic_write_text  # noqa: E402
from laconic_record import home  # noqa: E402
from laconic_review import load_json, validate  # noqa: E402

UI_FILE = HERE / "review_ui.html"
DECISIONS = {None, "accept", "reject"}


def decision_document(review_id, proposals):
    return {
        "schema_version": 1,
        "purpose": "laconic-bootstrap-decisions",
        "review_id": review_id,
        "decisions": [
            {"proposal_id": proposal["proposal_id"], "decision": None}
            for proposal in proposals
        ],
    }


def load_decisions(path, review_id, proposals):
    expected = [proposal["proposal_id"] for proposal in proposals]
    if not path.exists():
        return decision_document(review_id, proposals)
    document = load_json(path, "decisions")
    if document.get("schema_version") != 1 \
            or document.get("purpose") != "laconic-bootstrap-decisions" \
            or document.get("review_id") != review_id:
        raise ValueError("decision file does not match this review")
    rows = document.get("decisions")
    if not isinstance(rows, list):
        raise ValueError("decisions must be a list")
    found = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"proposal_id", "decision"}:
            raise ValueError("invalid decision row")
        if row["proposal_id"] in found or row["decision"] not in DECISIONS:
            raise ValueError("invalid or duplicate proposal decision")
        found[row["proposal_id"]] = row["decision"]
    if set(found) != set(expected):
        raise ValueError("decision file must cover every current proposal")
    return {
        "schema_version": 1, "purpose": "laconic-bootstrap-decisions",
        "review_id": review_id,
        "decisions": [
            {"proposal_id": proposal_id, "decision": found[proposal_id]}
            for proposal_id in expected
        ],
    }


def save_decision(path, document, proposal_id, decision):
    if decision not in DECISIONS:
        raise ValueError("decision must be accept, reject, or null")
    matched = False
    for row in document["decisions"]:
        if row["proposal_id"] == proposal_id:
            row["decision"] = decision
            matched = True
            break
    if not matched:
        raise ValueError("unknown proposal_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(document, indent=2) + "\n")


def existing_concept(concept_id):
    path = home() / "concepts" / f"{concept_id}.md"
    if not path.is_file():
        return None
    try:
        return read_concept(path)
    except (OSError, ValueError):
        return {"id": concept_id, "error": "existing concept could not be parsed"}


class ReviewState:
    def __init__(self, bundle_path, proposals_path, decisions_path):
        self.bundle_path = bundle_path
        self.proposals_path = proposals_path
        self.decisions_path = decisions_path
        self.bundle = load_json(bundle_path, "bundle")
        document = load_json(proposals_path, "proposals")
        self.proposals, self.sources = validate(self.bundle, document, home())
        self.decisions = load_decisions(
            decisions_path, self.bundle["review_id"], self.proposals
        )
        self.lock = Lock()

    def payload(self):
        decisions = {
            row["proposal_id"]: row["decision"] for row in self.decisions["decisions"]
        }
        proposals = []
        for proposal in self.proposals:
            source = self.sources[proposal["source_refs"][0]]
            proposals.append({
                **proposal,
                "decision": decisions[proposal["proposal_id"]],
                "source": source,
                "existing": existing_concept(proposal["concept_id"]),
            })
        return {
            "review_id": self.bundle["review_id"],
            "projects": self.bundle.get("projects") or [self.bundle.get("project")],
            "created_at": self.bundle.get("created_at"),
            "proposals": proposals,
            "decisions_path": str(self.decisions_path),
            "apply_command": "~/.laconic/bin/laconic-apply-review " + " ".join(
                shlex.quote(value) for value in [
                    "--bundle", str(self.bundle_path),
                    "--proposals", str(self.proposals_path),
                    "--decisions", str(self.decisions_path),
                    "--confirm-review-id", self.bundle["review_id"],
                ]
            ),
        }

    def decide(self, proposal_id, decision):
        with self.lock:
            save_decision(self.decisions_path, self.decisions, proposal_id, decision)


class Handler(BaseHTTPRequestHandler):
    state = None

    def log_message(self, format, *args):
        pass

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

    def _same_origin(self):
        return request_is_same_origin(self.headers, self.server.server_port)

    def _json_body(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
        except ValueError as error:
            raise ValueError("invalid content length") from error
        if size < 0 or size > MAX_BODY:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        if not self._same_origin():
            return self._send(403, json.dumps({"error": "unexpected host"}))
        if self.path in ("/", "/index.html"):
            return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/review":
            return self._send(200, json.dumps(self.state.payload(), ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._same_origin():
            return self._send(403, json.dumps({"error": "cross-origin request refused"}))
        if not request_is_json(self.headers):
            return self._send(415, json.dumps({"error": "application/json required"}))
        try:
            body = self._json_body()
            if self.path != "/api/decision":
                return self._send(404, json.dumps({"error": "not found"}))
            self.state.decide(body["proposal_id"], body.get("decision"))
        except (KeyError, TypeError, ValueError) as error:
            return self._send(400, json.dumps({"error": str(error)}))
        return self._send(200, json.dumps({"ok": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--proposals", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--port", type=int, default=7643)
    parser.add_argument("--home", help="override LACONIC_HOME")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if args.home:
        os.environ["LACONIC_HOME"] = args.home
    try:
        state = ReviewState(args.bundle, args.proposals, args.decisions)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"laconic bootstrap review → {url}")
    print(f"{len(state.proposals)} proposals; decisions: {args.decisions}")
    print("This interface records decisions only; Ctrl-C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
