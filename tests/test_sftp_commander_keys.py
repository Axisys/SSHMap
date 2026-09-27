# -*- coding: utf-8 -*-
"""v1.7rc3 — Files Commander, step 3: the mc/far walk, the hint row and the preview of the other pane
(ROADMAP v1.7rc3).

The topical file of the 1.7 line's THIRD release. rc1 shipped the pane MODEL, rc2 the copy/move
family over it; this slot spends the second pane's BUTTON ROW on the keys that act on it, makes the
two-pane view walkable without the mouse and shows a preview WHERE THE OTHER PANE IS — the classic
commander's three faculties:

  §1 The HINT ROW: the SECOND pane hides the shipped button row (a commander has ONE button row —
     the first pane's) and shows the key hints in that line; the FIRST pane keeps its buttons and
     no hints; the shipped single-pane look is untouched. The row is ONE elided line (a narrow
     pane or a long translation never reflows the listing), its tooltip carries the whole text,
     every entry is built from `PANE_HINTS` over the SAME keys `PANE_SHORTCUTS` binds, and the
     background colour of both rows is the historical one (the second pane is not repainted).
  §2 The PANE TOGGLE: `Tab` and `Shift+Tab` move the ACTIVE pane AND the keyboard, in both
     directions, and the walk is a CYCLE (neither key can leave the Files tab); with ONE pane the
     toggle answers None (the shipped single-pane look keeps its tab order) and the container's
     `focus_pane()` / `focus_other_pane()` are honest about a foreign pane.
  §3 The WALK over a listing: `Enter`/`Return` on a directory row ENTERS it, on a file row opens
     the preview (§6 — the other pane in the two-pane view) and on ".." goes one level up (exactly
     the `F3` slot); `Insert` and
     `Space` MARK the current row and step down (the mc/far mark — the tree's own selection, which
     is what the rc2 batch reads), with no row they answer `sftp.cmd.no_selection`; `Backspace`
     goes one level up; `Left` on a directory leaves it for its PARENT ROW instead of collapsing
     it; a `Left` on a file row and an unmodified key like `Down` fall through to Qt. A listing
     that came back with no current row puts the cursor on its FIRST navigable one.
  §4 The KEYBOARD DOMAIN: the walk is reached from the ADDRESS BAR and from the hint row as well
     as from the tree (the pane's `eventFilter`), the completer's popup keeps Qt's own `Tab`/`Enter`
     completion, and a `Tab` in the pane queues NO worker task (the keys are pure view state).
  §5 The MARK feeds the rc2 batch END TO END: two rows marked with `Insert` copy with ONE `F5`,
     the conflict question is the shipped one and the batch lands BOTH files in the other pane.
  §6 The PREVIEW OF THE OTHER PANE (the mc `F3`): a file opened in one pane is shown in the OTHER
     pane's splitter while the reading pane keeps its cursor and the keyboard; the borrowed pane
     gives up its address bar and its key row for as long as the panel is there; `Esc` closes the
     preview from EITHER side (the tree and the address bar), puts the viewer back in its own pane
     and restores the reading pane's rows; ONE preview exists at a time (a second file opened
     while the other pane previews is refused with ONE sentence); opening a file always starts
     from a clean look; the single-pane mode keeps the shipped in-pane panel.
  §7 i18n + the release state: the nine keys of the slot are present and non-empty in EVERY
     language, the hint row is really re-texted by `retranslate()`, and the version/format/deps
     pins are the release's.

ALL the checks are offscreen and without the network: the in-memory fake SFTP of `tests/_fakes.py`
behind a real `SftpWorker` (the worker is the CONTAINER's — one transport, one queue, two panes).

Run:  python tests/test_sftp_commander_keys.py   (from the project root) or python tests/run_all.py
"""
import os
import re
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, clear_cfg, releases_at_least,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_tab as STAB
from modules.sftp_tab import HINT_SEPARATOR, PANE_HINTS, PANE_SHORTCUTS, SftpTab
from modules.sftp_worker import SftpWorker

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker


def make_tab(fs, commander=False):
    """(tab, worker, log, client) with the listing of "/" already rendered.

    The tab is SHOWN: the walk is a real Qt keyboard path (`sendEvent` → the widget), and Qt
    delivers a key event only to a widget that is really on screen — the same reason the
    shipped commander file shows the window it probes.
    """
    client = FakeSftpClient(fs)
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = SftpTab()
    tab.resize(900, 500)
    tab.show()
    app.processEvents()
    tab.message.connect(lambda *_a: None)
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    return tab, worker, log, client


def item_by_name(pane, name):
    """The listing row by its visible name (None — not there yet)."""
    for i in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(i)
        if item.text(0) == name:
            return item
    return None


def row_names(pane):
    """The visible names of a pane's listing, in order."""
    return [pane.tree.topLevelItem(i).text(0) for i in range(pane.tree.topLevelItemCount())]


