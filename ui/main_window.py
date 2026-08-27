import os
import sys
import copy
from typing import Optional, List

try:
    from ..models.server import server_data_from_dict
except ImportError:
    from models.server import server_data_from_dict

try:
    from ..graphics.map_scene import MapScene
    from ..graphics.map_view import MapView
    from ..graphics.server_node import ServerNode
    from ..graphics.node_group import NodeGroup  # v0.8.1: группировка узлов (кластеры/папки)
    from ..graphics.connection_arrow import (
        ConnectionArrow, DEFAULT_CONNECTION_TYPE,
    )
except ImportError:
    from graphics.map_scene import MapScene
    from graphics.map_view import MapView
    from graphics.server_node import ServerNode
    from graphics.node_group import NodeGroup  # v0.8.1
    from graphics.connection_arrow import (
        ConnectionArrow, DEFAULT_CONNECTION_TYPE,
    )

try:
    from ..dialogs.add_server_dialog import AddServerDialog
    from ..dialogs.connection_dialog import ConnectionDialog
    from ..dialogs.ssh_connect_dialog import SSHConnectDialog
except ImportError:
    from dialogs.add_server_dialog import AddServerDialog
    from dialogs.connection_dialog import ConnectionDialog
    from dialogs.ssh_connect_dialog import SSHConnectDialog

try:
    from ..modules.ssh_terminal import SSHTerminalWindow
except ImportError:
    from modules.ssh_terminal import SSHTerminalWindow

try:  # v0.8.2: внешний (системный) терминал
    from ..modules import external_terminal as _ext_term
except ImportError:
    try:
        from modules import external_terminal as _ext_term
    except ImportError:
        _ext_term = None

try:  # UI polish: векторные иконки (замена эмодзи)
    from .icons import get_icon
except ImportError:
    try:
        from icons import get_icon
    except ImportError:  # flat-раскладка без ui/icons — кнопки текстовые, как раньше
        def get_icon(name):  # noqa: N802 — заглушка с той же сигнатурой
            return None


from PySide6.QtCore import Qt, QRectF, QSize, QTimer, QPointF
from PySide6.QtGui import (
    QMouseEvent,
    QIcon, QPixmap, QPainter, QBrush,  # ревью-фикс v0.8.0 (#3): маркеры статусов в сайдбаре
    QColor,  # v0.9.4: цветные точки тегов в комбобоксе фильтра (DecorationRole)
    QUndoStack,  # v0.8.3: undo/redo
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QToolBar, QMessageBox, QDialog, QFileDialog, QMenu,
    QApplication, QComboBox,
)

try:  # v0.8.3: undo/redo-команды карты
    from ..modules import undo_commands as _uc
except ImportError:
    from modules import undo_commands as _uc
from PySide6.QtCore import QThread, Signal as QtSignal  # v0.7.3: ping-поток
import platform as _platform_mod  # v0.7.3: ping-флаги по ОС
import subprocess as _subprocess_mod  # v0.7.3: системный ping


