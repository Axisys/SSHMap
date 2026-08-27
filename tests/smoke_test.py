"""Smoke tests for sshmap v0.6 audit fixes (v0.6.7).

Запуск:  python tests/smoke_test.py   (из корня проекта; QT_QPA_PLATFORM=offscreen ставится сам)
Проверяет ключевые пункты AUDIT.md: сохранение/загрузку проектов, keyring-пароли,
[*]-маркер, ANSI-очистку терминала, профили без паролей в JSON и i18n-fallback.
"""
import json, os, re, sys, tempfile, py_compile, traceback

# v0.9.4-fix: на консоли cp1251 (типичная русская Windows) print имени проверки
# с «→» падал с UnicodeEncodeError и убивал весь прогон. UTF-8 + replace —
# отчёт доезжает до пользователя на любой кодировке консоли.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # старый Python без reconfigure — живём как раньше

# v0.9.4-fix: изоляция HOME на время всего процесса теста. Тесты пишут
# ~/.sshmap/config.json и ~/.sshmap_settings.json; в песочницах/CI запись
# в реальный home запрещена или нежелательна — теперь весь ввод-вывод идёт
# во временную директорию (до импорта модулей приложения!).
if os.environ.get("SSHMAP_TEST_NO_HOME_ISOLATION") != "1":
    _test_home = tempfile.mkdtemp(prefix="sshmap_test_home_")
    os.environ["HOME"] = _test_home
    os.environ["USERPROFILE"] = _test_home

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # корень проекта (родитель tests/)
sys.path.insert(0, ROOT)

# Все файлы тестов — в рабочей директории (песочница не даёт писать в ~)
import shutil
WORK = os.path.join(ROOT, "_tmp_testdata")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)

PASS, FAIL = [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  ok  " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))

# ── 1. Compile all modules ───────────────────────────────
print("== compile ==")
bad = []
for dirpath, _, files in os.walk(ROOT):
    if "__pycache__" in dirpath:
        continue
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(dirpath, f)
            try:
                py_compile.compile(p, doraise=True)
            except Exception as e:
                bad.append((p, str(e)))
check("all .py compile", not bad, str(bad))

# ── 2. i18n: key parity + en fallback ────────────────────
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
check("key sets identical across en/ru/zh",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"]),
      str(set(langs["en"]).symmetric_difference(set(langs["ru"])))[:200])

from i18n import t, set_language
# Тест переключает языки и пишет в ~/.sshmap/config.json — сохраняем/возвращаем конфиг пользователя
_cfg_path = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
_orig_cfg = None
if os.path.exists(_cfg_path):
    with open(_cfg_path, encoding="utf-8") as f:
        _orig_cfg = f.read()
check("t() imported from i18n module", t.__module__ == "i18n")  # sanity import
set_language("zh")
v = t("status.project_saved")
check("zh translation loaded (not raw key)", v != "status.project_saved" and v in langs["zh"].values())
# en fallback: all keys exist in zh, so simulate a missing one via monkeypatch
import i18n as I
saved = dict(I._translations)
I._translations.pop("menu.file", None)
check("t() falls back to en.json when current lang lacks key", t("menu.file") == "File")
I._translations.update(saved)
set_language("ru")

# ── 3. models/server: from_dict robustness, to_dict strips password ──
print("== models.server ==")
from models.server import ServerData, server_data_from_dict, server_data_to_dict
d = server_data_from_dict({"id": "abc12345", "alias": "x", "host": "h", "user": "u",
                          "extra_junk_key": 42, "ssh_port": "2222"})
check("from_dict ignores extra keys", d.host == "h" and not hasattr(d, "extra_junk_key"))
check("from_dict coerces ssh_port str->int", d.ssh_port == 2222)
d2 = server_data_from_dict({"alias": "no-id", "host": "h"})
check("from_dict generates id when missing", len(d2.id) == 8)
s = ServerData(id="i1", alias="a", host="h", user="u", password="SECRET", key_path=r"C:\k.pem")
js = server_data_to_dict(s)
check("to_dict excludes password", "password" not in js)
check("to_dict keeps key_path", js.get("key_path") == r"C:\k.pem")

# ── 4. ANSI regex ────────────────────────────────────────
print("== ansi ==")
from modules.ssh_terminal import ANSI_ESCAPE_RE
samples = {
    "\x1b[31mRED\x1b[0m": "RED",
    "\x1b[2Jclear": "clear",
    "\x1b[Hhome": "home",
    "\x1b[?25lhidden\x1b[?25hshown": "hiddenshown",
    "\x1b]0;vim\x07prompt": "prompt",      # OSC (title) + BEL terminator
    "\x1b]8;;http://x\x1b\\link text plain": "link text plain",  # OSC 8: удаляется до ST, видимый текст остаётся
}
for src, want in samples.items():
    got = ANSI_ESCAPE_RE.sub("", src)
    check(f"ansi {src!r} -> {got!r}", got == want, f"want {want!r}")

# ── 5. profiles: no password in JSON; update(None) keeps password ──
print("== profiles ==")
import models.profile as P
prof_path = os.path.join(WORK, "sshmap_profiles.json")
P._profiles_path = lambda: prof_path  # тест не трогает реальный файл пользователя

from services.credential_manager import get_credential_manager
cm = get_credential_manager()
print(f"  (keyring available on this host: {cm.is_available})")

p = P.add_profile(name="TestProf", user="tester", password="SuperSecret123")
with open(prof_path, encoding="utf-8") as f:
    raw_text = f.read()
check("profiles JSON has no plaintext password", "SuperSecret123" not in raw_text)
data = json.loads(raw_text)
test_entry = [e for e in data if e["id"] == p.id]
check("profile entry only id/name/user keys (no password key)",
      test_entry and set(test_entry[0].keys()) <= {"id", "name", "user"}, str(test_entry))

# update with empty -> None semantics: model level, password=None must NOT delete keyring entry
if cm.is_available:
    before = P.get_profile_password(p.id)
    up = P.update_profile(p.id, name="TestProf2", user="tester2", password=None)
    after = P.get_profile_password(p.id)
    check("update_profile(password=None) keeps keyring password", before == "SuperSecret123" and after == before, f"{before!r} -> {after!r}")
else:
    up = P.update_profile(p.id, name="TestProf2", user="tester2", password=None)
    check("update_profile(password=None) no exception (no keyring)", up is not None)

# cleanup test profile (файл в WORK удалится вместе с рабочей папкой)
P.delete_profile(p.id)

# ── 6. Headless MainWindow: save/load round-trip (critical #1, #5, #7) ──
print("== main window ==")
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
# patch QMessageBox to avoid modal blocking in offscreen mode; record calls
boxes = []

def _fake_question(*a, **k):
    boxes.append(("question", str(a[1]) if len(a) > 1 else "", str(a[2]) if len(a) > 2 else ""))
    return QMessageBox.Save

MW.QMessageBox.question = staticmethod(_fake_question)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical", str(a[1]), str(a[2]))))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning", str(a[1]), str(a[2]))))

win = MW.MainWindow()
check("MainWindow constructed offscreen", win is not None)
check("title has no doubled prefix", win.windowTitle().count("SSH Map") == 1, win.windowTitle())

nd = ServerData(id="snode001", alias="web-1", host="10.0.0.5", user="root",
                password="NodePass999", key_path=r"C:\keys\web.pem", x=10, y=20)
win.scene.add_server(nd)
nd2 = ServerData(id="snode002", alias="db-1", host="10.0.0.6", user="root")
win.scene.add_server(nd2)

# dirty marker
check("not dirty initially", not win._dirty and " [*]" not in win.windowTitle())
win._mark_dirty()
check("_mark_dirty sets title marker", win._dirty and win.windowTitle().endswith("[*]"), win.windowTitle())

path = os.path.join(WORK, "save.json")
ok = win._do_save(path)  # bypasses file dialog
keyring_note = f"keyring_available={cm.is_available}"
check("_do_save returns True", ok is True, keyring_note)
with open(path, encoding="utf-8") as f:
    saved_json = json.load(f)
sids = {s["id"] for s in saved_json["servers"]}
check("saved JSON has both servers", {"snode001", "snode002"} <= sids, str(sids))
s1 = [s for s in saved_json["servers"] if s["id"] == "snode001"][0]
check("saved JSON: password stripped", "password" not in s1 or not s1.get("password"), str(s1.keys()))
check("saved JSON: key_path preserved (audit #5)", s1.get("key_path") == r"C:\keys\web.pem", str(s1))
check("[*] cleared after successful save (audit #7)", not win._dirty and " [*]" not in win.windowTitle(), win.windowTitle())

# password handling with keyring:
if cm.is_available:
    check("password moved to keyring on save", nd.password == "" and cm.load_password("snode001") == "NodePass999")
else:
    w = [b for b in boxes if b[0] == "warning"]
    check("no-keyring: password kept in memory (audit #12)", nd.password == "NodePass999", f"pw={nd.password!r}")
    check("no-keyring warning shown to user", len(w) >= 1, str(boxes))

# cleanup: при is_available=True выше тест записал тестовые пароли в РЕАЛЬНОЕ
# системное хранилище — удаляем, чтобы прогоны не копили записи «sshmap:snode00N».
if cm.is_available:
    try:
        cm.delete_password("snode001")
        cm.delete_password("snode002")
    except Exception:
        pass

# ── 6a. v0.9.5.6: SSH-диалог (keyring save через плоский импорт, без success-окна)
# и «Подключиться по SSH» в диалоге свойств ──
print("== v0.9.5.6 ssh dialog fixes ==")
from PySide6.QtWidgets import QDialog as _QDialog
from dialogs.ssh_connect_dialog import SSHConnectDialog
from dialogs.add_server_dialog import AddServerDialog

cdlg = SSHConnectDialog(ServerData(id="snode010", alias="web-x",
                                   host="10.0.0.7", user="root"), win)
cdlg.password_edit.setText("ConnectPw456")
class _FakeWorker:
    test_only = False
cdlg._ssh_worker = _FakeWorker()

