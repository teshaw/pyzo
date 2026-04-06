"""
Tests for DiffGutter / HunkPopup and the hunk-parsing helpers in githelper.
"""
import importlib
import importlib.util
import os
import sys
import types
import pathlib
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Load githelper without importing the full pyzo package
# ---------------------------------------------------------------------------

_REPO = pathlib.Path(__file__).parent.parent
_GITHELPER_PATH = _REPO / "pyzo" / "tools" / "pyzoFileBrowser" / "githelper.py"

spec = importlib.util.spec_from_file_location("githelper", _GITHELPER_PATH)
githelper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(githelper)

Hunk = githelper.Hunk
_parse_hunks = githelper._parse_hunks
get_diff_hunks = githelper.get_diff_hunks


# ===========================================================================
# Hunk / _parse_hunks unit tests  (no Qt required)
# ===========================================================================

SIMPLE_DIFF = textwrap.dedent("""\
    diff --git a/foo.py b/foo.py
    index abc1234..def5678 100644
    --- a/foo.py
    +++ b/foo.py
    @@ -1,4 +1,5 @@
     line1
    -line2
    +line2 modified
    +line2b added
     line3
     line4
    @@ -10,3 +11,2 @@
     lineA
    -lineB
     lineC
""")


def test_parse_hunks_count():
    hunks = _parse_hunks(SIMPLE_DIFF)
    assert len(hunks) == 2


def test_parse_hunks_header():
    hunks = _parse_hunks(SIMPLE_DIFF)
    assert hunks[0].header.startswith("@@")
    assert "-1,4" in hunks[0].header
    assert "+1,5" in hunks[0].header


def test_parse_hunks_old_new_start():
    hunks = _parse_hunks(SIMPLE_DIFF)
    assert hunks[0].old_start == 1
    assert hunks[0].new_start == 1
    assert hunks[0].old_count == 4
    assert hunks[0].new_count == 5
    assert hunks[1].old_start == 10
    assert hunks[1].new_start == 11


def test_parse_hunks_lines():
    hunks = _parse_hunks(SIMPLE_DIFF)
    hunk = hunks[0]
    # Header line + 6 body lines
    assert hunk.lines[0].startswith("@@")
    added = [l for l in hunk.lines[1:] if l.startswith("+")]
    removed = [l for l in hunk.lines[1:] if l.startswith("-")]
    assert len(added) == 2
    assert len(removed) == 1


def test_hunk_text():
    hunks = _parse_hunks(SIMPLE_DIFF)
    text = hunks[0].text
    assert text.startswith("@@")
    assert "+line2 modified" in text


def test_hunk_new_line_range():
    hunks = _parse_hunks(SIMPLE_DIFF)
    first, last = hunks[0].new_line_range()
    assert first == 1
    assert last == 5  # new_start=1, new_count=5


def test_parse_hunks_empty():
    assert _parse_hunks("") == []
    assert _parse_hunks("not a diff at all\n") == []


def test_parse_hunks_no_count():
    """Hunk header with no comma (count defaults to 1)."""
    diff = textwrap.dedent("""\
        @@ -5 +5 @@
        -old
        +new
    """)
    hunks = _parse_hunks(diff)
    assert len(hunks) == 1
    assert hunks[0].old_count == 1
    assert hunks[0].new_count == 1


def test_get_diff_hunks_non_git_path(tmp_path):
    """get_diff_hunks returns [] for a file not in any git repo."""
    f = tmp_path / "plain.py"
    f.write_text("hello\n")
    result = get_diff_hunks(str(f))
    assert result == []


def test_hunk_color_classification():
    """_parse_hunks assigns the right colour via hunk content."""
    # We test through the hunk's line content, not the Qt colour object directly
    add_only = textwrap.dedent("""\
        @@ -5,0 +5,2 @@
        +new line 1
        +new line 2
    """)
    del_only = textwrap.dedent("""\
        @@ -5,2 +5,0 @@
        -old line 1
        -old line 2
    """)
    mixed = textwrap.dedent("""\
        @@ -5,1 +5,1 @@
        -old
        +new
    """)
    hunks_add = _parse_hunks(add_only)
    hunks_del = _parse_hunks(del_only)
    hunks_mix = _parse_hunks(mixed)

    def has_add(h):
        return any(l.startswith("+") for l in h.lines[1:])

    def has_del(h):
        return any(l.startswith("-") for l in h.lines[1:])

    assert has_add(hunks_add[0]) and not has_del(hunks_add[0])
    assert has_del(hunks_del[0]) and not has_add(hunks_del[0])
    assert has_add(hunks_mix[0]) and has_del(hunks_mix[0])


