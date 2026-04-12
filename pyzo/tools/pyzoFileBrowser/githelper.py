"""
Git helper utilities for the pyzo file browser.

Provides lightweight, dependency-free git integration using only the
Python standard library.  subprocess is used only for `git status` and
`git show`.
`git diff`.
"""

import os
import os.path as op
import re
import subprocess
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Pure-Python helpers (no subprocess needed)
# ---------------------------------------------------------------------------


def get_git_root(path):
    """Return the git repository root for *path*, or ``None``.

    Walks up the directory tree looking for a ``.git`` directory.
    """
    if not op.isdir(path):
        path = op.dirname(path)
    current = op.abspath(path)
    while True:
        if op.isdir(op.join(current, ".git")):
            return current
        parent = op.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def get_git_branch(repo_root):
    """Return the current branch name for *repo_root*, or ``None``.

    Reads ``.git/HEAD`` directly - no subprocess required.
    Returns ``'HEAD:<short-sha>'`` when in detached-HEAD state.
    """
    head_file = op.join(repo_root, ".git", "HEAD")
    try:
        with open(head_file, encoding="utf-8") as fh:
            content = fh.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        # Detached HEAD - show short SHA
        return "HEAD:" + content[:7]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GitStatus - result object returned by get_git_status()
# ---------------------------------------------------------------------------


class GitStatus:
    """Holds the git status for one repository.

    Parameters
    ----------
    root : str
        Absolute path to the repository root (as returned by
        :func:`get_git_root`).
    status_dict : dict
        Mapping of *normalised* absolute paths to two-character XY
        status strings as produced by ``git status --porcelain``.
    """

    # Map of a *single* status character → RGB colour tuple.
    # X (index) and Y (working-tree) characters are looked up here.
    _CHAR_COLOR = {
        "M": (220, 140, 30),   # modified   - amber
        "A": (50, 170, 80),    # added       - green
        "R": (220, 140, 30),   # renamed     - amber
        "C": (220, 140, 30),   # copied      - amber
        "D": (200, 50, 50),    # deleted     - red
        "U": (200, 50, 50),    # unmerged    - red
        "?": (100, 180, 50),   # untracked   - lime-green
    }

    def __init__(self, root, status_dict):
        self.root = root
        # Pre-normalise all keys once so every lookup is O(1) / O(n) without
        # repeated normcase() calls per query.
        self._status = {op.normcase(k): v for k, v in status_dict.items()}

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def file_status(self, path):
        """Return the ``XY`` status string for *path*, or ``'  '`` if clean."""
        return self._status.get(op.normcase(path), "  ")

    def dir_has_changes(self, path):
        """Return ``True`` if any tracked file under *path* has a status."""
        prefix = op.normcase(path)
        if not prefix.endswith(os.sep):
            prefix = prefix + os.sep
        return any(p.startswith(prefix) for p in self._status)

    def get_color_for_xy(self, xy):
        """Return an RGB tuple for *xy*, or ``None`` when the file is clean."""
        x = xy[0] if len(xy) > 0 else " "
        y = xy[1] if len(xy) > 1 else " "

        # Working-tree status takes priority over index status for colour.
        for ch in (y, x):
            if ch in self._CHAR_COLOR:
                return self._CHAR_COLOR[ch]
        return None

    def get_dir_color(self, path):
        """Return an RGB tuple if any file under *path* has a status, else ``None``."""
        prefix = op.normcase(path)
        if not prefix.endswith(os.sep):
            prefix = prefix + os.sep
        for filepath, xy in self._status.items():
            if filepath.startswith(prefix):
                color = self.get_color_for_xy(xy)
                if color is not None:
                    return color
        return None


# ---------------------------------------------------------------------------
# subprocess-based git status
# ---------------------------------------------------------------------------


