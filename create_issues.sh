#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# create_issues.sh
# Usage: gh auth login   (first time only)
#        bash create_issues.sh [OWNER/REPO]
#
# Defaults to the repo detected by `gh repo view` if no argument is given.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="${1:-}"
REPO_FLAG=""
if [[ -n "$REPO" ]]; then
  REPO_FLAG="--repo $REPO"
fi

new_issue() {
  local title="$1"
  local label="$2"
  local body="$3"
  echo "Creating: $title"
  # shellcheck disable=SC2086
  gh issue create $REPO_FLAG \
    --title "$title" \
    --label "$label" \
    --body "$body"
}

# ---------------------------------------------------------------------------
# Ensure labels exist (idempotent)
# ---------------------------------------------------------------------------
ensure_label() {
  local name="$1" color="$2" desc="$3"
  # shellcheck disable=SC2086
  gh label create "$name" --color "$color" --description "$desc" $REPO_FLAG 2>/dev/null || true
}

ensure_label "enhancement"      "84b6eb" "New feature or request"
ensure_label "git-integration"  "0075ca" "Git-related features"
ensure_label "editor"           "e4e669" "Code-editor / gutter features"
ensure_label "toolpanel"        "d93f0b" "Pyzo tool-panel features"
ensure_label "infrastructure"   "cfd3d7" "Shared infrastructure / helpers"
ensure_label "branch-mgmt"      "1d76db" "Branch management features"
ensure_label "history-blame"    "5319e7" "Git history and blame"
ensure_label "conflict"         "b60205" "Merge conflict resolution"
ensure_label "remote-sync"      "0e8a16" "Remote / sync operations"
ensure_label "stash"            "f9d0c4" "Stash management"
ensure_label "pr-integration"   "c2e0c6" "Pull-request & issue integration"

# ===========================================================================
# FEATURE 1 — In-Editor Diff Gutter
# ===========================================================================

new_issue \
  "[DiffGutter] Create DiffGutterArea widget and extension skeleton" \
  "enhancement,editor,git-integration" \
'## Summary
Create `pyzo/codeeditor/extensions/diffgutter.py` following the same Extension mixin pattern used by `LineNumbers` in `codeeditor/extensions/appearance.py`.

## Acceptance criteria
- [ ] `__DiffGutterArea` subclasses `QtWidgets.QWidget`; placed to the **left** of the line-number margin
- [ ] Extension class `DiffGutter` is a mixin that can be added to the editor class list
- [ ] Gutter is 6 px wide; no content yet (just the placeholder widget)
- [ ] Extension gracefully no-ops when `git` is not installed or the file is not inside a repo

## References
- `pyzo/codeeditor/extensions/appearance.py` — `LineNumbers` pattern to follow
'

new_issue \
  "[DiffGutter] paintEvent: draw add/modify/delete stripes" \
  "enhancement,editor,git-integration" \
'## Summary
Implement `paintEvent()` in `__DiffGutterArea` to colour-code changed lines.

## Acceptance criteria
- [ ] **Green** filled rectangle for added lines
- [ ] **Amber** filled rectangle for modified lines
- [ ] **Red** small triangle or dash drawn *between* lines for deleted positions (no full-height bar because there is no line to paint on)
- [ ] Only the visible viewport range is iterated for performance
- [ ] Colours respect the current Qt palette / theme (use semi-transparent overlays so they degrade gracefully on light/dark themes)
'

new_issue \
  "[DiffGutter] Wire textChanged with 500 ms debounce to recompute diff" \
  "enhancement,editor,git-integration" \
'## Summary
Connect the editor `textChanged` signal to a diff-recompute slot gated by a 500 ms `QTimer` so the gutter updates as the user types without triggering a `git` subprocess on every keystroke.

## Acceptance criteria
- [ ] `QTimer` (single-shot, 500 ms) restarts on each `textChanged` event
- [ ] On timer fire: compare in-memory editor content against `git show HEAD:<relpath>` blob
- [ ] Parse unified diff `@@ -a,b +c,d @@` headers into a list of `Hunk` objects
- [ ] `Hunk` dataclass stores: `old_start`, `old_count`, `new_start`, `new_count`, `kind` (add/modify/delete)
- [ ] Gutter is invalidated and repaints after each recompute
- [ ] No subprocess is launched while the file path is unknown or the file is outside a git repo
'

new_issue \
  "[DiffGutter] HunkPopup: floating widget on gutter click" \
  "enhancement,editor,git-integration" \
