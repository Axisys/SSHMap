# -*- coding: utf-8 -*-
"""v0.9.9.7 — Map PDF export (ROADMAP v0.9.9.7); geometry pinned in v1.3.3.7-fix.

It checks (offscreen, WITHOUT parsing the PDF content):
  1. `MapScene.render_to_pdf()` → the file exists, the size > 0, the %PDF header and
     the %%EOF marker; the return value == the size of the file on disk.
  2. An empty scene — also a valid PDF (the fallback rect of render_to_pixmap).
  3. A portrait map (the height > the width) — the page without a crash.
  4. MainWindow: `_export_map_pdf` exists and is registered in the "File" menu
     (the i18n registry `_menu_i18n`).
  5. i18n: the new keys `file.export_pdf` / `status.export_pdf_ok` × en/ru/zh
     are not empty; the sets of keys are identical (the parity pin — tests/_common.py).
  6. **v1.3.3.7-fix — the PAGE GEOMETRY** (the regression that shipped in v0.9.9.7 and
     was found while verifying the export set: a ~72 pt thumbnail in the corner of a
     870×1200 pt white page). Measured on the real file: the /MediaBox (the long side
     1200 pt = 42 cm, the short side following the map's proportions, the orientation
     the map's own), the /Width//Height of the embedded image (the raster floor), and —
     when QtPdf is available — the INK COVERAGE of the page rendered back: the drawn
     map must fill the page, not sit in its corner. Both defects are also explained in
     `MapScene.render_to_pdf`.

Run: python tests/test_pdf_export.py   (from the project root) or python tests/run_all.py
"""
import os
import re

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData
from graphics.map_scene import MapScene

PDF_MEDIABOX_RE = re.compile(rb"/MediaBox\s*\[([^\]]*)\]")
PDF_IMAGE_RE = re.compile(rb"/Subtype\s*/Image(.{0,300}?)>>", re.S)
PAGE_LONG_SIDE_PT = 1200.0          # MapScene.PDF_PAGE_LONG_SIDE_PT
MIN_RASTER_DPI = 140.0              # the floor is MapScene.PDF_RASTER_DPI = 150 — with a margin
MIN_INK_COVERAGE = 0.85             # the map must fill the page (the regression was ~0.06)


def page_box(path):
    """The page rectangle in POINTS from the /MediaBox of the first page (or None)."""
    with open(path, "rb") as f:
        data = f.read()
    m = PDF_MEDIABOX_RE.search(data)
    return [float(v) for v in m.group(1).split()] if m else None


def embedded_image_px(path):
    """(width, height) of the embedded map image in PIXELS — the raster actually stored."""
    with open(path, "rb") as f:
        data = f.read()
    for blob in PDF_IMAGE_RE.findall(data):
        w = re.search(rb"/Width\s+(\d+)", blob)
        h = re.search(rb"/Height\s+(\d+)", blob)
        if w and h:
            return int(w.group(1)), int(h.group(1))
    return None


def ink_coverage(path, render_px=600):
    """The bounding box of the DRAWN content as a fraction of the page (fx, fy).

    Renders page 0 back through QtPdf (`QPdfDocument`, PySide6-Addons). The reference
    "empty page" colour is the DOMINANT pixel colour, not the corner pixel: on the
    v0.9.9.7 output the thumbnail sat exactly in the corner (the corner pixel was the
    map, and every white pixel looked like ink — the first version of this helper was
    fooled by it). With the dominant colour the tiny-image output yields a bbox of a few
    percent while a correct export spans the page. Returns None when QtPdf is missing.
    """
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QImage
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
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
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_RGB32)

    samples = {}
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            rgb = image.pixelColor(x, y).rgb()
            samples[rgb] = samples.get(rgb, 0) + 1
    background = max(samples, key=samples.get)

    min_x, min_y, max_x, max_y = image.width(), image.height(), -1, -1
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if image.pixelColor(x, y).rgb() != background:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
    if max_x < 0:
        return (0.0, 0.0)
    return (round((max_x - min_x) / image.width(), 3),
            round((max_y - min_y) / image.height(), 3))


