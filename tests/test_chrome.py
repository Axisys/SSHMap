# -*- coding: utf-8 -*-
"""v1.5rc4 — Density, focus & findability: the chrome answers the same questions as the map.

The LAST rc of the 1.5 line. v1.5rc1 fixed the palette, v1.5rc2 gave every meaning a
second channel and v1.5rc3 answered "how do I start"; this release makes the CHROME itself
work at any window width and gives the keyboard a visible home.

  §1 THE STATUS BAR has an overflow policy: below the MEASURED `status_bar_needed_width()` the
     "Servers / Connections" totals are given up, while the three CLICKABLE status
     counters and the zoom percentage STAY (the v1.4.5 counters are the interactive part)
     and the multi-input plaque belongs to its mode, never to a resize. ONE pure decision
     (`is_compact`) + ONE method on the window, so three widths are three assertions;
  §2 THE TOOLBAR stopped repeating the sidebar and the palette (the pinned keep-set:
     file new/open/save, center, fit, undo/redo and the four view toggles) and OVERFLOWS
     on a narrow window — a "»" menu carrying the very same QActions instead of a squeezed
     button row (the second pinned decision: overflow, not wrapping);
  §3 THE SETTINGS SEARCH: one field filters the rows and the pages by their TRANSLATED
     labels, a hit switches to its tab and highlights the row, Enter walks the hits. The
     acceptance asks for a key living on EACH of the eight tabs — this file asks for it;
  §4 THE HOTKEYS TAB became navigable: a filter (name OR current sequence), grouping by
     family with a caption row per family, a counts header ("with a key" / "assignable")
     and the assignment hint — while `ui/hotkey_registry.py` stays the only source;
  §5 THE VISIBLE FOCUS of the three keyboard domains (map / sidebar / terminal): ONE
     indicator (`ui/focus_ring.py`), ONE colour (`theme.ACCENT_STRONG` — the v1.5rc1 ink
     role, never a new tone) and one state per domain that follows the real focus events;
  §6 THE KEYBOARD WALK on the map: Tab/Shift+Tab walk the cards in reading order, the
     arrows move the selection to the geometrically nearest card, Enter opens per the
     pinned `ui_node_double_click` semantics, Esc clears — all on `MapView`, all through
     the window's ordinary selection path;
  §7 THE OVERLAY PRIORITY: the legend yields to the first-run hint, the minimap yields to
     the open search bar, the collapse diamond is never covered — decided in ONE place from
     the live geometry, and the temporary suppression never touches `ui_legend`;
  §8 the release state (version, i18n parity + the 13 new keys, the registry families).

Run: python tests/test_chrome.py   (from the project root) or python tests/run_all.py
"""
import os

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, read_cfg, clear_cfg,
                     EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QFocusEvent, QKeyEvent, QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QMenu, QMessageBox,  # noqa: E402
                               QToolButton)

app = QApplication.instance() or QApplication([])

import i18n  # noqa: E402
import ui.focus_ring as FR  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.status_bar as SB  # noqa: E402
from models.server import ServerData  # noqa: E402
from ui import theme, theme_qss  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402

# ── The harness: no modal box may block an offscreen run ─────────────────────
from _fakes import QuestionStub  # noqa: E402

boxes = []
QuestionStub(QMessageBox.Yes,
             record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))


class _FakeAddServerDialog:
    """The AddServer dialog stub — `ui_node_double_click = "properties"` lands here."""

    instances = []

    def __init__(self, parent=None, edit_data=None):
        self.edit_data = edit_data
        _FakeAddServerDialog.instances.append(self)

    def exec(self):
        return QDialog.Rejected     # the user closed it — no data change either way

    def get_data(self):
        return ServerData(id="x", alias="x", host="10.0.0.1")


MW.AddServerDialog = _FakeAddServerDialog


