"""Группы узлов на карте v0.8.1 (бывш. smoke_test.py «v0.8.1 groups»).

Часть сьюта, разбитого из smoke_test.py v0.6–v0.9.2 (см. INDEX.md).
Задачи релиза: (1) graphics/node_group.py — QGraphicsObject с рамкой и заголовком;
(2) серверы внутри группы автоматически перемещаются при изменении границы;
(3) группы сохраняются/загружаются из JSON (массив "groups").
  * создание/id/to_dict+from_dict, z ниже узлов;
  * геометрическое членство: центр карточки в верхней группе; find_group_at;
  * drag группы (QTest): члены сдвигаются на тот же дельта-сдвиг, sync data.x/y, moved-сигнал;
  * resize: пропорциональная репозиция ×3 включая кламп внутрь рамки меньше узла;
  * выход/вход узла из рамки — членство пересчитывается на лету;
  * перекрывающиеся группы: узел только в верхней (позднее добавленной);
  * JSON round-trip 4 групп + восстановление членства из геометрии, backward-compat;
  * путь через MainWindow: _add_group_at (QPoint и bool-guard), Delete-клавиша, Edit-menu;
  * ctx-меню группы add/rename/delete + double-click по заголовку → renameRequested.

Запуск: python tests/test_groups.py   (из корня проекта) или python tests/run_all.py
"""
import os
import sys

from _common import bootstrap, check, finish, viewport_point as _vp

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import server_data_from_dict
from i18n import t

# ══ v0.8.1: группировка узлов (кластеры/папки на карте) ═══════════
print("== v0.8.1 groups ==")

from graphics.node_group import NodeGroup as _NG
win_g = MW.MainWindow()
win_g.show(); app.processEvents()
view_g = win_g.view
vp_g = view_g.viewport()

from PySide6.QtCore import QPoint as _QPt, Qt as _Qt
from PySide6.QtTest import QTest as _QTest

# ── 1. Создание, id, сериализация ───────────────────────────────
g1 = win_g.scene.add_group(name="prod", x=100, y=100, width=500, height=360)
check("scene.add_group creates NodeGroup in _groups (QGraphicsObject with frame+title)",
      len(win_g.scene._groups) == 1 and g1 is win_g.scene._groups[0]
      and isinstance(g1, _NG), str(type(g1)))
check("group rendered below nodes/arrows (z < 0)", g1.zValue() < 0, str(g1.zValue()))
check("group has 8-char id (note/server pattern)", len(g1.group_id) == 8, str(g1.group_id))
d_g = g1.to_dict()
check("group to_dict: exactly {id,name,x,y,width,height} — no membership in JSON",
      set(d_g.keys()) == {"id", "name", "x", "y", "width", "height"}
      and d_g["name"] == "prod" and (d_g["x"], d_g["y"]) == (100.0, 100.0)
      and (d_g["width"], d_g["height"]) == (500.0, 360.0), str(d_g))
g_bad = _NG.from_dict({"x": "garbage", "width": None, "id": "abcdef12"})
check("group from_dict survives bad values (defaults)",
      g_bad.pos().x() == 0.0 and abs(g_bad.boundingRect().width() - _NG.DEFAULT_W) < 0.5
      and len(g_bad.group_id) == 8, str(g_bad.to_dict()))

# ── 2. Геометрическое членство: центр карточки в верхней группе ──
n_in = win_g.scene.add_server(server_data_from_dict({"alias": "g-in", "host": "10.9.9.1", "user": "u", "x": 140, "y": 140}))
n_out = win_g.scene.add_server(server_data_from_dict({"alias": "g-out", "host": "10.9.9.2", "user": "u", "x": 700, "y": -600}))
check("node with center inside group auto-joins on add", n_in in set(g1.get_members()),
      str([n.data.alias for n in g1.get_members()]))
