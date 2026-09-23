# -*- coding: utf-8 -*-
"""v1.5rc2 — the ENCODING gate: "no meaning in a colour alone" + the print-friendly export.

The 1.5 line opened with the design review of 2026-09-27: *the interface encodes meaning
in colour alone, and never says how fresh its data is.* v1.5rc1 fixed the palette (the
LIGHT instance, the two accent roles, `tests/test_theme_contrast.py`). v1.5rc2 adds the
SECOND CHANNEL and makes an export printable:

  §1 the two DECLARED encodings — every connection type has a pen style
     (`Theme.arrow_type_styles`) and every status has a shape (`Theme.status_shapes`);
     both sets are complete, pairwise distinct and identical in DARK and LIGHT;
  §2 the DESATURATION probe — the WCAG grey separation of every type from its canvas in
     BOTH themes, plus a real greyscale RENDER measured in the middle of the arc: a
     solid line has no holes, each dash rhythm has its own hole count, and the double
     type shows two rails in every column. The measured numbers are the criterion
     ("the pattern carries the meaning where the tones are close");
  §3 the status SHAPES reach the three surfaces — the path of every shape (a filled dot /
     a ring / a triangle), the painted mark, the card's status dot (its item, its colour
     and its shape per status), the sidebar row icon;
  §4 the LEGEND becomes a real key — every row's sample comes from the declared maps
     (never a copy) and follows a theme switch;
  §5 the PRINT-FRIENDLY export — PNG/PDF/SVG/drawio render the LIGHT page by default
     from a DARK window (`PALETTE_PRINT`), `PALETTE_THEME` keeps the current look, the
     active theme and the map are restored afterwards, and the SVG stays vector;
  §6 the EXPORT DIALOG (the opt-out) + the MainWindow path — the print default, the
     remembered choice, a cancelled dialog writing nothing;
  §7 i18n (the 3 new keys × every discovered language) + the release state.

Run: python tests/test_encoding.py   (from the project root) or python tests/run_all.py
"""
import hashlib
import os
import re

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData  # noqa: E402
from graphics.map_scene import MapScene  # noqa: E402
from ui import theme, status_shape  # noqa: E402
from ui.legend import LegendWidget  # noqa: E402
from storage import export_drawio  # noqa: E402

ARROW_SRC = open(os.path.join(ROOT, "graphics", "connection_arrow.py"), encoding="utf-8").read()
LEGEND_SRC = open(os.path.join(ROOT, "ui", "legend.py"), encoding="utf-8").read()
SIDEBAR_SRC = open(os.path.join(ROOT, "ui", "sidebar.py"), encoding="utf-8").read()
SCENE_SRC = open(os.path.join(ROOT, "graphics", "map_scene.py"), encoding="utf-8").read()
DRAWIO_SRC = open(os.path.join(ROOT, "storage", "export_drawio.py"), encoding="utf-8").read()

TYPES = list(theme.DARK.arrow_type_colors)
STATUSES = list(theme.DARK.status_colors)


# ════════════════════════════════════════════════════════════════════════════
# §1 The two declared encodings — complete, distinct, theme-independent
# ════════════════════════════════════════════════════════════════════════════
print("== §1 the declared encodings (the pen styles + the status shapes) ==")

_styles = theme.DARK.arrow_type_styles
_shapes = theme.DARK.status_shapes

check("§1 every connection type carries a DECLARED pen style",
      set(_styles) == set(TYPES) and len(_styles) == 6, str(sorted(_styles)))
check("§1 ...and the reverse: no style exists for a type the palette does not know",
      set(_styles) <= set(TYPES), str(sorted(set(_styles) - set(TYPES))))
check("§1 the three statuses carry a declared shape and nothing else does",
      set(_shapes) == set(STATUSES) and len(_shapes) == 3, str(_shapes))
check("§1 the shapes come from the pinned set (a filled dot / a ring / a triangle)",
      set(_shapes.values()) == set(theme.STATUS_SHAPE_IDS),
      str(sorted(set(_shapes.values()))))
check("§1 all three shapes are DIFFERENT (a status is never two marks at once)",
      len(set(_shapes.values())) == 3, str(_shapes))

# The pen styles are pairwise distinct — the whole point of the second channel. The
# comparison is the FULL tuple (dash, width, double): two types may share a width,
# they may not share their ink.
_style_keys = {ctype: (tuple(style.dash), float(style.width), bool(style.double))
               for ctype, style in _styles.items()}
_pairs = [(a, b) for i, a in enumerate(TYPES) for b in TYPES[i + 1:]]
check("§1 the six pen styles are PAIRWISE distinct (dash + width + double)",
      all(_style_keys[a] != _style_keys[b] for a, b in _pairs),
      str({k: v for k, v in _style_keys.items()
           if list(_style_keys.values()).count(v) > 1}))
check("§1 exactly ONE type is drawn as a double line",
      sum(1 for st in _styles.values() if st.double) == 1,
      str([c for c, st in _styles.items() if st.double]))
check("§1 the default type is a plain solid line (the v0.7 look is untouched)",
      _styles["ssh"].is_solid() and _styles["ssh"].width == 2.2, str(_styles["ssh"]))
check("§1 a dash pattern is a real rhythm (positive, and the pattern is not all-on)",
      all(all(float(v) > 0 for v in st.dash) for st in _styles.values())
      and all(len(st.dash) >= 2 for st in _styles.values() if st.dash),
      str({c: st.dash for c, st in _styles.items()}))

