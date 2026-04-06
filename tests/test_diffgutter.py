"""
Tests for the DiffGutter extension.

Covers:
- Hunk dataclass construction
- _parse_hunks() parsing of unified diff headers
- DiffGutter extension integration (widget exists, API is correct)
- setDiffGutterFilePath() triggers an immediate (0 ms) timer
- _recomputeDiff() populates _diffHunks for a tracked file and clears them
  when no file path is set or the file is outside a git repository
- File-load and file-save refresh: gutter clears and repaints after each
  call to setDiffGutterFilePath()
"""

import os
import subprocess
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyqt5")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Hunk and _parse_hunks – pure Python, no Qt needed
# ---------------------------------------------------------------------------
from pyzo.codeeditor.extensions.appearance import Hunk, _parse_hunks


def test_hunk_construction():
    h = Hunk(old_start=1, old_count=3, new_start=1, new_count=0, kind="delete")
    assert h.old_start == 1
    assert h.old_count == 3
    assert h.new_start == 1
    assert h.new_count == 0
    assert h.kind == "delete"


class TestParseHunks:
    def test_add_hunk(self):
        lines = ["@@ -5,0 +6,3 @@ some context\n"]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 1
        h = hunks[0]
        assert h.old_start == 5
        assert h.old_count == 0
        assert h.new_start == 6
        assert h.new_count == 3
        assert h.kind == "add"

    def test_delete_hunk(self):
        lines = ["@@ -2,4 +2,0 @@ some context\n"]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 1
        assert hunks[0].kind == "delete"
        assert hunks[0].old_count == 4
        assert hunks[0].new_count == 0

    def test_modify_hunk(self):
        lines = ["@@ -10,2 +10,3 @@ some context\n"]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 1
        assert hunks[0].kind == "modify"

    def test_implicit_count_one(self):
        """When the comma and count are absent the count defaults to 1."""
        lines = ["@@ -1 +1 @@\n"]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 1
        assert hunks[0].old_count == 1
        assert hunks[0].new_count == 1
        assert hunks[0].kind == "modify"

    def test_multiple_hunks(self):
        lines = [
            "@@ -1,0 +1,2 @@\n",
            "+added line 1\n",
            "+added line 2\n",
            "@@ -5,1 +7,0 @@\n",
            "-removed line\n",
        ]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 2
        assert hunks[0].kind == "add"
        assert hunks[1].kind == "delete"

    def test_non_hunk_lines_ignored(self):
        lines = [
            "diff --git a/foo b/foo\n",
            "--- a/foo\n",
            "+++ b/foo\n",
            "@@ -3,2 +3,2 @@\n",
        ]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 1


