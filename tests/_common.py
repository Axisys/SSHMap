"""The common harness of the SSHMap tests (plain scripts, no pytest) — `tests/INDEX.md` maps the files.

The pattern of every `tests/test_*.py`:
    from _common import bootstrap, check, finish
    ROOT, WORK = bootstrap()   # FIRST — before the imports of the app modules
    ... check("name", condition, detail) ...
    finish()                   # the summary, the exit code (0 = all passed) and the slowest checks
Each file runs as its own process; `python tests/run_all.py` runs the whole suite in parallel.

`bootstrap()` does the isolation: UTF-8 stdout/stderr (a cp1251 console must not die on a "→"),
HOME/USERPROFILE redirected into a temporary directory BEFORE the app modules are imported (so
`~/.sshmap/config.json` and friends never touch the real home; disable with `SSHMAP_TEST_NO_HOME_ISOLATION=1`), `QT_QPA_PLATFORM=offscreen` unless the user set one, `sys.path` with the project root, a fresh working folder per run (`_tmp_testdata`, or `$SSHMAP_TEST_WORKDIR` under the parallel runner) and a 180 s faulthandler timeout that dumps the stacks of a hung offscreen run."""
import json
import os
import re
import shutil
import sys
import tempfile
import time

PASS = []
FAIL = []

# Suite optimization phase 1: the time measurement. check() records how long it took
# the test segment BEFORE this check (time since the previous check()); finish()
# prints the "slowest checks" (only if there are checks >= SLOW_REPORT_THRESHOLD)
# and the total file time in the ALL PASS/FAILURES line. The check() signature is unchanged.
_T0 = None      # the file run start (sets bootstrap())
_LAST = None    # the moment of the last check()
_SLOW = []      # [(dt, name), …] — the segment time for every check
SLOW_REPORT_THRESHOLD = 0.1   # sec; the "slowest checks" output threshold


def bootstrap(faulthandler_timeout=180):
    """Initialize the test environment. Call before the imports of the app modules."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # an old Python without reconfigure — we live as before

    if os.environ.get("SSHMAP_TEST_NO_HOME_ISOLATION") != "1":
        _home = tempfile.mkdtemp(prefix="sshmap_test_home_")
        os.environ["HOME"] = _home
        os.environ["USERPROFILE"] = _home

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    # A parallel run_all.py passes a per-file unique directory via
    # SSHMAP_TEST_WORKDIR (otherwise the bootstrap() of the neighbouring process would wipe the scratch);
    # a single run — the fixed _tmp_testdata (gitignored).
    work = os.environ.get("SSHMAP_TEST_WORKDIR") or os.path.join(root, "_tmp_testdata")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    if faulthandler_timeout:
        import faulthandler
        faulthandler.dump_traceback_later(faulthandler_timeout, exit=True)

    global _T0, _LAST
    _T0 = time.monotonic()
    _LAST = _T0

    return root, work


def check(name, cond, detail=""):
    """One check: prints ok/FAIL and accumulates into PASS/FAIL.

    Additionally measures the time of the segment up to this check (since the previous
    check()) — finish() prints the top-20 of the slowest segments."""
    global _LAST
    dt = time.monotonic() - _LAST if _LAST is not None else 0.0
    _LAST = time.monotonic()
    _SLOW.append((dt, name))
    (PASS if cond else FAIL).append((name, detail))
    print(("  ok  " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


def finish():
    """The summary and the exit code: 0 = all the checks passed."""
    total = len(PASS) + len(FAIL)
    elapsed = time.monotonic() - _T0 if _T0 is not None else 0.0
    print()
    if FAIL:
        print(f"FAILURES ({len(FAIL)}) of {total}:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
        print(f"(file time: {elapsed:.2f} s)")
        sys.exit(1)
    if _SLOW and max(dt for dt, _ in _SLOW) >= SLOW_REPORT_THRESHOLD:
        print("== slowest checks ==")
        for dt, name in sorted(_SLOW, reverse=True)[:20]:
            print(f"  {dt:8.3f}s  {name}")
    print(f"ALL PASS ({total}) [{elapsed:.2f}s]")


def wait_until(cond, timeout_ms=3000, tick_ms=50):
    """The real Qt event loop until cond() or the deadline (the regression_v081 pattern)."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    ticks = {"n": 0}

    def _tick():
        if not cond() and ticks["n"] * tick_ms < timeout_ms:
            ticks["n"] += 1
        elif loop.isRunning():
            loop.quit()

    tmr = QTimer()
    tmr.setInterval(tick_ms)
    tmr.timeout.connect(_tick)
    tmr.start()
    loop.exec()
    tmr.stop()


