# -*- coding: utf-8 -*-
"""The Qt half of the theme: the QPalette, the QSS builders and the live switch (§4.6; the theme chapter
of `DOCUMENTATION.md`). It is a SEPARATE module because `ui/theme.py` is pure data that must stay
importable without PySide6 (the contract the tests and `ui/icons.py` rely on), while the palette, the QSS
strings and `apply_theme()` need Qt — so neither half has to compromise.

What lives here: `build_palette(theme)` (the base QPalette in ONE call); `build_qss(theme)` — **THE**
application stylesheet, every GLOBAL rule (the window chrome, the menu bar and menus, the tooltips, the
header/tab frame, the tables and trees, the floating cards), one theme → one stable string;
`STYLE_BUILDERS` — the widget-level registry (every stylesheet a SINGLE widget would build inline: the
muted status labels, the dialog separators and headings, the search-bar card, the find bar, the
multi-input frame), one name → one builder → one string, so the first styling and a theme switch go
through the same code; `style(name)` / `refresh(widget, name)` — the accessors the widgets use (`refresh` also hides the widget while the stylesheet changes, the Qt repaint rule); `apply_theme(theme, app=None)` — the live switch: the QPalette, the QSS and a repaint of every window (and of the scene, through `MainWindow`). Out of scope on purpose: the terminal's own output palettes, `TerminalWidget.CURSOR_COLOR`, the drawio writer and the sidebar's geometry-only `text-align` rule — non-QSS colours were never this module's."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

try:  # the module import shape used by every consumer since v1.2.5
    from . import theme as theme_module
except ImportError:  # flat launch from the project root
    import theme as theme_module


# ── The QPalette ──────────────────────────────────────────────────────────────

def build_palette(theme=None) -> QPalette:
    """The base window QPalette of a theme (the v1.2.5 ``main.py`` palette).

    Fusion + this palette is what the whole application draws its standard
    controls with; a theme switch therefore has to re-apply it (``apply_theme``).
    Built from a COPY of the application's current palette so platform-specific
    roles the project does not name survive untouched.
    """
    t = theme if theme is not None else theme_module.THEME
    app = QApplication.instance()
    palette = QPalette(app.palette()) if app is not None else QPalette()
    role = QPalette.ColorRole
    palette.setColor(role.Window, QColor(t.window_bg))
    palette.setColor(role.WindowText, QColor(t.text_primary))
    palette.setColor(role.Base, QColor(t.base_bg))
    palette.setColor(role.AlternateBase, QColor(t.surface_alt))
    palette.setColor(role.Text, QColor(t.text_primary))
    palette.setColor(role.Button, QColor(t.surface_alt))
    palette.setColor(role.ButtonText, QColor(t.text_primary))
    # Roles the palette leaves to the platform but which a LIGHT theme cannot inherit from a dark
    # Fusion default: the disabled/highlight tones follow the theme explicitly, or a disabled label
    # would stay pale-on-pale. The HIGHLIGHT is a FILL THAT CARRIES TEXT (`HighlightedText`), so it is
    # the STRONG accent — the decorative sky of LIGHT leaves selected text at 2.05:1. In DARK the two
    # are the same value, so nothing moves.
    palette.setColor(role.Highlight, QColor(t.accent_strong))
    palette.setColor(role.HighlightedText, QColor(t.canvas_bg))
    palette.setColor(role.ToolTipBase, QColor(t.window_bg))
    palette.setColor(role.ToolTipText, QColor(t.text_primary))
    palette.setColor(role.PlaceholderText, QColor(t.text_muted))
    for group in (QPalette.ColorGroup.Disabled,):
        palette.setColor(group, role.Text, QColor(t.text_muted))
        palette.setColor(group, role.WindowText, QColor(t.text_muted))
        palette.setColor(group, role.ButtonText, QColor(t.text_muted))
    return palette


# ── The application stylesheet ────────────────────────────────────────────────

def build_qss(theme=None) -> str:
    """**THE** application QSS of a theme (v1.4.3, ROADMAP task 4).

    One theme in → one stable string out (the acceptance test compares two calls
    and asserts LIGHT ≠ DARK on the surfaces). The rules are the *global* ones:
    the window chrome, the menu bar/menus, the tooltips, the header/tab frame,
    the item views (the sidebar tree, the hotkeys table, the settings lists) and
    the floating cards' shared frame. A widget that needs its OWN stylesheet
    takes it from ``STYLE_BUILDERS`` below — the two halves together are "all
    QSS strings in one place".

    **v1.5rc1 — the accent has TWO roles here.** A rule that uses the accent as
    INK (`color:`) or as a FILL THAT CARRIES TEXT (a selection row) uses
    ``accent_strong``; a rule that uses it as DECORATION (a frame, a border, a
    focus outline) keeps ``accent``. In DARK both resolve to the same value, so
    the DARK stylesheet is byte-identical to the v1.4.7 one; in LIGHT the strong
    tone is the one that clears AA (`tests/test_theme_contrast.py`).
    """
    t = theme if theme is not None else theme_module.THEME
    return f"""
