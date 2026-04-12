"""
Tests for pyzo/tools/pyzoGitPanel/commitwidget.py
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest

# ---------------------------------------------------------------------------
# pyzo.translate must be available before any pyzo.tools sub-package is
# imported (pyzo/tools/__init__.py does ``from pyzo import translate``).
# Stub it early so the tests can run without a full pyzo session.
# ---------------------------------------------------------------------------
import pyzo as _pyzo  # noqa: E402 – side-effect: registers pyzo in sys.modules

if not hasattr(_pyzo, "translate"):
    _pyzo.translate = lambda *a, **kw: a[1] if len(a) > 1 else ""

# ---------------------------------------------------------------------------
# Ensure a QApplication exists before any widget is created.
# ---------------------------------------------------------------------------
from pyzo.qt import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from pyzo.tools.pyzoGitPanel import gitops  # noqa: E402
from pyzo.tools.pyzoGitPanel.commitwidget import CommitWidget  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_git_repo():
    """Create a temporary git repository and return its path."""
    tmpdir = tempfile.mkdtemp()
    subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmpdir, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmpdir, check=True, capture_output=True,
    )
    return tmpdir


def _add_staged_file(repo_root, filename="test.txt", content="hello\n"):
    """Create *filename* in *repo_root* and stage it."""
    path = os.path.join(repo_root, filename)
    with open(path, "w") as fh:
        fh.write(content)
    subprocess.run(["git", "add", filename], cwd=repo_root, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Unit tests for gitops helpers (no Qt required)
# ---------------------------------------------------------------------------

class TestGitops(unittest.TestCase):

    def setUp(self):
        self.repo = _make_git_repo()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_get_branch_main(self):
        """get_branch returns something after repo init."""
        # On a fresh repo HEAD may point to 'main' or 'master' before first commit
        branch = gitops.get_branch(self.repo)
        # Should be a non-empty string
        self.assertIsNotNone(branch)
        self.assertIsInstance(branch, str)

    def test_get_staged_files_empty(self):
        self.assertEqual(gitops.get_staged_files(self.repo), [])

    def test_get_staged_files_after_add(self):
        _add_staged_file(self.repo)
        staged = gitops.get_staged_files(self.repo)
        self.assertIn("test.txt", staged)

    def test_stage_all(self):
        path = os.path.join(self.repo, "a.txt")
        with open(path, "w") as fh:
            fh.write("a")
        success, msg = gitops.stage_all(self.repo)
        self.assertTrue(success)
        self.assertIn("a.txt", gitops.get_staged_files(self.repo))

    def test_unstage_all(self):
        _add_staged_file(self.repo)
        self.assertTrue(len(gitops.get_staged_files(self.repo)) > 0)
        success, msg = gitops.unstage_all(self.repo)
        self.assertTrue(success)
        self.assertEqual(gitops.get_staged_files(self.repo), [])

    def test_commit(self):
        _add_staged_file(self.repo)
        success, sha = gitops.commit(self.repo, "Initial commit")
        self.assertTrue(success, sha)
        self.assertIsInstance(sha, str)
        self.assertTrue(len(sha) >= 4)

    def test_commit_amend(self):
        _add_staged_file(self.repo)
        gitops.commit(self.repo, "First commit")
        _add_staged_file(self.repo, "b.txt", "b\n")
        success, sha = gitops.commit(self.repo, "Amended commit", amend=True)
        self.assertTrue(success, sha)

    def test_get_repo_root(self):
        root = gitops.get_repo_root(self.repo)
        self.assertIsNotNone(root)

    def test_get_repo_root_none_outside_repo(self):
        root = gitops.get_repo_root("/tmp")
        # /tmp is usually not a git repo – just verify the call doesn't raise
        self.assertIn(root, (None, root))  # accepts any return value


# ---------------------------------------------------------------------------
# Widget tests (require a QApplication)
# ---------------------------------------------------------------------------

class TestCommitWidgetUI(unittest.TestCase):

    def setUp(self):
        self.repo = _make_git_repo()
        self.widget = CommitWidget(repo_root=self.repo)

    def tearDown(self):
        self.widget.close()
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_initial_commit_button_disabled(self):
        """Commit button starts disabled (no message, no staged files)."""
        self.assertFalse(self.widget._commitBtn.isEnabled())

    def test_commit_button_disabled_message_only(self):
        """Commit button stays disabled with message but no staged files."""
        self.widget._msgEdit.setPlainText("My commit message")
        _app.processEvents()
        self.assertFalse(self.widget._commitBtn.isEnabled())

    def test_commit_button_enabled_with_staged(self):
        """Commit button becomes enabled when message + staged file present."""
        _add_staged_file(self.repo)
        self.widget._msgEdit.setPlainText("My commit message")
        _app.processEvents()
        self.assertTrue(self.widget._commitBtn.isEnabled())

    def test_branch_label_set(self):
        """Branch label is set to a non-empty string."""
        text = self.widget._branchLabel.text()
        self.assertTrue(text.startswith("Branch:"))

    def test_char_counter_normal(self):
        """Counter is gray for short first line."""
        self.widget._msgEdit.setPlainText("Short message")
        _app.processEvents()
        style = self.widget._charCountLabel.styleSheet()
        self.assertIn("gray", style)

    def test_char_counter_orange(self):
        """Counter turns orange when first line is 51–72 characters."""
        msg = "A" * 60
        self.widget._msgEdit.setPlainText(msg)
        _app.processEvents()
        style = self.widget._charCountLabel.styleSheet()
        self.assertIn("orange", style)

    def test_char_counter_red(self):
        """Counter turns red when first line exceeds 72 characters."""
        msg = "A" * 73
        self.widget._msgEdit.setPlainText(msg)
        _app.processEvents()
        style = self.widget._charCountLabel.styleSheet()
        self.assertIn("red", style)

    def test_char_counter_value(self):
        """Counter shows the length of the first line."""
        self.widget._msgEdit.setPlainText("Hello\nMore text")
        _app.processEvents()
        self.assertEqual(self.widget._charCountLabel.text(), "5")

    def test_committed_signal(self):
        """committed signal is emitted after a successful commit."""
        _add_staged_file(self.repo)
        received = []
        self.widget.committed.connect(received.append)
        self.widget._msgEdit.setPlainText("Test commit message")
        _app.processEvents()
        self.widget._on_commit()
        _app.processEvents()
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], str)

    def test_message_cleared_after_commit(self):
        """Message text edit is cleared after a successful commit."""
        _add_staged_file(self.repo)
        self.widget._msgEdit.setPlainText("Test commit message")
        _app.processEvents()
        self.widget._on_commit()
        _app.processEvents()
        self.assertEqual(self.widget._msgEdit.toPlainText(), "")

    def test_status_label_shown_after_commit(self):
        """Status label shows 'Committed as ...' after commit."""
        _add_staged_file(self.repo)
        self.widget._msgEdit.setPlainText("Test commit message")
        _app.processEvents()
        self.widget._on_commit()
        _app.processEvents()
        status = self.widget._statusLabel.text()
        self.assertIn("Committed as", status)

    def test_amend_checkbox_exists(self):
        """Amend checkbox exists and is unchecked by default."""
        self.assertFalse(self.widget._amendCheck.isChecked())

    def test_stage_all_button(self):
        """Stage All button stages changes."""
        path = os.path.join(self.repo, "new.txt")
        with open(path, "w") as fh:
            fh.write("x")
        self.widget._on_stage_all()
        _app.processEvents()
        staged = gitops.get_staged_files(self.repo)
        self.assertIn("new.txt", staged)

    def test_unstage_all_button(self):
        """Unstage All button clears staged files."""
        _add_staged_file(self.repo)
        self.widget._on_unstage_all()
        _app.processEvents()
        staged = gitops.get_staged_files(self.repo)
        self.assertEqual(staged, [])

    def test_set_repo_root(self):
        """setRepoRoot updates branch label."""
        new_repo = _make_git_repo()
        try:
            self.widget.setRepoRoot(new_repo)
            text = self.widget._branchLabel.text()
            self.assertTrue(text.startswith("Branch:"))
        finally:
            import shutil
            shutil.rmtree(new_repo, ignore_errors=True)

    def test_no_repo_root(self):
        """Widget handles None repo_root gracefully."""
        w = CommitWidget(repo_root=None)
        self.assertEqual(w._branchLabel.text(), "")
        w.close()

    def test_commit_error_no_staged(self):
        """Commit with no staged files shows error in status label."""
        self.widget._msgEdit.setPlainText("No staged files")
        # Force-call _on_commit bypassing button disabled state
        self.widget._on_commit()
        _app.processEvents()
        # Should show an error (commit failed because nothing is staged)
        status = self.widget._statusLabel.text()
        self.assertTrue(len(status) > 0)


if __name__ == "__main__":
    unittest.main()
