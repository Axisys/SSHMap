# -*- coding: utf-8 -*-
"""v1.1.3 — SFTP-вкладка в окне терминала (ROADMAP v1.1.3, задачи 1–5).

Тема релиза: новый worker-поток с очередью задач (list/upload/download)
поверх живого transport'а + UI-вкладка [Терминал | Файлы]. ВСЕ проверки —
без сети: фейковый SFTPClient с in-memory ФС (та же поверхность API, что у
paramiko: listdir_attr/open/close/get_channel; ошибки — IOError "No such
file", как SSH_FX_NO_SUCH_FILE).

Секции:
  1. Фейковая ФС + worker: два upload'а СТРОГО последовательно,
     прогресс-сигналы по порядку (монотонность, финал == total, контент).
  2. Ошибка пути → error-сигнал БЕЗ падения очереди (list несуществующего
     каталога, upload в несуществующий каталог; следующие задачи работают).
  3. Отмена: флаг между операциями — текущая передача прерывается на чанке,
     очередь пропускается с task_cancelled, worker живёт, флаг автосбрасывается.
  4. Shutdown: idle (быстро) и во время передачи (в пределах wait-бюджета),
     SFTPClient закрыт, queue_* после стопа — None.
  5. SftpTab offscreen: листинг/переходы без сети («..», вход в каталог,
     Refresh, сталинг-фильтр устаревших ответов), upload/download выбранных
     (QFileDialog подменён), кнопка «Отменить» по передачам.
  6. SSHTerminalWindow offscreen: QTabWidget [Терминал | Файлы], ленивый
     open_sftp() на том же transport, connected_signal-подхват, ошибка
     open_sftp → статус-бар, прогресс в статус-баре, closeEvent-teardown.
  7. i18n: 21 ключ sftp.* × en/ru/zh, паритет 377 → 398.
  8. Состояние релиза: APP_VERSION == "1.1.3", pyproject-сверка, заголовок
     requirements.

Запуск:  python tests/test_sftp_tab.py   (из корня проекта) или python tests/run_all.py
"""
import os
import posixpath
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import QThread, Signal as QtSignal
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.sftp_worker as SW
import modules.sftp_tab as STAB
from modules.sftp_worker import SftpWorker
from modules.sftp_tab import SftpTab, format_size, format_mtime


# ════════════════════════════════════════════════════════════
# Фейковая in-memory ФС + фейковый SFTPClient (без сети)
# ════════════════════════════════════════════════════════════

def _norm(path):
    p = path or "/"
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p or "/"


class FakeSftpAttr:
    """Та же поверхность, что у paramiko SFTPAttributes (filename/st_mode/size/mtime)."""

    def __init__(self, filename, is_dir, size, mtime):
        self.filename = filename
        self.st_mode = 0o40755 if is_dir else 0o100644
        self.st_size = size
        self.st_mtime = mtime


class FakeSftpFS:
    """In-memory удалённая ФС: dirs (set путей) + files (dict путь→bytes)."""

    def __init__(self):
        self.dirs = {"/"}
        self.files = {}
        self.mtimes = {}

    def add_dir(self, path):
        self.dirs.add(_norm(path))

    def add_file(self, path, data, mtime=1700000000):
        path = _norm(path)
        parent = posixpath.dirname(path)
        if parent not in self.dirs:
            raise ValueError(f"нет родительского каталога {parent}")
        self.files[path] = bytes(data)
        self.mtimes[path] = mtime


class FakeSftpFile:
    """Файл фейковой ФС; chunk_delay имитирует сетевую задержку на чанк."""

    def __init__(self, fs, path, mode, chunk_delay=0.0):
        self._fs = fs
        self._path = _norm(path)
        self._pos = 0
        self._delay = chunk_delay
        if "w" in mode or "a" in mode:
            # Семантика paramiko: open("wb") НЕ создаёт родительские каталоги.
            if posixpath.dirname(self._path) not in fs.dirs:
                raise IOError("No such file")
            if self._path not in fs.files:
                fs.files[self._path] = bytearray()
        else:
            if self._path not in fs.files:
                raise IOError("No such file")

    def read(self, n=-1):
        if self._delay:
            time.sleep(self._delay)
        buf = self._fs.files[self._path]
        end = len(buf) if n < 0 else min(len(buf), self._pos + n)
        data = bytes(buf[self._pos:end])
        self._pos = end
        return data

    def write(self, data):
        if self._delay:
            time.sleep(self._delay)
        buf = self._fs.files.setdefault(self._path, bytearray())
        buf.extend(data)

    def close(self):
        pass


