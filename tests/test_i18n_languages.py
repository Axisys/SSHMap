"""v1.3.3 — Languages without writing code ("name" in JSON + parity policy + documentation): the release's themed test.

ROADMAP v1.3.3 (tasks 1–4):
  #1 the meta key "name" at the root of every language file; get_available_languages()
     reads the display name FROM THE FILE (missing / broken → the code); the hardcoded
     dict _LANG_LABELS is gone; the meta key is not a translation (excluded from the
     parity checks and from t() — pinned in the i18n module docstring);
  #2 the parity policy — a built-in language covers 100% of en's keys (strict) and the
     count matches the EXPECTED_I18N_KEYS pin; auto-discovery of ALL i18n/*.json;
  #3 the fallback behavior — documented, unchanged (a key missing in the active
     language → the en value; a new user → en; a saved language validated by file
     existence);
  #4 the documentation — a "How to add a language" section in DOCUMENTATION.md.

The sections of this file:
  §1 discovery — every i18n/*.json is a language, sorted by the displayed name;
  §2 the name comes from the file — a dropped-in language, a missing / empty /
     non-string / broken "name" (→ the code), no hardcoded label dict in the code;
  §3 the meta key is not a translation — t("name") never resolves, the key is stripped
     on load and absent from the en fallback, t() falls back to en / to the key;
  §4 the parity policy — en is the reference, strict key sets, the pinned count, the
     meta keys ignored (the harness helpers of tests/_common.py);
  §5 tests/check_i18n_keys.py — auto-discovery + parity over the discovered files
     (a complete dropped-in language → exit 0, a missing key everywhere → exit 1);
  §6 the UI shows the JSON name (the settings hub "Language" tab) + the release state.

Run: python tests/test_i18n_languages.py   (from the project root) or python tests/run_all.py
"""
import importlib.util
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, snapshot_i18n_config, restore_i18n_config,
                     i18n_lang_codes, i18n_parity_problems, translation_keys,
                     I18N_META_KEYS, I18N_REFERENCE, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

import i18n  # noqa: E402

I18N_DIR = os.path.join(ROOT, "i18n")
_CFG_SNAP = snapshot_i18n_config()   # the tests switch the language → config.json


# ── helpers ──────────────────────────────────────────────────────────────────