def export_and_check(scene, name, path, expect_landscape=None, has_content=True):
    """render_to_pdf + the file checks + the v1.3.3.7-fix page-geometry checks."""
    size = scene.render_to_pdf(path)
    exists = os.path.isfile(path)
    check(f"{name}: the file exists", exists, f"got {path!r}")
    if not exists:
        return False
    disk_size = os.path.getsize(path)
    check(f"{name}: the size > 1 KB", disk_size > 1024, f"got {disk_size} bytes")
    check(f"{name}: the returned value == the size on disk", size == disk_size,
          f"returned {size!r}, on disk {disk_size}")
    with open(path, "rb") as f:
        head = f.read(5)
        f.seek(-1024, os.SEEK_END)
        tail = f.read()
    check(f"{name}: the %PDF header", head == b"%PDF-", f"got {head!r}")
    check(f"{name}: the %%EOF marker in the tail of the file", b"%%EOF" in tail)

    # ── the page geometry (v1.3.3.7-fix) ────────────────────────────────────────────
    box = page_box(path)
    check(f"{name}: the /MediaBox is readable", box is not None, str(box))
    if box is None:
        return False
    page_w, page_h = box[2], box[3]
    long_side, short_side = max(page_w, page_h), min(page_w, page_h)
    check(f"{name}: the page long side is the documented 42 cm ({PAGE_LONG_SIDE_PT:.0f} pt)",
          abs(long_side - PAGE_LONG_SIDE_PT) <= 1.0, f"got {long_side} pt")

    image = embedded_image_px(path)
    check(f"{name}: the map image is embedded", image is not None, str(image))
    if image is not None:
        iw, ih = image
        check(f"{name}: the page keeps the image's proportions (a custom page, not A4)",
              abs((page_w / page_h) - (iw / ih)) < 0.02,
              f"page {page_w / page_h:.3f} vs image {iw / ih:.3f}")
        if has_content:
            dpi = max(iw, ih) / (long_side / 72.0)
            check(f"{name}: the raster floor holds (≈{MIN_RASTER_DPI:.0f}+ dpi on the page)",
                  dpi >= MIN_RASTER_DPI, f"{dpi:.1f} dpi ({iw}×{ih} px)")
        else:
            check(f"{name}: an empty scene keeps the cheap raster (the floor is skipped "
                  f"by design — a blank page needs no 25 MB image)",
                  max(iw, ih) < 1000, f"{iw}×{ih} px")

    if expect_landscape is not None and has_content:
        check(f"{name}: the page orientation is the map's own "
              f"({'landscape' if expect_landscape else 'portrait'})",
              (page_w > page_h) == expect_landscape, f"got {page_w}×{page_h} pt")

    coverage = ink_coverage(path)
    if coverage is not None:
        check(f"{name}: the map FILLS the page — no thumbnail in the corner (the v0.9.9.7 defect)",
              coverage[0] >= MIN_INK_COVERAGE and coverage[1] >= MIN_INK_COVERAGE,
              f"ink covers {coverage[0]:.3f}×{coverage[1]:.3f} of the page")
    else:  # pragma: no cover — QtPdf ships with the standard PySide6 wheel
        check(f"{name}: the ink coverage could not be rendered back (QtPdf missing) — "
              f"the structural checks above carry the pin", True, "")
    return True


# ── 1. A full map: nodes + a connection + a note + a group ───────────────────────────
scene = MapScene()
n1 = scene.add_server(ServerData(
    id="pdf1", alias="web-01", host="10.0.0.21", user="ubuntu",
    x=700, y=80, os_name="Ubuntu 24.04"))
n2 = scene.add_server(ServerData(
    id="pdf2", alias="db-01", host="10.0.0.22", user="ubuntu",
    x=700, y=350))
n3 = scene.add_server(ServerData(
    id="pdf3", alias="cache-01", host="10.0.0.23", user="ubuntu",
    x=120, y=160))
scene.add_connection("pdf1", "pdf2", label="replication", ctype="database")
note = scene.add_note("Check the backups", x=600, y=50)
check("the note is added to the scene", note is not None and bool(scene.notes()))
group = scene.add_group("prod", x=50, y=50, width=400, height=300)
group.add_member(n3)

src = scene.itemsBoundingRect().adjusted(-60.0, -60.0, 60.0, 60.0)
_landscape = float(src.width()) >= float(src.height())

path = os.path.join(WORK, "test_pdf_export.pdf")
export_and_check(scene, "the full map", path, expect_landscape=_landscape)

# ── 2. An empty scene — the fallback rect of render_to_pixmap ───────────────────────────
empty_path = os.path.join(WORK, "test_pdf_empty.pdf")
export_and_check(MapScene(), "the empty scene", empty_path, has_content=False)

# ── 3. A portrait map (taller than wide) — a portrait page ──────────────────
tall_scene = MapScene()
tall_scene.add_server(ServerData(id="pdf4", alias="top-01", host="10.0.0.24",
                                 user="root", x=100, y=-600))
tall_scene.add_server(ServerData(id="pdf5", alias="bottom-01", host="10.0.0.25",
                                 user="root", x=100, y=600))
tall_path = os.path.join(WORK, "test_pdf_tall.pdf")
export_and_check(tall_scene, "the portrait map", tall_path, expect_landscape=False)

# ── 4. The `scale` parameter: the PAGE follows the map, the raster follows the call ────
scale_path = os.path.join(WORK, "test_pdf_scale.pdf")
low_path = os.path.join(WORK, "test_pdf_low.pdf")
scene.render_to_pdf(scale_path, scale=3.0)
scene.render_to_pdf(low_path, scale=1.0)
check("the page rectangle does not depend on the raster scale",
      page_box(scale_path)[2:] == page_box(low_path)[2:] == page_box(path)[2:],
      f"{page_box(scale_path)} / {page_box(low_path)} / {page_box(path)}")
check("a scale ABOVE the raster floor really raises the embedded image",
      embedded_image_px(scale_path)[0] > embedded_image_px(low_path)[0],
      f"{embedded_image_px(scale_path)} vs {embedded_image_px(low_path)}")

# ── 5. MainWindow: the method + registration in the "File" menu ───────────────────────────
from ui.main_window import MainWindow

win = MainWindow()
check("the MainWindow has _export_map_pdf", hasattr(win, "_export_map_pdf"))
i18n_keys = [key for _widget, key in win._menu_i18n]
check("file.export_pdf is registered in the i18n registry (the File menu)",
      "file.export_pdf" in i18n_keys)
win._dirty = False  # closeEvent without a save dialog
win.close()

# ── 6. i18n: the new keys × en/ru/zh + the set identity ───────────────────────────────
langs = load_i18n_langs(ROOT)
new_keys = ["file.export_pdf", "status.export_pdf_ok"]
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 2 new keys of v0.9.9.7 are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

finish()
