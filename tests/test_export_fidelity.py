# -*- coding: utf-8 -*-
"""v1.3.3.7 — Export fidelity: the drawio vertex keeps the map's data, SVG joins the formats.

Checks (ROADMAP v1.3.3.7; offscreen, no network; the tests/test_drawio_export.py parser pattern):
  §1 the drawio label carries the TAGS and the COMMENT — a multi-line comment survives
     through `&#xa;`, the file stays parseable by `ET`, a node without them gains NO
     extra line, and a group MEMBER cell is built by the same label function;
  §2 the source audit of the two decisions: `status` is deliberately NOT read by the
     exporter (a runtime fact, not project data — a live status never reaches the file)
     and the tag COLOURS are not replicated;
  §3 the SVG export: the file, the `<?xml`/`<svg` header, the node and connection
     labels, background + grid (the drawBackground composition), the returned size ==
     the size on disk, the scale parameter, an empty scene, and the API identity with
     `render_to_pixmap`;
  §4 the File menu: `_export_map_svg` exists, `file.export_svg` is in the i18n registry
     AND in the hotkey registry (with a registered target), and a real call writes the file;
  §5 the fate of the dead `load_drawio_structure` helper — DELETED, no importers left
     (the decision recorded in v1.3.3.7);
  §6 i18n (the 2 new keys × every discovered language + parity + format) and the release state.

Run: python tests/test_export_fidelity.py   (from the project root) or python tests/run_all.py
"""
import os
import re
import xml.etree.ElementTree as ET

from _common import bootstrap, check, finish, check_i18n_parity, check_i18n_format, \
    load_i18n_langs, i18n_lang_codes, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData
from graphics.map_scene import MapScene
from ui import theme
import storage.export_drawio as export_drawio
from storage.export_drawio import export_scene_to_drawio

DRAWIO_SRC = open(os.path.join(ROOT, "storage", "export_drawio.py"),
                  encoding="utf-8").read()


def find_cells(root):
    return {c.get("id"): c for c in root.iter("mxCell")}


def cell_by_value(cells, needle):
    return next((c for c in cells.values() if needle in (c.get("value") or "")), None)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the drawio vertex: tags + the comment ==")
# ════════════════════════════════════════════════════════════════════════════

scene = MapScene()
n_tagged = scene.add_server(ServerData(
    id="ef1", alias="web-01", host="10.0.0.11", user="ubuntu", x=700, y=80,
    os_name="Ubuntu 24.04", tags=["prod", "db"],
    comment="primary replica\nfailover: standby"))
n_plain = scene.add_server(ServerData(
    id="ef2", alias="db-01", host="10.0.0.12", user="ubuntu", x=700, y=350))
n_member = scene.add_server(ServerData(
    id="ef3", alias="cache-01", host="10.0.0.13", user="ubuntu", x=120, y=160,
    tags=["cache"]))
scene.add_connection("ef1", "ef2", label="replication", ctype="database")
note = scene.add_note("Check the backups", x=600, y=50)
group = scene.add_group("prod", x=50, y=50, width=400, height=300)
group.add_member(n_member)
# A LIVE status is set before the export: it must NEVER reach the file (§2).
n_tagged.set_status("online")
check("the live status is really on the node (the §2 check has something to catch)",
      n_tagged.status == "online", n_tagged.status)

drawio_path = os.path.join(WORK, "test_export_fidelity.drawio")
cells_n = export_scene_to_drawio(scene, drawio_path)
check("the drawio export returns the cell count", isinstance(cells_n, int) and cells_n > 0,
      f"got {cells_n!r}")

try:
    drawio_tree = ET.parse(drawio_path)   # raises ParseError on a corrupt structure
    drawio_root = drawio_tree.getroot()
    parse_error = None
except ET.ParseError as e:  # pragma: no cover — a broken export fails the NEXT checks loudly
    drawio_root, parse_error = None, str(e)
check("the label with tags+comment stays parseable by ET", parse_error is None, str(parse_error))

cells = find_cells(drawio_root) if drawio_root is not None else {}
tagged_cell = cell_by_value(cells, "web-01")
check("the web-01 vertex exists", tagged_cell is not None)
tagged_value = (tagged_cell.get("value") or "") if tagged_cell is not None else ""
lines = tagged_value.split("\n")

