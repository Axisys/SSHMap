# -*- coding: utf-8 -*-
"""v1.9.8 — the panels and the consistency: the cells, the stamps, the two menus, the session rows.

The topical file of the release that CLOSES the `1.9` line: every check drives the shipped seams (no
`menu.exec()`, no modal box, no network). §1 the Activity panel and its ring — the level CELL's
vocabulary, the dated STAMP both panels share, the `Clear` question, the wrapping message; §2 the ONE
order of the two server menus (`ui/server_menu.py`, the `Diagnostics ▸` group, the declared
surface-only rows); §3 the Commands rows and the session tab — the full-name tooltip, the measured
Name column, the identity line, the STATE mark and the themed close glyph; §4 the Files Commander's
wording, cells, active-pane header and switch tooltips; §5 the Settings dialog's font row, the
inactive tab ink, the Plugins window's section titles and content-derived columns; §6 the release
state and the parity of the keys of this version."""
import os
import re
import sys

from _common import (EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, VERSION_FORMAT_RE, bootstrap, check,
                     check_i18n_format, check_i18n_parity, check_release_state, clear_cfg, finish,
                     load_i18n_langs, read_cfg, releases_at_least, wait_for)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtWidgets import QApplication, QMessageBox, QTabBar, QToolButton  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
from i18n import t as _t  # noqa: E402
import modules.activity_log as AL  # noqa: E402
import modules.command_library as CL  # noqa: E402
import modules.sftp_pane_listing as PL  # noqa: E402
import modules.sftp_tab as STAB  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
import modules.terminal_page as TP  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.plugins_panel as PP  # noqa: E402
import ui.server_menu as SM  # noqa: E402
import ui.theme_qss as TQ  # noqa: E402
from models.server import ServerData  # noqa: E402

from _fakes import FakeSSHThread as _FakeThread  # noqa: E402

# every session of this file runs on the fake thread (the `_fakes.py` seam): a REAL one would keep a
# socket attempt alive past the last check — which is exactly how a green file exits 0xC0000409.
_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread
from ui.activity_panel import ActivityPanel  # noqa: E402
from ui.icons import draw_icon, get_icon  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402
from ui.sidebar import CONTEXT_MENU_ACTIONS, CONTEXT_MENU_ITEMS  # noqa: E402

LANGS = load_i18n_langs(ROOT)
_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — the "it lives in ONE place" audits."""
    if parts not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
            _SRC[parts] = handle.read()
    return _SRC[parts]


def make_window():
    """An offscreen MainWindow with the timers stopped and NO status checker (hermetic)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    win.resize(1000, 700)
    win.show()
    app.processEvents()
    return win


def menu_rows(menu, deep=True):
    """The rows of a menu (and, with `deep`, of its submenus) as `(text, submenu-texts)` pairs."""
    out = []
    for action in menu.actions():
        if action.isSeparator():
            out.append(None)
            continue
        sub = action.menu() if deep else None
        out.append((action.text(), menu_rows(sub, deep=False) if sub is not None else None))
    return out


def answer_questions(answer):
    """Stub the ONE question dialog (the module-attribute pattern) and return the undo callable."""
    real = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: answer)
    return lambda: setattr(QMessageBox, "question", real)


def icon_has_ink(icon, size=20) -> bool:
    """Is any pixel of the icon inked? (a QIcon is a value — the activity-mark test's own seam)."""
    image = icon.pixmap(size, size).toImage()
    return any(image.pixelColor(x, y).alpha() > 0
               for y in range(image.height()) for x in range(image.width()))


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the Activity panel: the cells, the stamp, the ask ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
buffer = AL.reset_activity_buffer()
buffer.append("an info line", level="INFO", source="tests.consistency")
buffer.append("a warning line", level="WARNING", source="tests.consistency")
buffer.append("an error line", level="ERROR", source="tests.consistency")
AL.record_status_message("the interface said so")
_events = {e.message: e for e in buffer.events()}

check("§1 the ROW STAMP carries the DATE (a history a review returns to): "
      "`%Y-%m-%d %H:%M:%S`",
      AL.STAMP_FORMAT == "%Y-%m-%d %H:%M:%S"
      and len(AL.stamp_text(_events["an info line"].timestamp)) == 19
      and AL.stamp_text(_events["an info line"].timestamp)[4] == "-"
      and AL.stamp_text(_events["an info line"].timestamp)[10] == " "
      and _events["an info line"].time_text() == AL.stamp_text(_events["an info line"].timestamp),
      AL.stamp_text(_events["an info line"].timestamp))
