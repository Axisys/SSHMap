# -*- coding: utf-8 -*-
"""v1.2 (ROADMAP v1.2): TerminalSessionPage — SSH-сессия как переиспользуемый виджет.

Рефактор «окно → страница»: вся сессия (терминальный поток + pyte-экран +
терминальный холст + статус-строка + SFTP-вкладка) вынесена из SSHTerminalWindow
в QWidget, который не знает о QMainWindow. Окно терминала стало тонкой обёрткой
(WA_DeleteOnClose, заголовок, геометрия — см. modules/ssh_terminal.py), и на этой
странице строится остальная серия v1.2.x: вкладки в одном окне (v1.2.1) и док
окна карты (v1.2.2).

Один teardown-метод — `shutdown()` (идемпотентен): все teardown-пути (закрытие
окна, ошибка сессии, шатдаун MainWindow, лимит «4 своих терминала») проходят
через него. Осознанные guard'ы v1.1.x сохранены:
  * PTY-дебаунс-таймер останавливается ПЕРВЫМ (визги resize_pty в мёртвый канал);
  * SFTP-worker отключается и стопится ДО терминального потока (зависит от его
    transport'а), не дождавшийся wait — в реестр орфано-worker'ов;
  * сигналы потока отвязываются от страницы, потом stop() + wait(1500); поток,
    переживший ожидание (paramiko блокируется до ~15 c на connect), уходит в
    модульный реестр орфано-потоков `_orphan_threads` (v1.1.2RC1 N4) — живой
    QThread без QObject parent нельзя оставлять на GC;
  * RuntimeError C++-объектов не блокирует закрытие (teardown-устойчивость).

Мост в хост (окно/док): Qt-сигналы `status_message`/`progress_*` — страница НЕ
знает, куда они идут. В режиме `windows` SSHTerminalWindow подсоединяет их к
своему статус-бару и QProgressBar — отображение идентично v1.1.x.

Тестовые швы (паттерн v1.1.4 host_attr): класс потока и QMessageBox берутся из
модуля ssh_terminal в момент вызова — подмена `ST.SSHTerminalThread`/
`ST.QMessageBox.question` в тестах работает без изменений.
"""

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget

try:
    from .terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES
except ImportError:
    from modules.terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES

try:
    from .terminal_widget import TerminalWidget
except ImportError:
    from modules.terminal_widget import TerminalWidget

try:
    from .sftp_worker import SftpWorker, register_orphan_sftp_worker
except ImportError:
    from modules.sftp_worker import SftpWorker, register_orphan_sftp_worker

try:
    from .sftp_tab import SftpTab, format_size
except ImportError:
    from modules.sftp_tab import SftpTab, format_size


def _st_module():
    """Модуль ssh_terminal в момент вызова (тестовый шов подмены атрибутов).

    Ленивый импорт: terminal_page не импортирует ssh_terminal на уровне модуля
    (SSHTerminalWindow импортирует ЭТОТ модуль — прямой импорт дал бы цикл при
    старте с terminal_page).
    """
    try:
        from . import ssh_terminal as _st
    except ImportError:
        import ssh_terminal as _st
    return _st


def get_translator():
    """Safe i18n helper — returns cached translator or fallback (как в ssh_terminal)."""
    mod = _st_module()
    return mod.get_translator()