def key_event(key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    """A KeyPress QKeyEvent for `key`."""
    return QKeyEvent(QEvent.Type.KeyPress, int(key), mods, text)


def send(widget, key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    """Deliver a real KeyPress to `widget` through Qt (the eventFilter + keyPressEvent path)."""
    app.sendEvent(widget, key_event(key, mods, text))
    app.processEvents()


# ════════════════════════════════════════════════════════════
# 1. The hint row of the second pane
# ════════════════════════════════════════════════════════════
print("== 1. the second pane spends the button row on the key hints ==")

clear_cfg()
fs1 = FakeSftpFS()
fs1.add_dir("/left")
fs1.add_dir("/right")
fs1.add_file("/left/left.txt", b"L")
fs1.add_file("/right/right.txt", b"R")
tab1, worker1, _log1, _client1 = make_tab(fs1, commander=True)
pane_l, pane_r = tab1.panes[0], tab1.panes[1]

check("the map of the hints follows the map of the keys (ONE table, no second truth)",
      [k for k, _label in PANE_HINTS][:5] == [k for k, _slot in PANE_SHORTCUTS]
      and [k for k, _label in PANE_HINTS][5:] == ["Tab", "Ins", "Enter"],
      f"hints={[k for k, _l in PANE_HINTS]}")
check("the FIRST pane keeps the shipped button row and shows no hints",
      pane_l.buttons_bar.isVisible() and not pane_l.hints_label.isVisible()
      and pane_l.secondary is False)
check("the SECOND pane hides the button row and shows the hint row in that line",
      not pane_r.buttons_bar.isVisible() and pane_r.hints_label.isVisible()
      and pane_r.secondary is True)
check("the shipped button row is really the SAME widget in both roles (nothing is rebuilt)",
      pane_l.buttons_bar.isAncestorOf(pane_l.btn_up)
      and pane_r.buttons_bar.isAncestorOf(pane_r.btn_download)
      and pane_l.btn_up.text() == i18n.t("sftp.up"))
check("the row is the ENTRY PER KEY of the map, in the map's own order",
      pane_r.hints_label.text()
      == HINT_SEPARATOR.join(f"{k} {i18n.t(label)}" for k, label in PANE_HINTS),
      pane_r.hints_label.text())
check("every entry names its KEY and its translated meaning",
      all(f"F{n} " in pane_r.hints_label.text() for n in (3, 5, 6, 7, 8))
      and "Tab " in pane_r.hints_label.text()
      and "Ins " in pane_r.hints_label.text()
      and "Enter " in pane_r.hints_label.text()
      and i18n.t("sftp.hint.copy") in pane_r.hints_label.text()
      and i18n.t("sftp.cmd.switch_pane") in pane_r.hints_label.text(),
      pane_r.hints_label.text())
check("the whole text rides the tooltip (an elided row can always be read)",
      pane_r.hints_label.toolTip() == pane_r.hints_label.text()
      and bool(pane_r.hints_label.toolTip()))
check("the row is ONE line: word-wrap off and the button row's own height",
      pane_r.hints_label.wordWrap() is False
      and "\n" not in pane_r.hints_label.text()
      and pane_r.hints_label.height() == pane_r.buttons_bar.sizeHint().height(),
      f"{pane_r.hints_label.height()} vs {pane_r.buttons_bar.sizeHint().height()}")
check("the hint row carries the historical muted style (the pane is not repainted)",
      "color:" in pane_r.hints_label.styleSheet()
      and pane_r.hints_label.styleSheet() == pane_l.path_label.styleSheet()
      and pane_l.hints_label.styleSheet() == pane_l.path_label.styleSheet(),
      f"{pane_r.hints_label.styleSheet()!r}")

tab1.set_commander(False)
check("turning the mode OFF restores the button row of the surviving pane (no hint left)",
      tab1.commander is False and len(tab1.panes) == 1
      and tab1.panes[0].buttons_bar.isVisible()
      and not tab1.panes[0].hints_label.isVisible()
      and tab1.panes[0].secondary is False)
tab1.set_commander(True)
check("re-opening the mode gives the NEW second pane the hint row again",
      len(tab1.panes) == 2 and tab1.panes[1].secondary is True
      and not tab1.panes[1].buttons_bar.isVisible()
      and tab1.panes[1].hints_label.isVisible()
      and tab1.panes[0].secondary is False)
check("the mode is NOT reported as a new hint (the row is view state, not a message)",
      pane_r.hints_label.text().startswith("F3 "))
worker1.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 2. Tab / Shift+Tab — the pane toggle
# ════════════════════════════════════════════════════════════
print("== 2. Tab switches the active pane (the mc/far walk) ==")

clear_cfg()
fs2 = FakeSftpFS()
fs2.add_dir("/left")
fs2.add_dir("/right")
fs2.add_file("/left/left.txt", b"L")
fs2.add_file("/right/right.txt", b"R")
tab2, worker2, log2, _client2 = make_tab(fs2, commander=True)
pane_l, pane_r = tab2.panes[0], tab2.panes[1]
tab2.set_active_pane(pane_l)

check("the active pane is the LEFT one and its listing owns the keyboard domain",
      tab2.active_pane is pane_l and pane_l._ring.is_active() is True
      and pane_r._ring.is_active() is False)

send(pane_l.tree, Qt.Key.Key_Tab)
check("`Tab` in the LEFT pane makes the RIGHT pane ACTIVE (and MOVES the keyboard)",
      tab2.active_pane is pane_r and pane_r._ring.is_active() is True
      and pane_l._ring.is_active() is False,
      f"active is left: {tab2.active_pane is pane_l}")
check("...and the shipped tab-level reads follow the new active pane",
      tab2.tree is pane_r.tree and tab2.path_label is pane_r.path_label
      and tab2.current_dir == pane_r.current_dir)
check("...the focus really landed INSIDE the other pane's listing",
      pane_r.isAncestorOf(QApplication.focusWidget())
      or QApplication.focusWidget() is pane_r.tree,
      f"focus={QApplication.focusWidget()!r}")

send(pane_r.tree, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
check("`Shift+Tab` in the RIGHT pane comes back to the LEFT one (the inverse key)",
      tab2.active_pane is pane_l and pane_l._ring.is_active() is True)

check("the walk is a CYCLE — `Shift+Tab` on the first pane wraps to the second",
      tab2.focus_other_pane(pane_l, back=True) is pane_r
      and tab2.active_pane is pane_r)
check("...and `Tab` on the last pane wraps to the first (neither key leaves the Files tab)",
      tab2.focus_other_pane(pane_r) is pane_l and tab2.active_pane is pane_l)
check("the toggle answers None for a foreign pane (an honest refusal, never a silent move)",
      tab2.focus_other_pane(None) is None and tab2.focus_other_pane(object()) is None
      and tab2.focus_pane(None) is None)
check("focus_pane() of the ACTIVE pane is idempotent (it only re-lands the keyboard)",
      tab2.focus_pane(pane_l) is pane_l and tab2.active_pane is pane_l)

# ONE pane: nothing to switch to — the shipped single-pane look keeps its tab order
tab2.set_commander(False)
one = tab2.panes[0]
check("with ONE pane `Tab` is not consumed (the shipped tab order survives)",
      tab2.focus_other_pane(one) is None
      and one._on_pane_key(key_event(Qt.Key.Key_Tab)) is False)
tab2.set_commander(True)
pane_l, pane_r = tab2.panes[0], tab2.panes[1]
tab2.set_active_pane(pane_l)
# let the listings of the two fresh panes settle — the probe below counts what `Tab` adds
for _ in range(6):
    app.processEvents()
sent_ids = {e[1] for e in log2.events}
send(pane_l.tree, Qt.Key.Key_Tab)
for _ in range(3):
    app.processEvents()
check("a `Tab` in the pane queues NO worker task and re-lists NOTHING (pure view state)",
      {e[1] for e in log2.events} == sent_ids
      and not [e for e in log2.events if e[0] == "started"
               and e[2] in ("copy", "move")],
      f"new={[e for e in log2.events if e[1] not in sent_ids]!r}")
worker2.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 3. The walk over a listing: Enter / Insert / Space / Backspace / Left
# ════════════════════════════════════════════════════════════
print("== 3. Enter, Insert/Space, Backspace and Left ==")

clear_cfg()
fs3 = FakeSftpFS()
fs3.add_dir("/home")
fs3.add_dir("/home/sub")
fs3.add_file("/home/sub/deep.txt", b"deep")
fs3.add_file("/home/a.txt", b"alpha")
fs3.add_file("/home/b.txt", b"beta")
tab3, worker3, _log3, _client3 = make_tab(fs3)
pane3 = tab3.panes[0]
tab3._relist("/home")
wait_until(lambda: item_by_name(tab3, "a.txt") is not None, timeout_ms=5000)

# Enter on a FILE row — the shipped preview (F3's slot)
pane3.tree.setCurrentItem(item_by_name(pane3, "a.txt"))
send(pane3.tree, Qt.Key.Key_Return)
wait_until(lambda: not pane3.viewer.isHidden(), timeout_ms=5000)
check("`Enter` on a FILE row opens the shipped read-only preview (exactly the F3 slot)",
      not pane3.viewer.isHidden() and pane3.viewer_text.toPlainText() == "alpha",
      f"viewer={pane3.viewer_text.toPlainText()!r}")
pane3.close_viewer()

# Enter on the ".." row — one level up
pane3.tree.setCurrentItem(item_by_name(pane3, ".."))
send(pane3.tree, Qt.Key.Key_Return)
wait_until(lambda: pane3.current_dir == "/", timeout_ms=5000)
check("`Enter` on the '..' row goes one level up (the shipped navigation rule)",
      pane3.current_dir == "/")

# Enter on a DIRECTORY row — enter it
tab3._relist("/home")
wait_until(lambda: item_by_name(pane3, "sub") is not None, timeout_ms=5000)
pane3.tree.setCurrentItem(item_by_name(pane3, "sub"))
send(pane3.tree, Qt.Key.Key_Return)
wait_until(lambda: pane3.current_dir == "/home/sub", timeout_ms=5000)
check("`Enter` on a DIRECTORY row enters it (the mouse-free way into a tree)",
      pane3.current_dir == "/home/sub"
      and item_by_name(pane3, "deep.txt") is not None,
      f"dir={pane3.current_dir}")

# Backspace — one level up from anywhere
send(pane3.tree, Qt.Key.Key_Backspace)
wait_until(lambda: pane3.current_dir == "/home", timeout_ms=5000)
check("`Backspace` goes one level up (the commander's shortcut for '..')",
      pane3.current_dir == "/home")
wait_until(lambda: item_by_name(pane3, "a.txt") is not None, timeout_ms=5000)

# Insert / Space — the mark
# `QTreeWidget.setCurrentItem()` marks the row it makes current (Qt's own click behaviour), so
# the probe starts from an explicitly UNMARKED row — the same state a `Tab`-into-the-pane lands in.
pane3.tree.setCurrentItem(item_by_name(pane3, "a.txt"))
pane3.tree.clearSelection()
pane3._move_cursor(item_by_name(pane3, "a.txt"))
app.processEvents()
check("the probe starts from an UNMARKED listing (the mark below is really the key's work)",
      pane3.tree.selectedItems() == []
      and pane3.tree.currentItem() is item_by_name(pane3, "a.txt"))
send(pane3.tree, Qt.Key.Key_Insert)
check("`Insert` MARKS the current row (the tree's selection — the batch's own state)",
      pane3._row_marked(item_by_name(pane3, "a.txt"))
      and item_by_name(pane3, "a.txt") in pane3.tree.selectedItems(),
      f"marked={pane3._row_marked(item_by_name(pane3, 'a.txt'))} "
      f"sel={[i.text(0) for i in pane3.tree.selectedItems()]}")
check("...and the cursor STEPS DOWN to the next row (the mc/far mark)",
      pane3.tree.currentItem().text(0) == "b.txt",
      pane3.tree.currentItem().text(0))
send(pane3.tree, Qt.Key.Key_Space, text=" ")
check("`Space` marks the next row too — two rows marked without the mouse",
      pane3._row_marked(item_by_name(pane3, "b.txt"))
      and len(pane3.tree.selectedItems()) == 2,
      f"selected={[i.text(0) for i in pane3.tree.selectedItems()]}")

# the mark is a TOGGLE — a second key on a marked row unmarks it
pane3._move_cursor(item_by_name(pane3, "a.txt"))
pane3._mark_current_row()
check("a second mark on a marked row UNMARKS it (the toggle of every commander)",
      pane3._row_marked(item_by_name(pane3, "a.txt")) is False
      and pane3._row_marked(item_by_name(pane3, "b.txt")) is True,
      f"selected={[i.text(0) for i in pane3.tree.selectedItems()]}")

# the mark never lands on ".."
pane3.tree.clearSelection()
up = item_by_name(pane3, "..")
check("the listing really carries a '..' row (the probe is meaningful)",
      up is not None)
msgs_up = []
tab3.message.connect(msgs_up.append)
pane3._move_cursor(up)
pane3._mark_current_row()
check("the mark SKIPS the '..' row (navigation is not a subject of a batch)",
      pane3._row_marked(item_by_name(pane3, "..")) is False
      and pane3.tree.selectedItems() == []
      and msgs_up == [i18n.t("sftp.cmd.no_selection")],
      f"sel={[i.text(0) for i in pane3.tree.selectedItems()]} msgs={msgs_up!r}")
# no row at all — the shipped honest answer
msgs3 = []
tab3.message.connect(msgs3.append)
pane3.tree.setCurrentItem(None)
pane3._mark_current_row()
check("with no current row the mark answers `sftp.cmd.no_selection` (never a silent no-op)",
      msgs3 == [i18n.t("sftp.cmd.no_selection")], f"msgs={msgs3!r}")
msgs3.clear()
pane3._open_current_row()
check("...and so does `Enter`", msgs3 == [i18n.t("sftp.cmd.no_selection")], f"msgs={msgs3!r}")

# Left on a directory row — leave it for the parent row (not a collapse)
tab3._relist("/home")
wait_until(lambda: item_by_name(pane3, "sub") is not None, timeout_ms=5000)
pane3.tree.setCurrentItem(item_by_name(pane3, "sub"))
send(pane3.tree, Qt.Key.Key_Left)
wait_until(lambda: pane3.current_dir == "/", timeout_ms=5000)
check("`Left` on a directory row leaves it for its PARENT row (the mc/far gesture)",
      pane3.current_dir == "/", f"dir={pane3.current_dir}")

# a file row / "/" — Left falls through to Qt
tab3._relist("/home")
wait_until(lambda: item_by_name(pane3, "a.txt") is not None, timeout_ms=5000)
pane3.tree.setCurrentItem(item_by_name(pane3, "a.txt"))
check("`Left` on a FILE row is not consumed (the selection keeps Qt's own behaviour)",
      pane3._on_pane_key(key_event(Qt.Key.Key_Left)) is False)
tab3._relist("/")
wait_until(lambda: pane3.current_dir == "/", timeout_ms=5000)
check("`Left` never leaves '/' (there is no parent row to land on)",
      pane3._leave_current_dir() is False and pane3.current_dir == "/",
      pane3.current_dir)
tab3._relist("/home")
wait_until(lambda: item_by_name(pane3, "a.txt") is not None, timeout_ms=5000)
pane3.tree.setCurrentItem(item_by_name(pane3, "a.txt"))
send(pane3.tree, Qt.Key.Key_Down)
check("an unmodified key of the walk's list (`Down`) is the tree's own (never re-implemented)",
      pane3.tree.currentItem().text(0) == "b.txt",
      pane3.tree.currentItem().text(0))
worker3.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 4. The keyboard domain: the walk works from the address bar too
# ════════════════════════════════════════════════════════════
print("== 4. the walk answers from the address bar and the hint row ==")

clear_cfg()
fs4 = FakeSftpFS()
fs4.add_dir("/left")
fs4.add_dir("/right")
fs4.add_file("/left/left.txt", b"L")
tab4, worker4, _log4, _client4 = make_tab(fs4, commander=True)
pane_l, pane_r = tab4.panes[0], tab4.panes[1]
tab4.set_active_pane(pane_l)

send(pane_l.path_label, Qt.Key.Key_Tab)
check("`Tab` in the ADDRESS BAR switches the pane (the pane is the keyboard domain)",
      tab4.active_pane is pane_r, f"active={tab4.active_pane is pane_l}")

send(pane_r.path_label, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
check("...and `Shift+Tab` comes back from the other pane's address bar",
      tab4.active_pane is pane_l)

tab4.set_active_pane(pane_r)
pane_r._relist("/left")
wait_until(lambda: pane_r.current_dir == "/left", timeout_ms=5000)
send(pane_r.path_label, Qt.Key.Key_Backspace)
check("`Backspace` in the address bar goes one level up (the walk answers there too)",
      pane_r.current_dir == "/", f"dir={pane_r.current_dir}")

check("the completer popup is closed, so it never swallows the walk",
      pane_r._popup_open() is False)
check("the pane's hook is a NO-OP for a non-key event (the D&D family is untouched)",
      pane_r._on_pane_key(QEvent(QEvent.Type.FocusIn)) is False
      and pane_r._on_pane_key(None) is False)
worker4.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 5. The mark feeds the rc2 batch end to end
# ════════════════════════════════════════════════════════════
print("== 5. two marked rows copy with ONE F5 ==")

clear_cfg()
fs5 = FakeSftpFS()
fs5.add_dir("/left")
fs5.add_dir("/right")
fs5.add_file("/left/one.txt", b"1")
fs5.add_file("/left/two.txt", b"2")
tab5, worker5, _log5, _client5 = make_tab(fs5, commander=True)
pane_l, pane_r = tab5.panes[0], tab5.panes[1]
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "one.txt") is not None, timeout_ms=5000)
pane_r._relist("/right")
wait_until(lambda: pane_r.path_label.text() == "/right", timeout_ms=5000)

msgs5 = []
tab5.message.connect(msgs5.append)
pane_l.tree.setCurrentItem(item_by_name(pane_l, "one.txt"))
pane_l.tree.clearSelection()
pane_l._move_cursor(item_by_name(pane_l, "one.txt"))
app.processEvents()
check("the batch probe starts with NOTHING marked (the two marks below are the keyboard's)",
      pane_l.tree.selectedItems() == [])
send(pane_l.tree, Qt.Key.Key_Insert)      # mark one.txt, step to two.txt
send(pane_l.tree, Qt.Key.Key_Insert)      # mark two.txt
check("two rows are MARKED with the keyboard alone (the batch of F5/F6)",
      len(pane_l.tree.selectedItems()) == 2,
      f"selected={[i.text(0) for i in pane_l.tree.selectedItems()]}")

tab5.pane_shortcut("F5").trigger()
wait_until(lambda: fs5.files.get("/right/one.txt") == b"1"
           and fs5.files.get("/right/two.txt") == b"2", timeout_ms=8000)
check("ONE F5 copies the WHOLE marked batch into the other pane",
      fs5.files.get("/right/one.txt") == b"1"
      and fs5.files.get("/right/two.txt") == b"2"
      and fs5.files.get("/left/one.txt") == b"1",
      f"files={sorted(fs5.files)}")
wait_until(lambda: i18n.t("sftp.cmd.copy_report", done=2, skipped=0, failed=0) in msgs5,
           timeout_ms=5000)
check("...and the ship closing report names both files (the rc2 batch policy)",
      i18n.t("sftp.cmd.copy_report", done=2, skipped=0, failed=0) in msgs5,
      f"msgs={msgs5!r}")
worker5.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 6. The PREVIEW of the other pane (the mc F3) and Esc
# ════════════════════════════════════════════════════════════
print("== 6. the preview opens in the other pane and Esc closes it ==")

clear_cfg()
fs6 = FakeSftpFS()
fs6.add_dir("/left")
fs6.add_dir("/right")
fs6.add_file("/left/a.txt", b"alpha")
fs6.add_file("/left/b.txt", b"beta")
fs6.add_file("/right/r.txt", b"right")
tab6, worker6, _log6, _client6 = make_tab(fs6, commander=True)
pane_l, pane_r = tab6.panes[0], tab6.panes[1]
msgs6 = []
tab6.message.connect(msgs6.append)
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "a.txt") is not None, timeout_ms=5000)
pane_r._relist("/right")
wait_until(lambda: item_by_name(pane_r, "r.txt") is not None, timeout_ms=5000)
app.processEvents()

