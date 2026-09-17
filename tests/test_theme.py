# -*- coding: utf-8 -*-
"""v1.2.5 — The central theme ui/theme.py (release theme, ROADMAP v1.2.5).

ZERO VISUAL CHANGES: the mechanical refactoring — the hex colors/radii/fonts scattered across the classes
(the nodes, the arrows, the notes, the groups, the dialogs, the status labels)
are moved into the named constants of a single module ui/theme.py (the palette +
the semantic dicts TAG_COLORS/ARROW_TYPE_COLORS/STATUS_COLORS + the radii +
the fonts); the QSS strings became the f-strings with the references to the theme constants. NOT covered
(consciously): the palettes of terminal_screen.py (default/nord/dracula/tokyo_night —
the user-selectable color schemes of the TERMINAL OUTPUT), TerminalWidget.CURSOR_COLOR
(tied to the default text of the scheme), the colors of storage/export_drawio.py (the format of the export).

§1 The theme module — the pure data: it is imported WITHOUT PySide6 (not a single import),
   all the colors — the string hex "#rrggbb".
§2 The semantic dicts and the radii/fonts — the keys/values/order = the literals before
   the refactoring (including the order of ARROW_TYPE_COLORS — the combobox iterates it).
§3 The consumers — the class constants, the QSS, the fonts and the render give the same colors as before
   v1.2.5 (the point cross-check of the key colors: the node/the arrow/the group/the note/the scene/
   the search/the dialogs/the status labels/the multi-input).
§4 The AST audit — there are NO "raw" hex literals of the palette left in the code of the target files
   (the string constants; the comments do not count) — the regression "a new literal
   instead of a theme constant".
§5 Outside the coverage is unchanged: the palettes of terminal_screen, CURSOR_COLOR, export_drawio.
§6 The i18n parity (421 — no new keys in v1.2.5) + the release state.
"""
import ast
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state)
ROOT, WORK = bootstrap()

# ════════════════════════════════════════════════════════════
# 1. The theme module — pure data (before any Qt import!)
# ════════════════════════════════════════════════════════════
print("== 1. theme module: pure data ==")

import ui.theme as theme  # noqa: E402  — BEFORE PySide6: we check the absence of the dependency

check("theme.py imports without PySide6 (pure data)",
      "PySide6" not in sys.modules, str([m for m in sys.modules if "PySide" in m]))

