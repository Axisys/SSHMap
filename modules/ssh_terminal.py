import re
from typing import List

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from .terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES
except ImportError:
    from modules.terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES

try:
    from .terminal_widget import TerminalWidget
except ImportError:
    from modules.terminal_widget import TerminalWidget

try:
    from .host_key_policy import SshKnownHostsPolicy
except ImportError:
    from modules.host_key_policy import SshKnownHostsPolicy

# v1.1.3 (ROADMAP задачи 1–2): SFTP-вкладка — worker-поток с очередью задач и UI.
try:
    from .sftp_worker import SftpWorker, register_orphan_sftp_worker
except ImportError:
    from modules.sftp_worker import SftpWorker, register_orphan_sftp_worker

try:
    from .sftp_tab import SftpTab, format_size
except ImportError:
    from modules.sftp_tab import SftpTab, format_size

# v1.2 (ROADMAP v1.2): сессия вынесена в переиспользуемую страницу — окно стало
# тонкой обёрткой. terminal_page НЕ импортирует ssh_terminal на уровне модуля
# (берет его лениво через _st_module() — тестовый шов), поэтому цикл исключён.
try:
    from .terminal_page import TerminalSessionPage
except ImportError:
    from modules.terminal_page import TerminalSessionPage

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QPlainTextEdit,
    QMessageBox, QApplication, QTabWidget, QProgressBar,
)


# Pre-warmed translator for this module (loaded once on first call)
_t_cache = None

