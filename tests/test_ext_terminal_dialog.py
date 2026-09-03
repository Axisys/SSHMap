"""Регрессия v0.9.9.2 — UI внешнего терминала (пресеты + сброс к умолчанию).

ROADMAP v0.9.9.2:
  #1 Секция в SSHConnectDialog: выбор пресета (auto / windows_terminal / cmd /
     conhost на Windows; Linux-список) + кнопка «Сбросить к умолчанию»
     (= готовый откат на auto). Хранение — существующий ~/.sshmap_settings.json
     (load/save_external_terminal_setting из modules/external_terminal.py).
  #2 Пресет сохраняется из UI, применяется к запуску (detect_terminal читает
     конфиг) — и из диалога, и из ctx-меню MainWindow.
  #3 i18n × en/ru/zh: +13 ключей (ssh_ext.section/preset_label/reset/preset.*).
  Произвольная команда-шаблон с плейсхолдерами — осознанно в v1.1 (диалог настроек).

Запуск:  python tests/test_ext_terminal_dialog.py   (из корня проекта) или python tests/run_all.py
"""
import os, sys, json, shutil, tempfile, traceback

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from models.server import ServerData
from modules.external_terminal import (
    TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
    load_external_terminal_setting, save_external_terminal_setting,
    detect_terminal, build_command, _settings_path,
)
from dialogs.ssh_connect_dialog import SSHConnectDialog

# Тот же путь, что и модуль (~ — песочница: bootstrap() изолировал HOME/USERPROFILE).
SETTINGS_PATH = _settings_path()

# ══ i18n: 13 новых ключей × en/ru/zh, наборы идентичны (377 на язык; +2 в v0.9.9.7, +22 в v1.0RC4, +33 в v1.1, +2 в v1.1.2RC2, +2 в v1.1.2 final) ══
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = ["ssh_ext.section", "ssh_ext.preset_label", "ssh_ext.reset",
            "ssh_ext.preset.auto", "ssh_ext.preset.windows_terminal",
            "ssh_ext.preset.cmd", "ssh_ext.preset.conhost",
            "ssh_ext.preset.x-terminal-emulator", "ssh_ext.preset.gnome-terminal",
            "ssh_ext.preset.konsole", "ssh_ext.preset.xfce4-terminal",
            "ssh_ext.preset.alacritty", "ssh_ext.preset.kitty"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("13 новых ключей v0.9.9.2 есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (377 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 377 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# ══ Секция в SSHConnectDialog: состав пресетов под платформу ══
print("== dialog section ==")
sd = ServerData(id="ss92a", alias="ext-1", host="10.1.1.5", user="ops", ip="10.1.1.5")
dlg = SSHConnectDialog(sd)
app.processEvents()

combo = dlg.ext_terminal_combo
reset_btn = dlg.ext_terminal_reset_btn
check("dialog has ext-terminal combo + reset button",
      combo is not None and reset_btn is not None)

expected_choices = TERMINAL_CHOICES_WINDOWS if sys.platform == "win32" else TERMINAL_CHOICES_LINUX
got_ids = [combo.itemData(i) for i in range(combo.count())]
check(f"combo lists exactly the platform presets ({len(expected_choices)} on {sys.platform})",
      got_ids == expected_choices, f"got={got_ids} expected={expected_choices}")
check("all combo items have non-empty display labels",
      all(str(combo.itemText(i)).strip() for i in range(combo.count())))

# Чистый HOME: файла настроек нет — диалог открыт, файл НЕ создан (нет записи на open).
check("no settings file written on dialog open (fresh HOME)",
      not os.path.exists(SETTINGS_PATH), f"path={SETTINGS_PATH}")
check("initial preset is 'auto' (default in fresh HOME)",
      combo.itemData(combo.currentIndex()) == "auto"
      and load_external_terminal_setting() == "auto")

# ══ Выбор пресета из UI сохраняется сразу ══
print("== preset save from UI ==")
cmd_idx = got_ids.index("cmd") if "cmd" in got_ids else None
if cmd_idx is not None:
    combo.setCurrentIndex(cmd_idx)
    app.processEvents()
    check("selecting 'cmd' persists to settings immediately",
          load_external_terminal_setting() == "cmd",
          f"got={load_external_terminal_setting()!r}")
else:
    # Linux: cmd в списке нет — берём второй пресет (x-terminal-emulator и т.п.)
    alt_idx = 1
    combo.setCurrentIndex(alt_idx)
    app.processEvents()
    check("selecting a non-auto preset persists to settings immediately",
          load_external_terminal_setting() == got_ids[alt_idx],
          f"got={load_external_terminal_setting()!r} expected={got_ids[alt_idx]}")

# ══ «Сбросить к умолчанию» — откат на auto ══
print("== reset to default ==")
reset_btn.click()
app.processEvents()
check("reset button returns combo to 'auto'",
      combo.itemData(combo.currentIndex()) == "auto",
      f"current={combo.itemData(combo.currentIndex())!r}")
check("reset persists 'auto' to settings",
      load_external_terminal_setting() == "auto",
      f"got={load_external_terminal_setting()!r}")
# Идемпотентность: повторный сброс в состоянии auto — безопасно.
reset_btn.click()
app.processEvents()
check("second reset while already 'auto' is a safe no-op",
      load_external_terminal_setting() == "auto"
      and combo.itemData(combo.currentIndex()) == "auto")

# ══ Пресет применяется к запуску: detect_terminal читает сохранённый id ══
print("== applied at launch ==")
if sys.platform == "win32":
    save_external_terminal_setting("cmd")  # cmd.exe есть на любой Windows
    got = detect_terminal()
    check("preset 'cmd' is honored by detect_terminal (launch path)", got == "cmd", f"got={got}")
    cmd = build_command("cmd", "10.1.1.5", "ops")
    check("build_command('cmd', ...) starts with cmd.exe /c start",
          cmd[0] == "cmd.exe" and cmd[1:3] == ["/c", "start"], f"cmd={cmd[:4]}")
else:
    found = next((c for c in TERMINAL_CHOICES_LINUX if c != "auto" and shutil.which(c)), None)
    if found is not None:
        save_external_terminal_setting(found)
        got = detect_terminal()
        check(f"preset '{found}' is honored by detect_terminal (launch path)",
              got == found, f"got={got}")
    else:
        check("no forced preset available on this system — launch-path check skipped", True)

# Битый/чужой id в файле → авто-откат к auto (защита load_external_terminal_setting).
save_external_terminal_setting("definitely-not-a-terminal")
check("corrupted setting value falls back to 'auto'",
      load_external_terminal_setting() == "auto",
      f"got={load_external_terminal_setting()!r}")
save_external_terminal_setting("auto")  # вернуть чистое состояние

dlg.close()
app.processEvents()

finish()