# The encodings belong to the ACTIVE theme like every other datum of §4.6 — and they
# are geometry, so the two instances declare the SAME map (an export may not change a
# dash pattern).
check("§1 the two instances declare the same styles and shapes (geometry, not a colour)",
      theme.LIGHT.arrow_type_styles == theme.DARK.arrow_type_styles
      and theme.LIGHT.status_shapes == theme.DARK.status_shapes)
check("§1 the declarations are DERIVED properties (a second copy cannot drift)",
      isinstance(theme.Theme.arrow_type_styles, property)
      and isinstance(theme.Theme.status_shapes, property))
_fresh = theme.DARK.arrow_type_styles
_fresh["ssh"] = "mutated"
check("§1 a consumer cannot mutate the declaration through the property (a fresh dict)",
      theme.DARK.arrow_type_styles["ssh"] is _styles["ssh"],
      str(theme.DARK.arrow_type_styles.get("ssh")))
check("§1 the module proxies resolve them live (ARROW_TYPE_STYLES / STATUS_SHAPES)",
      theme.ARROW_TYPE_STYLES == _styles and theme.STATUS_SHAPES == _shapes
      and "ARROW_TYPE_STYLES" in dir(theme))
check("§1 an unknown type / status falls back to the default mark, never to a crash",
      theme.arrow_type_style("nope") is theme.arrow_type_style("ssh")
      and theme.status_shape("nope") == theme.STATUS_SHAPE_DOT
      and theme.status_shape("") == theme.STATUS_SHAPE_DOT)

# The source audit: the pen of an arrow is BUILT from the declaration, never from a
# literal that could drift from it (the v1.2.5 "no raw palette literal" rule).
check("§1 the arrow reads its stroke from the declared style (one setDashPattern call)",
      ARROW_SRC.count("setDashPattern") == 1 and "style.dash" in ARROW_SRC
      and "ARROW_HOVER_WIDTH_DELTA" in ARROW_SRC,
      str(ARROW_SRC.count("setDashPattern")))
check("§1 the v1.4.x hardcoded widths are gone from the hover/rest pair",
      "width = 2.4" not in ARROW_SRC and "width = 1.8" not in ARROW_SRC)
check("§1 the legend samples the declared maps (no dash literal in the panel)",
      "row_sample" in LEGEND_SRC and "setDashPattern" in LEGEND_SRC
      and "(7.0, 4.0)" not in LEGEND_SRC and "dash=(9" not in LEGEND_SRC)
check("§1 the sidebar asks the shared shape painter for its row marker",
      "status_shape.shape_icon" in SIDEBAR_SRC, "sidebar does not call status_shape.shape_icon")


# ════════════════════════════════════════════════════════════════════════════
# §2 The desaturation probe — greyscale arithmetic + a real render
# ════════════════════════════════════════════════════════════════════════════
print("== §2 the desaturation probe (the criterion, then the measurement) ==")


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


# THE CRITERION (pinned here, measured below):
#   * every type keeps at least GREY_INK_MIN of relative luminance away from its canvas
#     — a type may not vanish in greyscale;
#   * two types whose tones are closer than GREY_PAIR_MIN are told apart by the PATTERN
#     — that is exactly what "no meaning in a colour alone" means;
#   * and the pattern is not decoration: at least one pair really needs it.
GREY_INK_MIN = 0.20
GREY_PAIR_MIN = 0.05

check("§2 the criterion is anchored in the real WCAG arithmetic (21:1 and 1:1 are exact)",
      abs((relative_luminance("#ffffff") + 0.05) / (relative_luminance("#000000") + 0.05)
          - 21.0) < 1e-6
      and relative_luminance("#38bdf8") == relative_luminance("#38bdf8"))

_ink_sep = {}
_similar_pairs = []
for _instance, _name in ((theme.DARK, "DARK"), (theme.LIGHT, "LIGHT")):
    _canvas = relative_luminance(_instance.canvas_bg)
    for _ctype, _color in _instance.arrow_type_colors.items():
        _sep = abs(relative_luminance(_color) - _canvas)
        _ink_sep[(_name, _ctype)] = round(_sep, 4)
        check(f"§2 {_name}: the {_ctype} stroke keeps its greyscale separation from the canvas "
              f"(>= {GREY_INK_MIN})", _sep >= GREY_INK_MIN, f"{_sep:.4f}")
    for _i, _a in enumerate(TYPES):
        for _b in TYPES[_i + 1:]:
            _da = abs(relative_luminance(_instance.arrow_type_colors[_a])
                      - relative_luminance(_instance.arrow_type_colors[_b]))
            if _da < GREY_PAIR_MIN and _name == "LIGHT":
                _similar_pairs.append((_a, _b, round(_da, 4)))
check(f"§2 LIGHT: {len(_similar_pairs)} of the 15 tone pairs are within {GREY_PAIR_MIN} of each "
      f"other in greyscale — the pattern is not decoration",
      len(_similar_pairs) >= 5, str(_similar_pairs))
check("§2 ...and every one of those pairs IS separated by the declared pen style",
      all(_style_keys[_a] != _style_keys[_b] for _a, _b, _d in _similar_pairs),
      str([(a, b) for a, b, _d in _similar_pairs if _style_keys[a] == _style_keys[b]]))
print("    the measured greyscale separations:", _ink_sep)


