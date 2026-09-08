# -*- coding: utf-8 -*-
"""v1.2.5 — Центральная тема ui/theme.py (тема релиза, ROADMAP v1.2.5).

НОЛЬ ВИЗУАЛЬНЫХ ИЗМЕНЕНИЙ: механический рефакторинг — разбросанные по классам
hex-цвета/радиусы/шрифты (ноды, стрелки, заметки, группы, диалоги, статус-лейблы)
перенесены в именованные константы одного модуля ui/theme.py (палитра +
семантические dict'ы TAG_COLORS/ARROW_TYPE_COLORS/STATUS_COLORS + радиусы +
шрифты); QSS-строки стали f-strings со ссылками на константы темы. НЕ охват
(осознанно): палитры terminal_screen.py (default/nord/dracula/tokyo_night —
пользовательски выбираемые схемы цветов ВЫВОДА терминала), TerminalWidget.CURSOR_COLOR
(привязан к default-тексту схемы), цвета storage/export_drawio.py (формат экспорта).

§1 Модуль темы — чистые данные: импортируется БЕЗ PySide6 (ни одного импорта),
   все цвета — строчные hex "#rrggbb".
§2 Семантические dict'ы и радиусы/шрифты — ключи/значения/порядок = литералам до
   рефакторинга (включая порядок ARROW_TYPE_COLORS — его итерует комбобокс).
§3 Потребители — класс-константы, QSS, шрифты и рендер дают те же цвета, что до
   v1.2.5 (точечная сверка ключевых цветов: узел/стрелка/группа/заметка/сцена/
   поиск/диалоги/статус-лейблы/мультинабор).
§4 AST-аудит — в коде целевых файлов НЕ осталось «сырых» hex-литералов палитры
   (строковые константы; комментарии не считаются) — регрессия «новый литерал
   вместо константы темы».
§5 Вне охвата без изменений: палитры terminal_screen, CURSOR_COLOR, export_drawio.
§6 i18n-паритет (421 — новых ключей в v1.2.5 нет) + состояние релиза.
"""
import ast
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state)
ROOT, WORK = bootstrap()

# ════════════════════════════════════════════════════════════
# 1. Модуль темы — чистые данные (до любого импорта Qt!)
# ════════════════════════════════════════════════════════════
print("== 1. theme module: pure data ==")

import ui.theme as theme  # noqa: E402  — ДО PySide6: проверяем отсутствие зависимости

check("theme.py импортируется без PySide6 (чистые данные)",
      "PySide6" not in sys.modules, str([m for m in sys.modules if "PySide" in m]))