'## Summary
When the user clicks in the diff-gutter, show a small floating `HunkPopup` widget that displays the raw diff text for that hunk and offers quick actions.

## Acceptance criteria
- [ ] Popup appears near the click position, auto-dismissed on click-outside or Escape
- [ ] Shows the unified diff text for the hunk (syntax-highlighted if feasible)
- [ ] Buttons: **Stage hunk**, **Revert hunk**, **Dismiss**
- [ ] Clicking outside the popup closes it without side-effects
'

new_issue \
  "[DiffGutter] Refresh gutter on file load and save events" \
  "enhancement,editor,git-integration" \
'## Summary
Beyond the live-typing debounce, also refresh the gutter when the file is loaded into the editor and when it is saved.

## Acceptance criteria
- [ ] On editor `fileLoaded` / `fileSaved` (or equivalent signal): immediately call `get_hunk_diff(filepath)` synchronously (file already on disk, latency is acceptable) or dispatch to a thread worker
- [ ] Gutter clears and repaints after each refresh
- [ ] Works correctly when the file is first opened (no previous diff state)
'

# ===========================================================================
# FEATURE 2 — githelper.py extensions
# ===========================================================================

new_issue \
  "[githelper] Add get_hunk_diff(filepath) → list[Hunk]" \
  "enhancement,infrastructure,git-integration" \
'## Summary
Extend `pyzo/tools/githelper.py` (or the equivalent helper module) with a `get_hunk_diff` function that returns structured hunk data for the diff gutter.

## Acceptance criteria
- [ ] `get_hunk_diff(filepath: str | Path) -> list[Hunk]` runs `git diff HEAD -- <file>` (and `git diff --cached -- <file>` for staged files) via `subprocess`
- [ ] Returns an empty list when git is not available or the file is not tracked
- [ ] Parses `@@ -a,b +c,d @@` headers into `Hunk` objects
- [ ] Handles binary files (returns empty list)
- [ ] Runs without blocking: designed to be called from a `QThread` worker

## Related
Hunk dataclass defined alongside or imported by `diffgutter.py`.
'

new_issue \
  "[githelper] Add get_file_blob(repo_root, relpath, ref='HEAD') → str" \
  "enhancement,infrastructure,git-integration" \
'## Summary
Add a helper that retrieves the committed content of a file so the diff gutter can compare it against the in-editor buffer.

## Acceptance criteria
- [ ] `get_file_blob(repo_root, relpath, ref="HEAD") -> str` runs `git show <ref>:<relpath>`
- [ ] Returns `None` (or raises a specific exception) when the ref or path does not exist
- [ ] Handles Windows path separators (convert to forward slashes for git)
- [ ] Output decoded as UTF-8 with `errors="replace"` to cope with mixed encodings
'

new_issue \
  "[githelper] Add GitStatus.refresh() background worker" \
  "enhancement,infrastructure,git-integration" \
'## Summary
Add an async `refresh()` method to `GitStatus` so the panel can re-fetch status without blocking the UI thread on large repos.

## Acceptance criteria
- [ ] `GitStatus.refresh()` spawns (or re-uses) a `QThread` worker that runs `git status --porcelain`
- [ ] Worker posts result back to the main thread via a Qt signal (`statusRefreshed(data)`)
- [ ] Calling `refresh()` while a previous refresh is in-flight cancels / ignores the stale result
- [ ] `GitStatus` emits `statusRefreshed` with a structured dict/list of staged + unstaged files
'

# ===========================================================================
# FEATURE 3 — gitops.py write operations
# ===========================================================================

new_issue \
  "[gitops] Create gitops.py with foundational write operations" \
  "enhancement,infrastructure,git-integration" \
'## Summary
Create `pyzo/tools/gitops.py` with all write-side git operations used by the panel and the diff gutter.  All functions call the system `git` binary via `subprocess`; no external libraries.

## Functions to implement
- [ ] `stage_file(repo_root, filepath)` — `git add <file>`
- [ ] `unstage_file(repo_root, filepath)` — `git restore --staged <file>`
- [ ] `revert_file(repo_root, filepath)` — `git checkout HEAD -- <file>` (caller must confirm first)
- [ ] `ignore_file(repo_root, filepath)` — appends relative path to `.gitignore`
- [ ] `commit(repo_root, message, author=None, amend=False)` — `git commit [-m msg] [--amend] [--author=...]`
- [ ] `get_branch(repo_root)` — `git rev-parse --abbrev-ref HEAD`

