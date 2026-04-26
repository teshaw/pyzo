"""theme.py - Central color palette and stylesheet generation for dark/light mode.

This module is the single source of truth for UI colors and stylesheet
templates.  Every widget that needs theme-aware styling should import
:func:`get_active_palette` and one of the ``build_*_stylesheet`` helpers
instead of hard-coding hex values.

Usage example::

    from pyzo.core.theme import get_active_palette, build_tab_stylesheet
    palette  = get_active_palette()
    qss      = build_tab_stylesheet(palette, padding=(4, 4, 6, 6))
    self.setStyleSheet(qss)

To react to runtime theme changes connect to ``pyzo.main.themeChanged``::

    pyzo.main.themeChanged.connect(self._applyStylesheet)
"""

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

#: Valid values for ``pyzo.config.view.qt_ui_theme``.
THEME_AUTO = "auto"    #: Follow the OS light/dark setting.
THEME_LIGHT = "light"  #: Always use a light palette.
THEME_DARK = "dark"    #: Always use a dark palette.

#: Color tokens for a light-mode UI.
LIGHT_PALETTE = {
    "background": "#ffffff",
    "surface": "#f0f0f0",
    "border": "#A09B90",
    "text_primary": "#333333",
    "text_secondary": "#666666",
    "accent": "#268bd2",
    # Tab gradient tokens (must be valid QSS color expressions).
    "tab_border_selected": "#333",
    "tab_gradient_top_selected": "rgba(0,0,128,128)",
    "tab_gradient_unsel1": "rgba(220,220,220,128)",
    "tab_gradient_unsel2": "rgba(200,200,200,128)",
    "tab_gradient_unsel3": "rgba(100,100,100,128)",
    "tab_gradient_sel1": "rgba(245,250,255,128)",
    "tab_gradient_sel2": "rgba(210,210,210,128)",
    "tab_gradient_sel3": "rgba(200,200,200,128)",
}

#: Color tokens for a dark-mode UI.
DARK_PALETTE = {
    "background": "#2d2d2d",
    "surface": "#3a3a3a",
    "border": "#555555",
    "text_primary": "#dddddd",
    "text_secondary": "#aaaaaa",
    "accent": "#268bd2",
    # Tab gradient tokens.
    "tab_border_selected": "#ddd",
    "tab_gradient_top_selected": "rgba(0,255,255,128)",
    "tab_gradient_unsel1": "rgba(0,0,0,128)",
    "tab_gradient_unsel2": "rgba(140,140,140,128)",
    "tab_gradient_unsel3": "rgba(160,160,160,128)",
    "tab_gradient_sel1": "rgba(0,0,0,128)",
    "tab_gradient_sel2": "rgba(50,50,50,128)",
    "tab_gradient_sel3": "rgba(100,100,100,128)",
}


def get_active_palette():
    """Return the palette dict for the currently active dark/light mode.

    Reads ``pyzo.darkQt`` to decide which palette to return.  The return
    value is one of :data:`DARK_PALETTE` or :data:`LIGHT_PALETTE`.
    """
    import pyzo  # late import – avoids circular imports at module level

    return DARK_PALETTE if getattr(pyzo, "darkQt", False) else LIGHT_PALETTE


# ---------------------------------------------------------------------------
# Stylesheet builders
# ---------------------------------------------------------------------------

#: QSS template for CompactTabBar.  Tokens in ``{key}`` notation are filled
#: in by :func:`build_tab_stylesheet`.  Literal QSS braces are doubled.
_TAB_STYLESHEET_TEMPLATE = """
QTabWidget::pane {{
    border-top: 0px solid #A09B90;
}}

QTabWidget::tab-bar {{
    left: 0px;
}}

QTabBar::tab {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0.0 {tab_gradient_unsel1},
                stop: 0.4 {tab_gradient_unsel2},
                stop: 1.0 {tab_gradient_unsel3} );
    border: 1px solid #A09B90;
    border-bottom-color: #DAD5CC;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 5ex;
    padding-bottom: {padding_bottom}px;
    padding-top: {padding_top}px;
    padding-left: {padding_left}px;
    padding-right: {padding_right}px;
    margin-right: -1px;
}}
QTabBar::tab:last {{
    margin-right: 0px;
}}

QTabBar::tab:hover {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0.0 {tab_gradient_sel1},
                stop: 0.4 {tab_gradient_sel2},
                stop: 1.0 {tab_gradient_sel3} );
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0.0 {tab_gradient_top_selected},
                stop: 0.12 {tab_gradient_top_selected},
                stop: 0.120001 {tab_gradient_sel1},
                stop: 0.4 {tab_gradient_sel2},
                stop: 1.0 {tab_gradient_sel3} );
}}

QTabBar::tab:selected {{
    border-width: 1px;
    border-bottom-width: 0px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    border-color: {tab_border_selected};
}}

QTabBar::tab:!selected {{
    margin-top: 3px;
}}
"""


