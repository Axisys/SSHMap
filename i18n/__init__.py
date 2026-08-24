"""Internationalization (i18n) system for SSH Map v0.8.

Usage:
    from i18n import t, set_language, get_available_languages, current_language
    print(t("menu.file"))  # "File" / "Файл" / "文件" depending on language
    
    set_language("en")     # Switch to English
    set_language("ru")     # Switch to Russian  
    set_language("zh")     # Switch to Chinese

Language files are stored in i18n/ directory as JSON.
The last-used language is persisted to ~/.sshmap/config.json and restored on startup.
"""

import json
import os
from typing import Optional, Dict


# ── Configuration ──────────────────────────────────────────────

_i18n_dir = os.path.dirname(__file__)  # Points to i18n/ folder
_default_language = "ru"  # Russian is default (developer language)
_current_language: str = _default_language
_translations: Dict[str, str] = {}


# ── Config file helpers ───────────────────────────────────────

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".sshmap")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

_LANG_LABELS = {
    "en": "English",
    "ru": "Русский",
    "zh": "中文",
}


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
    """Return list of available language codes from i18n/ directory."""
    if not os.path.isdir(_i18n_dir):
        return []
    langs = []
    for fname in os.listdir(_i18n_dir):
        if fname.endswith(".json"):
            code = fname.replace(".json", "")
            labels = _LANG_LABELS.get(code, code)
            langs.append({"code": code, "name": labels})
    return sorted(langs, key=lambda x: x["name"])


# ── Core loading ─────────────────────────────────────────────

def load_language(language: str) -> bool:
    """Load translations from a language JSON file. Returns True on success."""
    global _translations, _current_language
    
    filepath = os.path.join(_i18n_dir, f"{language}.json")
    if not os.path.isfile(filepath):
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        _translations = data
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
    """Lazily load en.json as the fallback dictionary (cached after first call)."""
    global _en_fallback
    if _en_fallback is None:
        path = os.path.join(_i18n_dir, "en.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _en_fallback = json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            _en_fallback = {}
    return _en_fallback


def t(key: str, **kwargs) -> str:
    """Translate a key with optional formatting.

    Usage:
        t("dialog.ssh_connect", alias="web-1")  # "SSH Connection — web-1"
        t("msg.confirm_delete", alias=server_alias)

    Falls back to the English translation, then to the key itself.
    """
    translated = _translations.get(key)
    if translated is None:
        translated = _get_en_fallback().get(key, key)

    # Support Python-style formatting: {alias}, {host}, etc.
    if kwargs:
        try:
            translated = translated.format(**kwargs)
        except (KeyError, IndexError, ValueError) as fmt_err:
            # AUDIT v0.7.2 (низкая #20): не глотаем ошибки форматирования перевода в тишине —
            # минимум DEBUG-лог (раньше здесь было молчаливое pass на всех путях вызова).
            try:
                from modules.logger import get_logger as _gl
                _gl("i18n").debug(f"t({key!r}) format failed with {kwargs}: {fmt_err}")
            except Exception:
                pass

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
