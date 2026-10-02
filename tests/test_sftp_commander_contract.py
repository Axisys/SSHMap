# -*- coding: utf-8 -*-
"""v1.7 — Files Commander, the closing release: the CLAUSE AUDIT of the frozen contract
(SFTP_PANES.md) against the shipped code.

The rc series IMPLEMENTED the frozen contract; this release VERIFIES it — a GATE, not a paragraph:
every owner, name, refusal and persistence key is read off the SHIPPED objects, so a clause that quietly
stops being true fails in the suite. ALL checks are offscreen, on the fake SFTP behind a real SftpWorker.
§1 the pane model; §2 the worker API surface; §3 the key map; §4 the two-pane view; §5 the persistence;
§6 the follow rule; §7 the preview of §3b; §8 the line's state and the version pins."""
import os
import sys

from _common import (bootstrap, check, finish, wait_until, clear_cfg, check_release_state,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, releases_at_least, write_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

import i18n
import modules.sftp_tab as STAB
import modules.sftp_worker as SW
from modules.sftp_tab import (COMMANDER_CONFIG_BOOL, COMMANDER_CONFIG_RATIO, COMMANDER_MIN_PANE_PX,
                              COMMANDER_RATIO_DEFAULT, COMMANDER_RATIO_MAX, COMMANDER_RATIO_MIN,
                              PANE_HINTS, PANE_SHORTCUTS, WORKER_SIGNAL_NAMES, SftpTab)
from modules.sftp_worker import SftpWorker

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker


def make_tab(fs, commander=False):
    """(tab, worker, log, client) with the first pane's listing of "/" already rendered."""
    client = FakeSftpClient(fs)
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    tab = SftpTab()
    tab.resize(900, 500)
    tab.show()
    app.processEvents()
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    return tab, worker, log, client


def item_by_name(pane, name):
    for i in range(pane.tree.topLevelItemCount()):
        item = pane.tree.topLevelItem(i)
        if item.text(0) == name:
            return item
    return None


def key_event(key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    return QKeyEvent(QEvent.Type.KeyPress, int(key), mods, text)


# ════════════════════════════════════════════════════════════
# 1. The pane model (§1)
# ════════════════════════════════════════════════════════════
print("== 1. the pane model: who owns what ==")

clear_cfg()
fs1 = FakeSftpFS()
fs1.add_dir("/left")
fs1.add_dir("/right")
fs1.add_file("/left/left.txt", b"L")
fs1.add_file("/right/right.txt", b"R")

# a tab WITHOUT a transport: the container's facts are readable in the "waiting" state too
bare = SftpTab()
check("§1 a fresh tab is the ONE-pane container of the shipped listing",
      len(bare.panes) == 1 and bare.active_pane is bare.panes[0] and bare.commander is False,
      f"panes={len(bare.panes)} active={bare.active_pane is bare.panes[0]}")
check("§1 the CONTAINER owns the worker binding (and a pane only READS it)",
      bare.worker is None and bare._worker is None
      and isinstance(SftpTab.worker, property)
      and bare.panes[0].worker is bare.worker,
      f"worker={bare.worker!r}")
check("§1 the CONTAINER owns the follow switch, the pane list and the mode",
      hasattr(bare, "chk_follow_cwd") and hasattr(bare, "follow_cwd_changed")
      and hasattr(bare, "set_follow_cwd") and hasattr(bare, "set_commander")
      and hasattr(bare, "set_active_pane") and hasattr(bare, "relist_dir")
      and hasattr(bare, "commander_extra_config"))
check("§1 the `message` signal the page reads belongs to the CONTAINER (one bridge)",
      callable(getattr(bare.message, "connect", None))
      and callable(getattr(bare.panes[0].message, "connect", None)))

PANE_OWNED = ("_current_dir", "_pending_lists", "_read_tasks", "_last_read", "_op_tasks",
              "_pending_batches", "_normalize_tasks", "_completer_lists", "_completer_dir",
              "_blocked", "_transfer_tasks", "_highlighter")
_missing_pane = [n for n in PANE_OWNED if not hasattr(bare.panes[0], n)]
check("§1 a pane owns the whole of ONE listing (its bookkeeping and its viewer)",
      not _missing_pane and hasattr(bare.panes[0], "tree")
      and hasattr(bare.panes[0], "path_label") and hasattr(bare.panes[0], "viewer")
      and bare.panes[0].tree is not bare.panes[0].viewer,
      f"missing={_missing_pane}")
check("§1 ...and a REMOTE pane carries NO worker of its own (the binding is the container's)",
      "worker" not in bare.panes[0].__dict__ and isinstance(type(bare.panes[0]).worker, property)
      and "_worker" not in bare.panes[0].__dict__,
      str(sorted(bare.panes[0].__dict__))[:120])
# v1.7.4rc1 (LOCAL_PANE.md §1): the LOCAL source is the ONE exception to the clause above — its
# provider is not the container's, so a pane OWNS an object of its own exactly then. This is a
# recorded DECISION of the open line, asserted beside the shipped sentence instead of bending it.
check("§1 ...while a LOCAL pane's provider is its OWN (`_local_provider`, LOCAL_PANE.md §1)",
      bare.panes[0].source == "remote"
      and "_local_provider" in bare.panes[0].__dict__
      and bare.panes[0]._local_provider is None
      and isinstance(type(bare.panes[0]).provider, property)
      and callable(getattr(bare.panes[0], "set_source", None))
      and callable(getattr(SftpTab, "can_use_local", None)))
check("§1 the pane list and the mode are the CONTAINER's own attributes (never forwarded)",
      "panes" not in SftpTab.PANE_STATE and "tree" not in SftpTab.PANE_STATE
      and all(n in SftpTab.PANE_STATE for n in PANE_OWNED),
      f"missing-from-PANE_STATE={[n for n in PANE_OWNED if n not in SftpTab.PANE_STATE]}")

# the shipped single-pane surface resolves on the ACTIVE pane — reads AND writes
check("§1 the shipped attribute surface resolves on the ACTIVE pane (`tab.tree`)",
      bare.tree is bare.panes[0].tree and bare.path_label is bare.panes[0].path_label
      and bare.viewer is bare.panes[0].viewer and bare.splitter is bare.panes[0].splitter)
_bare_blocked = {"probe": 1}
bare._blocked = _bare_blocked
check("§1 ...and a PANE-owned write lands on the pane, not on the container (one truth)",
      bare.panes[0]._blocked is _bare_blocked and "_blocked" not in bare.__dict__)
check("§1 a name NOBODY owns still raises AttributeError (hasattr stays honest)",
      not hasattr(bare, "there_is_no_such_attribute"))
check("§1 the four Qt methods are DELEGATED, not inherited from QWidget",
      SftpTab.dragEnterEvent is not QWidget.dragEnterEvent
      and SftpTab.dragMoveEvent is not QWidget.dragMoveEvent
      and SftpTab.dropEvent is not QWidget.dropEvent
      and SftpTab.eventFilter is not QWidget.eventFilter)
check("§1 the drag-payload helper stays a CLASS-level read for the shipped suite",
      callable(getattr(SftpTab, "_local_files", None)))
bare.set_worker(None)

# ════════════════════════════════════════════════════════════
# 2. The worker API surface (§2, §2a)
# ════════════════════════════════════════════════════════════
print("== 2. the worker API surface of the contract ==")

check("§2 both reserved kinds are SHIPPED and take the declared fields",
      callable(getattr(SftpWorker, "queue_copy", None))
      and callable(getattr(SftpWorker, "queue_move", None))
      and SW.KIND_COPY == "copy" and SW.KIND_MOVE == "move"
      and SW.KIND_COPY in SW.OP_KINDS and SW.KIND_MOVE in SW.OP_KINDS)
check("§2 a copy/move joins the LOGGED kinds (the activity history reads the same tuple)",
      isinstance(SW.LOGGED_KINDS, tuple)
      and len(SW.LOGGED_KINDS) == len(set(SW.LOGGED_KINDS)))
check("§2a the bounded walk is DECLARED as two module constants",
      isinstance(SW.MAX_TREE_ENTRIES, int) and SW.MAX_TREE_ENTRIES > 0
      and isinstance(SW.MAX_TREE_DEPTH, int) and SW.MAX_TREE_DEPTH > 0,
      f"{SW.MAX_TREE_ENTRIES} / {SW.MAX_TREE_DEPTH}")
check("§2a the three machine payloads of the tree/refusal paths are declared once",
      SW.PARTIAL_CODE == "partial" and SW.MOVE_ERROR_REFUSED == "move_refused"
      and SW.TREE_ERROR_TOO_BIG == "tree_too_big")
check("§2 the signal set of the contract is complete (a pane binds it per pane)",
      all(hasattr(SftpWorker, n) for n in
          ("list_ready", "task_started", "progress", "task_done", "task_error",
           "task_cancelled", "read_ready", "normalize_ready"))
      and set(WORKER_SIGNAL_NAMES) == {"list_ready", "task_started", "task_done", "task_error",
                                       "task_cancelled", "read_ready", "normalize_ready"})

# ════════════════════════════════════════════════════════════
# 3. The key map (§3, §3a)
# ════════════════════════════════════════════════════════════
print("== 3. the pane-scoped key map ==")

tab3, worker3, _log3, _client3 = make_tab(fs1, commander=True)
pane_l, pane_r = tab3.panes[0], tab3.panes[1]
check("§2 the two panes read the SAME bound worker (one transport, one queue)",
      pane_l.worker is worker3 and pane_r.worker is worker3 and tab3.worker is worker3)
check("§3 the pane-scoped map is F3/F5/F6/F7/F8 in the declared order",
      [seq for seq, _slot in PANE_SHORTCUTS] == ["F3", "F5", "F6", "F7", "F8"],
      str([seq for seq, _s in PANE_SHORTCUTS]))
_pane_actions = [seq for seq, act in pane_l._pane_actions if act.shortcutContext()
                 == Qt.ShortcutContext.WidgetWithChildrenShortcut]
check("§3 every row is ONE QAction owned by the PANE with WidgetWithChildrenShortcut",
      _pane_actions == [seq for seq, _slot in PANE_SHORTCUTS]
      and all(act.parent() is pane_l for _seq, act in pane_l._pane_actions),
      str(_pane_actions))
_fkey_actions = [a.shortcut().toString() for a in tab3.actions()
                 if a.shortcut().toString().startswith("F")]
check("§3 the CONTAINER carries no F-key action of its own (the map is the panes')",
      not _fkey_actions, str(_fkey_actions))
check("§3 `F4` is REFUSED — absent from the map, from the hints and from the pane's actions",
      pane_l.pane_shortcut("F4") is None and "F4" not in [k for k, _l in PANE_HINTS])
check("§3 the rc3 walk keys are NOT actions (the focus walk, read by the pane's own hook)",
      all(pane_l.pane_shortcut(k) is None for k in ("Tab", "Enter", "Insert", "Backspace", "Left"))
      and callable(getattr(pane_l, "_on_pane_key", None)))
check("§3 the hint row of §4a advertises the SAME keys the pane really binds",
      [k for k, _l in PANE_HINTS][:5] == [seq for seq, _s in PANE_SHORTCUTS])

# a key with no current row answers the contract's sentence (never "whatever is selected")
msgs3 = []
tab3.message.connect(msgs3.append)
pane_l.tree.clearSelection()
pane_l.tree.setCurrentItem(None)
pane_l._cmd_view()
check("§3 a key with no current row answers `sftp.cmd.no_selection`",
      i18n.t("sftp.cmd.no_selection") in msgs3, str(msgs3))

# ════════════════════════════════════════════════════════════
# 4. The two-pane view and the ACTIVE pane (§4, §4a)
# ════════════════════════════════════════════════════════════
print("== 4. the two-pane view: one pane, one handle, one button row ==")

_bare2 = SftpTab()
_bare2.resize(900, 500)
_bare2.show()
app.processEvents()
_one_handles = [_bare2.pane_splitter.handle(i) for i in range(_bare2.pane_splitter.count() + 1)]
check("§4 with ONE pane the container's splitter draws NO handle (the shipped look is free)",
      _bare2.pane_splitter.count() == 1
      and not any(h is not None and h.isVisible() for h in _one_handles)
      and _bare2.pane_splitter.childrenCollapsible() is False,
      f"count={_bare2.pane_splitter.count()} visible="
      f"{[h.isVisible() for h in _one_handles if h is not None]}")
_bare2.set_worker(None)
check("§4 the mode builds a SECOND member of that splitter (never a second splitter)",
      tab3.pane_splitter.count() == 2
      and tab3.pane_splitter.widget(0) is pane_l and tab3.pane_splitter.widget(1) is pane_r)
_two_handles = [tab3.pane_splitter.handle(i) for i in range(tab3.pane_splitter.count() + 1)]
check("§4 ...and with TWO panes exactly ONE handle appears (the draggable divider)",
      len([h for h in _two_handles if h is not None and h.isVisible()]) == 1,
      f"visible={[h.isVisible() for h in _two_handles if h is not None]}")
check("§4 the ACTIVE pane is ringed IN THE MODE and the other one is not",
      pane_l._ring is not None and pane_l._ring.is_active() is (tab3.active_pane is pane_l)
      and pane_r._ring.is_active() is (tab3.active_pane is pane_r))
tab3.set_active_pane(pane_r)
check("§4 ...and the ring follows the ACTIVE pane (one state, two views)",
      pane_r._ring.is_active() is True and pane_l._ring.is_active() is False)
check("§4 the FIRST pane keeps the shipped button row and shows no hints",
      pane_l.secondary is False and pane_l.buttons_bar.isVisibleTo(pane_l)
      and not pane_l.hints_label.isVisibleTo(pane_l))
check("§4a the SECOND pane hides the row and spends the line on the hints (never both)",
      pane_r.secondary is True and not pane_r.buttons_bar.isVisibleTo(pane_r)
      and pane_r.hints_label.isVisibleTo(pane_r))
check("§4a the hint row is ONE line, elided, with the whole text in the tooltip",
      pane_r.hints_label.wordWrap() is False
      and pane_r.hints_label.toolTip() == pane_r.hints_label.text()
      and pane_r.hints_label.text() == pane_r.hint_text())
tab3.set_commander(False)
check("§4 turning the mode OFF leaves ONE pane and NO minimum floor behind",
      len(tab3.panes) == 1 and pane_l.minimumWidth() == 0 and pane_l.secondary is False
      and pane_l._ring.is_active() is False,
      f"panes={len(tab3.panes)} floor={pane_l.minimumWidth()}")
tab3.set_worker(None)
worker3.shutdown(wait_ms=2000)   # never leave a live QThread for GC (AGENTS.md §4.3)

# ════════════════════════════════════════════════════════════
# 5. The persistence (§5)
# ════════════════════════════════════════════════════════════
print("== 5. the persistence keys of the mode ==")

check("§5 the two DECLARED config keys are the ones the contract names",
      COMMANDER_CONFIG_BOOL == "ui_sftp_commander"
      and COMMANDER_CONFIG_RATIO == "ui_sftp_commander_ratio")
check("§5 the declared default and the declared clamp are the shipped numbers",
      COMMANDER_RATIO_DEFAULT == 0.5 and (COMMANDER_RATIO_MIN, COMMANDER_RATIO_MAX) == (0.2, 0.8),
      f"{COMMANDER_RATIO_DEFAULT} / {COMMANDER_RATIO_MIN}..{COMMANDER_RATIO_MAX}")
check("§5 a narrow pane has a DECLARED floor (installed only while the mode is on)",
      isinstance(COMMANDER_MIN_PANE_PX, int) and COMMANDER_MIN_PANE_PX > 0)
_defaults = STAB.load_commander_settings()
check("§5 a missing payload answers the defaults (a broken config opens no second pane)",
      _defaults == {"commander": False, "ratio": COMMANDER_RATIO_DEFAULT}, str(_defaults))
clear_cfg()
write_cfg({COMMANDER_CONFIG_BOOL: "true", COMMANDER_CONFIG_RATIO: "0.95"})
_foreign = STAB.load_commander_settings()
check("§5 a FOREIGN type answers the DEFAULT for both keys (never `bool('false')`)",
      _foreign == {"commander": False, "ratio": COMMANDER_RATIO_DEFAULT}, str(_foreign))
clear_cfg()
write_cfg({COMMANDER_CONFIG_BOOL: True, COMMANDER_CONFIG_RATIO: 0.99})
_clamped = STAB.load_commander_settings()
check("§5 an out-of-range ratio is CLAMPED into the declared band",
      _clamped["ratio"] == COMMANDER_RATIO_MAX and _clamped["commander"] is True, str(_clamped))
_writer = SftpTab()
check("§5 the mode writes its state as those two keys and keeps a foreign one",
      _writer.commander_extra_config({"ui_terminal_split": True}).get("ui_terminal_split") is True
      and set(_writer.commander_extra_config()) == {COMMANDER_CONFIG_BOOL, COMMANDER_CONFIG_RATIO})
_writer.set_worker(None)
clear_cfg()

# ════════════════════════════════════════════════════════════
# 6. The follow rule (§6)
# ════════════════════════════════════════════════════════════
print("== 6. the follow is OFF and greyed in the mode ==")

tab6, worker6, _log6, _client6 = make_tab(fs1, commander=False)
reported6 = []
tab6.follow_cwd_changed.connect(reported6.append)
tab6.set_follow_cwd(True)
tab6.set_worker(worker6)
check("§6 the follow is available and ON with a transport in the single-pane look",
      tab6.chk_follow_cwd.isEnabled() and tab6._follow_cwd is True)
tab6.set_commander(True)
check("§6 opening the mode switches the follow OFF, greys the switch and TELLS the session",
      tab6._follow_cwd is False and tab6.chk_follow_cwd.isChecked() is False
      and reported6[-1] is False and tab6.chk_follow_cwd.isEnabled() is False,
      f"reported={reported6!r} enabled={tab6.chk_follow_cwd.isEnabled()}")
check("§6 `follow_directory()` refuses in the mode (one OSC 7 cannot answer 'which pane')",
      tab6.follow_directory("/right") is False)
tab6.set_commander(False)
check("§6 leaving the mode restores the SWITCH (the state stays the user's)",
      tab6.chk_follow_cwd.isEnabled() is True and tab6._follow_cwd is False)
tab6.set_worker(None)
worker6.shutdown(wait_ms=2000)

# ════════════════════════════════════════════════════════════
# 7. The preview of §3b — the clause this audit closed
# ════════════════════════════════════════════════════════════
print("== 7. the preview clause: the panel really takes the other pane ==")

clear_cfg()
fs7 = FakeSftpFS()
fs7.add_dir("/left")
fs7.add_dir("/right")
fs7.add_file("/left/a.txt", b"alpha")
fs7.add_file("/left/b.bin", b"\x00\x01binary")
fs7.add_file("/left/c.txt", b"gamma")
fs7.add_file("/right/r.txt", b"right")
tab7, worker7, _log7, _client7 = make_tab(fs7, commander=True)
pane_l, pane_r = tab7.panes[0], tab7.panes[1]
msgs7 = []
tab7.message.connect(msgs7.append)
pane_l._relist("/left")
wait_until(lambda: item_by_name(pane_l, "a.txt") is not None, timeout_ms=5000)
pane_r._relist("/right")
wait_until(lambda: item_by_name(pane_r, "r.txt") is not None, timeout_ms=5000)
app.processEvents()

tab7.set_active_pane(pane_l)
pane_l._cmd_view()
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
check("§3b the panel of one pane is SHOWN in the OTHER pane's splitter (mc/far)",
      pane_l.viewer.parent() is pane_r.splitter and pane_l.viewer_text.toPlainText() == "alpha")
check("§3b ...and it really OCCUPIES the column it took over (a look-only panel shows nothing)",
      pane_l.viewer.width() > 0 and pane_l.viewer.isVisibleTo(pane_r)
      and pane_r.splitter.sizes()[pane_r.splitter.indexOf(pane_l.viewer)] > 0,
      f"w={pane_l.viewer.width()} sizes={pane_r.splitter.sizes()}")
check("§3b ...while the host's OWN panel steps aside (one panel on screen, ever)",
      pane_r.viewer.isHidden())
check("§3b the borrowing pane gives up its address bar and its key row (it is a PANEL)",
      pane_r._viewer_borrowed is True and not pane_r.path_label.isVisibleTo(pane_r)
      and not pane_r.buttons_bar.isVisibleTo(pane_r)
      and not pane_r.hints_label.isVisibleTo(pane_r))
# v1.7: the carrier is a PANEL, so its LISTING leaves the layout and the panel takes the whole
# pane (the mc/far quick view) — a shared half-width column wasted the space the file needs.
check("§3b ...and its LISTING leaves the layout: the panel takes the WHOLE pane",
      pane_r.tree.isHidden() and pane_r.splitter.sizes()[0] == 0
      and pane_l.viewer.width() >= pane_r.width() - 2,
      f"tree-hidden={pane_r.tree.isHidden()} sizes={pane_r.splitter.sizes()} "
      f"panel={pane_l.viewer.width()} pane={pane_r.width()}")
check("§3b ...and the disarmed listing answers none of its pane-scoped keys",
      pane_r.pane_shortcut("F3").isEnabled() is False
      and pane_r.pane_shortcut("F8").isEnabled() is False
      and pane_l.pane_shortcut("F3").isEnabled() is True)
check("§3b `Tab` with a panel next door is INERT (a panel is not a listing)",
      pane_l._on_pane_key(key_event(Qt.Key.Key_Tab)) is True and tab7.active_pane is pane_l,
      f"active={tab7.active_pane is pane_l}")
check("§3b the READING pane keeps its listing and its cursor (the panel is a view, not a move)",
      pane_l.tree.currentItem() is item_by_name(pane_l, "a.txt")
      and pane_l.path_label.isVisibleTo(pane_l))

msgs7.clear()
pane_l.tree.setCurrentItem(item_by_name(pane_l, "c.txt"))
pane_l._cmd_view()
for _ in range(6):
    app.processEvents()
check("§3b a second file from the READING pane is not 'busy': its own panel is re-read",
      pane_l.viewer_text.toPlainText() == "gamma"
      and pane_l.viewer.parent() is pane_r.splitter
      and i18n.t("sftp.cmd.preview_busy") not in msgs7,
      f"text={pane_l.viewer_text.toPlainText()!r} msgs={msgs7!r}")

msgs7.clear()
pane_l.tree.setCurrentItem(item_by_name(pane_l, "b.bin"))
pane_l._cmd_view()
for _ in range(8):
    app.processEvents()
check("§3b a read the worker REFUSES leaves the other pane a LISTING (no empty panel)",
      pane_l._viewer_open is False and tab7.preview_pane() is None
      and pane_r._viewer_borrowed is False
      and pane_r.path_label.isVisibleTo(pane_r) and pane_r.hints_label.isVisibleTo(pane_r)
      and i18n.t("sftp.viewer.binary") in msgs7,
      f"open={pane_l._viewer_open} msgs={msgs7!r}")

pane_l.tree.setCurrentItem(item_by_name(pane_l, "a.txt"))
pane_l._cmd_view()
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
msgs7.clear()
pane_r.tree.setCurrentItem(item_by_name(pane_r, "r.txt"))
pane_r._cmd_view()
for _ in range(6):
    app.processEvents()
check("§3b ONE preview at a time: the other pane's own file is refused with ONE sentence",
      i18n.t("sftp.cmd.preview_busy") in msgs7, str(msgs7))
closed = tab7.close_preview()
check("§3b `Esc` closes the open preview from EITHER side and the panels go home",
      closed is True and pane_l._viewer_open is False
      and pane_l.viewer.parent() is pane_l.splitter and pane_l.viewer.isHidden()
      and pane_r._viewer_borrowed is False and pane_r.path_label.isVisibleTo(pane_r))
for _ in range(3):
    app.processEvents()
wait_until(lambda: pane_r.splitter.sizes()[0] > 0, timeout_ms=2000)
check("§3b ...and the listing that stepped aside comes back with its keys armed",
      pane_r.tree.isHidden() is False and pane_r.splitter.sizes()[0] > 0
      and pane_r.pane_shortcut("F3").isEnabled() is True
      and pane_r.splitter.isCollapsible(0) is False,
      f"sizes={pane_r.splitter.sizes()} f3={pane_r.pane_shortcut('F3').isEnabled()} "
      f"collapsible={pane_r.splitter.isCollapsible(0)}")
check("§3b ...and with nothing open `Esc` is NOT consumed (it stays the widget's key)",
      tab7.close_preview() is False)

# `Esc` typed INTO the open panel closes it: the pane's own viewer counts as the pane even while
# the other one BORROWS it (a re-parented widget is nobody's descendant any more)
pane_l.tree.setCurrentItem(item_by_name(pane_l, "a.txt"))
pane_l._cmd_view()
wait_until(lambda: pane_l._viewer_open, timeout_ms=5000)
for _ in range(4):
    app.processEvents()
app.sendEvent(pane_l.viewer_text, key_event(Qt.Key.Key_Escape))
for _ in range(4):
    app.processEvents()
check("§3b `Esc` typed INSIDE the panel closes the preview (the panel is the owner's own widget)",
      pane_l._viewer_open is False and tab7.preview_pane() is None
      and pane_r.tree.isHidden() is False and pane_r._viewer_borrowed is False,
      f"open={pane_l._viewer_open} preview={tab7.preview_pane()!r} "
      f"tree-hidden={pane_r.tree.isHidden()}")
worker7.shutdown(wait_ms=2000)

# ════════════════════════════════════════════════════════════
# 8. The line's state and the documents (§8)
# ════════════════════════════════════════════════════════════
print("== 8. the line's state and the contract's own document ==")

_contract = os.path.join(ROOT, "SFTP_PANES.md")
check("§8 the frozen contract of the line is in the repository", os.path.exists(_contract))
_contract_text = ""
if os.path.exists(_contract):
    with open(_contract, encoding="utf-8") as fh:
        _contract_text = fh.read()
_SECTIONS = ("## 1. The pane model", "## 2. The worker API surface",
             "### 2a. The directory boundary", "## 3. The pane-scoped key map",
             "### 3a. The walk (rc3)", "### 3b. The preview in the other pane (rc3)",
             "## 4. The two-pane view and the ACTIVE pane", "### 4a. The hint row of the second pane",
             "## 5. The persistence", "## 6. The follow rule",
             "## 7. The refactor boundary", "## 8. Acceptance per slot")
_missing_sections = [s for s in _SECTIONS if s not in _contract_text]
check("§8 every clause of the contract keeps its heading (§-numbers are stable identifiers)",
      not _missing_sections, str(_missing_sections))
check("§8 the contract names the slot THIS release closes",
      "**`v1.7`:** the contract audit and the line's documents" in _contract_text)
check("§8 the contract stays FROZEN: it is not a changelog (no release narrative in it)",
      "used to" not in _contract_text and "previously" not in _contract_text)

check_release_state(ROOT)
check("§8 the version pin is the release this file describes",
      releases_at_least(EXPECTED_APP_VERSION, "1.7"), EXPECTED_APP_VERSION)
check("§8 ...and the line's release model is the ROADMAP one: a BASE release plus a follow-up",
      releases_at_least("1.7.0.1", "1.7") and releases_at_least("1.7.1", "1.7")
      and releases_at_least(EXPECTED_APP_VERSION, "1.7"),
      EXPECTED_APP_VERSION)
check("§8 the i18n pin counts the closing release and nothing of its own (the audit adds no key)",
      EXPECTED_I18N_KEYS >= 863, str(EXPECTED_I18N_KEYS))
check("§8 VERSION_FORMAT stays `0.9` (the Commander stores its state in config.json)",
      __import__("version").VERSION_FORMAT == "0.9")
check("§8 no new dependency was added (the four pinned ones)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))

finish()
