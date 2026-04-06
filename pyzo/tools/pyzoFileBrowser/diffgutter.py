"""
DiffGutter and HunkPopup widgets for pyzo.

DiffGutter is a narrow left-margin widget that paints coloured bands
next to editor lines that were added or modified compared to HEAD.
Clicking a band opens a floating :class:`HunkPopup` showing the raw
unified-diff text for that hunk and offering quick-action buttons
(Stage hunk, Revert hunk, Dismiss).
"""

import os
import subprocess

from pyzo.qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt

from .githelper import get_diff_hunks, get_git_root, Hunk


# ---------------------------------------------------------------------------
# Colours used in the gutter
# ---------------------------------------------------------------------------

_COLOR_ADDED = QtGui.QColor(80, 180, 80)       # green  – new lines
_COLOR_MODIFIED = QtGui.QColor(220, 140, 30)   # amber  – changed lines
_COLOR_DELETED = QtGui.QColor(200, 80, 80)     # red    – deletion marker


def _hunk_color(hunk):
    """Return the QColor to use for *hunk*'s gutter band."""
    has_add = any(l.startswith("+") for l in hunk.lines[1:])
    has_del = any(l.startswith("-") for l in hunk.lines[1:])
    if has_add and has_del:
        return _COLOR_MODIFIED
    if has_add:
        return _COLOR_ADDED
    return _COLOR_DELETED


# ---------------------------------------------------------------------------
# HunkPopup
# ---------------------------------------------------------------------------