def wait_for(predicate, timeout_ms=3000, tick_ms=10):
    """Drive `processEvents()` until predicate() is true; return a BOOL (v1.4.1 suite cleanup).

    `wait_until()` above runs a REAL Qt event loop and returns nothing; this poll is for a
    predicate fed by plain Python threads / queued signals (the plugin tests): it returns
    True/False, so `check(..., wait_for(...))` fails honestly on a timeout.

    Do not swap one for the other: `wait_until(...) is not False` against the event-loop
    version is TRUE even on a timeout (`None is not False`), which is a silently passing check.
    """
    import time as _time
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = _time.monotonic() + timeout_ms / 1000.0
    while _time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        _time.sleep(tick_ms / 1000.0)
    if app is not None:
        app.processEvents()
    return bool(predicate())


def viewport_point(view, scene_pos):
    """The scene → a QPoint in the coordinates of the viewport (Qt 6.11: mapFromScene can give a QPoint or a QPointF)."""
    from PySide6.QtCore import QPoint
    q = view.mapFromScene(scene_pos)
    return QPoint(int(q.x()), int(q.y()))


def snapshot_i18n_config():
    """The snapshot of ~/.sshmap/config.json (None, if the file is absent).

    The tests switching the language (set_language) write into the config; under the isolated
    HOME this is the sandbox and the snapshot is not needed, but with SSHMAP_TEST_NO_HOME_ISOLATION=1
    it preserves the real config of the user.
    """
    p = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return (p, f.read())


def restore_i18n_config(snap):
    """The restore of the i18n config from the snapshot of snapshot_i18n_config()."""
    if snap is None:
        return
    try:
        with open(snap[0], "w", encoding="utf-8") as f:
            f.write(snap[1])
    except OSError:
        pass  # sandbox may block writes to ~ — config untouched anyway


# ─────────────────────────────────────────────────────────────────────────────
# config.json — the shared fixture helpers (call `bootstrap()` FIRST: the path comes from
# the isolated HOME). The two divergences of the per-file variants are explicit arguments
# now: a missing file as {} vs None, and the write MERGING (`i18n.save_config`) or REPLACING.
# ─────────────────────────────────────────────────────────────────────────────