def read_lang(code, root=None):
    with open(os.path.join(root or ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        return json.load(f)


def write_lang(code, data, root):
    with open(os.path.join(root, "i18n", f"{code}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_fake_project(name, mutate=None):
    """A fake project root: i18n/en.json (a real copy) + i18n/xx.json (en ⊕ mutate).

    mutate(data) may change the dropped-in language: remove a key, add one, break
    the "name". No .py files — the used-keys part of check_i18n_keys.py stays clean.
    """
    root = os.path.join(WORK, name)
    os.makedirs(os.path.join(root, "i18n"), exist_ok=True)
    en = read_lang("en")
    xx = dict(en)
    xx["name"] = "Xx"
    if mutate:
        mutate(xx)
    write_lang("en", en, root)
    write_lang("xx", xx, root)
    return root


def with_lang_dir(path):
    """Temporarily point the i18n module at another i18n/ directory (the test seam)."""
    class _Ctx:
        def __enter__(self):
            self._saved = i18n._i18n_dir
            i18n._i18n_dir = path
            return path

        def __exit__(self, *exc):
            i18n._i18n_dir = self._saved
            return False
    return _Ctx()


def load_check_script():
    """tests/check_i18n_keys.py as a module (main(root=…) — an isolated run, no subprocess)."""
    path = os.path.join(ROOT, "tests", "check_i18n_keys.py")
    spec = importlib.util.spec_from_file_location("_i18n_check_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_check_script(mod, root):
    """(exit code, the captured output) of check_i18n_keys.main(root)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(root=root)
    return rc, buf.getvalue()


# ════════════════════════════════════════════════════════════════════════════
print("== §1 discovery ==")
# ════════════════════════════════════════════════════════════════════════════
langs = i18n.get_available_languages()
codes = [lg["code"] for lg in langs]
file_codes = i18n_lang_codes(ROOT)

check("get_available_languages() returns entries of {code, name}",
      bool(langs) and all(set(lg) == {"code", "name"} for lg in langs), str(langs))
check("discovery covers EVERY i18n/*.json (no hardcoded list)", sorted(codes) == file_codes,
      f"{sorted(codes)} vs {file_codes}")
check("the built-in languages are discovered (en/ru/zh)",
      {"en", "ru", "zh"} <= set(codes), str(codes))
check("sorted by the displayed name",
      [lg["name"] for lg in langs] == sorted(lg["name"] for lg in langs),
      str([lg["name"] for lg in langs]))
check("the code is the file name (i18n/<code>.json)",
      all(os.path.isfile(os.path.join(I18N_DIR, f"{lg['code']}.json")) for lg in langs))

# The names come from the JSON, not from the code (the v1.3.3 goal)
names = {lg["code"]: lg["name"] for lg in langs}
for code, expected in (("en", "English"), ("ru", "Русский"), ("zh", "中文")):
    check(f"the name of {code} comes from the file (\"{expected}\")",
          names.get(code) == expected, repr(names.get(code)))
    check(f"i18n/{code}.json carries the meta key name == {expected!r}",
          read_lang(code).get("name") == expected, repr(read_lang(code).get("name")))
check("every discovered name equals the \"name\" value of its own file",
      all(names[c] == read_lang(c).get("name") for c in codes),
      str({c: (names[c], read_lang(c).get("name")) for c in codes}))
check("the harness discovers the same languages (load_i18n_langs)",
      sorted(load_i18n_langs(ROOT)) == file_codes, str(sorted(load_i18n_langs(ROOT))))

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the name comes from the file (a dropped-in language, no code change) ==")
# ════════════════════════════════════════════════════════════════════════════
fake = make_fake_project("dropped_in")
fake_i18n = os.path.join(fake, "i18n")
with with_lang_dir(fake_i18n):
    got = {lg["code"]: lg["name"] for lg in i18n.get_available_languages()}
    check("a dropped-in i18n/xx.json is discovered with its own name",
          got.get("xx") == "Xx", str(got))
    check("the fake project is discovered entirely (en + xx)",
          sorted(got) == ["en", "xx"], str(sorted(got)))
    check("a dropped-in language is loadable at once (file name = code)",
          i18n.load_language("xx") is True and i18n.get_current_language() == "xx")
    i18n.load_language("en")  # leave the module on the real language file content
check("the i18n directory is restored after the seam",
      i18n._i18n_dir == I18N_DIR, i18n._i18n_dir)

# Missing / broken "name" → the CODE (the file still works)
no_name = make_fake_project("no_name", lambda d: d.pop("name", None))
with with_lang_dir(os.path.join(no_name, "i18n")):
    got = {lg["code"]: lg["name"] for lg in i18n.get_available_languages()}
    check("a file without \"name\" falls back to the code", got.get("xx") == "xx", str(got))
    check("the name-less language still loads (translations are intact)",
          i18n.load_language("xx") is True and i18n.t("menu.file") == "File")
    i18n.load_language("en")

for label, value in (("an empty", ""), ("a whitespace-only", "   "), ("a non-string (int)", 5),
                     ("a list", ["Xx"]), ("null", None)):
    slug = "".join(ch if ch.isalnum() else "_" for ch in label.split()[-1])
    bad = make_fake_project(f"name_{slug}", lambda d, v=value: d.update({"name": v}))
    with with_lang_dir(os.path.join(bad, "i18n")):
        got = {lg["code"]: lg["name"] for lg in i18n.get_available_languages()}
        check(f"{label} \"name\" falls back to the code", got.get("xx") == "xx", str(got))

# A broken JSON file: the code is shown and other languages are unaffected
broken = make_fake_project("broken_json")
with open(os.path.join(broken, "i18n", "xx.json"), "w", encoding="utf-8") as f:
    f.write('{"name": "Xx", "menu.file": ')   # truncated JSON
with with_lang_dir(os.path.join(broken, "i18n")):
    got = {lg["code"]: lg["name"] for lg in i18n.get_available_languages()}
    check("a broken JSON falls back to the code (discovery does not raise)",
          got.get("xx") == "xx" and got.get("en") == "English", str(got))
    check("a broken JSON is not loadable (no half-loaded language)",
          i18n.load_language("xx") is False)

# A JSON root that is not an object
array_root = make_fake_project("array_root")
with open(os.path.join(array_root, "i18n", "xx.json"), "w", encoding="utf-8") as f:
    f.write('["not", "a", "language"]')
with with_lang_dir(os.path.join(array_root, "i18n")):
    got = {lg["code"]: lg["name"] for lg in i18n.get_available_languages()}
    check("a non-object JSON root falls back to the code", got.get("xx") == "xx", str(got))
    check("a non-object JSON root is not loadable", i18n.load_language("xx") is False)

# The hardcoded dict is gone: the language names live ONLY in the JSON files
check("_LANG_LABELS is removed from the i18n module", not hasattr(i18n, "_LANG_LABELS"))
_i18n_src = open(os.path.join(ROOT, "i18n", "__init__.py"), encoding="utf-8").read()
_labels_re = re.compile(r"""["'](?:en|ru|zh|de|es|fr)["']\s*:\s*["'][^"']+["']""")
check("no hardcoded code → display-name dict is left in i18n/__init__.py",
      _labels_re.search(_i18n_src) is None and "_LANG_LABELS" not in _i18n_src,
      str(_labels_re.findall(_i18n_src)))
check("the module docstring pins the \"name\" meta-key policy (v1.3.3)",
      "meta key" in (i18n.__doc__ or "") and "name" in (i18n.__doc__ or ""))
check("the meta keys of the module and the harness agree",
      set(I18N_META_KEYS) == set(i18n._META_KEYS) == {"name", "partial"},
      str((sorted(I18N_META_KEYS), sorted(i18n._META_KEYS))))

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the meta key is NOT a translation (t() / load / fallback) ==")
# ════════════════════════════════════════════════════════════════════════════
check("t(\"name\") never resolves to the language name", i18n.t("name") == "name",
      repr(i18n.t("name")))
check("the meta key is stripped when a language is loaded",
      "name" not in i18n._translations, str(sorted(i18n._translations)[:3]))
check("the en fallback dictionary carries no meta keys",
      "name" not in i18n._get_en_fallback())

check("a new user (no config) gets the default language en", i18n._default_language == "en",
      i18n._default_language)
check("a saved language is validated by file existence (get_last_language)",
      i18n.get_last_language() in i18n_lang_codes(ROOT), i18n.get_last_language())

i18n.set_language("ru")
check("switching a language still works (ru loaded)",
      i18n.get_current_language() == "ru" and i18n.t("menu.file") == read_lang("ru")["menu.file"],
      repr(i18n.t("menu.file")))
check("the meta key stays invisible in a non-en language too", i18n.t("name") == "name",
      repr(i18n.t("name")))

# t() fallback: a key missing in the ACTIVE language → the en value; nowhere → the key
_saved_translations = dict(i18n._translations)
i18n._translations.pop("menu.file", None)
check("a key missing in the active language → the en value (fallback)",
      i18n.t("menu.file") == read_lang("en")["menu.file"], repr(i18n.t("menu.file")))
check("a key missing everywhere → the key itself",
      i18n.t("no.such.key") == "no.such.key", repr(i18n.t("no.such.key")))
i18n._translations.clear()
i18n._translations.update(_saved_translations)
check("the translations are restored after the fallback probe",
      "name" not in i18n._translations and i18n.t("menu.file") == read_lang("ru")["menu.file"])

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the parity policy (100% of en, strict; the pin) ==")
# ════════════════════════════════════════════════════════════════════════════
check("the released files satisfy the parity policy (no problems)",
      i18n_parity_problems(load_i18n_langs(ROOT)) == [],
      str(i18n_parity_problems(load_i18n_langs(ROOT))[:3]))
check("en is the reference language of the policy", I18N_REFERENCE == "en", I18N_REFERENCE)
check("the pin counts the TRANSLATION keys (the meta key is excluded)",
      all(len(translation_keys(d)) == EXPECTED_I18N_KEYS for d in load_i18n_langs(ROOT).values()),
      str({c: len(translation_keys(d)) for c, d in load_i18n_langs(ROOT).items()}))
check("translation_keys() drops the meta key", translation_keys({"name": "x", "a": "b"}) == {"a"})

_base = {c: dict(d) for c, d in load_i18n_langs(ROOT).items()}
_missing = {c: dict(d) for c, d in _base.items()}
_missing["ru"].pop("menu.file")
_problems = i18n_parity_problems(_missing)
check("a missing key in ONE language → FAIL (the defect names the language and the key)",
      any("ru" in p and "menu.file" in p for p in _problems), str(_problems))
check("the missing key is also caught by the count", any("EXPECTED_I18N_KEYS" in p for p in _problems),
      str(_problems))

_extra = {c: dict(d) for c, d in _base.items()}
_extra["zh"]["zz.extra"] = "b"
_problems = i18n_parity_problems(_extra)
check("an extra key in ONE language → FAIL (strict parity)",
      any("zz.extra" in p for p in _problems), str(_problems))

_count = i18n_parity_problems({"en": {"a": "1"}, "xx": {"a": "2"}}, expected_keys=2)
check("a count different from the pin → FAIL", len(_count) == 2 and "EXPECTED_I18N_KEYS" in _count[0],
      str(_count))
check("the meta keys are ignored by the parity check",
      i18n_parity_problems({"en": {"name": "English", "a": "1"}, "xx": {"a": "2"}},
                           expected_keys=1) == [])
check("a language file without the meta key still passes the parity check",
      i18n_parity_problems({"en": {"a": "1"}, "xx": {"a": "2"}}, expected_keys=1) == [])
check("a missing reference language is reported",
      any("reference" in p for p in i18n_parity_problems({"ru": {"a": "1"}}, expected_keys=1)))

# ════════════════════════════════════════════════════════════════════════════
print("== §5 check_i18n_keys.py (auto-discovery + the parity over the discovered files) ==")
# ════════════════════════════════════════════════════════════════════════════
_checker = load_check_script()
_rc, _out = run_check_script(_checker, ROOT)
check("the real project passes the check (exit 0)", _rc == 0, _out[-400:])
check("the report names the discovered languages and the count",
      "en, ru, zh" in _out and str(EXPECTED_I18N_KEYS) in _out, _out[:300])

_ok_root = make_fake_project("check_ok")
_rc, _out = run_check_script(_checker, _ok_root)
check("a COMPLETE dropped-in language passes (exit 0, no code change needed)",
      _rc == 0, _out[-400:])
check("the check discovers the dropped-in language (not just en/ru/zh)",
      "en, xx" in _out, _out[:300])

_bad_root = make_fake_project("check_missing", lambda d: d.pop("menu.file"))
_rc, _out = run_check_script(_checker, _bad_root)
check("a missing key in a discovered language → FAIL (exit 1)", _rc == 1, _out[-400:])
check("the FAIL names the language and the key", "xx" in _out and "menu.file" in _out, _out[-400:])
check("the pinned count is enforced too (457 != pin)", "EXPECTED_I18N_KEYS" in _out, _out[-400:])

_extra_root = make_fake_project("check_extra", lambda d: d.update({"zz.extra": "b"}))
_rc, _out = run_check_script(_checker, _extra_root)
check("an extra key in a discovered language → FAIL (strict parity)", _rc == 1, _out[-400:])

# ════════════════════════════════════════════════════════════════════════════
print("== §6 the UI shows the JSON name (the settings hub) + the release state ==")
# ════════════════════════════════════════════════════════════════════════════
from PySide6.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication(sys.argv)
from ui.settings_dialog import SettingsDialog  # noqa: E402

_dlg = SettingsDialog(None)
_combo = _dlg.language_combo
_items = {_combo.itemData(i): _combo.itemText(i) for i in range(_combo.count())}
check("the \"Language\" tab lists every discovered language", sorted(_items) == file_codes,
      str(sorted(_items)))
check("the combo shows the names from the JSON files (en/ru/zh)",
      _items.get("ru") == "Русский" and _items.get("zh") == "中文" and _items.get("en") == "English",
      str(_items))
check("the combo shows exactly what get_available_languages() returns",
      all(_items.get(lg["code"]) == lg["name"] for lg in langs), str(_items))
_dlg.close()
_dlg.destroy()

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

restore_i18n_config(_CFG_SNAP)
finish()