/* ── global chrome ───────────────────────────────────────────────────── */
QMainWindow, QDialog {{
    background-color: {t.window_bg};
    color: {t.text_primary};
}}
QWidget {{
    color: {t.text_primary};
}}
QLabel:disabled {{
    color: {t.text_muted};
}}

/* ── menu bar and menus ──────────────────────────────────────────────── */
QMenuBar {{
    background-color: {t.window_bg};
    color: {t.text_primary};
    border-bottom: 1px solid {t.surface_alt};
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
}}
QMenuBar::item:selected {{
    background-color: {t.base_bg};
    border-radius: 4px;
}}
QMenu {{
    background-color: {t.window_bg};
    color: {t.text_primary};
    border: 1px solid {t.surface_alt};
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {t.accent_strong};
    color: {t.canvas_bg};
}}
QMenu::item:disabled {{
    color: {t.text_muted};
}}
QMenu::separator {{
    height: 1px;
    background: {t.surface_alt};
    margin: 4px 8px;
}}

/* ── tooltips ────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {t.window_bg};
    color: {t.text_primary};
    border: 1px solid {t.surface_alt};
    padding: 3px 6px;
}}

/* ── frames, tabs, dock titles ───────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t.surface_alt};
}}
QTabBar::tab {{
    background-color: {t.base_bg};
    color: {t.text_primary};
    padding: 5px 12px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{
    background-color: {t.surface_alt};
}}
/* v1.9.8 (task 5): an INACTIVE tab label keeps the primary ink — the muted tone the audit
   measured was too close to the surface behind it, and the selected BACKGROUND is what tells the
   two apart. */
