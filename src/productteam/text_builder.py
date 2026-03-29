"""Text-only builder for models that don't support tool calling.

Extracts code from markdown fenced code blocks in model output and
writes them to disk.  This enables small local models (4B-20B) to
participate in the pipeline without tool-calling support.

Fence format expected (any of these):

    **src/models.py**
    ```python
    code here
    ```

    # src/models.py
    ```python
    code here
    ```

    ```python
    # src/models.py
    code here
    ```

    <!-- file: src/models.py -->
    ```python
    code here
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedFile:
    path: str
    content: str


# Patterns for file path detection before or inside a code fence
_PATH_BEFORE_FENCE = re.compile(
    r"(?:"
    # **path/to/file.ext**  or  `path/to/file.ext`
    r"(?:\*\*|`)([\w./-]+\.(?:py|js|ts|json|yaml|yml|toml|txt|md|html|css|cfg|ini|sh|bat))(?:\*\*|`)"
    r"|"
    # # path/to/file.ext  or  ## path/to/file.ext
    r"#{1,3}\s+([\w./-]+\.(?:py|js|ts|json|yaml|yml|toml|txt|md|html|css|cfg|ini|sh|bat))"
    r"|"
    # <!-- file: path/to/file.ext -->
    r"<!--\s*file:\s*([\w./-]+\.(?:py|js|ts|json|yaml|yml|toml|txt|md|html|css|cfg|ini|sh|bat))\s*-->"
    r"|"
    # File: path/to/file.ext  or  Filename: path/to/file.ext
    r"(?:File|Filename|Path):\s*`?([\w./-]+\.(?:py|js|ts|json|yaml|yml|toml|txt|md|html|css|cfg|ini|sh|bat))`?"
    r")"
    r"\s*\n",
    re.MULTILINE,
)

# Comment-style path at the start of code content
_PATH_IN_COMMENT = re.compile(
    r"^#\s*([\w./-]+\.(?:py|js|ts|json|yaml|yml|toml|txt|md|html|css|cfg|ini|sh|bat))\s*\n"
)

# Fenced code block
_CODE_FENCE = re.compile(
    r"```(?:\w+)?\s*\n(.*?)```",
    re.DOTALL,
)


def extract_files(text: str) -> list[ExtractedFile]:
    """Extract file paths and content from markdown-fenced code blocks.

    Returns a list of ExtractedFile with path and content.
    Files without a detectable path are skipped.
    """
    results: list[ExtractedFile] = []
    seen_paths: set[str] = set()

    # Find all code fences and their positions
    for fence_match in _CODE_FENCE.finditer(text):
        code = fence_match.group(1)
        fence_start = fence_match.start()

        # Look for a file path in the text before this fence
        # (within the last 200 chars before the fence)
        prefix = text[max(0, fence_start - 200):fence_start]
        file_path = None

        # Check for path patterns before the fence
        for path_match in _PATH_BEFORE_FENCE.finditer(prefix):
            # Take the last match (closest to the fence)
            for g in path_match.groups():
                if g:
                    file_path = g
                    break

        # Check for path as first-line comment inside the code
        if not file_path:
            comment_match = _PATH_IN_COMMENT.match(code)
            if comment_match:
                file_path = comment_match.group(1)
                # Remove the path comment from the code
                code = code[comment_match.end():]

        if not file_path:
            continue

        # Normalize path
        file_path = file_path.strip().lstrip("/").lstrip("\\")

        # Deduplicate — last occurrence wins
        code = code.rstrip() + "\n"

        if file_path in seen_paths:
            # Update existing entry
            for i, r in enumerate(results):
                if r.path == file_path:
                    results[i] = ExtractedFile(path=file_path, content=code)
                    break
        else:
            seen_paths.add(file_path)
            results.append(ExtractedFile(path=file_path, content=code))

    return results


def write_extracted_files(
    files: list[ExtractedFile],
    project_dir: Path,
) -> list[str]:
    """Write extracted files to disk under project_dir.

    Returns list of paths that were written.
    Skips files that would escape the project directory.
    """
    written: list[str] = []
    root = project_dir.resolve()

    for f in files:
        target = (project_dir / f.path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue  # Skip path traversal attempts

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
        written.append(f.path)

    return written