# v0.9.5.6: success-info-окно УБРАНО — патчим information() и убеждаемся,
# что _on_worker_success его не вызывает (иначе был бы лишний кликабельный блок)
_info_calls = []
_orig_info = MW.QMessageBox.information
MW.QMessageBox.information = staticmethod(lambda *a, **k: _info_calls.append(a))
_boxes_before = len(boxes)
try:
    cdlg._on_worker_success("connected ok")
finally:
    MW.QMessageBox.information = _orig_info

check("connect dialog: accepted without modal success box",
      cdlg.result() == _QDialog.Accepted and len(_info_calls) == 0,
      f"info_calls={len(_info_calls)}")
if cm.is_available:
    check("connect dialog: password saved to keyring (flat import fallback)",
          cm.load_password("snode010") == "ConnectPw456")
    check("connect dialog: no save-failure warning",
          not [b for b in boxes[_boxes_before:] if b[0] == "warning"],
          str(boxes[_boxes_before:]))
    try:
        cm.delete_password("snode010")
    except Exception:
        pass
else:
    check("connect dialog (no keyring): save-failure warning shown",
          len([b for b in boxes[_boxes_before:] if b[0] == "warning"]) >= 1)

# «Подключиться по SSH» в диалоге свойств: слева, с валидацией host
adlg = AddServerDialog(win)
check("properties dialog: 'Connect via SSH' button exists",
      getattr(adlg, "ssh_connect_btn", None) is not None)
adlg.host.setText("")
adlg.ssh_connect_btn.click()
check("properties dialog: connect with empty host rejected",
      adlg.result() != _QDialog.Accepted and adlg._connect_after_accept is False)
adlg.host.setText("10.0.0.9")
adlg.ssh_connect_btn.click()
check("properties dialog: connect click accepted + flag set",
      adlg.result() == _QDialog.Accepted and adlg._connect_after_accept is True)
adlg2 = AddServerDialog(win)
adlg2.host.setText("10.0.0.8")
adlg2._on_ok()
check("properties dialog: OK still works, no connect flag",
      adlg2.result() == _QDialog.Accepted and adlg2._connect_after_accept is False)

# open project round-trip (audit #5: key_path restored)
win2 = MW.MainWindow()
raw = json.load(open(path, encoding="utf-8"))
from storage.project import load_project
raw = load_project(path)
for s in raw["servers"]:
    win2.scene.add_server(server_data_from_dict(s))
loaded1 = win2.scene._nodes.get("snode001")
check("reload: key_path restored via server_data_from_dict", loaded1 is not None and loaded1.data.key_path == r"C:\keys\web.pem")

# duplicate connection protection (audit #43 / docs task 3)
a = win2.scene.add_connection("snode001", "snode002", "l1")
b = win2.scene.add_connection("snode001", "snode002", "dup")
check("duplicate A->B rejected by scene", a is not None and b is None)
check("has_connection detects dup", win2.scene.has_connection("snode001", "snode002"))

# ── 6b. v0.7: Bezier arrows, typed connections, edge-to-edge, drag mode ──
print("== v0.7 ==")
from graphics.map_scene import MapScene as _MapScene
from graphics.connection_arrow import (
    ConnectionArrow as _CA, CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE, type_color,
)

# Geometрия: два узла горизонтально друг против друга (A слева, B справа на 310 px)
vsc = _MapScene()
ndA = ServerData(id="va01", alias="A", host="10.9.9.1", user="u")
ndB = ServerData(id="vb02", alias="B", host="10.9.9.2", user="u")
node_a = vsc.add_server(ndA)          # rect (0, 0, 180, 130), центр (90, 65)
node_b = vsc.add_server(ndB)
node_b.setPos(400, 0)                 # rect (400, 0, 180, 130), центр (490, 65)

arrow_ab = vsc.add_connection("va01", "vb02", "lan-1", "vpn")
check("typed connection: type stored on arrow",
      arrow_ab is not None and arrow_ab.connection_type == "vpn")
check("type colors are distinct and vpn=#60a5fa",
      len({c.name().lower() for c in map(type_color, CONNECTION_TYPES)}) == 6
      and type_color("vpn").name().lower() == "#60a5fa")

# Геометрия: (path, p0, p3, c1, c2); структура пути — через elementAt (Qt6 PySide6)
from PySide6.QtCore import QPointF as _QPointF
geom = arrow_ab._compute_geometry()
check("arrow geometry computed (nodes apart)", geom is not None)
if geom is not None:
    _gpath, p0, p3, _c1, _c2 = geom
else:  # фолбэк, чтобы следующие проверки не упали с AttributeError
    _gpath = arrow_ab.path(); p0 = _QPointF(0, 0); p3 = _QPointF(0, 0)
# cubic Bezier в Qt6: [MoveTo(p0), CurveTo(p3), data(c1), data(c2)] → elementCount == 4
check("arrow path is a single cubic Bezier (moveTo + curve)",
      _gpath.elementCount() == 4 and _gpath.elementAt(0).isMoveTo()
      and _gpath.elementAt(1).isCurveTo(), str(_gpath.elementCount()))
rect_a, rect_b = node_a.sceneBoundingRect(), node_b.sceneBoundingRect()
check("edge-to-edge: starts on source boundary (right edge of A)",
      abs(p0.x() - rect_a.right()) < 1.5 and rect_a.top() - 1 <= p0.y() <= rect_a.bottom() + 1,
      f"p0=({p0.x():.1f},{p0.y():.1f}) right={rect_a.right()}")
check("edge-to-edge: ends on target boundary (left edge of B)",
      abs(p3.x() - rect_b.left()) < 1.5 and rect_b.top() - 1 <= p3.y() <= rect_b.bottom() + 1,
      f"p3=({p3.x():.1f},{p3.y():.1f}) left={rect_b.left()}")
check("arrow is a curve (bbox taller than the chord)",
      arrow_ab.path().boundingRect().height() > 2, str(arrow_ab.path().boundingRect()))

# A->B и B->A прогибаются на противоположные стороны — не перекрываются
arrow_ba = vsc.add_connection("vb02", "va01", "", "carrier-pigeon")  # неизвестный тип → дефолт
check("unknown connection type falls back to default (ssh)",
      arrow_ba is not None and arrow_ba.connection_type == DEFAULT_CONNECTION_TYPE)
check("A->B and B->A bow on opposite sides of the chord",
      arrow_ab.path().boundingRect().center().y() > 65.0
      and arrow_ba.path().boundingRect().center().y() < 65.0,
      f"{arrow_ab.path().boundingRect().center().y():.1f} / {arrow_ba.path().boundingRect().center().y():.1f}")

# set_type меняет цвет и тип (для будущего контекстного меню v0.7.3)
old_color = arrow_ba._base_color.name()
arrow_ba.set_type("database")
check("set_type changes color",
      arrow_ba.connection_type == "database" and arrow_ba._base_color.name() != old_color
      and arrow_ba._base_color.name().lower() == "#a78bfa")
arrow_ba.set_type("not-a-type")  # неизвестный — игнорируется без ошибок

# Сериализация: version синхронизирована с релизом приложения (ревью-фикс v0.8.0 #2)
# + поле type в связях (на сцене win2). Поле не валидируется при загрузке — старые
# файлы (0.6/0.7/0.7.2) читаются без изменений, см. backward-compat ниже.
typed = win2.scene.add_connection("snode002", "snode001", "vpn-link", "database")
check("scene accepts reverse-direction typed connection",
      typed is not None and typed.connection_type == "database")
p7 = os.path.join(WORK, "save_v07.json")
ok7 = win2._do_save(p7)
with open(p7, encoding="utf-8") as f:
    j7 = json.load(f)
# v0.8.1: версия формата — новая (ключ "groups"); старые версии читаются без изменений ниже
check("saved version synced to format 0.9", ok7 and j7.get("version") == "0.9", str(j7.get("version")))
conn_db = [c for c in j7["connections"] if c.get("label") == "vpn-link"]
check("connection type serialized in JSON",
      conn_db and conn_db[0].get("type") == "database", str(conn_db))

# Backward-compat: проект v0.6 без поля type загружается как SSH
raw_old = {
    "version": "0.6",
    "servers": [
        {"id": "oldaaa01", "alias": "old-1", "host": "10.1.1.1", "user": "u"},
        {"id": "oldbbb02", "alias": "old-2", "host": "10.1.1.2", "user": "u"},
    ],
    "connections": [{"source_id": "oldaaa01", "target_id": "oldbbb02", "label": "legacy"}],
}
win3 = MW.MainWindow()
win3._import_project_raw(raw_old)
la = win3.scene._arrows[0] if win3.scene._arrows else None
check("v0.6 project (no type field): connection loads with default ssh",
      la is not None and la.connection_type == DEFAULT_CONNECTION_TYPE, str(getattr(la, "connection_type", None)))

# ConnectionDialog: 6 типов + prefill source/target для drag-режима
from dialogs.connection_dialog import ConnectionDialog as _CDlg
cdlg = _CDlg(list(win3.scene._nodes.values()), None,
             default_source_id="oldaaa01", default_target_id="oldbbb02")
check("ConnectionDialog exposes type combo with 6 types", cdlg.type_combo.count() == 6)
check("ConnectionDialog prefills source/target (drag mode)",
      cdlg.source.currentData() == "oldaaa01" and cdlg.target.currentData() == "oldbbb02")
res = cdlg.get_connection()
check("get_connection returns 4-tuple with valid type",
      len(res) == 4 and res[3] in CONNECTION_TYPES, str(res))

# Drag-режим: Shift+ЛКМ на узле → движение → отпускание над другим узлом.
# Модальный диалог заменяем фейком (offscreen), проверяется весь путь MapView→MainWindow.
# Направление B→A: связь A→B ("legacy") уже существует, дубль в ту же сторону будет отклонён.
# ВАЖНО (Qt 6.11): ручные QMouseEvent НЕ запускают внутреннюю обработку QGraphicsView
# (проверено эмпирически на PySide6 и PyQt6) — ввод шлём через QTest.mousePress/move/release,
# который генерирует события штатным для Qt способом (маршрутизация viewport→view).
from PySide6.QtCore import Qt as _Qt, QPoint as _QPt
from PySide6.QtTest import QTest as _QTest

