"""Фоновая диагностика узлов карты: ping + обратный DNS (v0.9.9.3).

Классы перенесены в v0.9.9.3 ИЗ ui/main_window.py, где они были вложены прямо
в методы `_ping_node` / `_copy_node_info` (фаза 0 серии «Гигиена main_window.py»).
НУЛЕВОЕ изменение поведения: те же сигналы, те же командные строки ping'а,
те же i18n-ключи, тот же fallback на host при неудаче DNS.

Паттерн «модуль + колбэки»: MainWindow держит ссылки на потоки
(`self._ping_thread` / `self._dns_thread` — guard AUDIT v0.7.2 #8 против
затирания работающего ping'а и orphan-потоков), подключает сигналы
локальными замыканиями-колбэками и стартует поток; остановка при закрытии
окна — общий `_shutdown_background_threads()` (stop()/wait(), как у StatusChecker).

Использование (MainWindow):
    from services.diagnostics import PingThread, ReverseDnsThread

    ping = PingThread(host)
    ping.finished_ping.connect(on_done)      # (ok: bool, text: str)
    self._ping_thread = ping                 # держать ссылку — не orphan
    ping.start()

    dns = ReverseDnsThread(host, parent=self)  # v1.2.10rc1: parent — владелец C++-объекта
    dns.resolved.connect(on_resolved)        # (name: str)
    self._dns_thread = dns
    dns.start()

v1.2.10rc1 (AUDIT авто #2 + находка верификации): реестр орфано-потоков
`_orphan_threads` + `register_orphan_thread()` — ping/DNS не имеют stop(), и при
недоступном резолвере getaddrinfo/ping доживают дольше wait-бюджета шатдауна
(~2 c); переживший поток нельзя оставлять на GC («QThread: Destroyed while thread
is still running») — реестр держит его до finished() (паттерн N4, _orphan_threads
из modules/ssh_terminal.py).
"""
import platform
import subprocess
from typing import List

from PySide6.QtCore import QThread, Signal


# ── v1.2.10rc1: реестр орфано-потоков ping/DNS (паттерн N4) ───────────────────
# PingThread/ReverseDnsThread НЕ имеют stop(): при закрытии окна их можно только
# ждать с бюджетом (~2 c, MainWindow._shutdown_background_threads). Если
# getaddrinfo/ping переживут бюджет (недоступный резолвер — ровно тот сценарий,
# ради которого DNS выносился в поток), живой QThread без сильного ссылающегося
# объекта нельзя оставлять на GC: «QThread: Destroyed while thread is still
# running» + риск RuntimeError на поздних emit. Реестр держит такие потоки до
# finished() — как _orphan_threads (modules/ssh_terminal.py, v1.1.2RC1 N4); все
# слоты окна к этому моменту уже отвязаны/окно закрыто, поэтому поздние emit без
# приёмников — безопасный no-op.
_orphan_threads: List["QThread"] = []


def register_orphan_thread(thread: "QThread"):
    """Держать ещё работающий ping/DNS-поток до finished() (v1.2.10rc1).

    Идемпотентно; самовычищается по сигналу finished().
    """
    if thread not in _orphan_threads:
        _orphan_threads.append(thread)

        def _drop(_=None, t=thread):
            try:
                _orphan_threads.remove(t)
            except ValueError:
                pass  # уже удалён (двойной finished — на практике не бывает)
        thread.finished.connect(_drop)


class PingThread(QThread):
    """Ping узла в отдельном потоке без блокировки GUI (v0.7.3).

    Windows: `ping -n 3`, POSIX: `ping -c 3`. Результат — сигнал finished_ping;
    интерпретация (статус-бар / диалог) остаётся за вызывающим колбэком.
    """

    finished_ping = Signal(bool, str)

    def __init__(self, host):
        super().__init__()
        self._host = host

    def run(self):
        try:
            from i18n import t as _t
        except Exception:
            def _t(key, **kw):
                return key.format(**kw) if kw else key
        # v1.2.10rc2 (AUDIT ручной #5d): guard ДО subprocess — Windows ping НЕ
        # поддерживает «--» (асимметрия веток: POSIX-команда ниже имеет его), поэтому
        # хост, начинающийся с «-», мог бы быть съеден как флаг. Такой хост невалиден
        # как DNS-имя и так — отказываемся БЕЗ запуска процесса (на обеих ОС).
        if isinstance(self._host, str) and self._host.startswith("-"):
            self.finished_ping.emit(False, _t("status.ping_failed", host=self._host))
            return
        count_flag = "-n" if platform.system() == "Windows" else "-c"
        # AUDIT v0.9.5.5 (безопасность #4): -w/-W — миллисекунды на Windows,
        # секунды на Linux; таймаут 3 с в обоих случаях. На Linux "--" перед
        # хостом, чтобы хост вида "-x" не съелся как флаг.
        if platform.system() == "Windows":
            cmd = ["ping", count_flag, "3", "-w", "3000", self._host]
        else:
            cmd = ["ping", "-c", "3", "-W", "3", "--", self._host]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if platform.system() == "Windows" else 0)
            ok = proc.returncode == 0
            key = "status.ping_ok" if ok else "status.ping_failed"
            msg = _t(key, host=self._host)
            out = proc.stdout.decode(errors="replace")[-400:] if not ok else ""
            self.finished_ping.emit(ok, msg + ("\n" + out if out else ""))
        except Exception as exc:
            self.finished_ping.emit(False, _t("status.ping_failed", host=self._host)
                                    + f" ({exc})")


class ReverseDnsThread(QThread):
    """Обратный DNS вне GUI-потока (AUDIT v0.7.2, средняя #6).

    gethostbyaddr при недоступном резолвере раньше замерзал на таймауте DNS
    в GUI-потоке; теперь — отдельный поток, сигнал resolved(name).
    DNS не отдал имя → name = сам host (колбэк копирует его как есть).
    """

    resolved = Signal(str)

    def __init__(self, host_, parent=None):
        # v1.2.10rc1 (AUDIT авто #2): parent — QObject-владелец C++-объекта потока
        # (MainWindow передаёт self): пока окно живо, поток не может быть уничтожен
        # GC независимо от Python-ссылок; переживший wait-бюджет шатдауна поток
        # регистрируется в _orphan_threads выше (register_orphan_thread).
        super().__init__(parent)
        self._host = host_

    def run(self):
        import socket as _socket
        try:
            name = _socket.gethostbyaddr(self._host)[0]
        except Exception:
            name = self._host  # DNS не отдал имя — копируем сам host
        self.resolved.emit(name)