def cfg_path() -> str:
    """`~/.sshmap/config.json` of the sandbox HOME."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def read_cfg(default=None):
    """The parsed config.json.

    `default` is what a MISSING or unreadable file yields — `{}` for "no settings
    yet" (the usual test fixture) or `None` for "was the file there at all?".
    A non-object JSON root counts as missing (the app ignores such a file too).
    """
    try:
        with open(cfg_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, dict) else default


def write_cfg(data) -> None:
    """A WHOLE-DOCUMENT write: what is on disk is exactly `data` (the folder is created)."""
    path = cfg_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def merge_cfg(data) -> None:
    """A MERGE write — the `i18n.save_config` semantics: the foreign keys survive.

    This is the behaviour a test needs when it changes ONE setting and then checks
    that the others are still there.
    """
    current = read_cfg({}) or {}
    current.update(data)
    write_cfg(current)


def clear_cfg(*extra_paths: str) -> None:
    """Remove config.json (and any extra path passed — e.g. a legacy settings file).

    No arguments = the ordinary "a clean config for this section" call.
    """
    for path in (cfg_path(),) + tuple(extra_paths):
        try:
            os.remove(path)
        except OSError:
            pass


# The MainWindow FAMILY: the facade module plus every `ui/main_window_*.py` mixin. A cluster of the
# window moves into a mixin without changing a line of a method's body, so an audit that pins a method
# reads it WHEREVER the family defines it — a pin that names `ui/main_window.py` stops protecting the
# day the method moves (`AGENTS.md` §9, `ROADMAP.md`'s 1.8rc wave).
WINDOW_FAMILY_GLOB = os.path.join("ui", "main_window*.py")


def window_family_files(root):
    """Every file of the MainWindow family, as paths relative to `root` (sorted, one glob)."""
    import glob
    return sorted(os.path.relpath(p, root).replace("\\", "/")
                  for p in glob.glob(os.path.join(root, WINDOW_FAMILY_GLOB)))


def window_family_sources(root):
    """{relative path: source} of the MainWindow family — the facade and every mixin."""
    out = {}
    for rel in window_family_files(root):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            out[rel] = fh.read()
    return out


def window_func_body(func, root=None, docstring=False):
    """The source of ONE method of the MainWindow family, its docstring STRIPPED by default.

    A source audit has to look at the CODE, not at the prose (a docstring that NAMES a call while
    explaining why the method must not make it would fail its own check), and the method may live in any
    file of the family. Raises KeyError when no file of the family defines `func`.
    """
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, source in window_family_sources(root).items():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
                body = list(node.body)
                if not docstring and body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    body = body[1:]  # drop the docstring
                return ast.unparse(ast.Module(body=body or [ast.Pass()], type_ignores=[]))
    raise KeyError(f"{func} is not defined anywhere in the MainWindow family "
                   f"({', '.join(window_family_files(root))})")


def window_func_owner(func, root=None):
    """The family file that defines `func` ('' — none). The owner question a split audit asks."""
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, source in window_family_sources(root).items():
        for node in ast.parse(source).body:
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == func:
                        return rel
    return ""


# The `TerminalWidget` FAMILY: `modules/terminal_widget.py` plus every `terminal_widget_*.py` mixin.
# The same rule as the MainWindow and `_SftpPane` families: a canvas cluster moves into a mixin without
# changing a line of a method's body, so a pin reads it WHEREVER the family defines it.
CANVAS_FAMILY_GLOB = os.path.join("modules", "terminal_widget*.py")
CANVAS_FACADE = "modules/terminal_widget.py"


def canvas_family_files(root):
    """Every file of the canvas family, as paths relative to `root` (sorted, one glob)."""
    import glob
    found = sorted(os.path.relpath(p, root).replace("\\", "/")
                   for p in glob.glob(os.path.join(root, CANVAS_FAMILY_GLOB)))
    return [rel for rel in found if rel == CANVAS_FACADE] + \
           [rel for rel in found if rel != CANVAS_FACADE]


def canvas_family_sources(root):
    """{relative path: source} of the canvas family — the facade and every mixin."""
    out = {}
    for rel in canvas_family_files(root):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            out[rel] = fh.read()
    return out


def canvas_family_text(root):
    """The family's sources as ONE text — a substring pin that follows the code (never a file name)."""
    return "\n".join(canvas_family_sources(root).values())


def canvas_func_body(func, root=None, docstring=False):
    """The source of ONE method of the canvas family, its docstring STRIPPED by default.

    The `window_func_body()` rule applied to the canvas wave: the audit looks at the CODE and the
    method may live in any file of the family. Raises KeyError when no file defines `func`.
    """
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, source in canvas_family_sources(root).items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
                body = list(node.body)
                if not docstring and body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    body = body[1:]  # drop the docstring
                return ast.unparse(ast.Module(body=body or [ast.Pass()], type_ignores=[]))
    raise KeyError(f"{func} is not defined anywhere in the canvas family "
                   f"({', '.join(canvas_family_files(root))})")


