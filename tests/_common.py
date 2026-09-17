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
EXPECTED_APP_VERSION = "1.3.1.1"  # the current release (a sentinel: it catches "a bump to the wrong version")
EXPECTED_I18N_KEYS = 453        # the en/ru/zh parity (v1.3.1: +7 sftp.viewer.* → 453; before, 446 since v1.3;
                                # v1.3.1.1 reuses those keys for the row tooltips — no new ones)
VERSION_FORMAT_RE = re.compile(r"^\d+(\.\d+){1,3}([Rr][Cc]\d+)?$")  # "1.1.3", "1.0RC4", "0.9.9.7", "1.2.10rc1" (v1.2.10: + lowercase rc)


def load_i18n_langs(root):
    """i18n/{en,ru,zh}.json → {code: dict} (the shared loading for the parity checks)."""
    langs = {}
    for code in ("en", "ru", "zh"):
        with open(os.path.join(root, "i18n", f"{code}.json"), encoding="utf-8") as f:
            langs[code] = json.load(f)
    return langs


def check_i18n_parity(langs):
    """The en/ru/zh parity: the sets of the keys are equal and the count == EXPECTED_I18N_KEYS."""
    check(
        f"i18n parity en/ru/zh ({EXPECTED_I18N_KEYS} keys each)",
        set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
        and all(len(d) == EXPECTED_I18N_KEYS for d in langs.values()),
        str({c: len(d) for c, d in langs.items()}))


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
