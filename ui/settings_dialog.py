# -*- coding: utf-8 -*-
"""v1.1: Settings dialog (hub) — ROADMAP v1.1, tasks 1–6; v1.1.1 — options around the hub.

QTabWidget "General / Terminal / Statuses / Autosave / Map / Hotkeys / Language":
centralized application settings + entry points (the "Settings" menu and the
⚙ sidebar button — in ui/main_window.py / ui/sidebar.py). Each next idea from
the ROADMAP is added as a field/checkbox in an existing tab, not as a new
UI version.

Storage — a SINGLE ~/.sshmap/config.json (i18n.save_config, atomic
merge-write); all keys are optional, defaults = current behavior:
  * General:          external_terminal (v1.1: moved from ~/.sshmap_settings.json,
                     migration on read — modules/external_terminal.py, task 7)
                     + v1.1.1: ui_font_family/ui_font_size (UI font, live),
                     ui_show_sidebar_buttons (the sidebar button block);
  * Terminal:         terminal_palette / terminal_font_size / terminal_history_lines
                     (v1.0 keys) + terminal_close_behavior (v1.1: "close"|"ask")
                     + v1.1.1: terminal_font (family; read since v1.0, UI for
                     the first time), terminal_max_open (own-terminals limit,
                     default 4; v1.3.3.8: the spin is 1..32 — the VALIDATOR's range)
                      + v1.2.2: terminal_mode ("windows" default | "tabs" — the dock on the map)
                      + v1.3.3.8: terminal_wheel ("scrollback" default | "off" — the
                      mouse wheel; the LAST key that had no UI at all)
                      + v1.6.2: terminal_cursor_style ("bar" default — the thin blinking
                      line of Windows Terminal | "block" | "underline"; the first NEW
                      UI-facing key since terminal_wheel, so collect() goes 22 → 23);
  * Statuses:         status_interval_sec / status_probe_timeout_sec (v1.1; defaults
                     30 s / 3.0 s — v1.0 behavior, services/status_checker.py);
  * Autosave:         autosave_enabled / autosave_interval_sec / backup_count (v0.9.7);
  * Map:              v1.1.1: ui_node_double_click ("properties"|"connect"),
                     ui_show_connection_type (type on the connection plaque);
  * Language:         language — applied immediately (signal language_changed →
                     MainWindow._switch_language; the "Help → Language" item is kept).
                     v1.3.3.8 (ROADMAP task 2): the tab also carries the language
                     MANAGER — "Import a language file…" (validated + copied into
                     ~/.sshmap/languages/, the user folder, created on demand; the
                     imported language becomes active at once) and "Export the current
                     language…" (the file that WINS for the active language, or the
                     `en` template); both report through `language.*` in a status
                     label. Import/export only — no editor, no downloading.
  * Hotkeys (v1.3.2): hotkeys — a nested dict action_id → sequence string
                     ("" = the hotkey is disabled); the rows come from the action
                     registry ui/hotkey_registry.py, the action NAMES reuse the
                     existing menu i18n keys. Collected on OK and applied live by
                     MainWindow._apply_hotkeys (QAction.setShortcut/QShortcut.setKey).

v1.1.1: load_ui_settings() — the ui_* key validator (the get_status_settings
pattern); live application without a restart — MainWindow
(_apply_settings_from_dialog): QApplication.setFont, the font of open
terminal windows, sidebar button visibility, double-click mode, connection
plaque redraw.

Signals (the module pattern — like ui/sidebar.py: the dialog does not know
about MainWindow):
    applied()            — the config was saved on OK; MainWindow applies
                           autosave (QTimer), statuses (StatusChecker) and
                           the v1.1.1 options (fonts/buttons/double-click/
                           plaques) live; the terminal reads the config on
                           the next window creation;
    language_changed(str)— the language choice in the "Language" tab
                           (immediately, before OK).

i18n: keys settings.* × en/ru/zh; the string registry — in retranslate()
(a language change inside the open dialog updates its own labels).
"""

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QPushButton, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QKeySequenceEdit, QFileDialog,
)

try:  # v1.2.5: central theme (colors/radii/fonts — ui/theme.py); no literals in the UI code
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # i18n — top-level package (flat run from the project root)
    from i18n import t as _translate
except Exception:  # pragma: no cover - fallback path
    try:
        from .i18n import t as _translate
    except Exception:
        _translate = None

try:  # v1.1 (task 7): a single source — config.json; the migration is inside the module
    from ..modules.external_terminal import (
        TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
        load_external_terminal_setting,
    )
except ImportError:
    try:
        from modules.external_terminal import (
            TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
            load_external_terminal_setting,
        )
    except ImportError:  # flat layout without the module — the "General" tab without the combo
        TERMINAL_CHOICES_WINDOWS = ["auto"]
        TERMINAL_CHOICES_LINUX = ["auto"]
        def load_external_terminal_setting():  # noqa: N802
            return "auto"


def _t(key: str, **kw) -> str:
    """Safe translation (like in ui/command_palette.py): without i18n — the key itself."""
    if _translate is not None:
        try:
            return _translate(key, **kw) if kw else _translate(key)
        except Exception:  # noqa: BLE001 — an i18n failure must not break the dialog
            pass
    return key


def _log_dialog(message: str) -> None:
    """A lazy logger for the dialog's non-fatal failures (the hotkey reset path).

    Mirrors the `_log` of ui/hotkey_registry.py: a broken registry / a failed save
    must be visible in ~/.sshmap/logs without ever breaking the open dialog.
    """
    try:
        from modules.logger import get_logger
        get_logger("ui.settings_dialog").warning(message)
    except Exception:  # noqa: BLE001 — logging must never break the dialog
        pass


# v1.3.3.8 (ROADMAP task 2): the technical detail behind a refused language file.
# `language.import_failed` / `language.exported` carry it as {error} — exactly like
# `msg.save_failed{error=…}` and `msg.import_servers_failed{error=…}` carry a path or
# an exception text: a reason is a diagnostic, not a translatable UI sentence. The
# reason CODES come from i18n.import_language_file()/export_language_file().
_IMPORT_ERROR_DETAIL = {
    "unreadable": "the file cannot be read",
    "not_json": "not a JSON file",
    "not_object": "the root is not a JSON object",
    "no_keys": "no translation keys",
    "name_missing": None,       # translated — language.name_missing (see _import_error_detail)
    "bad_code": "the file name is not usable as a language code",
    "copy_failed": "the file could not be written into ~/.sshmap/languages/",
}
_EXPORT_ERROR_DETAIL = {
    "unknown_language": "no such language file",
    "unreadable": "the language file cannot be read",
    "not_json": "the language file is not valid JSON",
    "not_object": "the language file's root is not a JSON object",
    "write_failed": "the destination file could not be written",
}


def _import_error_detail(reason: str) -> str:
    """The {error} text of a refused import (v1.3.3.8) — the one reason that is a real
    UI sentence instead of a diagnostic is translated (`language.name_missing`)."""
    if reason == "name_missing":
        return _t("language.name_missing")
    return _IMPORT_ERROR_DETAIL.get(reason, reason or "unknown error")


def load_ui_settings():
    """v1.1.1 (ROADMAP v1.1.1): reads and validates the ui_* keys from ~/.sshmap/config.json.

    The same pattern as get_status_settings()/get_autosave_settings() — each
    domain reads its own keys; the source is i18n.load_config() (never
    fails). Returns:
      {"font_family": str,            # "" — not set (the system font)
       "font_size": int | None,       # None — not set (the system size; 0 = the same)
       "node_double_click": str,      # "properties" (default) | "connect"
       "show_sidebar_buttons": bool,  # default True — the sidebar button block is visible
       "show_connection_type": bool}  # default False — the type on the connection plaque is not drawn
    Invalid values (foreign type, out of range) → default. Never raises.
    """
    defaults = {"font_family": "", "font_size": None,
                "node_double_click": "properties",
                "show_sidebar_buttons": True, "show_connection_type": False}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    cfg = load_config()

    v = cfg.get("ui_font_family")
    if isinstance(v, str):
        defaults["font_family"] = v.strip()

    v = cfg.get("ui_font_size")
    if isinstance(v, int) and not isinstance(v, bool) and 6 <= v <= 72:
        defaults["font_size"] = v     # broken/0/out of range → the system size (default)

    v = cfg.get("ui_node_double_click")
    if isinstance(v, str) and v.strip().lower() in ("properties", "connect"):
        defaults["node_double_click"] = v.strip().lower()  # broken/foreign → "properties"

    v = cfg.get("ui_show_sidebar_buttons")
    if isinstance(v, bool):
        defaults["show_sidebar_buttons"] = v

    v = cfg.get("ui_show_connection_type")
    if isinstance(v, bool):
        defaults["show_connection_type"] = v

    return defaults


# ── v1.4.3 (ROADMAP task 6): the "Appearance" tab — the theme config ──────────
# The `theme` key of ~/.sshmap/config.json: a NESTED object {"mode", "accent"}
# (the `hotkeys` precedent — one key, several values). Everything here validates
# and never raises: a broken value is the DARK theme + the default hue, plus ONE
# log line, which is what keeps a hand-edited config from leaving the app
# themeless (exactly like `get_status_settings` and `load_ui_settings`).
#
# Note the SHAPE of the choice: the user picks a COLOUR (a swatch or their own
# hex), while `Theme` stores the HUE. The hue comes back out of the hex through
# `theme.hex_hue`, so editing "accent": "#38bdf8" by hand and re-opening the tab
# shows the same swatch as picking sky by hand would.

#: The accent swatches of the tab: (key suffix, hue, representative hex).
#: The hex is computed, not typed — a swatch cannot drift from its hue.
def accent_swatches():
    """[(name, hue, hex)] — the presets the "Appearance" tab offers (v1.4.3).

    Sky is FIRST and equals the default hue, so "reset to the default look" is
    one click on the leftmost swatch. The middle of the accent's own range is the
    generator's job: every entry is `theme.accent_hex(hue)`.
    """
    presets = [("sky", theme.DEFAULT_ACCENT_HUE),
               ("cyan", 187.0),
               ("green", 142.0),
               ("amber", 38.0),
               ("orange", 25.0),
               ("pink", 330.0),
               ("violet", 262.0),
               ("slate", 215.0)]
    return [(name, hue, theme.accent_hex(hue)) for name, hue in presets]


def load_theme_settings() -> dict:
    """The validated `theme` key: {"mode", "accent", "motion", "density"} (v1.4.3).

    ``mode`` is one of ``theme.MODES`` — ``dark`` (the default), ``light`` or
    ``auto`` (v1.5rc1: the platform's own colour scheme decides, and the window
    follows a live ``colorSchemeChanged``). ``motion`` is the "Reduce motion"
    switch of the same tab. ``density`` (v1.6) is the card density of the map —
    ``normal`` (the historical card) or ``compact`` — validated by
    ``theme.resolve_density``.

    Broken / missing / foreign values fall back to the dark theme, the default
    accent, the motion ON and the normal card — the config is hand-editable, so every
    read is defensive. Never raises.
    """
    result = {"mode": theme.MODE_DARK, "accent": theme.accent_hex(), "motion": True,
              "density": theme.DENSITY_NORMAL}
    try:
        from i18n import load_config
    except Exception:
        return result
    raw = load_config().get("theme")
    if not isinstance(raw, dict):
        if raw is not None:
            _log_dialog(f"theme: the config value is not an object ({raw!r}) — using the defaults")
        return result
    mode = raw.get("mode")
    if isinstance(mode, str) and mode.strip().lower() in theme.MODES:
        result["mode"] = mode.strip().lower()
    elif mode is not None:
        _log_dialog(f"theme.mode {mode!r} is not one of {theme.MODES} — using {result['mode']!r}")
    accent = raw.get("accent")
    if theme.is_valid_hex(accent):
        result["accent"] = "#" + accent.strip().lstrip("#").lower()
    elif accent is not None:
        _log_dialog(f"theme.accent {accent!r} is not a #rrggbb colour — using the default")
    # v1.5rc1: the motion switch. Only a real boolean counts — a string "false"
    # or a 0 is a broken value, and a broken value means TODAY'S behaviour (on).
    motion = raw.get("motion")
    if isinstance(motion, bool):
        result["motion"] = motion
    elif motion is not None:
        _log_dialog(f"theme.motion {motion!r} is not a boolean — keeping the motion on")
    # v1.6 (ROADMAP task 2): the card density — a foreign value is the historical card.
    density = raw.get("density")
    resolved = theme.resolve_density(density)
    if density is not None and resolved != str(density).strip().lower():
        _log_dialog(f"theme.density {density!r} is not one of {theme.DENSITIES} — using 'normal'")
    result["density"] = resolved
    return result


