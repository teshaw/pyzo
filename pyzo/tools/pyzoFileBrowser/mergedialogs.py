"""
Merge / Rebase dialog for the pyzo File Browser Git panel.

Provides :class:`MergeRebaseDialog`, a small dialog that lets the user
pick a local branch and run either ``git merge`` or ``git rebase`` against
it.  Command output is streamed into an embedded log widget, and any
merge / rebase conflicts are reported with a list of the affected files.
"""

import os.path as op

from pyzo.qt import QtCore, QtGui, QtWidgets

from . import githelper


class MergeRebaseDialog(QtWidgets.QDialog):
    """Dialog for running ``git merge`` or ``git rebase`` on a branch.

    Parameters
    ----------
    parent : QWidget
        Parent widget (typically the :class:`~browser.Browser`).
    repo_root : str
        Absolute path to the git repository root.
    current_branch : str or None
        Name of the currently checked-out branch (used for display only).
    """

    def __init__(self, parent, repo_root, current_branch=None):
        super().__init__(parent)
        self._repo_root = repo_root
        self._current_branch = current_branch or ""
        self._process = None

        self.setWindowTitle("Merge / Rebase Branch")
        self.setMinimumWidth(480)
        self._build_ui()
        self._populate_branches()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)

        # --- target branch row ---
        branch_row = QtWidgets.QHBoxLayout()
        branch_row.addWidget(QtWidgets.QLabel("Branch:"))
        self._branchCombo = QtWidgets.QComboBox()
        self._branchCombo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        branch_row.addWidget(self._branchCombo)
        layout.addLayout(branch_row)

        # --- current branch hint ---
        if self._current_branch:
            hint = QtWidgets.QLabel(
                "Current branch: <b>{}</b>".format(self._current_branch)
            )
            hint.setTextFormat(QtCore.Qt.TextFormat.RichText)
            layout.addWidget(hint)

        # --- action buttons ---
        btn_row = QtWidgets.QHBoxLayout()
        self._mergeBtn = QtWidgets.QPushButton("Merge branch")
        self._mergeBtn.setToolTip(
            "Run: git merge &lt;selected branch&gt;"
        )
        self._rebaseBtn = QtWidgets.QPushButton("Rebase onto…")
        self._rebaseBtn.setToolTip(
            "Run: git rebase &lt;selected branch&gt;"
        )
        btn_row.addWidget(self._mergeBtn)
        btn_row.addWidget(self._rebaseBtn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # --- log output ---
        self._log = QtWidgets.QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(140)
        font = QtGui.QFont("Monospace")
        font.setStyleHint(QtGui.QFont.StyleHint.TypeWriter)
        self._log.setFont(font)
        layout.addWidget(self._log)

        # --- conflict panel (hidden until conflicts are detected) ---
        self._conflictPanel = QtWidgets.QWidget()
        conflict_layout = QtWidgets.QVBoxLayout(self._conflictPanel)
        conflict_layout.setContentsMargins(0, 0, 0, 0)

        conflict_header = QtWidgets.QHBoxLayout()
        warn_icon = QtWidgets.QApplication.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning
        )
        warn_label = QtWidgets.QLabel()
        warn_label.setPixmap(warn_icon.pixmap(16, 16))
        conflict_header.addWidget(warn_label)
        conflict_header.addWidget(
            QtWidgets.QLabel("<b>Conflicts detected – resolve before committing:</b>"),
        )
        conflict_header.addStretch()
        conflict_layout.addLayout(conflict_header)

        self._conflictList = QtWidgets.QListWidget()
        self._conflictList.setMaximumHeight(120)
        conflict_layout.addWidget(self._conflictList)

        tip = QtWidgets.QLabel(
            "Open each conflicted file, resolve the markers, "
            "then run <tt>git add &lt;file&gt;</tt> followed by "
            "<tt>git commit</tt> (or <tt>git rebase --continue</tt>)."
        )
        tip.setWordWrap(True)
        conflict_layout.addWidget(tip)

        self._conflictPanel.setVisible(False)
        layout.addWidget(self._conflictPanel)

        # --- close button ---
        close_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

        # --- connect signals ---
        self._mergeBtn.clicked.connect(self._onMerge)
        self._rebaseBtn.clicked.connect(self._onRebase)

    # ------------------------------------------------------------------
    # Branch population
    # ------------------------------------------------------------------

    def _populate_branches(self):
        branches = githelper.list_git_branches(self._repo_root)
        # Exclude the current branch from the list – merging/rebasing onto
        # yourself makes no sense.
        branches = [b for b in branches if b != self._current_branch]
        self._branchCombo.clear()
        self._branchCombo.addItems(branches)
        has_branches = bool(branches)
        self._mergeBtn.setEnabled(has_branches)
        self._rebaseBtn.setEnabled(has_branches)
        if not has_branches:
            self._log.appendPlainText("No other local branches found.")

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _onMerge(self):
        branch = self._branchCombo.currentText()
        if branch:
            self._run_git(["merge", branch])

    def _onRebase(self):
        branch = self._branchCombo.currentText()
        if branch:
            self._run_git(["rebase", branch])

    # ------------------------------------------------------------------
    # Git process execution
    # ------------------------------------------------------------------

    def _run_git(self, args):
        """Start a git subprocess with *args* and stream its output to the log."""
        if self._process and self._process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self._log.appendPlainText("A git operation is already running.")
            return

        self._log.clear()
        self._conflictPanel.setVisible(False)
        self._conflictList.clear()

        self._mergeBtn.setEnabled(False)
        self._rebaseBtn.setEnabled(False)

        cmd_display = "git " + " ".join(args)
        self._log.appendPlainText("$ " + cmd_display)

        self._process = QtCore.QProcess(self)
        self._process.setWorkingDirectory(self._repo_root)
        self._process.setProcessChannelMode(
            QtCore.QProcess.ProcessChannelMode.MergedChannels
        )
        self._process.readyRead.connect(self._onReadyRead)
        self._process.finished.connect(self._onFinished)
        self._process.start("git", args)

    def _onReadyRead(self):
        raw = bytes(self._process.readAll())
        text = raw.decode("utf-8", errors="replace")
        self._log.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def _onFinished(self, exit_code, exit_status):
        self._mergeBtn.setEnabled(True)
        self._rebaseBtn.setEnabled(True)

        if exit_code == 0:
            self._log.appendPlainText("\n✓ Done.")
        else:
            self._log.appendPlainText(
                "\n✗ git exited with code {}.".format(exit_code)
            )
            self._check_conflicts()

    def _check_conflicts(self):
        """Check for merge conflicts and populate the conflict panel."""
        status = githelper.get_git_status(self._repo_root)
        if status is None or not status.has_conflicts():
            return

        warn_icon = QtWidgets.QApplication.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning
        )
        for abs_path in status.get_conflicted_files():
            rel = op.relpath(abs_path, self._repo_root)
            item = QtWidgets.QListWidgetItem(warn_icon, rel)
            self._conflictList.addItem(item)

        self._conflictPanel.setVisible(True)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._process and self._process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(2000)
        super().closeEvent(event)