def get_translator():
    """Safe i18n helper — returns cached translator or fallback."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache


# ── v1.0 финал (ROADMAP задача 9): ключи terminal_* из ~/.sshmap/config.json ───
# Все ключи ОПЦИОНАЛЬНЫ, дефолты = текущее поведение (конфиг без ключей —
# вид ровно как в RC4): палитра "default", системный моноширинный pt 10, глубина
# HistoryScreen DEFAULT_HISTORY_LINES=1000 (скроллбэк ВКЛЮЧЁН — поведение RC3;
# явный 0 — пользователь сознательно отключил скроллбэк), закрытие сессии —
# сразу (v1.1: terminal_close_behavior). UI для ключей — v1.1 (диалог настроек);
# здесь они читаются при создании окна терминала.
def load_terminal_settings():
    """Читает и валидирует terminal_* ключи из ~/.sshmap/config.json.

    Источник — i18n.load_config() (никогда не падает, {} на ошибку). Возвращает:
      {"palette": str | None,     # None — не задан; неизвестное имя → окно держит "default"
       "font_family": str,        # "" — не задан (системный моноширинный)
       "font_size": int | None,   # None — не задан (pt 10)
       "history_lines": int,      # глубина deque-истории HistoryScreen (0 = выкл.)
       "close_behavior": str,     # v1.1: "close" (дефолт) | "ask" — поведение закрытия
       "max_open": int,           # v1.1.1: лимит своих открытых терминалов (дефолт 4)
       "wheel": str}              # v1.1.2RC3 (U3): "scrollback" (дефолт) | "off" — колесо
    Невалидные значения (чужой тип, вне диапазона) → дефолт. Никогда не бросает.
    """
    defaults = {"palette": None, "font_family": "", "font_size": None,
                "history_lines": DEFAULT_HISTORY_LINES, "close_behavior": "close",
                "max_open": 4, "wheel": "scrollback"}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    cfg = load_config()

    v = cfg.get("terminal_palette")
    if isinstance(v, str) and v.strip():
        defaults["palette"] = v.strip()   # неизвестное имя → set_palette() False → "default"

    v = cfg.get("terminal_font")
    if isinstance(v, str):
        defaults["font_family"] = v.strip()

    v = cfg.get("terminal_font_size")
    if isinstance(v, int) and not isinstance(v, bool) and 6 <= v <= 72:
        defaults["font_size"] = v         # вне диапазона → pt 10 (дефолт)

    v = cfg.get("terminal_history_lines")
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1_000_000:
        defaults["history_lines"] = v     # отрицательное/переполнение → дефолт 1000

    v = cfg.get("terminal_close_behavior")
    if isinstance(v, str) and v.strip().lower() in ("close", "ask"):
        defaults["close_behavior"] = v.strip().lower()  # битое/чужее → "close" (дефолт)

    # v1.1.1 (ROADMAP пункт 3): лимит своих открытых терминалов — дефолт 4;
    # при достижении MainWindow предлагает закрыть старейшую сессию, а не отказывает.
    v = cfg.get("terminal_max_open")
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 32:
        defaults["max_open"] = v     # битое/вне диапазона → 4 (дефолт)

    # v1.1.2RC3 (AUDIT U3, остаток): колесо мыши — "scrollback" (дефолт: колесо
    # скроллит локальный скроллбэк, как в v1.0RC3) | "off" (колесо не перехватывается
    # для скроллбэка; полный SGR-passthrough колеса в приложение — v1.2+, т.к. pyte
    # 0.8.2 не трекает mouse-режимы DECSET 1000/1002/1006). Ключ только конфиг
    # (решение по ROADMAP v1.1.2RC3 — без UI в диалоге настроек).
    v = cfg.get("terminal_wheel")
    if isinstance(v, str) and v.strip().lower() in ("scrollback", "off"):
        defaults["wheel"] = v.strip().lower()   # битое/чужое → "scrollback" (дефолт)

    return defaults


# ANSI escape sequences:
#   CSI (ESC [ ... final byte), simple escapes (ESC + char) и
#   OSC (ESC ] ... BEL | ESC \) — последовательности установки заголовка окна,
#   которые TUI-приложения (vim/htop) отправляют постоянно. Без их удаления
#   в выводе остаётся мусор вида «0;vim».
ANSI_ESCAPE_RE = re.compile(
    r'\x1B\[[0-?]*[ -/]*[@-~]'   # CSI: ESC [ params final
    r'|\x1B\][^\x07\x1b]*(?:\x07|\x1B\\)'  # OSC: ESC ] ... BEL / ST
    r'|\x1B[@-_]'                # simple two-byte escapes
)


# ── v1.1.2RC1 (N4): реестр орфано-терминальных потоков ────────────────────────
# Окно терминала имеет WA_DeleteOnClose: если его закрыть во время подключения,
# closeEvent ждёт поток лишь wait(1500), а paramiko может блокироваться до 15 c.
# Поток создан БЕЗ QObject parent — без сильного ссылающегося объекта GC уничтожит
# ЖИВОЙ QThread («QThread: Destroyed while thread is still running» + риск
# RuntimeError на поздних emit). Реестр держит такие потоки до finished() — паттерн
# _active_workers (modules/ssh_worker.py): все слоты окна уже отвязаны в closeEvent,
# поэтому поздние emit без приёмников — безопасный no-op.
_orphan_threads: List["SSHTerminalThread"] = []


def register_orphan_thread(thread: "SSHTerminalThread"):
    """Держать ещё работающий терминальный поток до finished() (v1.1.2RC1, N4).

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


