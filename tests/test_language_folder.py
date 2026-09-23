"""v1.3.3.8 — What the app supports but the UI cannot reach: the user language folder, the import/export manager, one range for `terminal_max_open`, a UI for `terminal_wheel`.

ROADMAP v1.3.3.8 (tasks 1-4):
  #1 the USER language folder `~/.sshmap/languages/*.json` joins the discovery in ONE
     place (`i18n.language_file_path()`): a user file SHADOWS the built-in one of the
     same code, a new code adds a language, and every consumer (the `Help → Language`
     submenu, the settings combo, `lang.reload`) sees both without a restart. The
     folder is created ON DEMAND — never at startup. A user file that is not a usable
     language file (broken JSON / a non-object root / no translation key) is SKIPPED
     with a log line and the built-in file of that code is used instead. The strict
     suite check keeps walking the PACKAGE `i18n/` folder only (`i18n_lang_codes()`),
     so a user folder can neither break nor weaken it;
  #2 the language manager in the "Language" tab: "Import a language file…" validates
     (object root, >= 1 translation key, the `"name"` meta key, a usable code) and
     copies into the user folder — a refused file never reaches it; an INCOMPLETE file
     is imported WITH the English-fallback note (the copy is marked `"partial": true`);
     "Export the current language…" writes the file that wins for the active language
     (or the `en` template);
  #3 `terminal_max_open`: the spin follows the VALIDATOR (1..32) — the old 1..16 range
     was a BUG, not only a narrower range: a saved 20 was displayed as 16 and an OK
     wrote 16 back, silently lowering a valid value;
  #4 `terminal_wheel` gets its UI (a two-value combo in the "Terminal" tab) — the hub's
     `collect()` goes 20 -> 21 keys and the last "config-only" key is closed.

Sections:
  §1 the folder is created on demand (never by the import of the module);
  §2 discovery: a new code appears, the user's "name" is displayed;
  §3 shadowing: the user's file wins for its code, removing it restores the built-in;
  §4 broken / non-object / foreign files are skipped and the app still starts;
  §5 the strict suite check is neither broken nor weakened by a user folder;
  §6 import: validation, the partial marker, a clean folder on a refusal;
  §7 export: the active language (or the en template), the file imports back;
  §8 the hub: terminal_max_open is ONE 1..32 range (the silent-downgrade regression);
  §9 the hub: the terminal_wheel combo, collect() = 21 keys, "off" reaches the canvas;
  §10 the manager through the real dialog (buttons, reports, the live switch);
  §11 the release state (the pins of tests/_common.py).

Run: python tests/test_language_folder.py   (from the project root) or python tests/run_all.py
"""
import importlib.util
import io
import json
import os
import shutil
import sys
from contextlib import redirect_stdout

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, i18n_lang_codes,
                     i18n_parity_problems, translation_keys, EXPECTED_I18N_KEYS,
                     I18N_REFERENCE, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

import i18n  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import modules.ssh_terminal as ST  # noqa: E402
from modules.ssh_terminal import load_terminal_settings  # noqa: E402
from modules.terminal_page import TerminalSessionPage  # noqa: E402
from models.server import ServerData  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.settings_dialog as SD  # noqa: E402

from _fakes import FakeSSHThread as _FakeThread  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
_ORIG_THREAD_CLS = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # every page in this file — on the fake

LANG_DIR = i18n.user_language_dir()      # ~/.sshmap/languages under the sandbox HOME
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
PKG_I18N = os.path.join(ROOT, "i18n")
PKG_CODES = i18n_lang_codes(ROOT)


# ── helpers ──────────────────────────────────────────────────────────────────

def write_cfg(data):
    return i18n.save_config(data)
def folder_files():
    """The *.json names currently in the user language folder ([] when it is absent)."""
    if not os.path.isdir(LANG_DIR):
        return []
    return sorted(f for f in os.listdir(LANG_DIR) if f.endswith(".json"))


def remove_user_file(name):
    try:
        os.remove(os.path.join(LANG_DIR, name))
    except OSError:
        pass


def write_lang(code, data, folder=None):
    folder = folder or LANG_DIR
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{code}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_lang_file(code):
    with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8-sig") as f:
        return json.load(f)


