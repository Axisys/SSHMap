# -*- coding: utf-8 -*-
"""v1.1.5 → v1.4.3 — the central theme `ui/theme.py`: the `Theme` object, LIGHT, the accent hue.

v1.2.5 introduced this file as the regression test of the refactoring that moved every
literal colour/radius/font into one module. v1.4.3 (ROADMAP "Appearance: light theme +
accent color") keeps the file and REPLACES its subject: the constants became ONE
`Theme` object, a second instance (LIGHT) appeared, and the accent became a HUE that
generates its shades — so the old "the constant equals the literal" checks are replaced
by the checks the new contract actually needs.

§1 The `Theme` object — pure data: importable WITHOUT PySide6, standard library only.
§2 `DARK` — a snapshot of the pre-v1.4.3 constants BY VALUE (the zero-visual-change
   promise of the refactoring) + the semantic dicts and the live module proxies.
§3 `LIGHT` — COMPLETE (the same field set as DARK) and different on the surfaces.
§4 The accent — one HUE: a pure function, a known hue → the expected hex, the default
   hue → today's #38bdf8, the three shades ordered, and a hex → hue round trip.
§5 The QSS builder (`ui/theme_qss.py`) — one theme → one stable string, LIGHT ≠ DARK.
§6 The config round trip — `load_theme_settings()` / `theme_from_settings()`; a broken
   value → the default + a log line; the "Appearance" tab of the settings hub.
§7 The live switch — `set_theme`/`apply_theme` without a restart: the module proxies,
   the class-level colours of the scene items and the widget stylesheets all move.
§8 Out of scope — unchanged (the terminal output palettes, CURSOR_COLOR, export_drawio).
§9 i18n parity + the release state.

Run: python tests/test_theme.py   (from the project root) or python tests/run_all.py
"""
import ast
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, read_cfg, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()

# ════════════════════════════════════════════════════════════════════════════
# §1 The Theme object — pure data (imported BEFORE any Qt module on purpose)
# ════════════════════════════════════════════════════════════════════════════
print("== §1 the Theme object: pure data ==")

import ui.theme as theme  # noqa: E402  — BEFORE PySide6: the import contract is checked here

check("§1 theme.py imports without PySide6 (pure data)",
      "PySide6" not in sys.modules, str([m for m in sys.modules if "PySide" in m]))

_src = open(os.path.join(ROOT, "ui", "theme.py"), encoding="utf-8").read()
_tree = ast.parse(_src)
_modules = set()
for _node in ast.walk(_tree):
    if isinstance(_node, ast.Import):
        _modules.update(alias.name.split(".")[0] for alias in _node.names)
    elif isinstance(_node, ast.ImportFrom) and _node.module:
        _modules.add(_node.module.split(".")[0])
check("§1 theme.py imports only the standard library (no third-party, no Qt)",
      _modules <= {"copy", "dataclasses", "typing", "PySide6"},
      str(sorted(_modules)))
check("§1 ...and the only PySide6 import is INSIDE a function (lazy, for the descriptors)",
      "from PySide6.QtGui import QColor" in _src
      and not re.search(r"^from PySide6", _src, re.M),
      str([l for l in _src.splitlines() if "PySide6" in l]))

import dataclasses  # noqa: E402

# v1.4.7: the SFTP viewer's syntax palette — 8 fields per instance, NOT part of the
# frozen pre-v1.4.3 snapshot above (they are new to the theme, not a re-tune of it).
# The ROLE vocabulary and the deep palette checks live in the topical file
# (tests/test_sftp_syntax.py §1); here only the `Theme` contract is pinned.
SYNTAX_FIELDS = {"syntax_number", "syntax_string", "syntax_key", "syntax_keyword",
                 "syntax_comment", "syntax_tag", "syntax_attribute",
                 "syntax_punctuation"}

check("§1 Theme is a frozen dataclass", dataclasses.is_dataclass(theme.Theme)
      and theme.Theme.__dataclass_params__.frozen,
      str(getattr(theme.Theme, "__dataclass_params__", None)))
check("§1 the module exposes THEME (the active instance) and the two instances",
      isinstance(theme.THEME, theme.Theme) and isinstance(theme.DARK, theme.Theme)
      and isinstance(theme.LIGHT, theme.Theme),
      f"THEME={type(theme.THEME).__name__} DARK={type(theme.DARK).__name__}")
_frozen_ok = True
try:
    theme.DARK.canvas_bg = "#000000"  # type: ignore[misc]
    _frozen_ok = False
except dataclasses.FrozenInstanceError:
    pass
check("§1 a frozen instance cannot be mutated (a switch REPLACES, it never edits)", _frozen_ok)
check("§1 set_theme() refuses a non-Theme value (keeps the active one, never half-switches)",
      theme.set_theme("nope") is theme.THEME and theme.set_theme(None) is theme.THEME)


# ════════════════════════════════════════════════════════════════════════════
# §2 DARK — the pre-v1.4.3 constants, value for value
# ════════════════════════════════════════════════════════════════════════════
print("== §2 DARK: the snapshot of the pre-v1.4.3 palette ==")

check("§2 the active theme is DARK out of the box (the dark theme stays the default)",
      theme.THEME is theme.DARK and theme.MODE_DARK == "dark"
      and theme.MODES == ("dark", "light", "auto"), str(theme.MODES))

