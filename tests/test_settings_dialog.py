"""v1.1 — Settings dialog (hub): the release's themed test.

ROADMAP v1.1 (tasks 1–7):
  #1 The frame — the QTabWidget "General / Terminal / Statuses / Autosave / Map / Language"
     (the "Hotkeys" tab will appear in v1.3);
  #2 The entry points — the "Settings" menu item BETWEEN "View" and "Help" + the ⚙ button at the bottom
     of the sidebar (the 6th in ui/sidebar.py _BUTTONS, the settings_clicked signal) + the vector
     gear (ui/icons.py); the command palette (Ctrl+K) picks up the item automatically;
  #3 The "Terminal" tab — the palette/font size/history depth (the v1.0 terminal_* keys)
     + the session close behavior (the new key terminal_close_behavior: "close"|"ask";
     "ask" → the confirmation in closeEvent, only for the active session);
  #4 The "Statuses" tab — the probe interval and the timeout of the StatusChecker
     (status_interval_sec / status_probe_timeout_sec; the defaults 30 s / 3.0 s = v1.0;
     on the fly — set_interval/set_probe_timeout after the OK);
  #5 The "Autosave" tab — on/off, the interval, the number of backups (the v0.9.7 keys);
  #6 The "Language" tab — the en/ru/zh switch with the immediate apply
     (the language_changed signal BEFORE the OK; the "Help → Language" item is kept);
  #7 The single settings file — the external_terminal key is moved from the separate
    ~/.sshmap_settings.json into config.json (the migration on the read, the old file is removed).

The storage — the SINGLE ~/.sshmap/config.json (i18n.load_config/save_config, the atomic
merge write); all the keys are optional, the defaults = the current behavior. i18n: +33 keys ×
en/ru/zh in v1.1 (the parity 326 → 359) + 14 in v1.1.1 (the options around the hub — the parity 373;
+2 in v1.1.2RC2 — msg.confirm_delete_profile, status.import_resolving — the parity 375;
+2 in v1.1.2 final — settings.statuses.max_parallel, status.auto_interval_hint — the parity 377;
its own thematic test — tests/test_settings_options.py).

Run: python tests/test_settings_dialog.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity, read_cfg,
                     write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

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
# ════════════════════════════════════════════════════════════
# 1. i18n: +33 keys × en/ru/zh, parity 326 → 359 → … → 377 (since v1.1.2 final)
# ════════════════════════════════════════════════════════════
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = [
    "settings.title", "settings.ok", "settings.cancel",
    "settings.tab.general", "settings.tab.terminal", "settings.tab.statuses",
    "settings.tab.autosave", "settings.tab.map", "settings.tab.language",
    "settings.tab.hotkeys",   # v1.3.2
    "settings.tab.appearance",   # v1.4.3
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
check("the 33 new v1.1 keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

# ════════════════════════════════════════════════════════════
# 2. The gear icon (ui/icons.py)
# ════════════════════════════════════════════════════════════
print("== gear icon ==")
ic = get_icon("settings")
pm = ic.pixmap(20, 20)
check("get_icon('settings') — a non-null QIcon with a 20×20 pixmap",
      not ic.isNull() and not pm.isNull() and (pm.width(), pm.height()) == (20, 20))
img = pm.toImage()
ink = sum(1 for y in range(img.height()) for x in range(img.width())
          if img.pixelColor(x, y).alpha() > 0)
check("the gear is drawn (the ink on the transparent canvas)", ink > 40, f"ink={ink}")

# ════════════════════════════════════════════════════════════
# 3. The ⚙ sidebar button: 6th in _BUTTONS + the settings_clicked signal
# ════════════════════════════════════════════════════════════
print("== sidebar button ==")
check("_BUTTONS: exactly 6 buttons, the 6th — (btn_settings, settings, btn.settings)",
      len(_BUTTONS) == 6 and _BUTTONS[-1] == ("btn_settings", "settings",
                                              "btn.settings", "Settings"),
      str(_BUTTONS))
_actions = {k: (lambda node, _k=k: None) for k in
            ("ssh", "external", "edit", "copy_ip", "copy_hostname", "ping",
             "collect_info", "check_status", "diagnose", "reveal", "delete")}
            # v1.3.3.3: + check_status; v1.5.3: + diagnose
sb = SidebarPanel(translate_fn=i18n.t, actions=_actions)
check("btn_settings exists and carries the vector gear",
      hasattr(sb, "btn_settings") and not sb.btn_settings.icon().isNull())
clicks = []
sb.settings_clicked.connect(lambda: clicks.append(1))
sb.btn_settings.click()
check("a click on the ⚙ → settings_clicked (exactly once)", len(clicks) == 1, str(clicks))
check("the button's label is translated (btn.settings)",
      sb.btn_settings.text() == i18n.t("btn.settings"), sb.btn_settings.text())

# ════════════════════════════════════════════════════════════
# 4. Task 7: external_terminal — a single config.json + migration
# ════════════════════════════════════════════════════════════
print("== external terminal: single config.json ==")
clear_cfg(LEGACY_PATH)
check("a fresh HOME: load → 'auto', the file is not created",
      load_external_terminal_setting() == "auto" and read_cfg() is None)

with open(LEGACY_PATH, "w", encoding="utf-8") as f:
    json.dump({"external_terminal": "cmd"}, f)
v = load_external_terminal_setting()
cfg = read_cfg()
check("the legacy 'cmd' from ~/.sshmap_settings.json → the migration into config.json",
      v == "cmd" and cfg is not None and cfg.get("external_terminal") == "cmd",
      f"v={v!r} cfg={cfg}")
check("the old file is removed after the successful migration", not os.path.exists(LEGACY_PATH))

# The key is already in config.json → the legacy is ignored (nothing is overwritten).
# v1.1.2RC1 (N2): the old value "conhost" is no longer a preset — it is read as "cmd"
# (backward-compat on read; the on-disk file keeps its original value).
write_cfg({"external_terminal": "conhost"})
with open(LEGACY_PATH, "w", encoding="utf-8") as f:
    json.dump({"external_terminal": "cmd"}, f)
v = load_external_terminal_setting()
check("config.json takes priority over the legacy (no overwrite); 'conhost' is read as 'cmd' (N2)",
      v == "cmd" and read_cfg().get("external_terminal") == "conhost", f"v={v!r}")

# save writes ONLY to config.json (no legacy is created)
os.remove(LEGACY_PATH)
save_val = "cmd" if sys.platform == "win32" else "gnome-terminal"
ok = save_external_terminal_setting(save_val)
check("save_external_terminal_setting → config.json, the legacy is not created",
      ok and read_cfg().get("external_terminal") == save_val
      and not os.path.exists(LEGACY_PATH))

write_cfg({"external_terminal": "no-such-terminal"})
check("a broken value in config.json → 'auto'", load_external_terminal_setting() == "auto")
clear_cfg(LEGACY_PATH)

# ════════════════════════════════════════════════════════════
# 5. Task 4: the status settings (get_status_settings + live)
# ════════════════════════════════════════════════════════════
print("== status settings ==")
clear_cfg(LEGACY_PATH)
st = get_status_settings()
check("no config → the v1.0 defaults (30 s / 3.0 s / 16 parallel, the v1.1.2 final)",
      st == {"interval_sec": 30, "probe_timeout_sec": 3.0, "max_parallel": 16}, str(st))
write_cfg({"status_interval_sec": 45, "status_probe_timeout_sec": 2.5})
st = get_status_settings()
check("the valid values are read (45 s / 2.5 s)",
      st == {"interval_sec": 45, "probe_timeout_sec": 2.5, "max_parallel": 16}, str(st))
write_cfg({"status_interval_sec": 1, "status_probe_timeout_sec": 99})
st = get_status_settings()
check("the clamps: interval ≥ 5 s, timeout ≤ 60 s",
      st == {"interval_sec": 5, "probe_timeout_sec": 60.0, "max_parallel": 16}, str(st))
write_cfg({"status_interval_sec": True, "status_probe_timeout_sec": "abc"})
st = get_status_settings()
check("the broken values (bool/str) → the defaults",
      st == {"interval_sec": 30, "probe_timeout_sec": 3.0, "max_parallel": 16}, str(st))
# v1.1.2 final: the clamps of status_max_parallel (details — tests/test_status_parallel.py)
write_cfg({"status_max_parallel": 9999})
st = get_status_settings()
check("the status_max_parallel clamp from above → 64", st["max_parallel"] == 64, str(st))

chk = StatusChecker(parent=None)
chk.set_interval(1000)
check("set_interval: the clamp not more often than once in 5 s", chk.interval_ms == 5000,
      str(chk.interval_ms))
chk.set_interval(60000)
chk.set_probe_timeout(0.01)
check("set_interval/set_probe_timeout are applied (the timeout clamp ≥ 0.2)",
      chk.interval_ms == 60000 and abs(chk.probe_timeout - 0.2) < 1e-9,
      f"interval={chk.interval_ms} timeout={chk.probe_timeout}")
clear_cfg(LEGACY_PATH)

# ════════════════════════════════════════════════════════════
# 6. Task 3: the session closing behaviour (terminal_close_behavior)
# ════════════════════════════════════════════════════════════
print("== terminal close behavior ==")


from _fakes import FakeSSHThread as _FakeSSHThreadBase, QuestionStub


class _FakeSSHThread(_FakeSSHThreadBase):
    """+ a deterministic isRunning: the active session is simulated with the
    _running_override flag (the test_terminal_acceptance.py pattern)."""

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__(host, user, port, password, key_path)
        self._running_override = False

    def isRunning(self):
        if self._running_override:
            return True
        return super().isRunning()


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread
term_windows = []


def alive(w):
    """Is the C++ object of the window alive (WA_DeleteOnClose: after the accept — already destroyed)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


