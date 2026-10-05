# -*- coding: utf-8 -*-
"""The terminal family's CONFIG surface — the keys, the declared values and the four readers.

Every `terminal_*` / `ui_*` key of the terminal family is declared HERE once: the accepted values
(`TERMINAL_MODES`, `FILES_MODES`), the defaults (`FILES_MODE_DEFAULT`), the panel's declared floors
and the four module-level loaders — `load_terminal_settings()`, `resolve_files_mode()`,
`load_files_panel_settings()` and `load_split_settings()`. `modules/ssh_terminal.py` and
`modules/terminal_split.py` RE-EXPORT them, because ssh_terminal is the family's live namespace the
suite reads (`ST.load_terminal_settings`) and the split module keeps its shipped surface; a reader
never raises, and an unusable value answers the DEFAULT (`AGENTS.md` §4.3, `DOCUMENTATION.md` §64).
"""

try:
    from .terminal_screen import (DEFAULT_HISTORY_LINES, SCROLL_MODE_DEFAULT, SCROLL_MODES)
except ImportError:
    from modules.terminal_screen import (DEFAULT_HISTORY_LINES, SCROLL_MODE_DEFAULT, SCROLL_MODES)

try:
    from .terminal_widget import (CURSOR_STYLE_DEFAULT, CURSOR_STYLES,
                                  FONT_SIZE_MAX, FONT_SIZE_MIN)
except ImportError:
    from modules.terminal_widget import (CURSOR_STYLE_DEFAULT, CURSOR_STYLES,
                                         FONT_SIZE_MAX, FONT_SIZE_MIN)

#: The accepted values of `terminal_mode`, the DEFAULT first. `"single"` makes every new session
#: join the LAST live terminal window as its next tab — one window that collects them all.
TERMINAL_MODES = ("windows", "tabs", "single")

# ── the terminal_* keys of `~/.sshmap/config.json` ───────────────────────────
# All keys are OPTIONAL and a config without them behaves exactly like the shipped defaults:
# palette "default", the system monospace at pt 10, the scrollback depth
# `DEFAULT_HISTORY_LINES = 1000` (an explicit 0 disables it) and an immediate close. They are read
# when the terminal window is created; the UI is the settings dialog (`AGENTS.md` §4.12).
def load_terminal_settings():
    """Reads and validates the terminal_* keys from ~/.sshmap/config.json.

    Source — i18n.load_config() (never raises, {} on error). Returns:
      {"palette": str | None,     # None — not set; an unknown name → the window keeps "default"
       "font_family": str,        # "" — not set (system monospace)
       "font_size": int | None,   # None — not set (pt 10)
       "history_lines": int,      # HistoryScreen deque-history depth (0 = off)
       "close_behavior": str,     # "close" (default) | "ask" — close behaviour
       "max_open": int,           # limit of own open terminals (default 4)
       "wheel": str,              # "scrollback" (default) | "off" — the wheel
       "cursor": str,             # "block" | "bar" (default) | "underline"
       "scroll": str,             # "live" (default) | "pin" — new output pulls the view to the
                                  #            live line, or holds it still
       "follow_cwd": bool,        # follow the shell's directory (OSC 7)
       "mode": str}               # "windows" (default) | "tabs" | "single" — display mode
    Invalid values (a foreign type, out of range) → default. Never raises.
    """
    defaults = {"palette": None, "font_family": "", "font_size": None,
                "history_lines": DEFAULT_HISTORY_LINES, "close_behavior": "close",
                "max_open": 4, "wheel": "scrollback", "mode": "windows",
                "cursor": CURSOR_STYLE_DEFAULT, "scroll": SCROLL_MODE_DEFAULT,
                "follow_cwd": False}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    cfg = load_config()

    v = cfg.get("terminal_palette")
    if isinstance(v, str) and v.strip():
        defaults["palette"] = v.strip()   # unknown name → set_palette() False → "default"

    v = cfg.get("terminal_font")
    if isinstance(v, str):
        defaults["font_family"] = v.strip()

    v = cfg.get("terminal_font_size")
    if isinstance(v, int) and not isinstance(v, bool) and FONT_SIZE_MIN <= v <= FONT_SIZE_MAX:
        defaults["font_size"] = v         # out of range → pt 10 (default)

    v = cfg.get("terminal_history_lines")
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1_000_000:
        defaults["history_lines"] = v     # negative/overflow → default 1000

    v = cfg.get("terminal_close_behavior")
    if isinstance(v, str) and v.strip().lower() in ("close", "ask"):
        defaults["close_behavior"] = v.strip().lower()  # corrupt/foreign → "close" (default)

    # limit of own open terminals — default 4; when reached, MainWindow offers to close the
    # oldest session instead of refusing.
    v = cfg.get("terminal_max_open")
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 32:
        defaults["max_open"] = v     # corrupt/out of range → 4 (default)

    # Mouse wheel — "scrollback" (the DEFAULT: the wheel scrolls the local scrollback) | "off"
    # (the wheel is not intercepted for scrollback; the full SGR wheel passthrough to the application
    # remains, since pyte 0.8.2 does not track the DECSET 1000/1002/1006 mouse modes). Config-only.
    v = cfg.get("terminal_wheel")
    if isinstance(v, str) and v.strip().lower() in ("scrollback", "off"):
        defaults["wheel"] = v.strip().lower()   # corrupt/foreign → "scrollback" (default)

    # The cursor SHAPE — "bar" (the default: the thin blinking line of Windows Terminal) |
    # "block" (the historical full-cell slab) | "underline". Read on session creation like the
    # palette and the font; the shape set is `modules/terminal_widget.py`'s own declaration.
    v = cfg.get("terminal_cursor_style")
    if isinstance(v, str) and v.strip().lower() in CURSOR_STYLES:
        defaults["cursor"] = v.strip().lower()   # corrupt/foreign → the declared default

    # The SCROLLBACK mode — "live" (the default: new output pulls the view back to the live line) |
    # "pin" (OPT-IN: the view keeps the lines the user is reading while output arrives). The key is
    # CONFIG-ONLY (the settings hub gains no row); the accepted values are the screen's declaration.
    v = cfg.get("terminal_scroll")
    if isinstance(v, str) and v.strip().lower() in SCROLL_MODES:
        defaults["scroll"] = v.strip().lower()   # corrupt/foreign → "live" (the default)

    # The cwd follow — the Files tab moves when the shell's directory changes (the OSC 7 hook). A
    # REAL bool, OPT-IN: a missing or unusable value is OFF, so a session never injects a hook the
    # user did not ask for (the write path is the tab's checkbox, not a settings-hub row).
    v = cfg.get("terminal_follow_cwd")
    if isinstance(v, bool):
        defaults["follow_cwd"] = v

    # The display mode: "windows" (separate SSHTerminalWindow windows) | "tabs" (the "Terminals"
    # QDockWidget in MainWindow) | "single" (every session joins the LAST live terminal window as
    # its next tab). Validation — the other keys' rule: a corrupt value / a foreign type → default.
    v = cfg.get("terminal_mode")
    if isinstance(v, str) and v.strip().lower() in TERMINAL_MODES:
        defaults["mode"] = v.strip().lower()   # corrupt/foreign → "windows" (default)

    return defaults


