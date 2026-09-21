# -*- coding: utf-8 -*-
"""Central UI theme for SSH Map — the ``Theme`` object (v1.2.5, reworked in v1.4.3).

The single source of truth for every colour, corner radius and font family of
the application UI: nodes, arrows, notes, groups, dialogs, status labels, QSS
strings, the base window palette (main.py).

* v1.2.5 introduced the module with module-level constants (~50 colour points
  in ~14 files with duplicates).
* **v1.4.3 turned those constants into ONE ``Theme`` object.** The v1.2.5
  docstring promised "the accent colour and a light theme are added by
  reassigning this module's constants" — that promise was WRONG in one detail:
  a consumer that captured a value at import time (``COLOR_BG = theme.NODE_BG``
  in a class body, a QBrush built in ``__init__``) would never see the switch.
  Reassigning is still what happens underneath, but the reading side moved to
  *access time*: a consumer asks for ``theme.NODE_BG`` (the live proxy) or reads
  a live descriptor / a property inside ``paint()``, so ``set_theme()`` is
  visible everywhere without touching a single consumer.

Structure of this module:

    Theme      — the frozen dataclass: EVERY colour, radius and font of the UI;
    DARK       — the instance that replicates the pre-v1.4.3 constants (the
                 default; the values are pinned by tests/test_theme.py);
    LIGHT      — the slate-100 counterpart (a light canvas, darker statuses);
    accent_hex / accent_hover_hex / accent_selected_hex
               — PURE functions: one hue → the three accent shades;
    THEME      — the ACTIVE instance; ``set_theme()`` swaps it;
    every old name (CANVAS_BG, ACCENT, RADIUS_NODE, FONT_UI, …) — a live proxy
               that resolves against the ACTIVE instance on EVERY access;
    STATUS_COLORS / TAG_COLORS / TAG_PALETTE / ARROW_TYPE_COLORS — live dict
               views of the same instance (they are DERIVED, not stored twice).

The module stays pure data: NO PySide6 import, importable without QApplication
(convenient for tests). Colours are "#rrggbb" hex strings (QSS-compatible);
consumers wrap them in QColor() where needed. The one exception is the
PySide6-touching half of the switch — ``ui/theme_qss.py`` (the QPalette + the
QSS builder), deliberately a separate module so this one keeps its promise.

Out of scope (deliberately — see AGENTS.md §4.6):
  * the palettes in modules/terminal_screen.py (default/nord/dracula/
    tokyo_night) — user-selectable colour schemes for TERMINAL OUTPUT, not the
    app UI theme;
  * the colours in storage/export_drawio.py — the export format (its own
    dark/light variants in draw.io XML);
  * TerminalWidget.CURSOR_COLOR — the block cursor is tied to the terminal
    scheme's default text ("classic look"), part of the output appearance.

Adding a colour: one field on ``Theme``, one line in ``DARK``, one line in
``LIGHT``, one proxy line at the bottom of this module — and NOTHING else (a
new field that exists in only one instance is refused by the completeness test).

Dependency policy (unchanged in spirit, adjusted in v1.4.3): the module imports
NOTHING outside the standard library (``dataclasses`` / ``copy`` / ``typing``) —
in particular NO PySide6, so it stays importable without a QApplication. The
PySide6 half of the switch lives in ``ui/theme_qss.py``.
"""

import copy
import dataclasses
from dataclasses import dataclass
from typing import Dict, List, Optional

# The default accent hue (v1.4.3): the sky accent of v1.2.5-v1.4.2 (#38bdf8).
# The three numbers below are the HSL coordinates of that EXACT colour — and the
# HSL↔RGB formulas round 0.5 up, so the coordinates are pinned by the acceptance
# test as VALUES rather than as a claim: 198.4/93/59.6 reproduces `#38bdf8` to
# the byte, which is what keeps DARK's accent identical to the pre-v1.4.3
# constant instead of "nearly identical". (198/92/60, the obvious reading, gives
# `#3bbbf7` — three channels off — which is why the pair is written out.)
DEFAULT_ACCENT_HUE = 198.4

# The saturation/lightness of the accent shades. They are FIXED so that the
# three shades of one hue stay a family; only the lightness moves (0 = base,
# ±5 = the natural hover / selection pair).
ACCENT_SATURATION = 93
ACCENT_LIGHTNESS = 59.6
ACCENT_HOVER_DELTA = 5      # the brighter/hover shade   (59.6 → 64.6)
ACCENT_SELECTED_DELTA = -5  # the darker/selection shade (59.6 → 54.6)