def make_term(alias):
    # IMPORTANT: show() BEFORE close() — WA_DeleteOnClose removes the window only if it is
    # was visible at least once (verified offscreen, Qt 6.11: close() of an invisible
    # the window accepts the event, but the C++ object lives).
    w = ST.SSHTerminalWindow(
        ServerData(id=f"set-{alias}", alias=alias, host="10.98.0.1", user="root"),
        None, password="pw")
    term_windows.append(w)
    w.resize(700, 500)
    w.show()
    app.processEvents()
    return w


asked = []
_question = QuestionStub(QMessageBox.StandardButton.Cancel,
                         record=lambda title, text: asked.append(title)).install(ST)

try:
    # "ask" + an active session → confirmation; Cancel → the window survives
    write_cfg({"terminal_close_behavior": "ask"})
    w = make_term("ask1")
    check("the window reads terminal_close_behavior from the config ('ask')",
          getattr(w, "_close_behavior", None) == "ask",
          str(getattr(w, "_close_behavior", None)))
    w.terminal_thread._running_override = True  # the active session
    w.close()
    app.processEvents()
    check("'ask' + an active session: the confirmation is shown (msg.confirm_close_session)",
          len(asked) == 1 and asked[0] == i18n.t("msg.close_session_title"), str(asked))
    check("Cancel → the window survives (event.ignore, WA_DeleteOnClose did not fire)",
          alive(w))

    _question.answer = QMessageBox.StandardButton.Close
    asked.clear()
    w.close()
    app.processEvents()
    check("'ask' + Close: the confirmation again, the window closes",
          len(asked) == 1 and not alive(w), f"asked={asked}")

    # "close" (the v1.0 default) + an active session → no dialog
    clear_cfg(LEGACY_PATH)
    w2 = make_term("cl1")
    check("no config → the default 'close' (the v1.0 behavior)",
          getattr(w2, "_close_behavior", None) == "close")
    w2.terminal_thread._running_override = True
    asked.clear()
    w2.close()
    app.processEvents()
    check("'close' + an active session: no dialog, the window closes",
          len(asked) == 0 and not alive(w2), f"asked={asked}")

    # "ask", but the session is already finished → no dialog
    write_cfg({"terminal_close_behavior": "ask"})
    w3 = make_term("ask2")
    w3.terminal_thread.wait(2000)  # a guaranteed inactive session (no race)
    asked.clear()
    w3.close()
    app.processEvents()
    check("'ask' + a finished session: no dialog", len(asked) == 0 and not alive(w3),
          f"asked={asked}")
