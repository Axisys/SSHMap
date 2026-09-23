# -*- coding: utf-8 -*-
"""v1.5.1 (ROADMAP task 2): render the DOCUMENTATION poster of the README from the EXAMPLE map.

Not part of the suite (the runner skips the files whose name starts with `_`), like
`_gen_index.py` — it is the generator behind the image the README links, so the picture in
the repository is REPRODUCIBLE instead of a hand-made screenshot:

    python tests/_gen_docs_image.py                       # → docs/map-example.png
    python tests/_gen_docs_image.py --out /tmp/x.png      # another destination

Two rules make the file safe to publish, and both are why this script exists at all:

  * **the subject is the EXAMPLE map** (`storage/example_project.py`), never the project the
    maintainer happens to have open. A saved real project holds REAL topology and is
    gitignored; a one-click "docs image" on the currently open project is exactly how that
    accident happens. The demo uses RFC 5737 documentation addresses (`192.0.2.0/24`) only,
    so the published picture can never name a real host;
  * **the render is the SHIPPED one** — the ordinary load path into a `MapScene` followed by
    `MapScene.render_frame_to_pixmap()` with the DEFAULT DARK theme, i.e. the same 1600×900
    logical frame at 2× (3200×1800 px) the File → "Save Documentation Image…" action writes.
    The image therefore cannot drift from the action: both call the same method.

The refresh rule (DOCUMENTATION.md §5, AGENTS.md §2): re-run this script after a change that
alters the card, the theme or the demo map, and commit the new `docs/map-example.png`.
The topical gate (`tests/test_map_images.py`) checks that the file exists at the exact size
and that the README links it.

Run from the project root (headless — offscreen Qt, no window, no event loop needed).

**Fonts (measured, not assumed).** The `offscreen` platform plugin of PySide6 6.8+ ships no
font directory, so it renders every label as a box (Qt's own warning:
"QFontDatabase: Cannot find font directory …/PySide6/lib/fonts"); the harness runs the suite
that way, and a test never reads the pixels, so it does not matter there. A POSTER does. This
script therefore runs on the platform that really has fonts: `SSHMAP_DOCS_QT_PLATFORM` if it
is set, otherwise the NATIVE platform on Windows/macOS (they need no display in this process —
the scene is rendered into a QPixmap, never shown) and `offscreen` everywhere else (Linux CI
has no display; set the env var to `xcb` when a font set is available). The chosen platform and
the family count are printed, so a box-glyph poster cannot be committed silently.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _pick_qt_platform() -> str:
    """The Qt platform plugin of a TEXT-bearing render (see the module docstring)."""
    chosen = os.environ.get("SSHMAP_DOCS_QT_PLATFORM")
    if chosen:
        return chosen
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "cocoa"
    return "offscreen"


os.environ.setdefault("QT_QPA_PLATFORM", _pick_qt_platform())

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# The scene classes import PySide6 at module level, so the QApplication must exist first.
app = QApplication.instance() or QApplication([])

# A platform plugin without any font renders every label as a BOX (the offscreen plugin of
# PySide6 6.8+). The native one does have fonts, but it needs the right plugin name on every
# OS, so the fallback is measured instead of guessed: when the first choice has no family at
# all, the app is re-created on the native platform. Without Qt on a machine whose native
# plugin also has no fonts the script still writes the file and the count in the report says
# why the text is a box — an honest failure beats a silent one.
_FAMILIES = QFontDatabase.families()
if not _FAMILIES and os.environ.get("SSHMAP_DOCS_QT_PLATFORM") is None:
    _native = "windows" if sys.platform == "win32" else ("cocoa" if sys.platform == "darwin"
                                                         else "xcb")
    for _candidate in (_native, "offscreen"):
        if _candidate == os.environ.get("QT_QPA_PLATFORM"):
            continue
        os.environ["QT_QPA_PLATFORM"] = _candidate
        app = QApplication([])
        _FAMILIES = QFontDatabase.families()
        if _FAMILIES:
            break

from graphics.map_scene import MapScene  # noqa: E402
from models.server import server_data_from_dict  # noqa: E402
from storage.example_project import build_example_project  # noqa: E402
from ui import theme  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "docs", "map-example.png")


def build_example_scene() -> MapScene:
    """The example project loaded into a plain `MapScene` — the app's own load order.

    Groups first (membership is geometric and recomputed on every `add_server`), then the
    nodes, then the connections, then the notes: the same order
    `MainWindow._import_project_raw()` uses. The emulated statuses of v1.5 are deliberately
    NOT applied here: a status is a measurement, the project format keeps none, and the
    poster is a picture of the MAP, not of a probe round.
    """
    raw = build_example_project()
    scene = MapScene()

    for g in raw.get("groups", []):
        scene.add_group(name=str(g.get("name") or ""), x=float(g.get("x") or 0.0),
                        y=float(g.get("y") or 0.0),
                        width=float(g.get("width") or 480.0),
                        height=float(g.get("height") or 320.0),
                        group_id=str(g.get("id") or "")[:8] or None,
                        collapsed=bool(g.get("collapsed")),
                        expanded_width=g.get("expanded_width"),
                        expanded_height=g.get("expanded_height"))

    for s in raw.get("servers", []):
        scene.add_server(server_data_from_dict(s))

    for c in raw.get("connections", []):
        scene.add_connection(c["source_id"], c["target_id"], c.get("label", ""),
                             c.get("type", "ssh"),
                             bidirectional=bool(c.get("bidirectional", False)))

    for n in raw.get("notes", []):
        note = scene.add_note(text=str(n.get("text") or ""), x=float(n.get("x") or 0.0),
                              y=float(n.get("y") or 0.0),
                              width=float(n.get("width") or 240.0),
                              height=float(n.get("height") or 160.0),
                              note_id=str(n.get("id") or "")[:8] or None)
        server_id = n.get("server_id")
        if server_id and note is not None:
            node = scene.get_node(server_id)
            if node is not None:
                scene.attach_note_to_node(note, node, keep_position=True)
    return scene


def render(out_path: str = DEFAULT_OUT) -> str:
    """Render the poster to `out_path` and return the path written.

    The palette is the module default (`PALETTE_THEME` — the ACTIVE instance, DARK out of
    the box): the README shows the application as the user sees it. Passing
    `theme.PALETTE_PRINT` here would produce the light printable page instead.
    """
    scene = build_example_scene()
    pixmap = scene.render_frame_to_pixmap(palette=theme.PALETTE_THEME)
    folder = os.path.dirname(os.path.abspath(out_path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    if not pixmap.save(out_path):
        raise SystemExit(f"cannot write the documentation image: {out_path}")
    print(f"documentation image: {out_path} "
          f"({pixmap.width()}x{pixmap.height()} px, "
          f"{os.path.getsize(out_path)} bytes, palette={theme.PALETTE_THEME}, "
          f"platform={os.environ.get('QT_QPA_PLATFORM')}, font families={len(_FAMILIES)})")
    return out_path


def _parse_out(argv) -> str:
    if "--out" in argv:
        try:
            return argv[argv.index("--out") + 1]
        except IndexError:
            raise SystemExit("--out needs a path")
    return DEFAULT_OUT


if __name__ == "__main__":
    render(_parse_out(sys.argv[1:]))
