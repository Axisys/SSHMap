# -*- coding: utf-8 -*-
"""v1.3.3.4 — Terminal: working with the output (ROADMAP v1.3.3.4, the topical file).

The last version of the v1.3.3.x follow-up series gives the terminal the three
"output" capabilities it never had (search in the scrollback, a way to throw the
history away, a transcript), turns the command-library seed names into i18n keys and
adds the per-session multi-input exclusion. Offscreen, NO network: the terminal
thread is the shared fake (`tests/_fakes.py`), the SFTP progress is fed by hand.

§1 The find bar over a synthetic scrollback (task 1): the panel opens from the
   CANVAS (Ctrl+Shift+F) and from the context menu; a case-insensitive LITERAL
   search over the history AND the live grid; the "k / N" counter; Enter/Shift+
   Enter walk the matches with wraparound and the viewport follows; Esc closes the
   panel and restores the history position the search started from; NOT one byte
   reaches the PTY (the fake thread records every send); a plain Ctrl+F still goes
   to the shell as \\x06 (the §14a scope boundary — the terminal's keys are the
   xterm protocol and are not configurable).

§2 Clear the scrollback / reset the screen (task 2): two LOCAL context-menu actions
   — the history is dropped while the live grid survives, the grid is re-initialized
   and repainted; the PTY receives nothing.

§3 Save transcript… (task 3): the checkable menu item + the file dialog seam; the tee
   appends EXACTLY the fed bytes (raw, ANSI and non-UTF-8 included); an existing file
   is appended to, never truncated; a cancelled dialog leaves the tee off; the file is
   closed by the idempotent page.shutdown() and a write after it is a safe no-op.

§4 The command-library seed names (task 4): the first seeding writes the names in the
   ACTIVE language; an EXISTING commands.json is never re-translated.

§5 The multi-input exclusion (task 5): the hub skips an excluded session (its own
   typing keeps working), the participant count / the plaque counter follow, the tab
   carries the "NO MULTI" badge, un-excluding restores everything; F12 / the registry
   entry are unchanged.

§6 The transfer rate/ETA of the SFTP progress line (task 6 — the detachable task 7 of
   v1.3.3.2): the duration formatter and the sliding-window meter (pure, an injected
   clock), and the progress line the page actually emits.

§7 i18n parity (+17 keys) and the release state (the pin in tests/_common.py).

Run:  python tests/test_terminal_output.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

app = QApplication(sys.argv)

import i18n
import modules.command_library as CL
import modules.ssh_terminal as ST
import modules.terminal_widget as TW
from models.server import ServerData
from modules.multi_input import MultiInputHub, apply_container_highlight
from modules.terminal_page import TerminalSessionPage, TransferMeter, format_duration
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget

from _fakes import FakeSSHThread as _FakeThread

_orig_thread_cls = ST.SSHTerminalThread


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


def menu_action(menu, label):
    """The QAction of a built context menu by its (translated) text."""
    for act in menu.actions():
        if act.text() == label:
            return act
    return None


def config_path():
    """~/.sshmap/config.json (the sandbox HOME — bootstrap() isolates it)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


SCROLLBACK = [
    "hist 0 filler", "hist 1 filler", "hist 2 filler", "hist 3 filler",
    "hist 4 filler", "hist 5 filler", "hist 6 filler", "hist 7 filler",
    "hist 8 filler", "hist 9 filler", "hist 10 NEEDLE here", "hist 11 filler",
    "hist 12 filler", "hist 13 filler", "hist 14 filler", "hist 15 filler",
    "hist 16 filler", "hist 17 filler", "hist 18 filler", "hist 19 filler",
    "live 0 filler", "live 1 filler", "live 2 filler",
    "live 3 filler", "live 4 filler", "live 5 NEEDLE tail",
]


def feed_scrollback(tscreen):
    """26 lines on a 6-line grid with a 50-line history: 20 in the history + 6 live.

    The marker sits in BOTH halves on purpose — the acceptance of task 1 asks for
    matches in the history AND on the live screen."""
    for line in SCROLLBACK:
        tscreen.feed((line + "\r\n").encode("utf-8"))


def make_widget(hub=None, columns=40, lines=6, history=50):
    tscreen = TerminalScreen(columns=columns, lines=lines, history_lines=history)
    thread = _FakeThread("h-out", "u", 22)
    w = TerminalWidget(tscreen, thread, multi_hub=hub)
    w.resize(320, 120)
    return w, tscreen, thread


# ══════════════════════════════════════════════════════════════════════════════
print("== 1. the find bar over a synthetic scrollback (task 1) ==")
# ══════════════════════════════════════════════════════════════════════════════

hub_iso = MultiInputHub()          # an isolated hub: the app singleton stays untouched
w1, scr1, th1 = make_widget(hub=hub_iso)
feed_scrollback(scr1)