# ── the FILES PANEL — the right half of the window ───────────────────────────────
# In `terminal_mode = "windows"` a wide screen shows `[commands | terminal | files]` at once:
# the session's Files widget is RE-PARENTED from its tab strip into a right-hand panel (ONE
# stack page per session; the strip becomes `Terminal | History`). The mode is ONE key —
# `terminal_files_mode` ("tab" | "panel"); `ui_files_panel` is the legacy migration source.
FILES_MODE_CONFIG_KEY = "terminal_files_mode"              # str — "tab" | "panel"
FILES_PANEL_MIGRATION_BOOL = "ui_files_panel"              # LEGACY (read-only migration source)
FILES_PANEL_CONFIG_COLLAPSED = "ui_files_panel_collapsed"  # bool — the panel was folded

#: The accepted values of `terminal_files_mode`, the DEFAULT first (`resolve_files_mode()`).
FILES_MODES = ("tab", "panel")
FILES_MODE_DEFAULT = "tab"

#: The width the panel opens with (px) the FIRST time in a window: the collapse remembers what the
#: user dragged afterwards. Deliberately NOT a config key — the mode owns exactly TWO `ui_*` keys.
FILES_PANEL_WIDTH_DEFAULT = 320

#: The horizontal floor of the CANVAS while the panel is on, in CELLS — the mirror of `SPLIT_MIN_ROWS`
#: (the vertical floor of the split pane): the narrowest canvas the panel may squeeze the terminal into,
#: built from the live cell metrics (`widget.cell_size[0]`), never a magic pixel number. 20 columns is a
#: QUARTER of the classic 80-column line, and it still leaves room for the command panel and the panel.
FILES_PANEL_MIN_COLS = 20

#: The floor of the panel itself (px) while the mode is on — the `COMMANDER_MIN_PANE_PX` rule
#: (Qt gotcha #13 forbids `setMaximum*` on a splitter member, so it is installed as
#: `setMinimumWidth` and dropped again when the mode goes off).
FILES_PANEL_MIN_PX = 200