def canvas_func_owner(func, root=None):
    """The family file that defines `func` ('' — none). The owner question the canvas wave asks."""
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, source in canvas_family_sources(root).items():
        for node in ast.parse(source).body:
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == func:
                        return rel
    return ""


# The `_SftpPane` FAMILY: the `modules/sftp_tab.py` facade plus every `sftp_pane_*.py` pane mixin.
# Same rule as the MainWindow family above (`ROADMAP.md`'s `1.8rc4` wave): a pane cluster moves into
# a mixin without changing a line of a method's body, so a pin must read it WHEREVER the family
# defines it — a pin that names `modules/sftp_tab.py` stops protecting the day the method moves.
PANE_FAMILY_GLOB = os.path.join("modules", "sftp_pane*.py")
PANE_FACADE = "modules/sftp_tab.py"


def pane_family_files(root):
    """Every file of the pane family, as paths relative to `root` (sorted, one glob + the facade)."""
    import glob
    found = sorted(os.path.relpath(p, root).replace("\\", "/")
                   for p in glob.glob(os.path.join(root, PANE_FAMILY_GLOB)))
    return [PANE_FACADE] + [rel for rel in found if rel != PANE_FACADE]


def pane_family_sources(root):
    """{relative path: source} of the pane family — the facade and every pane mixin."""
    out = {}
    for rel in pane_family_files(root):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            out[rel] = fh.read()
    return out


def pane_family_text(root):
    """The family's sources as ONE text — a substring pin that follows the code (never a file name)."""
    return "\n".join(pane_family_sources(root).values())


def pane_func_body(func, root=None, docstring=False):
    """The source of ONE method of the `_SftpPane` family, its docstring STRIPPED by default.

    The `window_func_body()` rule applied to the pane wave: the audit looks at the CODE (a docstring
    that NAMES a call while explaining why it must not be made would fail its own check) and the
    method may live in any file of the family. Raises KeyError when no file defines `func`.
    """
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, source in pane_family_sources(root).items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
                body = list(node.body)
                if not docstring and body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    body = body[1:]  # drop the docstring
                return ast.unparse(ast.Module(body=body or [ast.Pass()], type_ignores=[]))
    raise KeyError(f"{func} is not defined anywhere in the pane family "
                   f"({', '.join(pane_family_files(root))})")


def pane_func_owner(func, root=None):
    """The family file that defines `func` ('' — none). The owner question the pane wave asks."""
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, source in pane_family_sources(root).items():
        for node in ast.parse(source).body:
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == func:
                        return rel
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# The release pins: at every release update ONLY HERE (earlier: the "N keys" number
# in 12 i18n files + the APP_VERSION/requirements pins in 7 release-state sections).
# The misses of the keys themselves against the code are caught by check_i18n_keys.py.
# ─────────────────────────────────────────────────────────────────────────────
EXPECTED_APP_VERSION = "1.8.2"   # the current release (a sentinel: it catches "a bump to the wrong version")
EXPECTED_I18N_KEYS = 1003       # the parity of the TRANSLATION keys of every language file vs en (the
                                # "name"/"partial" meta keys are excluded) — ONE number per release; the
                                # per-release counts live in the changelog family, never here
VERSION_FORMAT_RE = re.compile(r"^\d+(\.\d+){1,3}([Rr][Cc]\d+)?$")  # "1.1.3", "1.0RC4", "0.9.9.7", "1.2.10rc1" (v1.2.10: + lowercase rc)

# The test-file counter quoted by README.md / ROADMAP.md is checked against the real
# number of tests/test_*.py : the counter is easy to forget — it went stale twice in one stretch,
# so the guard parses the documents and
# asserts every quoted counter equals this number (tests/test_i18n_live.py).
TEST_FILE_COUNTER_RE = re.compile(r"(\d+)\s+(?:test[ _-]?files?|test_\*\.py)")
# The key-count figures a version section quotes: "parity: 458", "parity **458 → 459**",
# "parity baseline (v1.3.3.1): 460". A "~" marks a deliberately approximate figure and
# is skipped (the guard compares EXACT numbers). FOUR digits are accepted: the pin
# crossed 1000 with v1.8.2, and a three-only pattern silently read "100" out of "1003".
I18N_PARITY_FIGURE_RE = re.compile(r"parity[^\n]{0,32}?(?<!~)(\d{3,4})")

