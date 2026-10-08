# -*- coding: utf-8 -*-
"""v1.6.7 — The bookmarks: ONE application-level place for the links the team uses.

A link that belongs to nobody's server had no home (the quick launch of a card is PER SERVER), so the
release adds ONE user file (`~/.sshmap/bookmarks.json`), ONE floating panel over the canvas and ONE
editor — all three built on shipped precedents (the `commands.json` store, the legend/minimap panel
family, the quick-launch editor) and inventing nothing new.
§1 the STORE (`modules/bookmarks.py`): the path, the `utf-8-sig` read, the atomic MERGE-write (a foreign
top-level key survives), the sanitizer of the PROJECT reused, add / update / remove / move, the declared cap, the POSITIONAL rule that keeps a foreign `command` entry where it is, and the broken-file path (skipped, never overwritten); §2 the PANEL (the rows with the URL as the second channel, the filter, the fold, the ONE opener behind a callback); §3 the SWITCH (ONE registry action with an EMPTY default, the checkable View item, the toolbar mirror, the owner-written `ui_bookmarks*` keys); §4 the EDITOR (it writes ONLY `url` entries); §5 the WINDOW (the toggle and its persistence, the snap, `retranslate()` / `refresh_theme()`, the real opener with its failure sentence); §6 the i18n parity and the release state."""
import json
import os
import re
import sys
import webbrowser

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, clear_cfg, merge_cfg, read_cfg,
                     write_cfg, window_family_sources, window_func_body,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS,
                     releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox

app = QApplication(sys.argv)

# Network is forbidden in tests: the status probes return the result instantly.
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import i18n
import modules.bookmarks as BM
from modules.bookmarks import BookmarkStore
import ui.hotkey_registry as HR
import ui.main_window as MW
from models.server import ServerData
from ui.bookmark_panel import BookmarkPanel
from ui.icons import get_icon
from ui.settings_dialog import SettingsDialog

# ── the harness (the test_view_toggles pattern) ─────────────────────────────
boxes = []

from _fakes import FakeSSHThread as _FakeSSHThreadBase, QuestionStub