def make_main():
    """An offscreen MainWindow with every timer stopped (deterministic, no event loop)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w._freshness_timer.stop()
    w._status_checker = None    # hermetic: no probe round ever leaves this file
    w.resize(1100, 760)
    w.show()
    app.processEvents()
    return w


def add_node(win, nid, alias, host, x=0.0, y=0.0):
    """Put a card on the map at a scene position (the geometry the walk reads)."""
    node = win.scene.add_server(ServerData(id=nid, alias=alias, host=host, user="root"))
    node.setPos(QPointF(float(x), float(y)))
    win.refresh_sidebar()
    return node


def key_event(key, modifiers=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)


def toolbar_buttons(win):
    """{action text: QToolButton} of the window's toolbar (the overflow button excluded)."""
    out = {}
    toolbar = win._toolbar
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if isinstance(widget, QToolButton) and widget is not win._toolbar_overflow_btn:
            out[action.text()] = widget
    return out


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the status bar at three window widths (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
win = make_main()
_needed = win._status_bar_overflow_needed()
_wide = _needed + 200

check("§1 the policy is ONE pure decision over the live width and the MEASURED need",
      SB.is_compact(_needed, _needed) is False
      and SB.is_compact(_needed - 1, _needed) is True
      and SB.is_compact(0, _needed) is False and SB.is_compact(None, _needed) is False
      and SB.is_compact("wide", _needed) is False
      and _needed > 0,
      f"needed={_needed}")

check("§1 the threshold is measured from the bar's own widgets (not a typed number)",
      _needed == SB.status_bar_needed_width(win._status_bar_permanent_widgets())
      and _needed > win._status_bar_permanent_widgets()[0].sizeHint().width(),
      str([w.sizeHint().width() for w in win._status_bar_permanent_widgets() if w]))

_w1 = win._sync_status_bar_overflow(_wide)
check("§1 a WIDE window: the totals pair is shown, nothing is compact",
      _w1 is False and win.status_bar_compact() is False
      and win.counts_label.isHidden() is False
      and win.counts_label.text() == i18n.t("status.counts", servers=0, connections=0))

_w2 = win._sync_status_bar_overflow(_needed - 1)
check("§1 ONE pixel short: the totals pair is given up",
      _w2 is True and win.counts_label.isHidden() is True,
      f"compact={win.status_bar_compact()} hidden={win.counts_label.isHidden()}")

_w3 = win._sync_status_bar_overflow(win.MIN_WINDOW_WIDTH)
check("§1 the narrowest window the app allows: still only the totals pair is given up",
      _w3 is True and win.counts_label.isHidden() is True
      and win.MIN_WINDOW_WIDTH < _needed,
      f"floor={win.MIN_WINDOW_WIDTH} needed={_needed}")

check("§1 the three CLICKABLE status counters stay (the v1.4.5 interactive part)",
      set(win.status_filter_labels) == {"online", "warn", "offline"}
      and all(not c.isHidden() for c in win.status_filter_labels.values()))

check("§1 the zoom percentage stays",
      win.zoom_label.isHidden() is False and win.zoom_label.text().endswith("%"))

# The plaque belongs to the multi-input MODE: the policy must not have an opinion about it.
win._multi_plaque.setVisible(False)
win._sync_status_bar_overflow(win.MIN_WINDOW_WIDTH)
check("§1 the multi-input plaque is not part of the resize policy (the mode owns it)",
      win._multi_plaque.isHidden() is True
      and win._multi_plaque not in win._status_bar_permanent_widgets())

_w4 = win._sync_status_bar_overflow(_wide)
check("§1 widening again gives the pair back (only visibility moved, never the widget)",
      _w4 is False and win.status_bar_compact() is False
      and win.counts_label.isHidden() is False)

# The policy really runs from the live width: a resize goes through it.
win.resize(win.MIN_WINDOW_WIDTH, 700)
app.processEvents()
app.processEvents()
check("§1 a real resize drives the policy (the window's own width, not an argument)",
      win.width() < _needed and win.status_bar_compact() is True
      and win.counts_label.isHidden() is True,
      f"width={win.width()} compact={win.status_bar_compact()}")
win.resize(1200, 760)
app.processEvents()
app.processEvents()
check("§1 the window itself can get that narrow (the chrome no longer dictates the floor)",
      win.MIN_WINDOW_WIDTH == win.minimumWidth() and win.status_bar_compact() is False,
      f"min={win.minimumWidth()} width={win.width()}")


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the toolbar: the pinned keep-set and the overflow (task 2) ==")
# ════════════════════════════════════════════════════════════════════════════

_buttons = toolbar_buttons(win)
_texts = sorted(_buttons)
_dropped = [i18n.t("file.save_as"), i18n.t("btn.add_server"), i18n.t("btn.add_connection")]

check("§2 the toolbar stopped repeating the sidebar and the palette (the de-duplication)",
      not any(text in _texts for text in _dropped),
      f"texts={_texts}")

check("§2 the keep-set: 3 file verbs + Center + Fit, undo/redo and the five view toggles",
      len(_buttons) == 3 + 2 + 2 + 5
      and all(i18n.t(k) in _texts for k in ("file.new_project", "file.open", "file.save",
                                           "view.center_map", "view.fit_map",
                                           "edit.undo", "edit.redo"))
      and all(text in _texts for text in
              (i18n.t("view.toggle_sidebar"), i18n.t("view.toggle_map"),
               i18n.t("view.toggle_minimap"), i18n.t("view.toggle_legend"),
               i18n.t("view.toggle_activity"))),
      f"{len(_buttons)} buttons: {_texts}")

check("§2 the dropped actions are still reachable (the menus and the palette own them)",
      i18n.t("file.save_as") in [a.text() for a in win.findChildren(type(win.act_undo))]
      or any(i18n.t("file.save_as") in a.text() for a in win.findChildren(type(win.act_undo))),
      "the File menu")

_tb_need = win._toolbar_full_width()
_tb_compact_below = int(_tb_need * win.TOOLBAR_OVERFLOW_COMFORT)


def _bar_widget(action):
    """The toolbar's own widget for an action (a view toggle is a QAction, not a widget)."""
    return win._toolbar.widgetForAction(action)


def _overflow_visible():
    """Is the "»" on the bar? — the toolbar ACTION's visibility is the contract."""
    return bool(win._toolbar_overflow_action.isVisible())


_long = win._sync_toolbar_overflow(_tb_compact_below + 100)
check("§2 a WIDE window: every pinned button is on the bar, no '»'",
      _long is False and win.toolbar_overflow_active() is False
      and _overflow_visible() is False
      and all(not widget.isHidden() for widget in _buttons.values()),
      f"needed={_tb_need} below={_tb_compact_below} "
      f"btn_visible={_overflow_visible()} "
      f"hidden={[t for t, w in _buttons.items() if w.isHidden()]}")

_short = win._sync_toolbar_overflow(_tb_compact_below - 1)
check("§2 a NARROW window: OVERFLOW, not wrapping — the '»' menu takes the buttons",
      _short is True and win.toolbar_overflow_active() is True
      and _overflow_visible() is True
      and all(_bar_widget(a).isHidden() for a in win._toolbar_overflow_actions),
      f"below={_tb_compact_below}")

_core_actions = [win._legend_toolbar_btn, win._minimap_toolbar_btn,
                 win._sidebar_toolbar_btn, win._map_toolbar_btn, win.act_undo, win.act_redo]
check("§2 the core buttons stay on the bar while the secondary ones move",
      all(not _bar_widget(a).isHidden() for a in _core_actions)
      and all(_bar_widget(a).isHidden() for a in win._toolbar_overflow_actions),
      f"core_hidden={[a.text() for a in _core_actions if _bar_widget(a).isHidden()]}")

_overflow_texts = [a.text() for a in win._toolbar_overflow_menu.actions() if a.text()]
check("§2 the '»' menu carries exactly the five overflowable actions",
      len(win._toolbar_overflow_actions) == 5
      and _overflow_texts == [a.text() for a in win._toolbar_overflow_actions],
      str(_overflow_texts))

check("§2 the menu holds the SAME QAction objects (enablement/icons cannot diverge)",
      all(a in win._toolbar_overflow_actions
          for a in win._toolbar_overflow_menu.actions() if not a.isSeparator()))

check("§2 undo/redo and the four view toggles NEVER move into the menu",
      not any(a in win._toolbar_overflow_actions
              for a in (win.act_undo, win.act_redo,
                        win._legend_toolbar_btn, win._minimap_toolbar_btn,
                        win._sidebar_toolbar_btn, win._map_toolbar_btn)))

check("§2 the overflow button is a real QToolButton with an instant popup and a translated tip",
      isinstance(win._toolbar_overflow_btn, QToolButton)
      and win._toolbar_overflow_btn.text() == "\u00bb"
      and win._toolbar_overflow_btn.toolTip() == i18n.t("toolbar.more")
      and win._toolbar_overflow_btn.menu() is win._toolbar_overflow_menu
      and win._toolbar_overflow_menu.__class__ is QMenu,
      f"type={type(win._toolbar_overflow_btn)} text={win._toolbar_overflow_btn.text()!r} "
      f"tip={win._toolbar_overflow_btn.toolTip()!r} exp={i18n.t('toolbar.more')!r} "
      f"menu={win._toolbar_overflow_btn.menu() is win._toolbar_overflow_menu} "
      f"cls={win._toolbar_overflow_menu.__class__}")

win._sync_toolbar_overflow(_tb_compact_below + 100)
check("§2 widening again restores the bar (idempotent policy)",
      win.toolbar_overflow_active() is False and _overflow_visible() is False
      and all(not w.isHidden() for w in _buttons.values()))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the settings search (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

dlg = SettingsDialog(None)
check("§3 the field sits above the tabs and carries a translated placeholder",
      dlg.search_edit.placeholderText() == i18n.t("settings.search.placeholder")
      and dlg.layout().indexOf(dlg.search_edit) < dlg.layout().indexOf(dlg.tabs))

# The acceptance: A KEY LIVING ON EACH OF THE EIGHT TABS.
_missing_tabs = []
for _index in range(dlg.tabs.count()):
    _title = dlg.tabs.tabText(_index)
    _hits = dlg.search_settings(_title)
    if not _hits or dlg.tabs.currentIndex() != _index:
        _missing_tabs.append((_index, _title, len(_hits), dlg.tabs.currentIndex()))
check("§3 the search finds a key living on EACH of the eight tabs (title = the page)",
      not _missing_tabs, str(_missing_tabs))

_hits = dlg.search_settings(i18n.t("settings.statuses.interval"))
check("§3 a ROW hit switches to its tab and reports itself",
      len(_hits) == 1 and _hits[0][0] == 3
      and dlg.tabs.currentIndex() == 3
      and i18n.t("settings.statuses.interval") in _hits[0][1],
      str(_hits))

_row_entry = [e for e in dlg._search_entries
              if e["text"] == i18n.t("settings.statuses.interval")]
check("§3 the hit's row is HIGHLIGHTED in the strong accent (v1.5rc1 ink role)",
      len(_row_entry) == 1
      and theme.ACCENT_STRONG.lower() in _row_entry[0]["label"].styleSheet().lower(),
      _row_entry[0]["label"].styleSheet() if _row_entry else "no entry")

_other = [e for e in dlg._search_entries
          if e["page"] is _row_entry[0]["page"] and e is not _row_entry[0]]
check("§3 the rows of that page that do NOT match are hidden",
      bool(_other) and all(not w.isHidden() for w in _other[0]["widgets"] if w is not None)
      or all(any(w.isHidden() for w in e["widgets"]) for e in _other),
      f"{len(_other)} other row(s) on the tab")

_none = dlg.search_settings("zzz-no-such-setting-zzz")
check("§3 no match: an honest line, no tab jump and no highlight",
      _none == [] and dlg.search_status_lbl.text() == i18n.t("settings.search.none")
      and not any(e.get("hit") for e in dlg._search_entries))

dlg.search_settings("")
check("§3 clearing the query restores every row and drops the highlight",
      all(not any(w.isHidden() for w in e["widgets"]) for e in dlg._search_entries)
      and not any(e.get("hit") for e in dlg._search_entries)
      and dlg.search_status_lbl.isHidden())

# The count line and the hit walk (Enter) — the palette's "k / N" idea, one field over.
dlg.search_settings(i18n.t("settings.tab.terminal"))
check("§3 a page hit reports its position and the field walks the hits",
      dlg.search_status_lbl.text().endswith(f"/ {len(dlg.search_hits())}")
      and dlg.search_status_lbl.text().startswith("1 /"))
dlg.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the Hotkeys tab is navigable (task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

dlg = SettingsDialog(None)
_ids = list(HR.action_ids())
_grouped = HR.actions_by_family()

check("§4 the registry groups every action exactly once (the six pinned families)",
      HR.family_order() == ["file", "edit", "view", "node", "plugins", "help"]
      and sorted(a for ids in _grouped.values() for a in ids) == sorted(_ids)
      and all(HR.action_family(a) in HR.family_order() for a in _ids))

check("§4 the table has a caption row per non-empty family + one ACTION row per action",
      len(dlg.hotkey_family_rows()) == 6
      and dlg.hotkeys_table.rowCount() == len(_ids) + 6
      and [dlg._hotkey_rows[r][1] for r in dlg.hotkey_action_rows()]
      == [a for fam in HR.family_order() for a in _grouped[fam]])

check("§4 the captions read the translated family names and span both columns",
      [dlg.hotkeys_table.item(r, 0).text() for r in dlg.hotkey_family_rows()]
      == [i18n.t(HR.family_label_key(f)) for f in HR.family_order()]
      and all(dlg.hotkeys_table.columnSpan(r, 0) == 2 for r in dlg.hotkey_family_rows()))

check("§4 any action is reachable by id, whatever its row is",
      dlg.hotkey_row("file.new") >= 0
      and dlg.hotkey_row("help.example") >= 0
      and dlg.hotkey_row("nope.nope") == -1)

_counts = dlg.hotkey_sequences()
_with = sum(1 for s in _counts.values() if s)
check("§4 the counts header is the LIVE table, not the registry",
      dlg._lbl_hotkeys_counts.text()
      == i18n.t("settings.hotkeys.counts", with_key=_with,
                assignable=len(_counts) - _with)
      and _with == 23 and len(_counts) - _with == 36,
      f"{_with} with a key, {len(_counts) - _with} assignable")

check("§4 the assignment hint is shown next to the older 'clear to disable' one",
      dlg._lbl_hotkeys_assign_hint.text() == i18n.t("settings.hotkeys.assign_hint")
      and dlg._lbl_hotkeys_disabled_hint.text() == i18n.t("settings.hotkeys.disabled_hint"))

check("§4 no filter: every action row is visible",
      dlg.hotkeys_visible_ids() == [a for fam in HR.family_order() for a in _grouped[fam]])

_visible = dlg.filter_hotkeys(i18n.t("file.save"))
check("§4 the filter narrows the table to the matching rows",
      0 < len(_visible) < len(_ids) and "file.save" in _visible,
      f"{len(_visible)} of {len(_ids)}: {_visible}")

_visible = dlg.filter_hotkeys("Ctrl+S")
check("§4 the filter matches the CURRENT SEQUENCE as well as the name",
      "file.save" in _visible and len(_visible) < len(_ids),
      str(_visible))

_label = dlg._hotkey_label("help.open_logs")
_visible = dlg.filter_hotkeys(_label)
check("§4 a name match hides the families that have nothing to show",
      _visible == ["help.open_logs"]
      and all(dlg.hotkeys_table.isRowHidden(r) for r in dlg.hotkey_family_rows()
              if dlg._hotkey_rows[r][1] != "help"),
      str(_visible))

dlg.filter_hotkeys("")
check("§4 clearing the filter brings the whole grouped table back",
      len(dlg.hotkeys_visible_ids()) == len(_ids)
      and not any(dlg.hotkeys_table.isRowHidden(r) for r in dlg.hotkey_family_rows()))
dlg.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the visible focus of the three keyboard domains (task 5) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 the indicator has ONE colour — the strong accent of v1.5rc1 (never a new tone)",
      FR.ring_color().lower() == theme.ACCENT_STRONG.lower()
      and FR.ring_pen().color().name().lower() == theme.ACCENT_STRONG.lower())

check("§5 the frame's thickness is declared ONCE and shared by both halves of the indicator",
      FR.RING_WIDTH == theme_qss.FOCUS_RING_WIDTH
      and theme_qss.style_names().count(FR.STYLE_ACTIVE) == 1
      and theme_qss.style_names().count(FR.STYLE_INACTIVE) == 1
      and str(FR.RING_WIDTH) in theme_qss.style(FR.STYLE_ACTIVE)
      and theme.ACCENT_STRONG.lower() in theme_qss.style(FR.STYLE_ACTIVE).lower()
      and "transparent" in theme_qss.style(FR.STYLE_INACTIVE).lower())

# The painter really paints (the ONE painter the map and the terminal canvas call).
_image = QImage(40, 30, QImage.Format.Format_ARGB32)
_image.fill(0)
_painter = QPainter(_image)
try:
    _drawn = FR.paint_ring(_painter, QRect(0, 0, 40, 30))
finally:
    _painter.end()
_pixels = {_image.pixelColor(x, y).name().lower()
           for x in range(40) for y in range(30)}
check("§5 paint_ring() draws the frame in that colour",
      _drawn is True and theme.ACCENT_STRONG.lower() in _pixels,
      sorted(_pixels)[:3])

# ── the MAP domain ────────────────────────────────────────────────────────────
win = make_main()
_view = win.view
check("§5 the map is a focus domain (StrongFocus) and starts without the ring",
      _view.focusPolicy() in (Qt.FocusPolicy.StrongFocus,
                              Qt.FocusPolicy.WheelFocus)
      and _view.focus_ring_active() is False
      and win.sidebar.focus_indicator_active() is False)
_view.setFocus(Qt.FocusReason.OtherFocusReason)
app.processEvents()
check("§5 the map shows the ring once it owns the keyboard",
      _view.focus_ring_active() is True and win.sidebar.focus_indicator_active() is False)

# ── the SIDEBAR domain ────────────────────────────────────────────────────────
_tree = win.sidebar.tree
_tree.setFocus(Qt.FocusReason.OtherFocusReason)
app.processEvents()
check("§5 the sidebar shows the ring when the tree takes the keyboard (and the map yields)",
      win.sidebar.focus_indicator_active() is True
      and _view.focus_ring_active() is False
      and theme.ACCENT_STRONG.lower() in _tree.styleSheet().lower(),
      _tree.styleSheet())
check("§5 the inactive sidebar frame keeps the SAME thickness (no layout jump)",
      str(FR.RING_WIDTH) in theme_qss.style(FR.STYLE_INACTIVE))

# The keyboard domains are also a WALK: "Focus the map" (the one new registry action)
# and Ctrl+Tab (`_focus_domain_step`) move the keyboard between them.
check("§5 'Focus the map' is a registry action with an EMPTY default and a View menu item",
      HR.default_sequence("view.focus_map") == ""
      and win._hotkey_targets.get("view.focus_map")
      and i18n.t("view.focus_map") in [a.text() for a in win.findChildren(type(win.act_undo))])
win.sidebar.tree.setFocus(Qt.FocusReason.OtherFocusReason)
app.processEvents()
win._focus_map()
app.processEvents()
check("§5 'Focus the map' hands the keyboard to the canvas",
      _view.focus_ring_active() is True and win.sidebar.focus_indicator_active() is False,
      f"map_ring={_view.focus_ring_active()} sidebar={win.sidebar.focus_indicator_active()}")
check("§5 Ctrl+Tab walks from the map to the sidebar",
      win._focus_domain_step(+1) is _tree and win.sidebar.focus_indicator_active() is True)
check("§5 ...and back again (a two-domain cycle on a map with no session)",
      win._focus_domain_step(+1) is _view and _view.focus_ring_active() is True)

# ── the TERMINAL domain ───────────────────────────────────────────────────────
from modules.terminal_screen import TerminalScreen  # noqa: E402
from modules.terminal_widget import TerminalWidget  # noqa: E402

_screen = TerminalScreen(40, 10, history_lines=100)
_canvas = TerminalWidget(_screen, None)
_canvas.resize(320, 160)
_canvas.show()
app.processEvents()
check("§5 the terminal canvas starts without the ring and is its own focus domain",
      _canvas.focus_ring_active() is False
      and _canvas.focusPolicy() == Qt.FocusPolicy.StrongFocus)
_canvas.setFocus(Qt.FocusReason.OtherFocusReason)
app.processEvents()
check("§5 the terminal canvas shows the SAME ring (the 'where do my keys go' answer)",
      _canvas.focus_ring_active() is True
      and _canvas._focus_ring is not None)
_canvas.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
check("§5 losing the focus drops the ring again (the state follows the real events)",
      _canvas.focus_ring_active() is False)
_canvas.hide()


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the keyboard walk on the map (task 6) ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_view = win.view
_A = add_node(win, "kbdA", "Alpha", "10.20.0.1", 0, 0)
_B = add_node(win, "kbdB", "Bravo", "10.20.0.2", 400, 0)
_C = add_node(win, "kbdC", "Charlie", "10.20.0.3", 0, 300)
_D = add_node(win, "kbdD", "Delta", "10.20.0.4", 400, 300)
app.processEvents()

check("§6 the walk order is the READING order of the map, not the insertion order",
      _view.keyboard_walk_order() == [_A, _B, _C, _D],
      str([n.data.alias for n in _view.keyboard_walk_order()]))

_selected = lambda: [i for i in win.scene.selectedItems()]  # noqa: E731
check("§6 nothing is selected before the walk", _selected() == [])

# Tab through the cards (the real event path — `MapView.event()` intercepts Qt's focus walk)
_QTab = QTest.keyClick(_view, Qt.Key.Key_Tab)
check("§6 Tab selects the first card (the event really reaches the walk)",
      _view.keyboard_current_node() is _A, str(win.scene.selectedItems()))

_view.event(key_event(Qt.Key.Key_Tab))
check("§6 Tab walks forward", _view.keyboard_current_node() is _B)
_view.event(key_event(Qt.Key.Key_Tab))
_view.event(key_event(Qt.Key.Key_Tab))
check("§6 ...and wraps around at the end", _view.keyboard_current_node() is _D)
_view.event(key_event(Qt.Key.Key_Tab))
check("§6 the wrap returns to the first card", _view.keyboard_current_node() is _A)
_view.event(key_event(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier))
check("§6 Shift+Tab walks backwards", _view.keyboard_current_node() is _D)

# The arrows: the geometrically nearest card in that direction.
_view.select_keyboard_node(_A)
_view.event(key_event(Qt.Key.Key_Right))
check("§6 ArrowRight moves to the nearest card to the right", _view.keyboard_current_node() is _B)
_view.event(key_event(Qt.Key.Key_Down))
check("§6 ArrowDown moves to the nearest card below", _view.keyboard_current_node() is _D)
_view.event(key_event(Qt.Key.Key_Left))
check("§6 ArrowLeft moves to the nearest card to the left", _view.keyboard_current_node() is _C)
_view.event(key_event(Qt.Key.Key_Up))
check("§6 ArrowUp comes back to the first row", _view.keyboard_current_node() is _A)

check("§6 the arrow rule is the WEIGHTED nearest (it never jumps backwards or far aside)",
      _view.nearest_node_in_direction(_A, 1.0, 0.0) is _B
      and _view.nearest_node_in_direction(_A, -1.0, 0.0) is None
      and _view.nearest_node_in_direction(_D, 1.0, 0.0) is None)

# Enter: the pinned `ui_node_double_click` semantics, through the window's own method.
_FakeAddServerDialog.instances = []
_connect_calls = []
_orig_connect = win._run_ssh_connect
win._run_ssh_connect = lambda node, *a, **k: _connect_calls.append(node)
try:
    win._node_double_click_mode = "properties"
    _view.select_keyboard_node(_A)
    _view.event(key_event(Qt.Key.Key_Return))
    check("§6 Enter opens the EDITOR in the 'properties' mode (the double-click path)",
          len(_FakeAddServerDialog.instances) >= 1
          and _FakeAddServerDialog.instances[-1].edit_data is _A.data
          and not _connect_calls)

    win._node_double_click_mode = "connect"
    _FakeAddServerDialog.instances = []
    _view.select_keyboard_node(_B)
    _view.event(key_event(Qt.Key.Key_Space))
    check("§6 Space follows the OTHER pinned mode — straight to the SSH dialog",
          _connect_calls == [_B] and not _FakeAddServerDialog.instances)
finally:
    win._run_ssh_connect = _orig_connect
    win._node_double_click_mode = "properties"

# Esc: clear the selection (and nothing else).
_nodes_before = len(list(win.scene.nodes()))
_view.select_keyboard_node(_C)
_view.event(key_event(Qt.Key.Key_Escape))
check("§6 Esc clears the selection",
      win.scene.selectedItems() == [] and _view.keyboard_current_node() is None)
check("§6 ...and deletes nothing (Esc is a selection gesture, never a destructive key)",
      len(list(win.scene.nodes())) == _nodes_before == 4)

check("§6 with nothing selected the arrows keep Qt's own behaviour (panning is not lost)",
      _view._handle_navigation_key(key_event(Qt.Key.Key_Right)) is False
      and _view._handle_navigation_key(key_event(Qt.Key.Key_Down)) is False)

# An EMPTY map must not swallow Tab — the focus chain stays usable.
_empty = make_main()
check("§6 an empty map does not claim Tab (keyboard accessibility of the window)",
      _empty.view._handle_navigation_key(key_event(Qt.Key.Key_Tab)) is False
      and _empty.view.keyboard_walk_order() == [])

check("§6 the walk reuses the WINDOW's selection path (the sidebar follows it)",
      _view.select_keyboard_node(_D) is True
      and _view.keyboard_current_node() is _D
      and [n.data.id for n in win.selected_nodes()] == ["kbdD"])


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the floating-panel priority (task 7) ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
win = make_main()
check("§7 an empty map shows the first-run hint and the legend yields to it",
      win.empty_state.is_state_visible() is True
      and win.legend_suppressed() is True
      and win.legend.isHidden() is True)
check("§7 the suppression is TEMPORARY — it writes no `ui_legend` and keeps the choice",
      "ui_legend" not in (read_cfg({}) or {}) and win._legend_enabled is True)

add_node(win, "ovl1", "Overlay", "10.30.0.1", 0, 0)
app.processEvents()
check("§7 the first server hides the hint and the legend comes back",
      win.empty_state.is_state_visible() is False
      and win.legend_suppressed() is False
      and win.legend.isHidden() is False)

# An EXPLICIT user choice survives a suppression round-trip.
win._toggle_legend(False)
check("§7 the user's OFF choice is persisted and respected",
      win._legend_enabled is False and win.legend.isHidden() is True
      and read_cfg({}).get("ui_legend") is False)
win._toggle_legend(True)
check("§7 the user's ON choice is persisted",
      win._legend_enabled is True and read_cfg({}).get("ui_legend") is True)

# While the hint is up, the user's ON choice is remembered but the panel stays hidden.
win._remove_node_guarded(win.scene.get_node("ovl1"))
app.processEvents()
check("§7 back to an empty map: the hint returns and the legend yields again",
      win.empty_state.is_state_visible() is True
      and win.legend.isHidden() is True
      and win._legend_enabled is True and read_cfg({}).get("ui_legend") is True)

# The collapse diamond is never covered by a panel.
win.resize(520, 560)
app.processEvents()
_legend = win.legend
_legend.setVisible(True)
_legend.move(max(0, win.view.width() - _legend.width() - 4),
             max(0, win.view.height() - _legend.height() - 4))
win._position_map_collapse_btn()
_btn_rect = QRect(win._map_collapse_btn.geometry())
check("§7 the collapse diamond moves out from under a panel",
      not _btn_rect.intersects(QRect(_legend.geometry())),
      f"button={_btn_rect} legend={QRect(_legend.geometry())}")

win._sync_overlay_priority()
check("§7 the priority rule is ONE resolver (it is safe to call at any time)",
      win._sync_overlay_priority() is None)

# The minimap still yields to the open search bar (the v1.4.2 rule, kept).
win._open_map_search()
app.processEvents()
check("§7 the minimap steps below the OPEN search bar",
      win.minimap.geometry().top() >= win.map_search.geometry().bottom(),
      f"minimap={win.minimap.geometry().top()} bar={win.map_search.geometry().bottom()}")
win._close_map_search()
app.processEvents()
check("§7 ...and returns to the top-right corner when the bar closes",
      win.map_search.isHidden() is True and win.minimap.geometry().top() == 12)


# ════════════════════════════════════════════════════════════════════════════
print("== §8 i18n and the release state ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
check_release_state(ROOT)

_NEW_KEYS = ("settings.search.placeholder", "settings.search.none",
             "settings.hotkeys.filter", "settings.hotkeys.counts",
             "settings.hotkeys.assign_hint", "settings.hotkeys.family.file",
             "settings.hotkeys.family.edit", "settings.hotkeys.family.view",
             "settings.hotkeys.family.node", "settings.hotkeys.family.plugins",
             "settings.hotkeys.family.help", "view.focus_map", "toolbar.more")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in _langs.items()}
check(f"§8 the {len(_NEW_KEYS)} keys of v1.5rc4 are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check(f"§8 the pin moved 630 → {EXPECTED_I18N_KEYS} (13 keys of v1.5rc4, +1 of v1.5, +4 of v1.5.1,"
      f" +13 of v1.5.2, +20 of v1.5.3, +11 of v1.5.4, +14 of v1.5.5, +2 of v1.5.6,"
      f" +29 of v1.5.7, +41 of v1.6, +4 of v1.6.2, +4 of v1.6.3, +3 of v1.6.4)",
      EXPECTED_I18N_KEYS == 789)

check("§8 the family map of the registry is complete (every action has a home)",
      all(HR.action_family(a) in HR.family_order() for a in HR.action_ids())
      and sum(len(v) for v in HR.actions_by_family().values()) == len(HR.action_ids()))

check("§8 the registry grew by the panel/map toggles, the v1.5.3 freshness pair "
      "and the v1.5.5 inventory pair",
      len(HR.action_ids()) == 59
      and HR.default_sequence("view.focus_map") == ""
      and len(HR.empty_default_action_ids()) == 36)

_hub = SettingsDialog(None)
check("§8 the hub's collect() carries 23 config.json keys (this section adds none)",
      len(_hub.collect()) == 23)
_hub.close()

finish()
