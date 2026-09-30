# -*- coding: utf-8 -*-
"""Central UI theme — the ``Theme`` object: the single source of every colour, radius and font.

PURE DATA — nothing outside the standard library is imported (no PySide6, so it is importable
without a QApplication; the PySide6 half of the switch is ``ui/theme_qss.py``). The READING side
resolves at ACCESS time: a value captured at import time never follows ``set_theme()``, so a
consumer asks for ``theme.NODE_BG`` (the live proxy) or reads a live descriptor inside ``paint()``.
``Theme`` is frozen and ``DARK`` / ``LIGHT`` are the two instances; the accent shades, the declared
``ARROW_TYPE_STYLES`` / ``STATUS_SHAPES`` and the dict views (``STATUS_COLORS``, ``TAG_COLORS``,
``SYNTAX_COLORS``) all resolve against the ACTIVE instance. Out of scope: the terminal output
palettes, the draw.io colours and ``TerminalWidget.CURSOR_COLOR``. The cache rule, the numbers and
the gates — ``DOCUMENTATION.md`` (the "Central UI theme" chapter) and ``AGENTS.md`` §4.6."""

import copy
import dataclasses
from dataclasses import dataclass
from typing import Dict, List, Optional

# The default accent hue: the sky accent `#38bdf8`, whose HSL coordinates are the three numbers
# below. The HSL↔RGB formulas round 0.5 up, so the pair is pinned by the acceptance test as VALUES
# rather than as a claim: 198.4/93/59.6 reproduces the colour to the byte, while the obvious reading
# 198/92/60 gives `#3bbbf7` — three channels off, which is why it is written out.
DEFAULT_ACCENT_HUE = 198.4

# The saturation/lightness of the accent shades. They are FIXED so that the
# three shades of one hue stay a family; only the lightness moves (0 = base,
# ±5 = the natural hover / selection pair).
ACCENT_SATURATION = 93
ACCENT_LIGHTNESS = 59.6
ACCENT_HOVER_DELTA = 5      # the brighter/hover shade   (59.6 → 64.6)
ACCENT_SELECTED_DELTA = -5  # the darker/selection shade (59.6 → 54.6)

# The theme-mode ids of the "Appearance" tab / of the ``theme.mode`` key
# (v1.5rc1: `MODE_AUTO` joins them — the platform's own colour scheme decides).
MODE_DARK = "dark"
MODE_LIGHT = "light"
MODE_AUTO = "auto"
MODES = (MODE_DARK, MODE_LIGHT, MODE_AUTO)

# ── The CARD DENSITY ──────────────────────────────────────────────────────────
# The SECOND non-colour flag of the nested ``theme`` config object (the `motion` precedent):
# how much of a card the map paints. NOT a Theme field, but read live like every other datum
# here.   * ``normal``  — alias, host, the info plaque and the two badges (the DEFAULT,
# byte-identical to the pre-1.6 card);   * ``compact`` — alias, host and the status marks only.
DENSITY_NORMAL = "normal"
DENSITY_COMPACT = "compact"
DENSITIES = (DENSITY_NORMAL, DENSITY_COMPACT)

#: The ACTIVE density — module state, set by the "Appearance" tab and applied at startup
#: (`apply_density_setting`). Read through `card_density()`, never imported as a value.
_CARD_DENSITY = DENSITY_NORMAL


def resolve_density(value) -> str:
    """A stored density value → one of ``DENSITIES`` (a broken value = ``normal``).

    PURE validation: the config is hand-editable, so an unknown string, a number or
    ``None`` means the historical card, never an error.
    """
    text = str(value or "").strip().lower()
    return text if text in DENSITIES else DENSITY_NORMAL


def card_density() -> str:
    """The ACTIVE card density (``normal`` | ``compact``) — read by the cards."""
    return _CARD_DENSITY


def set_card_density(value) -> str:
    """Install the density and return the value that is now active (never raises)."""
    global _CARD_DENSITY
    _CARD_DENSITY = resolve_density(value)
    return _CARD_DENSITY

