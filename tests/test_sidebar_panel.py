"""ui/sidebar.py: SidebarPanel — фасад MainWindow + retranslate (v0.9.9.4).

ROADMAP v0.9.9.4 — фаза 1 серии «Гигиена main_window.py»: сайдбар-кластер
(кнопки, заголовок, поиск, тег-фильтр, дерево с маркерами статусов, контекстное
меню) перенесён из ui/main_window.py в ui/sidebar.py (SidebarPanel(QWidget)).
Публичный API MainWindow остаётся фасадом — существующие тесты не трогали.

  * фасад: win.tree/win.tag_filter/win.search_edit/win.btn_* — ссылки на виджеты
    панели; refresh_sidebar/_sync_selection_state/_on_tree_item_clicked и др. — методы окна;
  * гигиена: дерево/маркеры/строки строит панель, в main_window.py их кода нет;
  * панель unit-уровнем: translate_fn=None → русские литералы, retranslate no-op;
    недостающий колбэк действия → ValueError; fill_context_menu — 9 пунктов + 4 разделителя;
  * РЕГРЕССИЯ БАГА v0.9.2 (i18n-реестр через колбэк): при смене языка строки сайдбара
    (кнопки, заголовок, плейсхолдер, «Все теги») НЕ теряются и не остаются на старом
    языке; выбор тег-фильтра переживает retranslate.

Запуск: python tests/test_sidebar_panel.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData
from i18n import t as _t
import ui.sidebar as SB


# ══ 1. Фасад MainWindow: панель встроена, публичный API не изменился ═══════
print("== v0.9.9.4 sidebar panel: facade ==")

win = MW.MainWindow()
check("MainWindow owns a ui.sidebar.SidebarPanel",
      isinstance(getattr(win, "sidebar", None), SB.SidebarPanel),
      repr(type(getattr(win, "sidebar", None))))

# Фасадные ссылки — те же объекты, что внутри панели (тесты ходят через win.tree и т.д.)
check("facade: win.tree is panel.tree", win.tree is win.sidebar.tree)
check("facade: win.tag_filter is panel.tag_filter", win.tag_filter is win.sidebar.tag_filter)
check("facade: win.search_edit is panel.search_edit", win.search_edit is win.sidebar.search_edit)
for _attr in ("btn_add", "btn_connect", "btn_connect_ssh", "btn_props", "btn_delete"):
    check(f"facade: win.{_attr} is panel.{_attr}", getattr(win, _attr) is getattr(win.sidebar, _attr))
check("facade: win._sidebar_title is panel.title_label",
      win._sidebar_title is win.sidebar.title_label)

# Публичный API окна (используют существующие тесты) — методы MainWindow, не панели
for _m in ("refresh_sidebar", "_sync_selection_state", "_on_tree_item_clicked",
           "_on_tree_item_double_click", "_on_sidebar_context_menu", "_reveal_node_on_map",
           "_update_sidebar_status_marker", "_active_tag_filter", "_on_tag_filter_changed"):
    check(f"facade: MainWindow has method {_m}",
          callable(getattr(MW.MainWindow, _m, None)), _m)

# Сигналы кнопок панели подключены к слотам окна. SignalInstance в PySide6 не имеет
# .receivers() (а QObject.receivers('name') отдаёт 0 для new-style сигналов), поэтому
# связь проверяем на уровне исходников — тот же паттерн, что у гигиенических проверок ниже:
# фасадные ссылки win.btn_* — виджеты панели (проверено выше), клик эмитит ровно эти
# сигналы, а connect() в main_window.py замыкает цепь.
_mw_src_signals = open(sys.modules[MW.__name__].__file__, encoding="utf-8").read()
for _sig in ("add_server_clicked", "add_connection_clicked", "connect_ssh_clicked",
             "show_properties_clicked", "delete_selected_clicked"):
    check(f"main_window.py wires sidebar.{_sig} to a window slot",
          f"self.sidebar.{_sig}.connect(" in _mw_src_signals)

# Гигиена: код кластера из main_window.py исчез (дерево/маркеры/строки — в панели)
_mw_src = open(sys.modules[MW.__name__].__file__, encoding="utf-8").read()
check("main_window.py: no 'self.tree = QTreeWidget()' left", "self.tree = QTreeWidget()" not in _mw_src)
check("main_window.py: no '_status_dot_icon' definition left", "def _status_dot_icon" not in _mw_src)
check("main_window.py: no '_apply_status_marker' definition left", "def _apply_status_marker" not in _mw_src)
check("main_window.py: no '_sync_tag_filter_items' definition left", "def _sync_tag_filter_items" not in _mw_src)
_sb_src = open(sys.modules[SB.__name__].__file__, encoding="utf-8").read()
check("ui/sidebar.py defines SidebarPanel(QWidget)", "class SidebarPanel(QWidget)" in _sb_src)

# ══ 2. refresh_sidebar через фасад: строки, маркеры, поиск, тег-фильтр ═════
print("== v0.9.9.4 sidebar panel: refresh via facade ==")

n1 = win.scene.add_server(ServerData(id="sp7a", alias="web-1", host="10.30.0.1",
                                     user="ops", ip="10.30.0.1", tags=["prod"], x=100, y=100))
n2 = win.scene.add_server(ServerData(id="sp7b", alias="db-1", host="db.internal",
                                     user="dba", x=500, y=300))
win.refresh_sidebar()
check("refresh_sidebar builds a row per node (facade)", win.tree.topLevelItemCount() == 2,
      f"rows={win.tree.topLevelItemCount()}")
row1 = None
for i in range(win.tree.topLevelItemCount()):
    if win.tree.topLevelItem(i).data(0, Qt.UserRole) == "sp7a":
        row1 = win.tree.topLevelItem(i)
check("row text is 'alias  (host)' + tag suffix",
      row1 is not None and row1.text(0) == "web-1  (10.30.0.1)  [prod]",
      row1.text(0) if row1 else "no row")
check("row carries a status marker icon (idle dot)",
      row1 is not None and not row1.icon(0).isNull())

# Поиск: поле поиска панели фильтрует строки (textChanged → refresh_sidebar)
win.search_edit.setText("db.internal")  # host узла db-1 (поиск — подстрока по alias/host/ip/comment/тегам)
check("search query filters rows", win.tree.topLevelItemCount() == 1,
      f"rows={win.tree.topLevelItemCount()}")
win.search_edit.setText("")

# Тег-фильтр: комбобокс панели (уникальные теги + «Все теги»), выбор фильтрует строки
_tags = [win.tag_filter.itemText(i) for i in range(win.tag_filter.count())]
check("tag filter lists 'All tags' + unique tag", _tags[0] == _t("filter.all_tags") and "prod" in _tags[1],
      str(_tags))
idx_prod = win.tag_filter.findData("prod")
win.tag_filter.setCurrentIndex(idx_prod)
check("selecting a tag filters rows (db-1 hidden)",
      win.tree.topLevelItemCount() == 1, f"rows={win.tree.topLevelItemCount()}")
check("tag filter dims non-matching node on the map (AND-семантика v0.9.8)",
      getattr(n2, "_dimmed", False) is True and getattr(n1, "_dimmed", False) is False,
      f"n1={getattr(n1, '_dimmed', '?')} n2={getattr(n2, '_dimmed', '?')}")
win.tag_filter.setCurrentIndex(0)

# Маркер статуса обновляется на месте (без пересбора дерева — паттерн v0.8.0 #3)
_rows_before = win.tree.topLevelItemCount()
n1.set_status("online")
win._update_sidebar_status_marker("sp7a")
check("status marker updates in place (row count unchanged)",
      win.tree.topLevelItemCount() == _rows_before, f"{_rows_before} -> {win.tree.topLevelItemCount()}")

# Клик по строке — слот окна выделяет узел на сцене
for i in range(win.tree.topLevelItemCount()):
    if win.tree.topLevelItem(i).data(0, Qt.UserRole) == "sp7b":
        win._on_tree_item_clicked(win.tree.topLevelItem(i), 0)
check("tree row click selects the node on the scene (window slot)",
      win.scene.get_selected_node() is n2, repr(win.scene.get_selected_node()))

# ══ 3. Панель unit-уровнем: колбэки, i18n=None, контекстное меню ═══════════
print("== v0.9.9.4 sidebar panel: unit level ==")

# Без i18n (translate_fn=None): русские литералы с момента конструирования, retranslate no-op
panel_ru = SB.SidebarPanel(translate_fn=None, actions={k: (lambda n: None) for k in
                                 ("ssh", "external", "edit", "copy_ip", "copy_hostname",
                                  "ping", "collect_info", "reveal", "delete")}, show_title=False)
check("panel without i18n keeps Russian button literals", panel_ru.btn_add.text() == "Добавить сервер",
      panel_ru.btn_add.text())
check("panel without i18n: no title label (as before v0.9.9.4)", panel_ru.title_label is None)
panel_ru.retranslate()  # no-op — не должно пасть и ничего не менять
check("panel without i18n: retranslate is a safe no-op", panel_ru.btn_add.text() == "Добавить сервер")

# Недостающий колбэк действия → ValueError (fail fast при неверной сборке)
try:
    SB.SidebarPanel(translate_fn=None, actions={"ssh": lambda n: None}, show_title=False)
    check("panel raises ValueError on missing action callback", False, "no exception")
except ValueError as e:
    check("panel raises ValueError on missing action callback", "ssh" in str(e) or "нет колбэков" in str(e), str(e))

# fill_context_menu: 9 пунктов + 4 разделителя в порядке ROADMAP v0.9.6, подписи — i18n
_calls = []
panel_ctx = SB.SidebarPanel(translate_fn=_t, actions={k: (lambda n, _k=k: _calls.append(_k))
                                   for k in ("ssh", "external", "edit", "copy_ip",
                                             "copy_hostname", "ping", "collect_info",
                                             "reveal", "delete")}, show_title=False)
fake_node = ServerData(id="sp7c", alias="ctx", host="10.30.0.9", user="u")
menu = QMenu()
panel_ctx.fill_context_menu(menu, fake_node)
_actions = [a for a in menu.actions() if not a.isSeparator()]
_seps = sum(1 for a in menu.actions() if a.isSeparator())
check("fill_context_menu: exactly 9 actions", len(_actions) == 9, f"got {len(_actions)}")
check("fill_context_menu: grouped by 4 separators", _seps == 4, f"separators={_seps}")
_expected = [_t(k) for k in ("ctx.ssh_connect", "ctx.ssh_external", "ctx.edit_server",
                             "ctx.copy_ip", "ctx.copy_hostname", "ctx.ping",
                             "ctx.collect_info", "ctx.reveal_on_map", "ctx.delete_server")]
check("fill_context_menu: action order + i18n labels per ROADMAP v0.9.6",
      [a.text() for a in _actions] == _expected, str([a.text() for a in _actions]))
_actions[3].trigger()  # ctx.copy_ip
check("context menu action triggers its callback with the node", _calls == ["copy_ip"], str(_calls))

# ══ 4. РЕГРЕССИЯ БАГА v0.9.2: строки сайдбара переживают смену языка ═══════
print("== v0.9.9.4 sidebar panel: retranslate on language switch ==")

# Базовые строки на текущем языке (ru по умолчанию в изолированном HOME)
btn_ru = win.btn_add.text()
title_ru = win._sidebar_title.text()
ph_ru = win.search_edit.placeholderText()
alltags_ru = win.tag_filter.itemText(0)
check("baseline: sidebar strings are translated (not raw keys)",
      btn_ru == _t("btn.add_server") and title_ru == _t("server.title")
      and ph_ru == _t("search.placeholder") and alltags_ru == _t("filter.all_tags"),
      f"{btn_ru!r}/{title_ru!r}")

# Выбор тег-фильтра, который должен пережить retranslate
win.tag_filter.setCurrentIndex(win.tag_filter.findData("prod"))

# Смена языка — полный путь окна (set_language → _apply_ui_translations → panel.retranslate)
win._switch_language("en")
check("after switch to en: button label retranslated", win.btn_add.text() == _t("btn.add_server"),
      f"{win.btn_add.text()!r} want {_t('btn.add_server')!r}")
check("after switch to en: title retranslated", win._sidebar_title.text() == _t("server.title"),
      repr(win._sidebar_title.text()))
check("after switch to en: search placeholder retranslated",
      win.search_edit.placeholderText() == _t("search.placeholder"),
      repr(win.search_edit.placeholderText()))
check("after switch to en: 'All tags' label retranslated (not lost)",
      win.tag_filter.itemText(0) == _t("filter.all_tags"), repr(win.tag_filter.itemText(0)))
check("tag filter selection survives retranslate",
      win.tag_filter.currentData() == "prod", repr(win.tag_filter.currentData()))

# Обратно: строки возвращаются на русский (реестр применяется повторно)
win._switch_language("ru")
check("back to ru: button label restored", win.btn_add.text() == btn_ru, f"{win.btn_add.text()!r} want {btn_ru!r}")
check("back to ru: title restored", win._sidebar_title.text() == title_ru)
check("back to ru: placeholder restored", win.search_edit.placeholderText() == ph_ru)
check("back to ru: 'All tags' label restored", win.tag_filter.itemText(0) == alltags_ru)
win.tag_filter.setCurrentIndex(0)

finish()