finally:
    _question.restore()
    ST.SSHTerminalThread = _orig_thread_cls
    clear_cfg(LEGACY_PATH)

# ════════════════════════════════════════════════════════════
# 7. The dialog: 7 tabs (v1.3.2: + Hotkeys), widgets, prefill from the config, collect/OK/Cancel
# ════════════════════════════════════════════════════════════
print("== settings dialog ==")
clear_cfg(LEGACY_PATH)
dlg = SettingsDialog(None)
check("a QTabWidget with 8 tabs (v1.3.2: + Hotkeys; v1.4.3: + Appearance)",
      dlg.tabs.count() == 8, str(dlg.tabs.count()))
expected_tabs = [i18n.t(k) for k in ("settings.tab.general", "settings.tab.appearance",
                                     "settings.tab.terminal",
                                     "settings.tab.statuses", "settings.tab.autosave",
                                     "settings.tab.map", "settings.tab.hotkeys",
                                     "settings.tab.language")]
got_tabs = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
check("the tab order: General / Appearance / Terminal / Status Checks / Autosave / Map / Hotkeys / Language",
      got_tabs == expected_tabs, str(got_tabs))

# v1.3.3.3 (task 3/4): the "Hotkeys" tab grew to the FULL action registry (~40 rows, most
# of them with an empty default) and gained the "Reset to defaults" button.
import ui.hotkey_registry as _HR