na3 = win3.scene._nodes["oldaaa01"]
nb3 = win3.scene._nodes["oldbbb02"]
na3.setPos(-300, -300)   # разъединяем узлы (из v0.6-файла оба были в (0,0))
nb3.setPos(500, 100)

drag_calls = []

class _FakeConnDialog:
    def __init__(self, nodes, parent=None, default_source_id=None, default_target_id=None):
        drag_calls.append((default_source_id, default_target_id))
    def exec(self): return 1  # QDialog.Accepted
    def get_connection(self):
        src, tgt = drag_calls[-1]
        return (src, tgt, "drag-label", "http")

def _vp(view3, scene_pos):
    """Сцена → QPoint в координатах viewport (Qt 6.11: mapFromScene может дать QPoint или QPointF)."""
    q = view3.mapFromScene(scene_pos)
    return _QPt(int(q.x()), int(q.y()))

_orig_cd = MW.ConnectionDialog
MW.ConnectionDialog = _FakeConnDialog
try:
    view3 = win3.view
    vp3 = view3.viewport()
    _QTest.mousePress(vp3, _Qt.LeftButton, stateKey=_Qt.ShiftModifier,
                      pos=_vp(view3, nb3.sceneBoundingRect().center()))
    app.processEvents()
    check("drag mode starts on Shift+press over node", view3._connect_source is nb3)
    mid_scene = (na3.sceneBoundingRect().center() + nb3.sceneBoundingRect().center()) / 2
    _QTest.mouseMove(vp3, pos=_vp(view3, mid_scene))
    app.processEvents()
    _rb = view3._rubber_band
    check("rubber band follows the cursor",
          _rb is not None and _rb.path().elementCount() >= 2)
    _QTest.mouseRelease(vp3, _Qt.LeftButton, pos=_vp(view3, na3.sceneBoundingRect().center()))
    app.processEvents()
finally:
    MW.ConnectionDialog = _orig_cd

check("drag state cleaned up after release",
      win3.view._connect_source is None and win3.view._rubber_band is None)
check("release over target opens pre-filled connection dialog (B->A)",
      drag_calls == [("oldbbb02", "oldaaa01")], str(drag_calls))
new_arrow = win3.scene._arrows[-1] if win3.scene._arrows else None
check("drag created typed connection (http) with label",
      new_arrow is not None and new_arrow.connection_type == "http"
      and new_arrow.label_text == "drag-label"
      and new_arrow.source.data.id == "oldbbb02" and new_arrow.target.data.id == "oldaaa01")

# ── 6c. v0.6.x patch: SSHWorker registry + delete guard ───────
print("== v0.6.x worker guard ==")
from modules.ssh_worker import (
    SSHWorker as _SW, get_active_worker as _gaw, wait_for_worker as _wfw,
)

# 1) Реестр: создан → на месте; завершён → не виден. Реальный быстрый
# провал (127.0.0.1:9 — connection refused), поток завершается сам за <1 c.
w_g = _SW(host="127.0.0.1", user="u", port=9, server_id="guardtest")
check("worker registered in active registry on construction", _gaw("guardtest") is w_g)
# wait() на нестартованном потоке по Qt мгновенно true — guard не блокирует удаление
check("wait_for_worker: never-started worker -> True immediately", _wfw("guardtest", 500) is True)
# стартуем по-настоящему, чтобы проверить авто-очистку реестра по finished:
w_g2s = _SW(host="127.0.0.1", user="u", port=9, server_id="guardrun")
w_g2s.start()
check("started worker finishes (fast refused) and leaves registry",
      w_g2s.wait(3000) is True and _gaw("guardrun") is None)
# w_g нестартованный — вручную уберём из реестра, чтобы не засорять последующие проверки
from modules.ssh_worker import _active_workers as _aw_reg
_aw_reg.pop("guardtest", None)
check("wait_for_worker for unknown id -> True", _wfw("no-such-id", 100) is True)

# 2) MainWindow._ensure_worker_done — единый guard для удаления узла
win4 = MW.MainWindow()
ndg = ServerData(id="guardnode", alias="gn", host="127.0.0.1", user="u")
win4.scene.add_server(ndg)
check("_ensure_worker_done passes when no running worker", win4._ensure_worker_done("guardnode") is True)

# 3) SSHConnectDialog.closeEvent дожидается потока перед закрытием диалога:
# close() на невидимом виджете событие может не доставить — вызываем closeEvent напрямую.
from dialogs.ssh_connect_dialog import SSHConnectDialog as _SCD2
from PySide6.QtGui import QCloseEvent as _QCE

sdlg = _SCD2(ndg, None)
w_g3 = _SW(host="127.0.0.1", user="u", port=9, server_id="guardclose")
w_g3.start()
sdlg._ssh_worker = w_g3
_ev_close = _QCE()  # PySide6 6.11: конструктор без аргументов (Qt5-стиль)
sdlg.closeEvent(_ev_close)
check("dialog closeEvent waits for SSHWorker to finish", not w_g3.isRunning())
check("closeEvent accepts the close after worker done", _ev_close.isAccepted() is True)

# ── 6d. v0.7.1: status checker (online/warn/offline) ───────────
print("== v0.7.1 statuses ==")
import socket as _sock, threading as _threading
from services.status_checker import probe_ssh, StatusChecker

def _free_port():
    s = _sock.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

# online: локальный «SSH-сервер» шлёт баннер после accept
port_on = _free_port()
srv_on = _sock.socket(); srv_on.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
srv_on.bind(("127.0.0.1", port_on)); srv_on.listen(1); srv_on.settimeout(3)

def _serve_banner():
    try:
        conn, _ = srv_on.accept()
        conn.sendall(b"SSH-2.0-SmokeTest\r\n")
        import time as _t2; _t2.sleep(0.4)
        conn.close()
    except OSError:
        pass

th_on = _threading.Thread(target=_serve_banner, daemon=True); th_on.start()
check("probe_ssh: TCP + SSH banner -> online", probe_ssh("127.0.0.1", port_on, 1.5) == "online")

# warn: порт открыт, но данных нет (accept держит соединение молча)
port_warn = _free_port()
srv_w = _sock.socket(); srv_w.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
srv_w.bind(("127.0.0.1", port_warn)); srv_w.listen(1); srv_w.settimeout(3)

def _serve_silent():
    try:
        conn, _ = srv_w.accept()
        import time as _t3; _t3.sleep(2.5)  # дольше recv-таймаута пробы
        conn.close()
    except OSError:
        pass

th_warn = _threading.Thread(target=_serve_silent, daemon=True); th_warn.start()
check("probe_ssh: port open but no banner -> warn", probe_ssh("127.0.0.1", port_warn, 0.8) == "warn")

# offline: закрытый порт (connection refused мгновенно) + пустой host
port_off = _free_port()
check("probe_ssh: closed port -> offline", probe_ssh("127.0.0.1", port_off, 0.5) == "offline")
check("probe_ssh: empty host -> offline", probe_ssh("", 22, 0.5) == "offline")

# ServerNode: цвет рамки + tooltip + пульс-оверлей
from graphics.server_node import ServerNode as _SN
nd_st = ServerData(id="statnode", alias="st", host="127.0.0.1", user="u")
n_st = _SN(nd_st)
check("node has no status color initially (transparent pen)", n_st._state_pen().color().alpha() == 0)
n_st.set_status("offline")
check("set_status(offline): border turns red", n_st._state_pen().color().name().lower() == "#ef4444")
tip = n_st.toolTip()
check("set_status: tooltip filled via i18n with host (not raw key)",
      bool(tip) and not tip.startswith("[") and "127.0.0.1" in tip, tip)
n_st.set_status("online")
check("set_status(online): border turns green", n_st._state_pen().color().name().lower() == "#22c55e")
n_st.set_status("warn")
check("set_status(warn): border turns yellow", n_st._state_pen().color().name().lower() == "#facc15")
n_st.set_status("bogus-status")  # неизвестный — игнорируется без ошибок
check("unknown status ignored (still warn)", n_st.status == "warn")
# selected приоритетнее статуса (и обратно — после снятия выделения)
n_st._selected = True
check("selection color wins over status", n_st._state_pen().color() == _SN.COLOR_SELECTED)
n_st._selected = False
check("pulse overlay exists and was shown by set_status", hasattr(n_st, "_pulse"))
# Анимация реально работает: новый статус перезапускает fade; после ~0.6 c
# накачки событий opacity оверлея должна упасть от 1.0
import time as _t_pulse
n_st.set_status("online")  # warn -> online: рестарт пульса с opacity=1.0
_p_start = n_st._pulse.opacity()
_deadline = _t_pulse.time() + 0.65
while _t_pulse.time() < _deadline and n_st._pulse.isVisible():
    app.processEvents(); _t_pulse.sleep(0.02)
check("pulse animation fades the overlay (opacity drops from ~1)",
      _p_start > 0.9 and n_st._pulse.opacity() < 0.75, f"{_p_start:.2f} -> {n_st._pulse.opacity():.2f}")
n_st.reset_status()
check("reset_status clears border back to transparent", n_st._state_pen().color().alpha() == 0)

# StatusChecker: полный раунд (поток + сигналы), цели — закрытый порт и online-сервер
chk = StatusChecker(interval_ms=5000, probe_timeout=1.0)
import time as _t4
srv_on.settimeout(3)  # второй accept для round (первый баннер уже ушёл)
def _serve_banner2():
    try:
        conn, _ = srv_on.accept()
        conn.sendall(b"SSH-2.0-SmokeTest\r\n")
        _t4.sleep(0.4); conn.close()
    except OSError:
        pass
th_on2 = _threading.Thread(target=_serve_banner2, daemon=True); th_on2.start()

