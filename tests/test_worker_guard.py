"""SSHWorker: реестр активных потоков + гард удаления узла (бывш. smoke_test.py §6c).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
  * реестр: worker виден после construction, исчезает по finished;
  * wait_for_worker: нестартованный поток → True мгновенно (guard не блокирует удаление),
    неизвестный id → True;
  * MainWindow._ensure_worker_done — единый guard для удаления узла;
  * SSHConnectDialog.closeEvent дожидается потока перед закрытием диалога.

Запуск: python tests/test_worker_guard.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData

# ── v0.6.x patch: SSHWorker registry + delete guard ───────
print("== v0.6.x worker guard ==")
from modules.ssh_worker import (
    SSHWorker as _SW, get_active_worker as _gaw, wait_for_worker as _wfw,
)

# 1) Реестр: создан → на месте; завершён → не виден. Реальный быстрый
# провал (127.0.0.1:9 — connection refused), поток завершается сам за <1 c.
w_g = _SW(host="127.0.0.1", user="u", port=9, server_id="guardtest")
check("worker registered in active registry on construction", _gaw("guardtest") is w_g)
# wait() на нестартованном потоке по Qt мгновенно true — guard не блокирует удаление
check("wait_for_worker: never-started worker -> True immediately", _wfw("guardtest", 500) is True)
# стартуем по-настоящему, чтобы проверить авто-очистку реестра по finished:
w_g2s = _SW(host="127.0.0.1", user="u", port=9, server_id="guardrun")
w_g2s.start()
check("started worker finishes (fast refused) and leaves registry",
      w_g2s.wait(3000) is True and _gaw("guardrun") is None)
# w_g нестартованный — вручную уберём из реестра, чтобы не засорять последующие проверки
from modules.ssh_worker import _active_workers as _aw_reg
_aw_reg.pop("guardtest", None)
check("wait_for_worker for unknown id -> True", _wfw("no-such-id", 100) is True)

# 2) MainWindow._ensure_worker_done — единый guard для удаления узла
win4 = MW.MainWindow()
ndg = ServerData(id="guardnode", alias="gn", host="127.0.0.1", user="u")
win4.scene.add_server(ndg)
check("_ensure_worker_done passes when no running worker", win4._ensure_worker_done("guardnode") is True)

# 3) SSHConnectDialog.closeEvent дожидается потока перед закрытием диалога:
# close() на невидимом виджете событие может не доставить — вызываем closeEvent напрямую.
from dialogs.ssh_connect_dialog import SSHConnectDialog as _SCD2
from PySide6.QtGui import QCloseEvent as _QCE

sdlg = _SCD2(ndg, None)
w_g3 = _SW(host="127.0.0.1", user="u", port=9, server_id="guardclose")
w_g3.start()
sdlg._ssh_worker = w_g3
_ev_close = _QCE()  # PySide6 6.11: конструктор без аргументов (Qt5-стиль)
sdlg.closeEvent(_ev_close)
check("dialog closeEvent waits for SSHWorker to finish", not w_g3.isRunning())
check("closeEvent accepts the close after worker done", _ev_close.isAccepted() is True)

finish()