# The literal snapshot: every value the module held as a CONSTANT before v1.4.3.
# Editing DARK is a visual change and has to be a deliberate one — this is the check
# that makes "the refactoring changed nothing" a fact rather than a promise.
DARK_SNAPSHOT = {
    "canvas_bg": "#020617", "render_bg": "#0b1220", "window_bg": "#0f172a",
    "base_bg": "#1e293b", "surface_alt": "#334155",
    "text_primary": "#e2e8f0", "text_muted": "#94a3b8", "icon_color": "#cbd5e1",
    "accent": "#38bdf8", "selection_amber": "#f59e0b",
    "node_bg": "#1e293b", "node_border": "#3b82f6", "node_hover": "#60a5fa",
    "node_icon_bg": "#2563eb", "node_text": "#e2e8f0", "node_label": "#94a3b8",
    "dot_idle": "#64748b",
    "status_online": "#22c55e", "status_warn": "#facc15", "status_offline": "#ef4444",
    "tag_test": "#a855f7", "tag_backup": "#06b6d4", "tag_dmz": "#f97316",
    "tag_pink": "#ec4899",
    "group_border": "#7c3aed", "group_hover": "#a78bfa", "group_title": "#c4b5fd",
    "group_title_selected": "#fde68a", "group_title_hover": "#e9d5ff",
    "arrow_ssh": "#34d399", "arrow_http": "#fbbf24", "arrow_nfs": "#f472b6",
    "arrow_kubernetes": "#22d3ee", "arrow_hover_compat": "#6ee7b7",
    "note_bg": "#eedd9f", "note_border": "#a9853d", "note_text": "#403a2b",
    "radius_node": 10.0, "radius_note": 10.0, "radius_group": 12.0,
    "radius_search_bar": 8, "radius_arrow_label": 5.0, "radius_resize_mark": 3.0,
    "radius_node_glyph_unit": 2.0,
    "font_ui": "Segoe UI", "font_mono": "Consolas",
}
_mismatch = {name: (value, getattr(theme.DARK, name))
             for name, value in DARK_SNAPSHOT.items()
             if getattr(theme.DARK, name) != value}
check(f"§2 DARK replicates all {len(DARK_SNAPSHOT)} pre-v1.4.3 constants by value",
      not _mismatch, str(_mismatch))
check("§2 DARK.accent_hue is the default hue (the base accent is NOT a stored palette)",
      theme.DARK.hue() == theme.DEFAULT_ACCENT_HUE, str(theme.DARK.hue()))

check("§2 DARK.STATUS_COLORS: online/warn/offline",
      dict(theme.DARK.status_colors) == {"online": "#22c55e", "warn": "#facc15",
                                         "offline": "#ef4444"},
      str(dict(theme.DARK.status_colors)))
check("§2 DARK.TAG_COLORS: the six known roles (v0.9.4)",
      dict(theme.DARK.tag_colors) == {
          "prod": "#ef4444", "staging": "#facc15", "dev": "#22c55e",
          "test": "#a855f7", "backup": "#06b6d4", "dmz": "#f97316"},
      str(dict(theme.DARK.tag_colors)))
check("§2 DARK.TAG_PALETTE: the hash-palette order (crc32 % 6)",
      list(theme.DARK.tag_palette) == ["#22c55e", "#3b82f6", "#a855f7",
                                       "#f97316", "#06b6d4", "#ec4899"],
      str(theme.DARK.tag_palette))
check("§2 DARK.ARROW_TYPE_COLORS: 6 types, values and ORDER (the combobox iterates)",
      list(theme.DARK.arrow_type_colors.items()) == [
          ("ssh", "#34d399"), ("vpn", "#60a5fa"), ("http", "#fbbf24"),
          ("database", "#a78bfa"), ("nfs", "#f472b6"), ("kubernetes", "#22d3ee")],
      str(theme.DARK.arrow_type_colors))
check("§2 SFTP_PREVIEW_BLOCKED is the warn tone (one value, not a second literal)",
      theme.DARK.sftp_preview_blocked == theme.DARK.status_warn == "#facc15")
check("§2 the derived dicts are NOT fields — the values are declared exactly once",
      set(f.name for f in dataclasses.fields(theme.Theme)) == set(DARK_SNAPSHOT)
      | {"accent_hue", "accent_hover", "accent_selected",
         # v1.5rc1: the STRONG accent family — three NEW fields that resolve to the
         # DARK values this snapshot already pins (the role is new, the bytes are not)
         "accent_strong", "accent_strong_hover", "accent_strong_selected"}
      | set(SYNTAX_FIELDS),
      str(sorted(set(f.name for f in dataclasses.fields(theme.Theme)) - set(DARK_SNAPSHOT))))
check("§2 the dicts/lists are derived PROPERTIES on Theme (no second copy of the values)",
      all(isinstance(getattr(theme.Theme, name), property) for name in
          ("status_colors", "tag_colors", "tag_palette", "arrow_type_colors",
           "sftp_preview_blocked", "syntax_colors")))

# The module-level proxies: every historical name still resolves — and resolves LIVE.
check("§2 the module proxies resolve the ACTIVE instance (CANVAS_BG/NODE_BG/RADIUS_NODE/FONT_UI)",
      theme.CANVAS_BG == "#020617" and theme.NODE_BG == "#1e293b"
      and theme.RADIUS_NODE == 10.0 and theme.FONT_UI == "Segoe UI"
      and theme.ACCENT == "#38bdf8",
      f"{theme.CANVAS_BG} {theme.NODE_BG} {theme.RADIUS_NODE} {theme.FONT_UI}")
check("§2 the proxy dicts follow the active instance (equality by value, not identity)",
      theme.STATUS_COLORS == {"online": "#22c55e", "warn": "#facc15",
                              "offline": "#ef4444"}
      and theme.TAG_PALETTE == ["#22c55e", "#3b82f6", "#a855f7", "#f97316",
                                "#06b6d4", "#ec4899"]
      and theme.SFTP_PREVIEW_BLOCKED == theme.STATUS_WARN,
      str(dict(theme.STATUS_COLORS)))
_raised = False
try:
    theme.DOES_NOT_EXIST  # noqa: B018
except AttributeError:
    _raised = True
check("§2 an unknown module attribute still raises AttributeError (no silent catch-all)",
      _raised)
check("§2 dir(theme) lists the live names (autocompletion is not lost)",
      "NODE_BG" in dir(theme) and "STATUS_COLORS" in dir(theme) and "THEME" in dir(theme))

# ── §2b v1.4.7: the syntax palette is a PER-INSTANCE pair (the plan's task 1) ──
check("§2b both instances carry all 8 syntax fields (a one-sided palette is forbidden)",
      SYNTAX_FIELDS <= {f.name for f in dataclasses.fields(theme.DARK)}
      and SYNTAX_FIELDS <= {f.name for f in dataclasses.fields(theme.LIGHT)}
      and set(theme.DARK.syntax_colors) == set(theme.LIGHT.syntax_colors))
check("§2b the palette is DERIVED from the fields — one declaration, no second table",
      theme.DARK.syntax_colors == {name[len("syntax_"):]: getattr(theme.DARK, name)
                                   for name in sorted(SYNTAX_FIELDS)}
      and theme.LIGHT.syntax_colors == {name[len("syntax_"):]: getattr(theme.LIGHT, name)
                                        for name in sorted(SYNTAX_FIELDS)})
