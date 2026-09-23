# -*- coding: utf-8 -*-
"""v1.5rc1 — the CONTRAST GATE: the LIGHT palette, the two accent roles and the numbers that pin them.

The 1.5 line opened with a measured problem (the design review of 2026-09-27, the
as-shipped v1.4.5 palette): the accent used as TEXT measured 1.96:1 in LIGHT
(DARK 8.33), a selected menu/item row 2.05 (9.42), the six arrow strokes
2.4 … 4.4 (7.4 … 12.1), the three statuses 2.4 … 3.9 (3.9 … 9.6) and
`text_muted` 4.34 (6.96). Two of the weak arrows had a NAMEABLE cause: `vpn`
derives from `node_hover` and `database` from `group_hover`, and those two fields
were among the five that LIGHT never re-tuned — a dark-tuned value propagated
onto a light surface by the (correct!) "declared once" design.

This file is the gate the ROADMAP asked for: **numbers, not taste**, in the spirit
of the i18n-parity check. It is deliberately NOT a screenshot comparison — it reads
the DECLARED table of pairs below, computes the WCAG ratio for BOTH themes (and for
"auto", whichever way the platform resolves) and fails when a tone drops below its
threshold. A colour that no pair covers and no exemption explains also fails.

  §1 the WCAG arithmetic — the formula itself, with known answers;
  §2 the DECLARED table of pairs + the decorative exemptions;
  §3 the COMPLETENESS audit — every colour field of `Theme` is gated or explained;
  §4 the GATE — every pair clears its threshold in DARK, LIGHT and auto;
  §5 DARK did not move a pixel — the strong accent resolves to the DARK values and
     the DARK QSS / QPalette / widget styles are the v1.4.7 ones, value for value;
  §6 the LIGHT decisions — the re-tuned fields, the arrow derivation and the fact
     that the strong family is GENERATED from the hue (no second stored palette);
  §7 "Auto (system)" — `resolve_mode` follows a stubbed platform scheme live, and
     the "Appearance" tab resolves the same way;
  §8 the two roles at the call sites — the menu/item selection, the status-bar
     counters and the empty-state button read `accent_strong`, the decoration
     (borders, frames, the minimap frame) still reads `accent`;
  §9 a render probe — a real DARK/LIGHT/auto render, most frequent pixel = the
     canvas of the resolved mode (this is the "screenshot probe" of the acceptance);
  §10 i18n parity + the release state.

Run: python tests/test_theme_contrast.py   (from the project root) or python tests/run_all.py
"""
import dataclasses
import hashlib
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, write_cfg, clear_cfg,
                     EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

import ui.theme as theme  # noqa: E402  — pure data, no PySide6 needed for §1-§7

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FIELD_NAMES = {f.name for f in dataclasses.fields(theme.Theme)}


# ════════════════════════════════════════════════════════════════════════════
# §1 The WCAG arithmetic — the formula, with answers that are not opinions
# ════════════════════════════════════════════════════════════════════════════
print("== §1 the WCAG relative-luminance formula ==")