def grey_map(ctype=None, scale: float = 1.0, padding: float = 0.0,
             palette=theme.PALETTE_PRINT):
    """Render a two-node map (optionally with ONE typed arrow) as a greyscale image.

    Returns ``(image, source_rect)`` — `source_rect` is the scene rectangle the image
    covers, so a check can address a SCENE point (the middle of the arc) instead of a
    pixel that moves with the card size. Rendering goes through the production path
    (`render_to_pixmap`), i.e. through the export palette of §5.
    """
    scene = MapScene()
    scene.add_server(ServerData(id="enc-a", alias="AA", host="10.0.0.1", user="root",
                                x=0.0, y=0.0))
    scene.add_server(ServerData(id="enc-b", alias="BB", host="10.0.0.2", user="root",
                                x=420.0, y=0.0))
    if ctype is not None:
        scene.add_connection("enc-a", "enc-b", "", ctype)
    src = scene.itemsBoundingRect()
    image = scene.render_to_pixmap(scale=scale, padding=padding).toImage().convertToFormat(
        QImage.Format.Format_Grayscale8)
    return image, src


def _canvas_grey(image) -> int:
    """The grey value of the CANVAS in a rendered map (the corner, away from the grid)."""
    return image.pixelColor(2, 2).red()


# The window in SCENE coordinates that sees the middle of the arc: far from both cards
# (the arrow tips) and from the label plaque, i.e. the pure stroke.
WINDOW_X0, WINDOW_X1 = 230.0, 370.0
INK_DROP = 40          # the pixels of the printed page that count as "ink" (grid = 241/250)


def _window_profile(image, src, threshold=INK_DROP):
    """The per-column number of ink runs inside the middle-of-the-arc window.

    Returns ``(runs, holes)``: ``runs[x]`` is how many separate ink runs the column `x`
    has (a double rail shows TWO), ``holes`` counts the columns with no ink at all (a
    dash rhythm shows holes, a solid line does not).
    """
    canvas = _canvas_grey(image)
    x0, x1 = int(WINDOW_X0 - src.left()), int(WINDOW_X1 - src.left())
    runs = []
    for x in range(max(x0, 0), min(x1, image.width())):
        count, prev = 0, False
        for y in range(image.height()):
            inked = image.pixelColor(x, y).red() < canvas - threshold
            if inked and not prev:
                count += 1
            prev = inked
        runs.append(count)
    return runs, sum(1 for r in runs if r == 0)


_profiles = {}
for _ctype in TYPES:
    _img, _src = grey_map(_ctype)
    _runs, _holes = _window_profile(_img, _src)
    _profiles[_ctype] = {"ink": sum(_runs), "holes": _holes,
                         "double_columns": sum(1 for r in _runs if r >= 2),
                         "columns": len(_runs)}
    check(f"§2 the {_ctype} stroke survives the DESATURATION (ink pixels in a greyscale render)",
          _profiles[_ctype]["ink"] > 0, str(_profiles[_ctype]))

check("§2 the solid type shows an UNBROKEN greyscale line (no hole in the window)",
      _profiles["ssh"]["holes"] == 0, str(_profiles["ssh"]))
_dashed = {c: _profiles[c]["holes"] for c in TYPES if theme.arrow_type_style(c).dash}
check("§2 every dashed type really breaks its line in greyscale (the pattern reached the paint)",
      all(h > 0 for h in _dashed.values()), str(_dashed))
check("§2 ...and the three dash rhythms give three DIFFERENT hole counts (they are readable apart)",
      len(set(_dashed.values())) == len(_dashed), str(_dashed))
check("§2 the DOUBLE type shows two rails in every column (the casing really splits the stroke)",
      _profiles["nfs"]["double_columns"] == _profiles["nfs"]["columns"]
      and _profiles["nfs"]["double_columns"] > 0, str(_profiles["nfs"]))
check("§2 ...while no single-stroke type does (the channels are exclusive)",
      all(_profiles[c]["double_columns"] == 0 for c in TYPES
          if c != "nfs"),
      str({c: _profiles[c]["double_columns"] for c in TYPES}))
_signatures = {c: (_profiles[c]["holes"], _profiles[c]["double_columns"]) for c in TYPES}
check("§2 the six types are pairwise DISTINCT in a greyscale render (the acceptance probe)",
      len(set(_signatures.values())) == 6, str(_signatures))
check("§2 the render is deterministic (the same probe twice gives the same numbers)",
      _window_profile(*grey_map("database"))[1] == _profiles["database"]["holes"])


# ════════════════════════════════════════════════════════════════════════════
# §3 The status shapes reach the three surfaces
# ════════════════════════════════════════════════════════════════════════════
print("== §3 the status shapes (the path, the paint, the card, the sidebar) ==")

_paths = {status: status_shape.shape_path(status, 14.0) for status in STATUSES}
check("§3 every status has its own path (three marks, three geometries)",
      len({_paths[s].elementCount() for s in STATUSES}) >= 2
      and all(not _paths[s].isEmpty() for s in STATUSES),
      str({s: _paths[s].elementCount() for s in STATUSES}))
check("§3 the paths differ in their element count (an annulus needs two ellipses)",
      _paths["online"].elementCount() != _paths["warn"].elementCount()
      and _paths["online"].elementCount() != _paths["offline"].elementCount(),
      str({s: _paths[s].elementCount() for s in STATUSES}))
check("§3 the DOT shape is a closed one-contour path",
      _paths["online"].elementCount() == 13, str(_paths["online"].elementCount()))