class FakeSftpClient:
    """Фейковый paramiko SFTPClient (listdir_attr/open/close/get_channel)."""

    def __init__(self, fs, chunk_delay=0.0):
        self._fs = fs
        self._chunk_delay = chunk_delay
        self._closed = False

    def listdir_attr(self, path):
        if self._chunk_delay:
            time.sleep(self._chunk_delay)
        path = _norm(path)
        if path not in self._fs.dirs:
            raise IOError("No such file")
        out = []
        for d in sorted(self._fs.dirs):
            if d != "/" and posixpath.dirname(d) == path:
                out.append(FakeSftpAttr(posixpath.basename(d), True, 0,
                                        self._fs.mtimes.get(d, 0)))
        for f in sorted(self._fs.files):
            if posixpath.dirname(f) == path:
                out.append(FakeSftpAttr(posixpath.basename(f), False,
                                        len(self._fs.files[f]),
                                        self._fs.mtimes.get(f, 0)))
        return out

    def open(self, path, mode="r"):
        if self._chunk_delay:
            time.sleep(self._chunk_delay)
        return FakeSftpFile(self._fs, path, mode, self._chunk_delay)

    def get_channel(self):
        return self  # «канал» = сам клиент (атрибут closed для worker-проверки)

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


class EventLog:
    """Журнал сигналов worker'а (queued-доставка в GUI-потоке через wait_until)."""

    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def add(self, *ev):
        with self.lock:
            self.events.append(ev)

    def of_kind(self, kind, task_id=None):
        with self.lock:
            return [e for e in self.events if e[0] == kind
                    and (task_id is None or len(e) > 1 and e[1] == task_id)]


def wire_worker(worker, log):
    worker.list_ready.connect(lambda tid, d, e: log.add("list", tid, d, e))
    worker.task_started.connect(lambda tid, k, l: log.add("started", tid, k, l))
    worker.progress.connect(lambda tid, dn, tot: log.add("progress", tid, dn, tot))
    worker.task_done.connect(lambda tid, det: log.add("done", tid, det))
    worker.task_error.connect(lambda tid, k, m: log.add("error", tid, k, m))
    worker.task_cancelled.connect(lambda tid, k: log.add("cancelled", tid, k))


def make_local_file(name, size, pattern=b"0"):
    p = os.path.join(WORK, name)
    with open(p, "wb") as f:
        f.write(pattern * size)
    return p


# ════════════════════════════════════════════════════════════
# 1. Worker: два upload'а строго последовательно + прогресс по порядку
# ════════════════════════════════════════════════════════════
print("== 1. worker: two uploads strictly sequential ==")

fs1 = FakeSftpFS()
client1 = FakeSftpClient(fs1, chunk_delay=0.005)  # задержка на чанк — порядок наблюдаем
worker1 = SftpWorker(client1)
log1 = EventLog()
wire_worker(worker1, log1)
worker1.start()

SIZE_A, SIZE_B = 4 * 32768, 3 * 32768  # 4 и 3 чанка по 32 КБ
local_a = make_local_file("a.bin", SIZE_A, b"a")
local_b = make_local_file("b.bin", SIZE_B, b"b")

tid_a = worker1.queue_upload(local_a, "/")
tid_b = worker1.queue_upload(local_b, "/")
check("queue_upload вернул task id (1, 2)", (tid_a, tid_b) == (1, 2),
      f"got={tid_a},{tid_b}")

wait_until(lambda: log1.of_kind("done", tid_b), timeout_ms=8000)
app.processEvents()

idx = {}
with log1.lock:
    for i, e in enumerate(log1.events):
        if len(e) > 1 and e[1] in (tid_a, tid_b):
            idx.setdefault(e[1], []).append(i)
last_a = max(idx.get(tid_a, [0]))
first_b = min(idx.get(tid_b, [len(log1.events)]))
check("строго последовательно: ВСЕ события A раньше ЛЮБЫХ B", last_a < first_b,
      f"last_a={last_a} first_b={first_b}")

kinds_a = [log1.events[i][0] for i in idx.get(tid_a, [])]
check("A: started → progress* → done", kinds_a[:1] == ["started"]
      and kinds_a[-1] == "done" and all(k == "progress" for k in kinds_a[1:-1]),
      f"kinds={kinds_a}")