_expected_rows = len(_HR.action_ids())
check("'Hotkeys': one ACTION row per registry action (56 in v1.5.5: +the inventory report "
      "pair over the 54 of v1.5.3), grouped by family",
      len(dlg.hotkey_edits) == _expected_rows
      and _expected_rows == 56
      and dlg.hotkeys_table.rowCount() == _expected_rows + len(dlg.hotkey_family_rows())
      and [dlg._hotkey_rows[r][1] for r in dlg.hotkey_action_rows()]
      == [aid for fam in _HR.family_order() for aid in _HR.actions_by_family()[fam]],
      f"rows={dlg.hotkeys_table.rowCount()} registry={_expected_rows}")
check("'Hotkeys': the row names come from the registry label keys",
      [dlg.hotkeys_table.item(r, 0).text() for r in dlg.hotkey_action_rows()]
      == [i18n.t(_HR.action_label_key(a))
          for fam in _HR.family_order() for a in _HR.actions_by_family()[fam]])
check("'Hotkeys': the v1.3.3.3 defaults are prefilled (Save As / Reset zoom / Zoom In / Zoom Out)",
      dlg.hotkey_edits["file.save_as"].keySequence().toString() == "Ctrl+Shift+S"
      and dlg.hotkey_edits["view.reset_zoom"].keySequence().toString() == "Ctrl+0"
      and dlg.hotkey_edits["view.zoom_in"].keySequence().toString() == "Ctrl+="
      and dlg.hotkey_edits["view.zoom_out"].keySequence().toString() == "Ctrl+-")
check("'Hotkeys': an empty-default action shows an EMPTY field (assignable, no hotkey)",
      dlg.hotkey_edits["help.open_logs"].keySequence().toString() == ""
      and dlg.hotkey_edits["view.center_map"].keySequence().toString() == ""
      and dlg.hotkey_edits["file.export_png"].keySequence().toString() == "")
check("'Hotkeys': the 'Reset to defaults' button is present with its own i18n label",
      dlg.reset_hotkeys_btn.text() == i18n.t("settings.hotkeys.reset")
      and bool(dlg.reset_hotkeys_btn.text()))

choices = TERMINAL_CHOICES_WINDOWS if sys.platform == "win32" else TERMINAL_CHOICES_LINUX
check("'General': the combo of the external terminal — the platform presets",
      dlg.ext_term_combo.count() == len(choices), str(dlg.ext_term_combo.count()))
check("'Terminal': the palettes (default/nord/dracula/tokyo_night)",
      [dlg.palette_combo.itemData(i) for i in range(dlg.palette_combo.count())]
      == ["default", "nord", "dracula", "tokyo_night"])
check("'Terminal': the font size 6–72 pt (the validator's range)",
      dlg.font_size_spin.minimum() == 6 and dlg.font_size_spin.maximum() == 72)
check("'Terminal': the history depth from 0 (0 = the scrollback is off)",
      dlg.history_spin.minimum() == 0)
check("'Terminal': the close behavior (close/ask)",
      [dlg.close_behavior_combo.itemData(i) for i in range(dlg.close_behavior_combo.count())]
      == ["close", "ask"])
check("'Terminal': the display mode (windows/tabs, v1.2.2)",
      [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())]
      == ["windows", "tabs"] and dlg.mode_combo.currentData() == "windows")
check("'Status Checks': the interval (≥5 s) + the probe timeout (≤60 s)",
      dlg.status_interval_spin.minimum() >= 5 and dlg.probe_timeout_spin.maximum() <= 60.0)
check("'Autosave': the on/off checkbox + the interval + the number of backups",
      hasattr(dlg, "autosave_enabled_chk") and hasattr(dlg, "autosave_interval_spin")
      and hasattr(dlg, "backup_count_spin"))
# v1.3.3: the combo is built from the DISCOVERED i18n/*.json — the test must not carry a
# hardcoded language list either (dropping in a new language file is not a code change).
_lang_codes = sorted(lg["code"] for lg in i18n.get_available_languages())
check("'Language': the combo lists every discovered language (en/ru/zh + dropped-in files)",
      sorted(dlg.language_combo.itemData(i) for i in range(dlg.language_combo.count())) == _lang_codes
      and {"en", "ru", "zh"} <= set(_lang_codes),
      str(_lang_codes))