check("the label carries the tag line in the sidebar shape [prod, db]",
      "[prod, db]" in tagged_value, repr(tagged_value))
check("the label carries the comment's first line",
      "primary replica" in tagged_value, repr(tagged_value))
check("the label carries the comment's second line (no line is lost)",
      "failover: standby" in tagged_value, repr(tagged_value))
check("the multi-line comment became ONE line break, not a space",
      "\n" in tagged_value and "failover: standby" in lines[-1], repr(tagged_value))
check("the tag line sits after the hardware details and before the comment",
      lines.index("[prod, db]") == 3 and lines[4:] == ["primary replica", "failover: standby"],
      str(lines))
check("the alias and the host are still the first two lines",
      lines[0] == "web-01" and lines[1] == "@10.0.0.11", str(lines[:2]))

raw = open(drawio_path, encoding="utf-8").read()
check("the file carries the &#xa; entity (the drawio line-break mechanism)",
      "&#xa;" in raw)
check("the placeholder itself never reaches the file", "\x01" not in raw)

# A node WITHOUT tags/comment gains no extra line (the optional-field pattern).
plain_cell = cell_by_value(cells, "db-01")
plain_value = (plain_cell.get("value") or "") if plain_cell is not None else ""
check("a node without tags/comment: exactly alias + host",
      plain_value.split("\n") == ["db-01", "@10.0.0.12"], repr(plain_value))
check("…and no empty tag/comment line is left behind",
      "[" not in plain_value and not plain_value.endswith("\n"), repr(plain_value))
cache_cell = cell_by_value(cells, "cache-01")
cache_value = (cache_cell.get("value") or "") if cache_cell is not None else ""
check("a node with tags but no comment: the tag line is the LAST line",
      cache_value.split("\n") == ["cache-01", "@10.0.0.13", "[cache]"], repr(cache_value))

# A group MEMBER is written by the same _node_label — the tags ride along.
member_cell = next((c for c in cells.values()
                    if str(c.get("id", "")).endswith("-member-0")), None)
member_value = (member_cell.get("value") or "") if member_cell is not None else ""
check("a group member's label carries its tag line too",
      "[cache]" in member_value, repr(member_value))

# The note cell keeps its own text untouched (notes carry no tags — "Not in v1.3.3.7").
note_cell = next((c for c in cells.values() if "shape=note" in (c.get("style") or "")), None)
check("the note cell keeps its plain text",
      note_cell is not None and note_cell.get("value") == "Check the backups",
      repr(note_cell.get("value") if note_cell is not None else None))


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the source audit: no status, no tag colours ==")
# ════════════════════════════════════════════════════════════════════════════

check("the exporter never READS a server's status (a runtime fact, not project data)",
      "data.status" not in DRAWIO_SRC and 'getattr(data, "status"' not in DRAWIO_SRC,
      "a status read found in storage/export_drawio.py")
check("the module docstring spells the no-status decision out (so nobody 'fixes' it)",
      "deliberately NOT exported" in DRAWIO_SRC and "RUNTIME fact" in DRAWIO_SRC)
check("the module documents that tag COLOURS are not replicated",
      "Tag COLOURS are NOT" in DRAWIO_SRC)
check("the live status really does not reach the file (behaviour, not only the source)",
      "online" not in tagged_value, repr(tagged_value))
check("no rich-text markup rides along with the tags (the colours stay out of scope)",
      "<font" not in raw and "<span" not in raw and "<b>" not in raw)
check("the label function reads tags and the comment",
      "tags" in DRAWIO_SRC and "comment" in DRAWIO_SRC)


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the SVG export ==")
# ════════════════════════════════════════════════════════════════════════════

svg_path = os.path.join(WORK, "test_export_fidelity.svg")
# v1.5rc2: the export path is PRINT-friendly by default (a light page), so a check
# about the ACTIVE theme's canvas asks for PALETTE_THEME explicitly; the print
# default + the opt-out are pinned by tests/test_encoding.py §5.
svg_size = scene.render_to_svg(svg_path, palette=theme.PALETTE_THEME)