prog_a = [e[2] for e in log1.of_kind("progress", tid_a)]
check("A: прогресс монотонно растёт",
      prog_a and all(x <= y for x, y in zip(prog_a, prog_a[1:])), f"prog={prog_a}")
check("A: финальный прогресс == total (4 чанка)", prog_a[-1] == SIZE_A,
      f"last={prog_a[-1]} total={SIZE_A}")
prog_b = [e[2] for e in log1.of_kind("progress", tid_b)]
check("B: финальный прогресс == total (3 чанка)", prog_b and prog_b[-1] == SIZE_B,
      f"last={prog_b[-1] if prog_b else None} total={SIZE_B}")

check("контент A на «сервере»", fs1.files.get("/a.bin") == b"a" * SIZE_A)
check("контент B на «сервере»", fs1.files.get("/b.bin") == b"b" * SIZE_B)
done_a = log1.of_kind("done", tid_a)
check("task_done A: detail = удалённый путь", done_a and done_a[0][2] == "/a.bin",
      f"got={done_a}")

# download в обратную сторону (прогресс с total из листинга)
local_dl = os.path.join(WORK, "dl")
os.makedirs(local_dl, exist_ok=True)
tid_dl = worker1.queue_download("/b.bin", local_dl, SIZE_B)
wait_until(lambda: log1.of_kind("done", tid_dl), timeout_ms=8000)
check("download: файл на диске с тем же контентом",
      open(os.path.join(local_dl, "b.bin"), "rb").read() == b"b" * SIZE_B)

worker1.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 2. Ошибка пути → error-сигнал без падения очереди
# ════════════════════════════════════════════════════════════
print("== 2. worker: path error → error signal, queue survives ==")

fs2 = FakeSftpFS()
worker2 = SftpWorker(FakeSftpClient(fs2))
log2 = EventLog()
wire_worker(worker2, log2)
worker2.start()

tid_err1 = worker2.queue_list("/nope")
wait_until(lambda: log2.of_kind("error", tid_err1), timeout_ms=5000)
err1 = log2.of_kind("error", tid_err1)[0]
check("list несуществующего каталога → task_error", "No such file" in err1[3],
      f"msg={err1[3]!r}")

tid_ok1 = worker2.queue_list("/")
wait_until(lambda: log2.of_kind("list", tid_ok1), timeout_ms=5000)
check("очередь жива: следующий list завершился (list_ready)",
      bool(log2.of_kind("list", tid_ok1)))

tid_err2 = worker2.queue_upload(make_local_file("c.bin", 100, b"c"), "/nope")
wait_until(lambda: log2.of_kind("error", tid_err2), timeout_ms=5000)
check("upload в несуществующий каталог → task_error",
      bool(log2.of_kind("error", tid_err2)))

tid_ok2 = worker2.queue_upload(make_local_file("d.bin", 100, b"d"), "/")
wait_until(lambda: log2.of_kind("done", tid_ok2), timeout_ms=5000)
check("очередь жива после ошибок: валидный upload завершился",
      fs2.files.get("/d.bin") == b"d" * 100)

tid_err3 = worker2.queue_download("/nope/file.bin", WORK, 0)
wait_until(lambda: log2.of_kind("error", tid_err3), timeout_ms=5000)
check("download несуществующего файла → task_error",
      bool(log2.of_kind("error", tid_err3)))

worker2.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 3. Отмена: флаг между операциями, очередь пропускается, автосброс флага
# ════════════════════════════════════════════════════════════
print("== 3. worker: cancellation ==")

fs3 = FakeSftpFS()
client3 = FakeSftpClient(fs3, chunk_delay=0.02)  # ~10 чанков × 20 мс = 200 мс
worker3 = SftpWorker(client3)
log3 = EventLog()
wire_worker(worker3, log3)
worker3.start()

SLOW_SIZE = 10 * 32768
local_slow = make_local_file("slow.bin", SLOW_SIZE, b"s")
tid_slow = worker3.queue_upload(local_slow, "/")
tid_next = worker3.queue_upload(make_local_file("next.bin", 100, b"n"), "/")

wait_until(lambda: log3.of_kind("progress", tid_slow), timeout_ms=5000)
worker3.cancel()
wait_until(lambda: len(log3.of_kind("cancelled")) >= 2, timeout_ms=8000)

check("отменена текущая передача (task_cancelled)",
      bool(log3.of_kind("cancelled", tid_slow)))
