"""Фоновая проверка статусов узлов карты (v0.7.1).

Семантика статусов:
    online  — TCP-порт открыт И сервер прислал SSH-баннер ("SSH-x.y-...")
    warn    — порт открыт, но баннера нет за таймаут (не-SSH сервис / фильтр)
    offline — недоступен (refused / timeout / DNS)

Пробы выполняются в отдельном QThread (_ProbeThread), а не по QTimer на
главном потоке: синхронный socket.create_connection с timeout=3 c × N узлов
блокировал бы GUI. QTimer здесь только разводит раунды во времени
(интервал configurable, дефолт 30 c); одновременный повторный запуск
раунда невозможен (флаг _busy).

Отмена: stop()/shutdown() выставляют threading.Event — цикл проб выходит
между узлами (текущая проба доживает свой сетевой таймаут), затем поток
дожидается с запасом N × timeout + 2 c. Раньше shutdown ждал лишь
probe_timeout + 2 c, что при ≥ 2 узлах короче всего раунда — QObject
уничтожался вместе с работающим QThread (AUDIT v0.7.2, высокая #5).

В headless-окружении без работающего event loop таймеры не срабатывают —
потомки-потоки не стартуют, что делает модуль безопасным для smoke-тестов.
"""
import socket
import threading

from PySide6.QtCore import QObject, QThread, QTimer, Signal


STATUS_ONLINE = "online"    # зелёный: TCP + SSH баннер
STATUS_WARN = "warn"        # жёлтый: порт открыт, но нет баннера
STATUS_OFFLINE = "offline"  # красный: недоступен

DEFAULT_INTERVAL_MS = 30_000   # интервал периодических проверок
DEFAULT_INTERVAL_SEC = 30      # то же, в секундах — дефолт ключа status_interval_sec (v1.1)
PROBE_TIMEOUT_S = 3.0          # таймаут одной пробы (подключение + баннер)


def get_status_settings() -> dict:
    """v1.1 (ROADMAP задача 4): читать настройки статусов из ~/.sshmap/config.json.

    Источник — i18n.load_config() (никогда не падает, {} на ошибку). Возвращает:
        {"interval_sec": int, "probe_timeout_sec": float}
    Ключи ОПЦИОНАЛЬНЫ, дефолты = текущее поведение v1.0 (30 c / 3.0 c):
        status_interval_sec      — период раундов (кламп 5..86400 c);
        status_probe_timeout_sec — таймаут одной пробы (кламп 0.2..60 c).
    Битые значения (не-число, bool) → дефолт. Никогда не бросает.
    """
    cfg: dict = {}
    try:
        from i18n import load_config
        cfg = load_config() or {}
    except Exception:  # noqa: BLE001 — конфиг опционален, дефолты важнее
        pass

    def _num(value, default: float) -> float:
        try:
            if isinstance(value, bool):
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    interval = int(_num(cfg.get("status_interval_sec"), DEFAULT_INTERVAL_SEC))
    interval = max(5, min(interval, 86400))
    timeout = _num(cfg.get("status_probe_timeout_sec"), PROBE_TIMEOUT_S)
    timeout = max(0.2, min(timeout, 60.0))
    return {"interval_sec": interval, "probe_timeout_sec": timeout}