QTabBar::tab:!selected {{
    color: {t.text_primary};
}}
QHeaderView::section {{
    background-color: {t.base_bg};
    color: {t.text_primary};
    border: none;
    border-right: 1px solid {t.surface_alt};
    border-bottom: 1px solid {t.surface_alt};
    padding: 4px 6px;
}}
QDockWidget {{
    color: {t.text_primary};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QSplitter::handle {{
    background-color: {t.surface_alt};
}}

/* ── item views (tree / table / list) ────────────────────────────────── */
QTreeWidget, QTreeView, QTableWidget, QTableView, QListWidget, QListView {{
    background-color: {t.base_bg};
    alternate-background-color: {t.window_bg};
    color: {t.text_primary};
    border: 1px solid {t.surface_alt};
    selection-background-color: {t.accent_strong};
    selection-color: {t.canvas_bg};
}}
QTreeWidget::item:hover, QTableWidget::item:hover {{
    background-color: {t.surface_alt};
}}

/* ── the floating cards (the search bar / find bar / minimap keep their own) */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {t.base_bg};
    color: {t.text_primary};
    border: 1px solid {t.surface_alt};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {t.accent_strong};
    selection-color: {t.canvas_bg};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {t.accent};
}}
QPushButton {{
    background-color: {t.surface_alt};
    color: {t.text_primary};
    border: 1px solid {t.surface_alt};
    border-radius: 4px;
    padding: 4px 12px;
}}
QPushButton:hover {{
    border: 1px solid {t.accent};
}}
QPushButton:disabled {{
    color: {t.text_muted};
}}
QCheckBox, QRadioButton {{
    color: {t.text_primary};
}}
QStatusBar {{
    background-color: {t.window_bg};
    color: {t.text_muted};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: {t.window_bg};
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: {t.surface_alt};
    border-radius: 4px;
}}
""".strip()


# ── The widget-level stylesheets (the ONE registry) ───────────────────────────
# Every entry replaces an f-string that would otherwise be built inline in a widget's
# __init__ — and, more importantly, that could never be rebuilt. The keys are
# stable names; a widget calls `theme_qss.style("<key>")` at construction and
# `theme_qss.refresh(self, "<key>")` from its `refresh_theme()`.

#: v1.5rc4 (ROADMAP task 5): the thickness of the visible focus frame, in pixels —
#: declared HERE because the frame is a stylesheet for a standard widget and a pen
#: width for a custom canvas, and the two must be the same number. `ui/focus_ring.py`
#: reads this constant instead of carrying a second copy.
FOCUS_RING_WIDTH = 2

STYLE_BUILDERS = {
    # status / hint labels (TEXT_MUTED, with the padding of their own layout)
    "status.muted": lambda t: f"color: {t.text_muted};",
    "status.bar_counts": lambda t: f"color: {t.text_muted}; padding-right: 10px;",
    "status.bar_zoom": lambda t: f"color: {t.text_primary}; padding-right: 6px;",
    # The CLICKABLE status counters of the status bar: the clickable ones are tinted like a link (the
    # accent) and the ACTIVE one — the filter currently applied to the sidebar — is bold, so the
    # transient state is visible without a second widget. This is INK on the window surface, so it is
    # the STRONG accent (and its strong hover shade): the decorative sky of LIGHT measured 1.96:1 here.
    "status.bar_filter": lambda t: f"color: {t.accent_strong}; padding-right: 10px;",
    "status.bar_filter_active": lambda t: (
        f"color: {t.accent_strong_hover}; font-weight: bold; padding-right: 10px;"),
    # v1.4.5 (ROADMAP task 2): the one button of the first-run empty state — the
    # primary action of an empty map, so it carries the accent fill instead of the
    # neutral surface the global QPushButton rule gives every other button.
    # v1.5rc1: an accent FILL THAT CARRIES TEXT — the strong tone, with the strong
    # hover shade as its border and its hover fill.
    "empty_state.button": lambda t: f"""
QPushButton#EmptyStateButton {{
    background-color: {t.accent_strong};
    color: {t.canvas_bg};
    border: 1px solid {t.accent_strong_hover};
    border-radius: 4px;
    padding: 4px 14px;
    font-weight: bold;
}}
QPushButton#EmptyStateButton:hover {{
    background-color: {t.accent_strong_hover};
}}
""",
    # v1.5rc3 (ROADMAP task 2): the Undo affordance next to a destructive action's
    # status message (ui/status_bar.py). It is a LINK-like button (ink, no frame) and
    # it is INK on the window surface — the STRONG accent, exactly like the status
    # counters above (the decorative sky measured 1.96:1 in LIGHT).
    "status.undo_button": lambda t: f"""
QToolButton#UndoOfferButton {{
    color: {t.accent_strong};
    border: none;
    background-color: transparent;
    padding: 0px 4px;
    font-weight: bold;
}}
QToolButton#UndoOfferButton:hover {{
    color: {t.accent_strong_hover};
    text-decoration: underline;
}}
""",
    "status.sftp_row": lambda t: f"color: {t.text_muted}; padding: 2px 0;",    "status.terminal_row": lambda t: f"color: {t.text_muted}; padding: 4px 0;",    "status.terminal_bold": lambda t: f"font-weight: bold; color: {t.text_primary};",
    # v1.9.8 (task 3): the terminal's two CORNER controls (Split Terminal / Files Commander) and
    # the session tab's close mark. The shipped buttons wore the global QPushButton rule, which
    # paints no :checked state at all — a checkable control looked the same on and off. The padding
    # stays TIGHT on purpose: the corner sits on the session tab bar, whose width is part of the
    # terminal window's own 640 px floor.
    "corner.button": lambda t: f"""