check("§1 the renderer is PURE and never raises (a broken timestamp answers an empty stamp)",
      AL.stamp_text(0.0) and AL.stamp_text(None) == "" and AL.stamp_text("nonsense") == ""
      and AL.stamp_text(_events["an info line"].timestamp, "%H:%M") ==
      _events["an info line"].time_text("%H:%M"))
check("§1 the level CELL's vocabulary is the ONE the filter renders (`level_key`)",
      AL.level_key(_events["an info line"]) == "info"
      and AL.level_key(_events["a warning line"]) == "warning"
      and AL.level_key(_events["an error line"]) == "error"
      and AL.level_key(_events["the interface said so"]) == "status"
      and AL.level_key(None) == "all",
      str([AL.level_key(e) for e in _events.values()]))
_critical = AL.ActivityEvent(99, 0.0, "CRITICAL", "m", "boom")
check("§1 ...and a CRITICAL record is the filter's `error` (one question, one word)",
      AL.level_key(_critical) == "error"
      and AL.matches_level(_critical, "error") and not AL.matches_level(_critical, "warning"))

win = make_window()
panel = win.activity_panel
win.act_show_activity.setChecked(True)
wait_for(lambda: panel.is_shown() and panel.row_count() > 0)
_rows = panel.rows_text()
check("§1 the panel renders the ring and the LEVEL cell wears the panel's own word",
      len(_rows) == 4
      and _rows[0][1] == _t("activity.level.status")
      and _rows[1][1] == _t("activity.level.error")
      and _rows[2][1] == _t("activity.level.warning")
      and _rows[3][1] == _t("activity.level.info"),
      str(_rows))
check("§1 ...and the ring's machine spelling (`UI`) never reaches a cell",
      all(row[1] != AL.LEVEL_STATUS for row in _rows)
      and AL.LEVEL_STATUS == "UI" and 'f"activity.level.{key}"' in _src("ui", "activity_panel.py"))
check("§1 the stamp column fits the full stamp it now holds (measured, with a declared floor)",
      panel.tree.columnWidth(0) == panel.stamp_column_width()
      and panel.tree.columnWidth(0) >= panel.tree.fontMetrics().horizontalAdvance(
          AL.stamp_text(_events["an info line"].timestamp))
      and panel.COLUMN_WIDTHS[0] == 152,
      f"{panel.tree.columnWidth(0)} px")
check("§1 a long message WRAPS (the row grows) and its full text is the tooltip",
      panel.tree.wordWrap() is True and panel.tree.uniformRowHeights() is False
      and panel.tree.topLevelItem(0).toolTip(3) == "the interface said so",
      f"wrap={panel.tree.wordWrap()}")
_asks = []
_restore = answer_questions(QMessageBox.No)
try:
    panel.clear()
finally:
    _restore()
check("§1 `Clear` ASKS first (a refusal keeps the history AND the rows)",
      len(AL.get_activity_buffer()) == 4 and panel.row_count() == 4)
_restore = answer_questions(QMessageBox.Yes)
try:
    panel.clear()
finally:
    _restore()
check("§1 ...and the answer YES empties the RING, not only the rows",
      len(AL.get_activity_buffer()) == 0 and panel.row_count() == 0)
check("§1 the `Clear` tooltip is a sentence of its own, never the button's label again",
      panel.clear_btn.toolTip() == _t("activity.clear_hint")
      and panel.clear_btn.toolTip() != panel.clear_btn.text()
      and "activity.clear_hint" in _src("ui", "activity_panel.py"))
check("§1 the ONE ask is declared for BOTH panels (one title key, two bodies)",
      all(str(LANGS[code].get(key) or "").strip() for code in LANGS
          for key in ("dialog.confirm_clear", "activity.clear_confirm",
                      "activity.clear_hint", "plugins.window.clear_confirm",
                      "plugins.window.clear_hint")))

# The Plugins window shares the ORDINARY renderer and gets the same guard.
_pp = PP.PluginsPanel(manager=None)
_pp.record_events([{"kind": "reloaded", "count": 2}])
_row = _pp.event_rows()[0]
check("§1 the Plugins window's stamp is the SAME renderer (its export carries the date too)",
      _row[0] == AL.stamp_text(_pp.visible_events()[0].timestamp)
      and _row[0].count("-") == 2 and len(_row[0]) == 19
      and _row[0] in _pp.export_text() and _pp.export_text().split("  ", 1)[0] == _row[0],
      f"{_row[0]!r}")
