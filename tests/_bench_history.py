# -*- coding: utf-8 -*-
"""v1.2.12 замер D1 (PYTE82_AUDIT.md пачка D): overhead обёрток HistoryScreen
при глубокой истории — худший случай авто-возврата к live-строке.

НЕ часть сьюта (файлы с префиксом _ run_all.py пропускает). Протокол (D1):
  * TerminalScreen(120, 32, history_lines=1000); напечатать ~1050 строк истории;
  * scroll_up() до верхней границы — пользователь у верха истории (худший случай:
    before_event авто-возвратом крутит next_page() до ~250 раз в ОДНОМ feed);
  * замер подачи htop-подобного чанка (~19 КБ) → мс;
  * базовые линии: тот же чанк на live-строке (без истории для возврата) +
    чистый pyte.Screen без истории;
  * ожидаемое число next_page ≈ (size − position) / ceil(lines × ratio)
    (~250 при глубокой истории, ratio=0.1 → страница = 4 строки).

Числа — в CHANGELOG/ROADMAP («измерено на …, v1.2.12»); порог боли ~20–50 мс на
чанк при глубокой истории — триггер v1.2.14 (батчинг авто-возврата).

v1.2.14: батчинг выпущен (override before_event в SshmapHistoryScreen) — сценарий A
обязан быть ≈ B (измерено: A = 42,7 мс против B = 42,4 мс, overhead 0,25 мс). Скрипт
остался монитором регрессии: если A снова > 50 мс или A−B велик — проверить override.

htop-чанк: pyte/tests/captured/htop.input из master-checkout F:\\PythonAI\\pyte
(~19 КБ); нет файла — синтетический htop-подобный чанк того же размера.

Запуск: python tests/_bench_history.py   (из корня проекта)
"""
import math
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pyte  # noqa: E402
from modules.terminal_screen import TerminalScreen  # noqa: E402

COLUMNS, LINES = 120, 32
HISTORY_LINES = 1000
HISTORY_PRINTED = 1050        # ~1050 строк истории (заполняет deque на 1000)
CHUNK_TARGET = 19000          # htop.input — ~19 КБ
REPEATS = 5                   # лучший из N замеров

HTOP_INPUT_CANDIDATES = [
    os.path.join(os.path.dirname(ROOT), "pyte", "tests", "captured", "htop.input"),
]


def load_chunk():
    """htop-подобный чанк ~19 КБ: реальный захват pyte или синтетика."""
    for path in HTOP_INPUT_CANDIDATES:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            return data, path
    # Синтетика: повторяющиеся полноэкранные фреймы htop (ESC[2J + SGR-заголовки).
    header = (b"\x1b[7m\x1b[46m\x1b[30m PID USER PR NI VIRT RES SHR S %CPU %MEM "
              b"TIME+ COMMAND \x1b[0m\r\n")
    body = b""
    pid = 1
    while len(body) < LINES * 55:
        body += (b"%-7d %-8s %3d %3d %6d %6d %5d S %5.1f %5.1f %7s python\r\n"
                 % (pid, b"root", 20, 0, 1048576, 52428 + pid * 137, 26214,
                    float(pid % 9), float(1 + pid % 7), b"0:0%d.%d" % (pid % 10, pid % 9)))
        pid += 1
    frame = b"\x1b[2J\x1b[H" + header + body
    n = max(1, CHUNK_TARGET // len(frame))
    return frame * n, "<synthetic htop-like>"


def to_top(t):
    """scroll_up() до верхней границы истории (no-op на границе)."""
    while t.scroll_up():
        pass


def measure(t, chunk, repeats=REPEATS, at_top=True):
    """Лучшее время подачи чанка (мс); при at_top — перед каждым замером возврат
    к верхней границе истории (худший случай)."""
    best = None
    for _ in range(repeats):
        if at_top:
            to_top(t)
        t0 = time.perf_counter()
        t.feed(chunk)
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None else min(best, dt)
    return best


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    chunk, chunk_src = load_chunk()

    print("SSHMap bench D1 (v1.2.12): overhead HistoryScreen при глубокой истории")
    print(f"  machine : {platform.system()} {platform.release()}, "
          f"Python {sys.version.split()[0]}, pyte {getattr(pyte, '__version__', '0.8.2 (установленная)')}")
    # Размер страницы — та же арифметика, что в pyte HistoryScreen.next_page:
    # int(math.ceil(lines * ratio)) (ratio=SCROLL_RATIO=0.1).
    page = max(1, int(math.ceil(LINES * 0.1)))
    print(f"  screen  : {COLUMNS}x{LINES}, history_lines={HISTORY_LINES}, ratio=0.1 "
          f"(страница = {page} строк)")
    print(f"  chunk   : {len(chunk)} байт ({chunk_src})")

    # Сценарий A: глубокая история, пользователь у ВЕРХНЕЙ границы (худший случай).
    t_deep = TerminalScreen(COLUMNS, LINES, history_lines=HISTORY_LINES)
    for i in range(HISTORY_PRINTED):
        t_deep.feed(b"history line %d\r\n" % i)
    to_top(t_deep)
    pos, size = t_deep.scroll_info()
    expected_pages = (size - pos) / float(page)
    ms_deep = measure(t_deep, chunk)
    print(f"  A deep history (user at top): position={pos}/{size}, "
          f"ожидаемых next_page ≈ {expected_pages:.0f} → {ms_deep:.2f} мс/чанк")

    # Сценарий B: тот же чанк на live-строке (авто-возврат не нужен).
    t_live = TerminalScreen(COLUMNS, LINES, history_lines=HISTORY_LINES)
    for i in range(HISTORY_PRINTED):
        t_live.feed(b"history line %d\r\n" % i)
    ms_live = measure(t_live, chunk, at_top=False)   # на live-строке: авто-возврат не нужен
    print(f"  B live line (no auto-return) : {ms_live:.2f} мс/чанк")

    # Сценарий C: чистый pyte.Screen без истории (нижняя граница стоимости).
    plain = pyte.Screen(COLUMNS, LINES)
    plain_stream = pyte.ByteStream(plain)

    def measure_plain():
        best = None
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            plain_stream.feed(chunk)
            dt = (time.perf_counter() - t0) * 1000.0
            best = dt if best is None else min(best, dt)
        return best

    ms_plain = measure_plain()
    print(f"  C plain pyte.Screen (no history): {ms_plain:.2f} мс/чанк")

    overhead = ms_deep - ms_live
    # v1.2.14: батчинг авто-возврата выпущен — сценарий A обязан быть ≈ B (feed идёт
    # в GUI-потоке через queued signal; порог боли D2 был > ~20–50 мс на чанк).
    # Отклонение A от B или A > 50 мс — регрессия override before_event.
    verdict = ("РЕГРЕССИЯ БАТЧИНГА (A >> B или A > 50 мс) — проверить override "
               "before_event в SshmapHistoryScreen (v1.2.14)" if overhead > 5 or ms_deep > 50
               else "в норме: A ≈ B — батчинг авто-возврата работает (v1.2.14)")
    print(f"  overhead A−B (стоимость ~{expected_pages:.0f} next_page): {overhead:.2f} мс; "
          f"A = {ms_deep:.2f} мс/чанк при глубокой истории → {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