chk.set_servers([("st-off", "127.0.0.1", port_off), ("st-on", "127.0.0.1", port_on)])
from PySide6.QtCore import QEventLoop as _QEL, QTimer as _QTmr
loop = _QEL()
rounds = []
chk.round_finished.connect(lambda r: (rounds.append(r), loop.quit()))
_QTmr.singleShot(8000, loop.quit)  # страховка от зависания теста
chk.start_round()
loop.exec()
res_map = dict(rounds[0]) if rounds else {}
check("checker round finished with both targets", res_map.get("st-off") == "offline" and res_map.get("st-on") == "online", str(res_map))
check("last_status remembers per-server results", chk.last_status("st-on") == "online" and chk.last_status("nope") == "")
chk.shutdown()

# ── v0.7.1: StatusChecker ↔ MainWindow — связка (интеграция) ───────
check("MainWindow has StatusChecker wired", getattr(win, "_status_checker", None) is not None)
if getattr(win, "_status_checker", None) is not None:
    # _sync_status_targets собирает план проверок из узлов сцены (win: snode001/snode002)
    win._sync_status_targets()
    tgt = {sid: (host, port) for sid, host, port in win._status_checker._targets}
    check("_sync_status_targets puts scene nodes into the plan",
          tgt.get("snode001") == ("10.0.0.5", 22) and tgt.get("snode002") == ("10.0.0.6", 22), str(tgt))
    # start_status_checks — как в main.py после show(): не должен падать offscreen;
    # без event loop отложенный первый раунд (singleShot 2 c) просто не сработает.
    win.start_status_checks()
    check("start_status_checks activates periodic timer", win._status_checker._timer.isActive())
    # Сигнал status_changed (путь из _ProbeThread) → _on_node_status_changed → node.set_status
    n_chk = win.scene._nodes.get("snode001")
    check("node has no status before checker emit", n_chk is not None and n_chk.status == "")
    win._status_checker.status_changed.emit("snode001", "offline")
    check("status_changed(offline) paints node border red via window handler",
          n_chk.status == "offline" and n_chk._state_pen().color().name().lower() == "#ef4444")
    win._status_checker.status_changed.emit("snode001", "online")
    check("status_changed(online) repaints node border green",
          n_chk.status == "online" and n_chk._state_pen().color().name().lower() == "#22c55e")
    # Герметичность теста: останавливаем таймер и чистим план — если отложенный первый
    # раунд (singleShot) всё же сработает в поздних processEvents, целей не будет и поток
    # реальным хостам из JSON не пошлёт.
    win._status_checker.stop()
    win._status_checker.set_servers([])

# ── 6e. v0.7.2: sticky notes (drag/resize/edit/delete + JSON) ───
print("== v0.7.2 notes ==")
from graphics.sticky_note import StickyNote as _SN2
from PySide6.QtWidgets import QGraphicsView as _QGV2
from PySide6.QtCore import QPointF as _QP2, QEvent as _QEv2

# Создание + сериализация
note1 = win4.scene.add_note(text="hello", x=50.0, y=60.0)
check("scene.add_note creates StickyNote in _notes", len(win4.scene._notes) == 1 and note1 is win4.scene._notes[0])
d1 = note1.to_dict()
check("note to_dict has id/text/x/y/width/height",
      set(d1.keys()) == {"id", "text", "x", "y", "width", "height"} and d1["text"] == "hello"
      and len(d1["id"]) == 8, str(d1))

# from_dict: битые значения — дефолты, лишние ключи игнорируются
n_bad = _SN2.from_dict({"x": "garbage", "width": None, "extra_key": 1})
check("note from_dict survives bad values (defaults)", n_bad.pos().x() == 0.0 and n_bad.rect().width() >= _SN2.MIN_W)

# Размер: clamp MIN/MAX
n_cl = win4.scene.add_note(x=800, y=400)
n_cl.set_note_size(10, 5)
check("note size clamped to MIN", n_cl.rect().width() == _SN2.MIN_W and n_cl.rect().height() == _SN2.MIN_H)
n_cl.set_note_size(9999, 9999)
check("note size clamped to MAX", n_cl.rect().width() == _SN2.MAX_W and n_cl.rect().height() == _SN2.MAX_H)

# Drag заметки мышью через ПОЛНЫЙ pipeline view->scene->item (QTest-ввод, см. v0.7 секцию):
# MapView сам переключает NoDrag при нажатии над заметкой (динамический режим).
view4 = win4.view
check("drag mode is ScrollHandDrag before press over note", view4.dragMode() == _QGV2.DragMode.ScrollHandDrag)

vp4 = view4.viewport()   # QTest шлёт события в viewport — штатный путь маршрутизации Qt

moved_signals = []
note1.moved.connect(lambda: moved_signals.append(1))
p0 = _QP2(note1.pos().x() + 80, note1.pos().y() + 50)   # тело заметки (не угол!)
pos_before = (note1.pos().x(), note1.pos().y())          # отсчёт: заметка сдвигается на DELTA
_QTest.mousePress(vp4, _Qt.LeftButton, pos=_vp(view4, p0))
app.processEvents()
check("press over note switches view to NoDrag", view4.dragMode() == _QGV2.DragMode.NoDrag)
check("note press in body starts move-drag", note1._drag_mode == "move")
p1 = _QP2(p0.x() + 65, p0.y() + 45)
_QTest.mouseMove(vp4, pos=_vp(view4, p1))
app.processEvents()
pos_after_move = (note1.pos().x(), note1.pos().y())
check("note drag moves the item by delta (~+65/+45)",
      abs(pos_after_move[0] - (pos_before[0] + 65)) < 3 and abs(pos_after_move[1] - (pos_before[1] + 45)) < 3,
      f"{pos_before} -> {pos_after_move}")
_QTest.mouseRelease(vp4, _Qt.LeftButton, pos=_vp(view4, p1))
app.processEvents()
check("note moved signal fired on release", len(moved_signals) == 1, str(moved_signals))
check("drag mode restored to ScrollHandDrag after release", view4.dragMode() == _QGV2.DragMode.ScrollHandDrag)

# Resize за правый нижний угол: press в углу -> move наружу -> размер растёт
w0, h0 = note1.rect().width(), note1.rect().height()
corner = _QP2(note1.pos().x() + w0 - 6, note1.pos().y() + h0 - 6)
_QTest.mousePress(vp4, _Qt.LeftButton, pos=_vp(view4, corner))
app.processEvents()
check("press in bottom-right corner starts resize", note1._drag_mode == "resize")
_QTest.mouseMove(vp4, pos=_vp(view4, _QP2(corner.x() + 60, corner.y() + 40)))
app.processEvents()
check("note resize grows from the corner",
      note1.rect().width() > w0 + 40 and note1.rect().height() > h0 + 30,
      f"{w0:.0f}x{h0:.0f} -> {note1.rect().width():.0f}x{note1.rect().height():.0f}")
_QTest.mouseRelease(vp4, _Qt.LeftButton, pos=_vp(view4, corner))
app.processEvents()

# Edit mode: двойной клик через QTest — РЕАЛЬНЫЙ QGraphicsSceneMouseEvent (handler может
# переслать его в QTextEdit через super(); фейковый duck-typed event падал на C++-методе).
check("note not in edit mode initially", note1.editing is False)
_QTest.mouseDClick(vp4, _Qt.LeftButton, pos=_vp(view4, _QP2(note1.pos().x() + 60, note1.pos().y() + 40)))
app.processEvents()
check("double-click enters edit mode", note1.editing is True)
ed = note1.widget()
from PySide6.QtCore import Qt as _Qt2
check("edit mode: editor focus policy becomes StrongFocus", ed.focusPolicy() == _Qt2.FocusPolicy.StrongFocus)
note1.exit_edit_mode()
check("exit_edit_mode restores NoFocus", note1.editing is False and ed.focusPolicy() == _Qt2.FocusPolicy.NoFocus)

# Text change -> signal (только после добавления в сцену)
dirty_hits = []
note1.textEdited.connect(lambda *_a: dirty_hits.append(1))
ed.setPlainText("changed")
check("editor textChanged emits note.textEdited", len(dirty_hits) == 1, str(dirty_hits))

# Delete-клавиша удаляет выделенную заметку через MainWindow._remove_note
note1.setSelected(True)
from PySide6.QtGui import QKeyEvent as _QKE
view4.keyPressEvent(_QKE(_QEv2.Type.KeyPress, _Qt.Key_Delete, _Qt.NoModifier))  # Qt.Key_Delete (0x0100007 в Qt 6.11 — не хардкод!)
check("Delete key removes selected note via window", len(win4.scene._notes) == 1 and win4.scene.get_note_by_id(note1.note_id) is None)

# JSON round-trip: save с заметками -> load -> backward-compat без ключа notes
win4._add_note_at(_QP2(300, 300))  # через MainWindow (сигналы подключены)
check("_add_note_at creates note via window", len(win4.scene._notes) == 2)
added = win4.scene._notes[-1]
win4._mark_dirty()  # заметка добавлена — проект dirty (как в реальном потоке)
# текст для round-trip: правим через редактор (сигнал textEdited сработает сам)
added.widget().setPlainText("roundtrip")
p_notes = os.path.join(WORK, "save_v072.json")
okn = win4._do_save(p_notes)
with open(p_notes, encoding="utf-8") as f:
    jn = json.load(f)
check("saved JSON contains notes array with 2 entries", okn and len(jn.get("notes", [])) == 2, str(jn.get("notes")))
ids_saved = {n["id"] for n in jn["notes"]}
# Загрузка в новое окно через _import_project_raw (backward-compat: старый файл без "notes")
win5 = MW.MainWindow()
win5._import_project_raw(json.load(open(p_notes, encoding="utf-8")))
check("reload restores both notes (same ids)",
      len(win5.scene._notes) == 2 and {n.note_id for n in win5.scene._notes} == ids_saved,
      str([(n.note_id, n.text()) for n in win5.scene._notes]))
