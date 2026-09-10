# -*- coding: utf-8 -*-
"""v1.2.10rc3 — замер rubber-band выделения (AUDIT авто #9). НЕ часть сьюта.

Паттерн standalone-замера (как tests/_bench_history.py для v1.2.12): запускается
вручную, печатает мс в stdout — числа уходят в CHANGELOG.md («измерено на …,
v1.2.10rc3»). run_all.py его НЕ собирает (файлы с префиксом _ пропускаются).

Сценарий: синтетическая карта 500 ServerNode (сетка 25×20) + связи и заметка
(реалистичный состав элементов сцены); драг рамки выделения через всю карту —
N шагов от левого верхнего угла к правому нижнему. Каждый шаг = одно движение
мыши = один вызов MapView._update_rubber_select (до фикса v1.2.10rc3 — полный
O(n) обход scene.items(); после — пространственный индекс scene().items(rect)
+ фильтр isinstance).

Сравнение до/после: прогнать скрипт на кодовой базе v1.2.10rc2 (до фикса),
затем после фикса graphics/map_view.py — обе пары чисел в CHANGELOG.

Запуск:  python tests/_bench_rubber.py   (из корня проекта)
"""
import platform
import sys
import time

from _common import bootstrap

ROOT, WORK = bootstrap(faulthandler_timeout=300)

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def build_scene(n_cols=25, n_rows=20):
    """Синтетическая карта: сетка узлов + связи и заметка (прочие элементы сцены)."""
    from models.server import ServerData
    from graphics.map_scene import MapScene

    scene = MapScene()
    dx, dy = 280.0, 240.0   # шаг сетки > MIN_NODE_WIDTH/HEIGHT — узлы не перекрываются
    ids = []
    for r in range(n_rows):
        for c in range(n_cols):
            data = ServerData(id=f"bench{r:02d}{c:02d}", alias=f"node-{r:02d}-{c:02d}",
                              host=f"10.0.{r}.{c}", user="root",
                              x=100.0 + c * dx, y=100.0 + r * dy)
            scene.add_server(data)
            ids.append(data.id)
    # Связи и заметка — другие элементы сцены (старый полный обход тоже их видел;
    # items(rect) отдаёт их кандидатами — фильтр isinstance должен отсечь).
    for i in range(0, len(ids) - 1, 37):
        scene.add_connection(ids[i], ids[i + 1])
    scene.add_note("bench note", x=40.0, y=40.0)
    return scene


def drag_across(view, steps=25):
    """Один полный драг рамки через карту: start → steps обновлений → finish.

    Возвращает (ms_обновлений, ширина/высота финальной рамки). Замеряется ТОЛЬКО
    цикл _update_rubber_select — старт/финиш (addItem/removeItem) не в счёт."""
    nodes = view.scene().nodes()
    xs = [n.pos().x() for n in nodes]
    ys = [n.pos().y() for n in nodes]
    origin = QPointF(min(xs) - 60.0, min(ys) - 60.0)
    end = QPointF(max(xs) + 240.0, max(ys) + 190.0)
    view._start_rubber_select(origin)
    t0 = time.perf_counter()
    for i in range(1, steps + 1):
        t = i / steps
        view._update_rubber_select(QPointF(origin.x() + (end.x() - origin.x()) * t,
                                           origin.y() + (end.y() - origin.y()) * t))
    dt_ms = (time.perf_counter() - t0) * 1000.0
    view._finish_rubber_select()
    return dt_ms, end.x() - origin.x(), end.y() - origin.y()


def main():
    from PySide6 import __version__ as pyside_ver
    from PySide6.QtCore import qVersion as qt_ver
    from graphics.map_view import MapView

    scene = build_scene()
    n_nodes = scene.node_count()
    n_items = len(scene.items())
    view = MapView(scene)
    view.resize(1200, 800)

    steps = 25
    print(f"_bench_rubber (v1.2.10rc3, AUDIT авто #9): {n_nodes} узлов (сетка 25x20), "
          f"элементов сцены={n_items}")
    print(f"  среда: python {platform.python_version()}, Qt {qt_ver()}, "
          f"PySide6 {pyside_ver}, offscreen")

    # Разогрев: первый прогон строит внутренние индексы/кэши Qt — не в зачёт.
    for _ in range(3):
        drag_across(view, steps)
    cycles = [drag_across(view, steps)[0] for _ in range(5)]
    w, h = drag_across(view, steps)[1], drag_across(view, steps)[2]

    print(f"  драг рамки через карту: {steps} шагов (каждый = mouse move), "
          f"финальная рамка {w:.0f}x{h:.0f}")
    for i, ms in enumerate(cycles, 1):
        print(f"  цикл {i}: {ms:8.2f} мс   ({ms * 1000.0 / steps:7.1f} мкс/обновление)")
    best = min(cycles)
    print(f"  ЛУЧШИЙ из {len(cycles)} циклов: {best:.2f} мс "
          f"({best * 1000.0 / steps:.1f} мкс/обновление, {n_nodes} узлов)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
