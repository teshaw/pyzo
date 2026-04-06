"""
Git helper utilities for the pyzo file browser.

Provides lightweight, dependency-free git integration using only the
Python standard library.  subprocess is used only for `git status` and
background fetch operations.
"""

import os
import os.path as op
import subprocess
import threading
import time


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
# subprocess-based git fetch and ahead/behind
# ---------------------------------------------------------------------------


def git_fetch(repo_root):
    """Run ``git fetch --quiet`` for *repo_root*.

    Returns ``True`` on success, ``False`` on failure.  Times out after
    30 seconds so it never blocks indefinitely.
    """
    try:
        result = subprocess.run(
            ["git", "fetch", "--quiet"],
            cwd=repo_root,
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_ahead_behind(repo_root):
    """Return ``(ahead, behind)`` counts vs the upstream branch.

    Runs ``git rev-list --count @{u}..HEAD`` (ahead) and
    ``git rev-list --count HEAD..@{u}`` (behind).
    Returns ``(0, 0)`` when there is no upstream or on any error.
    """
    try:
        ahead_result = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        behind_result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..@{u}"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        if ahead_result.returncode != 0 or behind_result.returncode != 0:
            return (0, 0)
        ahead = int(ahead_result.stdout.strip())
        behind = int(behind_result.stdout.strip())
        return (ahead, behind)
    except Exception:
        return (0, 0)


def get_upstream_branch(repo_root):
    """Return the upstream tracking branch name for HEAD, or ``None``.

    Uses ``git rev-parse --abbrev-ref --symbolic-full-name @{u}``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="surrogateescape").strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Background fetch worker
# ---------------------------------------------------------------------------


class GitFetchWorker(threading.Thread):
    """Background thread that periodically fetches from the remote and
    reports ahead/behind commit counts to the UI via a callback.

    Parameters
    ----------
    callback : callable
        Called with ``(ahead: int, behind: int, upstream: str | None)``
        from the worker thread.  The caller is responsible for
        marshalling the result to the main thread (e.g. via a Qt signal).
    interval : float
        Seconds between fetch runs (default 300 = 5 minutes).
    """

    def __init__(self, callback, interval=300):
        super().__init__(name="GitFetchWorker", daemon=True)
        self._callback = callback
        self._interval = interval
        self._repo_root = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially
        # Trigger an immediate fetch when the repo root changes
        self._trigger_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API (safe to call from any thread)
    # ------------------------------------------------------------------

    def set_repo(self, repo_root):
        """Set the repository root and trigger an immediate fetch."""
        with self._lock:
            changed = repo_root != self._repo_root
            self._repo_root = repo_root
        if changed:
            self._trigger_event.set()

    def pause(self):
        """Pause periodic fetching (e.g. when the application loses focus)."""
        self._pause_event.clear()

    def resume(self):
        """Resume periodic fetching and trigger an immediate run."""
        self._pause_event.set()
        self._trigger_event.set()

    def stop(self, timeout=2.0):
        """Stop the worker thread."""
        self._stop_event.set()
        self._pause_event.set()   # unblock any wait
        self._trigger_event.set()  # unblock any wait
        self.join(timeout)

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self):
        while not self._stop_event.is_set():
            # Wait until not paused
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            with self._lock:
                repo = self._repo_root

            if repo:
                self._trigger_event.clear()
                git_fetch(repo)
                if not self._stop_event.is_set():
                    ahead, behind = get_ahead_behind(repo)
                    upstream = get_upstream_branch(repo)
                    try:
                        self._callback(ahead, behind, upstream)
                    except Exception:
                        pass

            # Sleep for the configured interval, but wake early if
            # triggered (repo changed) or stopped.
            self._trigger_event.wait(timeout=self._interval)
            self._trigger_event.clear()
