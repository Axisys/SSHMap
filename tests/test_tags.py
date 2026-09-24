# -*- coding: utf-8 -*-
"""Regression v0.9.4: server tags/color labels.

Run: python tests/test_tags.py or python tests/run_all.py
Without pytest: the common harness tests/_common.py.
"""
import json
import os
import sys
import tempfile

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def main():
    print("== v0.9.4: server tags ==")

    from models.server import ServerData, server_data_from_dict, server_data_to_dict
    from graphics.map_scene import MapScene
    from graphics.server_node import ServerNode

    scene = MapScene()

    # ── #1 The model: the tags field, the defaults, and normalization when reading JSON ──
    d = ServerData(id="t1", alias="web", host="10.0.0.1", user="root",
                   tags=["prod", " web ", "", "PROD"])
    check("model stores tags as given (normalize at parse/dialog layer)",
          d.tags == ["prod", " web ", "", "PROD"])

    raw = {"id": "t2", "alias": "db", "host": "10.0.0.2",
           "tags": ["prod", " dev ", "", 42]}
    parsed = server_data_from_dict(raw)
    check("from_dict normalizes tags", parsed.tags == ["prod", "dev", "42"])

    legacy = server_data_from_dict({"id": "t3", "alias": "old", "host": "h"})
    check("legacy json -> empty tags", legacy.tags == [])

    scalar = server_data_from_dict({"id": "t4", "alias": "s", "host": "h", "tags": "prod"})
    check("scalar tag string wrapped to list", scalar.tags == ["prod"])

    out = json.loads(json.dumps(server_data_to_dict(parsed)))
    check("to_dict serializes tags array", out["tags"] == ["prod", "dev", "42"])
    check("password not in dict", "password" not in out)

    # ── #2 The tag colors: the known roles + a stable hash of arbitrary ones ──
    check("known role color prod", ServerNode.tag_color("prod").name() == "#ef4444")
    check("role color case-insensitive",
          ServerNode.tag_color("Prod") == ServerNode.tag_color("prod"))
    c1 = ServerNode.tag_color("webfarm")
    c2 = ServerNode.tag_color("webfarm")
    check("arbitrary tag color stable across calls", c1.name() == c2.name())
    palette = {Q.name() for Q in ServerNode.TAG_PALETTE}
    check("arbitrary tag from palette", ServerNode.tag_color("webfarm").name() in palette)

    # ── #3 The environment TONE on the card's ICON (v1.5.6 — the 5 px strip is gone) ──
    # The card below carries an OS line, so it is WIDE enough for the tag chip of #3b: the
    # chip lives on the alias row and the alias owns its left side, so a MIN-width card has
    # no room for it (the ICON then carries the environment alone).
    from ui import theme
    n = scene.add_server(ServerData(id="n1", alias="app", host="10.0.0.3", user="u",
                                    tags=["prod", "dmz"],
                                    os_name="Ubuntu 22.04.3 LTS"))
    check("the ICON carries the PRIMARY tag's tone (the strip's colour moved there)",
          n._icon.brush().color().name() == ServerNode.tag_color("prod").name(),
          f"{n._icon.brush().color().name()} vs {ServerNode.tag_color('prod').name()}")
    check("the strip is GONE (no segment item, no constant, no builder, no source line)",
          not hasattr(n, "_tag_segments")
          and not any(_name.startswith("TAG_STRIP") for _name in dir(ServerNode))
          and "_rebuild_tag_strip" not in dir(ServerNode)
          and "TAG_STRIP" not in open(os.path.join(ROOT, "graphics", "server_node.py"),
                                      encoding="utf-8").read())

    n.data.tags = ["staging"]
    n.refresh_tags()
    check("refresh_tags after an edit moves the icon tone (the declared `staging` role)",
          n._icon.brush().color().name() == ServerNode.tag_color("staging").name())

    n_arb = scene.add_server(ServerData(id="n-arb", alias="app", host="10.0.0.3", user="u",
                                        tags=["webfarm", "db"],
                                        os_name="Ubuntu 22.04.3 LTS"))
    check("an arbitrary tag gets the deterministic palette tone (crc32 → tag_palette)",
          n_arb._icon.brush().color().name() == ServerNode.tag_color("webfarm").name()
          and ServerNode.tag_color("webfarm").name() in
          {_c.name() for _c in ServerNode.TAG_PALETTE})

    n_plain = scene.add_server(ServerData(id="n-plain", alias="app", host="10.0.0.3", user="u"))
    check("a card WITHOUT tags keeps the neutral icon tone it has always had",
          n_plain._icon.brush().color().name() == QColor(theme.NODE_ICON_BG).name(),
          n_plain._icon.brush().color().name())

    # ── #3b v1.5 (ROADMAP): the ENVIRONMENT badge — the tag's TEXT on the alias row ──
    from graphics.server_node import ENV_TAGS, env_tag
    check("v1.5 env_tag: the vocabulary is DECLARED and its order IS the precedence",
          ENV_TAGS == ("prod", "staging", "stage", "dev", "test"))
    check("v1.5 env_tag: the declared word wins whatever order the user typed",
          env_tag(["web", "prod"]) == "prod" and env_tag(["dev", "prod"]) == "prod"
          and env_tag(["stage"]) == "stage" and env_tag(["staging"]) == "staging")
    check("v1.5 env_tag: the USER's spelling is kept (a badge never renames the data)",
          env_tag(["Prod"]) == "Prod" and env_tag([" DEV "]) == "DEV")
    check("v1.5 env_tag: an unknown tag falls back to the FIRST one (the primary label)",
          env_tag(["webfarm", "db"]) == "webfarm")
    check("v1.5 env_tag: no tags → no badge (and never a crash on junk)",
          env_tag([]) == "" and env_tag(None) == "" and env_tag(["", "  ", 42]) == "42")
    check("v1.5 env_tag is the SKINNY pick — the colour stays `tag_color()`",
          ServerNode.tag_color(env_tag(["Prod"])).name()
          == ServerNode.tag_color("prod").name())

    n.data.tags = ["prod", "dmz"]
    n.refresh_tags()
    check("v1.5 the badge is the tag's TEXT (a second channel beside the colour)",
          n._env_badge is not None and n._env_badge.isVisible()
          and n._env_badge.text() == "prod", repr(getattr(n._env_badge, "text", lambda: "")()))
    check("v1.5 ...tinted with the SAME colour the card's icon paints that tag",
          n._env_chip.pen().color().name() == ServerNode.tag_color("prod").name()
          and n._env_chip.brush().color().alpha() > 0
          and n._env_badge.brush().color().name()
          == theme.THEME.node_label, n._env_chip.pen().color().name())
    _row = n._alias.boundingRect().translated(n._alias.pos())
    _chip = n._env_chip.path().boundingRect()
    check("v1.5 the chip sits in the free band ABOVE the alias (it keeps the name its row)",
          _chip.top() >= 0.0 and _chip.bottom() <= _row.top() + 0.01
          and _chip.left() >= ServerNode.LABEL_X - 0.01,
          f"chip={_chip} alias row={_row} card={n._current_width}x{n._current_height}")
    check("v1.5.6 ...left-aligned with the alias and clear of the chevron",
          _chip.right() <= n._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01
          and _chip.right() <= n._status_dot.pos().x() - 0.01,
          f"chip right={_chip.right()} band right={n._current_width - ServerNode.BADGE_RIGHT_INSET}")

    _long = "free-form-tag-" + "x" * 60
    n_long = scene.add_server(ServerData(id="n-long", alias="tiny", host="10.0.0.9", user="u",
                                         tags=[_long], os_name="Ubuntu 22.04.3 LTS",
                                         cpu="Intel Xeon E5-2670"))
    check("v1.5 a long free-form tag is ELIDED to the band (it never leaves the card)",
          n_long._env_badge.text() != _long and n_long._env_badge.text().endswith("…")
          and n_long._env_badge.toolTip() == _long
          and n_long._env_chip.path().boundingRect().right()
          <= n_long._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01,
          f"{n_long._env_badge.text()!r} of {_long!r} card={n_long._current_width}")
    check("v1.5 ...and it does not enter the card's WIDTH formula (a long tag never stretches it)",
          n_long._current_width <= ServerNode.MAX_NODE_WIDTH
          and n_long._env_badge.text() != _long)

    check("v1.5 a card WITHOUT tags carries no badge item at all (byte-identical to today)",
          n_plain._env_badge is None and n_plain._env_chip is None
          and n_plain._demo_badge is None)

    n.toggle_collapsed()
    check("v1.5.6 the collapsed card keeps the TONE on its icon (both card modes)",
          n._icon.brush().color().name() == ServerNode.tag_color("prod").name()
          and n._current_height == ServerNode.COLLAPSED_HEIGHT)
    check("v1.5 ...and the collapsed single line carries no chip (no band on it)",
          n._env_badge.isVisible() is False,
          f"h={n._current_height} alias={n._alias.toPlainText()!r}")
    n.toggle_collapsed()
    check("v1.5 unfolding brings it back", n._env_badge.isVisible() is True)

    _dark_pen = n._env_chip.pen().color().name()
    _dark_icon = n._icon.brush().color().name()
    _switched = None
    try:
        from ui.theme import set_theme
        set_theme(theme.LIGHT)
        _switched = True
        n.refresh_theme()
    except Exception:  # noqa: BLE001 — a stripped theme module must not break the file
        _switched = False
    if _switched:
        check("v1.5 a theme switch repaints the badge (the chip colour moved)",
              n._env_chip.pen().color().name() != _dark_pen
              and n._env_badge.brush().color().name() == theme.LIGHT.node_label,
              f"{_dark_pen} -> {n._env_chip.pen().color().name()}")
        check("v1.5.6 ...and re-resolves the ICON tone (it is a tag colour, not a literal)",
              n._icon.brush().color().name() == ServerNode.tag_color("prod").name(),
              f"{_dark_icon} -> {n._icon.brush().color().name()}")
        set_theme(theme.DARK)
        n.refresh_theme()
        check("v1.5 ...and switching back restores the card's own tone",
              n._env_chip.pen().color().name() == _dark_pen
              and n._icon.brush().color().name() == _dark_icon)

    # ── #4 The collapsed view: the tone stays, the row keeps its geometry ──
    n.toggle_collapsed()
    check("collapsed height applied", n._current_height == ServerNode.COLLAPSED_HEIGHT)
    check("the collapsed card still carries the environment tone (the icon is always there)",
          n._icon.brush().color().name() == ServerNode.tag_color("prod").name()
          and n._current_width >= ServerNode.MIN_NODE_WIDTH)
    n.toggle_collapsed()

    # ── #5 Empty tags — the neutral tone comes back and the chip disappears ──
    n.data.tags = []
    n.refresh_tags()
    check("no tags -> the icon returns to the neutral tone and the chip is hidden",
          n._icon.brush().color().name() == QColor(theme.NODE_ICON_BG).name()
          and n._env_badge.isVisible() is False)

    # ── #6 set_dimmed: dimming the non-matching nodes ──
    n.set_dimmed(True)
    check("dimmed opacity", abs(n.opacity() - ServerNode.DIM_OPACITY) < 1e-6)
    n.set_dimmed(True)   # a repeated call — a no-op
    check("dim idempotent", abs(n.opacity() - ServerNode.DIM_OPACITY) < 1e-6)
    n.set_dimmed(False)
    check("undim restores opacity", abs(n.opacity() - 1.0) < 1e-6)

    # ── #7 Backward-compat: a project in the old format (no tags) is readable ──
    old_project = {
        "version": "0.9",
        "servers": [
            {"id": "s1", "alias": "a", "host": "h1", "user": "root", "x": 0, "y": 0},
            {"id": "s2", "alias": "b", "host": "h2", "user": "root", "x": 100, "y": 0,
             "tags": ["dev"]},
        ],
        "connections": [],
    }
    from storage.project import load_project
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(old_project, fh)
        loaded = load_project(path)
        s1 = server_data_from_dict(loaded["servers"][0])
        s2 = server_data_from_dict(loaded["servers"][1])
        check("legacy server without tags -> []", s1.tags == [])
        check("server with tags preserved", s2.tags == ["dev"])
    finally:
        os.unlink(path)

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