check("a freshly rendered listing puts the CURSOR on its first navigable row (a commander is",
      pane_l.tree.currentItem() is not None
      and pane_l.tree.currentItem().text(0) == "a.txt"
      and pane_l.tree.currentItem() is not pane_l._up_item,
      f"current={pane_l.tree.currentItem() and pane_l.tree.currentItem().text(0)!r}")
check("...and the '..' row is never the one the cursor lands on",
      tab6.panes[0]._up_item is not None
      and pane_l.tree.currentItem() is not pane_l._up_item)

# `Enter` on the current row opens the preview IN THE OTHER PANE
tab6.set_active_pane(pane_l)
send(pane_l.tree, Qt.Key.Key_Return)
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
check("`Enter` on a file shows the preview in the OTHER pane (the mc F3)",
      pane_l.viewer.parent() is pane_r.splitter
      and pane_l.viewer_text.toPlainText() == "alpha",
      f"parent-is-R={pane_l.viewer.parent() is pane_r.splitter} text={pane_l.viewer_text.toPlainText()!r}")
check("...the READING pane keeps its cursor and its listing (the panel is a VIEW, not a move)",
      pane_l._viewer_open is True and pane_l._viewer_host is pane_r
      and pane_l.tree.currentItem() is item_by_name(pane_l, "a.txt")
      and pane_l.secondary is False,
      f"open={pane_l._viewer_open} host-is-R={pane_l._viewer_host is pane_r} "
      f"current={pane_l.tree.currentItem() and pane_l.tree.currentItem().text(0)!r} "
      f"active={tab6.active_pane is pane_l}")
