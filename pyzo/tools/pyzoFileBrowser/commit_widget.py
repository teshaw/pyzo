"""
CommitWidget – a small dialog for composing git commit messages with
``#``-autocomplete that suggests open GitHub issues.

Usage::

    dlg = CommitWidget(parent, repo_root, owner, repo_name)
    if dlg.exec() == dlg.DialogCode.Accepted:
        message = dlg.commitMessage()
"""

import json
import re
import subprocess
import urllib.error
import urllib.request

from pyzo.qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt

# ---------------------------------------------------------------------------
# Session-level issue cache
# ---------------------------------------------------------------------------

#: ``{"{owner}/{repo}": [(number, title), …]}`` – persists for the lifetime
#: of the Python process so that repeated opens of the dialog do not hammer
#: the GitHub API.
_issue_cache: dict = {}


def fetch_issues(owner: str, repo: str) -> list:
    """Return a list of ``(number, title)`` tuples for open issues.

    Results are cached in :data:`_issue_cache` for the session.  On any
    network or API error an empty list is returned silently.

    Pull-request objects returned by the issues endpoint are filtered out
    (they carry a ``"pull_request"`` key).
    """
    key = f"{owner}/{repo}"
    if key in _issue_cache:
        return _issue_cache[key]

    url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        "/issues?state=open&per_page=100"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "pyzo-commit-widget",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    issues = [
        (item["number"], item["title"])
        for item in data
        if "pull_request" not in item
    ]
    _issue_cache[key] = issues
    return issues


# ---------------------------------------------------------------------------
# Issue-completer popup
# ---------------------------------------------------------------------------


class _IssuePopup(QtWidgets.QListWidget):
    """Floating list widget that shows issue suggestions.

    The popup has no focus so that keyboard input continues to reach the
    parent text-edit.  Clicking an entry or pressing Enter/Return on the
    parent while the popup is open triggers :pyattr:`issueSelected`.
    """

    #: Emitted with the chosen issue number when the user selects an entry.
    issueSelected = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.itemClicked.connect(self._on_item_clicked)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def populate(self, issues: list, prefix: str) -> bool:
        """Fill the list with *issues* that match *prefix* (digits only).

        Returns ``True`` if at least one entry was added.
        """
        self.clear()
        for number, title in issues:
            if str(number).startswith(prefix):
                item = QtWidgets.QListWidgetItem(f"#{number}  {title}")
                item.setData(Qt.ItemDataRole.UserRole, number)
                self.addItem(item)
        if self.count():
            self.setCurrentRow(0)
            return True
        return False

    def selectedIssueNumber(self) -> int | None:
        """Return the issue number of the currently highlighted row."""
        item = self.currentItem()
        if item is not None:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        self.issueSelected.emit(item.data(Qt.ItemDataRole.UserRole))


# ---------------------------------------------------------------------------
# CommitMessageEdit
# ---------------------------------------------------------------------------


