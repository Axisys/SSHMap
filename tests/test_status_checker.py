"""Server statuses: probe_ssh, node colors, pulse, StatusChecker (former smoke_test §6d).

A part of the suite split out of smoke_test.py v0.6–v0.9.2 (see INDEX.md).
  * probe_ssh on the local sockets: the online (the banner) / the warn (the port is silent) / the offline;
  * ServerNode: the color of the frame by the status + the tooltip through the i18n + the pulse overlay (the animation really goes out);
  * the full round of StatusChecker (the thread + the signals round_finished);
  * the integration of StatusChecker ↔ MainWindow: the plan from the nodes of the scene, the timer,
    status_changed → the coloring of the node.

Run: python tests/test_status_checker.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData

# ── v0.7.1: status checker (online/warn/offline) ───────────
print("== v0.7.1 statuses ==")
import socket as _sock, threading as _threading
from services.status_checker import probe_ssh, StatusChecker

def _free_port():
    s = _sock.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

# online: a local "SSH server" sends the banner after accept
port_on = _free_port()
srv_on = _sock.socket(); srv_on.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
srv_on.bind(("127.0.0.1", port_on)); srv_on.listen(1); srv_on.settimeout(3)

def _serve_banner():
    try:
        conn, _ = srv_on.accept()
        conn.sendall(b"SSH-2.0-SmokeTest\r\n")
        import time as _t2; _t2.sleep(0.4)
        conn.close()
    except OSError:
        pass

th_on = _threading.Thread(target=_serve_banner, daemon=True); th_on.start()
check("probe_ssh: TCP + SSH banner -> online", probe_ssh("127.0.0.1", port_on, 1.5) == "online")

# warn: the port is open, but there is no data (accept holds the connection silently)
port_warn = _free_port()
srv_w = _sock.socket(); srv_w.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
srv_w.bind(("127.0.0.1", port_warn)); srv_w.listen(1); srv_w.settimeout(3)

def _serve_silent():
    try:
        conn, _ = srv_w.accept()
        import time as _t3; _t3.sleep(2.5)  # longer than the probe recv timeout
        conn.close()
    except OSError:
        pass

th_warn = _threading.Thread(target=_serve_silent, daemon=True); th_warn.start()
check("probe_ssh: port open but no banner -> warn", probe_ssh("127.0.0.1", port_warn, 0.8) == "warn")

# offline: a closed port (connection refused instantly) + an empty host
port_off = _free_port()
check("probe_ssh: closed port -> offline", probe_ssh("127.0.0.1", port_off, 0.5) == "offline")
check("probe_ssh: empty host -> offline", probe_ssh("", 22, 0.5) == "offline")

# ServerNode: the frame color + the tooltip + the pulse overlay
from graphics.server_node import ServerNode as _SN
nd_st = ServerData(id="statnode", alias="st", host="127.0.0.1", user="u")
n_st = _SN(nd_st)
check("node has no status color initially (transparent pen)", n_st._state_pen().color().alpha() == 0)
n_st.set_status("offline")
check("set_status(offline): border turns red", n_st._state_pen().color().name().lower() == "#ef4444")
tip = n_st.toolTip()
check("set_status: tooltip filled via i18n with host (not raw key)",
      bool(tip) and not tip.startswith("[") and "127.0.0.1" in tip, tip)
n_st.set_status("online")
check("set_status(online): border turns green", n_st._state_pen().color().name().lower() == "#22c55e")
n_st.set_status("warn")
check("set_status(warn): border turns yellow", n_st._state_pen().color().name().lower() == "#facc15")
n_st.set_status("bogus-status")  # an unknown one — ignored without errors
check("unknown status ignored (still warn)", n_st.status == "warn")
# selected takes priority over the status (and vice versa — after deselecting)
n_st._selected = True
check("selection color wins over status", n_st._state_pen().color() == _SN.COLOR_SELECTED)
n_st._selected = False
check("pulse overlay exists and was shown by set_status", hasattr(n_st, "_pulse"))
# The animation really works: a new status restarts the fade; after ~0.6 s
# the flood of the overlay opacity events must drop from 1.0
import time as _t_pulse
n_st.set_status("online")  # warn -> online: the pulse restarts with opacity=1.0
_p_start = n_st._pulse.opacity()
_deadline = _t_pulse.time() + 0.65
while _t_pulse.time() < _deadline and n_st._pulse.isVisible():
    app.processEvents(); _t_pulse.sleep(0.02)
check("pulse animation fades the overlay (opacity drops from ~1)",
      _p_start > 0.9 and n_st._pulse.opacity() < 0.75, f"{_p_start:.2f} -> {n_st._pulse.opacity():.2f}")
n_st.reset_status()
check("reset_status clears border back to transparent", n_st._state_pen().color().alpha() == 0)

# StatusChecker: a full round (a thread + signals), the targets — a closed port and an online server
chk = StatusChecker(interval_ms=5000, probe_timeout=1.0)
import time as _t4
srv_on.settimeout(3)  # the second accept for the round (the first banner already went)
def _serve_banner2():
    try:
        conn, _ = srv_on.accept()
        conn.sendall(b"SSH-2.0-SmokeTest\r\n")
        _t4.sleep(0.4); conn.close()
    except OSError:
        pass
th_on2 = _threading.Thread(target=_serve_banner2, daemon=True); th_on2.start()

chk.set_servers([("st-off", "127.0.0.1", port_off), ("st-on", "127.0.0.1", port_on)])
from PySide6.QtCore import QEventLoop as _QEL, QTimer as _QTmr
loop = _QEL()
rounds = []
chk.round_finished.connect(lambda r: (rounds.append(r), loop.quit()))
_QTmr.singleShot(8000, loop.quit)  # a guard against the test hanging
chk.start_round()
loop.exec()
res_map = dict(rounds[0]) if rounds else {}
check("checker round finished with both targets", res_map.get("st-off") == "offline" and res_map.get("st-on") == "online", str(res_map))
check("last_status remembers per-server results", chk.last_status("st-on") == "online" and chk.last_status("nope") == "")
chk.shutdown()

# ── v0.7.1: StatusChecker ↔ MainWindow — the wiring (integration) ───────
win = MW.MainWindow()
win.scene.add_server(ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root"))
win.scene.add_server(ServerData(id="snode002", alias="db-1", host="10.0.0.6", user="root"))
check("MainWindow has StatusChecker wired", getattr(win, "_status_checker", None) is not None)
if getattr(win, "_status_checker", None) is not None:
    # _sync_status_targets assembles the check plan from the scene's nodes (win: snode001/snode002)
    win._sync_status_targets()
    tgt = {sid: (host, port) for sid, host, port in win._status_checker._targets}
    check("_sync_status_targets puts scene nodes into the plan",
          tgt.get("snode001") == ("10.0.0.5", 22) and tgt.get("snode002") == ("10.0.0.6", 22), str(tgt))
    # start_status_checks — as in main.py after show(): must not crash offscreen;
    # without an event loop the deferred first round (singleShot 2 s) simply does not fire.
    win.start_status_checks()
    check("start_status_checks activates periodic timer", win._status_checker._timer.isActive())
    # The status_changed signal (the path from _ProbeThread) → _on_node_status_changed → node.set_status
    n_chk = win.scene._nodes.get("snode001")
    check("node has no status before checker emit", n_chk is not None and n_chk.status == "")
    win._status_checker.status_changed.emit("snode001", "offline")
    check("status_changed(offline) paints node border red via window handler",
          n_chk.status == "offline" and n_chk._state_pen().color().name().lower() == "#ef4444")
    win._status_checker.status_changed.emit("snode001", "online")
    check("status_changed(online) repaints node border green",
          n_chk.status == "online" and n_chk._state_pen().color().name().lower() == "#22c55e")
    # The test hermeticity: we stop the timer and clear the plan — if the deferred first
    # the round (singleShot) will still fire in the late processEvents, there will be no targets and the thread
    # to the real hosts from the JSON it will not send.
    win._status_checker.stop()
    win._status_checker.set_servers([])

finish()
