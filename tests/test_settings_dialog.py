"""v1.1 — Диалог настроек (хаб): тематический тест релиза.

ROADMAP v1.1 (задачи 1–7):
  #1 Каркас — QTabWidget «Общие / Терминал / Статусы / Автосохранение / Карта / Язык»
     (вкладка «Горячие клавиши» появится в v1.3);
  #2 Точки входа — пункт меню «Настройки» МЕЖДУ «Вид» и «Помощь» + кнопка ⚙ внизу
     сайдбара (6-я в ui/sidebar.py _BUTTONS, сигнал settings_clicked) + векторная
     шестерёнка (ui/icons.py); палитра команд (Ctrl+K) подхватывает пункт автоматически;
  #3 Вкладка «Терминал» — палитра/размер шрифта/глубина истории (ключи v1.0 terminal_*)
     + поведение закрытия сессии (новый ключ terminal_close_behavior: "close"|"ask";
     "ask" → подтверждение в closeEvent, только для активной сессии);
  #4 Вкладка «Статусы» — интервал проверок и таймаут пробы StatusChecker
     (status_interval_sec / status_probe_timeout_sec; дефолты 30 c / 3.0 c = v1.0;
     на лету — set_interval/set_probe_timeout после ОК);
  #5 Вкладка «Автосохранение» — вкл/выкл, интервал, число бэкапов (ключи v0.9.7);
  #6 Вкладка «Язык» — переключатель en/ru/zh с немедленным применением
     (сигнал language_changed ДО ОК; пункт «Помощь → Язык» сохранён);
  #7 Единый файл настроек — ключ external_terminal перенесён из отдельного
     ~/.sshmap_settings.json в config.json (миграция при чтении, старый файл удаляется).

Хранение — ЕДИНЫЙ ~/.sshmap/config.json (i18n.load_config/save_config, атомарная
merge-запись); все ключи опциональны, дефолты = текущее поведение. i18n: +33 ключа ×
en/ru/zh в v1.1 (паритет 326 → 359) + 14 в v1.1.1 (опции вокруг хаба — паритет 373;
свой тематический тест — tests/test_settings_options.py).

Запуск: python tests/test_settings_dialog.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция внутри)

from PySide6.QtCore import QThread, Signal as QtSignal
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
from modules.external_terminal import (
    TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
    load_external_terminal_setting, save_external_terminal_setting,
    _legacy_settings_path,
)
from models.server import ServerData
from services.status_checker import StatusChecker, get_status_settings
from ui.icons import get_icon
from ui.sidebar import SidebarPanel, _BUTTONS
from ui.settings_dialog import SettingsDialog

CFG_PATH = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
LEGACY_PATH = _legacy_settings_path()


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
    for p in (CFG_PATH, LEGACY_PATH):
        try:
            os.remove(p)
        except OSError:
            pass


# ════════════════════════════════════════════════════════════
# 1. i18n: +33 ключа × en/ru/zh, паритет 326 → 373
# ════════════════════════════════════════════════════════════
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = [
    "settings.title", "settings.ok", "settings.cancel",
    "settings.tab.general", "settings.tab.terminal", "settings.tab.statuses",
    "settings.tab.autosave", "settings.tab.map", "settings.tab.language",
    "settings.open", "menu.settings", "btn.settings", "status.settings_saved",
    "settings.general.external_terminal",
    "settings.terminal.palette", "settings.terminal.palette.default",
    "settings.terminal.palette.nord", "settings.terminal.palette.dracula",
    "settings.terminal.palette.tokyo_night", "settings.terminal.font_size",
    "settings.terminal.history_lines", "settings.terminal.close_behavior",
    "settings.terminal.close_behavior.close", "settings.terminal.close_behavior.ask",
    "settings.statuses.interval", "settings.statuses.timeout",
    "settings.autosave.enabled", "settings.autosave.interval",
    "settings.autosave.backups", "settings.map.placeholder",
    "settings.language.label", "msg.close_session_title", "msg.confirm_close_session",
]
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("33 новых ключа v1.1 есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (373 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 373 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# ════════════════════════════════════════════════════════════
# 2. Иконка шестерёнки (ui/icons.py)
# ════════════════════════════════════════════════════════════
print("== gear icon ==")
ic = get_icon("settings")
pm = ic.pixmap(20, 20)
check("get_icon('settings') — непустой QIcon с pixmap 20×20",
      not ic.isNull() and not pm.isNull() and (pm.width(), pm.height()) == (20, 20))
img = pm.toImage()
ink = sum(1 for y in range(img.height()) for x in range(img.width())
          if img.pixelColor(x, y).alpha() > 0)
check("шестерёнка нарисована (чернила на прозрачном канвасе)", ink > 40, f"ink={ink}")

# ════════════════════════════════════════════════════════════
# 3. Кнопка ⚙ сайдбара: 6-я в _BUTTONS + сигнал settings_clicked
# ════════════════════════════════════════════════════════════
print("== sidebar button ==")
check("_BUTTONS: ровно 6 кнопок, 6-я — (btn_settings, settings, btn.settings)",
      len(_BUTTONS) == 6 and _BUTTONS[-1] == ("btn_settings", "settings",
                                              "btn.settings", "Настройки"),
      str(_BUTTONS))
_actions = {k: (lambda node, _k=k: None) for k in
            ("ssh", "external", "edit", "copy_ip", "copy_hostname", "ping",
             "collect_info", "reveal", "delete")}
sb = SidebarPanel(translate_fn=i18n.t, actions=_actions)
check("btn_settings существует и несёт векторную шестерёнку",
      hasattr(sb, "btn_settings") and not sb.btn_settings.icon().isNull())
clicks = []
sb.settings_clicked.connect(lambda: clicks.append(1))
sb.btn_settings.click()
check("клик по ⚙ → settings_clicked (ровно один раз)", len(clicks) == 1, str(clicks))
check("подпись кнопки переведена (btn.settings)",
      sb.btn_settings.text() == i18n.t("btn.settings"), sb.btn_settings.text())

# ════════════════════════════════════════════════════════════
# 4. Задача 7: external_terminal — единый config.json + миграция
# ════════════════════════════════════════════════════════════
print("== external terminal: single config.json ==")
clear_cfg()
check("свежий HOME: load → 'auto', файл не создаётся",
      load_external_terminal_setting() == "auto" and read_cfg() is None)

with open(LEGACY_PATH, "w", encoding="utf-8") as f:
    json.dump({"external_terminal": "cmd"}, f)
v = load_external_terminal_setting()
cfg = read_cfg()
check("legacy 'cmd' из ~/.sshmap_settings.json → миграция в config.json",
      v == "cmd" and cfg is not None and cfg.get("external_terminal") == "cmd",
      f"v={v!r} cfg={cfg}")
check("старый файл удалён после успешной миграции", not os.path.exists(LEGACY_PATH))

# Ключ уже в config.json → legacy игнорируется (ничего не перезаписывается)
write_cfg({"external_terminal": "conhost"})
with open(LEGACY_PATH, "w", encoding="utf-8") as f:
    json.dump({"external_terminal": "cmd"}, f)
v = load_external_terminal_setting()
check("config.json приоритетнее legacy (без перезаписи)",
      v == "conhost" and read_cfg().get("external_terminal") == "conhost", f"v={v!r}")

# save пишет ТОЛЬКО в config.json (legacy не создаётся)
os.remove(LEGACY_PATH)
save_val = "cmd" if sys.platform == "win32" else "gnome-terminal"
ok = save_external_terminal_setting(save_val)
check("save_external_terminal_setting → config.json, legacy не создаётся",
      ok and read_cfg().get("external_terminal") == save_val
      and not os.path.exists(LEGACY_PATH))

write_cfg({"external_terminal": "no-such-terminal"})
check("битое значение в config.json → 'auto'", load_external_terminal_setting() == "auto")
clear_cfg()

# ════════════════════════════════════════════════════════════
# 5. Задача 4: настройки статусов (get_status_settings + на лету)
# ════════════════════════════════════════════════════════════
print("== status settings ==")
clear_cfg()
st = get_status_settings()
check("нет конфига → дефолты v1.0 (30 c / 3.0 c)",
      st == {"interval_sec": 30, "probe_timeout_sec": 3.0}, str(st))
write_cfg({"status_interval_sec": 45, "status_probe_timeout_sec": 2.5})
st = get_status_settings()
check("валидные значения читаются (45 c / 2.5 c)",
      st == {"interval_sec": 45, "probe_timeout_sec": 2.5}, str(st))
write_cfg({"status_interval_sec": 1, "status_probe_timeout_sec": 99})
st = get_status_settings()
check("клампы: interval ≥ 5 c, timeout ≤ 60 c",
      st == {"interval_sec": 5, "probe_timeout_sec": 60.0}, str(st))
write_cfg({"status_interval_sec": True, "status_probe_timeout_sec": "abc"})
st = get_status_settings()
check("битые значения (bool/str) → дефолты",
      st == {"interval_sec": 30, "probe_timeout_sec": 3.0}, str(st))

chk = StatusChecker(parent=None)
chk.set_interval(1000)
check("set_interval: кламп не чаще раза в 5 c", chk.interval_ms == 5000,
      str(chk.interval_ms))
chk.set_interval(60000)
chk.set_probe_timeout(0.01)
check("set_interval/set_probe_timeout применяются (timeout-кламп ≥ 0.2)",
      chk.interval_ms == 60000 and abs(chk.probe_timeout - 0.2) < 1e-9,
      f"interval={chk.interval_ms} timeout={chk.probe_timeout}")
clear_cfg()

# ════════════════════════════════════════════════════════════
# 6. Задача 3: поведение закрытия сессии (terminal_close_behavior)
# ════════════════════════════════════════════════════════════
print("== terminal close behavior ==")


class _FakeChannel:
    closed = False

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)


class _FakeSSHThread(QThread):
    """Фейковый SSH-поток (паттерн test_terminal_acceptance.py) + детерминированный
    isRunning: активная сессия симулируется флагом _running_override."""

    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.channel = _FakeChannel()
        self.running = True
        self._running_override = False

    def isRunning(self):
        if self._running_override:
            return True
        return super().isRunning()

    def run(self):  # реальный SSH не нужен
        pass

    def stop(self):
        self.running = False

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            self.channel.send(data_bytes)


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread
term_windows = []


def alive(w):
    """Жив ли C++-объект окна (WA_DeleteOnClose: после accept — уже уничтожен)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


