"""Tests for the git helper utilities in pyzo.tools.pyzoFileBrowser.githelper."""

import importlib.util
import os
import subprocess
import sys
import tempfile

import pytest

# Import githelper directly to avoid triggering the pyzo.tools package
# initialisation (which requires a running Qt application).
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(tmp_path):
    """Create a minimal git repository under *tmp_path* and return its path."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Create an initial commit so that HEAD is valid
    readme = tmp_path / "README.md"
    readme.write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return str(tmp_path)


# ---------------------------------------------------------------------------
# get_git_branches
# ---------------------------------------------------------------------------


def test_get_git_branches_single_branch(tmp_path):
    root = _init_repo(tmp_path)
    local, remote, current = githelper.get_git_branches(root)
    # There should be exactly one local branch (master or main depending on git config)
    assert len(local) == 1
    assert remote == []
    assert current == local[0]


def test_get_git_branches_multiple_branches(tmp_path):
    root = _init_repo(tmp_path)
    # Create an additional local branch
    subprocess.run(
        ["git", "branch", "feature/x"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    local, remote, current = githelper.get_git_branches(root)
    assert len(local) == 2
    assert "feature/x" in local
    assert remote == []
    assert current is not None
    assert current in local


def test_get_git_branches_current_marked(tmp_path):
    root = _init_repo(tmp_path)
    subprocess.run(
        ["git", "branch", "other"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    local, remote, current = githelper.get_git_branches(root)
    # Switch to 'other' and verify current updates
    subprocess.run(
        ["git", "checkout", "other"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    local2, remote2, current2 = githelper.get_git_branches(root)
    assert current2 == "other"


def test_get_git_branches_invalid_path():
    local, remote, current = githelper.get_git_branches("/nonexistent/path")
    assert local == []
    assert remote == []
    assert current is None


# ---------------------------------------------------------------------------
# has_tracked_changes (GitStatus.has_tracked_changes)
# ---------------------------------------------------------------------------


def test_has_tracked_changes_clean(tmp_path):
    root = _init_repo(tmp_path)
    status = githelper.get_git_status(root)
    assert status is not None
    assert status.has_tracked_changes() is False


def test_has_tracked_changes_modified(tmp_path):
    root = _init_repo(tmp_path)
    # Modify the tracked file
    (tmp_path / "README.md").write_text("modified")
    status = githelper.get_git_status(root)
    assert status is not None
    assert status.has_tracked_changes() is True


def test_has_tracked_changes_staged(tmp_path):
    root = _init_repo(tmp_path)
    new_file = tmp_path / "new.txt"
    new_file.write_text("new")
    subprocess.run(
        ["git", "add", "new.txt"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    status = githelper.get_git_status(root)
    assert status is not None
    assert status.has_tracked_changes() is True


def test_has_tracked_changes_untracked_only(tmp_path):
    root = _init_repo(tmp_path)
    # Only add an untracked file (not staged)
    (tmp_path / "untracked.txt").write_text("untracked")
    status = githelper.get_git_status(root)
    assert status is not None
    # Untracked files should NOT count as tracked changes
    assert status.has_tracked_changes() is False


# ---------------------------------------------------------------------------
# git_checkout
# ---------------------------------------------------------------------------


def test_git_checkout_success(tmp_path):
    root = _init_repo(tmp_path)
    subprocess.run(
        ["git", "branch", "new-branch"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    success, error = githelper.git_checkout(root, "new-branch")
    assert success is True
    assert error == ""
    # Verify the current branch changed
    _, _, current = githelper.get_git_branches(root)
    assert current == "new-branch"


def test_git_checkout_nonexistent_branch(tmp_path):
    root = _init_repo(tmp_path)
    success, error = githelper.git_checkout(root, "nonexistent-branch")
    assert success is False
    assert error  # should contain an error message


def test_git_checkout_invalid_path():
    success, error = githelper.git_checkout("/nonexistent/path", "main")
    assert success is False
    assert error
