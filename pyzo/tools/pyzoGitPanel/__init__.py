from pyzo import translate

tool_name = translate("pyzoGitPanel", "Git Panel")
tool_summary = "Shows the Git status of the current repository."

"""Git Panel tool for Pyzo.

Displays the current branch and working-tree status for the Git repository
that contains the active editor file (falling back to the File Browser path).
"""

import os
import os.path as op
import subprocess

import pyzo
from pyzo.qt import QtCore, QtWidgets


# ---------------------------------------------------------------------------
# Lightweight, dependency-free Git helpers (subprocess only for git status)
# ---------------------------------------------------------------------------


def _git_root(path):
    """Return the repository root for *path*, or ``None``."""
    if not op.isdir(path):
        path = op.dirname(path)
    current = op.abspath(path)
    while True:
        if op.isdir(op.join(current, ".git")):
            return current
        parent = op.dirname(current)
        if parent == current:
            return None
        current = parent


def _git_branch(root):
    """Return the current branch name, or ``None``."""
    head = op.join(root, ".git", "HEAD")
    try:
        with open(head, encoding="utf-8") as fh:
            content = fh.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        return "HEAD:" + content[:7]
    except Exception:
        return None


def _git_status(root):
    """Return a list of ``(xy, path)`` tuples from ``git status --porcelain``."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "-u"],
            cwd=root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        raw = result.stdout.decode("utf-8", errors="surrogateescape")
        entries = raw.split("\0")
        items = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            xy = entry[:2]
            path = entry[3:]
            if xy[0] in ("R", "C"):
                i += 1  # skip original-path entry for renames/copies
            items.append((xy, path))
        return items
    except Exception:
        return []


def _current_path():
    """Return the best available path for repository detection."""
    # Prefer the active editor file path
    if pyzo.editors is not None:
        ed = pyzo.editors.getCurrentEditor()
        if ed is not None:
            fname = ed.filename
            if fname and op.isabs(fname):
                return fname
    # Fall back to the File Browser path
    fb = pyzo.toolManager.getTool("pyzofilebrowser")
    if fb is not None and hasattr(fb, "path"):
        p = fb.path()
        if p and op.isabs(p):
            return p
    return op.expanduser("~")


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------


_XY_LABEL = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "unmerged",
    "?": "untracked",
}


class PyzoGitPanel(QtWidgets.QWidget):
    """Git Panel – shows branch and working-tree status."""

    def __init__(self, parent):
        super().__init__(parent)

        # --- Header ---
        self._branch_label = QtWidgets.QLabel("", self)
        self._branch_label.setWordWrap(True)

        refresh_btn = QtWidgets.QPushButton(
            translate("pyzoGitPanel", "Refresh"), self
        )
        refresh_btn.clicked.connect(self.refresh)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self._branch_label, 1)
        header.addWidget(refresh_btn, 0)

        # --- Status list ---
        self._status_list = QtWidgets.QTreeWidget(self)
        self._status_list.setHeaderLabels(
            [
                translate("pyzoGitPanel", "Status"),
                translate("pyzoGitPanel", "File"),
            ]
        )
        self._status_list.setRootIsDecorated(False)
        self._status_list.setAlternatingRowColors(True)
        header_view = self._status_list.header()
        header_view.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        header_view.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )

        # --- Layout ---
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._status_list, 1)
        layout.setSpacing(4)
        margin = pyzo.config.view.widgetMargin
        layout.setContentsMargins(margin, margin, margin, margin)
        self.setLayout(layout)

        # --- Auto-refresh timer (every 30 s) ---
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self.refresh()

    # ------------------------------------------------------------------
    # Refresh logic
    # ------------------------------------------------------------------

    def refresh(self):
        """Refresh branch name and status list."""
        path = _current_path()
        root = _git_root(path)

        if root is None:
            self._branch_label.setText(
                translate("pyzoGitPanel", "No Git repository found.")
            )
            self._status_list.clear()
            return

        branch = _git_branch(root) or translate("pyzoGitPanel", "(unknown branch)")
        self._branch_label.setText(
            "\u2387 {}  \u2014  {}".format(branch, root)
        )

        items = _git_status(root)
        self._status_list.clear()
        for xy, rel_path in items:
            label = self._status_label(xy)
            item = QtWidgets.QTreeWidgetItem([label, rel_path])
            item.setToolTip(1, op.join(root, rel_path))
            self._status_list.addTopLevelItem(item)

        if not items:
            clean_item = QtWidgets.QTreeWidgetItem(
                ["", translate("pyzoGitPanel", "Working tree clean")]
            )
            self._status_list.addTopLevelItem(clean_item)

    @staticmethod
    def _status_label(xy):
        """Convert a two-character XY string to a human-readable label."""
        x, y = (xy[0] if xy else " "), (xy[1] if len(xy) > 1 else " ")
        parts = []
        if x != " " and x != "?":
            parts.append(_XY_LABEL.get(x, x) + " (staged)")
        if y != " ":
            parts.append(_XY_LABEL.get(y, y))
        return ", ".join(parts) if parts else xy.strip()