# The structural probe: which of the four probe points of the box each mark covers.
#   dot      → centre + top + left + bottom
#   ring     → everything BUT the centre (the hole is the point of a ring)
#   triangle → the centre and the bottom, not the left corner
_probe_points = {"centre": QPointF(7.0, 7.0), "top": QPointF(7.0, 3.0),
                 "left": QPointF(2.0, 7.0), "bottom": QPointF(7.0, 12.0)}
_coverage = {status: {name: _paths[status].contains(point)
                      for name, point in _probe_points.items()} for status in STATUSES}
check("§3 the ring has a HOLE in the centre (that is what makes it a ring)",
      _coverage["warn"]["centre"] is False
      and all(_coverage["warn"][k] for k in ("top", "left", "bottom")), str(_coverage["warn"]))
check("§3 the dot is FILLED in the centre (and in all four probes)",
      all(_coverage["online"].values()), str(_coverage["online"]))
check("§3 the triangle is pointed: the corner of its box is empty",
      _coverage["offline"]["left"] is False and _coverage["offline"]["bottom"] is True,
      str(_coverage["offline"]))
check("§3 the three coverage signatures are pairwise distinct",
      len({tuple(sorted(v.items())) for v in _coverage.values()}) == 3, str(_coverage))


def _fill_fraction(path, size: float = 14.0, n: int = 28) -> float:
    """The share of a size×size box the path fills (a sampling grid, no rasterizer)."""
    hits = sum(1 for i in range(n) for j in range(n)
               if path.contains(QPointF(size * (i + 0.5) / n, size * (j + 0.5) / n)))
    return hits / float(n * n)


_fills = {status: round(_fill_fraction(_paths[status]), 3) for status in STATUSES}
check("§3 the marks are ordered by their ink: dot > ring > triangle",
      _fills["online"] > _fills["warn"] > _fills["offline"],
      str(_fills))
check("§3 a ring costs visibly less ink than a dot (the hole is measurable)",
      _fills["online"] - _fills["warn"] > 0.05, str(_fills))


