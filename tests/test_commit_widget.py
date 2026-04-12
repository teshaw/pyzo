"""
Tests for the commit_widget module.

Covers:
* fetch_issues() caching behaviour (no real network call – urllib is patched).
* CommitMessageEdit  #-autocomplete: popup shown, item selection, escape dismissal.
* CommitWidget construction with and without GitHub information.
"""

import sys
import os
import importlib.util
import pathlib

import pytest

# ---------------------------------------------------------------------------
# Ensure PyQt5 is used and the offscreen platform is active so the tests
# can run headlessly.
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_API", "pyqt5")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from pyzo.qt import QtCore, QtGui, QtWidgets

# Import commit_widget directly (bypasses pyzo.tools.__init__ which needs a
# running pyzo instance to provide pyzo.translate).
_CW_PATH = (
    pathlib.Path(__file__).parent.parent
    / "pyzo"
    / "tools"
    / "pyzoFileBrowser"
    / "commit_widget.py"
)
_spec = importlib.util.spec_from_file_location("commit_widget", str(_CW_PATH))
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)


# ---------------------------------------------------------------------------
# Minimal QApplication fixture (one per session is enough)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])
    yield app


# ---------------------------------------------------------------------------
# fetch_issues – cache behaviour
# ---------------------------------------------------------------------------


def test_fetch_issues_uses_cache(monkeypatch):
    """fetch_issues returns cached results without calling urlopen again."""
    cw._issue_cache.clear()
    cw._issue_cache["owner/repo"] = [(1, "cached issue")]

    called = []

    def fake_urlopen(*_a, **_kw):
        called.append(True)

    monkeypatch.setattr(cw.urllib.request, "urlopen", fake_urlopen)

    result = cw.fetch_issues("owner", "repo")
    assert result == [(1, "cached issue")]
    assert not called, "urlopen should not be called when cache is populated"


def test_fetch_issues_network_error_returns_empty(monkeypatch):
    """fetch_issues returns [] on network errors and does NOT cache the failure."""
    cw._issue_cache.clear()

    def fake_urlopen(*_a, **_kw):
        raise OSError("network unreachable")

    monkeypatch.setattr(cw.urllib.request, "urlopen", fake_urlopen)

    result = cw.fetch_issues("bad", "owner")
    assert result == []
    assert "bad/owner" not in cw._issue_cache


def test_fetch_issues_filters_pull_requests(monkeypatch):
    """fetch_issues excludes items that have a 'pull_request' key."""
    cw._issue_cache.clear()

    import io
    import json

    fake_data = json.dumps(
        [
            {"number": 1, "title": "real issue"},
            {"number": 2, "title": "a pull request", "pull_request": {}},
        ]
    ).encode()

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return fake_data

    monkeypatch.setattr(cw.urllib.request, "urlopen", lambda *_a, **_kw: FakeResp())

    result = cw.fetch_issues("o", "r")
    assert result == [(1, "real issue")]
    assert cw._issue_cache["o/r"] == [(1, "real issue")]


# ---------------------------------------------------------------------------
# _IssuePopup
# ---------------------------------------------------------------------------


def test_issue_popup_populate_filters(qapp):
    """_IssuePopup.populate keeps only issues whose number starts with the prefix."""
    popup = cw._IssuePopup(None)
    issues = [(10, "ten"), (11, "eleven"), (20, "twenty")]

    has_matches = popup.populate(issues, "1")
    assert has_matches
    texts = [popup.item(i).text() for i in range(popup.count())]
    assert all("10" in t or "11" in t for t in texts)
    assert not any("20" in t for t in texts)


def test_issue_popup_populate_no_match(qapp):
    """_IssuePopup.populate returns False when nothing matches."""
    popup = cw._IssuePopup(None)
    has_matches = popup.populate([(10, "ten")], "99")
    assert not has_matches
    assert popup.count() == 0


def test_issue_popup_selected_issue_number(qapp):
    """selectedIssueNumber returns the number of the currently highlighted row."""
    popup = cw._IssuePopup(None)
    popup.populate([(42, "the answer")], "4")
    assert popup.selectedIssueNumber() == 42


