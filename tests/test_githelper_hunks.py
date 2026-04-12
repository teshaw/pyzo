"""
Tests for the Hunk dataclass and get_hunk_diff helper in githelper.py.
"""

import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path

# Import githelper directly to avoid triggering pyzo/tools/__init__.py which
# requires a full Qt/pyzo runtime environment.
_GITHELPER_PATH = Path(__file__).parent.parent / "pyzo" / "tools" / "pyzoFileBrowser" / "githelper.py"
_spec = importlib.util.spec_from_file_location("githelper", _GITHELPER_PATH)
_githelper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_githelper)

Hunk = _githelper.Hunk
_parse_hunks = _githelper._parse_hunks
get_hunk_diff = _githelper.get_hunk_diff


# ---------------------------------------------------------------------------
# Hunk dataclass
# ---------------------------------------------------------------------------


def test_hunk_fields():
    h = Hunk(old_start=1, old_count=5, new_start=1, new_count=7)
    assert h.old_start == 1
    assert h.old_count == 5
    assert h.new_start == 1
    assert h.new_count == 7


def test_hunk_equality():
    h1 = Hunk(1, 5, 1, 7)
    h2 = Hunk(1, 5, 1, 7)
    assert h1 == h2


# ---------------------------------------------------------------------------
# _parse_hunks – unit-level parsing tests (no subprocess needed)
# ---------------------------------------------------------------------------

_SAMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
index abc1234..def5678 100644
--- a/foo.py
+++ b/foo.py
@@ -1,4 +1,6 @@
 line1
+added1
+added2
 line2
 line3
 line4
@@ -20,3 +22,2 @@
 lineA
-removed
 lineB
"""


def test_parse_hunks_basic():
    hunks = _parse_hunks(_SAMPLE_DIFF)
    assert len(hunks) == 2

    assert hunks[0] == Hunk(old_start=1, old_count=4, new_start=1, new_count=6)
    assert hunks[1] == Hunk(old_start=20, old_count=3, new_start=22, new_count=2)


def test_parse_hunks_empty_string():
    assert _parse_hunks("") == []


def test_parse_hunks_binary_file():
    binary_diff = (
        "diff --git a/image.png b/image.png\n"
        "Binary files a/image.png and b/image.png differ\n"
    )
    assert _parse_hunks(binary_diff) == []


def test_parse_hunks_omitted_count_defaults_to_one():
    # When count is omitted in @@ header it means 1 (e.g. new empty file)
    diff = "@@ -0,0 +1 @@\n+only line\n"
    hunks = _parse_hunks(diff)
    assert len(hunks) == 1
    assert hunks[0] == Hunk(old_start=0, old_count=0, new_start=1, new_count=1)


# ---------------------------------------------------------------------------
# get_hunk_diff – integration-level tests using a real temp git repo
# ---------------------------------------------------------------------------


def _init_repo(tmp_path):
    """Create a minimal git repo and return its Path."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_get_hunk_diff_no_git_repo():
    """A file outside any git repo returns an empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        filepath = os.path.join(tmp, "nottracked.py")
        with open(filepath, "w") as f:
            f.write("hello\n")
        result = get_hunk_diff(filepath)
        assert result == []


def test_get_hunk_diff_untracked_file():
    """An untracked file inside a git repo returns an empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        filepath = repo / "untracked.py"
        filepath.write_text("hello\n")
        result = get_hunk_diff(str(filepath))
        assert result == []


def test_get_hunk_diff_clean_tracked_file():
    """A tracked, unmodified file returns an empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        filepath = repo / "clean.py"
        filepath.write_text("line1\nline2\n")
        subprocess.run(
            ["git", "add", str(filepath)], cwd=str(repo), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        result = get_hunk_diff(str(filepath))
        assert result == []


def test_get_hunk_diff_modified_file():
    """A modified tracked file returns non-empty hunk list."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        filepath = repo / "modified.py"
        filepath.write_text("line1\nline2\nline3\n")
        subprocess.run(
            ["git", "add", str(filepath)], cwd=str(repo), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        # Modify the file
        filepath.write_text("line1\nline2\nline3\nline4\n")
        result = get_hunk_diff(str(filepath))
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(h, Hunk) for h in result)


def test_get_hunk_diff_staged_file():
    """A fully-staged file (no working-tree changes) returns hunks via --cached fallback."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_repo(repo)
        filepath = repo / "staged.py"
        filepath.write_text("line1\nline2\nline3\n")
        subprocess.run(
            ["git", "add", str(filepath)], cwd=str(repo), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        # Modify and stage only (no further working-tree changes)
        filepath.write_text("line1\nline2\nline3\nline4\n")
        subprocess.run(
            ["git", "add", str(filepath)], cwd=str(repo), check=True, capture_output=True
        )
        result = get_hunk_diff(str(filepath))
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(h, Hunk) for h in result)


def test_get_hunk_diff_accepts_path_object():
    """get_hunk_diff accepts a pathlib.Path as well as a str."""
    with tempfile.TemporaryDirectory() as tmp:
        result = get_hunk_diff(Path(tmp) / "nonexistent.py")
        assert result == []


# ---------------------------------------------------------------------------
# diffgutter re-exports
# ---------------------------------------------------------------------------


def test_diffgutter_exports():
    _DIFFGUTTER_PATH = (
        Path(__file__).parent.parent
        / "pyzo"
        / "tools"
        / "pyzoFileBrowser"
        / "diffgutter.py"
    )
    # Load diffgutter with githelper already in sys.modules under the name the
    # relative import expects.
    import sys

    sys.modules.setdefault("githelper", _githelper)
    # Use a package-level spec so relative imports resolve correctly.
    _pkg_init = (
        Path(__file__).parent.parent
        / "pyzo"
        / "tools"
        / "pyzoFileBrowser"
        / "__init__.py"
    )
    pkg_spec = importlib.util.spec_from_file_location(
        "pyzoFileBrowser", _pkg_init, submodule_search_locations=[]
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules["pyzoFileBrowser"] = pkg

    gh_spec = importlib.util.spec_from_file_location(
        "pyzoFileBrowser.githelper", _GITHELPER_PATH
    )
    gh_mod = importlib.util.module_from_spec(gh_spec)
    gh_mod.__package__ = "pyzoFileBrowser"
    sys.modules["pyzoFileBrowser.githelper"] = gh_mod
    gh_spec.loader.exec_module(gh_mod)

    dg_spec = importlib.util.spec_from_file_location(
        "pyzoFileBrowser.diffgutter", _DIFFGUTTER_PATH
    )
    dg_mod = importlib.util.module_from_spec(dg_spec)
    dg_mod.__package__ = "pyzoFileBrowser"
    sys.modules["pyzoFileBrowser.diffgutter"] = dg_mod
    dg_spec.loader.exec_module(dg_mod)

    assert dg_mod.Hunk is gh_mod.Hunk
    assert dg_mod.get_hunk_diff is gh_mod.get_hunk_diff
