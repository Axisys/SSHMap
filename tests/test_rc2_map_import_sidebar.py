# -*- coding: utf-8 -*-
"""v1.1.2RC2 — Map, import, sidebar (release theme).

ROADMAP v1.1.2RC2 (the AUDIT §5 items, verified on v1.1.1):
  N3    MapView: the reset of the drag state on the loss of focus/activation (the focusOutEvent
         "blur" + changeEvent ActivationChange — there is no separate blurEvent for a QWidget):
         if _move_drag_node is set or
         dragMode()==NoDrag → ScrollHandDrag + the cleanup of _move_drag_node/
         _group_drag_olds. Before, the only reset — mouseReleaseEvent; the stickiness path — the loss
         of the capture (Alt+Tab in the middle of a drag).
  N6    the import from TXT: the DNS resolve outside the GUI thread — the batch resolve_host() in
         HostResolverThread (QThread, the _ProbeThread pattern) with the progress in the
         status bar; a file with dozens of names on an unreachable resolver does not
         freeze the interface. IP addresses do not need the resolve — synchronously.
  N8/N9 the dead code of the sidebar: item.setForeground(0, windowText()) (a visual
         no-op under the "tags in gray" comment) and setItemData(QColor,
         Qt.DecorationRole) (the standard style reads DecorationRole as a QIcon)
         — removed, the comments corrected.
  N10   the i18n key msg.confirm_delete_profile × en/ru/zh: the confirmation of the PROFILE deletion
         is no longer the server's msg.confirm_delete ("Delete server ...?").
         The release parity 373 → 375 (with v1.1.2 final — 377): +N10 (msg.confirm_delete_profile) and +N6
         (status.import_resolving — the resolve progress in the status bar).
  U1    the buttons of the sidebar are left-aligned: the offset from the left edge, the icon,
         the text (the users' remark; before — the central alignment by default).

Run: python tests/test_rc2_map_import_sidebar.py   (from the project root) or python tests/run_all.py
"""
import os
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until, viewport_point as _vp,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication, QMessageBox

from _fakes import QuestionStub
app = QApplication(sys.argv)


# ════════════════════════════════════════════════════════════
# N3. MapView: resetting the drag state on blur/ActivationChange
# ════════════════════════════════════════════════════════════
print("== N3: MapView drag-state reset on blur/activation ==")
from PySide6.QtCore import QPointF, QEvent, Qt as _Qt, QPoint as _QPt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest as _QTest
from PySide6.QtWidgets import QGraphicsView

from graphics.map_scene import MapScene
from graphics.map_view import MapView
from models.server import ServerData

scene3 = MapScene()
node3 = scene3.add_server(ServerData(id="n3srv01", alias="N3", host="10.0.0.1",
                                     user="u", x=100, y=100))
view3 = MapView(scene3)
view3.resize(400, 300)
view3.show()
app.processEvents()


def _stuck_drag():
    """Simulate a "stuck" gesture: NoDrag + the live state of the drag."""
    view3.setDragMode(QGraphicsView.NoDrag)
    view3._move_drag_node = node3
    view3._move_drag_old = QPointF(node3.pos())
    view3._group_drag_olds = [(node3, QPointF(node3.pos()))]


# (a) focusOutEvent ("blur" in ROADMAP terminology) — losing focus mid-drag
_stuck_drag()
check("N3: preconditions — NoDrag + _move_drag_node/_group_drag_olds",
      view3.dragMode() == QGraphicsView.NoDrag and view3._move_drag_node is node3
      and len(view3._group_drag_olds) == 1)
view3.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
check("N3: focusOutEvent (blur) restores ScrollHandDrag",
      view3.dragMode() == QGraphicsView.ScrollHandDrag, str(view3.dragMode()))
check("N3: focusOutEvent clears _move_drag_node/_move_drag_old",
      view3._move_drag_node is None and view3._move_drag_old is None)
check("N3: focusOutEvent clears _group_drag_olds", view3._group_drag_olds == [])