# v1.3.3: the meta keys of a language file — file metadata, not UI strings.
# A language file: {"name": "Русский", "partial": true, "menu.file": "Файл", …}. "name" is the language
# name in its own language; "partial": true marks a DELIBERATELY incomplete file — it loads and works
# (the en-fallback is unchanged) but its missing keys are a WARNING, not a defect. Both are excluded
# from the key parity; a missing "name" only degrades the display to the code.
I18N_META_KEYS = frozenset({"name", "partial"})
I18N_REFERENCE = "en"   # the source language: every other file must cover 100% of its keys
I18N_LANG_ENCODING = "utf-8-sig"   # v1.3.3.1: a Notepad "UTF-8 with BOM" file must load
I18N_PARTIAL_KEY = "partial"       # the meta key of a deliberately incomplete language


def i18n_lang_codes(root):
    """Auto-discovery of the languages: every i18n/*.json is a language, the file name is its code."""
    i18n_dir = os.path.join(root, "i18n")
    if not os.path.isdir(i18n_dir):
        return []
    return sorted(f[:-len(".json")] for f in os.listdir(i18n_dir) if f.endswith(".json"))


def translation_keys(data):
    """The TRANSLATION keys of a loaded language file (the meta keys are dropped)."""
    return {k for k in data if k not in I18N_META_KEYS}


def is_partial_lang(data) -> bool:
    """Is this loaded language file marked `"partial": true` (v1.3.3.1)?

    Only a real JSON `true` counts — a string "true" / 1 / a missing key keeps the
    file under the STRICT parity policy.
    """
    return isinstance(data, dict) and data.get(I18N_PARTIAL_KEY) is True


def load_i18n_langs(root, codes=None, encoding=None):
    """i18n/*.json → {code: dict} (the shared loading for the parity checks).

    v1.3.3: auto-discovery (the file name is the code) — a dropped-in language file is
    picked up by the checks without touching them. codes=… narrows the set.
    v1.3.3.1: read as "utf-8-sig" by default — a BOM saved by Notepad loads exactly
    like a plain UTF-8 file (pass encoding=… to re-read a file as raw UTF-8).
    """
    langs = {}
    for code in (i18n_lang_codes(root) if codes is None else codes):
        path = os.path.join(root, "i18n", f"{code}.json")
        with open(path, encoding=encoding or I18N_LANG_ENCODING) as f:
            langs[code] = json.load(f)
    return langs


# ── v1.3.3.1 (ROADMAP task 4): placeholders and line breaks ──────────────────
# The two defect types the v1.3.3 policy could not see. The helpers live HERE (the
# "one place" rule): both tests/check_i18n_keys.py and tests/test_i18n_languages.py /
# tests/test_i18n_live.py consume them.

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def placeholder_names(value) -> set:
    """The SET of `{placeholder}` names of one translation value (not a string → empty).

    The SET, not the list: the ORDER of the placeholders in a sentence is a language
    matter ("{alias} auf {host}" vs "{host} → {alias}"), their PRESENCE is not.
    """
    if not isinstance(value, str):
        return set()
    return set(PLACEHOLDER_RE.findall(value))


def newline_count(value) -> int:
    """The COUNT of `\\n` line breaks of one translation value (not a string → 0).

    The count (not the positions): word order differs between languages, the number
    of lines a dialog shows does not.
    """
    if not isinstance(value, str):
        return 0
    return value.count("\n")


