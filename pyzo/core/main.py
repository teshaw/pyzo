"""Module main

This module contains the main frame. Implements the main window.
Also adds some variables to the pyzo namespace, such as the callLater
function which is also defined here.

"""

import os
import sys
import time
import base64
from queue import Queue, Empty

import pyzo
from pyzo.core.icons import IconArtist
from pyzo.core import commandline
from pyzo.core.statusbar import StatusBar
from pyzo.qt import QtCore, QtGui, QtWidgets
from pyzo.core.splash import SplashWidget
from pyzo.util import paths
from pyzo.util import zon as ssdf  # zon is ssdf-light
from pyzo import translate
from pyzo.core.views import ViewManager


class MainWindow(QtWidgets.QMainWindow):
    #: Emitted after the active Qt color theme has changed (dark ↔ light or
    #: Qt style switch).  Widgets that have theme-sensitive stylesheets should
    #: connect to this signal and call their own re-styling logic.
    themeChanged = QtCore.Signal()

    def __init__(self, parent=None, locale=None):
        super().__init__(parent)

        self._closeflag = 0  # Used during closing/restarting

        # Init window title and application icon
        # Set title to something nice. On Ubuntu 12.10 this text is what
        # is being shown at the fancy title bar (since it's not properly
        # updated)
        self.setMainTitle()
        loadAppIcons()
        self.setWindowIcon(pyzo.icon)

        # Restore window geometry before drawing for the first time,
        # such that the window is in the right place
        self.resize(800, 600)  # default size
        self.restoreGeometry()

        # Show splash screen (we need to set our color too)
        w = SplashWidget(self, distro="no distro")
        self.setCentralWidget(w)
        self.setStyleSheet("QMainWindow { background-color: #268bd2;}")

        # Show empty window and disable updates for a while
        self.show()
        self.paintNow()
        self.setUpdatesEnabled(False)

        # Determine timeout for showing splash screen
        splash_timeout = time.time() + 1.0

        # Set locale of main widget, so that qt strings are translated
        # in the right way
        if locale:
            self.setLocale(locale)

        # Store myself
        pyzo.main = self

        # Init dockwidget settings
        self.setTabPosition(
            QtCore.Qt.DockWidgetArea.AllDockWidgetAreas,
            QtWidgets.QTabWidget.TabPosition.South,
        )
        self.setDockOptions(
            QtWidgets.QMainWindow.DockOption.AllowTabbedDocks
            | QtWidgets.QMainWindow.DockOption.AllowNestedDocks
            # |  QtWidgets.QMainWindow.DockOption.AnimatedDocks
        )

        # Set window atrributes
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)

        # Load icons and fonts
        loadIcons()
        loadFonts()

        # Set qt style, test success and detect Qt dark mode
        self.setQtStyle(None)  # None means init!

        if pyzo.config.settings.theme == "":
            # set light or dark mode when running Pyzo the first time
            pyzo.config.settings.theme = "default_dark" if pyzo.darkQt else "default"

        # detect dark syntax style (light text on dark background)
        try:
            theme = pyzo.themes[pyzo.config.settings.theme.lower()]["data"]
            s = theme["editor.text"]  # e.g.: "fore:#657b83, back:#fff"
            colors = dict(
                [tuple(s3.strip() for s3 in s2.split(":")) for s2 in s.split(",")]
            )
            pyzo.darkSyntax = (
                QtGui.QColor(colors["fore"]).lightness()
                > QtGui.QColor(colors["back"]).lightness()
            )
        except KeyError:
            pyzo.darkSyntax = False

        # Hold the splash screen if needed
        while time.time() < splash_timeout:
            QtWidgets.qApp.sendPostedEvents()
            QtWidgets.qApp.processEvents()
            time.sleep(0.05)

        # Populate the window (imports more code)
        self._populate()

        # Revert to normal background, and enable updates
        self.setStyleSheet("")
        self.setUpdatesEnabled(True)

        # Restore window state, force updating, and restore again
        self.restoreState()
        self.paintNow()
        self.restoreState()
        pyzo.editors.restoreEditorState()

        # Instantiate view manager
        pyzo.viewManager = ViewManager()

        # Present user with wizard if he/she is new.
        if False:  # pyzo.config.state.newUser:
            from pyzo.util.pyzowizard import PyzoWizard

            w = PyzoWizard(self)
            w.show()  # Use show() instead of exec() so the user can interact with pyzo

        # Create new shell config if there is None
        if not pyzo.config.shellConfigs2:
            from pyzo.core.kernelbroker import KernelInfo

            pyzo.config.shellConfigs2.append(KernelInfo())

        # Focus on editor
        e = pyzo.editors.getCurrentEditor()
        if e is not None:
            e.setFocus()

        # Handle any actions
        commandline.handle_cmd_args()

    # To force drawing ourselves
    def paintEvent(self, event):
        super().paintEvent(event)
        self._ispainted = True

    def paintNow(self):
        """Enforce a repaint and keep calling processEvents until
        we are repainted.
        """
        self._ispainted = False
        self.update()
        while not self._ispainted:
            QtWidgets.qApp.sendPostedEvents()
            QtWidgets.qApp.processEvents()
            time.sleep(0.01)

    def _populate(self):
        # Delayed imports
        from pyzo.core.editorTabs import EditorTabs
        from pyzo.core.shellStack import ShellStackWidget
        from pyzo.core import codeparser
        from pyzo.core.history import CommandHistory
        from pyzo.tools import ToolManager

        # Instantiate tool manager
        pyzo.toolManager = ToolManager()

        # Instantiate and start source-code parser
        if pyzo.parser is None:
            pyzo.parser = codeparser.Parser()
            pyzo.parser.start()

        # Create editor stack and make the central widget
        pyzo.editors = EditorTabs(self)
        self.setCentralWidget(pyzo.editors)

        # Create floater for shell
        self._shellDock = dock = QtWidgets.QDockWidget(self)
        DWF = dock.DockWidgetFeature
        if pyzo.config.settings.allowFloatingShell:
            dock.setFeatures(DWF.DockWidgetMovable | DWF.DockWidgetFloatable)
        else:
            dock.setFeatures(DWF.DockWidgetMovable)
        dock.setObjectName("shells")
        dock.setWindowTitle("Shells")
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)

        # Create shell stack
        pyzo.shells = ShellStackWidget(self)
        dock.setWidget(pyzo.shells)

        # Initialize command history
        pyzo.command_history = CommandHistory("command_history.py")

        # Create the default shell when returning to the event queue
        callLater(pyzo.shells.addShell)

        # Create status bar
        self.setStatusBar(StatusBar())
        # show or hide
        self.statusBar().setVisible(pyzo.config.view.showStatusbar)

        # Create menu
        from pyzo.core import menu

        pyzo.keyMapper = menu.KeyMapper()
        menu.buildMenus(self.menuBar())

        # Add the context menu to the editor
        pyzo.editors.addContextMenu()
        pyzo.shells.addContextMenu()

        # Load tools
        if pyzo.config.state.newUser and not pyzo.config.state.loadedTools:
            pyzo.toolManager.loadTool("pyzosourcestructure")
            pyzo.toolManager.loadTool("pyzofilebrowser", "pyzosourcestructure")
        elif pyzo.config.state.loadedTools:
            self.restoreTools()

    def setMainTitle(self, path=None):
        """Set the title of the main window, by giving a file path."""
        if not path:
            # Plain title
            title = "Interactive Editor for Python"
        else:
            # Title with a filename
            name = os.path.basename(path)
            if os.path.isfile(path):
                pass
            elif name == path:
                path = translate("main", "unsaved")
            else:
                pass  # We hope the given path is informative
            # Set title
            tmp = {
                "fileName": name,
                "filename": name,
                "name": name,
                "fullPath": path,
                "fullpath": path,
                "path": path,
            }
            title = pyzo.config.advanced.titleText.format(**tmp)

        # Set
        self.setWindowTitle(title)

    def getWindowState(self):
        return {
            # list of tools which are loaded
            "loadedTools": pyzo.toolManager.getLoadedTools(),
            # geometry of the top level window
            "windowGeometry": base64.encodebytes(self.saveGeometry().data()).decode(
                "ascii"
            ),
            # layout of dockwidgets and toolbars
            "windowState": base64.encodebytes(self.saveState().data()).decode("ascii"),
        }

    def saveWindowState(self):
        """Save:
        * which tools are loaded
        * geometry of the top level windows
        * layout of dockwidgets and toolbars
        """
        pyzo.config.state.update(self.getWindowState())

    def restoreTools(self, value=None):
        """Restore loaded tools"""

        if value is None:
            # No value given, try to get it from the config
            value = pyzo.config.state.loadedTools

        toolsTarget = set(value)
        toolsLoaded = set(pyzo.toolManager.getLoadedTools())
        for t in toolsLoaded - toolsTarget:
            pyzo.toolManager.closeTool(t)
        for t in toolsTarget - toolsLoaded:
            pyzo.toolManager.loadTool(t)

    def restoreGeometry(self, value=None):
        """Restore window position and whether it is maximized"""

        if value is not None:
            return super().restoreGeometry(value)

        # No value given, try to get it from the config
        if pyzo.config.state.windowGeometry:
            try:
                geometry = pyzo.config.state.windowGeometry
                geometry = base64.decodebytes(geometry.encode("ascii"))
                self.restoreGeometry(geometry)
            except Exception as err:
                print("Could not restore window geometry: " + str(err))

    def restoreState(self, value=None):
        """Restore layout of dock widgets and toolbars"""

        if value is not None:
            return super().restoreState(value)

        # No value given, try to get it from the config
        if pyzo.config.state.windowState:
            try:
                state = pyzo.config.state.windowState
                state = base64.decodebytes(state.encode("ascii"))
                self.restoreState(state)
            except Exception as err:
                print("Could not restore window state: " + str(err))

    def setQtStyle(self, stylename=None):
        """Set the style and the palette, based on the given style name.
        If stylename is None or not given will do some initialization.
        If bool(stylename) evaluates to False will use the default style
        for this system. Returns the QStyle instance.
        """

        if stylename is None:
            # Initialize

            # Get native palette (used below)
            QtWidgets.qApp.nativePalette = QtWidgets.qApp.palette()

            # Obtain default style name
            pyzo.defaultQtStyleName = str(QtWidgets.qApp.style().objectName())

            # Other than gtk+ and mac, Fusion/Cleanlooks looks best (in my opinion)
            if "gtk" in pyzo.defaultQtStyleName.lower():
                pass  # Use default style
            elif "macintosh" in pyzo.defaultQtStyleName.lower():
                pass  # Use default style
            else:
                pyzo.defaultQtStyleName = "Fusion"

            # Set style if there is no style yet
            if not pyzo.config.view.qtstyle:
                pyzo.config.view.qtstyle = pyzo.defaultQtStyleName

            # Hook into the OS color-scheme change signal (Qt 6.5+) so that
            # switching between system light/dark mode is reflected immediately.
            hints = QtWidgets.QApplication.styleHints()
            if hasattr(hints, "colorSchemeChanged"):
                try:
                    hints.colorSchemeChanged.connect(
                        self._onSystemColorSchemeChanged
                    )
                except (AttributeError, RuntimeError) as err:
                    print(
                        "Could not connect to colorSchemeChanged signal: " + str(err)
                    )

        # Init
        if not stylename:
            stylename = pyzo.config.view.qtstyle

        # Check if this style exist, set to default otherwise
        styleNames = [name.lower() for name in QtWidgets.QStyleFactory.keys()]
        if stylename.lower() not in styleNames:
            stylename = pyzo.defaultQtStyleName

        # Try changing the style
        qstyle = QtWidgets.qApp.setStyle(stylename)

        # Set palette
        if qstyle:
            QtWidgets.qApp.setPalette(QtWidgets.qApp.nativePalette)

        # detect dark mode for widgets (might be different than dark mode for syntax)
        pal = QtWidgets.qApp.palette()
        pyzo.darkQt = (
            pal.window().color().lightness() < pal.windowText().color().lightness()
        )

        # Apply theme-aware stylesheets across the application.
        self.applyTheme()

        # Done
        return qstyle

    def applyTheme(self):
        """Apply the active color theme to the application UI.

        Updates the global ``QApplication`` stylesheet with colors from
        the active palette and emits :attr:`themeChanged` so that all
        connected widgets (e.g. :class:`CompactTabBar`) can re-apply their
        own theme-sensitive stylesheets.
        """
        from pyzo.core.theme import get_active_palette, build_application_stylesheet

        palette = get_active_palette()
        QtWidgets.qApp.setStyleSheet(build_application_stylesheet(palette))
        self.themeChanged.emit()

    def _onSystemColorSchemeChanged(self):
        """Called when the OS switches between dark and light mode (Qt 6.5+).

        Re-applies the current Qt style so that ``pyzo.darkQt`` and all
        theme-sensitive stylesheets are updated to match the new scheme.
        """
        # Refresh the native palette first so the new OS colors are picked up.
        QtWidgets.qApp.nativePalette = QtWidgets.qApp.palette()
        self.setQtStyle(pyzo.config.view.qtstyle)

    def closeEvent(self, event):
        """Override close event handler."""

        # Are we restaring?
        restarting = time.time() - self._closeflag < 1.0  # noqa: F841

        # Proceed with closing...
        result = pyzo.editors.closeAll()
        if not result:
            self._closeflag = False
            event.ignore()
            return
        else:
            self._closeflag = True
            # event.accept()  # Had to comment on Windows+py3.3 to prevent error

        # Save settings
        pyzo.saveConfig()
        pyzo.command_history.save()

        # Stop command server
        commandline.stop_our_server()

        # Proceed with closing shells
        pyzo.localKernelManager.terminateAll()

        for shell in pyzo.shells:
            shell._context.close()

        # The tools need to be explicitly closed to allow them to clean up
        for toolname in pyzo.toolManager.getLoadedTools():
            tool = pyzo.toolManager.getTool(toolname)
            if hasattr(tool, "cleanUp"):
                tool.cleanUp()

        # Stop all threads (this should really only be daemon threads)
        import threading

        for thread in threading.enumerate():
            if hasattr(thread, "stop"):
                try:
                    thread.stop(0.1)
                except Exception:
                    pass

        #         # Wait for threads to die ...
        #         # This should not be necessary, but I used it in the hope that it
        #         # would prevent the segfault on Python3.3. It didn't.
        #         timeout = time.time() + 0.5
        #         while threading.activeCount() > 1 and time.time() < timeout:
        #             time.sleep(0.1)
        #         print('Number of threads alive:', threading.activeCount())

        # Proceed as normal
        super().closeEvent(event)

    def restart(self):
        """Restart Pyzo."""

        self._closeflag = time.time()

        # Close
        self.close()

        if self._closeflag:
            # Get args
            args = list(sys.argv)

            if not paths.is_frozen():
                # Prepend the executable name (required on Linux)
                lastBit = os.path.basename(sys.executable)
                args.insert(0, lastBit)

            # When running from the pip entry point pyzo.exe ... (issue #641)
            if (
                len(args) == 2
                and args[0] == "python.exe"
                and not os.path.isfile(args[1])
            ):
                args = ["python.exe", "-m", "pyzo"]

            if sys.platform == "win32":
                # workaround for MSVCRT issue with spaces in arguments
                #     https://bugs.python.org/issue436259
                from subprocess import list2cmdline

                args = [list2cmdline([s]) for s in args]

            # Replace the process!
            os.execv(sys.executable, args)

    def createPopupMenu(self):
        # This menu pops up when right clicking on the menu bar
        # or when right clicking on the title bar of a panel.

        # We have to use the initialized menu from the parent class because creating
        # a completely new QMenu would result in a memory error.
        menu = super().createPopupMenu()
        menu.clear()

        # The build_callback function is necessary because without that, a simple lambda
        # would bind the argument to the latest action of the for loop via the closure.
        def build_callback(cb, action):
            return lambda: cb(action.isChecked())

        # Add all tools, with checkmarks for those that are active
        for tool in pyzo.toolManager.getToolInfo():
            a = menu.addAction(tool.name)
            a.setCheckable(True)
            a.setChecked(bool(tool.instance))
            a.triggered.connect(build_callback(tool.menuLauncher, a))

        return menu

    def keyPressEvent(self, event):
        # Here we forward the key press events to the editor widget so that tab switching
        # will also be possible when the focus is outside the editor widget.
        if pyzo.editors:  # check for None to avoid crash during Pyzo startup
            pyzo.editors.processKeyPressFromMainWindow(event)