# The theme-mode ids of the "Appearance" tab / of the ``theme.mode`` key.
MODE_DARK = "dark"
MODE_LIGHT = "light"
MODES = (MODE_DARK, MODE_LIGHT)


# ── The accent generator (pure: no Qt, no state) ──────────────────────────────

def hsl_hex(hue, saturation: float, lightness: float) -> str:
    """HSL → "#rrggbb" (v1.4.3). A PURE function — the module stays Qt-free.

    ``hue`` is an angle in degrees (any real number — it wraps), saturation and
    lightness are 0..100 percentages. 199/92/60 gives the v1.2.5 accent
    ``#38bdf8`` exactly (pinned by the acceptance test).
    """
    h = (float(hue) % 360.0) / 360.0
    s = min(max(float(saturation), 0.0), 100.0) / 100.0
    li = min(max(float(lightness), 0.0), 100.0) / 100.0

    if s <= 0.0:
        v = int(round(li * 255))
        return "#{:02x}{:02x}{:02x}".format(v, v, v)
    q = li * (1.0 + s) if li < 0.5 else li + s - li * s
    p = 2.0 * li - q

    def channel(t: float) -> int:
        t = t % 1.0
        if t < 1.0 / 6.0:
            value = p + (q - p) * 6.0 * t
        elif t < 0.5:
            value = q
        elif t < 2.0 / 3.0:
            value = p + (q - p) * (2.0 / 3.0 - t) * 6.0
        else:
            value = p
        return int(round(value * 255))

    return "#{:02x}{:02x}{:02x}".format(channel(h + 1.0 / 3.0),
                                        channel(h), channel(h - 1.0 / 3.0))


def hex_hue(hex_color: str) -> float:
    """The hue (degrees, rounded to 1 decimal) of a "#rrggbb" colour.

    The reverse of :func:`hsl_hex`, used by the settings hub to derive the hue
    of a hand-picked colour (and by the tests to close the round trip).
    """
    value = (hex_color or "").strip().lstrip("#")
    if len(value) != 6:
        return float(DEFAULT_ACCENT_HUE)
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return float(DEFAULT_ACCENT_HUE)
    mx, mn = max(r, g, b), min(r, g, b)
    delta = mx - mn
    if delta <= 1e-9:
        return 0.0
    if mx == r:
        h = ((g - b) / delta) % 6.0
    elif mx == g:
        h = (b - r) / delta + 2.0
    else:
        h = (r - g) / delta + 4.0
    return round((h * 60.0) % 360.0, 1)


def accent_hex(hue=None) -> str:
    """The BASE accent of a hue (v1.4.3) — 199 → today's ``#38bdf8``."""
    return hsl_hex(DEFAULT_ACCENT_HUE if hue is None else hue,
                   ACCENT_SATURATION, ACCENT_LIGHTNESS)


def accent_hover_hex(hue=None) -> str:
    """The HOVER/brighter accent shade of a hue (60 → 70 lightness)."""
    return hsl_hex(DEFAULT_ACCENT_HUE if hue is None else hue,
                   ACCENT_SATURATION, ACCENT_LIGHTNESS + ACCENT_HOVER_DELTA)


def accent_selected_hex(hue=None) -> str:
    """The SELECTION/darker accent shade of a hue (60 → 50 lightness)."""
    return hsl_hex(DEFAULT_ACCENT_HUE if hue is None else hue,
                   ACCENT_SATURATION, ACCENT_LIGHTNESS + ACCENT_SELECTED_DELTA)


def is_valid_hex(value) -> bool:
    """Is ``value`` a usable "#rrggbb" colour (the config.json validator)?"""
    if not isinstance(value, str):
        return False
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


# ── The Theme object ──────────────────────────────────────────────────────────
# Field names are the snake_case form of the historical constant names
# (CANVAS_BG → canvas_bg); the module proxies at the bottom of this file restore
# the historical spelling for every existing consumer.

