"""
gitops.py — lightweight git operations for the pyzoGitPanel.

All operations use only the Python standard library (subprocess).
"""

import os
import os.path as op
import subprocess


def _run(args, cwd, timeout=10):
    """Run a git command in *cwd* and return ``(returncode, stdout, stderr)``.

    Parameters
    ----------
    args : list[str]
        Git sub-command and arguments (without the leading ``"git"``).
    cwd : str
        Working directory in which to run the command.
    timeout : int
        Maximum seconds to wait before raising ``subprocess.TimeoutExpired``.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
    )
    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    return result.returncode, stdout, stderr


def get_repo_root(path=None):
    """Return the git repository root for *path* (cwd if ``None``), or ``None``."""
    if path is None:
        path = os.getcwd()
    if not op.isdir(path):
        path = op.dirname(path)
    try:
        rc, out, _ = _run(["rev-parse", "--show-toplevel"], cwd=path)
        if rc == 0 and out:
            return out
    except Exception:
        pass
    return None


def get_branch(repo_root):
    """Return the current branch name for *repo_root*, or ``None``.

    Returns ``'HEAD:<short-sha>'`` in detached-HEAD state.
    """
    head_file = op.join(repo_root, ".git", "HEAD")
    try:
        with open(head_file, encoding="utf-8") as fh:
            content = fh.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        return "HEAD:" + content[:7]
    except Exception:
        pass
    # Fall back to git command
    try:
        rc, out, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
        if rc == 0 and out:
            return out
    except Exception:
        pass
    return None


def get_staged_files(repo_root):
    """Return a list of staged (index) file paths relative to *repo_root*."""
    try:
        rc, out, _ = _run(
            ["diff", "--name-only", "--cached"], cwd=repo_root
        )
        if rc == 0:
            return [f for f in out.splitlines() if f]
    except Exception:
        pass
    return []


def stage_all(repo_root):
    """Stage all changes (``git add -A``).

    Returns ``(success: bool, message: str)``.
    """
    try:
        rc, out, err = _run(["add", "-A"], cwd=repo_root)
        if rc == 0:
            return True, "All changes staged."
        return False, err or "git add -A failed."
    except Exception as exc:
        return False, str(exc)


def unstage_all(repo_root):
    """Unstage all staged changes.

    Uses ``git reset HEAD`` when a HEAD commit exists, otherwise falls back to
    ``git rm --cached -r .`` for repositories that have no commits yet.

    Returns ``(success: bool, message: str)``.
    """
    try:
        rc, out, err = _run(["reset", "HEAD"], cwd=repo_root)
        if rc == 0:
            return True, "All changes unstaged."
        # Likely no commits yet – fall back to removing from index
        rc2, out2, err2 = _run(["rm", "--cached", "-r", "."], cwd=repo_root)
        if rc2 == 0:
            return True, "All changes unstaged."
        return False, err2 or err or "Could not unstage changes."
    except Exception as exc:
        return False, str(exc)


def commit(repo_root, message, amend=False):
    """Create a commit in *repo_root* with *message*.

    Parameters
    ----------
    repo_root : str
        Absolute path to the repository root.
    message : str
        Commit message.
    amend : bool
        When ``True`` passes ``--amend`` to ``git commit``.

    Returns
    -------
    tuple[bool, str]
        ``(success, short_sha_or_error_message)``
    """
    args = ["commit", "-m", message]
    if amend:
        args.append("--amend")
    try:
        rc, out, err = _run(args, cwd=repo_root)
        if rc == 0:
            sha = _get_short_sha(repo_root)
            return True, sha
        return False, err or out or "git commit failed."
    except Exception as exc:
        return False, str(exc)


def _get_short_sha(repo_root):
    """Return the short SHA of the current HEAD commit."""
    try:
        rc, out, _ = _run(["rev-parse", "--short", "HEAD"], cwd=repo_root)
        if rc == 0 and out:
            return out
    except Exception:
        pass
    return "unknown"