class SSHTerminalThread(QThread):
    # v0.8.1: Signal(bytes), а не str — recv() возвращает байты, и PySide6 при
    # Signal(str) не может сконвертировать bytes в QString («Shiboken::Conversions:
    # Cannot copy-convert (bytes) to C++»); слот получал пустую строку, pyte ничего
    # не видел — терминал «не печатает». bytes ↔ QByteArray конвертируется штатно.
    output_signal = Signal(bytes)
    error_signal = Signal(str)
    status_signal = Signal(str)
    closed_signal = Signal()
    # v1.0RC4: Быстрый запуск — эмитится ровно один раз после invoke_shell,
    # когда канал жив и готов принимать ввод (окно отправляет первую команду).
    connected_signal = Signal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host = host
        self.user = user
        self.port = port
        self.password = password
        self.key_path = key_path
        self.client = None
        self.channel = None
        self.running = True

    def run(self):
        import paramiko
        t = get_translator()

        try:
            self.status_signal.emit(t("terminal.connecting", user=self.user, host=self.host, port=self.port))

            # AUDIT v0.7.2 (высокая #4): вместо AutoAddPolicy — known_hosts-пиннинг
            client = paramiko.SSHClient()
            policy = SshKnownHostsPolicy(hostname=self.host, port=self.port)
            policy.apply_to_client(client)

            if self.key_path:
                client.connect(
                    self.host,
                    username=self.user,
                    port=self.port,
                    key_filename=self.key_path,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=True,
                )
            elif self.password:
                client.connect(
                    self.host,
                    username=self.user,
                    password=self.password,
                    port=self.port,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=False,
                )
            else:
                client.connect(
                    self.host,
                    username=self.user,
                    port=self.port,
                    timeout=15,
                    look_for_keys=True,
                    allow_agent=True,
                )

            self.client = client
            self.channel = client.invoke_shell(term='xterm', width=120, height=32)
            self.channel.settimeout(0.2)
            # v1.0RC4: канал готов — окно может отправить первую команду (Быстрый запуск)
            self.connected_signal.emit()
            self.status_signal.emit(t("terminal.session_opened"))

            # AUDIT v0.7.2 (высокая #4): первое подключение — показать принятый отпечаток
            if policy.accepted_new_key and policy.last_fingerprint:
                note = t("ssh.host_key_new", host=self.host, fp=policy.last_fingerprint)
                self.status_signal.emit(note if not note.startswith("[")
                                        else f"New host key accepted ({policy.last_fingerprint})")

            while self.running and self.channel and not self.channel.closed:
                try:
                    if self.channel.recv_ready():
                        # v0.8: сырые байты без вырезания ANSI — их парсит pyte (TerminalScreen)
                        data = self.channel.recv(4096)
                        if data:
                            self.output_signal.emit(data)
                    else:
                        self.msleep(30)
                except TimeoutError:
                    continue
                except Exception as recv_error:
                    if self.running:
                        self.error_signal.emit(str(recv_error))
                    break

        except paramiko.BadHostKeyException as e:
            # AUDIT v0.7.2 (высокая #4): сохранённый ключ хоста изменился — вероятен MITM
            try:
                from modules.logger import get_logger as _gl
                _gl("modules.ssh_terminal").warning(f"Host key mismatch for {self.host}: {e}")
            except Exception:
                pass
            msg = t("ssh.host_key_changed", host=self.host) + "\n" + str(e)
            # v1.1.2RC1 (N4): guard как в recv-цикле — окно могло закрыться во время
            # подключения (stop() → running=False); поздний emit без приёмников не нужен.
            if self.running:
                self.error_signal.emit(msg if not msg.startswith("[") else f"Host key changed for {self.host}: {e}")
        except Exception as e:
            # v1.1.2RC1 (N4): guard как в recv-цикле — см. выше.
            if self.running:
                self.error_signal.emit(str(e))
        finally:
            self.running = False
            if self.channel:
                try:
                    self.channel.close()
                except Exception:
                    pass
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
            self.closed_signal.emit()

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            try:
                self.channel.send(data_bytes)
            except Exception as e:
                self.error_signal.emit(str(e))

    def stop(self):
        self.running = False