def get_git_status(repo_root):
    """Return a :class:`GitStatus` for *repo_root*, or ``None`` on failure.

    Uses ``git status --porcelain=v1 -z`` with NUL-terminated output to
    correctly handle filenames that contain spaces, quotes or non-ASCII
    characters without relying on Git's C-string quoting.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "-u"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        # NUL-terminated records: "XY <path>\0" or "XY <path>\0<orig>\0"
        # Decode with surrogateescape so binary filenames don't raise.
        raw = result.stdout.decode("utf-8", errors="surrogateescape")
        entries = raw.split("\0")
        status = {}
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            xy = entry[:2]
            path = entry[3:]
            # For rename/copy the original path follows as a separate entry
            if xy[0] in ("R", "C"):
                i += 1  # skip the original path entry
            abs_path = op.join(repo_root, path)
            status[abs_path] = xy
        return GitStatus(repo_root, status)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# subprocess-based git show (blob retrieval)
# ---------------------------------------------------------------------------


def get_file_blob(repo_root, relpath, ref="HEAD"):
    """Return the committed content of *relpath* at *ref* as a string.

    Runs ``git show <ref>:<relpath>`` inside *repo_root*.

    Parameters
    ----------
    repo_root : str
        Absolute path to the repository root (as returned by
        :func:`get_git_root`).
    relpath : str
        Path of the file relative to *repo_root*.  Windows backslashes
        are converted to forward slashes automatically.
    ref : str
        Any git revision accepted by ``git show`` (branch name, tag,
        commit SHA, …).  Defaults to ``'HEAD'``.

    Returns
    -------
    str or None
        Decoded file content, or ``None`` when the ref or path does not
        exist (or on any other git/subprocess error).
    """
    # Git always uses forward slashes in object paths, even on Windows.
    relpath = relpath.replace("\\", "/")
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{relpath}"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None
# Hunk - structured diff hunk data for the diff gutter
# ---------------------------------------------------------------------------


@dataclass
class Hunk:
    """Represents a single diff hunk from ``git diff`` output.

    Attributes
    ----------
    old_start : int
        Starting line number in the old (a) version.
    old_count : int
        Number of lines in the old (a) version.
    new_start : int
        Starting line number in the new (b) version.
    new_count : int
        Number of lines in the new (b) version.
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int


# Compiled regex for the ``@@ -a,b +c,d @@`` hunk header.
# The count fields (,b and ,d) are optional; when absent they default to 1.
_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
    re.MULTILINE,
)


def _parse_hunks(diff_output):
    """Parse *diff_output* and return a list of :class:`Hunk` objects.

    Parameters
    ----------
    diff_output : str
        Raw output from ``git diff``.

    Returns
    -------
    list[Hunk]
        Parsed hunks, or an empty list for binary files or empty output.
    """
    if "Binary files" in diff_output:
        return []
    hunks = []
    for m in _HUNK_RE.finditer(diff_output):
        old_start = int(m.group(1))
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_count = int(m.group(4)) if m.group(4) is not None else 1
        hunks.append(
            Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
            )
        )
    return hunks


def get_hunk_diff(filepath):
    """Return a list of :class:`Hunk` objects for *filepath*.

    Runs ``git diff HEAD -- <file>`` to obtain the diff of working-tree
    changes against HEAD.  For files that are staged but have no
    working-tree changes, falls back to ``git diff --cached -- <file>``
    to capture staged-only hunks.

    Parameters
    ----------
    filepath : str or pathlib.Path
        Absolute or relative path to the file to diff.

    Returns
    -------
    list[Hunk]
        Parsed diff hunks.  An empty list is returned when:

        * ``git`` is not available or exits with a non-zero status,
        * the file is not inside a git repository,
        * the file is not tracked / has no changes,
        * the file is binary.

    Notes
    -----
    Designed to be called from a ``QThread`` worker so that it does not
    block the Qt main thread.
    """
    filepath = str(filepath)
    repo_root = get_git_root(filepath)
    if repo_root is None:
        return []

    def _run_diff(extra_args):
        try:
            result = subprocess.run(
                ["git", "diff"] + extra_args + ["--", filepath],
                cwd=repo_root,
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return ""
            return result.stdout.decode("utf-8", errors="surrogateescape")
        except Exception:
            return ""

    # First try working-tree diff against HEAD (covers staged + unstaged).
    output = _run_diff(["HEAD"])
    if output:
        return _parse_hunks(output)

    # Fall back to staged-only diff for files that are fully staged.
    output = _run_diff(["--cached"])
    return _parse_hunks(output)