class CommitMessageEdit(QtWidgets.QPlainTextEdit):
    """Plain-text editor that triggers an issue-autocomplete popup when the
    user types ``#`` followed by at least one digit.

    Parameters
    ----------
    parent:
        Parent widget (typically :class:`CommitWidget`).
    issues:
        List of ``(number, title)`` tuples returned by :func:`fetch_issues`.
        May be empty; the popup will simply never appear.
    """

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        issues: list,
    ) -> None:
        super().__init__(parent)
        self._issues = issues

        self._popup = _IssuePopup(self)
        self._popup.hide()
        self._popup.issueSelected.connect(self._insert_issue)

        # Cursor position just *after* the triggering ``#`` character.
        self._hash_pos: int | None = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def setIssues(self, issues: list) -> None:
        """Replace the issue list (used when issues are fetched asynchronously)."""
        self._issues = issues

    # ------------------------------------------------------------------
    # Popup management
    # ------------------------------------------------------------------

    def _digit_prefix(self) -> str | None:
        """Return the digit string typed after ``#``, or ``None`` if not applicable."""
        if self._hash_pos is None:
            return None
        cursor = self.textCursor()
        pos = cursor.position()
        if pos <= self._hash_pos:
            return None
        doc = self.document()
        text_after_hash = doc.toPlainText()[self._hash_pos:pos]
        if text_after_hash.isdigit():
            return text_after_hash
        return None

    def _show_popup(self, prefix: str) -> None:
        """Update the popup content for *prefix* and position it below the cursor."""
        if not self._popup.populate(self._issues, prefix):
            self._popup.hide()
            return

        # Size
        self._popup.setFixedWidth(360)
        rows = min(self._popup.count(), 8)
        row_h = self._popup.sizeHintForRow(0) if rows else 20
        self._popup.setFixedHeight(rows * row_h + 4)

        # Position below the ``#`` character
        cur = self.textCursor()
        saved_pos = cur.position()
        if self._hash_pos is not None:
            cur.setPosition(self._hash_pos - 1)  # position of the '#'
        rect = self.cursorRect(cur)
        cur.setPosition(saved_pos)

        global_pt = self.mapToGlobal(
            rect.bottomLeft() + self.viewport().pos()
        )
        self._popup.move(global_pt)
        self._popup.show()

    def _close_popup(self) -> None:
        self._popup.hide()
        self._hash_pos = None

    def _insert_issue(self, number: int) -> None:
        """Replace ``#<digits>`` with ``#<number>`` and close the popup."""
        if self._hash_pos is None:
            self._close_popup()
            return
        cursor = self.textCursor()
        cursor.setPosition(self._hash_pos - 1)  # before the '#'
        cursor.setPosition(
            self.textCursor().position(), QtGui.QTextCursor.MoveMode.KeepAnchor
        )
        cursor.insertText(f"#{number}")
        self.setTextCursor(cursor)
        self._close_popup()

    # ------------------------------------------------------------------
    # Event overrides
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = event.key()

        # Escape: dismiss popup
        if key == Qt.Key.Key_Escape and self._popup.isVisible():
            self._close_popup()
            return

        # Enter/Return: accept highlighted popup item
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._popup.isVisible():
            number = self._popup.selectedIssueNumber()
            if number is not None:
                self._insert_issue(number)
                return

        # Arrow keys: navigate popup
        if self._popup.isVisible():
            if key == Qt.Key.Key_Up:
                row = max(0, self._popup.currentRow() - 1)
                self._popup.setCurrentRow(row)
                return
            if key == Qt.Key.Key_Down:
                row = min(self._popup.count() - 1, self._popup.currentRow() + 1)
                self._popup.setCurrentRow(row)
                return

        # Regular typing
        super().keyPressEvent(event)

        # Check whether we need to open/update/close the popup after the key
        text = self.document().toPlainText()
        pos = self.textCursor().position()

        # Detect '#' being typed
        if event.text() == "#":
            self._hash_pos = pos  # position right after '#'
            return  # no digits yet – wait for next keystroke

        # If popup is active, keep updating or close it
        if self._hash_pos is not None:
            prefix = self._digit_prefix()
            if prefix is not None:
                self._show_popup(prefix)
            else:
                # Something non-digit was typed or cursor moved before '#'
                self._close_popup()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._close_popup()
        super().mousePressEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        # Close unless focus moved to the popup itself
        if not self._popup.underMouse():
            self._close_popup()
        super().focusOutEvent(event)


# ---------------------------------------------------------------------------
# CommitWidget dialog
# ---------------------------------------------------------------------------


class CommitWidget(QtWidgets.QDialog):
    """Dialog for composing a git commit message with issue autocomplete.

    Parameters
    ----------
    parent:
        Parent widget.
    repo_root:
        Absolute path to the git repository root.
    owner:
        GitHub repository owner (user or organisation name).
    repo_name:
        GitHub repository name.
    """

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        repo_root: str,
        owner: str | None,
        repo_name: str | None,
    ) -> None:
        super().__init__(parent)
        self._repo_root = repo_root
        self._owner = owner
        self._repo_name = repo_name

        self.setWindowTitle("Git Commit")
        self.setMinimumWidth(480)

        # Fetch issues (possibly empty if not on GitHub)
        issues: list = []
        if owner and repo_name:
            issues = fetch_issues(owner, repo_name)

        # Message editor
        self._edit = CommitMessageEdit(self, issues)
        self._edit.setPlaceholderText(
            "Commit message…  (type # then digits to link an issue)"
        )
        self._edit.setMinimumHeight(80)

        # Buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Commit")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Commit message:"))
        layout.addWidget(self._edit)
        layout.addWidget(buttons)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def commitMessage(self) -> str:
        """Return the text entered by the user."""
        return self._edit.toPlainText().strip()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        message = self.commitMessage()
        if not message:
            QtWidgets.QMessageBox.warning(
                self,
                "Empty message",
                "Please enter a commit message.",
            )
            return

        try:
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self._repo_root,
                capture_output=True,
                timeout=30,
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Git error",
                f"Failed to run git commit:\n{exc}",
            )
            return

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            QtWidgets.QMessageBox.critical(
                self,
                "Git commit failed",
                stderr or "git commit returned a non-zero exit code.",
            )
            return

        self.accept()
