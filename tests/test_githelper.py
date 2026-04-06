"""
Tests for pyzo.tools.pyzoFileBrowser.githelper – specifically the new
async GitStatus.refresh() worker introduced to satisfy:
  • GitStatus.refresh() spawns a QThread worker running git status --porcelain
  • Worker posts the result back via statusRefreshed(dict) signal
  • Calling refresh() while a previous refresh is in-flight discards the stale result
  • statusRefreshed emits a structured dict with "staged" and "unstaged" lists
"""

import os
import sys
import importlib.util
import subprocess
import tempfile
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap Qt before importing githelper (which now depends on pyzo.qt)
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_API", "pyqt5")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure pyzo package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pyzo.qt import QtCore, QtWidgets  # noqa: E402 – must come after sys.path setup

# Create a single QApplication for the whole test session
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Load githelper via importlib to avoid triggering pyzo.tools.__init__
# ---------------------------------------------------------------------------
def _load_githelper():
    pkg_dir = os.path.join(
        os.path.dirname(__file__), "..", "pyzo", "tools", "pyzoFileBrowser"
    )
    spec = importlib.util.spec_from_file_location(
        "githelper", os.path.join(pkg_dir, "githelper.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gh = _load_githelper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _wait_for_signal(signal, timeout_ms=3000):
    """Block the event loop until *signal* is emitted or *timeout_ms* elapses.

    Returns the list of arguments emitted with the signal, or None on timeout.
    """
    received = []

    def _slot(*args):
        received.extend(args)
        loop.quit()

    loop = QtCore.QEventLoop()
    signal.connect(_slot)
    QtCore.QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    signal.disconnect(_slot)
    return received if received else None


def _make_git_repo(tmp_path):
    """Initialise a minimal git repository in *tmp_path* with one tracked file."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    tracked = os.path.join(str(tmp_path), "tracked.py")
    with open(tracked, "w") as f:
        f.write("x = 1\n")
    subprocess.run(
        ["git", "add", "tracked.py"], cwd=str(tmp_path), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return str(tmp_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGitStatusIsQObject:
    """GitStatus must now be a QtCore.QObject so it can carry signals."""

    def test_inherits_qobject(self):
        gs = gh.GitStatus("/fake/root", {})
        assert isinstance(gs, QtCore.QObject)

    def test_has_status_refreshed_signal(self):
        gs = gh.GitStatus("/fake/root", {})
        assert hasattr(gs, "statusRefreshed")


class TestParseGitStatus:
    """Unit-test the internal _parse_git_status() helper in isolation."""

    def test_returns_staged_and_unstaged_keys(self):
        data = gh._parse_git_status.__wrapped__ if hasattr(
            gh._parse_git_status, "__wrapped__"
        ) else None
        # Call the real helper against a dummy repo (will fail gracefully)
        result = gh._parse_git_status("/non_existent_repo")
        assert isinstance(result, dict)
        assert "staged" in result
        assert "unstaged" in result

    def test_failure_returns_empty_lists(self):
        result = gh._parse_git_status("/non_existent_path_xyz")
        assert result == {"staged": [], "unstaged": []}

    def test_staged_file(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        # Stage a new file
        new_file = os.path.join(repo, "new.py")
        with open(new_file, "w") as f:
            f.write("y = 2\n")
        subprocess.run(
            ["git", "add", "new.py"], cwd=repo, check=True, capture_output=True
        )
        data = gh._parse_git_status(repo)
        assert any(os.path.basename(e["path"]) == "new.py" for e in data["staged"])
        # Staged additions use XY = "A "
        staged_xys = {os.path.basename(e["path"]): e["xy"] for e in data["staged"]}
        assert staged_xys["new.py"][0] == "A"

    def test_untracked_file_in_unstaged(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        untracked = os.path.join(repo, "untracked.py")
        with open(untracked, "w") as f:
            f.write("z = 3\n")
        data = gh._parse_git_status(repo)
        # Untracked files (xy == "??") should appear in unstaged
        assert any(
            os.path.basename(e["path"]) == "untracked.py" for e in data["unstaged"]
        )
        # Untracked files must NOT appear in staged
        assert not any(
            os.path.basename(e["path"]) == "untracked.py" for e in data["staged"]
        )

    def test_modified_unstaged(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        tracked = os.path.join(repo, "tracked.py")
        with open(tracked, "a") as f:
            f.write("# modified\n")
        data = gh._parse_git_status(repo)
        assert any(
            os.path.basename(e["path"]) == "tracked.py" for e in data["unstaged"]
        )
        # Not staged (X is ' ')
        assert not any(
            os.path.basename(e["path"]) == "tracked.py" for e in data["staged"]
        )


class TestGitRefreshWorker:
    """Unit-test _GitRefreshWorker directly."""

    def test_emits_result_ready(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        worker = gh._GitRefreshWorker(repo)
        emitted = []
        worker.result_ready.connect(lambda d: emitted.append(d))
        worker.start()
        worker.wait(3000)
        _app.processEvents()
        assert len(emitted) == 1
        assert "staged" in emitted[0]
        assert "unstaged" in emitted[0]

    def test_result_on_invalid_root(self):
        worker = gh._GitRefreshWorker("/non_existent_xyz")
        emitted = []
        worker.result_ready.connect(lambda d: emitted.append(d))
        worker.start()
        worker.wait(3000)
        _app.processEvents()
        assert emitted == [{"staged": [], "unstaged": []}]


class TestGitStatusRefresh:
    """Integration tests for GitStatus.refresh()."""

    def test_refresh_emits_status_refreshed(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        gs = gh.GitStatus(repo, {})
        gs.refresh()
        result = _wait_for_signal(gs.statusRefreshed)
        assert result is not None
        data = result[0]
        assert isinstance(data, dict)
        assert "staged" in data
        assert "unstaged" in data

    def test_refresh_updates_internal_status(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        # Create an untracked file so there is something to report
        with open(os.path.join(repo, "extra.py"), "w") as f:
            f.write("a = 1\n")
        gs = gh.GitStatus(repo, {})
        _wait_for_signal(gs.statusRefreshed)  # prime before refresh
        gs.refresh()
        _wait_for_signal(gs.statusRefreshed)
        # The internal _status should now contain the untracked file
        assert any(
            "extra.py" in k for k in gs._status.keys()
        ), f"_status keys: {list(gs._status.keys())}"

    def test_worker_is_none_after_refresh_completes(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        gs = gh.GitStatus(repo, {})
        gs.refresh()
        _wait_for_signal(gs.statusRefreshed)
        # The 'finished' signal fires after 'result_ready'; one processEvents()
        # round is enough to let _on_worker_finished clear gs._worker.
        _app.processEvents()
        assert gs._worker is None

    def test_stale_result_is_ignored_when_refresh_called_again(self, tmp_path):
        """Calling refresh() a second time before the first finishes must
        cause the first worker's result to be silently ignored."""
        repo = _make_git_repo(tmp_path)
        gs = gh.GitStatus(repo, {})

        received = []
        gs.statusRefreshed.connect(lambda d: received.append(d))

        # Issue two refreshes in quick succession; the first one's result
        # should be ignored (sender check in _on_worker_result).
        gs.refresh()
        gs.refresh()

        # Wait for the second (current) refresh to complete.
        _wait_for_signal(gs.statusRefreshed, timeout_ms=5000)

        # Process any remaining queued events (finished signals, etc.)
        _app.processEvents()

        # Only one result should arrive (from the second worker).
        assert len(received) == 1, (
            f"Expected exactly 1 statusRefreshed emission but got {len(received)}"
        )

        # Allow any stale events from the first worker a chance to be processed,
        # then confirm the count is still exactly 1.
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(300, loop.quit)
        loop.exec()
        assert len(received) == 1  # still exactly 1

    def test_refresh_with_staged_file(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        new_file = os.path.join(repo, "staged_file.py")
        with open(new_file, "w") as f:
            f.write("b = 2\n")
        subprocess.run(
            ["git", "add", "staged_file.py"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        gs = gh.GitStatus(repo, {})
        gs.refresh()
        result = _wait_for_signal(gs.statusRefreshed)
        assert result is not None
        data = result[0]
        staged_paths = [os.path.basename(e["path"]) for e in data["staged"]]
        assert "staged_file.py" in staged_paths

    def test_refresh_structured_entries_have_path_and_xy(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        with open(os.path.join(repo, "new.py"), "w") as f:
            f.write("c = 3\n")
        gs = gh.GitStatus(repo, {})
        gs.refresh()
        result = _wait_for_signal(gs.statusRefreshed)
        assert result is not None
        data = result[0]
        for entry in data["staged"] + data["unstaged"]:
            assert "path" in entry, f"Missing 'path' key in entry: {entry}"
            assert "xy" in entry, f"Missing 'xy' key in entry: {entry}"
            assert len(entry["xy"]) == 2, f"xy should be 2 chars: {entry['xy']!r}"
            assert os.path.isabs(entry["path"]), f"path should be absolute: {entry['path']!r}"