MW.QMessageBox.question = QuestionStub(
    QMessageBox.Discard,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",) + tuple(a[1:2])))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))

import modules.ssh_terminal as ST


class _FakeThread(_FakeSSHThreadBase):
    """An idle thread (the same API as SSHTerminalThread) without a channel."""


ST.SSHTerminalThread = _FakeThread


def make_main():
    """An offscreen MainWindow with a stopped autosave timer (determinism)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    return w


def close_window(w):
    w._dirty = False
    w._undo_baseline_dirty = False
    w.close()
    app.processEvents()


def write_json(path, doc, encoding="utf-8"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the store: the file, the read, the merge-write ==")
# ════════════════════════════════════════════════════════════════════════════

_SRC = open(os.path.join(ROOT, "modules", "bookmarks.py"), encoding="utf-8").read()
_BOOKMARKS_SRC = window_family_sources(ROOT)["ui/main_window_bookmarks.py"]
check("§1 the store is headless (no PySide6 import — the module is pure Python)",
      "PySide6" not in _SRC)
check("§1 the sanitizer of the PROJECT is reused (no second copy of the shape)",
      "sanitize_quick_launch" in _SRC and "def sanitize" not in _SRC)
check("§1 the default path is ~/.sshmap/bookmarks.json (next to config.json)",
      BM.default_store_path() == os.path.join(os.path.expanduser("~"), ".sshmap",
                                              "bookmarks.json"),
      BM.default_store_path())
check("§1 the module-level singleton is ONE store and it points at the default file",
      BM.get_bookmark_store() is BM.get_bookmark_store()
      and BM.get_bookmark_store().path == BM.default_store_path())

STORE_PATH = os.path.join(WORK, "bm_store", "bookmarks.json")
store = BookmarkStore(path=STORE_PATH)
check("§1 a missing file reads as an EMPTY list (and the read never creates it)",
      store.load() == [] and store.load_urls() == [] and not os.path.exists(STORE_PATH))
check("§1 a foreign `command` entry is loaded like any other (the panel filters it later)",
      store.save([{"type": "command", "name": "uptime", "value": "uptime"},
                  {"type": "url", "name": "Wiki", "value": "https://wiki.example.com"}])
      and len(store.load()) == 2 and store.load_urls() == [
          {"type": "url", "name": "Wiki", "value": "https://wiki.example.com"}],
      str(store.load()))
check("§1 the document is ONE list under the declared key",
      read_json(STORE_PATH) == {"bookmarks": store.load()}, str(read_json(STORE_PATH)))

# the merge-write: a foreign TOP-LEVEL key of the document survives
write_json(STORE_PATH, {"_note": "hand edited", "bookmarks": store.load()})
check("§1 a foreign top-level key survives a save (the merge-write rule)",
      store.add("Grafana", "https://grafana.example.com")
      and read_json(STORE_PATH).get("_note") == "hand edited",
      str(read_json(STORE_PATH)))

# the operations
check("§1 add() appends and answers False for an unusable pair",
      store.add("Ticket queue", "https://tickets.example.com")
      and store.load_urls()[-1]["name"] == "Ticket queue"
      and store.add("", "https://x.example.com") is False
      and store.add("X", "") is False)
check("§1 update() replaces IN PLACE (the position does not move)",
      store.update(1, "Grafana (prod)", "https://grafana.example.com/Prod")
      and [e["name"] for e in store.load_urls()] == ["Wiki", "Grafana (prod)", "Ticket queue"]
      and store.update(99, "nope", "https://nope.example.com") is False)
check("§1 move() swaps two entries and REFUSES a move past either end",
      store.move(0, 1) and [e["name"] for e in store.load_urls()][:2] == ["Grafana (prod)", "Wiki"]
      and store.move(0, -1) is False and store.move(2, 1) is False)
check("§1 remove() drops one entry and refuses a bad index",
      store.remove(0) and [e["name"] for e in store.load_urls()] == ["Wiki", "Ticket queue"]
      and store.remove(42) is False)
check("§1 a `command` entry survives every URL write (it is never listed and never lost)",
      [e["type"] for e in store.load()] == ["command", "url", "url"]
      and store.load()[0]["name"] == "uptime",
      str(store.load()))

# the cap: refuse the ADD instead of dropping an entry
full = BookmarkStore(path=os.path.join(WORK, "bm_store", "full.json"))
_urls = [{"type": "url", "name": f"b{i}", "value": f"https://h.example.com/{i}"}
         for i in range(BM.MAX_BOOKMARKS)]
full.save(_urls)
check(f"§1 the declared cap is {BM.MAX_BOOKMARKS} and is_full() reports it",
      full.is_full() and len(full.load_urls()) == BM.MAX_BOOKMARKS)
check("§1 add() at the cap answers False instead of silently dropping an entry",
      full.add("one more", "https://one.example.com") is False
      and len(full.load_urls()) == BM.MAX_BOOKMARKS)

# the broken / hand-edited file paths
broken = BookmarkStore(path=os.path.join(WORK, "bm_store", "broken.json"))
with open(broken.path, "w", encoding="utf-8") as f:
    f.write("{ this is not json")
check("§1 a broken file is SKIPPED with an empty list (never a crash)",
      broken.load() == [] and broken.load_urls() == [])
check("§1 the read does not overwrite the broken file (user data is never clobbered)",
      open(broken.path, encoding="utf-8").read() == "{ this is not json")

junk = BookmarkStore(path=os.path.join(WORK, "bm_store", "junk.json"))
write_json(junk.path, {"bookmarks": [
    {"type": "url", "name": "Good", "value": "https://good.example.com"},
    "a bare string",
    {"type": "url", "name": "", "value": "https://nameless.example.com"},
    {"type": "url", "name": "No value", "value": None},
    {"type": "url", "name": "  Kept  ", "value": "  https://kept.example.com  "},
]})
check("§1 a hand-edited junk entry is dropped WITHOUT losing the rest",
      [e["name"] for e in junk.load()] == ["Good", "Kept"], str(junk.load()))
check("§1 the surviving entries are stripped by the project's sanitizer",
      junk.load()[1]["value"] == "https://kept.example.com")

bare = BookmarkStore(path=os.path.join(WORK, "bm_store", "bare.json"))
write_json(bare.path, [{"type": "url", "name": "Bare", "value": "https://bare.example.com"}])
check("§1 a bare JSON LIST is accepted as the document (a hand-edited file)",
      [e["name"] for e in bare.load_urls()] == ["Bare"])

bom = BookmarkStore(path=os.path.join(WORK, "bm_store", "bom.json"))
os.makedirs(os.path.dirname(bom.path), exist_ok=True)
with open(bom.path, "wb") as f:
    f.write(b"\xef\xbb\xbf" + json.dumps(
        {"bookmarks": [{"type": "url", "name": "BOM", "value": "https://bom.example.com"}]}
    ).encode("utf-8"))
check("§1 a \"UTF-8 with BOM\" file loads (the utf-8-sig rule of every user file)",
      [e["name"] for e in bom.load_urls()] == ["BOM"])
check("§1 a write leaves no *.tmp behind (the atomic-rename rule)",
      store.add("tmp-check", "https://tmp.example.com")
      and not [n for n in os.listdir(os.path.dirname(STORE_PATH)) if n.endswith(".tmp")])

# the pure filter
_entries = [{"type": "url", "name": "Wiki", "value": "https://wiki.example.com"},
            {"type": "url", "name": "Grafana", "value": "https://mon.example.com:3000"},
            {"type": "url", "name": "Tickets", "value": "https://JIRA.example.com"}]
check("§1 filter_entries() is PURE and matches the NAME or the URL, case-insensitively",
      [e["name"] for e in BM.filter_entries(_entries, "wik")] == ["Wiki"]
      and [e["name"] for e in BM.filter_entries(_entries, "MON.")] == ["Grafana"]
      and [e["name"] for e in BM.filter_entries(_entries, "jira")] == ["Tickets"])
check("§1 an empty query answers every entry (no filter and a cleared field are one state)",
      BM.filter_entries(_entries, "") == _entries and BM.filter_entries(_entries, "   ") == _entries
      and BM.filter_entries(_entries, None) == _entries
      and BM.filter_entries(_entries, "nothing here") == [])
check("§1 url_entries() is the panel's declared SCOPE (a `command` is never offered)",
      BM.url_entries([{"type": "command", "name": "c", "value": "c"},
                      {"type": "url", "name": "u", "value": "u"}]) == [
          {"type": "url", "name": "u", "value": "u"}])


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the panel: the rows, the filter, the fold and the ONE opener ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
win = make_main()
panel = win.bookmark_panel
check("§2 the panel is a child of the VIEW (a floating panel, never a scene item)",
      panel is not None and panel.parentWidget() is win.view)
check("§2 the panel starts HIDDEN (a first run must not open it — the activity rule)",
      not panel.isVisible() and win.act_show_bookmarks.isChecked() is False)

opened = []
panel.set_opener(lambda url, name: opened.append((url, name)))
panel.set_entries(_entries)
check("§2 a row carries the NAME and the URL as the second channel (text + item data + tooltip)",
      panel.rows_text() == [("Wiki", "https://wiki.example.com"),
                            ("Grafana", "https://mon.example.com:3000"),
                            ("Tickets", "https://JIRA.example.com")],
      str(panel.rows_text()))
check("§2 with rows on the screen no message is shown", panel.message_key() == "")

panel.filter.setText("graf")
check("§2 the filter narrows the rows and is case-insensitive",
      panel.rows_text() == [("Grafana", "https://mon.example.com:3000")]
      and len(panel.visible_entries()) == 1)
panel.filter.setText("nothing-matches-this")
check("§2 a filter that keeps nothing says so (and hides the list)",
      panel.message_key() == "bookmarks.no_matches" and panel.list.isHidden())
panel.filter.clear()
check("§2 clearing the filter brings every row back",
      len(panel.rows_text()) == 3 and panel.message_key() == "")

panel.set_entries([])
check("§2 an EMPTY store has its OWN sentence (not the no-match one)",
      panel.message_key() == "bookmarks.empty" and panel.row_count() == 0)
panel.set_entries(_entries)

# the opener: double click, Enter, and the refusals
opened.clear()
panel.list.setCurrentRow(0)
panel._on_entry_entered()
check("§2 Enter on the list opens the row through the opener (url + name)",
      opened == [("https://wiki.example.com", "Wiki")], str(opened))
opened.clear()
panel._on_item_double_clicked(panel.list.item(2))
check("§2 a double click opens THAT row", opened == [("https://JIRA.example.com", "Tickets")],
      str(opened))
check("§2 open_row() refuses a row that does not exist",
      panel.open_row(99) is False and panel.open_row(-1) is False)
_saved_opener = panel._opener
panel.set_opener(None)
check("§2 a panel with no opener lists links and opens nothing (no crash)",
      panel.open_row(0) is False)
panel.set_opener(_saved_opener)

# the fold
_panel_collapsed = []
panel.collapsed_changed.connect(lambda value: _panel_collapsed.append(value))
_open_height = panel.height()
panel.set_collapsed(True)
app.processEvents()
check("§2 the fold collapses the panel to its title band and hides the body",
      panel.is_collapsed() and panel.height() == panel.HEADER_H
      and panel.filter.isHidden() and panel.list.isHidden()
      and panel.manage_btn.isHidden() and _panel_collapsed == [True],
      f"h={panel.height()} signals={_panel_collapsed}")
panel.set_collapsed(False, persist=False)
check("§2 unfolding RESTORES the body and `persist=False` writes no signal (the load path)",
      not panel.is_collapsed() and panel.height() == _open_height
      and _panel_collapsed == [True] and not panel.filter.isHidden(),
      f"h={panel.height()} signals={_panel_collapsed}")
check("§2 the header band is the fold AND the drag handle", panel.header_rect().height()
      == panel.HEADER_H)

# the drag of the title band reports where the panel landed
_moved = []
panel.moved.connect(lambda pos: _moved.append(pos))
from PySide6.QtTest import QTest  # noqa: E402

QTest.mousePress(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 8))
QTest.mouseMove(panel, QPoint(120, 150))
app.processEvents()
QTest.mouseRelease(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(120, 150))
app.processEvents()
check("§2 dragging the title band moves the panel and reports it",
      bool(_moved) and panel.pos().x() > win.BOOKMARKS_MARGIN,
      f"pos={panel.pos()} moved={_moved}")
check("§2 the panel's UI state keys are the declared `ui_bookmarks*` family (the ui_legend rule)",
      all(key in _BOOKMARKS_SRC
          for key in ("ui_bookmarks_panel", "ui_bookmarks_collapsed", "ui_bookmarks_position")))
check("§2 the panel is the FOURTH floating panel of the priority resolver",
      "'legend', 'bookmark_panel'," in window_func_body("_overlay_panel_rects", ROOT))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the switch: ONE action, its menu item and its toolbar mirror ==")
# ════════════════════════════════════════════════════════════════════════════

check("§3 the registry carries the action with an EMPTY default (assignable, no key taken)",
      "view.toggle_bookmarks" in HR.HOTKEY_ACTIONS
      and HR.default_sequence("view.toggle_bookmarks") == ""
      and "view.toggle_bookmarks" in HR.empty_default_action_ids())
check("§3 the action joins the VIEW family of the Hotkeys tab (derived from its id)",
      HR.action_family("view.toggle_bookmarks") == "view"
      and "view.toggle_bookmarks" in HR.actions_by_family()["view"])
check("§3 it was the SIXTIETH action and the THIRTY-SEVENTH with an empty default"
      " (v1.6.8 adds the attention report, the sixty-first)",
      len(HR.HOTKEY_ACTIONS) == 62 and len(HR.empty_default_action_ids()) == 39,
      f"{len(HR.HOTKEY_ACTIONS)} / {len(HR.empty_default_action_ids())}")

check("§3 the checkable View item exists, is registered and mirrors the saved state",
      win.act_show_bookmarks.isCheckable()
      and win.act_show_bookmarks.text() == i18n.t("view.toggle_bookmarks")
      and any(w is win.act_show_bookmarks and k == "view.toggle_bookmarks"
              for w, k in win._menu_i18n)
      and win._hotkey_targets.get("view.toggle_bookmarks") == [win.act_show_bookmarks])
check("§3 the item lives in the SAME menu as the other panel toggles (the View menu)",
      isinstance(win.act_show_bookmarks.parent(), QMenu)
      and win.act_show_bookmarks.parent() is win.act_show_legend.parent())
check("§3 the toolbar DECLARES it in the view cluster and the button exists",
      ("view.toggle_bookmarks", "bookmarks", "view.toggle_bookmarks", "Bookmarks")
      in MW._VIEW_TOOLBAR_ITEMS
      and MW._VIEW_TOOLBAR_ACTIONS["view.toggle_bookmarks"] == "act_show_bookmarks"
      and win._bookmarks_toolbar_btn is win._view_toolbar_buttons["view.toggle_bookmarks"])
check("§3 a toolbar button is a MIRROR: it owns NO sequence (the v1.3.3.3 rule)",
      win._bookmarks_toolbar_btn.shortcut().isEmpty()
      and win._bookmarks_toolbar_btn.isCheckable()
      and win._bookmarks_toolbar_btn.isChecked() == win.act_show_bookmarks.isChecked())
check("§3 the panel switch has its OWN glyph (the ribbon renders)",
      not get_icon("bookmarks").isNull())
check("§3 the toolbar's right-click menu lists the switch (the declaration, not N buttons)",
      win.act_show_bookmarks in win._panel_switch_actions())
_hub = SettingsDialog(None)
check("§3 the settings hub collects the SAME 25 config keys (UI state is owner-written)",
      len(_hub.collect()) == 25
      and not any("bookmark" in key for key in _hub.collect()),
      str(sorted(_hub.collect()))[:120])
_hub.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the editor: add / edit / remove / reorder, url entries only ==")
# ════════════════════════════════════════════════════════════════════════════

from dialogs.bookmark_edit_dialog import BookmarkEditDialog  # noqa: E402

EDIT_PATH = os.path.join(WORK, "bm_editor", "bookmarks.json")
editor_store = BookmarkStore(path=EDIT_PATH)
editor_store.save([{"type": "command", "name": "uptime", "value": "uptime"},
                   {"type": "url", "name": "Wiki", "value": "https://wiki.example.com"}])
dlg = BookmarkEditDialog(None, store=editor_store)
check("§4 the editor opens on the URLs of the store (the `command` is not shown)",
      dlg.table.rowCount() == 1 and dlg.table.item(0, 0).text() == "Wiki")
check("§4 the editor names its two columns and its add button (i18n chrome)",
      [dlg.table.horizontalHeaderItem(i).text() for i in range(2)] == [
          i18n.t("bookmarks.col_name"), i18n.t("bookmarks.col_url")]
      and dlg.btn_apply.text() == i18n.t("bookmarks.add"))

boxes.clear()
dlg.name_edit.setText("Grafana")
dlg.value_edit.setText("grafana.local")
dlg._apply_fields()
check("§4 a value without http(s) is refused with the quick-launch sentence",
      any(b[0] == "warning" for b in boxes) and dlg.table.rowCount() == 1)
boxes.clear()
dlg.name_edit.setText("")
dlg.value_edit.setText("https://x.example.com")
dlg._apply_fields()
check("§4 an empty name is refused", any(b[0] == "warning" for b in boxes))

dlg.name_edit.setText("Grafana")
dlg.value_edit.setText("https://grafana.example.com")
dlg._apply_fields()
check("§4 a valid pair is added to the list and the fields are cleared",
      dlg.table.rowCount() == 2 and dlg.name_edit.text() == ""
      and dlg.get_entries()[1] == {"type": "url", "name": "Grafana",
                                   "value": "https://grafana.example.com"})
boxes.clear()
dlg._start_edit(0)
check("§4 Edit loads the row back into the fields and the apply button says `Save`",
      dlg.name_edit.text() == "Wiki"
      and dlg.btn_apply.text() == i18n.t("file.save") and not dlg.btn_edit.isEnabled())
dlg.name_edit.setText("Wiki (team)")
dlg._apply_fields()
check("§4 the edited entry is REPLACED in place (the order does not move)",
      [e["name"] for e in dlg.get_entries()] == ["Wiki (team)", "Grafana"]
      and dlg.table.item(0, 0).text() == "Wiki (team)"
      and dlg.btn_apply.text() == i18n.t("bookmarks.add"))
dlg.table.setCurrentCell(1, 0)
dlg._move_selected(-1)
check("§4 the arrows reorder the list (the order of the panel)",
      [e["name"] for e in dlg.get_entries()] == ["Grafana", "Wiki (team)"])
dlg._move_selected(-1)
check("§4 a move past the end is refused, never wrapped",
      [e["name"] for e in dlg.get_entries()] == ["Grafana", "Wiki (team)"])
dlg.table.setCurrentCell(1, 0)
dlg._remove_selected()
check("§4 Remove drops the selected entry",
      [e["name"] for e in dlg.get_entries()] == ["Grafana"])

dlg.name_edit.setText("Ticket queue")
dlg.value_edit.setText("https://tickets.example.com")
dlg._apply_fields()
dlg.accept()
check("§4 accept() wrote the URL list through the store", dlg.saved is True
      and dlg.save_failed is False)
check("§4 ...and the FOREIGN `command` entry of the file was kept, in its place",
      [e["type"] for e in editor_store.load()] == ["command", "url", "url"]
      and editor_store.load()[0]["name"] == "uptime",
      str(editor_store.load()))
check("§4 the editor wrote `type: url` on every entry it owns",
      all(e["type"] == "url" for e in editor_store.load_urls()))
check("§4 a dialog WITHOUT a store writes nothing and reports nothing (the test seam)",
      BookmarkEditDialog(None).get_entries() == [])
dlg.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the window: the toggle, the persistence, the opener and the editor door ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
win._bookmarks_pos = None            # §2 dragged the panel — this section starts anchored
win._position_bookmarks_panel()
store = panel.store()
store.save_urls([{"type": "url", "name": "Wiki", "value": "https://wiki.example.com"},
                 {"type": "url", "name": "Grafana", "value": "https://grafana.example.com"}])
win.act_show_bookmarks.setChecked(True)
app.processEvents()
check("§5 the View item shows the panel and persists `ui_bookmarks_panel`",
      panel.isVisible() and read_cfg({}).get("ui_bookmarks_panel") is True)
check("§5 showing the panel RELOADS the store (the rows are the file)",
      panel.rows_text() == [("Wiki", "https://wiki.example.com"),
                            ("Grafana", "https://grafana.example.com")],
      str(panel.rows_text()))
check("§5 the toolbar button follows the item (blocked signals, no loop)",
      win._bookmarks_toolbar_btn.isChecked())
check("§5 a VISIBLE panel is part of the collapse-diamond priority resolver",
      any(rect == panel.geometry() for rect in win._overlay_panel_rects(win.view)))
check("§5 with no saved position it sits in the top-left corner (the plaque's yield rule)",
      panel.pos() == QPoint(win.BOOKMARKS_MARGIN, win.BOOKMARKS_MARGIN),
      f"pos={panel.pos()}")

# the REAL opener: the success and the failure sentence (ONE opener, one home)
panel.set_opener(win._quick_launch_url)      # the callback the window installs at construction
webbrowser.open = lambda url: boxes.append(("opened", url)) or True
boxes.clear()
panel.open_row(0)
check("§5 opening a row goes through the quick-launch URL path (the ONE opener)",
      ("opened", "https://wiki.example.com") in boxes
      and win.statusBar().currentMessage() == i18n.t("status.ql_opened", name="Wiki"),
      f"{boxes} / {win.statusBar().currentMessage()!r}")
webbrowser.open = lambda url: False
boxes.clear()
panel.open_row(0)
check("§5 a browser that refuses is a REPORTED failure, never a traceback",
      any(b[0] == "warning" for b in boxes))
webbrowser.open = lambda url: (_ for _ in ()).throw(OSError("no browser"))
boxes.clear()
panel.open_row(1)
check("§5 an opener that raises is caught by the opener itself (the panel stays alive)",
      any(b[0] == "warning" for b in boxes) and panel.isVisible())

# the SNAP: a drop on the anchored LEFT|TOP edge re-anchors and clears the saved position
panel.move(win.SNAP_PX - 4, 200)
win._on_bookmarks_moved(panel.pos())
app.processEvents()
check("§5 SNAP: a drop at the anchored LEFT edge clears the saved position (the null sentinel)",
      win._bookmarks_pos is None
      and read_cfg({}).get("ui_bookmarks_position") == {"x": None, "y": None}
      and panel.pos() == QPoint(win.BOOKMARKS_MARGIN, win.BOOKMARKS_MARGIN),
      f"pos={panel.pos()} saved={read_cfg({}).get('ui_bookmarks_position')}")
panel.move(200, 150)
win._on_bookmarks_moved(panel.pos())
check("§5 a drop OUTSIDE the threshold keeps the detached spot",
      win._bookmarks_pos == QPoint(200, 150)
      and read_cfg({}).get("ui_bookmarks_position") == {"x": 200, "y": 150},
      str(read_cfg({}).get("ui_bookmarks_position")))
panel.set_collapsed(True)
check("§5 the fold is persisted by the window and re-places the panel",
      read_cfg({}).get("ui_bookmarks_collapsed") is True and panel.is_collapsed())
panel.set_collapsed(False)

# a language switch and a theme switch re-text and re-paint the OPEN panel
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("§5 a language switch re-texts the OPEN panel (the title band and the button)",
      panel._labels.get("bookmarks.title") == i18n.t("bookmarks.title")
      and panel.manage_btn.text() == i18n.t("bookmarks.manage")
      and panel.filter.placeholderText() == i18n.t("bookmarks.filter_placeholder"))
i18n.set_language("en")
win._apply_ui_translations()
_theme_ok = True
try:
    win.refresh_theme()
except Exception as exc:  # noqa: BLE001
    _theme_ok = False
    print("   theme switch raised:", repr(exc))
check("§5 a theme switch re-paints the panel without raising",
      _theme_ok and panel.rows_text() != [])

# the editor door: the window opens it, reloads the panel and reports the truth
import dialogs.bookmark_edit_dialog as BED  # noqa: E402

_orig_dialog_cls = BED.BookmarkEditDialog


class _FakeEditor:
    def __init__(self, *a, **kw):
        self.saved = True
        self.save_failed = False
        self._entries = [{"type": "url", "name": "New", "value": "https://new.example.com"}]

    def exec(self):
        store.save_urls(self._entries)
        return QDialog.Accepted

    def get_entries(self):
        return list(self._entries)


BED.BookmarkEditDialog = _FakeEditor
win._open_bookmarks_dialog()
app.processEvents()
check("§5 the panel's editor door writes through the store and RELOADS the panel",
      panel.rows_text() == [("New", "https://new.example.com")], str(panel.rows_text()))
check("§5 the save is reported on the status bar with its count",
      win.statusBar().currentMessage() == i18n.t("status.bookmarks_saved", count=1),
      repr(win.statusBar().currentMessage()))
BED.BookmarkEditDialog = _orig_dialog_cls


# the restart round trip: visibility, fold and position come back
close_window(win)
write_cfg({"ui_bookmarks_panel": True, "ui_bookmarks_collapsed": True,
           "ui_bookmarks_position": {"x": 60, "y": 120}, "language": "en"})
win2 = make_main()
check("§5 a new window applies the saved state (visible + folded + the saved spot)",
      win2.act_show_bookmarks.isChecked() and win2.bookmark_panel.isVisible()
      and win2.bookmark_panel.is_collapsed()
      and win2.bookmark_panel.pos() == QPoint(60, 120),
      f"visible={win2.bookmark_panel.isVisible()} "
      f"collapsed={win2.bookmark_panel.is_collapsed()} "
      f"pos={win2.bookmark_panel.pos()}")
close_window(win2)

write_cfg({"ui_bookmarks_panel": "yes", "ui_bookmarks_collapsed": 1,
           "ui_bookmarks_position": ["a", "b"]})
win3 = make_main()
check("§5 a BROKEN ui_bookmarks* value falls back to the default (off, unfolded, top-left)",
      win3.bookmark_panel.isHidden() and not win3.bookmark_panel.is_collapsed()
      and win3._bookmarks_pos is None
      and win3.bookmark_panel.pos() == QPoint(win3.BOOKMARKS_MARGIN, win3.BOOKMARKS_MARGIN),
      f"pos={win3.bookmark_panel.pos()} pos-state={win3._bookmarks_pos}")
check("§5 the merge write never resets a foreign config key",
      read_cfg({}).get("ui_bookmarks_position") == ["a", "b"]
      and read_cfg({}).get("ui_bookmarks_panel") == "yes")
close_window(win3)


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the i18n parity + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

langs = load_i18n_langs(ROOT)
_new_keys = ("view.toggle_bookmarks", "bookmarks.title", "bookmarks.tooltip",
             "bookmarks.filter_placeholder", "bookmarks.empty", "bookmarks.no_matches",
             "bookmarks.manage", "bookmarks.manage_tooltip", "dialog.bookmarks",
             "dialog.bookmarks_desc", "bookmarks.col_name", "bookmarks.col_url",
             "bookmarks.add", "bookmarks.remove", "bookmarks.url_hint",
             "status.bookmarks_saved", "status.bookmarks_save_failed")
_missing = {code: [k for k in _new_keys if not str(data.get(k) or "").strip()]
            for code, data in langs.items()}
check(f"§6 the {len(_new_keys)} keys of v1.6.7 are present and non-empty in EVERY language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§6 the reused keys the editor reports with are the quick-launch ones (no second wording)",
      all(str(langs["en"].get(k) or "").strip() for k in
          ("validation.ql_name_empty", "validation.ql_value_empty", "validation.ql_url_scheme",
           "validation.ql_duplicate", "status.ql_opened", "msg.ql_open_failed",
           "msg.ql_no_browser")))
check_i18n_parity(langs)
check_i18n_format(langs)
check("§6 the pin counts the SHIPPED release (811 + the 17 keys of v1.6.7 + the 13 of v1.6.8 + the 5 of v1.7rc1 + the 8 of v1.7rc2 + the 9 of v1.7rc3 + the 4 of v1.7.1 + the 3 of v1.7.1.1 + the 4 of the v1.7.1.2 device choice + the 4 of v1.7.2: the third row of the display mode (the single window), the merge action with its one closing report and the remote title of a tab + the 19 of v1.7.3: the Send-to row and its dialog, the busy/progress/done/failed reports, the two-sided conflict facts, the remembered-folder sentence, the two drop refusals and Word wrap + the 17 of v1.7.4rc1: the local source switch, its two refusals, the permanent-delete warning and the local file-surface sentences + the 1 of v1.7.4rc2: the refusal of a move that would cross the two sources + the 6 of v1.7.5.1: the three external-terminal refusals, the unpinned host-key warning, the send-queue notice and the refused download name, and v1.8 adds TWENTY: the elevated pane, v1.8.1 its 41: the trust surface, and v1.8.1.1 adds ONE: the identity sentence of a send) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact, and v1.9 adds FOUR: the production-tag guard — its title, the broadcast sentence and the paste sentence — and the notice of a checked selection that has left the map",
      EXPECTED_I18N_KEYS == 811 + 17 + 13 + 5 + 8 + 9 + 4 + 3 + 4 + 4 + 19 + 17 + 1 + 4 + 6 + 20 + 41 + 1 + 16 + 23 + 10 + 4,
      str(EXPECTED_I18N_KEYS))
check("§6 EXPECTED_APP_VERSION is the release this file describes",
      releases_at_least(EXPECTED_APP_VERSION, "1.7"), EXPECTED_APP_VERSION)
check_release_state(ROOT)
check("§6 nothing about the bookmarks touches the PROJECT format (VERSION_FORMAT stays 0.9)",
      __import__("version").VERSION_FORMAT == "0.9"
      and "bookmarks" not in open(os.path.join(ROOT, "storage", "project.py"),
                                  encoding="utf-8").read())

finish()
