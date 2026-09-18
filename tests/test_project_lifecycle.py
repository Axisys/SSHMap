# -*- coding: utf-8 -*-
"""v1.3.3.6 (ROADMAP "Projects: open, recover, remember"): the life cycle of a project file.

Four holes of the released v1.3.3.x, closed in one topical test (offscreen, sandbox HOME,
no network):

  * the MRU — `recent_projects` in config.json (newest first, deduplicated by the
    normalized absolute path, capped at 10, missing files pruned on read, a broken value
    ignored) + the "File → Recent" submenu rebuilt on `aboutToShow` with its QActions
    alive (PySide6 6.11 gotcha #9);
  * the drop — a real QDropEvent carrying ONE local `.json`/`.sshmap` file loads the
    project through `_load_project_at()` (the File → Open path); two files, a directory
    and a foreign suffix are refused with a hint and no state change;
  * the recovery — an unreadable project no longer ends in a bare critical dialog: the
    backup ring and the autosave are consulted (nothing is overwritten without an
    explicit choice), while the v0.9.7 #3 autosave-newer prompt keeps its own case;
  * the panel widths — `ui_splitter_state` (base64 QSplitter.saveState()) round-trips,
    a broken value falls back to the 250/950 defaults, and the restore runs AFTER the
    collapsed-panel state so a collapsed panel keeps its strip.

Run: python tests/test_project_lifecycle.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys
from datetime import datetime

from _common import (bootstrap, check, finish, check_release_state, load_i18n_langs,
                     check_i18n_parity, check_i18n_format, placeholder_names, newline_count,
                     clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + faulthandler inside)

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

# Network is forbidden in tests: the status probes answer instantly (otherwise
# _load_project_at → start_round would spawn threads with network timeouts).
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

from i18n import load_config, save_config
from _fakes import QuestionStub
from storage import autosave as AS
from storage.project import write_project_json
from models.server import ServerData
import ui.main_window as MW
import ui.main_window_project_io as PI
from modules.window_geometry import (
    save_splitter_state, restore_splitter_state, splitter_state_b64,
)

# ── QMessageBox: no modals offscreen; question() answers from a queue ──────────────
# The patch goes through the shared PySide6 class, so it covers the mixin's methods too.
boxes = []
question_replies = []

MW.QMessageBox.question = QuestionStub(
    QMessageBox.Yes, replies=question_replies,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(
    lambda *a, **k: boxes.append(("critical", str(a[1]), str(a[2]))))
MW.QMessageBox.warning = staticmethod(
    lambda *a, **k: boxes.append(("warning", str(a[1]), str(a[2]))))
MW.QMessageBox.information = staticmethod(
    lambda *a, **k: boxes.append(("information", str(a[1]), str(a[2]))))
def make_window(show=False):
    """An offscreen MainWindow with a stopped autosave timer (ticks are called by hand)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    if show:
        win.resize(1200, 850)
        win.show()
        app.processEvents()
    return win


def project_dict(aliases):
    """A minimal readable project (the storage format; no passwords anywhere)."""
    return {
        "version": "0.9",
        "servers": [{"id": f"pl{i:02d}", "alias": a, "host": f"10.9.0.{i + 1}",
                     "user": "root", "x": float(i * 40), "y": 0.0}
                    for i, a in enumerate(aliases)],
        "connections": [], "notes": [], "groups": [],
    }


def make_project(path, aliases=("Alpha",)):
    """Write a readable project file with one node per alias; returns the path."""
    write_project_json(path, project_dict(aliases))
    return path


def same_path(a, b) -> bool:
    """Path equality across the two spellings of one file (Qt hands out '/', os '\\\\')."""
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def drop_mime(paths=None, text=None):
    """A QMimeData for a drop: local-file URLs (or plain text) — kept alive by the caller."""
    mime = QMimeData()
    if paths is not None:
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    if text is not None:
        mime.setText(text)
    return mime


def drop_event(mime):
    """A real QDropEvent over `mime` (the caller holds the mime alive)."""
    return QDropEvent(QPointF(12.0, 12.0), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)