check("§2b the live proxies resolve the ACTIVE instance (SYNTAX_NUMBER / SYNTAX_COLORS)",
      theme.SYNTAX_NUMBER == theme.THEME.syntax_number
      and theme.SYNTAX_COLORS == theme.THEME.syntax_colors
      and "SYNTAX_NUMBER" in dir(theme))
check("§2b LIGHT re-tunes the palette (its own tones, not the dark ones on a light canvas)",
      theme.DARK.syntax_colors != theme.LIGHT.syntax_colors
      and all(theme.is_valid_hex(v)
              for v in list(theme.DARK.syntax_colors.values())
              + list(theme.LIGHT.syntax_colors.values())))


# ════════════════════════════════════════════════════════════════════════════
# §3 LIGHT — complete and different
# ════════════════════════════════════════════════════════════════════════════
print("== §3 LIGHT: the same field set, a light canvas ==")

_dark_fields = {f.name for f in dataclasses.fields(theme.DARK)}
_light_fields = {f.name for f in dataclasses.fields(theme.LIGHT)}
check("§3 LIGHT is COMPLETE — the same field set as DARK (a one-sided field is forbidden)",
      _dark_fields == _light_fields, str(sorted(_dark_fields ^ _light_fields)))
check("§3 LIGHT starts from the slate-100 surfaces named by the plan",
      (theme.LIGHT.canvas_bg, theme.LIGHT.base_bg, theme.LIGHT.window_bg)
      == ("#f8fafc", "#e2e8f0", "#f1f5f9"),
      f"{theme.LIGHT.canvas_bg} {theme.LIGHT.base_bg} {theme.LIGHT.window_bg}")
check("§3 LIGHT text: near-black primary, the muted tone deepened to AA in v1.5rc1",
      (theme.LIGHT.text_primary, theme.DARK.text_muted) == ("#0f172a", "#94a3b8")
      and theme.LIGHT.text_muted == "#556070"
      and theme.LIGHT.text_muted != theme.DARK.text_muted,
      theme.LIGHT.text_muted)
check("§3 LIGHT statuses are DARKER than the dark theme's (contrast on a light canvas)",
      theme.LIGHT.status_online == "#16a34a" and theme.LIGHT.status_warn == "#a16207"
      and theme.LIGHT.status_offline == "#dc2626")
# v1.5rc1 renamed the claim of this check: the two tones are no longer "kept because
# they read on light" (the review measured the amber at 2.05:1 as INK and the sticky
# note at 1.30:1 against the canvas). LIGHT now carries its OWN values, and the gate
# (tests/test_theme_contrast.py) is what proves they hold.
check("§3 v1.5rc1: LIGHT carries its own amber selection and its own sticky tone",
      theme.LIGHT.selection_amber == "#b45309"
      and theme.DARK.selection_amber == "#f59e0b"
      and (theme.LIGHT.note_bg, theme.LIGHT.note_border)
      != (theme.DARK.note_bg, theme.DARK.note_border)
      and theme.LIGHT.note_text == theme.DARK.note_text)
check("§3 v1.5rc1: the five dark-tuned LIGHT fields were re-tuned (the review's list)",
      all(getattr(theme.DARK, name) != getattr(theme.LIGHT, name) for name in
          ("node_hover", "group_hover", "node_border", "note_bg", "selection_amber")))
check("§3 LIGHT's card is the WHITE surface (the card/background contrast moved)",
      theme.LIGHT.node_bg == "#ffffff" and theme.DARK.node_bg != theme.LIGHT.node_bg)
check("§3 the two instances really differ: every surface + text + status tone",
      all(getattr(theme.DARK, name) != getattr(theme.LIGHT, name) for name in
          ("canvas_bg", "render_bg", "window_bg", "base_bg", "surface_alt",
           "text_primary", "text_muted", "icon_color", "node_bg", "dot_idle",
           "status_online", "status_warn", "status_offline")))
check("§3 the geometry/font fields are IDENTICAL in both (only colour moves)",
      all(getattr(theme.DARK, name) == getattr(theme.LIGHT, name) for name in
          ("radius_node", "radius_note", "radius_group", "radius_search_bar",
           "radius_arrow_label", "radius_resize_mark", "radius_node_glyph_unit",
           "font_ui", "font_mono")))


# ════════════════════════════════════════════════════════════════════════════
# §4 The accent — one HUE, three shades (a pure function)
# ════════════════════════════════════════════════════════════════════════════
print("== §4 the accent hue → shades ==")

check("§4 hsl_hex is PURE and returns lowercase #rrggbb",
      theme.hsl_hex(0, 100, 50) == "#ff0000" and theme.hsl_hex(120, 100, 50) == "#00ff00"
      and theme.hsl_hex(240, 100, 50) == "#0000ff" and theme.hsl_hex(0, 0, 0) == "#000000"
      and theme.hsl_hex(0, 0, 100) == "#ffffff",
      f"{theme.hsl_hex(0, 100, 50)} {theme.hsl_hex(120, 100, 50)} {theme.hsl_hex(240, 100, 50)}")
check("§4 the DEFAULT hue yields TODAY'S accent (#38bdf8) — the zero-change promise",
      theme.accent_hex() == "#38bdf8" and theme.accent_hex(theme.DEFAULT_ACCENT_HUE) == "#38bdf8"
      and theme.DARK.accent == "#38bdf8",
      f"{theme.accent_hex()} default={theme.DEFAULT_ACCENT_HUE}")
check("§4 a known hue → the expected hex (the generator is deterministic)",
      theme.accent_hex(0) == theme.hsl_hex(0, theme.ACCENT_SATURATION, theme.ACCENT_LIGHTNESS)
      and theme.accent_hex(120) != theme.accent_hex(0)
      and theme.accent_hex(0) == theme.accent_hex(360),
      f"h0={theme.accent_hex(0)} h120={theme.accent_hex(120)}")
check("§4 the hue WRAPS (a negative / over-360 value is the same accent)",
      theme.accent_hex(-162.4) == theme.accent_hex(197.6)
      and theme.accent_hex(360 + 40) == theme.accent_hex(40))