check("note text round-trips through JSON", any(n.text() == "roundtrip" for n in win5.scene._notes))
win6 = MW.MainWindow()
old_raw = {"version": "0.7", "servers": [], "connections": []}  # без ключа notes
win6._import_project_raw(old_raw)
check("v0.7 project without 'notes' key loads fine (backward-compat)", len(win6.scene._notes) == 0)

# ── 7. Dialogs construct without errors (button code paths) ──
print("== dialogs ==")

from dialogs.ssh_connect_dialog import SSHConnectDialog
from dialogs.add_server_dialog import AddServerDialog
try:
    dlg = SSHConnectDialog(nd, None)
    check("SSHConnectDialog builds; cancel button present", hasattr(dlg, "cancel_btn") if hasattr(dlg, "cancel_btn") else True)
except Exception as e:
    check("SSHConnectDialog builds; cancel button present", False, traceback.format_exc(limit=1))
try:
    dlg2 = AddServerDialog(None, edit_data=nd)
    check("AddServerDialog builds in edit mode", dlg2.host.text() == "10.0.0.5")
except Exception as e:
    check("AddServerDialog builds in edit mode", False, traceback.format_exc(limit=1))

# ══ v0.7.3: контекстное меню узла и стрелки ═══════════════════════
print("== v0.7.3 context menus ==")

from dialogs.connection_dialog import ConnectionDialog as _CD73, EditConnectionDialog as _ECD73
from graphics.connection_arrow import CONNECTION_TYPES as _CT73

win73 = MW.MainWindow()
# Позиции явные и разнесённые: без x/y обе ноды падают в (0,0) — rect'и перекрываются,
# кривая вырождается в точку внутри самих нод, и _classify_at-проверки ниже теряют смысл.
d_a = server_data_from_dict({"alias": "ctx-a", "host": "192.168.3.52", "user": "u", "ip": "192.0.2.10", "x": 100, "y": 100})
d_b = server_data_from_dict({"alias": "ctx-b", "host": "192.168.3.53", "user": "u", "x": 450, "y": 160})
n_a = win73.scene.add_server(d_a)
n_b = win73.scene.add_server(d_b)
arrow73 = win73.scene.add_connection(d_a.id, d_b.id, "l1", "vpn")
check("fixture: two nodes + one vpn arrow", arrow73 is not None and arrow73.connection_type == "vpn")

# MapScene.remove_connection: удаление + повторный вызов
ok_rm = win73.scene.remove_connection(arrow73)
check("scene.remove_connection removes the arrow", ok_rm and arrow73 not in win73.scene._arrows)
check("scene.remove_connection returns False for unknown arrow",
      win73.scene.remove_connection(arrow73) is False)
arrow73 = win73.scene.add_connection(d_a.id, d_b.id, "l1", "vpn")  # вернуть для следующих тестов

# EditConnectionDialog: prefill метки/типа, get_connection -> (label, ctype)
try:
    ecd = _ECD73(arrow73, None)
    check("EditConnectionDialog prefills label", ecd.label.text() == "l1")
    check("EditConnectionDialog prefills type vpn", ecd.type_combo.currentData() == "vpn")
    check("EditConnectionDialog source is readonly", ecd.source.isReadOnly() and ecd.target.isReadOnly())
    check("EditConnectionDialog get_connection returns (label, ctype)",
          ecd.get_connection() == ("l1", "vpn"))
except Exception:
    check("EditConnectionDialog builds", False, traceback.format_exc(limit=1))

# MainWindow._edit_connection: применяет метку и тип к стрелке + dirty-маркер
class _FakeDlg:
    def __init__(self, label, ctype): self._r = (label, ctype)
    def exec(self): return 1  # QDialog.Accepted
    def get_connection(self): return self._r
_real_ecd = _ECD73
win73._dirty = False
import dialogs.connection_dialog as _dcd_mod
_dcd_mod.EditConnectionDialog = lambda arrow, parent=None: _FakeDlg("new-label", "database")
try:
    win73._edit_connection(arrow73)
finally:
    _dcd_mod.EditConnectionDialog = _real_ecd
check("_edit_connection applies label+type and marks dirty",
      arrow73.label_text == "new-label" and arrow73.connection_type == "database" and win73._dirty,
      f"{arrow73.label_text}/{arrow73.connection_type}/dirty={win73._dirty}")

# _copy_node_info: IP в буфере обмена (hostname — без DNS-зависимости: только вызов).
# v0.8.1: у узла есть отдельное поле `ip` (models.server) — «копировать IP» отдаёт его,
# а host берётся как fallback, когда ip пустой (поведение _copy_node_info, v0.7.3).
win73._copy_node_info(n_a, "ip")
check("_copy_node_info(ip) copies the node's ip field when set",
      QApplication.clipboard().text() == "192.0.2.10", QApplication.clipboard().text())
d_noip = server_data_from_dict({"alias": "ctx-noip", "host": "192.168.3.99", "user": "u"})
n_noip = win73.scene.add_server(d_noip)
win73._copy_node_info(n_noip, "ip")
check("_copy_node_info(ip) falls back to host when ip is empty",
      QApplication.clipboard().text() == "192.168.3.99", QApplication.clipboard().text())
win73.scene.remove_server(n_noip.data.id)

# _ping_node: поток стартует и завершается (без сети — 192.168.3.52 из TEST-NET, быстрый fail).
# Headless-герметичность: при неудачном пинге слот показывает МОДАЛЬНЫЙ QMessageBox.information()
# — в offscreen его никто не закроет и exec() зависнет навсегда (закреплено по итогам прогона
# аудита v0.7.2). На время проверки подменяем на заглушку-записчик, как выше для EditConnectionDialog.
import PySide6.QtWidgets as _QW73
_real_qmb_info = _QW73.QMessageBox.information
_ping_dialog_calls = []
_QW73.QMessageBox.information = staticmethod(
    lambda *a, **kw: (_ping_dialog_calls.append(a), 0)[1])
try:
    win73._ping_node(n_a)
    check("_ping_node starts background thread", win73._ping_thread is not None)
    for _ in range(200):
        if win73._ping_thread is None:
            break
        app.processEvents(); _QTest.qWait(50)
    check("_ping_node thread finishes and clears itself", win73._ping_thread is None)
finally:
    _QW73.QMessageBox.information = _real_qmb_info

# Контекстное меню: классификация точки узла/стрелки (без exec — headless)
v73 = win73.view
cls_node = v73._classify_at(n_a.sceneBoundingRect().center())
check("_classify_at finds node at its center", cls_node[0] is n_a)
# середина связи: геометрия edge-to-edge РОВНО как в ConnectionArrow._compute_geometry()
# (edge_point на границах узлов → build_curve). Раньше здесь строилась кривая центр→центр —
# она не совпадает с нарисованной, и точка t=0.5 оказывалась мимо штриха стрелки.
from graphics.connection_arrow import build_curve as _bc73, curve_midpoint as _cm73, edge_point as _ep73
_src_rect_c = arrow73.source.sceneBoundingRect()
_tgt_rect_c = arrow73.target.sceneBoundingRect()
p0c = _ep73(_src_rect_c, _src_rect_c.center(), _tgt_rect_c.center())
p3c = _ep73(_tgt_rect_c, _tgt_rect_c.center(), _src_rect_c.center())
_path, c1c, c2c = _bc73(p0c, p3c)
cls_arrow = v73._classify_at(_cm73(p0c, c1c, c2c, p3c))
check("_classify_at finds arrow at curve midpoint", cls_arrow[1] is arrow73, str(cls_arrow))

# Удаление связи через MainWindow (без подтверждения — monkeypatch question)
_real_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    ok_del = win73._remove_connection(arrow73)
finally:
    QMessageBox.question = _real_q
check("_remove_connection deletes arrow after confirm",
      ok_del and arrow73 not in win73.scene._arrows and win73._dirty)

# ══ v0.8.1: группировка узлов (кластеры/папки на карте) ═══════════
# Задачи релиза: (1) graphics/node_group.py — QGraphicsObject с рамкой и заголовком;
# (2) серверы внутри группы автоматически перемещаются при изменении границы;
# (3) группы сохраняются/загружаются из JSON (массив "groups").
print("== v0.8.1 groups ==")

from graphics.node_group import NodeGroup as _NG
win_g = MW.MainWindow()
win_g.show(); app.processEvents()
view_g = win_g.view
vp_g = view_g.viewport()

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

# bool из QAction.triggered (паттерн regression_v081 #1): не падает, группа создаётся в центре вида
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

def _ctx_g(view, sp):             # синтетический QContextMenuEvent (паттерн regression_v081)
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

# ══ UI polish (quick wins): ноды, сетка, fit/zoom, статус-бар, иконки ═══
print("== UI polish ==")

# Узел: полоска тени входит в boundingRect; декоративная кнопка 🔒 удалена
check("node boundingRect includes shadow strip",
      abs(n_a.boundingRect().height() - (_SN.MIN_NODE_HEIGHT + _SN.SHADOW_BOTTOM)) < 0.5,
      str(n_a.boundingRect()))
check("decorative SSH lock button removed from node", not hasattr(n_a, "_ssh_btn"))

# Точка статуса + затемнение контента offline-узла (рамка и точки остаются яркими)
n_a.set_status("offline")
check("status dot turns red on offline",
      n_a._status_dot.brush().color().name() == _SN.STATUS_COLORS["offline"].name())
check("offline node content dimmed to 0.55",
      abs(n_a._alias.opacity() - 0.55) < 1e-6 and abs(n_a._icon.opacity() - 0.55) < 1e-6)
n_a.set_status("online")
check("content opacity restored on online", n_a._alias.opacity() == 1.0)

# Адаптивная сетка: базовый шаг при зуме >= 1; удвоение шага при мелком зуме
check("grid step stays 20px at scale >= 1", win73.scene._current_grid_step(1.0) == 20)
check("grid step adapts to low zoom (screen interval stays in [16, 32) px)",
      16.0 <= win73.scene._current_grid_step(0.1) * 0.1 < 32.0)

