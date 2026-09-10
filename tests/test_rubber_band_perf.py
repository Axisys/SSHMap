# -*- coding: utf-8 -*-
"""v1.2.10rc3 — производительность rubber-band выделения на больших картах (AUDIT авто #9).

Тематический тест релиза (ROADMAP v1.2.10rc3; offscreen, без сети):
  * синтетическая сцена 520 ServerNode (сетка 26×20) + связи и заметки — «большие карты»;
  * рамка выделяет ровно пересекаемые узлы — результат идентичен алгоритму ДО v1.2.10rc3
    (референс в тесте: полный обход scene.items() + intersects + base_ids, как в rc2);
  * live-выделение на промежуточных шагах драга тоже совпадает с референсом;
  * аддитивный режим (Shift): базовое выделение ∪ пересечение, база вне рамки сохранена;
  * неаддитивный режим: ранее выделенные узлы вне рамки сняты (семантика замены);
  * клик без движения мыши выделение не меняет (press→release без _update);
  * заметки/стрелки рамкой НЕ выделяются (фильтр только ServerNode — как до фикса);
  * полный путь мыши через QTest (Ctrl+ЛКМ по пустому месту → драг → отпускание;
    Ctrl+Shift — аддитивный) — wiring модификаторов end-to-end.

Запуск: python tests/test_rubber_band_perf.py или python tests/run_all.py
"""
import sys

