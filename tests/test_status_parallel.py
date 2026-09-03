"""v1.1.2 final — Параллельные пробы статусов (тема релиза, ROADMAP v1.1.2 final).

Acceptance-тест серии: фейковые пробы (monkeypatch probe_ssh) без сети:
  * подсчёт параллельных вызовов (max_active ≤ max_parallel и > 1),
    раунд короче последовательного;
  * результаты прилетают ПО МЕРЕ ГОТОВНОСТИ (не в порядке списка целей);
  * семантика _busy не меняется: во время раунда True, повторный start_round()
    игнорируется, после round_finished False и новый раунд стартует;
  * отмена (stop()) на параллельном раунде: выход за один таймаут, а не
    ceil(N/mp) × timeout; отменённые до начала пробы результата не дают;
  * ключ status_max_parallel: дефолт 16, кламп 1..64, битые значения → дефолт,
    set_max_parallel на лету;
  * мягкий авто-интервал (задача 3): N > LARGE_MAP_THRESHOLD (50) → интервал
    удваивается (effective_interval_ms, таймер обновляется после раунда и в
    set_interval), E2E подсказка в статус-баре MainWindow;
  * диалог «Статусы»: спин max_parallel (1..64, prefill из конфига),
    collect() — 18 ключей (+status_max_parallel);
  * i18n: +2 ключа × en/ru/zh — паритет 375 → 377;
  * состояние релиза: APP_VERSION == "1.1.2", pyproject-сверка, заголовок requirements.

Запуск: python tests/test_status_parallel.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import re
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

# Сеть в тестах запрещена: пробы — фейк с управляемыми задержками и счётчиком
# параллельных вызовов (monkeypatch модульной глобальной — _probe_one читает её).
import services.status_checker as SC
from services.status_checker import (
    StatusChecker, get_status_settings,
    DEFAULT_MAX_PARALLEL, MAX_PARALLEL_LIMIT, LARGE_MAP_THRESHOLD)

_probe_lock = threading.Lock()
_active = {"n": 0}          # сейчас в пробах (воркеры пула)
_max_active = {"n": 0}      # пик параллельности за раунд
_calls = {"n": 0}           # всего вызовов фейковой пробы
_delays = {}                # host -> задержка, сек (управляемый порядок готовности)


def _fake_probe(host, port, timeout=3.0):
    with _probe_lock:
        _active["n"] += 1
        _max_active["n"] = max(_max_active["n"], _active["n"])
        _calls["n"] += 1
    time.sleep(_delays.get(host, 0.0))
    with _probe_lock:
        _active["n"] -= 1
    return "offline"


SC.probe_ssh = _fake_probe


def _reset_counters():
    with _probe_lock:
        _max_active["n"] = 0
        _calls["n"] = 0


def _run_round(chk, timeout_ms=8000):
    """Один раунд на настоящем event loop до round_finished (паттерн test_status_checker)."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    rounds = []
    chk.round_finished.connect(lambda r: (rounds.append(r), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)  # страховка от зависания теста
    t0 = time.time()
    chk.start_round()
    loop.exec()
    return rounds, time.time() - t0


def _targets(n, prefix="p", delay=0.0):
    """n целей с уникальными host'ами; задержка каждого — из _delays[host]."""
    out = []
    for i in range(n):
        h = f"h{prefix}{i}"
        _delays[h] = delay  # ключ — ТОЧНО host (фейк читает _delays.get(host))
        out.append((f"{prefix}{i}", h, 22))
    return out


# ══ 1. Подсчёт параллельных вызовов (задача 1: ThreadPoolExecutor) ══════════
print("== parallelism ==")
chk = StatusChecker(interval_ms=5000, probe_timeout=0.5, max_parallel=4, parent=None)
_reset_counters()
chk.set_servers(_targets(8, delay=0.25))
rounds, elapsed = _run_round(chk)
res_map = dict(rounds[0]) if rounds else {}
check("раунд завершён: все 8 целей в round_finished", len(res_map) == 8, str(res_map))
check("все результаты offline (фейк)", all(v == "offline" for v in res_map.values()), str(res_map))
with _probe_lock:
    peak = _max_active["n"]
    total_calls = _calls["n"]
check("параллельность реально была (пик > 1 одновременной пробы)", peak >= 2, f"peak={peak}")
check("потолок max_parallel=4 не превышен (пик ≤ 4)", peak <= 4, f"peak={peak}")
check("ровно 8 вызовов фейковой пробы (без дублей)", total_calls == 8, str(total_calls))
# Последовательный цикл: 8 × 0.25 = 2.0 c; параллельный (4 воркера): ~0.5–0.7 c
check("раунд короче последовательного (elapsed < 1.6 c при baseline 2.0 c)",
      elapsed < 1.6, f"elapsed={elapsed:.2f}s")
chk.stop()

# ══ 2. Результаты по мере готовности (as_completed, не порядок списка) ══════
print("== results as they complete ==")
chk2 = StatusChecker(interval_ms=5000, probe_timeout=0.6, max_parallel=4, parent=None)
_reset_counters()
# Порядок СЛЕДОВАНИЯ целей: от медленной к быстрой (t0 — самая долгая).
for i, d in enumerate((0.5, 0.3, 0.15, 0.05)):
    _delays[f"hq{i}"] = d
chk2.set_servers([(f"q{i}", f"hq{i}", 22) for i in range(4)])
order = []
times = []
chk2.status_changed.connect(lambda sid, st: (order.append(sid), times.append(time.time())))
rounds, elapsed = _run_round(chk2)
check("все 4 результата доставлены", len(order) == 4, str(order))
check("быстрая проба прилетела ПЕРВОЙ (не первая в списке целей)", order[:1] == ["q3"], str(order))
check("медленная проба прилетела ПОСЛЕДНЕЙ (первая в списке целей)", order[-1:] == ["q0"], str(order))
if len(times) >= 2:
    check("результаты разнесены во времени по мере готовности (разбег ≥ 0.15 c)",
          times[-1] - times[0] >= 0.15, f"spread={times[-1] - times[0]:.2f}s")
else:
    check("результаты разнесены во времени по мере готовности (разбег ≥ 0.15 c)", False, str(times))
chk2.stop()

# ══ 3. Семантика _busy не меняется (задача 1: повторный старт игнорируется) ══
print("== _busy semantics ==")
chk3 = StatusChecker(interval_ms=5000, probe_timeout=0.6, max_parallel=2, parent=None)
_reset_counters()
chk3.set_servers(_targets(2, prefix="b", delay=0.5))
chk3.start_round()
check("во время раунда is_busy == True (синхронно, до потока)", chk3.is_busy is True)
thread_before = chk3._thread
chk3.start_round()  # повторный запуск во время активного раунда — должен игнорироваться
check("повторный start_round() не создал второй поток", chk3._thread is thread_before,
      f"{chk3._thread} vs {thread_before}")
rounds, elapsed = _run_round(chk3)  # дожидаемся round_finished первого раунда
with _probe_lock:
    calls_after_r1 = _calls["n"]
check("раунд отработал ровно 2 пробы (игнор не добавил вызовов)", calls_after_r1 == 2, str(calls_after_r1))
check("после round_finished is_busy == False", chk3.is_busy is False)
rounds2, _ = _run_round(chk3)  # новый раунд после освобождения — стартует
with _probe_lock:
    calls_after_r2 = _calls["n"]
check("следующий раунд отработал (ещё 2 пробы)", calls_after_r2 == 4, str(calls_after_r2))
chk3.stop()

# ══ 4. Отмена на параллельном раунде (stop()) ═══════════════════════════════
print("== cancel ==")
chk4 = StatusChecker(interval_ms=5000, probe_timeout=0.5, max_parallel=2, parent=None)
_reset_counters()
# 6 целей × 0.5 c при mp=2: без отмены раунд ≥ 1.5 c (3 батча); с отменой — ~0.5 c.
chk4.set_servers(_targets(6, prefix="c", delay=0.5))
emitted = []
chk4.status_changed.connect(lambda sid, st: emitted.append(sid))
t0 = time.time()
chk4.start_round()
time.sleep(0.1)          # даём раунду стартовать (все 6 задач уже в пуле)
chk4.stop()              # отмена + ожидание потока (блокирует до finish'а потока)
elapsed_cancel = time.time() - t0
check("stop() вывел раунд быстрее полного параллельного цикла (< 1.3 c при baseline ≥ 1.5 c)",
      elapsed_cancel < 1.3, f"elapsed={elapsed_cancel:.2f}s")
wait_until(lambda: not chk4.is_busy, timeout_ms=3000)
check("после stop() is_busy == False (finished-сигнал доставлен)", chk4.is_busy is False)
# В полёте при отмене был один батч (mp=2): ≤ 2 результата; остальные пробы
# отменены до начала — результатов им нет (семантика «не проверяли» сохранена).
check("отменённые до начала пробы результата не дали (доставлено < 6, ≤ 2)",
      len(emitted) < 6 and len(emitted) <= 2, str(emitted))

# ══ 5. Ключ status_max_parallel: конфиг + сеттеры (задача 2) ════════════════
print("== status_max_parallel config ==")
from i18n import save_config as _save_cfg, load_config as _load_cfg


def _clear_cfg():
    for p in (os.path.join(os.path.expanduser("~"), ".sshmap", "config.json"),):
        try:
            os.remove(p)
        except OSError:
            pass


_clear_cfg()
st = get_status_settings()
check("нет конфига → max_parallel дефолт 16 (ROADMAP «дефолт 16»)",
      st["max_parallel"] == DEFAULT_MAX_PARALLEL == 16, str(st))
_save_cfg({"status_max_parallel": 32})
st = get_status_settings()
check("валидное значение читается (32)", st["max_parallel"] == 32, str(st))
_save_cfg({"status_max_parallel": 0})
st = get_status_settings()
check("кламп снизу: 0 → 1", st["max_parallel"] == 1, str(st))
_save_cfg({"status_max_parallel": 9999})
st = get_status_settings()
check(f"кламп сверху: 9999 → {MAX_PARALLEL_LIMIT}", st["max_parallel"] == MAX_PARALLEL_LIMIT, str(st))
_save_cfg({"status_max_parallel": "abc"})
st = get_status_settings()
check("битое значение (str) → дефолт 16", st["max_parallel"] == 16, str(st))
_save_cfg({"status_max_parallel": True})
st = get_status_settings()
check("bool → дефолт 16 (паттерн _num)", st["max_parallel"] == 16, str(st))

chk5 = StatusChecker(interval_ms=5000, probe_timeout=0.3, max_parallel=8, parent=None)
check("конструктор: max_parallel=8 читается", chk5.max_parallel == 8, str(chk5.max_parallel))
chk5.set_max_parallel(3)
check("set_max_parallel(3) на лету", chk5.max_parallel == 3, str(chk5.max_parallel))
chk5.set_max_parallel(10**6)
check(f"set_max_parallel: кламп сверху → {MAX_PARALLEL_LIMIT}", chk5.max_parallel == MAX_PARALLEL_LIMIT)
chk5.set_max_parallel("junk")
check("set_max_parallel: битое значение → дефолт 16", chk5.max_parallel == 16)
chk5.stop()

# ══ 6. Мягкий авто-интервал для больших карт (задача 3) ═════════════════════
print("== auto interval for large maps ==")
chk6 = StatusChecker(interval_ms=30_000, probe_timeout=0.2, max_parallel=16, parent=None)
check("N=50 — НЕ большая карта (порог: N > 50)", not chk6.is_large_map()
      and chk6.target_count == 0)
chk6.set_servers(_targets(50, prefix="m"))
check("N=50: эффективный интервал = базовый (30 c)",
      not chk6.is_large_map() and chk6.effective_interval_ms() == 30_000,
      f"eff={chk6.effective_interval_ms()}")
chk6.set_servers(_targets(51, prefix="m"))
check("N=51: большая карта → интервал удвоен (60 c)",
      chk6.is_large_map() and chk6.effective_interval_ms() == 60_000,
      f"eff={chk6.effective_interval_ms()}")
_reset_counters()
_run_round(chk6)  # раунд на 51 цели (фейк мгновенный)
check("после раунда таймер реально переключён на удвоенный интервал",
      chk6._timer.interval() == 60_000, str(chk6._timer.interval()))
chk6.set_interval(20_000)
check("set_interval при большой карте: в таймер сразу ЭФФЕКТИВНЫЙ (40 c)",
      chk6.interval_ms == 20_000 and chk6._timer.interval() == 40_000,
      f"base={chk6.interval_ms} timer={chk6._timer.interval()}")
chk6.set_servers(_targets(10, prefix="m"))
check("N=10: обратно к базовому интервалу (20 c)",
      not chk6.is_large_map() and chk6.effective_interval_ms() == 20_000)
_run_round(chk6)
check("после раунда на маленькой карте таймер возвращён к базовому",
      chk6._timer.interval() == 20_000, str(chk6._timer.interval()))
chk6.stop()

# ══ 7. E2E: подсказка в статус-баре MainWindow при N > 50 (задача 3) ════════
print("== main window hint ==")
import ui.main_window as MW
from models.server import ServerData

win = MW.MainWindow()
for i in range(51):
    win.scene.add_server(ServerData(id=f"big{i:02d}", alias=f"n{i}", host="10.9.9.9", user="u"))
win._sync_status_targets()
check("MainWindow: 51 цель в план, is_large_map True",
      win._status_checker.target_count == 51 and win._status_checker.is_large_map(),
      str(win._status_checker.target_count))
check("подсказка показана один раз (_auto_interval_hinted)", getattr(win, "_auto_interval_hinted", None) is True)
msg = win.statusBar().currentMessage()
check("статус-бар: подсказка с числом узлов (51)", "51" in msg and msg != "", msg)
win._sync_status_targets()  # повторный sync при том же N — подсказка не дублируется
check("повторный sync не сбрасывает флаг (подсказка одноразовая)", win._auto_interval_hinted is True)
# Снова ниже порога → флаг сброшен, можно подсказать заново
for n in list(win.scene.nodes()):
    win.scene.remove_server(n.data.id)
win._sync_status_targets()
check("после очистки сцены флаг сброшен (порог снова пересечём — подсказка возможна)",
      win._auto_interval_hinted is False and win._status_checker.target_count == 0)
win._dirty = False
win.close(); win.destroy()

# ══ 8. Диалог «Статусы»: спин + collect() (задача 2) ════════════════════════
print("== settings dialog ==")
import i18n as _i18n_mod
from ui.settings_dialog import SettingsDialog

_clear_cfg()
dlg = SettingsDialog(None)
check("спин max_parallel существует, диапазон 1..64",
      hasattr(dlg, "max_parallel_spin") and dlg.max_parallel_spin.minimum() == 1
      and dlg.max_parallel_spin.maximum() == MAX_PARALLEL_LIMIT,
      f"min={getattr(dlg, 'max_parallel_spin', None) and dlg.max_parallel_spin.minimum()}")
check("prefill без конфига: дефолт 16", dlg.max_parallel_spin.value() == 16,
      str(dlg.max_parallel_spin.value()))
_save_cfg({"status_max_parallel": 32})
dlg2 = SettingsDialog(None)
check("prefill из конфига: 32", dlg2.max_parallel_spin.value() == 32, str(dlg2.max_parallel_spin.value()))
dlg2.retranslate()  # смена языка в открытом диалоге — новый лейбл не падает
check("retranslate: лейбл переведён (не сырой ключ)",
      dlg2._lbl_max_parallel.text() == _i18n_mod.t("settings.statuses.max_parallel")
      and dlg2._lbl_max_parallel.text() != "settings.statuses.max_parallel",
      dlg2._lbl_max_parallel.text())
c = dlg2.collect()
check("collect(): ровно 18 ключей (17 + status_max_parallel, v1.1.2 final)",
      len(c) == 18 and "status_max_parallel" in c, str(sorted(c)))
check("collect(): status_max_parallel = int из спинбокса",
      isinstance(c["status_max_parallel"], int) and c["status_max_parallel"] == 32, str(c.get("status_max_parallel")))
_clear_cfg()

# ══ 9. i18n: +2 ключа × en/ru/zh — паритет 375 → 377 ════════════════════════
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = ["settings.statuses.max_parallel", "status.auto_interval_hint"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("2 новых ключа v1.1.2 final есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (377 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 377 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# ══ 10. Состояние релиза v1.1.2 final ═══════════════════════════════════════
print("== release state ==")
from version import APP_VERSION
check("release: APP_VERSION == '1.1.2'", APP_VERSION == "1.1.2", APP_VERSION)
try:
    try:
        import tomllib as _toml
    except ModuleNotFoundError:
        import tomli as _toml
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        _pp = _toml.load(f)
    check("release: pyproject version == APP_VERSION",
          _pp["project"]["version"] == APP_VERSION, str(_pp["project"].get("version")))
except Exception as e:  # noqa: BLE001
    check("release: pyproject version == APP_VERSION", False, repr(e))
try:
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
        _req_head = f.readline()
    check("release: requirements.txt header carries v1.1.2 (не RC)",
          re.search(r"v1\.1\.2(?![A-Za-z0-9])", _req_head) is not None, _req_head.strip())
except Exception as e:  # noqa: BLE001
    check("release: requirements.txt header carries v1.1.2 (не RC)", False, repr(e))

finish()