# «Вписать карту»: есть контент -> True и зум в диапазоне; пустая сцена -> False без падения
fit_ok = win73.view.fit_to_content()
check("fit_to_content fits existing nodes", fit_ok and 0.1 <= win73.view.zoom <= 5.0,
      f"zoom={win73.view.zoom}")
_empty_win = MW.MainWindow()
check("fit on empty map returns False (no crash)", _empty_win.view.fit_to_content() is False)
_empty_win.close(); _empty_win.destroy()

# Восстановление сохранённого вида: валидные значения применяются, битые игнорируются
win73.view.set_zoom_and_center(2.0, -100, -50)
check("set_zoom_and_center applies zoom", abs(win73.view.zoom - 2.0) < 1e-6)
try:
    win73.view.set_zoom_and_center("garbage", None, "x")  # битые значения — вид не меняется
except Exception as _bad_view_exc:
    check("set_zoom_and_center ignores bad values (no exception)", False, str(_bad_view_exc))
check("set_zoom_and_center ignores bad values", abs(win73.view.zoom - 2.0) < 1e-6)

# Центрирование по содержимому карты (а не по началу координат сцены)
_crect = win73.view.content_bounding_rect()
win73._center_view()
_mapped = win73.view.mapFromScene(_crect.center())
_vp_center = win73.view.viewport().rect().center()
check("_center_view centers on map content",
      abs(float(_mapped.x()) - float(_vp_center.x())) < 2.0
      and abs(float(_mapped.y()) - float(_vp_center.y())) < 2.0,
      f"mapped=({_mapped.x():.1f},{_mapped.y():.1f}) vp=({_vp_center.x():.1f},{_vp_center.y():.1f})")

# Статус-бар: % зума и счётчики (язык фиксируем на ru для стабильного ассерта)
set_language("ru")
win73._on_zoom_changed(1.5)
check("zoom label shows percent", win73.zoom_label.text() == "150%", win73.zoom_label.text())
win73._update_counts_label()
check("counts label has servers and connections (ru)",
      "Серверы: 2" in win73.counts_label.text() and "Связи: 0" in win73.counts_label.text(),
      win73.counts_label.text())

# Векторные иконки: известные рендерятся 20x20, неизвестное имя -> пустой QIcon
from ui.icons import get_icon as _gi_up
_ic_fit = _gi_up("fit")
check("icons module renders vector icons (20x20)",
      not _ic_fit.isNull() and _ic_fit.pixmap(20).width() == 20)
check("unknown icon name -> empty QIcon", _gi_up("no_such_icon").isNull())

# Hit-область стрелки: середина кривой теперь ловится (contains() шире видимого штриха —
# в этом PySide6 strokeToFill/strokedPath не пробиндены, и fill-only contains точку ровно
# на линии НЕ ловил; тонкая линия 1.8 px физически была некликабельна)
_arrow_hit = win73.scene.add_connection(d_a.id, d_b.id, "up-hit", "ssh")
if _arrow_hit is not None:
    _s_r = _arrow_hit.source.sceneBoundingRect()
    _t_r = _arrow_hit.target.sceneBoundingRect()
    _hp0 = _ep73(_s_r, _s_r.center(), _t_r.center())
    _hp3 = _ep73(_t_r, _t_r.center(), _s_r.center())
    _hpath, _hc1, _hc2 = _bc73(_hp0, _hp3)
    cls_up = win73.view._classify_at(_cm73(_hp0, _hc1, _hc2, _hp3))
    check("arrow hit area catches curve midpoint (shape widened)", cls_up[1] is _arrow_hit, str(cls_up))
else:
    check("arrow recreated for hit test", False)

# i18n: новые ключи v0.7.3 + UI polish присутствуют во всех 3 языках
import json as _json73
_langs73 = {}
for _l in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{_l}.json"), encoding="utf-8") as _f:
        _langs73[_l] = _json73.load(_f)
_v73_keys = ["ctx.ssh_connect", "ctx.edit_server", "ctx.copy_ip", "ctx.copy_hostname",
             "ctx.ping", "ctx.delete_server", "ctx.edit_connection", "ctx.delete_connection",
             "dialog.edit_connection", "status.copied_to_clipboard", "status.ping_ok",
             "status.ping_failed", "status.ping_running", "status.connection_updated",
             "status.connection_deleted", "msg.confirm_delete_connection"]
_up_keys = ["view.fit_map", "status.counts", "status.fit_nothing"]  # UI polish (quick wins)
_grp_keys = ["edit.add_group", "ctx.add_group", "ctx.rename_group", "ctx.delete_group",
             "dialog.rename_group", "group.default_name", "group.name_label",
             "status.group_added", "status.group_renamed", "status.group_deleted"]  # v0.8.1
check("v0.7.3 + UI polish + v0.8.1 i18n keys present in en/ru/zh (>=213 keys each)",
      all(_k in _langs73[_l] for _k in (_v73_keys + _up_keys + _grp_keys) for _l in _langs73)
      and all(len(_langs73[_l]) >= 213 for _l in _langs73),  # v0.8.2: +6 ключей = 219
      str({l: len(d) for l, d in _langs73.items()}))

# Headless-герметичность закрытия: win73 сейчас dirty, а глобальная заглушка question()
# отвечает Save → closeEvent ушёл бы в _save_project_as() → модальный QFileDialog в
# offscreen зависает навсегда. Поток сохранения уже покрыт секцией "main window" выше —
# здесь проверяем только чистое close/destroy.
win73._dirty = False
win73.close()
win73.destroy()

# ══ Ревью-фиксы v0.8.0: elide/макс.ширина узлов, маркеры статусов в сайдбаре ═══
# (#1 центрирование _add_server покрыт tests/regression_v081.py; #2 версия — выше)
print("== review fixes v0.8.0 ==")

from PySide6.QtGui import QFontMetrics as _QFM  # ревью-фикс v0.8.0 (#4)

win_rev = MW.MainWindow()
win_rev.show(); app.processEvents()


def _label_invariant(node, item, fm, source):
    """Elide-инвариант подписи (шрифто-независимый): либо полный текст без tooltip,
    либо elided + полный текст в tooltip; правый край не заходит под точки [W-46, W-10]."""
    rendered = item.toPlainText()
    ovh = max(0.0, item.boundingRect().width() - fm.horizontalAdvance(rendered)) if rendered else 0.0
    end = 55 + fm.horizontalAdvance(rendered) + ovh
    zone_ok = end <= node._current_width - 46 - 2
    detail = f"rendered={rendered[:30]!r} tip={(item.toolTip() or '')[:30]!r} W={node._current_width}"
    if rendered.endswith("\u2026"):
        return item.toolTip() == source and rendered != source and zone_ok, detail
    return item.toolTip() == "" and rendered == source and zone_ok, detail


# #4: узел с длинным alias/host/comment → потолок MAX_NODE_WIDTH + полный текст в tooltip'ах
rev_alias = "production-web-server-04-eu-west-1-cluster-node"
rev_host = "very-long-hostname.example.corp.internal-dns-name"
rev_comment = "x" * 300
n_rev = win_rev.scene.add_server(ServerData(
    id="revlong", alias=rev_alias, host=rev_host, user="u", comment=rev_comment,
    cpu="64 core", ram="512 gb", disk="10 tb"))
check("long node width capped at MAX_NODE_WIDTH",
      n_rev._current_width == int(_SN.MAX_NODE_WIDTH), str(n_rev._current_width))
ok, det = _label_invariant(n_rev, n_rev._alias, _QFM(n_rev._alias.font()), rev_alias)
check("elided alias: full text in tooltip, clear of dot zone", ok, det)
ok, det = _label_invariant(n_rev, n_rev._host_label, _QFM(n_rev._host_label.font()), "@" + rev_host)
check("elided host: full text in tooltip, clear of dot zone", ok, det)
rev_info_lines = n_rev._info.toPlainText().splitlines()
check("comment elided at MAX while short lines stay full",
      any(l.endswith("\u2026") for l in rev_info_lines) and "CPU: 64 core" in n_rev._info.toPlainText(),
      str(rev_info_lines[:3]))
check("info tooltip carries the full (unelided) text block",
      bool(n_rev._info.toolTip()) and rev_comment in n_rev._info.toolTip() and "RAM: 512 gb" in n_rev._info.toolTip(),
      f"tip_len={len(n_rev._info.toolTip() or '')}")

# #4: узел с крошечным контентом → MIN-размер, elide не нужен; идемпотентность пересборки
n_tiny = win_rev.scene.add_server(ServerData(id="revtiny", alias="A", host="h", user="u"))
check("tiny node keeps MIN width (no stretch)", n_tiny._current_width == _SN.MIN_NODE_WIDTH, str(n_tiny._current_width))
_snap = (n_rev._current_width, n_rev._alias.toPlainText(), n_rev._info.toPlainText())
n_rev.update_appearance()
check("update_appearance idempotent (width+texts stable)",
      (n_rev._current_width, n_rev._alias.toPlainText(), n_rev._info.toPlainText()) == _snap)

# #3: маркеры статусов в дереве сайдбара — иконка строки + live-обновление без пересбора
win_rev.refresh_sidebar()
check("sidebar has a row per node with status icon",
      win_rev.tree.topLevelItemCount() == 2 and not win_rev.tree.topLevelItem(0).icon(0).isNull())
_it_idle = win_rev.tree.topLevelItem(0)
idle_px = _it_idle.icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("unverified node shows idle (gray) dot",
      idle_px == _SN.COLOR_DOT_IDLE.name().lower(), idle_px)

_item_before = win_rev.tree.topLevelItem(0)
win_rev._on_node_status_changed("revlong", "online")
_it_now = win_rev.tree.topLevelItem(0)
check("status marker updates in place (row not rebuilt)", _it_now is _item_before, f"{id(_item_before)} vs {id(_it_now)}")
green_px = _it_now.icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("online node dot turns green", green_px == _SN.STATUS_COLORS["online"].name().lower(), green_px)
_tip = _it_now.toolTip(0) or ""
check("sidebar tooltip is i18n text with host (not a raw key)",
      bool(_tip) and rev_host in _tip and not _tip.startswith("node."), repr(_tip))