check("...and the borrowing pane gives up its address bar and its key row (it is a PANEL now)",
      pane_r._viewer_borrowed is True
      and not pane_r.path_label.isVisibleTo(pane_r)
      and not pane_r.buttons_bar.isVisibleTo(pane_r)
      and not pane_r.hints_label.isVisibleTo(pane_r),
      f"borrowed={pane_r._viewer_borrowed} path={pane_r.path_label.isVisibleTo(pane_r)}")
# the look is not the feature: the borrowed panel must really GET the column it took over.
# A share handed out by POSITION gave the column to the host's own (hidden) panel and left the
# borrowed one zero pixels wide — the pane changed its look and showed NOTHING at all.
wait_until(lambda: pane_l.viewer.width() > 0, timeout_ms=2000)
check("...and the borrowed panel really gets the column it took over (a look-only panel "
      "shows nothing)",
      pane_l.viewer.width() > 0
      and pane_l.viewer.isVisibleTo(pane_r)
      and pane_r.splitter.sizes()[pane_r.splitter.indexOf(pane_l.viewer)] > 0,
      f"w={pane_l.viewer.width()} visible={pane_l.viewer.isVisibleTo(pane_r)} "
      f"sizes={pane_r.splitter.sizes()} idx={pane_r.splitter.indexOf(pane_l.viewer)}")
