# -*- coding: utf-8 -*-
"""v1.1.1 — Мелкие опции вокруг хаба: тематический тест релиза (ROADMAP v1.1.1).

Пункты ROADMAP v1.1.1 (каждый независимо шиппабелен, здесь покрыт своим блоком):
  #1 Шрифты — ui_font_family/ui_font_size (UI) + terminal_font (терминал, ключ
     читался с v1.0, UI впервые); применение на лету без перезапуска:
     QApplication.setFont + widget.set_font() в открытые окна терминала;
  #2 Английский по умолчанию — i18n._default_language "ru" → "en": влияет только
     на новых пользователей (без config.json); у существующих get_last_language()
     возвращает сохранённый язык;
  #3 Лимит своих терминалов = 4 — terminal_max_open (дефолт 4); при достижении
     не отказ, а предложение закрыть СТАРЕЙШУЮ сессию / отмена (_spawn_terminal_window);
  #4 Двойной клик по узлу — ui_node_double_click "properties"|"connect"
     ("connect" → _run_ssh_connect(node) сразу открывает SSHConnectDialog);
  #5 Скрытие кнопочного блока сайдбара — ui_show_sidebar_buttons (дефолт True) +
     SidebarPanel.set_buttons_visible(bool); весь сайдбар — пункт меню «Вид → Сайдбар»;
  #6 Плашка связи — тип на плашке (ui_show_connection_type: «SSH · <метка>») +
     лимит 20 символов метки (setMaxLength(20) в ConnectionDialog/EditConnectionDialog,
     только на ввод — старые проекты с длинными метками читаются без изменений).

Хранение — ЕДИНЫЙ ~/.sshmap/config.json; все ключи опциональны, дефолты = поведение
v1.1. i18n: +14 ключей × en/ru/zh (паритет 359 → 373).

Запуск: python tests/test_settings_options.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция внутри)

from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication(sys.argv)

# ВАЖНО: i18n импортируется ДО любой записи в config.json — свежая песочница HOME
# без ~/.sshmap/config.json = «новый пользователь» (проверка пункта #2).
import i18n
from models.server import ServerData
from graphics.map_scene import MapScene
from graphics.connection_arrow import ConnectionArrow, label_display_text
from dialogs.connection_dialog import ConnectionDialog, EditConnectionDialog
from ui.settings_dialog import SettingsDialog, load_ui_settings
from modules.ssh_terminal import load_terminal_settings

CFG_PATH = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def read_cfg():
    if not os.path.isfile(CFG_PATH):
        return None
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_cfg(d):
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


def clear_cfg():
    try:
        os.remove(CFG_PATH)
    except OSError:
        pass


# ════════════════════════════════════════════════════════════
# 0. i18n: +14 ключей × en/ru/zh, паритет 359 → 373
# ════════════════════════════════════════════════════════════
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = [
    "settings.general.ui_font_family", "settings.general.ui_font_size",
    "settings.ui_font_system", "settings.terminal.font_family",
    "settings.terminal.max_open", "msg.terminal_limit_title",
    "msg.terminal_limit_close_oldest", "settings.map.node_double_click",
    "settings.map.node_double_click.properties", "settings.map.node_double_click.connect",
    "settings.general.sidebar_buttons", "view.toggle_sidebar",
    "settings.map.show_connection_type", "connection.label_hint",
]
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("14 новых ключей v1.1.1 есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (373 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 373 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# ════════════════════════════════════════════════════════════
# 1. Пункт #2: английский по умолчанию (только для новых пользователей)
# ════════════════════════════════════════════════════════════
print("== default language ==")
check("новый пользователь (без config.json): язык по умолчанию — en",
      i18n.get_current_language() == "en", i18n.get_current_language())
check("i18n._default_language == 'en' (было 'ru')", i18n._default_language == "en")
write_cfg({"language": "ru"})
check("существующий пользователь: сохранённый язык ru читается (get_last_language)",
      i18n.get_last_language() == "ru", i18n.get_last_language())
clear_cfg()

# ════════════════════════════════════════════════════════════
# 2. Пункт #1: шрифты — load_ui_settings() (валидатор) + live-применение
# ════════════════════════════════════════════════════════════
print("== fonts ==")
clear_cfg()
s = load_ui_settings()
check("load_ui_settings: дефолты (без конфига)",
      s == {"font_family": "", "font_size": None, "node_double_click": "properties",
            "show_sidebar_buttons": True, "show_connection_type": False}, str(s))

write_cfg({"ui_font_family": " Courier New ", "ui_font_size": 14,
           "ui_node_double_click": " connect ", "ui_show_sidebar_buttons": False,
           "ui_show_connection_type": True})
s = load_ui_settings()
check("load_ui_settings: валидные значения читаются (trim пробелов)",
      s == {"font_family": "Courier New", "font_size": 14, "node_double_click": "connect",
            "show_sidebar_buttons": False, "show_connection_type": True}, str(s))

write_cfg({"ui_font_family": 42, "ui_font_size": "big", "ui_node_double_click": "yell",
           "ui_show_sidebar_buttons": "yes", "ui_show_connection_type": 1})
s = load_ui_settings()
check("load_ui_settings: битые значения (чужие типы) → дефолты",
      s == {"font_family": "", "font_size": None, "node_double_click": "properties",
            "show_sidebar_buttons": True, "show_connection_type": False}, str(s))

write_cfg({"ui_font_size": 0})
check("load_ui_settings: ui_font_size=0 → системный размер (None)",
      load_ui_settings()["font_size"] is None)
write_cfg({"ui_font_size": 99})
check("load_ui_settings: ui_font_size вне диапазона (99) → None",
      load_ui_settings()["font_size"] is None)
clear_cfg()

# Диалог настроек: новые поля + prefill + collect()
write_cfg({"ui_font_family": "Consolas", "ui_font_size": 12, "terminal_font": "JetBrains Mono",
           "terminal_max_open": 6, "ui_node_double_click": "connect",
           "ui_show_sidebar_buttons": False, "ui_show_connection_type": True})
dlg = SettingsDialog(None)
check("«Общие»: поле семейства UI-шрифта + спин размера (0 = системный)",
      dlg.ui_font_family_edit.text() == "Consolas" and dlg.ui_font_size_spin.value() == 12
      and dlg.ui_font_size_spin.minimum() == 0)
check("«Терминал»: поле семейства терминального шрифта + спин лимита (1..16)",
      dlg.term_font_family_edit.text() == "JetBrains Mono"
      and dlg.max_open_spin.value() == 6
      and dlg.max_open_spin.minimum() == 1 and dlg.max_open_spin.maximum() == 16)
check("«Карта»: комбо двойного клика (properties/connect) + чекбокс «тип на плашке»",
      [dlg.node_dblclick_combo.itemData(i) for i in range(dlg.node_dblclick_combo.count())]
      == ["properties", "connect"]
      and dlg.node_dblclick_combo.currentData() == "connect"
      and dlg.show_conn_type_chk.isChecked() is True)
check("«Общие»: чекбокс кнопок сайдбара (prefill False из конфига)",
      dlg.sidebar_buttons_chk.isChecked() is False)
c = dlg.collect()
check("collect(): новые ключи v1.1.1 со значениями",
      c.get("ui_font_family") == "Consolas" and c.get("ui_font_size") == 12
      and c.get("terminal_font") == "JetBrains Mono" and c.get("terminal_max_open") == 6
      and c.get("ui_node_double_click") == "connect"
      and c.get("ui_show_sidebar_buttons") is False
      and c.get("ui_show_connection_type") is True, str(c))

# Live-применение: MainWindow + QApplication.setFont + шрифт открытых окон терминала
import ui.main_window as MW

clear_cfg()
win = MW.MainWindow()
win.show()
app.processEvents()

write_cfg({"ui_font_family": "Consolas", "ui_font_size": 14,
           "terminal_font": "DejaVu Sans Mono", "terminal_font_size": 13})


class _FakeTermWidget:
    def __init__(self):
        self.font_calls = []

    def set_font(self, family="", size=10):
        self.font_calls.append((family, size))


class _FakeTermWindow(QObject):
    """Фейковое окно терминала (без SSH): только то, что трогает MainWindow."""
    destroyed = QtSignal()

    def __init__(self, server_data, parent=None, password=None, initial_command=""):
        super().__init__()
        self.server_data = server_data
        self.widget = _FakeTermWidget()
        self.closed = False
        self._force_close = False

    def show(self):
        pass

    def close_terminal(self):
        self.closed = True


win._terminal_windows.append(
    _FakeTermWindow(ServerData(id="fw1", alias="font-win", host="10.99.0.1", user="root")))
win._apply_settings_from_dialog()
app_font = app.font()
check("live: шрифт UI применён к QApplication (Consolas 14) без перезапуска",
      app_font.family() == "Consolas" and app_font.pointSize() == 14,
      f"{app_font.family()} {app_font.pointSize()}")
fw = win._terminal_windows[0]
check("live: шрифт терминала применён в открытое окно (DejaVu Sans Mono 13)",
      fw.widget.font_calls == [("DejaVu Sans Mono", 13)], str(fw.widget.font_calls))

# Без ключей шрифтов — приложение не трогает текущий шрифт
clear_cfg()
app.setFont(app.font())  # запомним «текущий» (Consolas 14) как базу
base_family, base_size = app_font.family(), app_font.pointSize()
win._apply_settings_from_dialog()
check("live: без ключей шрифтов в конфиге — шрифт не меняется",
      app.font().family() == base_family and app.font().pointSize() == base_size)
win._terminal_windows.clear()

# ════════════════════════════════════════════════════════════
# 3. Пункт #3: лимит своих терминалов (terminal_max_open, дефолт 4)
# ════════════════════════════════════════════════════════════
print("== terminal limit ==")
clear_cfg()
check("load_terminal_settings: max_open дефолт 4", load_terminal_settings()["max_open"] == 4)

win2 = MW.MainWindow()
win2.show()
app.processEvents()


def _mk(alias, host="10.98.0.1"):
    return _FakeTermWindow(ServerData(id=f"lim-{alias}", alias=alias, host=host, user="root"))


asked = []
_limit_result = [QMessageBox.Close]
_orig_question = MW.QMessageBox.question
_orig_win_cls = MW.SSHTerminalWindow  # ДО try: finally восстанавливает даже при крахе тела


def _fake_question(parent, title, text, buttons=0, default=0):
    asked.append((title, text))
    return _limit_result[0]


MW.QMessageBox.question = staticmethod(_fake_question)
try:
    # Ниже лимита (3 < 4) — без диалога, окно создаётся напрямую
    win2._terminal_windows.extend([_mk("a"), _mk("b"), _mk("c")])

    class _SpawnedRecorder(_FakeTermWindow):
        created = []

        def __init__(self, server_data, parent=None, password=None, initial_command=""):
            super().__init__(server_data, parent, password, initial_command)
            _SpawnedRecorder.created.append(self)

    MW.SSHTerminalWindow = _SpawnedRecorder
    node3 = win2.scene.add_server(
        ServerData(id="lim-d", alias="d", host="10.98.0.4", user="root"))
    asked.clear()
    w_new = win2._spawn_terminal_window(node3)
    check("ниже лимита (3<4): диалог не показан, окно создано",
          len(asked) == 0 and w_new is not None and len(win2._terminal_windows) == 4)

    # На лимите (4 >= 4): предложение закрыть старейшую → Close → старейшая закрыта
    asked.clear()
    _limit_result[0] = QMessageBox.Close
    node4 = win2.scene.add_server(
        ServerData(id="lim-e", alias="e", host="10.98.0.5", user="root"))
    oldest_before = win2._terminal_windows[0]
    w_new2 = win2._spawn_terminal_window(node4)
    check("на лимите (4>=4): показан диалог про старейшую сессию",
          len(asked) == 1 and asked[0][0] == i18n.t("msg.terminal_limit_title"),
          str(asked))
    check("текст диалога: лимит + alias старейшей («a»)",
          "4" in asked[0][1] and "«a»" in asked[0][1], asked[0][1])
    check("Close: старейшая закрыта (close_terminal + _force_close против повторного 'ask')",
          oldest_before.closed is True and oldest_before._force_close is True)
    check("Close: старейшая убрана из реестра, новое окно создано (снова 4)",
          w_new2 is not None and win2._terminal_windows[0] is not oldest_before
          and len(win2._terminal_windows) == 4
          and win2._terminal_windows[-1] is w_new2)

    # На лимите: Отмена → окно не создаётся, реестр не тронут
    asked.clear()
    _limit_result[0] = QMessageBox.Cancel
    node5 = win2.scene.add_server(
        ServerData(id="lim-f", alias="f", host="10.98.0.6", user="root"))
    list_before = list(win2._terminal_windows)
    w_cancel = win2._spawn_terminal_window(node5)
    check("Cancel: новое окно НЕ создано (None), реестр не изменился, диалог был",
          w_cancel is None and len(asked) == 1
          and list(win2._terminal_windows) == list_before)

    # Лимит из конфига (terminal_max_open=2): срабатывает раньше
    write_cfg({"terminal_max_open": 2})
    asked.clear()
    _limit_result[0] = QMessageBox.Close
    node6 = win2.scene.add_server(
        ServerData(id="lim-g", alias="g", host="10.98.0.7", user="root"))
    w_new3 = win2._spawn_terminal_window(node6)
    check("terminal_max_open=2: лимит читается из конфига (диалог при 4 открытых)",
          len(asked) == 1 and "2" in asked[0][1] and w_new3 is not None, str(asked))
finally:
    MW.QMessageBox.question = _orig_question
    MW.SSHTerminalWindow = _orig_win_cls
    clear_cfg()

# ════════════════════════════════════════════════════════════
# 4. Пункт #4: двойной клик по узлу (ui_node_double_click)
# ════════════════════════════════════════════════════════════
print("== node double-click mode ==")
clear_cfg()
win3 = MW.MainWindow()
win3.show()
app.processEvents()
node_dc = win3.scene.add_server(
    ServerData(id="dc1", alias="dblclick", host="10.97.0.1", user="root"))

check("дефолт (без конфига): режим 'properties' (поведение v1.1)",
      win3._node_double_click_mode == "properties")

# connect: двойной клик → _run_ssh_connect(node)
write_cfg({"ui_node_double_click": "connect"})
win3._apply_ui_options_from_config()
check("конфиг 'connect': кэш режима обновлён", win3._node_double_click_mode == "connect")
dc_calls = []
win3._run_ssh_connect = lambda n, **kw: dc_calls.append(n.data.id)  # noqa: E731
win3._on_node_double_click_direct(node_dc)
check("'connect': двойной клик открыл _run_ssh_connect(node)",
      dc_calls == ["dc1"], str(dc_calls))

# properties (дефолт): диалог свойств, SSH-диалог НЕ открывается
clear_cfg()
win3._apply_ui_options_from_config()


class _FakeAddServerDialog(QDialog):
    def __init__(self, parent=None, edit_data=None):
        super().__init__(parent)
        self.edit_data = edit_data

    def exec(self):  # noqa: A003 — имитация отказа пользователя
        return QDialog.Rejected


_orig_add_dlg = MW.AddServerDialog
MW.AddServerDialog = _FakeAddServerDialog
try:
    win3._on_node_double_click_direct(node_dc)
    check("'properties': диалог свойств, _run_ssh_connect не вызван",
          dc_calls == ["dc1"])  # список не вырос
finally:
    MW.AddServerDialog = _orig_add_dlg
    del win3._run_ssh_connect

# Битое значение → дефолт properties
write_cfg({"ui_node_double_click": "yell"})
win3._apply_ui_options_from_config()
check("битое ui_node_double_click ('yell') → дефолт 'properties'",
      win3._node_double_click_mode == "properties")
clear_cfg()

# ════════════════════════════════════════════════════════════
# 5. Пункт #5: кнопочный блок сайдбара + пункт меню «Вид → Сайдбар»
# ════════════════════════════════════════════════════════════
print("== sidebar buttons ==")
from ui.sidebar import SidebarPanel, _BUTTONS

panel = SidebarPanel(translate_fn=i18n.t, actions={
    k: (lambda n, _k=k: None) for k in
    ("ssh", "external", "edit", "copy_ip", "copy_hostname", "ping",
     "collect_info", "reveal", "delete")})
panel.show()
app.processEvents()
panel.set_buttons_visible(False)
app.processEvents()
check("set_buttons_visible(False): все 6 кнопок скрыты",
      all(not getattr(panel, attr).isVisible() for attr, *_ in _BUTTONS))
panel.set_buttons_visible(True)
app.processEvents()
check("set_buttons_visible(True): все 6 кнопок видны снова (layout перестроен)",
      all(getattr(panel, attr).isVisible() for attr, *_ in _BUTTONS))

# MainWindow: настройка + пункт меню
clear_cfg()
win4 = MW.MainWindow()
win4.show()
app.processEvents()
check("меню «Вид»: checkable-пункт 'Сайдбар' (checked по умолчанию)",
      getattr(win4, "act_show_sidebar", None) is not None
      and win4.act_show_sidebar.isCheckable() and win4.act_show_sidebar.isChecked())

write_cfg({"ui_show_sidebar_buttons": False})
win4._apply_settings_from_dialog()
app.processEvents()
check("конфиг ui_show_sidebar_buttons=False: блок кнопок скрыт",
      all(not getattr(win4, attr).isVisible() for attr, *_ in _BUTTONS))
check("дерево/поиск сайдбара при этом видны (прятается только блок кнопок)",
      win4.tree.isVisible() and win4.search_edit.isVisible())

write_cfg({"ui_show_sidebar_buttons": True})
win4._apply_settings_from_dialog()
app.processEvents()
check("конфиг ui_show_sidebar_buttons=True: кнопки вернулись",
      all(getattr(win4, attr).isVisible() for attr, *_ in _BUTTONS))

# Пункт меню — способ вернуть ВЕСЬ сайдбар. PySide6 6.11: trigger() на checkable-
# действии = клик по пункту (сам инвертирует checked и эмитит triggered с НОВЫМ
# состоянием), поэтому setChecked+trigger здесь двойная инверсия — один trigger().
win4.act_show_sidebar.trigger()
app.processEvents()
check("меню «Вид → Сайдбар» (снять): весь сайдбар скрыт", win4.sidebar.isHidden())
win4.act_show_sidebar.trigger()
app.processEvents()
check("меню «Вид → Сайдбар» (поставить): сайдбар вернулся", not win4.sidebar.isHidden())
clear_cfg()

# ════════════════════════════════════════════════════════════
# 6. Пункт #6: плашка связи — тип на плашке + лимит 20 символов метки
# ════════════════════════════════════════════════════════════
print("== connection label ==")
clear_cfg()
check("label_display_text: опция выключена → только метка",
      label_display_text("ssh", "web") == "web")
write_cfg({"ui_show_connection_type": True})
check("label_display_text: опция включена → «SSH · web»",
      label_display_text("ssh", "web") == f"{i18n.t('connection.type.ssh')} · web")
check("label_display_text: без метки → сам тип («VPN»)",
      label_display_text("vpn", "") == i18n.t("connection.type.vpn"))

# E2E: стрелка на сцене + refresh_label() после смены опции (без пересоздания).
# Конфиг очищаем: стрелка создаётся при ВЫКЛЕННОЙ опции (на плашке только метка) —
# иначе унаследует ui_show_connection_type=True из функциональных проверок выше.
clear_cfg()
scene = MapScene()
na = scene.add_server(ServerData(id="ca", alias="A", host="10.96.0.1", user="root"))
nb = scene.add_server(ServerData(id="cb", alias="B", host="10.96.0.2", user="root"))
arrow = scene.add_connection("ca", "cb", label="web", ctype="ssh")
check("стрелка: опция выключена → текст метки «web»",
      arrow._label.toPlainText() == "web", arrow._label.toPlainText())
write_cfg({"ui_show_connection_type": True})
arrow.refresh_label()
check("refresh_label(): после включения опции → «SSH · web» (без пересоздания)",
      arrow._label.toPlainText() == f"{i18n.t('connection.type.ssh')} · web",
      arrow._label.toPlainText())
clear_cfg()
arrow.refresh_label()
check("refresh_label(): после выключения опции → снова «web»",
      arrow._label.toPlainText() == "web")

# Диалоги: лимит 20 символов — только на ввод
nodes = [na, nb]
cdlg = ConnectionDialog(nodes, None)
check("ConnectionDialog: label.maxLength() == 20 + подсказка в i18n",
      cdlg.label.maxLength() == 20
      and cdlg.label.placeholderText() == i18n.t("connection.label_hint"))

long_label = "x" * 30  # старая метка из чужого проекта длиннее лимита
arrow_long = scene.add_connection("cb", "ca", label=long_label, ctype="vpn")
edlg = EditConnectionDialog(arrow_long, None)
check("EditConnectionDialog: maxLength() == 20", edlg.label.maxLength() == 20)
check("EditConnectionDialog: старая длинная метка (30 символов) НЕ обрезана",
      edlg.label.text() == long_label and len(edlg.label.text()) == 30,
      f"len={len(edlg.label.text())}")

# ════════════════════════════════════════════════════════════
# 7. Состояние релиза v1.1.1
# ════════════════════════════════════════════════════════════
print("== release state ==")
from version import APP_VERSION

check("APP_VERSION == '1.1.1'", APP_VERSION == "1.1.1", APP_VERSION)
try:
    import tomllib as _toml
except ImportError:  # Python < 3.11
    import tomli as _toml
with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
    _pp = _toml.load(f)
check("pyproject version == APP_VERSION (1.1.1)",
      _pp["project"]["version"] == "1.1.1", _pp["project"]["version"])

clear_cfg()
finish()
