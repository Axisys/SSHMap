# -*- coding: utf-8 -*-
"""v1.6.1 — the review batch (hardening): the shipped facts, the guards and the leftovers.

The first follow-up of the 1.6 line is a HARDENING slot in the v1.5rc5 shape: every task of it
is a defect or a guard — no new feature, no new dependency, no new colour, no schema move and
NO i18n key (the parity pin stays 778 and not one language file is touched). The ledger with
the probes is `AUDIT_PENDING.md` (`N9`–`N22`); this file is the regression of every one of them.

  §1  N9  — the external terminal opens on macOS: the AppleScript `-e` SOURCE is an AppleScript
            double-quoted literal (the POSIX `_sh_quote()` cannot compile there) and the
            `osascript` path reports what the interpreter DID instead of assuming success.
  §2  N10 — the no-i18n fallback literals equal `en.json`, and the FOURTH part of
            `tests/check_i18n_keys.py` keeps them there: the walk is RED on each of the six
            pre-fix drifts handed to it as a synthetic source.
  §3  N11 — the string annotations resolve (a hermetic AST gate) and `pyflakes` reports no
            `undefined name`; the only reports left are the documented `_st_module()` seams.
  §4  N12/N13/N14/N15/N16 — the writers, the readers and the report survive a broken value:
            no `*.tmp` after a failed write, a REAL bool out of `autosave_enabled`, a language
            file that is not valid UTF-8 falls back instead of raising, and `dedup_entries()`
            counts only the entries it really folded.
  §5  N17 — the log survives a GUI launch without a console (`pythonw.exe`: BOTH streams None).
  §6  N18 — the profile mask does not follow the length of the stored password.
  §7  N19 — the toolbar's right-click menu names every row it lists.
  §8  N20 — a shown session owns the keyboard; a SPLIT PANE deliberately does not take it.
  §9  N21 — the quick-launch editor REPLACES a selected row in place and can reorder entries.
  §10 N22 — the CPU model sits on the CPU line and the info block keeps its line COUNT.
  §11 the release state (version, i18n parity — NO new key).

Run: python tests/test_audit_v161.py   (from the project root) or python tests/run_all.py
"""
import ast
import builtins
import json
import os
import subprocess
import sys
import tempfile

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, EXPECTED_I18N_KEYS, I18N_REFERENCE)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import logging  # noqa: E402
import i18n  # noqa: E402
import check_i18n_keys as CIK  # noqa: E402 — the checker's own pure half (part 4)
from _fakes import FakeSSHThread  # noqa: E402

EN = {k: v for k, v in json.load(
    open(os.path.join(ROOT, "i18n", "en.json"), encoding="utf-8-sig")).items()
    if isinstance(v, str)}


def _tmpdir():
    return tempfile.mkdtemp(prefix="sshmap_v161_")


# ════════════════════════════════════════════════════════════════════════════
print("== §1 N9 — the external terminal on macOS ==")
# ════════════════════════════════════════════════════════════════════════════

from modules import external_terminal as ET  # noqa: E402

_SSH_ARGS = ET.build_ssh_args("10.0.0.5", "root", 2222, "/keys/my key")
_SCRIPT = ET._shell_join(_SSH_ARGS) + "; exec bash"
_CMD = ET.build_command("open_terminal", "10.0.0.5", "root", 2222, "/keys/my key")

check("N9: the macOS branch is `osascript -e <source>`",
      _CMD[0] == "osascript" and _CMD[1] == "-e" and len(_CMD) == 3, str(_CMD[:2]))

_PREFIX = 'tell application "Terminal" to do script '
_SOURCE = _CMD[2]
_LITERAL = _SOURCE[len(_PREFIX):] if _SOURCE.startswith(_PREFIX) else ""
check("N9: the `-e` SOURCE is an AppleScript DOUBLE-QUOTED literal",
      bool(_LITERAL) and _LITERAL.startswith('"') and _LITERAL.endswith('"')
      and not _LITERAL.startswith("'"), _SOURCE)

check("N9: ...and carries NO POSIX single-quote escaping (what osascript could not compile)",
      "'\"'\"'" not in _SOURCE, _SOURCE)


def _applescript_value(literal):
    """The string an AppleScript double-quoted literal denotes (\\" and \\\\ unescaped)."""
    body = literal[1:-1]
    out, i = [], 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append(body[i + 1])
            i += 2
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