class TerminalSessionPage(QWidget):
    """v1.2: SSH-сессия как переиспользуемый виджет.

    Состав: terminal_thread (SSHTerminalThread) + tscreen (TerminalScreen) +
    widget (TerminalWidget, холст) + статус-строка (status_label) + QTabWidget
    [Терминал | Файлы] (SftpTab, ленивый worker). Конфиг terminal_* читается из
    config.json при создании (load_terminal_settings — дефолты = поведение v1.0).

    Хост (SSHTerminalWindow / будущий док) создаёт страницу с parent и может:
      * подсоединить мостовые сигналы status_message/progress_* к своему UI;
      * вызвать set_host_window(w) — close_terminal() закроет таб этой сессии на
        хосте (v1.2.1: последний таб закрывает окно);
      * пройти teardown через shutdown() (единый метод, идемпотентен).
    """

    # v1.0RC3: resize PTY — guard по смене сетки + дебаунс ~150 мс перед
    # channel.resize_pty (TERMINAL.md §5.5); начальный invoke_shell 120×32,
    # первый resize холста синхронизирует с реальным размером.
    PTY_RESIZE_DEBOUNCE_MS = 150

    # v1.0RC4: Быстрый запуск — задержка отправки первой команды после invoke_shell
    # (login-скрипты/motd; PTY-ввод буферизуется, команда не теряется).
    INITIAL_COMMAND_DELAY_MS = 500

    # ── Мост в хост (окно/док): страница не знает, куда идут сообщения ──────
    status_message = Signal(str, int)   # (text, timeout_ms); 0 — sticky (без таймаута)
    progress_busy = Signal()            # SFTP: показать индетерминированный бар
    progress_update = Signal(int, int)  # SFTP: (done, total); total<=0 — индетерминированный
    progress_hidden = Signal()          # SFTP: скрыть бар

    def __init__(self, server_data, parent=None, password: str = None,
                 initial_command: str = ""):
        super().__init__(parent)
        self.server_data = server_data
        self._host_window = None     # хост-окно (SSHTerminalWindow); close_terminal() его закрывает
        self._force_close = False    # v1.1.1: путь лимита — подтверждённое решение, «ask» не спрашивает повторно
        self._shut_down = False      # shutdown() идемпотентен (все teardown-пути через один метод)

        t = get_translator()
        layout = QVBoxLayout(self)

        self.status_label = QLabel(t("terminal.initializing"))
        self.status_label.setStyleSheet("color: #94a3b8; padding: 4px 0;")
        layout.addWidget(self.status_label)

        # AUDIT v0.7.2 (средняя #7): явный пароль приоритетнее node.data.password —
        # модель не загрязняется открытым текстом до записи в keyring/сохранения проекта.
        if password is not None:
            pwd = password or ""
        else:
            pwd = getattr(server_data, 'password', '') or ""

        # Тестовый шов: класс потока берётся из модуля ssh_terminal в момент
        # вызова (подмена ST.SSHTerminalThread в тестах работает без изменений).
        thread_cls = _st_module().SSHTerminalThread
        self.terminal_thread = thread_cls(
            host=server_data.host,
            user=server_data.user,
            port=server_data.ssh_port or 22,
            password=pwd,
            key_path=server_data.key_path,
        )

        # v1.0 финал (ROADMAP задача 9): terminal_* ключи из ~/.sshmap/config.json —
        # все опциональны, дефолты = текущее поведение (вид RC4). UI — v1.1.
        term_cfg = _st_module().load_terminal_settings()
        # v1.1 (ROADMAP задача 3): поведение закрытия сессии — используется в confirm_close().
        self._close_behavior = term_cfg["close_behavior"]

        # v0.8: pyte-экран — сетка 120x32, та же геометрия, что у invoke_shell;
        # глубина скроллбэка HistoryScreen — terminal_history_lines (дефолт 1000).
        self.tscreen = TerminalScreen(columns=120, lines=32,
                                      history_lines=term_cfg["history_lines"])

        # v1.0RC1: посячейный холст (QWidget + QPainter) вместо QPlainTextEdit+HTML.
        # Шрифт — системный моноширинный pt 10, палитра 'default' = текущий вид;
        # runs/курсор/широкие глифы — см. terminal_widget.py. v1.1.2RC3 (AUDIT U3):
        # режим колеса из конфига (terminal_wheel).
        self.widget = TerminalWidget(self.tscreen, self.terminal_thread,
                                     wheel_mode=term_cfg["wheel"])
        # v1.0 финал: применение конфига (неизвестная палитра → set_palette() False
        # → остаётся "default"; битые значения отброшены в load_terminal_settings).
        if term_cfg["palette"] is not None:
            self.widget.set_palette(term_cfg["palette"])
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            self.widget.set_font(
                family=term_cfg["font_family"],
                size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)

        # v1.1.3 (ROADMAP задача 4): QTabWidget [Терминал | Файлы]. SFTP-вкладка
        # переиспользует тот же transport (terminal_thread.client.open_sftp() —
        # без второй аутентификации и known_hosts-прохода); worker создаётся
        # лениво — при первом переходе на «Файлы» / после connected_signal.
        self.tabs = QTabWidget()
        self.tabs.addTab(self.widget, t("sftp.tab_terminal"))
        self.sftp_tab = SftpTab()
        self.tabs.addTab(self.sftp_tab, t("sftp.tab_files"))
        layout.addWidget(self.tabs)

        # v1.1.3: состояние SFTP (worker ленивый; реестр задач для прогресс-текста).
        # Визуализация — мостовые сигналы progress_* (в режиме windows окно
        # подсоединяет их к своему QProgressBar в статус-баре — вид v1.1.x).
        self._sftp_worker = None
        self._sftp_tasks = {}      # task_id → (kind, label)
        self._sftp_busy = 0        # сколько upload/download в полёте
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.sftp_tab.message.connect(self._on_sftp_tab_message)

        # v1.0RC3: resize PTY — guard по смене сетки + дебаунс ~150 мс. Холст живёт
        # внутри таба (а не в resizeEvent окна): eventFilter на самом виджете ловит
        # РЕАЛЬНЫЙ ресайз холста — пересчёт отложен на singleShot(0), пока layout
        # устоится (паттерн v1.1.x: транзитный размер не должен менять сетку).
        self._last_cols, self._last_rows = 120, 32
        self._pending_pty = None
        self._pty_timer = QTimer(self)
        self._pty_timer.setInterval(self.PTY_RESIZE_DEBOUNCE_MS)
        self._pty_timer.timeout.connect(self._on_pty_debounce)
        self.widget.installEventFilter(self)

        self.terminal_thread.output_signal.connect(self._on_output)
        self.terminal_thread.error_signal.connect(self._show_error)
        self.terminal_thread.status_signal.connect(self._set_status)
        self.terminal_thread.closed_signal.connect(self._on_closed)
        # v1.1.3: пользователь мог уже стоять на вкладке «Файлы» во время
        # подключения — открываем SFTP, как только клиент появится в потоке.
        self.terminal_thread.connected_signal.connect(self._on_connected_for_sftp)

        # v1.0RC4: Быстрый запуск — первая команда отправляется после подключения
        # (connected_signal), а не до него: при неудачной аутентификации команда
        # просто не уходит, ошибка показывается штатным error-путём. Connection
        # храним — shutdown() отвязывает ТОЛЬКО если подключение было (PySide6 6.11:
        # disconnect неподключённого слота бросает RuntimeWarning).
        self._initial_command = (initial_command or "").strip()
        self._initial_cmd_conn = None
        if self._initial_command:
            self._initial_cmd_conn = self.terminal_thread.connected_signal.connect(
                self._send_initial_command)

        self.terminal_thread.start()
        self.widget.setFocus()

    # ── Хост ────────────────────────────────────────────────────────────────

    def set_host_window(self, window):
        """Хост-окно (SSHTerminalWindow): close_terminal() закроет его, а
        QMessageBox получат его как parent. Без хоста — teardown напрямую."""
        self._host_window = window

    # ── v1.2: teardown — один метод на все пути ─────────────────────────────

    def confirm_close(self) -> bool:
        """Gate перед teardown (v1.1, ROADMAP задача 3): terminal_close_behavior.

        "ask": активная сессия (SSH-поток ещё работает) → подтверждение; отмена —
        False (хост должен event.ignore() и жить дальше). "close" (дефолт) и уже
        завершённая сессия — без диалога. _force_close (путь лимита v1.1.1:
        решение «закрыть старейшую» уже подтверждено пользователем) — тоже без
        диалога. Teardown-устойчивость: RuntimeError C++-объектов не блокирует
        закрытие."""
        try:
            if getattr(self, "_close_behavior", "close") == "ask" \
                    and not getattr(self, "_force_close", False):
                _thread = self.terminal_thread
                if _thread is not None and _thread.isRunning():
                    t = get_translator()
                    box = _st_module().QMessageBox   # тестовый шов (ST.QMessageBox)
                    reply = box.question(
                        self._host_window, t("msg.close_session_title"),
                        t("msg.confirm_close_session"),
                        box.Close | box.Cancel, box.Close)
                    if reply != box.Close:
                        return False
        except RuntimeError:
            pass  # Qt teardown — закрываем без вопросов (как раньше)
        return True

    def stop_thread(self):
        """Остановить поток БЕЗ ожидания (close_terminal-путь; wait() — в shutdown())."""
        try:
            thread = getattr(self, "terminal_thread", None)
            if thread is not None:
                thread.stop()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)

    def close_terminal(self):
        """Закрыть сессию (v1.2.1): стоп потока + закрытие СВОЕГО таба на хосте
        (window.close_page → confirm_close → shutdown; последний таб закрывает окно).
        Путь MainWindow._shutdown_background_threads и лимита «4 своих терминала»:
        в табовом окне закрытие сессии НЕ затрагивает соседние табы. Без хоста /
        у хоста нет close_page (фейк) — teardown напрямую."""
        self.stop_thread()
        w = getattr(self, "_host_window", None)
        if w is not None:
            close_page_fn = getattr(w, "close_page", None)
            if callable(close_page_fn):
                try:
                    close_page_fn(self)
                    return
                except RuntimeError:
                    pass  # хост уже уничтожен — teardown напрямую
        self.shutdown()

    def shutdown(self):
        """ЕДИНЫЙ teardown-метод (v1.2, ROADMAP задача 3): все teardown-пути
        (закрытие окна, ошибка сессии, шатдаун MainWindow, путь лимита) проходят
        через него. Идемпотентен (повторный вызов — no-op).

        Порядок (порядок v1.1.x closeEvent сохранён):
          1. SFTP-worker ПЕРВЫМ (зависит от transport'а терминального потока):
             отвязываем слоты страницы, stop с ограниченным ожиданием; не дождался
             (передача встала на мёртвой сети) — реестр орфано-worker'ов держит
             поток до finished();
          2. PTY-дебаунс-таймер стопим (resize_pty в мёртвый канал);
          3. сигналы потока отвязываем от страницы и stop() + wait(1500): recv-цикл
             имеет msleep(30) — после stop() поток выходит за ~100 мс, wait на
             практике всегда успевает; окно/страница после этого события может быть
             уничтожена (WA_DeleteOnClose), а paramiko ещё может подключаться до 15 c
             → переживший ожидание поток регистрируется в реестре орфано-потоков
             `_orphan_threads` (v1.1.2RC1 N4): живой QThread без QObject parent нельзя
             оставлять на GC, поздние emit без приёмников — безопасный no-op.
        """
        if self._shut_down:
            return
        self._shut_down = True

        # ВАЖНО (проверено прогоном, PySide6 6.11): signal.disconnect(объект-приёмник)
        # бросает TypeError — отвязка идёт по ТОЧНОМУ слоту (bound method); TypeError
        # ловим только для «слот не был подключён» (conditional-подключения).
        def _dissig(sig, slot):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass  # слот не был подключён — делать нечего

        # v1.1.3: SFTP-worker ПЕРВЫМ (зависит от transport'а терминального потока).
        sftp_worker = getattr(self, "_sftp_worker", None)
        if sftp_worker is not None:
            _dissig(sftp_worker.task_started, self._on_sftp_task_started)
            _dissig(sftp_worker.progress, self._on_sftp_progress)
            _dissig(sftp_worker.task_done, self._on_sftp_task_done)
            _dissig(sftp_worker.task_error, self._on_sftp_task_error)
            _dissig(sftp_worker.task_cancelled, self._on_sftp_task_cancelled)
            _dissig(sftp_worker.finished, self._on_sftp_worker_finished)
            sftp_worker.shutdown(wait_ms=2500)
            if sftp_worker.isRunning():
                register_orphan_sftp_worker(sftp_worker)

        try:
            self._pty_timer.stop()
        except Exception:
            pass  # RuntimeError C++-объекта (teardown) — не блокирует закрытие

        thread = getattr(self, "terminal_thread", None)
        if thread is not None:
            _dissig(thread.output_signal, self._on_output)
            _dissig(thread.error_signal, self._show_error)
            _dissig(thread.status_signal, self._set_status)
            _dissig(thread.closed_signal, self._on_closed)
            # v1.0-fix (audit #6): + connected_signal — раньше не отвязывался; при
            # закрытии до завершения connect орфано-поток после успешного подключения
            # всё же отправлял первую команду Быстрого запуска в пустоту.
            _dissig(thread.connected_signal, self._on_connected_for_sftp)
            # Быстрый запуск — только если был подключён (connection-объект из __init__)
            if getattr(self, "_initial_cmd_conn", None) is not None:
                try:
                    thread.connected_signal.disconnect(self._initial_cmd_conn)
                except (TypeError, RuntimeError):
                    pass
            thread.stop()
            if thread.isRunning():
                thread.wait(1500)
                # v1.1.2RC1 (N4): страница после этого события может быть уничтожена
                # (окно — WA_DeleteOnClose), а paramiko ещё может подключаться (до 15 c).
                if thread.isRunning():
                    _st_module().register_orphan_thread(thread)

        # Слота вкладок «Файлы» тоже отвязываем (list_ready worker'а идёт во
        # вкладку напрямую — она умрёт вместе со страницей).
        _dissig(self.sftp_tab.message, self._on_sftp_tab_message)

    # ── v1.0RC3: dirty-рендер без таймера (ROADMAP задача 8) ────────────────

    def eventFilter(self, obj, event):
        """v1.2: ресайз холста (внутри таба) → пересчёт сетки. Раньше —
        SSHTerminalWindow.resizeEvent; guard по смене сетки и дебаунс те же."""
        if obj is self.widget and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._sync_grid)
        return super().eventFilter(obj, event)

    def _on_output(self, data: bytes):
        """Слот из SSH-потока (queued signal — уже в GUI-потоке): сырые байты
        в pyte + прямой update() холста. 30 FPS-таймер не нужен: Qt сам
        коалесит несколько update() за один цикл событий; paintEvent читает
        сетку сам (TerminalWidget._paint). Авто-снап скроллбэка к live-строке
        при новом выводе — внутри pyte (HistoryScreen.before_event), поэтому
        новый вывод виден сразу, даже если пользователь смотрел историю.

        v1.1.2RC3 (N7): если этот вывод авто-вернул скроллбэк к live (позиция
        history изменилась) — выделение сбрасывается: координаты (row, col)
        зафиксированы в release на ИСТОРИЧЕСКОМ экране, а после возврата они
        указывают на ДРУГИЕ ячейки live-экрана — Ctrl+C скопировал бы чужой
        текст. Без нового вывода / без активного выделения поведение простого
        клика и Ctrl+C не меняется."""
        try:
            pos_before = self.tscreen.scroll_info()[0]
            self.tscreen.feed(data)
        except Exception:
            return
        # v1.1.2RC3 (N7): смена позиции history ⇔ авто-возврат к live (feed() —
        # единственный путь, меняющий позицию без ручного скролла). Активное
        # выделение на «старом» экране сбрасываем до копирования.
        try:
            if self.tscreen.scroll_info()[0] != pos_before \
                    and self.widget.has_selection():
                self.widget.clear_selection()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка WA_DeleteOnClose при закрытии)
        try:
            self.widget.update()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка WA_DeleteOnClose при закрытии)

    # ── v1.0RC3: resize PTY — guard по сетке + дебаунс (ROADMAP задача 6) ───

    def _visible_grid(self):
        """(cols, rows) видимой сетки: размер холста / метрики ячейки."""
        cw, chh = self.widget.cell_size
        cols = max(2, self.widget.width() // cw)
        rows = max(1, self.widget.height() // chh)
        return cols, rows

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
        self.status_message.emit(text, 0)   # v1.1.x: statusBar().showMessage(text) (sticky)

    def _show_error(self, error: str):
        t = get_translator()
        self.status_label.setText(f"{t('terminal.error_prefix')} {error}")
        box = _st_module().QMessageBox   # тестовый шов (ST.QMessageBox)
        box.critical(
            self._host_window,
            t("msg.ssh_error"),
            f"{t('terminal.error_prefix')} {error}",
        )
        self.close_terminal()

    def _on_closed(self):
        t = get_translator()
        self.status_label.setText(t("terminal.session_closed"))
        self.status_message.emit(t("terminal.session_closed"), 0)

    # ── v1.0RC4: Быстрый запуск ─────────────────────────────────────────────

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

    # ── v1.1.3: SFTP-вкладка (ROADMAP задачи 2–4) ───────────────────────────

    def _ensure_sftp(self) -> bool:
        """Открыть SFTP-канал поверх живого transport'а и запустить worker.

        Переиспользует `terminal_thread.client.open_sftp()` — без второй
        аутентификации и второго known_hosts-прохода (ROADMAP задача 3):
        policy уже применён к client при connect, open_sftp лишь открывает
        новый канал на том же Transport. Ленивый вызов: первый переход на
        вкладку «Файлы» / connected_signal, если пользователь уже там.
        Сессия ещё не подключена → False (вкладка ждёт). SFTP-подсистема на
        сервере недоступна → ошибка в статус (мост status_message), worker не
        создаётся (повторная попытка — при следующем переходе на вкладку).
        """
        t = get_translator()
        worker = getattr(self, "_sftp_worker", None)
        if worker is not None and not worker.isFinished():
            return True
        thread = getattr(self, "terminal_thread", None)
        client = getattr(thread, "client", None) if thread is not None else None
        transport = None
        if client is not None:
            try:
                transport = client.get_transport()
            except Exception:
                transport = None
        if transport is None or not transport.is_active():
            return False
        try:
            sftp = client.open_sftp()
        except Exception as e:  # noqa: BLE001 — подсистема SFTP может быть выключена
            msg = t("sftp.open_failed", error=str(e))
            self.status_message.emit(
                msg if not msg.startswith("[") else f"Failed to open SFTP channel: {e}",
                8000)
            return False
        # БЕЗ QObject parent: окно WA_DeleteOnClose, а висящая передача может
        # пережить его — реестр орфано-worker'ов (паттерн N4 v1.1.2RC1) держит
        # поток до finished(); все слоты отвязаны в shutdown().
        new_worker = SftpWorker(sftp)
        self._sftp_worker = new_worker
        new_worker.task_started.connect(self._on_sftp_task_started)
        new_worker.progress.connect(self._on_sftp_progress)
        new_worker.task_done.connect(self._on_sftp_task_done)
        new_worker.task_error.connect(self._on_sftp_task_error)
        new_worker.task_cancelled.connect(self._on_sftp_task_cancelled)
        new_worker.finished.connect(self._on_sftp_worker_finished)
        new_worker.start()
        self.sftp_tab.set_worker(new_worker)
        return True

    def _on_tab_changed(self, index: int):
        """Переход на вкладку «Файлы» — ленивый старт SFTP (идемпотентно)."""
        if self.tabs.widget(index) is self.sftp_tab:
            self._ensure_sftp()

    def _on_sftp_tab_message(self, msg: str):
        """Сообщение вкладки (выбор файлов и пр.) → мост status_message (5 c)."""
        self.status_message.emit(msg, 5000)

    def _on_connected_for_sftp(self):
        """connected_signal: пользователь мог уже стоять на «Файлы»."""
        try:
            if self.tabs.currentWidget() is self.sftp_tab:
                self._ensure_sftp()
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)

    def _on_sftp_task_started(self, task_id: int, kind: str, label: str):
        t = get_translator()
        self._sftp_tasks[task_id] = (kind, label)
        if kind in ("upload", "download"):
            self._sftp_busy += 1
            self.progress_busy.emit()   # v1.1.x: setRange(0,0)+setValue(0)+show()
            key = "sftp.uploading" if kind == "upload" else "sftp.downloading"
            self.status_message.emit(t(key, name=label), 0)
        else:  # list — без прогресс-бара
            self.status_message.emit(t("sftp.listing", path=label), 0)

    def _on_sftp_progress(self, task_id: int, done: int, total: int):
        t = get_translator()
        entry = self._sftp_tasks.get(task_id)
        if entry is None or entry[0] not in ("upload", "download"):
            return
        _kind, label = entry
        if total > 0:
            self.progress_update.emit(done, total)   # v1.1.x: setRange(0,total)+setValue
            text = t("sftp.progress", name=label, pct=int(done * 100 // total),
                     done=format_size(done), total=format_size(total))
        else:  # total неизвестен — только имя (индетерминированный бар)
            self.progress_update.emit(done, 0)
            key = "sftp.uploading" if entry[0] == "upload" else "sftp.downloading"
            text = t(key, name=label)
        self.status_message.emit(text, 0)

    def _on_sftp_task_done(self, task_id: int, detail: str):
        t = get_translator()
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in ("upload", "download"):
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
            self.status_message.emit(t("sftp.transfer_done", name=entry[1]), 5000)

    def _on_sftp_task_error(self, task_id: int, kind: str, message: str):
        t = get_translator()
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in ("upload", "download"):
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        prefix = t("terminal.error_prefix")
        self.status_message.emit(f"{prefix} {message}", 8000)

    def _on_sftp_task_cancelled(self, task_id: int, kind: str):
        t = get_translator()
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in ("upload", "download"):
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        self.status_message.emit(t("sftp.transfer_cancelled"), 5000)

    def _on_sftp_worker_finished(self):
        """Worker остановился сам (transport умер — сессия закрыта/упала):
        сброс состояния; вкладка возвращается в «ожидание», повторный старт —
        при следующем переходе на неё, если появится живое соединение."""
        try:
            self._sftp_worker = None
            self._sftp_tasks.clear()
            self._sftp_busy = 0
            self.progress_hidden.emit()
            self.sftp_tab.set_worker(None)
        except RuntimeError:
            pass  # C++-объект уже удалён (гонка закрытия)
