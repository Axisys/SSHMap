import os
import sys
import copy
from typing import Optional, List

try:
    from ..graphics.map_scene import MapScene
    from ..graphics.map_view import MapView
    from ..graphics.server_node import ServerNode
    from ..graphics.node_group import NodeGroup  # v0.8.1: группировка узлов (кластеры/папки)
except ImportError:
    from graphics.map_scene import MapScene
    from graphics.map_view import MapView
    from graphics.server_node import ServerNode
    from graphics.node_group import NodeGroup  # v0.8.1

try:
    from ..dialogs.add_server_dialog import AddServerDialog
    from ..dialogs.connection_dialog import ConnectionDialog
    from ..dialogs.ssh_connect_dialog import SSHConnectDialog
except ImportError:
    from dialogs.add_server_dialog import AddServerDialog
    from dialogs.connection_dialog import ConnectionDialog
    from dialogs.ssh_connect_dialog import SSHConnectDialog

# v1.1.4: AddServerDialog/ConnectionDialog/SSHConnectDialog/SSHTerminalWindow/_ext_term —
# ТОЧКИ ПОДМЕНЫ В ТЕСТАХ (MW.<имя> = Fake): методы, перенесённые в миксины
# (NodeOpsMixin._add_server/_add_connection, SshMixin._run_ssh_connect/
# _spawn_terminal_window/_connect_ssh_external), берут их из ЭТОГО модуля в момент
# вызова (host_attr, см. ui/mixin_support.py) — поэтому импорты остаются здесь,
# даже если ядро их больше не использует напрямую (ConnectionDialog/SSHConnectDialog).

try:
    from ..modules.ssh_terminal import SSHTerminalWindow
except ImportError:
    from modules.ssh_terminal import SSHTerminalWindow

try:  # v0.8.2: внешний (системный) терминал (v1.1.4: использует SshMixin через host_attr)
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

try:  # v0.9.9.4: сайдбар-кластер (дерево, тег-фильтр, статус-маркеры, контекстное меню)
    from .sidebar import SidebarPanel
except ImportError:
    from sidebar import SidebarPanel

try:  # v1.1.2RC3 (AUDIT U2): размеры окон — saveGeometry()/saveState() в config.json
    from ..modules.window_geometry import (
        save_window_geometry, restore_window_geometry,
    )
except ImportError:
    from modules.window_geometry import (
        save_window_geometry, restore_window_geometry,
    )


from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QFont,      # v1.1.1: шрифт UI из конфига (QApplication.setFont)
    QMouseEvent,
    QUndoStack,  # v0.8.3: undo/redo
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter,
    QLabel, QTreeWidgetItem,  # QTreeWidgetItem — аннотации слотов дерева (v0.9.9.4: дерево в ui/sidebar.py)
    QToolBar, QMessageBox, QDialog, QFileDialog, QMenu,
    QApplication,
)

# v1.1.4 (ROADMAP): разрез на миксины — кластеры «проект I/O», «операции над
# узлами/связями» и «SSH/терминалы» вынесены в ui/main_window_*.py. MainWindow
# остаётся фасадом: публичный API, имена методов и точки вызова не изменились;
# миксины НЕ импортируют main_window (цикл) — только duck-typing по инстансу.
try:
    from .main_window_project_io import ProjectIOMixin
    from .main_window_node_ops import NodeOpsMixin, _is_scene_point
    from .main_window_ssh import SshMixin
except ImportError:  # flat-раскладка без пакета (паттерн остальных импортов выше)
    from main_window_project_io import ProjectIOMixin
    from main_window_node_ops import NodeOpsMixin, _is_scene_point
    from main_window_ssh import SshMixin