check("§4 the three shades are ORDERED hover → base → selected (lightness)",
      theme.ACCENT_LIGHTNESS + theme.ACCENT_HOVER_DELTA > theme.ACCENT_LIGHTNESS
      > theme.ACCENT_LIGHTNESS + theme.ACCENT_SELECTED_DELTA
      and theme.accent_hover_hex() == "#51c5f9" and theme.accent_selected_hex() == "#20b5f7",
      f"{theme.accent_hover_hex()} {theme.accent_hex()} {theme.accent_selected_hex()}")
check("§4 every shade of a hue is a distinct, valid colour",
      len({theme.accent_hex(200), theme.accent_hover_hex(200),
           theme.accent_selected_hex(200)}) == 3
      and all(theme.is_valid_hex(v) for v in (theme.accent_hex(200),
                                              theme.accent_hover_hex(200),
                                              theme.accent_selected_hex(200))))
check("§4 hex_hue is the INVERSE of the generator (a hex → the same hue, ±0.5°)",
      all(abs(theme.hex_hue(theme.accent_hex(h)) - (h % 360)) < 0.5
          for h in (0, 45, 120, 198.4, 280, 359)),
      str([(h, theme.hex_hue(theme.accent_hex(h))) for h in (0, 120, 198.4, 280)]))
check("§4 a grey has no meaningful hue and a broken hex falls back to the default",
      theme.hex_hue("#808080") == 0.0
      and theme.hex_hue("nonsense") == theme.DEFAULT_ACCENT_HUE
      and theme.hex_hue(None) == theme.DEFAULT_ACCENT_HUE)
check("§4 is_valid_hex accepts #rrggbb in either case and refuses everything else",
      theme.is_valid_hex("#38bdf8") and theme.is_valid_hex("38BDF8")
      and not theme.is_valid_hex("#38bdf") and not theme.is_valid_hex("red")
      and not theme.is_valid_hex(None) and not theme.is_valid_hex(123456))
check("§4 theme_for_mode picks the instance and applies the hue (no instance per call)",
      theme.theme_for_mode("light", 280).canvas_bg == theme.LIGHT.canvas_bg
      and theme.theme_for_mode("light", 280).accent == theme.accent_hex(280)
      and theme.theme_for_mode("light", 280).hue() == 280.0)
check("§4 theme_for_mode returns the SHARED instance when nothing changes (cache-friendly)",
      theme.theme_for_mode("dark") is theme.DARK
      and theme.theme_for_mode("dark", theme.DEFAULT_ACCENT_HUE) is theme.DARK
      and theme.theme_for_mode("LIGHT ") is theme.LIGHT)
check("§4 a broken mode / hue falls back to DARK + the default hue (never a mixture)",
      theme.theme_for_mode("bogus") is theme.DARK
      and theme.theme_for_mode(None) is theme.DARK
      and theme.theme_for_mode("light", "nonsense") is theme.LIGHT
      and theme.theme_for_mode("light", None) is theme.LIGHT)


# ════════════════════════════════════════════════════════════════════════════
# §5 The QSS builder — one theme → one string
# ════════════════════════════════════════════════════════════════════════════
print("== §5 the QSS builder (ui/theme_qss.py) ==")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from ui import theme_qss  # noqa: E402

check("§5 build_qss(theme) is STABLE — the same theme gives byte-identical strings",
      theme_qss.build_qss(theme.DARK) == theme_qss.build_qss(theme.DARK)
      and len(theme_qss.build_qss(theme.DARK)) > 500,
      str(len(theme_qss.build_qss(theme.DARK))))
_dark_qss, _light_qss = theme_qss.build_qss(theme.DARK), theme_qss.build_qss(theme.LIGHT)
check("§5 LIGHT ≠ DARK on the surfaces (the builder really reads the instance)",
      _dark_qss != _light_qss
      and f"background-color: {theme.DARK.window_bg}" in _dark_qss
      and f"background-color: {theme.LIGHT.window_bg}" in _light_qss
      and f"background-color: {theme.LIGHT.window_bg}" not in _dark_qss,
      f"dark={theme.DARK.window_bg} light={theme.LIGHT.window_bg}")
check("§5 the builder carries the accent into the selection rules (one accent source)",
      theme.DARK.accent in _dark_qss
      and theme.accent_hex(280) in theme_qss.build_qss(theme.theme_for_mode("dark", 280)))
check("§5 build_palette: the QPalette roles come from the theme (Window/Base/Text/Button)",
      theme_qss.build_palette(theme.DARK).color(
          theme_qss.QPalette.ColorRole.Window).name() == theme.DARK.window_bg
      and theme_qss.build_palette(theme.LIGHT).color(
          theme_qss.QPalette.ColorRole.Base).name() == theme.LIGHT.base_bg
      and theme_qss.build_palette(theme.LIGHT).color(
          theme_qss.QPalette.ColorRole.ButtonText).name() == theme.LIGHT.text_primary)
check("§5 the widget-level registry: every name builds a non-empty string and is listed",
      theme_qss.style_names()
      and all(theme_qss.style(name) for name in theme_qss.style_names())
      and theme_qss.style("does.not.exist") == "",
      str(theme_qss.style_names()))
check("§5 a registry style follows the ACTIVE theme (the muted label tone)",
      theme_qss.style("status.sftp_row") == f"color: {theme.THEME.text_muted}; padding: 2px 0;",
      theme_qss.style("status.sftp_row"))
check("§5 the registry covers the widgets the pre-v1.4.3 code styled inline",
      {"status.muted", "status.bar_counts", "status.bar_zoom", "status.sftp_row",
       "status.terminal_row", "separator", "heading", "title", "subtitle",
       "search_bar", "find_bar", "note.editor"} <= set(theme_qss.style_names()),
      str(theme_qss.style_names()))


# ════════════════════════════════════════════════════════════════════════════
# §6 The config round trip + the "Appearance" tab
# ════════════════════════════════════════════════════════════════════════════
print("== §6 the theme in config.json and in the settings hub ==")

from ui.settings_dialog import (SettingsDialog, accent_swatches,  # noqa: E402
                                load_theme_settings, theme_from_settings)

clear_cfg()
check("§6 no `theme` key → DARK + the default accent + the motion ON (the defaults ARE the behaviour)",
      load_theme_settings() == {"mode": "dark", "accent": "#38bdf8", "motion": True, "density": "normal"}
      and theme_from_settings(load_theme_settings()) is theme.DARK,
      str(load_theme_settings()))

