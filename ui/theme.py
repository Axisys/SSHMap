# -*- coding: utf-8 -*-
"""Central UI theme for SSH Map (v1.2.5, ROADMAP v1.2.5).

Single source of truth for all colors, corner radii and font families of
the application UI: nodes, arrows, notes, groups, dialogs, status labels,
QSS strings, the base window palette (main.py). Before v1.2.5 the values
were scattered across class constants and paint code: ~50 color points in
~14 files with duplicates (#94a3b8 — 6+ places, #e2e8f0 — ~8, #38bdf8 — 5,
#f59e0b — 4).

The module is pure data: NO PySide6 import (importable without
QApplication — convenient for tests). Colors are "#rrggbb" hex strings
(QSS-compatible); consumers wrap them in QColor() where needed. Each
unique value is defined exactly ONCE; values shared by several roles are
tied together with aliases (one constant instead of two literals) —
"a single palette".

Out of scope (deliberately):
  * the palettes in modules/terminal_screen.py (default/nord/dracula/
    tokyo_night) — user-selectable color schemes for TERMINAL OUTPUT, not
    the app UI theme;
  * the colors in storage/export_drawio.py — the export format (its own
    dark/light variants in draw.io XML);
  * TerminalWidget.CURSOR_COLOR — the block cursor is tied to the
    terminal scheme's default text ("classic look"), part of the output
    appearance, not UI chrome.

Next step (ROADMAP v1.2.5 task 3, not planned here): the accent color and
a light theme are added by reassigning this module's constants — consumers
already know no literals.
"""

# ── Surfaces (dark theme, slate scale) ────────────────────────────────

CANVAS_BG = "#020617"      # canvas background: MapView background + MapScene.drawBackground (visible in export too)
RENDER_BG = "#0b1220"      # initial pixmap fill in render_to_pixmap (drawBackground paints
                           # CANVAS_BG + grid on top — like the interactive view, since v0.9.1)
WINDOW_BG = "#0f172a"      # QPalette Window; minor grid lines; search bar card
BASE_BG = "#1e293b"        # QPalette Base; node card background; major grid lines; collapse strip
SURFACE_ALT = "#334155"    # QPalette AlternateBase/Button; dialog separators; hover strip

# ── Text and icons ────────────────────────────────────────────────────────

TEXT_PRIMARY = "#e2e8f0"   # primary text: QPalette WindowText/Text/ButtonText, node text,
                           # dialog titles, status-bar zoom label
TEXT_MUTED = "#94a3b8"     # muted text: node labels, status-bar counters,
                           # terminal UI status labels (page/SFTP/dock), profile subtitle
ICON_COLOR = "#cbd5e1"     # vector icon outlines (ui/icons.py) + collapse-strip rhombi

# ── Accent and selection ────────────────────────────────────────────────────

ACCENT = "#38bdf8"             # app accent: reveal flash, search match frame,
                               # rubber-band selection, search bar frame/selection (sky-400)
SELECTION_AMBER = "#f59e0b"    # amber selection: selected node/group, background-image frame,
                               # multi-select mode badge/frame (amber-500)

# ── Server node (card) ───────────────────────────────────────────────────

NODE_BG = BASE_BG             # card background (same as QPalette Base)
NODE_BORDER = "#3b82f6"       # default border (blue-500)
NODE_HOVER = "#60a5fa"        # hover border (blue-400; same value as the "vpn" arrow)
NODE_ICON_BG = "#2563eb"      # icon circle fill (blue-600)
NODE_TEXT = TEXT_PRIMARY      # card alias text
NODE_LABEL = TEXT_MUTED       # @host label, collapse chevron
DOT_IDLE = "#64748b"          # status/SSH dots before checking (slate-500); @host label tone

# ── Availability statuses (StatusChecker) ───────────────────────────────────

STATUS_ONLINE = "#22c55e"     # green: TCP + SSH banner
STATUS_WARN = "#facc15"       # yellow: port open, no banner
STATUS_OFFLINE = "#ef4444"    # red: unreachable