## Acceptance criteria
- [ ] Each function returns `(success: bool, output: str)`
- [ ] Each function raises `GitNotFoundError` when `git` binary is absent
- [ ] Paths are handled via `pathlib.Path`; arguments are passed as list (no shell=True)
- [ ] Unit-testable without a real repo (mock `subprocess.run`)
'

# ===========================================================================
# FEATURE 4 — PyzoGitPanel tool
# ===========================================================================

new_issue \
  "[GitPanel] Create pyzoGitPanel tool directory and __init__.py panel layout" \
  "enhancement,toolpanel,git-integration" \
'## Summary
Create `pyzo/tools/pyzoGitPanel/__init__.py` implementing the top-level `PyzoGitPanel(QWidget)` following the Pyzo tool-panel convention.

## Layout
```
PyzoGitPanel (QWidget)
├── Top bar:  branch label  +  Refresh button
├── QSplitter (horizontal)
│   ├── Left  (40 %): ChangesModel QTreeView  (staged + unstaged sections)
│   └── Right (60 %): DiffView  (syntax-highlighted unified diff)
└── Bottom: CommitWidget  (collapsible, visible when ≥ 1 file is staged)
```

## Acceptance criteria
- [ ] Panel inherits from the standard Pyzo tool base class so it docks correctly
- [ ] `QSplitter` persists its split ratio in Pyzo config
- [ ] `ChangesModel` is a `QStandardItemModel` with two top-level items: "Staged" and "Unstaged"
- [ ] Selecting a file in the tree loads its diff into `DiffView`
- [ ] `DiffView` renders unified diff with `+` lines green, `-` lines red (plain `QTextEdit` or `QPlainTextEdit` is fine for MVP)
- [ ] Auto-refresh: `QTimer` (5 s) calls `GitStatus.refresh()` when panel is visible and CWD is a git repo
- [ ] Timer is suspended when Pyzo loses focus (`QApplication.focusChanged`)
'

new_issue \
  "[GitPanel] commitwidget.py — commit form widget" \
  "enhancement,toolpanel,git-integration" \
'## Summary
Create `pyzo/tools/pyzoGitPanel/commitwidget.py` with a `CommitWidget(QWidget)` for composing and submitting commits.

## Acceptance criteria
- [ ] `QTextEdit` for commit message; placeholder: `"Summary\n\nDescription…"`
- [ ] Character counter label below the text edit; turns **orange/red** when first line exceeds 72 characters
- [ ] Branch indicator label (reads from `gitops.get_branch()`)
- [ ] **Commit** button — disabled until message is non-empty and ≥ 1 file is staged; calls `gitops.commit()`
- [ ] **Amend last commit** checkbox — appends `--amend` flag
- [ ] After successful commit: clear message field, emit `committed(short_sha)` signal, show transient status label "Committed as `abc1234`" for 3 s
- [ ] **Stage All** and **Unstage All** convenience buttons
'

new_issue \
  "[GitPanel] Register PyzoGitPanel in default tool list (core/main.py)" \
  "enhancement,toolpanel,git-integration" \
'## Summary
Add `pyzoGitPanel` to the list of tools shown to new users by default.

## Acceptance criteria
- [ ] `pyzo/core/main.py` (or equivalent default-tools config) includes `"pyzoGitPanel"` in the default tool list
- [ ] Existing users are not affected (the tool list in their config is not overwritten)
- [ ] Tool auto-discovery in `pyzo/tools/__init__.py` picks up the new directory without manual registration
'

# ===========================================================================
# ADDITIONAL FEATURES — Git History & Blame
# ===========================================================================

new_issue \
  "[History/Blame] Inline blame annotations in the editor gutter" \
  "enhancement,editor,history-blame" \
'## Summary
Add toggleable inline blame annotations to the editor gutter (similar to VS Code GitLens), showing author, short commit hash, and relative date for each line.

## Acceptance criteria
- [ ] Toggle on/off via menu item or keyboard shortcut
- [ ] Annotations rendered in a secondary gutter column (right of line numbers, left of code)
- [ ] Text truncated to fit; full info shown in a tooltip on hover
- [ ] Clicking a blame entry opens the commit details in the Git Panel
- [ ] Data sourced from `git blame --porcelain <file>`; loaded asynchronously
- [ ] Annotations stay in sync while the file is being edited (cleared/re-fetched on save)
'

new_issue \
  "[History/Blame] File history log tab in Git Panel" \
  "enhancement,toolpanel,history-blame" \
'## Summary
Add a "History" tab to the Git Panel showing `git log --follow` output for the currently open file.