def make_term(alias):
    # ВАЖНО: show() ДО close() — WA_DeleteOnClose удаляет окно только если оно
    # хотя бы раз было видимо (проверено offscreen, Qt 6.11: close() невидимого
    # окна принимает событие, но C++-объект живёт).
    w = ST.SSHTerminalWindow(
        ServerData(id=f"set-{alias}", alias=alias, host="10.98.0.1", user="root"),
        None, password="pw")
    term_windows.append(w)
    w.resize(700, 500)
    w.show()
    app.processEvents()
    return w


asked = []
_question_result = [QMessageBox.StandardButton.Cancel]
_orig_question = ST.QMessageBox.question


def _fake_question(*a, **k):
    asked.append(a[1] if len(a) > 1 else None)
    return _question_result[0]


ST.QMessageBox.question = staticmethod(_fake_question)

try:
    # "ask" + активная сессия → подтверждение; Cancel → окно живёт
    write_cfg({"terminal_close_behavior": "ask"})
    w = make_term("ask1")
    check("окно читает terminal_close_behavior из конфига ('ask')",
          getattr(w, "_close_behavior", None) == "ask",
          str(getattr(w, "_close_behavior", None)))
    w.terminal_thread._running_override = True  # активная сессия
    w.close()
    app.processEvents()
    check("'ask' + активная сессия: показано подтверждение (msg.confirm_close_session)",
          len(asked) == 1 and asked[0] == i18n.t("msg.close_session_title"), str(asked))
    check("Cancel → окно живёт (event.ignore, WA_DeleteOnClose не сработал)",
          alive(w))

    _question_result[0] = QMessageBox.StandardButton.Close
    asked.clear()
    w.close()
    app.processEvents()
    check("'ask' + Close: подтверждение снова, окно закрывается",
          len(asked) == 1 and not alive(w), f"asked={asked}")

    # "close" (дефолт v1.0) + активная сессия → без диалога
    clear_cfg()
    w2 = make_term("cl1")
    check("нет конфига → дефолт 'close' (поведение v1.0)",
          getattr(w2, "_close_behavior", None) == "close")
    w2.terminal_thread._running_override = True
    asked.clear()
    w2.close()
    app.processEvents()
    check("'close' + активная сессия: без диалога, окно закрывается",
          len(asked) == 0 and not alive(w2), f"asked={asked}")

    # "ask", но сессия уже завершена → без диалога
    write_cfg({"terminal_close_behavior": "ask"})
    w3 = make_term("ask2")
    w3.terminal_thread.wait(2000)  # гарантированно неактивная сессия (без гонки)
    asked.clear()
    w3.close()
    app.processEvents()
    check("'ask' + завершённая сессия: без диалога", len(asked) == 0 and not alive(w3),
          f"asked={asked}")