check("пропущена следующая из очереди (task_cancelled)",
      bool(log3.of_kind("cancelled", tid_next)))
check("ни одна из отменённых не завершилась (нет task_done)",
      not log3.of_kind("done", tid_slow) and not log3.of_kind("done", tid_next))
prog_slow = [e[2] for e in log3.of_kind("progress", tid_slow)]
check("передача прервана ДО конца (прогресс < total)",
      prog_slow and prog_slow[-1] < SLOW_SIZE,
      f"last={prog_slow[-1] if prog_slow else None} total={SLOW_SIZE}")
partial = fs3.files.get("/slow.bin", b"")
check("частичный файл на «сервере» (короче исходного)", len(partial) < SLOW_SIZE,
      f"len={len(partial)}")
check("worker жив после отмены", worker3.isRunning())

tid_after = worker3.queue_upload(make_local_file("after.bin", 100, b"f"), "/")
wait_until(lambda: log3.of_kind("done", tid_after), timeout_ms=5000)
check("флаг автосбросился: новый upload после отмены завершился",
      fs3.files.get("/after.bin") == b"f" * 100)

worker3.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 4. Shutdown: idle и во время передачи; SFTPClient закрыт
# ════════════════════════════════════════════════════════════
print("== 4. worker: shutdown ==")

client4 = FakeSftpClient(FakeSftpFS())
worker4 = SftpWorker(client4)
worker4.start()
wait_until(lambda: worker4.isRunning(), timeout_ms=2000)
t0 = time.time()
worker4.shutdown(wait_ms=2000)
elapsed = time.time() - t0
check("idle shutdown: поток завершился", not worker4.isRunning())
check("idle shutdown: быстро (< 1 c, не весь wait-бюджет)", elapsed < 1.0,
      f"elapsed={elapsed:.3f}")
check("SFTPClient закрыт в finally run()", client4.closed)
check("queue_* после стопа → None", worker4.queue_list("/") is None)

fs5 = FakeSftpFS()
client5 = FakeSftpClient(fs5, chunk_delay=0.05)  # ~7 чанков × 50 мс = 350 мс
worker5 = SftpWorker(client5)
log5 = EventLog()
wire_worker(worker5, log5)
worker5.start()
tid_mid = worker5.queue_upload(make_local_file("mid.bin", 7 * 32768, b"m"), "/")
wait_until(lambda: log5.of_kind("progress", tid_mid), timeout_ms=5000)
t0 = time.time()
worker5.shutdown(wait_ms=2000)
elapsed = time.time() - t0
check("shutdown во время передачи: поток завершился", not worker5.isRunning())
check("shutdown уложился в wait-бюджет (+запас)", elapsed < 2.3,
      f"elapsed={elapsed:.3f}")
# queued-сигналы доставляются через event loop — дожидаемся перед проверкой
wait_until(lambda: log5.of_kind("cancelled", tid_mid), timeout_ms=3000)
check("передача при остановке отчиталась task_cancelled",
      bool(log5.of_kind("cancelled", tid_mid)))
check("SFTPClient закрыт (во время передачи)", client5.closed)


# ════════════════════════════════════════════════════════════
# 5. SftpTab: листинг/переходы без сети + upload/download выбранных
# ════════════════════════════════════════════════════════════
print("== 5. sftp tab: listing/navigation (offscreen, no network) ==")

fs6 = FakeSftpFS()
fs6.add_dir("/var")
fs6.add_dir("/home")
fs6.add_file("/home/a.txt", b"x" * 100)
fs6.add_file("/home/b.log", b"y" * 2048)
fs6.add_dir("/home/sub")
client6 = FakeSftpClient(fs6, chunk_delay=0.01)  # сталинг-сценарий наблюдаем
worker6 = SftpWorker(client6)
log6 = EventLog()
wire_worker(worker6, log6)
worker6.start()

tab = SftpTab()
msgs = []
tab.message.connect(msgs.append)
tab.set_worker(worker6)  # → _relist("/")

wait_until(lambda: tab.tree.topLevelItemCount() >= 2, timeout_ms=5000)
names = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
check("листинг корня: каталоги home/var (без «..» на /)", names == ["home", "var"],
      f"names={names}")
check("path_label = текущий каталог", tab.path_label.text() == "/",
      f"got={tab.path_label.text()!r}")
check("btn_up отключена на /", not tab.btn_up.isEnabled())

