"""Панель сайдбара (список серверов) — v0.9.9.4.

Сайдбар-кластер перенесён из ui/main_window.py (фаза 1 серии «Гигиена
main_window.py»): кнопки действий, заголовок, поле поиска, тег-фильтр, дерево
серверов с маркерами статусов и состав контекстного меню по строке.

Паттерн «модуль + колбэки» (как services/diagnostics.py в v0.9.9.3): панель не
знает ни о MainWindow, ни о MapScene — всё приходит извне:
  * translate_fn(key, **kw) — i18n-колбэк; реестр собственных строк панели
    повторно применяется в retranslate() при смене языка (регрессия на баг
    v0.9.2 — строки сайдбара не теряются/не остаются на старом языке);
  * actions — словарь колбэков контекстного меню {ключ действия: callable(node)};
  * клики кнопок — сигналы панели, MainWindow подключает свои слоты.

MainWindow остаётся фасадом (публичный API не меняется): self.tree /
self.tag_filter / self.search_edit / self.btn_* — ссылки на виджеты панели,
refresh_sidebar()/_sync_selection_state()/_on_tree_item_clicked() и др. — методы
окна. Объект контекстного меню СОЗДАЁТ MainWindow (QMenu — модульная глобальная,
тестовый шов подмены), панель лишь наполняет его пунктами (fill_context_menu).
"""
from PySide6.QtCore import Qt, QSize, Signal
# v1.1.2RC2 (N9): QColor убран из импортов — с удалением мёртвого setItemData(...,
# Qt.DecorationRole) в панели не осталось ни одного использования
from PySide6.QtGui import QIcon, QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QComboBox,
    QTreeWidget, QTreeWidgetItem, QPushButton,
)

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:  # UI polish: векторные иконки (ui/icons.py) — замена эмодзи, единый стиль с тулбаром
    from .icons import get_icon
except ImportError:
    try:
        from icons import get_icon
    except ImportError:  # flat-раскладка без ui/icons — кнопки текстовые, как раньше
        def get_icon(name):  # noqa: N802 — заглушка с той же сигнатурой
            return None


# Ключи действий контекстного меню (порядок и разделители — ROADMAP v0.9.6, пункт 1).
# «Карточные» действия сознательно НЕ дублируются (ROADMAP #2): drag-связь и
# свернуть/развернуть плашку живут только в контексте карты, где они имеют смысл.
CONTEXT_MENU_ITEMS = (
    ("ssh", "ctx.ssh_connect"),
    ("external", "ctx.ssh_external"),
    None,  # разделитель
    ("edit", "ctx.edit_server"),
    None,
    ("copy_ip", "ctx.copy_ip"),
    ("copy_hostname", "ctx.copy_hostname"),
    ("ping", "ctx.ping"),
    ("collect_info", "ctx.collect_info"),
    None,
    ("reveal", "ctx.reveal_on_map"),
    None,
    ("delete", "ctx.delete_server"),
)

# Кнопки панели: (атрибут, иконка, i18n-ключ) — порядок как в исходном _setup_ui.
# v1.1: 6-я кнопка «Настройки» (хаб, ROADMAP v1.1 задача 2) — векторная шестерёнка
# из ui/icons.py; retranslate() ниже обходит _BUTTONS — новый кортеж подхватывается.
_BUTTONS = (
    ("btn_add", "add_server", "btn.add_server", "Добавить сервер"),
    ("btn_connect", "connection", "btn.add_connection", "Добавить связь"),
    ("btn_connect_ssh", "ssh", "btn.connect_ssh", "SSH Подключение"),
    ("btn_props", "properties", "btn.properties", "Свойства"),
    ("btn_delete", "delete", "btn.delete", "Удалить"),
    ("btn_settings", "settings", "btn.settings", "Настройки"),
)