finally:
    ST.QMessageBox.question = _orig_question
    ST.SSHTerminalThread = _orig_thread_cls
    clear_cfg()

# ════════════════════════════════════════════════════════════
# 7. Диалог: 6 вкладок, виджеты, prefill из конфига, collect/OK/Cancel
# ════════════════════════════════════════════════════════════
print("== settings dialog ==")
clear_cfg()
dlg = SettingsDialog(None)
check("QTabWidget с 6 вкладками", dlg.tabs.count() == 6, str(dlg.tabs.count()))
expected_tabs = [i18n.t(k) for k in ("settings.tab.general", "settings.tab.terminal",
                                     "settings.tab.statuses", "settings.tab.autosave",
                                     "settings.tab.map", "settings.tab.language")]
got_tabs = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
check("порядок вкладок: Общие / Терминал / Статусы / Автосохранение / Карта / Язык",
      got_tabs == expected_tabs, str(got_tabs))

choices = TERMINAL_CHOICES_WINDOWS if sys.platform == "win32" else TERMINAL_CHOICES_LINUX
check("«Общие»: комбо внешнего терминала — пресеты платформы",
      dlg.ext_term_combo.count() == len(choices), str(dlg.ext_term_combo.count()))
check("«Терминал»: палитры (default/nord/dracula/tokyo_night)",
      [dlg.palette_combo.itemData(i) for i in range(dlg.palette_combo.count())]
      == ["default", "nord", "dracula", "tokyo_night"])