check("node outside the frame stays ungrouped", n_out not in set(g1.get_members()))
check("find_group_at returns topmost group under point / None otherwise",
      win_g.scene.find_group_at(_QPt(300, 250)) is g1 and win_g.scene.find_group_at(_QPt(900, 900)) is None)

# ── 3. Drag группы: члены сдвигаются на тот же дельта-сдвиг (задача #2) ──
view_g.centerOn(_QPt(380, 280)); app.processEvents()
moved_hits = []
g1.moved.connect(lambda *_a: moved_hits.append(1))
p0g = _QPt(150, 420)   # тело рамки g1 (100..600 × 100..460): НЕ угол resize, не узел
node_before = (n_in.data.x, n_in.data.y)          # (140, 140)
_QTest.mousePress(vp_g, _Qt.LeftButton, pos=_vp(view_g, p0g))
app.processEvents()
check("press over group body starts manual move-drag", g1._drag_mode == "move")
p1g = _QPt(p0g.x() + 60, p0g.y() + 40)
_QTest.mouseMove(vp_g, pos=_vp(view_g, p1g))
app.processEvents()
_QTest.mouseRelease(vp_g, _Qt.LeftButton, pos=_vp(view_g, p1g))
app.processEvents()
check("group drag moves the group by delta", abs(g1.pos().x() - 160) < 2 and abs(g1.pos().y() - 140) < 2,
      f"({g1.pos().x():.1f},{g1.pos().y():.1f})")
check("member node shifted with the group; data.x/data.y synced",
      abs(n_in.data.x - (node_before[0] + 60)) < 2 and abs(n_in.data.y - (node_before[1] + 40)) < 2,
      f"({n_in.data.x:.1f},{n_in.data.y:.1f}) want ({node_before[0]+60},{node_before[1]+40})")
check("group moved signal fired during drag", len(moved_hits) >= 1, str(moved_hits))

# ── 4. Resize: пропорциональная репозиция + кламп внутрь рамки (задача #2) ──
g2 = win_g.scene.add_group(name="resize-me", x=-900, y=-900, width=400, height=400)
n_r = win_g.scene.add_server(server_data_from_dict({"alias": "g-r", "host": "10.9.9.3", "user": "u", "x": -850, "y": -850}))
check("new group captured the node under its frame on add", n_r in set(g2.get_members()))
g2.set_group_size(800, 400)   # sx=2, sy=1: локальный (50,50) → (100,50) → сцена (-800,-850)
check("resize scales member position proportionally",
      abs(n_r.pos().x() - (-800)) < 1 and abs(n_r.pos().y() - (-850)) < 1,
      f"({n_r.pos().x():.1f},{n_r.pos().y():.1f})")
g2.set_group_size(600, 400)   # sx=0.75: локальный x 100→75 → сцена (-825,-850)
check("second resize rescales from current local coords",
      abs(n_r.pos().x() - (-825)) < 1 and abs(n_r.pos().y() - (-850)) < 1,
      f"({n_r.pos().x():.1f},{n_r.pos().y():.1f})")
# Кламп-ожидаемое считаем от фактического размера узла (шрифто-независимо):
# локальный (75, 25) → clamp [MARGIN, max(MARGIN, W - nsize - MARGIN)]
_nr_rect = n_r.sceneBoundingRect()
_exp_lx = min(max(25.0, _NG.MEMBER_MARGIN), max(_NG.MEMBER_MARGIN, 200.0 - _nr_rect.width() - _NG.MEMBER_MARGIN))
_exp_ly = min(max(25.0, _NG.MEMBER_MARGIN), max(_NG.MEMBER_MARGIN, 200.0 - _nr_rect.height() - _NG.MEMBER_MARGIN))
g2.set_group_size(200, 200)   # группа меньше узла: x клампится в [MARGIN, W-nw-M]
check("resize clamps member inside a group smaller than the node",
      abs(n_r.pos().x() - (-900 + _exp_lx)) < 1 and abs(n_r.pos().y() - (-900 + _exp_ly)) < 1,
      f"({n_r.pos().x():.1f},{n_r.pos().y():.1f}) want ({-900+_exp_lx:.1f},{-900+_exp_ly:.1f})")