class HunkPopup(QtWidgets.QFrame):
    """Floating popup that shows a unified-diff hunk and quick-action buttons.

    Signals
    -------
    stageRequested(hunk)
        Emitted when the user clicks **Stage hunk**.
    revertRequested(hunk)
        Emitted when the user clicks **Revert hunk**.

    Parameters
    ----------
    parent : QWidget
        The parent widget (typically the editor or gutter).
    hunk : Hunk
        The diff hunk to display.
    filepath : str
        Absolute path to the file the hunk belongs to.
    """

    stageRequested = QtCore.Signal(object)
    revertRequested = QtCore.Signal(object)

    def __init__(self, parent, hunk, filepath):
        super().__init__(parent, Qt.WindowType.Popup)
        self._hunk = hunk
        self._filepath = filepath

        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        self.setLineWidth(1)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ---- diff text area ----
        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        font = QtGui.QFont("Monospace", 9)
        font.setStyleHint(QtGui.QFont.StyleHint.TypeWriter)
        self._text.setFont(font)
        self._text.setPlainText(self._hunk.text)
        self._apply_diff_highlighting()
        self._text.setFixedHeight(min(300, 18 * len(self._hunk.lines) + 8))
        layout.addWidget(self._text)

        # ---- buttons ----
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(4)

        self._btn_stage = QtWidgets.QPushButton("Stage hunk")
        self._btn_stage.setToolTip("Stage this hunk to the index")
        self._btn_stage.clicked.connect(self._on_stage)
        btn_layout.addWidget(self._btn_stage)

        self._btn_revert = QtWidgets.QPushButton("Revert hunk")
        self._btn_revert.setToolTip("Discard working-tree changes in this hunk")
        self._btn_revert.clicked.connect(self._on_revert)
        btn_layout.addWidget(self._btn_revert)

        btn_layout.addStretch()

        self._btn_dismiss = QtWidgets.QPushButton("Dismiss")
        self._btn_dismiss.clicked.connect(self.close)
        btn_layout.addWidget(self._btn_dismiss)

        layout.addLayout(btn_layout)
        self.adjustSize()

    def _apply_diff_highlighting(self):
        """Colour-highlight added/removed lines in the diff text area."""
        doc = self._text.document()
        cursor = QtGui.QTextCursor(doc)
        fmt_add = QtGui.QTextCharFormat()
        fmt_add.setBackground(QtGui.QColor(200, 255, 200))
        fmt_del = QtGui.QTextCharFormat()
        fmt_del.setBackground(QtGui.QColor(255, 200, 200))
        fmt_hdr = QtGui.QTextCharFormat()
        fmt_hdr.setBackground(QtGui.QColor(220, 235, 255))

        block = doc.begin()
        while block.isValid():
            text = block.text()
            if text.startswith("+"):
                fmt = fmt_add
            elif text.startswith("-"):
                fmt = fmt_del
            elif text.startswith("@@"):
                fmt = fmt_hdr
            else:
                block = block.next()
                continue
            cursor.setPosition(block.position())
            cursor.movePosition(
                QtGui.QTextCursor.MoveOperation.EndOfBlock,
                QtGui.QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.setCharFormat(fmt)
            block = block.next()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_stage(self):
        self.stageRequested.emit(self._hunk)
        self.close()

    def _on_revert(self):
        self.revertRequested.emit(self._hunk)
        self.close()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def show_near(self, global_pos):
        """Position and show the popup near *global_pos* (a QPoint in global coords).

        The popup is nudged so it stays fully on-screen.
        """
        self.adjustSize()
        screen = QtWidgets.QApplication.screenAt(global_pos)
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        screen_rect = screen.availableGeometry()

        x = global_pos.x() + 4
        y = global_pos.y()
        w, h = self.width(), self.height()

        # Nudge left/up if clipped by screen edge
        if x + w > screen_rect.right():
            x = global_pos.x() - w - 4
        if y + h > screen_rect.bottom():
            y = screen_rect.bottom() - h

        self.move(x, y)
        self.show()
        self.raise_()


# ---------------------------------------------------------------------------
# DiffGutter
# ---------------------------------------------------------------------------

class DiffGutter(QtWidgets.QWidget):
    """Left-margin widget that shows coloured diff bands for each hunk.

    Typically used as a child of a :class:`~pyzo.codeeditor.CodeEditor`
    instance, placed in the left margin alongside the line-number area.

    Parameters
    ----------
    editor : QPlainTextEdit
        The code editor this gutter is attached to.  Must implement the
        same geometry interface as :class:`~pyzo.codeeditor.base.CodeEditorBase`.
    filepath : str or None
        Absolute path to the file displayed by *editor*.  Pass ``None``
        to show no diff markers.

    Width
    -----
    The widget is ``WIDTH`` pixels wide.  Callers are responsible for
    reserving this space in the editor's left margin (via
    ``_setLeftBarMargin``).
    """

    WIDTH = 6  # pixels

    def __init__(self, editor, filepath=None):
        super().__init__(editor)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._editor = editor
        self._filepath = filepath
        self._hunks = []
        self._popup = None

        if filepath:
            self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_filepath(self, filepath):
        """Set the file to track and refresh diff markers."""
        self._filepath = filepath
        self.refresh()

    def refresh(self):
        """Re-run ``git diff`` and repaint."""
        if self._filepath:
            self._hunks = get_diff_hunks(self._filepath)
        else:
            self._hunks = []
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        if not self._hunks:
            return

        painter = QtGui.QPainter(self)
        editor = self._editor
        w = self.WIDTH

        viewport = editor.viewport()
        # Map gutter top-left to viewport coords to get vertical offset
        tmp = self.mapToGlobal(QtCore.QPoint(0, 0))
        offset = viewport.mapFromGlobal(tmp).y()

        for hunk in self._hunks:
            color = _hunk_color(hunk)
            first, last = hunk.new_line_range()
            # Convert 1-based line numbers to block numbers (0-based)
            first_block = editor.document().findBlockByLineNumber(first - 1)
            last_block = editor.document().findBlockByLineNumber(last - 1)
            if not first_block.isValid():
                continue
            if not last_block.isValid():
                last_block = first_block

            y_top = editor.blockBoundingGeometry(first_block).top() - offset
            y_bot = editor.blockBoundingGeometry(last_block).bottom() - offset

            # Only draw if visible
            if y_bot < 0 or y_top > self.height():
                continue

            painter.fillRect(
                QtCore.QRect(0, int(y_top), w, max(2, int(y_bot - y_top))),
                color,
            )

            # Deletion-only hunk: draw a thin red tick at the insertion point
            has_add = any(l.startswith("+") for l in hunk.lines[1:])
            if not has_add:
                painter.fillRect(QtCore.QRect(0, int(y_top) - 1, w, 2), _COLOR_DELETED)

        painter.end()

    # ------------------------------------------------------------------
    # Mouse interaction – open HunkPopup on click
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hunk = self._hunk_at(event.position().toPoint())
        if hunk is None:
            return

        global_pos = self.mapToGlobal(event.position().toPoint())
        self._show_popup(hunk, global_pos)

    def _hunk_at(self, pos):
        """Return the hunk whose band covers vertical position *pos* (widget coords)."""
        editor = self._editor
        viewport = editor.viewport()
        tmp = self.mapToGlobal(QtCore.QPoint(0, 0))
        offset = viewport.mapFromGlobal(tmp).y()

        for hunk in self._hunks:
            first, last = hunk.new_line_range()
            first_block = editor.document().findBlockByLineNumber(first - 1)
            last_block = editor.document().findBlockByLineNumber(last - 1)
            if not first_block.isValid():
                continue
            if not last_block.isValid():
                last_block = first_block

            y_top = editor.blockBoundingGeometry(first_block).top() - offset
            y_bot = editor.blockBoundingGeometry(last_block).bottom() - offset

            if y_top <= pos.y() <= y_bot:
                return hunk
        return None

    def _show_popup(self, hunk, global_pos):
        """Create and display a :class:`HunkPopup` for *hunk*."""
        # Close any previously open popup
        if self._popup is not None:
            try:
                self._popup.close()
            except RuntimeError:
                pass
            self._popup = None

        popup = HunkPopup(self, hunk, self._filepath)
        popup.stageRequested.connect(self._on_stage)
        popup.revertRequested.connect(self._on_revert)
        self._popup = popup
        popup.show_near(global_pos)

    # ------------------------------------------------------------------
    # Hunk actions
    # ------------------------------------------------------------------

    def _on_stage(self, hunk):
        """Apply *hunk* to the git index (``git apply --cached``)."""
        self._run_git_apply(hunk, cached=True)

    def _on_revert(self, hunk):
        """Discard *hunk* from the working tree (``git apply -R``)."""
        self._run_git_apply(hunk, reverse=True)

    def _run_git_apply(self, hunk, cached=False, reverse=False):
        """Build a minimal patch from *hunk* and feed it to ``git apply``."""
        if not self._filepath:
            return
        repo_root = get_git_root(self._filepath)
        if repo_root is None:
            return

        rel = os.path.relpath(self._filepath, repo_root).replace(os.sep, "/")
        patch = (
            f"--- a/{rel}\n"
            f"+++ b/{rel}\n"
            + hunk.text
        )

        cmd = ["git", "apply"]
        if cached:
            cmd.append("--cached")
        if reverse:
            cmd.append("-R")

        try:
            subprocess.run(
                cmd,
                input=patch.encode("utf-8", errors="surrogateescape"),
                cwd=repo_root,
                capture_output=True,
                timeout=5,
                check=True,
            )
        except Exception:
            pass  # Silently ignore apply errors; caller can re-run refresh()

        # Refresh markers after an apply attempt
        self.refresh()
