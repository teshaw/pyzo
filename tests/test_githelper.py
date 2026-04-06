"""
Tests for the githelper module.

Uses importlib to load the module in isolation so that the pyzo Qt
application does not need to be running (pyzo/tools/__init__.py would
otherwise try to import Qt).
"""

import importlib.util
import os
import os.path as op
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Load githelper without importing the pyzo.tools package
# ---------------------------------------------------------------------------

_GITHELPER_PATH = op.join(
    op.dirname(__file__),
    "..",
    "pyzo",
    "tools",
    "pyzoFileBrowser",
    "githelper.py",
)

spec = importlib.util.spec_from_file_location("githelper", _GITHELPER_PATH)
githelper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(githelper)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(tmp_path):
    """Create a minimal git repository in *tmp_path* and return its path."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


# ---------------------------------------------------------------------------
# GitStatus – conflict helpers
# ---------------------------------------------------------------------------


def test_is_conflict_xy_true():
    status = githelper.GitStatus("/repo", {})
    for xy in ("UU", "AA", "DD", "AU", "UA", "DU", "UD"):
        assert status.is_conflict_xy(xy), f"{xy!r} should be conflict"


def test_is_conflict_xy_false():
    status = githelper.GitStatus("/repo", {})
    for xy in (" M", "M ", "AM", "??", "  ", "D "):
        assert not status.is_conflict_xy(xy), f"{xy!r} should not be conflict"


def test_has_conflicts_true():
    status = githelper.GitStatus("/repo", {"/repo/a.txt": "UU"})
    assert status.has_conflicts()


def test_has_conflicts_false():
    status = githelper.GitStatus("/repo", {"/repo/a.txt": " M"})
    assert not status.has_conflicts()


def test_get_conflicted_files():
    files = {
        "/repo/a.txt": "UU",
        "/repo/b.txt": " M",
        "/repo/c.txt": "AA",
    }
    status = githelper.GitStatus("/repo", files)
    conflicted = status.get_conflicted_files()
    # Paths are normalised via normcase in __init__
    normalised = [op.normcase(p) for p in conflicted]
    assert op.normcase("/repo/a.txt") in normalised
    assert op.normcase("/repo/c.txt") in normalised
    assert op.normcase("/repo/b.txt") not in normalised


# ---------------------------------------------------------------------------
# list_git_branches
# ---------------------------------------------------------------------------


def test_list_git_branches_no_repo():
    with tempfile.TemporaryDirectory() as tmp:
        branches = githelper.list_git_branches(tmp)
    assert branches == []


def test_list_git_branches_single_branch():
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        # Create an initial commit so the branch exists
        with open(op.join(tmp, "f.txt"), "w") as fh:
            fh.write("hi")
        subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True,
                       capture_output=True)
        branches = githelper.list_git_branches(tmp)
    assert "main" in branches


def test_list_git_branches_multiple():
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        with open(op.join(tmp, "f.txt"), "w") as fh:
            fh.write("hi")
        subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True,
                       capture_output=True)
        subprocess.run(["git", "branch", "feature"], cwd=tmp, check=True,
                       capture_output=True)
        branches = githelper.list_git_branches(tmp)
    assert "main" in branches
    assert "feature" in branches
    assert branches == sorted(branches)  # must be sorted