def _painted_mark(status):
    """Paint one mark through `status_shape.paint_shape` and return its image + ink count."""
    image = QImage(24, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    status_shape.paint_shape(painter, QRectF(4.0, 4.0, 16.0, 16.0), status, "#22c55e")
    painter.end()
    ink = sum(1 for x in range(image.width()) for y in range(image.height())
              if image.pixelColor(x, y).alpha() > 0)
    return image, ink


_marks = {status: _painted_mark(status) for status in STATUSES}
check("§3 all three marks really paint (none is an empty path)",
      all(ink > 0 for _img, ink in _marks.values()),
      str({s: ink for s, (_i, ink) in _marks.items()}))
check("§3 the ring paints its hole (the centre pixel stays transparent)",
      _marks["warn"][0].pixelColor(12, 12).alpha() == 0
      and _marks["online"][0].pixelColor(12, 12).alpha() > 0,
      f"ring={_marks['warn'][0].pixelColor(12, 12).alpha()} "
      f"dot={_marks['online'][0].pixelColor(12, 12).alpha()}")

# The CARD: the status dot is a shaped item whose brush keeps the status colour.
scene = MapScene()
node = scene.add_server(ServerData(id="enc-node", alias="web-01", host="10.0.0.9",
                                   user="root", x=0.0, y=0.0))
check("§3 the card's status dot is a PATH item now (a shape needs a path, not an ellipse)",
      node._status_dot.__class__.__name__ == "QGraphicsPathItem",
      node._status_dot.__class__.__name__)
_idle_path = node._status_dot.path().elementCount()
check("§3 an unchecked status keeps the plain dot (the v1.4.x look) and the idle grey",
      node._status_dot.path().contains(QPointF(7.0, 7.0 + 23.0))
      and node._status_dot.brush().color().name() == theme.DOT_IDLE,
      f"{node._status_dot.brush().color().name()} / {_idle_path}")
_card_paths = {}
for _status in STATUSES:
    node.set_status(_status)
    _card_paths[_status] = (node._status_dot.path().elementCount(),
                            node._status_dot.brush().color().name())
    check(f"§3 the card draws the declared mark of '{_status}'",
          node._status_dot.path().contains(QPointF(7.0, 7.0 + 23.0))
          == (theme.status_shape(_status) != theme.STATUS_SHAPE_RING)
          and _card_paths[_status][1] == theme.STATUS_COLORS[_status],
          f"{_card_paths[_status]} shape={theme.status_shape(_status)}")
check("§3 the three card marks are structurally different (not the same dot recoloured)",
      len({v[0] for v in _card_paths.values()}) == 3, str(_card_paths))
node.reset_status()
check("§3 a reset returns the card to the idle dot (state, never a stale shape)",
      node._status_dot.path().contains(QPointF(7.0, 7.0 + 23.0))
      and node._status_dot.brush().color().name() == theme.DOT_IDLE,
      node._status_dot.brush().color().name())

# The SIDEBAR: the row marker is drawn by the same module and differs per status.
from ui.sidebar import SidebarPanel, CONTEXT_MENU_ITEMS  # noqa: E402

_panel = SidebarPanel(actions={entry[0]: (lambda *_a: None)
                               for entry in CONTEXT_MENU_ITEMS if entry is not None})
_icons = {status: _panel._status_dot_icon(status) for status in STATUSES}
_digests = {status: hashlib.sha256(_icons[status].pixmap(16, 16).toImage().bits().tobytes())
            .hexdigest()[:12] for status in STATUSES}
check("§3 the sidebar marker differs per status (three distinct pixmaps)",
      len(set(_digests.values())) == 3, str(_digests))
_marker_ink = {}
for _status in STATUSES:
    _img = _icons[_status].pixmap(16, 16).toImage()
    _marker_ink[_status] = sum(1 for x in range(_img.width()) for y in range(_img.height())
                              if _img.pixelColor(x, y).alpha() > 0)
check("§3 the sidebar ring keeps its hole (the centre of the ring icon is transparent)",
      _icons["warn"].pixmap(16, 16).toImage().pixelColor(8, 8).alpha() == 0
      and _icons["online"].pixmap(16, 16).toImage().pixelColor(8, 8).alpha() > 0,
      str(_marker_ink))
check("§3 a theme switch drops the baked marker cache (the colour follows the theme)",
      "self._status_dot_icons.clear()" in SIDEBAR_SRC)
check("§3 the card and the sidebar ask the SAME declaration",
      "status_shape.shape_path" in open(os.path.join(ROOT, "graphics", "server_node.py"),
                                        encoding="utf-8").read())


# ════════════════════════════════════════════════════════════════════════════
# §4 The legend becomes a real key
# ════════════════════════════════════════════════════════════════════════════
print("== §4 the legend samples (read from the declared maps, never a copy) ==")

from PySide6.QtWidgets import QGraphicsView  # noqa: E402

_scene = MapScene()          # the view does NOT own the scene — keep the reference alive
_view = QGraphicsView(_scene)
legend = LegendWidget(_view, parent=_view)
_rows = legend.rows()
check("§4 the panel still lists the six types + the three statuses + two captions (3-tuples)",
      len(_rows) == 11 and all(len(row) == 3 for row in _rows), str(len(_rows)))

_samples = {}
for _kind, _key, _color in _rows:
    _sample = legend.row_sample(_kind, _key, _color)
    if _kind == "section":
        check("§4 a section caption has no sample", _sample is None, str(_sample))
        continue
    _samples[_key] = _sample
    check(f"§4 the row '{_key}' carries a sample", isinstance(_sample, dict), str(_sample))
    check(f"§4 ...in the row's own colour (never a second lookup)",
          _sample is not None and _sample.get("color") == _color, str(_sample))

_type_samples = {k: v for k, v in _samples.items() if k.startswith("connection.type.")}
check("§4 every type row samples the DECLARED style (the same object the map paints)",
      all(v["style"] == theme.arrow_type_style(k.split("connection.type.")[1])
          for k, v in _type_samples.items()),
      str(sorted(_type_samples)))
check("§4 the samples cover all six types and the three statuses",
      len(_type_samples) == 6
      and len([k for k in _samples if k.startswith("legend.status.")]) == 3,
      str(sorted(_samples)))
_status_samples = {k: v for k, v in _samples.items() if k.startswith("legend.status.")}
check("§4 every status row samples the DECLARED shape",
      all(v["shape"] == theme.status_shape(k.split("legend.status.")[1])
          for k, v in _status_samples.items()),
      str(sorted((k, v["shape"]) for k, v in _status_samples.items())))
check("§4 the two sample KINDS are distinct (a line vs a shape)",
      {v["kind"] for v in _samples.values()} == {"line", "shape"},
      str(sorted({v["kind"] for v in _samples.values()})))
check("§4 an unknown row answers None instead of inventing a sample",
      legend.row_sample("item", "nope.key", "#ffffff") is None
      and legend.row_sample("section", "legend.title", None) is None)

_legend_pixmap = legend.grab()
check("§4 the panel paints the samples (a non-empty render with the declared tones)",
      not _legend_pixmap.isNull() and _legend_pixmap.width() == LegendWidget.WIDTH,
      f"{_legend_pixmap.width()}x{_legend_pixmap.height()}")
_legend_image = _legend_pixmap.toImage()
_legend_colours = {_legend_image.pixelColor(x, y).name()
                   for y in range(_legend_image.height())
                   for x in range(legend.PADDING, legend.PADDING + legend.SAMPLE_W)}
check("§4 the painted panel carries the DARK type tones (the sample is really drawn)",
      sum(1 for c in theme.DARK.arrow_type_colors.values() if c in _legend_colours) >= 4,
      str(sorted(_legend_colours)))
_saved_theme = theme.current_theme()
try:
    theme.set_theme(theme.LIGHT)
    _light_rows = {k: (c, legend.row_sample("item", k, c))
                   for _kd, k, c in legend.rows() if _kd == "item"}
    check("§4 the rows AND the samples follow a THEME switch (values of the active theme)",
          _light_rows["connection.type.ssh"][0] == theme.LIGHT.arrow_type_colors["ssh"]
          and _light_rows["legend.status.online"][0] == theme.LIGHT.status_colors["online"]
          and _light_rows["connection.type.vpn"][1]["style"]
          == theme.arrow_type_style("vpn")
          and _light_rows["legend.status.offline"][1]["shape"] == theme.STATUS_SHAPE_TRIANGLE,
          str({k: v[0] for k, v in _light_rows.items()}))
finally:
    theme.set_theme(_saved_theme)
check("§4 the panel is still a WIDGET over the scene, never a scene item",
      legend.parentWidget() is _view and not any(i is legend for i in _view.scene().items()))


# ════════════════════════════════════════════════════════════════════════════
# §5 The print-friendly export (ROADMAP task 3)
# ════════════════════════════════════════════════════════════════════════════
print("== §5 the print-friendly export (PNG / SVG / PDF / drawio) ==")

theme.set_theme(theme.DARK)
check("§5 the print palette is the LIGHT instance (with the user's hue), 'theme' is the active one",
      theme.export_theme(theme.PALETTE_PRINT) is theme.LIGHT
      and theme.export_theme(theme.PALETTE_THEME) is theme.DARK
      and theme.resolve_export_palette("nonsense") == theme.PALETTE_PRINT
      and theme.resolve_export_palette(None) == theme.PALETTE_PRINT,
      theme.resolve_export_palette("nonsense"))


def _dominant(image):
    """The most frequent colour of an image (sampled 4 px apart)."""
    counts = {}
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            name = image.pixelColor(x, y).name()
            counts[name] = counts.get(name, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])