# Border colors by status (v0.7.1): warn — yellow, distinct from the amber
# SELECTION_AMBER — only one of selection or status is shown at a time.
STATUS_COLORS = {
    "online": STATUS_ONLINE,   # green: TCP + SSH banner
    "warn": STATUS_WARN,       # yellow: port open, no banner
    "offline": STATUS_OFFLINE,  # red: unreachable
}

# ── Tags / environment roles (v0.9.4) ────────────────────────────────────────

TAG_TEST = "#a855f7"          # purple — test perimeter (tag + hash palette)
TAG_BACKUP = "#06b6d4"        # cyan — backup replica (tag + hash palette)
TAG_DMZ = "#f97316"           # orange — demilitarized zone (tag + hash palette)
TAG_PINK = "#ec4899"          # pink — arbitrary tags by hash

# Known roles — fixed colors (order — as in v0.9.4).
TAG_COLORS = {
    "prod": STATUS_OFFLINE,   # red — production environment
    "staging": STATUS_WARN,   # yellow — staging
    "dev": STATUS_ONLINE,     # green — development
    "test": TAG_TEST,         # purple — test perimeter
    "backup": TAG_BACKUP,     # cyan — backup replica
    "dmz": TAG_DMZ,           # orange — demilitarized zone
}

# Hash palette for arbitrary tags (crc32(name) % len): order fixed.
TAG_PALETTE = [STATUS_ONLINE, NODE_BORDER, TAG_TEST, TAG_DMZ, TAG_BACKUP, TAG_PINK]

# ── Groups (clusters/folders, v0.8.1) ───────────────────────────────────────

GROUP_BORDER = "#7c3aed"         # violet-600 — distinct from the nodes' blue (#3b82f6)
GROUP_HOVER = "#a78bfa"          # violet-400 (same value as the "database" arrow)
GROUP_TITLE = "#c4b5fd"          # violet-300 — readable on the dark map
GROUP_TITLE_SELECTED = "#fde68a"  # title when selected (amber-200)
GROUP_TITLE_HOVER = "#e9d5ff"     # title on hover (violet-200)

# ── Connection arrows: types (v0.7) ───────────────────────────────────────────

ARROW_SSH = "#34d399"            # green — default
ARROW_HTTP = "#fbbf24"           # amber
ARROW_NFS = "#f472b6"            # pink
ARROW_KUBERNETES = "#22d3ee"     # turquoise (Kubernetes)
ARROW_HOVER_COMPAT = "#6ee7b7"   # hover color, kept for compatibility with v0.6

# id → base arrow color; order — declaration order (the connection dialog
# combobox iterates it). SSH stays the default type (old projects without
# a "type" field load as SSH connections).
ARROW_TYPE_COLORS = {
    "ssh": ARROW_SSH,                    # green — default
    "vpn": NODE_HOVER,                   # blue (same value as the node hover border)
    "http": ARROW_HTTP,                  # amber
    "database": GROUP_HOVER,             # violet (same value as the group hover border)
    "nfs": ARROW_NFS,                    # pink
    "kubernetes": ARROW_KUBERNETES,      # turquoise (Kubernetes)
}

# ── Notes (stickies, muted palette v1.2.4-fix) ────────────────────

NOTE_BG = "#eedd9f"        # note body
NOTE_BORDER = "#a9853d"    # border
NOTE_TEXT = "#403a2b"      # text (editor is transparent)

# ── Corner radii (px) ───────────────────────────────────────────────

RADIUS_NODE = 10.0            # server node card (ServerNode.CORNER_RADIUS)
RADIUS_NOTE = 10.0            # note window (StickyNote.CORNER_RADIUS)
RADIUS_GROUP = 12.0           # group frame (NodeGroup.CORNER_RADIUS)
RADIUS_SEARCH_BAR = 8         # QSS border-radius of the map search bar (integer px in QSS)
RADIUS_ARROW_LABEL = 5.0      # rounded background behind the connection label text
RADIUS_RESIZE_MARK = 3.0      # group resize-corner marker
RADIUS_NODE_GLYPH_UNIT = 2.0  # "unit" corner radius in the server icon glyph

# ── Font families ─────────────────────────────────────────────────────

FONT_UI = "Segoe UI"    # UI font: node alias, group title, note editor
FONT_MONO = "Consolas"  # monospace: node info/host, connection label