# Вход в /home (двойной клик по строке каталога — прямой вызов слота)
item_home = tab.tree.topLevelItem(0)
tab._on_item_double_clicked(item_home, 0)
wait_until(lambda: tab.tree.topLevelItemCount() >= 4, timeout_ms=5000)
names = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
check("переход в /home: «..» первым", names[0] == "..", f"names={names}")
check("состав /home: .., каталог sub первыми, затем файлы по имени",
      names == ["..", "sub", "a.txt", "b.log"], f"names={names}")
check("path_label = /home", tab.path_label.text() == "/home")
check("btn_up включена вне /", tab.btn_up.isEnabled())

item_sub = tab.tree.topLevelItem(1)
item_a = tab.tree.topLevelItem(2)
item_b = tab.tree.topLevelItem(3)
check("размер файла в колонке (100 B)", item_a.text(1) == "100 B",
      f"got={item_a.text(1)!r}")
check("размер файла 2048 → «2.0 KB»", item_b.text(1) == "2.0 KB",
      f"got={item_b.text(1)!r}")
check("mtime отформатирован (не пусто)", len(item_a.text(2)) == 16,
      f"got={item_a.text(2)!r}")
check("PATH_ROLE — полный путь", item_a.data(0, tab.PATH_ROLE) == "/home/a.txt")
check("ISDIR_ROLE: каталог sub помечен", item_sub.data(0, tab.ISDIR_ROLE) is True)

# Назад через «..» (двойной клик по строке «..»)
tab._on_item_double_clicked(tab._up_item, 0)
wait_until(lambda: [tab.tree.topLevelItem(i).text(0)
                    for i in range(tab.tree.topLevelItemCount())] == ["home", "var"],
           timeout_ms=5000)
check("«..» — возврат в корень (без строки «..»)", tab.path_label.text() == "/")

# Кнопка «Вверх» = то же самое (сначала вниз, потом go_up())
tab._navigate("/home")
wait_until(lambda: tab.path_label.text() == "/home", timeout_ms=5000)
tab.go_up()
wait_until(lambda: tab.path_label.text() == "/", timeout_ms=5000)
check("кнопка «Вверх»: /home → /", tab.path_label.text() == "/")

# Сталкинг-фильтр: переход, пока летит старый листинг (chunk_delay=10 мс)
tab._navigate("/home")      # list A в пути
tab.go_up()                 # list B в пути; текущий = "/"
wait_until(lambda: log6.of_kind("list", None) and tab.tree.topLevelItemCount() >= 2
           and tab.path_label.text() == "/", timeout_ms=5000)
names = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
check("сталкинг-фильтр: отрисован ответ ТЕКУЩЕГО каталога (корень, без «..»)",
      names == ["home", "var"], f"names={names}")

