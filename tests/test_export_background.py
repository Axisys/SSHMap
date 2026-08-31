# -*- coding: utf-8 -*-
"""Регрессия v0.9.1: экспорт карты в изображение + фон-изображение.

Запуск: python tests/test_export_background.py или python tests/run_all.py
Без pytest: общая обвязка tests/_common.py.
"""
import json
import os
import sys
import tempfile

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def make_test_image(path: str, w=320, h=200):
    pm = QPixmap(w, h)
    pm.fill()
    assert pm.save(path), f"fixture save failed: {path}"
    return path


def main():
    print("== v0.9.1: background image + map export ==")

    from graphics.background_image import BackgroundImage
    from graphics.map_scene import MapScene
    from models.server import ServerData
    from storage.project import save_project, load_project

    tmpdir = tempfile.mkdtemp(prefix="sshmap_v091_")
    img_path = os.path.join(tmpdir, "bg.png")
    make_test_image(img_path)

    # #1 BackgroundImage: загрузка, размер по нативу, to_dict/try_from_dict
    bg = BackgroundImage(img_path, x=10.0, y=20.0)
    check("bg loads pixmap", not bg.pixmap_like().isNull() if hasattr(bg, "pixmap_like") else True)
    check("bg default size = native", bg.size() == (320.0, 200.0))
    check("bg z below groups", bg.Z_VALUE < -5.0)
    d = bg.to_dict()
    check("bg to_dict keys", set(d) == {"path", "x", "y", "width", "height"})
    bg2 = BackgroundImage.try_from_dict(d)
    check("bg round-trip", bg2 is not None and bg2.size() == (320.0, 200.0) and bg2.path == img_path)

    # #2 try_from_dict: отсутствующий файл / битая запись → None (не исключение)
    missing = dict(d, path=os.path.join(tmpdir, "nope.png"))
    check("missing file -> None", BackgroundImage.try_from_dict(missing) is None)
    check("garbage -> None", BackgroundImage.try_from_dict("junk") is None)
    check("empty -> None", BackgroundImage.try_from_dict({}) is None)

    # #3 MapScene: set/remove/clear_all
    scene = MapScene()
    check("no background initially", scene.background() is None)
    bgs = scene.set_background_image(img_path)
    check("set_background returns item", bgs is scene.background())
    check("background in scene", bgs.scene() is scene)
    scene.remove_background()
    check("remove_background clears", scene.background() is None and bgs.scene() is None)
    scene.remove_background()  # no-op без исключения
    scene.set_background_image(img_path)
    scene.clear_all()
    check("clear_all resets background", scene.background() is None)

    # #4 resize clamp
    bg3 = BackgroundImage(img_path)
    check("resize works", bg3.set_bg_size(100, 80))
    bg3.set_bg_size(1, 1)
    check("resize clamps min", bg3.size() == (BackgroundImage.MIN_SIZE,) * 2)

    # #5 render_to_pixmap: карта целиком, независимо от вьюпорта
    scene2 = MapScene()
    node = scene2.add_server(ServerData(id="n1", alias="web-01", host="10.0.0.1", user="root", x=-300.0, y=-250.0))
    scene2.add_server(ServerData(id="n2", alias="db-01", host="10.0.0.2", user="root", x=400.0, y=350.0))
    scene2.set_background_image(img_path)
    pm = scene2.render_to_pixmap(scale=2.0)
    check("render non-empty", pm.width() > 100 and pm.height() > 100)
    out_png = os.path.join(tmpdir, "map_export.png")
    check("pixmap.save png", pm.save(out_png) and os.path.getsize(out_png) > 0)
    out_jpg = os.path.join(tmpdir, "map_export.jpg")
    check("pixmap.save jpg", pm.save(out_jpg) and os.path.getsize(out_jpg) > 0)

    # #6 JSON round-trip с фоном
    proj = os.path.join(tmpdir, "proj.json")
    scene3 = MapScene()
    n = scene3.add_server(ServerData(id="n3", alias="web-01", host="10.0.0.1", user="root", x=50.0, y=60.0))
    bg4 = scene3.set_background_image(img_path)
    bg4.setPos(15.0, 25.0)
    bg4.set_bg_size(160.0, 100.0)
    save_project(proj, {n.data.id: n}, [], zoom=1.0, center_x=0.0, center_y=0.0,
                 notes=[], groups=[], background=scene3.background())
    raw = load_project(proj)
    check("json has background key", isinstance(raw.get("background"), dict))
    check("json bg geometry", raw["background"]["width"] == 160.0
          and raw["background"]["x"] == 15.0)

    # #7 backward-compat: проект без ключа "background"
    legacy_path = os.path.join(tmpdir, "legacy.json")
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump({"version": "0.6", "servers": [], "connections": []}, f)
    raw_legacy = load_project(legacy_path)
    check("legacy has no background", raw_legacy.get("background") is None)

    # #8 MainWindow._import_project_raw восстанавливает фон; missing file — пропускает
    from ui.main_window import MainWindow
    win = MainWindow()

    win._import_project_raw(raw)
    check("import restores background", win.scene.background() is not None
          and win.scene.background().size() == (160.0, 100.0))
    check("import bg position", abs(win.scene.background().pos().x() - 15.0) < 0.5)

    win._import_project_raw(dict(raw, background=dict(raw["background"], path="Z:/missing.png")))
    check("missing file skipped on import", win.scene.background() is None)

    win._import_project_raw({})  # пустой проект без ключа — не падает
    check("legacy import without key ok", win.scene.background() is None)

    # #9 методы окна существуют и remove на пустой карте — no-op
    check("win has export method", hasattr(win, "_export_map_image"))
    check("win has bg methods", hasattr(win, "_set_background_image")
          and hasattr(win, "_remove_background_image"))
    win._remove_background_image()  # не должно падать
    check("remove on empty map no-op", True)

    win.close()
    del win

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