check("§1 ...and its `Clear` asks with its OWN sentence and tooltip",
      _pp.clear_btn.toolTip() == _t("plugins.window.clear_hint")
      and _pp.clear_btn.toolTip() != _pp.clear_btn.text())
_restore = answer_questions(QMessageBox.No)
try:
    _pp.clear()
finally:
    _restore()
check("§1 a refusal keeps the whole session ring", len(_pp.ring) == 1 and _pp.row_count() == 1)
_restore = answer_questions(QMessageBox.Yes)
try:
    _pp.clear()
finally:
    _restore()
check("§1 ...and YES empties it", len(_pp.ring) == 0 and _pp.row_count() == 0)
_pp.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the server menu: ONE order, one case, one Diagnostics group ==")
# ════════════════════════════════════════════════════════════════════════════

_node = win.scene.add_server(ServerData(id="cons-1", alias="menus", host="192.0.2.44",
                                        user="u", x=100.0, y=100.0))
app.processEvents()
_card = menu_rows(win.view.build_context_menu(_node.card_rect_scene().center()))
_side_menu = MW.QMenu(win)
win.sidebar.fill_context_menu(_side_menu, _node)
_side = menu_rows(_side_menu)


def flat(rows):
    """The top-level texts of a `menu_rows()` list, separators dropped."""
    return [row[0] for row in rows if row is not None]


def sub_rows(rows, label):
    """The texts inside the submenu row named `label` ([] — it is not there)."""
    for row in rows:
        if row is not None and row[0] == label and row[1] is not None:
            return [text for text, _sub in (item for item in row[1] if item is not None)]
    return []


_declared_card = [_t(row[1]) for row in SM.rows(SM.CARD) if row is not None]
_declared_side = [_t(row[1]) for row in SM.rows(SM.SIDEBAR) if row is not None]
check("§2 the card menu renders the SHARED declaration, row for row and in its order",
      flat(_card) == _declared_card, f"got={flat(_card)}")
check("§2 the sidebar menu renders the SAME rows, in the SAME order",
      flat(_side) == _declared_side, f"got={flat(_side)}")
check("§2 the diagnostic verbs are ONE `Diagnostics ▸` group on BOTH surfaces",
      _t("ctx.diagnostics") in flat(_card) and _t("ctx.diagnostics") in flat(_side)
      and sub_rows(_card, _t("ctx.diagnostics"))
      == [_t(key) for _key, key in SM.DIAGNOSTIC_ITEMS]
      == sub_rows(_side, _t("ctx.diagnostics"))
      and not any(_t(key) in flat(_card) for _key, key in SM.DIAGNOSTIC_ITEMS),
      str(sub_rows(_card, _t("ctx.diagnostics"))))
check("§2 the case is ONE inside each menu (`Duplicate Server` beside `Delete Server`)",
      LANGS["en"]["ctx.duplicate_server"] == "Duplicate Server"
      and _t("ctx.duplicate_server") in flat(_card)
      and _t("ctx.delete_server") in flat(_card)
      and not any(text == "Duplicate server" for text in flat(_card)),
      LANGS["en"]["ctx.duplicate_server"])
check("§2 the rows only ONE surface offers are DECLARED, not levelled",
      SM.keys(SM.CARD) != SM.keys(SM.SIDEBAR)
      and "collapse" in SM.keys(SM.CARD) and "collapse" not in SM.keys(SM.SIDEBAR)
      and "duplicate" in SM.keys(SM.CARD) and "duplicate" not in SM.keys(SM.SIDEBAR)
      and "reveal" in SM.keys(SM.SIDEBAR) and "reveal" not in SM.keys(SM.CARD)
      and _t("ctx.collapse_server") in flat(_card)
      and _t("ctx.reveal_on_map") in flat(_side)
      and _t("ctx.reveal_on_map") not in flat(_card)
      and _t("ctx.collapse_server") not in flat(_side),
      f"card={SM.keys(SM.CARD)} sidebar={SM.keys(SM.SIDEBAR)}")