_probe_scene = MapScene()
_probe_scene.add_server(ServerData(id="print-a", alias="web-01", host="10.0.0.1",
                                   user="root", x=0.0, y=0.0, tags=["prod"]))
_probe_scene.add_server(ServerData(id="print-b", alias="db-01", host="10.0.0.2",
                                   user="root", x=420.0, y=0.0))
_arrow = _probe_scene.add_connection("print-a", "print-b", "replication", "database")

print_image = _probe_scene.render_to_pixmap(scale=1.0, padding=120.0).toImage()
_print_dominant = _dominant(print_image)
check("§5 a PNG export of a DARK window is dominated by the LIGHT canvas (a printable page)",
      _print_dominant[0] == theme.LIGHT.canvas_bg and _print_dominant[0] != theme.DARK.canvas_bg,
      f"{_print_dominant} vs {theme.LIGHT.canvas_bg}")
theme_image = _probe_scene.render_to_pixmap(scale=1.0, padding=120.0,
                                            palette=theme.PALETTE_THEME).toImage()
check("§5 ...and the opt-out keeps the DARK canvas (the current look is available)",
      _dominant(theme_image)[0] == theme.DARK.canvas_bg, str(_dominant(theme_image)))
check("§5 the active theme is RESTORED after both renders (no palette leaks into the window)",
      theme.current_theme() is theme.DARK and theme.RENDER_BG == theme.DARK.render_bg)
check("§5 ...and the map itself is back to the dark tones (the items were re-read)",
      _arrow.pen().color().name() == theme.DARK.arrow_type_colors["database"]
      and _arrow.pen().dashPattern() == list(theme.arrow_type_style("database").dash),
      f"{_arrow.pen().color().name()} {_arrow.pen().dashPattern()}")
check("§5 the default of every render method IS the print palette (the pinned decision)",
      SCENE_SRC.count("palette=theme.PALETTE_PRINT") >= 4
      and "use_view_rect=None,\n                         palette=theme.PALETTE_PRINT" in SCENE_SRC,
      str(SCENE_SRC.count("palette=theme.PALETTE_PRINT")))
check("§5 the scene swaps the theme through ONE scoped context manager",
      "def export_palette" in SCENE_SRC and "contextmanager" in SCENE_SRC
      and "theme.set_theme(previous)" in SCENE_SRC)

svg_print = os.path.join(WORK, "encoding_print.svg")
svg_theme = os.path.join(WORK, "encoding_theme.svg")
_size_print = _probe_scene.render_to_svg(svg_print)
_size_theme = _probe_scene.render_to_svg(svg_theme, palette=theme.PALETTE_THEME)
_text_print = open(svg_print, encoding="utf-8").read()
_text_theme = open(svg_theme, encoding="utf-8").read()
check("§5 the SVG export writes a file through both palettes",
      _size_print == os.path.getsize(svg_print) and _size_theme == os.path.getsize(svg_theme)
      and _size_print > 512, f"{_size_print} / {_size_theme}")
check("§5 the default SVG carries the LIGHT page, the opt-out the DARK one",
      theme.LIGHT.canvas_bg in _text_print and theme.DARK.canvas_bg not in _text_print
      and theme.DARK.canvas_bg in _text_theme,
      f"print={theme.LIGHT.canvas_bg in _text_print} theme={theme.DARK.canvas_bg in _text_theme}")
check("§5 the vector contract holds in both (v1.4.2: no pixmap halo in an SVG)",
      "base64" not in _text_print and "base64" not in _text_theme
      and "<text" in _text_print and "<text" in _text_theme)

pdf_print = os.path.join(WORK, "encoding_print.pdf")
_pdf_theme = os.path.join(WORK, "encoding_theme.pdf")
_size_pdf = _probe_scene.render_to_pdf(pdf_print)
_probe_scene.render_to_pdf(_pdf_theme, palette=theme.PALETTE_THEME)
with open(pdf_print, "rb") as _f:
    _head_pdf = _f.read(5)
check("§5 the PDF export is a real file (%PDF header + a size beyond a header-only file)",
      _head_pdf == b"%PDF-" and _size_pdf > 4096, f"{_head_pdf!r} {_size_pdf}")