# (b) changeEvent(ActivationChange) — the window activation change (Alt+Tab)
_stuck_drag()
view3.changeEvent(QEvent(QEvent.Type.ActivationChange))
check("N3: changeEvent(ActivationChange) restores ScrollHandDrag",
      view3.dragMode() == QGraphicsView.ScrollHandDrag, str(view3.dragMode()))
check("N3: changeEvent clears drag state",
      view3._move_drag_node is None and view3._group_drag_olds == [])

# (c) the other changeEvent types do NOT touch the drag state
_stuck_drag()
view3.changeEvent(QEvent(QEvent.Type.FontChange))
check("N3: other changeEvent types do not reset drag state",
      view3.dragMode() == QGraphicsView.NoDrag and view3._move_drag_node is node3)
view3.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))  # cleanup

# (d) control: blur without an active drag — a no-op, no crash
check("N3: control — clean state before blur",
      view3.dragMode() == QGraphicsView.ScrollHandDrag and view3._move_drag_node is None)
view3.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
check("N3: control — blur with clean state is a no-op",
      view3.dragMode() == QGraphicsView.ScrollHandDrag and view3._move_drag_node is None)

# (e) the real gesture via QTest: press on a node → NoDrag; blur resets;
#     release after the reset creates NO undo command (the gesture is interrupted)
committed = []
view3.node_drag_committed.connect(lambda *a: committed.append(a))
view3.centerOn(_QPt(int(node3.pos().x()), int(node3.pos().y())))
app.processEvents()
_press_pt = _vp(view3, node3.sceneBoundingRect().center())
_QTest.mousePress(view3.viewport(), _Qt.LeftButton, pos=_press_pt)
app.processEvents()
check("N3: real press over node starts move-drag (NoDrag + _move_drag_node)",
      view3.dragMode() == QGraphicsView.NoDrag and view3._move_drag_node is node3,
      f"mode={view3.dragMode()}")
view3.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))  # Alt+Tab mid-drag
check("N3: blur mid-drag resets the stuck state",
      view3.dragMode() == QGraphicsView.ScrollHandDrag and view3._move_drag_node is None)
_QTest.mouseRelease(view3.viewport(), _Qt.LeftButton, pos=_press_pt)
app.processEvents()
check("N3: release after reset does NOT commit a move command (gesture interrupted)",
      committed == [], str(committed))
check("N3: drag mode stays ScrollHandDrag after the late release",
      view3.dragMode() == QGraphicsView.ScrollHandDrag, str(view3.dragMode()))


# ════════════════════════════════════════════════════════════
# N6. Import from TXT: DNS resolution outside the GUI thread
# ════════════════════════════════════════════════════════════
print("== N6: TXT import — DNS resolve off the GUI thread ==")
import services.host_importer as HI

_orig_resolve = HI.resolve_host

# (a) unit: HostResolverThread — resolution in a non-main thread, progress + result map
_fake_ips = {"alpha.example": "10.0.0.1", "beta.example": "10.0.0.2"}  # gamma — does not resolve


def _fake_resolve(name):
    time.sleep(0.03)
    return _fake_ips.get(name)


threads_seen = []


def _tracked_resolve(name):
    threads_seen.append(threading.current_thread())
    return _fake_resolve(name)


HI.resolve_host = _tracked_resolve
progress_events = []
result_map = {}
done_flag = {"ok": False}
thr = HI.HostResolverThread(["alpha.example", "beta.example", "gamma.example"])
thr.progress.connect(lambda d, t: progress_events.append((d, t)))


def _on_resolved(m):
    result_map.update(m)
    done_flag["ok"] = True


thr.resolved_map.connect(_on_resolved)
thr.start()
wait_until(lambda: done_flag["ok"], timeout_ms=5000)
check("N6: HostResolverThread finished", bool(thr.wait(2000)))
check("N6: resolve ran in a non-main thread (GUI thread untouched)",
      len(threads_seen) == 3 and all(th is not threading.main_thread() for th in threads_seen),
      f"seen={len(threads_seen)}")
check("N6: result map — resolved names → IP, unresolvable → None",
      result_map.get("alpha.example") == "10.0.0.1"
      and result_map.get("beta.example") == "10.0.0.2"
      and result_map.get("gamma.example") is None, str(result_map))