class MainWindow(ProjectIOMixin, NodeOpsMixin, SshMixin, QMainWindow):
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

        # v1.1.2RC3 (AUDIT U2): восстановление размера/состояния главного окна из
        # config.json (сохраняется в closeEvent). Ключа нет / битое значение →
        # дефолтный 1200×850 выше; геометрия не должна ронять старт.
        try:
            restore_window_geometry("ui_window_geometry_main", self)
        except Exception:  # noqa: BLE001
            pass

        self._project_file: Optional[str] = None
        self._dirty = False  # Флаг несохранённых изменений (маркер " [*]" в заголовке)
        # v1.2 (ROADMAP задача 4): реестр открытых СЕССИЙ терминала
        # (modules/terminal_page.TerminalSessionPage), а не окон — зелёная точка
        # узла гаснет только когда закрыты ВСЕ сессии узла, лимит «4 своих
        # терминала» (v1.1.1) считается по сессиям. Имя сохранено (v1.1.x API).
        self._terminal_windows: List = []
        # v0.9.4-fix: id узлов с активной SSH-сессией (для сброса индикатора)
        self._ssh_connected_nodes: set = set()
        self._ping_thread = None   # v0.7.3: ping-поток (AUDIT v0.7.2 #8: guard против затирания)
        self._dns_thread = None    # AUDIT v0.7.2 (#6): поток обратного DNS для copy-hostname
        # v1.1.2RC2 (N6): пакетный DNS-резолв импорта из TXT вне GUI-потока —
        # поток + контекст пачки (pending/path/skipped), дожидающийся resolved_map
        self._import_resolve_thread = None
        self._import_pending = None   # [entry, ...] строки файла, ожидающие добавления
        self._import_path = None      # путь исходного TXT-файла (лог/статус)
        self._import_skipped = 0      # счётчик пропущенных дубликатов
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

        # ── v1.1.1: сохранённые UI-опции при старте (шрифты, кнопки сайдбара,
        #    режим двойного клика) — те же методы, что применение по ОК в диалоге ──
        self._node_double_click_mode = "properties"  # дефолт до чтения конфига
        try:
            self._apply_ui_options_from_config()
        except Exception as e:
            if self.log:
                self.log.warning(f"Apply UI options at startup failed: {e}")

        # ── v0.7.1: фоновая проверка статусов узлов (online/warn/offline) ──
        # Пробы идут в отдельном потоке — GUI не блокируется.
        # v1.1 (ROADMAP задача 4): интервал/таймаут — из ~/.sshmap/config.json
        # (status_interval_sec / status_probe_timeout_sec; дефолты 30 c / 3.0 c =
        # поведение v1.0); на лету меняются из диалога настроек (_apply_settings_from_dialog).
        # v1.1.2 final: пробы внутри раунда параллельные (ThreadPoolExecutor),
        # потолок — status_max_parallel (дефолт 16); для больших карт (N > 50)
        # интервал удваивается (effective_interval_ms + подсказка в статус-баре).
        self._status_checker = None
        self._auto_interval_hinted = False  # v1.1.2 final: подсказка о большом интервале — один раз
        try:
            from services.status_checker import StatusChecker as _StatusChecker, \
                get_status_settings as _get_status_cfg
            _st_cfg = _get_status_cfg()
            self._status_checker = _StatusChecker(
                interval_ms=int(_st_cfg["interval_sec"]) * 1000,
                probe_timeout=float(_st_cfg["probe_timeout_sec"]),
                max_parallel=int(_st_cfg["max_parallel"]), parent=self)
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

        # ── v0.9.7: автосохранение (ROADMAP #1) ────────────────────────
        # QTimer по интервалу из ~/.sshmap/config.json (autosave_interval_sec,
        # дефолт 60 c; autosave_enabled — вкл/выкл). Тик пишет автосохранение
        # ТОЛЬКО при dirty и при установленном файле проекта (новый несохранённый
        # проект восстанавливать некому — см. _autosave_tick). Интервал живёт до
        # перезапуска; диалог настроек появится в v1.1 (ROADMAP).
        self._autosave_timer = QTimer(self)
        try:
            from storage.autosave import get_autosave_settings as _get_as
            _as_cfg = _get_as()
        except Exception:  # noqa: BLE001 — дефолты важнее, модуль опционален
            _as_cfg = {"enabled": True, "interval_sec": 60}
        self._autosave_enabled = bool(_as_cfg.get("enabled", True))
        self._autosave_timer.setInterval(int(_as_cfg.get("interval_sec", 60)) * 1000)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        if self._autosave_enabled:
            self._autosave_timer.start()

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
            return
        # v1.1.2 final (задача 3): большая карта (N > LARGE_MAP_THRESHOLD) —
        # интервал проверок удваивается (StatusChecker.effective_interval_ms);
        # одноразовая подсказка в статус-баре при пересечении порога вверх.
        try:
            if checker.is_large_map():
                if not getattr(self, "_auto_interval_hinted", False):
                    self._auto_interval_hinted = True
                    self.statusBar().showMessage(
                        self.t("status.auto_interval_hint", servers=checker.target_count), 8000)
            else:
                self._auto_interval_hinted = False  # порог снова ниже — можно подсказать заново
        except (AttributeError, RuntimeError):
            pass  # Qt teardown — статус-бар уже уничтожен

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
        # v0.9.7: восстановление из автосохранения/бэкапов имеет смысл только для
        # открытого файла проекта (методы сами гвардятся — это UX-подсказка).
        for act in (getattr(self, "act_restore_autosave", None),
                    getattr(self, "act_backups", None)):
            if act is not None:
                act.setEnabled(bool(self._project_file))

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
        # v0.9.9.4: строки сайдбара (кнопки, заголовок, плейсхолдер, «Все теги») —
        # реестр панели; retranslate через i18n-колбэк (регрессия на баг v0.9.2:
        # раньше эти строки не обновлялись при смене языка).
        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.retranslate()
            except RuntimeError:
                pass  # Qt teardown — панель уже уничтожена
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

        # Side panel — v0.9.9.4: сайдбар-кластер (кнопки, заголовок, поиск,
        # тег-фильтр, дерево с маркерами статусов, контекстное меню) вынесен в
        # ui/sidebar.py (SidebarPanel). MainWindow остаётся фасадом: self.tree /
        # self.tag_filter / self.search_edit / self.btn_* — ссылки на виджеты
        # панели; публичный API и все слоты окна не изменились.
        self.sidebar = SidebarPanel(
            translate_fn=self.t if self._i18n_available else None,
            actions={
                # Контекстное меню строки (ROADMAP v0.9.6): «сначала выделить,
                # потом действие» — как в исходных замыканиях _on_sidebar_context_menu.
                "ssh": lambda n: (self._select_node(n), self._connect_ssh_to_selected()),
                "external": lambda n: (self._select_node(n), self._connect_ssh_external(n)),
                "edit": lambda n: self._edit_node(n),
                "copy_ip": lambda n: self._copy_node_info(n, "ip"),
                "copy_hostname": lambda n: self._copy_node_info(n, "hostname"),
                "ping": lambda n: self._ping_node(n),
                "collect_info": lambda n: self._collect_node_info(n),
                "reveal": lambda n: self._reveal_node_on_map(n),
                "delete": lambda n: self._remove_node_guarded(n),
                # v1.0RC4: Быстрый запуск — подменю первым пунктом (выше SSH);
                # ключи опциональные (вне CONTEXT_MENU_ITEMS) — см. SidebarPanel.
                "ql_entry": lambda n, e: self._run_quick_launch_entry(n, e),
                "ql_configure": lambda n: self._open_quick_launch_dialog(n),
            },
            show_title=self._i18n_available,  # раньше метка создавалась только при i18n
        )

        # Фасадные ссылки на виджеты панели (публичный API MainWindow — тесты)
        self.tree = self.sidebar.tree
        self.tag_filter = self.sidebar.tag_filter
        self.search_edit = self.sidebar.search_edit
        self.btn_add = self.sidebar.btn_add
        self.btn_connect = self.sidebar.btn_connect
        self.btn_connect_ssh = self.sidebar.btn_connect_ssh
        self.btn_props = self.sidebar.btn_props
        self.btn_delete = self.sidebar.btn_delete
        self.btn_settings = self.sidebar.btn_settings  # v1.1: кнопка ⚙ «Настройки» (6-я)
        self._sidebar_title = self.sidebar.title_label  # None без i18n (как раньше)

        # События панели — слоты окна (те же, что до v0.9.9.4)
        self.search_edit.textChanged.connect(self.refresh_sidebar)
        self.tag_filter.currentIndexChanged.connect(self._on_tag_filter_changed)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_click)
        # v0.9.6: контекстное меню дерева серверов (ПКМ по строке сайдбара);
        # политику CustomContextMenu выставляет сама панель при конструировании.
        self.tree.customContextMenuRequested.connect(self._on_sidebar_context_menu)

        # Кнопки панели → слоты окна
        self.sidebar.add_server_clicked.connect(self._add_server)
        self.sidebar.add_connection_clicked.connect(self._add_connection)
        self.sidebar.connect_ssh_clicked.connect(self._connect_ssh_to_selected)
        self.sidebar.show_properties_clicked.connect(self._show_properties)
        self.sidebar.delete_selected_clicked.connect(self._delete_selected)
        # v1.1: кнопка ⚙ «Настройки» внизу сайдбара → диалог настроек (хаб)
        self.sidebar.settings_clicked.connect(self._open_settings_dialog)

        splitter.addWidget(self.sidebar)

        # Map canvas
        self.scene = MapScene()
        # v0.9.9.1: reentry-guard синхронизации выделения (вместо blockSignals — см. _select_node)
        self._selection_syncing = False
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

        # v0.9.8: поиск по карте (Ctrl+F) — плавающая строка поверх canvas
        self._setup_map_search()

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
        # v1.1.2RC3 (AUDIT U2): сохранить размер/состояние окна ДО всего — даже при
        # отмене закрытия (event.ignore) записанные значения равны текущим, а при
        # нормальном выходе их прочитает следующий старт (ui_window_geometry_main).
        try:
            save_window_geometry("ui_window_geometry_main", self)
        except Exception:  # noqa: BLE001 — геометрия не блокирует закрытие
            pass

        # v0.9.7: автосохранение останавливается ДО диалога — во время решения
        # пользователя (Save/Discard/Cancel) запись в ~/.sshmap/autosave не нужна.
        try:
            self._autosave_timer.stop()
        except Exception:  # noqa: BLE001 — teardown-устойчивость (RuntimeError C++ объекта)
            pass

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
                # иначе данные терялись бы молча (бывш. AUDIT.md, критичная #1 — см. CHANGELOG.md).
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

        # Ping, обратный DNS и DNS-резолв импорта (v1.1.2RC2 N6 — stop() выставляет
        # cancel-флаг; текущий getaddrinfo доживает свой таймаут)
        for attr in ("_ping_thread", "_dns_thread", "_import_resolve_thread"):
            th = getattr(self, attr, None)
            if th is not None and hasattr(th, "isRunning") and th.isRunning():
                stop = getattr(th, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
                threads.append(th)

        # Терминальные СЕССИИ (v1.2: реестр хранит страницы, не окна): их teardown
        # сам делает thread.stop()+wait() через page.shutdown(); здесь только ждём
        # остаток, если окно ещё не закрыто пользователем. v1.2.1: закрываем ВСЕ
        # сессии, а не только видимые — в табовом окне неактивные табы «невидимы»
        # (QStackedWidget прячет их), но их потоки обязаны остановиться.
        terminal_waits = []
        for s in list(getattr(self, "_terminal_windows", [])):
            try:
                s.close_terminal()
                th = getattr(s, "terminal_thread", None)
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
        # v1.1.2RC3 (AUDIT U2): objectName нужен saveState()/restoreState() —
        # без него Qt шлёт в stderr «'objectName' not set for QToolBar».
        toolbar.setObjectName("main_toolbar")
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
        # v0.9.7: автосохранение + кольцевой буфер бэкапов (ROADMAP v0.9.7 #2/#3) —
        # включённость ведёт _update_window_title (нужен открытый файл проекта).
        self.act_restore_autosave = self._add_menu_action(
            file_menu, "file.restore_autosave", self._restore_from_autosave)
        self.act_backups = self._add_menu_action(
            file_menu, "file.backups", self._show_backups_dialog)
        # v0.9.5.5: массовый импорт серверов из текстового файла
        self._add_menu_action(file_menu, "file.import_servers", self._import_servers_from_txt)
        # v0.9.1: экспорт карты в изображение (PNG/JPEG)
        file_menu.addSeparator()
        self._add_menu_action(file_menu, "file.export_png", self._export_map_image)
        # v0.9.5: экспорт карты в drawio (.drawio)
        self._add_menu_action(file_menu, "file.export_drawio", self._export_map_drawio)
        # v0.9.9.7: экспорт карты в PDF (QPdfWriter поверх render_to_pixmap)
        self._add_menu_action(file_menu, "file.export_pdf", self._export_map_pdf)
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
        # v0.9.8: поиск по карте (Ctrl+F) — строка поиска поверх canvas; тот же аргумент
        # про Ctrl, что у fit_map (голая F занята вводом в поля поиска)
        self._add_menu_action(view_menu, "view.find_on_map", self._toggle_map_search, "Ctrl+F")
        # v1.1.1 (пункт 5): показать/скрыть ВЕСЬ сайдбар — один виджет в QSplitter;
        # пункт меню — способ вернуть его. Кнопочный блок прячется отдельно
        # (настройка ui_show_sidebar_buttons, чекбокс во вкладке «Общие»).
        self.act_show_sidebar = view_menu.addAction(
            self.t("view.toggle_sidebar") if self._i18n_available else "Сайдбар")
        self.act_show_sidebar.setCheckable(True)
        self.act_show_sidebar.setChecked(True)
        self.act_show_sidebar.triggered.connect(self._toggle_sidebar)
        self._register_i18n(self.act_show_sidebar, "view.toggle_sidebar")
        # v0.8.4 (бывш. DESIGN.md §D): массовое сворачивание — половина ценности фичи
        # для больших карт.
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "view.collapse_all", self._collapse_all_servers)
        self._add_menu_action(view_menu, "view.expand_all", self._expand_all_servers)
        # v0.9.1: фоновое изображение карты (схема здания / план дата-центра)
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "view.set_background", self._set_background_image)
        self._add_menu_action(view_menu, "view.remove_background", self._remove_background_image)

        # v1.1 (ROADMAP задача 2): диалог настроек (хаб) — пункт «Настройки» МЕЖДУ
        # «Вид» и «Помощь». Пункт — QAction ВНУТРИ меню (не голое действие на menubar):
        # палитра команд (Ctrl+K) обходит все QAction меню и подхватит его автоматически.
        settings_menu = menubar.addMenu(
            self.t("menu.settings") if self._i18n_available else "Настройки")
        self._register_i18n(settings_menu, "menu.settings")
        self.act_settings = self._add_menu_action(
            settings_menu, "settings.open", self._open_settings_dialog)

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

        # ── v0.9.8 bugfix (PySide6 6.11, shiboken): guard на QActions с меню ──
        # Эмпирически проверено (пробы regression_v098, offscreen И native Windows):
        # когда Python-обёртка QAction, у которого ПРИКРЕПЛЕНО QMenu, умирает
        # (GC временного объекта из menubar.actions()/act.menu()), PySide6 уничтожает
        # за ней C++-объект QMenu со всем содержимым. Без guard'а открытие палитры
        # команд (Ctrl+K) или смена языка убивали ВСЕ меню, кроме последнего
        # (палитра ходит по menubar.actions() временными обёртками). PySide6 кэширует
        # обёртки (повторный доступ — тот же объект), поэтому постоянное хранение
        # всех таких QAction в self._qaction_guard делает их бессмертными, а значит
        # и прикреплённые QMenu живут. Это латает и _switch_language, и палитру,
        # и любой будущий код, обходящий меню через action.menu().
        guard = []
        for w, _key in self._menu_i18n:
            if isinstance(w, QMenu):
                guard.extend(list(w.actions()))
        guard.extend(list(menubar.actions()))  # заголовки верхнего уровня (File/Edit/…)
        self._qaction_guard = guard

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

    def _toggle_sidebar(self, checked: bool = True):
        """v1.1.1 (пункт 5): показать/скрыть весь сайдбар (один виджет в QSplitter).

        QAction checkable — состояние пункта = видимость панели; скрытый сайдбар
        не теряет данные (поиск/тег-фильтр/дерево живут, refresh_sidebar работает).
        """
        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.setVisible(bool(checked))
            except RuntimeError:
                pass  # Qt teardown — панель уже уничтожена

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

                # v0.9.8: панель поиска по карте — плейсхолдер и счётчик на новом языке
                _map_bar = getattr(self, "map_search", None)
                if _map_bar is not None:
                    try:
                        _map_bar.retranslate()
                    except Exception:  # noqa: BLE001 — панель косметика при teardown
                        pass

                # Заголовок окна (с учётом файла проекта и маркера [*])
                self._update_window_title()

                # Отмечаем активный язык в подменю Язык.
                # v0.9.8 bugfix: НЕ обходим через action.menu() — см. _qaction_guard выше:
                # временные Python-обёртки QAction с прикреплённым QMenu роняли C++-меню
                # (PySide6 6.11). Подменю берём напрямую из i18n-реестра — безопасно.
                lang_menu = None
                for w, k in self._menu_i18n:
                    if k == "lang.menu":
                        lang_menu = w
                        break
                if lang_menu is not None:
                    try:
                        for sub in list(lang_menu.actions()):
                            if sub.data() is not None:
                                sub.setChecked(sub.data() == language_code)
                    except RuntimeError:
                        pass  # Qt teardown — подменю уже уничтожено, отмечать нечего

                if self.log:
                    self.log.info(f"Language switched to {language_code}")
            else:
                QMessageBox.warning(self, self.t("msg.error_title"), 
                                   f"{self.t('lang.switch_failed')}: {language_code}")
        except Exception as e:
            if self.log:
                self.log.exception(f"Error switching language to {language_code}")

    # ── v1.1: диалог настроек (хаб) — ROADMAP v1.1, задачи 1–7 ────────────────
    # ── v1.1.1: опции вокруг хаба — применение на лету без перезапуска ────────

    def _apply_ui_options_from_config(self):
        """v1.1.1: применить ui_* опции из config.json (старт и после ОК в диалоге).

        * Шрифт UI — QApplication.setFont (семейство/размер; пусто/0 = системный);
          применяется к виджетам без перезапуска (Qt пересчитывает шрифты, не
          установленные явно на каждом виджете).
        * Блок кнопок сайдбара — SidebarPanel.set_buttons_visible (layout сам
          перестроится); весь сайдбар прячется отдельно — пункт меню «Вид».
        * Режим двойного клика по узлу — кэш self._node_double_click_mode
          ("properties" дефолт | "connect" → _run_ssh_connect).
        """
        try:
            from ui.settings_dialog import load_ui_settings as _load_ui
        except ImportError:  # плоский запуск из корня проекта
            from settings_dialog import load_ui_settings as _load_ui
        ui_cfg = _load_ui()

        family = ui_cfg["font_family"]
        size = ui_cfg["font_size"]
        if family or size is not None:
            try:
                app = QApplication.instance()
                if app is not None:
                    f = QFont(app.font())
                    if family:
                        f.setFamily(family)
                    if size is not None:
                        f.setPointSize(int(size))
                    app.setFont(f)
            except Exception as e:  # noqa: BLE001 — шрифт не роняет старт/применение
                if self.log:
                    self.log.warning(f"Apply UI font failed: {e}")

        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.set_buttons_visible(ui_cfg["show_sidebar_buttons"])
            except RuntimeError:
                pass  # Qt teardown — панель уже уничтожена

        self._node_double_click_mode = ui_cfg["node_double_click"]

    def _open_settings_dialog(self):
        """v1.1: открыть диалог настроек (QTabWidget-хаб) — меню «Настройки» и кнопка ⚙."""
        try:
            from ui.settings_dialog import SettingsDialog
        except ImportError:  # плоский запуск из корня проекта
            from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        # Сигналы диалога → слоты окна (диалог не знает о MainWindow — паттерн sidebar.py):
        # applied — применить автосохранение/статусы на лету; language_changed — тот же
        # путь, что у пункта «Помощь → Язык» (set_language + полный retranslate UI).
        dlg.applied.connect(self._apply_settings_from_dialog)
        dlg.language_changed.connect(self._switch_language)
        dlg.exec()

    def _apply_settings_from_dialog(self):
        """v1.1: применить сохранённые настройки на лету (после ОК в диалоге).

        * Автосохранение — QTimer прямо сейчас (интервал + старт/стоп по enabled);
        * Статусы — StatusChecker.set_interval/set_probe_timeout/set_max_parallel
          (следующий раунд; v1.1.2 final: параллельные пробы, потолок 1..64);
        * v1.1.1: шрифт UI (QApplication.setFont), шрифт открытых окон терминала
          (widget.set_font — без перезапуска), кнопки сайдбара, режим двойного
          клика, перерисовка плашек связей (опция «тип на плашке»);
        * Терминал (палитра/история/поведение закрытия) и внешний терминал
          читают конфиг при следующем создании окна/запуске — действия не нужно.
        """
        try:
            from storage.autosave import get_autosave_settings as _get_as
            _as_cfg = _get_as()
            self._autosave_enabled = bool(_as_cfg.get("enabled", True))
            self._autosave_timer.setInterval(int(_as_cfg["interval_sec"]) * 1000)
            if self._autosave_enabled:
                self._autosave_timer.start()
            else:
                self._autosave_timer.stop()
        except Exception as e:  # noqa: BLE001 — таймер не должен ронять применение
            if self.log:
                self.log.warning(f"Apply autosave settings failed: {e}")
        checker = getattr(self, "_status_checker", None)
        if checker is not None:
            try:
                from services.status_checker import get_status_settings as _get_st
                _st_cfg = _get_st()
                checker.set_interval(int(_st_cfg["interval_sec"]) * 1000)
                checker.set_probe_timeout(float(_st_cfg["probe_timeout_sec"]))
                # v1.1.2 final (задача 2): потолок параллельных проб — со следующего раунда
                checker.set_max_parallel(int(_st_cfg["max_parallel"]))
            except Exception as e:  # noqa: BLE001 — статусы не должны ронять применение
                if self.log:
                    self.log.warning(f"Apply status settings failed: {e}")

        # v1.1.1 (пункт 1): шрифт UI + кнопки сайдбара + режим двойного клика
        try:
            self._apply_ui_options_from_config()
        except Exception as e:  # noqa: BLE001 — опции не должны ронять применение
            if self.log:
                self.log.warning(f"Apply UI options failed: {e}")

        # v1.1.1 (пункт 1): шрифт терминала — в УЖЕ ОТКРЫТЫЕ сессии без перезапуска
        # (v1.2: реестр хранит страницы — page.widget)
        try:
            from modules.ssh_terminal import load_terminal_settings as _load_ts
        except ImportError:
            from ..modules.ssh_terminal import load_terminal_settings as _load_ts
        term_cfg = _load_ts()
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            for s in list(getattr(self, "_terminal_windows", [])):
                try:
                    s.widget.set_font(
                        family=term_cfg["font_family"],
                        size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)
                except (RuntimeError, AttributeError):
                    pass  # Qt teardown / сессия без widget — пропускаем

        # v1.1.1 (пункт 6): опция «тип на плашке» — перерисовать метки связей сцены
        try:
            for arrow in list(getattr(self.scene, "_arrows", [])):
                arrow.refresh_label()
        except Exception:  # noqa: BLE001 — плашки косметика при teardown
            pass

        try:
            self.statusBar().showMessage(self.t("status.settings_saved"))
        except Exception:  # noqa: BLE001 — teardown-устойчивость
            pass

    # ─────────────────────────────────────────────

    def _on_node_double_click_direct(self, node: ServerNode):
        """Handle double-click on a node."""
        # v1.1.1 (пункт 4): режим из ключа ui_node_double_click — "connect" сразу
        # открывает диалог входа SSH (быстрее дублирует чекбокс «Подключиться по
        # SSH» в свойствах, тот не ломается); дефолт "properties" — поведение v1.1.
        if getattr(self, "_node_double_click_mode", "properties") == "connect":
            self._run_ssh_connect(node)
            return
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
        # v0.9.9.1: reentry-guard вместо scene.blockSignals — остальные слоты
        # selectionChanged продолжают работать во время программной смены; эхо-
        # обработчик сразу возвращается по флагу, а явная синхронизация ниже
        # идемпотентна (полный пересчёт состояния, «дерево = выделению сцены»).
        self._selection_syncing = True
        try:
            self.scene.clearSelection()
            node.setSelected(True)
        finally:
            self._selection_syncing = False
        self._sync_selection_state()
        if center:
            self.view.centerOn(node)

    def _sync_selection_state(self):
        # v0.9.9.1: reentry-guard — пока идёт программная смена выделения, эхо
        # собственных сигналов возвращается сразу (без рекурсии); явный вызов
        # после смены делает полный идемпотентный пересчёт, поэтому внешнее
        # изменение в окне синхронизации не теряется — следующее выравнивание сходится.
        if getattr(self, "_selection_syncing", False):
            return
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
            # v0.9.9.1: без tree.blockSignals — синхронизация идемпотентна по
            # состоянию (полный пересчёт, а не «применить дельту»), поэтому эхо
            # во время выравнивания безвредно, а чужие слоты дерева не подавляются.
            self.tree.setCurrentItem(None)
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, Qt.UserRole) == selected_id:
                    self.tree.setCurrentItem(item)
                    break
        except RuntimeError:
            # PySide6/Qt teardown при выходе из процесса: C++-объект сцены уже
            # уничтожен, а сигнал selectionChanged доехал до живого Python-слота.
            # Нормальное состояние — молча игнорируем (иначе traceback в консоль).
            pass

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

    def _add_note_at_view_center(self):
        """Ctrl+Shift+N: заметка в центре видимой области карты."""
        self._add_note_at()

    def _delete_selected(self):
        node = self.scene.get_selected_node()
        if node:
            self._remove_node_guarded(node)
            return
        # v0.8.1: выделенная группа — серверы остаются на карте, удаляется только рамка
        group = self.scene.get_selected_group()
        if group is not None:
            self._remove_group(group)

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

    def _export_map_pdf(self):
        """Экспорт карты в PDF (v0.9.9.7): открытая сцена → файл одним действием."""
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_pdf"), "", "PDF Documents (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            size = self.scene.render_to_pdf(path)
            self.statusBar().showMessage(self.t("status.export_pdf_ok"))
            if self.log:
                self.log.info(
                    "Map exported to PDF", extra={"file": path, "bytes": size})
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

    # ── v0.9.6: контекстное меню дерева серверов (сайдбар) ───────────────
    # v0.9.9.4: состав пунктов, разделители и i18n-подписи — в панели
    # (SidebarPanel.fill_context_menu); объект QMenu создаётся здесь (модульная
    # глобальная main_window — тестовый шов подмены), exec тоже на окне.

    def _on_sidebar_context_menu(self, pos):
        """v0.9.6 (ROADMAP #1–#2): ПКМ по серверу в дереве — действия узла.

        Состав и порядок — по ROADMAP v0.9.6 (SidebarPanel.CONTEXT_MENU_ITEMS):
        Подключиться SSH, Внешний терминал, Редактировать, Скопировать IP,
        Copy Hostname, Ping, Собрать информацию, Показать на карте
        (центрирование + акцент), Удалить (guarded-путь). i18n — переиспользование
        ключей ctx.* карты; новый только ctx.reveal_on_map. «Карточные» действия
        сознательно НЕ дублируются (ROADMAP #2): drag-связь и свернуть/развернуть
        плашку живут только в контексте карты, где они имеют смысл.
        """
        item = self.tree.itemAt(pos)
        if item is None:
            return  # клик мимо строк — меню не показываем (пустая область дерева)
        node_id = item.data(0, Qt.UserRole)
        if not node_id or not self.scene.has_node(node_id):
            return  # строка без узла (или узел исчез) — действий нет
        node = self.scene.get_node(node_id)

        menu = QMenu(self)  # v0.9.9.4: панель наполняет, окно создаёт и показывает
        self.sidebar.fill_context_menu(menu, node)

        try:
            menu.exec(self.tree.mapToGlobal(pos))
        except Exception as e:  # noqa: BLE001 — GUI-компонент не должен ронять приложение
            if self.log:
                self.log.warning(f"sidebar context menu exec failed: {e}")

    def _reveal_node_on_map(self, node: "ServerNode"):
        """v0.9.6 (ROADMAP #1): «Показать на карте» — центрирование + акцент.

        Выбор узла (строка дерева и рамка карты синхронизируются через
        _sync_selection_state), centerOn — готовый путь _select_node(center=True);
        акцент — рамка-вспышка ServerNode.reveal_flash (паттерн пульса set_status).
        """
        if node is None or node.scene() is None:
            return  # узел удалён, пока меню было открыто
        self._select_node(node, center=True)
        flash = getattr(node, "reveal_flash", None)
        if callable(flash):
            try:
                flash()
            except Exception:  # noqa: BLE001 — акцент косметика; навигация уже сработала
                pass

    def refresh_sidebar(self):
        """v0.9.9.4-фасад: строки дерева (поиск + тег-фильтр + маркеры статусов)
        и список тегов — SidebarPanel; затемнение/выделение/счётчики — окно."""
        query = self.search_edit.text().strip().lower() if hasattr(self, 'search_edit') else ""
        nodes = self.scene.nodes()
        self.sidebar.refresh_rows(nodes, query)
        self.sidebar.sync_tag_filter_items(nodes)
        self._apply_map_dimming()  # v0.9.8: затемнение = тег-фильтр И поиск по карте
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

    def _apply_map_dimming(self):
        """v0.9.4/v0.9.8: затемнение + подсветка активных фильтров на карте.

        Узел «горит» только если проходит ВСЕ активные фильтры (та же семантика,
        что в сайдбаре — refresh_sidebar применяет query и тег одновременно):
        - v0.9.4 тег-фильтр: узлы без выбранного тега затемнены;
        - v0.9.8 поиск по карте (Ctrl+F): несовпавшие с запросом затемнены,
          совпавшие — акцентная рамка (ServerNode.set_search_match).
        Стрелки не трогаем: связи между затемнёнными узлами читаются по контексту.
        """
        active = self._active_tag_filter()
        query = (getattr(self, "_map_search_query", "") or "").strip().lower()
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return
        for node in nodes:
            tags = getattr(node.data, "tags", None) or []
            tag_ok = (not active) or active in tags
            if query:
                haystack = " ".join([
                    node.data.alias, node.data.host, node.data.ip, node.data.comment,
                ]).lower()
                match_ok = query in haystack
            else:
                match_ok = True
            try:
                node.set_dimmed(not (tag_ok and match_ok))
                node.set_search_match(bool(query) and match_ok)
            except (AttributeError, RuntimeError):
                pass

    # Backward-compat: имя v0.9.4 (внешний код/тесты могли обращаться к нему)
    _apply_map_tag_dimming = _apply_map_dimming

    # ── v0.9.8: поиск по карте (Ctrl+F) — ROADMAP v0.9.8 ────────────────

    def _setup_map_search(self):
        """v0.9.8: создать плавающую строку поиска поверх canvas + состояние.

        Панель — дочерний виджет MapView (плавает над viewport, не мешает сцене).
        Хоткей Ctrl+F даёт пункт меню «Вид → Поиск по карте…» (QAction-шорткат) —
        отдельный QShortcut с той же последовательностью создал бы ambiguous shortcut.
        Логика поиска живёт здесь: совпадение/затемнение/центрирование — единый путь.
        """
        try:
            from ui.map_search_bar import MapSearchBar
        except ImportError:  # плоский запуск из корня проекта
            from map_search_bar import MapSearchBar

        # Состояние (пусто до первого запроса)
        self._map_search_query = ""
        self._map_search_matches = []
        self._map_search_index = -1

        self.map_search = MapSearchBar(self.view)
        self.map_search.query_changed.connect(self._on_map_search_query)
        self.map_search.next_requested.connect(lambda: self._map_search_step(+1))
        self.map_search.prev_requested.connect(lambda: self._map_search_step(-1))
        self.map_search.close_requested.connect(self._close_map_search)
        # Переставить панель при resize окна (она вне layout, child of view).
        # v0.9.9.1: сигнал MapView.resized добавлен — раньше connect падал в
        # AttributeError и молча глотался try/except (панель оставалась на старом x).
        self.view.resized.connect(self._position_map_search_bar)

    def _toggle_map_search(self):
        """v0.9.8: Ctrl+F / «Вид → Поиск по карте…» — открыть или закрыть панель."""
        if self.map_search.isVisible():
            self._close_map_search()
        else:
            self._open_map_search()

    def _open_map_search(self):
        """v0.9.8: показать панель, поставить в верхний центр viewport, фокус на ввод.

        Если в поле остался запрос (закрыли Esc, текст сохранился — как в браузере),
        оживляем его заново: пересчёт совпадений/счётчика по актуальной сцене.
        Иначе Enter ссылался бы на очищенный self._map_search_query, а панель
        показывала старый текст и счётчик — рассинхрон.
        """
        self.map_search.show()
        self.map_search.raise_()
        self._position_map_search_bar()
        if self.map_search.query.strip():
            self._on_map_search_query(self.map_search.query)
        self.map_search.focus_input()
        self.statusBar().showMessage(self.t("hint.map_search"))

    def _close_map_search(self):
        """v0.9.8: закрыть панель и снять состояние поиска (затемнение + рамки).

        Тег-фильтр при этом остаётся активным — _apply_map_dimming пересчитает
        затемнение по нему (query уже очищен выше).
        """
        if getattr(self, "map_search", None) is not None:
            self.map_search.hide()
        self._map_search_query = ""
        self._map_search_matches = []
        self._map_search_index = -1
        self._apply_map_dimming()
        try:
            self.statusBar().showMessage(self.t("status.ready"))
        except Exception:  # noqa: BLE001 — статус-бар косметика при teardown
            pass

    def _position_map_search_bar(self):
        """v0.9.8: панель в верхнем центре viewport (child of view, вне layout)."""
        bar = getattr(self, "map_search", None)
        if bar is None or not bar.isVisible():
            return
        vp = self.view.viewport()
        w = min(bar.PREFERRED_WIDTH, max(vp.width() - 16, bar.MIN_WIDTH))
        x = max(8, (vp.width() - w) // 2)
        h = max(bar.sizeHint().height(), 30)
        bar.setGeometry(int(x), 10, int(w), int(h))

    def _map_search_nodes(self, query: str):
        """v0.9.8: узлы, совпадающие с запросом (alias/host/ip/comment — как в сайдбаре)."""
        q = (query or "").strip().lower()
        if not q:
            return []
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return []
        out = []
        for node in nodes:
            d = node.data
            haystack = " ".join([d.alias, d.host, d.ip, d.comment]).lower()
            if q in haystack:
                out.append(node)
        return out

    def _on_map_search_query(self, query: str):
        """v0.9.8: текст запроса изменился — пересчитать совпадения и затемнение.

        Счётчик указывает на ПЕРВЫЙ результат (паттерн браузерного поиска);
        центрирование/выделение — только по Enter (ROADMAP #2).
        """
        self._map_search_query = query or ""
        matches = self._map_search_nodes(query)
        self._map_search_matches = matches
        self._map_search_index = 0 if matches else -1
        self._apply_map_dimming()
        self.map_search.set_count(self._map_search_index + 1, len(matches))

    def _map_search_step(self, direction: int):
        """v0.9.8: Enter/Shift+Enter — переход между результатами (с зацикливанием).

        Выбор узла (строка сайдбара следует за выделением через _sync_selection_state),
        центрирование view.centerOn и рамка-вспышка reveal_flash — тот же готовый путь,
        что «Показать на карте» v0.9.6 (паттерн пульса set_status). Совпадения
        пересчитываются свежими: узлы могли добавиться/удалиться с момента запроса.
        """
        matches = self._map_search_nodes(self._map_search_query)
        if not matches:
            q = (self._map_search_query or "").strip()
            try:
                self.statusBar().showMessage(self.t("status.no_matches", query=q))
            except Exception:  # noqa: BLE001 — сбой форматирования не критичен
                self.statusBar().showMessage(f"No matches: {q}")
            return
        n = len(matches)
        base = self._map_search_index if 0 <= self._map_search_index < n else -1
        idx = (base + direction) % n
        self._map_search_matches = matches
        self._map_search_index = idx
        node = matches[idx]
        self._select_node(node, center=True)
        flash = getattr(node, "reveal_flash", None)
        if callable(flash):
            try:
                flash()
            except Exception:  # noqa: BLE001 — акцент косметика; навигация уже сработала
                pass
        self.map_search.set_count(idx + 1, n)

    def _close_map_search_if_open(self):
        """v0.9.8: закрыть поиск при смене проекта (старый запрос к новым узлам неактуален)."""
        bar = getattr(self, "map_search", None)
        if bar is not None and bar.isVisible():
            self._close_map_search()

    # ── Ревью-фикс v0.8.0 (#3): маркеры статусов узлов в дереве сайдбара ──
    # v0.9.9.4: иконки точек и маркеры строк — SidebarPanel (apply_status_marker /
    # update_status_marker); окно передаёт панели актуальный статус узла.

    def _update_sidebar_status_marker(self, server_id: str) -> None:
        """Обновить маркер строки на месте (без полного пересбора дерева)."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # узла уже нет — статус никому не нужен
        self.sidebar.update_status_marker(server_id, node.status, node.data.host or "")

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
