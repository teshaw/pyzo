"""Tests for pyzo.tools.pyzoFileBrowser.githelper.get_file_blob."""

import importlib.util
import os

# Import githelper directly to avoid triggering the Qt-dependent
# pyzo.tools package __init__.
_GITHELPER_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "pyzo",
    "tools",
    "pyzoFileBrowser",
    "githelper.py",
)
_spec = importlib.util.spec_from_file_location("githelper", _GITHELPER_PATH)
githelper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(githelper)

get_file_blob = githelper.get_file_blob
get_git_root = githelper.get_git_root

# The test suite lives inside the repository, so we can use it as a live
# git repo for integration-style tests without any extra setup.
REPO_ROOT = get_git_root(os.path.dirname(__file__))


def test_get_file_blob_returns_content_for_tracked_file():
    """get_file_blob returns a non-empty str for a real tracked file."""
    content = get_file_blob(REPO_ROOT, "README.md")
    assert isinstance(content, str)
    assert len(content) > 0


def test_get_file_blob_nonexistent_file_returns_none():
    """get_file_blob returns None for a path that does not exist in git."""
    result = get_file_blob(REPO_ROOT, "this_file_does_not_exist_xyz.txt")
    assert result is None


def test_get_file_blob_nonexistent_ref_returns_none():
    """get_file_blob returns None when the ref does not exist."""
    result = get_file_blob(REPO_ROOT, "README.md", ref="nonexistent-ref-xyz")
    assert result is None


def test_get_file_blob_windows_path_separators():
    """get_file_blob converts backslashes to forward slashes for git."""
    # Use a path that exists; on Windows callers may pass backslashes.
    # pyzo/tools/pyzoFileBrowser/githelper.py is a tracked file.
    forward = get_file_blob(
        REPO_ROOT, "pyzo/tools/pyzoFileBrowser/githelper.py"
    )
    backslash = get_file_blob(
        REPO_ROOT, r"pyzo\tools\pyzoFileBrowser\githelper.py"
    )
    assert forward is not None
    assert forward == backslash


def test_get_file_blob_default_ref_is_head():
    """Calling with and without explicit ref='HEAD' yields the same result."""
    explicit = get_file_blob(REPO_ROOT, "README.md", ref="HEAD")
    implicit = get_file_blob(REPO_ROOT, "README.md")
    assert explicit == implicit


def test_get_file_blob_no_replacement_chars_in_ascii():
    """Returned string contains valid text (no replacement characters for ASCII)."""
    content = get_file_blob(REPO_ROOT, "README.md")
    # README.md is ASCII/UTF-8 so no replacement characters expected.
    assert "\ufffd" not in content
