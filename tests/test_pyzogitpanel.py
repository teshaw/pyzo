"""Tests for pyzo/tools/pyzoGitPanel/__init__.py

Run with:
    QT_API=pyqt5 QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pyzogitpanel.py -v
"""

import sys
import os
import importlib
import importlib.util
import types
import unittest.mock as mock

import pytest

# ---------------------------------------------------------------------------
# Qt / pyzo bootstrap (must happen before importing the tool module)
# ---------------------------------------------------------------------------

os.environ.setdefault("QT_API", "pyqt5")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pyzo.qt import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# Provide a minimal pyzo.config stub so PyzoGitPanel.__init__ doesn't crash.
import pyzo  # noqa: E402

# Stub pyzo.translate (only set by pyzo.start(); not available in bare import)
if not hasattr(pyzo, "translate"):
    pyzo.translate = lambda *args: args[-1]

# ---------------------------------------------------------------------------
# Pre-load githelper directly to avoid pulling in the full pyzoFileBrowser
# package (which needs pyzo.core and a running app).
# ---------------------------------------------------------------------------

_GITHELPER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "pyzo",
        "tools",
        "pyzoFileBrowser",
        "githelper.py",
    )
)

# Register parent-package stubs so Python doesn't try to import them.
if "pyzo.tools" not in sys.modules:
    sys.modules["pyzo.tools"] = types.ModuleType("pyzo.tools")
if "pyzo.tools.pyzoFileBrowser" not in sys.modules:
    _fb_stub = types.ModuleType("pyzo.tools.pyzoFileBrowser")
    sys.modules["pyzo.tools.pyzoFileBrowser"] = _fb_stub

# Load githelper.py directly.
_gh_spec = importlib.util.spec_from_file_location(
    "pyzo.tools.pyzoFileBrowser.githelper", _GITHELPER_PATH
)
_gh_mod = importlib.util.module_from_spec(_gh_spec)
sys.modules["pyzo.tools.pyzoFileBrowser.githelper"] = _gh_mod
_gh_spec.loader.exec_module(_gh_mod)

GitStatus = _gh_mod.GitStatus

_TOOL_ID = "pyzogitpanel"

if not hasattr(pyzo, "config") or pyzo.config is None:
    from pyzo.util import zon as ssdf

    pyzo.config = ssdf.new()

if not hasattr(pyzo.config, "tools") or pyzo.config.tools is None:
    from pyzo.util import zon as ssdf

    pyzo.config.tools = ssdf.new()

if _TOOL_ID not in pyzo.config.tools:
    from pyzo.util import zon as ssdf

    pyzo.config.tools[_TOOL_ID] = ssdf.new()

if not hasattr(pyzo.config, "view") or pyzo.config.view is None:
    from pyzo.util import zon as ssdf

    pyzo.config.view = ssdf.new()

if not hasattr(pyzo.config.view, "widgetMargin"):
    pyzo.config.view.widgetMargin = 2

# ---------------------------------------------------------------------------
# Load the tool module in isolation (bypass pyzo.tools package __init__)
# ---------------------------------------------------------------------------

_INIT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "pyzo",
        "tools",
        "pyzoGitPanel",
        "__init__.py",
    )
)