def _is_scene_point(value) -> bool:
    """v0.8.1: передана ли точка сцены (QPoint/QPointF), а не что-то другое.

    QAction.triggered передаёт Python-слоту bool `checked` — при прямом
    подключении действия (тулбар/меню) он приходит первым позиционным
    аргументом. Без этой проверки `_add_server(True)` падал на `center.x()`
    («'bool' object has no attribute 'x'»).
    """
    if value is None or isinstance(value, bool):
        return False
    x = getattr(value, "x", None)
    y = getattr(value, "y", None)
    return callable(x) and callable(y)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # ── i18n: restore user's last language choice ──
        self._i18n_available = False
        
        try:
            from i18n import (
                set_language as _set_lang,
                get_last_language,  # Restore preferred language
            )
            
            # Use last saved language or fall back to default
            preferred = get_last_language()
            self.current_language = preferred
            _set_lang(preferred)
            
            from i18n import t as __t
            self.t = __t  # Make translate function available on instance
            self._i18n_available = True
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
        
        self.resize(1200, 850)
        self._project_file: Optional[str] = None
        self._dirty = False  # Флаг несохранённых изменений (маркер " [*]" в заголовке)
        self._terminal_windows: List[SSHTerminalWindow] = []
        # v0.9.4-fix: id узлов с активной SSH-сессией (для сброса индикатора)
        self._ssh_connected_nodes: set = set()
        self._ping_thread = None   # v0.7.3: ping-поток (AUDIT v0.7.2 #8: guard против затирания)
        self._dns_thread = None    # AUDIT v0.7.2 (#6): поток обратного DNS для copy-hostname
        self._menu_i18n: List[tuple] = []  # (widget: QMenu|QAction, key) — для повторного перевода
        self._sidebar_title: Optional[QLabel] = None

        # ── v0.8.3: Undo/Redo ─────────────────────────────────────
        # Dirty-маркер привязан к cleanState/индексу стека: save/load ставит
        # новую точку отсчёта, undo/redo сами обновляют заголовок окна.
        self.undo_stack = QUndoStack(self)
        self._undo_baseline_dirty = False  # dirty-причины ВНЕ undo (статусы, группы)
        self._note_committed = {}          # note_id -> последний закоммиченный текст (дебаунс)
        self._note_edit_timer = QTimer(self)
        self._note_edit_timer.setSingleShot(True)
        self._note_edit_timer.setInterval(600)  # мс тишины → команда EditTextNote
        self._note_edit_timer.timeout.connect(self._commit_note_text)
        self._note_edit_pending = None     # (note, old_text) активной правки

        # ── Logger (lazy import to avoid circular deps at module level) ──
        self._log: Optional[object] = None

        self._setup_ui()
        self._setup_toolbar()
        self._setup_menubar()
        self._update_window_title()

        # ── i18n: apply translation to UI after setup ──
        if self._i18n_available:
            try:
                self._apply_ui_translations()
            except Exception as e:
                if self.log:
                    self.log.warning(f"i18n UI update error: {e}")

        # ── v0.7.1: фоновая проверка статусов узлов (online/warn/offline) ──
        # Пробы идут в отдельном потоке — GUI не блокируется; интервал 30 c.
        self._status_checker = None
        try:
            from services.status_checker import StatusChecker as _StatusChecker, \
                DEFAULT_INTERVAL_MS as _STATUS_INTERVAL
            self._status_checker = _StatusChecker(
                interval_ms=_STATUS_INTERVAL, parent=self)
            self._status_checker.status_changed.connect(self._on_node_status_changed)
            # При уничтожении окна — остановить таймер и дождаться текущего раунда,
            # чтобы поток-проба не был убит на ходу вместе с родителем.
            self.destroyed.connect(lambda *_a: self._status_checker.shutdown())
            # Цели синхронизируем сразу; сам запуск периодических проверок — один раз,
            # из main.py после window.show() (см. start_status_checks()). В headless-
            # тестах без event loop это гарантирует отсутствие фоновых потоков.
            self._sync_status_targets()
        except Exception as e:
            if self.log:
                self.log.warning(f"StatusChecker unavailable: {e}")

    def start_status_checks(self):
        """v0.7.1: запустить периодические проверки статусов (вызывается один раз)."""
        checker = getattr(self, "_status_checker", None)
        if checker is not None and not checker.is_busy:
            try:
                self._sync_status_targets()
                checker.start()
            except Exception as e:
                if self.log:
                    self.log.warning(f"StatusChecker start failed: {e}")

    # ── v0.7.1: статусы узлов ────────────────────────────────

    def _sync_status_targets(self):
        """Обновить список целей StatusChecker под текущие узлы сцены."""
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return
        try:
            checker.set_servers([
                (n.data.id, n.data.host, n.data.ssh_port or 22)
                for n in self.scene.nodes()
            ])
        except Exception as e:
            if self.log:
                self.log.warning(f"StatusChecker set_servers failed: {e}")

    def _on_node_status_changed(self, server_id: str, status: str):
        """Обработать результат пробы одного узла."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # узел уже удалён — статус ему не нужен
        try:
            node.set_status(status)
        except Exception as e:
            if self.log:
                self.log.warning(f"set_status failed for {server_id}: {e}")
        else:
            self._update_counts_label()  # UI polish: online/warn/offline в статус-баре
            # Ревью-фикс v0.8.0 (#3): маркер строки дерева обновляется на месте
            # (node.status — фактический статус после set_status; неизвестные игнорируются)
            self._update_sidebar_status_marker(server_id)

    def _update_window_title(self):
        """Пересобрать заголовок окна: базовый заголовок + файл проекта + маркер [*]."""
        # AUDIT v0.8.3 (#1): база — APP_NAME/APP_VERSION из version.py (единая
        # точка истины); i18n-ключ title.main_window больше не источник версии.
        try:
            from version import APP_NAME, APP_VERSION
        except ImportError:
            from .version import APP_NAME, APP_VERSION
        base = f"{APP_NAME} — v{APP_VERSION}"
        lang_code = (getattr(self, "current_language", "") or "").upper()
        title = f"{base} [{lang_code}]" if lang_code else base
        if self._project_file:
            title += f" — {os.path.basename(self._project_file)}"
        if self._dirty:
            title += " [*]"
        self.setWindowTitle(title)

    def _register_i18n(self, widget, key: str):
        """Запомнить виджет (QMenu/QAction) и ключ перевода для повторного применения."""
        self._menu_i18n.append((widget, key))

    def _apply_ui_translations(self):
        """Перевести меню, тулбар и служебные подписи на текущий язык."""
        for widget, key in self._menu_i18n:
            if widget is None:
                continue
            if isinstance(widget, QMenu):
                widget.setTitle(self.t(key))
            else:
                widget.setText(self.t(key))
        if self._sidebar_title is not None:
            self._sidebar_title.setText(self.t("server.title"))
        self.search_edit.setPlaceholderText(self.t("search.placeholder"))
        self.statusBar().showMessage(self.t("status.ready"))

    @property
    def log(self):
        """Lazy-imported logger."""
        if self._log is None:
            try:
                from modules.logger import get_logger as _get
                self._log = _get(__name__)
            except Exception:
                pass
        return self._log

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Side panel — always created, i18n applied where available
        self.sidebar = QWidget()
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(8, 8, 8, 8)

        def _connect_buttons():
            """Create side-panel buttons and add them to the layout.

            UI polish: векторные иконки (ui/icons.py) вместо эмодзи в тексте —
            кроссплатформенно и единый стиль с тулбаром; высота унифицирована.
            """
            self.btn_add = QPushButton("Добавить сервер")
            _set_btn_icon(self.btn_add, "add_server")
            self.btn_add.clicked.connect(self._add_server)
            sb_layout.addWidget(self.btn_add)

            self.btn_connect = QPushButton("Добавить связь")
            _set_btn_icon(self.btn_connect, "connection")
            self.btn_connect.clicked.connect(self._add_connection)
            sb_layout.addWidget(self.btn_connect)

            self.btn_connect_ssh = QPushButton("SSH Подключение")
            _set_btn_icon(self.btn_connect_ssh, "ssh")
            self.btn_connect_ssh.clicked.connect(self._connect_ssh_to_selected)
            sb_layout.addWidget(self.btn_connect_ssh)

            self.btn_props = QPushButton("Свойства")
            _set_btn_icon(self.btn_props, "properties")
            self.btn_props.clicked.connect(self._show_properties)
            sb_layout.addWidget(self.btn_props)

            self.btn_delete = QPushButton("Удалить")
            _set_btn_icon(self.btn_delete, "delete")
            self.btn_delete.clicked.connect(self._delete_selected)
            sb_layout.addWidget(self.btn_delete)

            for _b in (self.btn_add, self.btn_connect, self.btn_connect_ssh,
                       self.btn_props, self.btn_delete):
                _b.setMinimumHeight(34)  # UI polish: ровные кнопки сайдбара

        def _set_btn_icon(btn, name):
            """UI polish: векторная иконка на кнопке (no-op без ui/icons)."""
            try:
                icon = get_icon(name)
                if icon is not None and not icon.isNull():
                    btn.setIcon(icon)
                    btn.setIconSize(QSize(18, 18))
            except Exception:  # noqa: BLE001 — иконка косметика, не роняем сайдбар
                pass

        # ── Server title label ────────────────────────────────
        if self._i18n_available:
            try:
                from i18n import t as __t
                self._sidebar_title = QLabel(__t("server.title"))
                sb_layout.addWidget(self._sidebar_title)
            except Exception:
                pass

        # ── Search field ──────────────────────────────────────
        self.search_edit = QLineEdit()
        if self._i18n_available:
            try:
                from i18n import t as __t
                self.search_edit.setPlaceholderText(__t("search.placeholder"))
            except Exception:
                pass
        else:
            self.search_edit.setPlaceholderText("Поиск по alias / host / IP...")

        self.search_edit.textChanged.connect(self.refresh_sidebar)
        sb_layout.addWidget(self.search_edit)

        # ── v0.9.4: фильтр по тегам ───────────────────────────
        # Элементы: [0] = «Все теги» (фильтр выключен), далее — уникальные теги
        # всех серверов карты; перестраивается в refresh_sidebar (без сброса выбора).
        self.tag_filter = QComboBox()
        self.tag_filter.currentIndexChanged.connect(self._on_tag_filter_changed)
        sb_layout.addWidget(self.tag_filter)

        # ── Server tree ───────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_click)
        # Ревью-фикс v0.8.0 (#3): цветные маркеры статусов в дереве (16×16 — ровно
        # под pixmap точки; единый размер не зависит от стиля/платформы).
        self.tree.setIconSize(QSize(16, 16))
        sb_layout.addWidget(self.tree)
        # Кэш иконок точек по статусу ("", "online", "warn", "offline")
        self._status_dot_icons = {}

        # ── Buttons (always created here, i18n applied below) ─
        _connect_buttons()

        # ── Apply i18n labels to buttons if available ─────────
        if self._i18n_available:
            try:
                from i18n import t as __t
                # Эмодзи/префиксы уже содержатся в самих значениях перевода,
                # добавлять их здесь повторно нельзя (было «- - 添加连接» и т.п.)
                self.btn_add.setText(__t("btn.add_server"))
                self.btn_connect.setText(__t("btn.add_connection"))
                self.btn_connect_ssh.setText(__t("btn.connect_ssh"))
                self.btn_props.setText(__t("btn.properties"))
                self.btn_delete.setText(__t("btn.delete"))
            except Exception:
                pass  # keep Russian fallback labels already set above

        splitter.addWidget(self.sidebar)

        # Map canvas
        self.scene = MapScene()
        self.scene.selectionChanged.connect(self._sync_selection_state)
        self.view = MapView(self.scene, self)

        # v0.8.3: undo-стек — dirty по индексу, refresh после undo/redo
        self.undo_stack.indexChanged.connect(lambda *_a: self._on_stack_changed())
        self.undo_stack.cleanChanged.connect(lambda *_a: self._on_stack_changed())
        # Перемещение узла: MapView сообщает о завершении жеста → команда MoveNode
        try:
            self.view.node_drag_committed.connect(self._commit_node_move)
            self.view.nodes_drag_committed.connect(self._commit_nodes_move)  # v0.9.3
        except Exception:  # noqa: BLE001 — без сигнала перемещение просто не попадёт в undo
            pass

        # Mouse event filter for double-click on nodes
        self.view.viewport().installEventFilter(self)

        # v0.7: drag-режим создания связи (Shift+перетаскивание узла) — подсказка в статус-баре
        self.view.connect_drag_started.connect(
            lambda: self.statusBar().showMessage(self.t("hint.connect_drag")))
        self.view.connect_drag_finished.connect(
            lambda: self.statusBar().showMessage(self.t("status.ready")))

        splitter.addWidget(self.view)
        splitter.setSizes([250, 950])

        # Status bar
        if self._i18n_available:
            try:
                from i18n import t as __t
                self.statusBar().showMessage(__t("status.ready"))
            except Exception:
                pass
        else:
            self.statusBar().showMessage("Готово. Двойной клик — свойства узла.")

        # UI polish: постоянные индикаторы справа в статус-баре — счётчики узлов/
        # связей/статусов и процент зума (обновляются из MapView.zoomChanged).
        self.counts_label = QLabel("")
        self.counts_label.setStyleSheet("color: #94a3b8; padding-right: 10px;")
        self.statusBar().addPermanentWidget(self.counts_label)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.zoom_label.setStyleSheet("color: #e2e8f0; padding-right: 6px;")
        self.statusBar().addPermanentWidget(self.zoom_label)

        try:
            self.view.zoomChanged.connect(self._on_zoom_changed)
        except Exception:  # noqa: BLE001 — без сигнала статус-бар просто не обновится
            pass
        self._update_counts_label()

        if self.log:
            self.log.info("MainWindow UI initialized")

    # ── Unsaved changes tracking ─────────────────────
    
    def _mark_dirty(self):
        """Mark project as having unsaved changes."""
        self._dirty = True
        self._update_window_title()

    # ── v0.8.3: Undo/Redo ─────────────────────────────────────────

    def _push_command(self, command):
        """Единая точка входа: push команды в стек (redo выполняется сам)."""
        try:
            self.undo_stack.push(command)
        except Exception as e:
            if self.log:
                self.log.warning(f"undo push failed: {e}")

    def _commit_node_move(self, node, old_pos, new_pos):
        """v0.8.3: завершён жест перетаскивания узла → команда CmdMoveNode."""
        from modules.undo_commands import CmdMoveNode
        self._push_command(CmdMoveNode(self, node, old_pos, new_pos))
        self._mark_dirty()

    def _commit_nodes_move(self, moves):
        """v0.9.3: завершён групповой drag → ОДНА команда CmdMoveNodes."""
        from modules.undo_commands import CmdMoveNodes
        if not moves:
            return
        self._push_command(CmdMoveNodes(self, moves))
        self._mark_dirty()

    def _on_stack_changed(self):
        """QUndoStack.indexChanged/canUndoChanged → пересчитать dirty-маркер."""
        try:
            self._dirty = self.undo_stack.canUndo() or self._undo_baseline_dirty
        except RuntimeError:
            # Qt teardown: C++-объект стека уничтожен вместе с окном (паттерн
            # _sync_selection_state) — обновлять заголовок некому и незачем.
            return
        self._update_window_title()

    def _post_undo_refresh(self):
        """Синхронизировать UI с фактическим состоянием сцены (после undo/redo)."""
        try:
            self.refresh_sidebar()
        except Exception:
            pass
        try:
            self._update_counts_label()
        except Exception:
            pass
        try:
            self._sync_status_targets()
        except Exception:
            pass

    def _undo(self):
        try:
            self.undo_stack.undo()
            self.statusBar().showMessage(
                self.t("status.undone", action=self.undo_stack.text(self.undo_stack.index()))
                if self._i18n_available else "Undo.")
        except Exception as e:
            if self.log:
                self.log.warning(f"undo failed: {e}")

    def _redo(self):
        try:
            self.undo_stack.redo()
            self.statusBar().showMessage(
                self.t("status.redone") if self._i18n_available else "Redo.")
        except Exception as e:
            if self.log:
                self.log.warning(f"redo failed: {e}")

    def _reset_undo_stack(self):
        """Сброс стека и baseline (new/open/save/load)."""
        self.undo_stack.clear()
        self._note_committed.clear()
        for note in self.scene.notes():
            self._note_committed[note.note_id] = note.text()
        self._undo_baseline_dirty = False

    def _attach_note(self, note):
        """Подключить сигналы заметки (undo-текст + dirty) — путь создания и undo/redo."""
        self._connect_note_signals(note)
        self._note_committed[note.note_id] = note.text()

    def _commit_note_text(self):
        """Дебаунс правки текста заметки → команда CmdEditTextNote."""
        pending = self._note_edit_pending
        self._note_edit_pending = None
        if not pending:
            return
        note, old_text = pending
        try:
            new_text = note.text()
        except RuntimeError:
            return
        committed = self._note_committed.get(note.note_id)
        if new_text == old_text or (committed is not None and new_text == committed):
            return  # ничего не поменялось / уже закоммичено предыдущей командой
        from modules.undo_commands import CmdEditTextNote
        self._note_committed[note.note_id] = new_text
        self._push_command(CmdEditTextNote(self, note, committed if committed is not None else old_text, new_text))

    def closeEvent(self, event):
        """Ask to save on exit if there are unsaved changes."""
        # v0.9.4-fix: остановка фоновых QThread выполняется при ЛЮБОМ выходе.
        # Раньше вызов стоял только в конце «чистого» выхода: все три ветки
        # диалога делали ранний return до шатдауна, и при несохранённых
        # изменениях (самый частый случай) работающие SystemInfoCollector /
        # ping / DNS-потоки уничтожались вместе с QObject →
        # «QThread: Destroyed while thread is still running».
        # Потоки останавливаем ДО диалога — он может держать окно открытым
        # сколько угодно, а фоновая работа к моменту закрытия уже не нужна.
        self._shutdown_background_threads()

        if self._has_unsaved_changes:
            reply = QMessageBox.question(
                self, 
                self.t("dialog.save_changes") if self._i18n_available else "Сохранить изменения?",
                self.t("msg.save_on_exit") if self._i18n_available else "Есть несохранённые изменения. Сохранить перед выходом?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )
            if reply == QMessageBox.Save:
                # Закрываемся только если сохранение реально удалось —
                # иначе данные терялись бы молча (см. AUDIT.md, критичная #1).
                saved = self._save_project()
                event.accept() if saved else event.ignore()
                return
            elif reply == QMessageBox.Discard:
                event.accept()
                return
            else:
                event.ignore()
                return

        event.accept()

    def _shutdown_background_threads(self):
        """Остановить коллекторы, ping/DNS-потоки и терминальные сессии.

        Паттерн взят у StatusChecker: stop() + ограниченный wait() — никогда
        не блокируем GUI-поток дольше пары секунд на поток.
        """
        threads = []

        # Автосбор системной информации (SystemInfoCollector)
        for coll in getattr(self, "_info_collectors", {}).values():
            stop = getattr(coll, "stop", None) or getattr(coll, "request_stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
            if hasattr(coll, "isRunning"):
                threads.append(coll)

        # Ping и обратный DNS
        for attr in ("_ping_thread", "_dns_thread"):
            th = getattr(self, attr, None)
            if th is not None and hasattr(th, "isRunning") and th.isRunning():
                stop = getattr(th, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
                threads.append(th)

        # Терминальные окна: их closeEvent сам делает thread.stop()+wait();
        # здесь только ждём остаток, если окно ещё не закрыто пользователем.
        terminal_waits = []
        for w in list(getattr(self, "_terminal_windows", [])):
            try:
                if w.isVisible():
                    w.close_terminal()
                th = getattr(w, "terminal_thread", None)
                if th is not None and hasattr(th, "isRunning") and th.isRunning():
                    terminal_waits.append(th)
            except Exception:
                pass

        total_wait_ms = 2000
        per_thread = max(total_wait_ms // max(len(threads) + len(terminal_waits), 1), 200)
        deadline = __import__("time").monotonic() + total_wait_ms / 1000.0
        for th in threads + terminal_waits:
            remaining = int(max(deadline - __import__("time").monotonic(), 0.05) * 1000)
            try:
                th.wait(min(per_thread, remaining))
            except Exception:
                pass

    @property
    def _has_unsaved_changes(self) -> bool:
        """Check if current project has unsaved changes."""
        return self._dirty

    def _resolve_server_node(self, item):
        while item is not None:
            if isinstance(item, ServerNode):
                return item
            item = item.parentItem()
        return None

    def eventFilter(self, source, event):
        """Handle double-click on any child element of a node."""
        if source == self.view.viewport() and event.type() == QMouseEvent.MouseButtonDblClick:
            # AUDIT v0.7.2 (средняя #9): position() — современный Qt6 API;
            # pos() оставлен fallback'ом для legacy-биндингов.
            try:
                local_pos = event.position().toPoint()
            except AttributeError:
                local_pos = event.pos()
            scene_pos = self.view.mapToScene(local_pos)
            item = self.scene.itemAt(scene_pos, self.view.transform())
            node = self._resolve_server_node(item)
            if node:
                self._on_node_double_click_direct(node)
                return True
        return super().eventFilter(source, event)

    def _setup_toolbar(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        # UI polish: у всех действий — векторные иконки (ui/icons.py, замена эмодзи);
        # текстовые-только действия в тулбаре выглядели бы чужеродно.
        groups = (
            ((("file.new_project"), self._new_project, "new"),
             ("file.open", self._open_project, "open"),
             ("file.save", self._save_project, "save"),
             ("file.save_as", self._save_project_as, "save")),
            (("btn.add_server", self._add_server, "add_server"),
             ("btn.add_connection", self._add_connection, "connection"),
             ("view.center_map", self._center_view, "center"),
             ("view.fit_map", self._fit_to_content, "fit")),
        )
        # Тексты без i18n (как в старом else-ветвлении) — UI polish: иконки теперь есть
        _fallback = {
            "file.new_project": "Новый", "file.open": "Открыть", "file.save": "Сохранить",
            "file.save_as": "Сохранить как", "btn.add_server": "Добавить сервер",
            "btn.add_connection": "Добавить связь", "view.center_map": "Центрировать",
            "view.fit_map": "Вписать карту",
        }

        for gi, group in enumerate(groups):
            if gi:
                toolbar.addSeparator()
            for key, slot, icon_name in group:
                text = self.t(key) if self._i18n_available else _fallback[key]
                action = toolbar.addAction(text, slot)
                self._register_i18n(action, key)
                try:
                    icon = get_icon(icon_name)
                    if icon is not None and not icon.isNull():
                        action.setIcon(icon)  # tooltip подхватит текст действия сам
                except Exception:  # noqa: BLE001 — иконка косметика, не роняем тулбар
                    pass

        # v0.8.3: undo/redo в тулбаре (иконки + текст, включённость ведёт QUndoStack)
        toolbar.addSeparator()
        self.act_undo = toolbar.addAction(
            self.t("edit.undo") if self._i18n_available else "Отменить",
            self._undo)
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.setEnabled(False)
        try:
            icon = get_icon("undo")
            if icon is not None and not icon.isNull():
                self.act_undo.setIcon(icon)
        except Exception:
            pass
        self.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)

        self.act_redo = toolbar.addAction(
            self.t("edit.redo") if self._i18n_available else "Вернуть",
            self._redo)
        self.act_redo.setShortcuts(["Ctrl+Y", "Ctrl+Shift+Z"])
        self.act_redo.setEnabled(False)
        try:
            icon = get_icon("redo")
            if icon is not None and not icon.isNull():
                self.act_redo.setIcon(icon)
        except Exception:
            pass
        self.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)

    def _add_menu_action(self, menu, key: str, slot, shortcut: str = ""):
        """Добавить пункт меню с переводом и зарегистрировать его для повторного перевода."""
        action = menu.addAction(self.t(key), slot, shortcut) if shortcut \
            else menu.addAction(self.t(key), slot)
        self._register_i18n(action, key)
        return action

    def _setup_menubar(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(self.t("menu.file") if self._i18n_available else "Файл")
        self._register_i18n(file_menu, "menu.file")
        self._add_menu_action(file_menu, "file.new_project", self._new_project, "Ctrl+N")
        self._add_menu_action(file_menu, "file.open", self._open_project, "Ctrl+O")
        self._add_menu_action(file_menu, "file.save", self._save_project, "Ctrl+S")
        self._add_menu_action(file_menu, "file.save_as", self._save_project_as)
        # v0.9.5.5: массовый импорт серверов из текстового файла
        self._add_menu_action(file_menu, "file.import_servers", self._import_servers_from_txt)
        # v0.9.1: экспорт карты в изображение (PNG/JPEG)
        file_menu.addSeparator()
        self._add_menu_action(file_menu, "file.export_png", self._export_map_image)
        # v0.9.5: экспорт карты в drawio (.drawio)
        self._add_menu_action(file_menu, "file.export_drawio", self._export_map_drawio)
        file_menu.addSeparator()
        self._add_menu_action(file_menu, "file.exit", self.close)

        # Edit menu
        edit_menu = menubar.addMenu(self.t("menu.edit") if self._i18n_available else "Правка")
        self._register_i18n(edit_menu, "menu.edit")
        # v0.8.3: Undo/Redo — первые пункты меню «Правка»
        self._add_menu_action(edit_menu, "edit.undo", self._undo, "Ctrl+Z")
        self._add_menu_action(edit_menu, "edit.redo", self._redo, "Ctrl+Y")
        edit_menu.addSeparator()
        self._add_menu_action(edit_menu, "edit.add_server", self._add_server, "Ctrl+Shift+A")
        self._add_menu_action(edit_menu, "edit.add_group", self._add_group_at, "Ctrl+Shift+G")  # v0.8.1: группы узлов
        self._add_menu_action(edit_menu, "edit.add_connection", self._add_connection, "Ctrl+Shift+C")
        self._add_menu_action(edit_menu, "edit.properties", self._show_properties, "Ctrl+I")
        # v0.9.2: горячие клавиши частых действий над выделенным узлом
        self._add_menu_action(edit_menu, "ctx.ssh_connect", self._connect_ssh_to_selected, "Ctrl+Return")
        self._add_menu_action(edit_menu, "ctx.edit_server", self._edit_selected_node, "Ctrl+E")
        self._add_menu_action(edit_menu, "ctx.add_note", self._add_note_at_view_center, "Ctrl+Shift+N")
        self._add_menu_action(edit_menu, "edit.delete", self._delete_selected, "Delete")
        # v0.9.3: дублирование + групповые операции мультивыделения
        self._add_menu_action(edit_menu, "edit.duplicate", self._duplicate_selected_node, "Ctrl+D")
        edit_menu.addSeparator()
        self._add_menu_action(edit_menu, "edit.connect_selected", self._connect_selected_nodes)
        self._add_menu_action(edit_menu, "edit.delete_selected", self._delete_selected_nodes)

        # Profile menu
        profile_menu = menubar.addMenu(self.t("menu.profile") if self._i18n_available else "Профиль")
        self._register_i18n(profile_menu, "menu.profile")
        self._add_menu_action(profile_menu, "profile.manage", self._open_profile_manager)

        # View menu
        view_menu = menubar.addMenu(self.t("menu.view") if self._i18n_available else "Вид")
        self._register_i18n(view_menu, "menu.view")
        self._add_menu_action(view_menu, "view.center_map", self._center_view)
        self._add_menu_action(view_menu, "view.reset_zoom", self._reset_zoom)
        # UI polish: «Вписать карту» — fitInView по содержимому (Ctrl+Shift+F: F одной
        # клавишей конфликтовал бы с вводом в поле поиска сайдбара)
        self._add_menu_action(view_menu, "view.fit_map", self._fit_to_content, "Ctrl+Shift+F")
        # v0.8.4 (DESIGN.md §D): массовое сворачивание — половина ценности фичи
        # для больших карт.
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "view.collapse_all", self._collapse_all_servers)
        self._add_menu_action(view_menu, "view.expand_all", self._expand_all_servers)
        # v0.9.1: фоновое изображение карты (схема здания / план дата-центра)
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "view.set_background", self._set_background_image)
        self._add_menu_action(view_menu, "view.remove_background", self._remove_background_image)

        # Help menu
        help_menu = menubar.addMenu(self.t("menu.help") if self._i18n_available else "Помощь")
        self._register_i18n(help_menu, "menu.help")
        self._add_menu_action(help_menu, "help.open_logs", self._open_log_file)

        # Language submenu (i18n)
        if self._i18n_available:
            try:
                from i18n import get_available_languages as _get_langs
                langs = _get_langs()
                lang_menu = help_menu.addMenu(self.t("lang.menu"))
                self._register_i18n(lang_menu, "lang.menu")
                for lg in langs:
                    action = lang_menu.addAction(lg["name"])
                    action.setCheckable(True)
                    action.setChecked(lg["code"] == self.current_language)
                    action.setData(lg["code"])  # код языка — для отметки при переключении
                    code = lg["code"]
                    action.triggered.connect(lambda checked, c=code: self._switch_language(c))
            except Exception as e:
                if self.log:
                    self.log.warning(f"i18n lang menu error: {e}")

        # v0.9.2: палитра команд (Ctrl+K) — fuzzy-поиск по действиям и серверам.
        self._setup_command_palette()

    def _setup_command_palette(self):
        """v0.9.2: создать палитру команд и хоткей Ctrl+K."""
        try:
            from ui.command_palette import CommandPalette
        except ImportError:  # плоский запуск из корня проекта
            from command_palette import CommandPalette
        self._command_palette = CommandPalette(self, self)

        from PySide6.QtGui import QShortcut, QKeySequence
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.activated.connect(self._open_command_palette)

    def _open_command_palette(self):
        if getattr(self, "_command_palette", None) is not None:
            self._command_palette.open_palette()

    def _iter_server_nodes(self):
        """Все ServerNode сцены (для collapse/expand all)."""
        scene = getattr(self, "scene", None)
        if scene is None:
            return []
        try:
            return [it for it in scene.items()
                    if isinstance(it, ServerNode)]
        except Exception:
            return []

    def _set_all_collapsed(self, collapsed: bool):
        """v0.8.4: свернуть/развернуть все плашки; состояние сохраняется в проект."""
        changed = False
        for node in self._iter_server_nodes():
            if bool(getattr(node.data, "collapsed", False)) != collapsed:
                node.toggle_collapsed()
                changed = True
        if changed:
            self._mark_dirty()

    def _collapse_all_servers(self):
        self._set_all_collapsed(True)

    def _expand_all_servers(self):
        self._set_all_collapsed(False)

    def _switch_language(self, language_code: str):
        """Switch application language and re-apply to all UI elements."""
        try:
            from i18n import set_language as _set_lang
            
            # Set the new language
            success = _set_lang(language_code)
            
            if success:
                self.current_language = language_code

                # Переводим меню/тулбар/подписи по зарегистрированным ключам
                self._apply_ui_translations()

                # Заголовок окна (с учётом файла проекта и маркера [*])
                self._update_window_title()

                # Отмечаем активный язык в подменю Язык
                menubar = self.menuBar()
                for action in menubar.actions():
                    menu = action.menu() if hasattr(action, "menu") else None
                    if menu is None:
                        continue
                    for sub in menu.actions():
                        if sub.data() is not None:
                            sub.setChecked(sub.data() == language_code)

                if self.log:
                    self.log.info(f"Language switched to {language_code}")
            else:
                QMessageBox.warning(self, self.t("msg.error_title"), 
                                   f"{self.t('lang.switch_failed')}: {language_code}")
        except Exception as e:
            if self.log:
                self.log.exception(f"Error switching language to {language_code}")

    # ─────────────────────────────────────────────

    def _on_node_double_click_direct(self, node: ServerNode):
        """Handle double-click on a node."""
        try:
            dlg = AddServerDialog(self, edit_data=node.data)
            if dlg.exec() == QDialog.Accepted:
                new_data = dlg.get_data()
                # v0.8.3: правка данных сервера — undo-команда (id сохраняем!)
                new_data.id = node.data.id
                old_data = copy.deepcopy(node.data)
                from modules.undo_commands import CmdEditNodeData
                self._push_command(CmdEditNodeData(self, node, old_data, new_data))
                self.refresh_sidebar()
                # v0.7.1: host/порт могли измениться — обновляем план проверок и
                # сбрасываем статус (старый больше неактуален)
                node.reset_status()
                self._sync_status_targets()
                if self.log:
                    self.log.info("Server updated", extra={"alias": new_data.alias})
                self.statusBar().showMessage(self.t("status.server_updated", alias=new_data.alias))
                self._mark_dirty()  # ← unsaved changes
                # v0.9.5.6: «Подключиться по SSH» из свойств — данные уже
                # применены к узлу (CmdEditNodeData), открываем SSH-диалог
                # с предзаполненным паролем из полей свойств.
                if getattr(dlg, "_connect_after_accept", False):
                    self._run_ssh_connect(node, prefill_password=dlg.password.text())
        except Exception as e:
            if self.log:
                self.log.exception(f"Error updating server {node.data.alias}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.update_failed", error=str(e)))

    def _select_node(self, node: ServerNode, center: bool = False):
        self.scene.blockSignals(True)
        try:
            self.scene.clearSelection()
            node.setSelected(True)
        finally:
            self.scene.blockSignals(False)
        self._sync_selection_state()
        if center:
            self.view.centerOn(node)

    def _sync_selection_state(self):
        try:
            selected_node = self.scene.get_selected_node()
            # v0.9.3: мультивыделение — подсветка рамки у КАЖДОГО выделенного
            # узла, а не только первого из selectedItems().
            for node in self.scene.nodes():
                try:
                    node.set_selected(node.isSelected())
                except RuntimeError:
                    pass  # Qt teardown — отдельный item уничтожен

            selected_id = selected_node.data.id if selected_node else None
            self.tree.blockSignals(True)
            try:
                self.tree.setCurrentItem(None)
                for i in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(i)
                    if item.data(0, Qt.UserRole) == selected_id:
                        self.tree.setCurrentItem(item)
                        break
            finally:
                self.tree.blockSignals(False)
        except RuntimeError:
            # PySide6/Qt teardown при выходе из процесса: C++-объект сцены уже
            # уничтожен, а сигнал selectionChanged доехал до живого Python-слота.
            # Нормальное состояние — молча игнорируем (иначе traceback в консоль).
            pass

    def _connect_ssh_to_selected(self):
        """Connect via SSH to selected server."""
        node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                  self.t("msg.select_server_ssh"))
            return
        try:
            self._run_ssh_connect(node)
        except Exception as e:
            if self.log:
                self.log.exception(f"SSH connect error for {node.data.alias}")
            QMessageBox.critical(self, self.t("msg.ssh_error"), self.t("msg.connect_failed", error=str(e)))

    def _run_ssh_connect(self, node: "ServerNode", prefill_password: str = ""):
        """v0.9.5.6: SSH-диалог → при успехе: обновить данные узла, индикатор,
        автосбор информации и терминальное окно.

        Общий путь для «Подключиться по SSH» из тулбара/контекста (prefill="")
        и из диалога свойств сервера (prefill_password — пароль из полей свойств,
        чтобы пользователь не вставлял его повторно).
        """
        dlg = SSHConnectDialog(node.data, self)
        if prefill_password:
            dlg.password_edit.setText(prefill_password)
        if dlg.exec() != QDialog.Accepted:
            return
        # v0.9.4-fix: правки user/key_path/ssh_port из диалога идут через
        # undo-стек и помечают проект dirty (раньше писались напрямую в
        # node.data — терялись при выходе без Ctrl+S и не откатывались).
        from modules.undo_commands import CmdEditNodeData
        old_data = copy.deepcopy(node.data)
        new_data = copy.deepcopy(node.data)
        new_data.user = dlg.user_edit.text().strip()
        new_data.key_path = dlg.key_path_edit.text().strip()
        new_data.ssh_port = dlg.port_edit.value()
        if (old_data.user, old_data.key_path, old_data.ssh_port) != \
                (new_data.user, new_data.key_path, new_data.ssh_port):
            self._push_command(CmdEditNodeData(self, node, old_data, new_data))
        else:
            self._mark_dirty()
        # AUDIT v0.7.2 (средняя #7): пароль НЕ храним в модели — передаём его
        # напрямую терминальному окну ниже; сам диалог уже записал его в keyring
        # (_on_worker_success), так что ничего не теряется при сохранении проекта.

        node.update_appearance()
        node.set_ssh_connected(True)
        self._ssh_connected_nodes.add(node.data.id)  # v0.9.4-fix: сброс индикатора при закрытии терминала
        if self.log:
            self.log.info("SSH connected", extra={"alias": node.data.alias, "host": node.data.host})
        self.statusBar().showMessage(self.t("status.ssh_connected", alias=node.data.alias))

        # v0.9: автосбор данных о сервере после успешного подключения
        # (пароль из диалога ещё не потерян; НЕ через StatusChecker —
        # тот работает без аутентификации по дизайну)
        if getattr(node.data, "os_name", "") == "" and \
                hasattr(dlg, "password_edit"):
            self._collect_node_info(
                node, password=dlg.password_edit.text(), auto=True)

        # Open interactive terminal (пароль — явно, см. AUDIT v0.7.2 средняя #7)
        terminal_window = SSHTerminalWindow(
            node.data, self, password=dlg.password_edit.text())
        terminal_window.destroyed.connect(lambda *_: self._forget_terminal_window(terminal_window))
        self._terminal_windows.append(terminal_window)
        terminal_window.show()

    # ── v0.9: автосбор данных о сервере (Linux) ───────────────────

    def _collect_node_info(self, node, password: str = "", auto: bool = False):
        """Запустить SystemInfoCollector для узла.

        auto=True — тихий автозапуск после успешного SSH-подключения
        (без сообщений об ошибке, только статус-бар).
        """
        try:
            from services.system_info_collector import SystemInfoCollector
        except ImportError as e:
            if self.log:
                self.log.warning(f"SystemInfoCollector unavailable: {e}")
            return
        sid = node.data.id
        # Guard: не плодим параллельные сборы для одного узла
        old = getattr(self, "_info_collectors", {}).get(sid)
        if old is not None and old.isRunning():
            return
        if not hasattr(self, "_info_collectors"):
            self._info_collectors = {}
        collector = SystemInfoCollector(node.data, password=password, parent=self)
        self._info_collectors[sid] = collector

        def _ready(server_id, info, coll=collector):
            self._on_info_ready(server_id, info, coll)

        def _failed(server_id, error, coll=collector):
            self._on_info_failed(server_id, error, coll, auto=auto)

        collector.info_ready.connect(_ready)
        collector.info_failed.connect(_failed)
        collector.finished.connect(
            lambda *_a: self._info_collectors.pop(sid, None))
        collector.start()
        key = "status.info_running_auto" if auto else "status.info_running"
        try:
            self.statusBar().showMessage(self.t(key, alias=node.data.alias), 4000)
        except Exception:
            pass

    def _on_info_ready(self, server_id: str, info: dict, collector):
        """Результат сбора: записать в node.data + dirty + перерисовка."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # узел удалён, пока собирали
        d = node.data
        if info.get("os_name"):
            d.os_name = info["os_name"]
        if info.get("cpu_model"):
            d.cpu_model = info["cpu_model"]
        if info.get("cpu_cores"):
            d.cpu = f"{info['cpu_cores']} core"
        if info.get("ram_gb"):
            d.ram = info["ram_gb"]
        if info.get("disk_gb"):
            d.disk = info["disk_gb"]
        node.update_appearance()
        self.refresh_sidebar()
        self._mark_dirty()
        try:
            self.statusBar().showMessage(
                self.t("status.info_collected", alias=d.alias), 5000)
        except Exception:
            pass
        if self.log:
            self.log.info("System info collected",
                          extra={"alias": d.alias, "os": d.os_name})

    def _on_info_failed(self, server_id: str, error: str, collector,
                        auto: bool = False):
        node = self.scene.get_node(server_id)
        alias = node.data.alias if node is not None else server_id
        if self.log:
            self.log.warning(f"Info collection failed for {alias}: {error}")
        if auto:
            return  # тихий режим — не пугаем пользователя при обычном подключении
        try:
            self.statusBar().showMessage(
                self.t("status.info_failed", error=error), 8000)
        except Exception:
            pass

    def _connect_ssh_external(self, node=None):
        """v0.8.2: открыть SSH-сессию в системном терминале ОС (wt/cmd/gnome-terminal).

        Пароль НЕ передаётся (виден в ps) — ssh ОС спросит сам / key auth.
        """
        if node is None:
            node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                  self.t("msg.select_server_ssh"))
            return
        if _ext_term is None:
            return
        data = node.data
        ok, err = _ext_term.connect_external(
            host=data.host.strip(),
            user=(data.user or "").strip(),
            port=data.ssh_port or 22,
            key_path=(data.key_path or "").strip() or None,
        )
        if not ok:
            if err == "no_ssh_client":
                QMessageBox.warning(self, self.t("msg.error_title"),
                                    self.t("ssh_ext.no_ssh_client"))
            elif err == "no_terminal":
                QMessageBox.warning(self, self.t("msg.error_title"),
                                    self.t("ssh_ext.no_terminal"))
            else:
                self.statusBar().showMessage(
                    self.t("ssh_ext.launch_failed"), 5000)
                QMessageBox.critical(self, self.t("msg.ssh_error"),
                                     self.t("ssh_ext.launch_failed"))
            return
        self.statusBar().showMessage(
            self.t("ssh_ext.launched", alias=data.alias), 5000)
        if self.log:
            self.log.info("SSH launched in external terminal",
                          extra={"alias": data.alias, "host": data.host})

    def _forget_terminal_window(self, window):
        self._terminal_windows = [w for w in self._terminal_windows if w is not window]
        # v0.9.4-fix: терминал закрыт → гасим зелёную SSH-точку узла
        # (раньше индикатор горел вечно после первого подключения).
        try:
            sid = getattr(getattr(window, "server_data", None), "id", None)
            if sid:
                self._ssh_connected_nodes.discard(sid)
                node = self.scene.get_node(sid) if hasattr(self.scene, "get_node") else None
                if node is not None and not any(
                    getattr(w, "server_data", None) is not None
                    and getattr(w, "server_data").id == sid
                    for w in self._terminal_windows
                ):
                    node.set_ssh_connected(False)
        except RuntimeError:
            pass  # C++-объект уже уничтожен при teardown — нормально

    def _add_server(self, at_scene_pos=None):
        """Создать сервер (атрибут `at_scene_pos` — точка клика из контекстного меню)."""
        data = None  # чтобы except-ветка не падала на несуществующей переменной (AUDIT.md)
        try:
            dlg = AddServerDialog(self)
            if dlg.exec() == QDialog.Accepted:
                data = dlg.get_data()
                # Позиция: точка клика (ПКМ-меню, v0.7.2) или центр видимой области.
                # v0.8.1: принимаем позицию только если это действительно точка —
                # QAction.triggered (тулбар/меню) шлёт в слот bool `checked`, который
                # раньше попадал сюда как at_scene_pos и ронял `center.x()`.
                if _is_scene_point(at_scene_pos):
                    center = at_scene_pos
                else:
                    center = self.view.mapToScene(self.view.viewport().rect().center())
                # Ревью-фикс v0.8.0 (#1): оффсеты — половины базового размера узла
                # (MIN_NODE_WIDTH=180 / MIN_NODE_HEIGHT=130 → 90/65), чтобы новый узел
                # центрировался под точкой клика, а не смещался вправо-вниз от курсора.
                data.x = center.x() - ServerNode.MIN_NODE_WIDTH / 2
                data.y = center.y() - ServerNode.MIN_NODE_HEIGHT / 2
                # v0.8.3: узел создаёт команда undo (push сам выполняет redo)
                from modules.undo_commands import CmdAddRemoveNode
                self._push_command(CmdAddRemoveNode(self, self.scene, data, "add"))
                node = self.scene.get_node(data.id)
                self.refresh_sidebar()
                self._sync_status_targets()  # v0.7.1: новый узел — в план проверок
                if self.log:
                    self.log.info("Server added", extra={"alias": data.alias, "host": data.host})
                self.statusBar().showMessage(self.t("status.server_added", alias=data.alias))
                self._mark_dirty()  # ← unsaved changes
                # v0.9.5.6: «Подключиться по SSH» из диалога добавления — узел
                # уже создан, сразу открываем SSH-диалог (пароль предзаполнен).
                if getattr(dlg, "_connect_after_accept", False):
                    self._run_ssh_connect(node, prefill_password=dlg.password.text())
        except Exception as e:
            if self.log:
                self.log.exception(f"Error adding server {getattr(data, 'alias', '?')}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.add_failed", error=str(e)))

    def _import_servers_from_txt(self):
        """v0.9.5.5: массовый импорт серверов из текстового файла.

        Формат: по одному хосту в строке (IP или DNS-имя), '#'/'//' — комментарии.
        IP → host=IP; имя → резолвим в IP (поле `ip`), host остаётся именем.
        Дубликаты (уже на карте или повтор в файле) пропускаются. Один узел undo —
        вся пачка добавляется/откатывается одной командой CmdAddRemoveNodeBatch.
        """
        import socket as _socket
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.import_servers"), "",
            "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.import_servers_failed", error=str(e)))
            return

        from services.host_importer import parse_hosts_file, is_ip_address, resolve_host
        entries, file_dups = parse_hosts_file(text), []
        # Дедупликация строк файла (без учёта регистра)
        seen, unique_entries = set(), []
        for e in entries:
            if e.lower() in seen:
                continue
            seen.add(e.lower())
            unique_entries.append(e)

        # Хосты/IP, уже присутствующие на карте — тоже дубликаты
        existing = set()
        for node in self.scene.nodes():
            d = node.data
            existing.add((d.host or "").lower())
            if d.ip:
                existing.add(d.ip.lower())

        added_data, skipped = [], len(file_dups)
        for entry in unique_entries:
            if entry.lower() in existing:
                skipped += 1
                continue
            import uuid as _uuid
            if is_ip_address(entry):
                host, ip = entry, entry
            else:
                host, ip = entry, resolve_host(entry) or ""
                QApplication.processEvents()  # UI не замирает при длинном резолве
            from models.server import ServerData
            data = ServerData(
                id=str(_uuid.uuid4())[:8],
                alias=entry,
                host=host,
                user="",
                password="",
                ip=ip,
            )
            added_data.append(data)
            existing.add(entry.lower())

        if not added_data:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.import_servers_result", added=0, skipped=skipped))
            return

        # Раскладка импортированных узлов сеткой от центра видимой области
        center = self.view.mapToScene(self.view.viewport().rect().center())
        col_w, row_h, cols = ServerNode.MIN_NODE_WIDTH + 30, ServerNode.MIN_NODE_HEIGHT + 30, 6
        for i, data in enumerate(added_data):
            r, c = divmod(i, cols)
            data.x = center.x() - 90 + c * col_w
            data.y = center.y() - 65 + r * row_h

        from modules.undo_commands import CmdAddRemoveNodeBatch
        self._push_command(CmdAddRemoveNodeBatch(self, self.scene, added_data, "add"))
        self.refresh_sidebar()
        self._sync_status_targets()
        self._mark_dirty()
        if self.log:
            self.log.info(f"Imported {len(added_data)} servers from {path}")
        self.statusBar().showMessage(
            self.t("status.servers_imported", count=len(added_data)), 5000)
        QMessageBox.information(self, self.t("msg.success_title"),
                                self.t("msg.import_servers_result",
                                       added=len(added_data), skipped=skipped))

    def _add_connection(self, default_source_id=None, default_target_id=None):
        """Создать связь: диалог с выбором узлов, метки и типа (v0.7).

        Параметры prefill используются drag-режимом MapView (Shift+перетаскивание).
        """
        nodes = list(self.scene.nodes())
        if len(nodes) < 2:
            QMessageBox.information(self, self.t("msg.info_title"), 
                                  self.t("validation.min_servers"))
            return

        try:
            dlg = ConnectionDialog(
                nodes, self,
                default_source_id=default_source_id,
                default_target_id=default_target_id,
            )
            if dlg.exec() == QDialog.Accepted:
                # get_connection() возвращает id узлов (строки), а не объекты ServerNode;
                # 4-й элемент — тип связи (v0.7)
                src, tgt, lbl, ctype = dlg.get_connection()
                if src == tgt:
                    QMessageBox.warning(self, self.t("msg.error_title"), 
                                      self.t("validation.self_connection"))
                    return
                # v0.8.3: связь создаёт undo-команда (push сам выполняет redo)
                from modules.undo_commands import CmdAddRemoveConnection
                self._push_command(CmdAddRemoveConnection(
                    self, self.scene, src, tgt, lbl, ctype, "add"))
                if not self.scene.has_connection(src, tgt):
                    # команда не смогла создать (узлы исчезли?) — как раньше, предупреждение
                    QMessageBox.warning(self, self.t("msg.error_title"),
                                        self.t("validation.connection_error"))
                    return
                arrow = None
                if self.log:
                    src_node = self.scene.get_node(src)
                    tgt_node = self.scene.get_node(tgt)
                    if src_node and tgt_node:
                        self.log.info("Connection added", extra={"source": src_node.data.alias, "target": tgt_node.data.alias})
                self.statusBar().showMessage(self.t("status.connection_added"))
                self._update_counts_label()  # UI polish: счётчик связей в статус-баре
                self._mark_dirty()  # ← unsaved changes
        except Exception as e:
            if self.log:
                self.log.exception("Error adding connection")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.create_connection_failed", error=str(e)))

    def _show_properties(self):
        node = self.scene.get_selected_node()
        if node:
            self._on_node_double_click_direct(node)
        else:
            QMessageBox.information(self, self.t("msg.info_title"), 
                                  self.t("msg.properties_select"))

    # ── v0.7.3: контекстное меню узла и стрелки ────────────────

    def _edit_node(self, node: "ServerNode"):
        """Редактирование узла (контекстное меню / двойной клик)."""
        if node is not None:
            self._on_node_double_click_direct(node)

    # ── v0.9.2: хоткеи частых действий над выделенным узлом ─────

    def _edit_selected_node(self):
        """Ctrl+E: редактировать выделенный на карте сервер."""
        node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return
        self._edit_node(node)

    # ── v0.9.3: дублирование узла + мультивыделение/групповые операции ──

    def _duplicate_node(self, node: "ServerNode", offset: float = 40.0):
        """Ctrl+D / ПКМ: копия узла (все поля, кроме id) со смещением.

        Пароль в JSON не хранится — он лежит в keyring по server_id, поэтому
        для копии загружаем пароль исходника и сохраняем под НОВЫМ id.
        Возвращает новый ServerNode или None (узел не найден).
        """
        if node is None or node.scene() is None:
            return None
        import copy as _copy
        data = _copy.deepcopy(node.data)
        data.x = float(node.data.x) + offset
        data.y = float(node.data.y) + offset
        # новый уникальный id
        import uuid as _uuid
        while True:
            new_id = str(_uuid.uuid4())[:8]
            if not self.scene.has_node(new_id):
                break
        data.id = new_id
        # v0.9.3: пароль из keyring по server_id нового узла (задача #1)
        try:
            from services.credential_manager import get_credential_manager
            cm = get_credential_manager()
            pw = cm.load_password(node.data.id)
            if pw:
                cm.save_password(new_id, pw)
        except Exception:  # noqa: BLE001 — keyring недоступен: копия без пароля
            pass
        from modules.undo_commands import CmdAddRemoveNode
        self._push_command(CmdAddRemoveNode(self, self.scene, data, "add"))
        new_node = self.scene.get_node(new_id)
        self.refresh_sidebar()
        self._sync_status_targets()
        self.statusBar().showMessage(
            self.t("status.server_duplicated", alias=data.alias)
            if self._i18n_available else f"Duplicated: {data.alias}")
        self._mark_dirty()  # ← unsaved changes
        return new_node

    def _duplicate_selected_node(self):
        """Ctrl+D: продублировать выделенный узел; новый узел становится выделенным."""
        node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return None
        new_node = self._duplicate_node(node)
        if new_node is not None:
            self._select_node(new_node)
        return new_node

    def selected_nodes(self) -> list:
        """v0.9.3: все выделенные узлы карты (в порядке сцены)."""
        try:
            return [i for i in self.scene.selectedItems() if isinstance(i, ServerNode)]
        except RuntimeError:
            return []

    def _delete_selected_nodes(self):
        """v0.9.3: удалить ВСЕ выделенные узлы (каждый через guarded-путь)."""
        nodes = self.selected_nodes()
        if not nodes:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return False
        # одно подтверждение на всю группу
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Подтверждение",
            self.t("msg.confirm_delete_many").format(count=len(nodes))
            if self._i18n_available else f"Удалить серверы ({len(nodes)})?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        deleted = 0
        for node in list(nodes):
            if node.scene() is None:
                continue  # уже удалён вместе со своей стрелкой ранее в цикле
            if not self._ensure_worker_done(node.data.id):
                continue
            alias = node.data.alias
            arrows = [
                (a.source.data.id, a.target.data.id, a.label_text, a.connection_type)
                for a in self.scene.arrows()
                if a.source is node or a.target is node
            ]
            from modules.undo_commands import CmdAddRemoveNode
            self._push_command(CmdAddRemoveNode(self, self.scene, node.data, "remove", arrows))
            deleted += 1
            if self.log:
                self.log.info("Server deleted (multi)",
                              extra={"alias": alias, "host": node.data.host})
        if deleted:
            self.refresh_sidebar()
            self._sync_status_targets()
            self.statusBar().showMessage(
                self.t("status.servers_deleted_multi", count=deleted)
                if self._i18n_available else f"Deleted {deleted} servers")
            self._mark_dirty()  # ← unsaved changes
        return True

    def _connect_selected_nodes(self):
        """v0.9.3: создать связи между всеми парами выделенных узлов (полный граф).

        Каждый узел соединяется с каждым (без петель и дублей); тип связи —
        по умолчанию, метка пустая. Undo откатывает всё одной командой.
        """
        nodes = self.selected_nodes()
        if len(nodes) < 2:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("validation.min_servers"))
            return False
        ids = [n.data.id for n in nodes]
        created = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                src, tgt = ids[i], ids[j]
                if self.scene.has_connection(src, tgt):
                    continue
                arrow = self.scene.add_connection(src, tgt)
                if arrow is not None:
                    created.append((src, tgt))
        if not created:
            return False
        from modules.undo_commands import CmdConnectSelected
        self._push_command(CmdConnectSelected(self, self.scene, created))
        self._update_counts_label()
        self.statusBar().showMessage(
            self.t("status.connections_created_multi", count=len(created))
            if self._i18n_available else f"Created {len(created)} connections")
        self._mark_dirty()  # ← unsaved changes
        return True

    def _add_note_at_view_center(self):
        """Ctrl+Shift+N: заметка в центре видимой области карты."""
        self._add_note_at()

    def _copy_node_info(self, node: "ServerNode", what: str = "ip"):
        """Скопировать IP или hostname узла в буфер обмена (v0.7.3).

        AUDIT v0.7.2 (средняя #6): обратный DNS (gethostbyaddr) выполняется в отдельном
        потоке — при недоступном резолвере GUI-поток раньше замерзал на таймауте DNS.
        """
        if node is None:
            return

        def _copy(value: str, what_: str):
            QApplication.clipboard().setText(value)
            self.statusBar().showMessage(self.t("status.copied_to_clipboard", value=value))
            if self.log:
                self.log.info(f"Copied {what_} to clipboard", extra={"alias": node.data.alias})

        if what == "hostname":
            host = node.data.host

            class _ReverseDnsThread(QThread):
                """Обратный DNS вне GUI-потока (AUDIT v0.7.2, средняя #6)."""
                resolved = QtSignal(str)

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

            thread = _ReverseDnsThread(host)

            def _on_dns_done(name):
                if getattr(self, "_dns_thread", None) is thread:
                    self._dns_thread = None
                _copy(name, "hostname")

            thread.resolved.connect(_on_dns_done)
            self._dns_thread = thread  # держим ссылку — поток не должен стать orphan'ом
            thread.start()
            return

        # "ip" и прочие варианты: сетевых вызовов нет — синхронно (и так ожидает smoke-тест)
        _copy(node.data.ip.strip() or node.data.host, what)

    def _ping_node(self, node: "ServerNode"):
        """Ping узла в отдельном потоке без блокировки GUI (v0.7.3).

        Windows: `ping -n 3`, POSIX: `ping -c 3`. Результат — в статус-бар.
        """
        if node is None:
            return

        class _PingThread(QThread):
            finished_ping = QtSignal(bool, str)

            def __init__(self, host):
                super().__init__()
                self._host = host

            def run(self):
                try:
                    from i18n import t as _t
                except Exception:
                    def _t(key, **kw):
                        return key.format(**kw) if kw else key
                count_flag = "-n" if _platform_mod.system() == "Windows" else "-c"
                # AUDIT v0.9.5.5 (безопасность #4): -w/-W — миллисекунды на Windows,
                # секунды на Linux; таймаут 3 с в обоих случаях. На Linux "--" перед
                # хостом, чтобы хост вида "-x" не съелся как флаг.
                if _platform_mod.system() == "Windows":
                    cmd = ["ping", count_flag, "3", "-w", "3000", self._host]
                else:
                    cmd = ["ping", "-c", "3", "-W", "3", "--", self._host]
                try:
                    proc = _subprocess_mod.run(
                        cmd, capture_output=True, timeout=15,
                        creationflags=getattr(_subprocess_mod, "CREATE_NO_WINDOW", 0)
                        if _platform_mod.system() == "Windows" else 0)
                    ok = proc.returncode == 0
                    key = "status.ping_ok" if ok else "status.ping_failed"
                    msg = _t(key, host=self._host)
                    out = proc.stdout.decode(errors="replace")[-400:] if not ok else ""
                    self.finished_ping.emit(ok, msg + ("\n" + out if out else ""))
                except Exception as exc:
                    self.finished_ping.emit(False, _t("status.ping_failed", host=self._host)
                                            + f" ({exc})")

        # AUDIT v0.7.2 (средняя #8): не затираем ещё работающий ping — повторный запрос
        # игнорируем (раньше ссылка перезаписывалась, а старый поток оставался orphan'ом).
        if self._ping_thread is not None and self._ping_thread.isRunning():
            self.statusBar().showMessage(self.t("status.ping_running", host=node.data.host))
            return

        ping_thread = _PingThread(node.data.host)

        def _on_ping_done(ok, text):
            if ok:
                self.statusBar().showMessage(text)
            else:
                QMessageBox.information(self, self.t("msg.info_title"), text)
            # Чистим ссылку только на СВОЙ поток: запоздалый старый ping не должен
            # обнулять ссылку уже запущенного нового (AUDIT v0.7.2, средняя #8).
            if getattr(self, "_ping_thread", None) is ping_thread:
                self._ping_thread = None

        ping_thread.finished_ping.connect(_on_ping_done)
        self._ping_thread = ping_thread
        ping_thread.start()
        self.statusBar().showMessage(self.t("status.ping_running", host=node.data.host))

    def _edit_connection(self, arrow):
        """Диалог изменения метки и типа связи (v0.7.3)."""
        if arrow is None:
            return
        try:
            from dialogs.connection_dialog import EditConnectionDialog
            dlg = EditConnectionDialog(arrow, self)
            if dlg.exec() == QDialog.Accepted:
                label, ctype = dlg.get_connection()
                # v0.8.3: правка связи (метка/тип) — undo-команда
                from modules.undo_commands import CmdEditConnection
                self._push_command(CmdEditConnection(
                    self, arrow, arrow.label_text, arrow.connection_type, label, ctype))
                self.statusBar().showMessage(self.t("status.connection_updated"))
                self._mark_dirty()  # ← unsaved changes
        except Exception as e:
            if self.log:
                self.log.exception("Error editing connection")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.update_failed", error=str(e)))

    def _remove_connection(self, arrow) -> bool:
        """Удалить связь с подтверждением (v0.7.3). Возвращает True при удалении."""
        if arrow is None:
            return False
        src_alias = arrow.source.data.alias
        tgt_alias = arrow.target.data.alias
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Подтверждение",
            self.t("msg.confirm_delete_connection").format(src=src_alias, tgt=tgt_alias)
            if self._i18n_available else f"Удалить связь '{src_alias}' → '{tgt_alias}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return False
        # v0.8.3: удаление связи — undo-команда
        from modules.undo_commands import CmdAddRemoveConnection
        src_id = arrow.source.data.id
        tgt_id = arrow.target.data.id
        lbl = arrow.label_text
        ctype = arrow.connection_type
        self._push_command(CmdAddRemoveConnection(self, self.scene, src_id, tgt_id,
                                                  lbl, ctype, "remove"))
        self.statusBar().showMessage(self.t("status.connection_deleted"))
        self._update_counts_label()  # UI polish: счётчик связей в статус-баре
        self._mark_dirty()  # ← unsaved changes
        if self.log:
            self.log.info("Connection deleted",
                          extra={"source": src_alias, "target": tgt_alias})
        return True

    def _delete_selected(self):
        node = self.scene.get_selected_node()
        if node:
            self._remove_node_guarded(node)
            return
        # v0.8.1: выделенная группа — серверы остаются на карте, удаляется только рамка
        group = self.scene.get_selected_group()
        if group is not None:
            self._remove_group(group)

    def _ensure_worker_done(self, server_id: str) -> bool:
        """Патч v0.6.x: дождаться завершения SSHWorker перед удалением узла.

        Если поток всё ещё выполняется и не успевает завершиться за таймаут —
        показать предупреждение и отменить удаление (иначе success/error могли бы
        прилететь в уничтоженный диалог / данные удалённого узла).
        """
        try:
            from modules.ssh_worker import wait_for_worker as _wait_worker
            if not _wait_worker(server_id, 5000):
                QMessageBox.warning(self, self.t("msg.error_title"), self.t("msg.worker_busy"))
                return False
        except Exception:
            pass  # реестр недоступен — не блокируем удаление из-за этого
        return True

    def _remove_node_guarded(self, node: "ServerNode") -> bool:
        """Единый путь удаления узла: подтверждение → guard SSHWorker → remove.

        Используется кнопкой сайдбара, клавишей Delete (MapView) и контекстным
        меню узла (v0.7.3). Возвращает True, если удаление произошло.
        """
        reply = QMessageBox.question(
            self, 
            self.t("dialog.confirm_delete") if self._i18n_available else "Подтверждение",
            f"{self.t('msg.confirm_delete').format(alias=node.data.alias)}" if self._i18n_available else f"Удалить сервер '{node.data.alias}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        if not self._ensure_worker_done(node.data.id):
            return False
        alias = node.data.alias
        host = node.data.host
        # v0.8.3: захват стрелок узла ДО удаления — undo восстановит их вместе с узлом
        arrows = [
            (a.source.data.id, a.target.data.id, a.label_text, a.connection_type)
            for a in self.scene.arrows()
            if a.source is node or a.target is node
        ]
        from modules.undo_commands import CmdAddRemoveNode
        self._push_command(CmdAddRemoveNode(self, self.scene, node.data, "remove", arrows))
        self.refresh_sidebar()
        self._sync_status_targets()  # v0.7.1: узла больше нет — убрать из плана проверок
        if self.log:
            self.log.info("Server deleted", extra={"alias": alias, "host": host})
        self.statusBar().showMessage(self.t("status.server_deleted", alias=alias))
        self._mark_dirty()  # ← unsaved changes
        return True

    # ── v0.7.2: Sticky Notes (заметки на карте) ───────────────

    def _connect_note_signals(self, note):
        """Подключить сигналы заметки к dirty-маркеру и undo (v0.8.3: правка текста)."""
        try:
            note.textEdited.connect(lambda *_a: self._on_note_text_edited(note))
            note.moved.connect(lambda *_a: self._mark_dirty())
        except Exception:
            pass  # повторное подключение для той же заметки — не критично

    def _on_note_text_edited(self, note):
        """v0.8.3: правка текста — перезапуск дебаунса; по тишине → команда undo."""
        self._mark_dirty()
        try:
            committed = self._note_committed.get(note.note_id)
            if committed is not None and note.text() == committed:
                self._note_edit_pending = None
                return  # текст совпадает с уже закоммиченным (undo/redo вернул) — команды не надо
        except RuntimeError:
            return
        if not self._note_edit_pending or self._note_edit_pending[0] is not note:
            # новая сессия правки этой заметки — фиксируем стартовый текст
            try:
                start = self._note_committed.get(note.note_id, note.text())
            except RuntimeError:
                return
            self._note_edit_pending = (note, start)
        self._note_edit_timer.start()

    def _add_note_at(self, scene_pos=None) -> None:
        """Создать заметку в точке сцены (центр — под курсором)."""
        if scene_pos is not None:
            x = float(scene_pos.x()) - 120.0   # ~половина ширины по умолчанию
            y = float(scene_pos.y()) - 80.0    # ~половина высоты по умолчанию
        else:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            x, y = float(center.x()) - 120.0, float(center.y()) - 80.0
        note = self.scene.add_note(x=x, y=y)
        # v0.8.3: создание заметки — undo-команда; сама заметка уже добавлена выше
        # (add_note вернул объект), но для undo её нужно удалить/восстановить командой.
        from modules.undo_commands import CmdAddRemoveNote, CmdEditTextNote
        raw = {"id": note.note_id, "text": "", "x": float(note.pos().x()),
               "y": float(note.pos().y()),
               "width": float(note.rect().width()), "height": float(note.rect().height())}
        self._note_committed[note.note_id] = ""
        self._push_command(CmdAddRemoveNote(self, self.scene, raw, "add"))
        self._attach_note(note)
        if self.log:
            self.log.info("Note added", extra={"id": note.note_id})
        self.statusBar().showMessage(self.t("status.note_added"))
        self._mark_dirty()

    def _remove_note(self, note) -> bool:
        """Удалить заметку (лёгкий объект — без диалога подтверждения)."""
        note_id = getattr(note, "note_id", None)
        if not note_id or self.scene.get_note_by_id(note_id) is None:
            return False
        from modules.undo_commands import CmdAddRemoveNote
        try:
            raw = note.to_dict()
        except RuntimeError:
            return False
        self._note_edit_pending = None  # незакоммиченная правка уходит вместе с командой удаления
        self._push_command(CmdAddRemoveNote(self, self.scene, raw, "remove"))
        if self.log:
            self.log.info("Note deleted", extra={"id": note_id})
        self.statusBar().showMessage(self.t("status.note_deleted"))
        self._mark_dirty()
        return True

    # ── v0.8.1: Группировка узлов (кластеры/папки на карте) ─────

    def _commit_group_move(self, group, old_pos, new_pos):
        """v0.8.3-audit (#6): завершён жест перемещения группы → CmdMoveGroup."""
        from modules.undo_commands import CmdMoveGroup
        self._push_command(CmdMoveGroup(self, group, old_pos, new_pos))
        self._mark_dirty()

    def _commit_group_resize(self, group, w0, h0, w1, h1):
        """v0.8.3-audit (#6): завершён resize группы → CmdResizeGroup."""
        from modules.undo_commands import CmdResizeGroup
        self._push_command(CmdResizeGroup(self, group, (w0, h0), (w1, h1)))
        self._mark_dirty()

    def _connect_group_signals(self, group):
        """Подключить сигналы группы: dirty-маркер + undo-команды
        (v0.8.3-audit #6: перемещение/resize/переименование входят в стек);
        renameRequested — к диалогу переименования."""
        try:
            for sig in (group.moved, group.resized, group.titleChanged,
                        group.membershipChanged):
                sig.connect(lambda *_a: self._mark_dirty())
            # Undo-коммиты завершённых жестов (паттерн node_drag_committed)
            group.moveCommitted.connect(
                lambda op, np, g=group: self._commit_group_move(g, op, np))
            group.resizeCommitted.connect(
                lambda w0, h0, w1, h1, g=group: self._commit_group_resize(
                    g, w0, h0, w1, h1))
            # Двойной клик по заголовку → QInputDialog (замыкание g — группа-источник)
            group.renameRequested.connect(
                lambda *_a, g=group: self._rename_group(g))
        except Exception:  # noqa: BLE001 — повторное подключение не критично
            pass

    # ── v0.9.1: экспорт карты в изображение + фон-изображение ────

    def _connect_background_signals(self, bg):
        """Подключить сигналы фона к dirty-маркеру (undo — НЕ нужен:
        геометрия фона хранится в JSON, но в стек undo не входит)."""
        try:
            bg.moved.connect(lambda *_a: self._mark_dirty())
            bg.resized.connect(lambda *_a: self._mark_dirty())
        except Exception:  # noqa: BLE001
            pass

    def _export_map_image(self):
        """Экспорт карты в PNG/JPEG (v0.9.1 #1): рендер всей сцены в файл."""
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_png"), "",
            "PNG Images (*.png);;JPEG Images (*.jpg)")
        if not path:
            return
        # Расширение по выбранному фильтру, если пользователь его не дописал
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            ext = ".jpg" if "JPEG" in (selected_filter or "") else ".png"
            path += ext
        try:
            pixmap = self.scene.render_to_pixmap(scale=2.0)
            if not pixmap.save(path):
                raise OSError("QPixmap.save returned False")
            self.statusBar().showMessage(self.t("status.export_ok"))
            if self.log:
                self.log.info("Map exported", extra={"file": path})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_drawio(self):
        """Экспорт карты в draw.io (.drawio) — v0.9.5 #1–#4."""
        from storage.export_drawio import export_scene_to_drawio
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_drawio"), "",
            "draw.io Diagrams (*.drawio)")
        if not path:
            return
        if not path.lower().endswith(".drawio"):
            path += ".drawio"
        try:
            cells = export_scene_to_drawio(self.scene, path)
            self.statusBar().showMessage(self.t("status.export_drawio_ok"))
            if self.log:
                self.log.info(
                    "Map exported to drawio", extra={"file": path, "cells": cells})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _set_background_image(self):
        """Выбрать и установить фоновое изображение карты (v0.9.1 #2/#3)."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("view.set_background"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        try:
            bg = self.scene.set_background_image(path)
        except Exception as e:  # noqa: BLE001 — битое/нечитаемое изображение
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.background_failed", error=str(e)))
            return
        # Фон по умолчанию ставим в видимую область карты
        try:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            w, h = bg.size()
            bg.setPos(center.x() - w / 2, center.y() - h / 2)
        except Exception:  # noqa: BLE001 — вид недоступен (headless) — оставляем (0,0)
            pass
        self._connect_background_signals(bg)
        self._mark_dirty()
        self.statusBar().showMessage(self.t("status.background_set"))
        if self.log:
            self.log.info("Background image set", extra={"file": path})

    def _remove_background_image(self):
        """Убрать фоновое изображение карты (v0.9.1)."""
        if self.scene.background() is None:
            return
        self.scene.remove_background()
        self._mark_dirty()
        self.statusBar().showMessage(self.t("status.background_removed"))

    def _add_group_at(self, at_scene_pos=None) -> None:
        """Создать группу (рамка + заголовок), центрируя её под точкой клика.

        `at_scene_pos` опционален: QAction.triggered шлёт первым аргументом bool
        `checked` — позицию принимаем только если это действительно точка сцены
        (тот же фикс, что у _add_server; regression_v081 #1). Узлы, уже лежащие под
        рамкой, становятся членами автоматически (MapScene.resync_group_members).
        """
        try:
            if _is_scene_point(at_scene_pos):
                center = at_scene_pos
            else:
                center = self.view.mapToScene(self.view.viewport().rect().center())

            base_name = self.t("group.default_name")
            used = {g.name for g in self.scene.groups()}
            name, n = base_name, 2
            while name in used:  # не повторяем имена существующих групп
                name = f"{base_name} {n}"
                n += 1

            grp = self.scene.add_group(
                name=name,
                x=float(center.x()) - NodeGroup.DEFAULT_W / 2,
                y=float(center.y()) - NodeGroup.DEFAULT_H / 2)
            self._connect_group_signals(grp)
            if self.log:
                self.log.info("Group added", extra={"id": grp.group_id, "group_name": name})
            self.statusBar().showMessage(self.t("status.group_added"))
            self._mark_dirty()
        except Exception as e:
            if self.log:
                self.log.exception("Error adding group")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.add_failed", error=str(e)))

    def _rename_group(self, group) -> None:
        """Переименовать группу (двойной клик по заголовку / контекстное меню)."""
        if group is None:
            return
        try:
            from PySide6.QtWidgets import QInputDialog, QLineEdit
            text, ok = QInputDialog.getText(
                self,
                self.t("dialog.rename_group"),
                f"{self.t('group.name_label')} ",
                QLineEdit.Normal,
                group.name)
            if ok and str(text).strip():
                new_name = str(text).strip()
                if new_name != group.name:
                    # v0.8.3-audit (#6): переименование — через undo-команду
                    from modules.undo_commands import CmdEditGroupName
                    self._push_command(
                        CmdEditGroupName(self, group, group.name, new_name))
                    self._mark_dirty()
                self.statusBar().showMessage(self.t("status.group_renamed"))
        except Exception as e:
            if self.log:
                self.log.exception(f"Error renaming group {group.name}")

    def _remove_group(self, group) -> bool:
        """Удалить группу. Серверы-члены остаются на карте в тех же позициях —
        группа это контейнер-подпись (лёгкий объект, без диалога подтверждения)."""
        gid = getattr(group, "group_id", None)
        if not gid or self.scene.get_group_by_id(gid) is None:
            return False
        name = group.name
        self.scene.remove_group(group)
        if self.log:
            self.log.info("Group deleted", extra={"id": gid, "group_name": name})
        self.statusBar().showMessage(self.t("status.group_deleted"))
        self._mark_dirty()
        return True

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        node_id = item.data(0, Qt.UserRole)
        if node_id and self.scene.has_node(node_id):
            self._select_node(self.scene.get_node(node_id), center=False)

    def _on_tree_item_double_click(self, item: QTreeWidgetItem, column: int):
        node_id = item.data(0, Qt.UserRole)
        if node_id and self.scene.has_node(node_id):
            self._select_node(self.scene.get_node(node_id), center=True)

    def refresh_sidebar(self):
        self.tree.clear()
        query = self.search_edit.text().strip().lower() if hasattr(self, 'search_edit') else ""
        # v0.9.4: активный тег-фильтр ("" = выключен)
        active_tag = self._active_tag_filter()
        for node in self.scene.nodes():
            haystack = " ".join([
                node.data.alias,
                node.data.host,
                node.data.ip,
                node.data.comment,
                # v0.9.4: поиск ищет и по тегам
                " ".join(getattr(node.data, "tags", None) or []),
            ]).lower()
            if query and query not in haystack:
                continue
            if active_tag and active_tag not in (getattr(node.data, "tags", None) or []):
                continue

            item = QTreeWidgetItem()
            item.setText(0, f"{node.data.alias}  ({node.data.host})")
            item.setData(0, Qt.UserRole, node.data.id)
            # Ревью-фикс v0.8.0 (#3): цветной маркер статуса узла (online/warn/offline/не проверен)
            self._apply_status_marker(item, node.status, node.data.host or "")
            # v0.9.4: подпись тегов серым в конце строки
            tags = getattr(node.data, "tags", None) or []
            if tags:
                item.setText(0, item.text(0) + f"  [{', '.join(tags[:3])}]")
                item.setForeground(0, self.palette().windowText())
            self.tree.addTopLevelItem(item)

        self._sync_tag_filter_items()
        self._apply_map_tag_dimming()
        self._sync_selection_state()
        self._update_counts_label()  # UI polish: счётчики в статус-баре следят за составом

    # ── v0.9.4: фильтр по тегам (сайдбар + затемнение на карте) ──

    def _active_tag_filter(self) -> str:
        """Выбранный в комбобоксе тег или \"\" («Все теги»)."""
        combo = getattr(self, "tag_filter", None)
        if combo is None or not hasattr(combo, "currentData"):
            return ""
        data = combo.currentData()
        return str(data) if data else ""

    def _on_tag_filter_changed(self, *_a):
        """Смена тега в фильтре → перерисовать дерево и пересчитать затемнение."""
        if hasattr(self, "tree"):
            self.refresh_sidebar()

    def _sync_tag_filter_items(self):
        """Перестроить список уникальных тегов в комбобоксе, сохраняя выбор.

        Вызовется из refresh_sidebar — сигнал currentIndexChanged при этом не должен
        зациклить пересборку (блокируем сигналы на время заполнения).
        """
        combo = getattr(self, "tag_filter", None)
        if combo is None:
            return
        all_tags = sorted({
            t.strip()
            for n in self.scene.nodes()
            for t in (getattr(n.data, "tags", None) or [])
            if t and t.strip()
        }, key=str.lower)
        current = self._active_tag_filter()
        combo.blockSignals(True)
        try:
            from i18n import t as __t  # noqa: PLC0415 — ленивый импорт как в остальном UI
            try:
                all_label = __t("filter.all_tags")
            except Exception:
                all_label = "All tags"
            combo.clear()
            combo.addItem(all_label, "")
            for tag in all_tags:
                color = ServerNode.tag_color(tag).name()
                combo.addItem(f"● {tag}", tag)
                combo.setItemData(combo.count() - 1, QColor(color), Qt.DecorationRole)
            idx = combo.findData(current) if current else 0
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        except RuntimeError:
            pass  # Qt teardown
        finally:
            combo.blockSignals(False)

    def _apply_map_tag_dimming(self):
        """Затемнить карточки узлов, не подходящих под активный тег-фильтр.

        Узлы с совпадающим (или любым, если фильтр пуст) тегом — полная яркость.
        Стрелки не трогаем: связи между затемнёнными узлами читаются по контексту.
        """
        active = self._active_tag_filter()
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return
        for node in nodes:
            tags = getattr(node.data, "tags", None) or []
            matched = (not active) or active in tags
            try:
                node.set_dimmed(not matched)
            except (AttributeError, RuntimeError):
                pass

    # ── Ревью-фикс v0.8.0 (#3): маркеры статусов узлов в дереве сайдбара ──

    def _status_dot_icon(self, status: str) -> QIcon:
        """Цветная точка для строки дерева — та же палитра, что у точек на карточках."""
        icon = self._status_dot_icons.get(status)
        if icon is not None:
            return icon
        color = ServerNode.STATUS_COLORS.get(status, ServerNode.COLOR_DOT_IDLE)
        pm = QPixmap(16, 16)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(3, 3, 10, 10)
        painter.end()
        icon = QIcon(pm)
        self._status_dot_icons[status] = icon
        return icon

    def _apply_status_marker(self, item: QTreeWidgetItem, status: str, host: str = "") -> None:
        """Поставить на строку дерева точку статуса + tooltip (i18n node.status.*)."""
        item.setIcon(0, self._status_dot_icon(status))
        if status and status in ServerNode.STATUS_COLORS:
            try:
                tip = self.t(f"node.status.{status}", host=host or "")
            except Exception:
                tip = f"{status}: {host}"
            # i18n вернул «ключ» (нет перевода) — показываем статус без ключа
            item.setToolTip(0, tip if not tip.startswith("[") else f"{status}: {host}")
        else:
            item.setToolTip(0, "")  # не проверялся — подсказки нет

    def _update_sidebar_status_marker(self, server_id: str) -> None:
        """Обновить маркер строки на месте (без полного пересбора дерева)."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # узла уже нет — статус никому не нужен
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == server_id:
                self._apply_status_marker(item, node.status, node.data.host or "")
                return
        # Строки нет (например, отфильтрована поиском) — следующий refresh_sidebar
        # построит её с актуальным маркером.

    def _center_view(self):
        """UI polish: центрировать по содержимому карты, а не по началу координат.

        Раньше centerOn(0, 0) — при узлах в отрицательных координатах взгляд уходил
        в пустой угол сцены (баг из ревью v0.8).
        """
        rect = self.view.content_bounding_rect()
        if rect is None or rect.isEmpty():
            self.view.centerOn(0, 0)
            return
        self.view.centerOn(rect.center())

    def _fit_to_content(self):
        """UI polish: «Вписать карту» — все узлы и заметки в видимой области."""
        if not self.view.fit_to_content():
            self.statusBar().showMessage(self.t("status.fit_nothing"))

    def _on_zoom_changed(self, zoom: float):
        """UI polish: процент зума в статус-баре (сигнал MapView.zoomChanged)."""
        try:
            self.zoom_label.setText(f"{int(round(zoom * 100))}%")
        except RuntimeError:
            pass  # Qt teardown — виджет статус-бара уже уничтожен

    def _update_counts_label(self):
        """UI polish: постоянные счётчики «серверы · связи · online/warn/offline»."""
        try:
            nodes = list(self.scene.nodes())
            conns = self.scene.arrow_count()
        except (AttributeError, RuntimeError):
            return  # сцена ещё не создана / уже уничтожена
        statuses = [getattr(n, "status", "") for n in nodes]
        self.counts_label.setText(
            self.t("status.counts",
                   servers=len(nodes), connections=conns,
                   online=statuses.count("online"),
                   warn=statuses.count("warn"),
                   offline=statuses.count("offline")))

    def _reset_zoom(self):
        # AUDIT v0.7.2 (низкая #19): публичный метод MapView вместо лезть в view._zoom
        self.view.reset_zoom()

    def _open_profile_manager(self):
        """Open the profile manager dialog."""
        try:
            from ..dialogs.profile_manager_dialog import ProfileManagerDialog
        except ImportError:
            from dialogs.profile_manager_dialog import ProfileManagerDialog

        dlg = ProfileManagerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.statusBar().showMessage(self.t("status.profile_updated"))
            if self.log:
                self.log.info("Profile manager closed (saved)")

    def _open_log_file(self):
        """Open the log file in default text editor."""
        try:
            from modules.logger import get_log_file_path as _get
            path = _get()
            # Open with default application for the OS
            import os, subprocess
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, self.t("dialog.open_logs"), f"Failed to open:{e}")

    # ─── Serialization ───────────────────────────

    def _new_project(self):
        # Заголовок собирается единым методом — раньше сюда дописывался
        # «[Новый проект]» к уже полному заголовку и он нарастал с каждым разом.
        self.scene.clear_all()
        self._project_file = None
        self._dirty = False
        self._reset_undo_stack()  # v0.8.3: новый проект — чистый undo-стек
        self.refresh_sidebar()
        self._sync_status_targets()  # v0.7.1: сцена пуста — план проверок пуст
        self._update_window_title()
        if self.log:
            self.log.info("New project created")

    def _import_project_raw(self, raw: dict):
        """Импортировать уже загруженный JSON-проект в сцену.

        Вынесен из _open_project() для тестов и backward-compat: файлы v0.6
        не имеют поля "type" у связей — подставляется тип по умолчанию (SSH).
        """
        self.scene.clear_all()

        # v0.8.1: группы ДО узлов — членство геометрическое и пересчитывается в
        # MapScene.resync_group_members при каждом add_server, поэтому порядок не важен
        # для корректности; создаём раньше ещё и ради z-порядка (файловый = исходный).
        # Backward-compat: проекты до v0.8.1 не имеют ключа "groups" → пусто.
        for raw_g in raw.get('groups', []):
            if not isinstance(raw_g, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                grp = self.scene.add_group(
                    name=str(raw_g.get("name") or ""),
                    x=float(raw_g.get("x") or 0.0),
                    y=float(raw_g.get("y") or 0.0),
                    width=float(raw_g.get("width") or NodeGroup.DEFAULT_W),
                    height=float(raw_g.get("height") or NodeGroup.DEFAULT_H),
                    group_id=str(raw_g.get("id") or "")[:8] or None,
                )
            except (TypeError, ValueError):
                continue
            self._connect_group_signals(grp)

        for s in raw.get('servers', []):
            # v0.9.3 fix: per-record try/except, как у notes/groups выше и как
            # обещано в доках — одна битая запись не роняет загрузку всего проекта.
            if not isinstance(s, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                # Единый путь десериализации: сохраняет key_path и корректно
                # игнорирует лишние ключи (AUDIT.md, средняя #5).
                server_data = server_data_from_dict(s)
            except (TypeError, ValueError, KeyError) as e:
                if self.log:
                    self.log.warning("Skipping broken server record on load", extra={"error": str(e)})
                continue
            self.scene.add_server(server_data)

        for c in raw.get('connections', []):
            # v0.9.3 fix: та же защита, что у servers — отсутствие source_id/target_id
            # в одной записи не должно убивать весь проект.
            if not isinstance(c, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                ctype = c.get("type", DEFAULT_CONNECTION_TYPE)  # v0.6: нет поля type → SSH
                self.scene.add_connection(
                    c["source_id"], c["target_id"],
                    c.get("label", ""), ctype,
                )
            except KeyError as e:
                if self.log:
                    self.log.warning("Skipping broken connection record on load", extra={"error": str(e)})
                continue

        # v0.7.1: после загрузки проекта узлы попадают в план периодических
        # проверок; немедленный раунд запускает _open_project (user path), а не
        # здесь — чтобы headless-тесты без event loop не плодили фоновые потоки.
        self._sync_status_targets()

        # v0.7.2: заметки из файла. Backward-compat: проекты до v0.7.2 не имеют
        # ключа "notes" — raw.get(...) даёт пустой список, всё остаётся как было.
        for raw_note in raw.get('notes', []):
            if not isinstance(raw_note, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                note_id = str(raw_note.get("id") or "")[:8] or None
                note = self.scene.add_note(
                    text=str(raw_note.get("text") or ""),
                    x=float(raw_note.get("x") or 0.0),
                    y=float(raw_note.get("y") or 0.0),
                    width=float(raw_note.get("width") or 240.0),
                    height=float(raw_note.get("height") or 160.0),
                    note_id=note_id,
                )
            except (TypeError, ValueError):
                continue
            self._connect_note_signals(note)

        # v0.9.1: фон из файла. Backward-compat: проекты до v0.9.1 не имеют ключа
        # "background" → raw.get(...) = None, карта открывается без фона.
        # Отсутствующий файл изображения тоже не мешает загрузке (warning в лог).
        try:
            from graphics.background_image import BackgroundImage as _BgCls
        except ImportError:
            from background_image import BackgroundImage as _BgCls
        bg_raw = raw.get('background')
        if isinstance(bg_raw, dict):
            bg = _BgCls.try_from_dict(bg_raw)
            if bg is not None:
                self.scene.addItem(bg)
                self.scene._background = bg
                self._connect_background_signals(bg)
            elif self.log:
                self.log.warning("Background image missing on disk, skipped", extra={
                    "path": str(bg_raw.get("path") or "")})

        # v0.8.1: страховочный пересчёт членства групп после полной сборки сцены
        # (обычно состав уже корректен — resync шёл при каждом add_server/add_group).
        if self.scene.groups():
            self.scene.resync_group_members()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.open"), "", "JSON Files (*.json *.sshmap)")
        if not path:
            return
        try:
            from storage.project import load_project as _load_project
            raw = _load_project(path)

            server_count = len(raw.get('servers', []))
            conn_count = len(raw.get('connections', []))

            self._import_project_raw(raw)

            # UI polish: восстановить сохранённое состояние вида (zoom + center).
            # _do_save() эти поля в JSON пишет, а старый код при открытии их игнорировал.
            try:
                self.view.set_zoom_and_center(
                    raw.get("zoom"), raw.get("center_x", 0.0), raw.get("center_y", 0.0))
            except Exception as e:  # noqa: BLE001 — битые значения не мешают открытию
                if self.log:
                    self.log.warning(f"Failed to restore view state: {e}")

            # v0.7.1: сразу после загрузки — немедленный раунд проверок статусов
            checker = getattr(self, "_status_checker", None)
            if checker is not None and not checker.is_busy:
                try:
                    checker.start_round()
                except Exception as e:
                    if self.log:
                        self.log.warning(f"StatusChecker round failed: {e}")

            # Load passwords from keyring if available
            try:
                from services.credential_manager import get_credential_manager as _get_cm
                cm = _get_cm()
                for node in list(self.scene.nodes()):
                    sid = getattr(node.data, 'id', '')
                    cached_pw = cm.load_password(sid)
                    if cached_pw:
                        node.data.password = cached_pw
            except Exception as e:
                if self.log:
                    self.log.warning(f"Failed to load passwords from keyring: {e}")
                QMessageBox.warning(
                    self, self.t("msg.error_title"),
                    self.t("msg.passwords_from_keyring_load_failed"))

            self.refresh_sidebar()
            self._project_file = path
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: загрузка — новая точка отсчёта undo
            self._update_window_title()
            self.statusBar().showMessage(self.t("status.project_loaded"))

            if self.log:
                self.log.info("Project loaded", extra={"file": path, "servers": server_count})
        except Exception as e:
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.load_failed", error=str(e)))

    def _save_project(self) -> bool:
        """Сохранить текущий проект. Возвращает True, если сохранение удалось."""
        if self._project_file:
            return self._do_save(self._project_file)
        return self._save_project_as()

    def _save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.save_as"), "", "JSON Files (*.json *.sshmap)")
        if not path:
            return False  # пользователь отменил — не ошибка, но и не сохранение
        saved = self._do_save(path)
        if saved:
            self._project_file = path
        return saved

    def _do_save(self, path: str) -> bool:
        """Сохранить проект в файл. Пароли уходят в keyring (JSON — только без них)."""
        from storage.project import save_project as _save_project_fn
        try:
            center = self.view.mapToScene(
                self.view.viewport().rect().center())

            server_count = self.scene.node_count()
            arrow_count = self.scene.arrow_count()

            # Save non-empty passwords to keyring BEFORE clearing.
            # Результат проверяем: если keyring недоступен, пароль НЕ сбрасываем —
            # иначе он тихо сгорал (AUDIT.md, средняя #12).
            from services.credential_manager import get_credential_manager as _get_cm
            cm = _get_cm()
            unsaved_aliases = []
            for node in list(self.scene.nodes()):
                pw = getattr(node.data, 'password', '')
                sid = getattr(node.data, 'id', '')
                if pw:  # only save non-empty passwords to keyring
                    saved_to_store = cm.is_available and bool(cm.save_password(sid, pw))
                    if saved_to_store:
                        node.data.password = ""  # clear in memory — пароль в хранилище
                    else:
                        unsaved_aliases.append(getattr(node.data, 'alias', sid))

            _save_project_fn(
                path=path,
                nodes={n.data.id: n for n in self.scene.nodes()},
                arrows=self.scene.arrows(),
                zoom=self.view.zoom,  # AUDIT v0.7.2 (низкая #19): публичное свойство
                center_x=center.x(),
                center_y=center.y(),
                notes=self.scene.notes(),  # v0.7.2: массив заметок (публичный итератор)
                groups=self.scene.groups(),  # v0.8.1: массив групп (кластеры)
                background=self.scene.background(),  # v0.9.1: фон-изображение
            )

            # Сброс маркера несохранённых изменений (AUDIT.md, средняя #7)
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: сохранение — новая точка отсчёта undo
            self._update_window_title()

            if unsaved_aliases:
                QMessageBox.warning(
                    self, self.t("msg.error_title"),
                    "\n".join(self.t("msg.credentials_save_failed", alias=a) for a in unsaved_aliases))

            self.statusBar().showMessage(self.t("status.project_saved"))

            if self.log:
                self.log.info("Project saved", extra={
                    "file": path,
                    "servers": server_count,
                    "connections": arrow_count,
                })
            return True
        except Exception as e:
            # Restore passwords from keyring on failure so they're not lost
            try:
                from services.credential_manager import get_credential_manager as _get_cm2
                cm = _get_cm2()
                for node in list(self.scene.nodes()):
                    sid = getattr(node.data, 'id', '')
                    cached_pw = cm.load_password(sid)
                    if cached_pw:
                        node.data.password = cached_pw
            except Exception:
                pass

            if self.log:
                self.log.exception(f"Failed to save project {path}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.save_failed", error=str(e)))
            return False

