"""Tests for the stash helpers added to githelper.py."""

import importlib.util
import os
import subprocess
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Import the helpers without triggering Qt (bypass pyzo/tools/__init__.py)
# ---------------------------------------------------------------------------

_GITHELPER_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "pyzo",
    "tools",
    "pyzoFileBrowser",
    "githelper.py",
)
_spec = importlib.util.spec_from_file_location("githelper", _GITHELPER_PATH)
_githelper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_githelper)

get_stash_list = _githelper.get_stash_list
run_stash_command = _githelper.run_stash_command


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_git_repo(tmp_path):
    """Create a minimal git repo in *tmp_path* and return its path."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    # Initial commit so HEAD exists
    readme = tmp_path / "README.md"
    readme.write_text("hello\n")
    subprocess.run(
        ["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return str(tmp_path)


def _dirty(repo_root):
    """Stage a new file to make the working tree dirty."""
    with open(os.path.join(repo_root, "dirty.txt"), "w") as fh:
        fh.write("dirty\n")
    subprocess.run(
        ["git", "add", "dirty.txt"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )


def test_get_stash_list_empty(tmp_path):
    repo = _make_git_repo(tmp_path)
    assert get_stash_list(repo) == []


def test_get_stash_list_one_entry(tmp_path):
    repo = _make_git_repo(tmp_path)
    _dirty(repo)
    subprocess.run(
        ["git", "stash", "push", "-m", "my stash"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    entries = get_stash_list(repo)
    assert len(entries) == 1
    ref, message = entries[0]
    assert ref == "stash@{0}"
    assert "my stash" in message


def test_get_stash_list_multiple_entries(tmp_path):
    repo = _make_git_repo(tmp_path)
    for i in range(3):
        _dirty(repo)
        # rename file so next _dirty call creates a new one
        os.rename(
            os.path.join(repo, "dirty.txt"),
            os.path.join(repo, f"dirty{i}.txt"),
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "stash", "push", "-m", f"stash {i}"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    entries = get_stash_list(repo)
    assert len(entries) == 3
    # Most recent stash first
    assert entries[0][0] == "stash@{0}"
    assert entries[2][0] == "stash@{2}"


def test_get_stash_list_invalid_path():
    # Should return [] rather than raise
    assert get_stash_list("/nonexistent/path") == []


# ---------------------------------------------------------------------------
# Tests for run_stash_command
# ---------------------------------------------------------------------------


def test_run_stash_push(tmp_path):
    repo = _make_git_repo(tmp_path)
    _dirty(repo)
    ok, out = run_stash_command(repo, ["push", "-m", "test push"])
    assert ok
    assert get_stash_list(repo) != []


def test_run_stash_apply(tmp_path):
    repo = _make_git_repo(tmp_path)
    _dirty(repo)
    run_stash_command(repo, ["push", "-m", "to apply"])
    # Working tree should be clean now
    assert get_stash_list(repo) != []
    ok, out = run_stash_command(repo, ["apply", "stash@{0}"])
    assert ok
    # Stash still in list after apply
    assert get_stash_list(repo) != []


def test_run_stash_pop(tmp_path):
    repo = _make_git_repo(tmp_path)
    _dirty(repo)
    run_stash_command(repo, ["push", "-m", "to pop"])
    ok, out = run_stash_command(repo, ["pop", "stash@{0}"])
    assert ok
    # Stash removed from list after pop
    assert get_stash_list(repo) == []


def test_run_stash_drop(tmp_path):
    repo = _make_git_repo(tmp_path)
    _dirty(repo)
    run_stash_command(repo, ["push", "-m", "to drop"])
    ok, out = run_stash_command(repo, ["drop", "stash@{0}"])
    assert ok
    assert get_stash_list(repo) == []


def test_run_stash_command_failure(tmp_path):
    repo = _make_git_repo(tmp_path)
    # Trying to pop from an empty stash should fail
    ok, out = run_stash_command(repo, ["pop"])
    assert not ok
    assert out  # Should have an error message


def test_run_stash_command_invalid_path():
    ok, out = run_stash_command("/nonexistent/path", ["list"])
    assert not ok
