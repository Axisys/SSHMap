import re

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from .terminal_screen import TerminalScreen
except ImportError:
    from modules.terminal_screen import TerminalScreen

try:
    from .host_key_policy import SshKnownHostsPolicy
except ImportError:
    from modules.host_key_policy import SshKnownHostsPolicy

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat, QTextBlockFormat, QFontDatabase
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QHBoxLayout, QMessageBox, QApplication,
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
    RENDER_INTERVAL_MS = 33  # ~30 FPS перерисовки экрана

    def __init__(self, server_data: ServerData, parent=None, password: str = None):
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

        self.edit = SSHTerminalTextEdit(None)
        self.edit.setReadOnly(True)
        self.edit.setFocusPolicy(Qt.StrongFocus)
        # AUDIT v0.7.2 (низкая #18): системный моноширинный шрифт вместо хардкода "Consolas"
        # — на Linux/macOS Consolas отсутствует и fallback Qt мог выбрать немоноширинный.
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono_font.setPointSize(10)
        self.edit.setFont(mono_font)
        self.edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                border: none;
            }
        """)
        layout.addWidget(self.edit)

        btn_layout = QHBoxLayout()
        close_btn = QPushButton(t("terminal.close_button"))
        close_btn.clicked.connect(self.close_terminal)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

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
        self.edit.terminal_thread = self.terminal_thread

        # v0.8: pyte-экран — сетка 120x32, та же геометрия, что у invoke_shell
        self.tscreen = TerminalScreen(columns=120, lines=32)
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(self.RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._redraw)
        self._dirty = False

        self.terminal_thread.output_signal.connect(self._on_output)
        self.terminal_thread.error_signal.connect(self._show_error)
        self.terminal_thread.status_signal.connect(self._set_status)
        self.terminal_thread.closed_signal.connect(self._on_closed)
        self.terminal_thread.start()
        self._render_timer.start()
        self.edit.setFocus()

    # ── v0.8: pyte-рендер экрана ─────────────────────────────
    def _on_output(self, data: bytes):
        """Слот из SSH-потока: данные — сырые байты, копим dirty-флаг."""
        try:
            self.tscreen.feed(data)
        except Exception:
            return
        self._dirty = True

    def _redraw(self):
        """Перерисовка экрана (QTimer, GUI-поток): HTML со цветами + курсор."""
        if not self._dirty:
            return
        self._dirty = False
        html_lines, cx, cy = self.tscreen.render()

        doc = self.edit.document()
        doc.clear()
        cursor = QTextCursor(doc)
        for y, line_html in enumerate(html_lines):
            if y > 0:
                cursor.insertBlock()
            if not line_html:
                continue
            # простой разбор наших span'ов (формат строго свой — без общего HTML-парсера)
            pos = 0
            while True:
                lt = line_html.find("<span", pos)
                if lt == -1:
                    self._insert_escaped(cursor, line_html[pos:])
                    break
                if lt > pos:
                    self._insert_escaped(cursor, line_html[pos:lt])
                gt = line_html.find(">", lt)
                end = line_html.find("</span>", gt)
                style = line_html[lt + 5:gt]
                text = line_html[gt + 1:end]
                fmt = QTextCharFormat()
                for part in style.split(";"):
                    part = part.strip()
                    if part.startswith("color:"):
                        fmt.setForeground(QColor(part[6:].strip()))
                    elif part.startswith("background-color:"):
                        fmt.setBackground(QColor(part[17:].strip()))
                    elif part == "font-weight:bold":
                        fmt.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(text, fmt)
                pos = end + len("</span>")

        # курсор: позиционируем текстовый курсор по координатам pyte.
        # v0.8.1: без movePosition — в PySide6 6.5+/Qt6 вложенные перечисления
        # QTextCursor.MovePosition/MoveMode удалены (AttributeError ронял каждый
        # кадр перерисовки); позиция считается от начала блока напрямую.
        block = doc.findBlockByNumber(cy)
        if block.isValid():
            col = min(cx, len(block.text()) - 1) if block.text() else 0
            c2 = QTextCursor(block)
            # position() — позиция первого символа блока (у PySide6 нет start())
            c2.setPosition(max(0, block.position() + max(0, col)))
            self.edit.setTextCursor(c2)

    @staticmethod
    def _insert_escaped(cursor, html_text):
        """Вставляем уже экранированный текст: разворачиваем только наши сущности."""
        if "&amp;" in html_text or "&lt;" in html_text or "&gt;" in html_text:
            html_text = (html_text.replace("&lt;", "<")
                                  .replace("&gt;", ">")
                                  .replace("&amp;", "&"))
        if html_text:
            cursor.insertText(html_text)

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
        # AUDIT v0.7.2 (средняя #10): окно имеет WA_DeleteOnClose — C++-объект будет
        # уничтожен сразу после этого события. Сигналы ещё работающего потока могли бы
        # приехать в удалённый объект (RuntimeError/crash на некоторых билдах Qt).
        # Поэтому: останавливаем render-таймер, отвязываем все слоты от окна и ждём
        # завершение потока с запасом (recv-цикл имеет msleep(30) — после stop() поток
        # выходит за ~100 мс; wait(1500) на практике всегда успевает).
        try:
            self._render_timer.stop()
        except Exception:
            pass
        thread = getattr(self, "terminal_thread", None)
        if thread is not None:
            for _sig in (thread.output_signal, thread.error_signal,
                         thread.status_signal, thread.closed_signal):
                try:
                    _sig.disconnect(self)
                except TypeError:
                    pass  # слот не был подключён — делать нечего
            thread.stop()
            if thread.isRunning():
                thread.wait(1500)
        super().closeEvent(event)