# The EXPORT palettes (v1.5rc2, ROADMAP task 3). An export is a different medium
# from the screen: it must not print a dark page, so the DEFAULT is `print` — the
# LIGHT instance (a white page with the high-contrast lines) — and `theme` is the
# opt-out that keeps the current look. The two ids are the vocabulary of
# `MapScene.render_to_*` / `export_scene_to_drawio` and of the export dialog.
PALETTE_PRINT = "print"
PALETTE_THEME = "theme"
EXPORT_PALETTES = (PALETTE_PRINT, PALETTE_THEME)

# ── the STRONG accent ─────────────────────────────────────────────────────────
# The second role of the same hue: the tone for TEXT on a surface and for a FILL that
# carries text, so it clears the AA threshold on the surfaces of its mode. In DARK it IS
# the decorative tone (the DARK look does not move a pixel); in LIGHT its hover/selected
# pair only ever goes DARKER. Numbers, roles and the gate — `DOCUMENTATION.md`, §4.6.
ACCENT_STRONG_LIGHTNESS = {MODE_DARK: ACCENT_LIGHTNESS, MODE_LIGHT: 34.0}
ACCENT_STRONG_HOVER_DELTA = {MODE_DARK: ACCENT_HOVER_DELTA, MODE_LIGHT: -4.0}
ACCENT_STRONG_SELECTED_DELTA = {MODE_DARK: ACCENT_SELECTED_DELTA, MODE_LIGHT: -8.0}



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


# ── The STRONG accent generator (v1.5rc1) ─────────────────────────────────────
# Same hue, same saturation — a different LIGHTNESS per mode, because the job of
# this tone is contrast rather than decoration (see the constants at the top).
# The mode argument is the RESOLVED mode ("dark"/"light"), never "auto".

def _strong_lightness(mode: str, delta: float = 0.0) -> float:
    """The lightness of a strong shade for a resolved mode (an unknown mode → DARK)."""
    base = ACCENT_STRONG_LIGHTNESS.get(mode, ACCENT_STRONG_LIGHTNESS[MODE_DARK])
    return base + delta


def accent_strong_hex(hue=None, mode: str = MODE_DARK) -> str:
    """The STRONG accent of a hue (v1.5rc1) — text on a surface, a fill under text.

    DARK: the value equals ``accent_hex()`` (#38bdf8) — moving a call site onto
    the strong tone does not move a pixel. LIGHT: the lightness drops to
    ``ACCENT_STRONG_LIGHTNESS["light"]`` so the pair clears AA.
    """
    return hsl_hex(DEFAULT_ACCENT_HUE if hue is None else hue,
                   ACCENT_SATURATION, _strong_lightness(mode))


def accent_strong_hover_hex(hue=None, mode: str = MODE_DARK) -> str:
    """The HOVER shade of the strong accent (+5 lightness in DARK, −4 in LIGHT)."""
    return hsl_hex(DEFAULT_ACCENT_HUE if hue is None else hue, ACCENT_SATURATION,
                   _strong_lightness(mode, ACCENT_STRONG_HOVER_DELTA.get(
                       mode, ACCENT_STRONG_HOVER_DELTA[MODE_DARK])))


def accent_strong_selected_hex(hue=None, mode: str = MODE_DARK) -> str:
    """The SELECTED shade of the strong accent (−5 lightness in DARK, −8 in LIGHT)."""
    return hsl_hex(DEFAULT_ACCENT_HUE if hue is None else hue, ACCENT_SATURATION,
                   _strong_lightness(mode, ACCENT_STRONG_SELECTED_DELTA.get(
                       mode, ACCENT_STRONG_SELECTED_DELTA[MODE_DARK])))


# ── The second channel: per-type pen styles + status shapes ───────────────────
# OWNED HERE, next to the palettes they accompany, so a consumer (the arrow, the card dot,
# the sidebar row, the legend, the exports, the topical test) reads ONE source and a mark
# cannot drift from the map. A dash pattern and a shape are geometry, identical in DARK and
# LIGHT — but they are still reached through the ACTIVE theme (the §4.6 reading rule).