def i18n_format_problems(langs, reference=I18N_REFERENCE):
    """The placeholder / line-break defects of the discovered languages vs the reference.

    For every translation key present in BOTH the reference and the language:
    the SET of `{placeholder}` names must match, and the COUNT of `\\n` must match.
    A partial language (`"partial": true`) skips the check — its strings are still
    being written. Returns {code: [problem, …]} with only the languages that have any.
    """
    if reference not in langs:
        return {}
    ref = langs[reference]
    out = {}
    for code in sorted(langs):
        if code == reference or is_partial_lang(langs[code]):
            continue
        problems = []
        for key, ref_value in ref.items():
            if key in I18N_META_KEYS or key not in langs[code]:
                continue
            value = langs[code][key]
            ph_ref, ph_got = placeholder_names(ref_value), placeholder_names(value)
            if ph_ref != ph_got:
                problems.append(
                    f"{key}: placeholders {sorted(ph_got)} vs {reference} {sorted(ph_ref)}")
            nl_ref, nl_got = newline_count(ref_value), newline_count(value)
            if nl_ref != nl_got:
                problems.append(
                    f"{key}: {nl_got} line break(s) vs {reference} {nl_ref}")
        if problems:
            out[code] = problems
    return out


def i18n_parity_warnings(langs, reference=I18N_REFERENCE):
    """The parity WARNINGS of the discovered languages: [] = none.

    v1.3.3.1 (ROADMAP task 2): a file with the meta key `"partial": true` is a
    deliberately incomplete translation — it loads and works (the runtime
    en-fallback covers the missing keys), so its MISSING keys and its key COUNT are
    reported here as warnings instead of defects. Everything else stays strict.
    """
    if reference not in langs:
        return []
    ref_keys = translation_keys(langs[reference])
    warnings = []
    for code in sorted(langs):
        data = langs[code]
        if not is_partial_lang(data):
            continue
        keys = translation_keys(data)
        missing = sorted(ref_keys - keys)
        count_note = ""
        if len(keys) != len(ref_keys):
            count_note = f" ({len(keys)} of {len(ref_keys)} {reference} keys)"
        if missing or count_note:
            detail = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
            warnings.append(
                f"{code}: partial language — {len(missing)} key(s) fall back to {reference}"
                + (f": {detail}" if detail else "") + count_note)
    return warnings


def i18n_parity_problems(langs, expected_keys=None, reference=I18N_REFERENCE):
    """The parity defects among the discovered languages: [] = clean.

    The policy (v1.3.3): a built-in language must cover 100% of the reference (en)
    keys — STRICT parity, so an extra key is a defect as well (it would be dead
    weight in one file only) — and the count is pinned by EXPECTED_I18N_KEYS.
    Meta keys are not translations and are ignored here.

    v1.3.3.1: a `"partial": true` file is graded leniently — its MISSING keys and the
    count mismatch are warnings (`i18n_parity_warnings`), not defects. An EXTRA key
    is still a defect: a key that en does not have is dead weight / a typo, in a
    partial file as much as in a strict one.
    """
    expected = EXPECTED_I18N_KEYS if expected_keys is None else expected_keys
    if reference not in langs:
        return [f"the reference language {reference!r} is not among the discovered files"]
    ref_keys = translation_keys(langs[reference])
    problems = []
    for code in sorted(langs):
        keys = translation_keys(langs[code])
        partial = is_partial_lang(langs[code])
        missing = sorted(ref_keys - keys)
        extra = sorted(keys - ref_keys)
        if missing and not partial:
            problems.append(f"{code}: {len(missing)} key(s) missing vs {reference}: "
                            + ", ".join(missing[:5]) + ("…" if len(missing) > 5 else ""))
        if extra:
            problems.append(f"{code}: {len(extra)} key(s) not in {reference}: "
                            + ", ".join(extra[:5]) + ("…" if len(extra) > 5 else ""))
        if expected is not None and len(keys) != expected and not partial:
            problems.append(f"{code}: {len(keys)} translation keys (the pin EXPECTED_I18N_KEYS = {expected})")
    return problems