def write_raw(name, text):
    os.makedirs(LANG_DIR, exist_ok=True)
    path = os.path.join(LANG_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def lang_names():
    return {lg["code"]: lg["name"] for lg in i18n.get_available_languages()}


def lang_codes():
    return sorted(lg["code"] for lg in i18n.get_available_languages())


def load_check_script():
    """tests/check_i18n_keys.py as a module (an isolated run of main(root: ROOT))."""
    path = os.path.join(ROOT, "tests", "check_i18n_keys.py")
    spec = importlib.util.spec_from_file_location("_i18n_check_script_lf", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_check_script(mod, root):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(root=root)
    return rc, buf.getvalue()


def make_page(alias):
    return TerminalSessionPage(
        ServerData(id=f"lf-{alias}", alias=alias, host="10.99.0.9", user="root"), None)


_INCOMING = os.path.join(WORK, "incoming")
os.makedirs(_INCOMING, exist_ok=True)


def incoming(name, payload=None, raw=None):
    path = os.path.join(_INCOMING, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else json.dumps(payload, ensure_ascii=False))
    return path


_EN_TEMPLATE = load_i18n_langs(ROOT)[I18N_REFERENCE]   # the reference, meta keys included
i18n.set_language("en")   # the deterministic base (the sandbox HOME starts empty anyway)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the folder is created on demand ==")
# ════════════════════════════════════════════════════════════════════════════

check("~/.sshmap/languages does not exist after the module import (NO empty directory at startup)",
      not os.path.isdir(LANG_DIR), LANG_DIR)
check("an absent user folder still discovers exactly the package languages",
      lang_codes() == PKG_CODES and not folder_files(),
      f"{lang_codes()} vs {PKG_CODES}")
check("ensure_user_language_dir() creates it and is idempotent",
      i18n.ensure_user_language_dir() is True and i18n.ensure_user_language_dir() is True
      and os.path.isdir(LANG_DIR))


# ════════════════════════════════════════════════════════════════════════════
print("== §2 discovery: a new code joins the list ==")
# ════════════════════════════════════════════════════════════════════════════

write_lang("zz", {"name": "Zzz Lang", "menu.file": "Zzz File", "btn.add_server": "Zzz Add"})
names = lang_names()
check("a user file with a NEW code appears in get_available_languages()",
      names.get("zz") == "Zzz Lang", str(names))
check("the built-in languages are all still there next to it",
      set(PKG_CODES) <= set(names), str(sorted(names)))
check("the list stays sorted by the displayed name",
      [lg["name"] for lg in i18n.get_available_languages()]
      == sorted(lg["name"] for lg in i18n.get_available_languages()))
check("the resolution of a user-only code points INTO the user folder",
      i18n.language_file_path("zz") == os.path.join(LANG_DIR, "zz.json"),
      str(i18n.language_file_path("zz")))
check("the user language loads and its values are the translated ones",
      i18n.load_language("zz") is True and i18n.t("menu.file") == "Zzz File"
      and i18n.get_current_language() == "zz", i18n.t("menu.file"))
check("the partial flag of a user file is read from the user folder (a missing flag → False)",
      i18n.is_partial("zz") is False)
i18n.set_language("en")


# ════════════════════════════════════════════════════════════════════════════
print("== §3 shadowing: the user's file wins for its code ==")
# ════════════════════════════════════════════════════════════════════════════

_BUILTIN_RU_NAME = next(lg["name"] for lg in i18n.get_available_languages() if lg["code"] == "ru")
write_lang("ru", {"name": "Schatten-Russisch", "menu.file": "Schatten", "partial": True})
check("a user file with the code of a BUILT-IN language shadows it (the displayed name is the user's)",
      lang_names().get("ru") == "Schatten-Russisch", str(lang_names().get("ru")))
check("the resolution for a shadowed code points into the user folder",
      i18n.language_file_path("ru") == os.path.join(LANG_DIR, "ru.json"))
check("the LOADED values come from the user's file, not from the package one",
      i18n.load_language("ru") is True and i18n.t("menu.file") == "Schatten",
      i18n.t("menu.file"))
check("a user file marked \"partial\": true is reported as partial by the runtime reader",
      i18n.is_partial("ru") is True)
write_cfg({"language": "zz"})
check("get_last_language() honours a saved USER code (it survives a restart)",
      i18n.get_last_language() == "zz", i18n.get_last_language())
write_cfg({"language": "../../etc/passwd"})
check("a broken saved code falls back to the default language",
      i18n.get_last_language() == "en", i18n.get_last_language())
remove_user_file("ru.json")
i18n.set_language("en")
check("removing the user file restores the BUILT-IN language (shadowing is not a replacement)",
      lang_names().get("ru") == _BUILTIN_RU_NAME
      and i18n.load_language("ru") is True and i18n.t("menu.file") != "Schatten",
      f"{lang_names().get('ru')} / {i18n.t('menu.file')}")
i18n.set_language("en")


# ════════════════════════════════════════════════════════════════════════════
print("== §4 broken / non-object / foreign user files are skipped ==")
# ════════════════════════════════════════════════════════════════════════════

write_raw("bad.json", '{"name": "Bad", "menu.file": ')    # truncated JSON
write_raw("arr.json", '["not", "a", "language"]')         # a non-object root
write_raw("meta.json", '{"name": "Only Meta"}')           # no translation key
write_raw("notes.txt", 'this is not even JSON')           # a foreign file
# The requirement is "skipped WITH A LOG LINE", not merely "no crash": capture the
# module's own log seam while the discovery walks the folder. v1.5.2 raised this line
# from DEBUG to WARNING (a skipped file is a real FALLBACK — the built-in takes over),
# so the seam under test is `_log_warning`.
_logged = []
_orig_log_warning = i18n._log_warning
i18n._log_warning = lambda message: _logged.append(str(message))
try:
    _codes = lang_codes()
finally:
    i18n._log_warning = _orig_log_warning
check("every skipped user file leaves a LOG line naming the file and the reason",
      any("bad" in m and "not_json" in m for m in _logged)
      and any("arr" in m and "not_object" in m for m in _logged)
      and any("meta" in m and "no_keys" in m for m in _logged), str(_logged))
check("a broken JSON user file is SKIPPED (it never takes a slot in the menu)",
      "bad" not in _codes and i18n.language_file_path("bad") is None, str(_codes))
check("a non-object JSON root is skipped",
      "arr" not in _codes and i18n.language_file_path("arr") is None)
check("a file without a single translation key is skipped (a label is not a language)",
      "meta" not in _codes and i18n.language_file_path("meta") is None)
check("a non-.json file is ignored by the discovery (and did not abort it)",
      "notes" not in _codes and set(PKG_CODES) <= set(_codes), str(_codes))
check("loading a skipped code fails cleanly (no half-loaded language)",
      i18n.load_language("bad") is False and i18n.get_current_language() == "en")
write_raw("ru.json", "{ not json at all")
check("a BROKEN user file cannot cost the user a built-in language (the built-in is used)",
      lang_names().get("ru") == _BUILTIN_RU_NAME
      and i18n.language_file_path("ru") == os.path.join(PKG_I18N, "ru.json"),
      str(lang_names().get("ru")))
for _name in ("bad.json", "arr.json", "meta.json", "notes.txt", "ru.json", "ru.json.bak"):
    remove_user_file(_name)
check("the discovery is still complete after the garbage (the app starts)",
      "zz" in lang_codes() and set(PKG_CODES) <= set(lang_codes()), str(lang_codes()))


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the strict suite check is neither broken nor weakened ==")
# ════════════════════════════════════════════════════════════════════════════

_pkg_langs = load_i18n_langs(ROOT)
_pkg_problems = i18n_parity_problems(_pkg_langs)
check("the harness discovers the PACKAGE languages only (a user folder is not suite data)",
      sorted(_pkg_langs) == PKG_CODES, f"{sorted(_pkg_langs)} vs {PKG_CODES}")
check("the parity of the package languages is clean with a user folder present "
      "(the pin EXPECTED_I18N_KEYS)",
      not _pkg_problems, str(_pkg_problems))
check("every package language still carries the pinned number of translation keys",
      all(len(translation_keys(d)) == EXPECTED_I18N_KEYS for d in _pkg_langs.values()),
      str({c: len(translation_keys(d)) for c, d in _pkg_langs.items()}))
check("a user file is never graded by the SUITE policy (is_partial is not applied to it)",
      i18n.is_partial("zz") is False
      and not any(i18n.is_partial(c) for c in _pkg_langs))
_check_mod = load_check_script()
_rc, _out = run_check_script(_check_mod, ROOT)
check("tests/check_i18n_keys.py stays green (exit 0) while the user folder is populated",
      _rc == 0, _out[-400:])
check("the runtime SEES the user language while the suite does not — both facts at once",
      "zz" in lang_codes() and "zz" not in sorted(_pkg_langs))


# ════════════════════════════════════════════════════════════════════════════
print("== §6 import: validation, the partial marker, a clean folder on a refusal ==")
# ════════════════════════════════════════════════════════════════════════════

# A COMPLETE file (a full copy of en with its own name) — the "good" import
_complete = dict(_EN_TEMPLATE)
_complete["name"] = "Complete Test"
_src_complete = incoming("good.json", _complete)
_res = i18n.import_language_file(_src_complete)
check("a good file is imported: ok + code + name + the key count",
      _res["ok"] and _res["code"] == "good" and _res["name"] == "Complete Test"
      and _res["keys"] == EXPECTED_I18N_KEYS and not _res["partial"], str(_res))
check("it LANDED in the user folder",
      os.path.isfile(os.path.join(LANG_DIR, "good.json")) and "good.json" in folder_files())
check("it is discoverable at once (the menu and the combo read the folder, not a cache)",
      "good" in lang_codes() and lang_names()["good"] == "Complete Test")
check("a complete import carries no \"partial\" marker (the file is not modified)",
      read_lang_file("good").get("partial") is None)

# An INCOMPLETE file — imported WITH the English-fallback note
_res_p = i18n.import_language_file(incoming("partial_import.json",
                                            {"name": "Partial Test", "menu.file": "Partial File"}))
check("an incomplete file is imported anyway (the runtime en-fallback makes it usable)",
      _res_p["ok"] and _res_p["code"] == "partial_import" and _res_p["keys"] == 1, str(_res_p))
check("the fallback count is reported (meta keys are not translations)",
      _res_p["partial"] is True and _res_p["missing"] == EXPECTED_I18N_KEYS - 1,
      str(_res_p["missing"]))
check("the COPY is marked \"partial\": true on disk (the v1.3.3.1 marker)",
      read_lang_file("partial_import").get("partial") is True)
check("the imported partial file loads and falls back to English for the holes",
      i18n.load_language("partial_import") is True and i18n.t("menu.file") == "Partial File"
      and i18n.t("menu.edit") == _EN_TEMPLATE["menu.edit"], i18n.t("menu.edit"))
i18n.set_language("en")

# Refusals — the folder must stay clean
_before = folder_files()
_res_nj = i18n.import_language_file(incoming("bad_import.json", raw="{not json"))
check("a non-JSON file is refused (\"not_json\") and never reaches the folder",
      _res_nj["error"] == "not_json" and folder_files() == _before, str(folder_files()))
_res_arr = i18n.import_language_file(incoming("arr_import.json", raw='["a", "b"]'))
check("an array root is refused (\"not_object\")",
      _res_arr["error"] == "not_object" and folder_files() == _before)
_res_noname = i18n.import_language_file(incoming("nameless_import.json", {"menu.file": "X"}))
check("a file with NO \"name\" meta key is refused (\"name_missing\") — the folder stays clean",
      _res_noname["error"] == "name_missing" and folder_files() == _before
      and not os.path.isfile(os.path.join(LANG_DIR, "nameless_import.json")))
_res_meta = i18n.import_language_file(incoming("metaonly_import.json", {"name": "Only"}))
check("a file with no translation key is refused (\"no_keys\")",
      _res_meta["error"] == "no_keys" and folder_files() == _before)
_res_missing = i18n.import_language_file(os.path.join(_INCOMING, "no_such_file.json"))
check("a missing source is refused (\"unreadable\")",
      _res_missing["error"] == "unreadable" and folder_files() == _before)
check("an empty / broken source path is refused without raising",
      i18n.import_language_file("")["ok"] is False
      and i18n.import_language_file(None)["ok"] is False)

# An existing user file is REPLACED (the documented "update your language" path)
_updated = dict(_complete)
_updated["menu.file"] = "Updated"
_res_upd = i18n.import_language_file(incoming("good.json", _updated))
check("re-importing the same code REPLACES the user file (shadowing = update)",
      _res_upd["ok"] and read_lang_file("good")["menu.file"] == "Updated"
      and folder_files().count("good.json") == 1)
shutil.rmtree(LANG_DIR, ignore_errors=True)
_res_mk = i18n.import_language_file(_src_complete)
check("the import creates the folder ON DEMAND when it is missing",
      _res_mk["ok"] is True and os.path.isdir(LANG_DIR), LANG_DIR)
check("an unsafe code cannot be resolved (a config.json hand-edit cannot traverse paths)",
      i18n.language_file_path("../../etc/passwd") is None
      and i18n.language_file_path("a/b") is None and i18n.language_file_path(5) is None)


# ════════════════════════════════════════════════════════════════════════════
print("== §7 export: the active language (or the en template) ==")
# ════════════════════════════════════════════════════════════════════════════

_export_path = os.path.join(WORK, "exported_ru.json")
_res_e = i18n.export_language_file("ru", _export_path)
check("the export writes the file that WINS for the code and reports the path + the count",
      _res_e["ok"] and _res_e["path"] == os.path.abspath(_export_path)
      and _res_e["code"] == "ru" and _res_e["keys"] == EXPECTED_I18N_KEYS, str(_res_e))
with open(_export_path, encoding="utf-8") as _f:
    _exported = json.load(_f)
check("the exported file is a readable JSON language file with the same key set",
      set(translation_keys(_exported)) == set(translation_keys(_EN_TEMPLATE)))
_back = i18n.import_language_file(_export_path)
check("the exported file IMPORTS BACK (the round trip)",
      _back["ok"] and _back["code"] == "exported_ru"
      and _back["keys"] == EXPECTED_I18N_KEYS and _back["missing"] == 0, str(_back))
_res_unk = i18n.export_language_file("qq_no_such_language", os.path.join(WORK, "template.json"))
check("an unknown code falls back to the `en` TEMPLATE (the export always produces something)",
      _res_unk["ok"] and _res_unk["code"] == "en"
      and _res_unk["keys"] == EXPECTED_I18N_KEYS, str(_res_unk))
_res_seq = i18n.export_language_file("../etc/passwd", os.path.join(WORK, "template2.json"))
check("an unsafe code falls back to the template too (no path traversal)",
      _res_seq["ok"] and _res_seq["code"] == "en")


# ════════════════════════════════════════════════════════════════════════════
print("== §8 the hub: terminal_max_open is ONE 1..32 range ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
_mw = MW.MainWindow()
_mw.show()
app.processEvents()

write_cfg({"terminal_max_open": 20})
_dlg20 = SD.SettingsDialog(_mw)
check("a saved 20 is DISPLAYED as 20 (the silent-downgrade regression)",
      _dlg20.max_open_spin.value() == 20, str(_dlg20.max_open_spin.value()))
check("the spin's range IS the validator's range (1..32)",
      (_dlg20.max_open_spin.minimum(), _dlg20.max_open_spin.maximum()) == (1, 32)
      and load_terminal_settings()["max_open"] == 20,
      f"{_dlg20.max_open_spin.minimum()}..{_dlg20.max_open_spin.maximum()}")
_dlg20._on_accept()
_cfg_after = i18n.load_config()
check("an open + OK KEEPS 20 (previously it wrote 16 back)",
      _cfg_after.get("terminal_max_open") == 20, str(_cfg_after.get("terminal_max_open")))
write_cfg({"terminal_max_open": 32})
check("32 is accepted by the validator (the upper bound of the unified range)",
      load_terminal_settings()["max_open"] == 32)
write_cfg({"terminal_max_open": 99})
_dlg99 = SD.SettingsDialog(_mw)
check("a saved 99 falls back to 4 in both the validator and the spin",
      load_terminal_settings()["max_open"] == 4 and _dlg99.max_open_spin.value() == 4,
      f"{load_terminal_settings()['max_open']} / {_dlg99.max_open_spin.value()}")


# ════════════════════════════════════════════════════════════════════════════
print("== §9 the hub: the terminal_wheel combo ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
_dlg_w = SD.SettingsDialog(_mw)
check("the combo appears with the two fixed ids (the settings.terminal.* convention)",
      [(_dlg_w.wheel_combo.itemData(i), _dlg_w.wheel_combo.itemText(i))
       for i in range(_dlg_w.wheel_combo.count())]
      == [("scrollback", SD._t("settings.terminal.wheel.scrollback")),
          ("off", SD._t("settings.terminal.wheel.off"))],
      str([_dlg_w.wheel_combo.itemData(i) for i in range(_dlg_w.wheel_combo.count())]))
check("without a config it prefills the documented default (scrollback)",
      _dlg_w.wheel_combo.currentData() == "scrollback")
write_cfg({"terminal_wheel": "off"})
_dlg_w2 = SD.SettingsDialog(_mw)
check("it prefills from the config (\"off\")",
      _dlg_w2.wheel_combo.currentData() == "off", str(_dlg_w2.wheel_combo.currentData()))
_hub_keys = _dlg_w2.collect()
check("collect() carries terminal_wheel (the 21st key — the hub has no config-only key left)",
      _hub_keys.get("terminal_wheel") == "off" and len(_hub_keys) == 22,
      f"{len(_hub_keys)} keys: {sorted(_hub_keys)}")
_dlg_w2._on_accept()
check("OK writes terminal_wheel into config.json",
      i18n.load_config().get("terminal_wheel") == "off",
      str(i18n.load_config().get("terminal_wheel")))
_pg = make_page("wheel")
check("the page still reads the key: \"off\" disables the wheel scrollback on the canvas",
      _pg.widget._wheel_mode == "off", str(_pg.widget._wheel_mode))
_pg.shutdown()
clear_cfg()
_pg_on = make_page("wheel_on")
check("the default (no config) leaves the wheel scrollback on",
      _pg_on.widget._wheel_mode == "scrollback", str(_pg_on.widget._wheel_mode))
_pg_on.shutdown()


# ════════════════════════════════════════════════════════════════════════════
print("== §10 the manager through the real dialog + the live switch ==")
# ════════════════════════════════════════════════════════════════════════════

# §6 wiped the folder (the on-demand-creation check), so the user language of §2
# is put back — the point here is that every CONSUMER sees the folder.
write_lang("zz", {"name": "Zzz Lang", "menu.file": "Zzz File", "btn.add_server": "Zzz Add"})
_mw._populate_language_menu(_mw._lang_menu)
_menu_codes = sorted(a.data() for a in _mw._lang_menu.actions() if a.data())
check("the Help → Language submenu sees the user folder (backed by get_available_languages)",
      "zz" in _menu_codes and set(PKG_CODES) <= set(_menu_codes), str(_menu_codes))
write_lang("ru", {"name": "Dialog Shadow", "menu.file": "S"})
_mw._populate_language_menu(_mw._lang_menu)
check("the submenu shows the USER display name of a shadowing file",
      "Dialog Shadow" in [a.text() for a in _mw._lang_menu.actions()],
      str([a.text() for a in _mw._lang_menu.actions()]))
remove_user_file("ru.json")
_mw._populate_language_menu(_mw._lang_menu)

_dlg = SD.SettingsDialog(_mw)
_dlg.language_changed.connect(_mw._switch_language)   # what _open_settings_dialog() wires
_dlg._refresh_language_combo()
_combo_data = [_dlg.language_combo.itemData(i) for i in range(_dlg.language_combo.count())]
check("the settings combo sees the user folder too (refreshed at open)",
      "zz" in _combo_data and "good" in _combo_data, str(_combo_data))


class _FakeFileDialog:
    """The QFileDialog seam: the two static getters the dialog uses."""
    open_path = ""
    save_path = ""

    @staticmethod
    def getOpenFileName(*_a, **_kw):
        return (_FakeFileDialog.open_path, "JSON (*.json)")

    @staticmethod
    def getSaveFileName(*_a, **_kw):
        return (_FakeFileDialog.save_path, "JSON (*.json)")


_orig_filedialog = SD.QFileDialog
SD.QFileDialog = _FakeFileDialog
try:
    _FakeFileDialog.open_path = incoming("via_button.json",
                                         {"name": "Via Button",
                                          "menu.file": "Via Button File",
                                          "partial": True})
    _dlg._on_import_language()
    _status = _dlg.lang_status_lbl.text()
    check("the import button: the success report names the language and the key count",
          _status.startswith(SD._t("language.imported", name="Via Button", keys=1)), _status)
    check("the report carries the English-fallback note for an incomplete file",
          SD._t("language.incomplete_warning", keys=EXPECTED_I18N_KEYS - 1) in _status, _status)
    check("the imported language became ACTIVE without a restart (the live switch)",
          i18n.get_current_language() == "via_button"
          and _mw.current_language == "via_button", i18n.get_current_language())
    check("the combo rebuilt itself and selects the new language",
          _dlg.language_combo.currentData() == "via_button"
          and "via_button" in [_dlg.language_combo.itemData(i)
                               for i in range(_dlg.language_combo.count())],
          str(_dlg.language_combo.currentData()))

    # A shadowing import of the ACTIVE language re-reads it (no combo change to hang on)
    _FakeFileDialog.open_path = incoming("via_button.json",
                                         {"name": "Via Button",
                                          "menu.file": "Via Button File 2",
                                          "partial": True})
    _dlg._on_import_language()
    check("re-importing the ACTIVE language re-reads it (the shadowing path)",
          i18n.t("menu.file") == "Via Button File 2", i18n.t("menu.file"))

    # A refused import: the report names the reason, the language does NOT move
    _FakeFileDialog.open_path = incoming("refused_button.json", raw="{broken")
    _dlg._on_import_language()
    check("a refused import reports the failure and does not switch the language",
          _dlg.lang_status_lbl.text()
          == SD._t("language.import_failed", error="not a JSON file")
          and i18n.get_current_language() == "via_button", _dlg.lang_status_lbl.text())
    _FakeFileDialog.open_path = incoming("nameless_button.json", {"menu.file": "X"})
    _dlg._on_import_language()
    check("a nameless file is refused through the button with the translated reason",
          SD._t("language.name_missing") in _dlg.lang_status_lbl.text(),
          _dlg.lang_status_lbl.text())
    _status_before_cancel = _dlg.lang_status_lbl.text()
    _FakeFileDialog.open_path = ""
    _FakeFileDialog.save_path = ""
    _dlg._on_import_language()
    _dlg._on_export_language()
    check("a cancelled file dialog is a silent no-op (no report, no write)",
          _dlg.lang_status_lbl.text() == _status_before_cancel,
          _dlg.lang_status_lbl.text())

    # Export through the button
    _export_out = os.path.join(WORK, "button_export.json")
    _FakeFileDialog.save_path = _export_out
    _dlg._on_export_language()
    check("the export button writes the ACTIVE language to the chosen path",
          os.path.isfile(_export_out)
          and _dlg.lang_status_lbl.text()
          == SD._t("language.exported", path=os.path.abspath(_export_out)),
          _dlg.lang_status_lbl.text())
    check("the file written by the button imports back",
          i18n.import_language_file(_export_out)["ok"] is True)
finally:
    SD.QFileDialog = _orig_filedialog
    i18n.set_language("en")

_dlg.retranslate()
check("retranslate() re-texts the two manager buttons (the container rule of AGENTS §4.5)",
      _dlg.import_lang_btn.text() == SD._t("language.import")
      and _dlg.export_lang_btn.text() == SD._t("language.export"),
      f"{_dlg.import_lang_btn.text()!r} / {_dlg.export_lang_btn.text()!r}")
check("the new keys exist in ALL the discovered languages (the release rule)",
      all("language.import" in translation_keys(d)
          and "settings.terminal.wheel.off" in translation_keys(d)
          for d in load_i18n_langs(ROOT).values()))


# ════════════════════════════════════════════════════════════════════════════
print("== §11 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
check_release_state(ROOT)

ST.SSHTerminalThread = _ORIG_THREAD_CLS
finish()