check("«Терминал»: размер шрифта 6–72 pt (диапазон валидатора)",
      dlg.font_size_spin.minimum() == 6 and dlg.font_size_spin.maximum() == 72)
check("«Терминал»: глубина истории от 0 (0 = скроллбэк выключен)",
      dlg.history_spin.minimum() == 0)
check("«Терминал»: поведение закрытия (close/ask)",
      [dlg.close_behavior_combo.itemData(i) for i in range(dlg.close_behavior_combo.count())]
      == ["close", "ask"])
check("«Статусы»: интервал (≥5 c) + таймаут пробы (≤60 c)",
      dlg.status_interval_spin.minimum() >= 5 and dlg.probe_timeout_spin.maximum() <= 60.0)
check("«Автосохранение»: чекбокс вкл/выкл + интервал + число бэкапов",
      hasattr(dlg, "autosave_enabled_chk") and hasattr(dlg, "autosave_interval_spin")
      and hasattr(dlg, "backup_count_spin"))
check("«Язык»: комбо en/ru/zh",
      sorted(dlg.language_combo.itemData(i) for i in range(dlg.language_combo.count()))
      == ["en", "ru", "zh"])

# Prefill из конфига (все ключи опциональны — значения ниже валидны по построению)
write_cfg({"terminal_palette": "dracula", "terminal_font_size": 14,
           "terminal_history_lines": 250, "status_interval_sec": 90,
           "status_probe_timeout_sec": 5.0, "autosave_enabled": False,
           "autosave_interval_sec": 120, "backup_count": 3,
           "language": "ru", "terminal_font": "Consolas"})