def loadAppIcons():
    """Load the application icons."""
    # Get directory containing the icons
    appiconDir = os.path.join(pyzo.pyzoDir, "resources", "appicons")

    # Determine template for filename of the application icon-files.
    fnameT = "pyzologo{}.png"

    # Construct application icon. Include a range of resolutions. Note that
    # Qt somehow does not use the highest possible res on Linux/Gnome(?), even
    # the logo of qt-designer when alt-tabbing looks a bit ugly.
    pyzo.icon = QtGui.QIcon()

    # Construct another icon to show when the current shell is busy
    pyzo.iconRunning = QtGui.QIcon(pyzo.icon)

    for sze in [16, 32, 48, 64, 128, 256]:
        fname = os.path.join(appiconDir, fnameT.format(sze))
        if os.path.isfile(fname):
            pyzo.icon.addFile(fname, QtCore.QSize(sze, sze))

            artist = IconArtist(pyzo.icon, size=sze)
            artist.setPenColor("#0D0")
            artist.setBrushColor("#0D0")
            a = 6 * sze // 16
            x2 = sze - 1
            x1 = x2 - a + 1
            y1 = sze - 1
            y2 = y1 - a + 1
            y3 = y2 - a + 1
            artist.addPolygon([(x1, y1), (x2, y2), (x1, y3)])
            pm = artist.finish().pixmap(sze, sze)
            pyzo.iconRunning.addPixmap(pm)

    # Set as application icon. This one is used as the default for all
    # windows of the application.
    QtWidgets.qApp.setWindowIcon(pyzo.icon)