check("N6: progress(done, total) signals in order",
      progress_events == [(1, 3), (2, 3), (3, 3)], str(progress_events))

# (b) stop(): cancellation between names — not all of them get resolved
slow_count = {"n": 0}


def _slow_resolve(name):
    slow_count["n"] += 1
    time.sleep(0.25)
    return "10.1.1.1"


HI.resolve_host = _slow_resolve
thr2 = HI.HostResolverThread([f"h{i}.example" for i in range(5)])
res2 = {}
thr2.resolved_map.connect(lambda m: res2.update(m))
thr2.start()
time.sleep(0.1)  # the first probe in work (sleep 0.25 s) — we ask for a cancellation
thr2.stop()
check("N6: stop() finished the thread", bool(thr2.wait(5000)))
check("N6: stop() cancels the loop between names (not all 5 resolved)",
      slow_count["n"] < 5, f"resolved={slow_count['n']}")

# (c) E2E MainWindow: a file with IPs + names; the GUI is not blocked; progress in the status bar
import ui.main_window as MW
from PySide6.QtWidgets import QFileDialog
from modules.undo_commands import CmdAddRemoveNodeBatch

win = MW.MainWindow()
win.show()
app.processEvents()

txt_path = os.path.join(WORK, "rc2_hosts.txt")
with open(txt_path, "w", encoding="utf-8") as f:
    f.write("# comment\n// another\n10.1.1.1\nalpha.example\nbeta.example\nALPHA.EXAMPLE\n\n")

# a fake "unreachable resolver": 150 ms for the name; beta — never resolves
def _e2e_resolve(name):
    time.sleep(0.15)
    return {"alpha.example": "10.0.0.99"}.get(name)


HI.resolve_host = _e2e_resolve
_orig_open = QFileDialog.getOpenFileName
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (txt_path, ""))
info_calls = []
_orig_info = QMessageBox.information
QMessageBox.information = staticmethod(lambda *a, **k: info_calls.append(a) or QMessageBox.Ok)
status_msgs = []
win.statusBar().messageChanged.connect(status_msgs.append)

try:
    t0 = time.monotonic()
    win._import_servers_from_txt()
    elapsed_ms = (time.monotonic() - t0) * 1000
    check("N6 E2E: _import_servers_from_txt returns immediately (GUI not blocked)",
          elapsed_ms < 250, f"{elapsed_ms:.0f} ms")
    check("N6 E2E: resolver thread started and held on the window",
          win._import_resolve_thread is not None, str(win._import_resolve_thread))

    wait_until(lambda: len(win.scene.nodes()) == 3, timeout_ms=8000)
    app.processEvents()
    by_alias = {n.data.alias.lower(): n for n in win.scene.nodes()}
    check("N6 E2E: all three nodes on the map (IP + two names)",
          len(win.scene.nodes()) == 3, str(sorted(by_alias)))
    check("N6 E2E: IP entry — host=ip as-is",
          by_alias.get("10.1.1.1") is not None and by_alias["10.1.1.1"].data.ip == "10.1.1.1")
    check("N6 E2E: resolved name — ip filled, host stays the name",
          by_alias.get("alpha.example") is not None
          and by_alias["alpha.example"].data.ip == "10.0.0.99"
          and by_alias["alpha.example"].data.host == "alpha.example",
          str({a: n.data.ip for a, n in by_alias.items()}))
    check("N6 E2E: unresolvable name — node created with ip=''",
          by_alias.get("beta.example") is not None and by_alias["beta.example"].data.ip == "")
    check("N6 E2E: duplicate ALPHA.EXAMPLE deduped (3 nodes, not 4)",
          len(win.scene.nodes()) == 3, str(len(win.scene.nodes())))
    check("N6 E2E: progress visible in the status bar (i/N)",
          any("/2" in m for m in status_msgs), str(status_msgs[:6]))
    check("N6 E2E: result dialog added=3 skipped=0",
          len(info_calls) == 1
          and info_calls[0][2] == win.t("msg.import_servers_result", added=3, skipped=0),
          str(info_calls[:1]))

    top = win.undo_stack.command(win.undo_stack.count() - 1) if win.undo_stack.count() else None
    check("N6 E2E: one undo command for the whole batch",
          isinstance(top, CmdAddRemoveNodeBatch), f"cmd={type(top).__name__ if top else None}")
    win._undo()  # Ctrl+Z — the whole batch is reverted by a single command
    check("N6 E2E: Ctrl+Z removes the whole batch at once", len(win.scene.nodes()) == 0,
          str(len(win.scene.nodes())))

    # (d) IP addresses only — the synchronous path without a thread
    txt_ip = os.path.join(WORK, "rc2_ips.txt")
    with open(txt_ip, "w", encoding="utf-8") as f:
        f.write("10.2.2.2\n192.168.7.7\n")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (txt_ip, ""))
    info_calls.clear()
    win._import_servers_from_txt()
    app.processEvents()
    check("N6 E2E (IP-only): sync path — nodes added immediately, no resolver thread",
          len(win.scene.nodes()) == 2 and win._import_resolve_thread is None,
          f"nodes={len(win.scene.nodes())} thread={win._import_resolve_thread}")