@dataclass(frozen=True)
class Theme:
    """Every colour, radius and font of the application UI (v1.4.3).

    Frozen: a switch REPLACES the active instance (``set_theme()``), it never
    mutates one — a half-switched palette cannot happen. The three semantic
    dicts (STATUS_COLORS / TAG_COLORS / TAG_PALETTE / ARROW_TYPE_COLORS) are
    DERIVED properties, not fields: the values are declared exactly once and the
    dicts always follow the instance.
    """

    # ── Surfaces ─────────────────────────────────────────────────────────────
    canvas_bg: str         # canvas background: MapView + MapScene.drawBackground (visible in export too)
    render_bg: str         # initial pixmap fill in render_to_pixmap (drawBackground paints canvas_bg + grid on top)
    window_bg: str         # QPalette Window; minor grid lines; search bar card
    base_bg: str           # QPalette Base; node card background; major grid lines; collapse strip
    surface_alt: str       # QPalette AlternateBase/Button; dialog separators; hover strip

    # ── Text and icons ───────────────────────────────────────────────────────
    text_primary: str      # QPalette WindowText/Text/ButtonText, node text, dialog titles
    text_muted: str        # node labels, status-bar counters, terminal UI status labels
    icon_color: str        # vector icon outlines (ui/icons.py) + collapse-strip rhombi

    # ── Accent and selection ─────────────────────────────────────────────────
    accent_hue: Optional[float]  # the ONE accent source (None = DEFAULT_ACCENT_HUE)
    accent: str                 # the base accent (reveal flash, search frame, rubber band)
    accent_hover: str           # the brighter accent shade
    accent_selected: str        # the darker accent shade
    selection_amber: str        # amber selection: selected node/group, multi-select badge/frame

    # ── Server node (card) ───────────────────────────────────────────────────
    node_bg: str
    node_border: str
    node_hover: str
    node_icon_bg: str
    node_text: str
    node_label: str
    dot_idle: str          # status/SSH dots before checking; @host label tone

    # ── Availability statuses (StatusChecker) ────────────────────────────────
    status_online: str
    status_warn: str
    status_offline: str

    # ── Tags / environment roles ─────────────────────────────────────────────
    tag_test: str
    tag_backup: str
    tag_dmz: str
    tag_pink: str

    # ── Groups (clusters/folders) ────────────────────────────────────────────
    group_border: str
    group_hover: str
    group_title: str
    group_title_selected: str
    group_title_hover: str

    # ── Connection arrows: types ─────────────────────────────────────────────
    arrow_ssh: str
    arrow_http: str
    arrow_nfs: str
    arrow_kubernetes: str
    arrow_hover_compat: str

    # ── Notes (stickies) ─────────────────────────────────────────────────────
    note_bg: str
    note_border: str
    note_text: str

    # ── Corner radii (px) ────────────────────────────────────────────────────
    radius_node: float
    radius_note: float
    radius_group: float
    radius_search_bar: int      # integer px (QSS border-radius)
    radius_arrow_label: float
    radius_resize_mark: float
    radius_node_glyph_unit: float

    # ── Font families ────────────────────────────────────────────────────────
    font_ui: str
    font_mono: str

    # ── The semantic dicts (derived — declared once, above) ──────────────────

    @property
    def status_colors(self) -> Dict[str, str]:
        """Border colours by availability status (the v0.7.1 semantics)."""
        return {"online": self.status_online,
                "warn": self.status_warn,
                "offline": self.status_offline}

    @property
    def tag_colors(self) -> Dict[str, str]:
        """Known roles — fixed colours (order as in v0.9.4)."""
        return {"prod": self.status_offline,   # red — production environment
                "staging": self.status_warn,   # yellow — staging
                "dev": self.status_online,     # green — development
                "test": self.tag_test,         # purple — test perimeter
                "backup": self.tag_backup,     # cyan — backup replica
                "dmz": self.tag_dmz}           # orange — demilitarized zone

    @property
    def tag_palette(self) -> List[str]:
        """Hash palette for arbitrary tags (crc32(name) % len): order fixed."""
        return [self.status_online, self.node_border, self.tag_test,
                self.tag_dmz, self.tag_backup, self.tag_pink]

    @property
    def arrow_type_colors(self) -> Dict[str, str]:
        """id → base arrow colour; declaration order = the connection dialog's combo."""
        return {"ssh": self.arrow_ssh,             # green — default
                "vpn": self.node_hover,            # blue (same value as the node hover border)
                "http": self.arrow_http,           # amber
                "database": self.group_hover,      # violet (same value as the group hover border)
                "nfs": self.arrow_nfs,             # pink
                "kubernetes": self.arrow_kubernetes}  # turquoise (Kubernetes)

    @property
    def sftp_preview_blocked(self) -> str:
        """A row the SFTP viewer refuses to preview (a binary / an over-limit file)."""
        return self.status_warn

    def hue(self) -> float:
        """The resolved accent hue (``accent_hue`` or the default 198.4).

        A float on purpose: the default IS fractional, and rounding it here
        would move the default accent off ``#38bdf8`` (see the module note).
        A broken value (a string, None handled above) falls back to the default.
        """
        value = self.accent_hue
        if value is None:
            return float(DEFAULT_ACCENT_HUE)
        try:
            return round(float(value) % 360.0, 1)
        except (TypeError, ValueError):
            return float(DEFAULT_ACCENT_HUE)

    def replace(self, **changes) -> "Theme":
        """A copy with the given fields replaced (the same contract as dataclasses.replace)."""
        return dataclasses.replace(self, **changes)