check("member keeps membership after resize (center still inside)", n_r in set(g2.get_members()))

# ── 5. Выход/вход узла из рамки: членство пересчитывается на лету ──
g3 = win_g.scene.add_group(name="leave-me", x=1400, y=1400, width=400, height=400)
n_m = win_g.scene.add_server(server_data_from_dict({"alias": "g-m", "host": "10.9.9.4", "user": "u", "x": 1500, "y": 1500}))
check("node joined its group on creation", n_m in set(g3.get_members()))
n_m.setPos(2100, 2100)   # центр (2190,2165) — полностью вне всех рамок
app.processEvents()
check("moving node fully out of the frame drops membership", len(g3.get_members()) == 0,
      str([n.data.alias for n in g3.get_members()]))
n_m.setPos(1500, 1500)   # обратно внутрь
check("moving node back inside re-joins membership", n_m in set(g3.get_members()))

# ── 6. Перекрывающиеся группы: узел — только в ВЕРХНЕЙ (позднее добавленной) ──
g_top = win_g.scene.add_group(name="top-g", x=-900, y=-900, width=300, height=300)  # поверх g2
check("overlapping groups: node belongs to the topmost one only",
      n_r in set(g_top.get_members()) and n_r not in set(g2.get_members()),
      f"top={[n.data.alias for n in g_top.get_members()]} g2={[n.data.alias for n in g2.get_members()]}")
check("find_group_at prefers the later-added (top) group", win_g.scene.find_group_at(_QPt(-800, -810)) is g_top)

# ── 7. JSON: массив "groups", версия 0.8.1, round-trip + backward-compat ──
import json
win_g._dirty = False
p_groups = os.path.join(WORK, "save_v081g.json")
okg = win_g._do_save(p_groups)
with open(p_groups, encoding="utf-8") as f:
    jg = json.load(f)
check("saved JSON contains groups array with all 4 entries", okg and len(jg.get("groups", [])) == 4,
      str([g["name"] for g in jg.get("groups", [])]))
check("saved group entries carry only geometry+name (membership is derived)",
      all(set(g.keys()) == {"id", "name", "x", "y", "width", "height"} for g in jg.get("groups", [])))
check("saved JSON version bumped to 0.9 (format change: os_name/cpu_model)",
      jg.get("version") == "0.9", str(jg.get("version")))

win_g2 = MW.MainWindow()
win_g2._import_project_raw(json.load(open(p_groups, encoding="utf-8")))
check("reload restores all groups (same ids)",
      len(win_g2.scene._groups) == 4
      and {g.group_id for g in win_g2.scene._groups} == {g1.group_id, g2.group_id, g3.group_id, g_top.group_id},
      str([g.name for g in win_g2.scene._groups]))
saved_g1 = [g for g in jg["groups"] if g["id"] == g1.group_id][0]
g1_r = win_g2.scene.get_group_by_id(g1.group_id)
check("group rect+name round-trips through JSON",
      g1_r is not None and g1_r.name == "prod"
      and abs(g1_r.pos().x() - saved_g1["x"]) < 0.5 and abs(g1_r.size()[0] - saved_g1["width"]) < 0.5,
      str(g1_r.to_dict() if g1_r else None))
n_in_r = win_g2.scene._nodes.get(n_in.data.id)
check("membership reconstructed from geometry on load (node in its group)",
      n_in_r is not None and g1_r.has_member(n_in_r),
      str([n.data.alias for n in g1_r.get_members()]) if g1_r else "no group")
g2_r = win_g2.scene.get_group_by_id(g2.group_id)
g_top_r = win_g2.scene.get_group_by_id(g_top.group_id)
n_r_r = win_g2.scene._nodes.get(n_r.data.id)
check("topmost-overlap membership also reconstructed on load",
      n_r_r is not None and g_top_r.has_member(n_r_r)
      and (g2_r is None or not g2_r.has_member(n_r_r)),
      f"top={[n.data.alias for n in g_top_r.get_members()]}")

