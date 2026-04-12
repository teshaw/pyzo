"""
Diff gutter extension for the code editor.

Displays a narrow coloured marker strip to the left of the line-number margin
indicating which lines have been added, modified, or removed relative to the
current git HEAD commit.

This module provides:
    DiffGutter  – extension mixin to be mixed into the CodeEditor class.

Gracefully no-ops when git is not installed or the file is not part of a
git repository.
"""

import functools
import os
import subprocess

from ..qt import QtGui, QtCore, QtWidgets

Qt = QtCore.Qt

# Width of the gutter in pixels
_GUTTER_WIDTH = 6


@functools.lru_cache(maxsize=1)
def _git_available():
    """Return True if the ``git`` executable can be found on PATH."""
    try:
        subprocess.run(
            ["git", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _file_in_git_repo(filepath):
    """Return True if *filepath* is tracked by a git repository."""
    if not filepath:
        return False
    dirpath = filepath if os.path.isdir(filepath) else os.path.dirname(filepath)
    if not dirpath:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", dirpath, "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


class DiffGutter:
    """Extension mixin that adds a 6 px diff-gutter widget to the left of the
    line-number margin.

    The gutter currently acts as a placeholder – no diff markers are painted
    yet.  When git is not installed or the open file does not belong to a git
    repository the gutter is simply left blank.
    """

    class __DiffGutterArea(QtWidgets.QWidget):
        """Widget responsible for drawing the diff gutter."""

        def __init__(self, codeEditor):
            super().__init__(codeEditor)

        def paintEvent(self, event):
            # Placeholder: no diff markers painted yet.
            pass

    def __init__(self, *args, **kwds):
        self.__diffGutterArea = None
        self.__leftMarginHandle = None
        super().__init__(*args, **kwds)
        # Create the gutter widget and claim a left-bar margin slot.
        self.__diffGutterArea = self.__DiffGutterArea(self)
        self.__leftMarginHandle = self._setLeftBarMargin(
            self.__leftMarginHandle, _GUTTER_WIDTH
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        m = self._getMarginBeforeLeftBar(self.__leftMarginHandle)
        self.__diffGutterArea.setGeometry(
            rect.x() + m, rect.y(), _GUTTER_WIDTH, rect.height()
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        self.__diffGutterArea.update(0, 0, _GUTTER_WIDTH, self.height())