# ════════════════════════════════════════════════════════════════════════════════
print("== 1. the MRU: recent_projects in config.json ==")
# ════════════════════════════════════════════════════════════════════════════════

clear_cfg()
MRU_FILES = [os.path.join(WORK, f"mru_{i:02d}.json") for i in range(12)]
for _i, p in enumerate(MRU_FILES):
    make_project(p, (f"mru{_i}",))

win = make_window()
check("a fresh config: the MRU is empty", win._recent_projects() == [],
      str(win._recent_projects()))

ok = win._load_project_at(MRU_FILES[0])
check("a load fills the MRU (stored as an absolute path)",
      ok is True and win._recent_projects() == [os.path.abspath(MRU_FILES[0])],
      str(win._recent_projects()))

saved_path = os.path.join(WORK, "mru_saved.json")
saved_ok = win._do_save(saved_path)
items = win._recent_projects()
check("a save fills the MRU too (the saved path becomes the head)",
      saved_ok is True and items[0] == os.path.abspath(saved_path), str(items[:3]))
check("recent_projects is a plain list of strings in config.json",
      isinstance(load_config().get(PI.RECENT_PROJECTS_KEY), list)
      and all(isinstance(x, str) for x in load_config()[PI.RECENT_PROJECTS_KEY]),
      str(load_config().get(PI.RECENT_PROJECTS_KEY)))

# newest first + deduplication by the normalized absolute path
win._load_project_at(MRU_FILES[0])  # already in the list — it must move to the head
items = win._recent_projects()
check("newest first", items[0] == os.path.abspath(MRU_FILES[0]), str(items[:3]))
check("deduplicated — one entry per normalized absolute path",
      len(items) == len({os.path.normcase(os.path.abspath(p)) for p in items})
      and items.count(os.path.abspath(MRU_FILES[0])) == 1, str(items))

# the same file spelled with a redundant separator is the same entry (abspath normalizes it)
_equivalent = os.path.join(WORK, ".", os.path.basename(MRU_FILES[0]))
win._remember_recent_project(_equivalent)
items = win._recent_projects()
check("deduplication sees through an equivalent spelling of one path",
      items[0] == os.path.abspath(MRU_FILES[0])
      and items.count(os.path.abspath(MRU_FILES[0])) == 1, str(items))

# the cap
for p in MRU_FILES:
    win._load_project_at(p)
items = win._recent_projects()
check(f"capped at RECENT_PROJECTS_MAX ({PI.RECENT_PROJECTS_MAX})",
      len(items) == PI.RECENT_PROJECTS_MAX, str(len(items)))
check("the cap keeps the NEWEST entries",
      items[0] == os.path.abspath(MRU_FILES[-1]) and items[-1] == os.path.abspath(MRU_FILES[2]),
      str(items))

# pruning of the missing files
gone = items[-1]
os.remove(gone)
pruned = win._recent_projects()
check("a missing file is pruned on read",
      gone not in pruned and len(pruned) == PI.RECENT_PROJECTS_MAX - 1, str(len(pruned)))

# a broken value is ignored
save_config({PI.RECENT_PROJECTS_KEY: "not-a-list"})
check("a broken recent_projects value (not a list) is ignored",
      win._recent_projects() == [], str(win._recent_projects()))
save_config({PI.RECENT_PROJECTS_KEY: [None, 5, "", "   ", MRU_FILES[0]]})
check("broken / empty entries inside the list are dropped (the valid one survives)",
      win._recent_projects() == [MRU_FILES[0]], str(win._recent_projects()))

# ════════════════════════════════════════════════════════════════════════════════
print("== 2. the File → Recent submenu ==")
# ════════════════════════════════════════════════════════════════════════════════

save_config({PI.RECENT_PROJECTS_KEY: [MRU_FILES[0], MRU_FILES[1]]})
menu = win._recent_menu
check("the Recent submenu exists and is registered for re-translation",
      menu is not None and any(w is menu and k == "file.recent" for w, k in win._menu_i18n))

