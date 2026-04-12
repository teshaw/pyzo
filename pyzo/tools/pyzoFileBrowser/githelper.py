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

from pyzo.qt import QtCore

# XY status codes that indicate an unmerged (conflict) state.
_CONFLICT_CODES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})


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
# Internal helpers for background git-status parsing
# ---------------------------------------------------------------------------


def _parse_git_status(repo_root):
    """Run ``git status --porcelain`` and return a structured result dict.

    The returned dict has two keys:

    * ``"staged"``   – list of ``{"path": str, "xy": str}`` for every entry
      whose *index* status character (X) is not ``' '`` or ``'?'``.
    * ``"unstaged"`` – list of ``{"path": str, "xy": str}`` for every entry
      whose *working-tree* status character (Y) is not ``' '``.  Untracked
      files (``xy == "??"``), whose Y is ``'?'``, are included here.

    Returns ``{"staged": [], "unstaged": []}`` on any error.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "-u"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"staged": [], "unstaged": []}
        raw = result.stdout.decode("utf-8", errors="surrogateescape")
        entries = raw.split("\0")
        staged = []
        unstaged = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            xy = entry[:2]
            path = entry[3:]
            if xy[0] in ("R", "C"):
                i += 1  # skip next entry (original path) for renames/copies
            abs_path = op.join(repo_root, path)
            x, y = xy[0], xy[1]
            if x not in (" ", "?"):
                staged.append({"path": abs_path, "xy": xy})
            if y != " ":
                unstaged.append({"path": abs_path, "xy": xy})
        return {"staged": staged, "unstaged": unstaged}
    except Exception:
        return {"staged": [], "unstaged": []}


class _GitRefreshWorker(QtCore.QThread):
    """QThread that runs :func:`_parse_git_status` off the UI thread.

    Emits :attr:`result_ready` with the structured status dict when the
    subprocess finishes.  The worker is single-use: create a new instance
    for every :meth:`GitStatus.refresh` call.
    """

    result_ready = QtCore.Signal(dict)

    def __init__(self, repo_root, parent=None):
        super().__init__(parent)
        self._root = repo_root

    def run(self):
        data = _parse_git_status(self._root)
        self.result_ready.emit(data)


# ---------------------------------------------------------------------------
# GitStatus - result object returned by get_git_status()
# ---------------------------------------------------------------------------


class GitStatus(QtCore.QObject):
    """Holds the git status for one repository.

    Parameters
    ----------
    root : str
        Absolute path to the repository root (as returned by
        :func:`get_git_root`).
    status_dict : dict
        Mapping of *normalised* absolute paths to two-character XY
        status strings as produced by ``git status --porcelain``.

    Signals
    -------
    statusRefreshed(dict)
        Emitted when a background :meth:`refresh` completes.  The dict
        has keys ``"staged"`` and ``"unstaged"``, each a list of
        ``{"path": str, "xy": str}`` entries.
    """

    statusRefreshed = QtCore.Signal(dict)

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
        super().__init__()
        self.root = root
        # Pre-normalise all keys once so every lookup is O(1) / O(n) without
        # repeated normcase() calls per query.
        self._status = {op.normcase(k): v for k, v in status_dict.items()}
        self._worker = None  # most-recent (relevant) _GitRefreshWorker, or None
        # Keeps strong references to ALL in-flight workers so that the Python
        # wrapper outlives the C++ QThread's internal post-run cleanup.  Each
        # worker removes itself here from _on_worker_finished.
        self._running_workers = []

    # ------------------------------------------------------------------
    # Background refresh
    # ------------------------------------------------------------------

    def refresh(self):
        """Spawn a background :class:`_GitRefreshWorker` to re-run git status.

        If a previous refresh is still in-flight its result is silently
        discarded (checked in :meth:`_on_worker_result` via sender identity)
        so only the most-recent call's result is ever delivered.

        Emits :attr:`statusRefreshed` with the structured result dict once
        the worker finishes.
        """
        worker = _GitRefreshWorker(self.root)
        worker.result_ready.connect(self._on_worker_result)
        # _on_worker_finished releases the strong reference once the C++
        # QThread has fully exited, preventing "destroyed while running" aborts.
        worker.finished.connect(self._on_worker_finished)
        self._running_workers.append(worker)  # keep Python wrapper alive
        self._worker = worker
        worker.start()

    def _on_worker_result(self, data):
        """Slot called on the main thread when the background worker finishes.

        Updates the internal status mapping and emits :attr:`statusRefreshed`.
        Stale results (from a superseded worker) are silently ignored via a
        sender-identity check against :attr:`_worker`.
        """
        if self.sender() is not self._worker:
            return  # Stale result from a superseded refresh call
        # Rebuild the internal path→xy mapping from the structured data so
        # that the query helpers (file_status, dir_has_changes, …) stay
        # up-to-date after a background refresh.
        # A file may appear in both lists (e.g. xy="MM" → staged AND unstaged),
        # but always carries the same XY code, so iterating both lists together
        # is safe: duplicate assignments simply write the same value twice.
        new_status = {}
        for item in data.get("staged", []) + data.get("unstaged", []):
            new_status[op.normcase(item["path"])] = item["xy"]
        self._status = new_status
        # NOTE: do NOT clear self._worker here.  The C++ QThread may still be
        # in its post-run cleanup phase (about to emit 'finished').  Clearing
        # the Python reference now could trigger premature GC of the wrapper
        # and a "QThread destroyed while running" abort.  The reference is
        # cleared safely in _on_worker_finished once the thread has fully exited.
        self.statusRefreshed.emit(data)

    def _on_worker_finished(self):
        """Slot called on the main thread once the worker QThread fully exits.

        Removes the finished worker from the running-workers list so its Python
        wrapper can be collected, and clears :attr:`_worker` if this was the
        most-recent refresh worker.
        """
        worker = self.sender()
        try:
            self._running_workers.remove(worker)
        except ValueError:
            pass
        if worker is self._worker:
            self._worker = None

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

    def is_conflict_xy(self, xy):
        """Return ``True`` if *xy* represents an unmerged (conflict) state."""
        return xy in _CONFLICT_CODES

    def has_conflicts(self):
        """Return ``True`` if any file is in an unmerged (conflict) state."""
        return any(xy in _CONFLICT_CODES for xy in self._status.values())

    def get_conflicted_files(self):
        """Return a list of absolute paths for files in conflict."""
        return [
            path
            for path, xy in self._status.items()
            if xy in _CONFLICT_CODES
        ]

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

    def has_tracked_changes(self):
        """Return ``True`` if any tracked file has staged or unstaged changes.

        Untracked (``??``) and ignored (``!!``) entries are excluded so that
        the presence of new, uncommitted files does not trigger the warning.
        """
        return any(xy not in ("??", "!!") for xy in self._status.values())


# ---------------------------------------------------------------------------
# Branch name validation and creation
# ---------------------------------------------------------------------------

# Characters that are invalid in git branch names (per git-check-ref-format).
_INVALID_BRANCH_CHARS = set(" \t\n\x00\x7f\\~^:?*[")


def is_valid_branch_name(name):
    """Return ``True`` if *name* is a valid git branch name.

    Validates against ``git check-ref-format`` rules:

    * Must not be empty.
    * Must not contain spaces, control characters, or the characters
      ``~ ^ : ? * [ \\ \x7f``.
    * Must not start or end with a dot (``.``).
    * Must not contain consecutive dots (``..``).
    * Must not start with a dash (``-``).
    * Must not end with ``.lock``.
    * Must not be the single character ``@``.
    """
    if not name:
        return False
    if any(c in _INVALID_BRANCH_CHARS for c in name):
        return False
    if name.startswith(".") or name.endswith("."):
        return False
    if ".." in name:
        return False
    if name.startswith("-"):
        return False
    if name.endswith(".lock"):
        return False
    if name == "@":
        return False
    return True


def create_branch(repo_root, name):
    """Create and checkout a new branch *name* in *repo_root*.

    Runs ``git checkout -b <name>`` and returns ``(True, '')`` on success,
    or ``(False, error_message)`` on failure.
    """
    try:
        result = subprocess.run(
            ["git", "checkout", "-b", name],
            cwd=repo_root,
            capture_output=True,
            timeout=10,
            text=True,
        )
        if result.returncode == 0:
            return True, ""
        msg = (result.stderr or result.stdout).strip()
        return False, msg
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# subprocess-based git status
# ---------------------------------------------------------------------------


def git_stash(repo_root, message):
    """Create a new stash entry with *message* in *repo_root*.

    Runs ``git stash push -m <message>`` and returns ``True`` when the git
    command exits successfully (exit code 0), ``False`` on failure (e.g. git
    not found, invalid repository).  Note that git exits with code 0 even
    when there are no local changes to save.
    """
    try:
        result = subprocess.run(
            ["git", "stash", "push", "-m", message],
            cwd=repo_root,
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_git_status(repo_root):
    """Return a :class:`GitStatus` for *repo_root*, or ``None`` on failure.

    Uses ``git status --porcelain=v1 -z`` with NUL-terminated output to
    correctly handle filenames that contain spaces, quotes or non-ASCII
    characters without relying on Git's C-string quoting.

    This call runs synchronously in the calling thread.  For non-blocking
    use see :meth:`GitStatus.refresh`.
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