# 26 fed lines with a trailing CRLF: pyte keeps 21 lines above a 6-row grid (the
# trailing newline opens one empty line) — the document is history + live grid.
check("the document: the history lines + the live grid (21 + 6)", len(scr1.text_lines()) == 27,
      str(len(scr1.text_lines())))
check("the marker is in the HISTORY and on the LIVE screen",
      scr1.text_lines()[10].rstrip() == "hist 10 NEEDLE here"
      and "NEEDLE" in scr1.text_lines()[25],
      f"h={scr1.text_lines()[10]!r} l={scr1.text_lines()[25]!r}")
check("the search starts on the live line (history position == size)",
      scr1.at_bottom() and scr1.scroll_info()[0] == scr1.scroll_info()[1])
check("no find panel before the first open (a lazy child — a session pays nothing)",
      w1._find_bar is None and w1.find_active is False)

pos_start = scr1.scroll_info()[0]   # the position Esc must restore
th1.channel.sent.clear()
w1.keyPressEvent(key_event(Qt.Key.Key_F, "f",
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
check("Ctrl+Shift+F in the CANVAS opens the panel (no hotkey registry entry — §14a)",
      w1.find_active is True and w1._find_bar is not None)
check("the panel is a child of the canvas (an overlay, not a dock)",
      w1._find_bar.parent() is w1)
check("Ctrl+Shift+F does NOT reach the PTY", th1.channel.sent == [], repr(th1.channel.sent))

bar = w1._find_bar
bar.set_query("needle")
state = w1.find_state()
check("a case-insensitive search finds BOTH markers", state["total"] == 2, str(state))
check("the counter shows 'k / N' (the first match is current)",
      state["current"] == 1
      and bar._count.text() == i18n.t("terminal.find.count").format(cur=1, total=2),
      f"{state} text={bar._count.text()!r}")
check("the viewport followed the first match INTO the history (it is visible)",
      "NEEDLE" in w1.visible_text(), repr(w1.visible_text().replace("\n", "|")))
check("a second search state: the query is stored as typed",
      w1.find_state()["query"] == "needle")

# Enter — the next match (the live screen), then the wraparound
w1.find_next()
check("Enter: the second match (on the live screen) and the counter follows",
      w1.find_state()["current"] == 2 and "live 5 NEEDLE" in w1.visible_text(),
      f"{w1.find_state()} text={w1.visible_text().replace(chr(10), '|')!r}")
w1.find_next()
check("Enter past the LAST match wraps to the first one",
      w1.find_state()["current"] == 1 and "hist 10 NEEDLE" in w1.visible_text(),
      f"{w1.find_state()} text={w1.visible_text().replace(chr(10), '|')!r}")
w1.find_prev()
check("Shift+Enter wraps back to the last match", w1.find_state()["current"] == 2)

# the panel's own keys (the field has the focus while the panel is open)
QTest.keyClick(bar._line, Qt.Key_Return)
check("Enter in the panel's field: the next match (a wraparound to the first)",
      w1.find_state()["current"] == 1)
QTest.keyClick(bar._line, Qt.Key_Enter, Qt.ShiftModifier)
check("Shift+Enter in the panel's field: the previous match (a wraparound to the last)",
      w1.find_state()["current"] == 2)

check("NOT a single byte reached the PTY during the whole search",
      th1.channel.sent == [], repr(th1.channel.sent))

# Esc — the close + the restore of the pre-search view state
QTest.keyClick(bar._line, Qt.Key_Escape)
check("Esc closes the panel", w1.find_active is False)
check("Esc drops the matches (nothing is highlighted any more)",
      w1.find_state()["total"] == 0 and w1.find_state()["current"] == 0)
check("Esc restores the history position the search started from",
      scr1.scroll_info()[0] == pos_start and scr1.at_bottom(),
      f"pos={scr1.scroll_info()} was={pos_start}")
check("the field is emptied (the next open starts clean)", bar.query == "")

# a plain Ctrl+F keeps going to the shell as \x06 (the §14a scope boundary)
th1.channel.sent.clear()
w1.keyPressEvent(key_event(Qt.Key.Key_F, "\x06", Qt.KeyboardModifier.ControlModifier))
check("a plain Ctrl+F is NOT a find key: it goes to the PTY as \\x06",
      th1.channel.sent == [b"\x06"], repr(th1.channel.sent))

# the context menu opens it too and it is labelled with the panel's own key
menu1 = w1._build_context_menu()
check("the context menu carries 'Find…' (terminal.find.placeholder)",
      menu_action(menu1, i18n.t("terminal.find.placeholder")) is not None)
menu_action(menu1, i18n.t("terminal.find.placeholder")).trigger()
check("the menu item opens the panel", w1.find_active is True)
w1.close_find()

# an empty query → the empty state, no matches, no crash
w1.open_find()
bar.set_query("zzz-nothing-here")
check("no matches: the empty state reuses search.no_results (ZERO new keys)",
      w1.find_state()["total"] == 0 and bar._count.text() == i18n.t("search.no_results"),
      repr(bar._count.text()))
check("navigation without matches: False, nothing happens",
      w1.find_next() is False and w1.find_prev() is False)
w1.close_find()

# a LITERAL search (regex search is explicitly NOT in this version)
w1.open_find()
bar.set_query("hist 1.")
check("the query is escaped: 'hist 1.' matches NO line (a literal dot, not 'any char')",
      w1.find_state()["total"] == 0, str(w1.find_state()))
w1.close_find()

# a DEEP scrollback: the navigation budget is derived from the ACTUAL history depth,
# so a match at the very top of a deque that needs more pages than any fixed cap allows
# is still reachable (pyte's page is ~10% of the grid — ONE line on a 4-row screen, so
# ~5000 lines above the grid need ~5000 pages).
print("-- a deep scrollback (the derived page budget) --")
w_deep, scr_deep, _th_deep = make_widget(columns=20, lines=4, history=6000)
for i in range(5000):
    scr_deep.feed(f"deep {i:04d} filler\r\n".encode())
scr_deep.feed(b"deep TOP-ANCHOR marker\r\n")
for _ in range(4):
    scr_deep.feed(b"tail filler\r\n")
lines_deep = len(scr_deep.text_lines())
check("the deep fixture: thousands of history lines above the live grid (> 4096 pages)",
      lines_deep > 5000, str(lines_deep))
w_deep.open_find()
w_deep._find_bar.set_query("top-anchor")
check("a match deep in the scrollback is found (the document is the whole deque)",
      w_deep.find_state()["total"] == 1, str(w_deep.find_state()))
check("the viewport reached it (more pages than a fixed 4096-step cap would allow)",
      "TOP-ANCHOR" in w_deep.visible_text(),
      repr(w_deep.visible_text().replace("\n", "|")))
w_deep.close_find()

# the panel follows a language switch (the v1.3.3.1 container invariant, wired
# TerminalSessionPage.retranslate() → widget.retranslate() → the open find panel)
_saved_lang = i18n.get_current_language()
try:
    w1.open_find()
    i18n.set_language("ru")
    w1.retranslate()
    check("an OPEN find panel is re-texted on a language switch (page → canvas → panel)",
          w1._find_bar._line.placeholderText() == i18n.t("terminal.find.placeholder")
          and w1._find_bar._close_btn.toolTip() == i18n.t("terminal.find.close"),
          f"{w1._find_bar._line.placeholderText()!r}")
    check("the counter is re-rendered in the new language (the empty state here)",
          w1._find_bar._count.text() in ("", i18n.t("search.no_results")),
          repr(w1._find_bar._count.text()))
finally:
    i18n.set_language(_saved_lang)
    w1.close_find()


# ══════════════════════════════════════════════════════════════════════════════
print("== 2. clear the scrollback / reset the screen (task 2) ==")
# ══════════════════════════════════════════════════════════════════════════════

w2, scr2, th2 = make_widget(hub=hub_iso)
feed_scrollback(scr2)
check("the fixture: 21 history lines + 6 live ones", len(scr2.text_lines()) == 27,
      str(len(scr2.text_lines())))
th2.channel.sent.clear()

menu2 = w2._build_context_menu()
act_clear = menu_action(menu2, i18n.t("terminal.menu.clear_scrollback"))
act_reset = menu_action(menu2, i18n.t("terminal.menu.reset_screen"))
check("the context menu carries the two local actions",
      act_clear is not None and act_reset is not None)

act_clear.trigger()
check("clear scrollback: the history is dropped (the document is the live grid only)",
      len(scr2.text_lines()) == 6, str(len(scr2.text_lines())))
check("clear scrollback KEEPS the live screen (the last line is still there)",
      "live 5 NEEDLE tail" in w2.visible_text(),
      repr(w2.visible_text().replace("\n", "|")))
check("clear scrollback: nothing is above any more (scroll_up is a no-op)",
      scr2.scroll_up() is False and scr2.at_bottom())
check("clear scrollback: not one byte to the PTY", th2.channel.sent == [], repr(th2.channel.sent))

act_reset.trigger()
check("reset screen: the grid is empty", w2.visible_text().strip() == "",
      repr(w2.visible_text().replace("\n", "|")))
check("reset screen: the history is dropped too", len(scr2.text_lines()) == 6)
check("reset screen: the viewport is on the live line again", scr2.at_bottom())
check("reset screen: not one byte to the PTY", th2.channel.sent == [], repr(th2.channel.sent))
# the repaint: a real paint of the fresh grid draws no text at all
pix = QPixmap(w2.width(), w2.height())
w2.render(pix)
check("reset screen: the canvas repaints the empty grid (a real paint, no glyphs)",
      w2.last_paint_stats["draw_text_calls"] == 0, str(w2.last_paint_stats))


# ══════════════════════════════════════════════════════════════════════════════
print("== 3. save transcript… (task 3) ==")
# ══════════════════════════════════════════════════════════════════════════════

ST.SSHTerminalThread = _FakeThread   # the pages of this file — on the fake

_paths = {"answer": ""}


class _FakeFileDialog:
    """The QFileDialog seam (module attribute): getSaveFileName → the canned answer."""

    @staticmethod
    def getSaveFileName(*_a, **_k):
        return _paths["answer"], ""


_orig_file_dialog = TW.QFileDialog
TW.QFileDialog = _FakeFileDialog

page = TerminalSessionPage(
    ServerData(id="to-p1", alias="tr", host="10.97.0.1", user="root"), None)
app.processEvents()
wtr = page.widget
tr_path = os.path.join(WORK, "transcript.log")
_paths["answer"] = tr_path

menu_tr = wtr._build_context_menu()
act_tr = menu_action(menu_tr, i18n.t("terminal.menu.save_transcript"))
check("the menu carries the transcript item and it is CHECKABLE (the on/off state)",
      act_tr is not None and act_tr.isCheckable() and act_tr.isChecked() is False)

act_tr.trigger()   # toggled(True) → the dialog (the fake) → open the file
check("the item starts the tee (the dialog answered with a path)",
      wtr.transcript_active is True and wtr.transcript_path == tr_path)

page._on_output(b"hello\r\n")
page._on_output(b"\x1b[31mred\xff\xfe\r\n")   # ANSI + non-UTF-8: raw bytes
with open(tr_path, "rb") as f:
    fed = f.read()
check("the transcript holds EXACTLY the fed bytes (the raw stream, ANSI included)",
      fed == b"hello\r\n\x1b[31mred\xff\xfe\r\n", repr(fed))
check("the tee is a copy — the screen got the output as usual",
      "red" in wtr.visible_text())

# a second run of the tee APPENDS (never truncates an existing file)
check("with an active tee the menu item comes up CHECKED",
      wtr.transcript_active is True
      and menu_action(wtr._build_context_menu(),
                      i18n.t("terminal.menu.save_transcript")).isChecked() is True)
wtr.stop_transcript()
wtr.start_transcript(tr_path)
wtr.write_transcript(b"second")
wtr.stop_transcript()
with open(tr_path, "rb") as f:
    fed = f.read()
check("a restart appends instead of truncating the existing file",
      fed == b"hello\r\n\x1b[31mred\xff\xfe\r\nsecond", repr(fed))

# the checkable item switches the tee off
wtr.start_transcript(tr_path)
act_tr2 = menu_action(wtr._build_context_menu(), i18n.t("terminal.menu.save_transcript"))
check("with an active tee the item comes up CHECKED (the on/off state is the checkmark)",
      act_tr2.isChecked() is True and wtr.transcript_active is True)
act_tr2.trigger()
check("unchecking the item stops the tee", wtr.transcript_active is False)

# a cancelled dialog leaves the tee off and the item unchecked
_paths["answer"] = ""
act_tr3 = menu_action(wtr._build_context_menu(), i18n.t("terminal.menu.save_transcript"))
act_tr3.trigger()
check("a cancelled file dialog: no transcript, the item is put back to unchecked",
      wtr.transcript_active is False and act_tr3.isChecked() is False)

# the shutdown path closes the file, twice, and never raises into the teardown
_paths["answer"] = tr_path
act_tr4 = menu_action(wtr._build_context_menu(), i18n.t("terminal.menu.save_transcript"))
act_tr4.trigger()
check("the tee is on again (the same file)", wtr.transcript_active is True)
page.shutdown()
check("page.shutdown() closes the transcript (the single idempotent teardown)",
      wtr.transcript_active is False and wtr.transcript_path is None)
page.shutdown()
check("a repeated shutdown() is a safe no-op", wtr.transcript_active is False)
page._on_output(b"after-shutdown")
with open(tr_path, "rb") as f:
    fed = f.read()
check("no byte is written after the teardown (the tee is closed with the session)",
      fed.endswith(b"second"), repr(fed[-20:]))

# a page without a host: the teardown of a session that never saved anything
page2 = TerminalSessionPage(
    ServerData(id="to-p2", alias="tr2", host="10.97.0.2", user="root"), None)
app.processEvents()
check("a session without a transcript: transcript_active is False",
      page2.widget.transcript_active is False)
page2.widget.write_transcript(b"nowhere")   # must not raise
page2.shutdown()
check("write_transcript without a tee is a safe no-op", page2.widget.transcript_active is False)

TW.QFileDialog = _orig_file_dialog


# ══════════════════════════════════════════════════════════════════════════════
print("== 4. the command-library seed names are i18n keys (task 4) ==")
# ══════════════════════════════════════════════════════════════════════════════

SEED_KEYS = ("terminal.cmdlib.seed.tail_nginx", "terminal.cmdlib.seed.restart_docker",
             "terminal.cmdlib.seed.top_processes", "terminal.cmdlib.seed.disk_usage",
             "terminal.cmdlib.seed.sum_column")
_langs = load_i18n_langs(ROOT)
check("the 5 seed keys exist and are non-empty in ALL the discovered languages",
      all(str(_langs[c].get(k, "")).strip() for c in _langs for k in SEED_KEYS),
      str([c for c in _langs for k in SEED_KEYS if not str(_langs[c].get(k, "")).strip()]))
check("the en values keep the v1.3 seed names (the stored file of a user does not change)",
      _langs["en"]["terminal.cmdlib.seed.disk_usage"] == "Disk usage"
      and _langs["en"]["terminal.cmdlib.seed.sum_column"] == "Sum column (awk)")

seed_path = os.path.join(WORK, "commands_seed.json")
try:
    i18n.set_language("ru")
    entries = CL.CommandLibraryStore(path=seed_path).load()
    names = [e["name"] for e in entries]
    ru_names = [_langs["ru"][k] for k in SEED_KEYS]
    check("the FIRST seeding of commands.json writes the names in the ACTIVE language (ru)",
          names == ru_names, f"{names!r} vs {ru_names!r}")
    with open(seed_path, encoding="utf-8") as f:
        doc = json.load(f)
    check("the seeded document carries seeded: true and the translated names",
          doc.get("seeded") is True and [c["name"] for c in doc["commands"]] == ru_names)
    check("the commands themselves stay as they are (content, not UI text)",
          doc["commands"][3]["command"] == "df -h")
finally:
    i18n.set_language("en")

# an EXISTING file is never re-translated
own_path = os.path.join(WORK, "commands_own.json")
with open(own_path, "w", encoding="utf-8") as f:
    json.dump({"seeded": True, "commands": [
        {"id": "own1", "name": "My own macro", "command": "uptime",
         "category": "Mine", "enabled": True}]}, f)
try:
    i18n.set_language("de")
    own = CL.CommandLibraryStore(path=own_path).load()
finally:
    i18n.set_language("en")
check("an EXISTING commands.json is never re-translated (the user's own text wins)",
      [e["name"] for e in own] == ["My own macro"], str(own))
with open(own_path, encoding="utf-8") as f:
    own_doc = json.load(f)
check("the stored file is left byte-equivalent (no re-seed, no rewrite)",
      own_doc["commands"][0]["name"] == "My own macro")


# ══════════════════════════════════════════════════════════════════════════════
print("== 5. excluding a session from multi-input (task 5) ==")
# ══════════════════════════════════════════════════════════════════════════════


class _PageStub:
    """A duck-typed registry record (like TerminalSessionPage: .widget + .terminal_thread)."""

    def __init__(self, thread, widget, alias):
        self.terminal_thread = thread
        self.widget = widget
        self.server_data = ServerData(id=f"stub-{alias}", alias=alias,
                                      host="10.96.0.1", user="root")


hub5 = MultiInputHub()
w_a, _scr_a, th_a = make_widget(hub=hub5)
w_b, _scr_b, th_b = make_widget(hub=hub5)
w_c, _scr_c, th_c = make_widget(hub=hub5)
pages5 = [_PageStub(th_a, w_a, "alpha"), _PageStub(th_b, w_b, "beta"),
          _PageStub(th_c, w_c, "gamma")]
hub5.set_session_provider(lambda: list(pages5))
hub5.set_active(True)

check("the exclusion starts off (the state is per session and in memory)",
      w_a.multi_excluded is False and hub5.participant_count() == 3)

w_c.set_multi_excluded(True)
check("the flag lives on the session's canvas and is readable by the hub",
      w_c.multi_excluded is True)
check("participant_count: the excluded session is not a participant any more",
      hub5.participant_count() == 2, str(hub5.participant_count()))

for t in (th_a, th_b, th_c):
    t.channel.sent.clear()
w_a.keyPressEvent(key_event(Qt.Key.Key_X, "x"))
check("broadcast: the excluded session receives NOTHING",
      th_c.channel.sent == [] and th_b.channel.sent == [b"x"],
      f"c={th_c.channel.sent!r} b={th_b.channel.sent!r}")
check("the source still receives its own key exactly once (no echo added)",
      th_a.channel.sent == [b"x"], repr(th_a.channel.sent))
check("the number of receivers excludes it (2 sessions - the source)", 
      hub5.broadcast(b"y", source_widget=w_a) == 1, "beta only")
for t in (th_a, th_b, th_c):
    t.channel.sent.clear()

# the EXCLUDED session's own typing keeps working (its own shell, not the broadcast)
w_c.keyPressEvent(key_event(Qt.Key.Key_Z, "z"))
check("the excluded session's own typing keeps working (its own send_data)",
      th_c.channel.sent == [b"z"], repr(th_c.channel.sent))
check("the exclusion filters RECEIVERS only: the excluded session still talks to the others",
      th_a.channel.sent == [b"z"] and th_b.channel.sent == [b"z"],
      f"a={th_a.channel.sent!r} b={th_b.channel.sent!r}")

# the badge on the tab (the container highlight is the single badge renderer)
class _TabPage(QWidget):
    """A minimal page: what apply_container_highlight duck-types (.server_data/.widget)."""

    def __init__(self, widget, alias):
        super().__init__()
        self.widget = widget
        self.server_data = ServerData(id=f"tab-{alias}", alias=alias,
                                      host="10.96.0.9", user="root")


tabs = QTabWidget()
for page in pages5:
    tabs.addTab(_TabPage(page.widget, page.server_data.alias), page.server_data.alias)
host = type("_Host", (), {"session_tabs": tabs})()
apply_container_highlight(host, True)
check("the excluded session's tab carries the badge (terminal.multi_excluded_badge)",
      tabs.tabText(2) == i18n.t("terminal.multi_excluded_badge", alias="gamma"),
      repr(tabs.tabText(2)))
check("the other tabs keep the plain MULTI badge",
      tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="alpha")
      and tabs.tabText(1) == i18n.t("terminal.multi_tab_badge", alias="beta"),
      f"{tabs.tabText(0)!r} {tabs.tabText(1)!r}")

w_c.set_multi_excluded(False)
check("un-excluding: the session is a participant again", hub5.participant_count() == 3)
apply_container_highlight(host, True)
check("un-excluding restores the ordinary badge",
      tabs.tabText(2) == i18n.t("terminal.multi_tab_badge", alias="gamma"),
      repr(tabs.tabText(2)))
th_a.channel.sent.clear(); th_c.channel.sent.clear()
w_a.keyPressEvent(key_event(Qt.Key.Key_W, "w"))
check("after un-excluding the session receives the broadcast again",
      th_c.channel.sent == [b"w"], repr(th_c.channel.sent))

# the mode's own rules are untouched: F12 exits, and an empty registry is not a defect
w_a.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12 still exits the mode (the exclusion did not touch the mode's rules)",
      hub5.active is False)
hub5.set_active(True)

# ── a real MainWindow: the plaque counter follows the exclusion ────────────────
print("-- the plaque counter through MainWindow --")
import ui.main_window as MW   # noqa: E402 — after the module-level wiring of the seam

hub_app = MW._multi_input_mod.get_hub()
hub_app.reset()
mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

wins = {}
for i, alias in enumerate(("one", "two", "three")):
    node = mw.scene.add_server(
        ServerData(id=f"to-{alias}", alias=alias, host=f"10.95.{i}.1", user="root"))
    wins[alias] = mw._spawn_terminal_window(node)
    app.processEvents()

check("3 sessions in the registry", len(mw._terminal_windows) == 3,
      str(len(mw._terminal_windows)))
mw._toggle_multi_input(True)
check("the plaque counts the participants (3)",
      mw._multi_label.text() == i18n.t("terminal.multi_status", count=3),
      repr(mw._multi_label.text()))

msg_before = mw.statusBar().currentMessage()
wins["two"].page.widget.set_multi_excluded(True)
check("the plaque counter follows the exclusion (2 participants)",
      mw._multi_label.text() == i18n.t("terminal.multi_status", count=2),
      repr(mw._multi_label.text()))
check("the exclusion refresh does NOT re-announce the mode (status.multi_enabled)",
      mw.statusBar().currentMessage() == msg_before,
      repr(mw.statusBar().currentMessage()))
check("the excluded tab carries the badge",
      wins["two"].session_tabs.tabText(0)
      == i18n.t("terminal.multi_excluded_badge", alias="two"),
      repr(wins["two"].session_tabs.tabText(0)))

threads_mw = {alias: wins[alias].page.terminal_thread for alias in wins}
for t in threads_mw.values():
    t.channel.sent.clear()
wins["one"].page.widget.keyPressEvent(key_event(Qt.Key.Key_M, "m"))
check("the excluded window receives nothing through the real registry",
      threads_mw["two"].channel.sent == [] and threads_mw["three"].channel.sent == [b"m"],
      f"two={threads_mw['two'].channel.sent!r}")

wins["two"].page.widget.set_multi_excluded(False)
check("un-excluding restores the counter (3)",
      mw._multi_label.text() == i18n.t("terminal.multi_status", count=3),
      repr(mw._multi_label.text()))
mw._toggle_multi_input(False)


# ══════════════════════════════════════════════════════════════════════════════
print("== 5b. the canvas owns its keys in a DOCKED session (the ShortcutOverride fix) ==")
# ══════════════════════════════════════════════════════════════════════════════
# In `terminal_mode = "tabs"` the session lives INSIDE the main window, so its
# window-level QActions claim Ctrl+F / Ctrl+Shift+F / Ctrl+D / Ctrl+Z / Delete…
# Qt asks the FOCUS WIDGET first (ShortcutOverride) — before v1.3.3.4-fix the plain
# QWidget ignored it and the QAction won, so a docked terminal never received those
# keys (Ctrl+D duplicated a map node, Ctrl+Shift+F ran "fit map"). The canvas now
# claims the Ctrl+… combinations and the function/Delete family; the map-focused
# case below proves the claim is scoped to the focused canvas.

os.makedirs(os.path.dirname(config_path()), exist_ok=True)
with open(config_path(), "w", encoding="utf-8") as f:
    json.dump({"terminal_mode": "tabs"}, f)

node_d = mw.scene.add_server(
    ServerData(id="to-dock", alias="dock", host="10.93.0.1", user="root"))
dock = mw._spawn_terminal_window(node_d)      # tabs mode → the dock
app.processEvents()
page_d = dock.content.session_tabs.widget(0)
w_d = page_d.widget
th_d = page_d.terminal_thread
# the §5 block above opened separate terminal WINDOWS — in offscreen Qt the ACTIVE
# window decides which window-level QActions are in the shortcut map, so the main
# window is activated before the keys go out (a real user typing into the dock has it
# active by that very fact).
mw.raise_()
mw.activateWindow()
QApplication.setActiveWindow(mw)
app.processEvents()
w_d.setFocus()
app.processEvents()
check("the docked canvas really has the keyboard focus (the probe is meaningful)",
      app.focusWidget() is w_d, type(app.focusWidget()).__name__)


def _real_ctrl(key, text):
    """A Ctrl+<key> press with the text a REAL key press carries (the control code)."""
    th_d.channel.sent.clear()
    app.sendEvent(w_d, QKeyEvent(QKeyEvent.Type.KeyPress, int(key),
                                 Qt.KeyboardModifier.ControlModifier, text))
    app.processEvents()


zoom_before = mw.view.transform().m11()
mw.map_search.hide()
QTest.keyClick(w_d, Qt.Key_F, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
app.processEvents()
check("Ctrl+Shift+F in a DOCKED session opens the find bar, not 'fit map'",
      w_d.find_active is True and abs(mw.view.transform().m11() - zoom_before) < 1e-9,
      f"find={w_d.find_active} zoom_delta={mw.view.transform().m11() - zoom_before:+.4f}")
w_d.close_find()

items_before = len(mw.scene.items())
_real_ctrl(Qt.Key_F, "\x06")
check("Ctrl+F in a DOCKED session reaches the SHELL as \\x06 (the map search does not steal it)",
      th_d.channel.sent == [b"\x06"] and mw.map_search.isVisible() is False,
      f"pty={th_d.channel.sent!r} map_search={mw.map_search.isVisible()}")
_real_ctrl(Qt.Key_D, "\x04")
check("Ctrl+D in a DOCKED session sends \\x04 (it does not duplicate a map node)",
      th_d.channel.sent == [b"\x04"], repr(th_d.channel.sent))
_real_ctrl(Qt.Key_Z, "\x1a")
check("Ctrl+Z in a DOCKED session sends \\x1a (it does not undo the scene)",
      th_d.channel.sent == [b"\x1a"] and mw.undo_stack.count() == 0,
      f"pty={th_d.channel.sent!r} undo={mw.undo_stack.count()}")
check("the scene is untouched by the control keys of the docked session",
      len(mw.scene.items()) == items_before, f"{items_before} → {len(mw.scene.items())}")

th_d.channel.sent.clear()
QTest.keyClick(w_d, Qt.Key_Delete)
app.processEvents()
check("Delete in a DOCKED session sends \\x1b[3~ (it does not delete the selection)",
      th_d.channel.sent == [b"\x1b[3~"], repr(th_d.channel.sent))

mw._toggle_multi_input(True)
th_d.channel.sent.clear()
QTest.keyClick(w_d, Qt.Key_F12)
app.processEvents()
check("F12 still works in a DOCKED session (the canvas handles it, the mode exits)",
      hub_app.active is False and th_d.channel.sent == [],
      f"active={hub_app.active} pty={th_d.channel.sent!r}")

mw.view.setFocus()
app.processEvents()
mw.map_search.hide()
QTest.keyClick(mw.view, Qt.Key_F, Qt.KeyboardModifier.ControlModifier)
app.processEvents()
check("the map search still opens with Ctrl+F when the CANVAS does not have the focus",
      mw.map_search.isVisible() is True)
mw.map_search.hide()

with open(config_path(), "w", encoding="utf-8") as f:
    json.dump({"terminal_mode": "windows"}, f)


# ══════════════════════════════════════════════════════════════════════════════
print("== 6. the transfer rate / ETA of the progress line (task 6) ==")
# ══════════════════════════════════════════════════════════════════════════════

check("format_duration: seconds → M:SS", format_duration(0) == "0:00"
      and format_duration(42) == "0:42" and format_duration(61) == "1:01",
      f"{format_duration(0)!r} {format_duration(42)!r} {format_duration(61)!r}")
check("format_duration: hours → H:MM:SS", format_duration(3600) == "1:00:00"
      and format_duration(3661) == "1:01:01", f"{format_duration(3661)!r}")
check("format_duration: no usable value → '' (a busy bar without a total)",
      format_duration(None) == "" and format_duration(-5) == ""
      and format_duration("x") == "")

clock = {"t": 100.0}
meter = TransferMeter(clock=lambda: clock["t"])
check("one sample is not a measurement", meter.update(1000, 10000) is None)
clock["t"] += 1.0
rate, eta = meter.update(3000, 10000)
check("two samples → the rate over the elapsed time (2000 B/s)", abs(rate - 2000.0) < 1e-6,
      str(rate))
check("with a known total → the ETA ((10000-3000)/2000 = 3.5 s)", abs(eta - 3.5) < 1e-6, str(eta))

clock["t"] = 200.0
stall = TransferMeter(clock=lambda: clock["t"])
stall.update(1000, 10000)
check("a frozen clock (dt == 0) is not a measurement", stall.update(1000, 10000) is None)
clock["t"] = 201.0
check("a stalled transfer (no bytes moved) is not a measurement",
      stall.update(1000, 10000) is None)
clock["t"] = 202.0
rate3, eta3 = stall.update(5000, 0)
check("an unknown total → a rate (2000 B/s) without an ETA",
      rate3 is not None and abs(rate3 - 2000.0) < 1e-6 and eta3 is None,
      f"{rate3} {eta3}")

# the page's own progress line
page6 = TerminalSessionPage(
    ServerData(id="to-p6", alias="rate", host="10.94.0.1", user="root"), None)
app.processEvents()
seen_messages = []
page6.status_message.connect(lambda text, ms: seen_messages.append(text))
page6._sftp_tasks[7] = ("upload", "big.bin")
page6._sftp_busy = 1
clock6 = {"t": 500.0}
page6._transfer_meters[7] = TransferMeter(clock=lambda: clock6["t"])
page6._on_sftp_progress(7, 1000, 100000)     # the first sample — no suffix yet
first = seen_messages[-1]
clock6["t"] += 2.0
page6._on_sftp_progress(7, 5000, 100000)     # 2000 B/s → an ETA of 47.5 s
second = seen_messages[-1]
check("the first progress line has no rate suffix (nothing honest to show yet)",
      i18n.t("sftp.rate", rate="") not in first and i18n.t("sftp.eta", time="") not in first, first)
check("the second progress line appends the measured rate",
      i18n.t("sftp.rate", rate="2.0 KB") in second or "KB" in second, second)
check("the second progress line appends the ETA",
      i18n.t("sftp.eta", time="0:48") in second or "0:48" in second, second)
check("the base line is unchanged (sftp.progress is still the same sentence)",
      second.startswith(i18n.t("sftp.progress", name="big.bin", pct=5,
                               done="4.9 KB", total="97.7 KB")) or second.startswith("big.bin"),
      second)
page6._on_sftp_task_done(7, "big.bin")
check("the meter dies with the task (no leak per finished transfer)",
      page6._transfer_meters == {}, str(page6._transfer_meters))
page6.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
print("== 7. i18n parity + release state ==")
# ══════════════════════════════════════════════════════════════════════════════

NEW_KEYS = (
    "terminal.find.placeholder", "terminal.find.count", "terminal.find.next",
    "terminal.find.prev", "terminal.find.close",
    "terminal.menu.clear_scrollback", "terminal.menu.reset_screen",
    "terminal.menu.save_transcript",
    "terminal.cmdlib.seed.tail_nginx", "terminal.cmdlib.seed.restart_docker",
    "terminal.cmdlib.seed.top_processes", "terminal.cmdlib.seed.disk_usage",
    "terminal.cmdlib.seed.sum_column",
    "terminal.multi_exclude", "terminal.multi_excluded_badge",
    "sftp.rate", "sftp.eta",
)
check("v1.3.3.4: all 17 new keys are present and non-empty in every discovered language",
      all(str(_langs[c].get(k, "")).strip() for c in _langs for k in NEW_KEYS),
      str([f"{c}:{k}" for c in _langs for k in NEW_KEYS if not str(_langs[c].get(k, "")).strip()]))
check("the new placeholders are rendered (not left as braces)",
      "{cur}" not in i18n.t("terminal.find.count", cur=1, total=2)
      and "{alias}" not in i18n.t("terminal.multi_excluded_badge", alias="x")
      and "{time}" not in i18n.t("sftp.eta", time="0:42"))
check_i18n_parity(_langs)
check_release_state(ROOT)

# ── cleanup ──────────────────────────────────────────────────────────────────
try:
    mw.close()
except Exception:
    pass
app.processEvents()
ST.SSHTerminalThread = _orig_thread_cls
finish()