# ── DARK — the default; the pre-v1.4.3 constants, value for value ─────────────

DARK = Theme(
    # Surfaces (slate scale)
    canvas_bg="#020617",
    render_bg="#0b1220",
    window_bg="#0f172a",
    base_bg="#1e293b",
    surface_alt="#334155",

    # Text and icons
    text_primary="#e2e8f0",
    text_muted="#94a3b8",
    icon_color="#cbd5e1",

    # Accent (the generated sky pair is unused by DARK's own consumers — the
    # base accent IS today's #38bdf8; the other two shades exist for the
    # widgets that want a hover/selected variant of the accent)
    accent_hue=DEFAULT_ACCENT_HUE,
    accent=accent_hex(DEFAULT_ACCENT_HUE),
    accent_hover=accent_hover_hex(DEFAULT_ACCENT_HUE),
    accent_selected=accent_selected_hex(DEFAULT_ACCENT_HUE),
    selection_amber="#f59e0b",

    # Server node (card)
    node_bg="#1e293b",
    node_border="#3b82f6",
    node_hover="#60a5fa",
    node_icon_bg="#2563eb",
    node_text="#e2e8f0",
    node_label="#94a3b8",
    dot_idle="#64748b",

    # Availability statuses
    status_online="#22c55e",
    status_warn="#facc15",
    status_offline="#ef4444",

    # Tags / environment roles
    tag_test="#a855f7",
    tag_backup="#06b6d4",
    tag_dmz="#f97316",
    tag_pink="#ec4899",

    # Groups
    group_border="#7c3aed",
    group_hover="#a78bfa",
    group_title="#c4b5fd",
    group_title_selected="#fde68a",
    group_title_hover="#e9d5ff",

    # Connection arrows
    arrow_ssh="#34d399",
    arrow_http="#fbbf24",
    arrow_nfs="#f472b6",
    arrow_kubernetes="#22d3ee",
    arrow_hover_compat="#6ee7b7",

    # Notes — the muted yellow palette of v1.2.4-fix (kept by LIGHT too: it
    # reads on a light background, which is why the sticky note does not change)
    note_bg="#eedd9f",
    note_border="#a9853d",
    note_text="#403a2b",

    # Corner radii
    radius_node=10.0,
    radius_note=10.0,
    radius_group=12.0,
    radius_search_bar=8,
    radius_arrow_label=5.0,
    radius_resize_mark=3.0,
    radius_node_glyph_unit=2.0,

    # Fonts
    font_ui="Segoe UI",
    font_mono="Consolas",
)


# ── LIGHT — the slate-100 counterpart (v1.4.3, ROADMAP task 2) ────────────────
# The SAME field set as DARK (a field existing in only one instance is refused
# by the completeness test). Only what a light background really changes moves:
# the surfaces, the two text tones, the icon outline, the three statuses
# (darkened for contrast on white), the arrow colours that are too pale on a
# light canvas, and the group title tones. The node border/icon, the tag roles,
# the amber selection and the sticky note stay — they already read on light.