finally:
    HI.resolve_host = _orig_resolve
    QFileDialog.getOpenFileName = _orig_open
    QMessageBox.information = _orig_info

# ════════════════════════════════════════════════════════════
# N8/N9. The sidebar dead code is removed
# ════════════════════════════════════════════════════════════
print("== N8/N9: sidebar dead code removed ==")

# (a) source level: the calls no longer exist in the CODE of ui/sidebar.py
# (comments naming removed code are allowed — we filter via tokenize)
import io as _io
import tokenize as _tokenize

with open(os.path.join(ROOT, "ui", "sidebar.py"), encoding="utf-8") as f:
    _sb_src = f.read()
_sb_code = "\n".join(tok.string for tok in _tokenize.generate_tokens(_io.StringIO(_sb_src).readline)
                     if tok.type != _tokenize.COMMENT)
check("N8: no setForeground call in ui/sidebar.py code", "setForeground" not in _sb_code)
check("N9: no DecorationRole in ui/sidebar.py code", "DecorationRole" not in _sb_code)

# (b) behaviour: a row with tags — a caption in the text, ForegroundRole is not set
from ui.sidebar import SidebarPanel, CONTEXT_MENU_ITEMS, _BUTTONS


class _FakeNodeN8:
    def __init__(self, data):
        self.data = data
        self.status = ""


_actions_n8 = {entry[0]: (lambda n: None) for entry in CONTEXT_MENU_ITEMS if entry is not None}
panel = SidebarPanel(translate_fn=None, actions=_actions_n8)
fake_nodes = [
    _FakeNodeN8(ServerData(id="n8a", alias="srv-a", host="10.0.0.1", user="u", ip="10.0.0.1",
                           tags=["prod", "db"])),
    _FakeNodeN8(ServerData(id="n8b", alias="srv-b", host="10.0.0.2", user="u", ip="", tags=[])),
]
panel.refresh_rows(fake_nodes)
check("N8: two rows built", panel.tree.topLevelItemCount() == 2, str(panel.tree.topLevelItemCount()))
item_a = panel.tree.topLevelItem(0)
check("N8: tag label at the end of the row", "[prod, db]" in item_a.text(0), item_a.text(0))
_fg = item_a.data(0, _Qt.ForegroundRole)
check("N8: ForegroundRole NOT set on tagged rows (no windowText paint)",
      _fg is None, str(_fg))

# (c) tag filter: "● tag" in the text, no DecorationRole data
panel.sync_tag_filter_items(fake_nodes)
combo = panel.tag_filter
texts = [combo.itemText(i) for i in range(combo.count())]
check("N9: combo has '● <tag>' items", "● prod" in texts and "● db" in texts, str(texts))
_deco = [combo.itemData(i, _Qt.DecorationRole) for i in range(1, combo.count())]
check("N9: no DecorationRole data on tag items (QColor was never rendered)",
      all(d is None for d in _deco), str(_deco))

