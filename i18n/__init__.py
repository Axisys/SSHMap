"""Internationalization (i18n) system for SSH Map.

Usage:
    from i18n import t, set_language, get_available_languages, current_language
    print(t("menu.file"))  # "File" / "Файл" / "文件" depending on language

    set_language("en")     # Switch to English
    set_language("ru")     # Switch to Russian
    set_language("zh")     # Switch to Chinese

Language files are stored in i18n/ directory as JSON; the FILE NAME is the language
code and every *.json there is a language (no hardcoded list of codes — v1.3.3).
Since v1.3.3.8 the USER folder ~/.sshmap/languages/ is discovered next to it.
The last-used language is persisted to ~/.sshmap/config.json and restored on startup.

Adding a language (v1.3.3 — no code changes):
    1. copy i18n/en.json to i18n/<code>.json (e.g. i18n/de.json);
    2. set the root meta key "name" to the language name IN ITS OWN LANGUAGE
       ("Deutsch") — that is what the UI shows;
    3. translate every value; all of en's keys must stay present (parity policy:
       a built-in language covers 100% of en's keys);
    4. python tests/check_i18n_keys.py   # green = the language is complete.

The USER language folder (v1.3.3.8, ROADMAP task 1) — the same recipe WITHOUT
touching the installed package:
    * ~/.sshmap/languages/*.json is a SECOND discovery folder, read next to the
      built-in i18n/ one. The file name is the code here as well;
    * a user file whose code matches a BUILT-IN language SHADOWS it (the user's
      file wins, the built-in one is not read at all); a NEW code adds a language;
    * ~/.sshmap/languages/ is created ON DEMAND only — an import creates it, never
      the import of this module, so no empty directory appears for a user who does
      not care about languages;
    * a user file that cannot be parsed / whose root is not an object / that carries
      no translation key at all is NOT a language: it is SKIPPED with a log line and
      the built-in file of that code (if any) is used instead — a typo in an editor
      can never cost the user a built-in language. Everything else (an incomplete
      file, a missing "name", a stray extra key) loads exactly as a built-in one:
      the runtime never refuses a file, the en fallback covers the holes;
    * the developer's strict parity check (tests/check_i18n_keys.py) walks the
      PACKAGE i18n/ folder only (tests/_common.py i18n_lang_codes()), so a user
      folder can never break or weaken the suite;
    * "partial": true keeps the v1.3.3.1 meaning in the user folder too (see below).

The meta keys are NOT translations — they are pinned here and relied upon by the
code:
    * "name" — the display name: get_available_languages() reads it from the file
      (missing / broken / empty → the language code is shown instead — a language
      file still works);
    * "partial" (v1.3.3.1) — `true` marks a DELIBERATELY incomplete language: the
      file loads and works exactly as any other (the runtime en-fallback is what
      makes it usable), but the parity check reports its missing keys / count
      mismatch as a WARNING instead of a defect. A file WITHOUT the key stays
      STRICT (a missing key AND an extra key are defects);
    * both are STRIPPED when a language is loaded, so t("name") / t("partial")
      never resolve to them (they return the key itself, exactly like any other
      unknown key);
    * the parity checks (tests/check_i18n_keys.py, tests/_common.py) compare the
      TRANSLATION keys only — meta keys are outside the en-parity policy.
The name is displayed in the "Help → Language" submenu and in the "Language" tab of
the settings hub.

Encoding (v1.3.3.1): every language file is read as "utf-8-sig" — a file saved by
Notepad as "UTF-8 with BOM" (the first thing a Windows contributor produces) loads
exactly like a plain UTF-8 one. The BOM is a file-level artifact, never a key.
"""

import json
import os
from typing import Optional, Dict


# ── Configuration ──────────────────────────────────────────────

_i18n_dir = os.path.dirname(__file__)  # Points to i18n/ folder
# v1.1.1 (ROADMAP item 2): English by default — affects only NEW
# users (without a saved config.json); existing users already have the chosen
# language recorded in ~/.sshmap/config.json (get_last_language() returns it).
# Restore Russian: "Help → Language" or the "Language" tab of the settings dialog.
_default_language = "en"  # English is default (v1.1.1; previously "ru")
_current_language: str = _default_language
_translations: Dict[str, str] = {}


# ── Config file helpers ───────────────────────────────────────

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".sshmap")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

