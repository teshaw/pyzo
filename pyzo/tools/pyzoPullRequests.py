"""
This module provides the Pull Requests tool for pyzo.

Shows open pull requests for the current GitHub repository, fetching data
from the GitHub REST API.  Authentication tokens are stored in the system
keyring (via the optional ``keyring`` package) with a per-user config
fallback.
"""

import os
import json
import webbrowser
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import pyzo
from pyzo.qt import QtCore, QtGui, QtWidgets
from pyzo.util import zon as ssdf

tool_name = "Pull Requests"
tool_summary = "Shows open pull requests from GitHub."

_USER_AGENT = "pyzo-pull-requests"


# ---------------------------------------------------------------------------
# Keyring helpers (optional dependency)
# ---------------------------------------------------------------------------

_KEYRING_SERVICE = "pyzo-github"
_KEYRING_USERNAME = "token"


def _get_token_from_keyring():
    """Return the stored GitHub token from the system keyring, or ``''``."""
    try:
        import keyring  # optional

        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME) or ""
    except Exception:
        return ""


def _store_token_in_keyring(token):
    """Store *token* in the system keyring.  Returns ``True`` on success."""
    try:
        import keyring  # optional

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, token)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Git / GitHub remote helpers
# ---------------------------------------------------------------------------


def _get_git_remote_url(repo_root):
    """Return the remote URL for *origin* from ``.git/config``, or ``None``."""
    config_path = os.path.join(repo_root, ".git", "config")
    try:
        with open(config_path, encoding="utf-8") as fh:
            in_origin = False
            for line in fh:
                line = line.strip()
                if line == '[remote "origin"]':
                    in_origin = True
                elif line.startswith("["):
                    in_origin = False
                elif in_origin and line.startswith("url"):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def _parse_github_info(remote_url):
    """Parse owner, repo and API base URL from a GitHub remote URL.

    Returns ``(owner, repo, api_base)`` or ``None`` when *remote_url* is not
    recognisable as a GitHub (or GitHub Enterprise) URL.

    Supported formats:

    * SSH:   ``git@github.com:owner/repo.git``
    * HTTPS: ``https://github.com/owner/repo.git``
    * GHE:   ``https://ghe.corp.com/owner/repo.git``
              ``git@ghe.corp.com:owner/repo.git``

    Non-GitHub hosts (e.g. ``gitlab.com``, ``bitbucket.org``) return ``None``.
    """
    if not remote_url:
        return None

    url = remote_url.strip()
    owner = repo = host = None

    if url.startswith("git@"):
        # SSH: git@<host>:<owner>/<repo>[.git]
        try:
            after_at = url[4:]
            host, path = after_at.split(":", 1)
            path = path.rstrip("/")
            if path.endswith(".git"):
                path = path[:-4]
            parts = path.split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
        except (ValueError, IndexError):
            return None
    elif "://" in url:
        # HTTPS
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = parsed.hostname or ""
            path = parsed.path.strip("/")
            if path.endswith(".git"):
                path = path[:-4]
            parts = path.split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
        except Exception:
            return None
    else:
        return None

    if not owner or not repo or not host:
        return None

    # Reject well-known non-GitHub hosts
    if host in ("gitlab.com", "bitbucket.org"):
        return None

    api_base = (
        "https://api.github.com"
        if host == "github.com"
        else f"https://{host}/api/v3"
    )
    return owner, repo, api_base


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class GitHubApiWorker(QtCore.QThread):
    """Fetches open pull requests and their CI statuses in a background thread.

    Emits :attr:`prsLoaded` with a list of dicts on success, or
    :attr:`errorOccurred` with a message string on failure.
    """

    prsLoaded = QtCore.Signal(list)
    errorOccurred = QtCore.Signal(str)

    def __init__(self, owner, repo, api_base, token, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._repo = repo
        self._api_base = api_base.rstrip("/")
        self._token = token

    # ------------------------------------------------------------------

    def _request(self, url):
        """Make an authenticated GET request and return the parsed JSON body."""
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _ci_status(self, sha):
        """Return a CI status string for *sha*: ``'success'``, ``'failure'``,
        ``'pending'``, or ``'unknown'``."""
        # Try the newer Check Runs API first
        try:
            url = (
                f"{self._api_base}/repos/{self._owner}/{self._repo}"
                f"/commits/{sha}/check-runs"
            )
            data = self._request(url)
            runs = data.get("check_runs", [])
            if runs:
                conclusions = [r.get("conclusion") for r in runs]
                if any(c == "failure" for c in conclusions):
                    return "failure"
                if any(c is None for c in conclusions):
                    return "pending"
                if all(c == "success" for c in conclusions):
                    return "success"
                return "unknown"
        except Exception:
            pass

        # Fall back to the legacy Commit Status API
        try:
            url = (
                f"{self._api_base}/repos/{self._owner}/{self._repo}"
                f"/commits/{sha}/status"
            )
            return self._request(url).get("state", "unknown")
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------

    def run(self):
        try:
            url = (
                f"{self._api_base}/repos/{self._owner}/{self._repo}"
                f"/pulls?state=open&per_page=50"
            )
            prs = self._request(url)
            result = []
            for pr in prs:
                sha = pr.get("head", {}).get("sha", "")
                ci = self._ci_status(sha) if sha else "unknown"
                result.append(
                    {
                        "number": pr.get("number"),
                        "title": pr.get("title", ""),
                        "author": pr.get("user", {}).get("login", ""),
                        "author_avatar": pr.get("user", {}).get("avatar_url", ""),
                        "html_url": pr.get("html_url", ""),
                        "ci_status": ci,
                    }
                )
            self.prsLoaded.emit(result)
        except HTTPError as e:
            self.errorOccurred.emit(f"HTTP {e.code}: {e.reason}")
        except URLError as e:
            self.errorOccurred.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.errorOccurred.emit(str(e))


class AvatarLoader(QtCore.QThread):
    """Downloads a single avatar image in a background thread.

    Emits :attr:`loaded` with ``(pr_number, image_bytes)`` on success.
    """

    loaded = QtCore.Signal(int, bytes)

    def __init__(self, pr_number, avatar_url, parent=None):
        super().__init__(parent)
        self._pr_number = pr_number
        self._avatar_url = avatar_url

    def run(self):
        try:
            req = Request(
                self._avatar_url,
                headers={"User-Agent": _USER_AGENT},
            )
            with urlopen(req, timeout=5) as resp:
                data = resp.read()
            self.loaded.emit(self._pr_number, data)
        except Exception:
            pass  # Avatar is cosmetic; silently ignore failures


# ---------------------------------------------------------------------------
# Token dialog
# ---------------------------------------------------------------------------


class TokenDialog(QtWidgets.QDialog):
    """Dialog for entering / editing the GitHub personal access token."""

    def __init__(self, parent, current_token="", api_base="https://api.github.com"):
        super().__init__(parent)
        self.setWindowTitle("GitHub Token")
        self.setMinimumWidth(440)

        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            "Enter a GitHub <b>personal access token</b> with the "
            "<code>repo</code> scope to view pull requests and CI status.<br>"
            'Create one at <a href="https://github.com/settings/tokens">'
            "github.com/settings/tokens</a>."
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        layout.addWidget(intro)
        layout.addSpacing(8)

        form = QtWidgets.QFormLayout()
        self._tokenEdit = QtWidgets.QLineEdit(current_token)
        self._tokenEdit.setPlaceholderText("ghp_xxxxxxxxxxxx")
        self._tokenEdit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addRow("Token:", self._tokenEdit)

        self._apiBaseEdit = QtWidgets.QLineEdit(api_base)
        self._apiBaseEdit.setToolTip(
            "Leave as https://api.github.com for github.com\n"
            "For GitHub Enterprise use https://<host>/api/v3"
        )
        form.addRow("API base URL:", self._apiBaseEdit)
        layout.addLayout(form)

        showCheck = QtWidgets.QCheckBox("Show token")
        showCheck.toggled.connect(self._on_show_toggled)
        layout.addWidget(showCheck)
        layout.addSpacing(4)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_show_toggled(self, show):
        mode = (
            QtWidgets.QLineEdit.EchoMode.Normal
            if show
            else QtWidgets.QLineEdit.EchoMode.Password
        )
        self._tokenEdit.setEchoMode(mode)

    def token(self):
        """Return the token text entered by the user."""
        return self._tokenEdit.text().strip()

    def apiBase(self):
        """Return the API base URL entered by the user."""
        return self._apiBaseEdit.text().strip().rstrip("/")


# ---------------------------------------------------------------------------
# PR item widget
# ---------------------------------------------------------------------------

_CI_ICONS = {
    "success": "✓",
    "failure": "✗",
    "pending": "⏳",
    "unknown": "?",
}

_CI_COLORS = {
    "success": "green",
    "failure": "red",
    "pending": "darkorange",
    "unknown": "gray",
}


class _ElidingLabel(QtWidgets.QLabel):
    """A QLabel that elides text with '…' when the widget is too narrow.

    Overrides ``sizeHint`` / ``minimumSizeHint`` so the label can shrink
    within a layout without forcing its parent to expand.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text):
        self._full_text = text
        self._apply_elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def sizeHint(self):
        sh = super().sizeHint()
        return QtCore.QSize(0, sh.height())

    def minimumSizeHint(self):
        msh = super().minimumSizeHint()
        return QtCore.QSize(0, msh.height())

    def _apply_elide(self):
        metrics = self.fontMetrics()
        available = max(self.width(), 1)
        elided = metrics.elidedText(
            self._full_text,
            QtCore.Qt.TextElideMode.ElideRight,
            available,
        )
        super().setText(elided)


class PrItemWidget(QtWidgets.QWidget):
    """A single row in the pull request list.

    Displays: avatar, CI status icon, PR number, title, author, and an
    "Open in browser" button.
    """

    def __init__(self, pr_data, parent=None):
        super().__init__(parent)
        self._url = pr_data.get("html_url", "")

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(6)

        # --- avatar placeholder (filled later by AvatarLoader) ---
        self._avatarLabel = QtWidgets.QLabel()
        self._avatarLabel.setFixedSize(24, 24)
        self._avatarLabel.setScaledContents(True)
        self._avatarLabel.setStyleSheet(
            "background: palette(mid); border-radius: 12px;"
        )
        outer.addWidget(self._avatarLabel)

        # --- CI status ---
        ci = pr_data.get("ci_status", "unknown")
        ciLabel = QtWidgets.QLabel(_CI_ICONS.get(ci, "?"))
        ciLabel.setToolTip(f"CI status: {ci}")
        ciLabel.setStyleSheet(f"color: {_CI_COLORS.get(ci, 'gray')};")
        ciLabel.setFixedWidth(16)
        outer.addWidget(ciLabel)

        # --- PR number ---
        numLabel = QtWidgets.QLabel(f"<b>#{pr_data.get('number', '')}</b>")
        numLabel.setFixedWidth(48)
        outer.addWidget(numLabel)

        # --- title + author ---
        infoWidget = QtWidgets.QWidget()
        infoLayout = QtWidgets.QVBoxLayout(infoWidget)
        infoLayout.setContentsMargins(0, 0, 0, 0)
        infoLayout.setSpacing(1)

        titleLabel = _ElidingLabel(pr_data.get("title", ""))
        infoLayout.addWidget(titleLabel)

        authorLabel = QtWidgets.QLabel(
            f"<small>{pr_data.get('author', '')}</small>"
        )
        authorLabel.setStyleSheet("color: palette(shadow);")
        infoLayout.addWidget(authorLabel)

        outer.addWidget(infoWidget, 1)

        # --- open in browser button ---
        openBtn = QtWidgets.QPushButton("Open ↗")
        openBtn.setFixedWidth(64)
        openBtn.setToolTip("Open pull request in browser")
        openBtn.clicked.connect(self._open_in_browser)
        outer.addWidget(openBtn)

        self.setStyleSheet(
            "PrItemWidget { border-bottom: 1px solid palette(mid); }"
        )

    @property
    def avatarLabel(self):
        """The QLabel used to display the author avatar."""
        return self._avatarLabel

    def _open_in_browser(self):
        if self._url:
            webbrowser.open(self._url)


# ---------------------------------------------------------------------------
# Main panel widget
# ---------------------------------------------------------------------------


class PyzoPullRequests(QtWidgets.QWidget):
    """Pull Requests panel – shows open PRs for the current GitHub repository.

    * Detects the GitHub remote from the working directory's git config.
    * Fetches PR data (including CI status) via a background QThread worker.
    * Loads author avatars asynchronously after the PR list is displayed.
    * Stores the GitHub token in the system keyring (falls back to pyzo config).
    * Gracefully degrades when no GitHub remote is detected.
    """

    def __init__(self, parent):
        super().__init__(parent)

        # Per-tool persistent config
        tool_id = "pyzopullrequests"
        if not hasattr(pyzo.config.tools, tool_id):
            pyzo.config.tools[tool_id] = ssdf.new()
        self._config = pyzo.config.tools[tool_id]
        if not hasattr(self._config, "token"):
            self._config.token = ""
        if not hasattr(self._config, "api_base_override"):
            self._config.api_base_override = ""

        self._owner = None
        self._repo = None
        self._api_base = "https://api.github.com"
        self._worker = None
        self._avatar_loaders = []  # keep references so GC doesn't kill threads
        self._pr_widgets = {}  # pr_number -> PrItemWidget

        self._setup_ui()
        self._detect_repo()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        margin = pyzo.config.view.widgetMargin
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(4)

        # toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(4)

        self._repoLabel = QtWidgets.QLabel("No GitHub repo detected")
        toolbar.addWidget(self._repoLabel, 1)

        self._refreshBtn = QtWidgets.QPushButton("↺")
        self._refreshBtn.setToolTip("Refresh pull requests")
        self._refreshBtn.setAccessibleName("Refresh pull requests")
        self._refreshBtn.setFixedWidth(28)
        self._refreshBtn.clicked.connect(self._refresh)
        toolbar.addWidget(self._refreshBtn)

        tokenBtn = QtWidgets.QPushButton("🔑")
        tokenBtn.setToolTip("Configure GitHub token")
        tokenBtn.setAccessibleName("Configure GitHub token")
        tokenBtn.setFixedWidth(28)
        tokenBtn.clicked.connect(self._configure_token)
        toolbar.addWidget(tokenBtn)

        layout.addLayout(toolbar)

        # status label (shows spinner text / error / PR count)
        self._statusLabel = QtWidgets.QLabel("")
        layout.addWidget(self._statusLabel)

        # scrollable PR list
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self._prContainer = QtWidgets.QWidget()
        self._prLayout = QtWidgets.QVBoxLayout(self._prContainer)
        self._prLayout.setContentsMargins(0, 0, 0, 0)
        self._prLayout.setSpacing(0)
        self._prLayout.addStretch()

        scroll.setWidget(self._prContainer)
        layout.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    # Repository detection
    # ------------------------------------------------------------------

    def _detect_repo(self):
        """Auto-detect the GitHub repository from the working directory."""
        repo_root = self._find_repo_root()
        if repo_root is None:
            self._statusLabel.setText(
                "Open a directory inside a GitHub repository to see pull requests."
            )
            return

        remote_url = _get_git_remote_url(repo_root)
        info = _parse_github_info(remote_url)
        if info is None:
            self._statusLabel.setText(
                "Remote origin is not a GitHub repository."
            )
            return

        owner, repo, api_base = info
        self._owner = owner
        self._repo = repo
        self._api_base = self._config.api_base_override or api_base
        self._repoLabel.setText(f"{owner}/{repo}")
        self._refresh()

    def _find_repo_root(self):
        """Return the git root for ``os.getcwd()``, or ``None``."""
        try:
            from pyzo.tools.pyzoFileBrowser.githelper import get_git_root

            return get_git_root(os.getcwd())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _get_token(self):
        """Return the GitHub token: keyring first, then config fallback."""
        return _get_token_from_keyring() or self._config.token or ""

    def _configure_token(self):
        """Open the token configuration dialog."""
        dialog = TokenDialog(
            self,
            current_token=self._get_token(),
            api_base=self._config.api_base_override or self._api_base,
        )
        if dialog.exec():
            token = dialog.token()
            api_base = dialog.apiBase()
            # Persist token
            if not _store_token_in_keyring(token):
                self._config.token = token  # fallback: store in config
            # Persist API base override (empty = use auto-detected value)
            self._config.api_base_override = (
                "" if api_base == "https://api.github.com" else api_base
            )
            if self._owner:
                self._api_base = api_base
                self._refresh()

    # ------------------------------------------------------------------
    # Loading pull requests
    # ------------------------------------------------------------------

    def _refresh(self):
        """Start loading pull requests from the GitHub API."""
        if not self._owner or not self._repo:
            return
        if self._worker and self._worker.isRunning():
            return  # already loading

        self._clear_prs()
        self._statusLabel.setText("⏳ Loading pull requests…")
        self._refreshBtn.setEnabled(False)

        self._worker = GitHubApiWorker(
            self._owner,
            self._repo,
            self._api_base,
            self._get_token(),
            parent=self,
        )
        self._worker.prsLoaded.connect(self._on_prs_loaded)
        self._worker.errorOccurred.connect(self._on_error)
        self._worker.finished.connect(
            lambda: self._refreshBtn.setEnabled(True)
        )
        self._worker.start()

    def _clear_prs(self):
        """Remove all PR item widgets from the layout."""
        self._pr_widgets.clear()
        self._avatar_loaders.clear()
        # Remove every item except the trailing stretch (last item)
        while self._prLayout.count() > 1:
            item = self._prLayout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _on_prs_loaded(self, prs):
        """Populate the panel with the fetched PR data."""
        self._clear_prs()
        if not prs:
            self._statusLabel.setText("No open pull requests.")
            return

        count = len(prs)
        self._statusLabel.setText(
            f"{count} open pull request{'s' if count != 1 else ''}"
        )

        for pr_data in prs:
            widget = PrItemWidget(pr_data, self._prContainer)
            # Insert before the trailing stretch (which is always the last item)
            self._prLayout.insertWidget(self._prLayout.count() - 1, widget)
            self._pr_widgets[pr_data["number"]] = widget

        self._load_avatars(prs)

    def _on_error(self, msg):
        """Display an appropriate error message."""
        if "401" in msg or "403" in msg:
            self._statusLabel.setText(
                "⚠ Authentication failed – click 🔑 to configure your GitHub token."
            )
        elif "404" in msg:
            self._statusLabel.setText(
                "⚠ Repository not found – check owner/repo name."
            )
        else:
            self._statusLabel.setText(f"⚠ {msg}")

    # ------------------------------------------------------------------
    # Avatar loading
    # ------------------------------------------------------------------

    def _load_avatars(self, prs):
        """Spawn an :class:`AvatarLoader` for each PR that has an avatar URL."""
        for pr_data in prs:
            url = pr_data.get("author_avatar", "")
            if url:
                loader = AvatarLoader(pr_data["number"], url, parent=self)
                loader.loaded.connect(self._on_avatar_loaded)
                self._avatar_loaders.append(loader)
                loader.start()

    def _on_avatar_loaded(self, pr_number, data):
        """Apply a downloaded avatar image to the corresponding PR widget."""
        widget = self._pr_widgets.get(pr_number)
        if widget is None:
            return
        pixmap = QtGui.QPixmap()
        if pixmap.loadFromData(data):
            widget.avatarLabel.setPixmap(pixmap)
            widget.avatarLabel.setStyleSheet("")  # remove placeholder style