def density_from_settings(settings) -> str:
    """The card density of a stored `theme` dict (v1.6) — a broken value is ``normal``."""
    if isinstance(settings, dict):
        return theme.resolve_density(settings.get("density"))
    return theme.DENSITY_NORMAL


def apply_density_setting(settings) -> str:
    """Install the card density of a `theme` dict into `ui/theme.py` (v1.6).

    The `apply_motion_setting` sibling: the module holds the ACTIVE value (the cards
    read it on every `update_appearance()`), so the settings hub can apply the choice
    live and a rejected dialog can put it back. Returns the value now active; never raises.
    """
    try:
        return theme.set_card_density(density_from_settings(settings))
    except Exception:  # noqa: BLE001 — the switch is cosmetic, never break a startup
        return theme.DENSITY_NORMAL


def motion_from_settings(settings) -> bool:
    """The motion flag of a stored `theme` dict (v1.5rc1) — a broken value is True.

    The ONE reader of the flag for the callers that already hold the dict
    (`main.py`, `MainWindow`, the settings hub); it never raises and never
    returns None.
    """
    if isinstance(settings, dict) and isinstance(settings.get("motion"), bool):
        return settings["motion"]
    return True


def apply_motion_setting(settings) -> bool:
    """Install the motion flag of a `theme` dict into `ui/motion.py` (v1.5rc1).

    Returns the flag that is now active. A missing `ui.motion` (a partial install)
    is not an error: the gestures simply keep their standard behaviour.
    """
    enabled = motion_from_settings(settings)
    try:
        from . import motion
    except ImportError:  # flat launch from the project root
        try:
            import motion  # type: ignore
        except ImportError:
            return enabled
    try:
        return bool(motion.set_motion_enabled(enabled))
    except AttributeError:
        return enabled


def theme_from_settings(settings) -> "theme.Theme":
    """The `Theme` instance of a stored `theme` dict (v1.4.3).

    Never raises and never returns None: the caller gets DARK (or LIGHT) with the
    requested hue, which is exactly what the settings hub writes into the app.
    """
    settings = settings if isinstance(settings, dict) else {}
    hue = theme.hex_hue(settings.get("accent") or theme.accent_hex())
    return theme.theme_for_mode(settings.get("mode"), hue)