class SidebarPanel(QWidget):
    """Сайдбар: кнопки, заголовок, поиск, тег-фильтр, дерево серверов (v0.9.9.4).

    Сигналы (MainWindow подключает свои слоты):
        add_server_clicked / add_connection_clicked / connect_ssh_clicked /
        show_properties_clicked / delete_selected_clicked — клики кнопок;
        settings_clicked — клик кнопки «Настройки» (v1.1, хаб настроек);
    события дерева (itemClicked/itemDoubleClicked/customContextMenuRequested)
    доступны напрямую на self.tree.
    """

    add_server_clicked = Signal()
    add_connection_clicked = Signal()
    connect_ssh_clicked = Signal()
    show_properties_clicked = Signal()
    delete_selected_clicked = Signal()
    settings_clicked = Signal()  # v1.1: кнопка ⚙ «Настройки» (6-я в _BUTTONS)

    def __init__(self, translate_fn=None, actions=None, show_title: bool = True,
                 parent=None):
        """
        :param translate_fn: i18n-колбэк (key, **kw) -> str; None — i18n недоступен
            (строки остаются русскими литералами, как при конструировании).
        :param actions: {ключ действия: callable(node)} для контекстного меню;
            обязательны все ключи из CONTEXT_MENU_ITEMS.
        :param show_title: создавать ли заголовок «Серверы» (MainWindow передаёт
            _i18n_available — раньше метка создавалась только при доступном i18n).
        """
        super().__init__(parent)
        self._translate = translate_fn
        self._actions = dict(actions or {})
        missing = [entry[0] for entry in CONTEXT_MENU_ITEMS
                   if entry is not None and entry[0] not in self._actions]
        if missing:
            raise ValueError(f"SidebarPanel: нет колбэков для действий {missing}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Server title label (только при доступном i18n — как раньше) ────────
        self.title_label = None
        if show_title:
            self.title_label = QLabel(self._tr("server.title"))
            layout.addWidget(self.title_label)

        # ── Search field ────────────────────────────────────────────────────────
        self.search_edit = QLineEdit()
        if translate_fn is not None:
            try:
                self.search_edit.setPlaceholderText(self._translate("search.placeholder"))
            except Exception:  # noqa: BLE001 — плейсхолдер косметика
                pass
        else:
            self.search_edit.setPlaceholderText("Поиск по alias / host / IP...")
        layout.addWidget(self.search_edit)

        # ── v0.9.4: фильтр по тегам ────────────────────────────────────────────
        # Элементы: [0] = «Все теги» (фильтр выключен), далее — уникальные теги
        # всех серверов карты; перестраивается в sync_tag_filter_items (без сброса выбора).
        self.tag_filter = QComboBox()
        layout.addWidget(self.tag_filter)

        # ── Server tree ────────────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # Ревью-фикс v0.8.0 (#3): цветные маркеры статусов в дереве (16×16 — ровно
        # под pixmap точки; единый размер не зависит от стиля/платформы).
        self.tree.setIconSize(QSize(16, 16))
        layout.addWidget(self.tree)
        # Кэш иконок точек по статусу ("", "online", "warn", "offline")
        self._status_dot_icons = {}

        # v0.9.6: контекстное меню дерева серверов (ПКМ по строке сайдбара).
        # Политика CustomContextMenu + сигнал customContextMenuRequested — штатный
        # путь Qt для QTreeWidget (у виджета нет переопределяемого contextMenuEvent
        # без перехвата событий viewport'а; сигнал несёт позицию в координатах
        # дерева, itemAt(pos) даёт строку). Слот-обработчик — у MainWindow.
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # ── Buttons (всегда создаются, i18n применяется при наличии колбэка) ──
        for attr, icon_name, i18n_key, ru_fallback in _BUTTONS:
            btn = QPushButton(ru_fallback)
            self._set_btn_icon(btn, icon_name)
            btn.setMinimumHeight(34)  # UI polish: ровные кнопки сайдбара
            # v1.1.2RC2 (U1, замечание пользователей): выравнивание влево — отступ
            # от левого края, иконка, текст. QPushButton по умолчанию центрирует
            # содержимое; QStyle не даёт настроить alignment без stylesheet,
            # поэтому — минимальный CSS (рамка/фон нативные, стилизация только
            # позиционированием контента).
            btn.setStyleSheet("QPushButton { text-align: left; padding-left: 12px; }")
            if translate_fn is not None:
                try:
                    # Эмодзи/префиксы уже содержатся в самих значениях перевода,
                    # добавлять их здесь повторно нельзя (было «- - 添加连接» и т.п.)
                    btn.setText(self._translate(i18n_key))
                except Exception:  # noqa: BLE001 — keep Russian fallback labels
                    pass
            setattr(self, attr, btn)
            layout.addWidget(btn)

        self.btn_add.clicked.connect(self.add_server_clicked)
        self.btn_connect.clicked.connect(self.add_connection_clicked)
        self.btn_connect_ssh.clicked.connect(self.connect_ssh_clicked)
        self.btn_props.clicked.connect(self.show_properties_clicked)
        self.btn_delete.clicked.connect(self.delete_selected_clicked)
        self.btn_settings.clicked.connect(self.settings_clicked)  # v1.1: хаб настроек

    # ── i18n (колбэк + retranslate — регрессия на баг v0.9.2) ─────────────────

    def _tr(self, key: str, **kw) -> str:
        """Перевод через переданный колбэк; без колбэка — сам ключ."""
        if self._translate is not None:
            try:
                return self._translate(key, **kw)
            except Exception:  # noqa: BLE001 — сбой i18n не роняет панель
                pass
        return key

    def retranslate(self):
        """Повторно применить перевод к собственным строкам панели (смена языка).

        Регрессия на баг v0.9.2: до v0.9.9.4 строки сайдбара (кнопки, заголовок,
        плейсхолдер поиска, «Все теги» в тег-фильтре) выставлялись только при
        конструировании и оставались на старом языке после переключения. Реестр
        строк — здесь; i18n-модуль панель не импортирует (колбэк translate_fn).
        Вызывается из MainWindow._apply_ui_translations().
        """
        if self._translate is None:
            return  # i18n недоступен — русские литералы с момента конструирования
        try:
            if self.title_label is not None:
                self.title_label.setText(self._tr("server.title"))
            self.search_edit.setPlaceholderText(self._tr("search.placeholder"))
            for attr, _icon, key, _ru in _BUTTONS:
                getattr(self, attr).setText(self._tr(key))
            # Тег-фильтр: подпись элемента 0 («Все теги») — без сброса выбора.
            # setCurrentIndex на тот же индекс сигнал не эмитит (Qt), повторный
            # refresh_sidebar в любом случае идемпотентен.
            idx = self.tag_filter.currentIndex()
            self.tag_filter.setItemText(0, self._tr("filter.all_tags"))
            if idx > 0:
                self.tag_filter.setCurrentIndex(idx)
        except RuntimeError:
            pass  # Qt teardown — виджеты уже уничтожены

    # ── Кнопки ─────────────────────────────────────────────────────────────────

    def set_buttons_visible(self, visible: bool) -> None:
        """v1.1.1 (ROADMAP пункт 5): show/hide блока кнопок сайдбара.

        Ключ ui_show_sidebar_buttons (дефолт True — поведение v1.1). Layout сам
        перестраивается: скрытые кнопки занимают ноль места, дерево/поиск растут.
        Весь сайдбар прячется отдельно (MainWindow: пункт меню «Вид → Сайдбар»);
        этот метод трогает только кнопочный блок.
        """
        for attr, _icon, _key, _ru in _BUTTONS:
            btn = getattr(self, attr, None)
            if btn is not None:
                try:
                    btn.setVisible(bool(visible))
                except RuntimeError:
                    pass  # Qt teardown — виджет уже уничтожен

    def _set_btn_icon(self, btn, name):
        """UI polish: векторная иконка на кнопке (no-op без ui/icons)."""
        try:
            icon = get_icon(name)
            if icon is not None and not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QSize(18, 18))
        except Exception:  # noqa: BLE001 — иконка косметика, не роняем сайдбар
            pass

    # ── Дерево: построение строк (refresh из MainWindow) ──────────────────────

    def active_tag_filter(self) -> str:
        """Выбранный в комбобоксе тег или "" («Все теги»)."""
        data = self.tag_filter.currentData()
        return str(data) if data else ""

    def refresh_rows(self, nodes, query: str = ""):
        """Пересобрать строки дерева: поиск (query) + активный тег-фильтр.

        `nodes` — итерируемое ServerNode (MainWindow передаёт scene.nodes());
        панель не зависит от сцены — только от данных узлов.
        """
        self.tree.clear()
        active_tag = self.active_tag_filter()
        for node in nodes:
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
            self.apply_status_marker(item, node.status, node.data.host or "")
            # v0.9.4: подпись тегов в конце строки («[tag1, tag2]», до 3 тегов).
            # v1.1.2RC2 (N8): setForeground(0, palette().windowText()) УБРАН — под
            # комментарием «серым» он красил ВСЮ строку стандартным цветом текста
            # (визуальный no-op: цвет не отличался от дефолтного).
            tags = getattr(node.data, "tags", None) or []
            if tags:
                item.setText(0, item.text(0) + f"  [{', '.join(tags[:3])}]")
            self.tree.addTopLevelItem(item)

    def sync_tag_filter_items(self, nodes):
        """Перестроить список уникальных тегов в комбобоксе, сохраняя выбор.

        Вызывается из refresh_sidebar (MainWindow) — сигнал currentIndexChanged
        при этом не должен зациклить пересборку (блокируем сигналы на время заполнения).
        """
        all_tags = sorted({
            t.strip()
            for n in nodes
            for t in (getattr(n.data, "tags", None) or [])
            if t and t.strip()
        }, key=str.lower)
        current = self.active_tag_filter()
        try:
            all_label = self._translate("filter.all_tags") if self._translate else "All tags"
        except Exception:  # noqa: BLE001 — как раньше: fallback на английский литерал
            all_label = "All tags"
        if not all_label:
            all_label = "All tags"
        combo = self.tag_filter
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(all_label, "")
            # v1.1.2RC2 (N9): setItemData(QColor, Qt.DecorationRole) УБРАН — стандартный
            # стиль читает DecorationRole как QIcon, QColor не рендерился (мёртвый код);
            # «● tag» в тексте — обычный символ цветом текста, цвет тегов несёт карточка.
            for tag in all_tags:
                combo.addItem(f"● {tag}", tag)
            idx = combo.findData(current) if current else 0
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        except RuntimeError:
            pass  # Qt teardown
        finally:
            combo.blockSignals(False)

    # ── Маркеры статусов (ревью-фикс v0.8.0, #3) ──────────────────────────────

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

    def apply_status_marker(self, item: QTreeWidgetItem, status: str, host: str = "") -> None:
        """Поставить на строку дерева точку статуса + tooltip (i18n node.status.*)."""
        item.setIcon(0, self._status_dot_icon(status))
        if status and status in ServerNode.STATUS_COLORS:
            tip = self._tr(f"node.status.{status}", host=host or "")
            # i18n вернул «ключ» (нет перевода) — показываем статус без ключа
            item.setToolTip(0, tip if not tip.startswith("[") else f"{status}: {host}")
        else:
            item.setToolTip(0, "")  # не проверялся — подсказки нет

    def update_status_marker(self, server_id: str, status: str, host: str = "") -> None:
        """Обновить маркер строки на месте (без полного пересбора дерева)."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == server_id:
                self.apply_status_marker(item, status, host)
                return
        # Строки нет (например, отфильтрована поиском) — следующий refresh_sidebar
        # построит её с актуальным маркером.

    # ── Контекстное меню (состав v0.9.6; объект QMenu создаёт MainWindow) ─────

    def fill_context_menu(self, menu, node) -> None:
        """Наполнить QMenu пунктами действий узла (порядок — ROADMAP v0.9.6).

        `menu` создаёт MainWindow (QMenu — модульная глобальная main_window; так
        сохраняется тестовый шов подмены класса меню), parent/показ тоже на окне.
        Каждый пункт подключён к колбэку из self._actions: callable(node).

        v1.0RC4: первым пунктом — подменю «Быстрый запуск» (если потребитель
        передал колбэки ql_entry/ql_configure; без них меню — как в v0.9.6,
        backward-compat для старых вызывающих кодов).
        """
        self._fill_quick_launch(menu, node)
        for entry in CONTEXT_MENU_ITEMS:
            if entry is None:
                menu.addSeparator()
                continue
            action_key, i18n_key = entry
            act = menu.addAction(self._tr(i18n_key))
            callback = self._actions[action_key]
            # checked — bool из QAction.triggered; колбэку передаём только узел.
            act.triggered.connect(lambda checked=False, n=node, cb=callback: cb(n))

    def _fill_quick_launch(self, menu, node) -> None:
        """v1.0RC4: подменю «Быстрый запуск» — ПЕРВЫЙ пункт меню (выше SSH).

        Состав: пункты server.data.quick_launch (ссылки/команды), затем разделитель
        и «Настроить…». Без пунктов — только «Настроить…» (фича остаётся
        discoverable). Колбэки из self._actions (опциональные, вне CONTEXT_MENU_ITEMS):
          * "ql_entry"     — callable(node, entry): открыть ссылку/отправить команду;
          * "ql_configure" — callable(node): диалог настройки.
        Если ни одного нет — подменю не строится (старые потребители без изменений).
        """
        cb_entry = self._actions.get("ql_entry")
        cb_config = self._actions.get("ql_configure")
        if cb_entry is None and cb_config is None:
            return  # потребитель не знает о Быстром запуске — меню как в v0.9.6
        entries = list(getattr(node.data, "quick_launch", None) or [])
        sub = menu.addMenu(self._tr("ctx.quick_launch"))
        # v1.0RC4-fix (PySide6 6.11/shiboken — тот же баг, что _qaction_guard в
        # main_window.py v0.9.8): локальная обёртка sub умирает при возврате из
        # метода, а MainWindow показывает меню лишь ПОСЛЕ возврата (menu.exec).
        # Когда Python-обёртка QAction с прикреплённым QMenu умирает (GC), PySide6
        # уничтожает за ней C++-подменю — пункт «Быстрый запуск» исчезал из меню
        # или падал RuntimeError'ом. Держим ссылки (QAction + QMenu) на обёртке
        # родительского меню: живут ровно столько, сколько само эфемерное меню.
        _guard = getattr(menu, "_sshmap_ql_guard", None)
        if _guard is None:
            _guard = menu._sshmap_ql_guard = []
        _ql_action = next((a for a in menu.actions() if a.menu() is sub), None)
        if _ql_action is not None:
            _guard.append(_ql_action)
        _guard.append(sub)
        for e in entries:
            if cb_entry is None:
                break  # только настройка доступна — пункты не показываем
            name = str(e.get("name") or e.get("value") or "?")
            act = sub.addAction(name)
            # checked — bool из QAction.triggered; замыкаем и узел, и пункт.
            act.triggered.connect(
                lambda checked=False, n=node, en=e, cb=cb_entry: cb(n, en))
        if entries:
            sub.addSeparator()
        if cb_config is not None:
            act_cfg = sub.addAction(self._tr("ql.configure"))
            act_cfg.triggered.connect(
                lambda checked=False, n=node, cb=cb_config: cb(n))
        menu.addSeparator()  # Быстрый запуск отделён от «боевого» меню (как на карте)