check("§2 the sidebar's own declaration is DERIVED from the table (no second copy)",
      CONTEXT_MENU_ITEMS == tuple(row for row in SM.rows(SM.SIDEBAR) if row is None or
                                  row[0] != "quick_launch")
      and CONTEXT_MENU_ACTIONS == tuple(
          [row[0] for row in SM.rows(SM.SIDEBAR)
           if row is not None and row[0] not in (SM.DIAGNOSTICS_KEY, "quick_launch")]
          + [key for key, _k in SM.DIAGNOSTIC_ITEMS]),
      str(CONTEXT_MENU_ITEMS))
check("§2 the imperative the review asked for is a NEW key, and the old one SURVIVES",
      LANGS["en"]["ctx.diagnose_offline"] == "Diagnose Offline"
      and all(str(data.get("ctx.diagnose_offline") or "").strip() for data in LANGS.values())
      and all(str(data.get("ctx.diagnose") or "").strip() for data in LANGS.values())
      and _t("ctx.diagnose_offline") in sub_rows(_card, _t("ctx.diagnostics")),
      LANGS["en"]["ctx.diagnose_offline"])
check("§2 the registry row and the Edit menu name the verb the same way (ONE name, three rows)",
      __import__("ui.hotkey_registry", fromlist=["x"]).HOTKEY_ACTIONS["node.diagnose"]["label"]
      == "ctx.diagnose_offline"
      and any(k == "ctx.diagnose_offline" for _w, k in win._menu_i18n)
      and 'ctx.diagnose_offline' in _src("graphics", "map_view.py")
      and 'ctx.diagnose_offline' in _src("ui", "main_window_node_ops.py")
      and 'ctx.diagnose_offline' in _src("ui", "server_menu.py")
      and 'ctx.diagnose_offline' in _src("ui", "main_window_menubar.py"))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the Commands rows and the session tab ==")
# ════════════════════════════════════════════════════════════════════════════

_lib = CL.CommandLibraryPanel()
_lib.reload()
app.processEvents()
_item = None
for _i in range(_lib.tree.topLevelItemCount()):
    _cat = _lib.tree.topLevelItem(_i)
    if _cat.childCount():
        _item = _cat.child(0)
        break
_longest = max((_lib.tree.topLevelItem(i).child(j).text(0)
                for i in range(_lib.tree.topLevelItemCount())
                for j in range(_lib.tree.topLevelItem(i).childCount())), key=len, default="")
check("§3 a saved command's row carries its FULL name and its command as tooltips",
      _item is not None and _item.toolTip(0) == _item.text(0)
      and _item.toolTip(1) == _item.text(1) and _item.toolTip(0),
      f"{_item.toolTip(0)!r}" if _item is not None else "no rows")
check("§3 the Name column is MEASURED from the content (the shipped seed needs 120–288 px)",
      _lib.tree.columnWidth(0) >= min(_lib.tree.fontMetrics().horizontalAdvance(_longest),
                                      CL.CMDLIB_NAME_COLUMN_MAX)
      and _lib.tree.columnWidth(0) > 100,
      f"{_lib.tree.columnWidth(0)} px for {_longest!r}")
check("§3 the Commands header's two icon-only buttons name themselves",
      _lib._file_btn.toolTip() and _lib._collapse_btn.toolTip()
      and not _lib._file_btn.icon().isNull()
      and _lib._file_btn.text() == "" and _lib._collapse_btn.text() == "",
      f"file={_lib._file_btn.toolTip()!r}")
check("§3 the header's glyphs come from the ONE icon set (a theme switch can repaint them)",
      all(not draw_icon(name).isNull() and icon_has_ink(draw_icon(name))
          for name in ("menu_dots", "split", "files", "close"))
      and "refresh_button_icon(self._file_btn, \"menu_dots\")" in _src("modules",
                                                                      "command_library.py"))
_lib.deleteLater()

check("§3 `Split Terminal` and `Files Commander` wear a glyph and the corner stylesheet",
      not get_icon("split").isNull() and not get_icon("files").isNull()
      and ":checked" in TQ.style("corner.button") and ":hover" in TQ.style("corner.button")
      and "apply_corner_style(btn)" in _src("modules", "terminal_split.py")
      and "apply_corner_style(self.btn)" in _src("modules", "sftp_commander_corner.py"),
      TQ.style("corner.button")[:60])

_win2 = MW.MainWindow() if False else make_window()
_node2 = _win2.scene.add_server(ServerData(id="cons-t", alias="tabby", host="192.0.2.45",
                                           user="root", x=200.0, y=200.0))