class SettingsDialog(QDialog):
    """Settings dialog (hub): 6 tabs, saved to ~/.sshmap/config.json on OK."""

    applied = Signal()           # the config was saved — apply live (MainWindow)
    language_changed = Signal(str)  # the language choice in the "Language" tab (immediately)
    theme_changed = Signal(object)  # v1.4.3: the "Appearance" tab — a Theme instance (immediately)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("settings.title"))
        self.resize(500, 400)

        # v1.4.3 (ROADMAP task 6): the theme the dialog OPENED with. The
        # "Appearance" tab applies live (that is what makes the choice
        # meaningful), so Cancel has to put the application back — otherwise a
        # rejected dialog would still have changed the look of the app.
        self._initial_theme = theme.THEME
        # v1.5rc1: the motion flag the dialog OPENED with — the "Reduce motion"
        # box is live too, so Cancel has to restore it (the theme's own rule).
        self._initial_motion = load_theme_settings()["motion"]
        # v1.6 (ROADMAP task 2): the card density the dialog opened with — the combo is
        # live as well, so `reject()` restores it together with the theme and the motion.
        self._initial_density = load_theme_settings()["density"]
        self._density = self._initial_density

        # ── v1.5rc4 (ROADMAP task 3): the settings search ─────────────────────
        # ONE field above the tabs filters the ROWS and the PAGES by their TRANSLATED
        # labels (the command palette's matching — a plain case-insensitive substring,
        # no new dependency). The index behind it is filled by the tab builders through
        # `_register_search_entry()` / `_register_form_rows()`; a hit switches to its tab
        # and highlights the row, and Enter walks the hits.
        self._search_entries = []     # [{"page", "label", "widgets", "text"}, …]
        self._search_hits = []
        self._search_index = -1

        layout = QVBoxLayout(self)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_t("settings.search.placeholder"))
        self.search_edit.setObjectName("SettingsSearchEdit")
        try:  # Qt >= 6.4 — one click to clear the query
            self.search_edit.setClearButtonEnabled(True)
        except AttributeError:
            pass
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.returnPressed.connect(lambda: self._search_step(+1))
        layout.addWidget(self.search_edit)
        self.search_status_lbl = QLabel("")
        self.search_status_lbl.setObjectName("SettingsSearchStatus")
        self.search_status_lbl.setWordWrap(True)
        self.search_status_lbl.hide()
        layout.addWidget(self.search_status_lbl)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_general_tab()
        self._build_appearance_tab()   # v1.4.3 (ROADMAP task 6)
        self._build_terminal_tab()
        self._build_statuses_tab()
        self._build_autosave_tab()
        self._build_map_tab()
        self._build_hotkeys_tab()   # v1.3.2 (ROADMAP v1.3.2, task 2)
        self._build_language_tab()

        # ── OK/Cancel buttons (OK = saving config.json + the applied signal) ─────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.ok_btn = QPushButton(_t("settings.ok"))
        self.cancel_btn = QPushButton(_t("settings.cancel"))
        self.ok_btn.clicked.connect(self._on_accept)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    # ── v1.5rc4 (ROADMAP task 3): the settings search ──────────────────────────
    # The hub is eight tabs deep and the thing a user wants is a WORD they read in a
    # dialog once. The search therefore indexes the rows the tabs already built (their
    # TRANSLATED labels — the same strings on screen, so a re-worded setting is found by
    # its new name) plus the tab titles, which makes "the whole page" a searchable item
    # of its own. Matching is the command palette's: a case-insensitive substring.
    #
    # The index is built by REGISTRATION while the tabs are constructed
    # (`_register_form_rows()` for a form layout, `_register_search_entry()` for a row
    # that is a layout of its own) — the builders know their rows, so nothing has to be
    # guessed from the widget tree at search time.

    def _register_search_entry(self, page, label_widget, widgets=None, text=None) -> None:
        """Add ONE searchable row of ``page`` to the index.

        ``widgets`` are the pieces that hide/show together (the label and its field).
        A row whose text is empty (a separator line, a button row of its own) is NOT
        indexed: it cannot be searched for, and hiding it would leave a hole the user
        cannot explain.
        """
        if page is None:
            return
        if text is None:
            try:
                text = label_widget.text() if label_widget is not None else ""
            except (RuntimeError, AttributeError):
                text = ""
        text = str(text or "").strip()
        if not text:
            return
        if widgets is None:
            widgets = [label_widget]
        self._search_entries.append({
            "page": page,
            "label": label_widget,
            "widgets": [w for w in widgets if w is not None],
            "text": text,
        })

    def _register_form_rows(self, page, form) -> None:
        """Index every row of a QFormLayout (v1.5rc4, ROADMAP task 3).

        A row is its label + its field; a row whose field is a LAYOUT (the language
        manager's two buttons) contributes all of that layout's widgets. A row added with
        an empty label (the checkbox rows) is named by the CHECKBOX's own text — that is
        the sentence the user reads.
        """
        for index in range(form.rowCount()):
            label_item = form.itemAt(index, QFormLayout.ItemRole.LabelRole)
            field_item = form.itemAt(index, QFormLayout.ItemRole.FieldRole)
            label = label_item.widget() if label_item is not None else None
            widgets = []
            if label is not None:
                widgets.append(label)
            field_widget = None
            if field_item is not None:
                field_widget = field_item.widget()
                if field_widget is None and field_item.layout() is not None:
                    for position in range(field_item.layout().count()):
                        child = field_item.layout().itemAt(position)
                        if child is not None and child.widget() is not None:
                            widgets.append(child.widget())
                elif field_widget is not None:
                    widgets.append(field_widget)
            text = ""
            try:
                text = label.text() if label is not None else ""
            except (RuntimeError, AttributeError):
                text = ""
            if not str(text or "").strip() and field_widget is not None:
                try:
                    text = field_widget.text()   # the checkbox rows: addRow("", box)
                except (RuntimeError, AttributeError):
                    text = ""
            # The field widgets of a layout row are already in `widgets`
            self._register_search_entry(page, label, widgets, text)

    def _on_search_changed(self, text: str):
        """The field changed (v1.5rc4, task 3) — re-filter and jump to the first hit."""
        self._apply_settings_search(text)

    def _apply_settings_search(self, query: str) -> list:
        """Filter the rows/pages by ``query``; returns the hits (the test seam).

        A row matches when its label contains the query; a PAGE matches when its TITLE
        does, and then every row of that page matches (asking for "Terminal" must show the
        whole tab, not nothing). Every hit is highlighted; the first one switches the tab.
        """
        text = str(query or "").strip().lower()
        pages = []
        page_ids = set()
        if text:
            for index in range(self.tabs.count()):
                if text in str(self.tabs.tabText(index) or "").lower():
                    page = self.tabs.widget(index)
                    if page is not None and id(page) not in page_ids:
                        pages.append((page, str(self.tabs.tabText(index))))
                        page_ids.add(id(page))
        # 1. a PAGE that matched by its title is a hit of its own, and it comes FIRST: the
        #    user asking for "Terminal" means the tab, not the one row elsewhere that
        #    happens to contain the word (the v1.5rc4 ordering rule).
        hits = [{"page": page, "label": None, "widgets": [], "text": title, "hit": True}
                for page, title in pages]
        for entry in getattr(self, "_search_entries", []):
            page = entry.get("page")
            if not text:
                match = True
            elif page is not None and id(page) in page_ids:
                match = True
            else:
                match = text in str(entry.get("text") or "").lower()
            for widget in entry.get("widgets") or []:
                try:
                    widget.setVisible(match)
                except RuntimeError:
                    continue  # Qt teardown — this widget is already destroyed
            entry["hit"] = bool(text) and match
            self._set_search_highlight(entry, entry["hit"])
            # 2. the ROW hits of a page that already matched as a whole are not repeated:
            #    the page hit carries the switch, and a duplicate would inflate "k / N".
            if match and text and (page is None or id(page) not in page_ids):
                hits.append(entry)
        self._search_hits = hits
        self._search_index = -1
        self._update_search_status()
        if hits:
            self._search_step(0)   # switch to the first hit's tab
        return hits

    def _set_search_highlight(self, entry, highlighted: bool) -> None:
        """Mark a matching row (bold + the STRONG accent — the v1.5rc1 ink role)."""
        label = entry.get("label") if isinstance(entry, dict) else None
        if label is None:
            return
        try:
            label.setStyleSheet(
                f"color: {theme.ACCENT_STRONG}; font-weight: bold;" if highlighted else "")
        except RuntimeError:
            pass  # Qt teardown — the label is already destroyed

    def _clear_search_highlight(self) -> None:
        """Drop every highlight (the empty query / the release of the dialog)."""
        for entry in getattr(self, "_search_entries", []):
            entry["hit"] = False
            self._set_search_highlight(entry, False)

    def _reapply_search_highlights(self) -> None:
        """Re-colour the CURRENT hits — the theme switch path (no re-filter, no tab jump)."""
        for entry in getattr(self, "_search_entries", []):
            self._set_search_highlight(entry, bool(entry.get("hit")))

    def _search_step(self, step: int):
        """Walk the hits: switch to the next/previous one's tab (wrapping)."""
        hits = getattr(self, "_search_hits", None) or []
        if not hits:
            return None
        if step:
            self._search_index = (self._search_index + int(step)) % len(hits)
        elif self._search_index < 0:
            self._search_index = 0
        entry = hits[self._search_index]
        page = entry.get("page")
        try:
            index = self.tabs.indexOf(page) if page is not None else -1
            if index >= 0:
                self.tabs.setCurrentIndex(index)
        except RuntimeError:
            return None
        self._update_search_status()
        return entry

    def _update_search_status(self):
        """The one-line report under the field: nothing / "k of N" / "no match"."""
        try:
            label = self.search_status_lbl
        except AttributeError:
            return
        query = ""
        try:
            query = self.search_edit.text().strip()
        except RuntimeError:
            return
        if not query:
            label.setText("")
            label.hide()
            return
        hits = getattr(self, "_search_hits", None) or []
        if not hits:
            label.setText(_t("settings.search.none"))
        else:
            # A count, not a sentence: no new key per language for "3 of 5".
            label.setText(f"{self._search_index + 1} / {len(hits)}")
        label.show()

    def search_settings(self, query: str) -> list:
        """Set the query and return the hits as ``[(tab index, label text), …]``.

        The topical test's seam (and what a caller inside the app would use): it drives
        the REAL field, so the filtering, the highlighting and the tab switch are the ones
        a user gets.
        """
        try:
            if self.search_edit.text() != str(query or ""):
                self.search_edit.setText(str(query or ""))
                # setText emits textChanged → the search is already applied
                return self.search_hits()
        except RuntimeError:
            return []
        self._apply_settings_search(query)
        return self.search_hits()

    def search_hits(self) -> list:
        """The current hits as ``[(tab index, label text), …]`` (never raises)."""
        out = []
        for entry in getattr(self, "_search_hits", None) or []:
            page = entry.get("page")
            try:
                index = self.tabs.indexOf(page) if page is not None else -1
            except RuntimeError:
                continue
            out.append((index, str(entry.get("text") or "")))
        return out

    # ── "General" tab (v1.1: external_terminal — a single config.json) ─────────

    def _build_general_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.ext_term_combo = QComboBox()
        choices = (TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                   else TERMINAL_CHOICES_LINUX)
        for tid in choices:
            # i18n preset labels — the existing keys ssh_ext.preset.* (v0.9.9.2)
            self.ext_term_combo.addItem(_t(f"ssh_ext.preset.{tid}"), tid)
        cur = load_external_terminal_setting()
        idx = next((i for i in range(self.ext_term_combo.count())
                    if self.ext_term_combo.itemData(i) == cur), 0)
        self.ext_term_combo.setCurrentIndex(idx)
        self._lbl_ext_term = QLabel(_t("settings.general.external_terminal"))
        form.addRow(self._lbl_ext_term, self.ext_term_combo)

        # v1.1.1 (item 1): the interface font — family + size (pt); applied
        # live without a restart (MainWindow: QApplication.setFont on OK and at startup).
        ui_cfg = load_ui_settings()
        self.ui_font_family_edit = QLineEdit(ui_cfg["font_family"])
        self._lbl_ui_font_family = QLabel(_t("settings.general.ui_font_family"))
        form.addRow(self._lbl_ui_font_family, self.ui_font_family_edit)
        # 0 = the system size (specialValueText); the validator range is 6..72
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(0, 72)
        self.ui_font_size_spin.setValue(ui_cfg["font_size"] or 0)
        self.ui_font_size_spin.setSpecialValueText(_t("settings.ui_font_system"))
        self._lbl_ui_font_size = QLabel(_t("settings.general.ui_font_size"))
        form.addRow(self._lbl_ui_font_size, self.ui_font_size_spin)

        # v1.1.1 (item 5): the sidebar button block — show/hide (the layout
        # reflows itself); the whole sidebar is hidden by a separate "View"
        # menu item (MainWindow).
        self.sidebar_buttons_chk = QCheckBox(_t("settings.general.sidebar_buttons"))
        self.sidebar_buttons_chk.setChecked(ui_cfg["show_sidebar_buttons"])
        form.addRow("", self.sidebar_buttons_chk)

        self._register_form_rows(tab, form)   # v1.5rc4: the searchable rows of this tab
        self.tabs.addTab(tab, _t("settings.tab.general"))

    # ── "Appearance" tab (v1.4.3, ROADMAP task 6): the theme — mode + accent ────

    def _build_appearance_tab(self):
        """The theme of the application: dark/light + the accent hue (v1.4.3).

        LIVE apply without a restart: the hub pattern (the "Language" tab
        precedent) — every control pushes the choice through ``theme_changed``
        immediately, so the user SEES the result while the dialog is open, and
        ``collect()`` writes it to config.json on OK. ``reject()`` restores the
        theme the dialog opened with (a rejected dialog changes nothing).

        The accent is a HUE, not a palette: the swatches and the hex field both
        end up as one hue through ``theme.hex_hue``.
        """
        current = load_theme_settings()
        self._accent_hex = current["accent"]

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ── the mode: dark (default) / light / auto (system) ──────────────────
        # v1.5rc1: the third entry follows the PLATFORM's colour scheme
        # (`theme.resolve_mode`); the live change is the window's half
        # (`MainWindow` listens to `QStyleHints.colorSchemeChanged`).
        mode_row = QHBoxLayout()
        self._lbl_theme_mode = QLabel(_t("settings.appearance.mode"))
        self.theme_mode_combo = QComboBox()
        for mode_id, key in ((theme.MODE_DARK, "settings.appearance.mode.dark"),
                             (theme.MODE_LIGHT, "settings.appearance.mode.light"),
                             (theme.MODE_AUTO, "settings.appearance.mode.auto")):
            self.theme_mode_combo.addItem(_t(key), mode_id)
        idx = next((i for i in range(self.theme_mode_combo.count())
                    if self.theme_mode_combo.itemData(i) == current["mode"]), 0)
        self.theme_mode_combo.setCurrentIndex(idx)
        mode_row.addWidget(self._lbl_theme_mode)
        mode_row.addWidget(self.theme_mode_combo, 1)
        layout.addLayout(mode_row)

        # ── v1.5rc1: the motion switch ("Reduce motion") ──────────────────────
        # Read by `ui/motion.py`: with it off every gesture applies its FINAL
        # state at once. LIVE like the rest of the tab.
        self._motion_enabled = current["motion"]
        self.motion_chk = QCheckBox(_t("settings.appearance.motion"))
        self.motion_chk.setChecked(not self._motion_enabled)
        self.motion_chk.setToolTip(_t("settings.appearance.motion.tooltip"))
        self.motion_chk.toggled.connect(self._on_motion_toggled)
        layout.addWidget(self.motion_chk)

        # ── v1.6 (ROADMAP task 2): the CARD DENSITY ───────────────────────────
        # The second non-colour flag of the nested `theme` object (the motion
        # precedent): `normal` is the historical card, `compact` hides the info
        # plaque and the tag chip of every card on the map. LIVE, like the mode and
        # the motion switch — the cards follow through the ordinary refresh walk.
        density_row = QHBoxLayout()
        self._lbl_theme_density = QLabel(_t("settings.appearance.density"))
        self.density_combo = QComboBox()
        for density_id, key in ((theme.DENSITY_NORMAL, "settings.appearance.density.normal"),
                                (theme.DENSITY_COMPACT, "settings.appearance.density.compact")):
            self.density_combo.addItem(_t(key), density_id)
        _d_idx = next((i for i in range(self.density_combo.count())
                       if self.density_combo.itemData(i) == current["density"]), 0)
        self.density_combo.setCurrentIndex(_d_idx)
        self.density_combo.setToolTip(_t("settings.appearance.density.tooltip"))
        density_row.addWidget(self._lbl_theme_density)
        density_row.addWidget(self.density_combo, 1)
        layout.addLayout(density_row)

        # ── the accent swatches ───────────────────────────────────────────────
        self._lbl_theme_accent = QLabel(_t("settings.appearance.accent"))
        layout.addWidget(self._lbl_theme_accent)
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(4)
        self._swatch_buttons = {}
        for name, hue, hex_value in accent_swatches():
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setToolTip(_t(f"settings.appearance.accent.{name}"))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {hex_value};"
                f" border: 1px solid {theme.SURFACE_ALT}; border-radius: 4px; }}")
            btn.clicked.connect(lambda _checked=False, h=hue: self._on_accent_hue(h))
            swatch_row.addWidget(btn)
            self._swatch_buttons[name] = (btn, hex_value)
        swatch_row.addStretch(1)
        layout.addLayout(swatch_row)

        # ── the user's own colour: a hex field + a colour picker ──────────────
        own_row = QHBoxLayout()
        self._lbl_theme_own = QLabel(_t("settings.appearance.own_color"))
        self.accent_hex_edit = QLineEdit(self._accent_hex)
        self.accent_hex_edit.setMaxLength(7)
        self.accent_hex_edit.setFixedWidth(90)
        self.accent_hex_edit.editingFinished.connect(self._on_accent_hex_edited)
        self.accent_pick_btn = QPushButton(_t("settings.appearance.pick_color"))
        self.accent_pick_btn.clicked.connect(self._on_pick_accent_color)
        own_row.addWidget(self._lbl_theme_own)
        own_row.addWidget(self.accent_hex_edit)
        own_row.addWidget(self.accent_pick_btn)
        own_row.addStretch(1)
        layout.addLayout(own_row)

        self._lbl_theme_hint = QLabel(_t("settings.appearance.hint"))
        self._lbl_theme_hint.setWordWrap(True)
        layout.addWidget(self._lbl_theme_hint)
        layout.addStretch(1)

        # The live application — wired AFTER the initial values are in place
        # (the "Language" tab precedent: otherwise the construction echo would
        # apply the theme onto itself).
        self.theme_mode_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.density_combo.currentIndexChanged.connect(self._on_density_changed)
        self._mark_current_swatch()

        # ── v1.5rc4 (ROADMAP task 3): the searchable rows of this tab ─────────
        # The tab is a QVBoxLayout (not a form), so its rows are registered by hand —
        # the mode row, the motion box, the accent label + its swatches, the user's own
        # colour row and the hint. Each entry names the pieces that hide together.
        self._register_search_entry(tab, self._lbl_theme_mode,
                                    [self._lbl_theme_mode, self.theme_mode_combo])
        self._register_search_entry(tab, self.motion_chk, [self.motion_chk])
        self._register_search_entry(
            tab, self._lbl_theme_density, [self._lbl_theme_density, self.density_combo])
        self._register_search_entry(
            tab, self._lbl_theme_accent,
            [self._lbl_theme_accent] + [btn for btn, _hex in self._swatch_buttons.values()])
        self._register_search_entry(tab, self._lbl_theme_own,
                                    [self._lbl_theme_own, self.accent_hex_edit,
                                     self.accent_pick_btn])
        self._register_search_entry(tab, self._lbl_theme_hint, [self._lbl_theme_hint])

        self.tabs.addTab(tab, _t("settings.tab.appearance"))

    def _mark_current_swatch(self):
        """Frame the swatch that matches the current accent (a visual prefill)."""
        try:
            for _name, (btn, hex_value) in getattr(self, "_swatch_buttons", {}).items():
                selected = hex_value.lower() == (self._accent_hex or "").lower()
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {hex_value};"
                    f" border: 2px solid "
                    f"{theme.TEXT_PRIMARY if selected else theme.SURFACE_ALT};"
                    f" border-radius: 4px; }}")
        except RuntimeError:
            pass  # Qt teardown — a button is already destroyed

    def _current_theme(self):
        """The Theme the tab currently describes (mode + hue)."""
        mode = self.theme_mode_combo.currentData() or theme.MODE_DARK
        return theme.theme_for_mode(mode, theme.hex_hue(self._accent_hex))

    def _on_accent_hue(self, hue):
        """A swatch was clicked: adopt its colour and apply live."""
        self._accent_hex = theme.accent_hex(hue)
        try:
            self.accent_hex_edit.setText(self._accent_hex)
        except RuntimeError:
            return  # Qt teardown
        self._mark_current_swatch()
        self._emit_theme()

    def _on_accent_hex_edited(self):
        """The hex field lost focus: accept a valid colour, otherwise restore."""
        try:
            value = (self.accent_hex_edit.text() or "").strip()
        except RuntimeError:
            return  # Qt teardown
        if theme.is_valid_hex(value):
            self._accent_hex = "#" + value.lstrip("#").lower()
            try:
                self.accent_hex_edit.setText(self._accent_hex)
            except RuntimeError:
                return
            self._mark_current_swatch()
            self._emit_theme()
            return
        # An unusable value is not applied and not kept: the field returns to the
        # last valid colour (a typo must not silently change the theme).
        _log_dialog(f"appearance: {value!r} is not a #rrggbb colour — keeping {self._accent_hex}")
        try:
            self.accent_hex_edit.setText(self._accent_hex)
        except RuntimeError:
            pass

    def _on_pick_accent_color(self):
        """The colour picker — the same value as the hex field, chosen visually."""
        try:
            from PySide6.QtWidgets import QColorDialog
        except Exception:  # noqa: BLE001 — without the dialog the field still works
            return
        try:
            initial = QColor(self._accent_hex)
            chosen = QColorDialog.getColor(initial, self, _t("settings.appearance.pick_color"))
        except Exception as e:  # noqa: BLE001 — a broken picker must not break the tab
            _log_dialog(f"appearance: the colour dialog failed: {e!r}")
            return
        if not chosen.isValid():
            return  # the user cancelled
        self._accent_hex = chosen.name().lower()
        try:
            self.accent_hex_edit.setText(self._accent_hex)
        except RuntimeError:
            return
        self._mark_current_swatch()
        self._emit_theme()

    def _on_theme_changed(self, *_args):
        """The mode combo moved (the accent has its own two slots)."""
        self._mark_current_swatch()
        self._emit_theme()

    def _on_motion_toggled(self, checked):
        """The "Reduce motion" box moved (v1.5rc1) — applied to `ui/motion.py` live.

        The checkbox reads "Reduce motion", so CHECKED means the animations are
        OFF (`motion.set_motion_enabled(not checked)`). Never raises: the switch is
        cosmetic and a missing module must not break the dialog.
        """
        self._motion_enabled = not bool(checked)
        try:
            from . import motion
        except ImportError:  # flat launch from the project root
            try:
                import motion  # type: ignore
            except ImportError:
                return
        try:
            motion.set_motion_enabled(self._motion_enabled)
        except AttributeError:
            pass

    def _emit_theme(self):
        """Push the current choice to the live window (v1.4.3, the "immediately" rule)."""
        try:
            self.theme_changed.emit(self._current_theme())
        except RuntimeError:
            pass  # Qt teardown

    def _on_density_changed(self, *_args):
        """The card-density combo moved (v1.6, ROADMAP task 2) — applied LIVE.

        The density is module state (`theme.set_card_density`) rather than a Theme
        field, so it is installed here and the cards follow through the ordinary
        refresh walk the emitted `theme_changed` triggers (the `_on_motion_toggled`
        pattern, one level down). Never raises: the switch is cosmetic.
        """
        try:
            self._density = self.density_combo.currentData() or theme.DENSITY_NORMAL
        except (AttributeError, RuntimeError):
            return  # Qt teardown / a dialog built without the tab
        try:
            theme.set_card_density(self._density)
        except Exception:  # noqa: BLE001 — a cosmetic switch must not break the dialog
            return
        self._emit_theme()

    # ── "Terminal" tab (v1.0 keys + the new close behavior) ─────────────

    def _build_terminal_tab(self):
        try:
            from ..modules.ssh_terminal import load_terminal_settings
        except ImportError:
            from modules.ssh_terminal import load_terminal_settings
        cfg = load_terminal_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        # v1.2.2 (task 4): the terminal display mode — "windows" (default,
        # current behavior: separate windows) | "tabs" (the "Terminals" dock on the map).
        # Applied without a restart: new sessions go to the chosen mode,
        # open windows/the dock stay as-is until closed.
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(_t("settings.terminal.mode.windows"), "windows")
        self.mode_combo.addItem(_t("settings.terminal.mode.tabs"), "tabs")
        idx = next((i for i in range(self.mode_combo.count())
                    if self.mode_combo.itemData(i) == cfg["mode"]), 0)
        self.mode_combo.setCurrentIndex(idx)
        self._lbl_mode = QLabel(_t("settings.terminal.mode"))
        form.addRow(self._lbl_mode, self.mode_combo)

        self.palette_combo = QComboBox()
        self.palette_combo.addItem(_t("settings.terminal.palette.default"), "default")
        self.palette_combo.addItem(_t("settings.terminal.palette.nord"), "nord")
        self.palette_combo.addItem(_t("settings.terminal.palette.dracula"), "dracula")
        self.palette_combo.addItem(_t("settings.terminal.palette.tokyo_night"), "tokyo_night")
        cur_pal = cfg["palette"] or "default"
        idx = next((i for i in range(self.palette_combo.count())
                    if self.palette_combo.itemData(i) == cur_pal), 0)
        self.palette_combo.setCurrentIndex(idx)
        self._lbl_palette = QLabel(_t("settings.terminal.palette"))
        form.addRow(self._lbl_palette, self.palette_combo)

        # v1.1.1 (item 1): the terminal font family (monospace); empty —
        # the system monospace. The terminal_font key was read since v1.0,
        # the UI appears for the first time; live application — to open
        # windows (MainWindow on OK).
        self.term_font_family_edit = QLineEdit(cfg["font_family"])
        self._lbl_term_font_family = QLabel(_t("settings.terminal.font_family"))
        form.addRow(self._lbl_term_font_family, self.term_font_family_edit)

        # Font size: the same validator range (6–72 pt), default 10
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 72)
        self.font_size_spin.setValue(cfg["font_size"] or 10)
        self._lbl_font_size = QLabel(_t("settings.terminal.font_size"))
        form.addRow(self._lbl_font_size, self.font_size_spin)

        # v1.1.1 (item 3): the limit of own open terminals — when reached,
        # not a refusal but an offer to close the oldest session
        # (MainWindow._spawn_terminal_window).
        # v1.3.3.8 (ROADMAP task 3): the spin follows the VALIDATOR (1..32 in
        # load_terminal_settings) instead of the old 1..16. That was a bug, not only
        # a narrower range: a saved 20 was DISPLAYED as 16 and an OK wrote 16 back,
        # silently lowering a valid value. The two limits are ONE limit now, pinned
        # by tests/test_language_folder.py.
        self.max_open_spin = QSpinBox()
        self.max_open_spin.setRange(1, 32)
        self.max_open_spin.setValue(cfg["max_open"])
        self._lbl_max_open = QLabel(_t("settings.terminal.max_open"))
        form.addRow(self._lbl_max_open, self.max_open_spin)

        # History depth: the validator range (0 = scrollback disabled)
        self.history_spin = QSpinBox()
        self.history_spin.setRange(0, 1_000_000)
        self.history_spin.setValue(cfg["history_lines"])
        self._lbl_history = QLabel(_t("settings.terminal.history_lines"))
        form.addRow(self._lbl_history, self.history_spin)

        # v1.1 (task 3): the session close behavior — a new key
        self.close_behavior_combo = QComboBox()
        self.close_behavior_combo.addItem(
            _t("settings.terminal.close_behavior.close"), "close")
        self.close_behavior_combo.addItem(
            _t("settings.terminal.close_behavior.ask"), "ask")
        idx = next((i for i in range(self.close_behavior_combo.count())
                    if self.close_behavior_combo.itemData(i) == cfg["close_behavior"]), 0)
        self.close_behavior_combo.setCurrentIndex(idx)
        self._lbl_close_behavior = QLabel(_t("settings.terminal.close_behavior"))
        form.addRow(self._lbl_close_behavior, self.close_behavior_combo)

        # v1.3.3.8 (ROADMAP task 4): the mouse wheel — the LAST key that had no UI at
        # all (documented as deliberate in v1.1.2RC3 and never revisited). "scrollback"
        # (default) = the wheel scrolls the local scrollback; "off" = the wheel is not
        # intercepted, only the full SGR/X10 passthrough of a mouse-tracking TUI is
        # left (widget._wheel_mode — modules/terminal_widget.py). The page/window reads
        # the key on creation exactly as before: only the UI is new.
        self.wheel_combo = QComboBox()
        self.wheel_combo.addItem(_t("settings.terminal.wheel.scrollback"), "scrollback")
        self.wheel_combo.addItem(_t("settings.terminal.wheel.off"), "off")
        idx = next((i for i in range(self.wheel_combo.count())
                    if self.wheel_combo.itemData(i) == cfg["wheel"]), 0)
        self.wheel_combo.setCurrentIndex(idx)
        self._lbl_wheel = QLabel(_t("settings.terminal.wheel"))
        form.addRow(self._lbl_wheel, self.wheel_combo)

        # v1.6.2 (ROADMAP task 4): the cursor SHAPE — the first new UI-facing key since
        # terminal_wheel. "bar" (the DEFAULT: the thin blinking line of Windows Terminal) |
        # "block" (the historical full-cell slab) | "underline". The canvas reads the key on
        # session creation (load_terminal_settings → TerminalWidget(cursor_style=…)) and the
        # window re-applies it to the OPEN sessions on OK, exactly like the font.
        self.cursor_combo = QComboBox()
        self.cursor_combo.addItem(_t("settings.terminal.cursor.bar"), "bar")
        self.cursor_combo.addItem(_t("settings.terminal.cursor.block"), "block")
        self.cursor_combo.addItem(_t("settings.terminal.cursor.underline"), "underline")
        idx = next((i for i in range(self.cursor_combo.count())
                    if self.cursor_combo.itemData(i) == cfg["cursor"]), 0)
        self.cursor_combo.setCurrentIndex(idx)
        self._lbl_cursor = QLabel(_t("settings.terminal.cursor"))
        form.addRow(self._lbl_cursor, self.cursor_combo)

        self._register_form_rows(tab, form)   # v1.5rc4: the searchable rows of this tab
        self.tabs.addTab(tab, _t("settings.tab.terminal"))

    # ── "Statuses" tab (the StatusChecker probe interval + timeout) ─────────────

    def _build_statuses_tab(self):
        try:
            from ..services.status_checker import (
                get_status_settings, MAX_PARALLEL_LIMIT as _MPL,
                MANUAL_INTERVAL_SEC as _MANUAL_SEC)
        except ImportError:
            from services.status_checker import (
                get_status_settings, MAX_PARALLEL_LIMIT as _MPL,
                MANUAL_INTERVAL_SEC as _MANUAL_SEC)
        st = get_status_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        # v1.6.6 (ROADMAP task 3): the THIRD state of the cadence. The checkbox owns the visible
        # state and the `status_interval_sec = 0` SENTINEL is what `collect()` writes for it, so
        # one setting keeps one home; the interval spinbox beside it is DISABLED but REMEMBERED
        # (never zeroed), so un-ticking the box gives the user their number back. The row is a
        # VIEW of the state — the checker is its owner (`set_manual_only()`, applied live by
        # `MainWindow._apply_settings_from_dialog()`).
        self.manual_only_chk = QCheckBox(_t("settings.statuses.manual_only"))
        self.manual_only_chk.setChecked(bool(st["manual"]))
        self.manual_only_chk.toggled.connect(self._on_manual_only_toggled)
        form.addRow("", self.manual_only_chk)

        self.status_interval_spin = QSpinBox()
        self.status_interval_spin.setRange(5, 3600)
        self.status_interval_spin.setValue(
            st["interval_sec"] if st["interval_sec"] > 0 else 30)
        self._lbl_status_interval = QLabel(_t("settings.statuses.interval"))
        form.addRow(self._lbl_status_interval, self.status_interval_spin)

        # The sentence that spells out what "manual only" MEANS — shown with the state, because
        # a green card that was true yesterday is exactly the failure the mode may not ship with.
        self.manual_only_hint = QLabel(_t("settings.statuses.manual_only.hint"))
        self.manual_only_hint.setWordWrap(True)
        self.manual_only_hint.setVisible(bool(st["manual"]))
        form.addRow("", self.manual_only_hint)
        self._manual_interval_sec = _MANUAL_SEC

        self.probe_timeout_spin = QDoubleSpinBox()
        self.probe_timeout_spin.setRange(0.2, 60.0)
        self.probe_timeout_spin.setDecimals(1)
        self.probe_timeout_spin.setValue(st["probe_timeout_sec"])
        self._lbl_probe_timeout = QLabel(_t("settings.statuses.timeout"))
        form.addRow(self._lbl_probe_timeout, self.probe_timeout_spin)

        # v1.1.2 final (task 2): the cap on parallel probes per round —
        # status_max_parallel (default 16; range = the clamp of get_status_settings).
        self.max_parallel_spin = QSpinBox()
        self.max_parallel_spin.setRange(1, _MPL)
        self.max_parallel_spin.setValue(st["max_parallel"])
        self._lbl_max_parallel = QLabel(_t("settings.statuses.max_parallel"))
        form.addRow(self._lbl_max_parallel, self.max_parallel_spin)

        # The state of the widgets follows the checkbox BEFORE anything can read them.
        self._on_manual_only_toggled(bool(st["manual"]))

        self._register_form_rows(tab, form)   # v1.5rc4: the searchable rows of this tab
        self.tabs.addTab(tab, _t("settings.tab.statuses"))

    def _on_manual_only_toggled(self, checked: bool) -> None:
        """v1.6.6 (ROADMAP task 3): the manual-only row follows its checkbox.

        The interval spinbox is DISABLED and keeps its value (the user's number is remembered,
        not zeroed — the sentinel is written by `collect()`, never by the spinbox), and the
        sentence explaining what the mode means appears with it. A torn-down Qt object is a
        silent no-op.
        """
        checked = bool(checked)
        try:
            self.status_interval_spin.setEnabled(not checked)
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed
        hint = getattr(self, "manual_only_hint", None)
        if hint is not None:
            try:
                hint.setVisible(checked)
            except RuntimeError:
                pass


    # ── "Autosave" tab (v0.9.7 keys) ────────────────────────────────

    def _build_autosave_tab(self):
        try:
            from ..storage.autosave import get_autosave_settings
        except ImportError:
            from storage.autosave import get_autosave_settings
        as_cfg = get_autosave_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        self.autosave_enabled_chk = QCheckBox(_t("settings.autosave.enabled"))
        self.autosave_enabled_chk.setChecked(as_cfg["enabled"])
        form.addRow("", self.autosave_enabled_chk)

        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setRange(5, 86400)
        self.autosave_interval_spin.setValue(as_cfg["interval_sec"])
        self._lbl_autosave_interval = QLabel(_t("settings.autosave.interval"))
        form.addRow(self._lbl_autosave_interval, self.autosave_interval_spin)

        self.backup_count_spin = QSpinBox()
        self.backup_count_spin.setRange(1, 100)
        self.backup_count_spin.setValue(as_cfg["backup_count"])
        self._lbl_backup_count = QLabel(_t("settings.autosave.backups"))
        form.addRow(self._lbl_backup_count, self.backup_count_spin)

        self._register_form_rows(tab, form)   # v1.5rc4: the searchable rows of this tab
        self.tabs.addTab(tab, _t("settings.tab.autosave"))

    # ── "Map" tab (v1.1.1: map options — node double click, connection plaque) ─

    def _build_map_tab(self):
        ui_cfg = load_ui_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        # v1.1.1 (item 4): double click on a node — properties (default,
        # v1.1 behavior) or straight to the SSH login dialog (_run_ssh_connect).
        # The "Connect via SSH" checkbox in properties is not broken — the
        # new mode merely duplicates it faster.
        self.node_dblclick_combo = QComboBox()
        self.node_dblclick_combo.addItem(
            _t("settings.map.node_double_click.properties"), "properties")
        self.node_dblclick_combo.addItem(
            _t("settings.map.node_double_click.connect"), "connect")
        idx = next((i for i in range(self.node_dblclick_combo.count())
                    if self.node_dblclick_combo.itemData(i) == ui_cfg["node_double_click"]), 0)
        self.node_dblclick_combo.setCurrentIndex(idx)
        self._lbl_node_dblclick = QLabel(_t("settings.map.node_double_click"))
        form.addRow(self._lbl_node_dblclick, self.node_dblclick_combo)

        # v1.1.1 (item 6): the connection type on the plaque ("SSH · <label>") —
        # handy for PNG/PDF export, where color is less visible; off by default.
        self.show_conn_type_chk = QCheckBox(_t("settings.map.show_connection_type"))
        self.show_conn_type_chk.setChecked(ui_cfg["show_connection_type"])
        form.addRow("", self.show_conn_type_chk)

        self._register_form_rows(tab, form)   # v1.5rc4: the searchable rows of this tab
        self.tabs.addTab(tab, _t("settings.tab.map"))

    # ── "Hotkeys" tab (v1.3.2: the configurable hotkeys — the action registry) ──────

    def _build_hotkeys_tab(self):
        """v1.3.2 (ROADMAP task 2): a table [action | hotkey] over the action registry.

        The action's NAME reuses the existing menu i18n key (no new strings for the list
        itself). An EMPTY sequence = the hotkey is disabled, the action stays available
        from the menu. Two actions with the same sequence are BOTH marked + the warning
        label appears — saving is still possible (Qt resolves the ambiguity at runtime,
        and the user may be mid-edit).

        v1.3.3.3 (ROADMAP task 3/4): the registry grew, most of its actions with an
        EMPTY default (assignable, no hotkey out of the box), so "clearing a field is the
        documented way" stops being a reasonable answer to "I want the defaults back" —
        the "Reset to defaults" button (`_on_reset_hotkeys`) restores every registry
        default through the same merge-write.

        v1.5rc4 (ROADMAP task 4): the tab became NAVIGABLE — the plan's own words:
          * a **filter field** above the table (by the action's name OR its current
            sequence, so "ctrl+s" finds "Save" too);
          * **grouping by family** — a caption row per family (File / Edit / View / Node /
            Plugins / Help) and the registry's declaration order INSIDE it. The spine is
            `hotkey_registry.actions_by_family()`, so the registry stays the only source of
            the list and a new action joins its family by being named `<family>.*`;
          * a **header with the counts** ("with a key" vs "assignable") that follows every
            edit, and a **hint on assigning a key** next to the older "clear it to disable"
            one.
        The table still owns ONE QKeySequenceEdit per action (`self.hotkey_edits`), and
        `hotkey_row()` / `hotkey_action_rows()` are the public way to find a row — the
        caption rows shifted the arithmetic, so no caller should count rows by hand.
        """
        try:
            from ui.hotkey_registry import (
                action_ids, action_label_key, configured_hotkeys,
                actions_by_family, family_order, family_label_key,
            )
        except ImportError:  # flat launch from the project root
            from hotkey_registry import (
                action_ids, action_label_key, configured_hotkeys,
                actions_by_family, family_order, family_label_key,
            )
        # The registry/worker import path is fixed by the module, not by the dialog:
        # _apply_settings_from_dialog() in MainWindow does the actual installation.
        self._hotkey_ids = list(action_ids())
        current = configured_hotkeys()
        self._hotkeys_by_family = actions_by_family(self._hotkey_ids)

        tab = QWidget()
        layout = QVBoxLayout(tab)

        # v1.5rc4 (task 4): the filter field — the settings search of the hub (task 3) is
        # a search over the SETTINGS, this one narrows one long table.
        self.hotkeys_filter = QLineEdit()
        self.hotkeys_filter.setObjectName("HotkeysFilterEdit")
        self.hotkeys_filter.setPlaceholderText(_t("settings.hotkeys.filter"))
        try:  # Qt >= 6.4 — one click to clear the query
            self.hotkeys_filter.setClearButtonEnabled(True)
        except AttributeError:
            pass
        self.hotkeys_filter.textChanged.connect(self._on_hotkeys_filter_changed)
        layout.addWidget(self.hotkeys_filter)

        # v1.5rc4 (task 4): the counts header — how many actions have a key right now and
        # how many are still assignable. Read from the LIVE table (not from the registry),
        # so it answers the same question the user is looking at.
        self._lbl_hotkeys_counts = QLabel("")
        self._lbl_hotkeys_counts.setObjectName("HotkeysCountsLabel")
        self._lbl_hotkeys_counts.setWordWrap(True)
        layout.addWidget(self._lbl_hotkeys_counts)

        # v1.5rc4 (task 4): the row plan — a caption per family, its actions under it.
        self._hotkey_rows = []
        for family in family_order():
            ids = list(self._hotkeys_by_family.get(family) or [])
            if not ids:
                continue
            self._hotkey_rows.append(("family", family))
            for action_id in ids:
                self._hotkey_rows.append(("action", action_id))

        self.hotkeys_table = QTableWidget(len(self._hotkey_rows), 2, tab)
        self.hotkeys_table.setHorizontalHeaderLabels(
            [_t("settings.hotkeys.action"), _t("settings.hotkeys.sequence")])
        self.hotkeys_table.verticalHeader().setVisible(False)
        self.hotkeys_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hotkeys_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.hotkeys_table.setShowGrid(False)
        header = self.hotkeys_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.hotkey_edits = {}
        self._hotkey_row_of = {}
        for row, (kind, value) in enumerate(self._hotkey_rows):
            if kind == "family":
                item = QTableWidgetItem(_t(family_label_key(value)))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QColor(theme.TEXT_MUTED))
                # A caption is not an action: it cannot be selected and its two columns
                # are ONE cell (no half-empty "hotkey" column behind the caption).
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.hotkeys_table.setItem(row, 0, item)
                self.hotkeys_table.setSpan(row, 0, 1, 2)
                continue
            item = QTableWidgetItem(_t(action_label_key(value)))
            self.hotkeys_table.setItem(row, 0, item)
            edit = QKeySequenceEdit(QKeySequence(current.get(value, "")), self.hotkeys_table)
            try:  # Qt >= 6.4: the built-in "clear" button — one click to disable a hotkey
                edit.setClearButtonEnabled(True)
            except AttributeError:
                pass
            # keySequenceChanged carries the new QKeySequence; the slot ignores it and
            # re-reads every editor (the conflict set is global, one edit can clear it).
            edit.keySequenceChanged.connect(self._on_hotkey_changed)
            self.hotkeys_table.setCellWidget(row, 1, edit)
            self.hotkey_edits[value] = edit
            self._hotkey_row_of[value] = row

        self._lbl_hotkeys_disabled_hint = QLabel(_t("settings.hotkeys.disabled_hint"))
        self._lbl_hotkeys_disabled_hint.setWordWrap(True)
        # v1.5rc4 (task 4): "what do I do with a row?" — the assignment itself.
        self._lbl_hotkeys_assign_hint = QLabel(_t("settings.hotkeys.assign_hint"))
        self._lbl_hotkeys_assign_hint.setWordWrap(True)
        self._lbl_hotkeys_conflict = QLabel("")
        self._lbl_hotkeys_conflict.setWordWrap(True)

        layout.addWidget(self.hotkeys_table, 1)
        layout.addWidget(self._lbl_hotkeys_disabled_hint)
        layout.addWidget(self._lbl_hotkeys_assign_hint)
        # v1.3.3.3 (task 4): "Reset to defaults" — right-aligned under the hint; the
        # action is idempotent (a second click writes the very same mapping).
        _reset_row = QHBoxLayout()
        _reset_row.addStretch(1)
        self.reset_hotkeys_btn = QPushButton(_t("settings.hotkeys.reset"))
        self.reset_hotkeys_btn.clicked.connect(self._on_reset_hotkeys)
        _reset_row.addWidget(self.reset_hotkeys_btn)
        layout.addLayout(_reset_row)
        layout.addWidget(self._lbl_hotkeys_conflict)

        # v1.5rc4 (task 3): the page is searchable by the settings search too — the hint
        # row is its searchable label (the family captions and the table are the content
        # the hit reveals, not rows of their own). Without it a search for the TAB TITLE
        # would find "somewhere else" and this page would look like a dead end.
        self._register_search_entry(tab, self._lbl_hotkeys_assign_hint,
                                    [self.hotkeys_filter, self._lbl_hotkeys_counts,
                                     self.hotkeys_table, self._lbl_hotkeys_disabled_hint,
                                     self._lbl_hotkeys_assign_hint])

        self.tabs.addTab(tab, _t("settings.tab.hotkeys"))
        self._refresh_hotkey_conflicts()   # the saved config itself may already conflict

    # ── v1.5rc4 (ROADMAP task 4): querying and filtering the hotkey table ───────

    def hotkey_row(self, action_id: str) -> int:
        """The table row of an action (-1 — unknown) — the caption rows shifted them."""
        return int(getattr(self, "_hotkey_row_of", {}).get(action_id, -1))

    def hotkey_action_rows(self) -> list:
        """The rows that hold an ACTION, in table order (the caption rows excluded)."""
        return [row for row, (kind, _value) in enumerate(getattr(self, "_hotkey_rows", []))
                if kind == "action"]

    def hotkey_family_rows(self) -> list:
        """The rows that hold a FAMILY caption, in table order."""
        return [row for row, (kind, _value) in enumerate(getattr(self, "_hotkey_rows", []))
                if kind == "family"]

    def hotkeys_visible_ids(self) -> list:
        """The action ids the filter currently shows (table order)."""
        out = []
        for row, (kind, value) in enumerate(getattr(self, "_hotkey_rows", [])):
            if kind != "action":
                continue
            try:
                if not self.hotkeys_table.isRowHidden(row):
                    out.append(value)
            except RuntimeError:
                continue  # Qt teardown — the table is already destroyed
        return out

    def _on_hotkeys_filter_changed(self, text: str):
        """The filter field changed — narrow the table (v1.5rc4, task 4)."""
        self._apply_hotkeys_filter(text)

    def _apply_hotkeys_filter(self, query: str) -> list:
        """Hide the rows that do not match; hide a family caption with no visible action.

        The query is matched against the action's TRANSLATED name and against its CURRENT
        sequence (the QKeySequenceEdit's text), so both "save" and "ctrl+s" find the row.
        An empty query shows everything — the grouping, not the filter, is the default.
        Returns the visible action ids.
        """
        text = str(query or "").strip().lower()
        visible_by_family = {}
        for row, (kind, value) in enumerate(getattr(self, "_hotkey_rows", [])):
            if kind == "family":
                continue
            match = True
            if text:
                edit = getattr(self, "hotkey_edits", {}).get(value)
                sequence = ""
                if edit is not None:
                    try:
                        sequence = edit.keySequence().toString()
                    except RuntimeError:
                        sequence = ""
                match = text in self._hotkey_label(value).lower() or text in sequence.lower()
            try:
                self.hotkeys_table.setRowHidden(row, not match)
            except RuntimeError:
                continue  # Qt teardown — the table is already destroyed
            if match:
                visible_by_family[value] = True
        for row, (kind, value) in enumerate(getattr(self, "_hotkey_rows", [])):
            if kind != "family":
                continue
            ids = list(self._hotkeys_by_family.get(value) or [])
            shown = any(visible_by_family.get(aid) for aid in ids)
            try:
                self.hotkeys_table.setRowHidden(row, not shown)
            except RuntimeError:
                continue
        self._update_hotkey_counts()
        return self.hotkeys_visible_ids()

    def filter_hotkeys(self, query: str) -> list:
        """Set the filter through the REAL field and return the visible action ids."""
        try:
            if self.hotkeys_filter.text() != str(query or ""):
                self.hotkeys_filter.setText(str(query or ""))
                return self.hotkeys_visible_ids()
        except RuntimeError:
            return []
        return self._apply_hotkeys_filter(query)

    @staticmethod
    def _hotkey_label(action_id: str) -> str:
        """The translated name of an action ("" — a stripped build without the registry)."""
        try:
            try:
                from ui.hotkey_registry import action_label_key
            except ImportError:
                from hotkey_registry import action_label_key
            key = action_label_key(action_id)
        except Exception:  # noqa: BLE001 — a broken registry must not break the tab
            return str(action_id)
        return _t(key) if key else str(action_id)

    def _retranslate_hotkey_families(self):
        """Re-text the family captions of the hotkey table (v1.5rc4, task 4)."""
        try:
            try:
                from ui.hotkey_registry import family_label_key
            except ImportError:
                from hotkey_registry import family_label_key
        except Exception:  # noqa: BLE001 — a broken registry leaves the captions as they are
            return
        for row in self.hotkey_family_rows():
            try:
                item = self.hotkeys_table.item(row, 0)
            except RuntimeError:
                return  # Qt teardown — the table is already destroyed
            if item is None:
                continue
            family = self._hotkey_rows[row][1]
            item.setText(_t(family_label_key(family)))
            # The caption's tone is a VALUE (a QColor handed to the item) — read live so a
            # theme switch repaints it through `refresh_theme()`.
            item.setForeground(QColor(theme.TEXT_MUTED))

    def _update_hotkey_counts(self):
        """Re-read the counts header from the live table (v1.5rc4, task 4)."""
        label = getattr(self, "_lbl_hotkeys_counts", None)
        if label is None:
            return
        sequences = self.hotkey_sequences()
        with_key = sum(1 for value in sequences.values() if str(value or "").strip())
        assignable = max(len(sequences) - with_key, 0)
        try:
            label.setText(_t("settings.hotkeys.counts",
                             with_key=with_key, assignable=assignable))
        except RuntimeError:
            pass  # Qt teardown — the label is already destroyed

    def hotkey_sequences(self) -> dict:
        """The table's current values: {action_id: sequence string} ("" = disabled)."""
        return {aid: edit.keySequence().toString()
                for aid, edit in getattr(self, "hotkey_edits", {}).items()}

    def _on_reset_hotkeys(self):
        """v1.3.3.3 (task 4): restore every registry default in the table AND on disk.

        The mapping comes from the registry (``default_hotkeys``) — no default is
        duplicated here, so a new action in ``ui/hotkey_registry.py`` is reset for free.
        It goes through the ordinary merge-write (``save_hotkeys`` → ``i18n.save_config``),
        which is what keeps the FOREIGN keys of ``config.json`` (language, fonts, …)
        untouched; an unknown id in the stored config stays ignored (the v1.3.2 rule
        lives in the registry, not here).

        The write is deliberate — the button says what it does, and the table already
        showed the current values; the ``applied`` signal then reinstalls the sequences
        on the live window without a restart. Idempotent: a second click writes the same
        bytes. Never raises.
        """
        try:
            try:
                from ui.hotkey_registry import default_hotkeys, save_hotkeys
            except ImportError:
                from hotkey_registry import default_hotkeys, save_hotkeys
            defaults = default_hotkeys()
        except Exception as e:  # noqa: BLE001 — a broken registry must not break the tab
            _log_dialog(f"hotkey reset: registry unavailable: {e!r}")
            return
        for action_id, edit in getattr(self, "hotkey_edits", {}).items():
            try:
                edit.setKeySequence(QKeySequence(defaults.get(action_id, "")))
            except RuntimeError:
                continue  # Qt teardown — this editor is already destroyed
        self._refresh_hotkey_conflicts()
        try:
            ok = bool(save_hotkeys(defaults))
        except Exception as e:  # noqa: BLE001 — saving must not break the dialog
            _log_dialog(f"hotkey reset: save failed: {e!r}")
            ok = False
        if ok:
            self.applied.emit()   # the live window follows without a restart
        try:
            self._lbl_hotkeys_conflict.setText(
                _t("settings.hotkeys.reset_done") if ok else _t("msg.save_failed", error="config.json"))
        except RuntimeError:
            pass  # Qt teardown — the label is already destroyed

    def _on_hotkey_changed(self, *_args):
        """A QKeySequenceEdit changed — re-evaluate the conflicts (both rows are marked)."""
        self._refresh_hotkey_conflicts()

    def _refresh_hotkey_conflicts(self):
        """Mark the conflicting rows + show/hide the warning. Never raises.

        v1.5rc4 (ROADMAP task 4): the walk follows the ROW PLAN (`_hotkey_rows`) — a family
        caption is re-texted from the registry and never marked with "⚠", and the counts
        header is refreshed in the same pass (it reads the live editors, so every edit
        that reaches this method also updates "with a key" vs "assignable").
        """
        try:
            try:
                from ui.hotkey_registry import action_label_key, find_conflicts
            except ImportError:
                from hotkey_registry import action_label_key, find_conflicts
            conflicts = find_conflicts(self.hotkey_sequences())
        except Exception:  # noqa: BLE001 — the marking is cosmetic
            return
        self._update_hotkey_counts()
        try:
            for row, (kind, value) in enumerate(getattr(self, "_hotkey_rows", [])):
                item = self.hotkeys_table.item(row, 0)
                if item is None:
                    continue
                if kind == "family":
                    continue   # a caption carries no sequence and can never conflict
                marked = value in conflicts
                label = _t(action_label_key(value))
                item.setText(("\u26a0 " if marked else "") + label)
                item.setForeground(QColor(theme.STATUS_WARN if marked else theme.TEXT_PRIMARY))
            self._lbl_hotkeys_conflict.setText(
                _t("settings.hotkeys.conflict") if conflicts else "")
        except RuntimeError:
            pass  # Qt teardown — the table is already destroyed

    # ── "Language" tab (immediate application — before OK) ────────────────────────

    def _build_language_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.language_combo = QComboBox()
        try:
            from i18n import get_available_languages, get_current_language
            for lg in get_available_languages():
                self.language_combo.addItem(lg["name"], lg["code"])
            cur = get_current_language()
        except Exception:  # noqa: BLE001 — without i18n the combo is not built
            cur = ""
        idx = next((i for i in range(self.language_combo.count())
                    if self.language_combo.itemData(i) == cur), 0)
        self.language_combo.setCurrentIndex(idx)
        # Immediate application — AFTER setting the initial index (otherwise the
        # currentIndexChanged echo at construction time would switch the
        # language onto itself).
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._lbl_language = QLabel(_t("settings.language.label"))
        form.addRow(self._lbl_language, self.language_combo)

        # v1.3.3.8 (ROADMAP task 2): the language manager — IMPORT / EXPORT only
        # (a language EDITOR inside the app is deliberately NOT in this version: the
        # file stays the user's to edit in any text editor). The buttons copy a file
        # into ~/.sshmap/languages/ (the user folder, created on demand) and back out;
        # the result is reported in the label below them.
        lang_btns = QHBoxLayout()
        self.import_lang_btn = QPushButton(_t("language.import"))
        self.export_lang_btn = QPushButton(_t("language.export"))
        self.import_lang_btn.clicked.connect(self._on_import_language)
        self.export_lang_btn.clicked.connect(self._on_export_language)
        lang_btns.addWidget(self.import_lang_btn)
        lang_btns.addWidget(self.export_lang_btn)
        lang_btns.addStretch(1)
        form.addRow("", lang_btns)
        self.lang_status_lbl = QLabel("")
        self.lang_status_lbl.setWordWrap(True)
        form.addRow("", self.lang_status_lbl)

        self._register_form_rows(tab, form)   # v1.5rc4: the searchable rows of this tab
        self.tabs.addTab(tab, _t("settings.tab.language"))

    def _set_language_status(self, text: str):
        """The report line of the language manager (v1.3.3.8). Never raises."""
        try:
            self.lang_status_lbl.setText(text)
        except RuntimeError:
            pass  # Qt teardown — the label is already destroyed

    def _on_import_language(self):
        """v1.3.3.8 (ROADMAP task 2): "Import a language file…".

        Validate + copy the chosen `.json` into `~/.sshmap/languages/`
        (`i18n.import_language_file()` does the validation and the atomic write — a
        broken / non-JSON / key-less file never reaches the folder), report the key
        count (plus the English-fallback note for an incomplete file, which is
        imported with `"partial": true`) and make the imported language ACTIVE
        immediately. Never raises.
        """
        try:
            from i18n import import_language_file
        except Exception as e:  # noqa: BLE001 — a broken i18n must not break the tab
            self._set_language_status(_t("language.import_failed", error=str(e)))
            return
        try:
            path, _selected = QFileDialog.getOpenFileName(
                self, _t("language.import"), "", "JSON (*.json);;All files (*)")
        except Exception as e:  # noqa: BLE001
            _log_dialog(f"language import: file dialog failed: {e!r}")
            return
        if not path:
            return  # the user cancelled — nothing to report
        try:
            result = import_language_file(path)
        except Exception as e:  # noqa: BLE001 — the report must survive any failure
            _log_dialog(f"language import failed: {e!r}")
            result = {"ok": False, "error": str(e)}
        if not result.get("ok"):
            self._set_language_status(
                _t("language.import_failed", error=_import_error_detail(str(result.get("error") or ""))))
            return
        message = _t("language.imported", name=result["name"], keys=result["keys"])
        if result.get("missing"):
            message += " " + _t("language.incomplete_warning", keys=result["missing"])
        self._set_language_status(message)
        # The list CHANGED (a new code) or the NAME of an existing one did (shadowing)
        # — a forced rebuild is what makes both visible; then activate the language.
        self._refresh_language_combo(force=True)
        self._activate_language(result["code"])

    def _on_export_language(self):
        """v1.3.3.8 (ROADMAP task 2): "Export the current language…".

        Writes the file that WINS for the ACTIVE language (`i18n.export_language_file`)
        — or the `en` template when the active file is unavailable — to a path the
        user chooses, and reports it. The default file name is the language code, so
        an exported file imports back under the same code. Never raises.
        """
        try:
            from i18n import export_language_file, get_current_language
            code = get_current_language()
        except Exception as e:  # noqa: BLE001
            _log_dialog(f"language export: i18n unavailable: {e!r}")
            self._set_language_status(_t("language.import_failed", error=str(e)))
            return
        default_name = f"{code or 'en'}.json"
        try:
            path, _selected = QFileDialog.getSaveFileName(
                self, _t("language.export"), default_name, "JSON (*.json);;All files (*)")
        except Exception as e:  # noqa: BLE001
            _log_dialog(f"language export: file dialog failed: {e!r}")
            return
        if not path:
            return  # the user cancelled
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            result = export_language_file(code, path)
        except Exception as e:  # noqa: BLE001 — the report must survive any failure
            _log_dialog(f"language export failed: {e!r}")
            result = {"ok": False, "error": str(e)}
        if not result.get("ok"):
            reason = str(result.get("error") or "")
            detail = _EXPORT_ERROR_DETAIL.get(reason, reason or "unknown error")
            self._set_language_status(_t("language.import_failed", error=detail))
            return
        self._set_language_status(_t("language.exported", path=result["path"]))

    def _activate_language(self, code: str):
        """Select `code` in the combo and APPLY it (v1.3.3.8).

        The ordinary path is `setCurrentIndex` → `currentIndexChanged` →
        `_on_language_changed` (the immediate application of the tab). When the combo
        already sits on that code — the import SHADOWED the active language — no
        signal would fire, so the slot is called directly: the point of that case is
        precisely to re-read the freshly copied file. Never raises.
        """
        combo = getattr(self, "language_combo", None)
        if combo is None or not code:
            return
        try:
            idx = combo.findData(code)
            if idx < 0:
                return
            if idx == combo.currentIndex():
                self._on_language_changed(idx)
            else:
                combo.setCurrentIndex(idx)
        except RuntimeError:
            pass  # Qt teardown — the combo is already destroyed

    def _refresh_language_combo(self, force: bool = False):
        """v1.3.3.1 (ROADMAP task 3): re-read the discovered languages at dialog open.

        The combo was built once at dialog construction; a language file dropped into
        `i18n/` (or into the user folder since v1.3.3.8) afterwards must not need a
        restart — `showEvent` calls this. The current language is preselected, so the
        refresh does not fire `currentIndexChanged` for the already active language.
        `force=True` (the import path) rebuilds even when the code list is unchanged,
        because a SHADOWING import changes the displayed NAME of an existing code.
        Never raises.
        """
        combo = getattr(self, "language_combo", None)
        if combo is None:
            return
        try:
            from i18n import get_available_languages, get_current_language
            langs = get_available_languages()
            cur = get_current_language()
        except Exception:  # noqa: BLE001 — a broken i18n leaves the combo as it is
            return
        try:
            if not force and [combo.itemData(i) for i in range(combo.count())] == [lg["code"] for lg in langs]:
                return  # nothing changed — do not touch the selection
            combo.blockSignals(True)   # a programmatic rebuild must not re-apply the language
            combo.clear()
            for lg in langs:
                combo.addItem(lg["name"], lg["code"])
            idx = next((i for i in range(combo.count())
                        if combo.itemData(i) == cur), 0)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown — the combo is already destroyed

    def showEvent(self, event):
        """v1.3.3.1: refreshing the language list is part of "open the dialog"."""
        super().showEvent(event)
        try:
            self._refresh_language_combo()
        except Exception:  # noqa: BLE001 — show must never crash
            pass

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_language_changed(self, index: int):
        """The "Language" tab: immediate application (set_language + UI retranslate)."""
        code = self.language_combo.itemData(index)
        if not code:
            return
        self.language_changed.emit(code)
        # The dialog's own labels are updated immediately (t() is already in the new language).
        try:
            self.retranslate()
        except RuntimeError:
            pass  # Qt teardown

    def _on_accept(self):
        """OK: save the collected values to config.json + the applied signal."""
        try:
            from i18n import save_config
            if not save_config(self.collect()):
                QMessageBox.warning(
                    self, _t("msg.error_title"),
                    _t("msg.save_failed", error="~/.sshmap/config.json"))
                return  # do not close silently — the user sees the error
        except Exception as e:
            # v1.2.10 (AUDIT auto #3): the quiet `return` left a "frozen" dialog without an explanation;
            # now — a log + a visible error, as in the save_config()==False branch above (the same i18n keys).
            try:
                from modules.logger import get_logger
                get_logger("ui.settings_dialog").warning(f"save_config failed: {e}")
            except Exception:
                pass
            QMessageBox.warning(
                self, _t("msg.error_title"),
                _t("msg.save_failed", error="~/.sshmap/config.json"))
            return
        self.applied.emit()
        self.accept()

    def reject(self):
        """Cancel: put the theme back the way the dialog found it (v1.4.3).

        The "Appearance" tab applies LIVE (the "Language" tab precedent) — that
        is what makes the choice meaningful — so a rejected dialog must undo the
        preview. Nothing else in the hub is applied before OK, so nothing else
        has to be restored. Never raises.
        """
        try:
            initial = getattr(self, "_initial_theme", None)
            if initial is not None and initial is not theme.THEME:
                self.theme_changed.emit(initial)
        except RuntimeError:
            pass  # Qt teardown
        # v1.5rc1: the motion switch is live as well — put the flag back too.
        try:
            if bool(getattr(self, "_motion_enabled", True)) != bool(self._initial_motion):
                self.motion_chk.blockSignals(True)
                self.motion_chk.setChecked(not bool(self._initial_motion))
                self.motion_chk.blockSignals(False)
                apply_motion_setting({"motion": self._initial_motion})
                self._motion_enabled = bool(self._initial_motion)
        except (AttributeError, RuntimeError):
            pass  # Qt teardown / a dialog built without the tab
        # v1.6 (ROADMAP task 2): the card density is live too — restore it (the theme
        # walk that `theme_changed` triggers repaints the cards back).
        try:
            if str(getattr(self, "_density", "")) != str(self._initial_density):
                combo = getattr(self, "density_combo", None)
                if combo is not None:
                    idx = next((i for i in range(combo.count())
                                if combo.itemData(i) == self._initial_density), -1)
                    if idx >= 0:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(idx)
                        combo.blockSignals(False)
                theme.set_card_density(self._initial_density)
                self._density = self._initial_density
        except (AttributeError, RuntimeError):
            pass  # Qt teardown / a dialog built without the tab
        super().reject()

    # ── Collecting values (config.json keys; language is NOT included — it is immediate) ───────

    def collect(self) -> dict:
        """The tab values → the ~/.sshmap/config.json keys (all valid by construction:
        the combos give fixed ids, the spinboxes — their own range).

        v1.1.1: +7 keys — the UI/terminal fonts (ui_font_family/ui_font_size/
        terminal_font), the terminal limit (terminal_max_open), the node
        double click (ui_node_double_click), the sidebar buttons
        (ui_show_sidebar_buttons) and the type on the connection plaque
        (ui_show_connection_type). ui_font_size = 0 — the system size
        (the load_ui_settings() validator reads the range 6..72, otherwise
        the default).
        v1.1.2 final: +1 key — status_max_parallel (the cap on parallel
        probes; the spinbox range = the validator clamp of
        get_status_settings()).
        v1.2.2: +1 key — terminal_mode ("windows"|"tabs"; the combo gives
        fixed ids).
        v1.3.2: +1 key — hotkeys (a nested dict action_id → sequence string;
        "" = the hotkey is disabled). The values come from the QKeySequenceEdit
        cells; MainWindow._apply_hotkeys() installs them live after the
        applied signal (no restart). Conflict rows are saved as-is by design.
        v1.3.3.8: +1 key — terminal_wheel ("scrollback"|"off", the combo gives
        fixed ids). This closes the LAST config-only key: the hub's 20 UI-facing
        keys become 21 and every setting now lives in the hub.
        v1.4.3 (ROADMAP task 6): +1 key — theme ({mode, accent} of the
        "Appearance" tab). The value is NESTED like `hotkeys` — one config key
        carrying the whole appearance choice — and `i18n.save_config` merges at
        the TOP level, so `_on_accept` re-merges the stored object (a mode change
        must not drop the accent of a foreign version).
        v1.6.2 (ROADMAP task 4): +1 key — terminal_cursor_style ("bar"|"block"|
        "underline" of the "Terminal" tab; the combo gives fixed ids, so the value
        is valid by construction). 22 → 23 UI-facing keys.
        """
        return {
            "external_terminal": self.ext_term_combo.currentData() or "auto",
            # v1.2.2 (task 4): the terminal display mode
            "terminal_mode": self.mode_combo.currentData() or "windows",
            "terminal_palette": self.palette_combo.currentData() or "default",
            "terminal_font_size": int(self.font_size_spin.value()),
            "terminal_history_lines": int(self.history_spin.value()),
            "terminal_close_behavior": self.close_behavior_combo.currentData() or "close",
            # v1.3.3.8 (ROADMAP task 4): the mouse-wheel mode
            "terminal_wheel": self.wheel_combo.currentData() or "scrollback",
            # v1.6.2 (ROADMAP task 4): the cursor shape — the 23rd UI-facing key
            "terminal_cursor_style": self.cursor_combo.currentData() or "bar",
            # v1.4.3 (ROADMAP task 6): the appearance — the mode + the accent hue,
            # stored as the colour the user actually picked (the hue is derived
            # back). v1.5rc1: +`motion` — the "Reduce motion" switch of the same
            # tab, so the appearance choice stays ONE nested key (the hub's
            # collect() key count is unchanged).
            "theme": {"mode": self.theme_mode_combo.currentData() or theme.MODE_DARK,
                      "accent": self._accent_hex,
                      "motion": bool(self._motion_enabled),
                      # v1.6 (ROADMAP task 2): the card density — a fourth VALUE of the
                      # SAME nested key, so the hub's collect() key count stays 22.
                      "density": (self.density_combo.currentData()
                                  or theme.DENSITY_NORMAL)},
            # v1.6.6 (ROADMAP task 3): the DECLARED `0` sentinel is what the manual-only
            # checkbox writes — the spinbox itself is never zeroed, so the user's interval is
            # still there when the box is un-ticked (the row is a VIEW of the state).
            "status_interval_sec": (int(getattr(self, "_manual_interval_sec", 0))
                                    if self.manual_only_chk.isChecked()
                                    else int(self.status_interval_spin.value())),
            "status_probe_timeout_sec": float(self.probe_timeout_spin.value()),
            # v1.1.2 final (task 2): the cap on parallel probes per round
            "status_max_parallel": int(self.max_parallel_spin.value()),
            "autosave_enabled": bool(self.autosave_enabled_chk.isChecked()),
            "autosave_interval_sec": int(self.autosave_interval_spin.value()),
            "backup_count": int(self.backup_count_spin.value()),
            # v1.1.1: fonts (UI + terminal) and the own-terminals limit
            "ui_font_family": self.ui_font_family_edit.text().strip(),
            "ui_font_size": int(self.ui_font_size_spin.value()),
            "terminal_font": self.term_font_family_edit.text().strip(),
            "terminal_max_open": int(self.max_open_spin.value()),
            # v1.1.1: map/sidebar options
            "ui_node_double_click": self.node_dblclick_combo.currentData() or "properties",
            "ui_show_sidebar_buttons": bool(self.sidebar_buttons_chk.isChecked()),
            "ui_show_connection_type": bool(self.show_conn_type_chk.isChecked()),
            # v1.3.2 (ROADMAP task 2/3): the configurable hotkeys — the table's values
            # ({} — a dialog built without the tab, a defensive fallback)
            "hotkeys": self.hotkey_sequences(),
        }

    # ── i18n: retranslating the dialog's own strings (a language change in the open dialog) ───

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to the dialog's own strings.

        The hub is the ONE dialog that can be on screen WHILE the theme changes (its own
        "Appearance" tab applies live), so it owns the hook like every other container:
        the hotkey table's conflict marks are repainted and the table's row colours
        re-read (`_refresh_hotkey_conflicts` sets them from the theme). The tab's own
        swatches are painted from their FIXED preset colours — they deliberately do
        not follow the theme (a swatch shows the accent it would install).

        The other dialogs (AddServer, SSHConnection, …) build their small QSS strings
        from the live module constants at CONSTRUCTION time and are modal — a theme
        switch cannot happen while one of them is open — so they are outside this
        audit list by design (DOCUMENTATION.md §3).
        """
        try:
            self._refresh_hotkey_conflicts()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a dialog built without the tab
        # v1.5rc4 (ROADMAP task 3/4): the family captions and the search highlight are
        # VALUES of the same kind — re-read them from the live theme.
        try:
            self._retranslate_hotkey_families()
            self._reapply_search_highlights()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a dialog built without the search field

    def retranslate(self):
        """Re-apply translations to the dialog's strings (the registry — here)."""
        self.setWindowTitle(_t("settings.title"))
        self.tabs.setTabText(0, _t("settings.tab.general"))
        self.tabs.setTabText(1, _t("settings.tab.appearance"))   # v1.4.3
        self.tabs.setTabText(2, _t("settings.tab.terminal"))
        self.tabs.setTabText(3, _t("settings.tab.statuses"))
        self.tabs.setTabText(4, _t("settings.tab.autosave"))
        self.tabs.setTabText(5, _t("settings.tab.map"))
        self.tabs.setTabText(6, _t("settings.tab.hotkeys"))   # v1.3.2
        self.tabs.setTabText(7, _t("settings.tab.language"))

        # v1.4.3 (ROADMAP task 6): the "Appearance" tab
        self._lbl_theme_mode.setText(_t("settings.appearance.mode"))
        for i in range(self.theme_mode_combo.count()):
            mid = self.theme_mode_combo.itemData(i)
            key = {"dark": "settings.appearance.mode.dark",
                   "light": "settings.appearance.mode.light",
                   "auto": "settings.appearance.mode.auto"}.get(mid)
            if key:
                self.theme_mode_combo.setItemText(i, _t(key))
        # v1.5rc1: the motion switch of the same tab
        self.motion_chk.setText(_t("settings.appearance.motion"))
        self.motion_chk.setToolTip(_t("settings.appearance.motion.tooltip"))
        self._lbl_theme_accent.setText(_t("settings.appearance.accent"))
        for name, (btn, _hex) in getattr(self, "_swatch_buttons", {}).items():
            btn.setToolTip(_t(f"settings.appearance.accent.{name}"))
        self._lbl_theme_own.setText(_t("settings.appearance.own_color"))
        self.accent_pick_btn.setText(_t("settings.appearance.pick_color"))
        self._lbl_theme_hint.setText(_t("settings.appearance.hint"))

        self._lbl_ext_term.setText(_t("settings.general.external_terminal"))
        for i in range(self.ext_term_combo.count()):
            tid = self.ext_term_combo.itemData(i)
            if tid:
                self.ext_term_combo.setItemText(i, _t(f"ssh_ext.preset.{tid}"))

        # v1.1.1: UI font + sidebar buttons ("General" tab)
        self._lbl_ui_font_family.setText(_t("settings.general.ui_font_family"))
        self._lbl_ui_font_size.setText(_t("settings.general.ui_font_size"))
        self.ui_font_size_spin.setSpecialValueText(_t("settings.ui_font_system"))
        self.sidebar_buttons_chk.setText(_t("settings.general.sidebar_buttons"))

        # v1.2.2: the display mode ("Terminal" tab)
        self._lbl_mode.setText(_t("settings.terminal.mode"))
        for i in range(self.mode_combo.count()):
            mid = self.mode_combo.itemData(i)
            key = {
                "windows": "settings.terminal.mode.windows",
                "tabs": "settings.terminal.mode.tabs",
            }.get(mid)
            if key:
                self.mode_combo.setItemText(i, _t(key))

        self._lbl_palette.setText(_t("settings.terminal.palette"))
        for i in range(self.palette_combo.count()):
            pid = self.palette_combo.itemData(i)
            key = {
                "default": "settings.terminal.palette.default",
                "nord": "settings.terminal.palette.nord",
                "dracula": "settings.terminal.palette.dracula",
                "tokyo_night": "settings.terminal.palette.tokyo_night",
            }.get(pid)
            if key:
                self.palette_combo.setItemText(i, _t(key))
        self._lbl_term_font_family.setText(_t("settings.terminal.font_family"))
        self._lbl_font_size.setText(_t("settings.terminal.font_size"))
        self._lbl_max_open.setText(_t("settings.terminal.max_open"))
        self._lbl_history.setText(_t("settings.terminal.history_lines"))
        self._lbl_close_behavior.setText(_t("settings.terminal.close_behavior"))
        for i in range(self.close_behavior_combo.count()):
            cid = self.close_behavior_combo.itemData(i)
            key = {
                "close": "settings.terminal.close_behavior.close",
                "ask": "settings.terminal.close_behavior.ask",
            }.get(cid)
            if key:
                self.close_behavior_combo.setItemText(i, _t(key))

        # v1.3.3.8 (ROADMAP task 4): the wheel combo + the language manager buttons
        self._lbl_wheel.setText(_t("settings.terminal.wheel"))
        for i in range(self.wheel_combo.count()):
            wid = self.wheel_combo.itemData(i)
            key = {
                "scrollback": "settings.terminal.wheel.scrollback",
                "off": "settings.terminal.wheel.off",
            }.get(wid)
            if key:
                self.wheel_combo.setItemText(i, _t(key))

        # v1.6.2 (ROADMAP task 4): the cursor-shape combo
        self._lbl_cursor.setText(_t("settings.terminal.cursor"))
        for i in range(self.cursor_combo.count()):
            sid = self.cursor_combo.itemData(i)
            key = {
                "bar": "settings.terminal.cursor.bar",
                "block": "settings.terminal.cursor.block",
                "underline": "settings.terminal.cursor.underline",
            }.get(sid)
            if key:
                self.cursor_combo.setItemText(i, _t(key))

        self._lbl_status_interval.setText(_t("settings.statuses.interval"))
        self._lbl_probe_timeout.setText(_t("settings.statuses.timeout"))
        self._lbl_max_parallel.setText(_t("settings.statuses.max_parallel"))
        # v1.6.6 (ROADMAP task 3): the manual-only row is a CONTAINER of its own — the checkbox
        # and the sentence that explains the mode are re-texted with the rest of the tab.
        self.manual_only_chk.setText(_t("settings.statuses.manual_only"))
        self.manual_only_hint.setText(_t("settings.statuses.manual_only.hint"))

        self.autosave_enabled_chk.setText(_t("settings.autosave.enabled"))
        self._lbl_autosave_interval.setText(_t("settings.autosave.interval"))
        self._lbl_backup_count.setText(_t("settings.autosave.backups"))

        # v1.1.1: map options ("Map" tab)
        self._lbl_node_dblclick.setText(_t("settings.map.node_double_click"))
        for i in range(self.node_dblclick_combo.count()):
            cid = self.node_dblclick_combo.itemData(i)
            key = {
                "properties": "settings.map.node_double_click.properties",
                "connect": "settings.map.node_double_click.connect",
            }.get(cid)
            if key:
                self.node_dblclick_combo.setItemText(i, _t(key))
        self.show_conn_type_chk.setText(_t("settings.map.show_connection_type"))

        # v1.3.2: the "Hotkeys" tab — the headers, the hint, the warning and the
        # per-row action names (they reuse the existing menu i18n keys).
        # v1.5rc4 (task 4): + the filter placeholder, the counts header, the "how to
        # assign" hint and the FAMILY captions of the grouped table.
        self.hotkeys_table.setHorizontalHeaderLabels(
            [_t("settings.hotkeys.action"), _t("settings.hotkeys.sequence")])
        self.hotkeys_filter.setPlaceholderText(_t("settings.hotkeys.filter"))
        self._lbl_hotkeys_disabled_hint.setText(_t("settings.hotkeys.disabled_hint"))
        self._lbl_hotkeys_assign_hint.setText(_t("settings.hotkeys.assign_hint"))
        self.reset_hotkeys_btn.setText(_t("settings.hotkeys.reset"))   # v1.3.3.3
        self._retranslate_hotkey_families()
        self._refresh_hotkey_conflicts()   # re-marks the rows + re-texts the warning

        # v1.5rc4 (ROADMAP task 3): the settings search's own strings
        self.search_edit.setPlaceholderText(_t("settings.search.placeholder"))
        self._update_search_status()

        self._lbl_language.setText(_t("settings.language.label"))
        # v1.3.3.8: the language manager's own two buttons (the status line carries a
        # REPORT of a past action — data, not a label — and is left alone)
        self.import_lang_btn.setText(_t("language.import"))
        self.export_lang_btn.setText(_t("language.export"))

        self.ok_btn.setText(_t("settings.ok"))
        self.cancel_btn.setText(_t("settings.cancel"))