def build_tab_stylesheet(palette, padding=(4, 4, 6, 6)):
    """Build the QSS stylesheet string for :class:`CompactTabBar`.

    Parameters
    ----------
    palette:
        A palette dict, e.g. from :func:`get_active_palette`.
    padding:
        A 4-tuple ``(top, bottom, left, right)`` of tab padding values in
        pixels.  Note: this follows the order used internally by
        :class:`CompactTabBar`, which is **not** the standard CSS order
        (top, right, bottom, left).

    Returns
    -------
    str
        Ready-to-use QSS string for ``QWidget.setStyleSheet()``.
    """
    top, bottom, left, right = padding
    return _TAB_STYLESHEET_TEMPLATE.format(
        padding_top=top,
        padding_bottom=bottom,
        padding_left=left,
        padding_right=right,
        **palette,
    )


def build_application_stylesheet(palette):
    """Build a minimal QSS stylesheet for the whole application.

    Only covers widget types that the active Qt style/palette may not style
    correctly in dark mode (e.g. ``QDockWidget`` title bars with Fusion).
    Returns an empty string in light mode so as not to interfere with
    native widget rendering.

    Parameters
    ----------
    palette:
        A palette dict, e.g. from :func:`get_active_palette`.

    Returns
    -------
    str
        Ready-to-use QSS string for ``QApplication.setStyleSheet()``.
    """
    import pyzo  # late import

    if not getattr(pyzo, "darkQt", False):
        return ""

    return """
QDockWidget::title {{
    background: {surface};
    padding: 4px;
    color: {text_primary};
}}
QDockWidget::title:hover {{
    background: {background};
}}
""".format(
        **palette
    )


def make_dark_app_palette():
    """Build and return a dark ``QPalette`` for the entire application.

    Creates a Fusion-compatible dark palette using colors from
    :data:`DARK_PALETTE`.  Compatible with PyQt5, PyQt6, PySide2, and
    PySide6 via the ``pyzo.qt`` abstraction layer.

    Returns
    -------
    QtGui.QPalette
        A fully configured dark palette ready to pass to
        ``QApplication.setPalette()``.
    """
    from pyzo.qt import QtGui

    pal = QtGui.QPalette()
    CR = QtGui.QPalette.ColorRole
    CG = QtGui.QPalette.ColorGroup
    c = QtGui.QColor

    pal.setColor(CR.Window, c(45, 45, 45))
    pal.setColor(CR.WindowText, c(221, 221, 221))
    pal.setColor(CR.Base, c(35, 35, 35))
    pal.setColor(CR.AlternateBase, c(45, 45, 45))
    pal.setColor(CR.ToolTipBase, c(25, 25, 25))
    pal.setColor(CR.ToolTipText, c(221, 221, 221))
    pal.setColor(CR.Text, c(221, 221, 221))
    pal.setColor(CR.Button, c(53, 53, 53))
    pal.setColor(CR.ButtonText, c(221, 221, 221))
    pal.setColor(CR.BrightText, c(255, 255, 255))
    pal.setColor(CR.Link, c(38, 139, 210))
    pal.setColor(CR.Highlight, c(38, 139, 210))
    pal.setColor(CR.HighlightedText, c(0, 0, 0))

    # Muted colors for the disabled state.
    for role in (CR.WindowText, CR.Text, CR.ButtonText):
        pal.setColor(CG.Disabled, role, c(127, 127, 127))
    pal.setColor(CG.Disabled, CR.Highlight, c(80, 80, 80))
    pal.setColor(CG.Disabled, CR.HighlightedText, c(127, 127, 127))

    return pal