# Prefill from the config (all keys are optional — the values below are valid by construction)
write_cfg({"terminal_palette": "dracula", "terminal_font_size": 14,
           "terminal_history_lines": 250, "status_interval_sec": 90,
           "status_probe_timeout_sec": 5.0, "autosave_enabled": False,
           "autosave_interval_sec": 120, "backup_count": 3,
           "language": "ru", "terminal_font": "Consolas",
           "terminal_mode": "tabs"})   # v1.2.2
dlg2 = SettingsDialog(None)
check("'Terminal' reflects the config (dracula / 14 pt / 250 lines)",
      dlg2.palette_combo.currentData() == "dracula" and dlg2.font_size_spin.value() == 14
      and dlg2.history_spin.value() == 250)
check("'Terminal' reflects the terminal_mode (tabs, v1.2.2)",
      dlg2.mode_combo.currentData() == "tabs", str(dlg2.mode_combo.currentData()))
check("'Status Checks' reflect the config (90 s / 5.0 s)",
      dlg2.status_interval_spin.value() == 90
      and abs(dlg2.probe_timeout_spin.value() - 5.0) < 1e-6)
check("'Autosave' reflects the config (off / 120 s / 3 backups)",
      not dlg2.autosave_enabled_chk.isChecked() and dlg2.autosave_interval_spin.value() == 120
      and dlg2.backup_count_spin.value() == 3)

# collect(): exactly 21 config.json keys (10 in v1.1 + 7 in v1.1.1 + 1 in v1.1.2 final
# + 1 in v1.2.2 — terminal_mode + 1 in v1.3.2 — hotkeys + 1 in v1.3.3.8 —
# terminal_wheel, which closes the "config-only key" category), the types are correct
# (language is NOT included — it is immediate)
dlg2.close_behavior_combo.setCurrentIndex(1)  # ask
dlg2.status_interval_spin.setValue(60)
dlg2.probe_timeout_spin.setValue(4.5)
c = dlg2.collect()
check("collect(): exactly 22 config.json keys (21 + theme, v1.4.3)",
      set(c) == {"external_terminal", "terminal_mode", "terminal_palette",
                 "terminal_font_size",
                 "terminal_history_lines", "terminal_close_behavior",
                 "terminal_wheel",
                 "status_interval_sec", "status_probe_timeout_sec", "status_max_parallel",
                 "autosave_enabled", "autosave_interval_sec", "backup_count",
                 "ui_font_family", "ui_font_size", "terminal_font",
                 "terminal_max_open", "ui_node_double_click",
                 "ui_show_sidebar_buttons", "ui_show_connection_type",
                 "hotkeys", "theme"}, str(sorted(c)))
check("collect(): the types (int/float/bool/str) and the changed values",
      isinstance(c["terminal_font_size"], int) and isinstance(c["status_interval_sec"], int)
      and isinstance(c["status_probe_timeout_sec"], float)
      and isinstance(c["autosave_enabled"], bool)
      and c["terminal_close_behavior"] == "ask" and c["status_interval_sec"] == 60
      and abs(c["status_probe_timeout_sec"] - 4.5) < 1e-9, str(c))

# OK: a merged write to config.json + the applied signal
applied = []
dlg2.applied.connect(lambda: applied.append(1))
dlg2._on_accept()
cfg = read_cfg()
check("OK: all the 22 keys are written into config.json",
      cfg is not None and all(k in cfg for k in c), str(cfg))
check("OK: the merge — the foreign keys are kept (language/terminal_font)",
      cfg.get("language") == "ru" and cfg.get("terminal_font") == "Consolas", str(cfg))
check("OK: the signal applied is emitted (the MainWindow applies it live)", len(applied) == 1)

# Cancel: no write, no applied
cfg_before = read_cfg()
dlg3 = SettingsDialog(None)
applied3 = []
dlg3.applied.connect(lambda: applied3.append(1))
dlg3.font_size_spin.setValue(42)
dlg3.reject()
check("Cancel: the config is unchanged, the applied is not emitted",
      read_cfg() == cfg_before and not applied3)

