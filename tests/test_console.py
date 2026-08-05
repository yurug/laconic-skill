"""The localhost console cannot be used cross-origin or bypass model invariants."""

import os
from pathlib import Path
from unittest import mock

from helpers import ModelTestCase
from laconic_console import (
    HTML_CSP,
    SECURITY_HEADERS,
    delete_concept,
    edit_metadata,
    human_label,
    request_is_json,
    request_is_same_origin,
    read_concept,
)


class ConsoleTestCase(ModelTestCase):
    def setUp(self):
        super().setUp()
        self.environment = mock.patch.dict(
            os.environ,
            {
                "LACONIC_HOME": str(self.home),
                "LACONIC_NO_PUSH": "1",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        super().tearDown()


class TestRequestBoundary(ConsoleTestCase):
    def test_console_exposes_structured_navigation_controls(self):
        ui = (Path(__file__).parent.parent / "tools" / "console_ui.html").read_text()
        for control in ('id="search"', 'id="domain"', 'id="kind"', 'id="scope"',
                        'id="sort"', 'data-view="${id}"'):
            self.assertIn(control, ui)
        self.assertIn('NAV={view:"claims"', ui)

    def test_model_read_rejects_an_unexpected_host(self):
        self.assertFalse(
            request_is_same_origin({"Host": "attacker.example"}, 7642)
        )

    def test_mutation_rejects_cross_origin_json(self):
        self.assertFalse(request_is_same_origin({
            "Host": "127.0.0.1:7642",
            "Origin": "https://attacker.example",
        }, 7642))

    def test_loopback_hosts_and_origins_are_accepted(self):
        for host in ("127.0.0.1:7642", "localhost:7642"):
            self.assertTrue(request_is_same_origin({"Host": host}, 7642))
            self.assertTrue(request_is_same_origin({
                "Host": host,
                "Origin": f"http://{host}",
            }, 7642))

    def test_mutation_requires_application_json(self):
        self.assertFalse(request_is_json({"Content-Type": "text/plain"}))
        self.assertTrue(request_is_json({
            "Content-Type": "application/json; charset=utf-8"
        }))

    def test_browser_security_headers_are_declared(self):
        self.assertEqual(SECURITY_HEADERS["X-Frame-Options"], "DENY")
        self.assertEqual(SECURITY_HEADERS["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", HTML_CSP)
        self.assertIn("frame-ancestors 'none'", HTML_CSP)


class TestMutationIntegrity(ConsoleTestCase):
    def test_storage_ids_get_readable_labels(self):
        self.assertEqual(human_label("pbc-prepared-by-client"), "PBC — Prepared By Client")
        self.assertEqual(human_label("rust-pin"), "Rust Pin")

    def test_tautological_summary_is_not_presented_as_meaning(self):
        self.create("rust-pin")
        concept = read_concept(self.path("rust-pin"))
        self.assertEqual(concept["label"], "Rust Pin")
        self.assertEqual(concept["summary"], "")

    def test_read_exposes_established_semantic_knowledge(self):
        self.create("thing", evidence="explained the invariant")
        result = self.record("thing", "--claim", "Treats it as an invariant",
                             "--claim-kind", "principle", "--claim-from", "1")
        self.assertEqual(result.code, 0, result.text)
        concept = read_concept(self.path("thing"))
        self.assertEqual(concept["knowledge"][0]["claim"], "Treats it as an invariant")
        self.assertEqual(concept["knowledge"][0]["evidence"], [1])

    def test_read_exposes_established_capabilities(self):
        self.create(
            "thing", "--kind", "world", "--capability", "Can map it to the domain",
            evidence="mapped the mechanism to the domain",
        )
        concept = read_concept(self.path("thing"))
        self.assertEqual(concept["capabilities"][0]["kind"], "world")
        self.assertEqual(concept["capabilities"][0]["claim"], "Can map it to the domain")
        self.assertEqual(concept["capabilities"][0]["scope"], "project")

    def test_valid_metadata_edit_still_works(self):
        self.create("thing")
        ok, message = edit_metadata(
            "thing", domain="new-domain", summary="Safe summary."
        )
        self.assertTrue(ok, message)
        self.assertIn("Safe summary.", self.read("thing"))
        self.assertEqual(self.field("thing", "domain"), "new-domain")
        index = (self.home / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("thing", index)
        self.assertNotIn("laconic-mechanism", index, "default model leaked across --home")

    def test_edit_rejects_path_traversal_and_frontmatter_injection(self):
        self.create("thing")
        ok, _ = edit_metadata("../../escape", summary="bad")
        self.assertFalse(ok)
        ok, _ = edit_metadata("thing", domain="safe\nstate: verified")
        self.assertFalse(ok)

    def test_edit_rejects_secret_shaped_summary(self):
        self.create("thing")
        ok, message = edit_metadata(
            "thing", summary="password=definitely-not-for-a-model"
        )
        self.assertFalse(ok)
        self.assertIn("secret", message)

    def test_delete_uses_dependency_safe_forget_path(self):
        self.create("base")
        self.create("dependent", "--depends-on", "base")
        ok, message = delete_concept("base")
        self.assertFalse(ok)
        self.assertIn("depend", message)
        self.assertTrue(self.path("base").exists())

    def test_delete_rejects_path_traversal(self):
        ok, _ = delete_concept("../../escape")
        self.assertFalse(ok)


if __name__ == "__main__":
    import unittest

    unittest.main()
