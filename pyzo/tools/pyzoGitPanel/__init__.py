from pyzo import translate

tool_name = translate("pyzoGitPanel", "Git Panel")
tool_summary = "View staged/unstaged changes and commit to git."

"""Git panel tool for Pyzo.

Shows the current repository's staged and unstaged changes in a tree,
displays a unified diff for the selected file, and allows committing
staged changes.

Layout
------
PyzoGitPanel (QWidget)
├── Top bar:  branch label  +  Refresh button
├── QSplitter (horizontal)
│   ├── Left  (40 %): ChangesModel QTreeView  (staged + unstaged sections)
│   └── Right (60 %): DiffView  (syntax-highlighted unified diff)
└── Bottom: CommitWidget  (collapsible, visible when ≥ 1 file is staged)

Config keys (stored under pyzo.config.tools.pyzogitpanel)
----------------------------------------------------------
splitter_left  : int  – pixel width of the left splitter pane
splitter_right : int  – pixel width of the right splitter pane
"""

import os
import subprocess

import pyzo
from pyzo.qt import QtCore, QtGui, QtWidgets
from pyzo.util import zon as ssdf

from pyzo.tools.pyzoFileBrowser.githelper import (
    get_git_root,
    get_git_branch,
    get_git_status,
)

# ---------------------------------------------------------------------------
# Custom item-data roles
# ---------------------------------------------------------------------------

_PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1    # absolute file path (str)
_STAGED_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2  # True = staged, False = unstaged


# ---------------------------------------------------------------------------
# Git subprocess helpers
# ---------------------------------------------------------------------------


def _get_git_diff(repo_root, path, staged=False):
    """Return the unified diff text for *path*, or an empty string on failure.

    Parameters
    ----------
    repo_root : str
        Absolute path to the repository root.
    path : str
        Absolute path to the file.
    staged : bool
        When ``True``, show the staged (index vs HEAD) diff; otherwise show
        the working-tree diff.
    """
    try:
        cmd = ["git", "diff", "--unified=3"]
        if staged:
            cmd.append("--cached")
        cmd += ["--", path]
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        return result.stdout.decode("utf-8", errors="surrogateescape")
    except Exception:
        return ""


def _run_git_commit(repo_root, message):
    """Run ``git commit -m <message>`` and return ``(success, output)``."""
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_root,
            capture_output=True,
            timeout=10,
        )
        out = result.stdout.decode("utf-8", errors="replace")
        if result.returncode != 0:
            out += result.stderr.decode("utf-8", errors="replace")
        return result.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# DiffHighlighter – syntax-highlights a QTextDocument
# ---------------------------------------------------------------------------


class DiffHighlighter(QtGui.QSyntaxHighlighter):
    """Colours added/removed/hunk lines in a unified-diff document."""

    def __init__(self, parent):
        super().__init__(parent)

        self._fmt_added = QtGui.QTextCharFormat()
        self._fmt_added.setForeground(QtGui.QColor(0, 140, 0))     # green

        self._fmt_removed = QtGui.QTextCharFormat()
        self._fmt_removed.setForeground(QtGui.QColor(180, 0, 0))   # red

        self._fmt_hunk = QtGui.QTextCharFormat()
        self._fmt_hunk.setForeground(QtGui.QColor(0, 100, 160))    # blue-ish

        self._fmt_header = QtGui.QTextCharFormat()
        self._fmt_header.setForeground(QtGui.QColor(100, 100, 100))  # grey

    def highlightBlock(self, text):
        if text.startswith("+"):
            self.setFormat(0, len(text), self._fmt_added)
        elif text.startswith("-"):
            self.setFormat(0, len(text), self._fmt_removed)
        elif text.startswith("@@"):
            self.setFormat(0, len(text), self._fmt_hunk)
        elif text.startswith(("diff ", "index ", "--- ", "+++ ")):
            self.setFormat(0, len(text), self._fmt_header)


# ---------------------------------------------------------------------------
# DiffView – read-only plain-text widget for displaying a unified diff
# ---------------------------------------------------------------------------


