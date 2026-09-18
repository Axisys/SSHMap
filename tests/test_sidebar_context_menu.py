"""Regression v0.9.6 — the context menu in the sidebar (server list).

ROADMAP v0.9.6:
  #1 the RMB on the server in the tree: Connect via SSH, the external terminal, Edit,
     Copy IP, Copy Hostname, Ping, Gather the information,
     Show on the map (the centering + the accent), Delete (the guarded path).
  #2 do NOT duplicate the "card" actions (the drag-connection, the plaque collapse) — they
     are not in the list.
  #3 the groups/notes — N/A: the tree shows only the servers (refresh_sidebar
     iterates scene.nodes()), the condition of the task is not met — no menu is needed for them.
  #4 i18n: all the keys are reused from ctx.*; the new one is only ctx.reveal_on_map × en/ru/zh.

Run:  python tests/test_sidebar_context_menu.py   (from the project root) or python tests/run_all.py
"""
import os, sys, tempfile, traceback

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QPoint, QTimer, QEventLoop
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication(sys.argv)


from i18n import t as it
from models.server import ServerData
import ui.main_window as MW

win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

# Two servers — the tree rows. The first has an explicit IP (for Copy IP), the second — none.
n1 = win.scene.add_server(ServerData(id="sb6a", alias="web-1", host="10.20.0.11",
                                     user="ops", ip="10.20.0.11", x=500, y=300))
n2 = win.scene.add_server(ServerData(id="sb6b", alias="db-1", host="db.internal",
                                     user="dba", ip="", x=800, y=500))
win.refresh_sidebar()
app.processEvents()


def _item_for(node_id):
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.data(0, Qt.UserRole) == node_id:
            return item
    return None


def _row_center(item):
    r = win.tree.visualItemRect(item)
    return QPoint(int(r.center().x()), int(r.center().y()))


# ── The QMenu interception (the regression_v081 pattern): exec does not block offscreen ──
from _fakes import CaptureMenu as _CaptureMenu

captured = []
_CaptureMenu.captured = captured


def _ctx_row(item):
    """The real path: the signal customContextMenuRequested → the slot of MainWindow."""
    captured.clear()
    win.tree.customContextMenuRequested.emit(_row_center(item))
    app.processEvents()
    return captured[-1] if captured else None


