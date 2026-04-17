import re
import sys
import os.path as op

import pyzo
from pyzo import translate
from pyzo.util import zon as ssdf

from . import QtCore, QtGui, QtWidgets
from . import proxies
from . import githelper
from .tree import Tree
from .utils import cleanpath, isdir


class StashWidget(QtWidgets.QWidget):
    """Panel shown below the git branch label that lists stash entries.

    Each entry has **Apply**, **Pop**, and **Drop** buttons.  A **Stash
    changes** button at the top lets the user push new stash entries with an
    optional message.  The widget is hidden automatically when the current
    directory is not inside a git repository.
    """

    #: Emitted after any stash operation so the file-browser tree can refresh
    #: its git-status colours (the "Changes view").
    refreshRequested = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self._repo_root = None

        # --- "Stash changes" button in the header row ---
        self._pushButton = QtWidgets.QPushButton(
            translate("filebrowser", "Stash changes")
        )
        self._pushButton.setToolTip(
            translate("filebrowser", "Stash current changes (git stash push)")
        )
        self._pushButton.clicked.connect(self._onStashChanges)

        # --- List widget that holds one row per stash entry ---
        self._list = QtWidgets.QListWidget(self)
        self._list.setMaximumHeight(150)
        self._list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # --- Layout ---
        headerLabel = QtWidgets.QLabel(translate("filebrowser", "Stash"))
        headerLabel.setStyleSheet(
            "QLabel { font-style: italic; color: gray; padding: 1px 2px; }"
        )
        headerLayout = QtWidgets.QHBoxLayout()
        headerLayout.setContentsMargins(0, 0, 0, 0)
        headerLayout.addWidget(headerLabel)
        headerLayout.addStretch()
        headerLayout.addWidget(self._pushButton)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(headerLayout)
        layout.addWidget(self._list)
        self.setLayout(layout)

        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def updateForPath(self, path):
        """Show/refresh the stash panel for the git repo containing *path*."""
        root = githelper.get_git_root(path)
        self._repo_root = root
        if root:
            self._refreshList()
            self.setVisible(True)
        else:
            self._list.clear()
            self.setVisible(False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refreshList(self):
        """Repopulate the stash list from ``git stash list``."""
        self._list.clear()
        if not self._repo_root:
            return
        for ref, message in githelper.get_stash_list(self._repo_root):
            self._addEntry(ref, message)

    def _addEntry(self, ref, message):
        """Append one stash row (label + Apply/Pop/Drop buttons)."""
        item = QtWidgets.QListWidgetItem()
        self._list.addItem(item)

        row = QtWidgets.QWidget()
        rowLayout = QtWidgets.QHBoxLayout(row)
        rowLayout.setContentsMargins(2, 1, 2, 1)
        rowLayout.setSpacing(2)

        label = QtWidgets.QLabel(message)
        label.setToolTip(ref)
        label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        rowLayout.addWidget(label)

        for text, slot in [
            (translate("filebrowser", "Apply"), self._onApply),
            (translate("filebrowser", "Pop"), self._onPop),
            (translate("filebrowser", "Drop"), self._onDrop),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.setProperty("stashRef", ref)
            btn.clicked.connect(slot)
            rowLayout.addWidget(btn)

        item.setSizeHint(row.sizeHint())
        self._list.setItemWidget(item, row)

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _onApply(self):
        """Apply the selected stash entry without removing it from the list."""
        ref = self.sender().property("stashRef")
        if ref and self._repo_root:
            ok, out = githelper.run_stash_command(self._repo_root, ["apply", ref])
            if not ok:
                QtWidgets.QMessageBox.warning(
                    self, translate("filebrowser", "Stash Apply"), out
                )
            self._afterOperation()

    def _onPop(self):
        """Apply the selected stash entry and remove it from the list."""
        ref = self.sender().property("stashRef")
        if ref and self._repo_root:
            ok, out = githelper.run_stash_command(self._repo_root, ["pop", ref])
            if not ok:
                QtWidgets.QMessageBox.warning(
                    self, translate("filebrowser", "Stash Pop"), out
                )
            self._afterOperation()

    def _onDrop(self):
        """Drop (delete) the selected stash entry after confirmation."""
        ref = self.sender().property("stashRef")
        if ref and self._repo_root:
            answer = QtWidgets.QMessageBox.question(
                self,
                translate("filebrowser", "Drop Stash"),
                translate("filebrowser", "Drop {}?").format(ref),
            )
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                ok, out = githelper.run_stash_command(
                    self._repo_root, ["drop", ref]
                )
                if not ok:
                    QtWidgets.QMessageBox.warning(
                        self, translate("filebrowser", "Stash Drop"), out
                    )
                self._afterOperation()

    def _onStashChanges(self):
        """Push current working-tree changes onto the stash."""
        if not self._repo_root:
            return
        message, ok = QtWidgets.QInputDialog.getText(
            self,
            translate("filebrowser", "Stash Changes"),
            translate("filebrowser", "Optional message (leave blank for default):"),
        )
        if ok:
            args = ["push"]
            if message.strip():
                args += ["-m", message.strip()]
            ok2, out = githelper.run_stash_command(self._repo_root, args)
            if not ok2:
                QtWidgets.QMessageBox.warning(
                    self, translate("filebrowser", "Stash Changes"), out
                )
            self._afterOperation()

    def _afterOperation(self):
        """Refresh the stash list and ask the file browser to update.

        The refresh is unconditional: even when a command fails the working
        tree may have been partially modified (e.g. a conflicted apply), so
        keeping the UI in sync is always the right thing to do.
        """
        self._refreshList()
        self.refreshRequested.emit()


class Browser(QtWidgets.QWidget):
    """A browser consists of an address bar, and tree view, and other
    widgets to help browse the file system. The browser object is responsible
    for tying the different browser-components together.

    It is also provides the API for dealing with starred dirs.
    """

    # Emitted from the fetch worker thread (marshalled to the main thread)
    _fetchResultReady = QtCore.Signal(int, int, str)

    def __init__(self, parent, config, path=None):
        super().__init__(parent)

        # Store config
        self.config = config

        # Create star button
        self._projects = Projects(self)

        # Create path input/display lineEdit
        self._pathEdit = PathInput(self)

        # Create file system proxy
        self._fsProxy = proxies.NativeFSProxy()
        self.destroyed.connect(self._fsProxy.stop)

        # Create tree widget
        self._tree = Tree(self)
        self._tree.setPath(cleanpath(self.config.path))

        # Create name filter
        self._nameFilter = NameFilter(self)
        # self._nameFilter.lineEdit().setToolTip('File filter pattern')
        self._nameFilter.setToolTip(translate("filebrowser", "Filename filter"))
        self._nameFilter.setPlaceholderText(self._nameFilter.toolTip())

        # Create search filter
        self._searchFilter = SearchFilter(self)
        self._searchFilter.setToolTip(translate("filebrowser", "Search in files"))
        self._searchFilter.setPlaceholderText(self._searchFilter.toolTip())

        # Signals to sync path.
        # Widgets that can change the path transmit signal to _tree
        self._pathEdit.dirUp.connect(self._tree.setFocus)
        self._pathEdit.dirUp.connect(self._tree.setPathUp)
        self._pathEdit.dirChanged.connect(self._tree.setPath)
        self._projects.dirChanged.connect(self._tree.setPath)
        #
        self._nameFilter.filterChanged.connect(self._tree.onChanged)  # == update
        self._searchFilter.filterChanged.connect(self._tree.onChanged)
        # The tree transmits signals to widgets that need to know the path
        self._tree.dirChanged.connect(self._pathEdit.setPath)
        self._tree.dirChanged.connect(self._projects.setPath)
        self._tree.dirChanged.connect(self._updateGitPanel)
        self._tree.dirChanged.connect(self._updateBranchCombo)

        # Create git panel (hidden when not in a git repo)
        self._gitPanel = GitPanel(self)

        # Create branch-name label (hidden when not in a git repo)
        self._gitLabel = QtWidgets.QLabel("")
        self._gitLabel.setVisible(False)
        self._gitLabel.setStyleSheet(
            "QLabel { font-style: italic; color: gray; padding: 1px 2px; }"
        )

        # Create ahead/behind badge label (hidden when both counts are 0)
        self._gitBadge = QtWidgets.QLabel("")
        self._gitBadge.setVisible(False)
        self._gitBadge.setStyleSheet(
            "QLabel { font-size: 10px; color: #888; padding: 0px 4px; }"
        )

        # Background fetch worker
        interval = getattr(self.config, "fetchInterval", 300)
        self._fetchWorker = githelper.GitFetchWorker(
            self._onFetchResult, interval=interval
        )
        self._fetchWorker.start()

        # Marshal fetch results from the worker thread to the main thread
        self._fetchResultReady.connect(self._applyAheadBehind)

        # Pause/resume the worker when the application gains/loses focus
        QtWidgets.QApplication.instance().applicationStateChanged.connect(
            self._onApplicationStateChanged
        )

        # Stop the worker when this widget is destroyed
        self.destroyed.connect(self._stopFetchWorker)

        self._layout()

        # Set and sync path ...
        if path is not None:
            self._tree.setPath(path)
        self._tree.dirChanged.emit(self._tree.path())

    def _onFetchResult(self, ahead, behind, upstream):
        """Called from the worker thread; marshal to the main thread."""
        self._fetchResultReady.emit(ahead, behind, upstream or "")

    def _applyAheadBehind(self, ahead, behind, upstream):
        """Update the badge label in the main thread."""
        if ahead == 0 and behind == 0:
            self._gitBadge.setVisible(False)
            return
        parts = []
        if ahead:
            parts.append("\u2191{}".format(ahead))
        if behind:
            parts.append("\u2193{}".format(behind))
        self._gitBadge.setText("  " + " ".join(parts))
        # Build tooltip
        tip_parts = []
        if ahead:
            tip_parts.append(
                "{} commit{} ahead".format(ahead, "s" if ahead != 1 else "")
            )
        if behind:
            tip_parts.append(
                "{} commit{} behind".format(behind, "s" if behind != 1 else "")
            )
        if upstream and tip_parts:
            tip_parts[-1] += " " + upstream
        self._gitBadge.setToolTip(", ".join(tip_parts))
        # Show the badge only when we are inside a git repository
        self._gitBadge.setVisible(True)

    def _onApplicationStateChanged(self, state):
        """Pause the fetch worker when the application loses focus."""
        if state == QtCore.Qt.ApplicationState.ApplicationActive:
            self._fetchWorker.resume()
        else:
            self._fetchWorker.pause()

    def _stopFetchWorker(self):
        self._fetchWorker.stop()

    def _updateGitPanel(self, path):
        """Update the git panel when the browser's active directory changes."""
        self._gitPanel.setPath(path)

    def getImportWizard(self):
        # Lazy loading
        try:
            return self._importWizard
        except AttributeError:
            from .importwizard import ImportWizard

            self._importWizard = ImportWizard()

            return self._importWizard

    def _layout(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # layout.setSpacing(6)
        self.setLayout(layout)
        #
        layout.addWidget(self._projects)
        layout.addWidget(self._pathEdit)
        #
        gitRow = QtWidgets.QHBoxLayout()
        gitRow.setContentsMargins(0, 0, 0, 0)
        gitRow.setSpacing(0)
        gitRow.addWidget(self._gitLabel)
        gitRow.addWidget(self._gitBadge)
        gitRow.addStretch()
        layout.addLayout(gitRow)
        #
        layout.addWidget(self._gitPanel)
        #
        layout.addWidget(self._tree)
        #
        subLayout = QtWidgets.QHBoxLayout()
        subLayout.setSpacing(2)
        subLayout.addWidget(self._nameFilter, 5)
        subLayout.addWidget(self._searchFilter, 5)
        layout.addLayout(subLayout)

    def cleanUp(self):
        self._fsProxy.stop()
        self._fetchWorker.stop()

    def _updateBranchCombo(self, path):
        """Populate the branch combo box for the repository at *path*."""
        root = githelper.get_git_root(path)
        if root:
            branch = githelper.get_git_branch(root)
            if branch:
                self._gitLabel.setText("\u2387  " + branch)
                self._gitLabel.setVisible(True)
                # Update fetch worker with new repo root
                self._fetchWorker.set_repo(root)
                # Hide badge until the next fetch completes
                self._gitBadge.setVisible(False)
                return
        self._gitLabel.setVisible(False)
        self._gitBadge.setVisible(False)
        self._fetchWorker.set_repo(None)

    def nameFilter(self):
        # return self._nameFilter.lineEdit().text()
        return self._nameFilter.text()

    def searchFilter(self):
        return {
            "pattern": self._searchFilter.text(),
            "matchCase": self.config.searchMatchCase,
            "regExp": self.config.searchRegExp,
            "wholeWords": self.config.wholeWords,
            "subDirs": self.config.searchSubDirs,
            "excludeBinary": self.config.searchExcludeBinary,
        }

    def setSearchText(self, needle, setFocus=False):
        """Set the text in the search field."""
        if self.config.searchRegExp:
            needle = re.escape(needle)
        self._searchFilter.setText(needle)
        if setFocus:
            self._searchFilter.setFocus()

    @property
    def expandedDirs(self):
        """The list of the expanded directories."""
        return self.parent().config.expandedDirs

    @property
    def starredDirs(self):
        """A list of the starred directories."""
        return [d.path for d in self.parent().config.starredDirs]

    def dictForStarredDir(self, path):
        """Return the dict of the starred dir corresponding to
        the given path, or None if no starred dir was found.
        """
        if not path:
            return None
        for d in self.parent().config.starredDirs:
            if op.normcase(d["path"]) == op.normcase(path):
                return d
        else:
            return None

    def addStarredDir(self, path):
        """Add the given path to the starred directories."""
        # Create new dict
        newProject = ssdf.new()
        newProject.path = op.normcase(path)  # Normalize case!
        newProject.name = op.basename(path)
        newProject.addToPythonpath = False
        # Add it to the config
        self.parent().config.starredDirs.append(newProject)
        # Update list
        self._projects.updateProjectList()

    def removeStarredDir(self, path):
        """Remove the given path from the starred directories.
        The path must exactlty match.
        """
        # Remove
        starredDirs = self.parent().config.starredDirs
        pathn = op.normcase(path)
        for d in starredDirs:
            if op.normcase(pathn) == op.normcase(d.path):
                starredDirs.remove(d)
        # Update list
        self._projects.updateProjectList()

    def test(self, sort=False):
        items = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            items.append(item)
            # self._tree.removeItemWidget(item, 0)
        self._tree.clear()

        # items.sort(key=lambda x: x._path)
        for item in items[::-1]:
            self._tree.addTopLevelItem(item)

    def currentProject(self):
        """Return the ssdf dict for the current project, or None."""
        return self._projects.currentDict()


class LineEditWithToolButtons(QtWidgets.QLineEdit):
    """Line edit to which tool buttons (with icons) can be attached."""

    def __init__(self, parent):
        super().__init__(parent)
        self._leftButtons = []
        self._rightButtons = []

    def addButtonLeft(self, icon, willHaveMenu=False):
        return self._addButton(icon, willHaveMenu, self._leftButtons)

    def addButtonRight(self, icon, willHaveMenu=False):
        return self._addButton(icon, willHaveMenu, self._rightButtons)

    def _addButton(self, icon, willHaveMenu, L):
        # Create button
        button = QtWidgets.QToolButton(self)
        L.append(button)
        # Customize appearance
        button.setIcon(icon)
        button.setIconSize(QtCore.QSize(16, 16))
        button.setStyleSheet("QToolButton { border: none; padding: 0px; }")
        # button.setStyleSheet("QToolButton { border: none; padding: 0px; background-color:red;}");
        # Set behavior
        button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        button.setPopupMode(button.ToolButtonPopupMode.InstantPopup)
        # Customize alignment
        if willHaveMenu:
            button.setToolButtonStyle(
                QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            if sys.platform.startswith("win"):
                button.setText(" ")
        # Update self
        self._updateGeometry()
        return button

    def setButtonVisible(self, button, visible):
        for but in self._leftButtons:
            if but is button:
                but.setVisible(visible)
        for but in self._rightButtons:
            if but is button:
                but.setVisible(visible)
        self._updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateGeometry(True)

    def showEvent(self, event):
        super().showEvent(event)
        self._updateGeometry()

    def _updateGeometry(self, light=False):
        if not self.isVisible():
            return

        # Init
        rect = self.rect()

        # Determine padding and height
        paddingLeft, paddingRight, height = 1, 1, 0
        #
        for but in self._leftButtons:
            if but.isVisible():
                sz = but.sizeHint()
                height = max(height, sz.height())
                but.move(
                    int(1 + paddingLeft),
                    int(rect.bottom() + 1 - sz.height()) // 2,
                )
                paddingLeft += sz.width() + 1
        #
        for but in self._rightButtons:
            if but.isVisible():
                sz = but.sizeHint()
                paddingRight += sz.width() + 1
                height = max(height, sz.height())
                but.move(
                    int(rect.right() - 1 - paddingRight),
                    int(rect.bottom() + 1 - sz.height()) // 2,
                )

        # Set padding
        ss = "QLineEdit {{ padding-left: {}px; padding-right: {}px}} "
        self.setStyleSheet(ss.format(paddingLeft, paddingRight))

        # Set minimum size
        if not light:
            fw = QtWidgets.qApp.style().pixelMetric(
                QtWidgets.QStyle.PixelMetric.PM_DefaultFrameWidth
            )
            msz = self.minimumSizeHint()
            w = max(msz.width(), paddingLeft + paddingRight + 10)
            h = max(msz.height(), height + fw * 2 + 2)
            self.setMinimumSize(w, h)


class PathInput(LineEditWithToolButtons):
    """Line edit for selecting a path."""

    dirChanged = QtCore.Signal(
        str
    )  # Emitted when the user changes the path (and is valid)
    dirUp = QtCore.Signal()  # Emitted when user presses the up button

    def __init__(self, parent):
        super().__init__(parent)

        # Create up button
        self._upBut = self.addButtonLeft(pyzo.icons.folder_parent)
        self._upBut.clicked.connect(self.dirUp)

        # To receive focus events
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        # Set completion mode
        self.setCompleter(QtWidgets.QCompleter())
        c = self.completer()
        c.setCompletionMode(c.CompletionMode.InlineCompletion)

        # Set dir model to completer
        self._dirModel = QtWidgets.QFileSystemModel(c)
        self._dirModel.setFilter(
            QtCore.QDir.Filter.Dirs | QtCore.QDir.Filter.NoDotAndDotDot
        )
        # filter is not synchronized with NameFilter input (e.g. "!hidden")
        c.setModel(self._dirModel)
        if sys.platform != "win32":
            self._dirModel.setRootPath("/")
        # for win32 setRootPath is done self.setPath(...)

        # Connect signals
        # c.activated.connect(self.onActivated)
        self.textEdited.connect(self.onTextEdited)
        # self.textChanged.connect(self.onTextEdited)
        # self.cursorPositionChanged.connect(self.onTextEdited)

    def setPath(self, path):
        """Set the path to display. Does nothing if this widget has focus."""
        if sys.platform == "win32":
            oldDrive, _ = op.splitdrive(self.text())
            newDrive, _ = op.splitdrive(path)
            if oldDrive != newDrive:
                self._dirModel.setRootPath(newDrive)
        if not self.hasFocus():
            self.setText(path)
            self.checkValid()  # Reset style if it was invalid first

    def checkValid(self):
        # todo: This kind of violates the abstraction of the file system
        # ok for now, but we should find a different approach someday
        # Check
        text = self.text()
        dir = cleanpath(text)
        isvalid = text and isdir(dir) and op.isabs(dir)
        # Apply styling
        ss = self.styleSheet().replace("font-style:italic; ", "")
        if not isvalid:
            ss = ss.replace("QLineEdit {", "QLineEdit {font-style:italic; ")
        self.setStyleSheet(ss)
        # Return
        return isvalid

    def event(self, event):
        # Capture key events to explicitly apply the completion and
        # invoke checking whether the current text is a valid directory.
        # Test if QtGui is not None (can happen when reloading tools)
        if QtGui and isinstance(event, QtGui.QKeyEvent):
            k = QtCore.Qt.Key
            if event.key() in [k.Key_Tab, k.Key_Enter, k.Key_Return]:
                self.setText(self.text())  # Apply completion
                self.onTextEdited()  # Check if this is a valid dir
                return True
        return super().event(event)

    def onTextEdited(self, dummy=None):
        text = self.text()
        if self.checkValid():
            self.dirChanged.emit(cleanpath(text))

    def focusOutEvent(self, event=None):
        """On focusing out, make sure that the set path is correct."""
        if event is not None:
            super().focusOutEvent(event)

        path = self.parent()._tree.path()
        self.setPath(path)


class Projects(QtWidgets.QWidget):
    dirChanged = QtCore.Signal(str)  # Emitted when the user changes the project

    def __init__(self, parent):
        super().__init__(parent)

        # Init variables
        self._path = ""

        # Create combo button
        self._combo = QtWidgets.QComboBox(self)
        self._combo.setEditable(False)
        self.updateProjectList()

        # Create star button
        self._but = QtWidgets.QToolButton(self)
        self._but.setIcon(pyzo.icons.star3)
        self._but.setStyleSheet("QToolButton { padding: 0px; }")
        self._but.setIconSize(QtCore.QSize(18, 18))
        self._but.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._but.setPopupMode(self._but.ToolButtonPopupMode.InstantPopup)
        #
        self._menu = QtWidgets.QMenu(self._but)
        self._menu.triggered.connect(self.onMenuTriggered)
        self.buildMenu()

        # Make equal height
        h = max(self._combo.sizeHint().height(), self._but.sizeHint().height())
        self._combo.setMinimumHeight(h)
        self._but.setMinimumHeight(h)

        # Connect signals
        self._but.pressed.connect(self.onButtonPressed)
        self._combo.activated.connect(self.onProjectSelect)

        # Layout
        layout = QtWidgets.QHBoxLayout(self)
        self.setLayout(layout)
        layout.addWidget(self._but)
        layout.addWidget(self._combo)
        layout.setSpacing(2)
        layout.setContentsMargins(0, 0, 0, 0)

    def currentDict(self):
        """Return the current project-dict, or None."""
        path = self._combo.itemData(self._combo.currentIndex())
        return self.parent().dictForStarredDir(path)

    def setPath(self, path):
        self._path = path
        # Find project index
        projectIndex, L = 0, 0
        pathn = op.normcase(path) + op.sep
        for i in range(self._combo.count()):
            projectPath = self._combo.itemData(i) + op.sep
            if pathn.startswith(projectPath) and len(projectPath) > L:
                projectIndex, L = i, len(projectPath)
        # Select project or not ...
        self._combo.setCurrentIndex(projectIndex)
        if projectIndex:
            self._but.setIcon(pyzo.icons.star2)
            self._but.setMenu(self._menu)
        else:
            self._but.setIcon(pyzo.icons.star3)
            self._but.setMenu(None)

    def updateProjectList(self):
        # Get sorted version of starredDirs
        starredDirs = self.parent().starredDirs
        starredDirs.sort(key=lambda p: self.parent().dictForStarredDir(p).name.lower())
        # Refill the combo box
        self._combo.clear()
        if starredDirs:
            self._combo.addItem(
                translate("filebrowser", "Projects:"), ""
            )  # No-project item
            for p in starredDirs:
                name = self.parent().dictForStarredDir(p).name
                self._combo.addItem(name, p)
        else:
            self._combo.addItem(
                translate("filebrowser", "Click star to bookmark current dir"), ""
            )

    def buildMenu(self):
        menu = self._menu
        menu.clear()

        # Add action to remove bookmark
        action = menu.addAction(translate("filebrowser", "Remove project"))
        action._id = "remove"
        action.setCheckable(False)

        # Add action to change name
        action = menu.addAction(translate("filebrowser", "Change project name"))
        action._id = "name"
        action.setCheckable(False)

        menu.addSeparator()

        # Add check action for adding to Pythonpath
        action = menu.addAction(translate("filebrowser", "Add path to Python path"))
        action._id = "pythonpath"
        action.setCheckable(True)
        d = self.currentDict()
        if d:
            checked = bool(d and d["addToPythonpath"])
            action.setChecked(checked)

        # Add action to cd to the project directory
        action = menu.addAction(
            translate("filebrowser", "Go to this directory in the current shell")
        )
        action._id = "cd"
        action.setCheckable(False)

    def onMenuTriggered(self, action):
        d = self.currentDict()
        if not d:
            return

        if action._id == "remove":
            # Remove this project
            self.parent().removeStarredDir(d.path)

        elif action._id == "name":
            # Open dialog to ask for name
            name, ok = QtWidgets.QInputDialog.getText(
                self.parent(),
                translate("filebrowser", "Project name"),
                translate("filebrowser", "New project name:"),
                text=d["name"],
            )
            if name and ok:
                d["name"] = name
            self.updateProjectList()

        elif action._id == "pythonpath":
            # Flip add-to-pythonpath flag
            d["addToPythonpath"] = not d["addToPythonpath"]

        elif action._id == "cd":
            # cd to the directory
            shell = pyzo.shells.getCurrentShell()
            if shell:
                shell.executeCommand("cd " + d.path + "\n")

    def onButtonPressed(self):
        if self._but.menu():
            # The directory is starred and has a menu. The user just
            # used the menu (or not). Update so it is up-to-date next time.
            self.buildMenu()
        else:
            # Not starred right now, create new project!
            self.parent().addStarredDir(self._path)
        # Update
        self.setPath(self._path)

    def onProjectSelect(self, index):
        path = self._combo.itemData(index)
        if path:
            # Go to dir
            self.dirChanged.emit(path)
        else:
            # Dummy item, reset
            self.setPath(self._path)


class NameFilter(LineEditWithToolButtons):
    """Combobox to filter by name."""

    filterChanged = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)

        # Create tool button, and attach the menu
        self._menuBut = self.addButtonRight(pyzo.icons["filter"], True)
        self._menu = QtWidgets.QMenu(self._menuBut)
        self._menu.triggered.connect(self.onMenuTriggered)
        self._menuBut.setMenu(self._menu)
        #
        # Add common patterns
        for pattern in [
            "*",
            "!hidden",
            "!*.pyc !hidden",
            "*.py *.pyw",
            "*.py *.pyw *.pyx *.pxd",
            "*.h *.c *.cpp",
        ]:
            self._menu.addAction(pattern)

        # Emit signal when value is changed
        self._lastValue = ""
        self.returnPressed.connect(self.checkFilterValue)
        self.editingFinished.connect(self.checkFilterValue)

        # Ensure the namefilter is in the config and initialize
        config = self.parent().config
        if "nameFilter" not in config:
            config.nameFilter = "!*.pyc"
        self.setText(config.nameFilter)

    def setText(self, value, test=False):
        """To initialize the name filter."""
        super().setText(value)
        if test:
            self.checkFilterValue()
        self._lastValue = value

    def checkFilterValue(self):
        value = self.text()
        if value != self._lastValue:
            self.parent().config.nameFilter = value
            self._lastValue = value
            self.filterChanged.emit()

    def onMenuTriggered(self, action):
        self.setText(action.text(), True)


class SearchFilter(LineEditWithToolButtons):
    """Line edit to do a search in the files."""

    filterChanged = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)

        # Create tool button, and attach the menu
        self._menuBut = self.addButtonRight(pyzo.icons["magnifier"], True)
        self._menu = QtWidgets.QMenu(self._menuBut)
        self._menu.triggered.connect(self.onMenuTriggered)
        self._menuBut.setMenu(self._menu)
        self.buildMenu()

        # Create cancel button
        self._cancelBut = self.addButtonRight(pyzo.icons["cancel"])
        self._cancelBut.setVisible(False)

        # Keep track of last value of search (initialized empty)
        self._lastValue = ""

        # Connect signals
        self._cancelBut.pressed.connect(self.onCancelPressed)
        self.textChanged.connect(self.updateCancelButton)
        self.editingFinished.connect(self.checkFilterValue)
        self.returnPressed.connect(self.forceFilterChanged)

    def onCancelPressed(self):
        """Clear text or build menu."""
        if self.text():
            super().clear()
            self.checkFilterValue()
        else:
            self.buildMenu()

    def checkFilterValue(self):
        value = self.text()
        if value != self._lastValue:
            self._lastValue = value
            self.filterChanged.emit()

    def forceFilterChanged(self):
        self._lastValue = self.text()
        self.filterChanged.emit()

    def updateCancelButton(self, text):
        visible = bool(self.text())
        self.setButtonVisible(self._cancelBut, visible)

    def buildMenu(self):
        config = self.parent().config
        menu = self._menu
        menu.clear()

        map = [
            ("searchMatchCase", False, translate("filebrowser", "Match case")),
            ("searchRegExp", False, translate("filebrowser", "RegExp")),
            ("wholeWords", False, translate("filebrowser", "Whole words")),
            ("searchSubDirs", True, translate("filebrowser", "Search in subdirs")),
            ("searchExcludeBinary", True, translate("filebrowser", "Exclude binary")),
        ]

        # Fill menu
        for option, default, description in map:
            if option is None:
                menu.addSeparator()
            else:
                # Make sure the option exists
                if option not in config:
                    config[option] = default
                # Make action in menu
                action = menu.addAction(description)
                action._option = option
                action.setCheckable(True)
                action.setChecked(bool(config[option]))

    def onMenuTriggered(self, action):
        config = self.parent().config
        option = action._option
        # Swap this option
        if option in config:
            config[option] = not config[option]
        else:
            config[option] = True
        # Update
        self.filterChanged.emit()


class GitPanel(QtWidgets.QWidget):
    """Widget showing the current git branch and providing Push/Pull operations.

    The command output is streamed line-by-line to a collapsible
    ``QPlainTextEdit`` log widget.  Errors (non-zero exit) are shown in red
    and success is confirmed in green.  The Push and Pull buttons are
    disabled while an operation is in-flight.
    """

    def __init__(self, parent):
        super().__init__(parent)

        # Internal state
        self._repo_root = None
        self._process = None

        # Branch label
        self._branchLabel = QtWidgets.QLabel("")
        self._branchLabel.setStyleSheet(
            "QLabel { font-style: italic; color: gray; padding: 1px 2px; }"
        )

        # Push button
        self._pushBut = QtWidgets.QToolButton(self)
        self._pushBut.setText(translate("filebrowser", "Push"))
        self._pushBut.setToolTip(translate("filebrowser", "Run: git push"))
        self._pushBut.clicked.connect(self._onPush)

        # Pull button
        self._pullBut = QtWidgets.QToolButton(self)
        self._pullBut.setText(translate("filebrowser", "Pull"))
        self._pullBut.setToolTip(translate("filebrowser", "Run: git pull"))
        self._pullBut.clicked.connect(self._onPull)

        # Log toggle button
        self._logToggleBut = QtWidgets.QToolButton(self)
        self._logToggleBut.setText("\u25bc")  # ▼  (collapsed state)
        self._logToggleBut.setToolTip(translate("filebrowser", "Toggle output log"))
        self._logToggleBut.clicked.connect(self._toggleLog)

        # Log widget (collapsible, read-only)
        self._log = QtWidgets.QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        font = QtGui.QFont()
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self._log.setFont(font)
        self._log.setVisible(False)

        # Top-bar layout: branch label + buttons
        topBar = QtWidgets.QHBoxLayout()
        topBar.setContentsMargins(0, 0, 0, 0)
        topBar.setSpacing(2)
        topBar.addWidget(self._branchLabel, 1)
        topBar.addWidget(self._pushBut)
        topBar.addWidget(self._pullBut)
        topBar.addWidget(self._logToggleBut)

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(topBar)
        layout.addWidget(self._log)

        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setPath(self, path):
        """Update the panel to reflect the repository at *path*."""
        root = githelper.get_git_root(path)
        if root:
            branch = githelper.get_git_branch(root)
            if branch:
                self._repo_root = root
                self._branchLabel.setText("\u2387  " + branch)
                self.setVisible(True)
                return
        self._repo_root = None
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _onPush(self):
        self._runGit(["git", "push"])

    def _onPull(self):
        self._runGit(["git", "pull"])

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    def _runGit(self, cmd):
        """Start *cmd* as a :class:`~QtCore.QProcess` and stream its output."""
        if self._process is not None:
            return  # Operation already in progress
        if self._repo_root is None:
            return

        # Show log and disable buttons for the duration of the operation
        self._log.setVisible(True)
        self._logToggleBut.setText("\u25b2")  # ▲  (expanded state)
        self._pushBut.setEnabled(False)
        self._pullBut.setEnabled(False)

        # Print the command being run as a header line
        self._appendText("$ " + " ".join(cmd) + "\n")

        # Create and start the process
        self._process = QtCore.QProcess(self)
        self._process.setWorkingDirectory(self._repo_root)
        self._process.readyReadStandardOutput.connect(self._onReadOutput)
        self._process.readyReadStandardError.connect(self._onReadError)
        self._process.finished.connect(self._onFinished)
        self._process.start(cmd[0], cmd[1:])

    def _onReadOutput(self):
        data = self._process.readAllStandardOutput()
        self._appendText(bytes(data).decode("utf-8", errors="replace"))

    def _onReadError(self):
        # git sends progress/remote messages to stderr - show without coloring
        data = self._process.readAllStandardError()
        self._appendText(bytes(data).decode("utf-8", errors="replace"))

    def _onFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self._appendText(
                translate("filebrowser", "\u2713 Done\n"), "#2a7a2a"
            )
        else:
            self._appendText(
                translate("filebrowser", "\u2717 Failed (exit code {code})\n").format(
                    code=exitCode
                ),
                "#cc0000",
            )
        self._pushBut.setEnabled(True)
        self._pullBut.setEnabled(True)
        self._process = None

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _appendText(self, text, color=None):
        """Append *text* to the log, optionally in *color* (CSS colour string)."""
        cursor = self._log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if color is not None:
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(QtGui.QColor(color))
            cursor.setCharFormat(fmt)
        else:
            cursor.setCharFormat(QtGui.QTextCharFormat())
        cursor.insertText(text)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

    def _toggleLog(self):
        """Show or hide the log widget."""
        visible = not self._log.isVisible()
        self._log.setVisible(visible)
        self._logToggleBut.setText("\u25b2" if visible else "\u25bc")
