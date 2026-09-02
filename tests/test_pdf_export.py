# -*- coding: utf-8 -*-
"""v0.9.9.7 — PDF-экспорт карты (ROADMAP v0.9.9.7).

Проверяет (offscreen, БЕЗ парсинга содержимого PDF):
  1. `MapScene.render_to_pdf()` → файл существует, размер > 0, заголовок %PDF и
     маркер %%EOF; возвращаемое значение == размеру файла на диске.
  2. Пустая сцена — тоже валидный PDF (fallback-rect render_to_pixmap).
  3. Портретная карта (высота > ширина) — страница без падения.
  4. MainWindow: `_export_map_pdf` существует и зарегистрирован в меню «Файл»
     (i18n-реестр `_menu_i18n`).
  5. i18n: новые ключи `file.export_pdf` / `status.export_pdf_ok` × en/ru/zh
     не пусты; наборы ключей идентичны (304 на язык — +2 к пину v0.9.9.6).

Запуск: python tests/test_pdf_export.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from models.server import ServerData
from graphics.map_scene import MapScene


def export_and_check(scene, name, path):
    """render_to_pdf + базовые проверки файла: существование/размер/заголовок.

    Содержимое PDF НЕ парсится (конвенция ROADMAP v0.9.9.7) — только байты
    на границах файла: %PDF- заголовок и %%EOF в хвосте.
    """
    size = scene.render_to_pdf(path)
    exists = os.path.isfile(path)
    check(f"{name}: файл существует", exists, f"got {path!r}")
    if not exists:
        return False
    disk_size = os.path.getsize(path)
    check(f"{name}: размер > 1 KB", disk_size > 1024, f"got {disk_size} bytes")
    check(f"{name}: возвращённое значение == размеру на диске", size == disk_size,
          f"returned {size!r}, on disk {disk_size}")
    with open(path, "rb") as f:
        head = f.read(5)
        f.seek(-1024, os.SEEK_END)
        tail = f.read()
    check(f"{name}: заголовок %PDF", head == b"%PDF-", f"got {head!r}")
    check(f"{name}: маркер %%EOF в хвосте файла", b"%%EOF" in tail)
    return True


# ── 1. Полная карта: узлы + связь + заметка + группа ───────────────────────────
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
note = scene.add_note("Проверить бэкапы", x=600, y=50)
check("стикер добавлен в сцену", note is not None and bool(scene.notes()))
group = scene.add_group("prod", x=50, y=50, width=400, height=300)
group.add_member(n3)

path = os.path.join(WORK, "test_pdf_export.pdf")
export_and_check(scene, "полная карта", path)

# ── 2. Пустая сцена — fallback-rect render_to_pixmap ───────────────────────────
empty_path = os.path.join(WORK, "test_pdf_empty.pdf")
export_and_check(MapScene(), "пустая сцена", empty_path)

# ── 3. Портретная карта (выше, чем шире) — portrait-страница ──────────────────
tall_scene = MapScene()
tall_scene.add_server(ServerData(id="pdf4", alias="top-01", host="10.0.0.24",
                                 user="root", x=100, y=-600))
tall_scene.add_server(ServerData(id="pdf5", alias="bottom-01", host="10.0.0.25",
                                 user="root", x=100, y=600))
tall_path = os.path.join(WORK, "test_pdf_tall.pdf")
export_and_check(tall_scene, "портретная карта", tall_path)

# ── 4. MainWindow: метод + регистрация в меню «Файл» ───────────────────────────
from ui.main_window import MainWindow

win = MainWindow()
check("MainWindow имеет _export_map_pdf", hasattr(win, "_export_map_pdf"))
i18n_keys = [key for _widget, key in win._menu_i18n]
check("file.export_pdf зарегистрирован в i18n-реестре (меню «Файл»)",
      "file.export_pdf" in i18n_keys)
win._dirty = False  # closeEvent без диалога сохранения
win.close()

# ── 5. i18n: новые ключи × en/ru/zh + идентичность наборов (373 на язык; +22 в v1.0RC4, +33 в v1.1) ──
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = ["file.export_pdf", "status.export_pdf_ok"]
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("2 новых ключа v0.9.9.7 есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (373 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 373 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

finish()
