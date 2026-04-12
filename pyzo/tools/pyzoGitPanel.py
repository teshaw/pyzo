"""
Git Panel tool for Pyzo.

Provides a dockable panel with three tabs – Changes, History and Stash –
that show the git status of the repository associated with the currently
browsed directory (taken from the File Browser tool when available).

The panel polls git every few seconds so that the stash list (and other
tabs) stay up-to-date automatically after any git operation.
"""

import os
import os.path as op

import pyzo
from pyzo import translate
from pyzo.qt import QtCore, QtWidgets

from pyzo.tools.pyzoFileBrowser import githelper


tool_name = translate("pyzoGitPanel", "Git Panel")
tool_summary = "Show git changes, history, and stashes for the current project."

# How often (milliseconds) the panel refreshes its content.
_REFRESH_INTERVAL_MS = 3000


# ---------------------------------------------------------------------------
# Individual tab widgets
# ---------------------------------------------------------------------------


class _GitTabBase(QtWidgets.QWidget):
    """Base class for the three git tabs.

    Subclasses implement :meth:`_populate` which receives the repo root
    (or ``None`` when outside a git repository).  The base class handles
    the empty-state label, the tree widget and the stacked layout.
    """

    # Subclasses set these to customise the appearance.
    _EMPTY_MESSAGE = "Nothing to show"
    _HEADERS = []

    def __init__(self, parent=None):
        super().__init__(parent)

        # Tree widget for the data rows
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(self._HEADERS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        if self._HEADERS:
            # Stretch the second column (message/path) so it fills the space.
            header.setSectionResizeMode(
                1, QtWidgets.QHeaderView.ResizeMode.Stretch
            )

        # Empty-state label (shown instead of the tree when there is nothing)
        self._empty_label = QtWidgets.QLabel(self._EMPTY_MESSAGE)
        self._empty_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            "QLabel { color: gray; font-style: italic; }"
        )

        # Stacked widget: index 0 → tree, index 1 → empty label
        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self._tree)
        self._stack.addWidget(self._empty_label)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # Start with the empty state
        self._set_empty(self._EMPTY_MESSAGE)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_empty(self, message):
        """Show the empty-state label with *message*."""
        self._empty_label.setText(message)
        self._stack.setCurrentIndex(1)

    def _set_tree(self):
        """Show the tree widget."""
        self._stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self, repo_root):
        """Refresh the tab contents for *repo_root*.

        *repo_root* is ``None`` when the current directory is not inside a
        git repository.  Subclasses override :meth:`_populate` to provide
        concrete data.
        """
        if repo_root is None:
            self._set_empty("Not a git repository")
            return
        self._populate(repo_root)

    def _populate(self, repo_root):
        """Override in subclasses to fill the tree widget."""
        raise NotImplementedError


class _ChangesTab(_GitTabBase):
    """Displays the working-tree and index changes (``git status``)."""

    _EMPTY_MESSAGE = "No changes"
    _HEADERS = ["Status", "File"]

    def _populate(self, repo_root):
        status = githelper.get_git_status(repo_root)
        if status is None or not status._status:
            self._set_empty(self._EMPTY_MESSAGE)
            return

        self._tree.clear()
        for abs_path, xy in sorted(status._status.items()):
            rel_path = op.relpath(abs_path, repo_root)
            item = QtWidgets.QTreeWidgetItem([xy.strip(), rel_path])
            # Colour the status badge to match the file-browser colours
            color = status.get_color_for_xy(xy)
            if color is not None:
                item.setForeground(
                    0, QtWidgets.QApplication.palette().text()
                )
                from pyzo.qt import QtGui

                item.setForeground(0, QtGui.QColor(*color))
            self._tree.addTopLevelItem(item)
        self._set_tree()


