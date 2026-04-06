"""
commitwidget.py — commit form widget for the pyzoGitPanel.

Provides :class:`CommitWidget`, a ``QWidget`` that lets the user compose
and submit git commits without leaving pyzo.
"""

from pyzo.qt import QtCore, QtGui, QtWidgets

from . import gitops


class CommitWidget(QtWidgets.QWidget):
    """Widget for composing and submitting git commits.

    Signals
    -------
    committed(str)
        Emitted after a successful commit; carries the short SHA.
    """

    committed = QtCore.Signal(str)

    def __init__(self, parent=None, repo_root=None):
        super().__init__(parent)
        self._repo_root = repo_root

        self._build_ui()
        self._connect_signals()
        self._refresh_branch()
        self._update_commit_button()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ---- branch indicator ----------------------------------------
        self._branchLabel = QtWidgets.QLabel("")
        self._branchLabel.setStyleSheet(
            "QLabel { font-style: italic; color: gray; padding: 1px 2px; }"
        )
        layout.addWidget(self._branchLabel)

        # ---- commit message text edit --------------------------------
        self._msgEdit = QtWidgets.QTextEdit()
        self._msgEdit.setPlaceholderText("Summary\n\nDescription…")
        self._msgEdit.setAcceptRichText(False)
        self._msgEdit.setMinimumHeight(80)
        layout.addWidget(self._msgEdit)

        # ---- character counter ---------------------------------------
        self._charCountLabel = QtWidgets.QLabel("0")
        self._charCountLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self._charCountLabel.setStyleSheet("QLabel { color: gray; font-size: 10px; }")
        layout.addWidget(self._charCountLabel)

        # ---- amend checkbox ------------------------------------------
        self._amendCheck = QtWidgets.QCheckBox("Amend last commit")
        layout.addWidget(self._amendCheck)

        # ---- stage / unstage row -------------------------------------
        stage_row = QtWidgets.QHBoxLayout()
        self._stageAllBtn = QtWidgets.QPushButton("Stage All")
        self._unstageAllBtn = QtWidgets.QPushButton("Unstage All")
        stage_row.addWidget(self._stageAllBtn)
        stage_row.addWidget(self._unstageAllBtn)
        stage_row.addStretch()
        layout.addLayout(stage_row)

        # ---- commit button -------------------------------------------
        self._commitBtn = QtWidgets.QPushButton("Commit")
        self._commitBtn.setEnabled(False)
        layout.addWidget(self._commitBtn)

        # ---- status label (transient feedback) -----------------------
        self._statusLabel = QtWidgets.QLabel("")
        self._statusLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._statusLabel)

        # Timer to clear the status label
        self._statusTimer = QtCore.QTimer(self)
        self._statusTimer.setSingleShot(True)
        self._statusTimer.setInterval(3000)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self._msgEdit.textChanged.connect(self._on_text_changed)
        self._commitBtn.clicked.connect(self._on_commit)
        self._stageAllBtn.clicked.connect(self._on_stage_all)
        self._unstageAllBtn.clicked.connect(self._on_unstage_all)
        self._statusTimer.timeout.connect(self._clear_status)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setRepoRoot(self, repo_root):
        """Set the repository root and refresh branch/button state."""
        self._repo_root = repo_root
        self._refresh_branch()
        self._update_commit_button()

    def repoRoot(self):
        """Return the current repository root (may be ``None``)."""
        return self._repo_root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_branch(self):
        """Update the branch indicator label."""
        if self._repo_root:
            branch = gitops.get_branch(self._repo_root)
            self._branchLabel.setText("Branch: " + (branch or "(unknown)"))
        else:
            self._branchLabel.setText("")

    def _on_text_changed(self):
        self._update_char_counter()
        self._update_commit_button()

    def _update_char_counter(self):
        """Refresh the character counter below the text edit."""
        text = self._msgEdit.toPlainText()
        first_line = text.split("\n")[0] if text else ""
        count = len(first_line)
        self._charCountLabel.setText(str(count))
        if count > 72:
            self._charCountLabel.setStyleSheet(
                "QLabel { color: red; font-size: 10px; }"
            )
        elif count > 50:
            self._charCountLabel.setStyleSheet(
                "QLabel { color: orange; font-size: 10px; }"
            )
        else:
            self._charCountLabel.setStyleSheet(
                "QLabel { color: gray; font-size: 10px; }"
            )

    def _update_commit_button(self):
        """Enable the Commit button only when conditions are met."""
        has_message = bool(self._msgEdit.toPlainText().strip())
        has_staged = self._has_staged_files()
        self._commitBtn.setEnabled(has_message and has_staged)

    def _has_staged_files(self):
        """Return ``True`` when there is at least one staged file."""
        if not self._repo_root:
            return False
        return len(gitops.get_staged_files(self._repo_root)) > 0

    def _on_commit(self):
        if not self._repo_root:
            self._show_status("No repository set.", error=True)
            return
        message = self._msgEdit.toPlainText().strip()
        if not message:
            self._show_status("Commit message is empty.", error=True)
            return
        amend = self._amendCheck.isChecked()
        success, result = gitops.commit(self._repo_root, message, amend=amend)
        if success:
            short_sha = result
            self._msgEdit.clear()
            self._show_status(f"Committed as {short_sha}")
            self.committed.emit(short_sha)
        else:
            self._show_status(f"Commit failed: {result}", error=True)
        self._update_commit_button()

    def _on_stage_all(self):
        if not self._repo_root:
            self._show_status("No repository set.", error=True)
            return
        success, msg = gitops.stage_all(self._repo_root)
        self._show_status(msg, error=not success)
        self._update_commit_button()

    def _on_unstage_all(self):
        if not self._repo_root:
            self._show_status("No repository set.", error=True)
            return
        success, msg = gitops.unstage_all(self._repo_root)
        self._show_status(msg, error=not success)
        self._update_commit_button()

    def _show_status(self, text, error=False):
        """Display *text* in the status label for 3 seconds."""
        color = "red" if error else "green"
        self._statusLabel.setStyleSheet(f"QLabel {{ color: {color}; }}")
        self._statusLabel.setText(text)
        self._statusTimer.start()

    def _clear_status(self):
        self._statusLabel.setText("")
        self._statusLabel.setStyleSheet("")
