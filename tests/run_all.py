"""Единый запуск всех тестов SSHMap.

ROADMAP «Подготовка к 1.0»: задача «Единый раннер» (обязательна до v1.0) — выполнена
досрочно в v0.9.9.2: smoke_test.py + все regression_v*.py + check_i18n_keys.py заменены
единым прогоном по тематическим файлам tests/test_*.py.

Запуск из корня проекта:
    python tests/run_all.py              # все файлы test_*.py + check_i18n_keys.py
    python tests/run_all.py keyring      # только файлы, чьё имя содержит подстроку

Каждый файл — отдельный процесс (изоляция HOME/offscreen делает bootstrap() внутри).
exit code 0 = всё зелёное; в конце — таблица результатов.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def collect_files(filter_sub=None):
    """Сьют = все test_*.py + check_i18n_keys.py.

    Остальные .py в каталоге (сам run_all.py, будущие мета-скрипты) НЕ часть сьюта —
    иначе раннер рекурсивно запускал бы сам себя (каждый вложенный прогон
    собирает тот же список и спавнит следующий уровень).
    """
    files = []
    for name in sorted(os.listdir(TESTS)):
        if not name.endswith(".py"):
            continue
        if name.startswith("_"):
            continue  # _common.py — обвязка, не тест
        if not (name.startswith("test_") or name == "check_i18n_keys.py"):
            continue  # run_all.py и прочие нетестовые скрипты не входят в сьют
        if filter_sub and filter_sub not in name:
            continue
        files.append(name)
    return files


def main():
    filters = [a for a in sys.argv[1:] if not a.startswith("-")]
    sub = filters[0] if filters else None
    files = collect_files(sub)
    if not files:
        print(f"нет файлов тестов, совпадающих с {sub!r}")
        return 1

    try:
        # line_buffering: при перенаправлении в файл (CI/лог) заголовки секций
        # пишутся сразу, а не вместе со всей сводкой в конце (block-buffering).
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    print(f"SSHMap test suite: {len(files)} file(s)" + (f" (filter: {sub})" if sub else ""))
    results = []
    for name in files:
        path = os.path.join(TESTS, name)
        t0 = time.time()
        print(f"\n===== {name} =====")
        proc = subprocess.run([sys.executable, path], cwd=ROOT)
        dt = time.time() - t0
        results.append((name, proc.returncode, dt))

    print("\n" + "=" * 64)
    print(f"{'file':<42} {'result':<10} time")
    failed = 0
    for name, code, dt in results:
        status = "PASS" if code == 0 else f"FAIL({code})"
        if code != 0:
            failed += 1
        print(f"{name:<42} {status:<10} {dt:.1f}s")
    print("=" * 64)
    total = len(results)
    if failed:
        print(f"{total - failed}/{total} files green — ЕСТЬ ПРОВАЛЫ")
    else:
        print(f"{total}/{total} files green — ALL GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
