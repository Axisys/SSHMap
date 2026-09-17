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
    seg_h = n._tag_segments[0].rect().height()
    check("segments split height", abs(seg_h * 2 - n._current_height) < 1.5)
    check("strip width", n._tag_segments[0].rect().width() == ServerNode.TAG_STRIP_WIDTH)
    check("segment colors follow tags",
          n._tag_segments[0].brush().color().name()
          == ServerNode.tag_color("prod").name())

    n.data.tags = ["staging"]
    n.refresh_tags()
    vis = [s.isVisible() for s in n._tag_segments]
    check("refresh_tags after edit", vis[0] and not any(vis[1:]))

    # ── #4 The collapsed view: the strip stays and follows the height ──
    n.toggle_collapsed()
    check("collapsed height applied", n._current_height == ServerNode.COLLAPSED_HEIGHT)
    r = n._tag_segments[0].rect()
    check("collapsed segment fits strip",
          0 < r.height() <= ServerNode.COLLAPSED_HEIGHT + 0.1
          and r.width() == ServerNode.TAG_STRIP_WIDTH)
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
