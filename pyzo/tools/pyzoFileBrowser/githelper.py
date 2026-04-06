"""
Git helper utilities for the pyzo file browser.

Provides lightweight, dependency-free git integration using only the
Python standard library.  subprocess is used only for `git status`.
"""

import os
import os.path as op
import re
import subprocess


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
# Hunk - diff hunk representation
# ---------------------------------------------------------------------------

# Regex for the unified-diff hunk header: @@ -old_start[,old_count] +new_start[,new_count] @@
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)", re.MULTILINE
)


class Hunk:
    """Represents a single unified-diff hunk for one file.

    Attributes
    ----------
    old_start : int
        First line number (1-based) in the *old* file.
    old_count : int
        Number of lines from the old file covered by this hunk.
    new_start : int
        First line number (1-based) in the *new* (working-tree) file.
    new_count : int
        Number of lines from the new file covered by this hunk.
    lines : list[str]
        All lines belonging to this hunk, including the ``@@`` header
        line, each ending with ``'\\n'``.
    """

    def __init__(self, old_start, old_count, new_start, new_count, lines):
        self.old_start = old_start
        self.old_count = old_count
        self.new_start = new_start
        self.new_count = new_count
        self.lines = lines

    @property
    def header(self):
        """The ``@@`` header line of this hunk (first element of ``lines``)."""
        return self.lines[0] if self.lines else ""

    @property
    def text(self):
        """The full hunk text as a single string."""
        return "".join(self.lines)

    def new_line_range(self):
        """Return ``(first, last)`` 1-based line numbers in the new file."""
        return self.new_start, self.new_start + max(self.new_count, 1) - 1


def get_diff_hunks(filepath):
    """Return a list of :class:`Hunk` objects for *filepath*, or ``[]``.

    Runs ``git diff HEAD -- <filepath>`` so that the diff reflects
    changes relative to the last commit (both staged and unstaged
    modifications are included via ``HEAD``).

    Parameters
    ----------
    filepath : str
        Absolute (or repo-relative) path to the file of interest.

    Returns
    -------
    list[Hunk]
        Parsed hunks in the order they appear in the diff.  Returns an
        empty list when the file has no changes or on any error.
    """
    repo_root = get_git_root(filepath)
    if repo_root is None:
        return []
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", filepath],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        diff_text = result.stdout.decode("utf-8", errors="surrogateescape")
        return _parse_hunks(diff_text)
    except Exception:
        return []


def _parse_hunks(diff_text):
    """Parse *diff_text* (unified diff) into a list of :class:`Hunk` objects."""
    hunks = []
    lines = diff_text.splitlines(keepends=True)
    i = 0
    # Skip the file header lines (--- / +++ / diff --git …)
    while i < len(lines) and not lines[i].startswith("@@"):
        i += 1

    while i < len(lines):
        line = lines[i]
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            i += 1
            continue
        old_start = int(m.group(1))
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_count = int(m.group(4)) if m.group(4) is not None else 1
        hunk_lines = [line]
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            hunk_lines.append(lines[i])
            i += 1
        hunks.append(Hunk(old_start, old_count, new_start, new_count, hunk_lines))

    return hunks