app.processEvents()
_term = _win2._spawn_terminal_window(_node2)
app.processEvents()
_page = _term.session_tabs.widget(0)
check("§3 the session tab's TOOLTIP names the alias's identity (`user@ip:port` beside it)",
      TP.session_identity(_page) == "root@192.0.2.45"
      and _t("terminal.tab_identity", identity="root@192.0.2.45")
      in _term.session_tabs.tabToolTip(0)
      and _term.session_tabs.tabText(0) == "tabby",
      _term.session_tabs.tabToolTip(0))
check("§3 the identity reader is PURE (ip over host, no dangling `@`/`:` and nothing without data)",
      TP.session_identity(_page) == "root@192.0.2.45"
      and TP.session_identity(type("P", (), {"server_data": ServerData(
          id="x", alias="a", host="h.example", user="")})()) == "h.example"
      and TP.session_identity(type("P", (), {"server_data": ServerData(
          id="x", alias="a", host="", user="u")})()) == ""
      and TP.session_identity(object()) == "")
check("§3 the tab's fixed icon slot carries the STATE of the session (the cards' own shapes)",
      TP.session_mark_status(_page) == TP.SESSION_STATE_ONLINE
      and icon_has_ink(TP.session_tab_icon(_page))
      and TP.SESSION_STATE_OFFLINE == "offline" and TP.SESSION_STATE_WARN == "warn")
_page._session_ended = True
TP.render_session_activity(_term.session_tabs, _page, _t)
check("§3 ...and a dead channel switches it to `offline`, the ACTIVITY mark winning while set",
      TP.session_mark_status(_page) == TP.SESSION_STATE_OFFLINE
      and TP.session_tab_icon(_page) is not TP.activity_tab_icon(True)
      and (setattr(_page, "_session_ended", False), _page.set_activity(True),
          TP.session_tab_icon(_page) is TP.activity_tab_icon(True))[-1]
      and (_page.set_activity(False), True)[-1])
check("§3 the tab's close glyph is the icon set's own (never the style's red cross)",
      isinstance(_term.session_tabs.tabBar().tabButton(
          0, QTabBar.ButtonPosition.RightSide), QToolButton)
      and not _term.session_tabs.tabBar().tabButton(
          0, QTabBar.ButtonPosition.RightSide).icon().isNull()
      and _term.session_tabs.tabsClosable() is True
      and "refresh_button_icon(button, \"close\")" in _src("modules", "terminal_page.py"))
check("§3 the close button re-emits the container's ONE close signal (no second close path)",
      "tabCloseRequested.emit" in _src("modules", "terminal_page.py")
      and "def _emit_tab_close" in _src("modules", "terminal_page.py"))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the Files Commander: one wording, the cells, the active header ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the source switch CAPTIONS the control while the header names the source (one thing, one name)",
      LANGS["en"]["sftp.local.source"] == "Source:"
      and all(LANGS[code]["sftp.local.source"] != LANGS[code]["sftp.local.this_computer"]
              for code in LANGS)
      and all(str(LANGS[code].get("sftp.local.source") or "").strip() for code in LANGS)
      and len(LANGS["en"]["sftp.local.source"]) < len(LANGS["en"]["sftp.local.this_computer"]),
      LANGS["en"]["sftp.local.source"])
check("§4 ...which is what keeps the terminal window's 640 px floor (the switch sets the pane minimum)",
      LANGS["en"]["sftp.local.source"] == "Source:"
      and "sftp.source_button" in TQ.style_names()
      and "padding: 1px 3px" in TQ.style("sftp.source_button"),
      TQ.style("sftp.source_button").splitlines()[1] if TQ.style("sftp.source_button") else "")
check("§4 a column that does not apply to a row carries the declared DASH",
      PL.DIR_CELL == "—"
      and all(str(LANGS[code].get("sftp.column_size") or "").strip() for code in LANGS)
      and 'DIR_CELL if is_dir' in _src("modules", "sftp_pane_listing.py")
      and 'setText(1, ""' not in _src("modules", "sftp_pane_listing.py"))
check("§4 the ACTIVE pane is marked on its HEADER, not only by its border",
      PL.ACTIVE_PANE_MARK == "▸" and "header_text_marked" in _src("modules",
                                                                 "sftp_pane_listing.py")
      and 'getattr(self, "_active", False)' in _src("modules", "sftp_pane_listing.py")
      and "self._active = bool(on)" in _src("modules", "sftp_tab.py")
      and "_sync_header()" in _src("modules", "sftp_tab.py"))