from _common import (bootstrap, check, finish, viewport_point, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

N_COLS, N_ROWS = 26, 20   # 520 узлов > 500 (Acceptance: «синтетическая сцена 500+ узлов»)
DX, DY = 280.0, 240.0     # шаг сетки > MIN_NODE_WIDTH/HEIGHT — узлы не перекрываются


def build_scene():
    """Синтетическая карта: сетка узлов + связи и заметки (прочие элементы сцены)."""
    from models.server import ServerData
    from graphics.map_scene import MapScene
    scene = MapScene()
    ids = []
    for r in range(N_ROWS):
        for c in range(N_COLS):
            data = ServerData(id=f"rb{r:02d}{c:02d}", alias=f"node-{r:02d}-{c:02d}",
                              host=f"10.0.{r}.{c}", user="root",
                              x=100.0 + c * DX, y=100.0 + r * DY)
            scene.add_server(data)
            ids.append(data.id)
    for i in range(0, len(ids) - 1, 41):
        scene.add_connection(ids[i], ids[i + 1])
    notes = [scene.add_note("note A", x=60.0, y=60.0),
             scene.add_note("note B", x=3000.0, y=2400.0)]
    return scene, notes


def reference_selection(scene, rect, base_ids):
    """Алгоритм ДО v1.2.10rc3 (полный обход scene.items()) — референс «результат как до фикса»."""
    from graphics.server_node import ServerNode
    out = set()
    for item in scene.items():
        if isinstance(item, ServerNode):
            hit = rect.intersects(item.sceneBoundingRect())
            if hit or (id(item) in base_ids):
                out.add(id(item))
    return out


def selected_node_ids(scene):
    from graphics.server_node import ServerNode
    return {id(i) for i in scene.selectedItems() if isinstance(i, ServerNode)}


def drag_steps(origin, end, n=5):
    """Точки драга: от origin к end (каждая = одно движение мыши)."""
    return [QPointF(origin.x() + (end.x() - origin.x()) * i / n,
                    origin.y() + (end.y() - origin.y()) * i / n)
            for i in range(1, n + 1)]


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from graphics.map_view import MapView
    from graphics.server_node import ServerNode

    scene, notes = build_scene()
    check("сцена: 520 узлов (500+)", scene.node_count() == N_COLS * N_ROWS, str(scene.node_count()))
    check("сцена: есть связи и заметки (прочие элементы)",
          len(scene.arrows()) > 0 and len(notes) == 2,
          f"arrows={len(scene.arrows())}")

    view = MapView(scene)
    view.resize(7800, 5400)   # весь контент в пределах viewport — точки драга доступны мыши

    origin = QPointF(40.0, 40.0)
    end = QPointF(3500.0, 2600.0)          # рамка через часть карты (~четверть узлов)
    final_rect = QRectF(origin, end).normalized()

    # ── §1 неаддитивный драг: ровно пересекаемые узлы, live + финал как до фикса ──
    print("== rubber band: 520 узлов, неаддитивный драг ==")
    steps = drag_steps(origin, end, n=5)
    view._start_rubber_select(origin)
    check("рамка добавлена в сцену", view._rubber_select_item is not None
          and view._rubber_select_item.scene() is scene)
    live_ok = True
    for i, pos in enumerate(steps):
        view._update_rubber_select(pos)
        r_i = QRectF(origin, pos).normalized()
        if selected_node_ids(scene) != reference_selection(scene, r_i, set()):
            live_ok = False
    check("live-выделение на каждом шаге = референс (алгоритм до фикса)", live_ok)
    got = selected_node_ids(scene)
    want = reference_selection(scene, final_rect, set())
    check("финал: рамка выделяет ровно пересекаемые узлы", got == want,
          f"got={len(got)} want={len(want)}")
    check("выделено >0 узлов (рамка через карту не пуста)", len(want) > 0, str(len(want)))
    check("заметки рамкой НЕ выделяются", all(not n.isSelected() for n in notes))
    check("стрелки рамкой НЕ выделяются",
          all(not a.isSelected() for a in scene.arrows()))
    view._finish_rubber_select()
    check("финиш: рамка убрана, выделение сохранено",
          view._rubber_select_item is None and selected_node_ids(scene) == want)

    # ── §2 аддитивный режим (Shift): база ∪ пересечение, база вне рамки цела ──
    print("== rubber band: аддитивный режим (Shift) ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    nodes_all = scene.nodes()
    outside = [n for n in nodes_all
               if not final_rect.intersects(n.sceneBoundingRect())][:3]
    inside = [n for n in nodes_all if final_rect.intersects(n.sceneBoundingRect())][:1]
    base_nodes = outside + inside
    for n in base_nodes:
        n.setSelected(True)
    base_ids = {id(n) for n in base_nodes}
    check("база: 3 узла вне рамки + 1 внутри выделены",
          selected_node_ids(scene) == base_ids and len(base_nodes) == 4,
          f"base={len(base_nodes)}")
    view._start_rubber_select(origin, additive=True)
    for pos in steps:
        view._update_rubber_select(pos)
    want_add = reference_selection(scene, final_rect, base_ids)
    got_add = selected_node_ids(scene)
    check("аддитив: итог = база ∪ пересекаемые (как до фикса)", got_add == want_add,
          f"got={len(got_add)} want={len(want_add)}")
    check("аддитив: 3 узла базы вне рамки сохранены",
          all(id(n) in got_add for n in outside))
    view._finish_rubber_select()

    # ── §3 неаддитивный режим: замена — база вне рамки снята ──
    print("== rubber band: неаддитивный режим заменяет выделение ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    for n in outside[:2]:
        n.setSelected(True)
    view._start_rubber_select(origin)   # без additive
    for pos in steps:
        view._update_rubber_select(pos)
    got_repl = selected_node_ids(scene)
    check("замена: выделены ТОЛЬКО пересекаемые (база вне рамки снята)",
          got_repl == reference_selection(scene, final_rect, set()),
          f"got={len(got_repl)}")
    view._finish_rubber_select()

    # ── §4 клик без движения: выделение не меняется ──
    print("== rubber band: клик без движения ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    keep = nodes_all[:2]
    for n in keep:
        n.setSelected(True)
    view._start_rubber_select(QPointF(7400.0, 4900.0))   # за контентом — пусто
    view._finish_rubber_select()   # press→release без единого _update
    check("клик без движения: выделение не изменилось",
          selected_node_ids(scene) == {id(n) for n in keep})

    # ── §5 полный путь мыши через QTest (Ctrl+ЛКМ → драг → отпускание) ──
    print("== rubber band: полный путь мыши (QTest, Ctrl / Ctrl+Shift) ==")
    for i in scene.selectedItems():
        i.setSelected(False)
    # пусто: зазор между колоннами 5/6 и строками 0/1 сетки (узлы — от x=100+c*280, y=100+r*240)
    empty = QPointF(2550.0, 300.0)
    end_m = QPointF(7400.0, 2900.0)   # конец драга — правая часть карты (точка может быть над узлом)
    check("точка нажатия пуста (страховка)", view._item_at_scene(empty) is None,
          repr(view._item_at_scene(empty)))
    vp = view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, stateKey=Qt.ControlModifier,
                     pos=viewport_point(view, empty))
    app.processEvents()
    check("Ctrl+ЛКМ по пустому месту: рамка стартовала", view._rubber_select_item is not None)
    mid = QPointF((empty.x() + end_m.x()) / 2, (empty.y() + end_m.y()) / 2)
    QTest.mouseMove(vp, pos=viewport_point(view, mid))
    app.processEvents()
    r_mid = QRectF(empty, mid).normalized()
    check("драг: live-выделение = референс",
          selected_node_ids(scene) == reference_selection(scene, r_mid, set()))
    QTest.mouseMove(vp, pos=viewport_point(view, end_m))
    app.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, pos=viewport_point(view, end_m))
    app.processEvents()
    check("отпускание: рамка убрана", view._rubber_select_item is None)
    check("отпускание: финал = референс (Ctrl-драг через мышь)",
          selected_node_ids(scene) == reference_selection(scene, QRectF(empty, end_m).normalized(), set()))

    # Ctrl+Shift — аддитивный через мышь: база вне рамки сохраняется
    for i in scene.selectedItems():
        i.setSelected(False)
    base_m = [n for n in nodes_all if not QRectF(empty, end_m).normalized()
              .intersects(n.sceneBoundingRect())][:2]
    for n in base_m:
        n.setSelected(True)
    QTest.mousePress(vp, Qt.LeftButton,
                     stateKey=Qt.ControlModifier | Qt.ShiftModifier,
                     pos=viewport_point(view, empty))
    app.processEvents()
    check("Ctrl+Shift+ЛКМ: рамка стартовала в аддитивном режиме",
          view._rubber_select_item is not None and
          len(view._rubber_saved_selection) == 2,
          f"saved={len(view._rubber_saved_selection)}")
    QTest.mouseMove(vp, pos=viewport_point(view, end_m))
    app.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, pos=viewport_point(view, end_m))
    app.processEvents()
    want_m = reference_selection(scene, QRectF(empty, end_m).normalized(),
                                 {id(n) for n in base_m})
    check("Ctrl+Shift-драг: база ∪ пересекаемые (аддитивный через мышь)",
          selected_node_ids(scene) == want_m)

    # ── §6 состояние релиза + i18n-паритет ──
    print("== release state ==")
    langs = load_i18n_langs(ROOT)
    check_i18n_parity(langs)
    check_release_state(ROOT)

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