def _brighten_icon(icon):
    """Return a brightened copy of *icon* for use on dark backgrounds.

    Non-transparent pixels have their RGB channels boosted so that dark icons
    (e.g. those with black outlines) remain visible against dark widget
    backgrounds.  Fully- or nearly-transparent pixels are left untouched.
    """
    # Pixels with alpha below this threshold are considered transparent and
    # are skipped to avoid bleeding color into invisible edge pixels.
    _TRANSPARENT_ALPHA_THRESHOLD = 10
    # Amount (0-255) added to each RGB channel to brighten dark pixels.
    # Chosen to make typical dark outlines clearly visible on dark backgrounds
    # while not severely washing out saturated icon colors.
    _BRIGHTNESS_BOOST = 70

    pm = icon.pixmap(16, 16)
    img = pm.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            rgba = img.pixel(x, y)
            alpha = (rgba >> 24) & 0xFF
            if alpha < _TRANSPARENT_ALPHA_THRESHOLD:
                continue  # leave transparent pixels alone
            r = (rgba >> 16) & 0xFF
            g = (rgba >> 8) & 0xFF
            b = rgba & 0xFF
            # Boost each channel so that dark outlines become visible on
            # dark backgrounds, while saturated colours stay readable.
            r = min(255, r + _BRIGHTNESS_BOOST)
            g = min(255, g + _BRIGHTNESS_BOOST)
            b = min(255, b + _BRIGHTNESS_BOOST)
            img.setPixel(x, y, (alpha << 24) | (r << 16) | (g << 8) | b)
    return QtGui.QIcon(QtGui.QPixmap.fromImage(img))


