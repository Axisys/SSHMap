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

    dns = ReverseDnsThread(host)
    dns.resolved.connect(on_resolved)        # (name: str)
    self._dns_thread = dns
    dns.start()
"""
import platform
import subprocess

from PySide6.QtCore import QThread, Signal


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

    def __init__(self, host_):
        super().__init__()
        self._host = host_

    def run(self):
        import socket as _socket
        try:
            name = _socket.gethostbyaddr(self._host)[0]
        except Exception:
            name = self._host  # DNS не отдал имя — копируем сам host
        self.resolved.emit(name)