# ===========================================================================
# Qt widget tests
# ===========================================================================

@pytest.fixture(scope="session")
def qapp():
    """Provide a QApplication for the entire test session."""
    os.environ.setdefault("QT_API", "pyqt5")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Ensure pyzo is importable as a real package
    repo_root = str(_REPO)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from pyzo.qt import QtWidgets, QtCore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return app


def _load_diffgutter():
    """Import diffgutter, injecting githelper into its package namespace."""
    pkg_name = "pyzo.tools.pyzoFileBrowser"
    # Ensure the package stub exists so relative imports work
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_REPO / "pyzo" / "tools" / "pyzoFileBrowser")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    # Inject already-loaded githelper
    sys.modules[f"{pkg_name}.githelper"] = githelper

    dg_path = _REPO / "pyzo" / "tools" / "pyzoFileBrowser" / "diffgutter.py"
    spec2 = importlib.util.spec_from_file_location(
        f"{pkg_name}.diffgutter", dg_path,
    )
    dg = importlib.util.module_from_spec(spec2)
    dg.__package__ = pkg_name
    spec2.loader.exec_module(dg)
    return dg


@pytest.fixture(scope="session")
def diffgutter_mod(qapp):
    return _load_diffgutter()


def test_hunkpopup_creation(qapp, diffgutter_mod):
    """HunkPopup can be created without raising."""
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    popup = HunkPopup(None, hunks[0], "/fake/file.py")
    assert popup is not None
    popup.close()


def test_hunkpopup_has_buttons(qapp, diffgutter_mod):
    """HunkPopup exposes Stage, Revert and Dismiss buttons."""
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    popup = HunkPopup(None, hunks[0], "/fake/file.py")
    assert popup._btn_stage is not None
    assert popup._btn_revert is not None
    assert popup._btn_dismiss is not None
    popup.close()


def test_hunkpopup_shows_diff_text(qapp, diffgutter_mod):
    """HunkPopup text area contains the hunk's unified diff."""
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    hunk = hunks[0]
    popup = HunkPopup(None, hunk, "/fake/file.py")
    displayed = popup._text.toPlainText()
    assert "+line2 modified" in displayed
    assert "-line2" in displayed
    popup.close()


def test_hunkpopup_dismiss_closes(qapp, diffgutter_mod):
    """Clicking Dismiss hides the popup."""
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    popup = HunkPopup(None, hunks[0], "/fake/file.py")
    popup.show()
    popup._btn_dismiss.click()
    assert not popup.isVisible()


def test_hunkpopup_escape_closes(qapp, diffgutter_mod):
    """Pressing Escape hides the popup."""
    from pyzo.qt import QtCore, QtGui
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    popup = HunkPopup(None, hunks[0], "/fake/file.py")
    popup.show()
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    popup.keyPressEvent(event)
    assert not popup.isVisible()


def test_hunkpopup_stage_signal(qapp, diffgutter_mod):
    """Clicking Stage hunk emits stageRequested with the hunk."""
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    hunk = hunks[0]
    popup = HunkPopup(None, hunk, "/fake/file.py")

    received = []
    popup.stageRequested.connect(received.append)
    popup._btn_stage.click()
    assert received == [hunk]


def test_hunkpopup_revert_signal(qapp, diffgutter_mod):
    """Clicking Revert hunk emits revertRequested with the hunk."""
    HunkPopup = diffgutter_mod.HunkPopup
    hunks = _parse_hunks(SIMPLE_DIFF)
    hunk = hunks[0]
    popup = HunkPopup(None, hunk, "/fake/file.py")

    received = []
    popup.revertRequested.connect(received.append)
    popup._btn_revert.click()
    assert received == [hunk]


def test_diffgutter_creation(qapp, diffgutter_mod):
    """DiffGutter can be instantiated without a real file."""
    from pyzo.qt import QtWidgets
    DiffGutter = diffgutter_mod.DiffGutter
    editor = QtWidgets.QPlainTextEdit()
    gutter = DiffGutter(editor, filepath=None)
    assert gutter._hunks == []
    editor.close()


def test_diffgutter_refresh_nongit(qapp, diffgutter_mod, tmp_path):
    """DiffGutter.refresh() with a non-git file sets _hunks to []."""
    from pyzo.qt import QtWidgets
    DiffGutter = diffgutter_mod.DiffGutter
    f = tmp_path / "test.py"
    f.write_text("hello\n")
    editor = QtWidgets.QPlainTextEdit()
    gutter = DiffGutter(editor, filepath=str(f))
    assert gutter._hunks == []
    editor.close()