def loadIcons():
    """Load all icons in the icon dir."""
    # Get directory containing the icons
    iconDir = os.path.join(pyzo.pyzoDir, "resources", "icons")

    # Construct other icons
    dummyIcon = IconArtist().finish()
    pyzo.icons = ssdf.new()
    for fname in os.listdir(iconDir):
        if fname.endswith(".png"):
            try:
                # Short and full name
                name = fname.split(".")[0]
                name = name.replace("pyzo_", "")  # discard prefix
                ffname = os.path.join(iconDir, fname)
                # Create icon
                icon = QtGui.QIcon()
                icon.addFile(ffname, QtCore.QSize(16, 16))
                # In dark mode brighten the icon so dark outlines stay visible.
                if pyzo.darkQt:
                    icon = _brighten_icon(icon)
                # Store
                pyzo.icons[name] = icon
            except Exception as err:
                pyzo.icons[name] = dummyIcon
                print("Could not load icon {}: {}".format(fname, err))

    artist = IconArtist("folder_page")
    artist.addLayer("arrow_refresh")
    pyzo.icons["reload_file_from_disk"] = artist.finish()

    artist = IconArtist("page_white_copy")
    artist.addLayer("overlay_disk")
    pyzo.icons["save_copy_as"] = artist.finish()


def loadFonts():
    """Load all fonts that come with Pyzo."""
    import pyzo.codeeditor  # we need pyzo and codeeditor namespace here

    # Get directory containing the icons
    fontDir = os.path.join(pyzo.pyzoDir, "resources", "fonts")

    # Get database object
    db = QtGui.QFontDatabase  # static class

    # Set default font
    pyzo.codeeditor.Manager.setDefaultFontFamily("DejaVu Sans Mono")

    # Load fonts that are in the fonts directory
    if os.path.isdir(fontDir):
        for fname in os.listdir(fontDir):
            if "oblique" in fname.lower():  # issue #461
                continue
            if os.path.splitext(fname)[1].lower() in [".otf", ".ttf"]:
                try:
                    db.addApplicationFont(os.path.join(fontDir, fname))
                except Exception as err:
                    print("Could not load font {}: {}".format(fname, err))