# v1.3.3 (ROADMAP): the root meta keys of a language file. They describe the FILE,
# they are not UI strings — excluded from the parity checks and from t() (see the
# module docstring). "name" = the language name in its own language ("Русский");
# "partial" (v1.3.3.1) = `true` marks a deliberately incomplete translation file.
_META_KEYS = ("name", "partial")

# v1.3.3.1 (ROADMAP task 2): a Notepad "UTF-8 with BOM" file must load. Every read
# path of a language file goes through this encoding — the BOM is stripped by the
# codec, so a BOM-prefixed file is byte-for-byte equivalent to a plain UTF-8 one.
_LANG_ENCODING = "utf-8-sig"

# v1.3.3.8 (ROADMAP task 1): the USER language folder — ~/.sshmap/languages/. One
# more discovery source next to the package's i18n/ directory: the USER file wins
# for its code (shadowing), a new code adds a language. The folder is created ON
# DEMAND only (ensure_user_language_dir — the import path), never on import of this
# module, so a user who does not care about languages never sees an empty directory
# appear. The developer's strict parity check walks the PACKAGE folder only
# (tests/_common.py i18n_lang_codes()), so a user folder cannot break the suite.
_USER_LANG_DIRNAME = "languages"

# The reason codes of a rejected file (v1.3.3.8). They are machine values, translated
# by the caller (the import report); the discovery only logs them.
_LANG_ERR_UNREADABLE = "unreadable"
_LANG_ERR_JSON = "not_json"
_LANG_ERR_ROOT = "not_object"
_LANG_ERR_EMPTY = "no_keys"


def _log_debug(message: str) -> None:
    """A DEBUG line into ~/.sshmap/logs/sshmap.log — never raises (the logger may be
    uninitialized, e.g. in a bare headless script)."""
    try:
        from modules.logger import get_logger
        get_logger("i18n").debug(message)
    except Exception:  # noqa: BLE001 — i18n must work without the app
        pass


def _log_warning(message: str) -> None:
    """A WARNING line — the v1.5.2 LANGUAGE-FALLBACK record (ROADMAP task 2).

    A language that cannot be loaded is a real fallback (the app keeps the previous
    one, or English), and until v1.5.2 it was a DEBUG line — invisible in the activity
    panel and easy to miss in the file. `_log_debug` stays for the chatty cases (a
    missing key, a missing "name" meta key); this one is for "your choice was not
    applied, and here is why". Never raises.
    """
    try:
        from modules.logger import get_logger
        get_logger("i18n").warning(message)
    except Exception:  # noqa: BLE001 — i18n must work without the app
        pass


def _strip_meta(data) -> Dict[str, str]:
    """The translations of a language file without the meta keys (v1.3.3).

    A non-dict root (a broken file) yields {} — t() then falls back to English/key.
    """
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k not in _META_KEYS}


# ── The USER language folder and the resolution of a language code ────────────
# v1.3.3.8 (ROADMAP task 1): ONE place decides WHERE the file of a code lives — the
# user folder first (shadowing), the package second. Every consumer (discovery, the
# load path, the name/partial readers, the last-language restore, the import/export
# manager) goes through language_file_path(), so "the user's file wins" holds in one
# place instead of five.


def user_language_dir() -> str:
    """The path of the USER language folder (v1.3.3.8) — it is NOT created here.

    Creation is on demand (`ensure_user_language_dir()`): the folder appears when the
    user imports a language, never on the import of this module.
    """
    return os.path.join(_CONFIG_DIR, _USER_LANG_DIRNAME)


def ensure_user_language_dir() -> bool:
    """Create ~/.sshmap/languages on demand (v1.3.3.8). True = it exists afterwards.

    Called ONLY by the import path (and by the "open the folder" affordances) — never
    at startup, so no empty directory appears for a user who does not use languages.
    Never raises.
    """
    try:
        os.makedirs(user_language_dir(), exist_ok=True)
        return True
    except OSError:
        return False


def _is_safe_language_code(code) -> bool:
    """Is `code` usable as a FILE NAME (one component, no separators)?

    The code comes from a file name in the normal path, but `set_language()` /
    `get_last_language()` accept whatever is in `config.json` — so a hand-edited
    "language": "../../etc/passwd" must not become a path traversal. A separator, an
    empty string, "." and ".." are refused; `pt_BR`, `zh-Hans`, `de` pass.
    """
    if not isinstance(code, str):
        return False
    code = code.strip()
    if not code or code in (".", ".."):
        return False
    if os.path.basename(code) != code:
        return False
    for sep in (os.sep, os.altsep, "/", "\\"):
        if sep and sep in code:
            return False
    return True