QPushButton {{
    background-color: {t.surface_alt};
    color: {t.text_primary};
    border: 1px solid {t.surface_alt};
    border-radius: 4px;
    padding: 2px 6px;
}}
QPushButton:hover {{
    border: 1px solid {t.accent};
}}
QPushButton:checked {{
    background-color: {t.accent_strong};
    color: {t.canvas_bg};
    border: 1px solid {t.accent_strong_hover};
}}
""",
    # v1.9.8 (task 4): the source switch of a Files pane (`Server | Local | Elevated`). The
    # INACTIVE state is what a user has to read — the platform's auto-raised QToolButton left it
    # too close to the surface it sits on — so the ink is explicit and the ACTIVE state is the
    # strong accent with a frame of its own. The padding stays TIGHT on purpose: this row sets the
    # pane's minimum width, which the terminal window's own floor is built on.
    "sftp.source_button": lambda t: f"""
QToolButton {{
    color: {t.text_primary};
    background-color: transparent;
    border: 1px solid transparent;
    padding: 1px 3px;
}}
QToolButton:hover {{
    border: 1px solid {t.accent};
}}
QToolButton:checked {{
    color: {t.accent_strong};
    border: 1px solid {t.accent_strong};
}}
""",
    # dialog separators and headings
    "separator": lambda t: f"color: {t.surface_alt};",
    "heading": lambda t: f"font-weight: bold; color: {t.text_primary};",
    "title": lambda t: f"font-size: 13pt; font-weight: bold; color: {t.text_primary};",
    "subtitle": lambda t: f"color: {t.text_muted}; font-size: 10pt;",
    # the floating search card (ui/map_search_bar.py) — the geometry keeps the
    # sizes the widget always had; only the colours move with the theme
    "search_bar": lambda t: f"""
QWidget#MapSearchBar {{
    background-color: {t.window_bg};
    border: 1px solid {t.accent};
    border-radius: {t.radius_search_bar}px;
}}
QLineEdit {{
    background-color: transparent;
    border: none;
    color: {t.text_primary};
    font-size: 13px;
    padding: 2px 4px;
    selection-background-color: {t.accent_strong};
}}
QLabel {{
    color: {t.text_muted};
    font-size: 12px;
}}
QPushButton {{
    background-color: transparent;
    border: none;
    color: {t.text_muted};
    font-size: 15px;
}}
QPushButton:hover {{ color: {t.text_primary}; }}
""",
    # the floating find card of the terminal canvas (modules/terminal_find_bar.py)
    "find_bar": lambda t: f"""
QWidget#TerminalFindBar {{
    background-color: {t.window_bg};
    border: 1px solid {t.accent};
    border-radius: {t.radius_search_bar}px;
}}
QLineEdit {{
    background-color: transparent;
    border: none;
    color: {t.text_primary};
    font-size: 12px;
    padding: 2px 4px;
    selection-background-color: {t.accent_strong};
}}
QLabel {{
    color: {t.text_muted};
    font-size: 11px;
}}
QPushButton {{
    background-color: transparent;
    border: none;
    color: {t.text_muted};
    font-size: 14px;
}}
QPushButton:hover {{ color: {t.text_primary}; }}
""",
    # the sticky note editor (graphics/sticky_note.py) — transparent over the
    # painted note body, so only the text colour follows the theme
    "note.editor": lambda t: f"""
QTextEdit#StickyNoteEditor {{
    background: transparent;
    border: none;
    color: {t.note_text};
    padding: 6px;
}}
""",
    # v1.5rc4 (ROADMAP task 5): the VISIBLE FOCUS of a keyboard domain that is a
    # standard widget (the sidebar's tree — ui/focus_ring.py owns the state). The
    # INACTIVE entry keeps the very same 2 px so a focus change never reflows the
    # layout; the ACTIVE one is the STRONG accent (ink-level contrast, v1.5rc1 role),
    # never the decorative tone and never a new colour.
    "focus.widget": lambda t: f"border: {FOCUS_RING_WIDTH}px solid {t.accent_strong};",
    "focus.widget_off": lambda t: f"border: {FOCUS_RING_WIDTH}px solid transparent;",
    # The two panel COLLAPSE buttons (the "◇" of the sidebar's bottom row and the map's corner
    # overlay): plain QToolButtons, and this entry is their ONE definition — a themed surface fill with
    # a border, so the button READS as a button before the pointer arrives (an auto-raised button
    # appears only under the cursor). The padding is deliberately tight: the glyph stays the point.
    "collapse.button": lambda t: f"""