class SSHTerminalTextEdit(QPlainTextEdit):
    """DEPRECATED (v1.0RC1): HTML-путь QPlainTextEdit — заменён TerminalWidget
    (modules/terminal_widget.py, посячейный холст QWidget+QPainter). Класс оставлен
    до v1.2 (ROADMAP v1.0: «удалить не раньше v1.2»); SSHTerminalWindow его больше
    не создаёт. Клавиатурная обработка перенесена в TerminalWidget.keyPressEvent."""

    def __init__(self, terminal_thread, parent=None):
        super().__init__(parent)
        self.terminal_thread = terminal_thread
        self.setCursorWidth(2)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()

        if mod & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key_C:
                # v0.9.3 fix: стандартное поведение терминалов — Ctrl+C шлёт SIGINT
                # только когда нет выделения; при выделении копируем в буфер.
                if self.textCursor().hasSelection():
                    self.copy()
                    return
                self.terminal_thread.send_data(b'\x03')
                return
            elif key == Qt.Key_V:
                # v0.9.4-fix: вставка через bracketed paste — многострочный
                # буфер приходит в shell ЕДИНЫМ вставленным блоком, а не
                # построчным вводом (раньше каждая строка немедленно
                # исполнялась удалённой shell). Терминалы без поддержки
                # просто проигнорируют обёртку и получат сырой текст.
                clipboard = QApplication.clipboard()
                if clipboard.text():
                    try:
                        payload = clipboard.text().replace('\r\n', '\n').replace('\r', '\n')
                        self.terminal_thread.send_data(
                            b'\x1b[200~' + payload.encode('utf-8') + b'\x1b[201~')
                    except Exception:
                        pass
                    return
                event.ignore()
                return
            elif key == Qt.Key_D:
                self.terminal_thread.send_data(b'\x04')
                return
            elif key == Qt.Key_Z:
                self.terminal_thread.send_data(b'\x1a')
                return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.terminal_thread.send_data(b'\r')
            return
        elif key == Qt.Key_Backspace:
            self.terminal_thread.send_data(b'\x7f')
            return
        elif key == Qt.Key_Left:
            self.terminal_thread.send_data(b'\x1b[D')
            return
        elif key == Qt.Key_Right:
            self.terminal_thread.send_data(b'\x1b[C')
            return
        elif key == Qt.Key_Up:
            self.terminal_thread.send_data(b'\x1b[A')
            return
        elif key == Qt.Key_Down:
            self.terminal_thread.send_data(b'\x1b[B')
            return
        elif key == Qt.Key_Tab:
            self.terminal_thread.send_data(b'\t')
            return
        elif key == Qt.Key_Escape:
            self.terminal_thread.send_data(b'\x1b')
            return
        elif key == Qt.Key_Home:
            self.terminal_thread.send_data(b'\x1b[H')
            return
        elif key == Qt.Key_End:
            self.terminal_thread.send_data(b'\x1b[F')
            return
        elif key == Qt.Key_Delete:
            self.terminal_thread.send_data(b'\x1b[3~')
            return

        text = event.text()
        if text:
            try:
                self.terminal_thread.send_data(text.encode('utf-8'))
            except Exception:
                pass
            return

        event.ignore()


