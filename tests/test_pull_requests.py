"""
Unit tests for the pyzoPullRequests tool utility functions.

Tests focus on the pure-Python parsing helpers that do not require a running
Qt application or a real GitHub API connection.
"""

import os


# ---------------------------------------------------------------------------
# Helpers - import the module without Qt / pyzo bootstrapping
# ---------------------------------------------------------------------------

# We only need to test the pure-Python functions; import them directly to
# avoid pulling in the full pyzo/Qt stack.

_TOOL_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "pyzo",
    "tools",
    "pyzoPullRequests.py",
)


def _load_helpers():
    """Return the functions under test from pyzoPullRequests without Qt."""
    # Use a loader that only runs the module body up to the Qt imports, which
    # we handle via mocking.  The simplest approach is to exec just the
    # relevant function definitions after parsing them out of the source.
    with open(os.path.abspath(_TOOL_PATH), encoding="utf-8") as fh:
        source = fh.read()

    # Extract only the lines we need: everything up to the Qt import block.
    # We compile and exec the helper functions explicitly so we don't need Qt.
    ns = {"os": os, "json": __import__("json")}
    # Exec the helper functions (they depend only on stdlib)
    helpers_src = "\n".join(
        _extract_function_sources(
            source,
            [
                "_get_git_remote_url",
                "_parse_github_info",
                "_get_token_from_keyring",
                "_store_token_in_keyring",
            ],
        )
    )
    exec(compile(helpers_src, _TOOL_PATH, "exec"), ns)
    return ns


def _extract_function_sources(source, names):
    """Very small helper: return the source lines for the named top-level
    ``def`` blocks (stops at the next top-level ``def`` or ``class``)."""
    lines = source.splitlines()
    results = []
    for name in names:
        start = None
        for i, line in enumerate(lines):
            if line.startswith(f"def {name}(") or line.startswith(
                f"def {name} ("
            ):
                start = i
                break
        if start is None:
            continue
        block = []
        for line in lines[start:]:
            if block and line and not line[0].isspace() and not line.startswith("#"):
                break
            block.append(line)
        results.extend(block)
    return results


_helpers = _load_helpers()
_get_git_remote_url = _helpers["_get_git_remote_url"]
_parse_github_info = _helpers["_parse_github_info"]


# ---------------------------------------------------------------------------
# _parse_github_info
# ---------------------------------------------------------------------------


class TestParseGithubInfo:
    def test_https_github_com(self):
        result = _parse_github_info("https://github.com/owner/repo.git")
        assert result == ("owner", "repo", "https://api.github.com")

    def test_https_github_com_no_git_suffix(self):
        result = _parse_github_info("https://github.com/owner/repo")
        assert result == ("owner", "repo", "https://api.github.com")

    def test_ssh_github_com(self):
        result = _parse_github_info("git@github.com:owner/repo.git")
        assert result == ("owner", "repo", "https://api.github.com")

    def test_ssh_github_com_no_git_suffix(self):
        result = _parse_github_info("git@github.com:owner/repo")
        assert result == ("owner", "repo", "https://api.github.com")

    def test_https_ghe(self):
        result = _parse_github_info("https://ghe.corp.com/owner/repo.git")
        assert result is not None
        owner, repo, api_base = result
        assert owner == "owner"
        assert repo == "repo"
        assert api_base == "https://ghe.corp.com/api/v3"

    def test_ssh_ghe(self):
        result = _parse_github_info("git@ghe.corp.com:owner/repo.git")
        assert result is not None
        owner, repo, api_base = result
        assert owner == "owner"
        assert repo == "repo"
        assert api_base == "https://ghe.corp.com/api/v3"

    def test_gitlab_rejected(self):
        assert _parse_github_info("https://gitlab.com/owner/repo.git") is None

    def test_bitbucket_rejected(self):
        assert _parse_github_info("https://bitbucket.org/owner/repo.git") is None

    def test_none_input(self):
        assert _parse_github_info(None) is None

    def test_empty_string(self):
        assert _parse_github_info("") is None

    def test_non_url_string(self):
        assert _parse_github_info("not-a-url") is None

    def test_missing_repo(self):
        # URL with only one path segment - no repo
        assert _parse_github_info("https://github.com/owner") is None

    def test_trailing_slash(self):
        result = _parse_github_info("https://github.com/owner/repo/")
        assert result is not None
        assert result[0] == "owner"
        assert result[1] == "repo"

    def test_extra_path_segments_ignored(self):
        # e.g. https://github.com/owner/repo/tree/main
        result = _parse_github_info("https://github.com/owner/repo/tree/main")
        assert result is not None
        assert result[0] == "owner"
        assert result[1] == "repo"

    def test_hyphenated_owner_and_repo(self):
        result = _parse_github_info("git@github.com:my-org/my-repo.git")
        assert result == ("my-org", "my-repo", "https://api.github.com")


# ---------------------------------------------------------------------------
# _get_git_remote_url
# ---------------------------------------------------------------------------


class TestGetGitRemoteUrl:
    def _make_git_config(self, tmp_path, content):
        git_dir = os.path.join(tmp_path, ".git")
        os.makedirs(git_dir, exist_ok=True)
        config_path = os.path.join(git_dir, "config")
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return tmp_path

    def test_basic_origin(self, tmp_path):
        root = self._make_git_config(
            str(tmp_path),
            '[core]\n\trepositoryformatversion = 0\n'
            '[remote "origin"]\n'
            '\turl = https://github.com/owner/repo.git\n'
            '\tfetch = +refs/heads/*:refs/remotes/origin/*\n',
        )
        assert _get_git_remote_url(root) == "https://github.com/owner/repo.git"

    def test_no_origin(self, tmp_path):
        root = self._make_git_config(
            str(tmp_path),
            '[core]\n\trepositoryformatversion = 0\n',
        )
        assert _get_git_remote_url(root) is None

    def test_missing_config_file(self, tmp_path):
        # No .git directory at all
        assert _get_git_remote_url(str(tmp_path)) is None

    def test_ssh_url(self, tmp_path):
        root = self._make_git_config(
            str(tmp_path),
            '[remote "origin"]\n'
            '\turl = git@github.com:owner/repo.git\n',
        )
        assert _get_git_remote_url(root) == "git@github.com:owner/repo.git"

    def test_url_with_spaces_stripped(self, tmp_path):
        root = self._make_git_config(
            str(tmp_path),
            '[remote "origin"]\n'
            '\turl =  https://github.com/owner/repo.git  \n',
        )
        assert (
            _get_git_remote_url(root) == "https://github.com/owner/repo.git"
        )

    def test_multiple_remotes_picks_origin(self, tmp_path):
        root = self._make_git_config(
            str(tmp_path),
            '[remote "upstream"]\n'
            '\turl = https://github.com/upstream/repo.git\n'
            '[remote "origin"]\n'
            '\turl = https://github.com/fork/repo.git\n',
        )
        assert _get_git_remote_url(root) == "https://github.com/fork/repo.git"