# ════════════════════════════════════════════════════════════
# U1. The sidebar buttons — left alignment
# ════════════════════════════════════════════════════════════
print("== U1: sidebar buttons left-aligned ==")
_bad_align = []
_no_icon = []
for attr, _icon_name, _key, _ru in _BUTTONS:
    btn = getattr(panel, attr)
    ss = btn.styleSheet()
    if "text-align: left" not in ss or "padding-left" not in ss:
        _bad_align.append(attr)
    if btn.icon().isNull():
        _no_icon.append(attr)
check("U1: all 6 buttons — text-align: left + padding-left (the offset from the left edge)",
      not _bad_align, str(_bad_align))
check("U1: every button keeps its vector icon (icon, then text)", not _no_icon, str(_no_icon))
# v1.4.5 (ROADMAP task 1): the six buttons moved from full-width rows into a compact
# 2-column × 3-row grid and the row height shrank with them (34 → the compact height).
from ui.sidebar import _COMPACT_BUTTON_HEIGHT, _BUTTON_COLUMNS
check("U1: the buttons carry the compact row height (v1.4.5; was the full-width 34 px)",
      all(getattr(panel, a).minimumHeight() == _COMPACT_BUTTON_HEIGHT for a, *_r in _BUTTONS)
      and 0 < _COMPACT_BUTTON_HEIGHT < 34,
      str({a: getattr(panel, a).minimumHeight() for a, *_r in _BUTTONS}))
check("U1: the six buttons are placed in the compact grid (2 columns, 3 rows) — v1.4.5",
      panel.buttons_grid.count() == len(_BUTTONS) and _BUTTON_COLUMNS == 2,
      f"count={panel.buttons_grid.count()} columns={_BUTTON_COLUMNS}")

# ════════════════════════════════════════════════════════════
# N10. The i18n key msg.confirm_delete_profile
# ════════════════════════════════════════════════════════════
print("== N10: msg.confirm_delete_profile ==")
import i18n

for _code in ("en", "ru", "zh"):
    i18n.set_language(_code)
    _val = i18n.t("msg.confirm_delete_profile", alias="TestProfile")
    check(f"N10: {_code} — key translates and substitutes the alias placeholder",
          "TestProfile" in _val and _val != "msg.confirm_delete_profile", _val)
i18n.set_language("en")

check_i18n_parity(load_i18n_langs(ROOT))

# (b) dialog: confirming PROFILE deletion — its own key, not the server's msg.confirm_delete
from models import profile as _prof
from dialogs.profile_manager_dialog import ProfileManagerDialog

_p = _prof.add_profile(name="RC2Profile", user="rc2user")
dlg = ProfileManagerDialog(None)
dlg.refresh_table()
check("N10: profile visible in the dialog table",
      dlg.table.rowCount() >= 1 and dlg.table.item(0, 0).text() == "RC2Profile",
      str(dlg.table.rowCount()))
dlg.table.setCurrentCell(0, 0)
_qcalls = []
# the same shape the check reads: (…, title, text) — the stub hands over (title, text)
_question = QuestionStub(QMessageBox.Yes,
                         record=lambda title, text: _qcalls.append((None, title, text))).install()
try:
    dlg._on_delete_selected()
finally:
    _question.restore()
check("N10: question text is msg.confirm_delete_profile (alias substituted)",
      len(_qcalls) == 1 and _qcalls[0][2] == i18n.t("msg.confirm_delete_profile", alias="RC2Profile"),
      str(_qcalls[:1]))
check("N10: NOT the server-side msg.confirm_delete text",
      bool(_qcalls) and _qcalls[0][2] != i18n.t("msg.confirm_delete", alias="RC2Profile"),
      str(_qcalls[:1]))
check("N10: profile deleted after Yes",
      all(p.name != "RC2Profile" for p in _prof.load_profiles()),
      str([p.name for p in _prof.load_profiles()]))
dlg.close()

# ════════════════════════════════════════════════════════════
# Release state (pins — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

finish()
