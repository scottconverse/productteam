#!/usr/bin/env python3
"""
SessionStart companion for commit-size-gate (Hard Rule 11).

Injects a one-line reminder that the gate is active in this project,
so the assistant pre-tags large commits rather than hitting exit 2
and retrying. Advisory only — does not block.
"""

import json
import sys

MSG = (
    "Hard Rule 11 (Commit-Size Acknowledgment Gate) is active in this project. "
    "Any `git commit` with >800 staged lines must include one of: "
    "[MVP] [LARGE-CHANGE] [REFACTOR] [INITIAL] [MERGE] [REVERT] "
    "[SCOPE-EXPANSION: reason]. "
    "Bypass surfaces (fail-open): --amend, -F, editor commits. "
    "Pressure valve: user says `override rule 11` for a 60-second one-shot."
)

json.dump({"additionalContext": MSG}, sys.stdout)
sys.exit(0)