def _pdf_page_probe(path, render_px=400):
    """Render page 0 back and answer (dominant hex, its grey, the mean grey, its share).

    The PDF device round-trips a colour through its own colour space, so the check is
    about the TONE (a near-white surface), not about a byte-equal hex — the byte pin
    lives on the pixmap probe above, where Qt is the only renderer.
    """
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtPdf import QPdfDocument
    except ImportError:  # pragma: no cover — QtPdf ships with the standard wheel
        return None
    doc = QPdfDocument()
    doc.load(path)
    if doc.pageCount() < 1:
        doc.close()
        return None
    size = doc.pagePointSize(0)
    target = QSize(render_px, max(int(render_px * size.height() / max(size.width(), 1.0)), 1))
    image = doc.render(0, target)
    doc.close()
    if image.isNull():  # pragma: no cover
        return None
    counts = {}
    total = 0
    grey_sum = 0
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            colour = image.pixelColor(x, y)
            name = colour.name()
            grey = (colour.red() + colour.green() + colour.blue()) // 3
            counts[name] = counts.get(name, 0) + 1
            grey_sum += grey
            total += 1
    dominant = max(counts.items(), key=lambda kv: kv[1])
    dominant_grey = (int(dominant[0][1:3], 16) + int(dominant[0][3:5], 16)
                     + int(dominant[0][5:7], 16)) // 3
    return dominant[0], dominant_grey, round(grey_sum / max(total, 1), 1), \
        dominant[1] / max(total, 1)


_pdf_probe = _pdf_page_probe(pdf_print)
if _pdf_probe is None:  # pragma: no cover
    check("§5 the PDF page could not be rendered back (QtPdf missing) — the pixmap probe carries it",
          True, "")
else:
    check("§5 the printed page is LIGHT (the dominant sheet tone is a near-white surface)",
          _pdf_probe[1] >= 240 and _pdf_probe[2] > 200, str(_pdf_probe))
    check("§5 the light page really dominates the sheet (not a corner thumbnail)",
          _pdf_probe[3] > 0.35, str(_pdf_probe))

_drawio_print = os.path.join(WORK, "encoding_print.drawio")
_drawio_theme = os.path.join(WORK, "encoding_theme.drawio")
export_drawio.export_scene_to_drawio(_probe_scene, _drawio_print)
export_drawio.export_scene_to_drawio(_probe_scene, _drawio_theme, palette=theme.PALETTE_THEME)
_drawio_print_text = open(_drawio_print, encoding="utf-8").read()
_drawio_theme_text = open(_drawio_theme, encoding="utf-8").read()
check("§5 the .drawio export carries the SAME palette decision (a light card, the strong outline)",
      f"fillColor={theme.LIGHT.node_bg}" in _drawio_print_text
      and f"strokeColor={theme.LIGHT.accent_strong}" in _drawio_print_text
      and f"fillColor={export_drawio.NODE_FILL}" not in _drawio_print_text,
      theme.LIGHT.accent_strong)
check("§5 ...while the opt-out writes the dark format palette (the pre-v1.5rc2 bytes)",
      f"fillColor={export_drawio.NODE_FILL}" in _drawio_theme_text
      and theme.DARK.arrow_type_colors["database"] in _drawio_theme_text,
      export_drawio.NODE_FILL)
check("§5 every edge in the file carries the DECLARED dash pattern (the second channel)",
      "dashed=1;dashPattern=9 3 1.5 3;" in _drawio_print_text
      and f"strokeWidth={theme.arrow_type_style('database').width:g}" in _drawio_print_text,
      "no dash pattern in the drawio edges")
check("§5 the .drawio palette has ONE source (the theme), not a second colour table",
      "theme.export_theme" in DRAWIO_SRC and "theme.arrow_type_style" in DRAWIO_SRC
      and "def edge_dash_attributes" in DRAWIO_SRC)
check("§5 the drawio module stays Qt-free and carries no UI text (the v1.3.3.7 contract)",
      not re.search(r"^\s*from\s+PySide6", DRAWIO_SRC, re.M) and "i18n" not in DRAWIO_SRC)


# ════════════════════════════════════════════════════════════════════════════
# §6 The export dialog (the opt-out) + the MainWindow path
# ════════════════════════════════════════════════════════════════════════════
print("== §6 the export dialog and the window path ==")

from dialogs.export_options_dialog import ExportOptionsDialog  # noqa: E402
from i18n import t as _t  # noqa: E402

_dialog = ExportOptionsDialog()
check("§6 the dialog defaults to the PRINT-FRIENDLY palette (the pinned default)",
      _dialog.use_current_theme() is False
      and _dialog.chosen_palette() == theme.PALETTE_PRINT, _dialog.chosen_palette())
check("§6 the dialog is titled and worded by the i18n keys of §7",
      _dialog.windowTitle() == _t("dialog.export_options")
      and _dialog.chk_current_theme.text() == _t("export.use_current_theme"),
      f"{_dialog.windowTitle()!r} / {_dialog.chk_current_theme.text()!r}")
_dialog.chk_current_theme.setChecked(True)
check("§6 the checkbox is the opt-out (checked → the CURRENT theme)",
      _dialog.use_current_theme() is True
      and _dialog.chosen_palette() == theme.PALETTE_THEME, _dialog.chosen_palette())
_dialog2 = ExportOptionsDialog(use_current_theme=True)
check("§6 the dialog can open with the choice of the previous export",
      _dialog2.use_current_theme() is True and _dialog2.chosen_palette() == theme.PALETTE_THEME)
check("§6 the hint names the print palette (the user is told what the default does)",
      "print" in _t("export.palette_hint").lower()
      and _dialog.findChild(type(_dialog.chk_current_theme)) is not None)

from ui.main_window import MainWindow  # noqa: E402
import ui.main_window as MW  # noqa: E402

win = MainWindow()
check("§6 the window starts on the print-friendly default (an in-memory choice)",
      win._export_use_current_theme is False)