# Refresh — повторный листинг того же каталога
n_before = tab.tree.topLevelItemCount()
tab.btn_refresh.click()
wait_until(lambda: tab.tree.topLevelItemCount() == n_before, timeout_ms=5000)
check("Refresh: листинг перестроен (те же записи)",
      [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
      == ["home", "var"])

# ── upload через вкладку (QFileDialog подменён модульно) ──
up_local = make_local_file("upload_via_tab.txt", 256, b"u")


class _FakeDialog:
    @staticmethod
    def getOpenFileNames(*a, **k):
        return ([up_local], "")

    @staticmethod
    def getExistingDirectory(*a, **k):
        d = os.path.join(WORK, "dl2")  # реальный диалог отдаёт СУЩЕСТВУЮЩИЙ каталог
        os.makedirs(d, exist_ok=True)
        return d


saved_dialog = STAB.QFileDialog
STAB.QFileDialog = _FakeDialog
try:
    tab._navigate("/home")
    wait_until(lambda: tab.path_label.text() == "/home", timeout_ms=5000)
    done_before = len(log6.of_kind("done"))
    tab.btn_upload.click()
    # Ждём task_done, а не появление в fs6.files: open("wb") создаёт запись ДО
    # записи чанков — ожидание по наличию даёт гонку с беглым upload.
    wait_until(lambda: len(log6.of_kind("done")) >= done_before + 1, timeout_ms=5000)
    check("upload через вкладку → файл в ТЕКУЩЕМ каталоге (/home)",
          fs6.files.get("/home/upload_via_tab.txt") == b"u" * 256)

    # download выбранных (a.txt + b.log) в локальный каталог
    wait_until(lambda: tab.tree.topLevelItemCount() >= 4, timeout_ms=5000)
    tab.tree.clearSelection()
    tab.tree.topLevelItem(2).setSelected(True)  # a.txt
    tab.tree.topLevelItem(3).setSelected(True)  # b.log
    done_before = len(log6.of_kind("done"))
    tab.btn_download.click()
    # Ждём ОБА task_done, а не isfile(): файл существует на диске ещё до записи
    # чанков (open "wb") — ожидание по наличию даёт гонку с беглым download.
    wait_until(lambda: len(log6.of_kind("done")) >= done_before + 2, timeout_ms=5000)
    check("download выбранных: a.txt скачан с контентом",
          open(os.path.join(WORK, "dl2", "a.txt"), "rb").read() == b"x" * 100)
    check("download выбранных: b.log скачан с контентом",
          open(os.path.join(WORK, "dl2", "b.log"), "rb").read() == b"y" * 2048)

    # download без выбора — подсказка message(), в очередь ничего
    msgs.clear()
    tab.tree.clearSelection()
    tab.btn_download.click()
    check("download без выбора → message «выберите файлы»",
          msgs == [i18n.t("sftp.no_selection")], f"msgs={msgs}")

    # upload/download без worker — подсказка «ожидание соединения»
    tab.set_worker(None)
    check("без worker: состояние «ожидание» (path_label)",
          tab.path_label.text() == i18n.t("sftp.waiting_connection"),
          f"got={tab.path_label.text()!r}")
    # Кнопки в состоянии ожидания отключены (подсказка — path_label выше);
    # кликнуть нечего, message() здесь не эмитится.
    check("без worker: кнопки навигации/операций отключены",
          not tab.btn_up.isEnabled() and not tab.btn_refresh.isEnabled()
          and not tab.btn_upload.isEnabled() and not tab.btn_download.isEnabled())

    # Кнопка «Отменить» по передачам: медленный upload → cancel → сброс
    slow_fs = FakeSftpFS()
    slow_fs.add_dir("/data")  # непустой корень — листинг есть что отрисовать
    slow_client = FakeSftpClient(slow_fs, chunk_delay=0.05)
    worker_s = SftpWorker(slow_client)
    log_s = EventLog()
    wire_worker(worker_s, log_s)
    worker_s.start()
    tab.set_worker(worker_s)
    wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
    check("кнопка «Отменить» отключена до передач", not tab.btn_cancel.isEnabled())
    slow_local = make_local_file("slow_tab.bin", 8 * 32768, b"t")
    _FakeDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([slow_local], ""))
    tab.btn_upload.click()
    wait_until(lambda: tab.btn_cancel.isEnabled(), timeout_ms=5000)
    check("кнопка «Отменить» включена во время передачи", tab.btn_cancel.isEnabled())
    tab.btn_cancel.click()
    wait_until(lambda: not tab.btn_cancel.isEnabled(), timeout_ms=8000)
    check("после отмены: кнопка «Отменить» снова отключена",
          not tab.btn_cancel.isEnabled())
    worker_s.shutdown(wait_ms=2000)
finally:
    STAB.QFileDialog = saved_dialog

worker6.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 6. SSHTerminalWindow: QTabWidget + ленивый open_sftp на общем transport
# ════════════════════════════════════════════════════════════
print("== 6. terminal window: tabs + lazy open_sftp (offscreen) ==")

import modules.ssh_terminal as ST
from models.server import ServerData


class _FakeChannel:
    closed = False

    def send(self, data):
        pass


class _FakeTransport:
    def __init__(self, active=True):
        self._active = active

    def is_active(self):
        return self._active


class _FakeSshClient:
    """Та же поверхность, что у paramiko SSHClient для окна: get_transport/open_sftp."""

    def __init__(self, sftp_client):
        self._sftp = sftp_client
        self._tr = _FakeTransport(True)

    def get_transport(self):
        return self._tr

    def open_sftp(self):
        if self._sftp is None:
            raise Exception("SFTP subsystem disabled")
        return self._sftp

    def close(self):
        pass


class _FakeSSHThread(QThread):
    """Тот же API, что у SSHTerminalThread; run() — pass (реальный SSH не нужен)."""
    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.client = None  # появится «после подключения» (сценарий B)
        self.channel = _FakeChannel()
        self.running = True

    def run(self):
        pass

    def stop(self):
        self.running = False

    def send_data(self, data_bytes):
        pass


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread  # все окна терминала в этом файле — на фейке

