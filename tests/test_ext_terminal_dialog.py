"""Regression v0.9.9.2 — the external terminal UI (presets + reset to defaults).

ROADMAP v0.9.9.2:
  #1 the section in SSHConnectDialog: the preset choice (auto / windows_terminal / cmd /
     conhost on Windows; the Linux list) + the "Reset to default" button
     (= the ready rollback to auto). The storage — the existing ~/.sshmap_settings.json
     (load/save_external_terminal_setting from modules/external_terminal.py).
  #2 the preset is saved from the UI and applied to the launch (detect_terminal reads
     the config) — both from the dialog and from the ctx menu of MainWindow.
  #3 i18n × en/ru/zh: +13 keys (ssh_ext.section/preset_label/reset/preset.*).
  The arbitrary command template with the placeholders — deliberately in v1.1 (the settings dialog).

Run:  python tests/test_ext_terminal_dialog.py   (from the project root) or python tests/run_all.py
"""
import os, sys, shutil, tempfile, traceback

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from models.server import ServerData
from modules.external_terminal import (
    TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
    load_external_terminal_setting, save_external_terminal_setting,
    detect_terminal, build_command, _settings_path,
)
from dialogs.ssh_connect_dialog import SSHConnectDialog

# The same path as the module (~ — the sandbox: bootstrap() isolated HOME/USERPROFILE).
SETTINGS_PATH = _settings_path()

# ══ i18n: 13 new keys × en/ru/zh (the parity — _common.check_i18n_parity) ══
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = ["ssh_ext.section", "ssh_ext.preset_label", "ssh_ext.reset",
            "ssh_ext.preset.auto", "ssh_ext.preset.windows_terminal",
            "ssh_ext.preset.cmd", "ssh_ext.preset.conhost",
            "ssh_ext.preset.x-terminal-emulator", "ssh_ext.preset.gnome-terminal",
            "ssh_ext.preset.konsole", "ssh_ext.preset.xfce4-terminal",
            "ssh_ext.preset.alacritty", "ssh_ext.preset.kitty"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 13 new v0.9.9.2 keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

# ══ The section in the SSHConnectDialog: the preset composition for the platform ══
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

# A clean HOME: no settings file — the dialog is open, the file is NOT created (no open record).
check("no settings file written on dialog open (fresh HOME)",
      not os.path.exists(SETTINGS_PATH), f"path={SETTINGS_PATH}")
check("initial preset is 'auto' (default in fresh HOME)",
      combo.itemData(combo.currentIndex()) == "auto"
      and load_external_terminal_setting() == "auto")

# ══ The preset choice from the UI is saved immediately ══
print("== preset save from UI ==")
cmd_idx = got_ids.index("cmd") if "cmd" in got_ids else None
if cmd_idx is not None:
    combo.setCurrentIndex(cmd_idx)
    app.processEvents()
    check("selecting 'cmd' persists to settings immediately",
          load_external_terminal_setting() == "cmd",
          f"got={load_external_terminal_setting()!r}")
else:
    # Linux: cmd is not in the list — we take the second preset (x-terminal-emulator, etc.)
    alt_idx = 1
    combo.setCurrentIndex(alt_idx)
    app.processEvents()
    check("selecting a non-auto preset persists to settings immediately",
          load_external_terminal_setting() == got_ids[alt_idx],
          f"got={load_external_terminal_setting()!r} expected={got_ids[alt_idx]}")

# ══ "Reset to default" — the rollback to auto ══
print("== reset to default ==")
reset_btn.click()
app.processEvents()
check("reset button returns combo to 'auto'",
      combo.itemData(combo.currentIndex()) == "auto",
      f"current={combo.itemData(combo.currentIndex())!r}")
check("reset persists 'auto' to settings",
      load_external_terminal_setting() == "auto",
      f"got={load_external_terminal_setting()!r}")
# Idempotency: a repeated reset in the auto state — safe.
reset_btn.click()
app.processEvents()
check("second reset while already 'auto' is a safe no-op",
      load_external_terminal_setting() == "auto"
      and combo.itemData(combo.currentIndex()) == "auto")

# ══ The preset is applied to the launch: detect_terminal reads the saved id ══
print("== applied at launch ==")
if sys.platform == "win32":
    save_external_terminal_setting("cmd")  # cmd.exe exists on any Windows
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

# A corrupt/foreign id in the file → an auto-rollback to auto (the load_external_terminal_setting protection).
save_external_terminal_setting("definitely-not-a-terminal")
check("corrupted setting value falls back to 'auto'",
      load_external_terminal_setting() == "auto",
      f"got={load_external_terminal_setting()!r}")
save_external_terminal_setting("auto")  # return a clean state

dlg.close()
app.processEvents()

finish()