# ════════════════════════════════════════════════════════════
# 8. The "Language" tab: immediate application (before OK) + retranslating the dialog
# ════════════════════════════════════════════════════════════
print("== language tab ==")
clear_cfg(LEGACY_PATH)
# The "ru → en" scenario requires an explicit starting point: since v1.1.1 the default language — en
# (new users), and without this the combo already sits on en, so setCurrentIndex("en") —
# a no-op without a signal (the immediate application checked here would go blind).
i18n.set_language("ru")
dlg4 = SettingsDialog(None)
lang_events = []


def _apply_lang(code):  # what MainWindow._switch_language does on the signal
    lang_events.append(code)
    i18n.set_language(code)


dlg4.language_changed.connect(_apply_lang)
check("the combo starts with the current language (ru)",
      dlg4.language_combo.currentData() == i18n.get_current_language())
tab0_ru = dlg4.tabs.tabText(0)
dlg4.language_combo.setCurrentIndex(dlg4.language_combo.findData("en"))
check("the switch to en: the language_changed is immediate (before the OK)", lang_events == ["en"],
      str(lang_events))
check("the dialog re-translates itself (the tabs in English)",
      dlg4.tabs.tabText(0) == i18n.t("settings.tab.general") and tab0_ru != i18n.t("settings.tab.general"),
      f"ru={tab0_ru!r} en={dlg4.tabs.tabText(0)!r}")
dlg4.language_combo.setCurrentIndex(dlg4.language_combo.findData("ru"))
check("the return to ru (the signal + the current language)",
      lang_events[-1] == "ru" and i18n.get_current_language() == "ru")

# ════════════════════════════════════════════════════════════
# 9. MainWindow: the "Settings" menu between "View" and "Help", the palette, the ⚙ button,
#    live application (_apply_settings_from_dialog)
# ════════════════════════════════════════════════════════════
print("== main window entry points ==")
clear_cfg(LEGACY_PATH)
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
check("the 'Settings' menu is BETWEEN the 'View' and the 'Help'", 0 <= i_view < i_set < i_help, str(titles))
# The membership — via the list of menu actions (PySide6 6.11: QAction.menu() returns
# None even for the added item — a property of the binding, see the diag at v1.1).
_reg_settings = [w for w, k in win._menu_i18n if k == "menu.settings"]
check("act_settings: the settings.open item is inside the 'Settings' menu",
      getattr(win, "act_settings", None) is not None
      and win.act_settings.text() == i18n.t("settings.open")
      and len(_reg_settings) == 1 and win.act_settings in _reg_settings[0].actions())

from ui.command_palette import CommandPalette
pal = CommandPalette(win)
pal._collect_commands()
labels = [l for l, _k, _f in pal._commands]
check("the command palette (Ctrl+K) picked up the settings item automatically",
      i18n.t("settings.open") in labels, str(labels[:20]))

opened = []
_orig_open = win._open_settings_dialog
win._open_settings_dialog = lambda: opened.append(1)
try:
    win.sidebar.settings_clicked.emit()
    win.act_settings.trigger()
finally:
    win._open_settings_dialog = _orig_open
check("the ⚙ sidebar button AND the menu item open the settings dialog", len(opened) == 2,
      str(opened))

# Live application after OK: the statuses (StatusChecker) + the autosave (QTimer)
write_cfg({"status_interval_sec": 45, "status_probe_timeout_sec": 2.5,
           "autosave_enabled": False, "autosave_interval_sec": 120})
win._apply_settings_from_dialog()
chk = win._status_checker
check("applied: the StatusChecker — the interval 45 s / the probe timeout 2.5 s",
      chk is not None and chk.interval_ms == 45000 and abs(chk.probe_timeout - 2.5) < 1e-9,
      f"interval={chk.interval_ms if chk else None} "
      f"timeout={chk.probe_timeout if chk else None}")
check("applied: the autosave is stopped (enabled=False), the interval 120 s",
      not win._autosave_timer.isActive() and win._autosave_timer.interval() == 120000,
      f"active={win._autosave_timer.isActive()} interval={win._autosave_timer.interval()}")
write_cfg({"status_interval_sec": 30, "status_probe_timeout_sec": 3.0,
           "autosave_enabled": True, "autosave_interval_sec": 60})
win._apply_settings_from_dialog()
check("applied: the autosave is restarted (enabled=True, 60 s)",
      win._autosave_timer.isActive() and win._autosave_timer.interval() == 60000)

# Cleanup: no dirty — closeEvent will not go to the save dialog
win._dirty = False
win.close()
app.processEvents()
clear_cfg(LEGACY_PATH)

finish()