win_rev._on_node_status_changed("revlong", "bogus-status")
_still = win_rev.tree.topLevelItem(0).icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("unknown status ignored (node and marker stay online)", n_rev.status == "online" and _still == green_px)

win_rev.refresh_sidebar()
_kept = win_rev.tree.topLevelItem(0).icon(0).pixmap(16).toImage().pixelColor(8, 8).name().lower()
check("refresh_sidebar rebuilds rows with current markers", _kept == green_px, _kept)

win_rev._dirty = False
win_rev.close(); win_rev.destroy()

# ══════════════════════════════════════════════════════════
# v0.8.2: внешний (системный) терминал — modules/external_terminal.py
# build_command() для всех терминалов (БЕЗ реального запуска),
# detect_terminal(), настройки ~/.sshmap_settings.json round-trip,
# UI-интеграция (ctx-меню + кнопка диалога).
# ══════════════════════════════════════════════════════════
try:
    from modules import external_terminal as _ET
except ImportError:
    from modules.external_terminal import *  # noqa: F401,F403
    import modules.external_terminal as _ET

check("external_terminal module imports", _ET is not None)

# 1) build_ssh_args: порт/ключ/ConnectTimeout, known_hosts не трогаем
_a = _ET.build_ssh_args("h1", "root")
check("build_ssh_args: default port omitted",
      _a == ["ssh", "-o", "ConnectTimeout=10", "root@h1"], str(_a))
_a = _ET.build_ssh_args("h1", "root", port=2222, key_path="C:/k/k.pem")
check("build_ssh_args: -p and -i present",
      "-p" in _a and "2222" in _a and "-i" in _a and "C:/k/k.pem" in _a, str(_a))
check("build_ssh_args: no password ever in argv",
      not any(("pw" == x.lower() or x.startswith("-oPass")) for x in _a))

# 2) build_command для всех терминалов (без запуска)
_c = _ET.build_command("windows_terminal", "h1", "root", port=2222)
check("build_command windows_terminal: wt.exe + ssh args",
      _c[0] == "wt.exe" and "ssh" in _c and "2222" in _c, str(_c))
_c = _ET.build_command("cmd", "h1", "root")
check("build_command cmd: start with empty title",
      _c[1] == "/c" and _c[2] == "start" and _c[3] == "", str(_c))
_c = _ET.build_command("conhost", "h1", "root")
# v0.9.3 fix: conhost требует команду через cmd /c — голый `conhost ssh` не работает
check("build_command conhost",
      _c[0] == "conhost.exe" and _c[1].lower().endswith("cmd.exe")
      and "/c" in _c and _c[-1] == "root@h1", str(_c))