_bare = STAB._SftpPane(None)
_bare.set_active(True)
_marked = _bare.header_label.text()
_bare.set_active(False)
check("§4 ...driven: the mark appears on the active pane and leaves it again",
      _marked == f"{PL.ACTIVE_PANE_MARK} {_bare.header_text()}"
      and _bare.header_label.text() == _bare.header_text() == _bare.header_text_marked(),
      f"active={_marked!r} idle={_bare.header_label.text()!r}")
_bare.deleteLater()

check("§4 all THREE source states carry a tooltip (the elevated one had the only one)",
      all(str(LANGS[code].get(key) or "").strip() for code in LANGS
          for key in ("sftp.elevated.tooltip", "sftp.local.server_tooltip",
                      "sftp.local.local_tooltip"))
      and "btn_server.setToolTip(_t(\"sftp.local.server_tooltip\"))" in _src("modules",
                                                                            "sftp_tab.py"))
check("§4 the inactive states gain a DECLARED contrast in both themes (never a literal colour)",
      "sftp.source_button" in TQ.style_names()
      and "QToolButton:checked" in TQ.style("sftp.source_button")
      and "QToolButton:hover" in TQ.style("sftp.source_button")
      and "theme_qss.refresh(button, \"sftp.source_button\")" in _src("modules", "sftp_tab.py")
      and "sftp.source_button" in _src("ui", "theme_qss.py"))


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the Settings dialog and the Plugins window ==")
# ════════════════════════════════════════════════════════════════════════════

_hub = SettingsDialog(None)
check("§5 the `UI font family` field says what it expects (a placeholder and the rule in words)",
      _hub.ui_font_family_edit.placeholderText()
      == _t("settings.general.ui_font_family_placeholder")
      and bool(_hub.ui_font_family_edit.placeholderText())
      and _hub.ui_font_family_edit.toolTip() == _t("settings.general.ui_font_family_hint"))
check("§5 the size label is the Terminal tab's OWN spelling, and `0 = system` moved to the tooltip",
      _hub._lbl_ui_font_size.text() == _hub._lbl_font_size.text()
      and _hub._lbl_ui_font_size.text() == _t("settings.terminal.font_size")
      and "0" not in _hub._lbl_ui_font_size.text()
      and _hub.ui_font_size_spin.toolTip() == _t("settings.general.ui_font_size_hint")
      and "0" in _hub.ui_font_size_spin.toolTip(),
      f"{_hub._lbl_ui_font_size.text()!r}")
check("§5 ...and a language switch re-texts the three of them (the container's own retranslate)",
      (i18n.set_language("ru"), _hub.retranslate(), True)[-1]
      and _hub._lbl_ui_font_size.text() == LANGS["ru"]["settings.terminal.font_size"]
      and _hub.ui_font_family_edit.placeholderText()
      == LANGS["ru"]["settings.general.ui_font_family_placeholder"]
      and (i18n.set_language("en"), _hub.retranslate(), True)[-1],
      _hub._lbl_ui_font_size.text())
_hub.close()
check("§5 an INACTIVE tab label keeps the primary ink and drops the muted tone",
      f"QTabBar::tab:!selected {{\n    color: {__import__('ui.theme', fromlist=['t']).THEME.text_primary};"
      in TQ.build_qss()
      and "color: {t.text_muted};" not in TQ.build_qss().split("QTabBar::tab:!selected")[1][:40],
      TQ.build_qss().split("QTabBar::tab:!selected")[1][:40])

_plugins = PP.PluginsPanel(manager=None)
check("§5 the three captions are styled as SECTION titles (the ONE registry, no literal QSS)",
      all(caption.styleSheet() == TQ.style("heading") and "bold" in caption.styleSheet()
          for caption in (_plugins.plugin_caption, _plugins.server_caption, _plugins.event_caption))
      and "_apply_caption_style" in _src("ui", "plugins_panel.py"),
      _plugins.plugin_caption.styleSheet())
check("§5 the Run button's explanation is INLINE, in the shipped sentence (no new key)",
      _plugins.run_hint.text() == _t("plugins.window.checked_hint")
      and _plugins.run_hint.isHidden() is bool(_plugins.run_btn.isEnabled())
      and "plugins.window.checked_hint" in _src("ui", "plugins_panel.py"))