def _channel(value: int) -> float:
    """One 0..255 sRGB channel → its linear value (the WCAG 2.x definition)."""
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """The relative luminance of a "#rrggbb" colour (0 = black, 1 = white)."""
    value = str(color).strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"not a #rrggbb colour: {color!r}")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """The WCAG contrast ratio between two colours (1.0 … 21.0)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


check("§1 black on white is exactly 21:1 (the top of the scale)",
      abs(contrast_ratio("#000000", "#ffffff") - 21.0) < 0.001,
      str(contrast_ratio("#000000", "#ffffff")))
check("§1 a colour on itself is 1:1 (the bottom of the scale)",
      abs(contrast_ratio("#38bdf8", "#38bdf8") - 1.0) < 1e-9)
check("§1 the ratio is SYMMETRIC (order of the pair does not matter)",
      abs(contrast_ratio("#38bdf8", "#020617")
          - contrast_ratio("#020617", "#38bdf8")) < 1e-9)
check("§1 the known AA boundary: #767676 on white is 4.54:1 (the canonical value)",
      abs(contrast_ratio("#767676", "#ffffff") - 4.54) < 0.01,
      str(contrast_ratio("#767676", "#ffffff")))
check("§1 the formula is MONOTONE — a darker ink on white always wins",
      contrast_ratio("#0676a7", "#f8fafc") > contrast_ratio("#38bdf8", "#f8fafc")
      > contrast_ratio("#cbd5e1", "#f8fafc"))


def _raises(fn, *args) -> bool:
    """True when the call raises (the gate must not swallow a malformed colour)."""
    try:
        fn(*args)
    except Exception:
        return True
    return False


check("§1 a malformed colour raises instead of returning a silent ratio",
      all(_raises(contrast_ratio, value, "#ffffff")
          for value in ("red", "#12345", "", None, "#gggggg"))
      and not _raises(contrast_ratio, "#38bdf8", "#020617"),
      "one of the malformed values returned a number")


# ════════════════════════════════════════════════════════════════════════════
# §2 The DECLARED table of pairs + the exemptions
# ════════════════════════════════════════════════════════════════════════════
print("== §2 the declared pairs and the decorative exemptions ==")

# (label, foreground field, background field, threshold)
#   4.5 = text (WCAG AA, normal size)
#   3.0 = a non-text graphic that carries meaning, and the bold/large text case
# The BACKGROUND is the surface the tone is really drawn on — a status dot sits on
# the CARD (`node_bg`), not on the canvas, which is what the review measured.
CONTRAST_PAIRS = [
    # ── text on the chrome ────────────────────────────────────────────────────
    ("body text on the window", "text_primary", "window_bg", 4.5),
    ("body text on a card surface", "text_primary", "base_bg", 4.5),
    ("body text on a button", "text_primary", "surface_alt", 4.5),
    ("body text on the canvas", "text_primary", "canvas_bg", 4.5),
    ("muted text on the window (the status bar, the hints)", "text_muted", "window_bg", 4.5),
    ("muted text on a card surface (the item views)", "text_muted", "base_bg", 4.5),
    ("muted text on the canvas", "text_muted", "canvas_bg", 4.5),
    ("a vector icon on the chrome", "icon_color", "window_bg", 3.0),
    ("a vector icon on a card surface", "icon_color", "base_bg", 3.0),
    # ── the STRONG accent: the ink and the fill that carries text ─────────────
    ("the strong accent as text on the window", "accent_strong", "window_bg", 4.5),
    ("the strong accent as text on the canvas", "accent_strong", "canvas_bg", 4.5),
    ("canvas text ON the strong accent (a selected row)", "canvas_bg", "accent_strong", 4.5),
    ("the strong hover as text on the window", "accent_strong_hover", "window_bg", 4.5),
    ("canvas text ON the strong hover (a hovered button)", "canvas_bg", "accent_strong_hover", 4.5),
    ("the strong selected as text on the window", "accent_strong_selected", "window_bg", 4.5),
    # ── the amber selection (it is INK as well: the multi-input counter) ──────
    ("the amber selection as text on the window", "selection_amber", "window_bg", 4.5),
    ("the amber selection as a mark on the canvas", "selection_amber", "canvas_bg", 3.0),
    ("the amber selection as a mark on a card", "selection_amber", "node_bg", 3.0),
    # ── the server card ───────────────────────────────────────────────────────
    ("the card text", "node_text", "node_bg", 4.5),
    ("the card label", "node_label", "node_bg", 4.5),
    ("the server glyph ON the icon plate", "node_text", "node_icon_bg", 3.0),
    ("the card outline on the canvas", "node_border", "canvas_bg", 3.0),
    ("the card outline on the card", "node_border", "node_bg", 3.0),
    ("the hover outline on the canvas (also the `vpn` arrow)", "node_hover", "canvas_bg", 3.0),
    ("the hover outline on the card", "node_hover", "node_bg", 3.0),
    ("the not-yet-checked dot on the card", "dot_idle", "node_bg", 3.0),
    # ── the three statuses: ON THE CARD (where the dot is) and on the canvas ──
    ("online on the card", "status_online", "node_bg", 3.0),
    ("online on the canvas", "status_online", "canvas_bg", 3.0),
    ("warn on the card", "status_warn", "node_bg", 3.0),
    ("warn on the canvas", "status_warn", "canvas_bg", 3.0),
    ("the 'no preview' marker of the SFTP rows", "status_warn", "base_bg", 3.0),
    ("offline on the card", "status_offline", "node_bg", 3.0),
    ("offline on the canvas", "status_offline", "canvas_bg", 3.0),
    # ── the tag strip (the card's own bottom bar) ─────────────────────────────
    ("the test tag on the card", "tag_test", "node_bg", 3.0),
    ("the backup tag on the card", "tag_backup", "node_bg", 3.0),
    ("the dmz tag on the card", "tag_dmz", "node_bg", 3.0),
    ("the pink tag on the card", "tag_pink", "node_bg", 3.0),
    ("the test tag on the canvas", "tag_test", "canvas_bg", 3.0),
    ("the backup tag on the canvas", "tag_backup", "canvas_bg", 3.0),
    ("the dmz tag on the canvas", "tag_dmz", "canvas_bg", 3.0),
    ("the pink tag on the canvas", "tag_pink", "canvas_bg", 3.0),
    # ── the groups ────────────────────────────────────────────────────────────
    ("the group frame", "group_border", "canvas_bg", 3.0),
    ("the group hover frame (also the `database` arrow)", "group_hover", "canvas_bg", 3.0),
    ("the group title", "group_title", "canvas_bg", 4.5),
    ("the selected group title", "group_title_selected", "canvas_bg", 4.5),
    ("the hovered group title", "group_title_hover", "canvas_bg", 4.5),
    # ── the six connection types: a 2 px stroke on the canvas ─────────────────
    ("the ssh arrow", "arrow_ssh", "canvas_bg", 4.5),
    ("the http arrow", "arrow_http", "canvas_bg", 4.5),
    ("the nfs arrow", "arrow_nfs", "canvas_bg", 4.5),
    ("the kubernetes arrow", "arrow_kubernetes", "canvas_bg", 4.5),
    ("the vpn arrow (derived from `node_hover`)", "node_hover", "canvas_bg", 4.5),
    ("the database arrow (derived from `group_hover`)", "group_hover", "canvas_bg", 4.5),
    ("the arrow hover tone", "arrow_hover_compat", "canvas_bg", 3.0),
    # ── the sticky note ───────────────────────────────────────────────────────
    ("the note text", "note_text", "note_bg", 4.5),
    ("the note outline on the canvas", "note_border", "canvas_bg", 3.0),
    ("the note outline on a card", "note_border", "node_bg", 3.0),
    # ── the SFTP viewer's syntax palette (on the QPlainTextEdit surface) ──────
    ("syntax: a number", "syntax_number", "base_bg", 4.5),
    ("syntax: a string", "syntax_string", "base_bg", 4.5),
    ("syntax: a key", "syntax_key", "base_bg", 4.5),
    ("syntax: a keyword", "syntax_keyword", "base_bg", 4.5),
    ("syntax: a comment", "syntax_comment", "base_bg", 4.5),
    ("syntax: a tag", "syntax_tag", "base_bg", 4.5),
    ("syntax: an attribute", "syntax_attribute", "base_bg", 4.5),
    ("syntax: punctuation", "syntax_punctuation", "base_bg", 4.5),
]

# A tone that carries NO meaning on its own is EXEMPT — with the reason written
# down. The rule of the line ("no new meaning only in a colour") is what makes the
# list this short: every element the user must TELL APART is gated above.
DECORATIVE = {
    "render_bg": "the fill of the export pixmap — drawBackground paints canvas_bg over it",
    "accent": "decoration: borders, focus outlines, the search-bar frame, the minimap frame, "
              "the rubber band, the reveal glow (v1.5rc1 keeps it decorative on purpose)",
    "accent_hover": "the hover shade of the same decoration",
    "accent_selected": "the selected shade of the same decoration",
}

_gated = {name for _label, fg, bg, _t in CONTRAST_PAIRS for name in (fg, bg)}
check(f"§2 the table declares {len(CONTRAST_PAIRS)} pairs and no tone is both gated and exempt",
      not (_gated & set(DECORATIVE)),
      str(sorted(_gated & set(DECORATIVE))))
check("§2 the thresholds are the WCAG values (4.5 for text, 3.0 for a graphic)",
      {t for _l, _f, _b, t in CONTRAST_PAIRS} == {4.5, 3.0},
      str({t for _l, _f, _b, t in CONTRAST_PAIRS}))
check("§2 every pair names fields that EXIST on Theme (a typo cannot silently skip a tone)",
      all(fg in _FIELD_NAMES and bg in _FIELD_NAMES for _l, fg, bg, _t in CONTRAST_PAIRS),
      str([(fg, bg) for _l, fg, bg, _t in CONTRAST_PAIRS
           if not (fg in _FIELD_NAMES and bg in _FIELD_NAMES)]))
check("§2 every pair's foreground is a real colour (not a radius/font field)",
      all(isinstance(getattr(theme.DARK, fg), str) and HEX_RE.match(getattr(theme.DARK, fg))
          for _l, fg, _b, _t in CONTRAST_PAIRS))


# ════════════════════════════════════════════════════════════════════════════
# §3 The completeness audit — the "no orphans" rule of the hotkey registry
# ════════════════════════════════════════════════════════════════════════════
print("== §3 completeness: every colour field is gated or explained ==")

_colour_fields = {f.name for f in dataclasses.fields(theme.Theme)
                  if isinstance(getattr(theme.DARK, f.name), str)
                  and HEX_RE.match(getattr(theme.DARK, f.name))}
check(f"§3 the audit sees the {len(_colour_fields)} colour fields of Theme (the gate's subject)",
      len(_colour_fields) > 40 and "accent_strong" in _colour_fields
      and "syntax_punctuation" in _colour_fields,
      str(sorted(_colour_fields)))
check("§3 a colour entering the registry without a pair (or an exemption) FAILS the suite",
      _colour_fields <= (_gated | set(DECORATIVE)),
      "ungated: " + str(sorted(_colour_fields - _gated - set(DECORATIVE))))
check("§3 ...and the reverse: every gated/decorative name is a real colour field (no dead rows)",
      (_gated | set(DECORATIVE)) <= _colour_fields,
      "unknown: " + str(sorted((_gated | set(DECORATIVE)) - _colour_fields)))
check("§3 every exemption carries a reason (an unexplained exemption is a loophole)",
      all(isinstance(reason, str) and len(reason) > 20 for reason in DECORATIVE.values()),
      str(DECORATIVE))
check("§3 a colour field is a string in BOTH instances (a one-sided type is a defect)",
      all(isinstance(getattr(theme.LIGHT, name), str)
          for name in _colour_fields),
      str([name for name in _colour_fields
           if not isinstance(getattr(theme.LIGHT, name), str)]))


# ════════════════════════════════════════════════════════════════════════════
# §4 The gate — BOTH themes, plus "auto" resolved either way
# ════════════════════════════════════════════════════════════════════════════
print("== §4 the gate: every declared pair clears its threshold ==")

_original_scheme = theme.system_color_scheme
_auto_instances = []
try:
    for _resolved in (theme.MODE_DARK, theme.MODE_LIGHT):
        theme.system_color_scheme = lambda _r=_resolved: _r
        _auto_instances.append(theme.theme_for_mode(theme.MODE_AUTO, 210.0))
finally:
    theme.system_color_scheme = _original_scheme

_SUBJECTS = [("DARK", theme.DARK), ("LIGHT", theme.LIGHT),
             ("auto→dark", _auto_instances[0]), ("auto→light", _auto_instances[1])]

_failures = []
for _name, _instance in _SUBJECTS:
    for _label, _fg, _bg, _threshold in CONTRAST_PAIRS:
        _ratio = contrast_ratio(getattr(_instance, _fg), getattr(_instance, _bg))
        if _ratio < _threshold:
            _failures.append(f"{_name}: {_label} = {_ratio:.2f} (needs {_threshold})")
check(f"§4 the gate is GREEN in all {len(_SUBJECTS)} subjects × {len(CONTRAST_PAIRS)} pairs",
      not _failures,
      "; ".join(_failures[:6]) + (f" (+{len(_failures) - 6} more)" if len(_failures) > 6 else ""))

check("§4 the four subjects really are the resolved ones (auto followed the stub)",
      _auto_instances[0].canvas_bg == theme.DARK.canvas_bg
      and _auto_instances[1].canvas_bg == theme.LIGHT.canvas_bg,
      f"{_auto_instances[0].canvas_bg} / {_auto_instances[1].canvas_bg}")

# The gate must actually be ABLE to fail: the v1.4.3 tones are the input the design
# review measured, and the report's numbers have to reproduce here.
check("§4 the gate is not vacuous — the OLD light accent as text fails the 4.5 threshold",
      contrast_ratio("#38bdf8", theme.LIGHT.canvas_bg) < 4.5,
      str(contrast_ratio("#38bdf8", theme.LIGHT.canvas_bg)))
check("§4 the review's measured input reproduces on the v1.4.3 values it quoted",
      abs(contrast_ratio("#38bdf8", "#f1f5f9") - 1.96) < 0.02      # the accent as TEXT
      and abs(contrast_ratio("#38bdf8", "#f8fafc") - 2.05) < 0.02  # a selected row fill
      and abs(contrast_ratio("#60a5fa", "#f8fafc") - 2.43) < 0.02  # the vpn arrow
      and abs(contrast_ratio("#a78bfa", "#f8fafc") - 2.60) < 0.02  # the database arrow
      and abs(contrast_ratio("#ca8a04", "#ffffff") - 2.94) < 0.02  # the warn dot on the card
      and abs(contrast_ratio("#64748b", "#f1f5f9") - 4.34) < 0.02,  # text_muted
      f"accent/text={contrast_ratio('#38bdf8', '#f1f5f9'):.2f} "
      f"vpn={contrast_ratio('#60a5fa', '#f8fafc'):.2f} "
      f"muted={contrast_ratio('#64748b', '#f1f5f9'):.2f}")
check("§4 ...and every tone that replaced one of them is now above its threshold",
      contrast_ratio(theme.LIGHT.accent_strong, "#f1f5f9") >= 4.5
      and contrast_ratio(theme.LIGHT.node_hover, "#f8fafc") >= 3.0
      and contrast_ratio(theme.LIGHT.group_hover, "#f8fafc") >= 3.0
      and contrast_ratio(theme.LIGHT.status_warn, "#ffffff") >= 3.0
      and contrast_ratio(theme.LIGHT.text_muted, "#f1f5f9") >= 4.5,
      f"strong={contrast_ratio(theme.LIGHT.accent_strong, '#f1f5f9'):.2f}")


# ════════════════════════════════════════════════════════════════════════════
# §5 DARK did not move a pixel (the "Do not touch" rule, measured)
# ════════════════════════════════════════════════════════════════════════════
print("== §5 DARK is byte-identical to v1.4.7 ==")

check("§5 the strong accent IS the decorative accent in DARK (the role is new, the bytes are not)",
      (theme.DARK.accent_strong, theme.DARK.accent_strong_hover,
       theme.DARK.accent_strong_selected)
      == (theme.DARK.accent, theme.DARK.accent_hover, theme.DARK.accent_selected)
      == ("#38bdf8", "#51c5f9", "#20b5f7"),
      f"{theme.DARK.accent_strong} {theme.DARK.accent_strong_hover} "
      f"{theme.DARK.accent_strong_selected}")
check("§5 the strong family in DARK is GENERATED by the same hue (no literal to drift)",
      theme.accent_strong_hex() == theme.DARK.accent_strong
      and theme.accent_strong_hover_hex() == theme.DARK.accent_strong_hover
      and theme.accent_strong_selected_hex() == theme.DARK.accent_strong_selected)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPalette  # noqa: E402

app = QApplication.instance() or QApplication([])

from ui import theme_qss  # noqa: E402

# The v1.4.7 DARK stylesheet, value for value: the hexes it may contain at all, and
# the palette roles it writes. Measured against backup/sshmap_latest (v1.4.7) — the
# QSS string, the QPalette and the widget-style registry hashed IDENTICAL.
_V147_DARK_QSS_HEXES = ["#020617", "#0f172a", "#1e293b", "#334155", "#38bdf8",
                        "#94a3b8", "#e2e8f0"]
_V147_DARK_PALETTE = ["#e2e8f0", "#334155", "#ffffff", "#cacaca", "#9f9f9f", "#b8b8b8",
                      "#e2e8f0", "#ffffff", "#e2e8f0", "#1e293b", "#0f172a", "#767676",
                      "#38bdf8", "#020617", "#0000ff", "#ff00ff", "#334155", "#000000",
                      "#0f172a", "#e2e8f0", "#94a3b8", "#308cc6", "#94a3b8"]
_dark_qss = theme_qss.build_qss(theme.DARK)
check("§5 the DARK stylesheet carries exactly the v1.4.7 colours (no new tone leaked in)",
      sorted({m.lower() for m in re.findall(r"#[0-9a-fA-F]{6}\b", _dark_qss)})
      == _V147_DARK_QSS_HEXES,
      str(sorted({m.lower() for m in re.findall(r"#[0-9a-fA-F]{6}\b", _dark_qss)})))
_dark_palette = theme_qss.build_palette(theme.DARK)
_roles = []
for _role in QPalette.ColorRole:
    try:
        _roles.append(_dark_palette.color(_role).name())
    except Exception:  # noqa: BLE001 — a role the platform does not have
        pass
check("§5 the DARK QPalette is the v1.4.7 one (the Highlight moved to the strong tone = same value)",
      _roles == _V147_DARK_PALETTE, str(_roles))
check("§5 the moved call sites build the v1.4.7 DARK strings (the strong tone in place of the accent)",
      theme_qss.style("status.bar_filter") == "color: #38bdf8; padding-right: 10px;"
      and theme_qss.style("status.bar_filter_active")
      == "color: #51c5f9; font-weight: bold; padding-right: 10px;"
      and "background-color: #38bdf8;" in theme_qss.style("empty_state.button")
      and "border: 1px solid #51c5f9;" in theme_qss.style("empty_state.button"),
      theme_qss.style("empty_state.button").replace("\n", " ")[:120])


# ════════════════════════════════════════════════════════════════════════════
# §6 The LIGHT decisions — pinned as values
# ════════════════════════════════════════════════════════════════════════════
print("== §6 the LIGHT palette: the re-tuned values are pinned ==")

# The five fields the review listed as "never left DARK" — retuned here, and the
# numbers are the DECISION (the gate above is the proof they hold).
check("§6 the five dark-tuned LIGHT fields carry their own light values now",
      (theme.LIGHT.node_hover, theme.LIGHT.group_hover, theme.LIGHT.node_border,
       theme.LIGHT.note_bg, theme.LIGHT.selection_amber)
      == ("#1d4ed8", "#5b21b6", "#2563eb", "#ecd284", "#b45309"),
      str((theme.LIGHT.node_hover, theme.LIGHT.group_hover, theme.LIGHT.node_border,
           theme.LIGHT.note_bg, theme.LIGHT.selection_amber)))
check("§6 ...and none of them equals its DARK counterpart any more",
      all(getattr(theme.DARK, name) != getattr(theme.LIGHT, name) for name in
          ("node_hover", "group_hover", "node_border", "note_bg", "selection_amber")))
check("§6 text_muted reaches AA on every surface it is drawn on (the review's 4.34 case)",
      theme.LIGHT.text_muted != "#64748b"
      and min(contrast_ratio(theme.LIGHT.text_muted, "#f1f5f9"),
              contrast_ratio(theme.LIGHT.text_muted, "#f8fafc"),
              contrast_ratio(theme.LIGHT.text_muted, "#e2e8f0")) >= 4.5,
      f"{theme.LIGHT.text_muted} {contrast_ratio(theme.LIGHT.text_muted, '#e2e8f0'):.2f}")
check("§6 the card label follows the muted tone (one secondary ink, not two)",
      theme.LIGHT.node_label == theme.LIGHT.text_muted)

# The DECISION the ROADMAP asked to pin: the arrow palette keeps the DERIVATION
# (`vpn` ← node_hover, `database` ← group_hover) — LIGHT re-tunes the two hover
# fields instead of carrying a second table.
check("§6 the arrow derivation is KEPT — `vpn`/`database` still read the hover fields",
      theme.LIGHT.arrow_type_colors["vpn"] == theme.LIGHT.node_hover
      and theme.LIGHT.arrow_type_colors["database"] == theme.LIGHT.group_hover
      and theme.DARK.arrow_type_colors["vpn"] == theme.DARK.node_hover
      and theme.DARK.arrow_type_colors["database"] == theme.DARK.group_hover)
check("§6 the two derived arrows clear the AA target of a 2 px stroke (they measured 2.43/2.60)",
      contrast_ratio(theme.LIGHT.arrow_type_colors["vpn"], theme.LIGHT.canvas_bg) >= 4.5
      and contrast_ratio(theme.LIGHT.arrow_type_colors["database"],
                         theme.LIGHT.canvas_bg) >= 4.5,
      f"vpn={contrast_ratio(theme.LIGHT.arrow_type_colors['vpn'], theme.LIGHT.canvas_bg):.2f} "
      f"db={contrast_ratio(theme.LIGHT.arrow_type_colors['database'], theme.LIGHT.canvas_bg):.2f}")
check("§6 every LIGHT arrow clears 4.5:1 on the canvas (the report had 2.4 … 4.4)",
      all(contrast_ratio(value, theme.LIGHT.canvas_bg) >= 4.5
          for value in theme.LIGHT.arrow_type_colors.values()),
      str({k: round(contrast_ratio(v, theme.LIGHT.canvas_bg), 2)
           for k, v in theme.LIGHT.arrow_type_colors.items()}))
check("§6 the six LIGHT arrows are still PAIRWISE DISTINCT (a second channel is rc2's job)",
      len(set(theme.LIGHT.arrow_type_colors.values())) == 6)
check("§6 the light statuses are darker than the dark theme's (the card is white there)",
      all(contrast_ratio(getattr(theme.LIGHT, name), theme.LIGHT.node_bg) >= 3.0
          for name in ("status_online", "status_warn", "status_offline"))
      and theme.LIGHT.status_warn != "#ca8a04")

# The strong accent is a HUE-derived tone, per mode — never a stored second palette.
check("§6 the strong family is generated per mode from the SAME hue (a custom accent follows)",
      theme.accent_strong_hex(280.0, theme.MODE_LIGHT)
      == theme.theme_for_mode("light", 280.0).accent_strong
      and theme.accent_strong_hex(280.0, theme.MODE_DARK)
      == theme.theme_for_mode("dark", 280.0).accent_strong
      and theme.theme_for_mode("light", 280.0).accent_hue == 280.0)
check("§6 the LIGHT strong shades only ever go DARKER (more contrast is the one direction)",
      relative_luminance(theme.LIGHT.accent_strong)
      > relative_luminance(theme.LIGHT.accent_strong_hover)
      > relative_luminance(theme.LIGHT.accent_strong_selected)
      and contrast_ratio(theme.LIGHT.accent_strong_selected, theme.LIGHT.window_bg)
      > contrast_ratio(theme.LIGHT.accent_strong, theme.LIGHT.window_bg))
check("§6 the DARK strong shades keep the decorative ±5 direction (the look did not move)",
      relative_luminance(theme.DARK.accent_strong)
      < relative_luminance(theme.DARK.accent_strong_hover)
      and relative_luminance(theme.DARK.accent_strong)
      > relative_luminance(theme.DARK.accent_strong_selected))
check("§6 the light syntax palette was retuned to AA on the viewer surface (it measured 2.58 … 4.48)",
      all(contrast_ratio(value, theme.LIGHT.base_bg) >= 4.5
          for value in theme.LIGHT.syntax_colors.values())
      and theme.LIGHT.syntax_number != "#d97706",
      str({k: round(contrast_ratio(v, theme.LIGHT.base_bg), 2)
           for k, v in theme.LIGHT.syntax_colors.items()}))


# ════════════════════════════════════════════════════════════════════════════
# §7 "Auto (system)" — the third mode
# ════════════════════════════════════════════════════════════════════════════
print("== §7 Auto (system) ==")

check("§7 the mode list has the third value and the resolver answers with a REAL mode",
      theme.MODES == ("dark", "light", "auto")
      and theme.MODE_AUTO == "auto"
      and theme.resolve_mode("auto") in (theme.MODE_DARK, theme.MODE_LIGHT)
      and theme.resolve_mode(" AUTO ") in (theme.MODE_DARK, theme.MODE_LIGHT),
      str(theme.MODES))
check("§7 an unknown / broken mode still falls back to DARK (auto changed nothing there)",
      theme.resolve_mode("bogus") == theme.MODE_DARK
      and theme.resolve_mode(None) == theme.MODE_DARK
      and theme.resolve_mode(42) == theme.MODE_DARK
      and theme.theme_for_mode("bogus") is theme.DARK)

try:
    theme.system_color_scheme = lambda: theme.MODE_LIGHT
    _auto_light = theme.theme_for_mode("auto")
    theme.system_color_scheme = lambda: theme.MODE_DARK
    _auto_dark = theme.theme_for_mode("auto")
finally:
    theme.system_color_scheme = _original_scheme
check("§7 a stubbed platform scheme decides the instance (and it is RE-READ, not cached)",
      _auto_light is theme.LIGHT and _auto_dark is theme.DARK,
      f"{_auto_light.canvas_bg} / {_auto_dark.canvas_bg}")
check("§7 without the platform hint the answer is DARK (the pre-v1.5rc1 behaviour)",
      theme.system_color_scheme() in (theme.MODE_DARK, theme.MODE_LIGHT),
      theme.system_color_scheme())

from ui.settings_dialog import (SettingsDialog, load_theme_settings, theme_from_settings,  # noqa: E402
                                motion_from_settings, apply_motion_setting)

clear_cfg()
check("§7 no `theme` key → dark + the default accent + the motion ON",
      load_theme_settings() == {"mode": "dark", "accent": "#38bdf8", "motion": True}
      and theme_from_settings(load_theme_settings()) is theme.DARK,
      str(load_theme_settings()))
write_cfg({"theme": {"mode": "auto", "accent": "#38bdf8", "motion": False}})
check("§7 the round trip: `auto` + the motion flag come back unchanged",
      load_theme_settings() == {"mode": "auto", "accent": "#38bdf8", "motion": False},
      str(load_theme_settings()))
try:
    theme.system_color_scheme = lambda: theme.MODE_LIGHT
    _stored_auto = theme_from_settings(load_theme_settings())
finally:
    theme.system_color_scheme = _original_scheme
check("§7 ...and the stored `auto` resolves to the platform's LIGHT (not to dark)",
      _stored_auto.canvas_bg == theme.LIGHT.canvas_bg, _stored_auto.canvas_bg)
write_cfg({"theme": {"mode": "night", "accent": "#zzzzzz", "motion": "false"}})
check("§7 a foreign mode, a broken accent and a STRING motion → the defaults (never a crash)",
      load_theme_settings() == {"mode": "dark", "accent": "#38bdf8", "motion": True},
      str(load_theme_settings()))
check("§7 motion_from_settings: only a real boolean counts, a broken value means ON",
      motion_from_settings({"motion": False}) is False
      and motion_from_settings({"motion": True}) is True
      and motion_from_settings({"motion": "false"}) is True
      and motion_from_settings({"motion": 0}) is True
      and motion_from_settings(None) is True
      and motion_from_settings({}) is True)
check("§7 apply_motion_setting installs the flag into ui/motion.py",
      apply_motion_setting({"motion": False}) is False
      and apply_motion_setting({"motion": True}) is True)
clear_cfg()

try:
    theme.system_color_scheme = lambda: theme.MODE_LIGHT
    _dlg = SettingsDialog(None)
finally:
    theme.system_color_scheme = _original_scheme
check("§7 the mode combo offers dark / light / auto (auto last, dark still preselected)",
      [ _dlg.theme_mode_combo.itemData(i) for i in range(_dlg.theme_mode_combo.count()) ]
      == ["dark", "light", "auto"]
      and _dlg.theme_mode_combo.currentData() == "dark",
      str([_dlg.theme_mode_combo.itemData(i) for i in range(_dlg.theme_mode_combo.count())]))
check("§7 the 'Reduce motion' box exists, is NOT checked by default and names its effect",
      _dlg.motion_chk.text() != "" and _dlg.motion_chk.isChecked() is False
      and _dlg.motion_chk.toolTip() != "",
      f"{_dlg.motion_chk.text()!r} / {_dlg.motion_chk.toolTip()!r}")
_emitted_auto = []
_dlg.theme_changed.connect(lambda instance: _emitted_auto.append(instance))
try:
    theme.system_color_scheme = lambda: theme.MODE_LIGHT
    _dlg.theme_mode_combo.setCurrentIndex(2)   # auto
finally:
    theme.system_color_scheme = _original_scheme
check("§7 choosing `auto` emits the platform's instance live (a stubbed LIGHT here)",
      _emitted_auto and _emitted_auto[-1].canvas_bg == theme.LIGHT.canvas_bg,
      str([getattr(e, "canvas_bg", e) for e in _emitted_auto]))
check("§7 collect() keeps the appearance as ONE nested key (the hub stays 22 keys)",
      _dlg.collect()["theme"] == {"mode": "auto", "accent": _dlg._accent_hex, "motion": True}
      and len(_dlg.collect()) == 22,
      str(_dlg.collect()["theme"]))
from ui import motion as motion_mod  # noqa: E402
_was_motion = motion_mod.motion_enabled()
_dlg.motion_chk.setChecked(True)
check("§7 the box applies LIVE — checked means the animations are OFF",
      motion_mod.motion_enabled() is False and _dlg.collect()["theme"]["motion"] is False)
_dlg.reject()
check("§7 ...and Cancel() puts the flag back the way the dialog found it",
      motion_mod.motion_enabled() == _was_motion,
      f"{motion_mod.motion_enabled()} vs {_was_motion}")
_dlg.close()
motion_mod.set_motion_enabled(True)


# ════════════════════════════════════════════════════════════════════════════
# §8 The two roles AT THE CALL SITES
# ════════════════════════════════════════════════════════════════════════════
print("== §8 accent_strong at the call sites, accent in the decoration ==")

theme_qss.apply_theme(theme.LIGHT, app=app, refresh_windows=False)
_light_qss = theme_qss.build_qss(theme.LIGHT)
check("§8 the selected menu row is a STRONG fill with canvas text (was the decorative sky)",
      f"background-color: {theme.LIGHT.accent_strong};" in _light_qss
      and f"color: {theme.LIGHT.canvas_bg};" in _light_qss
      and f"background-color: {theme.LIGHT.accent};" not in _light_qss,
      theme.LIGHT.accent_strong)
check("§8 the item views and the text fields select with the strong tone (they carried text)",
      _light_qss.count(f"selection-background-color: {theme.LIGHT.accent_strong};") == 2
      and f"selection-background-color: {theme.LIGHT.accent};" not in _light_qss,
      str(_light_qss.count(f"selection-background-color: {theme.LIGHT.accent_strong};")))
check("§8 the floating cards select with it too, while their FRAME stays decorative",
      f"selection-background-color: {theme.LIGHT.accent_strong};" in theme_qss.style("search_bar")
      and f"selection-background-color: {theme.LIGHT.accent_strong};" in theme_qss.style("find_bar")
      and f"border: 1px solid {theme.LIGHT.accent};" in theme_qss.style("search_bar")
      and f"border: 1px solid {theme.LIGHT.accent};" in theme_qss.style("find_bar"))
check("§8 the status-bar counters are ink on the window surface — the strong tone",
      theme_qss.style("status.bar_filter") == f"color: {theme.LIGHT.accent_strong}; padding-right: 10px;"
      and theme_qss.style("status.bar_filter_active")
      == f"color: {theme.LIGHT.accent_strong_hover}; font-weight: bold; padding-right: 10px;",
      theme_qss.style("status.bar_filter"))
check("§8 the empty-state button fills with the strong tone and hovers DARKER in LIGHT",
      f"background-color: {theme.LIGHT.accent_strong};" in theme_qss.style("empty_state.button")
      and f"background-color: {theme.LIGHT.accent_strong_hover};"
      in theme_qss.style("empty_state.button")
      and relative_luminance(theme.LIGHT.accent_strong_hover)
      < relative_luminance(theme.LIGHT.accent_strong))
check("§8 the QPalette Highlight is the strong tone (a fill carrying HighlightedText)",
      theme_qss.build_palette(theme.LIGHT).color(QPalette.ColorRole.Highlight).name()
      == theme.LIGHT.accent_strong
      and theme_qss.build_palette(theme.LIGHT).color(
          QPalette.ColorRole.HighlightedText).name() == theme.LIGHT.canvas_bg)

# The source audit: a NEW `color: <accent>` in the QSS builder would be the same
# class of defect this release fixed. The rule is readable from the source.
_qss_src = open(os.path.join(ROOT, "ui", "theme_qss.py"), encoding="utf-8").read()
check("§8 the QSS builder never uses the DECORATIVE accent as `color:` (ink is the strong role)",
      not re.search(r"color:\s*\{t\.accent\}", _qss_src)
      and "color: {t.accent_strong}" in _qss_src,
      str(re.findall(r"color:\s*\{t\.\w+\}", _qss_src)))
check("§8 ...and every `selection-*` rule takes the strong tone (never the decorative one)",
      not re.search(r"selection-background-color:\s*\{t\.accent\}", _qss_src)
      and _qss_src.count("selection-background-color: {t.accent_strong}") >= 2)
theme_qss.apply_theme(theme.DARK, app=app, refresh_windows=False)


# ════════════════════════════════════════════════════════════════════════════
# §9 The render probe — dark / light / auto really paint differently
# ════════════════════════════════════════════════════════════════════════════
print("== §9 the render probe (dark / light / auto) ==")

from graphics.map_scene import MapScene  # noqa: E402
from models.server import ServerData  # noqa: E402


def _render_probe(instance):
    """Render a small real map under `instance`; return (dominant colour, digest, counts).

    The padding is generous on purpose: the CANVAS has to dominate the frame, so the
    dominant pixel is the surface colour of the mode (the card and the grid lines are
    counted too — that is what makes the probe see the real paint, not a constant).

    v1.5rc2: the export path defaults to the PRINT palette (the LIGHT page), so this
    probe — which asks about the theme it just installed — passes `PALETTE_THEME`
    explicitly. The print default and its opt-out are pinned by tests/test_encoding.py §5.
    """
    theme_qss.apply_theme(instance, app=app, refresh_windows=False)
    scene = MapScene()
    scene.add_server(ServerData(id="probe", alias="web-1", host="10.0.0.1",
                                user="root", tags=["prod"]))
    image = scene.render_to_pixmap(scale=1.0, padding=200.0,
                                   palette=theme.PALETTE_THEME).toImage()
    counts = {}
    digest = hashlib.sha256()
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            name = image.pixelColor(x, y).name()
            counts[name] = counts.get(name, 0) + 1
            digest.update(name.encode())
    top = max(counts.items(), key=lambda kv: kv[1])[0]
    scene.clear()
    return top, digest.hexdigest(), counts


_dark_canvas, _dark_digest, _dark_counts = _render_probe(theme.DARK)
check("§9 a DARK render is dominated by the DARK canvas (the probe sees the real paint)",
      _dark_canvas == theme.DARK.canvas_bg,
      f"{_dark_canvas} vs {theme.DARK.canvas_bg}")
_light_canvas, _light_digest, _light_counts = _render_probe(theme.LIGHT)
check("§9 a LIGHT render is dominated by the LIGHT canvas — the two really differ",
      _light_canvas == theme.LIGHT.canvas_bg and _light_canvas != _dark_canvas,
      f"{_light_canvas} vs {theme.LIGHT.canvas_bg}")
check("§9 the LIGHT render carries the retuned card (the palette reached the paint)",
      theme.LIGHT.node_bg in _light_counts and theme.DARK.node_bg in _dark_counts,
      str(sorted(_light_counts)[:8]))
check("§9 the render is DETERMINISTIC — the same theme twice gives the same image",
      _render_probe(theme.DARK)[1] == _dark_digest)
try:
    theme.system_color_scheme = lambda: theme.MODE_LIGHT
    _auto_light_canvas = _render_probe(theme.theme_for_mode(theme.MODE_AUTO))[0]
    theme.system_color_scheme = lambda: theme.MODE_DARK
    _auto_dark_canvas = _render_probe(theme.theme_for_mode(theme.MODE_AUTO))[0]
finally:
    theme.system_color_scheme = _original_scheme
check("§9 an AUTO render follows the platform both ways (the acceptance's 'auto' shot)",
      _auto_light_canvas == theme.LIGHT.canvas_bg
      and _auto_dark_canvas == theme.DARK.canvas_bg,
      f"{_auto_light_canvas} / {_auto_dark_canvas}")
theme_qss.apply_theme(theme.DARK, app=app, refresh_windows=False)


# ════════════════════════════════════════════════════════════════════════════
# §10 i18n parity + the release state
# ════════════════════════════════════════════════════════════════════════════
print("== §10 i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_i18n_format(langs)
APPEARANCE_KEYS = ["settings.appearance.mode.auto", "settings.appearance.motion",
                   "settings.appearance.motion.tooltip"]
_missing = [key for key in APPEARANCE_KEYS
            if any(not str(langs[code].get(key, "")).strip() for code in sorted(langs))]
check(f"§10 the {len(APPEARANCE_KEYS)} new appearance keys exist in EVERY language",
      not _missing, str(_missing))
_settings_src = open(os.path.join(ROOT, "ui", "settings_dialog.py"), encoding="utf-8").read()
check("§10 the new keys are actually USED by the UI code (no dead strings)",
      all(key in _settings_src for key in APPEARANCE_KEYS),
      str([key for key in APPEARANCE_KEYS if key not in _settings_src]))
check(f"§10 the parity pin covers the three new keys ({EXPECTED_I18N_KEYS})",
      all(len([k for k in langs[code] if k not in ("name", "partial")])
          == EXPECTED_I18N_KEYS for code in sorted(langs)),
      str({code: len([k for k in langs[code] if k not in ("name", "partial")])
           for code in sorted(langs)}))
check_release_state(ROOT)

finish()