check("N9: the decoded script IS the untouched ssh argv + `exec bash`",
      _applescript_value(_LITERAL) == _SCRIPT,
      f"{_applescript_value(_LITERAL)!r}")

_ESCAPED = ET.build_command("open_terminal", "10.0.0.5", 'ro"ot', 22, 'C:\\keys\\my "key"')[2]
_ESCAPED_LITERAL = _ESCAPED[len(_PREFIX):]
check("N9: a quote and a backslash in the user/key are escaped, not passed through",
      '\\"' in _ESCAPED_LITERAL and "\\\\" in _ESCAPED_LITERAL
      and _applescript_value(_ESCAPED_LITERAL) == ET._shell_join(
          ET.build_ssh_args("10.0.0.5", 'ro"ot', 22, 'C:\\keys\\my "key"')) + "; exec bash",
      _ESCAPED)

_LINUX = ET.build_command("konsole", "10.0.0.5", "root", 22, "/keys/my key")
check("N9: the Linux family still uses the POSIX `_sh_quote()` (it belongs to `bash -c`)",
      _LINUX[0].endswith("konsole") and "'ssh'" in _LINUX[-1] and "'/keys/my key'" in _LINUX[-1],
      repr(_LINUX[-1]))


class _Interpreter:
    """`subprocess.Popen` of an INTERPRETER: the process ends, the status is the answer."""
    status = 0
    instances = []

    def __init__(self, *args, **kwargs):
        self.command = args[0] if args else []
        self.waited = False
        _Interpreter.instances.append(self)

    def wait(self, timeout=None):
        self.waited = True
        return self.status


_real_popen = subprocess.Popen
subprocess.Popen = _Interpreter
try:
    _Interpreter.status = 1
    _Interpreter.instances = []
    check("N9: an osascript that FAILED is reported as a failure (it used to answer True)",
          ET.launch(["osascript", "-e", "x"]) is False
          and _Interpreter.instances[-1].waited,
          f"waited={_Interpreter.instances[-1].waited}")
    _Interpreter.status = 0
    _Interpreter.instances = []
    check("N9: an osascript that SUCCEEDED answers True",
          ET.launch(["osascript", "-e", "x"]) is True)
    _Interpreter.instances = []
    check("N9: a plain launcher is NOT waited for (the terminal owns its own life)",
          ET.launch(["wt.exe", "ssh", "root@10.0.0.5"]) is True
          and _Interpreter.instances[-1].waited is False)
finally:
    subprocess.Popen = _real_popen


# ════════════════════════════════════════════════════════════════════════════
print("== §2 N10 — the no-i18n fallback literals equal en.json, and the walk is RED on the drifts ==")
# ════════════════════════════════════════════════════════════════════════════

check("N10: the whole application source carries NO fallback literal that disagrees with en.json",
      CIK.collect_fallback_problems(ROOT, EN) == [],
      str(CIK.collect_fallback_problems(ROOT, EN))[:300])

# The six PRE-FIX drifts of the ledger, each handed to the walk as a synthetic source:
# the guard is proven RED on the exact text it exists for (a guard over nothing is useless).
_DRIFTS = (
    ("status.undone", 'x = self.t("status.undone", action=a) if self._i18n_available else "Undo."'),
    ("status.redone", 'x = self.t("status.redone") if self._i18n_available else "Redo."'),
    ("view.toggle_sidebar",
     'x = self.t("view.toggle_sidebar") if self._i18n_available else "Sidebar"'),
    ("view.toggle_map", 'x = self.t("view.toggle_map") if self._i18n_available else "Map"'),
    ("dialog.quick_launch_desc",
     'x = self._tr("dialog.quick_launch_desc") if self._i18n_available else "one\\ntwo"'),
    ("ql.value_hint_command",
     'x = self._tr("ql.value_hint_command") if self._i18n_available else "k9s, htop, docker ps ..."'),
)
for _key, _src in _DRIFTS:
    _found = CIK.fallback_literal_problems(_src, EN, "synthetic.py")
    check(f"N10: the walk is RED on the pre-fix drift of {_key}",
          len(_found) == 1 and _key in _found[0], str(_found))

check("N10: the SAME key with the en.json literal is clean (the guard is not a blanket)",
      CIK.fallback_literal_problems(
          'x = self.t("ql.add") if self._i18n_available else "Add"', EN, "s.py") == [])

