"""
Unit tests for pyzo.tools.gitops.

All tests mock ``subprocess.run`` so no real git repository is needed.

The module is loaded directly via ``importlib`` to avoid triggering the
``pyzo/tools/__init__.py`` import, which requires a Qt installation.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load gitops directly so we do not trigger pyzo/tools/__init__.py (Qt).
_spec = importlib.util.spec_from_file_location(
    "pyzo.tools.gitops",
    Path(__file__).parent.parent / "pyzo" / "tools" / "gitops.py",
)
_gitops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gitops)
_subprocess = _gitops.subprocess  # used by patch.object() in tests below

GitNotFoundError = _gitops.GitNotFoundError
stage_file = _gitops.stage_file
unstage_file = _gitops.unstage_file
revert_file = _gitops.revert_file
ignore_file = _gitops.ignore_file
commit = _gitops.commit
get_branch = _gitops.get_branch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed_process(returncode=0, stdout="", stderr=""):
    """Return a fake ``subprocess.CompletedProcess`` object."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


REPO = Path("/fake/repo")
FILE = Path("/fake/repo/src/foo.py")


# ---------------------------------------------------------------------------
# GitNotFoundError
# ---------------------------------------------------------------------------


def _patch_git_missing():
    """Context manager that makes subprocess.run raise FileNotFoundError."""
    return patch.object(
        _subprocess,
        "run",
        side_effect=FileNotFoundError("git not found"),
    )


def test_stage_file_raises_git_not_found():
    with _patch_git_missing():
        with pytest.raises(GitNotFoundError):
            stage_file(REPO, FILE)


def test_unstage_file_raises_git_not_found():
    with _patch_git_missing():
        with pytest.raises(GitNotFoundError):
            unstage_file(REPO, FILE)


def test_revert_file_raises_git_not_found():
    with _patch_git_missing():
        with pytest.raises(GitNotFoundError):
            revert_file(REPO, FILE)


def test_commit_raises_git_not_found():
    with _patch_git_missing():
        with pytest.raises(GitNotFoundError):
            commit(REPO, "msg")


def test_get_branch_raises_git_not_found():
    with _patch_git_missing():
        with pytest.raises(GitNotFoundError):
            get_branch(REPO)


# ---------------------------------------------------------------------------
# stage_file
# ---------------------------------------------------------------------------


