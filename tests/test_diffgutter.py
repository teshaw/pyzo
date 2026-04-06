"""
Tests for the DiffGutter extension.

Covers:
- Hunk dataclass construction
- _parse_hunks() parsing of unified diff headers
- DiffGutter._recomputeDiff() integration (requires a Qt application and a
  temporary git repository)
- 500 ms QTimer debounce: textChanged restarts the timer; setDiffGutterFilePath
  triggers an immediate (0 ms) recompute
"""

import os
import subprocess
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Hunk and _parse_hunks – pure Python, no Qt needed
# ---------------------------------------------------------------------------
from pyzo.codeeditor.extensions.appearance import Hunk, _parse_hunks


class TestHunk:
    def test_fields(self):
        h = Hunk(old_start=5, old_count=3, new_start=5, new_count=4, kind="modify")
        assert h.old_start == 5
        assert h.old_count == 3
        assert h.new_start == 5
        assert h.new_count == 4
        assert h.kind == "modify"

    def test_equality(self):
        h1 = Hunk(1, 2, 3, 4, "add")
        h2 = Hunk(1, 2, 3, 4, "add")
        assert h1 == h2

    def test_inequality(self):
        h1 = Hunk(1, 2, 3, 4, "add")
        h2 = Hunk(1, 2, 3, 4, "modify")
        assert h1 != h2


class TestParseHunks:
    def test_empty(self):
        assert _parse_hunks([]) == []

    def test_add_hunk(self):
        # @@ -10,0 +11,3 @@ means 0 lines removed → pure addition
        lines = ["@@ -10,0 +11,3 @@\n"]
        (h,) = _parse_hunks(lines)
        assert h.old_start == 10
        assert h.old_count == 0
        assert h.new_start == 11
        assert h.new_count == 3
        assert h.kind == "add"

    def test_delete_hunk(self):
        # @@ -5,2 +5,0 @@ means 0 new lines → pure deletion
        lines = ["@@ -5,2 +5,0 @@\n"]
        (h,) = _parse_hunks(lines)
        assert h.old_start == 5
        assert h.old_count == 2
        assert h.new_start == 5
        assert h.new_count == 0
        assert h.kind == "delete"

    def test_modify_hunk(self):
        lines = ["@@ -3,4 +3,5 @@\n"]
        (h,) = _parse_hunks(lines)
        assert h.old_start == 3
        assert h.old_count == 4
        assert h.new_start == 3
        assert h.new_count == 5
        assert h.kind == "modify"

    def test_implicit_count_one(self):
        # When the comma and count are absent the count is implicitly 1
        lines = ["@@ -1 +1 @@\n"]
        (h,) = _parse_hunks(lines)
        assert h.old_count == 1
        assert h.new_count == 1
        assert h.kind == "modify"

    def test_non_hunk_lines_ignored(self):
        lines = [
            "--- a/foo.py\n",
            "+++ b/foo.py\n",
            "@@ -1,3 +1,3 @@\n",
            " unchanged\n",
            "-removed\n",
            "+added\n",
        ]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 1

    def test_multiple_hunks(self):
        lines = [
            "@@ -1,2 +1,3 @@\n",
            "@@ -10,0 +11,1 @@\n",
            "@@ -20,3 +21,0 @@\n",
        ]
        hunks = _parse_hunks(lines)
        assert len(hunks) == 3
        assert hunks[0].kind == "modify"
        assert hunks[1].kind == "add"
        assert hunks[2].kind == "delete"


# ---------------------------------------------------------------------------
# DiffGutter widget tests – require a Qt application
# ---------------------------------------------------------------------------


def _get_qt_app():
    """Return an existing QApplication or create one."""
    try:
        from pyzo.qt import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication(sys.argv[:1])
        return app
    except Exception:
        return None


@pytest.fixture(scope="module")
def qt_app():
    app = _get_qt_app()
    if app is None:
        pytest.skip("Qt not available")
    return app


@pytest.fixture()
def editor(qt_app):
    """Return a minimal CodeEditor instance that includes DiffGutter."""
    from pyzo.codeeditor import CodeEditor

    ed = CodeEditor()
    yield ed
    ed.close()


@pytest.fixture()
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
    file_path = tmp_path / "hello.py"
    file_path.write_text("line1\nline2\nline3\n")
    subprocess.run(
        ["git", "add", "hello.py"], cwd=str(tmp_path), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path, file_path


class TestDiffGutterWidget:
    def test_initial_state(self, editor):
        """The gutter starts with no hunks and no file path."""
        assert editor._diffHunks == []
        assert editor._diffGutterFilePath == ""

    def test_show_diff_gutter_default_true(self, editor):
        assert editor.showDiffGutter() is True

    def test_set_show_diff_gutter(self, editor):
        editor.setShowDiffGutter(False)
        assert editor.showDiffGutter() is False
        editor.setShowDiffGutter(True)
        assert editor.showDiffGutter() is True

    def test_no_recompute_without_file_path(self, editor):
        """Calling _recomputeDiff with no path leaves hunks empty."""
        editor._diffGutterFilePath = ""
        editor._recomputeDiff()
        assert editor._diffHunks == []

    def test_no_recompute_outside_git(self, editor, tmp_path):
        """Calling _recomputeDiff for a file outside a git repo leaves hunks empty."""
        file_path = tmp_path / "outside.py"
        file_path.write_text("hello\n")
        editor._diffGutterFilePath = str(file_path)
        editor._recomputeDiff()
        assert editor._diffHunks == []

    def test_timer_is_single_shot(self, editor):
        """The debounce timer must be configured as single-shot."""
        assert editor._DiffGutter__diffDebounceTimer.isSingleShot()

    def test_timer_interval(self, editor):
        """The debounce timer interval must be 500 ms."""
        assert editor._DiffGutter__diffDebounceTimer.interval() == 500

    def test_text_changed_starts_timer(self, editor):
        """Editing text starts (or restarts) the debounce timer."""
        timer = editor._DiffGutter__diffDebounceTimer
        timer.stop()
        assert not timer.isActive()
        editor.setPlainText("hello")
        assert timer.isActive()
        timer.stop()

    def test_set_file_path_triggers_zero_ms_timer(self, editor, tmp_path):
        """setDiffGutterFilePath should restart the timer with 0 ms interval."""
        from pyzo.qt import QtWidgets

        timer = editor._DiffGutter__diffDebounceTimer
        timer.stop()
        editor.setDiffGutterFilePath(str(tmp_path / "x.py"))
        # After calling setDiffGutterFilePath the timer should be active (0 ms)
        assert timer.isActive()
        timer.stop()

    def test_recompute_in_git_repo(self, editor, git_repo):
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