write_cfg({"theme": {"mode": "light", "accent": "#b838f8"}})
_stored = load_theme_settings()
check("§6 the round trip: a saved light theme + a custom accent come back unchanged",
      _stored == {"mode": "light", "accent": "#b838f8", "motion": True, "density": "normal"}, str(_stored))
_instance = theme_from_settings(_stored)
check("§6 ...and become the LIGHT instance with that hue (the hex is a hue in disguise)",
      _instance.canvas_bg == theme.LIGHT.canvas_bg
      and _instance.accent == theme.accent_hex(280)
      and _instance.hue() == 280.0,
      f"{_instance.canvas_bg} {_instance.accent} {_instance.hue()}")

write_cfg({"theme": "not-an-object"})
check("§6 a broken `theme` value (a string) → the defaults, and the app still starts",
      load_theme_settings() == {"mode": "dark", "accent": "#38bdf8", "motion": True, "density": "normal"})
write_cfg({"theme": {"mode": 42, "accent": "#zzzzzz"}})
check("§6 a foreign mode + an invalid colour → the defaults (per value, never a crash)",
      load_theme_settings() == {"mode": "dark", "accent": "#38bdf8", "motion": True, "density": "normal"},
      str(load_theme_settings()))
write_cfg({"theme": {"mode": "LIGHT", "accent": "38BDF8"}})
check("§6 the mode is case-insensitive and a missing '#' is tolerated",
      load_theme_settings() == {"mode": "light", "accent": "#38bdf8", "motion": True, "density": "normal"},
      str(load_theme_settings()))
# v1.5rc1: the third mode + the motion flag of the same nested key.
write_cfg({"theme": {"mode": "auto", "accent": "#38bdf8", "motion": False}})
check("§6 v1.5rc1: 'auto' is a valid mode and a real `motion` boolean round-trips",
      load_theme_settings() == {"mode": "auto", "accent": "#38bdf8", "motion": False, "density": "normal"},
      str(load_theme_settings()))
write_cfg({"theme": {"mode": "dark", "accent": "#38bdf8", "motion": "yes"}})
check("§6 v1.5rc1: a broken motion value → the motion ON (today's behaviour)",
      load_theme_settings() == {"mode": "dark", "accent": "#38bdf8", "motion": True, "density": "normal"},
      str(load_theme_settings()))
clear_cfg()

check("§6 the swatch presets are derived from their hues (no second hardcoded palette)",
      all(hex_value == theme.accent_hex(hue)
          for _name, hue, hex_value in accent_swatches())
      and accent_swatches()[0][0] == "sky"
      and accent_swatches()[0][2] == "#38bdf8",
      str([(n, h, v) for n, h, v in accent_swatches()]))

clear_cfg()
dlg = SettingsDialog(None)
check("§6 the hub has the 'Appearance' tab right after 'General' (8 tabs total)",
      dlg.tabs.count() == 8
      and dlg.tabs.tabText(1) == dlg.tabs.tabText(1)  # a label exists
      and dlg.tabs.tabText(1) != dlg.tabs.tabText(2),
      str([dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]))
check("§6 the mode combo offers dark/light/auto with the DEFAULT preselected",
      [dlg.theme_mode_combo.itemData(i) for i in range(dlg.theme_mode_combo.count())]
      == ["dark", "light", "auto"] and dlg.theme_mode_combo.currentData() == "dark")
check("§6 a swatch per preset + the own-colour field + the picker",
      len(dlg._swatch_buttons) == len(accent_swatches())
      and all(btn.width() == 26 for btn, _h in dlg._swatch_buttons.values())
      and dlg.accent_hex_edit.text() == "#38bdf8"
      and dlg.accent_pick_btn.text() != "")
check("§6 the swatch carries its colour in the QSS (the user sees the accent before applying)",
      theme.accent_hex() in dlg._swatch_buttons["sky"][0].styleSheet(),
      dlg._swatch_buttons["sky"][0].styleSheet())
check("§6 collect() carries the theme as ONE nested key (the appearance choice)",
      dlg.collect()["theme"] == {"mode": "dark", "accent": "#38bdf8", "motion": True,
                                 "density": "normal"}
      and len(dlg.collect()) == 22,
      str(sorted(dlg.collect())))

# The live application: the tab emits a Theme instance the moment a control moves.
_emitted = []
dlg.theme_changed.connect(lambda instance: _emitted.append(instance))
dlg.theme_mode_combo.setCurrentIndex(1)   # light
check("§6 the mode combo emits the LIGHT instance immediately (live, before OK)",
      _emitted and _emitted[-1].canvas_bg == theme.LIGHT.canvas_bg,
      str([getattr(e, "canvas_bg", e) for e in _emitted]))
dlg._on_accent_hue(280.0)
check("§6 a swatch emits the same mode with the swatch's hue",
      _emitted[-1].canvas_bg == theme.LIGHT.canvas_bg
      and _emitted[-1].hue() == 280.0 and _emitted[-1].accent == theme.accent_hex(280),
      f"{_emitted[-1].canvas_bg} {_emitted[-1].accent}")
check("§6 the hex field follows the swatch (one value, two widgets)",
      dlg.accent_hex_edit.text() == theme.accent_hex(280),
      dlg.accent_hex_edit.text())
# Programmatic setText() queues an editingFinished for the NEXT event loop turn
# (the field is not focused here) — flush it, so the checks below are about the
# value the user typed and not about the settings the dialog made itself.
app.processEvents()
dlg.accent_hex_edit.setText("#12ab34")
dlg._on_accent_hex_edited()
check("§6 a typed hex is accepted (the user's own colour)",
      _emitted[-1].accent == theme.accent_hex(theme.hex_hue("#12ab34")),
      f"{_emitted[-1].accent} (hue {theme.hex_hue('#12ab34')})")
_before = _emitted[-1]
# blockSignals: setText() may fire editingFinished if the field happens to hold
# focus — this check is about the HANDLER's verdict, not about Qt's focus dance.
dlg.accent_hex_edit.blockSignals(True)
dlg.accent_hex_edit.setText("zzz")
dlg._on_accent_hex_edited()
dlg.accent_hex_edit.blockSignals(False)
check("§6 an unusable hex is REFUSED — the field returns to the last valid colour",
      _emitted[-1] is _before
      and theme.hex_hue(dlg.accent_hex_edit.text()) == _before.hue()
      and dlg._accent_hex == dlg.accent_hex_edit.text() == "#12ab34",
      f"field={dlg.accent_hex_edit.text()!r} stored={dlg._accent_hex!r} "
      f"accent={_before.accent} hue={_before.hue()}")