win_bc = MW.MainWindow()
old_raw = {"version": "0.8", "servers": [{"id": "old1", "alias": "a", "host": "h", "user": "u"}],
           "connections": []}  # без ключа "groups" — проекты до v0.8.1
win_bc._import_project_raw(old_raw)
check("project without 'groups' key loads fine (backward-compat)",
      len(win_bc.scene._groups) == 0 and len(win_bc.scene._nodes) == 1)

# ── 8. Путь через MainWindow: создание/имена/bool-guard/Delete-клавиша/меню ──
win_g3 = MW.MainWindow()
win_g3.show(); app.processEvents()
view_g3 = win_g3.view
vp3 = view_g3.viewport()
n_w = win_g3.scene.add_server(server_data_from_dict({"alias": "w-node", "host": "10.9.9.5", "user": "u"}))

win_g3._dirty = False
win_g3._add_group_at(_QPt(500, 400))   # центр → левый верхний (260,240) при DEFAULT_W/H 480×320
check("_add_group_at creates group centered under the point",
      len(win_g3.scene._groups) == 1 and win_g3._dirty
      and abs(win_g3.scene._groups[0].pos().x() - 260) < 0.5
      and abs(win_g3.scene._groups[0].pos().y() - 240) < 0.5,
      str([g.to_dict() for g in win_g3.scene._groups]))
gA = win_g3.scene._groups[0]

# bool из QAction.triggered (паттерн test_ssh_terminal #1): не падает, группа создаётся в центре вида
win_g3._dirty = False
try:
    win_g3._add_group_at(True)
    check("_add_group_at(True) does not raise", True)
except Exception as e:
    check("_add_group_at(True) does not raise", False, repr(e))
check("second group gets a non-duplicate default name",
      len(win_g3.scene._groups) == 2 and win_g3.scene._groups[1].name != gA.name,
      str([g.name for g in win_g3.scene._groups]))

# Delete-клавиша: выделенная группа удаляется (серверы остаются на карте; паттерн заметок)
win_g3._dirty = False
gA.setSelected(True)
from PySide6.QtGui import QKeyEvent as _QKE_g
from PySide6.QtCore import QEvent as _QEv2
view_g3.keyPressEvent(_QKE_g(_QEv2.Type.KeyPress, _Qt.Key_Delete, _Qt.NoModifier))
check("Delete key removes selected group; servers stay on the map",
      len(win_g3.scene._groups) == 1 and gA.group_id not in {g.group_id for g in win_g3.scene._groups}
      and n_w.data.id in win_g3.scene._nodes and win_g3._dirty,
      str([g.name for g in win_g3.scene._groups]))

# Меню «Правка» → Delete selected (get_selected_group-ветка _delete_selected)
gB = win_g3.scene._groups[0]   # осталась вторая группа («Группа 2»)
check("only the second group remains after key-delete", len(win_g3.scene._groups) == 1,
      str([g.name for g in win_g3.scene._groups]))
gB.setSelected(True)
win_g3._delete_selected()
check("Edit-menu delete path removes the selected group", len(win_g3.scene._groups) == 0,
      str([g.name for g in win_g3.scene._groups]))

# ── 9. Контекстное меню группы: add/rename/delete + диалог переименования ──
import graphics.map_view as _MVm_g
from PySide6.QtWidgets import QMenu as _QMenuBase, QInputDialog as _QDlg_g
captured_g = []

class _CaptureMenuG(_QMenuBase):
    def exec(self, *a, **k):      # Qt6: перехватываем — не блокируемся в offscreen
        captured_g.append(self)
        return 0
    def exec_(self, *a, **k):     # legacy-имя
        captured_g.append(self)
        return 0