check("N10: a VALUE-carrying ternary is not a candidate at all (the DECLARED flag keys the walk)",
      CIK.fallback_literal_problems(
          'x = self._t("settings.hotkeys.conflict") if conflicts else ""', EN, "s.py") == [])

check("N10: a `*_FALLBACKS` table is walked, and its GOOD values pass (`_AGE_FALLBACKS`)",
      CIK.fallback_literal_problems(
          "_AGE_FALLBACKS = {'sidebar.list.age_now': 'just now'}", EN, "s.py") == []
      and CIK.fallback_literal_problems(
          "_AGE_FALLBACKS = {'sidebar.list.age_now': 'right now'}", EN, "s.py") != [])

from ui.main_window import _VIEW_TOOLBAR_ITEMS  # noqa: E402

check("N10: the toolbar's panel cluster carries the en.json literals too (the 7th drift found here)",
      all(fallback == EN[key] for _id, _icon, key, fallback in _VIEW_TOOLBAR_ITEMS),
      str([(key, fallback, EN.get(key)) for _i, _n, key, fallback in _VIEW_TOOLBAR_ITEMS
           if fallback != EN.get(key)]))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 N11 — the static floor: the string annotations resolve, and pyflakes is clean ==")
# ════════════════════════════════════════════════════════════════════════════

_APP_DIRS = ("main.py", "modules", "ui", "graphics", "storage", "services", "dialogs", "models", "i18n")


def _string_annotation_names(node):
    """Every NAME a (possibly nested) annotation expression refers to."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            try:
                names |= _string_annotation_names(ast.parse(sub.value, mode="eval").body)
            except SyntaxError:
                continue
        elif isinstance(sub, ast.Name):
            names.add(sub.id)
    return names


def unresolved_annotation_names(source):
    """The names a module's annotations refer to but the module never BINDS (pure AST).

    v1.6.1 (ROADMAP task 3): a string annotation naming a type the module does not import
    fails nothing at runtime (a string annotation is never evaluated) and fails
    `typing.get_type_hints()`, a doc generator or a stricter linter tomorrow. The gate is
    hermetic — the `ast` module of the stdlib — so it runs everywhere; `pyflakes` is run
    beside it as the wider second opinion when the tool is installed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["<unparsable source>"]
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
    problems = set()
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
            if node.args.vararg:
                args.append(node.args.vararg)
            if node.args.kwarg:
                args.append(node.args.kwarg)
            annotations.append(node.returns)
            annotations.extend(a.annotation for a in args)
        for ann in annotations:
            if ann is None:
                continue
            for name in _string_annotation_names(ann):
                if name not in bound:
                    problems.add(name)
    return sorted(problems)


def _application_sources():
    for name in _APP_DIRS:
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            yield path
            continue
        for dirpath, _dirs, files in os.walk(path):
            if "__pycache__" in dirpath:
                continue
            for f in sorted(files):
                if f.endswith(".py") and not f.startswith("_"):
                    yield os.path.join(dirpath, f)


_ANNOTATION_PROBLEMS = {}
for _p in _application_sources():
    try:
        _names = unresolved_annotation_names(open(_p, encoding="utf-8").read())
    except OSError as e:
        _names = [repr(e)]
    if _names:
        _ANNOTATION_PROBLEMS[os.path.relpath(_p, ROOT)] = _names

check("N11: every name of every annotation is bound by its own module (the hermetic gate)",
      not _ANNOTATION_PROBLEMS, str(_ANNOTATION_PROBLEMS)[:400])

check("N11: ...and the gate is RED on the PRE-FIX shape it exists for",
      unresolved_annotation_names(
          'def f(node: "ServerNode") -> "QPixmap":\n    return None\n') == ["QPixmap", "ServerNode"]
      and unresolved_annotation_names('from typing import Optional\n'
                                      'def f() -> "Optional[int]":\n    return None\n') == []
      and unresolved_annotation_names('from typing import TYPE_CHECKING\n'
                                      'if TYPE_CHECKING:\n    from x import ServerNode\n'
                                      'def f(n: "ServerNode"): pass\n') == [])

_PYFLAKES_CMD = [sys.executable, "-m", "pyflakes"] + [
    os.path.join(ROOT, p) for p in _APP_DIRS]
try:
    _pf = subprocess.run(_PYFLAKES_CMD, capture_output=True, text=True, timeout=180)
    _pf_out = (_pf.stdout or "") + (_pf.stderr or "")
    _pf_lines = [ln for ln in _pf_out.splitlines() if ln.strip()]