_src = open(os.path.join(ROOT, "ui", "theme.py"), encoding="utf-8").read()
_tree = ast.parse(_src)
_imports = [n for n in ast.walk(_tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
check("theme.py has NOT a single import (no Qt dependency)", not _imports,
      repr([ast.dump(n) for n in _imports[:3]]))

HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
PALETTE_NAMES = [
    "CANVAS_BG", "RENDER_BG", "WINDOW_BG", "BASE_BG", "SURFACE_ALT",
    "TEXT_PRIMARY", "TEXT_MUTED", "ICON_COLOR", "ACCENT", "SELECTION_AMBER",
    "NODE_BORDER", "NODE_HOVER", "NODE_ICON_BG", "DOT_IDLE",
    "STATUS_ONLINE", "STATUS_WARN", "STATUS_OFFLINE",
    "TAG_TEST", "TAG_BACKUP", "TAG_DMZ", "TAG_PINK",
    "GROUP_BORDER", "GROUP_HOVER", "GROUP_TITLE", "GROUP_TITLE_SELECTED", "GROUP_TITLE_HOVER",
    "ARROW_SSH", "ARROW_HTTP", "ARROW_NFS", "ARROW_KUBERNETES", "ARROW_HOVER_COMPAT",
    "NOTE_BG", "NOTE_BORDER", "NOTE_TEXT",
]
bad_hex = [n for n in PALETTE_NAMES if not HEX_RE.match(getattr(theme, n))]
check(f"all the {len(PALETTE_NAMES)} palette constants are lowercase hex #rrggbb", not bad_hex, str(bad_hex))

# ════════════════════════════════════════════════════════════
# 2. The semantic dicts, radii, fonts (= the literals from before v1.2.5)
# ════════════════════════════════════════════════════════════
print("== 2. semantic dicts / radii / fonts ==")

check("TAG_COLORS: the keys and the role colors (v0.9.4)", theme.TAG_COLORS == {
    "prod": "#ef4444", "staging": "#facc15", "dev": "#22c55e",
    "test": "#a855f7", "backup": "#06b6d4", "dmz": "#f97316"}, str(theme.TAG_COLORS))

check("TAG_PALETTE: the hash-palette order (crc32 % 6)", theme.TAG_PALETTE == [
    "#22c55e", "#3b82f6", "#a855f7", "#f97316", "#06b6d4", "#ec4899"], str(theme.TAG_PALETTE))

check("STATUS_COLORS: online/warn/offline", theme.STATUS_COLORS == {
    "online": "#22c55e", "warn": "#facc15", "offline": "#ef4444"}, str(theme.STATUS_COLORS))

check("ARROW_TYPE_COLORS: 6 types, the values and the ORDER (the combobox iterates)",
      list(theme.ARROW_TYPE_COLORS.items()) == [
          ("ssh", "#34d399"), ("vpn", "#60a5fa"), ("http", "#fbbf24"),
          ("database", "#a78bfa"), ("nfs", "#f472b6"), ("kubernetes", "#22d3ee")],
      str(theme.ARROW_TYPE_COLORS))

check("the radii: node 10.0 / note 10.0 / group 12.0",
      (theme.RADIUS_NODE, theme.RADIUS_NOTE, theme.RADIUS_GROUP) == (10.0, 10.0, 12.0))

check("the radii: search 8 px (QSS) / connection label 5.0 / resize mark 3.0 / glyph 2.0",
      (theme.RADIUS_SEARCH_BAR, theme.RADIUS_ARROW_LABEL,
       theme.RADIUS_RESIZE_MARK, theme.RADIUS_NODE_GLYPH_UNIT) == (8, 5.0, 3.0, 2.0))

check("the fonts: FONT_UI=Segoe UI / FONT_MONO=Consolas",
      (theme.FONT_UI, theme.FONT_MONO) == ("Segoe UI", "Consolas"))

# ════════════════════════════════════════════════════════════
# 3. The consumers — the same colors/radii/fonts as before v1.2.5
# ════════════════════════════════════════════════════════════
print("== 3. consumers: zero visual change ==")

from PySide6.QtWidgets import QApplication, QWidget, QTabWidget  # noqa: E402
app = QApplication.instance() or QApplication([])

from models.server import ServerData  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402

node = ServerNode(ServerData(id="th1", alias="web-1", host="10.0.0.5", user="root"))
check("the node: the card bg/border/selected/hover (#1e293b/#3b82f6/#f59e0b/#60a5fa)",
      [c.name().lower() for c in (ServerNode.COLOR_BG, ServerNode.COLOR_BORDER,
                                  ServerNode.COLOR_SELECTED, ServerNode.COLOR_HOVER)] ==
      ["#1e293b", "#3b82f6", "#f59e0b", "#60a5fa"])
check("the node: the single accent reveal/search #38bdf8 + text/label/dot-idle",
      ServerNode.REVEAL_COLOR.name().lower() == "#38bdf8"
      and ServerNode.SEARCH_MATCH_COLOR.name().lower() == "#38bdf8"
      and ServerNode.COLOR_TEXT.name().lower() == "#e2e8f0"
      and ServerNode.COLOR_LABEL.name().lower() == "#94a3b8"
      and ServerNode.COLOR_DOT_IDLE.name().lower() == "#64748b")
check("the node: CORNER_RADIUS = theme.RADIUS_NODE (10.0)",
      ServerNode.CORNER_RADIUS == theme.RADIUS_NODE == 10.0)
check("the node: STATUS_COLORS online/warn/offline",
      {k: v.name().lower() for k, v in ServerNode.STATUS_COLORS.items()} ==
      {"online": "#22c55e", "warn": "#facc15", "offline": "#ef4444"})
check("the node: tag_color('prod') #ef4444 + the TAG_PALETTE order",
      ServerNode.tag_color("prod").name().lower() == "#ef4444"
      and [c.name().lower() for c in ServerNode.TAG_PALETTE] ==
      ["#22c55e", "#3b82f6", "#a855f7", "#f97316", "#06b6d4", "#ec4899"])
check("the node: the fonts alias=Segoe UI, info/host=Consolas",
      node._alias.font().family() == "Segoe UI"
      and node._info.font().family() == "Consolas"
      and node._host_label.font().family() == "Consolas")

from graphics.connection_arrow import (CONNECTION_TYPES, type_color,  # noqa: E402
                                       ConnectionArrow)
check("the arrow: CONNECTION_TYPES — the SAME dict as theme.ARROW_TYPE_COLORS",
      CONNECTION_TYPES is theme.ARROW_TYPE_COLORS)
check("the arrow: 6 types + the default for an unknown one (ssh)",
      [type_color(t).name().lower() for t in
       ("ssh", "vpn", "http", "database", "nfs", "kubernetes", "bogus")] ==
      ["#34d399", "#60a5fa", "#fbbf24", "#a78bfa", "#f472b6", "#22d3ee", "#34d399"])
check("the arrow: COLOR_IDLE #34d399 + COLOR_HOVER #6ee7b7 (the v0.6 compat)",
      ConnectionArrow.COLOR_IDLE.name().lower() == "#34d399"
      and ConnectionArrow.COLOR_HOVER.name().lower() == "#6ee7b7")

from graphics.node_group import NodeGroup  # noqa: E402
grp = NodeGroup(0, 0)
check("the group: border/hover/selected/title (#7c3aed/#a78bfa/#f59e0b/#c4b5fd)",
      [c.name().lower() for c in (NodeGroup.COLOR_BORDER, NodeGroup.COLOR_HOVER,
                                  NodeGroup.COLOR_SELECTED, NodeGroup.COLOR_TITLE)] ==
      ["#7c3aed", "#a78bfa", "#f59e0b", "#c4b5fd"])
check("the group: CORNER_RADIUS = theme.RADIUS_GROUP (12.0) + the title in Segoe UI",
      NodeGroup.CORNER_RADIUS == theme.RADIUS_GROUP == 12.0
      and grp._title_font().family() == "Segoe UI")
check("the group: the fills are the theme colors with alpha (#7c3aed 16/28, #f59e0b 20)",
      [(c.red(), c.green(), c.blue(), c.alpha()) for c in
       (NodeGroup.COLOR_FILL, NodeGroup.COLOR_FILL_HOVER, NodeGroup.COLOR_FILL_SELECTED)] ==
      [(0x7C, 0x3A, 0xED, 16), (0x7C, 0x3A, 0xED, 28), (0xF5, 0x9E, 0x0B, 20)])

from graphics.sticky_note import StickyNote  # noqa: E402
note = StickyNote("hello", 0, 0)
check("the note: the palette #eedd9f/#a9853d/#403a2b + CORNER_RADIUS 10.0",
      (StickyNote.BG_COLOR, StickyNote.BORDER_COLOR, StickyNote.TEXT_COLOR) ==
      ("#eedd9f", "#a9853d", "#403a2b") and StickyNote.CORNER_RADIUS == 10.0)
check("the note: the editor font is Segoe UI", note.widget().font().family() == "Segoe UI")

from graphics.map_scene import MapScene  # noqa: E402
scene = MapScene()
check("the scene: the minor/major grid #0f172a/#1e293b",
      scene._grid_color.name().lower() == "#0f172a"
      and scene._grid_major_color.name().lower() == "#1e293b")
_pm = scene.render_to_pixmap(scale=1.0)
_img = _pm.toImage()
# An empty scene → src = itemsBoundingRect().adjusted(±60) = (-60,-60,120,120), 1:1 into the pixmap.
# QGraphicsScene.render calls drawBackground (the behaviour since v0.9.1, unchanged):
# the CANVAS_BG background + the grid (lines at device x/y ∈ {0,20,…,120}). Pixels ≥2 px from the lines —
# a clean background; the pixel at the line intersection — a blend of the grid color (different from the background).
_bg = [_img.pixelColor(x, y) for x, y in ((5, 5), (10, 10), (30, 30))]
check("the render: the pixmap background between the grid lines #020617 (CANVAS_BG) — a pixel check",
      all((c.red(), c.green(), c.blue()) == (0x02, 0x06, 0x17) for c in _bg),
      str([(c.red(), c.green(), c.blue()) for c in _bg]))
_line = _img.pixelColor(20, 20)  # the intersection of the minor lines (device 20 = scene -40)
check("the render: the grid is drawn in the export (the pixel on the line ≠ the background)",
      (_line.red(), _line.green(), _line.blue()) != (0x02, 0x06, 0x17),
      f"rgb=({_line.red()}, {_line.green()}, {_line.blue()})")

from graphics.map_view import MapView  # noqa: E402
view = MapView(scene)
check("the view: the canvas background #020617 (CANVAS_BG)",
      view.backgroundBrush().color().name().lower() == "#020617")

from ui.map_search_bar import MapSearchBar  # noqa: E402
_bar = MapSearchBar()
ss = _bar.styleSheet()
check("the search: the QSS card #0f172a / the accent #38bdf8 / border-radius 8px",
      "background-color: #0f172a" in ss and "border: 1px solid #38bdf8" in ss
      and "border-radius: 8px" in ss, ss)
check("the search: the QSS text #e2e8f0 / the muted #94a3b8",
      "color: #e2e8f0" in ss and "color: #94a3b8" in ss)

from ui.main_window import _CollapseStrip, _diamond_icon  # noqa: E402
_strip = _CollapseStrip()
_sp = _strip.grab().toImage().pixelColor(2, 2)
check("the collapse strip: the fill #1e293b (BASE_BG) — a pixel check",
      (_sp.red(), _sp.green(), _sp.blue()) == (0x1E, 0x29, 0x3B),
      f"rgb=({_sp.red()}, {_sp.green()}, {_sp.blue()})")
check("the '◇' rhombus: the icon renders (the outline theme.ICON_COLOR)", not _diamond_icon().isNull())

from ui import icons as _icons  # noqa: E402
check("the icons: ICON_COLOR #cbd5e1 + the render",
      _icons.ICON_COLOR == "#cbd5e1" and not _icons.get_icon("new").isNull())

from dialogs.add_server_dialog import AddServerDialog  # noqa: E402
_dlg = AddServerDialog()
_styles = [w.styleSheet() for w in _dlg.findChildren(QWidget) if w.styleSheet()]
check("AddServerDialog: the separator #334155 (SURFACE_ALT)", "color: #334155;" in _styles,
      str(_styles))

from dialogs.ssh_connect_dialog import SSHConnectDialog  # noqa: E402
_cdlg = SSHConnectDialog(ServerData(id="th2", alias="db-1", host="10.0.0.6", user="root"))
_styles = [w.styleSheet() for w in _cdlg.findChildren(QWidget) if w.styleSheet()]
check("SSHConnectDialog: the separator #334155 / the headings #e2e8f0 / the status #94a3b8",
      "color: #334155;" in _styles and "font-weight: bold; color: #e2e8f0;" in _styles
      and "color: #94a3b8;" in _styles, str(_styles))

from dialogs.profile_manager_dialog import ProfileManagerDialog  # noqa: E402
_pdlg = ProfileManagerDialog()
_styles = [w.styleSheet() for w in _pdlg.findChildren(QWidget) if w.styleSheet()]
check("ProfileManagerDialog: the title #e2e8f0 / the subtitle #94a3b8",
      "font-size: 13pt; font-weight: bold; color: #e2e8f0;" in _styles
      and "color: #94a3b8; font-size: 10pt;" in _styles, str(_styles))

from modules.terminal_dock import TerminalDockContent  # noqa: E402
_dc = TerminalDockContent()
check("the terminals dock: the status label #94a3b8 (TEXT_MUTED)",
      _dc.status_label.styleSheet() == "color: #94a3b8; padding: 2px 0;",
      _dc.status_label.styleSheet())

from modules.sftp_tab import SftpTab  # noqa: E402
_tab = SftpTab()
check("the SFTP tab: the path row #94a3b8 (TEXT_MUTED)",
      _tab.path_label.styleSheet() == "color: #94a3b8; padding: 2px 0;",
      _tab.path_label.styleSheet())

from modules.multi_input import MULTI_ACCENT, apply_container_highlight  # noqa: E402


class _FakeHost:
    """A duck-typed host for apply_container_highlight (the tabs + the title)."""

    def __init__(self):
        self.session_tabs = QTabWidget()
        self._multi_base_title = None


_fh = _FakeHost()
check("multi-input: MULTI_ACCENT #f59e0b (SELECTION_AMBER) + the container frame",
      MULTI_ACCENT == "#f59e0b" and apply_container_highlight(_fh, True)
      and "border: 2px solid #f59e0b" in _fh.session_tabs.styleSheet(),
      f"accent={MULTI_ACCENT} qss={_fh.session_tabs.styleSheet()!r}")

# ════════════════════════════════════════════════════════════
# 4. AST audit: no "raw" palette hex literals are left in the code
# ════════════════════════════════════════════════════════════
print("== 4. AST audit: no raw palette literals in target files ==")

# The target files of the refactor (ROADMAP v1.2.5 task 2). ui/theme.py is NOT in the list —
# this is the source of truth of the literals. Out of scope (their own literals are legitimate):
# modules/terminal_screen.py, modules/terminal_widget.py, storage/export_drawio.py.
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
]

FORBIDDEN = {v.lower() for v in (
    list(PALETTE_NAMES) and [getattr(theme, n) for n in PALETTE_NAMES])}


def _hex_in_strings(path):
    """All the hex values (#rrggbb, case-insensitive) in the string constants of the file.

    AST: the comments and the docstring notes outside the code are not caught; the f-strings are parsed
    into the parts (the literal pieces + the expressions), hence "color: {theme.X}" gives no literal.
    """
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            for m in re.finditer(r"#[0-9a-fA-F]{6}\b", n.value):
                found.append((n.lineno, m.group(0).lower()))
    return found


violations = {}
for rel in SCAN_FILES:
    hits = [h for h in _hex_in_strings(rel) if h[1] in FORBIDDEN]
    if hits:
        violations[rel] = hits
check(f"the AST audit of the {len(SCAN_FILES)} files: not a single palette literal in the strings",
      not violations, str(violations))

# ════════════════════════════════════════════════════════════
# 5. Out of scope — unchanged (ROADMAP v1.2.5 "NOT in scope")
# ════════════════════════════════════════════════════════════
print("== 5. out-of-scope modules untouched ==")

from modules import terminal_screen as _ts  # noqa: E402
check("terminal_screen: the palettes default/nord/dracula/tokyo_night are in place",
      set(_ts.PALETTES) == {"default", "nord", "dracula", "tokyo_night"}
      and _ts.PALETTES["default"]["default_fg"] == "#e2e8f0"
      and _ts.PALETTES["nord"]["default_bg"] == "#2e3440"
      and _ts.DEFAULT_FG_HEX == "#e2e8f0" and _ts.DEFAULT_BG_HEX == "#0f172a")

from modules.terminal_widget import TerminalWidget  # noqa: E402
check("TerminalWidget.CURSOR_COLOR is unchanged (#e2e8f0, the default scheme text)",
      TerminalWidget.CURSOR_COLOR == "#e2e8f0", TerminalWidget.CURSOR_COLOR)

from storage.export_drawio import NODE_FILL, NODE_STROKE, NOTE_FILL  # noqa: E402
check("export_drawio: the export colors are unchanged (the draw.io format)",
      (NODE_FILL, NODE_STROKE, NOTE_FILL) == ("#0f172a", "#38bdf8", "#facc15"))

# ════════════════════════════════════════════════════════════
# 6. i18n parity + release state
# ════════════════════════════════════════════════════════════
print("== 6. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)  # 421 — v1.2.5 has no new keys (a refactor without UI texts)
check_release_state(ROOT)

finish()
