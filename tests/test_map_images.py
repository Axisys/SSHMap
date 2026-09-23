# -*- coding: utf-8 -*-
"""v1.5.1 — map images: "Copy Map as Image" and the fixed-frame documentation poster.

The first patch ON the released 1.5. Two pieces of the SAME machinery
(`MapScene.render_to_pixmap`, the v0.9.1 export path) that both exist to kill the manual
screenshot work the documentation and the issue reports still do by hand:

  * **the copy** — the 2× render of the CURRENT theme (`theme.PALETTE_THEME`) straight into
    `QApplication.clipboard()`, NO file dialog and NO palette question (an export is a
    document, a copy is "what I am looking at"); File menu + the map's empty-space menu;
  * **the docs frame** — `MapScene.render_frame_to_pixmap()`: the map fitted into a FIXED
    1600×900 LOGICAL frame at 2× (3200×1800 px) and centred on a 40 px margin, so the
    picture has the SAME size for every map. A poster of the MAP (a scene render), with the
    published README image taken from the EXAMPLE map through `tests/_gen_docs_image.py`.

Sections:
  §1 the fixed frame — the declared geometry, the fit ratio, the centring, the empty map,
     the determinism, the palette scope (the pure `frame_source_rect()` where possible);
  §2 the copy — the clipboard pixmap, the current-theme palette, the "no palette question"
     audit, the empty map and the two menu homes;
  §3 the docs frame — the file writer, the status report and the committed README image;
  §4 the release state — the pins, the two registry actions and the "no new contract" audit.

Run: python tests/test_map_images.py   (from the project root) or python tests/run_all.py
"""
import dataclasses
import os
import re
import struct

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from graphics.map_scene import MapScene  # noqa: E402
from models.server import ServerData  # noqa: E402
import storage.example_project as EP  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
from ui import theme  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402
from i18n import t as _t  # noqa: E402

_langs = load_i18n_langs(ROOT)
_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — for the "it lives in ONE place" audits."""
    key = parts
    if key not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            _SRC[key] = f.read()
    return _SRC[key]


def _func_body(*parts, func) -> str:
    """The source of ONE function with its docstring STRIPPED (the audit seam).

    A source audit has to look at the CODE, not at the prose: a docstring that names the
    palette dialog while explaining why the copy must NOT call it would otherwise fail its
    own check. `ast.parse` + `ast.unparse` (3.9+) yields the statements alone, so the check
    is about what really runs.
    """
    import ast

    tree = ast.parse(_src(*parts))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]  # drop the docstring
            return ast.unparse(ast.Module(body=body or [ast.Pass()], type_ignores=[]))
    raise AssertionError(f"{func} is not defined in {parts}")


def _copy_body() -> str:
    """The stripped body of `MainWindow._copy_map_image` — the v1.5.1 pinned decision."""
    return _func_body("ui", "main_window.py", func="_copy_map_image")


def png_size(path):
    """(width, height) read from the PNG IHDR — the file on disk, not a Qt object."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"not a PNG file: {path}")
    return struct.unpack(">II", head[16:24])