@dataclass(frozen=True)
class ArrowStyle:
    """How ONE connection type is DRAWN (v1.5rc2) — the channel next to its colour.

    ``dash``  — a QPen dash pattern (a tuple of floats, in units of the pen width;
                empty = a solid line);
    ``width`` — the stroke width at rest (the hover adds ``ARROW_HOVER_WIDTH_DELTA``);
    ``double``— draw the line as TWO rails: the stroke is laid down and a narrower
                stroke in the surface colour is painted over its centre
                (``ARROW_CASING_RATIO`` is the share the casing takes).
    """

    dash: tuple = ()
    width: float = 2.2
    double: bool = False

    def is_solid(self) -> bool:
        """True for a plain unbroken stroke (the "no second channel here" case)."""
        return not self.dash and not self.double


# The hover widens the stroke instead of replacing its width, so a wide type stays
# the widest one while it is hovered (v1.5rc2).
ARROW_HOVER_WIDTH_DELTA = 0.6
# The share of the outer width the surface-coloured casing takes on a double line.
# 0.45 leaves two rails of ~1.1 px on the declared 4.0 width — measured on the
# topical render probe (two ink runs in every column of the stroke window) and
# checked by eye at 100 % zoom, where a thinner casing reads as a single line.
ARROW_CASING_RATIO = 0.45

# The SIX declared styles — pairwise distinct (the topical gate proves it) and
# readable at 100 % zoom: a solid line, three dash rhythms, a dense dot line and a
# double rail. The keys ARE the connection type ids of `arrow_type_colors`.
ARROW_TYPE_STYLES: Dict[str, ArrowStyle] = {
    "ssh": ArrowStyle(),                                   # solid — the default type
    "vpn": ArrowStyle(dash=(7.0, 4.0)),                    # dash
    "http": ArrowStyle(dash=(1.2, 3.0)),                   # dots
    "database": ArrowStyle(dash=(9.0, 3.0, 1.5, 3.0)),     # dash-dot
    "nfs": ArrowStyle(width=4.0, double=True),             # double rail
    "kubernetes": ArrowStyle(dash=(14.0, 5.0), width=2.4),  # long dash
}

DEFAULT_ARROW_STYLE = ARROW_TYPE_STYLES.get("ssh") or ArrowStyle()


def arrow_type_style(ctype: str) -> ArrowStyle:
    """The declared style of a connection type — an unknown type gets the default's."""
    return ARROW_TYPE_STYLES.get(ctype, DEFAULT_ARROW_STYLE)


# ── The declared STATUS SHAPES ──────────────────────
# The pinned set: a filled dot / a ring / a triangle — one shape per availability status, drawn by the
# card's status dot, the sidebar row's marker and the legend, so a status is readable in greyscale and
# for colour-vision deficiencies. The WORDS stay in the tooltips (`node.status.*`), which is what makes
# the shape a second channel rather than a replacement (`AGENTS.md` §4.6).
STATUS_SHAPE_DOT = "dot"
STATUS_SHAPE_RING = "ring"
STATUS_SHAPE_TRIANGLE = "triangle"
STATUS_SHAPE_IDS = (STATUS_SHAPE_DOT, STATUS_SHAPE_RING, STATUS_SHAPE_TRIANGLE)

STATUS_SHAPES: Dict[str, str] = {
    "online": STATUS_SHAPE_DOT,       # a full dot: the machine answers
    "warn": STATUS_SHAPE_RING,        # hollow: something is off, but it is alive
    "offline": STATUS_SHAPE_TRIANGLE,  # a warning sign: unreachable
}
# The shape of an UNCHECKED status (the idle grey marker).
DEFAULT_STATUS_SHAPE = STATUS_SHAPE_DOT


def status_shape(status) -> str:
    """The declared shape of an availability status — an unknown/empty one gets the dot."""
    return STATUS_SHAPES.get(status, DEFAULT_STATUS_SHAPE)


# ── "Auto (system)" ───────────────────────────────────────────────────────────
# The third mode reads the PLATFORM's colour scheme through `QStyleHints.colorScheme()`; the
# import is LAZY (inside the function), which is how this module keeps its "no PySide6 at import
# time" contract — the same trick the class-level descriptors below use. A platform without the
# hint (or a PySide6 that does not know the enum) behaves like the dark theme, never an error.