## Acceptance criteria
- [ ] Tab added alongside the existing Changes view
- [ ] List shows: short hash, subject line, author, relative date
- [ ] Clicking a commit loads the diff for that commit in the DiffView
- [ ] Uses `git log --follow --pretty=format:...` so renames are tracked
- [ ] Loaded asynchronously; shows a spinner while fetching
'

new_issue \
  "[History/Blame] Time-travel diff: compare file against any historical commit" \
  "enhancement,toolpanel,history-blame" \
'## Summary
Allow the user to select any commit from the history list and view the file diff at that point in time in the existing DiffView.

## Acceptance criteria
- [ ] Double-clicking (or a "View diff" button on) a commit in the History tab renders `git show <sha> -- <file>` in DiffView
- [ ] Navigation arrows (prev/next commit) to step through history
- [ ] DiffView header shows commit hash, author, date, and subject
'

# ===========================================================================
# ADDITIONAL FEATURES — Branch Management
# ===========================================================================

new_issue \
  "[BranchMgmt] Branch switcher dropdown in Git Panel header" \
  "enhancement,toolpanel,branch-mgmt" \
'## Summary
Add a `QComboBox` to the Git Panel header populated by `git branch -a` so the user can checkout local or remote-tracking branches without leaving Pyzo.

## Acceptance criteria
- [ ] Combo box shows current branch as selected item
- [ ] Lists local branches, then remote-tracking branches (prefixed `remotes/`)
- [ ] Selecting a branch runs `git checkout <branch>`
- [ ] If there are uncommitted changes, show a confirmation dialog warning the user
- [ ] On success, refresh the Changes view and update the branch label
'

new_issue \
  "[BranchMgmt] Create and checkout a new branch" \
  "enhancement,toolpanel,branch-mgmt" \
'## Summary
Add an input field + "Create branch" button to the Git Panel to create and immediately checkout a new branch (`git checkout -b <name>`).

## Acceptance criteria
- [ ] Inline input field in the panel header (or a small dialog)
- [ ] Validates branch name (no spaces, no invalid git chars)
- [ ] Runs `git checkout -b <name>`
- [ ] Updates the branch label and combo box on success
- [ ] Shows error message in the panel status bar on failure
'

new_issue \
  "[BranchMgmt] Merge / rebase shortcut in Git Panel" \
  "enhancement,toolpanel,branch-mgmt" \
'## Summary
Provide a simple UI in the Git Panel to merge a selected branch into the current branch, with clear conflict indication on failure.

## Acceptance criteria
- [ ] "Merge branch…" button opens a small dialog with a branch selector
- [ ] Runs `git merge <branch>`; streams output to a log widget
- [ ] On conflict: highlights conflicted files in the Changes view with a ⚠ icon and suggests opening the Conflict Resolution view
- [ ] Optional: "Rebase onto…" variant running `git rebase <branch>`
'

# ===========================================================================
# ADDITIONAL FEATURES — Conflict Resolution
# ===========================================================================

new_issue \
  "[Conflict] Three-way merge view for conflict resolution" \
  "enhancement,editor,conflict" \
'## Summary
When a file contains git merge-conflict markers (`<<<<<<< HEAD`), open a three-column split view (Ours / Base / Theirs) with per-hunk Accept/Reject buttons.

## Acceptance criteria
- [ ] Detected automatically when the editor opens a file with conflict markers
- [ ] Three `QPlainTextEdit` panels shown side-by-side: **Ours** (HEAD), **Base** (common ancestor via `git show :1:<file>`), **Theirs** (MERGE_HEAD)
- [ ] Each conflicted hunk has **Accept Ours** / **Accept Theirs** / **Accept Both** buttons
- [ ] Resolved file is written back to disk and staged (`git add`) on confirmation
- [ ] Falls back gracefully to normal editor view if `git` is unavailable
'

# ===========================================================================
# ADDITIONAL FEATURES — Remote / Sync Operations
# ===========================================================================

new_issue \
  "[Remote] Push / Pull buttons with streamed output log" \
  "enhancement,toolpanel,remote-sync" \
'## Summary
Add **Push** and **Pull** buttons to the Git Panel that run `git push` / `git pull` and stream their output to a collapsible log widget.

## Acceptance criteria
- [ ] Buttons in the panel toolbar or bottom bar
- [ ] Output streamed line-by-line to a `QPlainTextEdit` log widget below the commit form
- [ ] Log widget is auto-scrolled and collapsible
- [ ] Errors (non-zero exit) shown in red; success shown in green
- [ ] Buttons disabled while an operation is in-flight
'