def _read_language_file(path: str):
    """Parse a USER language file: (root | None, reason | None) — v1.3.3.8.

    reason ∈ {"unreadable", "not_json", "not_object", "no_keys"} — the short machine
    value the import report translates and the discovery logs. The check is stricter
    than the load path on purpose: a file that cannot be parsed, whose root is not an
    object or that carries no translation key at all is NOT a language — it must not
    take a slot in the menu (and must not shadow a built-in language by accident).
    A merely INCOMPLETE file passes here and loads normally (the en fallback covers
    the holes — the runtime never refuses a file).
    """
    try:
        with open(path, "r", encoding=_LANG_ENCODING) as f:
            data = json.load(f)
    except ValueError:   # json.JSONDecodeError / UnicodeDecodeError are ValueErrors
        return None, _LANG_ERR_JSON
    except OSError:      # IOError is an OSError
        return None, _LANG_ERR_UNREADABLE
    if not isinstance(data, dict):
        return None, _LANG_ERR_ROOT
    if not _strip_meta(data):
        return None, _LANG_ERR_EMPTY
    return data, None


def _builtin_language_path(code) -> Optional[str]:
    """The package file of a code (i18n/<code>.json) or None. Existence only — the
    package files keep the v1.3.3 behaviour (a broken one is still LISTED: it is the
    developer's own file and the strict suite check is what guards it)."""
    if not _is_safe_language_code(code):
        return None
    path = os.path.join(_i18n_dir, f"{code}.json")
    return path if os.path.isfile(path) else None


def _user_language_path(code) -> Optional[str]:
    """The USABLE user file of a code or None (v1.3.3.8).

    "Usable" = parses, object root, at least one translation key (see
    `_read_language_file`). A refused file is logged and IGNORED — the built-in file
    of the same code (if any) is then used, so a broken user file can never cost the
    user a built-in language and never breaks the startup.
    """
    if not _is_safe_language_code(code):
        return None
    code = code.strip()
    path = os.path.join(user_language_dir(), f"{code}.json")
    if not os.path.isfile(path):
        return None
    data, reason = _read_language_file(path)
    if data is None:
        # v1.5.2 (ROADMAP task 2): a WARNING, not a DEBUG line — the built-in file takes
        # over here, i.e. the user's own file is silently ignored unless the log says so.
        _log_warning(f"user language {code!r} skipped ({reason}) — not a language file: {path}")
        return None
    return path


def language_file_path(code) -> Optional[str]:
    """The file that WINS for `code` — the USER folder first, the package second.

    v1.3.3.8 (ROADMAP task 1): the shadowing rule lives HERE, in one place. None means
    "no such language" (the caller keeps its default). Never raises.
    """
    return _user_language_path(code) or _builtin_language_path(code)


def _read_language_name(code: str) -> str:
    """The display name of a language file: the root meta key "name" (v1.3.3).

    Missing key / an empty or non-string value / an unreadable or broken file →
    the CODE (the file name), so a hand-made language file is usable immediately.
    v1.3.3.8: the file is the one that WINS for the code (the user folder shadows).
    A file that is not valid UTF-8 is "broken" like any other: `UnicodeDecodeError`
    is a `ValueError` and is caught here exactly as `_read_language_file()` catches
    it, so `get_available_languages()` can never raise on one.
    """
    path = language_file_path(code)
    name = None
    if path is not None:
        try:
            with open(path, "r", encoding=_LANG_ENCODING) as f:
                data = json.load(f)
            if isinstance(data, dict):
                name = data.get(_META_KEYS[0])
        except (ValueError, IOError, OSError):
            name = None
    if isinstance(name, str) and name.strip():
        return name.strip()
    _log_debug(f"language {code!r}: no usable \"name\" meta key — showing the code")
    return code


def is_partial(language: str) -> bool:
    """Is this language file marked `"partial": true` (v1.3.3.1, ROADMAP task 2)?

    A partial file is a deliberately INCOMPLETE translation: it loads and works
    exactly like a complete one (the runtime en-fallback is unchanged — a missing
    key falls back to English), but the parity check reports its missing keys and
    its key count as a WARNING rather than a defect. Only a real JSON `true` counts
    (a string "true" / 1 / a missing key → False: the strict policy). Never raises.
    v1.3.3.8: reads the file that WINS for the code (the user folder shadows).
    """
    path = language_file_path(language)
    if path is None:
        return False
    try:
        with open(path, "r", encoding=_LANG_ENCODING) as f:
            data = json.load(f)
    except (ValueError, IOError, OSError):
        return False
    return isinstance(data, dict) and data.get("partial") is True