# ---------------------------------------------------------------------------
# CommitMessageEdit
# ---------------------------------------------------------------------------


def _make_edit(qapp, issues=None):
    if issues is None:
        issues = [(1, "first issue"), (10, "tenth issue"), (11, "eleventh")]
    edit = cw.CommitMessageEdit(None, issues)
    edit.show()
    return edit


def test_hash_alone_does_not_show_popup(qapp):
    """Typing '#' alone (no digits) must not open the popup."""
    edit = _make_edit(qapp)
    QtWidgets.QApplication.processEvents()

    # Simulate typing '#'
    edit.setPlainText("")
    cursor = edit.textCursor()
    cursor.insertText("#")
    edit.setTextCursor(cursor)

    # Manually fire keyPressEvent with '#'
    key_event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_NumberSign,
        QtCore.Qt.KeyboardModifier.NoModifier,
        "#",
    )
    edit.keyPressEvent(key_event)
    QtWidgets.QApplication.processEvents()

    assert not edit._popup.isVisible()


def test_hash_digit_shows_popup(qapp):
    """Typing '#1' should make the popup visible."""
    edit = _make_edit(qapp)
    edit.setPlainText("")
    edit._hash_pos = None

    # Type '#'
    hash_event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_NumberSign,
        QtCore.Qt.KeyboardModifier.NoModifier,
        "#",
    )
    edit.keyPressEvent(hash_event)
    # Now hash_pos is set; type '1'
    one_event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_1,
        QtCore.Qt.KeyboardModifier.NoModifier,
        "1",
    )
    edit.keyPressEvent(one_event)
    QtWidgets.QApplication.processEvents()

    assert edit._popup.isVisible()


def test_escape_dismisses_popup(qapp):
    """Pressing Escape while the popup is visible must hide it."""
    edit = _make_edit(qapp)
    # Force popup open
    edit._hash_pos = 1
    edit._popup.populate(edit._issues, "1")
    edit._popup.show()
    assert edit._popup.isVisible()

    esc_event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
        "",
    )
    edit.keyPressEvent(esc_event)
    QtWidgets.QApplication.processEvents()

    assert not edit._popup.isVisible()
    assert edit._hash_pos is None


def test_enter_inserts_issue(qapp):
    """Pressing Enter/Return while the popup is visible inserts the selected issue."""
    issues = [(42, "the answer")]
    edit = _make_edit(qapp, issues=issues)
    edit.setPlainText("#4")
    cursor = edit.textCursor()
    cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
    edit.setTextCursor(cursor)

    # Position: '#' is at index 0, digits start at index 1
    edit._hash_pos = 1
    edit._popup.populate(issues, "4")
    edit._popup.show()

    enter_event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Return,
        QtCore.Qt.KeyboardModifier.NoModifier,
        "\r",
    )
    edit.keyPressEvent(enter_event)
    QtWidgets.QApplication.processEvents()

    assert not edit._popup.isVisible()
    assert edit.toPlainText() == "#42"


# ---------------------------------------------------------------------------
# CommitWidget construction
# ---------------------------------------------------------------------------


def test_commit_widget_construction_no_github(qapp, tmp_path):
    """CommitWidget can be constructed when owner/repo are None."""
    # Initialise a throwaway git repo so repo_root is valid
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    dlg = cw.CommitWidget(None, str(tmp_path), None, None)
    assert dlg is not None
    assert dlg.commitMessage() == ""
    dlg.close()


def test_commit_widget_uses_cached_issues(monkeypatch, qapp, tmp_path):
    """CommitWidget passes cached issues to the message editor."""
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    cw._issue_cache.clear()
    cw._issue_cache["myowner/myrepo"] = [(7, "lucky seven")]

    dlg = cw.CommitWidget(None, str(tmp_path), "myowner", "myrepo")
    assert dlg._edit._issues == [(7, "lucky seven")]
    dlg.close()