def system_color_scheme() -> str:
    """The platform's colour scheme as a mode id (v1.5rc1) — DARK when unknown.

    Never raises: without a QApplication, without ``QStyleHints.colorScheme`` or
    with an unknown enum value the answer is the dark default, which keeps
    "Auto" a strictly additive choice.
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
    except Exception:  # noqa: BLE001 — the module stays usable without Qt
        return MODE_DARK
    try:
        app = QGuiApplication.instance()
        if app is None:
            return MODE_DARK
        scheme = app.styleHints().colorScheme()
    except Exception:  # noqa: BLE001 — an old/limited platform has no hint
        return MODE_DARK
    try:
        if scheme == Qt.ColorScheme.Light:
            return MODE_LIGHT
    except Exception:  # noqa: BLE001
        return MODE_DARK
    return MODE_DARK


def resolve_mode(mode) -> str:
    """A mode id → a RESOLVED mode id ("dark"/"light") — v1.5rc1.

    "auto" asks the platform (``system_color_scheme()``); an unknown / missing /
    non-string value falls back to DARK (a broken config must never leave the app
    themeless). The result is always one of the two INSTANCES' ids, never "auto".
    """
    key = mode.strip().lower() if isinstance(mode, str) else MODE_DARK
    if key == MODE_AUTO:
        return system_color_scheme()
    return key if key in _MODES else MODE_DARK


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
    accent: str                 # the DECORATIVE accent (reveal flash, search frame, rubber band, borders)
    accent_hover: str           # the brighter decorative accent shade
    accent_selected: str        # the darker decorative accent shade
    accent_strong: str          # THE accent for text on a surface / a fill under text (v1.5rc1)
    accent_strong_hover: str    # the hover shade of the strong accent (v1.5rc1)
    accent_strong_selected: str  # the selected shade of the strong accent (v1.5rc1)
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

    # ── Syntax highlighting of the SFTP viewer ──────────────────────
    # A palette of its OWN, like the terminal output palettes of `modules/terminal_screen.py` — these
    # tones colour the READ-ONLY preview of `modules/sftp_tab.py` and nothing else. The names are the
    # ROLE names of `modules/syntax_highlight.py` (`syntax_<role>`), and the reader is the
    # `syntax_colors` property below (`DOCUMENTATION.md` §38).
    syntax_number: str
    syntax_string: str
    syntax_key: str
    syntax_keyword: str
    syntax_comment: str
    syntax_tag: str
    syntax_attribute: str
    syntax_punctuation: str

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
        """Known roles — the fixed colours (the v0.9.4 order)."""
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
    def arrow_type_styles(self) -> Dict[str, "ArrowStyle"]:
        """id → the declared PEN style of the connection type (v1.5rc2).

        The second channel next to :attr:`arrow_type_colors`: same keys, same
        declaration order, and the ONLY place a dash pattern / stroke width /
        "double line" is written down. Identical in DARK and LIGHT (geometry, not
        a colour), returned as a fresh dict so a consumer cannot mutate the map.
        """
        return dict(ARROW_TYPE_STYLES)

    @property
    def status_shapes(self) -> Dict[str, str]:
        """status → the declared SHAPE beside its colour (v1.5rc2).

        The second channel of the three availability statuses: the card's status
        dot, the sidebar row marker and the legend all draw the shape of this map,
        so a status survives greyscale / colour-vision deficiencies. The side
        effect is deliberate: the shape is drawn in the SAME colour the status has
        always had (`status_colors`), never in a new tone.
        """
        return dict(STATUS_SHAPES)

    @property
    def sftp_preview_blocked(self) -> str:
        """A row the SFTP viewer refuses to preview (a binary / an over-limit file)."""
        return self.status_warn

    @property
    def syntax_colors(self) -> Dict[str, str]:
        """The SFTP viewer's syntax palette by ROLE (v1.4.7).

        The role vocabulary is ``modules/syntax_highlight.py``'s
        (``number | string | key | keyword | comment | tag | attribute |
        punctuation``); the field of a role is ``syntax_<role>``, which is what
        ``syntax_highlight.syntax_field()`` answers and what the topical test
        pins against this dict — the two halves of the contract can not drift.
        """
        return {"number": self.syntax_number,
                "string": self.syntax_string,
                "key": self.syntax_key,
                "keyword": self.syntax_keyword,
                "comment": self.syntax_comment,
                "tag": self.syntax_tag,
                "attribute": self.syntax_attribute,
                "punctuation": self.syntax_punctuation}

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
    # widgets that want a hover/selected variant of the accent).
    # v1.5rc1: the STRONG family resolves to these same three values in DARK —
    # the role is new, the bytes are not (the literal snapshot test proves it).
    accent_hue=DEFAULT_ACCENT_HUE,
    accent=accent_hex(DEFAULT_ACCENT_HUE),
    accent_hover=accent_hover_hex(DEFAULT_ACCENT_HUE),
    accent_selected=accent_selected_hex(DEFAULT_ACCENT_HUE),
    accent_strong=accent_strong_hex(DEFAULT_ACCENT_HUE, MODE_DARK),
    accent_strong_hover=accent_strong_hover_hex(DEFAULT_ACCENT_HUE, MODE_DARK),
    accent_strong_selected=accent_strong_selected_hex(DEFAULT_ACCENT_HUE, MODE_DARK),
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

    # Notes — the muted yellow palette (kept by LIGHT too: it
    # reads on a light background, which is why the sticky note does not change)
    note_bg="#eedd9f",
    note_border="#a9853d",
    note_text="#403a2b",

    # Syntax highlighting of the SFTP viewer (v1.4.7). Every tone is one the DARK
    # palette already ships (the amber of the HTTP arrow, the green of the SSH
    # arrow, …) — the palette is a SECOND ROLE SET over familiar values, not a
    # second look. All eight are distinct and none is the "no preview" tone
    # (`status_warn`), which is what the topical test pins.
    syntax_number="#fbbf24",        # the HTTP-arrow amber
    syntax_string="#34d399",        # the SSH-arrow green
    syntax_key="#22d3ee",           # the Kubernetes turquoise
    syntax_keyword="#a78bfa",       # the group-hover violet
    syntax_comment="#94a3b8",       # the muted text tone
    syntax_tag="#f472b6",           # the NFS-arrow pink
    syntax_attribute="#60a5fa",     # the node-hover blue
    syntax_punctuation="#cbd5e1",   # the icon outline tone

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


# ── LIGHT — the slate-100 counterpart ─────────────────────────────────────────
# The SAME field set as DARK (a field in only one instance is refused by the completeness
# test); only what a light background really changes moves. The light half is tuned against
# MEASURED thresholds: every number below is pinned by `tests/test_theme_contrast.py`, so a
# tone that stops clearing its threshold fails the suite.

LIGHT = Theme(
    # Surfaces (slate-100 scale)
    canvas_bg="#f8fafc",
    render_bg="#ffffff",
    window_bg="#f1f5f9",
    base_bg="#e2e8f0",
    surface_alt="#cbd5e1",

    # Text and icons — `text_muted` reaches AA on EVERY surface it is drawn on
    # (the status-bar counters, the zoom label, the hints, the item views; it was
    # 4.34 on the window and 3.86 on `base_bg`, now 5.57 and 5.17)
    text_primary="#0f172a",
    text_muted="#556070",
    icon_color="#475569",

    # Accent — the same hue generator as DARK (the user's hue survives a mode
    # switch). The DECORATIVE tone is the sky of v1.4.3 (borders, glows, frames);
    # the STRONG one is the ink/fill tone and is generated at the light-mode
    # lightness (34.0 → #0676a7: 4.83 on the canvas, 4.61 on the window).
    accent_hue=DEFAULT_ACCENT_HUE,
    accent=accent_hex(DEFAULT_ACCENT_HUE),
    accent_hover=accent_hover_hex(DEFAULT_ACCENT_HUE),
    accent_selected=accent_selected_hex(DEFAULT_ACCENT_HUE),
    accent_strong=accent_strong_hex(DEFAULT_ACCENT_HUE, MODE_LIGHT),
    accent_strong_hover=accent_strong_hover_hex(DEFAULT_ACCENT_HUE, MODE_LIGHT),
    accent_strong_selected=accent_strong_selected_hex(DEFAULT_ACCENT_HUE, MODE_LIGHT),
    # The selection amber is TEXT too (the status-bar selection lines) and a mark
    # on the canvas: amber-700 clears AA on the window (4.58) and 3:1 as a mark.
    selection_amber="#b45309",

    # Server node (card): the card is WHITE on the light canvas — that is what separates a node from the
    # background now (the halo shadow still works). The blues are ordered by strength: the resting
    # outline, the hover outline (also the `vpn` arrow) and the icon PLATE — which inverts with the
    # theme (a pale plate under the near-black glyph; the deep one left the glyph at 2.05:1).
    node_bg="#ffffff",
    node_border="#2563eb",
    node_hover="#1d4ed8",
    node_icon_bg="#93c5fd",
    node_text="#0f172a",
    node_label="#556070",
    # the "not checked yet" dot: LIGHT's own pale slate (3.46:1 on the white card,
    # where the v1.4.3 value measured 2.56 — and it is not DARK's own grey)
    dot_idle="#7c8ba1",

    # Availability statuses — deeper than the dark theme's (a dot sits on the
    # WHITE card, so the card is the surface that decides, not the canvas)
    status_online="#16a34a",
    status_warn="#a16207",
    status_offline="#dc2626",

    # Tags / environment roles (the two hash tones darkened a step as well)
    tag_test="#9333ea",
    tag_backup="#0891b2",
    tag_dmz="#ea580c",
    tag_pink="#db2777",

    # Groups — the violet family keeps its declaration order; the hover tone is
    # deepened so the `database` arrow (derived from it) clears 4.5 on the canvas
    group_border="#7c3aed",
    group_hover="#5b21b6",
    group_title="#6d28d9",
    group_title_selected="#92400e",
    group_title_hover="#7c3aed",

    # Connection arrows — re-tuned to the AA target of a 2 px stroke on the light
    # canvas (the review measured 3.04 … 4.39); `vpn` and `database` ARE
    # `node_hover` and `group_hover` — the derivation is kept, the two fields it
    # reads were re-tuned instead of being bypassed with a second table.
    arrow_ssh="#047857",
    arrow_http="#b45309",
    arrow_nfs="#be185d",
    arrow_kubernetes="#155e75",
    arrow_hover_compat="#065f46",

    # Notes — LIGHT's OWN sticky tone (v1.5rc1): the dark-tuned `#eedd9f` sat
    # 1.30:1 on the light canvas. The fill stays a paper colour by design — the
    # note's separation channel is its BORDER (4.66:1 on the canvas) and the
    # cached halo shadow, which is what the gate pins.
    note_bg="#ecd284",
    note_border="#8a6d2f",
    note_text="#403a2b",

    # Syntax highlighting of the SFTP viewer: the SAME role set, tuned for the light viewer background
    # (`base_bg` — the QPlainTextEdit surface the global QSS gives it), re-tuned to AA on THAT surface
    # (the first set measured 2.58 … 4.48 there). Again: eight distinct values, none of them the light
    # "no preview" tone (#a16207), every one of them a value this instance already ships elsewhere.
    syntax_number="#92400e",        # the group-title-selected amber
    syntax_string="#065f46",        # the arrow-hover green
    syntax_key="#155e75",           # the Kubernetes deep cyan
    syntax_keyword="#6d28d9",       # the group-title violet
    syntax_comment="#556070",       # the muted text tone
    syntax_tag="#be185d",           # the NFS-arrow pink
    syntax_attribute="#1d4ed8",     # the node-hover blue
    syntax_punctuation="#475569",   # the icon outline tone

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
    """The instance of a mode id, with the accent hue applied (v1.4.3; auto in v1.5rc1).

    The mode is RESOLVED first (``resolve_mode``): ``"auto"`` asks the platform's
    colour scheme and lands on DARK or LIGHT, and an unknown / missing /
    non-string mode falls back to DARK (a broken config value must never leave
    the app themeless). A hue equal to the instance's own default returns the
    SHARED instance untouched (so ``theme_for_mode("dark")`` is ``DARK`` itself —
    the identity the tests and the caches rely on).
    """
    key = resolve_mode(mode)
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
        accent_strong=accent_strong_hex(hue, key),
        accent_strong_hover=accent_strong_hover_hex(hue, key),
        accent_strong_selected=accent_strong_selected_hex(hue, key),
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


# ── The export palette ────────────────────────────────────────────────────────
# An export renders PRINT-FRIENDLY by default and "print-friendly" is not a third palette:
# it IS `LIGHT` (the white page and the strokes the contrast gate already measured at AA),
# asked for with the ACTIVE theme's accent hue so the user's accent survives the switch.
# `theme` keeps the current look; both are addressed by the two ids above — ONE vocabulary.

def resolve_export_palette(palette) -> str:
    """An export palette id → a KNOWN id (an unknown / missing value → `print`)."""
    key = palette.strip().lower() if isinstance(palette, str) else PALETTE_PRINT
    return key if key in EXPORT_PALETTES else PALETTE_PRINT


def export_theme(palette=PALETTE_PRINT, accent_hue=None) -> Theme:
    """The instance an EXPORT renders with (v1.5rc2).

    ``print``  → the LIGHT instance with the ACTIVE theme's hue (the same instance
                 object whenever the hue is the default one, so the common case
                 costs nothing and the identity the tests rely on holds);
    ``theme``  → the ACTIVE instance, i.e. exactly what is on screen now.
    An unknown palette id resolves to ``print`` (``resolve_export_palette``).
    """
    if resolve_export_palette(palette) == PALETTE_THEME:
        return THEME
    hue = THEME.hue() if accent_hue is None else accent_hue
    return theme_for_mode(MODE_LIGHT, hue)


def theme_snapshot() -> dict:
    """Every field of the ACTIVE instance as a plain dict (the config writer)."""
    return {f.name: copy.deepcopy(getattr(THEME, f.name)) for f in dataclasses.fields(Theme)}


# ── Live descriptors for CLASS-LEVEL constants (the `DOCUMENTATION.md` theme chapter) ──
# A class attribute CACHING a colour (``ServerNode.COLOR_BG = QColor(theme.NODE_BG)``) would
# capture the value at IMPORT time and keep the old theme forever, so the class-level
# constants are `ThemeColor` / `ThemeMap` / `ThemeValue` descriptors resolving the ACTIVE
# instance on every access — a FRESH QColor each time (Qt implicit sharing is the trap).

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
# Every historical name (`theme.NODE_BG`, `theme.RADIUS_NODE`, …) is resolved by the PEP-562
# hook BELOW against the ACTIVE instance, on every access — that is what makes the switch
# reach a consumer that only wrote `theme.NODE_BG`. `THEME` stays a real `Theme` object, and
# a `from ui.theme import NODE_BG` would capture ONE value, so the project imports the module.

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
    "ACCENT_STRONG": "accent_strong",
    "ACCENT_STRONG_HOVER": "accent_strong_hover",
    "ACCENT_STRONG_SELECTED": "accent_strong_selected",
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
    # syntax highlighting of the SFTP viewer (v1.4.7)
    "SYNTAX_NUMBER": "syntax_number",
    "SYNTAX_STRING": "syntax_string",
    "SYNTAX_KEY": "syntax_key",
    "SYNTAX_KEYWORD": "syntax_keyword",
    "SYNTAX_COMMENT": "syntax_comment",
    "SYNTAX_TAG": "syntax_tag",
    "SYNTAX_ATTRIBUTE": "syntax_attribute",
    "SYNTAX_PUNCTUATION": "syntax_punctuation",
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
    "SYNTAX_COLORS": "syntax_colors",
    # v1.5rc2: the two declared ENCODINGS (the pen styles and the status shapes)
    "ARROW_TYPE_STYLES": "arrow_type_styles",
    "STATUS_SHAPES": "status_shapes",
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