check("the SVG file exists", os.path.isfile(svg_path), repr(svg_path))
check("the returned size == the size on disk",
      svg_size == os.path.getsize(svg_path), f"{svg_size} vs {os.path.getsize(svg_path)}")
check("the SVG is non-trivial", svg_size > 1024, str(svg_size))

svg_text = open(svg_path, encoding="utf-8").read()
check("the file starts with the XML declaration",
      svg_text.startswith("<?xml"), repr(svg_text[:40]))
check("the <svg> root element is present",
      "<svg" in svg_text[:600], repr(svg_text[:200]))
check("the SVG is vector text, not a raster blob",
      "<text" in svg_text and "base64" not in svg_text)

check("the connection label is in the SVG", "replication" in svg_text)
node_alias_painted = n_tagged._alias.toPlainText()
check("the node's painted alias label is in the SVG",
      bool(node_alias_painted) and node_alias_painted in svg_text, repr(node_alias_painted))
check("the canvas background reached the SVG (drawBackground ran)",
      theme.CANVAS_BG.lower() in svg_text.lower(), theme.CANVAS_BG)

# The composition identity with render_to_pixmap: the same source rect -> the same area.
src = scene.itemsBoundingRect().adjusted(-60.0, -60.0, 60.0, 60.0)
_vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg_text)
check("the SVG declares a viewBox", _vb is not None, repr(svg_text[:300]))
if _vb is not None:
    check("the viewBox is itemsBoundingRect + the 60 px padding (the render_to_pixmap area)",
          (int(_vb.group(1)), int(_vb.group(2)))
          == (max(int(src.width()), 1), max(int(src.height()), 1)),
          f"{_vb.groups()} vs {int(src.width())}x{int(src.height())}")

scaled_path = os.path.join(WORK, "test_export_fidelity_scaled.svg")
scaled_size = scene.render_to_svg(scaled_path, scale=2.0, palette=theme.PALETTE_THEME)
scaled_text = open(scaled_path, encoding="utf-8").read()
_vb2 = re.search(r'viewBox="0 0 (\d+) (\d+)"', scaled_text)
check("the scale parameter doubles the declared pixel size",
      _vb2 is not None and int(_vb2.group(1)) == max(int(src.width() * 2.0), 1),
      str(_vb2.groups() if _vb2 else None))
check("the scaled export is a real file with the same return contract",
      scaled_size == os.path.getsize(scaled_path) and scaled_size > 0, str(scaled_size))

empty_path = os.path.join(WORK, "test_export_fidelity_empty.svg")
try:
    empty_size = MapScene().render_to_svg(empty_path, palette=theme.PALETTE_THEME)
    empty_error = None
except Exception as e:  # noqa: BLE001 — the acceptance requires "no exception"
    empty_size, empty_error = 0, repr(e)
check("an empty scene renders without an exception", empty_error is None, str(empty_error))
with open(empty_path, encoding="utf-8") as _f:
    _empty_text = _f.read()
check("the empty export still writes a valid SVG",
      empty_size == os.path.getsize(empty_path) and _empty_text.startswith("<?xml"),
      str(empty_size))

# The composition identity with render_to_pixmap: the SVG area is the pixmap area at scale 1.
pixmap = scene.render_to_pixmap(scale=2.0, palette=theme.PALETTE_THEME)
check("the pixmap of the same scene is non-empty (the composition baseline)",
      not pixmap.isNull() and pixmap.width() > 0)
if _vb is not None:
    check("the SVG covers the same area as render_to_pixmap(scale=2.0) / 2",
          abs(pixmap.width() - 2 * int(_vb.group(1))) <= 2
          and abs(pixmap.height() - 2 * int(_vb.group(2))) <= 2,
          f"pixmap {pixmap.width()}x{pixmap.height()} vs {_vb.groups()}")


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the File menu + the hotkey registry ==")
# ════════════════════════════════════════════════════════════════════════════

from ui.main_window import MainWindow
import ui.main_window as MW
from ui import hotkey_registry as HR

win = MainWindow()
check("MainWindow has _export_map_svg", hasattr(win, "_export_map_svg"))
i18n_keys = [key for _widget, key in win._menu_i18n]
check("file.export_svg is registered in the i18n registry (the File menu)",
      "file.export_svg" in i18n_keys)
