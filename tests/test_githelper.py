"""Tests for the git helper utilities added for the background fetch feature.

These tests use only the Python standard library (no Qt required) and run
against a real git repository created in a temporary directory.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest


def _load_githelper():
    """Load githelper.py directly without triggering Qt imports."""
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "pyzo",
        "tools",
        "pyzoFileBrowser",
        "githelper.py",
    )
    spec = importlib.util.spec_from_file_location("githelper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


githelper = _load_githelper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(*args, cwd):
    """Run a git command and return (returncode, stdout)."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
    )
    return result.returncode, result.stdout.decode().strip()


def _init_repo(path):
    """Create a minimal git repository at *path* with one initial commit."""
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    # Create an initial commit so HEAD exists
    test_file = os.path.join(path, "README.md")
    with open(test_file, "w") as fh:
        fh.write("hello\n")
    _git("add", ".", cwd=path)
    _git("commit", "-m", "init", cwd=path)


# ---------------------------------------------------------------------------
# Tests for get_ahead_behind
# ---------------------------------------------------------------------------


class TestGetAheadBehind:
    def test_no_upstream_returns_zeros(self, tmp_path):
        """A branch with no upstream should return (0, 0)."""
        repo = str(tmp_path)
        _init_repo(repo)
        ahead, behind = githelper.get_ahead_behind(repo)
        assert (ahead, behind) == (0, 0)

    def test_ahead_count(self, tmp_path):
        """Local commits not yet pushed should be counted as ahead."""
        origin = str(tmp_path / "origin.git")
        local = str(tmp_path / "local")
        os.makedirs(origin)
        os.makedirs(local)

        _git("init", "--bare", cwd=origin)
        _init_repo(local)
        _git("remote", "add", "origin", origin, cwd=local)
        _git("push", "-u", "origin", "HEAD", cwd=local)

        # Add a local commit that hasn't been pushed
        extra = os.path.join(local, "extra.txt")
        with open(extra, "w") as fh:
            fh.write("new\n")
        _git("add", ".", cwd=local)
        _git("commit", "-m", "local commit", cwd=local)

        ahead, behind = githelper.get_ahead_behind(local)
        assert ahead == 1
        assert behind == 0

    def test_behind_count(self, tmp_path):
        """Commits on remote not yet pulled should be counted as behind."""
        origin = str(tmp_path / "origin.git")
        local1 = str(tmp_path / "local1")
        os.makedirs(origin)
        os.makedirs(local1)

        # Set up origin with explicit HEAD pointing to main
        _git("init", "--bare", cwd=origin)
        _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=origin)
        _init_repo(local1)
        _git("remote", "add", "origin", origin, cwd=local1)
        _git("push", "-u", "origin", "HEAD", cwd=local1)

        # Clone into local2 (let git create the directory)
        local2 = str(tmp_path / "local2")
        subprocess.run(["git", "clone", origin, local2], capture_output=True)
        _git("config", "user.email", "test@example.com", cwd=local2)
        _git("config", "user.name", "Test", cwd=local2)

        # Add a commit in local1 and push it
        extra = os.path.join(local1, "extra.txt")
        with open(extra, "w") as fh:
            fh.write("new\n")
        _git("add", ".", cwd=local1)
        _git("commit", "-m", "remote commit", cwd=local1)
        _git("push", cwd=local1)

        # Fetch in local2 so it knows about the remote commit (without merging)
        _git("fetch", cwd=local2)

        ahead, behind = githelper.get_ahead_behind(local2)
        assert ahead == 0
        assert behind == 1

    def test_invalid_path_returns_zeros(self, tmp_path):
        """A non-git directory should return (0, 0) without raising."""
        result = githelper.get_ahead_behind(str(tmp_path))
        assert result == (0, 0)


# ---------------------------------------------------------------------------
# Tests for git_fetch
# ---------------------------------------------------------------------------


class TestGitFetch:
    def test_returns_false_for_non_repo(self, tmp_path):
        """git fetch on a non-repository should return False."""
        ok = githelper.git_fetch(str(tmp_path))
        assert ok is False

    def test_returns_true_for_up_to_date_remote(self, tmp_path):
        """git fetch should return True when the remote exists and is reachable."""
        origin = str(tmp_path / "origin.git")
        local = str(tmp_path / "local")
        os.makedirs(origin)
        os.makedirs(local)

        _git("init", "--bare", cwd=origin)
        _init_repo(local)
        _git("remote", "add", "origin", origin, cwd=local)
        _git("push", "-u", "origin", "HEAD", cwd=local)

        ok = githelper.git_fetch(local)
        assert ok is True


# ---------------------------------------------------------------------------
# Tests for GitFetchWorker
# ---------------------------------------------------------------------------


class TestGitFetchWorker:
    def test_worker_calls_callback(self, tmp_path):
        """Worker should call the callback after set_repo."""
        origin = str(tmp_path / "origin.git")
        local = str(tmp_path / "local")
        os.makedirs(origin)
        os.makedirs(local)

        _git("init", "--bare", cwd=origin)
        _init_repo(local)
        _git("remote", "add", "origin", origin, cwd=local)
        _git("push", "-u", "origin", "HEAD", cwd=local)

        results = []
        event = threading.Event()

        def callback(ahead, behind, upstream):
            results.append((ahead, behind, upstream))
            event.set()

        worker = githelper.GitFetchWorker(callback, interval=60)
        worker.start()
        try:
            worker.set_repo(local)
            triggered = event.wait(timeout=10)
            assert triggered, "Callback was not called within timeout"
            assert len(results) >= 1
            ahead, behind, upstream = results[0]
            assert isinstance(ahead, int)
            assert isinstance(behind, int)
        finally:
            worker.stop()

    def test_worker_pause_resume(self, tmp_path):
        """Pausing the worker should prevent the callback from firing."""
        _init_repo(str(tmp_path))

        calls = []

        def callback(ahead, behind, upstream):
            calls.append((ahead, behind, upstream))

        worker = githelper.GitFetchWorker(callback, interval=60)
        worker.start()
        try:
            worker.pause()
            worker.set_repo(str(tmp_path))
            # Wait a short time; callback should NOT fire while paused
            time.sleep(0.3)
            assert len(calls) == 0
        finally:
            worker.stop()

    def test_worker_set_repo_none(self):
        """Setting repo to None should not crash the worker."""
        worker = githelper.GitFetchWorker(lambda a, b, u: None, interval=60)
        worker.start()
        try:
            worker.set_repo(None)
            time.sleep(0.1)
        finally:
            worker.stop()

    def test_worker_stop_is_clean(self):
        """Stopping the worker should join within the timeout."""
        worker = githelper.GitFetchWorker(lambda a, b, u: None, interval=300)
        worker.start()
        worker.stop(timeout=3.0)
        assert not worker.is_alive()


# ---------------------------------------------------------------------------
# Tests for get_upstream_branch
# ---------------------------------------------------------------------------


class TestGetUpstreamBranch:
    def test_no_upstream_returns_none(self, tmp_path):
        _init_repo(str(tmp_path))
        result = githelper.get_upstream_branch(str(tmp_path))
        assert result is None

    def test_returns_upstream_name(self, tmp_path):
        origin = str(tmp_path / "origin.git")
        local = str(tmp_path / "local")
        os.makedirs(origin)
        os.makedirs(local)
        _git("init", "--bare", cwd=origin)
        _init_repo(local)
        _git("remote", "add", "origin", origin, cwd=local)
        _git("push", "-u", "origin", "HEAD", cwd=local)

        result = githelper.get_upstream_branch(local)
        assert result == "origin/main"
