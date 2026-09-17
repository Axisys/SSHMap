# -*- coding: utf-8 -*-
"""v0.9.9.7 — Map PDF export (ROADMAP v0.9.9.7).

It checks (offscreen, WITHOUT parsing the PDF content):
  1. `MapScene.render_to_pdf()` → the file exists, the size > 0, the %PDF header and
     the %%EOF marker; the return value == the size of the file on disk.
  2. An empty scene — also a valid PDF (the fallback rect of render_to_pixmap).
  3. A portrait map (the height > the width) — the page without a crash.
  4. MainWindow: `_export_map_pdf` exists and is registered in the "File" menu
     (the i18n registry `_menu_i18n`).
  5. i18n: the new keys `file.export_pdf` / `status.export_pdf_ok` × en/ru/zh
     are not empty; the sets of keys are identical (the parity pin — tests/_common.py).

Run: python tests/test_pdf_export.py   (from the project root) or python tests/run_all.py
"""
import os

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData
from graphics.map_scene import MapScene


def export_and_check(scene, name, path):
    """render_to_pdf + the basic file checks: existence/size/header.

    The PDF content is NOT parsed (the ROADMAP v0.9.9.7 convention) — only the bytes
    at the file boundaries: the %PDF- header and the %%EOF at the tail.
    """
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

path = os.path.join(WORK, "test_pdf_export.pdf")
export_and_check(scene, "the full map", path)

# ── 2. An empty scene — the fallback rect of render_to_pixmap ───────────────────────────
empty_path = os.path.join(WORK, "test_pdf_empty.pdf")
export_and_check(MapScene(), "the empty scene", empty_path)

# ── 3. A portrait map (taller than wide) — a portrait page ──────────────────
tall_scene = MapScene()
tall_scene.add_server(ServerData(id="pdf4", alias="top-01", host="10.0.0.24",
                                 user="root", x=100, y=-600))
tall_scene.add_server(ServerData(id="pdf5", alias="bottom-01", host="10.0.0.25",
                                 user="root", x=100, y=600))
tall_path = os.path.join(WORK, "test_pdf_tall.pdf")
export_and_check(tall_scene, "the portrait map", tall_path)

# ── 4. MainWindow: the method + registration in the "File" menu ───────────────────────────
from ui.main_window import MainWindow

win = MainWindow()
check("the MainWindow has _export_map_pdf", hasattr(win, "_export_map_pdf"))
i18n_keys = [key for _widget, key in win._menu_i18n]
check("file.export_pdf is registered in the i18n registry (the File menu)",
      "file.export_pdf" in i18n_keys)
win._dirty = False  # closeEvent without a save dialog
win.close()

# ── 5. i18n: the new keys × en/ru/zh + the set identity (377 per language; +22 in v1.0RC4, +33 in v1.1, +2 in v1.1.2RC2, +2 in v1.1.2 final) ──
langs = load_i18n_langs(ROOT)
new_keys = ["file.export_pdf", "status.export_pdf_ok"]
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 2 new keys of v0.9.9.7 are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

finish()
