"""Общая обвязка тестов SSHMap (скрипты без pytest).

Паттерн для каждого файла tests/test_*.py:

    from _common import bootstrap, check, finish
    ROOT, WORK = bootstrap()   # ПЕРВЫМ делом — до импортов модулей приложения

...тело теста с check("имя", условие, detail) ...

    finish()   # сводка + exit code (0 = все проверки прошли)

Запуск всех тестов:  python tests/run_all.py
Карта файлов и конвенции:  tests/INDEX.md

Что делает bootstrap():
  * UTF-8 stdout/stderr — cp1251-консоль (типичная русская Windows) не роняет
    прогон UnicodeEncodeError'ом на «→» в отчёте;
  * изоляция HOME/USERPROFILE во временную директорию ДО импорта модулей
    приложения: тесты пишут ~/.sshmap/config.json, ~/.sshmap_settings.json и т.п. —
    весь ввод-вывод уходит в песочницу, реальный home не трогается (отключается
    SSHMAP_TEST_NO_HOME_ISOLATION=1);
  * QT_QPA_PLATFORM=offscreen по умолчанию (если пользователь не выставил свой);
  * sys.path: корень проекта; рабочая папка — свежая на каждый прогон
    (_tmp_testdata, либо $SSHMAP_TEST_WORKDIR при параллельном run_all.py);
  * faulthandler-таймаут 180 c: зависший offscreen (модалка) — дамп стеков и выход.
"""
import json
import os
import re
import shutil
import sys
import tempfile

PASS = []
FAIL = []


def bootstrap(faulthandler_timeout=180):
    """Инициализация окружения теста. Вызвать до импортов модулей приложения."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # старый Python без reconfigure — живём как раньше

    if os.environ.get("SSHMAP_TEST_NO_HOME_ISOLATION") != "1":
        _home = tempfile.mkdtemp(prefix="sshmap_test_home_")
        os.environ["HOME"] = _home
        os.environ["USERPROFILE"] = _home

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    # Параллельный run_all.py передаёт уникальный каталог на файл через
    # SSHMAP_TEST_WORKDIR (иначе bootstrap() соседнего процесса сотрёт scratch);
    # одиночный запуск — фиксированный _tmp_testdata (gitignored).
    work = os.environ.get("SSHMAP_TEST_WORKDIR") or os.path.join(root, "_tmp_testdata")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    if faulthandler_timeout:
        import faulthandler
        faulthandler.dump_traceback_later(faulthandler_timeout, exit=True)

    return root, work


def check(name, cond, detail=""):
    """Одна проверка: печатает ok/FAIL и копит в PASS/FAIL."""
    (PASS if cond else FAIL).append((name, detail))
    print(("  ok  " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


def finish():
    """Сводка и exit code: 0 = все проверки прошли."""
    total = len(PASS) + len(FAIL)
    print()
    if FAIL:
        print(f"FAILURES ({len(FAIL)}) из {total}:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    print(f"ALL PASS ({total})")


def wait_until(cond, timeout_ms=3000, tick_ms=50):
    """Настоящий Qt event loop до cond() или дедлайна (паттерн regression_v081)."""
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
    """Сцена → QPoint в координатах viewport (Qt 6.11: mapFromScene может дать QPoint или QPointF)."""
    from PySide6.QtCore import QPoint
    q = view.mapFromScene(scene_pos)
    return QPoint(int(q.x()), int(q.y()))


def snapshot_i18n_config():
    """Снимок ~/.sshmap/config.json (None, если файла нет).

    Тесты, переключающие язык (set_language), пишут в конфиг; под изолированным
    HOME это песочница и снимок не нужен, но при SSHMAP_TEST_NO_HOME_ISOLATION=1
    он сохраняет реальный конфиг пользователя.
    """
    p = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return (p, f.read())


def restore_i18n_config(snap):
    """Возврат конфига i18n по снимку из snapshot_i18n_config()."""
    if snap is None:
        return
    try:
        with open(snap[0], "w", encoding="utf-8") as f:
            f.write(snap[1])
    except OSError:
        pass  # sandbox may block writes to ~ — config untouched anyway


# ─────────────────────────────────────────────────────────────────────────────
# Пины релиза: при каждом релизе обновлять ТОЛЬКО ЗДЕСЬ (ранее: число «N ключей»
# в 12 i18n-файлах + APP_VERSION/requirements-пины в 7 release-state-секциях).
# Пропуски самих ключей против кода ловит check_i18n_keys.py.
# ─────────────────────────────────────────────────────────────────────────────
EXPECTED_APP_VERSION = "1.2"    # текущий релиз (sentinel: ловит «бамп не в ту версию»)
EXPECTED_I18N_KEYS = 398        # паритет en/ru/zh (v1.1.3: 377 + 21 sftp.*)
VERSION_FORMAT_RE = re.compile(r"^\d+(\.\d+){1,3}(RC\d+)?$")  # "1.1.3", "1.0RC4", "0.9.9.7"


def load_i18n_langs(root):
    """i18n/{en,ru,zh}.json → {code: dict} (общая загрузка для parity-проверок)."""
    langs = {}
    for code in ("en", "ru", "zh"):
        with open(os.path.join(root, "i18n", f"{code}.json"), encoding="utf-8") as f:
            langs[code] = json.load(f)
    return langs


def check_i18n_parity(langs):
    """Паритет en/ru/zh: наборы ключей равны и число == EXPECTED_I18N_KEYS."""
    check(
        f"i18n-паритет en/ru/zh ({EXPECTED_I18N_KEYS} keys each)",
        set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
        and all(len(d) == EXPECTED_I18N_KEYS for d in langs.values()),
        str({c: len(d) for c, d in langs.items()}))


def check_release_state(root):
    """Состояние релиза из version.py (единая точка истины): sentinel
    EXPECTED_APP_VERSION + формат + pyproject-сверка + заголовок requirements.txt.
    Вызывать ПОСЛЕ bootstrap() — version импортируется внутри функции."""
    try:
        from version import APP_VERSION
    except Exception as e:  # noqa: BLE001
        check("release: version.py читается", False, repr(e))
        return

    check(f"release: APP_VERSION == '{EXPECTED_APP_VERSION}'",
          APP_VERSION == EXPECTED_APP_VERSION, APP_VERSION)
    check("release: APP_VERSION формат (X.Y.Z[.W][RCn])",
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