_file_menu = None
for _act in win.menuBar().actions():
    if _act.menu() is not None and _act.text() == win.t("menu.file"):
        _file_menu = _act.menu()
check("Recent is the FIRST child of the File menu",
      _file_menu is not None and len(_file_menu.actions()) > 1
      and _file_menu.actions()[0].menu() is menu,
      str([a.text() for a in _file_menu.actions()[:3]]) if _file_menu else "no File menu")

win._populate_recent_menu(menu)
_first = [a.text() for a in menu.actions()]
win._populate_recent_menu(menu)  # the aboutToShow rebuild, twice
_second = [a.text() for a in menu.actions()]
expected = [os.path.basename(MRU_FILES[0]), os.path.basename(MRU_FILES[1]), "",
            win.t("file.recent_clear")]
check("the submenu lists the MRU by file name + the Clear item at the bottom",
      _second == expected, f"{_first} / {_second}")
check("the submenu is rebuilt twice with the same content (idempotent)",
      _first == _second, f"{_first} / {_second}")
check("the rebuilt QActions are alive after two rebuilds (gotcha #9)",
      len(menu.actions()) == 4 and menu.actions()[0].text() == os.path.basename(MRU_FILES[0]))
check("the rebuilt QActions are re-registered in _qaction_guard",
      all(any(a is g for g in win._qaction_guard) for a in menu.actions()),
      f"guard={len(win._qaction_guard)} children={len(menu.actions())}")
_acts = menu.actions()
check("each item is labelled by the file name with the full path in the tooltip",
      _acts[0].text() == os.path.basename(MRU_FILES[0])
      and _acts[0].toolTip() == MRU_FILES[0]
      and _acts[1].toolTip() == MRU_FILES[1],
      f"{_acts[0].toolTip()!r} / {_acts[1].toolTip()!r}")

# clicking an item loads that project (the same path as File → Open)
win._open_recent_project(MRU_FILES[1])
check("clicking a Recent item loads the project",
      win._project_file == MRU_FILES[1] and win.scene.node_count() == 1,
      f"file={win._project_file} nodes={win.scene.node_count()}")
check("the clicked project moved to the head of the MRU",
      win._recent_projects()[0] == os.path.abspath(MRU_FILES[1]), str(win._recent_projects()))

# "Clear the list"
win._clear_recent_projects()
check("Clear the list empties the MRU", win._recent_projects() == [],
      str(win._recent_projects()))
check("Clear refreshes the submenu immediately (the empty placeholder)",
      [a.text() for a in menu.actions()] == [win.t("file.recent_empty")],
      str([a.text() for a in menu.actions()]))
check("the empty placeholder is disabled (a hint, not a command)",
      not menu.actions()[0].isEnabled())
win._populate_recent_menu(menu)
check("the placeholder survives a rebuild (still alive)",
      [a.text() for a in menu.actions()] == [win.t("file.recent_empty")])

# a vanished entry: pruned instead of crashing
save_config({PI.RECENT_PROJECTS_KEY: [MRU_FILES[0]]})
os.remove(MRU_FILES[0])
win._populate_recent_menu(menu)
check("a vanished file disappears from the submenu on the next rebuild",
      [a.text() for a in menu.actions()] == [win.t("file.recent_empty")],
      str([a.text() for a in menu.actions()]))
check("_open_recent_project on a vanished path returns False (no exception)",
      win._open_recent_project(MRU_FILES[0]) is False)
make_project(MRU_FILES[0])

# ════════════════════════════════════════════════════════════════════════════════
print("== 3. dropping a project onto the window ==")
# ════════════════════════════════════════════════════════════════════════════════

clear_cfg()
drop_json = make_project(os.path.join(WORK, "drop_one.json"), ("DropOne", "DropTwo"))
drop_sshmap = make_project(os.path.join(WORK, "drop_two.sshmap"), ("ShOne",))
drop_txt = os.path.join(WORK, "drop_foreign.txt")
with open(drop_txt, "w", encoding="utf-8") as f:
    f.write("not a project\n")

w_drop = make_window(show=True)
check("the window accepts drops", w_drop.acceptDrops() is True)

