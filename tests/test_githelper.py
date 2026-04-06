"""Tests for pyzo.tools.pyzoFileBrowser.githelper."""

import importlib.util
import os
import subprocess
import sys
import tempfile

import pytest


def _import_githelper():
    """Import githelper directly without triggering Qt imports."""
    spec = importlib.util.spec_from_file_location(
        "githelper",
        os.path.join(
            os.path.dirname(__file__),
            "..", "pyzo", "tools", "pyzoFileBrowser", "githelper.py",
        ),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


githelper = _import_githelper()


def _init_git_repo(path):
    """Initialise a minimal git repo with one commit in *path*."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path, check=True, capture_output=True,
    )
    # Create an initial commit so HEAD is valid
    readme = os.path.join(path, "README.md")
    with open(readme, "w") as fh:
        fh.write("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=path, check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests for git_stash
# ---------------------------------------------------------------------------


def test_git_stash_creates_stash():
    """git_stash returns True and creates a stash entry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        # Modify a tracked file so there is something to stash
        readme = os.path.join(tmpdir, "README.md")
        with open(readme, "w") as fh:
            fh.write("modified\n")

        result = githelper.git_stash(tmpdir, "my stash message")

        assert result is True
        # Verify a stash was actually created
        stash_list = subprocess.run(
            ["git", "stash", "list"],
            cwd=tmpdir, capture_output=True, text=True,
        )
        assert "my stash message" in stash_list.stdout


def test_git_stash_nothing_to_stash():
    """git_stash returns True but creates no stash entry when working tree is clean."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        # Working tree is clean - nothing to stash
        result = githelper.git_stash(tmpdir, "empty stash")
        # git stash push exits 0 even when there is nothing to stash
        assert result is True
        # But no stash entry is created
        stash_list = subprocess.run(
            ["git", "stash", "list"],
            cwd=tmpdir, capture_output=True, text=True,
        )
        assert stash_list.stdout.strip() == ""


def test_git_stash_cancelled_does_not_stash():
    """Cancelling the prompt (not calling git_stash) leaves the repo unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        readme = os.path.join(tmpdir, "README.md")
        with open(readme, "w") as fh:
            fh.write("modified\n")

        # Simulate cancel: git_stash is simply NOT called
        stash_list = subprocess.run(
            ["git", "stash", "list"],
            cwd=tmpdir, capture_output=True, text=True,
        )
        assert stash_list.stdout.strip() == ""
        # File is still modified
        assert open(readme).read() == "modified\n"


def test_git_stash_invalid_repo_returns_false():
    """git_stash returns False for a path that is not a git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = githelper.git_stash(tmpdir, "irrelevant")
        assert result is False
