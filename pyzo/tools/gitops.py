"""
Git write-side operations for Pyzo.

Provides foundational git operations used by the panel and the diff gutter.
All functions call the system ``git`` binary via ``subprocess``; no external
libraries are required.

Each public function returns a ``(success: bool, output: str)`` tuple and
raises :class:`GitNotFoundError` when the ``git`` binary cannot be found.
Paths are handled via :mod:`pathlib`; arguments are passed as a list
(``shell=False``).
"""

import subprocess
from pathlib import Path


class GitNotFoundError(Exception):
    """Raised when the ``git`` binary is not found on the system."""


def _run_git(args, cwd):
    """Run a git command and return ``(success, output)``.

    Parameters
    ----------
    args : list[str]
        Full argument list, starting with ``"git"``.
    cwd : Path
        Working directory for the subprocess.

    Returns
    -------
    tuple[bool, str]
        ``(True, stdout)`` on success, ``(False, stderr)`` on failure.

    Raises
    ------
    GitNotFoundError
        When the ``git`` binary is not found.
    """
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise GitNotFoundError(
            "git binary not found. Please install git and ensure it is on PATH."
        )
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, result.stderr.strip()


def stage_file(repo_root, filepath):
    """Stage *filepath* (``git add <file>``).

    Parameters
    ----------
    repo_root : str or Path
        Absolute path to the repository root.
    filepath : str or Path
        Path to the file to stage (absolute or relative to *repo_root*).

    Returns
    -------
    tuple[bool, str]
        ``(True, stdout)`` on success, ``(False, stderr)`` on failure.

    Raises
    ------
    GitNotFoundError
        When the ``git`` binary is not found.
    """
    repo_root = Path(repo_root)
    filepath = Path(filepath)
    return _run_git(["git", "add", str(filepath)], cwd=repo_root)


def unstage_file(repo_root, filepath):
    """Unstage *filepath* (``git restore --staged <file>``).

    Parameters
    ----------
    repo_root : str or Path
        Absolute path to the repository root.
    filepath : str or Path
        Path to the file to unstage (absolute or relative to *repo_root*).

    Returns
    -------
    tuple[bool, str]
        ``(True, stdout)`` on success, ``(False, stderr)`` on failure.

    Raises
    ------
    GitNotFoundError
        When the ``git`` binary is not found.
    """
    repo_root = Path(repo_root)
    filepath = Path(filepath)
    return _run_git(["git", "restore", "--staged", str(filepath)], cwd=repo_root)


def revert_file(repo_root, filepath):
    """Revert *filepath* to HEAD (``git checkout HEAD -- <file>``).

    The caller is responsible for confirming the operation before calling
    this function, as it will discard all working-tree changes to the file.

    Parameters
    ----------
    repo_root : str or Path
        Absolute path to the repository root.
    filepath : str or Path
        Path to the file to revert (absolute or relative to *repo_root*).

    Returns
    -------
    tuple[bool, str]
        ``(True, stdout)`` on success, ``(False, stderr)`` on failure.

    Raises
    ------
    GitNotFoundError
        When the ``git`` binary is not found.
    """
    repo_root = Path(repo_root)
    filepath = Path(filepath)
    return _run_git(["git", "checkout", "HEAD", "--", str(filepath)], cwd=repo_root)


def ignore_file(repo_root, filepath):
    """Append the relative path of *filepath* to ``.gitignore``.

    If ``.gitignore`` does not exist it is created.  If the relative path is
    already present as a line the file is not modified (idempotent).

    Parameters
    ----------
    repo_root : str or Path
        Absolute path to the repository root.
    filepath : str or Path
        Path to the file to ignore.  May be absolute or relative to
        *repo_root*.

    Returns
    -------
    tuple[bool, str]
        ``(True, "")`` when the entry was added (or already present),
        ``(False, error_message)`` on I/O failure.

    Raises
    ------
    GitNotFoundError
        Not raised by this function (no git subprocess is used), but the
        signature is consistent with the rest of the module.
    """
    repo_root = Path(repo_root)
    filepath = Path(filepath)
    # Compute path relative to repo root, using forward slashes (standard for
    # .gitignore regardless of platform).
    try:
        rel = filepath.relative_to(repo_root)
    except ValueError:
        # filepath is already relative
        rel = filepath
    rel_str = rel.as_posix()

    gitignore = repo_root / ".gitignore"
    try:
        if gitignore.exists():
            existing = gitignore.read_text(encoding="utf-8")
            # Check for exact line match to stay idempotent.
            lines = existing.splitlines()
            if rel_str in lines:
                return True, ""
            # Ensure a trailing newline before appending.
            prefix = "" if existing.endswith("\n") or existing == "" else "\n"
            gitignore.write_text(existing + prefix + rel_str + "\n", encoding="utf-8")
        else:
            gitignore.write_text(rel_str + "\n", encoding="utf-8")
    except OSError as exc:
        return False, str(exc)
    return True, ""


def commit(repo_root, message, author=None, amend=False):
    """Create a git commit.

    Parameters
    ----------
    repo_root : str or Path
        Absolute path to the repository root.
    message : str
        Commit message.
    author : str or None
        Optional author string in ``"Name <email>"`` format.
    amend : bool
        When ``True``, amend the previous commit (``--amend``).

    Returns
    -------
    tuple[bool, str]
        ``(True, stdout)`` on success, ``(False, stderr)`` on failure.

    Raises
    ------
    GitNotFoundError
        When the ``git`` binary is not found.
    """
    repo_root = Path(repo_root)
    args = ["git", "commit", "-m", message]
    if amend:
        args.append("--amend")
    if author:
        args.extend(["--author", author])
    return _run_git(args, cwd=repo_root)


def get_branch(repo_root):
    """Return the current branch name.

    Uses ``git rev-parse --abbrev-ref HEAD``.

    Parameters
    ----------
    repo_root : str or Path
        Absolute path to the repository root.

    Returns
    -------
    tuple[bool, str]
        ``(True, branch_name)`` on success, ``(False, stderr)`` on failure.

    Raises
    ------
    GitNotFoundError
        When the ``git`` binary is not found.
    """
    repo_root = Path(repo_root)
    return _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