class _HistoryTab(_GitTabBase):
    """Displays recent commit history (``git log``)."""

    _EMPTY_MESSAGE = "No commits"
    _HEADERS = ["SHA", "Message", "Author", "Date"]

    def _populate(self, repo_root):
        commits = githelper.get_git_log(repo_root)
        if not commits:
            self._set_empty(self._EMPTY_MESSAGE)
            return

        self._tree.clear()
        for commit in commits:
            item = QtWidgets.QTreeWidgetItem(
                [
                    commit["sha"],
                    commit["message"],
                    commit["author"],
                    commit["date"],
                ]
            )
            self._tree.addTopLevelItem(item)
        self._set_tree()


class _StashTab(_GitTabBase):
    """Displays the stash list (``git stash list``)."""

    _EMPTY_MESSAGE = "No stashes"
    _HEADERS = ["Ref", "Message", "Author", "Date"]

    def _populate(self, repo_root):
        stashes = githelper.get_git_stash_list(repo_root)
        if not stashes:
            self._set_empty(self._EMPTY_MESSAGE)
            return

        self._tree.clear()
        for stash in stashes:
            item = QtWidgets.QTreeWidgetItem(
                [
                    stash["ref"],
                    stash["message"],
                    stash["author"],
                    stash["date"],
                ]
            )
            self._tree.addTopLevelItem(item)
        self._set_tree()


# ---------------------------------------------------------------------------
# Main panel widget
# ---------------------------------------------------------------------------


class PyzoGitPanel(QtWidgets.QWidget):
    """Git Panel tool widget.

    Contains a tab bar with Changes, History and Stash tabs.  The panel
    discovers the current git repository from the File Browser tool (when
    loaded) and falls back to ``os.getcwd()``.  Content is refreshed
    automatically every :data:`_REFRESH_INTERVAL_MS` milliseconds.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Repository root label shown above the tabs
        self._repo_label = QtWidgets.QLabel()
        self._repo_label.setStyleSheet(
            "QLabel { font-style: italic; color: gray; padding: 1px 2px; }"
        )

        # Tab widget
        self._tabs = QtWidgets.QTabWidget()

        self._changes_tab = _ChangesTab(self)
        self._history_tab = _HistoryTab(self)
        self._stash_tab = _StashTab(self)

        self._tabs.addTab(self._changes_tab, translate("pyzoGitPanel", "Changes"))
        self._tabs.addTab(self._history_tab, translate("pyzoGitPanel", "History"))
        self._tabs.addTab(self._stash_tab, translate("pyzoGitPanel", "Stash"))

        # Refresh all tabs when the user switches to one, so the content is
        # always up-to-date when it becomes visible.
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Layout
        margin = pyzo.config.view.widgetMargin
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.addWidget(self._repo_label)
        layout.addWidget(self._tabs)

        # Auto-refresh timer
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)

        # Perform an immediate first refresh
        self._refresh()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_repo_root(self):
        """Return the git repository root to show, or ``None``."""
        # Prefer the path shown by the File Browser tool.
        try:
            fb = pyzo.toolManager.getTool("pyzofilebrowser2")
            if fb is not None:
                path = fb.path()
                if path:
                    return githelper.get_git_root(path)
        except Exception:
            pass
        # Fall back to the process working directory.
        return githelper.get_git_root(os.getcwd())

    def _update_repo_label(self, repo_root):
        if repo_root:
            branch = githelper.get_git_branch(repo_root)
            text = repo_root
            if branch:
                text = f"{repo_root}  \u2387  {branch}"
            self._repo_label.setText(text)
        else:
            self._repo_label.setText(translate("pyzoGitPanel", "No repository"))

    def _refresh(self):
        """Refresh the currently visible tab."""
        repo_root = self._get_repo_root()
        self._update_repo_label(repo_root)
        current = self._tabs.currentWidget()
        if current is not None:
            current.refresh(repo_root)

    def _on_tab_changed(self, index):
        """Refresh the newly selected tab immediately."""
        self._refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self):
        """Trigger an immediate refresh of the panel."""
        self._refresh()