def probe_ssh(host: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> str:
    """Синхронная проба SSH-доступности. Вызывать только из потока!

    Подключается к host:port и читает первые байты: SSH-сервер сразу после
    TCP-handshake шлёт баннер "SSH-x.y-". Получили — online; соединение
    установлено, но данных нет/чужие — warn; не подключиться — offline.
    """
    if not host:
        return STATUS_OFFLINE
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            try:
                banner = sock.recv(32)
            except (socket.timeout, OSError):
                return STATUS_WARN  # соединение есть, данных за таймаут нет
            if not banner:
                return STATUS_WARN  # сервер закрыл соединение без байтов
            return STATUS_ONLINE if banner.lstrip().startswith(b"SSH-") else STATUS_WARN
    except (socket.timeout, OSError):
        return STATUS_OFFLINE


class _ProbeThread(QThread):
    """Один раунд проверки: пробы последовательно, результат — по мере готовности."""

    probed = Signal(str, str)  # (server_id, status)

    def __init__(self, targets, timeout: float = PROBE_TIMEOUT_S, parent=None,
                 cancel: "threading.Event | None" = None):
        super().__init__(parent)
        self._targets = list(targets)  # [(id, host, port), ...]
        self._timeout = max(0.2, float(timeout))
        self._cancel = cancel

    def run(self):
        for sid, host, port in self._targets:
            if self._cancel is not None and self._cancel.is_set():
                break  # раунд отменён (stop()/shutdown()) — не продолжаем пробы
            try:
                status = probe_ssh(host, port, self._timeout)
            except Exception:
                status = STATUS_OFFLINE  # проба не должна ронять раунд
            self.probed.emit(sid, status)


class StatusChecker(QObject):
    """Периодический контроллер проверок статусов узлов.

    Сигналы:
        status_changed(server_id, str) — определён статус одного сервера
        round_finished(list)           — раунд завершён; [(server_id, status), ...]

    Использование (MainWindow):
        checker = StatusChecker(parent=window)
        checker.status_changed.connect(on_status)
        checker.set_servers([(node.data.id, node.data.host, node.data.ssh_port), ...])
        checker.start()  # первый раунд через ~2 c + периодический QTimer
    """

    status_changed = Signal(str, str)
    round_finished = Signal(list)

    def __init__(self, interval_ms: int = DEFAULT_INTERVAL_MS,
                 probe_timeout: float = PROBE_TIMEOUT_S, parent=None):
        super().__init__(parent)
        self._interval = max(5000, int(interval_ms))  # не чаще раза в 5 c
        self._probe_timeout = float(probe_timeout)
        self._targets: list = []          # [(id, host, port), ...]
        self._busy = False                # раунд уже выполняется?
        self._last_results: dict = {}     # id -> последний status
        self._thread: _ProbeThread | None = None
        self._cancel = threading.Event()  # AUDIT v0.7.2 #5: отмена текущего раунда

        self._timer = QTimer(self)
        self._timer.setInterval(self._interval)
        self._timer.timeout.connect(self.start_round)

    @property
    def interval_ms(self) -> int:
        return self._interval

    @property
    def probe_timeout(self) -> float:
        """v1.1: таймаут одной пробы (сек) — для наглядности в тестах/диалоге."""
        return self._probe_timeout

    @property
    def is_busy(self) -> bool:
        return self._busy

    def set_interval(self, ms: int):
        """v1.1 (ROADMAP задача 4): сменить интервал раундов на лету (диалог «Статусы»).

        Кламп как в конструкторе (не чаще раза в 5 c). Работает и во время
        активного таймера — QTimer.setInterval перезапускает отсчёт.
        """
        self._interval = max(5000, int(ms))
        try:
            self._timer.setInterval(self._interval)
        except RuntimeError:
            pass  # Qt teardown — C++-объект таймера уже уничтожен

    def set_probe_timeout(self, seconds: float):
        """v1.1 (ROADMAP задача 4): сменить таймаут пробы (действует со следующего раунда)."""
        self._probe_timeout = max(0.2, float(seconds))

    def set_servers(self, servers):
        """Обновить список целей. `servers` — итерируемое (id, host, port)."""
        targets = []
        for sid, host, port in servers or ():
            if not sid or not host:
                continue  # без id/host проба бессмысленна
            try:
                p = int(port) if port else 22
            except (TypeError, ValueError):
                p = 22
            targets.append((sid, str(host).strip(), max(1, min(65535, p))))
        self._targets = targets

    def last_status(self, server_id: str) -> str:
        """Последний определённый статус сервера ("" — ещё не проверялся)."""
        return self._last_results.get(server_id, "")

    def start_round(self):
        """Запустить раунд проверки. Если предыдущий ещё идёт — ничего не делаем."""
        if self._busy or not self._targets:
            return
        self._busy = True
        self._cancel.clear()  # новый раунд — сбрасываем флаг отмены предыдущего
        thread = _ProbeThread(self._targets, self._probe_timeout, parent=self,
                              cancel=self._cancel)
        results = []

        def _on_probed(sid: str, status: str):
            results.append((sid, status))
            self._last_results[sid] = status
            self.status_changed.emit(sid, status)

        def _on_done():
            self._busy = False
            if self._thread is thread:
                self._thread = None
            thread.deleteLater()
            self.round_finished.emit(results)

        self._thread = thread
        thread.probed.connect(_on_probed)
        thread.finished.connect(_on_done)
        thread.start()

    def start(self):
        """Включить периодические проверки + первый раунд чуть позже запуска.

        Первый раунд через QTimer.singleShot(2000), а не сразу: при старте
        приложения сценарий событий ещё разворачивается, а в headless-тестах
        без event loop отложенный вызов просто не произойдёт (безопасно).
        """
        if not self._timer.isActive():
            self._timer.start()
            QTimer.singleShot(2000, self.start_round)

    def stop(self):
        """Остановить периодические проверки и текущий раунд.

        AUDIT v0.7.2 (высокая #5): ранний бег раунда невозможен — флаг отмены
        выставляется, цикл проб выходит между узлами; затем поток дожидаем с
        запасом N × timeout + 2 c (все пробы ограничены сетевыми таймаутами).
        """
        self._timer.stop()
        self._cancel.set()
        thread = self._thread
        if thread is not None and thread.isRunning():
            wait_ms = int(self._probe_timeout * 1000) * max(1, len(self._targets)) + 2000
            if not thread.wait(wait_ms):
                try:
                    from modules.logger import get_logger as _gl
                    _gl("services.status_checker").warning(
                        f"Probe thread did not finish within {wait_ms} ms after cancel")
                except Exception:
                    pass

    def shutdown(self):
        """Полная остановка при уничтожении MainWindow (сигнал destroyed).

        Таймер + отмена и ожидание текущего раунда — чтобы поток-проба не был
        уничтожен на ходу вместе с родителем (AUDIT v0.7.2, высокая #5: раньше
        ждали лишь probe_timeout + 2 c, что короче всего раунда при ≥ 2 узлах).
        """
        self.stop()
