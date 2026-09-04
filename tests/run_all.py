"""Единый запуск всех тестов SSHMap (параллельный).

ROADMAP «Подготовка к 1.0»: задача «Единый раннер» (обязательна до v1.0) — выполнена
досрочно в v0.9.9.2: smoke_test.py + все regression_v*.py + check_i18n_keys.py заменены
единым прогоном по тематическим файлам tests/test_*.py.

Запуск из корня проекта:
    python tests/run_all.py              # все test_*.py + check_i18n_keys.py, 4 воркера
    python tests/run_all.py --workers 8  # число воркеров (1 = последовательно, как раньше)
    python tests/run_all.py keyring      # только файлы, чьё имя содержит подстроку

Каждый файл — отдельный процесс (изоляция HOME/offscreen делает bootstrap() внутри).
Файлы независимы: рабочая папка на файл передаётся через SSHMAP_TEST_WORKDIR
(иначе параллельные bootstrap() сносили бы общий _tmp_testdata), каталог прогона
создаётся в %TEMP% и удаляется по завершении.
exit code 0 = всё зелёное; в конце — таблица результатов (отсортирована по имени).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
DEFAULT_WORKERS = 4


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


def run_one(name, workdir_root):
    """Один тестовый файл — отдельный процесс; вывод захватывается (параллельность)."""
    env = dict(os.environ)
    env["SSHMAP_TEST_WORKDIR"] = os.path.join(workdir_root, name[:-3])
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, os.path.join(TESTS, name)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    return name, proc.returncode, time.time() - t0, proc.stdout or "", proc.stderr or ""


def main():
    args = list(sys.argv[1:])
    workers = DEFAULT_WORKERS
    if "--workers" in args:
        i = args.index("--workers")
        try:
            workers = max(1, int(args[i + 1]))
        except (IndexError, ValueError):
            print("--workers ожидает число >= 1")
            return 1
        del args[i:i + 2]
    filters = [a for a in args if not a.startswith("-")]
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

    t_start = time.time()
    print(f"SSHMap test suite: {len(files)} file(s), workers={workers}"
          + (f" (filter: {sub})" if sub else ""))

    results = []
    run_root = tempfile.mkdtemp(prefix="sshmap_test_run_")
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(run_one, name, run_root) for name in files]
            for fut in as_completed(futures):
                name, code, dt, out, err = fut.result()
                results.append((name, code, dt))
                print(f"\n===== {name} =====")  # секции — в порядке завершения
                if out:
                    sys.stdout.write(out)
                if err:
                    sys.stdout.write("\n[stderr]\n" + err)
    finally:
        shutil.rmtree(run_root, ignore_errors=True)  # не оставлять рабочие каталоги

    print("\n" + "=" * 64)
    print(f"{'file':<42} {'result':<10} time")
    failed = 0
    for name, code, dt in sorted(results):
        status = "PASS" if code == 0 else f"FAIL({code})"
        if code != 0:
            failed += 1
        print(f"{name:<42} {status:<10} {dt:.1f}s")
    print("=" * 64)
    total = len(results)
    wall = time.time() - t_start
    if failed:
        print(f"{total - failed}/{total} files green — ЕСТЬ ПРОВАЛЫ (wall {wall:.1f}s)")
    else:
        print(f"{total}/{total} files green — ALL GREEN (wall {wall:.1f}s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
