#!/usr/bin/env python3
"""Stable, content-free assignment for the opt-in semantic-knowledge holdback."""

import hashlib
import os


def arm(session_id):
    """Return semantic or holdback; experiment requires separate telemetry consent."""
    if os.environ.get("LACONIC_TELEMETRY") != "1" \
            or os.environ.get("LACONIC_EXPERIMENT") != "1" or not session_id:
        return "semantic"
    # Twenty percent holdback gives a usable comparison without making the normal model the
    # minority experience. Assignment is stable per session and stores no user content.
    bucket = int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16) % 5
    return "holdback" if bucket == 0 else "semantic"


def includes_knowledge(session_id):
    return arm(session_id) != "holdback"
