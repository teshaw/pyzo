"""
Git helper utilities for the pyzo file browser.

Provides lightweight git integration using only the Python standard library
for filesystem queries and Qt for non-blocking status refresh.
subprocess is used only for `git status`.
"""

import os
import os.path as op
import subprocess

from pyzo.qt import QtCore


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