check("the container answers WHICH pane is previewing and WHO opened it",
      tab6.preview_pane() is pane_l and tab6.preview_source() is pane_l)

# `Esc` from the READING pane's listing closes it and puts everything back
send(pane_l.tree, Qt.Key.Key_Escape)
for _ in range(3):
    app.processEvents()
check("`Esc` in the reading pane closes the preview",
      pane_l._viewer_open is False and tab6.preview_pane() is None)
check("...the panel goes home and the borrowing pane gets its row back",
      pane_l.viewer.parent() is pane_l.splitter
      and pane_l.viewer_text.toPlainText() == ""
      and pane_r.path_label.isVisibleTo(pane_r)
      and pane_r.hints_label.isVisibleTo(pane_r)
      and pane_r._viewer_borrowed is False)

# ── the WALK over the listing: F3 after F3 is what a commander is FOR ──
# A panel THIS pane owns is never "in the way": the new file is read into the same widget. The
# gate must ask about the OWNER of the open panel and not about the pane that merely CARRIES it.
msgs6.clear()
pane_l.tree.setCurrentItem(item_by_name(pane_l, "a.txt"))
send(pane_l.tree, Qt.Key.Key_Return)
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
pane_l.tree.setCurrentItem(item_by_name(pane_l, "b.txt"))
send(pane_l.tree, Qt.Key.Key_Return)
for _ in range(6):
    app.processEvents()