def make_main():
    """An offscreen MainWindow with the timers stopped and NO status checker (hermetic)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


def build_scene():
    """A small deterministic scene (two cards and one arrow) — the topical fixture."""
    scene = MapScene()
    scene.add_server(ServerData(id="img-a", alias="web-01", host="192.0.2.10",
                                user="root", x=0.0, y=0.0, tags=["prod"]))
    scene.add_server(ServerData(id="img-b", alias="db-01", host="192.0.2.20",
                                user="root", x=420.0, y=0.0))
    scene.add_connection("img-a", "img-b", "API", "http")
    return scene


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the fixed 1600x900 @2x frame ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the frame geometry is DECLARED on the scene (one place, no magic numbers at a call site)",
      MapScene.DOCS_FRAME_W == 1600.0 and MapScene.DOCS_FRAME_H == 900.0
      and MapScene.DOCS_FRAME_SCALE == 2.0 and MapScene.DOCS_FRAME_PADDING == 40.0
      and "DOCS_FRAME_W" in _src("graphics", "map_scene.py"))
check("§1 the frame is 16:9 (the ratio of every screen the poster is looked at on)",
      abs(MapScene.DOCS_FRAME_W / MapScene.DOCS_FRAME_H - 16.0 / 9.0) < 1e-9,
      f"{MapScene.DOCS_FRAME_W}/{MapScene.DOCS_FRAME_H}")

_scene = build_scene()
_box = QRectF(_scene.itemsBoundingRect())
_src_rect = _scene.frame_source_rect()
_pad = MapScene.DOCS_FRAME_PADDING
_padded = _box.adjusted(-_pad, -_pad, _pad, _pad)
_ratio = max(_padded.width() / MapScene.DOCS_FRAME_W, _padded.height() / MapScene.DOCS_FRAME_H)
check("§1 the fit uses the LARGER dimension (the content is never cropped and never stretched)",
      abs(_src_rect.width() - MapScene.DOCS_FRAME_W * _ratio) < 0.01
      and abs(_src_rect.height() - MapScene.DOCS_FRAME_H * _ratio) < 0.01,
      f"src={_src_rect.width():.1f}x{_src_rect.height():.1f} ratio={_ratio:.4f}")
check("§1 the source rect carries the FRAME's own proportions (the poster is 16:9 edge to edge)",
      abs(_src_rect.width() / _src_rect.height()
          - MapScene.DOCS_FRAME_W / MapScene.DOCS_FRAME_H) < 1e-6,
      f"{_src_rect.width() / _src_rect.height():.6f}")
check("§1 ...and the content is CENTRED in it (the free axis carries the canvas on both sides)",
      abs(_src_rect.center().x() - _padded.center().x()) < 0.01
      and abs(_src_rect.center().y() - _padded.center().y()) < 0.01,
      f"{_src_rect.center()} vs {_padded.center()}")
check("§1 the map keeps its own proportions (the fit axis takes the margin, the free one more)",
      abs(_ratio - max(_padded.width() / MapScene.DOCS_FRAME_W,
                       _padded.height() / MapScene.DOCS_FRAME_H)) < 1e-9
      and _src_rect.width() >= _padded.width() and _src_rect.height() >= _padded.height(),
      f"{_src_rect.width():.1f}x{_src_rect.height():.1f} vs {_padded.width():.1f}x{_padded.height():.1f}")
check("§1 the source rect is PURE geometry (a second call answers the same numbers)",
      _scene.frame_source_rect() == _src_rect and _scene.frame_source_rect(1600.0, 900.0, 40.0)
      == _src_rect)

_empty = MapScene()
_empty_box = _empty.frame_source_rect()
_pad = MapScene.DOCS_FRAME_PADDING
check("§1 an EMPTY map gets the documented fallback rect, fitted to the frame (no exception)",
      abs(_empty_box.center().x() - (-400.0 + 800.0 / 2)) < 0.01
      and abs(_empty_box.center().y() - (-300.0 + 600.0 / 2)) < 0.01
      and abs(_empty_box.width() / _empty_box.height() - 16.0 / 9.0) < 1e-6
      and _empty_box.width() >= 800.0 + 2 * _pad and _empty_box.height() >= 600.0 + 2 * _pad,
      str(_empty_box))

_pm1 = _scene.render_frame_to_pixmap()
check("§1 the poster is exactly 1600x900 LOGICAL at 2x = 3200x1800 px",
      _pm1.width() == 3200 and _pm1.height() == 1800 and not _pm1.isNull(),
      f"{_pm1.width()}x{_pm1.height()}")
_pm2 = _scene.render_frame_to_pixmap()
check("§1 the same map renders the same pixel size twice (DETERMINISTIC — the acceptance)",
      _pm2.size() == _pm1.size() and _pm2.toImage() == _pm1.toImage(),
      f"{_pm2.size()} vs {_pm1.size()}")
check("§1 a non-default frame/scale is honoured (the constants are the DEFAULT, not a cage)",
      _scene.render_frame_to_pixmap(scale=1.0).size().toTuple() == (1600, 900)
      and _scene.render_frame_to_pixmap(frame_w=800.0, frame_h=600.0).size().toTuple() == (1600, 1200))

theme.set_theme(theme.DARK)


def dominant(image):
    """The most frequent colour of an image (sampled 4 px apart) — the page surface."""
    counts = {}
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            name = image.pixelColor(x, y).name()
            counts[name] = counts.get(name, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


_page_theme = dominant(_scene.render_frame_to_pixmap(palette=theme.PALETTE_THEME).toImage())
_page_print = dominant(_scene.render_frame_to_pixmap(palette=theme.PALETTE_PRINT).toImage())
check("§1 the poster defaults to the CURRENT theme (a poster is read on screen)",
      _page_theme == theme.DARK.canvas_bg and _page_print == theme.LIGHT.canvas_bg,
      f"{_page_theme} / {_page_print}")
check("§1 the palette is restored after the render (no leak into the window)",
      theme.current_theme() is theme.DARK
      and theme.export_theme(theme.PALETTE_THEME) is theme.DARK)
check("§1 ...and the scene's own items were re-read for the render (the arrow follows the palette)",
      _scene.arrows()[0].pen().color().name() == theme.DARK.arrow_type_colors["http"],
      _scene.arrows()[0].pen().color().name())


# ════════════════════════════════════════════════════════════════════════════
print("== §2 'Copy Map as Image' (the clipboard, in the CURRENT theme) ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
win.scene.add_server(ServerData(id="copy-a", alias="web-01", host="192.0.2.10",
                                user="root", x=0.0, y=0.0, tags=["prod"]))
win.scene.add_server(ServerData(id="copy-b", alias="db-01", host="192.0.2.20",
                                user="root", x=420.0, y=0.0))
app.processEvents()

_asked = {"palette": 0, "dialog": 0}


class _ForbiddenDialog:
    """A palette dialog that FAILS the test if the copy path ever builds one."""

    def __init__(self, *a, **k):
        _asked["dialog"] += 1
        raise RuntimeError("the copy must not ask the export palette question")


_orig_dialog = MW.ExportOptionsDialog
_orig_ask = MW.MainWindow._ask_export_palette


def _counting_ask(self):
    _asked["palette"] += 1
    return theme.PALETTE_THEME


MW.ExportOptionsDialog = _ForbiddenDialog
MW.MainWindow._ask_export_palette = _counting_ask
try:
    QApplication.clipboard().clear()
    _copy_ok = True
    try:
        win._copy_map_image()
    except Exception as e:  # noqa: BLE001 — the check below reports the failure
        _copy_ok = False
        print("        _copy_map_image raised:", repr(e))
    app.processEvents()
    _clip = QApplication.clipboard().pixmap()
finally:
    MW.ExportOptionsDialog = _orig_dialog
    MW.MainWindow._ask_export_palette = _orig_ask

check("§2 the action runs and the clipboard holds a non-empty pixmap",
      _copy_ok and not _clip.isNull() and _clip.width() > 1 and _clip.height() > 1,
      f"{_clip.width()}x{_clip.height()} null={_clip.isNull()}")
_expected = win.scene.render_to_pixmap(scale=2.0, palette=theme.PALETTE_THEME)
check("§2 the image is the 2x render of the CURRENT theme (byte-for-byte the render)",
      _clip.size() == _expected.size() and _clip.toImage() == _expected.toImage(),
      f"{_clip.size()} vs {_expected.size()}")
check("§2 ...and the copy asked NO palette question and built NO palette dialog",
      _asked == {"palette": 0, "dialog": 0}, str(_asked))
check("§2 the status bar reports the copy",
      win.statusBar().currentMessage() == _t("status.map_copied"),
      win.statusBar().currentMessage())
check("§2 the source audit: the copy path never asks the palette question (the pinned decision)",
      "self._ask_export_palette(" not in _copy_body()
      and "PALETTE_THEME" in _copy_body(),
      _copy_body().replace("\n", " ")[:120])
check("§2 ...while the PNG export DOES ask it (the two paths really differ)",
      "self._ask_export_palette(" in _func_body("ui", "main_window.py", func="_export_map_image"))

_win_empty = make_main()
_win_empty.scene.clear_all()
app.processEvents()
_ok_empty = True
try:
    _win_empty._copy_map_image()
except Exception as e:  # noqa: BLE001
    _ok_empty = False
    print("        empty-map copy raised:", repr(e))
app.processEvents()
check("§2 an EMPTY map copies without an exception (the render has its fallback rect)",
      _ok_empty and not QApplication.clipboard().pixmap().isNull()
      and QApplication.clipboard().pixmap().size()
      == _win_empty.scene.render_to_pixmap(scale=2.0, palette=theme.PALETTE_THEME).size(),
      f"{QApplication.clipboard().pixmap().size()}")
_win_empty.close()

# The two menu homes: the File menu (a registry QAction) and the empty-space map menu.
# The menu point is chosen FAR from every card, so the branch under test is the
# empty-space one (a point on a node would build the node menu instead).
_far = max((n.sceneBoundingRect().right() for n in win.scene.nodes()), default=0.0) + 500.0
_menu = win.view.build_context_menu(QPoint(int(_far), int(_far)))
_menu_labels = [a.text() for a in _menu.actions()]
check("§2 the File menu carries the copy action (one registered QAction target)",
      len(win._hotkey_targets.get("file.copy_map", [])) == 1
      and any(a.text() == _t("file.copy_map")
              for a in win._hotkey_targets["file.copy_map"][0].parent().actions()),
      f"targets={len(win._hotkey_targets.get('file.copy_map', []))}")
check("§2 the map's empty-space context menu carries it too (one method, two homes)",
      _t("file.copy_map") in _menu_labels, str(_menu_labels))
_act_copy = [a for a in _menu.actions() if a.text() == _t("file.copy_map")][0]
_called = []
_orig_copy = win._copy_map_image
win._copy_map_image = lambda *a, **k: _called.append(1)
try:
    _act_copy.trigger()
finally:
    win._copy_map_image = _orig_copy
check("§2 triggering the context-menu row reaches MainWindow._copy_map_image",
      _called == [1], str(_called))
win._dirty = False
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the docs frame: the file writer and the published README image ==")
# ════════════════════════════════════════════════════════════════════════════

win2 = make_main()
_orig_save_name = MW.QFileDialog.getSaveFileName
_out_png = os.path.join(WORK, "docs_frame.png")
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_out_png, "PNG Images (*.png)"))
try:
    win2._export_docs_frame()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save_name
app.processEvents()
check("§3 the action writes the file through the ordinary save dialog pattern",
      os.path.isfile(_out_png), _out_png)
check("§3 the written PNG is exactly 3200x1800 px",
      png_size(_out_png) == (3200, 1800), str(png_size(_out_png)))
check("§3 the status bar names the saved BASENAME (a long path cannot flood the bar)",
      win2.statusBar().currentMessage()
      == _t("status.docs_frame_saved", file=os.path.basename(_out_png)),
      win2.statusBar().currentMessage())

# A cancelled dialog writes nothing (the pattern every export shares).
_cancelled = os.path.join(WORK, "docs_frame_cancelled.png")
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
try:
    win2._export_docs_frame()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save_name
check("§3 a cancelled dialog writes NO file (the export is really aborted)",
      not os.path.exists(_cancelled))
win2._dirty = False
win2.close()

# The published image of the README — the example map, at the exact size, linked.
_docs_png = os.path.join(ROOT, "docs", "map-example.png")
_readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("§3 the README links the documentation image in its markdown",
      "docs/map-example.png" in _readme and "![The example map" in _readme,
      [ln for ln in _readme.splitlines() if "map-example" in ln][:2])
check("§3 ...and the image is COMMITTED at the frame's exact size",
      os.path.isfile(_docs_png) and png_size(_docs_png) == (3200, 1800),
      f"{os.path.isfile(_docs_png)} {png_size(_docs_png) if os.path.isfile(_docs_png) else '-'}")
check("§3 the generator exists and renders from the EXAMPLE map (never server_map*.json)",
      os.path.isfile(os.path.join(ROOT, "tests", "_gen_docs_image.py"))
      and "build_example_project" in _src("tests", "_gen_docs_image.py")
      and "render_frame_to_pixmap" in _src("tests", "_gen_docs_image.py")
      and "server_map" not in _src("tests", "_gen_docs_image.py"))
check("§3 ...and the refresh rule is written down where the workflow lives (DOCUMENTATION + README)",
      "_gen_docs_image.py" in _src("DOCUMENTATION.md")
      and "_gen_docs_image.py" in _readme)
check("§3 the demo addresses of the poster can only be RFC 5737 (nothing real can be published)",
      all(EP.is_reserved_host(s["host"]) for s in EP.build_example_project()["servers"])
      and EP.RESERVED_NETWORK in _readme)


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the release state and the 'no new contract' audit ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
check("§4 EXPECTED_APP_VERSION is this release (the first patch on the released 1.5)",
      EXPECTED_APP_VERSION == "1.5.2"
      and re.fullmatch(r"1\.5\.2", EXPECTED_APP_VERSION) is not None)
check("§4 the i18n pin moved by exactly FOUR keys in v1.5.1 (two labels + two reports) and "
      "by v1.5.2's thirteen on top",
      EXPECTED_I18N_KEYS == 661, str(EXPECTED_I18N_KEYS))
check_i18n_parity(_langs)
check_i18n_format(_langs)

_NEW_KEYS = ("file.copy_map", "file.docs_frame", "status.map_copied", "status.docs_frame_saved")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in _langs.items()}
check(f"§4 the four keys of v1.5.1 are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§4 the placeholders of the report key match en everywhere (the {file} name)",
      all(set(re.findall(r"\{(\w+)\}", _langs[c]["status.docs_frame_saved"])) == {"file"}
          for c in _langs),
      str({c: _langs[c]["status.docs_frame_saved"] for c in sorted(_langs)}))

check("§4 the two new actions are registered with an EMPTY default (assignable, no key taken)",
      {"file.copy_map", "file.docs_frame"} <= set(HR.action_ids())
      and HR.default_sequence("file.copy_map") == ""
      and HR.default_sequence("file.docs_frame") == ""
      and {"file.copy_map", "file.docs_frame"} <= set(HR.empty_default_action_ids()))
check("§4 the registry grew 49 -> 51 in v1.5.1 (+v1.5.2's View item -> 52) and the empty-default "
      "set 26 -> 28 (-> 29)",
      len(HR.HOTKEY_ACTIONS) == 52 and len(HR.empty_default_action_ids()) == 29,
      f"{len(HR.HOTKEY_ACTIONS)} / {len(HR.empty_default_action_ids())}")
check("§4 every registry action is still bound to a real object in a live window",
      all(len(targets) > 0 for targets in make_main()._hotkey_targets.values()))
check("§4 the two actions live in the File family (the Hotkeys tab's grouping derives it)",
      HR.action_family("file.copy_map") == "file" and HR.action_family("file.docs_frame") == "file")

_hub = SettingsDialog(None)
check("§4 no new config key (the hub still collects 22)",
      len(_hub.collect()) == 22, str(len(_hub.collect())))
_hub.close()
check("§4 no new theme field (the palette is the v1.5rc1 one)",
      len(dataclasses.fields(theme.Theme)) == 60)
_deps = {"PySide6", "paramiko", "keyring", "wcwidth"}
_req = _src("requirements.txt")
check("§4 no new dependency (the four pinned ones and nothing else)",
      all(f"{d}>=" in _req for d in _deps)
      and not re.search(r"^\s*(?!PySide6|paramiko|keyring|wcwidth|#)[A-Za-z][\w.-]*\s*[><=]",
                        _req, re.M))
check("§4 VERSION_FORMAT did NOT move (the project schema is unchanged)",
      __import__("version").VERSION_FORMAT == "0.9"
      and __import__("version").APP_VERSION == "1.5.2")

finish()