_mime = drop_mime([drop_json])
ev = drop_event(_mime)
w_drop.dropEvent(ev)
check("a dropped .json loads the project (scene + _project_file)",
      same_path(w_drop._project_file, drop_json) and w_drop.scene.node_count() == 2,
      f"file={w_drop._project_file} nodes={w_drop.scene.node_count()}")
check("the drop is accepted and reports through the status bar",
      ev.isAccepted() and w_drop.statusBar().currentMessage() == w_drop.t("status.project_loaded"),
      w_drop.statusBar().currentMessage())
check("the drop went through the MRU too (the same load path)",
      w_drop._recent_projects() and w_drop._recent_projects()[0] == os.path.abspath(drop_json),
      str(w_drop._recent_projects()))

w_drop.statusBar().clearMessage()
_mime2 = drop_mime([drop_sshmap])
ev2 = drop_event(_mime2)
w_drop.dropEvent(ev2)
check("a dropped .sshmap loads as well",
      ev2.isAccepted() and same_path(w_drop._project_file, drop_sshmap)
      and w_drop.scene.node_count() == 1, str(w_drop._project_file))


def _refused(paths, label, text=None):
    """Drop `paths` on the window → (accepted?, hint shown and no state change)."""
    before = (w_drop._project_file, w_drop.scene.node_count())
    w_drop.statusBar().clearMessage()
    mime = drop_mime(paths, text=text)
    event = drop_event(mime)
    w_drop.dropEvent(event)
    return (event.isAccepted(),
            (w_drop._project_file, w_drop.scene.node_count()) == before
            and w_drop.statusBar().currentMessage() == w_drop.t("msg.drop_project"))


_accepted, _unchanged = _refused([drop_json, drop_sshmap], "two files")
check("two files are refused with a hint and no state change",
      not _accepted and _unchanged)
_accepted, _unchanged = _refused([WORK], "a directory")
check("a directory is refused with a hint and no state change",
      not _accepted and _unchanged)
_accepted, _unchanged = _refused([drop_txt], "a foreign suffix")
check("a foreign suffix is refused with a hint and no state change",
      not _accepted and _unchanged)
_accepted, _unchanged = _refused([os.path.join(WORK, "nope.json")], "a missing file")
check("a missing path is refused with a hint and no state change",
      not _accepted and _unchanged)

# dragEnter/dragMove: any local-file drag is accepted (so a refusal can be explained),
# a text drag is not accepted at all — the OS keeps its "no drop" cursor.
_enter_mime = drop_mime([drop_json])
_enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, _enter_mime, Qt.LeftButton, Qt.NoModifier)
w_drop.dragEnterEvent(_enter)
check("dragEnter accepts a local-file drag (the refusals reach dropEvent)",
      _enter.isAccepted())
_txt_mime = drop_mime(None, text="hello")
_enter_txt = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, _txt_mime, Qt.LeftButton, Qt.NoModifier)
w_drop.dragEnterEvent(_enter_txt)
check("a text drag is not accepted (nothing is promised)", not _enter_txt.isAccepted())

# A drop while dirty goes through the existing unsaved-changes gate — that is, exactly the
# File → Open entry point (`_load_project_at`), not a private second load path. NOTE: in
# v1.3.3.5 `_open_project()` itself has NO busy/dirty dialog (only `closeEvent` asks), so
# "the gate" here means the shared path and its consequences, verified by the seam below.
w_dirty = make_window(show=True)
w_dirty._load_project_at(drop_json)
w_dirty.scene.add_server(
    ServerData(id="dirtypl1", alias="Dirty", host="10.11.0.1", user="root"))
w_dirty._mark_dirty()
check("the window is dirty before the drop", w_dirty._dirty is True)

_calls = []
_orig_load = w_dirty._load_project_at


def _recording_load(path, skip_autosave_prompt=False):
    _calls.append((path, skip_autosave_prompt))
    return _orig_load(path, skip_autosave_prompt)


w_dirty._load_project_at = _recording_load
try:
    _vm = drop_mime([drop_sshmap])
    _ev_dirty = drop_event(_vm)
    w_dirty.dropEvent(_ev_dirty)