_term_windows = []


def make_win(alias, ssh_client=None):
    """Окно терминала с фейковым потоком; ssh_client — «уже подключённый»
    paramiko-клиент (или None — соединение ещё не готово)."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"sftp-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password="pw")
    _term_windows.append(w)
    w.resize(700, 500)
    w.terminal_thread.client = ssh_client
    return w


# ── Сценарий A: соединение готово, переход на «Файлы» открывает SFTP ──
fs_first = FakeSftpFS()
fs_first.add_dir("/data")  # непустой корень — листинг есть что отрисовать
first_sftp = FakeSftpClient(fs_first)
win_a = make_win("a", _FakeSshClient(first_sftp))
check("QTabWidget с двумя вкладками", win_a.tabs.count() == 2)
check("заголовки вкладок: Терминал | Файлы (i18n en)",
      win_a.tabs.tabText(0) == i18n.t("sftp.tab_terminal")
      and win_a.tabs.tabText(1) == i18n.t("sftp.tab_files"),
      f"got={win_a.tabs.tabText(0)!r}/{win_a.tabs.tabText(1)!r}")
check("worker НЕ создан до перехода на вкладку (ленивый старт)",
      win_a._sftp_worker is None)
# isHidden() — флаг самого виджета: окно в тесте не show()-ится, поэтому
# isVisible() (учитывает предков) был бы False даже после show().
check("progress bar в статус-баре, скрыт", win_a._sftp_progress.isHidden())

win_a.tabs.setCurrentIndex(1)
wait_until(lambda: win_a._sftp_worker is not None and win_a._sftp_worker.isRunning(),
           timeout_ms=5000)
check("переход на «Файлы» → open_sftp() + worker запущен", win_a._sftp_worker is not None)
wait_until(lambda: win_a.sftp_tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
check("листинг корня в вкладке (через общий transport)",
      win_a.sftp_tab.path_label.text() == "/")

# Повторный переход — идемпотентно (тот же worker)
w_ref = win_a._sftp_worker
win_a.tabs.setCurrentIndex(0)
win_a.tabs.setCurrentIndex(1)
check("повторный старт идемпотентен (тот же worker)", win_a._sftp_worker is w_ref)

# «Сессия умерла»: transport закрыт → worker замечает мёртвый канал, сам
# останавливается и окно сбрасывает состояние (finished-сигнал).
first_sftp.close()
wait_until(lambda: win_a._sftp_worker is None, timeout_ms=5000)
check("смерть transport'а → worker сам остановился, состояние окна сброшено",
      win_a._sftp_worker is None)

# Новое соединение (медленный SFTP-клиент) — повторный ленивый старт
fsA = FakeSftpFS()
fsA.add_dir("/data")
slow_client_a = FakeSftpClient(fsA, chunk_delay=0.05)  # ~400 мс на upload
win_a.terminal_thread.client = _FakeSshClient(slow_client_a)
win_a.tabs.setCurrentIndex(0)
win_a.tabs.setCurrentIndex(1)
wait_until(lambda: win_a._sftp_worker is not None and win_a._sftp_worker.isRunning()
           and win_a._sftp_worker is not w_ref, timeout_ms=5000)
check("повторный старт после сброса — НОВЫЙ worker", win_a._sftp_worker is not w_ref)
wait_until(lambda: win_a.sftp_tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)

# Прогресс в статус-баре: медленный upload через вкладку
saved_dialog = STAB.QFileDialog
STAB.QFileDialog = _FakeDialog
try:
    big_local = make_local_file("big_win.bin", 8 * 32768, b"z")
    _FakeDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([big_local], ""))
    win_a.sftp_tab.btn_upload.click()
    wait_until(lambda: not win_a._sftp_progress.isHidden(), timeout_ms=5000)
    check("прогресс-бар виден во время передачи", not win_a._sftp_progress.isHidden())
    wait_until(lambda: "%" in (win_a.statusBar().currentMessage() or ""), timeout_ms=8000)
    msg = win_a.statusBar().currentMessage()
    check("статус-бар: текст прогресса с процентами", "%" in msg and "big_win.bin" in msg,
          f"msg={msg!r}")
    wait_until(lambda: win_a._sftp_progress.isHidden(), timeout_ms=8000)
    check("после завершения: прогресс-бар скрыт", win_a._sftp_progress.isHidden())
finally:
    STAB.QFileDialog = saved_dialog

# closeEvent: teardown SFTP-worker + терминального потока (idle — быстро)
t0 = time.time()
win_a.close()
elapsed = time.time() - t0
app.processEvents()
check("closeEvent окна с живым worker'ом: без падений, < 4 c", elapsed < 4.0,
      f"elapsed={elapsed:.3f}")
wait_until(lambda: len(SW._orphan_workers) == 0, timeout_ms=5000)
check("реестр орфано-worker'ов пуст после закрытия", len(SW._orphan_workers) == 0)

# ── Сценарий B: пользователь на «Файлы» во время подключения ──
win_b = make_win("b")  # client=None — ещё подключаемся
win_b.tabs.setCurrentIndex(1)
app.processEvents()
check("без соединения: worker не создан", win_b._sftp_worker is None)
check("без соединения: вкладка в состоянии ожидания",
      win_b.sftp_tab.path_label.text() == i18n.t("sftp.waiting_connection"),
      f"got={win_b.sftp_tab.path_label.text()!r}")

# «Подключение завершилось»: client появился + connected_signal
win_b.terminal_thread.client = _FakeSshClient(FakeSftpClient(FakeSftpFS()))
win_b.terminal_thread.connected_signal.emit()
wait_until(lambda: win_b._sftp_worker is not None and win_b._sftp_worker.isRunning(),
           timeout_ms=5000)
check("connected_signal → SFTP открыт (пользователь уже на вкладке)",
      win_b._sftp_worker is not None)
win_b.close()

# ── Сценарий C: open_sftp упал (подсистема выключена) — ошибка в статус-баре ──
win_c = make_win("c", _FakeSshClient(None))  # client, у которого open_sftp бросает
win_c.tabs.setCurrentIndex(1)
app.processEvents()
check("open_sftp упал: worker не создан", win_c._sftp_worker is None)
msg_c = win_c.statusBar().currentMessage() or ""
check("open_sftp упал: ошибка в статус-баре (i18n sftp.open_failed)",
      "SFTP" in msg_c, f"msg={msg_c!r}")
win_c.close()

ST.SSHTerminalThread = _orig_thread_cls  # вернуть оригинальный класс


# ════════════════════════════════════════════════════════════
# 7. i18n: 21 ключ sftp.* × en/ru/zh, паритет 377 → 398
# ════════════════════════════════════════════════════════════
print("== 7. i18n: sftp.* keys x3, parity 398 ==")

SFTP_KEYS = [
    "sftp.tab_terminal", "sftp.tab_files", "sftp.up", "sftp.refresh",
    "sftp.upload", "sftp.download", "sftp.cancel", "sftp.column_name",
    "sftp.column_size", "sftp.column_modified", "sftp.waiting_connection",
    "sftp.listing", "sftp.uploading", "sftp.downloading", "sftp.progress",
    "sftp.transfer_done", "sftp.transfer_cancelled", "sftp.no_selection",
    "sftp.upload_dialog_title", "sftp.download_dir_title", "sftp.open_failed",
]
check("в коде используется ровно 21 ключ sftp.*", len(SFTP_KEYS) == 21)

for code in ("en", "ru", "zh"):
    i18n.set_language(code)
    missing = [k for k in SFTP_KEYS if i18n.t(k) == k or not i18n.t(k).strip()]
    check(f"{code}: все 21 ключ sftp.* переведены (не пустые, не сырые)",
          not missing, f"missing={missing}")

i18n.set_language("en")  # вернуть дефолт для чистоты

check_i18n_parity(load_i18n_langs(ROOT))

# format_size/format_mtime — чистые функции (прогресс-текст статус-бара)
check("format_size: 0/1023/1024/1536/1MB",
      (format_size(0), format_size(1023), format_size(1024),
       format_size(1536), format_size(1024 * 1024))
      == ("0 B", "1023 B", "1.0 KB", "1.5 KB", "1.0 MB"))
check("format_size: битые значения → «?»",
      format_size(None) == "?" and format_size(-5) == "?")
check("format_mtime: нулевое/битое → пусто; валидное — 16 символов",
      format_mtime(0) == "" and format_mtime(None) == ""
      and len(format_mtime(1700000000)) == 16)


# ════════════════════════════════════════════════════════════
# 8. Состояние релиза (пины — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== 8. release state ==")
check_release_state(ROOT)

finish()