_spec = importlib.util.spec_from_file_location(
    "pyzo.tools.pyzoGitPanel",
    _INIT_PATH,
    submodule_search_locations=[os.path.dirname(_INIT_PATH)],
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["pyzo.tools.pyzoGitPanel"] = _mod
_spec.loader.exec_module(_mod)

ChangesModel = _mod.ChangesModel
CommitWidget = _mod.CommitWidget
DiffHighlighter = _mod.DiffHighlighter
DiffView = _mod.DiffView
PyzoGitPanel = _mod.PyzoGitPanel
_PATH_ROLE = _mod._PATH_ROLE
_STAGED_ROLE = _mod._STAGED_ROLE


# ---------------------------------------------------------------------------
# ChangesModel tests
# ---------------------------------------------------------------------------


def test_changes_model_initial_structure():
    """Model starts with exactly two top-level rows: Staged and Unstaged."""
    model = ChangesModel()
    assert model.rowCount() == 2
    assert model.item(0).text() == "Staged"
    assert model.item(1).text() == "Unstaged"


def test_changes_model_header_labels():
    model = ChangesModel()
    assert model.horizontalHeaderItem(0).text() == "File"
    assert model.horizontalHeaderItem(1).text() == "Status"


def test_changes_model_update_none_clears():
    """update(None) empties both sections."""
    model = ChangesModel()
    model.update(None)
    assert model.item(0).rowCount() == 0
    assert model.item(1).rowCount() == 0


def test_changes_model_update_staged_file():
    """A file modified in the index ('M ') appears only under Staged."""
    root = "/fake/repo"
    status = GitStatus(root, {"/fake/repo/hello.py": "M "})
    model = ChangesModel()
    model.update(status)

    assert model.staged_count() == 1
    assert model.item(1).rowCount() == 0  # nothing unstaged


def test_changes_model_update_unstaged_file():
    """A file modified in the working tree (' M') appears only under Unstaged."""
    root = "/fake/repo"
    status = GitStatus(root, {"/fake/repo/hello.py": " M"})
    model = ChangesModel()
    model.update(status)

    assert model.staged_count() == 0
    assert model.item(1).rowCount() == 1


def test_changes_model_update_both_staged_and_unstaged():
    """'MM' means the file appears in both sections."""
    root = "/fake/repo"
    status = GitStatus(root, {"/fake/repo/hello.py": "MM"})
    model = ChangesModel()
    model.update(status)

    assert model.staged_count() == 1
    assert model.item(1).rowCount() == 1


def test_changes_model_update_untracked():
    """Untracked ('??') files appear under Unstaged, not Staged."""
    root = "/fake/repo"
    status = GitStatus(root, {"/fake/repo/new.py": "??"})
    model = ChangesModel()
    model.update(status)

    assert model.staged_count() == 0
    assert model.item(1).rowCount() == 1

    unstaged_child = model.item(1).child(0)
    assert unstaged_child.data(_PATH_ROLE) == "/fake/repo/new.py"
    assert unstaged_child.data(_STAGED_ROLE) is False


def test_changes_model_item_roles():
    """File items carry _PATH_ROLE and _STAGED_ROLE data."""
    root = "/fake/repo"
    status = GitStatus(root, {"/fake/repo/a.py": "A "})
    model = ChangesModel()
    model.update(status)

    staged_child = model.item(0).child(0)
    assert staged_child.data(_PATH_ROLE) == "/fake/repo/a.py"
    assert staged_child.data(_STAGED_ROLE) is True


def test_changes_model_multiple_files():
    """Multiple files are placed in the correct sections."""
    root = "/fake/repo"
    status = GitStatus(
        root,
        {
            "/fake/repo/staged.py": "A ",
            "/fake/repo/unstaged.py": " M",
            "/fake/repo/both.py": "MM",
            "/fake/repo/untracked.txt": "??",
        },
    )
    model = ChangesModel()
    model.update(status)

    # staged.py (A) and both.py (M) → 2 staged
    assert model.staged_count() == 2
    # unstaged.py (M), both.py (M), untracked.txt (?) → 3 unstaged
    assert model.item(1).rowCount() == 3


# ---------------------------------------------------------------------------
# DiffView tests
# ---------------------------------------------------------------------------


def test_diff_view_creates():
    view = DiffView()
    assert view is not None
    assert view.isReadOnly()


def test_diff_view_set_diff():
    diff = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n"
    view = DiffView()
    view.setDiff(diff)
    assert view.toPlainText() == diff


def test_diff_view_set_diff_clears_previous():
    view = DiffView()
    view.setDiff("first content")
    view.setDiff("second content")
    assert view.toPlainText() == "second content"


def test_diff_view_empty_string():
    view = DiffView()
    view.setDiff("some text")
    view.setDiff("")
    assert view.toPlainText() == ""


# ---------------------------------------------------------------------------
# DiffHighlighter tests
# ---------------------------------------------------------------------------


def test_diff_highlighter_creates():
    doc = QtGui.QTextDocument()
    highlighter = DiffHighlighter(doc)
    assert highlighter is not None


# ---------------------------------------------------------------------------
# CommitWidget tests
# ---------------------------------------------------------------------------


def test_commit_widget_creates():
    widget = CommitWidget()
    assert widget is not None


def test_commit_widget_has_message_editor():
    widget = CommitWidget()
    assert isinstance(widget._msg_edit, QtWidgets.QPlainTextEdit)


def test_commit_widget_has_commit_button():
    widget = CommitWidget()
    assert isinstance(widget._commit_btn, QtWidgets.QPushButton)


def test_commit_widget_set_repo_root():
    widget = CommitWidget()
    widget.setRepoRoot("/some/path")
    assert widget._repo_root == "/some/path"


def test_commit_widget_empty_message_shows_error(monkeypatch):
    """Clicking Commit with an empty message sets a status label text."""
    widget = CommitWidget()
    widget.setRepoRoot("/fake/repo")
    widget._msg_edit.setPlainText("")
    widget._do_commit()
    assert widget._status_label.text() != ""


def test_commit_widget_no_repo_shows_error():
    widget = CommitWidget()
    widget._msg_edit.setPlainText("My commit message")
    # repo_root is None by default
    widget._do_commit()
    assert widget._status_label.text() != ""


# ---------------------------------------------------------------------------
# PyzoGitPanel smoke tests
# ---------------------------------------------------------------------------


def test_pyzo_git_panel_creates():
    """PyzoGitPanel should instantiate without raising."""
    panel = PyzoGitPanel(None)
    assert panel is not None
    panel._timer.stop()
    panel.close()


def test_pyzo_git_panel_has_branch_label():
    panel = PyzoGitPanel(None)
    panel._timer.stop()
    assert isinstance(panel._branch_label, QtWidgets.QLabel)
    panel.close()


def test_pyzo_git_panel_has_splitter():
    panel = PyzoGitPanel(None)
    panel._timer.stop()
    assert isinstance(panel._splitter, QtWidgets.QSplitter)
    panel.close()


def test_pyzo_git_panel_has_diff_view():
    panel = PyzoGitPanel(None)
    panel._timer.stop()
    assert isinstance(panel._diff_view, DiffView)
    panel.close()


def test_pyzo_git_panel_has_commit_widget():
    panel = PyzoGitPanel(None)
    panel._timer.stop()
    assert isinstance(panel._commit_widget, CommitWidget)
    panel.close()


def test_pyzo_git_panel_commit_widget_hidden_initially(monkeypatch, tmp_path):
    """CommitWidget is hidden when there are no staged files (non-git dir)."""
    monkeypatch.chdir(tmp_path)  # ensure not inside a git repo
    panel = PyzoGitPanel(None)
    panel._timer.stop()
    # In a non-git directory the commit widget must be hidden
    assert not panel._commit_widget.isVisible()
    panel.close()


def test_pyzo_git_panel_splitter_default_ratio():
    """Default splitter calls setSizes([40, 60]) (stored in config is empty)."""
    # Clear any persisted sizes so defaults apply
    cfg = pyzo.config.tools[_TOOL_ID]
    for key in ("splitter_left", "splitter_right"):
        if key in cfg:
            del cfg[key]

    captured = []
    original_set_sizes = QtWidgets.QSplitter.setSizes

    def mock_set_sizes(self, sizes):
        captured.append(list(sizes))
        original_set_sizes(self, sizes)

    with mock.patch.object(QtWidgets.QSplitter, "setSizes", mock_set_sizes):
        panel = PyzoGitPanel(None)
        panel._timer.stop()
        panel.close()

    assert captured and captured[0] == [40, 60]