def check_i18n_parity(langs):
    """The parity over the DISCOVERED languages: identical translation key sets vs en + the pinned count."""
    problems = i18n_parity_problems(langs)
    check(
        f"i18n parity: {len(langs)} language(s) × {EXPECTED_I18N_KEYS} keys "
        f"({', '.join(sorted(langs))})",
        not problems,
        "; ".join(problems) + " | "
        + str({c: len(translation_keys(d)) for c, d in sorted(langs.items())}))


def check_i18n_format(langs):
    """v1.3.3.1: the placeholder / line-break parity of the discovered languages vs en.

    Partial languages are skipped by `i18n_format_problems` (their strings are still
    being written); the warnings of partial languages are reported in the detail so a
    deliberate incompleteness is still visible in the log.
    """
    problems = i18n_format_problems(langs)
    warnings = i18n_parity_warnings(langs)
    check(
        f"i18n format: placeholders + line breaks of {len(langs)} language(s) vs {I18N_REFERENCE}"
        + (f" (+{len(warnings)} partial warning(s))" if warnings else ""),
        not problems,
        "; ".join(f"{c}: {p[0]} (+{len(p) - 1} more)" for c, p in sorted(problems.items()))
        + (" | warnings: " + " | ".join(warnings) if warnings else ""))


def releases_at_least(value, release=None):
    """True while `value` (default: the SHIPPED `EXPECTED_APP_VERSION`) is `release` or a LATER one.

    A topical test file describes the release it was written for, but `EXPECTED_APP_VERSION` is the
    LIVE pin (the whole suite is re-pointed at every release), so an equality against it breaks by
    definition the moment the next release ships. The version tuple is compared component by component
    (`rcN` counts as `N`), and a file may therefore state "this release or later" — the properties it
    really guards (the parity pin, the behaviour) stay exact, and only the sentinel moves on. The
    two-argument form (`releases_at_least(APP_VERSION, "1.7rc2")`) also lets a file check the value
    `version.py` really carries.
    """
    if release is None:
        release = value
        value = EXPECTED_APP_VERSION

    def parts(text):
        digits = [int(n) for n in re.findall(r"\d+", str(text or ""))]
        return tuple(digits + [0] * (4 - len(digits)))[:4] if digits else (0, 0, 0, 0)

    return parts(value) >= parts(release)


def check_release_state(root):
    """The state of the release from version.py (the single source of truth): the sentinel
    EXPECTED_APP_VERSION + the format + the pyproject cross-check + the header of requirements.txt.
    Call AFTER bootstrap() — the version is imported inside the function."""
    try:
        from version import APP_VERSION
    except Exception as e:  # noqa: BLE001
        check("release: version.py is readable", False, repr(e))
        return

    check(f"release: APP_VERSION == '{EXPECTED_APP_VERSION}'",
          APP_VERSION == EXPECTED_APP_VERSION, APP_VERSION)
    check("release: APP_VERSION format (X.Y.Z[.W][RCn])",
          bool(VERSION_FORMAT_RE.match(APP_VERSION)), APP_VERSION)
    try:
        try:
            import tomllib as _toml
        except ModuleNotFoundError:
            import tomli as _toml  # type: ignore
        with open(os.path.join(root, "pyproject.toml"), "rb") as f:
            _pp = _toml.load(f)
        check("release: pyproject version == APP_VERSION",
              _pp["project"]["version"] == APP_VERSION, str(_pp["project"].get("version")))
    except Exception as e:  # noqa: BLE001
        check("release: pyproject version == APP_VERSION", False, repr(e))
    try:
        with open(os.path.join(root, "requirements.txt"), encoding="utf-8") as f:
            _head = f.readline()
        pat = re.compile(rf"v{re.escape(APP_VERSION)}(?![A-Za-z0-9])")
        check(f"release: requirements.txt header carries v{APP_VERSION}",
              pat.search(_head) is not None, _head.strip())
    except Exception as e:  # noqa: BLE001
        check(f"release: requirements.txt header carries v{APP_VERSION}", False, repr(e))