LIGHT = Theme(
    # Surfaces (slate-100 scale)
    canvas_bg="#f8fafc",
    render_bg="#ffffff",
    window_bg="#f1f5f9",
    base_bg="#e2e8f0",
    surface_alt="#cbd5e1",

    # Text and icons
    text_primary="#0f172a",
    text_muted="#64748b",
    icon_color="#475569",

    # Accent — the same hue generator as DARK (the user's hue survives a mode switch)
    accent_hue=DEFAULT_ACCENT_HUE,
    accent=accent_hex(DEFAULT_ACCENT_HUE),
    accent_hover=accent_hover_hex(DEFAULT_ACCENT_HUE),
    accent_selected=accent_selected_hex(DEFAULT_ACCENT_HUE),
    selection_amber="#f59e0b",

    # Server node (card): the card is WHITE on the light canvas — that is what
    # separates a node from the background now (the halo shadow still works)
    node_bg="#ffffff",
    node_border="#3b82f6",
    node_hover="#60a5fa",
    node_icon_bg="#2563eb",
    node_text="#0f172a",
    node_label="#64748b",
    dot_idle="#94a3b8",

    # Availability statuses — slightly darker for contrast on a light background
    status_online="#16a34a",
    status_warn="#ca8a04",
    status_offline="#dc2626",

    # Tags / environment roles (the two hash tones darkened a step as well)
    tag_test="#9333ea",
    tag_backup="#0891b2",
    tag_dmz="#ea580c",
    tag_pink="#db2777",

    # Groups
    group_border="#7c3aed",
    group_hover="#a78bfa",
    group_title="#6d28d9",
    group_title_selected="#b45309",
    group_title_hover="#7c3aed",

    # Connection arrows — the four pale tones darkened one step
    arrow_ssh="#059669",
    arrow_http="#d97706",
    arrow_nfs="#db2777",
    arrow_kubernetes="#0891b2",
    arrow_hover_compat="#34d399",

    # Notes — unchanged by design (the yellow sticky fits a light background)
    note_bg="#eedd9f",
    note_border="#a9853d",
    note_text="#403a2b",

    # Corner radii — geometry, identical in both instances
    radius_node=10.0,
    radius_note=10.0,
    radius_group=12.0,
    radius_search_bar=8,
    radius_arrow_label=5.0,
    radius_resize_mark=3.0,
    radius_node_glyph_unit=2.0,

    # Fonts — identical in both instances
    font_ui="Segoe UI",
    font_mono="Consolas",
)


# ── The active instance and the switch ───────────────────────────────────────

DARK_MODE = MODE_DARK     # the default mode: the dark theme stays the default
THEME: Theme = DARK       # THE ACTIVE instance — swapped by set_theme()

_MODES: Dict[str, Theme] = {MODE_DARK: DARK, MODE_LIGHT: LIGHT}


def theme_for_mode(mode, accent_hue=None) -> Theme:
    """The instance of a mode id, with the accent hue applied (v1.4.3).

    An unknown / missing / non-string mode → DARK (the default; a broken config
    value must never leave the app themeless). A hue equal to the instance's own
    default returns the SHARED instance untouched (so ``theme_for_mode("dark")``
    is ``DARK`` itself — the identity the tests and the caches rely on).
    """
    key = mode.strip().lower() if isinstance(mode, str) else MODE_DARK
    base = _MODES.get(key) or DARK
    if accent_hue is None:
        return base
    try:
        hue = round(float(accent_hue) % 360.0, 1)
    except (TypeError, ValueError):
        return base
    if hue == base.hue():
        return base
    return dataclasses.replace(
        base,
        accent_hue=hue,
        accent=accent_hex(hue),
        accent_hover=accent_hover_hex(hue),
        accent_selected=accent_selected_hex(hue),
    )


def set_theme(instance: Theme) -> Theme:
    """Make ``instance`` the ACTIVE theme and return it (v1.4.3).

    Every live proxy / descriptor in the application resolves against this
    pointer at ACCESS time, so a switch is visible immediately — and it costs
    nothing else: no widget is rebuilt, no signal is emitted. The repaint is the
    caller's half (``ui/theme_qss.py apply_theme()`` does the palette + the QSS
    + a scene repaint); a non-Theme argument is IGNORED rather than raising, so
    a broken caller cannot leave the app half-switched.
    """
    global THEME
    if not isinstance(instance, Theme):
        return THEME
    THEME = instance
    return THEME


def current_theme() -> Theme:
    """The ACTIVE instance (the explicit form of ``THEME``)."""
    return THEME