dlg2 = SettingsDialog(None)
check("«Терминал» отражает конфиг (dracula / 14 pt / 250 строк)",
      dlg2.palette_combo.currentData() == "dracula" and dlg2.font_size_spin.value() == 14
      and dlg2.history_spin.value() == 250)
check("«Статусы» отражают конфиг (90 c / 5.0 c)",
      dlg2.status_interval_spin.value() == 90
      and abs(dlg2.probe_timeout_spin.value() - 5.0) < 1e-6)
check("«Автосохранение» отражает конфиг (выкл / 120 c / 3 бэкапа)",
      not dlg2.autosave_enabled_chk.isChecked() and dlg2.autosave_interval_spin.value() == 120
      and dlg2.backup_count_spin.value() == 3)

# collect(): ровно 17 ключей config.json (10 в v1.1 + 7 в v1.1.1), типы корректны
# (language НЕ входит — он сразу)
dlg2.close_behavior_combo.setCurrentIndex(1)  # ask
dlg2.status_interval_spin.setValue(60)
dlg2.probe_timeout_spin.setValue(4.5)
c = dlg2.collect()
check("collect(): ровно 17 ключей config.json (v1.1: 10 + v1.1.1: 7)",
      set(c) == {"external_terminal", "terminal_palette", "terminal_font_size",
                 "terminal_history_lines", "terminal_close_behavior",
                 "status_interval_sec", "status_probe_timeout_sec", "autosave_enabled",
                 "autosave_interval_sec", "backup_count",
                 "ui_font_family", "ui_font_size", "terminal_font",
                 "terminal_max_open", "ui_node_double_click",
                 "ui_show_sidebar_buttons", "ui_show_connection_type"}, str(sorted(c)))
check("collect(): типы (int/float/bool/str) и изменённые значения",
      isinstance(c["terminal_font_size"], int) and isinstance(c["status_interval_sec"], int)
      and isinstance(c["status_probe_timeout_sec"], float)
      and isinstance(c["autosave_enabled"], bool)
      and c["terminal_close_behavior"] == "ask" and c["status_interval_sec"] == 60
      and abs(c["status_probe_timeout_sec"] - 4.5) < 1e-9, str(c))

# OK: merge-запись в config.json + сигнал applied
applied = []
dlg2.applied.connect(lambda: applied.append(1))
dlg2._on_accept()
cfg = read_cfg()
check("ОК: все 17 ключей записаны в config.json",
      cfg is not None and all(k in cfg for k in c), str(cfg))
check("ОК: merge — чужие ключи сохранены (language/terminal_font)",
      cfg.get("language") == "ru" and cfg.get("terminal_font") == "Consolas", str(cfg))
check("ОК: signal applied эмитирован (MainWindow применяет на лету)", len(applied) == 1)

# Cancel: без записи, без applied
cfg_before = read_cfg()
dlg3 = SettingsDialog(None)
applied3 = []
dlg3.applied.connect(lambda: applied3.append(1))
dlg3.font_size_spin.setValue(42)
dlg3.reject()
check("Отмена: конфиг не изменился, applied не эмитирован",
      read_cfg() == cfg_before and not applied3)

# ════════════════════════════════════════════════════════════
# 8. Вкладка «Язык»: немедленное применение (до ОК) + retranslate диалога
# ════════════════════════════════════════════════════════════
print("== language tab ==")
clear_cfg()
# Сценарий «ru → en» требует явной стартовой точки: с v1.1.1 язык по умолчанию — en
# (новые пользователи), и без этого комбо уже стоит на en, setCurrentIndex("en") —
# no-op без сигнала (проверяемое здесь немедленное применение слепнет).
i18n.set_language("ru")
dlg4 = SettingsDialog(None)
lang_events = []


def _apply_lang(code):  # то, что делает MainWindow._switch_language по сигналу
    lang_events.append(code)
    i18n.set_language(code)


dlg4.language_changed.connect(_apply_lang)
check("комбо начинается с текущего языка (ru)",
      dlg4.language_combo.currentData() == i18n.get_current_language())