class DiffView(QtWidgets.QPlainTextEdit):
    """Read-only widget that displays a unified diff with syntax highlighting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        font = QtGui.QFont("Courier New", 9)
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self.setFont(font)
        self._highlighter = DiffHighlighter(self.document())

    def setDiff(self, diff_text):
        """Replace the displayed content with *diff_text* and scroll to top."""
        self.setPlainText(diff_text)
        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)


# ---------------------------------------------------------------------------
# ChangesModel – QStandardItemModel with Staged / Unstaged sections
# ---------------------------------------------------------------------------


class ChangesModel(QtGui.QStandardItemModel):
    """Two-section model: top-level items are 'Staged' and 'Unstaged'.

    Each file entry stores its absolute path via ``_PATH_ROLE`` and a
    boolean flag via ``_STAGED_ROLE``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["File", "Status"])

        self._staged_item = QtGui.QStandardItem("Staged")
        self._staged_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

        self._unstaged_item = QtGui.QStandardItem("Unstaged")
        self._unstaged_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

        self.appendRow([self._staged_item])
        self.appendRow([self._unstaged_item])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, git_status):
        """Repopulate the model from a :class:`~githelper.GitStatus` object.

        Pass ``None`` to clear both sections.
        """
        self._staged_item.removeRows(0, self._staged_item.rowCount())
        self._unstaged_item.removeRows(0, self._unstaged_item.rowCount())

        if git_status is None:
            return

        for abs_path, xy in git_status._status.items():
            x = xy[0] if len(xy) > 0 else " "
            y = xy[1] if len(xy) > 1 else " "
            rel_path = os.path.relpath(abs_path, git_status.root)

            # X = index status → Staged section
            if x not in (" ", "?", "!"):
                self._staged_item.appendRow(
                    self._make_row(rel_path, abs_path, x, staged=True)
                )

            # Y = working-tree status → Unstaged section
            # Untracked files ("??") also live here.
            if x == "?" and y == "?":
                # Untracked
                self._unstaged_item.appendRow(
                    self._make_row(rel_path, abs_path, "?", staged=False)
                )
            elif y not in (" ", "!"):
                self._unstaged_item.appendRow(
                    self._make_row(rel_path, abs_path, y, staged=False)
                )

    def staged_count(self):
        """Return the number of staged files."""
        return self._staged_item.rowCount()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_row(rel_path, abs_path, status_char, staged):
        """Return a two-element list ``[file_item, status_item]``."""
        file_item = QtGui.QStandardItem(rel_path)
        file_item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        file_item.setData(abs_path, _PATH_ROLE)
        file_item.setData(staged, _STAGED_ROLE)

        status_item = QtGui.QStandardItem(status_char)
        status_item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        return [file_item, status_item]


# ---------------------------------------------------------------------------
# CommitWidget – message editor + Commit button
# ---------------------------------------------------------------------------


class CommitWidget(QtWidgets.QWidget):
    """Compact widget for authoring and submitting a git commit.

    Emits :attr:`committed` after a successful ``git commit``.
    """

    committed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._repo_root = None

        self._msg_edit = QtWidgets.QPlainTextEdit()
        self._msg_edit.setPlaceholderText("Commit message…")
        self._msg_edit.setMaximumHeight(80)

        self._commit_btn = QtWidgets.QPushButton("Commit")
        self._commit_btn.clicked.connect(self._do_commit)

        self._status_label = QtWidgets.QLabel()

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._commit_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self._msg_edit)
        layout.addLayout(btn_row)
        layout.addWidget(self._status_label)

    def setRepoRoot(self, repo_root):
        """Set the repository root used for ``git commit``."""
        self._repo_root = repo_root

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _do_commit(self):
        msg = self._msg_edit.toPlainText().strip()
        if not msg:
            self._status_label.setText("Please enter a commit message.")
            return
        if not self._repo_root:
            self._status_label.setText("No git repository found.")
            return
        success, output = _run_git_commit(self._repo_root, msg)
        if success:
            self._msg_edit.clear()
            self._status_label.setText("Committed successfully.")
            self.committed.emit()
        else:
            self._status_label.setText("Commit failed: " + output.strip())


# ---------------------------------------------------------------------------
# PyzoGitPanel – the top-level Pyzo tool widget
# ---------------------------------------------------------------------------


