"""Статусы серверов: probe_ssh, цвета узлов, пульс, StatusChecker (бывш. smoke_test §6d).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * probe_ssh на локальных сокетах: online (баннер) / warn (порт молчит) / offline;
  * ServerNode: цвет рамки по статусу + tooltip через i18n + пульс-оверлей (анимация реально гаснет);
  * полный раунд StatusChecker (поток + сигналы round_finished);
  * интеграция StatusChecker ↔ MainWindow: план из узлов сцены, таймер,
    status_changed → покраска узла.

Запуск: python tests/test_status_checker.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

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

# online: локальный «SSH-сервер» шлёт баннер после accept
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

# warn: порт открыт, но данных нет (accept держит соединение молча)
port_warn = _free_port()
srv_w = _sock.socket(); srv_w.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
srv_w.bind(("127.0.0.1", port_warn)); srv_w.listen(1); srv_w.settimeout(3)

def _serve_silent():
    try:
        conn, _ = srv_w.accept()
        import time as _t3; _t3.sleep(2.5)  # дольше recv-таймаута пробы
        conn.close()
    except OSError:
        pass

th_warn = _threading.Thread(target=_serve_silent, daemon=True); th_warn.start()
check("probe_ssh: port open but no banner -> warn", probe_ssh("127.0.0.1", port_warn, 0.8) == "warn")

# offline: закрытый порт (connection refused мгновенно) + пустой host
port_off = _free_port()
check("probe_ssh: closed port -> offline", probe_ssh("127.0.0.1", port_off, 0.5) == "offline")
check("probe_ssh: empty host -> offline", probe_ssh("", 22, 0.5) == "offline")

# ServerNode: цвет рамки + tooltip + пульс-оверлей
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
n_st.set_status("bogus-status")  # неизвестный — игнорируется без ошибок
check("unknown status ignored (still warn)", n_st.status == "warn")
# selected приоритетнее статуса (и обратно — после снятия выделения)
n_st._selected = True
check("selection color wins over status", n_st._state_pen().color() == _SN.COLOR_SELECTED)
n_st._selected = False
check("pulse overlay exists and was shown by set_status", hasattr(n_st, "_pulse"))
# Анимация реально работает: новый статус перезапускает fade; после ~0.6 c
# накачки событий opacity оверлея должна упасть от 1.0
import time as _t_pulse
n_st.set_status("online")  # warn -> online: рестарт пульса с opacity=1.0
_p_start = n_st._pulse.opacity()
_deadline = _t_pulse.time() + 0.65
while _t_pulse.time() < _deadline and n_st._pulse.isVisible():
    app.processEvents(); _t_pulse.sleep(0.02)
check("pulse animation fades the overlay (opacity drops from ~1)",
      _p_start > 0.9 and n_st._pulse.opacity() < 0.75, f"{_p_start:.2f} -> {n_st._pulse.opacity():.2f}")
n_st.reset_status()
check("reset_status clears border back to transparent", n_st._state_pen().color().alpha() == 0)

# StatusChecker: полный раунд (поток + сигналы), цели — закрытый порт и online-сервер
chk = StatusChecker(interval_ms=5000, probe_timeout=1.0)
import time as _t4
srv_on.settimeout(3)  # второй accept для round (первый баннер уже ушёл)
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
_QTmr.singleShot(8000, loop.quit)  # страховка от зависания теста
chk.start_round()
loop.exec()
res_map = dict(rounds[0]) if rounds else {}
check("checker round finished with both targets", res_map.get("st-off") == "offline" and res_map.get("st-on") == "online", str(res_map))
check("last_status remembers per-server results", chk.last_status("st-on") == "online" and chk.last_status("nope") == "")
chk.shutdown()

# ── v0.7.1: StatusChecker ↔ MainWindow — связка (интеграция) ───────
win = MW.MainWindow()
win.scene.add_server(ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root"))
win.scene.add_server(ServerData(id="snode002", alias="db-1", host="10.0.0.6", user="root"))
check("MainWindow has StatusChecker wired", getattr(win, "_status_checker", None) is not None)
if getattr(win, "_status_checker", None) is not None:
    # _sync_status_targets собирает план проверок из узлов сцены (win: snode001/snode002)
    win._sync_status_targets()
    tgt = {sid: (host, port) for sid, host, port in win._status_checker._targets}
    check("_sync_status_targets puts scene nodes into the plan",
          tgt.get("snode001") == ("10.0.0.5", 22) and tgt.get("snode002") == ("10.0.0.6", 22), str(tgt))
    # start_status_checks — как в main.py после show(): не должен падать offscreen;
    # без event loop отложенный первый раунд (singleShot 2 c) просто не сработает.
    win.start_status_checks()
    check("start_status_checks activates periodic timer", win._status_checker._timer.isActive())
    # Сигнал status_changed (путь из _ProbeThread) → _on_node_status_changed → node.set_status
    n_chk = win.scene._nodes.get("snode001")
    check("node has no status before checker emit", n_chk is not None and n_chk.status == "")
    win._status_checker.status_changed.emit("snode001", "offline")
    check("status_changed(offline) paints node border red via window handler",
          n_chk.status == "offline" and n_chk._state_pen().color().name().lower() == "#ef4444")
    win._status_checker.status_changed.emit("snode001", "online")
    check("status_changed(online) repaints node border green",
          n_chk.status == "online" and n_chk._state_pen().color().name().lower() == "#22c55e")
    # Герметичность теста: останавливаем таймер и чистим план — если отложенный первый
    # раунд (singleShot) всё же сработает в поздних processEvents, целей не будет и поток
    # реальным хостам из JSON не пошлёт.
    win._status_checker.stop()
    win._status_checker.set_servers([])

finish()
