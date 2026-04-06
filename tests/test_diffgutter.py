"""Tests for the DiffGutter codeeditor extension."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyqt5")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def editor():
    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from pyzo.codeeditor import CodeEditor

    e = CodeEditor()
    e.setPlainText("line1\nline2\nline3\nline4\nline5\n")
    yield e


def test_diffgutter_importable():
    from pyzo.codeeditor import DiffGutter  # noqa: F401


def test_diffgutter_in_codeeditor_mro():
    from pyzo.codeeditor import CodeEditor, DiffGutter

    assert DiffGutter in CodeEditor.__mro__


def test_diffgutter_has_api(editor):
    assert hasattr(editor, "setDiffData")
    assert hasattr(editor, "showDiffGutter")
    assert hasattr(editor, "setShowDiffGutter")


def test_show_diff_gutter_default_true(editor):
    assert editor.showDiffGutter() is True


def test_set_show_diff_gutter(editor):
    editor.setShowDiffGutter(False)
    assert editor.showDiffGutter() is False
    editor.setShowDiffGutter(True)
    assert editor.showDiffGutter() is True


def test_set_diff_data_stores_data(editor):
    data = {1: "added", 2: "modified", 3: "deleted"}
    editor.setDiffData(data)
    assert editor._diffData == data


def test_set_diff_data_clear_with_none(editor):
    editor.setDiffData({1: "added"})
    editor.setDiffData(None)
    assert editor._diffData == {}


def test_set_diff_data_clear_with_empty_dict(editor):
    editor.setDiffData({2: "modified"})
    editor.setDiffData({})
    assert editor._diffData == {}


def test_set_diff_data_does_not_mutate_input(editor):
    data = {1: "added"}
    editor.setDiffData(data)
    data[2] = "modified"
    assert 2 not in editor._diffData