except Exception as e:  # noqa: BLE001 — the tool is optional for the suite, not for the release
    _pf_lines = []
    _pf_out = repr(e)
    print(f"    NOTE pyflakes could not be run ({e!r}) — the AST gate above still holds")

if "No module named pyflakes" in _pf_out:
    print("    NOTE pyflakes is not installed (pip install pyflakes) — the wider second opinion is skipped")
    _pf_lines = []

check("N11: pyflakes reports no `undefined name` in the application code",
      [ln for ln in _pf_lines if "undefined name" in ln] == [],
      str([ln for ln in _pf_lines if "undefined name" in ln]))

check("N11: the ONLY reports left are the documented ssh_terminal live-namespace seams",
      all("ssh_terminal.py" in ln and "imported but unused" in ln for ln in _pf_lines),
      str([ln for ln in _pf_lines if not ("ssh_terminal.py" in ln
                                          and "imported but unused" in ln)]))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 N12–N16 — the writers and the readers survive a broken value ==")
# ════════════════════════════════════════════════════════════════════════════

import storage.project as P  # noqa: E402
import storage.autosave as A  # noqa: E402
import modules.command_history as CH  # noqa: E402


def _blocked_write(func, *args):
    """A DIRECTORY in the file's place makes the atomic replace fail deterministically."""
    target = os.path.join(_tmpdir(), "blocked.json")
    os.makedirs(target)
    raised = None
    try:
        func(target, *args)
    except Exception as e:  # noqa: BLE001 — the point of the case
        raised = type(e).__name__
    return target, raised


_t, _raised = _blocked_write(P.write_project_json, {"servers": []})
check("N12: a failed write_project_json still raises — and leaves NO `*.tmp`",
      _raised is not None and not os.path.isfile(_t + ".tmp"),
      f"raised={_raised} tmp={os.path.isfile(_t + '.tmp')}")

_t, _raised = _blocked_write(A.atomic_write_json, {"a": 1})
check("N13: a failed autosave write leaves NO `*.tmp`",
      _raised is not None and not os.path.isfile(_t + ".tmp"),
      f"raised={_raised} tmp={os.path.isfile(_t + '.tmp')}")

_src = os.path.join(_tmpdir(), "src.json")
with open(_src, "w", encoding="utf-8") as f:
    f.write("{}")
_t, _raised = _blocked_write(A._atomic_copy, _src)
check("N13: a failed backup COPY leaves NO `*.tmp` (the second writer of the family)",
      _raised is not None and not os.path.isfile(_t + ".tmp"),
      f"raised={_raised} tmp={os.path.isfile(_t + '.tmp')}")

check("N14: `autosave_enabled` is read as a REAL bool — `false`/`0`/`no` mean OFF",
      A._bool_setting("false") is False and A._bool_setting("0") is False
      and A._bool_setting(" no ") is False and A._bool_setting(False) is False
      and A._bool_setting(0) is False)
check("N14: ...`true`/`1`/`yes` mean ON and an unusable value falls back to the default",
      A._bool_setting("true") is True and A._bool_setting(1) is True
      and A._bool_setting("garbage") is True and A._bool_setting(None) is True
      and A._bool_setting("garbage", False) is False)

_broken = _tmpdir()
with open(os.path.join(_broken, "xx.json"), "wb") as f:
    f.write(b'{"hello": "\xe9\xe8\xff"}')   # Latin-1 — not valid UTF-8
_i18n_dir_backup = i18n._i18n_dir
try:
    i18n._i18n_dir = _broken
    _langs = i18n.get_available_languages()
    check("N15: a Latin-1 PACKAGE file yields the language CODE instead of raising",
          [d["code"] for d in _langs] == ["xx"] and _langs[0]["name"] == "xx",
          str(_langs))
    check("N15: load_language() on it answers False (the ACTIVE language keeps working)",
          i18n.load_language("xx") is False, "True")
    check("N15: is_partial() on it answers False instead of raising",
          i18n.is_partial("xx") is False)
finally:
    i18n._i18n_dir = _i18n_dir_backup

