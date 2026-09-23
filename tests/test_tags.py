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

    # ── #3 The tag strip on the card (expanded) ──
    n = scene.add_server(ServerData(id="n1", alias="app", host="10.0.0.3", user="u",
                                    tags=["prod", "dmz"]))
    check("two visible segments for two tags",
          [s.isVisible() for s in n._tag_segments] == [True, True])
    r0 = n._tag_segments[0].rect()
    r1 = n._tag_segments[1].rect()
    corner = float(ServerNode.CORNER_RADIUS)
    check("segments split the INNER height (the corner insets are excluded)",
          abs(r0.height() * 2 + 2 * ServerNode.TAG_STRIP_GAP
              - (n._current_height - 2 * corner)) < 0.1,
          f"h={r0.height()} card={n._current_height}")
    check("strip width", r0.width() == ServerNode.TAG_STRIP_WIDTH)
    # v1.5rc5 (N5): the strip is part of the frame — inset from the outline (clear of the
    # 2/3 px pen band), from the rounded corners, and with a gap between the segments.
    check("N5: the strip is inset from the left outline (never over the status frame)",
          r0.left() >= 2.0 and r0.right() <= ServerNode.CORNER_RADIUS,
          f"x={r0.left()}..{r0.right()}")
    check("N5: the strip starts below the corner radius and stays inside the silhouette",
          r0.top() >= corner and r1.bottom() <= n._current_height - corner + 0.01,
          f"top={r0.top()} bottom={r1.bottom()} corner={corner}")
    check("N5: consecutive segments are separated (the tag boundary is visible)",
          r1.top() > r0.bottom(), f"{r0.bottom()} vs {r1.top()}")
    check("segment colors follow tags",
          n._tag_segments[0].brush().color().name()
          == ServerNode.tag_color("prod").name())

    n.data.tags = ["staging"]
    n.refresh_tags()
    vis = [s.isVisible() for s in n._tag_segments]
    check("refresh_tags after edit", vis[0] and not any(vis[1:]))

    # ── #3b v1.5 (ROADMAP): the ENVIRONMENT badge — the tag's TEXT above the alias ──
    from graphics.server_node import ENV_TAGS, env_tag
    from ui import theme
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
    check("v1.5 ...tinted with the SAME colour the left-edge strip paints that tag",
          n._env_chip.pen().color().name() == ServerNode.tag_color("prod").name()
          and n._env_chip.brush().color().alpha() > 0
          and n._env_badge.brush().color().name()
          == theme.THEME.node_label, n._env_chip.pen().color().name())
    _band = n._env_chip.path().boundingRect()
    check("v1.5 ...inside the MEASURED free band above the alias (clear of the dots)",
          _band.left() >= ServerNode.LABEL_X - 0.01 and _band.top() >= 0.0
          and _band.bottom() <= 18.0
          and _band.right() <= n._current_width - ServerNode.BADGE_RIGHT_INSET + 0.01,
          f"{_band} card={n._current_width}x{n._current_height}")

    _long = "free-form-tag-" + "x" * 60
    n_long = scene.add_server(ServerData(id="n-long", alias="tiny", host="10.0.0.9",
                                         user="u", tags=[_long]))
    check("v1.5 a long free-form tag is ELIDED to the band (it never leaves the card)",
          n_long._env_badge.text() != _long and n_long._env_badge.text().endswith("…")
          and n_long._env_badge.toolTip() == _long
          and n_long._env_badge.boundingRect().width() <=
          n_long._current_width - ServerNode.LABEL_X - ServerNode.BADGE_RIGHT_INSET,
          f"{n_long._env_badge.text()!r} of {_long!r} card={n_long._current_width}")

    n_plain = scene.add_server(ServerData(id="n-plain", alias="web", host="10.0.0.3",
                                          user="u"))
    check("v1.5 a card WITHOUT tags carries no badge item at all (byte-identical to today)",
          n_plain._env_badge is None and n_plain._env_chip is None
          and n_plain._demo_badge is None
          and n_plain._current_width == n._current_width, str(n_plain._current_width))

    n.toggle_collapsed()
    check("v1.5 the badge is HIDDEN on a collapsed card (the single line has no second row)",
          n._env_badge.isVisible() is False and n._current_height == ServerNode.COLLAPSED_HEIGHT)
    n.toggle_collapsed()
    check("v1.5 unfolding brings it back", n._env_badge.isVisible() is True)

    _dark_pen = n._env_chip.pen().color().name()
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
        set_theme(theme.DARK)
        n.refresh_theme()
        check("v1.5 ...and switching back restores the card's own tone",
              n._env_chip.pen().color().name() == _dark_pen)

    # ── #4 The collapsed view: the strip stays and follows the height ──
    n.toggle_collapsed()
    check("collapsed height applied", n._current_height == ServerNode.COLLAPSED_HEIGHT)
    r = n._tag_segments[0].rect()
    check("collapsed segment fits strip",
          0 < r.height() <= ServerNode.COLLAPSED_HEIGHT + 0.1
          and r.width() == ServerNode.TAG_STRIP_WIDTH)
    check("N5: the collapsed segment keeps the corner insets too",
          r.top() >= float(ServerNode.CORNER_RADIUS)
          and r.bottom() <= ServerNode.COLLAPSED_HEIGHT - float(ServerNode.CORNER_RADIUS),
          f"top={r.top()} bottom={r.bottom()}")
    n.toggle_collapsed()

    # ── #5 Empty tags — the segments are hidden ──
    n.data.tags = []
    n.refresh_tags()
    check("no tags -> all segments hidden",
          not any(s.isVisible() for s in n._tag_segments))

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