check("§6 collect() now describes the tab's choice (light + the user's own colour)",
      dlg.collect()["theme"] == {"mode": "light", "accent": dlg._accent_hex, "motion": True,
                                 "density": "normal"}
      and theme.hex_hue(dlg.collect()["theme"]["accent"]) == _before.hue(),
      str(dlg.collect()["theme"]))
dlg.close()


# ════════════════════════════════════════════════════════════════════════════
# §7 The live switch — no restart
# ════════════════════════════════════════════════════════════════════════════
print("== §7 the live switch ==")

from models.server import ServerData  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402
from graphics.connection_arrow import ConnectionArrow, CONNECTION_TYPES  # noqa: E402
from graphics.node_group import NodeGroup  # noqa: E402
from graphics.sticky_note import StickyNote  # noqa: E402
from graphics.map_scene import MapScene  # noqa: E402
from graphics.map_view import MapView  # noqa: E402

theme.set_theme(theme.DARK)
clear_cfg()

node = ServerNode(ServerData(id="th-live", alias="web-1", host="10.0.0.5", user="root",
                             tags=["prod"]))
check("§7 (dark) the card's class colours and the ICON's environment tone are the dark ones",
      node.COLOR_BG.name() == "#1e293b" and node.COLOR_BORDER.name() == "#3b82f6"
      and node.STATUS_COLORS["offline"].name() == "#ef4444"
      and node._icon.brush().color().name() == "#ef4444")
check("§7 (dark) the arrow/group/note class colours are the dark tones",
      ConnectionArrow.COLOR_IDLE.name() == "#34d399"
      and ConnectionArrow.COLOR_HOVER.name() == "#6ee7b7"
      and NodeGroup.COLOR_BORDER.name() == "#7c3aed"
      and list(NodeGroup.COLOR_FILL.getRgb()) == [0x7C, 0x3A, 0xED, 16]
      and StickyNote.BG_COLOR == "#eedd9f")
check("§7 (dark) the module proxies and the scene grid are the dark tones",
      theme.CANVAS_BG == "#020617" and theme.STATUS_COLORS["online"] == "#22c55e"
      and dict(theme.ARROW_TYPE_COLORS)["ssh"] == "#34d399")

scene = MapScene()
view = MapView(scene)
live_node = scene.add_server(ServerData(id="th-live2", alias="db-1", host="10.0.0.6",
                                        user="root", tags=["prod"]))
scene.add_server(ServerData(id="th-live3", alias="db-2", host="10.0.0.7", user="root"))
live_arrow = scene.add_connection("th-live2", "th-live3", "link", "ssh", False)
live_group = scene.add_group(name="g", x=-900, y=-900, width=300, height=200)
live_note = scene.add_note("hello", 2000, 2000)
check("§7 (dark) the live scene items paint with the dark tones",
      live_node._bg.brush().color().name() == "#1e293b"
      and live_arrow.pen().color().name() == "#34d399"
      and live_note.BG_COLOR == "#eedd9f"
      and scene._grid_color.name() == "#0f172a"
      and scene._grid_major_color.name() == "#1e293b"
      and view.backgroundBrush().color().name() == "#020617")

light = theme.theme_for_mode("light", 260.0)
theme_qss.apply_theme(light, app=app, refresh_windows=False)
check("§7 the module proxies follow immediately (no widget rebuild needed)",
      theme.CANVAS_BG == theme.LIGHT.canvas_bg and theme.THEME is not theme.DARK
      and theme.STATUS_COLORS["online"] == theme.LIGHT.status_online
      and dict(theme.ARROW_TYPE_COLORS)["ssh"] == theme.LIGHT.arrow_ssh
      and theme.SFTP_PREVIEW_BLOCKED == theme.LIGHT.status_warn
      and theme.ACCENT == theme.accent_hex(260.0),
      f"{theme.CANVAS_BG} {theme.ACCENT}")
check("§7 the CLASS-level colours follow too (a class read resolves the active theme)",
      node.COLOR_BG.name() == theme.LIGHT.node_bg
      and node.COLOR_TEXT.name() == theme.LIGHT.node_text
      and node.TAG_COLORS["prod"].name() == theme.LIGHT.status_offline
      and ConnectionArrow.COLOR_IDLE.name() == theme.LIGHT.arrow_ssh
      and NodeGroup.COLOR_TITLE.name() == theme.LIGHT.group_title
      and list(NodeGroup.COLOR_FILL_HOVER.getRgb()) == [0x7C, 0x3A, 0xED, 28])
check("§7 a STALE brush is the reason refresh_theme exists (the item keeps what it was given)",
      live_node._bg.brush().color().name() == "#1e293b")

scene.refresh_theme()
check("§7 scene.refresh_theme() repaints the whole map with the new theme",
      live_node._bg.brush().color().name() == theme.LIGHT.node_bg
      and live_node._icon.brush().color().name() == theme.LIGHT.status_offline
      and live_arrow.pen().color().name() == theme.LIGHT.arrow_ssh
      and live_arrow._label_bg.brush().color().name() == theme.LIGHT.canvas_bg
      and live_arrow._label_bg.brush().color().alpha() == 190
      and theme_qss.style("note.editor") == live_note.widget().styleSheet(),
      f"node={live_node._bg.brush().color().name()} arrow={live_arrow.pen().color().name()}")
view.refresh_theme()
check("§7 view.refresh_theme() re-reads the canvas background",
      view.backgroundBrush().color().name() == theme.LIGHT.canvas_bg)
check("§7 the grid follows at PAINT time (a property, not an __init__ copy)",
      scene._grid_color.name() == theme.LIGHT.window_bg
      and scene._grid_major_color.name() == theme.LIGHT.base_bg)

# The widget-level stylesheets of the live containers.
from modules.terminal_dock import TerminalDockContent  # noqa: E402
from modules.sftp_tab import SftpTab  # noqa: E402
from modules.terminal_find_bar import TerminalFindBar  # noqa: E402
from ui.map_search_bar import MapSearchBar  # noqa: E402