_orig_menu_cls = MW.QMenu
MW.QMenu = _CaptureMenu
try:
    item1 = _item_for("sb6a")
    check("tree has a row for the first server", item1 is not None,
          f"rows={win.tree.topLevelItemCount()}")

    # ══ #4. i18n: the new key ctx.reveal_on_map × en/ru/zh, the sets are identical ══
    print("== i18n ==")
    langs = load_i18n_langs(ROOT)
    check("ctx.reveal_on_map present and non-empty in en/ru/zh",
          all(langs[c].get("ctx.reveal_on_map", "").strip() for c in ("en", "ru", "zh")),
          str({c: langs[c].get("ctx.reveal_on_map") for c in ("en", "ru", "zh")}))
    # v0.9.7: +18 autosave/backups keys (file.restore_autosave … msg.open_project_first)
    # v0.9.8: +6 map search keys (view.find_on_map … status.no_matches)
    # v0.9.9.2: +13 external terminal UI keys (ssh_ext.section … ssh_ext.preset.kitty)
    # v0.9.9.7: +2 PDF export keys (file.export_pdf, status.export_pdf_ok)
    # v1.0RC4: +22 Quick launch keys (ctx.quick_launch … msg.ql_open_failed)
    # v1.1: +33 settings dialog keys (settings.* / menu.settings / btn.settings / status.settings_saved)
    # v1.1.2RC2: +2 keys (msg.confirm_delete_profile, status.import_resolving)
    # v1.1.2 final: +2 keys (settings.statuses.max_parallel, status.auto_interval_hint)
    check_i18n_parity(langs)
    _sidebar_keys = ["ctx.ssh_connect", "ctx.ssh_external", "ctx.edit_server",
                     "ctx.copy_ip", "ctx.copy_hostname", "ctx.ping",
                     "ctx.collect_info",
                     # v1.3.3.3 (ROADMAP task 5): the on-demand status round
                     "ctx.check_status",
                     "ctx.reveal_on_map", "ctx.delete_server"]
    check("all sidebar menu keys exist in every language",
          all(k in langs[c] for k in _sidebar_keys for c in ("en", "ru", "zh", "de")))

    # ══ #1. The menu composition and order (ROADMAP v0.9.6, item 1; v1.0RC4: +Quick launch) ══
    print("== menu composition ==")
    menu = _ctx_row(item1)
    check("context menu captured on right-click of a tree row", menu is not None)
    if menu:
        actions = [a for a in menu.actions()]
        non_sep = [a.text() for a in actions if a.isSeparator() is False]
        n_sep = sum(1 for a in actions if a.isSeparator())
        # v1.0RC4: the first item — the "Quick launch" submenu (sb6a has no items →
        # in it only "Configure…"), then a separator and the ROADMAP actions
        # (v1.3.3.3: +"Check statuses now" → 10 items).
        expected_order = [it("ctx.quick_launch")] + [it(k) for k in _sidebar_keys]
        check("menu has the Quick Launch submenu + the 10 ROADMAP actions",
              len(non_sep) == 11, f"got {len(non_sep)}: {non_sep}")
        check("action order: quick launch FIRST, then ROADMAP (ssh → … → check statuses → delete)",
              non_sep == expected_order, f"got={non_sep} want={expected_order}")
        check("menu grouped by 5 separators (4 ROADMAP + 1 after Quick Launch)",
              n_sep == 5, f"separators={n_sep}")
        # The submenu: a node without items — only "Configure…"
        ql_sub = next((a.menu() for a in actions if a.text() == it("ctx.quick_launch")), None)
        check("Quick Launch submenu exists as the first item", ql_sub is not None, str(non_sep[:2]))
        if ql_sub:
            ql_items = [a.text() for a in ql_sub.actions() if not a.isSeparator()]
            check("empty quick launch → submenu holds only 'Configure…'",
                  ql_items == [it("ql.configure")], str(ql_items))

        # ══ #2. The "card" actions are NOT duplicated in the list ══
        forbidden = {it("ctx.collapse_server"), it("ctx.expand_server"),
                     it("edit.connect_selected"), it("btn.add_connection")}
        leaked = [x for x in non_sep if x in forbidden]
        check("no card-only actions (the drag-connection / the plaque collapse) in the sidebar menu",
              not leaked, f"leaked={leaked}")

        # ══ #1. "Copy IP" — the clipboard receives the node's IP ══
        clip_before = app.clipboard().text()
        for act in menu.actions():
            if act.text() == it("ctx.copy_ip"):
                act.trigger()
                break
        app.processEvents()
        check("Copy IP puts the node IP into the clipboard",
              app.clipboard().text() == "10.20.0.11",
              f"clipboard={app.clipboard().text()!r} (before {clip_before!r})")

        # ══ #1. "Show on the map" — the selection + the centering + the accent flash ══
        status_before = n1.status
        for act in menu.actions():
            if act.text() == it("ctx.reveal_on_map"):
                act.trigger()
                break
        app.processEvents()
        check("reveal selects the node on the map", win.scene.get_selected_node() is n1,
              f"selected={win.scene.get_selected_node()}")
        c = view.mapFromScene(n1.sceneBoundingRect().center())
        vc = view.viewport().rect().center()
        check("reveal centers the view on the node",
              abs(float(c.x()) - float(vc.x())) < 3.0 and abs(float(c.y()) - float(vc.y())) < 3.0,
              f"node=({c.x():.1f},{c.y():.1f}) vp=({vc.x():.1f},{vc.y():.1f})")
        check("reveal accent flash is visible right after the action",
              n1._pulse.isVisible() and abs(n1._pulse.opacity() - 1.0) < 1e-6,
              f"visible={n1._pulse.isVisible()} opacity={n1._pulse.opacity()}")
        check("reveal does NOT change the node status (navigation signal, not a probe)",
              n1.status == status_before, f"{status_before!r} -> {n1.status!r}")
        wait_until(lambda: not n1._pulse.isVisible(), timeout_ms=2500)
        check("accent flash fades out and hides (900 ms animation completes)",
              not n1._pulse.isVisible())

        # ══ #1. "Connect SSH" — the node is selected, the dialog receives its data ══
        ssh_calls = []

        class _FakeSSHDialog:
            def __init__(self, data, parent=None):
                ssh_calls.append(data)
            def exec(self):
                return QDialog.Rejected

        _orig_ssh_dlg = MW.SSHConnectDialog
        MW.SSHConnectDialog = _FakeSSHDialog
        try:
            menu2 = _ctx_row(item1)
            if menu2:
                for act in menu2.actions():
                    if act.text() == it("ctx.ssh_connect"):
                        act.trigger()
                        break
            app.processEvents()
            check("SSH action selects the node and opens the dialog with its data",
                  len(ssh_calls) == 1 and ssh_calls[0] is n1.data
                  and win.scene.get_selected_node() is n1,
                  f"calls={len(ssh_calls)}")
        finally:
            MW.SSHConnectDialog = _orig_ssh_dlg

        # ══ #1. "External terminal" — connect_external receives the host/user/port ══
        ext_calls = []

        class _FakeExtTerm:
            def connect_external(self, **kw):
                ext_calls.append(kw)
                return (True, None)

        _orig_ext = MW._ext_term
        MW._ext_term = _FakeExtTerm()
        try:
            menu3 = _ctx_row(item1)
            if menu3:
                for act in menu3.actions():
                    if act.text() == it("ctx.ssh_external"):
                        act.trigger()
                        break
            app.processEvents()
            check("external terminal action passes host/user/port to connect_external",
                  len(ext_calls) == 1 and ext_calls[0].get("host") == "10.20.0.11"
                  and ext_calls[0].get("user") == "ops" and ext_calls[0].get("port") == 22,
                  f"calls={ext_calls}")
        finally:
            MW._ext_term = _orig_ext

        # ══ #1. "Gather information" — the collector is created and started (a fake, no SSH) ══
        import threading as _threading
        import services.system_info_collector as SIC
        from PySide6.QtCore import QThread, Signal as QtSignal

        collectors = []

        class _FakeCollector(QThread):
            info_ready = QtSignal(str, dict)
            info_failed = QtSignal(str, str)

            def __init__(self, data, password="", parent=None):
                super().__init__(parent)
                self._data = data
                collectors.append(self)
                self._stop_evt = _threading.Event()  # we hold "running" until the release

            def run(self):
                self._stop_evt.wait(timeout=5)  # without network; the cancellation — a flag (the pattern of the real class)

        _orig_coll_cls = SIC.SystemInfoCollector
        SIC.SystemInfoCollector = _FakeCollector
        try:
            menu4 = _ctx_row(item1)
            if menu4:
                for act in menu4.actions():
                    if act.text() == it("ctx.collect_info"):
                        act.trigger()
                        break
            app.processEvents()
            check("collect-info action starts a collector with the node data",
                  len(collectors) == 1 and collectors[0]._data is n1.data,
                  f"collectors={len(collectors)}")
            check("the running collector is registered in _info_collectors (the guard against the parallel runs)",
                  "sb6a" in win._info_collectors, str(list(win._info_collectors)))
            # We release the thread and check the cleanup by the finished signal
            for c in collectors:
                c._stop_evt.set()
            wait_until(lambda: not any(c.isRunning() for c in collectors), timeout_ms=2000)
            app.processEvents()
            check("collector finished -> registry entry cleaned up (finished handler)",
                  "sb6a" not in win._info_collectors, str(list(win._info_collectors)))
        finally:
            SIC.SystemInfoCollector = _orig_coll_cls

        # ══ #1. "Delete" — the guarded path (the confirmation → the worker guard → remove) ══
        rows_before = win.tree.topLevelItemCount()
        _orig_question = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        try:
            menu5 = _ctx_row(item1)
            if menu5:
                for act in menu5.actions():
                    if act.text() == it("ctx.delete_server"):
                        act.trigger()
                        break
            app.processEvents()
            check("delete action removes the node via the guarded path",
                  "sb6a" not in win.scene._nodes and n1.scene() is None,
                  f"nodes={list(win.scene._nodes)}")
            check("tree row disappears after delete (refresh_sidebar ran)",
                  win.tree.topLevelItemCount() == rows_before - 1,
                  f"rows {rows_before} -> {win.tree.topLevelItemCount()}")
            check("delete marks the project dirty", bool(win._dirty))
        finally:
            QMessageBox.question = _orig_question

    # ══ The empty area of the tree — the menu is not shown, no crashes ══
    print("== empty area ==")
    covered = [win.tree.visualItemRect(win.tree.topLevelItem(i))
               for i in range(win.tree.topLevelItemCount())]
    h = win.tree.height()
    empty_pos = None
    for y in (h - 2, h // 2, 5):
        p = QPoint(2, y)
        if not any(r.contains(p) for r in covered):
            empty_pos = p
            break
    if empty_pos is None:
        empty_pos = QPoint(2, max(h - 2, 1))
    captured.clear()
    try:
        win.tree.customContextMenuRequested.emit(empty_pos)
        app.processEvents()
        check("right-click on empty tree area shows no menu (no crash)", len(captured) == 0,
              f"captured={len(captured)}")
    except Exception as e:
        check("right-click on empty tree area shows no menu (no crash)", False, repr(e))

    # ══ Robustness: _reveal_node_on_map(None) — the node was removed while the menu was open ══
    try:
        win._reveal_node_on_map(None)
        check("_reveal_node_on_map(None) is a safe no-op", True)
    except Exception as e:
        check("_reveal_node_on_map(None) is a safe no-op", False, repr(e))

    # ══ The second node (a host without an IP): Copy IP copies the host — the existing semantics ══
    item2 = _item_for("sb6b")
    if item2 is not None:
        menu6 = _ctx_row(item2)
        if menu6:
            for act in menu6.actions():
                if act.text() == it("ctx.copy_ip"):
                    act.trigger()
                    break
            app.processEvents()
            check("Copy IP falls back to host when ip is empty (existing semantics)",
                  app.clipboard().text() == "db.internal",
                  f"clipboard={app.clipboard().text()!r}")
finally:
    MW.QMenu = _orig_menu_cls

# Cleanup: first reset dirty — otherwise closeEvent would go to the save dialog.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
