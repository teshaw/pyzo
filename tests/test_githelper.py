"""Tests for pyzo.tools.pyzoFileBrowser.githelper."""

import importlib.util
import os
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GITHELPER_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "pyzo",
    "tools",
    "pyzoFileBrowser",
    "githelper.py",
)


def _import_githelper():
    """Import githelper directly from its file path (avoids Qt imports)."""
    spec = importlib.util.spec_from_file_location("githelper", _GITHELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# is_valid_branch_name
# ---------------------------------------------------------------------------


class TestIsValidBranchName:
    @pytest.fixture(autouse=True)
    def _gh(self):
        self.gh = _import_githelper()

    def _valid(self, name):
        assert self.gh.is_valid_branch_name(name), f"{name!r} should be valid"

    def _invalid(self, name):
        assert not self.gh.is_valid_branch_name(name), f"{name!r} should be invalid"

    # --- valid names ---

    def test_simple(self):
        self._valid("main")

    def test_hyphen_in_middle(self):
        self._valid("feature-123")

    def test_slash_separator(self):
        self._valid("feature/my-feature")

    def test_digits(self):
        self._valid("release-1.0")

    def test_underscore(self):
        self._valid("my_branch")

    # --- invalid names ---

    def test_empty(self):
        self._invalid("")

    def test_space(self):
        self._invalid("my branch")

    def test_tab(self):
        self._invalid("my\tbranch")

    def test_tilde(self):
        self._invalid("bad~name")

    def test_caret(self):
        self._invalid("bad^name")

    def test_colon(self):
        self._invalid("bad:name")

    def test_question_mark(self):
        self._invalid("bad?name")

    def test_asterisk(self):
        self._invalid("bad*name")

    def test_open_bracket(self):
        self._invalid("bad[name")

    def test_backslash(self):
        self._invalid("bad\\name")

    def test_leading_dot(self):
        self._invalid(".hidden")

    def test_trailing_dot(self):
        self._invalid("name.")

    def test_double_dot(self):
        self._invalid("bad..name")

    def test_leading_dash(self):
        self._invalid("-bad")

    def test_dot_lock_suffix(self):
        self._invalid("branch.lock")

    def test_at_alone(self):
        self._invalid("@")


# ---------------------------------------------------------------------------
# create_branch (integration test – requires git)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    subprocess.call(
        ["git", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    != 0,
    reason="git not available",
)
class TestCreateBranch:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.gh = _import_githelper()
        # Initialise a minimal git repo
        self.repo = str(tmp_path)
        subprocess.run(["git", "init", self.repo], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        # Create an initial commit so HEAD exists
        readme = os.path.join(self.repo, "README.md")
        with open(readme, "w") as fh:
            fh.write("init\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def test_create_branch_success(self):
        ok, msg = self.gh.create_branch(self.repo, "feature-x")
        assert ok is True
        assert msg == ""
        # Verify the branch was actually checked out
        branch = self.gh.get_git_branch(self.repo)
        assert branch == "feature-x"

    def test_create_branch_duplicate_fails(self):
        self.gh.create_branch(self.repo, "feature-x")
        # Try to create the same branch again (from within that branch)
        ok, msg = self.gh.create_branch(self.repo, "feature-x")
        assert ok is False
        assert msg  # error message should be non-empty

    def test_create_branch_invalid_name_not_called(self):
        """is_valid_branch_name must reject names before we call git."""
        assert not self.gh.is_valid_branch_name("bad name")



# ---------------------------------------------------------------------------
# is_valid_branch_name
# ---------------------------------------------------------------------------


class TestIsValidBranchName:
    @pytest.fixture(autouse=True)
    def _gh(self):
        self.gh = _import_githelper()

    def _valid(self, name):
        assert self.gh.is_valid_branch_name(name), f"{name!r} should be valid"

    def _invalid(self, name):
        assert not self.gh.is_valid_branch_name(name), f"{name!r} should be invalid"

    # --- valid names ---

    def test_simple(self):
        self._valid("main")

    def test_hyphen_in_middle(self):
        self._valid("feature-123")

    def test_slash_separator(self):
        self._valid("feature/my-feature")

    def test_digits(self):
        self._valid("release-1.0")

    def test_underscore(self):
        self._valid("my_branch")

    # --- invalid names ---

    def test_empty(self):
        self._invalid("")

    def test_space(self):
        self._invalid("my branch")

    def test_tab(self):
        self._invalid("my\tbranch")

    def test_tilde(self):
        self._invalid("bad~name")

    def test_caret(self):
        self._invalid("bad^name")

    def test_colon(self):
        self._invalid("bad:name")

    def test_question_mark(self):
        self._invalid("bad?name")

    def test_asterisk(self):
        self._invalid("bad*name")

    def test_open_bracket(self):
        self._invalid("bad[name")

    def test_backslash(self):
        self._invalid("bad\\name")

    def test_leading_dot(self):
        self._invalid(".hidden")

    def test_trailing_dot(self):
        self._invalid("name.")

    def test_double_dot(self):
        self._invalid("bad..name")

    def test_leading_dash(self):
        self._invalid("-bad")

    def test_dot_lock_suffix(self):
        self._invalid("branch.lock")

    def test_at_alone(self):
        self._invalid("@")


# ---------------------------------------------------------------------------
# create_branch (integration test – requires git)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    subprocess.call(
        ["git", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    != 0,
    reason="git not available",
)
class TestCreateBranch:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.gh = _import_githelper()
        # Initialise a minimal git repo
        self.repo = str(tmp_path)
        subprocess.run(["git", "init", self.repo], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        # Create an initial commit so HEAD exists
        readme = os.path.join(self.repo, "README.md")
        with open(readme, "w") as fh:
            fh.write("init\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def test_create_branch_success(self):
        ok, msg = self.gh.create_branch(self.repo, "feature-x")
        assert ok is True
        assert msg == ""
        # Verify the branch was actually checked out
        branch = self.gh.get_git_branch(self.repo)
        assert branch == "feature-x"

    def test_create_branch_duplicate_fails(self):
        self.gh.create_branch(self.repo, "feature-x")
        # Try to create the same branch again (from within that branch)
        ok, msg = self.gh.create_branch(self.repo, "feature-x")
        assert ok is False
        assert msg  # error message should be non-empty

    def test_create_branch_invalid_name_not_called(self):
        """is_valid_branch_name must reject names before we call git."""
        assert not self.gh.is_valid_branch_name("bad name")