check("§6 the window exposes the ONE palette question (the four exports share it)",
      hasattr(win, "_ask_export_palette")
      and MW.ExportOptionsDialog is ExportOptionsDialog)


class _FakeExportDialog:
    """The test seam of the dialog (the `QFileDialog` pattern): answers a fixed choice."""

    accept = True

    def __init__(self, parent=None, use_current_theme=False):
        self._use = bool(use_current_theme)
        self.seen_flag = use_current_theme

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.DialogCode.Accepted if _FakeExportDialog.accept else QDialog.DialogCode.Rejected

    def use_current_theme(self):
        return self._use

    def chosen_palette(self):
        return theme.PALETTE_THEME if self._use else theme.PALETTE_PRINT


_saved_dialog_cls = MW.ExportOptionsDialog
_saved_save_name = MW.QFileDialog.getSaveFileName
MW.ExportOptionsDialog = _FakeExportDialog
try:
    _png_path = os.path.join(WORK, "encoding_window.png")
    MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_png_path, ""))
    check("§6 the window's palette question answers the print default",
          win._ask_export_palette() == theme.PALETTE_PRINT
          and win._export_use_current_theme is False)
    win.scene.add_server(ServerData(id="win-a", alias="w1", host="10.9.0.1", user="root",
                                    x=0.0, y=0.0))
    win._export_map_image()
    check("§6 the PNG written by the window handler is a LIGHT page (the default path)",
          os.path.isfile(_png_path) and os.path.getsize(_png_path) > 0)
    _win_image = QImage(_png_path)
    check("§6 ...and its dominant colour is the LIGHT canvas of the print palette",
          not _win_image.isNull() and _dominant(_win_image)[0] == theme.LIGHT.canvas_bg,
          str(_dominant(_win_image)) if not _win_image.isNull() else "no image")
    check("§6 the handler reported success in the status bar",
          win.statusBar().currentMessage() == win.t("status.export_ok"),
          repr(win.statusBar().currentMessage()))

    # The remembered choice: the next dialog opens with it, and the render follows it.
    _theme_png = os.path.join(WORK, "encoding_window_theme.png")
    _FakeExportDialog.accept = True
    _saved_choice = _FakeExportDialog.__init__

    def _remembering_init(self, parent=None, use_current_theme=False):
        _saved_choice(self, parent, use_current_theme)
        self._use = True          # the user ticks "use the current theme" this time

    _FakeExportDialog.__init__ = _remembering_init
    MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_theme_png, ""))
    win._export_map_image()
    _FakeExportDialog.__init__ = _saved_choice
    _theme_image = QImage(_theme_png)
    check("§6 the opt-out really switches the export to the DARK canvas",
          not _theme_image.isNull() and _dominant(_theme_image)[0] == theme.DARK.canvas_bg,
          str(_dominant(_theme_image)) if not _theme_image.isNull() else "no image")
    check("§6 ...and the choice is remembered for the next export of the session",
          win._export_use_current_theme is True)
    check("§6 the remembered choice is NOT persisted (the hub keeps its 22 keys)",
          "export" not in {k for k in __import__("i18n").load_config()})

    # A cancelled dialog writes nothing.
    _cancelled_path = os.path.join(WORK, "encoding_window_cancelled.png")
    _FakeExportDialog.accept = False
    MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_cancelled_path, ""))
    win._export_map_image()
    check("§6 a cancelled options dialog writes NO file (the export is really aborted)",
          not os.path.isfile(_cancelled_path))
    check("§6 a cancelled dialog does not change the remembered choice",
          win._export_use_current_theme is True)
finally:
    _FakeExportDialog.accept = True
    MW.ExportOptionsDialog = _saved_dialog_cls
    MW.QFileDialog.getSaveFileName = _saved_save_name
    win._dirty = False
    win.close()
theme.set_theme(theme.DARK)


# ════════════════════════════════════════════════════════════════════════════
# §7 i18n + the release state
# ════════════════════════════════════════════════════════════════════════════
print("== §7 i18n parity + the release state ==")

langs = load_i18n_langs(ROOT)
NEW_KEYS = ["dialog.export_options", "export.palette_hint", "export.use_current_theme"]
_missing = [key for key in NEW_KEYS
            if any(not str(langs[code].get(key, "")).strip() for code in sorted(langs))]
check(f"§7 the {len(NEW_KEYS)} new export keys exist in EVERY discovered language",
      not _missing, str(_missing))
check("§7 the keys are really used by the code (no dead strings)",
      all(key in open(os.path.join(ROOT, "dialogs", "export_options_dialog.py"),
                      encoding="utf-8").read() for key in NEW_KEYS),
      str([k for k in NEW_KEYS
           if k not in open(os.path.join(ROOT, "dialogs", "export_options_dialog.py"),
                            encoding="utf-8").read()]))
check("§7 the english strings say what the feature does",
      "print" in langs["en"]["export.palette_hint"].lower()
      and "theme" in langs["en"]["export.use_current_theme"].lower(),
      repr(langs["en"]["export.palette_hint"]))
check(f"§7 the parity pin covers the three new keys ({EXPECTED_I18N_KEYS})",
      all(len([k for k in langs[code] if k not in ("name", "partial")]) == EXPECTED_I18N_KEYS
          for code in sorted(langs)),
      str({code: len([k for k in langs[code] if k not in ("name", "partial")])
           for code in sorted(langs)}))
check_i18n_parity(langs)
check_i18n_format(langs)
check_release_state(ROOT)

finish()