def _ensure_config_dir() -> bool:
    """Create ~/.sshmap if it doesn't exist."""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def load_config() -> dict:
    """Load user config from ~/.sshmap/config.json.
    
    Returns an empty dict on any error (missing file, bad JSON, etc.).
    Never raises.
    """
    if not os.path.isfile(_CONFIG_FILE):
        return {}
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, IOError, OSError):
        pass
    return {}


def save_config(partial_update: dict) -> bool:
    """Atomically save partial config update to ~/.sshmap/config.json.
    
    Preserves existing keys — only overwrites the ones in partial_update.
    Returns False on any I/O error.
    """
    if not _ensure_config_dir():
        return False
    
    # Read existing, merge, write back
    current = load_config()
    current.update(partial_update)
    
    try:
        tmp_file = _CONFIG_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename (works on same filesystem)
        os.replace(tmp_file, _CONFIG_FILE)
        return True
    except OSError:
        try:
            os.remove(tmp_file)
        except OSError:
            pass
        return False


# ── Available languages ───────────────────────────────────────

def get_available_languages() -> list:
    """Return [{"code", "name"}] for every discovered language — never hardcoded.

    v1.3.3: the file name is the code and the display name comes from the file's
    "name" meta key (missing / broken → the code). Adding a language = dropping one
    JSON file: no code change, no list to update. Sorted by the displayed name.

    v1.3.3.8 (ROADMAP task 1): the USER folder `~/.sshmap/languages/` is merged in
    next to the package `i18n/` one. A user file with the code of a built-in language
    SHADOWS it (the displayed name comes from the user's file); a new code adds a
    language. A user file that is not a usable language file is skipped with a log
    line and the built-in file is used instead (see `_user_language_path`).
    """
    codes = []
    for folder in (_i18n_dir, user_language_dir()):
        if not os.path.isdir(folder):
            continue
        for fname in sorted(os.listdir(folder)):
            if not fname.endswith(".json"):
                continue
            code = fname[:-len(".json")]
            if code in codes or language_file_path(code) is None:
                continue
            codes.append(code)
    return sorted(({"code": code, "name": _read_language_name(code)} for code in codes),
                  key=lambda x: x["name"])


# ── Core loading ─────────────────────────────────────────────

def load_language(language: str) -> bool:
    """Load translations from a language JSON file. Returns True on success.

    The meta keys ("name") are stripped — they are file metadata, not translations
    (v1.3.3). A file whose root is not a JSON object is not a language file.
    v1.3.3.8: the file that WINS for the code is loaded (the USER folder shadows the
    package one), so an edited or replaced user file is picked up without a restart.

    A file that is not valid UTF-8 is a BROKEN file, not a crash: `UnicodeDecodeError`
    is a `ValueError` and is caught here (the `_read_language_file()` precedent), which
    matters most for a broken PACKAGE file of the ACTIVE language — `load_language()`
    runs during the import of `i18n` itself, i.e. on the startup path.
    """
    global _translations, _current_language

    filepath = language_file_path(language)
    if filepath is None:
        # v1.5.2 (ROADMAP task 2): the OTHER half of the language-fallback record — the
        # active language is kept and the caller only learns "False" without this line.
        _log_warning(f"language {language!r} not loaded (no usable file) — keeping "
                     f"{_current_language!r}")
        return False

    try:
        with open(filepath, "r", encoding=_LANG_ENCODING) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _log_warning(f"language {language!r} not loaded (the root of {filepath} is not "
                         f"an object) — keeping {_current_language!r}")
            return False

        _translations = _strip_meta(data)
        _current_language = language
        return True
    except (ValueError, IOError) as e:
        _log_warning(f"language {language!r} not loaded ({e!r}) — keeping "
                     f"{_current_language!r}")
        return False


def reload_current_language() -> bool:
    """Re-read the ACTIVE language file from disk (v1.3.3.1, ROADMAP task 3).

    The "Help → Language → Rescan the language files" action uses this: the language
    list itself is re-read by the menu rebuild, while an EDITED translation of the
    active language needs an explicit re-load. The current language keeps working
    from memory when its file disappeared or broke (returns False — the caller only
    reports it). Never raises.
    """
    return load_language(_current_language)


def get_current_language() -> str:
    """Return current active language code."""
    return _current_language