finally:
    w_dirty._load_project_at = _orig_load
check("a drop while dirty goes through the SAME entry point as File → Open",
      len(_calls) == 1 and same_path(_calls[0][0], drop_sshmap)
      and _calls[0][1] is False, str(_calls))
check("... and leaves a clean, replaced project (identical to File → Open)",
      same_path(w_dirty._project_file, drop_sshmap) and w_dirty._dirty is False
      and w_dirty.scene.node_count() == 1,
      f"file={w_dirty._project_file} dirty={w_dirty._dirty} nodes={w_dirty.scene.node_count()}")

# ════════════════════════════════════════════════════════════════════════════════
print("== 4. recovery when the project cannot be read ==")
# ════════════════════════════════════════════════════════════════════════════════

corrupt = make_project(os.path.join(WORK, "corrupt.json"), ("Good1", "Good2"))
AS.rotate_backups(corrupt, 3)  # slot 1 = the version before the next save (the good one)
check("the ring holds the good version of the file",
      len(AS.list_backups(corrupt)) == 1, str(AS.list_backups(corrupt)))
with open(corrupt, "w", encoding="utf-8") as f:
    f.write("{ this is not json")
with open(corrupt, "rb") as f:
    corrupt_bytes = f.read()

w_rec = make_window()
_answer = {"value": "restore"}
captured = {}


def _ask(error, source):
    captured["error"] = str(error)
    captured["source"] = dict(source)
    return _answer["value"]


w_rec._ask_recovery_source = _ask
ok = w_rec._load_project_at(corrupt)
check("a corrupt project with a fresh backup OFFERS the restore (not a dead end)",
      "source" in captured, str(captured))
check("the offered source is the NEWEST ring slot, named with its slot number",
      captured.get("source", {}).get("kind") == "backup"
      and captured["source"]["label"] == w_rec.t("backups.backup", n=1),
      str(captured.get("source")))
check("the sources are collected newest first",
      [s["kind"] for s in w_rec._unreadable_sources(corrupt)] == ["backup"],
      str(w_rec._unreadable_sources(corrupt)))