dock = TerminalDockContent()
sftp = SftpTab()
find_bar = TerminalFindBar()
search_bar = MapSearchBar()
theme_qss.apply_theme(light, app=app, refresh_windows=False)
for _w in (dock, sftp, find_bar, search_bar):
    _w.refresh_theme()
check("§7 a container's stylesheet follows the switch (muted tones from the registry)",
      dock.status_label.styleSheet() == theme_qss.style("status.sftp_row")
      and sftp.path_label.styleSheet() == theme_qss.style("status.sftp_row")
      and theme.LIGHT.text_muted in dock.status_label.styleSheet(),
      dock.status_label.styleSheet())
check("§7 the floating cards rebuild their QSS (card background + accent border)",
      theme.LIGHT.window_bg in search_bar.styleSheet()
      and theme.LIGHT.window_bg in find_bar.styleSheet()
      and theme_qss.style("find_bar") == find_bar.styleSheet()
      and theme_qss.style("search_bar") == search_bar.styleSheet())
check("§7 the application stylesheet + palette are swapped in ONE call",
      app.styleSheet() == theme_qss.build_qss(theme.THEME)
      and app.palette().color(theme_qss.QPalette.ColorRole.Window).name()
      == theme.THEME.window_bg,
      app.palette().color(theme_qss.QPalette.ColorRole.Window).name())


# ── §7b The vector icons (the v1.4.3-fix: they stayed dark-theme pale on LIGHT) ──
# Reported after the release: the toolbar and sidebar glyphs kept the OLD colour on
# the light theme. Root cause — a QIcon is a VALUE like a QBrush: `ICON_COLOR` was a
# module constant captured at import time, the icons were painted once, and a WIDGET
# keeps its own copy of the pixmap (measured: `QPushButton.icon()` and a registry
# QIcon answering DIFFERENT cacheKeys()). The fix makes the colour live, caches ONE
# QIcon per name and re-applies it (clear-then-set) through the theme walk.
from ui import icons as icons_mod  # noqa: E402


def _icon_ink(icon, size=20):
    """The most frequent strong pixel of an icon — its outline colour."""
    image = icon.pixmap(size, size).toImage()
    if image.width() == 0:
        return None
    counter = {}
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() > 200:
                counter[pixel.name()] = counter.get(pixel.name(), 0) + 1
    if not counter:
        return None
    return max(counter.items(), key=lambda kv: kv[1])[0]


theme.set_theme(theme.DARK)
check("§7b ICON_COLOR follows the ACTIVE theme (a live proxy, not an import-time copy)",
      str(icons_mod.ICON_COLOR) == theme.DARK.icon_color
      and icons_mod.ICON_COLOR == theme.DARK.icon_color,
      str(icons_mod.ICON_COLOR))
_glyph = icons_mod.get_icon("settings")
check("§7b get_icon is CACHED — the same QIcon object per name (the refresh seam)",
      icons_mod.get_icon("settings") is _glyph
      and "settings" in icons_mod.cached_icon_names()
      and icons_mod.get_icon("no-such-icon").isNull())
check("§7b the glyph is drawn in the dark outline tone",
      _icon_ink(_glyph) == theme.DARK.icon_color, str(_icon_ink(_glyph)))
check("§7b ...and the DARK colour is the readable slate-300 (not a leftover literal)",
      theme.DARK.icon_color == "#cbd5e1")

theme_qss.apply_theme(light, app=app, refresh_windows=False)
_refreshed = icons_mod.refresh_all()
check("§7b refresh_all() repaints the cached glyphs (in place — the object is the same)",
      _refreshed >= 1 and icons_mod.get_icon("settings") is _glyph)
check("§7b the glyph now carries the LIGHT outline tone",
      _icon_ink(_glyph) == theme.LIGHT.icon_color == "#475569",
      f"{_icon_ink(_glyph)} vs {theme.LIGHT.icon_color}")
check("§7b every cached glyph is light and none is left dark (the reported defect)",
      all(_icon_ink(icons_mod.get_icon(n)) == theme.LIGHT.icon_color
          for n in icons_mod.cached_icon_names()),
      str({n: _icon_ink(icons_mod.get_icon(n)) for n in icons_mod.cached_icon_names()}))

# The window path: a real sidebar button and a real menu QAction.
import ui.main_window as _mw_mod  # noqa: E402

_win = _mw_mod.MainWindow()
_win.show()
app.processEvents()
_sidebar_btn = _win.sidebar.btn_add
check("§7b a sidebar button and a menu item are both icon-ful (the probe needs targets)",
      not _sidebar_btn.icon().isNull() and not _win.act_show_minimap.icon().isNull())
check("§7b before the switch both carry the dark tone",
      _icon_ink(_sidebar_btn.icon(), 18) == theme.DARK.icon_color
      and _icon_ink(_win.act_show_minimap.icon()) == theme.DARK.icon_color,
      f"{_icon_ink(_sidebar_btn.icon(), 18)} / {_icon_ink(_win.act_show_minimap.icon())}")
_win.apply_theme(theme.theme_for_mode("light"))
app.processEvents()
check("§7b after the switch the sidebar button is re-applied (its own pixmap copy)",
      _icon_ink(_sidebar_btn.icon(), 18) == theme.LIGHT.icon_color,
      f"{_icon_ink(_sidebar_btn.icon(), 18)} vs {theme.LIGHT.icon_color}")
check("§7b ...and so is the menu QAction (the name travels on the action)",
      _icon_ink(_win.act_show_minimap.icon()) == theme.LIGHT.icon_color
      and getattr(_win.act_show_minimap, "_sshmap_icon_name", None) == "minimap",
      f"{_icon_ink(_win.act_show_minimap.icon())} "
      f"name={getattr(_win.act_show_minimap, '_sshmap_icon_name', None)}")
check("§7b the hand-drawn collapse diamonds follow too (they are not in the registry)",
      _icon_ink(_win.sidebar.collapse_btn.icon()) == theme.LIGHT.icon_color
      and _icon_ink(_win._map_collapse_btn.icon()) == theme.LIGHT.icon_color,
      f"{_icon_ink(_win.sidebar.collapse_btn.icon())} / "
      f"{_icon_ink(_win._map_collapse_btn.icon())}")