# ── v1.3.3.8 (ROADMAP task 2): the language manager (import / export) ──────────
# The two halves of "let the user bring a language in and take one out" without a
# language EDITOR (deliberately not in v1.3.3.8): the file stays the user's to edit
# in any text editor, the application only VALIDATES, COPIES and REPORTS. Both
# helpers return a plain dict of facts (never a UI string) — the "Language" tab of
# the settings hub is what turns them into the i18n messages of `language.*`.

def _atomic_write_json(path: str, data) -> bool:
    """Write JSON atomically (tmp + os.replace) — the storage/autosave pattern. Never raises."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def import_language_file(source_path) -> dict:
    """Validate + copy ONE foreign language file into the USER folder (v1.3.3.8).

    Validation — a file that fails ANY of these checks NEVER reaches the folder
    (it is not copied, not even as a broken half):
      * it is readable and parses as JSON                 → "unreadable" / "not_json";
      * the root is a JSON OBJECT                         → "not_object";
      * it carries at least one TRANSLATION key (the meta keys alone are not a
        language: `{"name": "Xx"}` is a label, not a translation) → "no_keys";
      * it declares a display name in the `"name"` meta key → "name_missing";
      * the file name is usable as a language code        → "bad_code".

    The `"name"` requirement is the stricter half of the ROADMAP wording ("the
    `"name"` meta key or a warning"): the acceptance pins "a file without `"name"` is
    refused and the folder stays clean", and a language in the menu must be able to
    say what it is called. (A nameless file DROPPED IN BY HAND still works — the
    runtime shows the code, the v1.3.3 rule; only the IMPORT asks for the name.)

    A file that passes and is INCOMPLETE (its key set misses keys of the reference
    `en`) is imported anyway: `"partial": true` is written into the COPY (the
    v1.3.3.1 marker — the file declares itself unfinished) and the number of keys
    that fall back to English is reported, because the runtime en-fallback makes it
    usable at once. An existing file of the same code is REPLACED atomically — that
    is the documented "shadow the built-in / update your language" path.

    Returns {"ok": bool, "error": str, "path": str, "code": str, "name": str,
             "keys": int, "missing": int, "partial": bool}.
    `error` is one of the machine reasons above (empty when ok); everything else is
    data for the report. Never raises.
    """
    result = {"ok": False, "error": _LANG_ERR_UNREADABLE, "path": "", "code": "",
              "name": "", "keys": 0, "missing": 0, "partial": False}

    try:
        source = os.path.abspath(os.path.expanduser(str(source_path or "")))
    except (TypeError, ValueError):
        return result
    if not source or not os.path.isfile(source):
        return result

    data, reason = _read_language_file(source)
    if data is None:
        result["error"] = reason
        return result

    code = os.path.splitext(os.path.basename(source))[0]
    if not _is_safe_language_code(code):
        result["error"] = "bad_code"
        return result
    code = code.strip()

    name_value = data.get(_META_KEYS[0])
    name = name_value.strip() if isinstance(name_value, str) and name_value.strip() else ""
    if not name:
        result["error"] = "name_missing"
        return result

    translations = _strip_meta(data)
    reference = _get_en_fallback()
    missing = [k for k in reference if k not in translations] if reference else []
    partial = bool(missing)

    payload = dict(data)
    if partial:
        payload["partial"] = True   # the v1.3.3.1 marker: "this file is unfinished"

    if not ensure_user_language_dir():
        result["error"] = "copy_failed"
        return result
    destination = os.path.join(user_language_dir(), f"{code}.json")
    if not _atomic_write_json(destination, payload):
        result["error"] = "copy_failed"
        return result

    result.update({"ok": True, "error": "", "path": destination, "code": code,
                   "name": name, "keys": len(translations),
                   "missing": len(missing), "partial": partial})
    _log_debug(f"language {code!r} imported into the user folder "
               f"({len(translations)} keys, {len(missing)} falling back to {_default_language})")
    return result


def export_language_file(code, destination_path) -> dict:
    """Write the file that WINS for `code` into `destination_path` (v1.3.3.8).

    "Export the current language": the caller passes `get_current_language()`. An
    empty / unknown / unsafe code falls back to the reference `en`, so the button
    ALWAYS produces something importable (the en template is the documented way to
    start a new translation). The file that WINS is exported — a user file shadows
    the built-in one, exactly as at load time — and the copy is written from the
    parsed data as plain UTF-8 (a BOM is dropped), so it imports back unchanged.

    Returns {"ok": bool, "error": str, "path": str, "code": str, "keys": int};
    `error` ∈ {"unknown_language", "unreadable", "not_json", "not_object",
    "write_failed"}. Never raises.
    """
    result = {"ok": False, "error": "unknown_language", "path": "", "code": "",
              "keys": 0}

    wanted = code if _is_safe_language_code(code) else ""
    source = language_file_path(wanted) if wanted else None
    if source is None:
        source = language_file_path(_default_language)
        wanted = _default_language
    if source is None:
        return result

    try:
        with open(source, "r", encoding=_LANG_ENCODING) as f:
            data = json.load(f)
    except ValueError:   # json.JSONDecodeError / UnicodeDecodeError are ValueErrors
        result["error"] = _LANG_ERR_JSON
        return result
    except OSError:      # IOError is an OSError
        result["error"] = _LANG_ERR_UNREADABLE
        return result
    if not isinstance(data, dict):
        result["error"] = _LANG_ERR_ROOT
        return result

    try:
        destination = os.path.abspath(os.path.expanduser(str(destination_path or "")))
    except (TypeError, ValueError):
        return result
    if not destination:
        return result
    if not _atomic_write_json(destination, data):
        result["error"] = "write_failed"
        return result

    result.update({"ok": True, "error": "", "path": destination, "code": wanted,
                   "keys": len(_strip_meta(data))})
    return result


# ── Translation lookup ───────────────────────────────────────

_en_fallback: Optional[Dict[str, str]] = None


def _get_en_fallback() -> Dict[str, str]:
    """Lazily load en.json as the fallback dictionary (cached after first call).

    The meta keys are stripped here too: t() must never resolve "name" (v1.3.3).
    Deliberately the PACKAGE file, never the user one: the reference must not be
    shadowable, or a user's partial `en.json` would shrink the fallback of every
    other language (v1.3.3.8). The import report uses this dict as its reference too.
    An unreadable reference (including a file that is not valid UTF-8 — a `ValueError`)
    answers an EMPTY fallback: `t()` then answers the key itself, never an exception.
    """
    global _en_fallback
    if _en_fallback is None:
        path = os.path.join(_i18n_dir, "en.json")
        try:
            with open(path, "r", encoding=_LANG_ENCODING) as f:
                _en_fallback = _strip_meta(json.load(f))
        except (ValueError, IOError, OSError):
            _en_fallback = {}
    return _en_fallback


def t(key: str, **kwargs) -> str:
    """Translate a key with optional formatting.

    Usage:
        t("dialog.ssh_connect", alias="web-1")  # "SSH Connection — web-1"
        t("msg.confirm_delete", alias=server_alias)

    Falls back to the English translation, then to the key itself.
    A meta key ("name") never resolves — it is stripped on load (v1.3.3).
    """
    translated = _translations.get(key)
    if translated is None:
        translated = _get_en_fallback().get(key, key)

    # Support Python-style formatting: {alias}, {host}, etc.
    if kwargs:
        try:
            translated = translated.format(**kwargs)
        except (KeyError, IndexError, ValueError) as fmt_err:
            # AUDIT v0.7.2 (low #20): do not swallow translation formatting errors silently —
            # at minimum a DEBUG log (previously a silent pass on all call paths).
            _log_debug(f"t({key!r}) format failed with {kwargs}: {fmt_err}")

    return translated


def set_language(language: str) -> bool:
    """Switch to a different language and persist the choice. Returns True if successful."""
    result = load_language(language)
    
    # Persist the choice so it survives restarts
    if result:
        save_config({"language": language})
    
    return result


# ── Public API for MainWindow ────────────────────────────────

def get_last_language() -> str:
    """Return the last-used language from config, or default.
    
    This function is called by ui/main_window.py on startup to restore
    the user's preferred language before any UI elements are created.
    v1.3.3.8: the saved code is validated against the RESOLUTION (the user folder or
    the package), so a language imported by the user survives a restart too. A broken
    code (a non-string, a path traversal attempt) falls back to the default.
    """
    config = load_config()
    saved_lang = config.get("language")
    if saved_lang:
        if language_file_path(saved_lang) is not None:
            return saved_lang
    return _default_language


# ── Initialization ───────────────────────────────────────────

# On module load: restore user's last language choice (or use default)
_restore_lang = get_last_language()
_load_result = load_language(_restore_lang)
if not _load_result:
    print(f"[i18n] WARNING: Failed to load language '{_restore_lang}', falling back to '{_default_language}'")
    load_language(_default_language)