class PyzoGitPanel(QtWidgets.QWidget):
    """Git panel tool for Pyzo.

    Docks as a standard Pyzo tool and provides a live view of staged /
    unstaged changes plus a one-click commit workflow.
    """

    def __init__(self, parent):
        super().__init__(parent)

        # ---- Config --------------------------------------------------------
        toolId = self.__class__.__name__.lower()
        if toolId not in pyzo.config.tools:
            pyzo.config.tools[toolId] = ssdf.new()
        self.config = pyzo.config.tools[toolId]

        # ---- Internal state ------------------------------------------------
        self._repo_root = None
        self._git_status = None
        self._selected_path = None
        self._selected_staged = False

        # ---- Top bar -------------------------------------------------------
        self._branch_label = QtWidgets.QLabel("(no git repo)")
        self._refresh_btn = QtWidgets.QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)

        top_bar = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._branch_label)
        top_layout.addStretch()
        top_layout.addWidget(self._refresh_btn)

        # ---- Changes tree --------------------------------------------------
        self._model = ChangesModel()
        self._tree = QtWidgets.QTreeView()
        self._tree.setModel(self._model)
        self._tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self._tree.selectionModel().currentChanged.connect(
            self._on_selection_changed
        )
        self._tree.expandAll()

        # ---- Diff view -----------------------------------------------------
        self._diff_view = DiffView()

        # ---- Splitter (40 / 60 default, persisted in config) ---------------
        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._tree)
        self._splitter.addWidget(self._diff_view)

        if (
            "splitter_left" in self.config
            and "splitter_right" in self.config
        ):
            self._splitter.setSizes(
                [self.config.splitter_left, self.config.splitter_right]
            )
        else:
            self._splitter.setSizes([40, 60])

        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        # ---- Commit widget (hidden until ≥ 1 file is staged) ---------------
        self._commit_widget = CommitWidget()
        self._commit_widget.committed.connect(self.refresh)
        self._commit_widget.setVisible(False)

        # ---- Main layout ---------------------------------------------------
        layout = QtWidgets.QVBoxLayout(self)
        margin = pyzo.config.view.widgetMargin
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(4)
        layout.addWidget(top_bar)
        layout.addWidget(self._splitter, 1)
        layout.addWidget(self._commit_widget)

        # ---- Auto-refresh timer (5 s) --------------------------------------
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start()

        # Suspend the timer whenever the application loses focus
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

        # Initial populate
        self.refresh()

    # -----------------------------------------------------------------------
    # Qt event handlers
    # -----------------------------------------------------------------------

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

    # -----------------------------------------------------------------------
    # Slots
    # -----------------------------------------------------------------------

    def refresh(self):
        """Refresh git status based on the current working directory."""
        cwd = os.getcwd()
        self._repo_root = get_git_root(cwd)

        if self._repo_root is None:
            self._branch_label.setText("(no git repo)")
            self._model.update(None)
            self._diff_view.setDiff("")
            self._commit_widget.setVisible(False)
            return

        branch = get_git_branch(self._repo_root)
        self._branch_label.setText("Branch: " + (branch or "(unknown)"))

        self._git_status = get_git_status(self._repo_root)
        self._model.update(self._git_status)
        self._tree.expandAll()

        # Show / hide CommitWidget depending on staged file count
        has_staged = self._model.staged_count() > 0
        self._commit_widget.setVisible(has_staged)
        self._commit_widget.setRepoRoot(self._repo_root)

        # Reload the diff for the currently selected file (if any)
        if self._selected_path:
            self._load_diff(self._selected_path, self._selected_staged)

    def _auto_refresh(self):
        """Called every 5 s by the timer; only acts when the panel is visible."""
        if self.isVisible() and self._repo_root is not None:
            self.refresh()

    def _on_focus_changed(self, old, new):
        """Stop the timer when the application loses focus; restart on return."""
        if new is None:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start()

    def _on_splitter_moved(self, pos, index):
        """Persist the splitter ratio to config whenever the user moves it."""
        sizes = self._splitter.sizes()
        if len(sizes) == 2:
            self.config.splitter_left = sizes[0]
            self.config.splitter_right = sizes[1]

    def _on_selection_changed(self, current, previous):
        """Load the diff for the newly selected file."""
        if not current.isValid():
            self._diff_view.setDiff("")
            return

        item = self._model.itemFromIndex(current)
        if item is None:
            return

        path = item.data(_PATH_ROLE)
        staged = item.data(_STAGED_ROLE)

        if path is None:
            # Header row selected ("Staged" / "Unstaged") – nothing to diff
            self._diff_view.setDiff("")
            return

        self._selected_path = path
        self._selected_staged = bool(staged)
        self._load_diff(path, self._selected_staged)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _load_diff(self, path, staged):
        """Fetch and display the diff for *path*."""
        if self._repo_root is None:
            return
        diff_text = _get_git_diff(self._repo_root, path, staged=staged)
        self._diff_view.setDiff(diff_text)