_src = open(os.path.join(ROOT, "ui", "theme.py"), encoding="utf-8").read()
_tree = ast.parse(_src)
_imports = [n for n in ast.walk(_tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
check("в theme.py НЕТ ни одного импорта (Qt-зависимости нет)", not _imports,
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
check(f"все {len(PALETTE_NAMES)} констант палитры — строчные hex #rrggbb", not bad_hex, str(bad_hex))

# ════════════════════════════════════════════════════════════
# 2. Семантические dict'ы, радиусы, шрифты (= литералам до v1.2.5)
# ════════════════════════════════════════════════════════════
print("== 2. semantic dicts / radii / fonts ==")

check("TAG_COLORS: ключи и цвета ролей (v0.9.4)", theme.TAG_COLORS == {
    "prod": "#ef4444", "staging": "#facc15", "dev": "#22c55e",
    "test": "#a855f7", "backup": "#06b6d4", "dmz": "#f97316"}, str(theme.TAG_COLORS))

check("TAG_PALETTE: порядок хэш-палитры (crc32 % 6)", theme.TAG_PALETTE == [
    "#22c55e", "#3b82f6", "#a855f7", "#f97316", "#06b6d4", "#ec4899"], str(theme.TAG_PALETTE))

check("STATUS_COLORS: online/warn/offline", theme.STATUS_COLORS == {
    "online": "#22c55e", "warn": "#facc15", "offline": "#ef4444"}, str(theme.STATUS_COLORS))

check("ARROW_TYPE_COLORS: 6 типов, значения и ПОРЯДОК (комбобокс итерует)",
      list(theme.ARROW_TYPE_COLORS.items()) == [
          ("ssh", "#34d399"), ("vpn", "#60a5fa"), ("http", "#fbbf24"),
          ("database", "#a78bfa"), ("nfs", "#f472b6"), ("kubernetes", "#22d3ee")],
      str(theme.ARROW_TYPE_COLORS))

check("радиусы: узел 10.0 / заметка 10.0 / группа 12.0",
      (theme.RADIUS_NODE, theme.RADIUS_NOTE, theme.RADIUS_GROUP) == (10.0, 10.0, 12.0))

check("радиусы: поиск 8 px (QSS) / метка связи 5.0 / resize-маркер 3.0 / глиф 2.0",
      (theme.RADIUS_SEARCH_BAR, theme.RADIUS_ARROW_LABEL,
       theme.RADIUS_RESIZE_MARK, theme.RADIUS_NODE_GLYPH_UNIT) == (8, 5.0, 3.0, 2.0))

check("шрифты: FONT_UI=Segoe UI / FONT_MONO=Consolas",
      (theme.FONT_UI, theme.FONT_MONO) == ("Segoe UI", "Consolas"))

# ════════════════════════════════════════════════════════════
# 3. Потребители — те же цвета/радиусы/шрифты, что до v1.2.5
# ════════════════════════════════════════════════════════════
print("== 3. consumers: zero visual change ==")

from PySide6.QtWidgets import QApplication, QWidget, QTabWidget  # noqa: E402
app = QApplication.instance() or QApplication([])

from models.server import ServerData  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402

node = ServerNode(ServerData(id="th1", alias="web-1", host="10.0.0.5", user="root"))
check("узел: карточка bg/border/selected/hover (#1e293b/#3b82f6/#f59e0b/#60a5fa)",
      [c.name().lower() for c in (ServerNode.COLOR_BG, ServerNode.COLOR_BORDER,
                                  ServerNode.COLOR_SELECTED, ServerNode.COLOR_HOVER)] ==
      ["#1e293b", "#3b82f6", "#f59e0b", "#60a5fa"])
check("узел: единый акцент reveal/search #38bdf8 + text/label/dot-idle",
      ServerNode.REVEAL_COLOR.name().lower() == "#38bdf8"
      and ServerNode.SEARCH_MATCH_COLOR.name().lower() == "#38bdf8"
      and ServerNode.COLOR_TEXT.name().lower() == "#e2e8f0"
      and ServerNode.COLOR_LABEL.name().lower() == "#94a3b8"
      and ServerNode.COLOR_DOT_IDLE.name().lower() == "#64748b")
check("узел: CORNER_RADIUS = theme.RADIUS_NODE (10.0)",
      ServerNode.CORNER_RADIUS == theme.RADIUS_NODE == 10.0)
check("узел: STATUS_COLORS online/warn/offline",
      {k: v.name().lower() for k, v in ServerNode.STATUS_COLORS.items()} ==
      {"online": "#22c55e", "warn": "#facc15", "offline": "#ef4444"})
check("узел: tag_color('prod') #ef4444 + порядок TAG_PALETTE",
      ServerNode.tag_color("prod").name().lower() == "#ef4444"
      and [c.name().lower() for c in ServerNode.TAG_PALETTE] ==
      ["#22c55e", "#3b82f6", "#a855f7", "#f97316", "#06b6d4", "#ec4899"])
check("узел: шрифты alias=Segoe UI, info/host=Consolas",
      node._alias.font().family() == "Segoe UI"
      and node._info.font().family() == "Consolas"
      and node._host_label.font().family() == "Consolas")

from graphics.connection_arrow import (CONNECTION_TYPES, type_color,  # noqa: E402
                                       ConnectionArrow)
check("стрелка: CONNECTION_TYPES — ТОТ ЖЕ dict, что theme.ARROW_TYPE_COLORS",
      CONNECTION_TYPES is theme.ARROW_TYPE_COLORS)
check("стрелка: 6 типов + дефолт для неизвестного (ssh)",
      [type_color(t).name().lower() for t in
       ("ssh", "vpn", "http", "database", "nfs", "kubernetes", "bogus")] ==
      ["#34d399", "#60a5fa", "#fbbf24", "#a78bfa", "#f472b6", "#22d3ee", "#34d399"])
check("стрелка: COLOR_IDLE #34d399 + COLOR_HOVER #6ee7b7 (v0.6-compat)",
      ConnectionArrow.COLOR_IDLE.name().lower() == "#34d399"
      and ConnectionArrow.COLOR_HOVER.name().lower() == "#6ee7b7")

from graphics.node_group import NodeGroup  # noqa: E402
grp = NodeGroup(0, 0)
check("группа: border/hover/selected/title (#7c3aed/#a78bfa/#f59e0b/#c4b5fd)",
      [c.name().lower() for c in (NodeGroup.COLOR_BORDER, NodeGroup.COLOR_HOVER,
                                  NodeGroup.COLOR_SELECTED, NodeGroup.COLOR_TITLE)] ==
      ["#7c3aed", "#a78bfa", "#f59e0b", "#c4b5fd"])
check("группа: CORNER_RADIUS = theme.RADIUS_GROUP (12.0) + заголовок Segoe UI",
      NodeGroup.CORNER_RADIUS == theme.RADIUS_GROUP == 12.0
      and grp._title_font().family() == "Segoe UI")
check("группа: заливки — цвета темы с альфой (#7c3aed 16/28, #f59e0b 20)",
      [(c.red(), c.green(), c.blue(), c.alpha()) for c in
       (NodeGroup.COLOR_FILL, NodeGroup.COLOR_FILL_HOVER, NodeGroup.COLOR_FILL_SELECTED)] ==
      [(0x7C, 0x3A, 0xED, 16), (0x7C, 0x3A, 0xED, 28), (0xF5, 0x9E, 0x0B, 20)])

from graphics.sticky_note import StickyNote  # noqa: E402
note = StickyNote("hello", 0, 0)
check("заметка: палитра #eedd9f/#a9853d/#403a2b + CORNER_RADIUS 10.0",
      (StickyNote.BG_COLOR, StickyNote.BORDER_COLOR, StickyNote.TEXT_COLOR) ==
      ("#eedd9f", "#a9853d", "#403a2b") and StickyNote.CORNER_RADIUS == 10.0)
check("заметка: шрифт редактора Segoe UI", note.widget().font().family() == "Segoe UI")

from graphics.map_scene import MapScene  # noqa: E402
scene = MapScene()
check("сцена: сетка minor/major #0f172a/#1e293b",
      scene._grid_color.name().lower() == "#0f172a"
      and scene._grid_major_color.name().lower() == "#1e293b")
_pm = scene.render_to_pixmap(scale=1.0)
_img = _pm.toImage()
# Пустая сцена → src = itemsBoundingRect().adjusted(±60) = (-60,-60,120,120), 1:1 в pixmap.
# QGraphicsScene.render вызывает drawBackground (поведение с v0.9.1, без изменений):
# фон CANVAS_BG + сетка (линии на device-x/y ∈ {0,20,…,120}). Пиксели ≥2 px от линий —
# чистый фон; пиксель на пересечении линий — blend цвета сетки (отличается от фона).
_bg = [_img.pixelColor(x, y) for x, y in ((5, 5), (10, 10), (30, 30))]
check("рендер: фон pixmap между линиями сетки #020617 (CANVAS_BG) — пиксельная сверка",
      all((c.red(), c.green(), c.blue()) == (0x02, 0x06, 0x17) for c in _bg),
      str([(c.red(), c.green(), c.blue()) for c in _bg]))
_line = _img.pixelColor(20, 20)  # пересечение minor-линий (device 20 = scene -40)
check("рендер: сетка в экспорте рисуется (пиксель на линии ≠ фон)",
      (_line.red(), _line.green(), _line.blue()) != (0x02, 0x06, 0x17),
      f"rgb=({_line.red()}, {_line.green()}, {_line.blue()})")

from graphics.map_view import MapView  # noqa: E402
view = MapView(scene)
check("вью: фон холста #020617 (CANVAS_BG)",
      view.backgroundBrush().color().name().lower() == "#020617")

from ui.map_search_bar import MapSearchBar  # noqa: E402
_bar = MapSearchBar()
ss = _bar.styleSheet()
check("поиск: QSS карточка #0f172a / акцент #38bdf8 / border-radius 8px",
      "background-color: #0f172a" in ss and "border: 1px solid #38bdf8" in ss
      and "border-radius: 8px" in ss, ss)
check("поиск: QSS текст #e2e8f0 / приглушённый #94a3b8",
      "color: #e2e8f0" in ss and "color: #94a3b8" in ss)

from ui.main_window import _CollapseStrip, _diamond_icon  # noqa: E402
_strip = _CollapseStrip()
_sp = _strip.grab().toImage().pixelColor(2, 2)
check("полоска сворачивания: заливка #1e293b (BASE_BG) — пиксельная сверка",
      (_sp.red(), _sp.green(), _sp.blue()) == (0x1E, 0x29, 0x3B),
      f"rgb=({_sp.red()}, {_sp.green()}, {_sp.blue()})")
check("ромб «◇»: иконка рендерится (контур theme.ICON_COLOR)", not _diamond_icon().isNull())

from ui import icons as _icons  # noqa: E402
check("иконки: ICON_COLOR #cbd5e1 + рендер",
      _icons.ICON_COLOR == "#cbd5e1" and not _icons.get_icon("new").isNull())

from dialogs.add_server_dialog import AddServerDialog  # noqa: E402
_dlg = AddServerDialog()
_styles = [w.styleSheet() for w in _dlg.findChildren(QWidget) if w.styleSheet()]
check("AddServerDialog: разделитель #334155 (SURFACE_ALT)", "color: #334155;" in _styles,
      str(_styles))

from dialogs.ssh_connect_dialog import SSHConnectDialog  # noqa: E402
_cdlg = SSHConnectDialog(ServerData(id="th2", alias="db-1", host="10.0.0.6", user="root"))
_styles = [w.styleSheet() for w in _cdlg.findChildren(QWidget) if w.styleSheet()]
check("SSHConnectDialog: разделитель #334155 / заголовки #e2e8f0 / статус #94a3b8",
      "color: #334155;" in _styles and "font-weight: bold; color: #e2e8f0;" in _styles
      and "color: #94a3b8;" in _styles, str(_styles))

from dialogs.profile_manager_dialog import ProfileManagerDialog  # noqa: E402
_pdlg = ProfileManagerDialog()
_styles = [w.styleSheet() for w in _pdlg.findChildren(QWidget) if w.styleSheet()]
check("ProfileManagerDialog: заголовок #e2e8f0 / подзаголовок #94a3b8",
      "font-size: 13pt; font-weight: bold; color: #e2e8f0;" in _styles
      and "color: #94a3b8; font-size: 10pt;" in _styles, str(_styles))

from modules.terminal_dock import TerminalDockContent  # noqa: E402
_dc = TerminalDockContent()
check("док терминалов: статус-лейбл #94a3b8 (TEXT_MUTED)",
      _dc.status_label.styleSheet() == "color: #94a3b8; padding: 2px 0;",
      _dc.status_label.styleSheet())

from modules.sftp_tab import SftpTab  # noqa: E402
_tab = SftpTab()
check("SFTP-вкладка: строка пути #94a3b8 (TEXT_MUTED)",
      _tab.path_label.styleSheet() == "color: #94a3b8; padding: 2px 0;",
      _tab.path_label.styleSheet())

from modules.multi_input import MULTI_ACCENT, apply_container_highlight  # noqa: E402


class _FakeHost:
    """Дак-тип хоста для apply_container_highlight (табы + заголовок)."""

    def __init__(self):
        self.session_tabs = QTabWidget()
        self._multi_base_title = None


_fh = _FakeHost()
check("мультинабор: MULTI_ACCENT #f59e0b (SELECTION_AMBER) + рамка контейнера",
      MULTI_ACCENT == "#f59e0b" and apply_container_highlight(_fh, True)
      and "border: 2px solid #f59e0b" in _fh.session_tabs.styleSheet(),
      f"accent={MULTI_ACCENT} qss={_fh.session_tabs.styleSheet()!r}")

# ════════════════════════════════════════════════════════════
# 4. AST-аудит: «сырых» hex-литералов палитры в коде не осталось
# ════════════════════════════════════════════════════════════
print("== 4. AST audit: no raw palette literals in target files ==")

# Целевые файлы рефакторинга (задача 2 ROADMAP v1.2.5). ui/theme.py НЕ в списке —
# это источник истины литералов. Вне охвата (свои литералы легитимны):
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
    """Все hex-значения (#rrggbb, без учёта регистра) в строковых константах файла.

    AST: комментарии и docstring-пометки вне кода не ловятся; f-strings разбираются
    на части (литеральные куски + выражения), поэтому «color: {theme.X}» литерала не даёт.
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
check(f"AST-аудит {len(SCAN_FILES)} файлов: ни одного литерала палитры в строках",
      not violations, str(violations))

# ════════════════════════════════════════════════════════════
# 5. Вне охвата — без изменений (ROADMAP v1.2.5 «НЕ охват»)
# ════════════════════════════════════════════════════════════
print("== 5. out-of-scope modules untouched ==")

from modules import terminal_screen as _ts  # noqa: E402
check("terminal_screen: палитры default/nord/dracula/tokyo_night на месте",
      set(_ts.PALETTES) == {"default", "nord", "dracula", "tokyo_night"}
      and _ts.PALETTES["default"]["default_fg"] == "#e2e8f0"
      and _ts.PALETTES["nord"]["default_bg"] == "#2e3440"
      and _ts.DEFAULT_FG_HEX == "#e2e8f0" and _ts.DEFAULT_BG_HEX == "#0f172a")

from modules.terminal_widget import TerminalWidget  # noqa: E402
check("TerminalWidget.CURSOR_COLOR без изменений (#e2e8f0, default-текст схемы)",
      TerminalWidget.CURSOR_COLOR == "#e2e8f0", TerminalWidget.CURSOR_COLOR)

from storage.export_drawio import NODE_FILL, NODE_STROKE, NOTE_FILL  # noqa: E402
check("export_drawio: цвета экспорта без изменений (формат draw.io)",
      (NODE_FILL, NODE_STROKE, NOTE_FILL) == ("#0f172a", "#38bdf8", "#facc15"))

# ════════════════════════════════════════════════════════════
# 6. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════════
print("== 6. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)  # 421 — в v1.2.5 новых ключей нет (рефакторинг без UI-текстов)
check_release_state(ROOT)

finish()
