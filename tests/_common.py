"""The common harness of the SSHMap tests (the scripts without pytest).

The pattern of every file tests/test_*.py:

    from _common import bootstrap, check, finish
    ROOT, WORK = bootstrap()   # FIRST — before the imports of the app modules

...the body of the test with check("name", condition, detail) ...

    finish()   # the summary + the exit code (0 = all the checks passed); prints the time of the file
               # and the "slowest checks" (segments >= 0.1 s — the top-20, see SLOW_REPORT_THRESHOLD)

Run all the tests:  python tests/run_all.py
The map of the files and the conventions:  tests/INDEX.md

What bootstrap() does:
  * UTF-8 stdout/stderr — the cp1251 console (the typical Russian Windows) does not
    drop the run with a UnicodeEncodeError on the "→" in the report;
  * the isolation of HOME/USERPROFILE into a temporary directory BEFORE the imports
    of the app modules: the tests write ~/.sshmap/config.json, ~/.sshmap_settings.json and the like —
    all the I/O goes to the sandbox, the real home is untouched (disabled by
    SSHMAP_TEST_NO_HOME_ISOLATION=1);
  * QT_QPA_PLATFORM=offscreen by default (if the user did not set their own);
  * sys.path: the root of the project; the working folder — a fresh one per run
    (_tmp_testdata, or $SSHMAP_TEST_WORKDIR under the parallel run_all.py);
  * the faulthandler timeout of 180 s: the hung offscreen (the modal) — the dump of the stacks and the exit.
"""
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
# The release pins: at every release update ONLY HERE (earlier: the "N keys" number
# in 12 i18n files + the APP_VERSION/requirements pins in 7 release-state sections).
# The misses of the keys themselves against the code are caught by check_i18n_keys.py.
# ─────────────────────────────────────────────────────────────────────────────
EXPECTED_APP_VERSION = "1.3.3"  # the current release (a sentinel: it catches "a bump to the wrong version")
EXPECTED_I18N_KEYS = 458        # the parity of the TRANSLATION keys (v1.3.3 has no new keys — the
                                # "name" meta key of the language files is NOT a translation and is
                                # excluded here and in check_i18n_keys.py). v1.3.2: +5 settings.hotkeys.*
                                # / settings.tab.hotkeys → 458; before, 453 since v1.3.1
VERSION_FORMAT_RE = re.compile(r"^\d+(\.\d+){1,3}([Rr][Cc]\d+)?$")  # "1.1.3", "1.0RC4", "0.9.9.7", "1.2.10rc1" (v1.2.10: + lowercase rc)

# v1.3.3: the meta keys of a language file — file metadata, not UI strings.
# A language file: {"name": "Русский", "menu.file": "Файл", …}. "name" is the
# language name in its own language; it is excluded from the key parity (a missing
# one only degrades the display to the code, it does not break the language).
I18N_META_KEYS = frozenset({"name"})
I18N_REFERENCE = "en"   # the source language: every other file must cover 100% of its keys


def i18n_lang_codes(root):
    """Auto-discovery of the languages: every i18n/*.json is a language, the file name is its code."""
    i18n_dir = os.path.join(root, "i18n")
    if not os.path.isdir(i18n_dir):
        return []
    return sorted(f[:-len(".json")] for f in os.listdir(i18n_dir) if f.endswith(".json"))


def translation_keys(data):
    """The TRANSLATION keys of a loaded language file (the meta keys are dropped)."""
    return {k for k in data if k not in I18N_META_KEYS}


def load_i18n_langs(root, codes=None):
    """i18n/*.json → {code: dict} (the shared loading for the parity checks).

    v1.3.3: auto-discovery (the file name is the code) — a dropped-in language file is
    picked up by the checks without touching them. codes=… narrows the set.
    """
    langs = {}
    for code in (i18n_lang_codes(root) if codes is None else codes):
        with open(os.path.join(root, "i18n", f"{code}.json"), encoding="utf-8") as f:
            langs[code] = json.load(f)
    return langs


def i18n_parity_problems(langs, expected_keys=None, reference=I18N_REFERENCE):
    """The parity defects among the discovered languages: [] = clean.

    The policy (v1.3.3): a built-in language must cover 100% of the reference (en)
    keys — STRICT parity, so an extra key is a defect as well (it would be dead
    weight in one file only) — and the count is pinned by EXPECTED_I18N_KEYS.
    Meta keys are not translations and are ignored here.
    """
    expected = EXPECTED_I18N_KEYS if expected_keys is None else expected_keys
    if reference not in langs:
        return [f"the reference language {reference!r} is not among the discovered files"]
    ref_keys = translation_keys(langs[reference])
    problems = []
    for code in sorted(langs):
        keys = translation_keys(langs[code])
        missing = sorted(ref_keys - keys)
        extra = sorted(keys - ref_keys)
        if missing:
            problems.append(f"{code}: {len(missing)} key(s) missing vs {reference}: "
                            + ", ".join(missing[:5]) + ("…" if len(missing) > 5 else ""))
        if extra:
            problems.append(f"{code}: {len(extra)} key(s) not in {reference}: "
                            + ", ".join(extra[:5]) + ("…" if len(extra) > 5 else ""))
        if expected is not None and len(keys) != expected:
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