def resolve_files_mode(cfg: dict = None) -> str:
    """The Files display mode of a terminal window — "tab" | "panel".

    The validation is the `load_terminal_settings()` rule (`terminal_mode`, `terminal_wheel`):
    a missing key, a foreign type (a number where a string is expected) and an unknown value
    all answer the DEFAULT `"tab"` — the shipped Files-tab look — so a broken config can never
    move a session's Files tree out of its tab strip.

    MIGRATION (read ONCE, never written): an older window wrote its own per-window mode as the
    `ui_files_panel` bool. When `terminal_files_mode` is ABSENT and that legacy value is a real
    JSON bool, it decides the answer — a user who had the panel on keeps it across the upgrade
    instead of silently losing the layout. A real `terminal_files_mode` always wins.

    `cfg` — a mapping to read (defaults to `i18n.load_config()`); a broken config store
    answers the DEFAULT. Never raises.
    """
    if cfg is None:
        try:
            from i18n import load_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the default
            return FILES_MODE_DEFAULT
        try:
            cfg = load_config()
        except Exception:  # noqa: BLE001 — a broken config store must not break the window
            return FILES_MODE_DEFAULT
    if not isinstance(cfg, dict):
        return FILES_MODE_DEFAULT

    v = cfg.get(FILES_MODE_CONFIG_KEY)
    if isinstance(v, str):
        value = v.strip().lower()
        if value in FILES_MODES:
            return value                     # a real key wins, legacy or not
    elif v is not None:
        return FILES_MODE_DEFAULT            # a foreign TYPE is a broken key, not a legacy one

    legacy = cfg.get(FILES_PANEL_MIGRATION_BOOL)
    if isinstance(legacy, bool):
        return "panel" if legacy else FILES_MODE_DEFAULT
    return FILES_MODE_DEFAULT


def load_files_panel_settings():
    """The Files display mode + the fold of a NEW terminal window.

    The `load_split_settings()` / `load_commander_settings()` shape (§4.3): both keys are
    optional and a foreign value answers the DEFAULT — a broken config must never move a
    session's Files tree out of its tab strip. The mode itself is `resolve_files_mode()`
    (the ONE reader, migration included). Never raises.
    Returns `{"mode": str, "collapsed": bool}`.
    """
    defaults = {"mode": FILES_MODE_DEFAULT, "collapsed": False}
    try:
        from i18n import load_config
    except Exception:  # noqa: BLE001 — a build without i18n keeps the defaults
        return dict(defaults)
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — a broken config store must not break the window
        return dict(defaults)
    if not isinstance(cfg, dict):
        return dict(defaults)

    defaults["mode"] = resolve_files_mode(cfg)
    v = cfg.get(FILES_PANEL_CONFIG_COLLAPSED)
    if isinstance(v, bool):
        defaults["collapsed"] = v
    return defaults


# ── the SPLIT state ─────────────────────────────────────────────────────────────
# ONE split state for the application — the dock and the standalone window share the two keys.
SPLIT_CONFIG_BOOL = "ui_terminal_split"          # bool — a pane was open at the last close
SPLIT_CONFIG_RATIO = "ui_terminal_split_ratio"   # float — the pane's share of the height
SPLIT_RATIO_DEFAULT = 0.25                       # a quarter of the height
SPLIT_RATIO_MIN = 0.10
SPLIT_RATIO_MAX = 0.75


def load_split_settings():
    """The split state/ratio from `~/.sshmap/config.json` — the `terminal_*` validation rule.

    Source — `i18n.load_config()` (never raises, `{}` on error); both keys are optional and the
    defaults equal the single-pane behaviour. Returns `{"split": bool, "ratio": float}`, the ratio
    clamped to `SPLIT_RATIO_MIN..SPLIT_RATIO_MAX`. A foreign type (a string `"true"`, a bool where a
    float is expected, a non-finite number) → the default: a broken config must never open a second
    session or squeeze the panes into unusability. Never raises.
    """
    defaults = {"split": False, "ratio": SPLIT_RATIO_DEFAULT}
    try:
        from i18n import load_config
    except Exception:  # noqa: BLE001 — a build without i18n keeps the defaults
        return dict(defaults)
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — a broken config store must not break the window
        return dict(defaults)
    if not isinstance(cfg, dict):
        return dict(defaults)

    v = cfg.get(SPLIT_CONFIG_BOOL)
    if isinstance(v, bool):
        defaults["split"] = v           # only a real JSON bool counts

    v = cfg.get(SPLIT_CONFIG_RATIO)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            ratio = float(v)
        except (TypeError, ValueError):
            ratio = SPLIT_RATIO_DEFAULT
        if ratio == ratio and ratio not in (float("inf"), float("-inf")):  # not NaN/inf
            defaults["ratio"] = max(SPLIT_RATIO_MIN, min(SPLIT_RATIO_MAX, ratio))
    return defaults