def theme_snapshot() -> dict:
    """Every field of the ACTIVE instance as a plain dict (the config writer)."""
    return {f.name: copy.deepcopy(getattr(THEME, f.name)) for f in dataclasses.fields(Theme)}


# ── Live descriptors for CLASS-LEVEL constants ────────────────────────────────
# A class that used to cache a colour in its body is the second half of the
# v1.4.3 problem (the first is the module constant): ``ServerNode.COLOR_BG =
# QColor(theme.NODE_BG)`` captured the value at IMPORT time, so a class attribute
# read (``node.COLOR_BG``, ``ServerNode.STATUS_COLORS``) — which is how the
# paint code and the tests read them — would keep the old theme forever. These
# two descriptors keep the exact old syntax working while resolving the ACTIVE
# instance on every access. A fresh QColor per access is deliberate: a QColor is
# a cheap value object and the shared-instance trap (Qt implicit sharing) is
# exactly what the switch has to avoid.

class ThemeColor:
    """A class attribute that is ``QColor(theme.<field>)`` of the ACTIVE theme.

    ``field`` may be a theme field (``"node_bg"``) or a derived one
    (``"sftp_preview_blocked"``). A class read returns the colour WITHOUT
    storing it, so a switch is picked up on the next paint.
    """

    __slots__ = ("_field", "_alpha")

    def __init__(self, field_name: str, alpha: int = 255):
        self._field = field_name
        self._alpha = int(alpha)

    def __get__(self, obj, objtype=None):
        from PySide6.QtGui import QColor  # lazy: the module stays Qt-free until used
        color = QColor(getattr(THEME, self._field))
        if self._alpha != 255:
            color.setAlpha(self._alpha)
        return color

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<ThemeColor {self._field!r} alpha={self._alpha}>"


class ThemeMap:
    """A class attribute that is a map (or a list) of one theme field.

    ``QColor`` values by default (``STATUS_COLORS`` / ``TAG_COLORS`` /
    ``TAG_PALETTE`` — the way the paint code and the tests read them); with
    ``as_hex=True`` the values stay the raw ``"#rrggbb"`` strings of the theme
    (a consumer that needs the QSS spelling).
    """

    __slots__ = ("_field", "_as_list", "_as_hex")

    def __init__(self, field_name: str, as_list: bool = False, as_hex: bool = False):
        self._field = field_name
        self._as_list = as_list
        self._as_hex = as_hex

    def __get__(self, obj, objtype=None):
        source = getattr(THEME, self._field)
        if self._as_hex:
            return list(source) if self._as_list else dict(source)
        from PySide6.QtGui import QColor  # lazy: the module stays Qt-free until used
        if self._as_list:
            return [QColor(value) for value in source]
        return {key: QColor(value) for key, value in source.items()}

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<ThemeMap {self._field!r} list={self._as_list} hex={self._as_hex}>"


class ThemeValue:
    """A class attribute computed from the ACTIVE theme on every access.

    The escape hatch for a colour that is not a plain field: a tinted fill
    (``_tint(t.group_border, 16)``), a value derived from another module
    (``ConnectionArrow.COLOR_IDLE`` = the default type's colour). The factory is
    called LAZILY, so the descriptor can be declared above the function or the
    module constant it uses — the look-up happens when the value is read.
    """

    __slots__ = ("_factory",)

    def __init__(self, factory):
        self._factory = factory

    def __get__(self, obj, objtype=None):
        return self._factory()

    def __repr__(self):  # pragma: no cover - debugging aid
        name = getattr(self._factory, "__name__", repr(self._factory))
        return f"<ThemeValue {name}>"


# ── Live module-level constants ───────────────────────────────────────────────
# Every historical name of this module (`theme.NODE_BG`, `theme.RADIUS_NODE`,
# `theme.FONT_UI`, …) is resolved by the module PEP-562 hook BELOW against the
# ACTIVE instance, on every access. This is what makes the switch reach a
# consumer that only ever wrote `theme.NODE_BG`: before v1.4.3 that read a plain
# string captured at import time; now it asks the module every single time.
#
# Two deliberate consequences:
#   * `THEME` stays a real Theme object (not a name in the mapping), so
#     `isinstance(theme.THEME, theme.Theme)` and `dataclasses.replace()` work;
#   * `from ui.theme import NODE_BG` would capture ONE value and silently stop
#     following the theme — the imports inside the project therefore always go
#     through the module (`from ..ui import theme`), which is what they did since
#     v1.2.5. The mapping below is the authoritative list of the live names.

