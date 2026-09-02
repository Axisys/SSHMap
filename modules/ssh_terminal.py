import re

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

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QPlainTextEdit,
    QMessageBox, QApplication,
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
       "max_open": int}           # v1.1.1: лимит своих открытых терминалов (дефолт 4)
    Невалидные значения (чужой тип, вне диапазона) → дефолт. Никогда не бросает.
    """
    defaults = {"palette": None, "font_family": "", "font_size": None,
                "history_lines": DEFAULT_HISTORY_LINES, "close_behavior": "close",
                "max_open": 4}
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
            self.error_signal.emit(msg if not msg.startswith("[") else f"Host key changed for {self.host}: {e}")
        except Exception as e:
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
    # v1.0RC3: dirty-рендер БЕЗ таймера — _on_output вызывает widget.update()
    # напрямую (queued signal уже в GUI-потоке); мигание курсора — свой QTimer
    # внутри TerminalWidget (останавливается при скрытом окне). Resize PTY —
    # guard по смене сетки + дебаунс ~150 мс перед channel.resize_pty
    # (TERMINAL.md §5.5, ROADMAP задача 6); начальный invoke_shell остаётся
    # 120×32 — первый resizeEvent синхронизирует с реальным размером окна.
    PTY_RESIZE_DEBOUNCE_MS = 150

    # v1.0RC4: Быстрый запуск — задержка отправки первой команды после invoke_shell.
    # Даем удалённому shell время на старт (login-скрипты/motd); ввод в PTY
    # буферизуется, поэтому команда не теряется даже если промпт появится позже.
    INITIAL_COMMAND_DELAY_MS = 500

    def __init__(self, server_data: ServerData, parent=None, password: str = None,
                 initial_command: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        # BUGFIX v0.9.5.5: сохраняем server_data на окне — _forget_terminal_window()
        # в MainWindow читает getattr(window, "server_data", None), чтобы погасить
        # зелёную SSH-точку узла при закрытии терминала.
        self.server_data = server_data

        t = get_translator()
        self.setWindowTitle(t("terminal.window_title", alias=server_data.alias, host=server_data.host))
        self.resize(800, 600)

        widget = QWidget()
        self.setCentralWidget(widget)
        layout = QVBoxLayout(widget)

        self.status_label = QLabel(t("terminal.initializing"))
        self.status_label.setStyleSheet("color: #94a3b8; padding: 4px 0;")
        layout.addWidget(self.status_label)

        # AUDIT v0.7.2 (средняя #7): явный пароль приоритетнее node.data.password —
        # модель не загрязняется открытым текстом до записи в keyring/сохранения проекта.
        if password is not None:
            pwd = password or ""
        else:
            pwd = getattr(server_data, 'password', '') or ""
        self.terminal_thread = SSHTerminalThread(
            host=server_data.host,
            user=server_data.user,
            port=server_data.ssh_port or 22,
            password=pwd,
            key_path=server_data.key_path,
        )

        # v1.0 финал (ROADMAP задача 9): terminal_* ключи из ~/.sshmap/config.json —
        # все опциональны, дефолты = текущее поведение (вид RC4). UI — v1.1.
        term_cfg = load_terminal_settings()
        # v1.1 (ROADMAP задача 3): поведение закрытия сессии — используется в closeEvent.
        self._close_behavior = term_cfg["close_behavior"]

        # v0.8: pyte-экран — сетка 120x32, та же геометрия, что у invoke_shell;
        # глубина скроллбэка HistoryScreen — terminal_history_lines (дефолт 1000).
        self.tscreen = TerminalScreen(columns=120, lines=32,
                                      history_lines=term_cfg["history_lines"])

        # v1.0RC1: посячейный холст (QWidget + QPainter) вместо QPlainTextEdit+HTML.
        # Шрифт — системный моноширинный pt 10 (AUDIT v0.7.2 низкая #18), палитра
        # 'default' = текущий вид; runs/курсор/широкие глифы — см. terminal_widget.py.
        self.widget = TerminalWidget(self.tscreen, self.terminal_thread)
        # v1.0 финал: применение конфига (неизвестная палитра → set_palette() False
        # → остаётся "default"; битые значения отброшены в load_terminal_settings).
        if term_cfg["palette"] is not None:
            self.widget.set_palette(term_cfg["palette"])
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            self.widget.set_font(
                family=term_cfg["font_family"],
                size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)
        layout.addWidget(self.widget)

        # v1.0RC3: кнопка «Закрыть терминал» убрана (смущала пользователей) —
        # окно закрывается штатным крестиком; close_terminal() сохранён для
        # cleanup-пути MainWindow (там же, где и раньше).

        # v1.0RC3: resize PTY — guard по смене сетки + дебаунс ~150 мс
        # (TERMINAL.md §5.5): начальный invoke_shell остаётся 120×32, первый
        # resizeEvent синхронизирует с реальным размером окна.
        self._last_cols, self._last_rows = 120, 32
        self._pending_pty = None
        self._pty_timer = QTimer(self)
        self._pty_timer.setInterval(self.PTY_RESIZE_DEBOUNCE_MS)
        self._pty_timer.timeout.connect(self._on_pty_debounce)

        self.terminal_thread.output_signal.connect(self._on_output)
        self.terminal_thread.error_signal.connect(self._show_error)
        self.terminal_thread.status_signal.connect(self._set_status)
        self.terminal_thread.closed_signal.connect(self._on_closed)

        # v1.0RC4: Быстрый запуск — первая команда отправляется после подключения
        # (connected_signal), а не до него: при неудачной аутентификации команда
        # просто не уходит, ошибка показывается штатным error-путём.
        self._initial_command = (initial_command or "").strip()
        if self._initial_command:
            self.terminal_thread.connected_signal.connect(self._send_initial_command)

        self.terminal_thread.start()
        self.widget.setFocus()

    def _send_initial_command(self):
        """v1.0RC4: отправить первую команду (Быстрый запуск) в shell после подключения.

        Отложенный вызов (INITIAL_COMMAND_DELAY_MS): invoke_shell возвращает канал
        сразу, а удалённый shell может ещё дописывать motd/login-скрипты; PTY-ввод
        буферизуется ядром, так что команда выполнится при появлении промпта.
        Отправляется ровно один раз; мёртвый/закрытый канал — тихий no-op.
        """
        def _do():
            try:
                cmd = getattr(self, "_initial_command", "")
                if not cmd:
                    return
                self._initial_command = ""  # только один раз
                thread = getattr(self, "terminal_thread", None)
                channel = getattr(thread, "channel", None) if thread is not None else None
                if channel is None or channel.closed:
                    return
                thread.send_data((cmd + "\n").encode("utf-8"))
            except Exception:  # noqa: BLE001 — окно могло закрыться (WA_DeleteOnClose)
                pass
        QTimer.singleShot(self.INITIAL_COMMAND_DELAY_MS, _do)

    # ── v1.0RC3: dirty-рендер без таймера (ROADMAP задача 8) ──────────────
    def _on_output(self, data: bytes):
        """Слот из SSH-потока (queued signal — уже в GUI-потоке): сырые байты
        в pyte + прямой update() холста. 30 FPS-таймер не нужен: Qt сам
        коалесит несколько update() за один цикл событий; paintEvent читает
        сетку сам (TerminalWidget._paint). Авто-снап скроллбэка к live-строке
        при новом выводе — внутри pyte (HistoryScreen.before_event), поэтому
        новый вывод виден сразу, даже если пользователь смотрел историю."""
        try:
            self.tscreen.feed(data)
        except Exception:
            return
        try:
            self.widget.update()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка WA_DeleteOnClose при закрытии)

    # ── v1.0RC3: resize PTY — guard по сетке + дебаунс (ROADMAP задача 6) ──
    def _visible_grid(self):
        """(cols, rows) видимой сетки: размер холста / метрики ячейки."""
        cw, chh = self.widget.cell_size
        cols = max(2, self.widget.width() // cw)
        rows = max(1, self.widget.height() // chh)
        return cols, rows

    def resizeEvent(self, event):
        """Ресайз окна → сетка (TERMINAL.md §5.5). Guard: PTY-сигнал только при
        РЕАЛЬНОЙ смене сетки — каждый пиксель перетаскивания не шлёт SIGWINCH;
        дебаунс ~150 мс коалесит серию изменений в один resize_pty.

        Пересчёт отложен на singleShot(0): в момент resizeEvent layout центрального
        виджета ещё может не устояться (холст получает итоговый размер после
        polish/активации) — иначе сетка посчитается от транзитного размера."""
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_grid)

    def _sync_grid(self):
        """Пересчёт видимой сетки (после устоявшегося layout)."""
        try:
            cols, rows = self._visible_grid()
            if (cols, rows) == (self._last_cols, self._last_rows):
                return  # сетка не изменилась — ни pyte.resize, ни PTY-сигнал
            self._last_cols, self._last_rows = cols, rows
            self.tscreen.resize(cols, rows)   # pyte: no-op при том же размере (факт №9)
            self.widget.update()              # сетка изменилась — перерисовать холст
            self._pending_pty = (cols, rows)
            self._pty_timer.start()           # перезапуск отсчёта 150 мс (дебаунс)
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка WA_DeleteOnClose при закрытии)

    def _on_pty_debounce(self):
        """Дебаунс истёк — resize_pty с ПОСЛЕДНЕЙ сеткой (только живой канал)."""
        if self._pending_pty is None:
            return
        cols, rows = self._pending_pty
        self._pending_pty = None
        thread = getattr(self, "terminal_thread", None)
        channel = getattr(thread, "channel", None) if thread is not None else None
        if channel is None or channel.closed:
            return
        try:
            channel.resize_pty(width=cols, height=rows)
        except Exception:
            pass  # канал умер во время дебаунса — нечего делать

    def _set_status(self, text: str):
        self.status_label.setText(text)
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(text)

    def _show_error(self, error: str):
        t = get_translator()
        self.status_label.setText(f"{t('terminal.error_prefix')} {error}")
        QMessageBox.critical(
            self, 
            t("msg.ssh_error"), 
            f"{t('terminal.error_prefix')} {error}"
        )
        self.close()

    def _on_closed(self):
        t = get_translator()
        self.status_label.setText(t("terminal.session_closed"))
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(t("terminal.session_closed"))

    def close_terminal(self):
        self.terminal_thread.stop()
        self.close()

    def closeEvent(self, event):
        # v1.1 (ROADMAP задача 3): поведение закрытия сессии — terminal_close_behavior.
        # "ask": активная сессия (SSH-поток ещё работает) → подтверждение; отмена =
        # окно живёт (event.ignore). "close" (дефолт, как в v1.0) и уже завершённая
        # сессия — без диалога. Теardown-устойчивость: RuntimeError C++-объектов не
        # должен блокировать закрытие.
        try:
            # v1.1.1 (ROADMAP пункт 3): закрытие по лимиту своих терминалов —
            # MainWindow ставит флаг _force_close, чтобы уже подтверждённое
            # пользователем решение («закрыть старейшую») не спрашивали повторно.
            if getattr(self, "_close_behavior", "close") == "ask" \
                    and not getattr(self, "_force_close", False):
                _thread = getattr(self, "terminal_thread", None)
                if _thread is not None and _thread.isRunning():
                    t = get_translator()
                    reply = QMessageBox.question(
                        self, t("msg.close_session_title"), t("msg.confirm_close_session"),
                        QMessageBox.Close | QMessageBox.Cancel, QMessageBox.Close)
                    if reply != QMessageBox.Close:
                        event.ignore()
                        return
        except RuntimeError:
            pass  # Qt teardown — закрываем без вопросов (как раньше)

        # AUDIT v0.7.2 (средняя #10): окно имеет WA_DeleteOnClose — C++-объект будет
        # уничтожен сразу после этого события. Сигналы ещё работающего потока могли бы
        # приехать в удалённый объект (RuntimeError/crash на некоторых билдах Qt).
        # Поэтому: останавливаем PTY-дебаунс-таймер (v1.0RC3; render-таймера больше
        # нет — dirty-рендер прямой), отвязываем все слоты от окна и ждём завершение
        # потока с запасом (recv-цикл имеет msleep(30) — после stop() поток выходит за
        # ~100 мс; wait(1500) на практике всегда успевает).
        try:
            self._pty_timer.stop()
        except Exception:
            pass
        thread = getattr(self, "terminal_thread", None)
        if thread is not None:
            # v1.0-fix (audit #6): + connected_signal — раньше не отвязывался; при
            # закрытии окна до завершения connect (paramiko блокирует до ~15 c)
            # орфано-поток после успешного подключения всё же отправлял первую
            # команду Быстрого запуска в пустоту (и сигнал летел в удалённый объект).
            for _sig in (thread.output_signal, thread.error_signal,
                         thread.status_signal, thread.closed_signal,
                         thread.connected_signal):
                try:
                    _sig.disconnect(self)
                except TypeError:
                    pass  # слот не был подключён — делать нечего
            thread.stop()
            if thread.isRunning():
                thread.wait(1500)
        super().closeEvent(event)