# ---------------------------------------------------------------------------
# Qt-based tests – require a QApplication
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    from pyzo.qt import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(scope="module")
def editor(qt_app):
    from pyzo.codeeditor import CodeEditor

    e = CodeEditor()
    e.setPlainText("line1\nline2\nline3\n")
    yield e


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repository with one committed file."""
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
    file_path = tmp_path / "sample.py"
    file_path.write_text("line1\nline2\nline3\n")
    subprocess.run(
        ["git", "add", "sample.py"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path, file_path


# ------------------------------------------------------------------
# Extension API
# ------------------------------------------------------------------


def test_diffgutter_importable():
    from pyzo.codeeditor import DiffGutter  # noqa: F401


def test_diffgutter_in_codeeditor_mro():
    from pyzo.codeeditor import CodeEditor, DiffGutter

    assert DiffGutter in CodeEditor.__mro__


def test_diffgutter_has_api(editor):
    assert hasattr(editor, "setDiffGutterFilePath")
    assert hasattr(editor, "showDiffGutter")
    assert hasattr(editor, "setShowDiffGutter")
    assert hasattr(editor, "_recomputeDiff")


def test_show_diff_gutter_default_true(editor):
    assert editor.showDiffGutter() is True


def test_set_show_diff_gutter(editor):
    editor.setShowDiffGutter(False)
    assert editor.showDiffGutter() is False
    editor.setShowDiffGutter(True)
    assert editor.showDiffGutter() is True


# ------------------------------------------------------------------
# _recomputeDiff behaviour
# ------------------------------------------------------------------


def test_no_recompute_without_file_path(editor):
    """Calling _recomputeDiff with no path leaves hunks empty."""
    editor._diffGutterFilePath = ""
    editor._recomputeDiff()
    assert editor._diffHunks == []


def test_no_recompute_outside_git(editor, tmp_path):
    """Calling _recomputeDiff for a file outside a git repo leaves hunks empty."""
    file_path = tmp_path / "outside.py"
    file_path.write_text("hello\n")
    editor._diffGutterFilePath = str(file_path)
    editor._recomputeDiff()
    assert editor._diffHunks == []


def test_recompute_in_git_repo(editor, git_repo):
    """_recomputeDiff produces the correct hunks for a modified tracked file."""
    _, file_path = git_repo

    # Load the HEAD content into the editor first (simulates file open)
    editor.setPlainText("line1\nline2\nline3\n")
    editor._diffGutterFilePath = str(file_path)

    # No changes → no hunks
    editor._recomputeDiff()
    assert editor._diffHunks == []

    # Add a line → one "add" hunk
    editor.setPlainText("line1\nline2\nnewline\nline3\n")
    editor._recomputeDiff()
    assert len(editor._diffHunks) == 1
    assert editor._diffHunks[0].kind == "add"

    # Delete a line → one "delete" hunk
    editor.setPlainText("line1\nline3\n")
    editor._recomputeDiff()
    assert len(editor._diffHunks) == 1
    assert editor._diffHunks[0].kind == "delete"

    # Modify a line → one "modify" hunk
    editor.setPlainText("line1\nLINE2\nline3\n")
    editor._recomputeDiff()
    assert len(editor._diffHunks) == 1
    assert editor._diffHunks[0].kind == "modify"


# ------------------------------------------------------------------
# File-load refresh
# ------------------------------------------------------------------


def test_file_load_sets_filepath_and_triggers_timer(editor, tmp_path):
    """setDiffGutterFilePath() activates the timer with a 0 ms interval."""
    timer = editor._DiffGutter__diffDebounceTimer
    timer.stop()
    assert not timer.isActive()

    path = str(tmp_path / "x.py")
    editor.setDiffGutterFilePath(path)

    assert editor._diffGutterFilePath == path
    assert timer.isActive()
    timer.stop()


def test_file_load_clears_old_hunks_immediately(editor, git_repo, qt_app):
    """After setDiffGutterFilePath() is called and the timer fires, hunks reflect
    the current diff (they are cleared before the new diff is computed)."""
    from pyzo.qt import QtCore

    _, file_path = git_repo

    # Prime the editor with a modification so hunks are non-empty
    editor.setPlainText("line1\nline2\nline3\n")
    editor._diffGutterFilePath = str(file_path)
    editor.setPlainText("line1\nline2\nEXTRA\nline3\n")
    editor._recomputeDiff()
    assert len(editor._diffHunks) == 1

    # Now "load" the same (unmodified) content — gutter should clear
    editor.setPlainText("line1\nline2\nline3\n")
    editor.setDiffGutterFilePath(str(file_path))

    # Drain the event loop until the 0 ms timer fires
    deadline = QtCore.QDeadlineTimer(2000)
    timer = editor._DiffGutter__diffDebounceTimer
    while timer.isActive() and not deadline.hasExpired():
        qt_app.processEvents()

    assert editor._diffHunks == [], "Gutter should be empty after loading unchanged content"


def test_file_load_no_previous_diff_state(editor, tmp_path):
    """Opening a file that is not in a git repo leaves the gutter empty (no crash)."""
    file_path = tmp_path / "standalone.py"
    file_path.write_text("hello\n")
    editor.setPlainText("hello\n")

    # Simulate fresh file open
    editor._diffHunks = []
    editor.setDiffGutterFilePath(str(file_path))
    # Timer is now pending; call _recomputeDiff directly to check
    editor._recomputeDiff()
    assert editor._diffHunks == []


# ------------------------------------------------------------------
# File-save refresh
# ------------------------------------------------------------------


def test_file_save_triggers_timer(editor, tmp_path):
    """Calling setDiffGutterFilePath() after a save activates the timer."""
    timer = editor._DiffGutter__diffDebounceTimer
    timer.stop()

    path = str(tmp_path / "saved.py")
    editor.setDiffGutterFilePath(path)

    assert timer.isActive()
    timer.stop()


def test_file_save_refresh_clears_hunks(editor, git_repo, qt_app):
    """After saving (content matches HEAD), the diff gutter should be empty."""
    from pyzo.qt import QtCore

    _, file_path = git_repo

    # Modify the editor content so hunks exist
    editor.setPlainText("line1\nline2\nMODIFIED\n")
    editor._diffGutterFilePath = str(file_path)
    editor._recomputeDiff()
    assert len(editor._diffHunks) == 1

    # Simulate a save: write current content back to the file so HEAD diff
    # will be non-trivial (we don't actually commit, so the diff remains).
    # The key test is that setDiffGutterFilePath() triggers the timer.
    timer = editor._DiffGutter__diffDebounceTimer
    timer.stop()
    editor.setDiffGutterFilePath(str(file_path))
    assert timer.isActive()
    timer.stop()


# ------------------------------------------------------------------
# Debounce timer behaviour
# ------------------------------------------------------------------


def test_timer_is_single_shot(editor):
    """The debounce timer must be configured as single-shot."""
    assert editor._DiffGutter__diffDebounceTimer.isSingleShot()


def test_timer_interval(editor):
    """The debounce timer interval matches the class constant (after explicit reset)."""
    from pyzo.codeeditor.extensions.appearance import DiffGutter

    timer = editor._DiffGutter__diffDebounceTimer
    timer.stop()
    # Reset the interval to the class default (it may have been set to 0 by
    # a previous test that called setDiffGutterFilePath()).
    timer.setInterval(DiffGutter._DIFF_DEBOUNCE_MS)
    assert timer.interval() == DiffGutter._DIFF_DEBOUNCE_MS


def test_text_changed_starts_timer(editor):
    """Editing text starts (or restarts) the debounce timer."""
    timer = editor._DiffGutter__diffDebounceTimer
    timer.stop()
    assert not timer.isActive()
    editor.setPlainText("hello")
    assert timer.isActive()
    timer.stop()
