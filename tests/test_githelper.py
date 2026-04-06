"""Tests for pyzo.tools.pyzoFileBrowser.githelper – stash and log helpers.

githelper.py has no Qt dependency of its own, but the parent package
``pyzo.tools`` imports Qt in its ``__init__.py``.  To keep these tests
free from Qt (and runnable without a display) we load the module directly
via ``importlib`` so the parent package initialisation is bypassed.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile


def _import_githelper():
    """Load githelper directly, bypassing the Qt-importing tools __init__."""
    here = os.path.dirname(__file__)
    module_path = os.path.join(
        here, "..", "pyzo", "tools", "pyzoFileBrowser", "githelper.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pyzo.tools.pyzoFileBrowser.githelper", module_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Import once at module level so all tests share the same object.
githelper = _import_githelper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_dir):
    """Create a minimal git repository in *tmp_dir* with one commit."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"}

    def run(*args):
        subprocess.check_call(list(args), cwd=tmp_dir, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "t@t.com")
    run("git", "config", "user.name", "Test")

    # Create and commit a file
    path = os.path.join(tmp_dir, "hello.txt")
    with open(path, "w") as fh:
        fh.write("hello\n")
    run("git", "add", "hello.txt")
    run("git", "commit", "-m", "Initial commit")
    return tmp_dir


# ---------------------------------------------------------------------------
# get_git_stash_list
# ---------------------------------------------------------------------------


def test_get_git_stash_list_empty():
    """get_git_stash_list returns [] when there are no stashes."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        result = githelper.get_git_stash_list(tmp)
        assert result == []


def test_get_git_stash_list_with_stash():
    """get_git_stash_list returns one entry after git stash."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)

        env = {**os.environ, "GIT_AUTHOR_NAME": "Alice",
               "GIT_AUTHOR_EMAIL": "a@a.com",
               "GIT_COMMITTER_NAME": "Alice",
               "GIT_COMMITTER_EMAIL": "a@a.com"}

        # Modify the tracked file so there is something to stash
        path = os.path.join(tmp, "hello.txt")
        with open(path, "w") as fh:
            fh.write("modified\n")

        subprocess.check_call(
            ["git", "stash", "push", "-m", "my stash message"],
            cwd=tmp, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        result = githelper.get_git_stash_list(tmp)
        assert len(result) == 1
        entry = result[0]
        assert entry["ref"] == "stash@{0}"
        assert "my stash message" in entry["message"]
        assert "author" in entry
        assert "date" in entry


def test_get_git_stash_list_multiple_stashes():
    """get_git_stash_list returns entries in stash order (newest first)."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        env = {**os.environ, "GIT_AUTHOR_NAME": "Bob",
               "GIT_AUTHOR_EMAIL": "b@b.com",
               "GIT_COMMITTER_NAME": "Bob",
               "GIT_COMMITTER_EMAIL": "b@b.com"}

        path = os.path.join(tmp, "hello.txt")
        for i in range(3):
            with open(path, "w") as fh:
                fh.write(f"change {i}\n")
            subprocess.check_call(
                ["git", "stash", "push", "-m", f"stash {i}"],
                cwd=tmp, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        result = githelper.get_git_stash_list(tmp)
        assert len(result) == 3
        assert result[0]["ref"] == "stash@{0}"
        assert result[1]["ref"] == "stash@{1}"
        assert result[2]["ref"] == "stash@{2}"


def test_get_git_stash_list_invalid_path():
    """get_git_stash_list returns [] for a non-repository directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = githelper.get_git_stash_list(tmp)
        assert result == []


# ---------------------------------------------------------------------------
# get_git_log
# ---------------------------------------------------------------------------


def test_get_git_log_empty_repo():
    """get_git_log returns [] for a repo with no commits."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.check_call(
            ["git", "init", "-b", "main"], cwd=tmp,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "config", "user.email", "t@t.com"], cwd=tmp,
        )
        subprocess.check_call(
            ["git", "config", "user.name", "Test"], cwd=tmp,
        )
        result = githelper.get_git_log(tmp)
        assert result == []


def test_get_git_log_single_commit():
    """get_git_log returns one entry for a repo with a single commit."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        result = githelper.get_git_log(tmp)
        assert len(result) == 1
        entry = result[0]
        assert "sha" in entry
        assert len(entry["sha"]) == 7  # abbreviated hash
        assert entry["message"] == "Initial commit"
        assert "author" in entry
        assert "date" in entry


def test_get_git_log_max_count():
    """get_git_log respects the max_count parameter."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        env = {**os.environ, "GIT_AUTHOR_NAME": "Test",
               "GIT_AUTHOR_EMAIL": "t@t.com",
               "GIT_COMMITTER_NAME": "Test",
               "GIT_COMMITTER_EMAIL": "t@t.com"}

        path = os.path.join(tmp, "hello.txt")
        for i in range(5):
            with open(path, "w") as fh:
                fh.write(f"line {i}\n")
            subprocess.check_call(
                ["git", "commit", "-am", f"commit {i}"],
                cwd=tmp, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        all_commits = githelper.get_git_log(tmp)
        assert len(all_commits) == 6  # 5 extra + initial

        limited = githelper.get_git_log(tmp, max_count=3)
        assert len(limited) == 3


def test_get_git_log_invalid_path():
    """get_git_log returns [] for a non-repository directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = githelper.get_git_log(tmp)
        assert result == []