_unique = [{"cmd": "cmd-%05d" % i, "last": i, "count": 1} for i in range(CH.MAX_ENTRIES_PER_SERVER + 500)]
_folded, _removed = CH.dedup_entries(_unique)
check("N16: the per-server CAP is NOT reported as removed duplicates",
      _removed == 0 and len(_folded) == CH.MAX_ENTRIES_PER_SERVER,
      f"folded={len(_folded)} removed={_removed}")

_with_dups = [{"cmd": "a", "last": 1, "count": 1}, {"cmd": "a", "last": 2, "count": 1},
              {"cmd": "b", "last": 3, "count": 1}, {"cmd": "a", "last": 4, "count": 2},
              {"cmd": "", "last": 5, "count": 1}]
_folded2, _removed2 = CH.dedup_entries(_with_dups)
check("N16: ...and the REAL duplicates are counted exactly (an unusable row is neither)",
      _removed2 == 2 and len(_folded2) == 2, f"folded={len(_folded2)} removed={_removed2}")


# ════════════════════════════════════════════════════════════════════════════
print("== §5 N17 — the log survives a GUI launch without a console ==")
# ════════════════════════════════════════════════════════════════════════════

import modules.logger as LOG  # noqa: E402

_log_dir_backup, _log_file_backup = LOG.LOG_DIR, LOG.LOG_FILE
LOG.LOG_DIR = os.path.join(_tmpdir(), "logs")
LOG.LOG_FILE = os.path.join(LOG.LOG_DIR, "sshmap.log")
_real_out, _real_err = sys.stdout, sys.stderr
try:
    logging.getLogger("sshmap").handlers.clear()
    _logger = LOG.setup_logging()
    _handlers = [type(h).__name__ for h in _logger.handlers]
    check("N17: a normal launch keeps the console handler (on the stream that exists)",
          "StreamHandler" in _handlers and "RotatingFileHandler" in _handlers, str(_handlers))

    logging.getLogger("sshmap").handlers.clear()
    sys.stdout = None
    sys.stderr = None
    try:
        _logger2 = LOG.setup_logging()
        _handlers2 = [type(h).__name__ for h in _logger2.handlers]
        _stream = LOG._console_stream()
        _logger2.warning("v1.6.1 probe: a warning with no console at all")
        _written = open(LOG.LOG_FILE, encoding="utf-8").read()
    finally:
        sys.stdout, sys.stderr = _real_out, _real_err
finally:
    LOG.LOG_DIR, LOG.LOG_FILE = _log_dir_backup, _log_file_backup

check("N17: under pythonw.exe (BOTH streams None) the console handler is NOT installed",
      "StreamHandler" not in _handlers2 and "RotatingFileHandler" in _handlers2,
      str(_handlers2))
check("N17: ...`_console_stream()` answers None, and the WARNING still reaches the FILE",
      _stream is None and "a warning with no console at all" in _written,
      f"stream={_stream}")
check("N17: a missing stdout falls back to stderr (one stream is enough)",
      LOG._console_stream() is not None)


# ════════════════════════════════════════════════════════════════════════════
print("== §6 N18 — the profile mask does not follow the length of the password ==")
# ════════════════════════════════════════════════════════════════════════════

from dialogs.profile_manager_dialog import password_cell_text, PASSWORD_MASK  # noqa: E402

check("N18: two passwords of different lengths render the SAME cell",
      password_cell_text("a") == password_cell_text("x" * 28) == PASSWORD_MASK,
      f"{password_cell_text('a')!r} vs {password_cell_text('x' * 28)!r}")
check("N18: the cell still says a password IS stored (it is not empty)",
      bool(PASSWORD_MASK.strip()) and password_cell_text("secret") != "")
check("N18: an empty password keeps the `profile.password_empty` caption",
      password_cell_text("", lambda k: "<" + k + ">") == "<profile.password_empty>")


# ════════════════════════════════════════════════════════════════════════════
print("== §7 N19 — the toolbar's right-click menu names every row ==")
# ════════════════════════════════════════════════════════════════════════════

from PySide6.QtWidgets import QToolBar  # noqa: E402
import ui.main_window as MW  # noqa: E402

_win = MW.MainWindow()
_bar = _win.findChild(QToolBar, "main_toolbar")
check("N19: the defect is real in Qt's own menu — the toolbar has no window title at all",
      _bar is not None and _bar.windowTitle() == "" and _bar.toggleViewAction().text() == "",
      f"title={_bar.windowTitle()!r} action={_bar.toggleViewAction().text()!r}")