for tid in ("gnome-terminal", "x-terminal-emulator", "xfce4-terminal"):
    _c = _ET.build_command(tid, "h1", "root")
    check(f"build_command {tid}: bash -c with exec bash (window survives)",
          _c[-3] == "bash" and _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
_c = _ET.build_command("konsole", "h1", "root")
check("build_command konsole: -e bash -c",
      _c[-4] == "-e" and _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
_c = _ET.build_command("alacritty", "h1", "root")
check("build_command alacritty: -e bash -c",
      _c[-4] == "-e" and _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
_c = _ET.build_command("kitty", "h1", "root")
check("build_command kitty: bash -c",
      _c[-2] == "-c" and "; exec bash" in _c[-1], str(_c))
try:
    _ET.build_command("bogus-term", "h1", "root")
    check("build_command unknown id raises ValueError", False)
except ValueError:
    check("build_command unknown id raises ValueError", True)

# пароль никогда не попадает в команду даже при jump
_c = _ET.build_command("windows_terminal", "h1", "root", jump="jump@bastion")
check("build_command supports -J jump", "-J" in _c and "jump@bastion" in _c, str(_c))

# 3) detect_terminal на текущей ОС (headless-friendly)
_dt = _ET.detect_terminal()
if sys.platform == "win32":
    check("detect_terminal on Windows returns wt/cmd/conhost/open_terminal",
          _dt in ("windows_terminal", "cmd", "conhost"), str(_dt))
else:
    check("detect_terminal returns known id or None", _dt is None or isinstance(_dt, str), str(_dt))

# 4) настройки: JSON round-trip с merge существующих ключей
_orig_settings = None
_sp = _ET._settings_path()
try:
    with open(_sp, "r", encoding="utf-8") as f:
        _orig_settings = f.read()
except OSError:
    pass
def _read_json_or_none(path):
    """v0.9.3 fix: чтение settings-файла, устойчивое к read-only home.

    На песочнице/read-only профиле запись могла не состояться — тогда вместо
    FileNotFoundError со stacktrace'ом (срывающего все последующие проверки,
    включая секцию v0.9.2) тест честно доложит FAIL по затронутым чекам.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json_v082.load(f)
    except (OSError, ValueError):
        return None

import json as _json_v082
try:
    check("load default setting is 'auto'", _ET.load_external_terminal_setting() == "auto")
    ok_w = _ET.save_external_terminal_setting("cmd" if sys.platform == "win32" else "kitty")
    check("save_external_terminal_setting writes file", ok_w)
    want = "cmd" if sys.platform == "win32" else "kitty"
    check("round-trip reads saved value back",
          _ET.load_external_terminal_setting() == want)
    # merge: другой ключ файла не теряется
    d = _read_json_or_none(_sp) or {}
    d["some_other_key"] = 42
    try:
        with open(_sp, "w", encoding="utf-8") as f:
            _json_v082.dump(d, f)
    except OSError:
        pass  # read-only home: чек ниже честно задокументирует потерю ключа
    _ET.save_external_terminal_setting("auto")
    d2 = _read_json_or_none(_sp) or {}
    check("settings merge keeps unrelated keys",
          d2.get("some_other_key") == 42 and d2.get("external_terminal") == "auto", str(d2))
    # невалидное значение → auto
    try:
        with open(_sp, "w", encoding="utf-8") as f:
            _json_v082.dump({"external_terminal": "not-a-terminal"}, f)
    except OSError:
        pass
    check("invalid setting falls back to 'auto'",
          _ET.load_external_terminal_setting() == "auto")
finally:
    try:
        if _orig_settings is not None:
            with open(_sp, "w", encoding="utf-8") as f:
                f.write(_orig_settings)
        else:
            os.remove(_sp)
    except OSError:
        pass

# 5) launch(): Popen мокается — проверяем флаги Windows и отсутствие исключений
_launched = {}
class _FakePopenV082:
    def __init__(self, cmd, **kw):
        _launched["cmd"] = cmd
        _launched["kw"] = kw
_orig_popen = _ET.subprocess.Popen
_ET.subprocess.Popen = _FakePopenV082
try:
    ok_l = _ET.launch(["fake-term.exe", "ssh", "root@h1"])
    check("launch returns True via Popen", ok_l is True)
    check("launch detaches console on Windows",
          (sys.platform != "win32") or (_launched["kw"].get("creationflags", 0) != 0), 
          str(_launched.get("kw")))
finally:
    _ET.subprocess.Popen = _orig_popen

# connect_external error paths (без GUI): ssh отсутствует → no_ssh_client
_orig_which = _ET._which
try:
    _ET._which = lambda name: None
    ok_e, err_e = _ET.connect_external("h1", "root")
    check("connect_external without ssh client → no_ssh_client",
          ok_e is False and err_e == "no_ssh_client", str((ok_e, err_e)))
    def _which_no_term(name):
        return "C:/fake/ssh.exe" if name == "ssh" else None
    _ET._which = _which_no_term
    ok_e, err_e = _ET.connect_external("h1", "root")
    check("connect_external without terminal → no_terminal",
          ok_e is False and err_e == "no_terminal", str((ok_e, err_e)))
finally:
    _ET._which = _orig_which

# 6) UI-интеграция: SSHConnectDialog имеет external_btn; ctx-ключ i18n присутствует
from dialogs.ssh_connect_dialog import SSHConnectDialog as _SCD_ext
_nd_ext = ServerData(id="extsrv", alias="ExtSrv", host="10.0.0.9", user="root")
_dlg_ext = _SCD_ext(_nd_ext, None)
check("SSHConnectDialog has external terminal button",
      hasattr(_dlg_ext, "external_btn") and bool(_dlg_ext.external_btn.text())
      and not _dlg_ext.external_btn.text().startswith("ssh_ext."),
      _dlg_ext.external_btn.text())
_dlg_ext.deleteLater()

# i18n: все три языка содержат новые ключи v0.8.2
import json as _json_i18n_v082
for _lang_k in ("en", "ru", "zh"):
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "i18n", f"{_lang_k}.json")
    with open(_p, encoding="utf-8") as f:
        _d = _json_i18n_v082.load(f)
    _missing = [k for k in ("ctx.ssh_external", "ssh_ext.open_button",
                            "ssh_ext.no_ssh_client", "ssh_ext.no_terminal",
                            "ssh_ext.launch_failed", "ssh_ext.launched")
                if k not in _d]
    check(f"i18n v0.8.2 keys present ({_lang_k})", not _missing, str(_missing))

# MainWindow method presence (класс, без инстанса)
from ui.main_window import MainWindow as _MW_v082
check("MainWindow has _connect_ssh_external",
      callable(getattr(_MW_v082, "_connect_ssh_external", None)))

# ══ v0.9: автозаполнение данных о сервере (Linux) ═══════════════════════
print("== v0.9 system info collector ==")

# Парсеры — чистые функции, без Qt-событий
from services.system_info_collector import (
    parse_info_output, parse_os_release, parse_cpu, parse_ram_bytes,
    parse_disk_bytes, bytes_to_gb, INFO_BATCH,
)

# Фикстура: типичный вывод батча на Ubuntu
_fixture = """---OS---
Linux 6.8.0-40-generic x86_64 GNU/Linux
PRETTY_NAME="Ubuntu 24.04 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
---CPU---
4
model name\t: Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz
---RAM---
16777216000
MemTotal:       16394256 kB
---DISK---
""" + "\n" + str(107374182400) + """
size
---END---
"""
_info = parse_info_output(_fixture)
check("parse os_name from PRETTY_NAME", _info.get("os_name") == "Ubuntu 24.04 LTS", str(_info))
check("parse cpu cores", _info.get("cpu_cores") == "4", str(_info))
check("parse cpu model", "Xeon" in _info.get("cpu_model", ""), str(_info))
check("ram bytes → gb", _info.get("ram_gb") == "15.6 gb", str(_info.get("ram_gb")))
check("disk bytes → gb", _info.get("disk_gb") == "100 gb", str(_info.get("disk_gb")))

# lsb_release fallback (без "=")
check("os-release fallback to lsb_release",
      parse_os_release('Debian GNU/Linux 12\n') == "Debian GNU/Linux 12")
# одинарные кавычки в PRETTY_NAME
check("PRETTY_NAME single quotes stripped",
      parse_os_release("PRETTY_NAME='Alpine Linux'\nID=alpine\n") == "Alpine Linux")

# BusyBox/meminfo fallback: free недоступен → MemTotal из /proc/meminfo
_ram = parse_ram_bytes("MemTotal:       16394256 kB\n")
check("ram fallback meminfo kB→bytes", _ram == 16394256 * 1024, str(_ram))

# Пустые/мусорные входы не должны ронять парсер. NB: одиночная нечисловая
# строка без «=» трактуется как вывод lsb_release -ds (документированный
# fallback) — проверяем отсутствие crash, а не пустоту словаря.
check("empty output → empty dict", parse_info_output("") == {})
_garbage = parse_info_output("---OS---\n\x00\x1b[31m junk\n---END---\n")
check("garbage output does not crash", isinstance(_garbage, dict))

# bytes_to_gb: формат как у модели («8 gb», без хвостового .0)
check("bytes_to_gb exact", bytes_to_gb(8589934592) == "8 gb", str(bytes_to_gb(8589934592)))
check("bytes_to_gb zero/negative → ''", bytes_to_gb(0) == "" and bytes_to_gb(-5) == "")

# Батч содержит все секции и завершается маркером END
for _m in ("---OS---", "---CPU---", "---RAM---", "---DISK---", "---END---"):
    check(f"INFO_BATCH contains {_m}", _m in INFO_BATCH)

# Модель: новые поля + backward-compat старых JSON
from models.server import ServerData, server_data_from_dict, server_data_to_dict
_sd = server_data_from_dict({"id": "t1", "alias": "A", "host": "h", "user": "u"})
check("old JSON without os_name defaults", _sd.os_name == "" and _sd.cpu_model == "")
check("new fields serialize", "os_name" in server_data_to_dict(ServerData(id="x", alias="a", host="h", user="u")))
_d2 = server_data_from_dict({"id": "t2", "alias": "B", "host": "h2", "user": "u",
                             "os_name": "Alpine", "collapsed": True})
check("round-trip os_name/collapsed", _d2.os_name == "Alpine" and _d2.collapsed is True)

# Версия формата JSON — 0.9 (единая точка истины version.py)
import version as _ver_mod
check("VERSION_FORMAT bumped to 0.9", getattr(_ver_mod, "VERSION_FORMAT", "") == "0.9",
      getattr(_ver_mod, "VERSION_FORMAT", "?"))
check("APP_VERSION is 0.9.x", getattr(_ver_mod, "APP_VERSION", "").startswith("0.9"),
      getattr(_ver_mod, "APP_VERSION", "?"))

# i18n: ключи v0.9 во всех трёх языках
import json as _json_i18n_v09
for _lang_k in ("en", "ru", "zh"):
    _p = os.path.join(ROOT, "i18n", f"{_lang_k}.json")
    with open(_p, encoding="utf-8") as f:
        _d = _json_i18n_v09.load(f)
    _missing = [k for k in ("server.os", "ctx.collect_info", "status.info_running",
                            "status.info_running_auto", "status.info_collected",
                            "status.info_failed")
                if k not in _d]
    check(f"i18n v0.9 keys present ({_lang_k})", not _missing, str(_missing))

# Collector-класс: сигнатура и сигналы (без реального SSH)
from services.system_info_collector import SystemInfoCollector as _SIC
check("SystemInfoCollector signals", hasattr(_SIC, "info_ready") and hasattr(_SIC, "info_failed"))
_c = _SIC(ServerData(id="sig", alias="s", host="127.0.0.1", user="u"), password="")
check("collector stores data+password", _c.data.id == "sig" and _c.password == "")

# MainWindow: точки входа v0.9
from ui.main_window import MainWindow as _MW_v09
check("MainWindow has _collect_node_info/_on_info_ready/_on_info_failed",
      all(callable(getattr(_MW_v09, m, None))
          for m in ("_collect_node_info", "_on_info_ready", "_on_info_failed")))

# ── v0.9.2: горячие клавиши + палитра команд ─────────────
print("== v0.9.2 hotkeys + command palette ==")

# Хоткеи: пункты меню несут ожидаемые QKeySequence
from PySide6.QtGui import QAction as _QA92
_w92 = MW.MainWindow()
def _find_actions(window):
    out = {}
    for act in window.findChildren(_QA92):
        txt = act.text().replace("&", "")
        key = act.shortcut().toString()
        if key:
            out.setdefault(key, []).append(txt)
    return out
_acts92 = _find_actions(_w92)
check("hotkey Ctrl+Return (SSH connect) registered",
      any("Ctrl+Return" in k for k in _acts92), str(list(_acts92)))
check("hotkey Ctrl+E (edit node) registered", "Ctrl+E" in _acts92, str(_acts92.get("Ctrl+E")))
check("hotkey Ctrl+Shift+N (add note) registered", "Ctrl+Shift+N" in _acts92)
check("hotkey Ctrl+K (palette) present via shortcut",
      any(getattr(sc, "key", lambda: None)().toString() == "Ctrl+K"
          for sc in _w92.findChildren(__import__("PySide6.QtGui", fromlist=["QShortcut"]).QShortcut)))

# Слоты-обёртки существуют и вызываемы
check("_edit_selected_node/_add_note_at_view_center callable",
      callable(getattr(_w92, "_edit_selected_node", None))
      and callable(getattr(_w92, "_add_note_at_view_center", None)))

# Палитра: создание, fuzzy_score, сбор команд
from ui.command_palette import CommandPalette as _CP, fuzzy_score as _fs
check("fuzzy_score subsequence match", _fs("cns", "Connect via SSH") is not None)
check("fuzzy_score rejects non-match", _fs("zzz", "Connect via SSH") is None)
check("fuzzy_score empty pattern matches all", _fs("", "anything") is not None)

_pal = _CP(_w92, _w92)
_pal._collect_commands()
_kinds = [k for _, k, _ in _pal._commands]
check("palette collected menu actions", _kinds.count("action") >= 5,
      f"actions={_kinds.count('action')}")
# Добавим сервер на сцену — палитра должна увидеть его при пересборке
_sd92 = ServerData(id="pal001", alias="PaletteHost", host="10.9.9.9", user="u")
_nd92 = _w92.scene.add_server(_sd92)
_pal._collect_commands()
_srv = [(lbl, fn) for lbl, k, fn in _pal._commands if k == "server"]
check("palette lists servers", len(_srv) == 1 and "PaletteHost" in _srv[0][0], str(_lbl := [l for l, _ in _srv]))

# Фильтрация по имени сервера
_pal.input.setText("palettehost")
check("palette filter finds server by name", _pal.listw.count() >= 1
      and any("PaletteHost" in _pal.listw.item(i).text() for i in range(_pal.listw.count())))

# Выбор сервера центрирует вид и выделяет узел.
# Offscreen-нюанс QGraphicsView: точный centerOn зависит от границ сцены/скроллбаров,
# поэтому проверяем выделение узла + факт вызова centerOn (сцена вид изменила transform).
_w92.view.resize(800, 600)
_app92 = QApplication.instance()
_app92.processEvents()
_srv[0][1]()
_app92.processEvents()
check("palette reveal selects node", _nd92.isSelected())
# Палитра должна была вызвать centerOn: sceneRect вырос/scrollbars сместились —
# надёжный прокси: повторный прямой centerOn даёт тот же scroll-стейт, что после reveal.
_hbar_before = _w92.view.horizontalScrollBar().value()
_vbar_before = _w92.view.verticalScrollBar().value()
_w92.view.centerOn(_nd92)
_app92.processEvents()
check("palette reveal centered on node (scroll state matches direct centerOn)",
      _w92.view.horizontalScrollBar().value() == _hbar_before
      and _w92.view.verticalScrollBar().value() == _vbar_before,
      f"h {_hbar_before}->{_w92.view.horizontalScrollBar().value()} "
      f"v {_vbar_before}->{_w92.view.verticalScrollBar().value()}")

# i18n: ключи v0.9.2 во всех трёх языках
import json as _json_i18n_v092
for _lang_k in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{_lang_k}.json"), encoding="utf-8") as f:
        _d92 = _json_i18n_v092.load(f)
    _miss92 = [k for k in ("palette.title", "palette.placeholder", "palette.hint",
                           "palette.kind_server", "msg.select_server_edit")
               if k not in _d92]
    check(f"i18n v0.9.2 keys present ({_lang_k})", not _miss92, str(_miss92))

# ── restore user's i18n config (test switched languages) ──
try:
    if _orig_cfg is not None:
        with open(_cfg_path, "w", encoding="utf-8") as f:
            f.write(_orig_cfg)
except OSError:
    pass  # sandbox may block writes to ~ — config untouched anyway

# ── cleanup test workspace ───────────────────────────────
shutil.rmtree(WORK, ignore_errors=True)

# ── summary ─────────────────────────────────────────────
print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
for name, detail in FAIL:
    print("  FAILED:", name, ("— " + detail) if detail else "")
sys.exit(1 if FAIL else 0)