class SSHTerminalWindow(QMainWindow):
    """v1.2 (ROADMAP v1.2): ТОНКАЯ ОБЁРТКА над TerminalSessionPage.

    В окне остались только: WA_DeleteOnClose, заголовок, сохранение/восстановление
    геометрии (modules/window_geometry.py, ключ ui_window_geometry_terminal) и
    статус-бар с SFTP-прогресс-баром — мост для сигналов страницы (в режиме
    `windows` отображение идентично v1.1.x). Состояние сессии (thread + screen +
    терминальный виджет + статус-строка + SFTP) и ВСЯ cleanup-логика — на странице
    (modules/terminal_page.py): teardown проходит через ЕДИНЫЙ метод page.shutdown(),
    gate «ask» — page.confirm_close().

    Совместимость v1.1.x: атрибуты сессии доступны на окне как live-свойства
    (self.widget is self.page.widget и т.д.) — существующий код/тесты, читающие
    их по окну, работают без изменений.
    """

    def __init__(self, server_data: ServerData, parent=None, password: str = None,
                 initial_command: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        # BUGFIX v0.9.5.5 (сохранено): server_data на окне — compat-атрибут;
        # с v1.2 трекинг MainWindow читает его со СЕССИИ (page.server_data).
        self.server_data = server_data

        t = get_translator()
        self.setWindowTitle(t("terminal.window_title", alias=server_data.alias, host=server_data.host))
        self.resize(800, 600)

        # v1.1.2RC3 (AUDIT U2): восстановление размера/состояния предыдущего окна
        # терминала из config.json (сохраняется в closeEvent). Все окна терминала
        # делят один ключ ui_window_geometry_terminal — запоминается последний
        # закрытый; без ключа/битое значение → дефолтный 800×600 выше.
        try:
            from .window_geometry import restore_window_geometry as _restore_geo
        except ImportError:
            from modules.window_geometry import restore_window_geometry as _restore_geo
        _restore_geo("ui_window_geometry_terminal", self)

        # v1.2: сессия = переиспользуемая страница (thread + screen + холст +
        # статус-строка + SFTP-вкладка). Конфиг terminal_* читает сама страница.
        self.page = TerminalSessionPage(
            server_data, parent=self, password=password, initial_command=initial_command)
        self.page.set_host_window(self)
        self.setCentralWidget(self.page)

        # v1.2 (режим `windows`): «статус-бар» страницы мостится в статус-бар окна —
        # sticky-текст + SFTP-прогресс (permanent-виджет справа, скрыт когда передач
        # нет) ровно как в v1.1.x. Страница не знает о QMainWindow: в док-режиме
        # (v1.2.2) мост подключит док.
        self._sftp_progress = QProgressBar()
        self._sftp_progress.setFixedWidth(180)
        self._sftp_progress.setTextVisible(True)
        self._sftp_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._sftp_progress)
        self.page.status_message.connect(self._on_page_status_message)
        self.page.progress_busy.connect(self._on_page_progress_busy)
        self.page.progress_update.connect(self._on_page_progress_update)
        self.page.progress_hidden.connect(self._sftp_progress.hide)

    # ── v1.2: мост «статус-бар страницы → статус-бар окна» (вид = v1.1.x) ────

    def _on_page_status_message(self, text: str, timeout_ms: int):
        try:
            if timeout_ms > 0:
                self.statusBar().showMessage(text, timeout_ms)
            else:
                self.statusBar().showMessage(text)
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)

    def _on_page_progress_busy(self):
        try:
            self._sftp_progress.setRange(0, 0)   # пока не прилетел total — busy
            self._sftp_progress.setValue(0)
            self._sftp_progress.show()
        except RuntimeError:
            pass

    def _on_page_progress_update(self, done: int, total: int):
        try:
            if total > 0:
                self._sftp_progress.setRange(0, total)
                self._sftp_progress.setValue(done)
            else:
                self._sftp_progress.setRange(0, 0)   # total неизвестен — busy
        except RuntimeError:
            pass

    # ── v1.2: compat-атрибуты — сессия живёт на странице (live-ссылки) ───────

    @property
    def terminal_thread(self):
        return self.page.terminal_thread

    @property
    def tscreen(self):
        return self.page.tscreen

    @property
    def widget(self):
        return self.page.widget

    @property
    def tabs(self):
        return self.page.tabs

    @property
    def sftp_tab(self):
        return self.page.sftp_tab

    @property
    def status_label(self):
        return self.page.status_label

    @property
    def _close_behavior(self):
        return self.page._close_behavior

    @property
    def _pty_timer(self):
        return self.page._pty_timer

    @property
    def _last_cols(self):
        return self.page._last_cols

    @_last_cols.setter
    def _last_cols(self, value):
        self.page._last_cols = value

    @property
    def _last_rows(self):
        return self.page._last_rows

    @_last_rows.setter
    def _last_rows(self, value):
        self.page._last_rows = value

    @property
    def _pending_pty(self):
        return self.page._pending_pty

    @_pending_pty.setter
    def _pending_pty(self, value):
        self.page._pending_pty = value

    @property
    def _sftp_worker(self):
        """v1.1.3: ленивый SFTP-worker — с v1.2 живёт на странице (live-ссылка)."""
        return self.page._sftp_worker

    # ── v1.2: teardown — страница (единый метод) ────────────────────────────

    def close_terminal(self):
        """v1.0RC3 сохранён для cleanup-пути MainWindow: с v1.2 — делегирование
        на страницу (стоп потока + закрытие окна → closeEvent → shutdown)."""
        self.page.close_terminal()

    def closeEvent(self, event):
        # v1.1.2RC3 (AUDIT U2): сохранить размер/состояние окна ДО «ask»-диалога —
        # если пользователь отменит закрытие (event.ignore), записанные значения и так
        # равны текущим; при нормальном закрытии они будут прочитаны следующим окном.
        try:
            from .window_geometry import save_window_geometry as _save_geo
        except ImportError:
            from modules.window_geometry import save_window_geometry as _save_geo
        try:
            _save_geo("ui_window_geometry_terminal", self)
        except Exception:  # noqa: BLE001 — геометрия не блокирует закрытие
            pass

        # v1.2 (ROADMAP задача 3): «ask»-gate и ВСЯ cleanup-логика — на странице;
        # все teardown-пути проходят через единый метод page.shutdown() (идемпотентен).
        if not self.page.confirm_close():
            event.ignore()
            return
        self.page.shutdown()
        super().closeEvent(event)