check("the action is in the hotkey registry (assignable in Settings → Hotkeys)",
      "file.export_svg" in HR.action_ids())
check("the registry entry is an EMPTY default (no hotkey out of the box)",
      "file.export_svg" in HR.empty_default_action_ids())
targets = win._hotkey_targets.get("file.export_svg") or []
check("the action has exactly one registered target (no ambiguity)",
      len(targets) == 1, str(len(targets)))

# A real call: the dialogs are stubbed, the rest is the production path.
# v1.5rc2: the export commands ask ONE question first — the print-friendly palette or
# the current theme (`MainWindow._ask_export_palette`). This section checks the File
# menu wiring, so the question is answered here; the dialog and the palette decision
# themselves are pinned by tests/test_encoding.py §6.
ui_path = os.path.join(WORK, "test_export_fidelity_menu.svg")
_saved_dialog = MW.QFileDialog.getSaveFileName
_saved_palette = win._ask_export_palette
MW.QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (ui_path, "SVG Images (*.svg)"))
win._ask_export_palette = lambda: theme.PALETTE_THEME
try:
    win._export_map_svg()
    menu_error = None
except Exception as e:  # noqa: BLE001
    menu_error = repr(e)
finally:
    MW.QFileDialog.getSaveFileName = _saved_dialog
    win._ask_export_palette = _saved_palette
check("the File-menu handler writes the file through render_to_svg",
      menu_error is None and os.path.isfile(ui_path), str(menu_error))
check("the handler reports success in the status bar",
      win.statusBar().currentMessage() == win.t("status.export_svg_ok"),
      repr(win.statusBar().currentMessage()))
win._dirty = False
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the fate of load_drawio_structure: DELETED (ROADMAP task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

check("the helper is gone from the module",
      not hasattr(export_drawio, "load_drawio_structure")
      and "load_drawio_structure" not in dir(export_drawio))

_IMPORTER_RE = re.compile(
    r"(import\s+load_drawio_structure|import\s*\([^)]*load_drawio_structure"
    r"|\.load_drawio_structure\s*\()")
_importers = []
for _dirpath, _dirnames, _files in os.walk(ROOT):
    _dirnames[:] = [d for d in _dirnames
                    if d not in ("third_party", "__pycache__", "_tmp_testdata", ".git",
                                 "test-results")]
    for _f in _files:
        if not _f.endswith(".py"):
            continue
        _p = os.path.join(_dirpath, _f)
        try:
            _txt = open(_p, encoding="utf-8").read()
        except OSError:  # pragma: no cover
            continue
        if _IMPORTER_RE.search(_txt):
            _importers.append(os.path.relpath(_p, ROOT))
check("no file imports or calls the deleted helper any more",
      not _importers, str(_importers))
check("the decision is recorded in the source (a tombstone, not a silent removal)",
      "DELETED" in DRAWIO_SRC and "v1.3.3.7" in DRAWIO_SRC)


# ════════════════════════════════════════════════════════════════════════════
print("== §6 i18n + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

langs = load_i18n_langs(ROOT)
new_keys = ["file.export_svg", "status.export_svg_ok"]
for code in i18n_lang_codes(ROOT):
    missing = [k for k in new_keys if not str(langs[code].get(k, "")).strip()]
    check(f"i18n/{code}.json carries the 2 new keys, non-empty", not missing, str(missing))
check("the two new keys describe the same thing in en (a real translation target)",
      langs["en"]["file.export_svg"] == "Export Map as SVG..."
      and langs["en"]["status.export_svg_ok"] == "Map exported to SVG.",
      repr(langs["en"]["file.export_svg"]))
check("the drawio half added NO UI string (the exporter carries no i18n and no Qt UI)",
      "i18n" not in DRAWIO_SRC and not re.search(r"^\s*from\s+PySide6", DRAWIO_SRC, re.M))
check("the failure path of the SVG export is the shared msg.export_failed key",
      "msg.export_failed" in langs["en"])
check_i18n_parity(langs)
check_i18n_format(langs)
check_release_state(ROOT)

finish()