new_issue \
  "[Remote] Background fetch indicator with ahead/behind badge" \
  "enhancement,toolpanel,remote-sync" \
'## Summary
Periodically run `git fetch --quiet` in the background and display an ahead/behind badge (e.g. "↑3 ↓1") on the branch label.

## Acceptance criteria
- [ ] Configurable fetch interval (default 5 minutes); stored in Pyzo config
- [ ] Fetch runs in a `QThread` worker; never blocks the UI
- [ ] Badge hidden when counts are both 0
- [ ] Fetch suspended when Pyzo loses focus
- [ ] Tooltip on badge shows full "3 commits ahead, 1 commit behind origin/main"
'

new_issue \
  "[Remote] Clone dialog: URL + destination form" \
  "enhancement,toolpanel,remote-sync" \
'## Summary
Add a "Clone repository…" dialog accessible from the Git Panel (or File menu) that clones a remote URL into a chosen local folder and then opens it in the file browser.

## Acceptance criteria
- [ ] Dialog fields: Repository URL, Destination folder (folder picker), optional Branch
- [ ] Runs `git clone [--branch <branch>] <url> <dest>` with progress output streamed to a log
- [ ] After successful clone, opens the new folder in the Pyzo file browser
- [ ] Validates that the destination folder is empty or does not exist
'

# ===========================================================================
# ADDITIONAL FEATURES — Stash Management
# ===========================================================================

new_issue \
  "[Stash] Stash list tab in Git Panel" \
  "enhancement,toolpanel,stash" \
'## Summary
Add a "Stash" tab to the Git Panel listing all stashes from `git stash list`.

## Acceptance criteria
- [ ] Tab alongside Changes and History tabs
- [ ] List shows: stash ref (`stash@{n}`), message, author, relative date
- [ ] List refreshed automatically after each stash operation
- [ ] Empty-state message "No stashes" when list is empty
'

new_issue \
  "[Stash] Stash push/pop/drop/apply actions" \
  "enhancement,toolpanel,stash" \
'## Summary
Provide per-stash action buttons and a "Stash current changes" button in the Stash tab.

## Acceptance criteria
- [ ] **Apply** — `git stash apply stash@{n}` (keeps stash in list)
- [ ] **Pop** — `git stash pop stash@{n}` (removes from list after applying)
- [ ] **Drop** — `git stash drop stash@{n}` (confirms before dropping)
- [ ] **Stash changes** button with optional message prompt (see companion issue)
- [ ] All operations refresh the stash list and Changes view on completion
'

new_issue \
  "[Stash] Stash with custom message prompt" \
  "enhancement,toolpanel,stash" \
'## Summary
When the user clicks "Stash changes", prompt for a custom message instead of using the default auto-message.

## Acceptance criteria
- [ ] Small inline input field or `QInputDialog` asking for a stash message
- [ ] Runs `git stash push -m "<message>"`
- [ ] Cancelling the prompt aborts the stash without side-effects
- [ ] New stash appears at the top of the stash list
'

# ===========================================================================
# ADDITIONAL FEATURES — Pull Request & Issue Integration
# ===========================================================================

new_issue \
  "[PR] PR summary panel using GitHub REST API" \
  "enhancement,toolpanel,pr-integration" \
'## Summary
Add a "Pull Requests" tab in the Git Panel that lists open PRs for the repo using the GitHub REST API. Auth token stored in the system keyring.

## Acceptance criteria
- [ ] Tab shows: PR number, title, author avatar/name, CI status icon (✓/✗/⏳), "Open in browser" button
- [ ] Token retrieved from system keyring (`keyring` stdlib or `secretstorage`); falls back to a settings dialog if absent
- [ ] API calls made in a `QThread` worker; panel shows spinner while loading
- [ ] Works for both `github.com` and configurable GitHub Enterprise base URLs
- [ ] Gracefully degrades (tab hidden or shows message) for non-GitHub remotes
'

new_issue \
  "[PR] Issue linker with #-autocomplete in commit message" \
  "enhancement,toolpanel,pr-integration" \
'## Summary
In the `CommitWidget` message text edit, trigger autocomplete when the user types `#` to suggest open issue numbers and titles.

## Acceptance criteria
- [ ] Popup list appears after typing `#` with at least one digit
- [ ] List shows matching issue number + title fetched from the GitHub API
- [ ] Selecting an entry inserts `#<number>` into the message
- [ ] Autocomplete dismissed on Escape or when no matches remain
- [ ] API results cached for the session to avoid repeated fetches
'

echo ""
echo "All issues created successfully."