class _CallbackEventHandler(QtCore.QObject):
    """Helper class to provide the callLater function."""

    def __init__(self):
        super().__init__()
        self.queue = Queue()

    def customEvent(self, event):
        while True:
            try:
                callback, args = self.queue.get_nowait()
            except Empty:
                break
            try:
                callback(*args)
            except Exception as why:
                print("callback failed: {}:\n{}".format(callback, why))

    def postEventWithCallback(self, callback, *args):
        self.queue.put((callback, args))
        QtWidgets.qApp.postEvent(self, QtCore.QEvent(QtCore.QEvent.Type.User))


def callLater(callback, *args):
    """Post a callback to be called in the main thread."""
    _callbackEventHandler.postEventWithCallback(callback, *args)


# Create callback event handler instance and insert function in pyzo namespace
_callbackEventHandler = _CallbackEventHandler()
pyzo.callLater = callLater


_SCREENSHOT_CODE = """
import random

numerator = 4

def get_number():
    # todo: something appears to be broken here
    val = random.choice(range(10))
    return numerator / val

class Groceries(list):
    \"\"\" Overloaded list class.
    \"\"\"
    def append_defaults(self):
        spam = 'yum'
        pie = 3.14159
        self.extend([spam, pie])

class GroceriesPlus(Groceries):
    \"\"\" Groceries with surprises!
    \"\"\"
    def append_random(self):
        value = get_number()
        self.append(value)

# Create some groceries
g = GroceriesPlus()
g.append_defaults()
g.append_random()

"""


def screenshotExample(width=1244, height=700):
    e = pyzo.editors.newFile()
    e.editor.setPlainText(_SCREENSHOT_CODE)
    pyzo.main.resize(width, height)


def screenshot(countdown=5):
    QtCore.QTimer.singleShot(countdown * 1000, _screenshot)


def _screenshot():
    # Grab
    print("SNAP!")
    screen = QtWidgets.qApp.primaryScreen()
    pix = screen.grabWindow(pyzo.main.winId())
    # Get name
    i = 1
    while i > 0:
        name = "pyzo_screen_{}_{:02d}.png".format(sys.platform, i)
        fname = os.path.join(os.path.expanduser("~"), name)
        if os.path.isfile(fname):
            i += 1
        else:
            i = -1
    # Save screenshot and a thumb
    pix.save(fname)
    thumb = pix.scaledToWidth(500, QtCore.Qt.SmoothTransformation)
    thumb.save(fname.replace("screen", "thumb"))
    print("Screenshot and thumb saved in", os.path.expanduser("~"))


pyzo.screenshot = screenshot
pyzo.screenshotExample = screenshotExample