check("§5 the two short columns are MEASURED from the content, not a literal width",
      PP.MEASURED_COLUMN_MAX == 240
      and "resizeColumnToContents(index)" in _src("ui", "plugins_panel.py")
      and "(160, 60)" not in _src("ui", "plugins_panel.py")
      and "(105, 115, 65, 50)" not in _src("ui", "plugins_panel.py")
      and _plugins.plugin_tree.header().stretchLastSection() is False
      and _plugins.event_tree.header().stretchLastSection() is True)
_long = PP.QTreeWidgetItem() if False else None
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem  # noqa: E402

_probe_tree = QTreeWidget()
_probe_tree.setColumnCount(2)
_item = QTreeWidgetItem(_probe_tree)
_item.setText(0, "a very long plugin name that a literal 160 px would cut")
_item.setText(1, "2026.10.9-beta.1")
PP.PluginsPanel._fit_columns(_probe_tree, 2)
check("§5 ...so a value nobody measured is no longer cut (and the growth is CAPPED)",
      _probe_tree.columnWidth(0) > 160
      and _probe_tree.columnWidth(0) <= PP.MEASURED_COLUMN_MAX
      and _probe_tree.columnWidth(1) >= _probe_tree.fontMetrics().horizontalAdvance(
          "2026.10.9-beta.1"),
      f"{_probe_tree.columnWidth(0)} / {_probe_tree.columnWidth(1)}")
_plugins.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

win._dirty = False
win.close()
_page.shutdown()
_win2._dirty = False
_win2.close()

check_release_state(ROOT)
check("§6 the pin is the release this file describes (the `1.9` line's LAST version)",
      EXPECTED_APP_VERSION == "1.9.8" and releases_at_least(EXPECTED_APP_VERSION, "1.9.7")
      and VERSION_FORMAT_RE.fullmatch(EXPECTED_APP_VERSION) is not None,
      EXPECTED_APP_VERSION)
check_i18n_parity(LANGS)
check_i18n_format(LANGS)
_NEW_KEYS = ("activity.clear_confirm", "activity.clear_hint", "dialog.confirm_clear",
             "plugins.window.clear_confirm", "plugins.window.clear_hint",
             "ctx.diagnostics", "ctx.diagnose_offline",
             "terminal.tab_identity",
             "sftp.local.server_tooltip", "sftp.local.local_tooltip",
             "settings.general.ui_font_family_placeholder",
             "settings.general.ui_font_family_hint", "settings.general.ui_font_size_hint")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in LANGS.items()}
check(f"§6 the {len(_NEW_KEYS)} keys of v1.9.8 are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§6 ...and they are the keys the CODE really asks for (the version's own vocabulary)",
      all(key in _src("ui", "activity_panel.py") or key in _src("ui", "plugins_panel.py")
          or key in _src("ui", "server_menu.py") or key in _src("modules", "terminal_page.py")
          or key in _src("modules", "sftp_tab.py") or key in _src("ui", "settings_dialog.py")
          for key in _NEW_KEYS)
      and "_t(\"ctx.diagnostics\")" in _src("graphics", "map_view.py"))
check("§6 no new dependency, no second config file, no pytest",
      all(f"{d}>=" in _src("requirements.txt")
          for d in ("PySide6", "paramiko", "keyring", "wcwidth"))
      and not re.search(r"^\s*(?!PySide6|paramiko|keyring|wcwidth|#)[A-Za-z][\w.-]*\s*[><=]",
                        _src("requirements.txt"), re.M)
      and not os.path.exists(os.path.join(ROOT, "pytest.ini"))
      and "pytest" not in _src("pyproject.toml"))
check("§6 VERSION_FORMAT did NOT move (no schema change in this version)",
      __import__("version").VERSION_FORMAT == "0.9")
check("§6 the plan LOST this version (ROADMAP.md's version sections are the open ones)",
      "## v1.9.8" not in open(os.path.join(ROOT, "ROADMAP.md"), encoding="utf-8").read())
check("§6 the topical file is listed by the suite map (tests/INDEX.md regenerated)",
      "test_ui_consistency" in open(os.path.join(ROOT, "tests", "INDEX.md"),
                                    encoding="utf-8").read())
check("§6 the 1.9 line's rollover PAIR exists (the history and its details beside it)",
      os.path.exists(os.path.join(ROOT, "CHANGELOG_HISTORY_V198.md"))
      and os.path.exists(os.path.join(ROOT, "CHANGELOG_DETAILS_V198.md")))

finish()