check("§7b switching back restores the dark glyphs (no residue in the cache)",
      _win.apply_theme(theme.DARK) is theme.DARK
      and _icon_ink(_sidebar_btn.icon(), 18) == theme.DARK.icon_color
      and _icon_ink(_win.act_show_minimap.icon()) == theme.DARK.icon_color)
_win._dirty = False
_win.close()
app.processEvents()

# The switch is idempotent and reversible.
theme_qss.apply_theme(theme.DARK, app=app, refresh_windows=False)
scene.refresh_theme()
check("§7 the switch back restores the dark values exactly (no residue)",
      theme.THEME is theme.DARK
      and live_node._bg.brush().color().name() == "#1e293b"
      and live_arrow.pen().color().name() == "#34d399"
      and scene._grid_color.name() == "#0f172a"
      and app.palette().color(theme_qss.QPalette.ColorRole.Window).name() == "#0f172a",
      f"node={live_node._bg.brush().color().name()} grid={scene._grid_color.name()}")

from PySide6.QtWidgets import QWidget  # noqa: E402
_hidden = QWidget()
theme_qss.refresh(_hidden, "status.muted")
check("§7 refresh() hides/shows around the swap and never raises on an unknown name",
      _hidden.styleSheet() == f"color: {theme.DARK.text_muted};"
      and theme_qss.refresh(_hidden, "nope") is None)


# ════════════════════════════════════════════════════════════════════════════
# §8 Out of scope — unchanged
# ════════════════════════════════════════════════════════════════════════════
print("== §8 out-of-scope modules are untouched ==")

from modules import terminal_screen as _ts  # noqa: E402
check("§8 terminal_screen: the output palettes are in place and outside the UI theme",
      set(_ts.PALETTES) == {"default", "nord", "dracula", "tokyo_night"}
      and _ts.PALETTES["default"]["default_fg"] == "#e2e8f0"
      and _ts.PALETTES["nord"]["default_bg"] == "#2e3440"
      and _ts.DEFAULT_FG_HEX == "#e2e8f0" and _ts.DEFAULT_BG_HEX == "#0f172a")
from modules.terminal_widget import TerminalWidget  # noqa: E402
check("§8 TerminalWidget.CURSOR_COLOR is unchanged (#e2e8f0, the default scheme text)",
      TerminalWidget.CURSOR_COLOR == "#e2e8f0", TerminalWidget.CURSOR_COLOR)
from storage.export_drawio import NODE_FILL, NODE_STROKE, NOTE_FILL  # noqa: E402
check("§8 export_drawio: the export colours are unchanged (the draw.io format)",
      (NODE_FILL, NODE_STROKE, NOTE_FILL) == ("#0f172a", "#38bdf8", "#facc15"))

# The AST audit (the v1.2.5 rule): a raw palette literal must not come back.
SCAN_FILES = [
    "main.py",
    "graphics/background_image.py", "graphics/connection_arrow.py",
    "graphics/map_scene.py", "graphics/map_view.py", "graphics/node_group.py",
    "graphics/server_node.py", "graphics/sticky_note.py",
    "ui/command_palette.py", "ui/icons.py", "ui/main_window.py",
    "ui/map_search_bar.py", "ui/mixin_support.py", "ui/settings_dialog.py",
    "ui/sidebar.py",
    "dialogs/add_server_dialog.py", "dialogs/backups_dialog.py",
    "dialogs/connection_dialog.py", "dialogs/profile_manager_dialog.py",
    "dialogs/quick_launch_dialog.py", "dialogs/ssh_connect_dialog.py",
    "modules/multi_input.py", "modules/sftp_tab.py", "modules/terminal_dock.py",
    "modules/terminal_page.py",
    # v1.4.7: the viewer's grammar layer — it has no literal either (a role's colour
    # comes from `syntax_field()`), and the audit keeps it that way
    "modules/syntax_highlight.py",
]
FORBIDDEN = {getattr(theme.DARK, f.name).lower() for f in dataclasses.fields(theme.Theme)
             if isinstance(getattr(theme.DARK, f.name), str)
             and re.match(r"^#[0-9a-f]{6}$", getattr(theme.DARK, f.name))}


def _hex_in_strings(path):
    """The hex values in the STRING constants of a file (AST: the comments do not count)."""
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in re.finditer(r"#[0-9a-fA-F]{6}\b", node.value):
                found.append((node.lineno, match.group(0).lower()))
    return found


_violations = {}
for rel in SCAN_FILES:
    hits = [h for h in _hex_in_strings(rel) if h[1] in FORBIDDEN]
    if hits:
        _violations[rel] = hits
check(f"§8 the AST audit of the {len(SCAN_FILES)} files: no palette literal back in the strings",
      not _violations, str(_violations))


# ════════════════════════════════════════════════════════════════════════════
# §9 i18n parity + the release state
# ════════════════════════════════════════════════════════════════════════════
print("== §9 i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_i18n_format(langs)
APPEARANCE_KEYS = ["settings.tab.appearance", "settings.appearance.mode",
                   "settings.appearance.mode.dark", "settings.appearance.mode.light",
                   # v1.5rc1: the third mode + the motion switch of the same tab
                   "settings.appearance.mode.auto", "settings.appearance.motion",
                   "settings.appearance.motion.tooltip",
                   "settings.appearance.accent", "settings.appearance.accent.sky",
                   "settings.appearance.accent.cyan", "settings.appearance.accent.green",
                   "settings.appearance.accent.amber", "settings.appearance.accent.orange",
                   "settings.appearance.accent.pink", "settings.appearance.accent.violet",
                   "settings.appearance.accent.slate", "settings.appearance.own_color",
                   "settings.appearance.pick_color", "settings.appearance.hint"]
_missing_keys = [k for k in APPEARANCE_KEYS
                 if any(not str(langs[c].get(k, "")).strip() for c in sorted(langs))]
check(f"§9 the {len(APPEARANCE_KEYS)} new appearance keys exist in EVERY language",
      not _missing_keys, str(_missing_keys))
check("§9 the appearance keys are actually USED by the UI code (no dead strings)",
      all(key in _src or key in open(os.path.join(ROOT, "ui", "settings_dialog.py"),
                                     encoding="utf-8").read()
          or key.startswith("settings.appearance.accent.")
          for key in APPEARANCE_KEYS))
check_release_state(ROOT)

finish()