check("a second file opened from the READING pane is not refused: the F3-after-F3 walk works",
      pane_l.viewer_text.toPlainText() == "beta"
      and pane_l.viewer.parent() is pane_r.splitter
      and i18n.t("sftp.cmd.preview_busy") not in msgs6,
      f"text={pane_l.viewer_text.toPlainText()!r} msgs={msgs6!r}")
check("...and the re-opened panel keeps the column (the walk never shrinks it away)",
      pane_l.viewer.width() > 0
      and pane_r.splitter.sizes()[pane_r.splitter.indexOf(pane_l.viewer)] > 0,
      f"w={pane_l.viewer.width()} sizes={pane_r.splitter.sizes()}")

# ── a read the WORKER refuses never changes the other pane's look ──
# The panel moves only once the content is there, so a binary/too-large file leaves a LISTING
# behind instead of a dressed-up pane with nothing in it (and no `Esc` that could undo it).
fs6.add_file("/left/bin.dat", b"\x00\x01binary")
send(pane_l.tree, Qt.Key.Key_Escape)   # clean look first
for _ in range(3):
    app.processEvents()
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "bin.dat") is not None, timeout_ms=5000)
msgs6.clear()
pane_l.tree.setCurrentItem(item_by_name(pane_l, "bin.dat"))
pane_l._cmd_view()
for _ in range(8):
    app.processEvents()