tab0_ru = dlg4.tabs.tabText(0)
dlg4.language_combo.setCurrentIndex(dlg4.language_combo.findData("en"))
check("смена на en: language_changed немедленно (до ОК)", lang_events == ["en"],
      str(lang_events))
check("диалог ре-транслирует сам себя (вкладки на английском)",
      dlg4.tabs.tabText(0) == i18n.t("settings.tab.general") and tab0_ru != i18n.t("settings.tab.general"),
      f"ru={tab0_ru!r} en={dlg4.tabs.tabText(0)!r}")
dlg4.language_combo.setCurrentIndex(dlg4.language_combo.findData("ru"))
check("возврат на ru (сигнал + текущий язык)",
      lang_events[-1] == "ru" and i18n.get_current_language() == "ru")

# ════════════════════════════════════════════════════════════
# 9. MainWindow: меню «Настройки» между «Вид» и «Помощь», палитра, кнопка ⚙,
#    применение на лету (_apply_settings_from_dialog)
# ════════════════════════════════════════════════════════════
print("== main window entry points ==")
clear_cfg()
import ui.main_window as MW

win = MW.MainWindow()
win.show()
app.processEvents()

mb = win.menuBar()
titles = [a.text() for a in mb.actions()]


def _idx(t):
    return titles.index(t) if t in titles else -1


i_view, i_set, i_help = (_idx(i18n.t("menu.view")), _idx(i18n.t("menu.settings")),
                         _idx(i18n.t("menu.help")))
check("меню «Настройки» МЕЖДУ «Вид» и «Помощь»", 0 <= i_view < i_set < i_help, str(titles))
# Членство — через список действий меню (PySide6 6.11: QAction.menu() возвращает
# None даже для добавленного пункта — свойство привязки, см. diag при v1.1).
_reg_settings = [w for w, k in win._menu_i18n if k == "menu.settings"]
check("act_settings: пункт settings.open внутри меню «Настройки»",
      getattr(win, "act_settings", None) is not None
      and win.act_settings.text() == i18n.t("settings.open")
      and len(_reg_settings) == 1 and win.act_settings in _reg_settings[0].actions())

from ui.command_palette import CommandPalette
pal = CommandPalette(win)
pal._collect_commands()
labels = [l for l, _k, _f in pal._commands]
check("палитра команд (Ctrl+K) подхватила пункт настроек автоматически",
      i18n.t("settings.open") in labels, str(labels[:20]))

opened = []
_orig_open = win._open_settings_dialog
win._open_settings_dialog = lambda: opened.append(1)
try:
    win.sidebar.settings_clicked.emit()
    win.act_settings.trigger()
finally:
    win._open_settings_dialog = _orig_open
check("кнопка ⚙ сайдбара И пункт меню открывают диалог настроек", len(opened) == 2,
      str(opened))

# Применение на лету после ОК: статусы (StatusChecker) + автосохранение (QTimer)
write_cfg({"status_interval_sec": 45, "status_probe_timeout_sec": 2.5,
           "autosave_enabled": False, "autosave_interval_sec": 120})
win._apply_settings_from_dialog()
chk = win._status_checker
check("applied: StatusChecker — интервал 45 c / таймаут пробы 2.5 c",
      chk is not None and chk.interval_ms == 45000 and abs(chk.probe_timeout - 2.5) < 1e-9,
      f"interval={chk.interval_ms if chk else None} "
      f"timeout={chk.probe_timeout if chk else None}")
check("applied: автосохранение остановлено (enabled=False), интервал 120 c",
      not win._autosave_timer.isActive() and win._autosave_timer.interval() == 120000,
      f"active={win._autosave_timer.isActive()} interval={win._autosave_timer.interval()}")
write_cfg({"status_interval_sec": 30, "status_probe_timeout_sec": 3.0,
           "autosave_enabled": True, "autosave_interval_sec": 60})
win._apply_settings_from_dialog()
check("applied: автосохранение перезапущено (enabled=True, 60 c)",
      win._autosave_timer.isActive() and win._autosave_timer.interval() == 60000)

# Cleanup: без dirty — closeEvent не пойдёт в диалог сохранения
win._dirty = False
win.close()
app.processEvents()
clear_cfg()

finish()