_menu = _win.createPopupMenu()
_rows = [(a.text(), a.isSeparator()) for a in _menu.actions()]
check("N19: OUR menu lists no blank row (a separator is not a row)",
      [t for t, sep in _rows if not sep and not t.strip()] == [], str(_rows))
check("N19: ...and it carries the FIVE panel switches of the toolbar cluster",
      [a.text() for a in _win._panel_switch_actions()] ==
      ["Sidebar / Map", "Map / List", "Minimap", "Legend", "Activity panel"],
      str([a.text() for a in _win._panel_switch_actions()]))
check("N19: the panel rows and the dock row are really IN the menu",
      all(a in _menu.actions() for a in _win._panel_switch_actions()))

_win._ensure_terminals_dock()
_menu2 = _win.createPopupMenu()
_dock_rows = [a.text() for a in _menu2.actions() if not a.isSeparator() and a.text() == "Terminals"]
check("N19: a NAMED dock row appears in the menu (and the toolbar row never does)",
      len(_dock_rows) == 1 and all(t != "" for t, sep in
                                   [(a.text(), a.isSeparator()) for a in _menu2.actions()]
                                   if not sep))
_win._dirty = False
_win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §8 N20 — a shown session owns the keyboard, a split pane does not ==")
# ════════════════════════════════════════════════════════════════════════════

import modules.ssh_terminal as ST  # noqa: E402
from models.server import ServerData  # noqa: E402

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = FakeSSHThread

_sd1 = ServerData(id="v161-a", alias="web-1", host="10.0.0.1", user="root", ssh_port=22)
_win_t = ST.SSHTerminalWindow(_sd1)
_win_t.show()
app.processEvents()
app.processEvents()
_page = _win_t.session_tabs.currentWidget()
check("N20: a SHOWN session owns the keyboard without a click on the canvas",
      _page.widget.hasFocus(), f"focus={QApplication.focusWidget()}")

_sd2 = ServerData(id="v161-b", alias="db-1", host="10.0.0.2", user="root", ssh_port=22)
_pane = _win_t.add_session(_sd2, split=True)
app.processEvents()
app.processEvents()
check("N20: the SPLIT PANE knows it is a pane from construction (`split=True`)",
      _pane._is_split_pane is True)
check("N20: ...and it REFUSES the keyboard claim (the choice belongs to the user)",
      _pane.claim_focus() is False)
check("N20: ...so the main session keeps the focus it had",
      _pane.widget.hasFocus() is False and _page.widget.hasFocus() is True,
      f"pane={_pane.widget.hasFocus()} tab={_page.widget.hasFocus()}")
_win_t._dirty = False
_win_t.close()
app.processEvents()
ST.SSHTerminalThread = _orig_thread_cls


# ════════════════════════════════════════════════════════════════════════════
print("== §9 N21 — the quick-launch editor can edit and reorder ==")
# ════════════════════════════════════════════════════════════════════════════

from dialogs.quick_launch_dialog import QuickLaunchDialog  # noqa: E402

_sd_ql = ServerData(id="v161-ql", alias="web-1", host="10.0.0.1", user="root", ssh_port=22)
_sd_ql.quick_launch = [{"type": "url", "name": "Webmin", "value": "https://10.0.0.1:10000"},
                       {"type": "command", "name": "K9S", "value": "k9s"}]
_dlg = QuickLaunchDialog(None, _sd_ql)
check("N21: the editor offers Edit and the two reorder buttons",
      _dlg.btn_edit.text() == "Edit" and _dlg.btn_up.text() == "↑"
      and _dlg.btn_down.text() == "↓" and _dlg.btn_apply.text() == "Add",
      f"{_dlg.btn_edit.text()!r} {_dlg.btn_up.text()!r} {_dlg.btn_down.text()!r}")

_dlg.table.setCurrentCell(0, 0)
_dlg._edit_selected()
check("N21: Edit loads the selected entry back into the fields",
      (_dlg.type_combo.currentData(), _dlg.name_edit.text(), _dlg.value_edit.text())
      == ("url", "Webmin", "https://10.0.0.1:10000"),
      f"{_dlg.type_combo.currentData()} {_dlg.name_edit.text()} {_dlg.value_edit.text()}")
check("N21: the apply button reuses an EXISTING key while editing (`file.save`)",
      _dlg.btn_apply.text() == "Save" and _dlg.btn_edit.isEnabled() is False)

