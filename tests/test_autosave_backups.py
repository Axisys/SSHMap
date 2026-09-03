"""Регрессия v0.9.7 — автосохранение + кольцевой буфер бэкапов проекта.

ROADMAP v0.9.7:
  #1 Автосохранение в ~/.sshmap/autosave/ (интервал из конфига, дефолт ~60 c,
     только при dirty и при открытом файле проекта).
  #2 Кольцевой буфер бэкапов (N файлов, дефолт 10) при каждом ручном save —
     откат на предыдущие версии файла.
  #3 Восстановление при открытии: если autosave свежее файла — предложение
     восстановить (до подмены содержимого).

Запуск:  python tests/test_autosave_backups.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import tempfile
import time as _time

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

# Сеть в тестах запрещена: пробы статусов возвращают результат мгновенно
# (иначе _load_project_at → start_round плодил бы потоки с сетевыми таймаутами).
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import storage.autosave as A
from i18n import t as it, save_config
from models.server import ServerData
import ui.main_window as MW

import shutil
WORK = os.path.join(ROOT, "_tmp_testdata_v097")
shutil.rmtree(WORK, ignore_errors=True)  # чистый старт (паттерн smoke_test): остатки прошлых прогонов не должны влиять
os.makedirs(WORK, exist_ok=True)
# v1.1.2 final (N12): при ВЫХОДЕ каталог тоже чистится (rmtree перед finish() внизу) —
# после прогона сьюта на диске ничего не остаётся.

# ══ storage.autosave: чистый модуль (без Qt) ════════════════════════════════
print("== project_key ==")
_orig_cwd = os.getcwd()
try:
    k_abs = A.project_key(os.path.join(WORK, "map.json"))
    os.chdir(WORK)
    k_rel = A.project_key("map.json")
finally:
    os.chdir(_orig_cwd)
check("project_key: относительный и абсолютный путь → один ключ", k_abs == k_rel,
      f"{k_abs} vs {k_rel}")
check("project_key: разные каталоги → разные ключи (одноимённые файлы)",
      A.project_key(os.path.join(WORK, "a.json")) != A.project_key(os.path.join(WORK, "sub", "a.json")))

print("== autosave round-trip ==")
p = os.path.join(WORK, "rt", "map.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, "w", encoding="utf-8") as f:
    json.dump({"version": "0.9", "servers": []}, f)
A.write_autosave(p, {"version": "0.9", "servers": [{"id": "x"}]})
check("write_autosave → файл в ~/.sshmap/autosave/", os.path.isfile(A.autosave_path_for(p)),
      A.autosave_path_for(p))
data = A.read_autosave(p)
check("read_autosave round-trip (содержимое совпадает)",
      data is not None and data["servers"] == [{"id": "x"}], str(data))
with open(A.autosave_path_for(p), "w", encoding="utf-8") as f:
    f.write("{not json")
check("повреждённый autosave → read_autosave None (без исключения)", A.read_autosave(p) is None)

print("== autosave_is_newer ==")
now = _time.time()
os.utime(A.autosave_path_for(p), (now - 100, now - 100))
os.utime(p, (now, now))
check("autosave СТАРЕЕ файла → не «свежее»", A.autosave_is_newer(p) is False)
os.utime(A.autosave_path_for(p), (now + 100, now + 100))
check("autosave НОВЕЕ файла → «свежее» (ROADMAP #3)", A.autosave_is_newer(p) is True)

print("== rotate_backups: кольцевой буфер ==")
q = os.path.join(WORK, "ring", "map.json")
os.makedirs(os.path.dirname(q), exist_ok=True)

def _save(v):
    with open(q, "w", encoding="utf-8") as f:
        json.dump({"v": v}, f)

def _slot(n):
    with open(A.backup_path_for(q, n), encoding="utf-8") as f:
        return json.load(f)["v"]

# 5 сохранений при N=3: каждое save предшествует rotate «до» перезаписи
_save("v1"); A.rotate_backups(q, 3)
_save("v2"); A.rotate_backups(q, 3)
_save("v3"); A.rotate_backups(q, 3)
_save("v4"); A.rotate_backups(q, 3)
_save("v5")
check("кольцо N=3: слот1 = версия перед текущей (v4)", _slot(1) == "v4", str(_slot(1)))
check("кольцо N=3: слот2 = v3", _slot(2) == "v3", str(_slot(2)))
check("кольцо N=3: слот3 = v2", _slot(3) == "v2", str(_slot(3)))
check("кольцо N=3: переполнение (v1) удалено — слота 4 нет",
      not os.path.isfile(A.backup_path_for(q, 4)))
with open(q, encoding="utf-8") as f:
    check("файл проекта = текущая версия (v5)", json.load(f)["v"] == "v5")

items = A.list_backups(q, 3)
check("list_backups: свежие первыми, ровно 3 записи", [i["slot"] for i in items] == [1, 2, 3],
      str([i["slot"] for i in items]))
check("list_backups: mtime/size на месте", all(i["mtime"] > 0 and i["size"] > 0 for i in items))

print("== restore_to_project ==")
A.restore_to_project(A.backup_path_for(q, 3), q)  # v2 обратно в файл
with open(q, encoding="utf-8") as f:
    check("restore копирует бэкап обратно в файл проекта", json.load(f)["v"] == "v2")
check("источник-бэкап не тронут после restore", _slot(3) == "v2")
try:
    A.restore_to_project(os.path.join(WORK, "nope.json"), q)
    check("отсутствующий источник → FileNotFoundError", False, "исключение не брошено")
except FileNotFoundError:
    check("отсутствующий источник → FileNotFoundError", True)

print("== get_autosave_settings (конфиг ~/.sshmap/config.json) ==")
s = A.get_autosave_settings()
check("дефолты: вкл / 60 c / 10 бэкапов (ROADMAP v0.9.7)",
      s == {"enabled": True, "interval_sec": 60, "backup_count": 10}, str(s))
save_config({"autosave_enabled": False, "autosave_interval_sec": "abc", "backup_count": -5})
s2 = A.get_autosave_settings()
check("битые значения → дефолт/граница (enabled=False читается)",
      s2 == {"enabled": False, "interval_sec": 60, "backup_count": 1}, str(s2))
save_config({"autosave_enabled": True, "autosave_interval_sec": 30, "backup_count": 5})
s3 = A.get_autosave_settings()
check("свои значения из конфига (30 c / 5 бэкапов)",
      s3["enabled"] is True and s3["interval_sec"] == 30 and s3["backup_count"] == 5, str(s3))

# ══ MainWindow: ручные save → кольцевой буфер ═══════════════════════════════
print("== MainWindow: save → бэкапы ==")
win = MW.MainWindow()
win.show(); app.processEvents()
view = win.view
view.resize(900, 700); app.processEvents()

proj_dir = os.path.join(WORK, "app")
os.makedirs(proj_dir, exist_ok=True)
proj_path = os.path.join(proj_dir, "map.json")

win.scene.add_server(ServerData(id="a7b1", alias="web-1", host="127.0.0.1", user="ops", x=100, y=100))
win.scene.add_server(ServerData(id="a7b2", alias="db-1", host="127.0.0.1", user="dba", x=300, y=100))
win._dirty = True
check("первый save нового файла succeeds", win._do_save(proj_path) is True)
# как _save_project_as: успешный save-as запоминает файл проекта
win._project_file = proj_path
with open(proj_path, encoding="utf-8") as f:
    check("файл записан (2 сервера)", len(json.load(f)["servers"]) == 2)
check("первый save: бэкапов ещё нет (предыдущей версии не было)", A.list_backups(proj_path) == [])

win.scene.add_server(ServerData(id="a7b3", alias="cache-1", host="127.0.0.1", user="redis", x=500, y=100))
win._dirty = True
check("второй save succeeds", win._do_save(proj_path) is True)
slots = A.list_backups(proj_path)
with open(slots[0]["path"], encoding="utf-8") as f:
    check("после 2-го save: слот1 = предыдущая версия (2 сервера)",
          len(slots) == 1 and len(json.load(f)["servers"]) == 2, str([i["slot"] for i in slots]))

win.scene.add_server(ServerData(id="a7b4", alias="mq-1", host="127.0.0.1", user="mq", x=700, y=100))
win._dirty = True
check("третий save succeeds", win._do_save(proj_path) is True)
slots = A.list_backups(proj_path)
with open(slots[0]["path"], encoding="utf-8") as f:
    s1 = len(json.load(f)["servers"])
with open(slots[1]["path"], encoding="utf-8") as f:
    s2 = len(json.load(f)["servers"])
check("после 3-го save: кольцо [слот1=3 сервера, слот2=2] свежие первыми",
      len(slots) == 2 and s1 == 3 and s2 == 2, f"slots={[i['slot'] for i in slots]} {s1}/{s2}")

# ══ MainWindow: автосохранение по тикам (ROADMAP #1) ════════════════════════
print("== autosave tick ==")
win.scene.add_server(ServerData(id="a7b5", alias="lb-1", host="127.0.0.1", user="nginx", x=900, y=100))
win._dirty = True
win._autosave_tick()
auto_p = A.autosave_path_for(proj_path)
check("тик при dirty пишет ~/.sshmap/autosave/<key>.json", os.path.isfile(auto_p), auto_p)
auto_data = A.read_autosave(proj_path)
check("автосохранение = текущая сцена (5 серверов)",
      auto_data is not None and len(auto_data["servers"]) == 5,
      str(None if auto_data is None else len(auto_data["servers"])))
check("паролей в автосохранении нет (server_data_to_dict вырезает)",
      auto_data is not None and all("password" not in s for s in auto_data["servers"]))

win._dirty = False
app.processEvents()
_mtime_before = os.path.getmtime(auto_p)
win._autosave_tick()
check("тик при clean НЕ перезаписывает (только dirty — ROADMAP #1)",
      os.path.getmtime(auto_p) == _mtime_before)

# новый проект БЕЗ файла — автосохранять не на что (ROADMAP #3 привязана к файлу)
_auto_files_before = len(os.listdir(A.AUTOSAVE_DIR))
win_ns = MW.MainWindow()
win_ns.scene.add_server(ServerData(id="ns01", alias="orphan", host="127.0.0.1", user="x", x=1, y=1))
win_ns._dirty = True
win_ns._autosave_tick()
_auto_files_after = len(os.listdir(A.AUTOSAVE_DIR))
check("нет файла проекта → тик автосохранения — no-op", _auto_files_before == _auto_files_after,
      f"{_auto_files_before} -> {_auto_files_after}")

# ══ Открытие: autosave свежее файла → предложение (ROADMAP #3) ═══════════════
print("== open: autosave newer → prompt ==")
with open(proj_path, encoding="utf-8") as f:
    check("предикат: файл=4 сервера, автосохранение=5 и новее",
          len(json.load(f)["servers"]) == 4 and A.autosave_is_newer(proj_path))

_q_orig = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    win2 = MW.MainWindow()
    ok2 = win2._load_project_at(proj_path)
    app.processEvents()
    check("«Да» → сцена загружена из автосохранения (5 серверов)",
          ok2 is True and len(win2.scene.nodes()) == 5, f"nodes={len(win2.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
try:
    win3 = MW.MainWindow()
    ok3 = win3._load_project_at(proj_path)
    app.processEvents()
    check("«Нет» → сцена загружена из файла (4 сервера)",
          ok3 is True and len(win3.scene.nodes()) == 4, f"nodes={len(win3.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

# ══ Диалог бэкапов + откат на предыдущие версии (ROADMAP #2) ════════════════
print("== backups dialog + restore ==")
items = win._backup_items()
check("_backup_items: автосохранение + 2 слота, свежие первыми",
      len(items) == 3
      and items[0]["label"] == it("backups.autosave")
      and items[1]["label"] == it("backups.backup", n=1)
      and items[2]["label"] == it("backups.backup", n=2),
      str([i["label"] for i in items]))

import dialogs.backups_dialog as BD
dlg = BD.BackupsDialog(items, parent=win)
check("BackupsDialog: 3 строки", dlg.item_count() == 3, str(dlg.item_count()))
emitted = []
dlg.restore_requested.connect(lambda p, l: emitted.append((p, l)))
rows = [dlg.tree.topLevelItem(i) for i in range(3)]
dlg.tree.setCurrentItem(rows[2])  # самый старый слот (2 сервера)
dlg._emit_restore()
app.processEvents()
check("BackupsDialog emit restore_requested(path, label)",
      emitted == [(items[2]["path"], items[2]["label"])], str(emitted))
dlg.reject()

# полный путь: откат на слот1 (3 сервера) поверх dirty-проекта — подтверждение «Да»
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    win._restore_from_source(items[1]["path"], items[1]["label"])
    app.processEvents()
    with open(proj_path, encoding="utf-8") as f:
        file_srv = len(json.load(f)["servers"])
    check("откат на слот1 → файл и сцена вернулись к 3 серверам",
          file_srv == 3 and len(win.scene.nodes()) == 3,
          f"file={file_srv} nodes={len(win.scene.nodes())}")
    check("после отката: dirty сброшен (новая undo-точка)", win._dirty is False)
finally:
    QMessageBox.question = _q_orig

# подтверждение «Нет» → проект не тронут
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
try:
    nodes_before = len(win.scene.nodes())
    win._restore_from_source(items[2]["path"], items[2]["label"])
    app.processEvents()
    check("подтверждение «Нет» → проект не изменился",
          len(win.scene.nodes()) == nodes_before, f"nodes={len(win.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

# ручной путь меню «Восстановить из автосохранения…» (5 серверов)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
try:
    win._restore_from_autosave()
    app.processEvents()
    check("меню «Восстановить из автосохранения» → сцена 5 серверов",
          len(win.scene.nodes()) == 5, f"nodes={len(win.scene.nodes())}")
finally:
    QMessageBox.question = _q_orig

# гард без открытого проекта — информационное сообщение, без падения
_info_orig = QMessageBox.information
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
try:
    win_ns._project_file = None
    win_ns._restore_from_autosave()
    win_ns._show_backups_dialog()
    check("без открытого проекта → гард (info), без падения", True)
except Exception as e:  # noqa: BLE001
    check("без открытого проекта → гард (info), без падения", False, repr(e))
finally:
    QMessageBox.information = _info_orig

# ══ i18n: 18 новых ключей × en/ru/zh ════════════════════════════════════════
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = ["file.restore_autosave", "file.backups", "dialog.autosave_found",
            "msg.autosave_newer", "dialog.backups", "backups.autosave",
            "backups.backup", "backups.empty", "backups.col_source",
            "backups.col_modified", "backups.col_size", "btn.restore",
            "msg.confirm_restore", "msg.confirm_restore_dirty", "status.restored",
            "status.autosaved", "msg.restore_failed", "msg.open_project_first"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("18 новых ключей v0.9.7 есть и не пусты в en/ru/zh", not missing, str(missing))
# v0.9.9.2: +13 ключей UI внешнего терминала (ssh_ext.section … ssh_ext.preset.kitty)
# v0.9.9.7: +2 ключа PDF-экспорта (file.export_pdf, status.export_pdf_ok)
# v1.0RC4: +22 ключа Быстрого запуска (ctx.quick_launch … msg.ql_open_failed)
# v1.1: +33 ключа диалога настроек (settings.* / menu.settings / btn.settings / status.settings_saved)
# v1.1.2RC2: +2 ключа (msg.confirm_delete_profile, status.import_resolving)
# v1.1.2 final: +2 ключа (settings.statuses.max_parallel, status.auto_interval_hint)
check("наборы ключей идентичны en/ru/zh (377 на язык)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 377 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# Cleanup: сначала dirty=False — иначе closeEvent уйдёт в диалог сохранения.
for w in (win, win2, win3, win_ns):
    try:
        w._dirty = False
        w.close(); w.destroy()
    except Exception:
        pass

# v1.1.2 final (N12): чистим за собой — rmtree рабочей папки при ВЫХОДЕ.
# Раньше каталог резали только при старте (строка 39) — после каждого прогона
# сьюта на диске оставались _tmp_testdata_v097/app|ring|rt.
shutil.rmtree(WORK, ignore_errors=True)

finish()