_LIVE_FIELDS: Dict[str, str] = {
    # surfaces
    "CANVAS_BG": "canvas_bg",
    "RENDER_BG": "render_bg",
    "WINDOW_BG": "window_bg",
    "BASE_BG": "base_bg",
    "SURFACE_ALT": "surface_alt",
    # text and icons
    "TEXT_PRIMARY": "text_primary",
    "TEXT_MUTED": "text_muted",
    "ICON_COLOR": "icon_color",
    # accent and selection
    "ACCENT": "accent",
    "ACCENT_HOVER": "accent_hover",
    "ACCENT_SELECTED": "accent_selected",
    "SELECTION_AMBER": "selection_amber",
    # server node (card)
    "NODE_BG": "node_bg",
    "NODE_BORDER": "node_border",
    "NODE_HOVER": "node_hover",
    "NODE_ICON_BG": "node_icon_bg",
    "NODE_TEXT": "node_text",
    "NODE_LABEL": "node_label",
    "DOT_IDLE": "dot_idle",
    # availability statuses
    "STATUS_ONLINE": "status_online",
    "STATUS_WARN": "status_warn",
    "STATUS_OFFLINE": "status_offline",
    # tags / environment roles
    "TAG_TEST": "tag_test",
    "TAG_BACKUP": "tag_backup",
    "TAG_DMZ": "tag_dmz",
    "TAG_PINK": "tag_pink",
    # groups
    "GROUP_BORDER": "group_border",
    "GROUP_HOVER": "group_hover",
    "GROUP_TITLE": "group_title",
    "GROUP_TITLE_SELECTED": "group_title_selected",
    "GROUP_TITLE_HOVER": "group_title_hover",
    # connection arrows
    "ARROW_SSH": "arrow_ssh",
    "ARROW_HTTP": "arrow_http",
    "ARROW_NFS": "arrow_nfs",
    "ARROW_KUBERNETES": "arrow_kubernetes",
    "ARROW_HOVER_COMPAT": "arrow_hover_compat",
    # notes
    "NOTE_BG": "note_bg",
    "NOTE_BORDER": "note_border",
    "NOTE_TEXT": "note_text",
    # corner radii
    "RADIUS_NODE": "radius_node",
    "RADIUS_NOTE": "radius_note",
    "RADIUS_GROUP": "radius_group",
    "RADIUS_SEARCH_BAR": "radius_search_bar",
    "RADIUS_ARROW_LABEL": "radius_arrow_label",
    "RADIUS_RESIZE_MARK": "radius_resize_mark",
    "RADIUS_NODE_GLYPH_UNIT": "radius_node_glyph_unit",
    # fonts
    "FONT_UI": "font_ui",
    "FONT_MONO": "font_mono",
    # derived single values
    "SFTP_PREVIEW_BLOCKED": "sftp_preview_blocked",
}

# The DERIVED dict/list names — a fresh object per access (so a consumer that
# holds one sees the values of the theme it asked of; a consumer that re-reads
# `theme.STATUS_COLORS` follows the switch). `is` is deliberately NOT identity
# here: `theme.ARROW_TYPE_COLORS == another_dict` is the contract (v1.4.3).
_LIVE_DERIVED: Dict[str, str] = {
    "STATUS_COLORS": "status_colors",
    "TAG_COLORS": "tag_colors",
    "TAG_PALETTE": "tag_palette",
    "ARROW_TYPE_COLORS": "arrow_type_colors",
}


def __getattr__(name: str):
    """PEP-562 hook: resolve the historical constants against the ACTIVE theme.

    Anything not in the two mappings keeps its ordinary module semantics (an
    AttributeError), so `theme.does_not_exist` still fails loudly.
    """
    field_name = _LIVE_FIELDS.get(name)
    if field_name is not None:
        return getattr(THEME, field_name)
    prop_name = _LIVE_DERIVED.get(name)
    if prop_name is not None:
        return getattr(THEME, prop_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """Include the live names in `dir(theme)` / the module's autocompletion."""
    return sorted(set(globals()) | set(_LIVE_FIELDS) | set(_LIVE_DERIVED))

