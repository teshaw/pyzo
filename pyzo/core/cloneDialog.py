"""Clone repository dialog.

Provides a simple dialog that clones a remote git repository into a
chosen local folder and then opens the result in the Pyzo file browser.
"""

import os
import os.path as op
import re

from pyzo.qt import QtCore, QtGui, QtWidgets

import pyzo
from pyzo import translate


class CloneDialog(QtWidgets.QDialog):
    """Dialog for cloning a remote git repository.

    Fields
    ------
    * Repository URL – the remote URL to clone.
    * Destination folder – a local folder (folder picker).
    * Branch (optional) – a specific branch to check out.

    The dialog validates that the destination folder is either empty or does
    not exist before starting the clone operation.  Progress is streamed to a
    read-only log widget.  After a successful clone the new folder is opened
    in the Pyzo file browser.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate("menu dialog", "Clone Repository"))
        self.resize(600, 480)
        self.setModal(True)

        self._process = None
        self._dest_path = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(layout)

        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        layout.addLayout(form)

        # Repository URL
        self._urlEdit = QtWidgets.QLineEdit(self)
        self._urlEdit.setPlaceholderText(
            translate("cloneDialog", "https://github.com/user/repo.git")
        )
        form.addRow(translate("cloneDialog", "Repository URL:"), self._urlEdit)

        # Destination folder
        destRow = QtWidgets.QHBoxLayout()
        self._destEdit = QtWidgets.QLineEdit(self)
        self._destEdit.setPlaceholderText(
            translate("cloneDialog", "/path/to/destination")
        )
        self._destButton = QtWidgets.QPushButton(
            translate("cloneDialog", "Browse…"), self
        )
        self._destButton.clicked.connect(self._browse_dest)
        destRow.addWidget(self._destEdit)
        destRow.addWidget(self._destButton)
        form.addRow(translate("cloneDialog", "Destination folder:"), destRow)

        # Branch (optional)
        self._branchEdit = QtWidgets.QLineEdit(self)
        self._branchEdit.setPlaceholderText(
            translate("cloneDialog", "main  (leave empty for default branch)")
        )
        form.addRow(translate("cloneDialog", "Branch (optional):"), self._branchEdit)

        # Log / progress output
        self._log = QtWidgets.QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        self._log.setMinimumHeight(160)
        layout.addWidget(self._log)

        # Status label
        self._statusLabel = QtWidgets.QLabel("", self)
        layout.addWidget(self._statusLabel)

        # Button box
        self._buttonBox = QtWidgets.QDialogButtonBox(self)
        self._cloneButton = self._buttonBox.addButton(
            translate("cloneDialog", "Clone"),
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._closeButton = self._buttonBox.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        layout.addWidget(self._buttonBox)

        self._buttonBox.accepted.connect(self._start_clone)
        self._buttonBox.rejected.connect(self._on_close)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse_dest(self):
        """Open a folder-picker dialog and fill the destination field."""
        start = self._destEdit.text().strip() or op.expanduser("~")
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            translate("cloneDialog", "Choose destination folder"),
            start,
        )
        if folder:
            self._destEdit.setText(folder)

    def _start_clone(self):
        """Validate inputs and launch the git clone subprocess."""
        url = self._urlEdit.text().strip()
        dest = self._destEdit.text().strip()
        branch = self._branchEdit.text().strip()

        # --- validation ---
        if not url:
            self._show_error(translate("cloneDialog", "Please enter a repository URL."))
            return
        if not dest:
            self._show_error(
                translate("cloneDialog", "Please choose a destination folder.")
            )
            return

        dest = op.abspath(dest)

        if op.exists(dest):
            if not op.isdir(dest):
                self._show_error(
                    translate(
                        "cloneDialog",
                        "The destination path exists but is not a directory.",
                    )
                )
                return
            if os.listdir(dest):
                self._show_error(
                    translate(
                        "cloneDialog",
                        "The destination folder is not empty. "
                        "Please choose an empty folder or a path that does not exist.",
                    )
                )
                return

        # --- build command ---
        cmd = ["git", "clone"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [url, dest]

        self._dest_path = dest

        # --- disable UI while running ---
        self._cloneButton.setEnabled(False)
        self._urlEdit.setEnabled(False)
        self._destEdit.setEnabled(False)
        self._destButton.setEnabled(False)
        self._branchEdit.setEnabled(False)
        self._log.clear()
        self._set_status(translate("cloneDialog", "Cloning…"))

        # --- launch process ---
        self._process = QtCore.QProcess(self)
        self._process.setProcessChannelMode(
            QtCore.QProcess.ProcessChannelMode.MergedChannels
        )
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)

        self._process.start(cmd[0], cmd[1:])

    def _on_output(self):
        """Append new process output to the log widget."""
        raw = self._process.readAllStandardOutput()
        text = bytes(raw).decode("utf-8", errors="replace")
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        self._log.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def _on_finished(self, exit_code, exit_status):
        """Handle process completion."""
        success = (
            exit_code == 0
            and exit_status == QtCore.QProcess.ExitStatus.NormalExit
        )

        # Re-enable form
        self._cloneButton.setEnabled(True)
        self._urlEdit.setEnabled(True)
        self._destEdit.setEnabled(True)
        self._destButton.setEnabled(True)
        self._branchEdit.setEnabled(True)

        if success:
            self._set_status(
                translate("cloneDialog", "Clone completed successfully."), ok=True
            )
            self._open_in_file_browser(self._dest_path)
        else:
            self._set_status(
                translate(
                    "cloneDialog",
                    "Clone failed (exit code {}). See the log above for details.".format(exit_code),
                ),
                ok=False,
            )

        self._process = None

    def _on_close(self):
        """Handle Close button – kill any running process first."""
        if self._process is not None:
            if self._process.state() != QtCore.QProcess.ProcessState.NotRunning:
                self._process.kill()
                self._process.waitForFinished(2000)
        self.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _show_error(self, message):
        QtWidgets.QMessageBox.warning(self, translate("cloneDialog", "Clone Repository"), message)

    def _set_status(self, message, ok=None):
        self._statusLabel.setText(message)
        if ok is True:
            self._statusLabel.setStyleSheet("color: green;")
        elif ok is False:
            self._statusLabel.setStyleSheet("color: red;")
        else:
            self._statusLabel.setStyleSheet("")

    def _open_in_file_browser(self, path):
        """Open *path* in the Pyzo file browser tool (if available)."""
        try:
            fileBrowser = pyzo.toolManager.getTool("pyzofilebrowser")
            if fileBrowser is not None:
                fileBrowser.setPath(path)
        except Exception:
            pass