def _ctx_g(view, sp):             # синтетический QContextMenuEvent (паттерн test_ssh_terminal)
    from PySide6.QtGui import QContextMenuEvent as _QCME_g
    vp_ = view.mapFromScene(sp)
    x, y = int(vp_.x()), int(vp_.y())
    ev = _QCME_g(_QCME_g.Reason.Mouse, _QPt(x, y), _QPt(x + 5, y + 5))
    view.contextMenuEvent(ev)

gC = win_g3.scene.add_group(name="ctx-g", x=100, y=600, width=400, height=300)
win_g3._connect_group_signals(gC)
_orig_menu_cls = _MVm_g.QMenu
_MVm_g.QMenu = _CaptureMenuG
try:
    captured_g.clear()
    _ctx_g(view_g3, gC.sceneBoundingRect().center())
    check("context menu over group background captured", len(captured_g) == 1)
    if captured_g:
        texts = [a.text() for a in captured_g[-1].actions()]
        check("group ctx menu has add/rename/delete actions (+ empty-space items)",
              t("ctx.add_group") in texts and t("ctx.rename_group") in texts
              and t("ctx.delete_group") in texts and t("btn.add_server") in texts, str(texts))

    # rename через действие меню + подменённый QInputDialog (headless-герметичность)
    _real_gettext = _QDlg_g.getText
    _QDlg_g.getText = staticmethod(lambda *a, **k: ("renamed-cluster", True))
    try:
        for act in captured_g[-1].actions():
            if act.text() == t("ctx.rename_group"):
                act.trigger()
                break
    finally:
        _QDlg_g.getText = _real_gettext
    check("rename action renames the group and marks dirty", gC.name == "renamed-cluster" and win_g3._dirty,
          str(gC.name))

    # delete через действие меню (без подтверждения — серверы не удаляются)
    captured_g.clear()
    _ctx_g(view_g3, gC.sceneBoundingRect().center())
    if captured_g:
        for act in captured_g[-1].actions():
            if act.text() == t("ctx.delete_group"):
                act.trigger()
                break
    check("delete action removes the group (servers remain)",
          len(win_g3.scene._groups) == 0 and n_w.data.id in win_g3.scene._nodes,
          str([g.name for g in win_g3.scene._groups]))
finally:
    _MVm_g.QMenu = _orig_menu_cls

# ── 10. Двойной клик по заголовку → renameRequested → диалог (E2E) + dirty-маркер ──
gD = win_g3.scene.add_group(name="dblclick", x=10, y=900, width=300, height=200)
win_g3._connect_group_signals(gD)
view_g3.centerOn(_QPt(60, 950)); app.processEvents()   # верхняя полоса gD в видимой области
_real_gettext2 = _QDlg_g.getText
_QDlg_g.getText = staticmethod(lambda *a, **k: ("renamed-dc", True))
try:
    _QTest.mouseDClick(vp3, _Qt.LeftButton, pos=_vp(view_g3, _QPt(40, 912)))  # верхняя полоса gD
finally:
    _QDlg_g.getText = _real_gettext2
app.processEvents()
check("double-click on group title renames it (renameRequested -> dialog)",
      gD.name == "renamed-dc", str(gD.name))
win_g3._dirty = False
gD.set_title("via-api")   # titleChanged → _mark_dirty (сигналы подключены)
check("group signals drive the window dirty marker", win_g3._dirty)

# cleanup: окна секции закрываем (паттерн win73/win_rev выше). ВАЖНО: сначала
# _dirty=False — иначе closeEvent увидит «несохранённые изменения», патченый
# question() ответит Save, и _save_project упрётся в МОДАЛЬНЫЙ QFileDialog
# (offscreen-зависание; файлов не открыто → путь Save-as).
for _w in (win_g, win_g2, win_bc, win_g3):
    try:
        _w._dirty = False
        _w.close(); _w.destroy()
    except Exception:
        pass

finish()