_when = datetime.fromtimestamp(captured["source"]["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
_prompt = w_rec._recovery_prompt_text(captured["error"], captured["source"])
check("the offer spells the source AND its date out",
      w_rec.t("backups.backup", n=1) in _prompt and _when in _prompt,
      _prompt.replace("\n", " | "))
check("the offer text is the i18n template with error / source / date filled in",
      _prompt == w_rec.t("msg.project_unreadable", error=captured["error"],
                         source=w_rec.t("backups.backup", n=1), date=_when),
      _prompt.replace("\n", " | "))

check("Restore leaves a READABLE project with the backed-up content",
      ok is True and w_rec._project_file == corrupt and w_rec.scene.node_count() == 2,
      f"ok={ok} file={w_rec._project_file} nodes={w_rec.scene.node_count()}")
with open(corrupt, encoding="utf-8") as f:
    _restored = json.load(f)
check("the file on disk parses again (the good content was written back)",
      len(_restored.get("servers", [])) == 2, str(len(_restored.get("servers", []))))
check("Restore leaves a clean undo baseline (a fresh project, not a dirty one)",
      w_rec.undo_stack.count() == 0 and w_rec._dirty is False,
      f"undo={w_rec.undo_stack.count()} dirty={w_rec._dirty}")
check("the recovered project joined the MRU",
      corrupt in [os.path.abspath(p) for p in w_rec._recent_projects()]
      or os.path.abspath(corrupt) in w_rec._recent_projects(),
      str(w_rec._recent_projects()[:2]))

# "Open the backup list…" hands the decision to the existing BackupsDialog — for the file
# that failed to load, not for whatever project happens to be open.
with open(corrupt, "w", encoding="utf-8") as f:
    f.write("{ this is not json")
_entries = w_rec._backup_items(corrupt)
check("the backup list of a file is built from ITS ring (an explicit target)",
      len(_entries) == 1 and _entries[0]["path"] == AS.backup_path_for(corrupt, 1),
      str(_entries))
_listed = []
w_rec._show_backups_dialog = lambda path=None: _listed.append(path)
_answer["value"] = "list"
captured.clear()
ok = w_rec._load_project_at(corrupt)
check("the backup-list option opens the list of the file that failed to load",
      _listed == [corrupt] and ok is False, str(_listed))

# Cancel leaves the corrupt file untouched
before_open = w_rec._project_file
captured.clear()
_answer["value"] = "skip"
ok = w_rec._load_project_at(corrupt)
with open(corrupt, "rb") as f:
    after_bytes = f.read()
check("Cancel leaves the corrupt file untouched (nothing is overwritten without consent)",
      ok is False and after_bytes == corrupt_bytes, f"ok={ok} same={after_bytes == corrupt_bytes}")
check("Cancel leaves the open project alone",
      w_rec._project_file == before_open, str(w_rec._project_file))

# NO source at all → the historic critical dialog, unchanged
w_bare = make_window()
bare = os.path.join(WORK, "corrupt_bare.json")
with open(bare, "w", encoding="utf-8") as f:
    f.write("{ nope")
boxes.clear()
ok = w_bare._load_project_at(bare)
check("a corrupt project WITHOUT any source keeps the critical dialog",
      ok is False and any(b[0] == "critical" and "Failed to load" in b[2] for b in boxes),
      str(boxes[-1:]))
check("... and the window is left without an open project file",
      w_bare._project_file is None and AS.list_backups(bare) == []
      and AS.read_autosave(bare) is None)

# a CORRUPT autosave is not offered as a rescue (it would just move the failure)
corrupt2 = make_project(os.path.join(WORK, "corrupt_auto.json"), ("OnlyOne",))
_auto_path = AS.autosave_path_for(corrupt2)
os.makedirs(os.path.dirname(_auto_path), exist_ok=True)
with open(_auto_path, "w", encoding="utf-8") as f:
    f.write("{ broken autosave")
with open(corrupt2, "w", encoding="utf-8") as f:
    f.write("{ broken project")
w_c2 = make_window()
check("a corrupt autosave is not offered as a recovery source",
      w_c2._unreadable_sources(corrupt2) == [], str(w_c2._unreadable_sources(corrupt2)))
os.remove(_auto_path)

# ... and neither is a corrupt RING slot (restoring it would loop back into the same dialog)
corrupt3 = make_project(os.path.join(WORK, "corrupt_slot.json"), ("SlotOne",))
with open(corrupt3, "w", encoding="utf-8") as f:
    f.write("{ broken project")
AS.atomic_write_json(AS.backup_path_for(corrupt3, 1), {"version": "0.9", "servers": [
    {"id": "slotok1", "alias": "SlotOK", "host": "10.9.9.9", "user": "root"}]})
with open(AS.backup_path_for(corrupt3, 2), "w", encoding="utf-8") as f:
    f.write("{ broken slot")
w_c3b = make_window()
_slot_sources = w_c3b._unreadable_sources(corrupt3)
check("a corrupt ring slot is skipped while a readable one is still offered",
      [s["path"] for s in _slot_sources] == [AS.backup_path_for(corrupt3, 1)],
      str(_slot_sources))

# a READABLE autosave IS offered, and wins over an older backup by mtime
good_auto = make_project(os.path.join(WORK, "auto_source.json"), ("FileOne",))
AS.rotate_backups(good_auto, 3)
AS.write_autosave(good_auto, project_dict(("AutoOne", "AutoTwo")))
_t_auto = os.path.getmtime(AS.autosave_path_for(good_auto))
os.utime(AS.backup_path_for(good_auto, 1), (_t_auto - 60, _t_auto - 60))
w_c3 = make_window()
_sources = w_c3._unreadable_sources(good_auto)
check("a readable autosave is offered and sorted newest first",
      [s["kind"] for s in _sources] == ["autosave", "backup"]
      and _sources[0]["label"] == w_c3.t("backups.autosave"), str(_sources))

# a READABLE project whose APPLY step fails is NOT a recovery case: offering to
# overwrite a good file with a backup would be data loss — the critical dialog stays.
w_apply = make_window()
apply_case = make_project(os.path.join(WORK, "apply_fails.json"), ("ApplyOne",))
AS.rotate_backups(apply_case, 3)  # a backup exists — and must NOT be offered
_apply_offers = []
w_apply._ask_recovery_source = lambda error, source: (
    _apply_offers.append(source), "skip")[1]
boxes.clear()
_orig_import = w_apply._import_project_raw
w_apply._import_project_raw = lambda raw: (_ for _ in ()).throw(RuntimeError("apply boom"))
try:
    ok = w_apply._load_project_at(apply_case)
finally:
    w_apply._import_project_raw = _orig_import
check("a readable file whose APPLY step fails keeps the critical dialog (no recovery offer)",
      ok is False and _apply_offers == []
      and any(b[0] == "critical" and "Failed to load" in b[2] for b in boxes),
      f"offers={_apply_offers} boxes={boxes[-1:]}")
check("... and the readable file on disk is left untouched",
      AS.list_backups(apply_case) and json.load(open(apply_case, encoding="utf-8")))

# the v0.9.7 #3 prompt keeps its own case: a READABLE file + a NEWER autosave
w_auto = make_window()
newer = make_project(os.path.join(WORK, "autosave_newer.json"), ("OldOne",))
AS.write_autosave(newer, project_dict(("NewOne", "NewTwo")))
_t_file = os.path.getmtime(newer)
os.utime(AS.autosave_path_for(newer), (_t_file + 30, _t_file + 30))
question_replies.clear()
question_replies.append(QMessageBox.Yes)
boxes.clear()
ok = w_auto._load_project_at(newer)
check("the v0.9.7 #3 autosave-newer prompt still fires in its own case",
      ok is True and any(b[0] == "question" for b in boxes), str(boxes))
check("... and answering Yes loads the autosave content",
      w_auto.scene.node_count() == 2, str(w_auto.scene.node_count()))
check("... without any recovery dialog (the file itself was readable)",
      not any(b[0] == "critical" for b in boxes), str(boxes))

question_replies.clear()
question_replies.append(QMessageBox.No)
w_auto2 = make_window()
w_auto2._load_project_at(newer)
check("... and answering No keeps the file on disk as the source",
      w_auto2.scene.node_count() == 1, str(w_auto2.scene.node_count()))

# ════════════════════════════════════════════════════════════════════════════════
print("== 5. the panel widths (ui_splitter_state) ==")
# ════════════════════════════════════════════════════════════════════════════════

STRIP_W = MW._CollapseStrip.STRIP_WIDTH
DEFAULT_RATIO = 250.0 / 1200.0


def _ratio(sizes):
    return sizes[0] / max(sum(sizes), 1)


save_config({"ui_sidebar_collapsed": False, "ui_map_collapsed": False})
save_config({"ui_splitter_state": "!!! not base64 !!!"})
w_sz = make_window(show=True)
_sizes = w_sz._splitter.sizes()
check("a broken ui_splitter_state falls back to the 250/950 defaults",
      abs(_ratio(_sizes) - DEFAULT_RATIO) < 0.03, str(_sizes))
check("restore_splitter_state reports False for a broken value",
      restore_splitter_state("ui_splitter_state", w_sz._splitter) is False)

w_src = make_window(show=True)
w_src._splitter.setSizes([700, 500])
app.processEvents()
_src_ratio = _ratio(w_src._splitter.sizes())
check("the source window really carries a non-default layout",
      abs(_src_ratio - DEFAULT_RATIO) > 0.1, str(w_src._splitter.sizes()))
check("save_splitter_state writes a base64 STRING (not a geometry object)",
      save_splitter_state("ui_splitter_state", w_src._splitter) is True
      and isinstance(load_config().get("ui_splitter_state"), str)
      and not isinstance(load_config().get("ui_splitter_state"), dict),
      str(type(load_config().get("ui_splitter_state"))))
check("splitter_state_b64 is never empty for a live splitter",
      len(splitter_state_b64(w_src._splitter)) > 8)

w_restored = make_window(show=True)
_d = w_restored._splitter.sizes()
check("the splitter state round-trips (the saved layout comes back)",
      _d[0] > _d[1] and abs(_ratio(_d) - _src_ratio) < 0.03,
      f"{_d} (source {w_src._splitter.sizes()}, default ratio {DEFAULT_RATIO:.3f})")

# the ORDER rule: the restore runs AFTER the collapsed-panel state, so a saved layout
# must not resurrect the width of a collapsed panel.
save_config({"ui_splitter_state": splitter_state_b64(w_src._splitter),
             "ui_sidebar_collapsed": True, "ui_map_collapsed": False})
w_coll = make_window(show=True)
check("the collapsed sidebar survives the splitter restore",
      w_coll._sidebar_collapsed is True and w_coll.sidebar.isHidden()
      and w_coll._sidebar_strip.isVisible())
check("... and keeps its 18px strip container (the width is not resurrected)",
      w_coll._sidebar_container.minimumWidth() == STRIP_W
      and w_coll._splitter.sizes()[0] <= w_coll._splitter.sizes()[1],
      f"min={w_coll._sidebar_container.minimumWidth()} sizes={w_coll._splitter.sizes()}")
check("the restored state does not re-show the collapsed panel",
      not w_coll.sidebar.isVisible())

save_config({"ui_sidebar_collapsed": False, "ui_map_collapsed": True})
w_coll2 = make_window(show=True)
check("the same rule for the map (collapsed, strip kept)",
      w_coll2._map_collapsed is True and w_coll2._map_container.minimumWidth() == STRIP_W
      and w_coll2._splitter.sizes()[1] <= w_coll2._splitter.sizes()[0],
      f"min={w_coll2._map_container.minimumWidth()} sizes={w_coll2._splitter.sizes()}")
check("collapsing both panels is still forbidden (the v1.2.4.1-fix invariant)",
      w_coll2._set_panel_collapsed("sidebar", True) == "forbidden")

# closeEvent writes the key next to the geometry (never throws, one save per window)
clear_cfg()
w_close = make_window(show=True)
w_close.scene.add_server(
    ServerData(id="closepj1", alias="Close", host="10.12.0.1", user="root"))
w_close._splitter.setSizes([640, 560])
app.processEvents()
w_close.close()
_cfg = load_config()
check("closeEvent persists ui_splitter_state next to ui_window_geometry_main",
      isinstance(_cfg.get("ui_splitter_state"), str) and _cfg.get("ui_splitter_state")
      and isinstance(_cfg.get("ui_window_geometry_main"), dict),
      str({k: type(v).__name__ for k, v in _cfg.items()}))

# ════════════════════════════════════════════════════════════════════════════════
print("== 6. i18n + the release state ==")
# ════════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)

_new_keys = ["file.recent", "file.recent_clear", "file.recent_empty", "msg.drop_project",
             "dialog.project_unreadable", "msg.project_unreadable",
             "msg.project_unreadable_restore", "msg.project_unreadable_backups",
             "msg.project_unreadable_skip"]
_missing = [k for k in _new_keys if k not in _langs["en"]]
check("every v1.3.3.6 key is in the reference language", not _missing, str(_missing))
check("the new keys are non-empty in every discovered language",
      all(_langs[c].get(k, "").strip() for c in _langs for k in _new_keys),
      str({c: [k for k in _new_keys if not _langs[c].get(k, "").strip()] for c in _langs}))
check("msg.project_unreadable keeps its placeholder set in every language",
      all(placeholder_names(_langs[c]["msg.project_unreadable"])
          == {"error", "source", "date"} for c in _langs),
      str({c: sorted(placeholder_names(_langs[c]["msg.project_unreadable"])) for c in _langs}))
check("the recovery text keeps its single line break everywhere",
      all(newline_count(_langs[c]["msg.project_unreadable"]) == 1 for c in _langs),
      str({c: newline_count(_langs[c]["msg.project_unreadable"]) for c in _langs}))

check_release_state(ROOT)

finish()