check("a read the worker REFUSES leaves the other pane a LISTING, not an empty borrowed panel",
      pane_l._viewer_open is False and tab6.preview_pane() is None
      and pane_r._viewer_borrowed is False
      and pane_r.path_label.isVisibleTo(pane_r)
      and pane_r.hints_label.isVisibleTo(pane_r)
      and i18n.t("sftp.viewer.binary") in msgs6,
      f"open={pane_l._viewer_open} borrowed={pane_r._viewer_borrowed} msgs={msgs6!r}")

# the other direction, closed from the ADDRESS BAR
pane_r.tree.setCurrentItem(item_by_name(pane_r, "r.txt"))
pane_r._cmd_view()
wait_until(lambda: pane_r._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
check("the same works in the other direction (the RIGHT pane previews in the LEFT one)",
      pane_r.viewer.parent() is pane_l.splitter
      and pane_r.viewer_text.toPlainText() == "right"
      and not pane_l.path_label.isVisibleTo(pane_l),
      f"parent-is-L={pane_r.viewer.parent() is pane_l.splitter}")
send(pane_r.path_label, Qt.Key.Key_Escape)
for _ in range(3):
    app.processEvents()
check("`Esc` works from the ADDRESS BAR too (the pane is the keyboard domain)",
      pane_r._viewer_open is False and pane_r.viewer.parent() is pane_r.splitter
      and pane_l.path_label.isVisibleTo(pane_l))

# ONE preview at a time: a second file opened while the other pane previews is refused
tab6.set_active_pane(pane_l)
pane_l.tree.setCurrentItem(item_by_name(pane_l, "a.txt"))
pane_l._cmd_view()
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(3):
    app.processEvents()
check("the probe really has a preview open before the second one is attempted",
      tab6.preview_pane() is pane_l and pane_l.viewer.parent() is pane_r.splitter,
      f"preview={tab6.preview_pane()!r}")
msgs6.clear()
pane_r.tree.setCurrentItem(item_by_name(pane_r, "r.txt"))
pane_r._cmd_view()
for _ in range(6):
    app.processEvents()
check("a second preview opened while the other pane previews is REFUSED with ONE sentence",
      pane_r._viewer_open is False
      and i18n.t("sftp.cmd.preview_busy") in msgs6,
      f"msgs={msgs6!r} open={pane_r._viewer_open}")
check("...and the preview that was already open is untouched",
      pane_l._viewer_open is True
      and pane_l.viewer.parent() is pane_r.splitter
      and pane_l.viewer_text.toPlainText() == "alpha")
check("the refusal sentence is TRANSLATED in every language (it is the slot's ninth key)",
      all(str(data.get("sftp.cmd.preview_busy") or "").strip()
          for data in load_i18n_langs(ROOT).values())
      and all(str(data["sftp.cmd.preview_busy"]) != "sftp.cmd.preview_busy"
              for code, data in load_i18n_langs(ROOT).items() if code != "en"))

# opening a file ALWAYS starts from a clean look
pane_l.close_viewer()
for _ in range(3):
    app.processEvents()
pane_l.tree.setCurrentItem(item_by_name(pane_l, "b.txt"))
pane_l._cmd_view()
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(3):
    app.processEvents()
check("a fresh open starts clean: the new file, in the other pane, no leftover panel",
      pane_l.viewer_text.toPlainText() == "beta"
      and pane_l.viewer.parent() is pane_r.splitter
      and pane_l.splitter.count() == 1
      and pane_r.splitter.count() == 3,
      f"text={pane_l.viewer_text.toPlainText()!r} L="
      f"{[pane_l.splitter.widget(i).__class__.__name__ for i in range(pane_l.splitter.count())]} R="
      f"{[pane_r.splitter.widget(i).__class__.__name__ for i in range(pane_r.splitter.count())]}")

# the mode goes OFF with a preview open: the preview closes and the panel goes home
tab6.set_commander(False)
for _ in range(3):
    app.processEvents()
check("turning the mode OFF closes the preview of the two-pane view (the panel goes home)",
      tab6.commander is False and len(tab6.panes) == 1
      and pane_l._viewer_open is False
      and pane_l.viewer.parent() is pane_l.splitter)
check("`Esc` with nothing open is NOT consumed (it stays the focused widget's key)",
      pane_l._on_pane_key(key_event(Qt.Key.Key_Escape)) is False)

# the shipped single-pane look: the panel stays INSIDE the pane and Esc still closes it
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "a.txt") is not None, timeout_ms=5000)
pane_l.tree.setCurrentItem(item_by_name(pane_l, "a.txt"))
pane_l._cmd_view()
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(3):
    app.processEvents()
