"""Tests that productteam's own docs are free of placeholder URLs and template artifacts."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER_PATTERNS = [
    r"your-username",
    r"yourusername",
    r"your_username",
    r"<your-(username|org|repo|name)>",  # template placeholders, not <your-ip>
    r"TODO",
    r"FIXME",
    r"TBD",
    r"coming soon",
]

DOC_FILES = [
    "README.md",
    "docs/index.html",
    "docs/terms.html",
    "CHANGELOG.md",
]


@pytest.mark.parametrize("doc_file", DOC_FILES)
def test_no_placeholder_urls_in_docs(doc_file):
    """ProductTeam's own docs must not contain placeholder URLs or template artifacts."""
    path = REPO_ROOT / doc_file
    if not path.exists():
        pytest.skip(f"{doc_file} does not exist")

    content = path.read_text(encoding="utf-8")

    for pattern in PLACEHOLDER_PATTERNS:
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        # Filter out false positives in code examples showing how to check for placeholders
        real_matches = [
            m for m in matches
            if "checklist" not in content[max(0, m.start() - 80):m.start()].lower()
            and "scan" not in content[max(0, m.start() - 80):m.start()].lower()
        ]
        assert not real_matches, (
            f"{doc_file} contains placeholder pattern '{pattern}' at "
            f"position(s): {[m.start() for m in real_matches]}"
        )
