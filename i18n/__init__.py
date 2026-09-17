"""Internationalization (i18n) system for SSH Map.

Usage:
    from i18n import t, set_language, get_available_languages, current_language
    print(t("menu.file"))  # "File" / "Файл" / "文件" depending on language

    set_language("en")     # Switch to English
    set_language("ru")     # Switch to Russian
    set_language("zh")     # Switch to Chinese

Language files are stored in i18n/ directory as JSON; the FILE NAME is the language
code and every *.json there is a language (no hardcoded list of codes — v1.3.3).
The last-used language is persisted to ~/.sshmap/config.json and restored on startup.

Adding a language (v1.3.3 — no code changes):
    1. copy i18n/en.json to i18n/<code>.json (e.g. i18n/de.json);
    2. set the root meta key "name" to the language name IN ITS OWN LANGUAGE
       ("Deutsch") — that is what the UI shows;
    3. translate every value; all of en's keys must stay present (parity policy:
       a built-in language covers 100% of en's keys);
    4. python tests/check_i18n_keys.py   # green = the language is complete.

The meta key "name" is NOT a translation — it is pinned here and relied upon by the
code:
    * get_available_languages() reads it from the file (missing / broken / empty →
      the language code is shown instead — a language file still works);
    * it is stripped when a language is loaded, so t("name") never resolves to it
      (it returns the key itself, exactly like any other unknown key);
    * the parity checks (tests/check_i18n_keys.py, tests/_common.py) compare the
      TRANSLATION keys only — meta keys are outside the en-parity policy.
The name is displayed in the "Help → Language" submenu and in the "Language" tab of
the settings hub.
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
# module docstring). "name" = the language name in its own language ("Русский").
_META_KEYS = ("name",)


def _log_debug(message: str) -> None:
    """A DEBUG line into ~/.sshmap/logs/sshmap.log — never raises (the logger may be
    uninitialized, e.g. in a bare headless script)."""
    try:
        from modules.logger import get_logger
        get_logger("i18n").debug(message)
    except Exception:  # noqa: BLE001 — i18n must work without the app
        pass


def _strip_meta(data) -> Dict[str, str]:
    """The translations of a language file without the meta keys (v1.3.3).

    A non-dict root (a broken file) yields {} — t() then falls back to English/key.
    """
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k not in _META_KEYS}


def _read_language_name(code: str) -> str:
    """The display name of a language file: the root meta key "name" (v1.3.3).

    Missing key / an empty or non-string value / an unreadable or broken file →
    the CODE (the file name), so a hand-made language file is usable immediately.
    """
    path = os.path.join(_i18n_dir, f"{code}.json")
    name = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            name = data.get(_META_KEYS[0])
    except (json.JSONDecodeError, IOError, OSError):
        name = None
    if isinstance(name, str) and name.strip():
        return name.strip()
    _log_debug(f"language {code!r}: no usable \"name\" meta key — showing the code")
    return code


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
    """Return [{"code", "name"}] for every i18n/*.json — discovered, never hardcoded.

    v1.3.3: the file name is the code and the display name comes from the file's
    "name" meta key (missing / broken → the code). Adding a language = dropping one
    JSON file: no code change, no list to update. Sorted by the displayed name.
    """
    if not os.path.isdir(_i18n_dir):
        return []
    langs = []
    for fname in sorted(os.listdir(_i18n_dir)):
        if fname.endswith(".json"):
            code = fname[:-len(".json")]
            langs.append({"code": code, "name": _read_language_name(code)})
    return sorted(langs, key=lambda x: x["name"])


# ── Core loading ─────────────────────────────────────────────

def load_language(language: str) -> bool:
    """Load translations from a language JSON file. Returns True on success.

    The meta keys ("name") are stripped — they are file metadata, not translations
    (v1.3.3). A file whose root is not a JSON object is not a language file.
    """
    global _translations, _current_language
    
    filepath = os.path.join(_i18n_dir, f"{language}.json")
    if not os.path.isfile(filepath):
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False

        _translations = _strip_meta(data)
        _current_language = language
        return True
    except (json.JSONDecodeError, IOError):
        return False


def get_current_language() -> str:
    """Return current active language code."""
    return _current_language


# ── Translation lookup ───────────────────────────────────────

_en_fallback: Optional[Dict[str, str]] = None


def _get_en_fallback() -> Dict[str, str]:
    """Lazily load en.json as the fallback dictionary (cached after first call).

    The meta keys are stripped here too: t() must never resolve "name" (v1.3.3).
    """
    global _en_fallback
    if _en_fallback is None:
        path = os.path.join(_i18n_dir, "en.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _en_fallback = _strip_meta(json.load(f))
        except (json.JSONDecodeError, IOError, OSError):
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
    """
    config = load_config()
    saved_lang = config.get("language")
    if saved_lang:
        # Verify the saved language file still exists
        filepath = os.path.join(_i18n_dir, f"{saved_lang}.json")
        if os.path.isfile(filepath):
            return saved_lang
    return _default_language


# ── Initialization ───────────────────────────────────────────

# On module load: restore user's last language choice (or use default)
_restore_lang = get_last_language()
_load_result = load_language(_restore_lang)
if not _load_result:
    print(f"[i18n] WARNING: Failed to load language '{_restore_lang}', falling back to '{_default_language}'")
    load_language(_default_language)