check("with ONE pane the preview keeps the shipped in-pane panel",
      pane_l.viewer.parent() is pane_l.splitter and not pane_l.viewer.isHidden())
send(pane_l.tree, Qt.Key.Key_Escape)
app.processEvents()
check("...and `Esc` closes it there too",
      pane_l._viewer_open is False and pane_l.viewer.isHidden())
worker6.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 7. i18n + the release state
# ════════════════════════════════════════════════════════════
print("== 7. i18n and the release state ==")

RC3_KEYS = ("sftp.hint.view", "sftp.hint.copy", "sftp.hint.move", "sftp.hint.mkdir",
            "sftp.hint.delete", "sftp.cmd.switch_pane", "sftp.hint.mark", "sftp.hint.open",
            "sftp.cmd.preview_busy")

langs = load_i18n_langs(ROOT)
_missing = {code: [k for k in RC3_KEYS if not str(data.get(k) or "").strip()]
            for code, data in langs.items()}
check(f"the {len(RC3_KEYS)} keys of v1.7rc3 are present and non-empty in EVERY language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("every hint label is SHORT enough for one line of a narrow pane (the row is elided)",
      all(len(str(langs[c][k])) <= 20 for c in langs
          for k in RC3_KEYS if k.startswith("sftp.hint.")),
      str({c: {k: len(str(langs[c][k])) for k in RC3_KEYS} for c in sorted(langs)}))
check("the hint row is TRANSLATED (no language ships the raw key or the English literal)",
      all(str(langs[c]["sftp.hint.copy"]) not in ("sftp.hint.copy", "Copy")
          for c in langs if c != "en"),
      str({c: langs[c]["sftp.hint.copy"] for c in sorted(langs)}))
check_i18n_parity(langs)
check_i18n_format(langs)

# a language switch re-texts the hint row of the second pane
i18n.set_language("ru")
tab_i = SftpTab()
tab_i.set_commander(True)
tab_i.retranslate()
check("a language switch re-texts the hint row of the second pane",
      tab_i.panes[1].hints_label.text()
      == HINT_SEPARATOR.join(f"{k} {i18n.t(label)}" for k, label in PANE_HINTS)
      and i18n.t("sftp.hint.copy") in tab_i.panes[1].hints_label.text(),
      tab_i.panes[1].hints_label.text())
check("...and the row stays ONE line with the new text (wrapping is never enabled)",
      tab_i.panes[1].hints_label.wordWrap() is False
      and "\n" not in tab_i.panes[1].hints_label.text())
tab_i.set_worker(None)
i18n.set_language("en")

check_release_state(ROOT)
check("the version pin is the release this file describes",
      re.fullmatch(r"1\.7(?:rc\d+)?", EXPECTED_APP_VERSION) is not None,
      EXPECTED_APP_VERSION)
check("the i18n pin counts the SHIPPED release (854 + the 9 keys of v1.7rc3)",
      EXPECTED_I18N_KEYS == 854 + 9 == 863, str(EXPECTED_I18N_KEYS))
check("VERSION_FORMAT did NOT move (the project schema is unchanged)",
      __import__("version").VERSION_FORMAT == "0.9")
check("no new dependency was added for the walk (the four pinned ones)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("the frozen contract of the line is still in the repository (SFTP_PANES.md)",
      os.path.exists(os.path.join(ROOT, "SFTP_PANES.md")))

finish()