QToolButton {{
    background-color: {t.surface_alt};
    color: {t.text_primary};
    border: 1px solid {t.base_bg};
    border-radius: 4px;
    padding: 2px 6px;
}}
QToolButton:hover {{
    border: 1px solid {t.accent};
}}
QToolButton:pressed {{
    background-color: {t.base_bg};
}}
""",
}


def style(name: str) -> str:
    """The stylesheet of one registry name under the ACTIVE theme.

    An unknown name returns an empty string rather than raising: a widget's
    cosmetic style must never be able to break the construction of a window.
    """
    builder = STYLE_BUILDERS.get(name)
    if builder is None:
        return ""
    return builder(theme_module.THEME)


def style_names():
    """The registry keys (the completeness/drift test asks for them)."""
    return sorted(STYLE_BUILDERS)


def refresh(widget, name: str) -> None:
    """Re-apply one registry stylesheet to a widget (v1.4.3).

    ``setStyleSheet`` on a VISIBLE widget does not always repaint the already
    laid-out text (Qt keeps the old appearance until the next paint — measured
    on this codebase in the profile dialog), so the widget is hidden for the
    swap and shown again. Idempotent; a dead C++ object (Qt teardown) is
    swallowed, because the switch may be walking containers a session is
    closing under it.
    """
    try:
        was_visible = widget.isVisible()
        if was_visible:
            widget.hide()
        widget.setStyleSheet(style(name))
        if was_visible:
            widget.show()
    except RuntimeError:
        pass  # Qt teardown — the widget is already destroyed


# ── The live switch ───────────────────────────────────────────────────────────

def apply_theme(theme=None, app=None, refresh_windows: bool = True):
    """Apply a theme to the live application (v1.4.3, ROADMAP task 4).

    The whole switch, in the ONE place it happens:

      1. ``theme.set_theme(instance)`` — every live module constant /
         descriptor in the application now resolves to the new values;
      2. the base QPalette (``build_palette``) + the application QSS
         (``build_qss``) — ``QApplication.setStyleSheet`` re-polishes every
         widget already constructed, which is what makes the standard controls
         follow without a rebuild;
      3. a repaint: every top-level window is updated, and each window that
         knows how to refresh its OWN half (``refresh_theme()`` — the terminals,
         the SFTP tabs, the floating cards, the scene/grid of the map) is asked.

    Returns the active instance. ``refresh_windows=False`` is for the tests and
    for a caller that repaints by itself. Never raises: a broken refresh path
    must not be able to leave the application in a half-applied theme.
    """
    instance = theme_module.set_theme(theme if theme is not None else theme_module.THEME)
    application = app if app is not None else QApplication.instance()
    if application is None:
        return instance
    try:
        application.setPalette(build_palette(instance))
        application.setStyleSheet(build_qss(instance))
    except Exception:  # noqa: BLE001 — the theme is cosmetic; never fatal
        pass
    if not refresh_windows:
        return instance
    try:
        for widget in application.topLevelWidgets():
            _refresh_tree(widget)
    except Exception:  # noqa: BLE001
        pass
    return instance


def _refresh_tree(widget) -> None:
    """Ask one top-level widget (and its children) to follow the theme.

    A widget opts in by defining ``refresh_theme()`` (the ``retranslate()``
    pattern of v1.3.3.1: "every UI container owns one"). The walk is bounded by
    the widget tree of the windows that are ALIVE right now — a session closing
    under the switch is skipped with its RuntimeError.
    """
    try:
        hook = getattr(widget, "refresh_theme", None)
        if callable(hook):
            hook()
        widget.update()
    except RuntimeError:
        return  # Qt teardown
    except Exception:  # noqa: BLE001 — one broken container must not stop the rest
        pass
    try:
        children = widget.findChildren(object)
    except RuntimeError:
        return
    for child in children:
        try:
            hook = getattr(child, "refresh_theme", None)
            if callable(hook):
                hook()
        except RuntimeError:
            continue
        except Exception:  # noqa: BLE001
            continue