def test_stage_file_success():
    cp = _make_completed_process(returncode=0, stdout="", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = stage_file(REPO, FILE)

    assert ok is True
    assert out == ""
    mock_run.assert_called_once_with(
        ["git", "add", str(FILE)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_stage_file_failure():
    cp = _make_completed_process(returncode=1, stdout="", stderr="error: pathspec")
    with patch.object(_subprocess, "run", return_value=cp):
        ok, out = stage_file(REPO, FILE)

    assert ok is False
    assert "pathspec" in out


# ---------------------------------------------------------------------------
# unstage_file
# ---------------------------------------------------------------------------


def test_unstage_file_success():
    cp = _make_completed_process(returncode=0, stdout="", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = unstage_file(REPO, FILE)

    assert ok is True
    mock_run.assert_called_once_with(
        ["git", "restore", "--staged", str(FILE)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_unstage_file_failure():
    cp = _make_completed_process(
        returncode=1, stdout="", stderr="fatal: not a git repo"
    )
    with patch.object(_subprocess, "run", return_value=cp):
        ok, out = unstage_file(REPO, FILE)

    assert ok is False
    assert "git repo" in out


# ---------------------------------------------------------------------------
# revert_file
# ---------------------------------------------------------------------------


def test_revert_file_success():
    cp = _make_completed_process(returncode=0, stdout="", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = revert_file(REPO, FILE)

    assert ok is True
    mock_run.assert_called_once_with(
        ["git", "checkout", "HEAD", "--", str(FILE)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_revert_file_failure():
    cp = _make_completed_process(returncode=1, stdout="", stderr="error: did not match")
    with patch.object(_subprocess, "run", return_value=cp):
        ok, out = revert_file(REPO, FILE)

    assert ok is False
    assert "match" in out


# ---------------------------------------------------------------------------
# ignore_file
# ---------------------------------------------------------------------------


def test_ignore_file_creates_gitignore(tmp_path):
    repo = tmp_path
    filepath = repo / "secret.txt"
    ok, out = ignore_file(repo, filepath)

    assert ok is True
    gitignore = repo / ".gitignore"
    assert gitignore.exists()
    assert "secret.txt\n" in gitignore.read_text()


def test_ignore_file_appends_to_existing(tmp_path):
    repo = tmp_path
    gitignore = repo / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")

    filepath = repo / "build" / "output.o"
    ok, out = ignore_file(repo, filepath)

    assert ok is True
    content = gitignore.read_text(encoding="utf-8")
    assert "*.pyc" in content
    assert "build/output.o" in content


def test_ignore_file_idempotent(tmp_path):
    repo = tmp_path
    gitignore = repo / ".gitignore"
    gitignore.write_text("secret.txt\n", encoding="utf-8")

    filepath = repo / "secret.txt"
    ok, _ = ignore_file(repo, filepath)
    ok2, _ = ignore_file(repo, filepath)

    assert ok is True
    assert ok2 is True
    # Entry must appear exactly once.
    content = gitignore.read_text(encoding="utf-8")
    assert content.count("secret.txt") == 1


def test_ignore_file_relative_path(tmp_path):
    repo = tmp_path
    # Pass a path that is already relative to the repo.
    ok, _ = ignore_file(repo, Path("data/cache.db"))

    gitignore = repo / ".gitignore"
    assert ok is True
    assert "data/cache.db" in gitignore.read_text(encoding="utf-8")


def test_ignore_file_no_double_newline(tmp_path):
    """Appending to a file that already ends with a newline must not add a blank line."""
    repo = tmp_path
    gitignore = repo / ".gitignore"
    gitignore.write_text("*.pyc\n", encoding="utf-8")

    ignore_file(repo, repo / "foo.txt")
    content = gitignore.read_text(encoding="utf-8")
    # There should be no blank line between *.pyc and foo.txt
    assert "\n\n" not in content


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


def test_commit_basic():
    cp = _make_completed_process(returncode=0, stdout="[main abc1234] msg", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = commit(REPO, "Initial commit")

    assert ok is True
    mock_run.assert_called_once_with(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_commit_with_amend():
    cp = _make_completed_process(
        returncode=0, stdout="[main abc1234] amended", stderr=""
    )
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = commit(REPO, "fix typo", amend=True)

    assert ok is True
    args_used = mock_run.call_args[0][0]
    assert "--amend" in args_used


def test_commit_with_author():
    cp = _make_completed_process(returncode=0, stdout="[main abc1234] msg", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = commit(REPO, "feat: add x", author="Dev <dev@example.com>")

    assert ok is True
    args_used = mock_run.call_args[0][0]
    assert "--author" in args_used
    assert "Dev <dev@example.com>" in args_used


def test_commit_with_amend_and_author():
    cp = _make_completed_process(returncode=0, stdout="[main abc1234] msg", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, out = commit(
            REPO, "chore: cleanup", author="Dev <dev@example.com>", amend=True
        )

    assert ok is True
    args_used = mock_run.call_args[0][0]
    assert "--amend" in args_used
    assert "--author" in args_used


def test_commit_failure():
    cp = _make_completed_process(returncode=1, stdout="", stderr="nothing to commit")
    with patch.object(_subprocess, "run", return_value=cp):
        ok, out = commit(REPO, "empty")

    assert ok is False
    assert "nothing to commit" in out


# ---------------------------------------------------------------------------
# get_branch
# ---------------------------------------------------------------------------


def test_get_branch_success():
    cp = _make_completed_process(returncode=0, stdout="main", stderr="")
    with patch.object(_subprocess, "run", return_value=cp) as mock_run:
        ok, branch = get_branch(REPO)

    assert ok is True
    assert branch == "main"
    mock_run.assert_called_once_with(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_get_branch_detached_head():
    cp = _make_completed_process(returncode=0, stdout="HEAD", stderr="")
    with patch.object(_subprocess, "run", return_value=cp):
        ok, branch = get_branch(REPO)

    assert ok is True
    assert branch == "HEAD"


def test_get_branch_failure():
    cp = _make_completed_process(
        returncode=128, stdout="", stderr="fatal: not a git repository"
    )
    with patch.object(_subprocess, "run", return_value=cp):
        ok, out = get_branch(REPO)

    assert ok is False
    assert "not a git repository" in out