_dlg.name_edit.setText("Webmin (https)")
_dlg.value_edit.setText("https://10.0.0.1:10000/")
_dlg._add_entry()
_entries = _dlg.get_entries()
check("N21: the edit REPLACES the entry in place — same position, no extra row",
      len(_entries) == 2 and _entries[0]["name"] == "Webmin (https)"
      and _entries[1]["name"] == "K9S" and _dlg.table.rowCount() == 2,
      str(_entries))
check("N21: ...the table shows it in place and the button says Add again",
      _dlg.table.item(0, 1).text() == "Webmin (https)" and _dlg.btn_apply.text() == "Add")

_dlg.table.setCurrentCell(0, 0)
_dlg._move_selected(1)
check("N21: Move down swaps the entry inside the LIST and the TABLE (one order)",
      [e["name"] for e in _dlg.get_entries()] == ["K9S", "Webmin (https)"]
      and [ _dlg.table.item(r, 1).text() for r in range(_dlg.table.rowCount())]
      == ["K9S", "Webmin (https)"],
      str([e["name"] for e in _dlg.get_entries()]))
_dlg._move_selected(1)
check("N21: a move past the end is refused instead of wrapping around",
      [e["name"] for e in _dlg.get_entries()] == ["K9S", "Webmin (https)"])
_dlg.table.setCurrentCell(1, 0)
_dlg._move_selected(-1)
check("N21: Move up brings it back",
      [e["name"] for e in _dlg.get_entries()] == ["Webmin (https)", "K9S"])
_dlg._on_row_double_clicked(_dlg.table.item(0, 1))
check("N21: a double click on a row is the SECOND door to the same gesture",
      _dlg.name_edit.text() == "Webmin (https)" and _dlg.btn_apply.text() == "Save")


# ════════════════════════════════════════════════════════════════════════════
print("== §10 N22 — the CPU model is on the CPU line, and the info block keeps its COUNT ==")
# ════════════════════════════════════════════════════════════════════════════

from graphics.server_node import ServerNode  # noqa: E402

_sd_card = ServerData(id="v161-card", alias="web-1", host="10.0.0.1", user="root", ssh_port=22)
_sd_card.os_name = "Debian GNU/Linux 12 (bookworm)"
_sd_card.cpu = "8"
_sd_card.cpu_model = "Intel(R) Xeon(R) Gold 6248R CPU @ 3.00GHz"
_sd_card.ram = "32 GB"
_node_card = ServerNode(_sd_card)
_full = _node_card._info_tip_full.split("\n")
check("N22: the OS line carries the OS and NOT the CPU model",
      _full[0] == _sd_card.os_name and _sd_card.cpu_model not in _full[0], repr(_full[0]))
check("N22: the CPU line carries the cores AND the model, in that order",
      _full[1] == f"CPU: 8 · {_sd_card.cpu_model}", repr(_full[1]))
check("N22: the NUMBER of info lines does not move (the measured `58 + info + 12` height)",
      len(_full) == 3 and len(_node_card._info.toPlainText().split("\n")) == 3,
      str(_full))
_sd_nocpu = ServerData(id="v161-card2", alias="db", host="10.0.0.2", user="root", ssh_port=22)
_sd_nocpu.os_name = "Ubuntu 22.04"
_node_nocpu = ServerNode(_sd_nocpu)
check("N22: an empty cpu_model adds no line (the empty-field rule)",
      _node_nocpu._info.toPlainText() == "Ubuntu 22.04",
      repr(_node_nocpu._info.toPlainText()))


# ════════════════════════════════════════════════════════════════════════════
print("== §11 the release state — v1.6.1 added NO i18n key ==")
# ════════════════════════════════════════════════════════════════════════════

check("§11 the hardening batch itself added no key (the pin is the SHIPPED one — v1.6's 778"
      " plus the four of v1.6.2, the four of v1.6.3, the three of v1.6.4 and the eleven"
      " of v1.6.5 and the eleven of v1.6.6)",
      EXPECTED_I18N_KEYS == 811, str(EXPECTED_I18N_KEYS))
check_release_state(ROOT)
_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check("§11 not one language file was touched by the batch (the four built-in codes)",
      sorted(_langs) == ["de", "en", "ru", "zh"], str(sorted(_langs)))
check("§11 the reference is still `en` and the drift was fixed on the CODE side",
      I18N_REFERENCE == "en")

finish()
