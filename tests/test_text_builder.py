"""Tests for text-only builder code extraction."""

from pathlib import Path

from productteam.text_builder import ExtractedFile, extract_files, write_extracted_files


def test_extract_bold_path_before_fence():
    text = (
        "Here is the code:\n\n"
        "**src/models.py**\n"
        "```python\n"
        "class Bookmark:\n"
        "    pass\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 1
    assert files[0].path == "src/models.py"
    assert "class Bookmark" in files[0].content


def test_extract_hash_path_before_fence():
    text = (
        "## src/cli.py\n"
        "```python\n"
        "import click\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 1
    assert files[0].path == "src/cli.py"


def test_extract_comment_path_inside_fence():
    text = (
        "```python\n"
        "# src/storage.py\n"
        "def save():\n"
        "    pass\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 1
    assert files[0].path == "src/storage.py"
    assert "# src/storage.py" not in files[0].content
    assert "def save" in files[0].content


def test_extract_backtick_path_before_fence():
    text = (
        "Create `tests/test_cli.py`:\n\n"
        "`tests/test_cli.py`\n"
        "```python\n"
        "def test_hello():\n"
        "    assert True\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 1
    assert files[0].path == "tests/test_cli.py"


def test_extract_multiple_files():
    text = (
        "**src/models.py**\n"
        "```python\n"
        "class Model:\n"
        "    pass\n"
        "```\n\n"
        "**src/cli.py**\n"
        "```python\n"
        "def main():\n"
        "    pass\n"
        "```\n\n"
        "**tests/test_models.py**\n"
        "```python\n"
        "def test_model():\n"
        "    assert True\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 3
    paths = [f.path for f in files]
    assert "src/models.py" in paths
    assert "src/cli.py" in paths
    assert "tests/test_models.py" in paths


def test_extract_no_path_skips_fence():
    text = (
        "Here is an example:\n"
        "```python\n"
        "print('hello')\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 0


def test_extract_duplicate_path_last_wins():
    text = (
        "**src/main.py**\n"
        "```python\n"
        "v1\n"
        "```\n\n"
        "Updated version:\n\n"
        "**src/main.py**\n"
        "```python\n"
        "v2\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 1
    assert "v2" in files[0].content


def test_write_extracted_files(tmp_path):
    files = [
        ExtractedFile(path="src/models.py", content="class Bookmark:\n    pass\n"),
        ExtractedFile(path="tests/test_models.py", content="def test():\n    assert True\n"),
    ]
    written = write_extracted_files(files, tmp_path)
    assert len(written) == 2
    assert (tmp_path / "src" / "models.py").exists()
    assert (tmp_path / "tests" / "test_models.py").exists()
    assert "class Bookmark" in (tmp_path / "src" / "models.py").read_text()


def test_write_extracted_files_blocks_traversal(tmp_path):
    files = [
        ExtractedFile(path="../escape.py", content="malicious\n"),
    ]
    written = write_extracted_files(files, tmp_path)
    assert len(written) == 0


def test_extract_file_colon_format():
    text = (
        "File: `src/utils.py`\n"
        "```python\n"
        "def helper():\n"
        "    pass\n"
        "```\n"
    )
    files = extract_files(text)
    assert len(files) == 1
    assert files[0].path == "src/utils.py"
