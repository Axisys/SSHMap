# -*- coding: utf-8 -*-
"""v1.2.8 — D&D файлов из Проводника в SFTP-вкладку (ROADMAP v1.2.8).

Тема релиза: SftpTab принимает drop файлов (URL из QMimeData) → upload через
worker-очередь v1.1.3 в ТЕКУЩИЙ показанный каталог; несколько файлов =
последовательные задачи очереди; прогресс — в статус-баре окна (ответственность
окна, не вкладки); ошибки (нет соединения / нет прав / ошибка пути) —
error-сигнал БЕЗ падения очереди.

ВСЕ проверки — без сети: фейковый SFTPClient с in-memory ФС (та же поверхность
API, что у paramiko: listdir_attr/open/close/get_channel; ошибки — IOError
"No such file" как SSH_FX_NO_SUCH_FILE и PermissionError "Permission denied")
+ симуляция drag через синтетические QDragEnterEvent/QDropEvent с QMimeData
(URL реальных локальных файлов из рабочей папки теста).

Offscreen-нюанс (установлен пробами, PySide6 6.11): синтетические drag-события
НЕ проходят по реальному DnD-пути Qt notify() (childAt/spontaneous — их
доставка виджетам под курсором недоступна из Python и обходит event-фильтры),
поэтому доставка в тесте — прямыми виртуальными вызовами
(`tab.dragEnterEvent(ev)` / `tab.dropEvent(ev)`) и прямым
`tab.eventFilter(child, ev)` для маршрутизации событий с ДЕТЕЙ. Это ровно та
логика обработчиков, которая обслуживает настоящий drop из Проводника:
в проде Qt доставляет событие виджету под курсором (дерево/viewport/кнопки —
детям вкладки), eventFilter пересылает его в обработчики САМОЙ вкладки
(см. docstring modules/sftp_tab.py, v1.2.8).

Секции:
  1. _local_files(mime): фильтрация URL (файлы/каталоги/не-локальные/
     несуществующие/пусто).
  2. Симуляция drag на вкладке: dragEnter принимает с файлами / отклоняет без;
     drop → upload'ы идут через worker-очередь СТРОГО последовательно,
     прогресс-сигналы по порядку (монотонность, финал == total), контент на
     «сервере», подсказка drop_queued (count+dir); цель = ТЕКУЩИЙ каталог.
  3. Маршрутизация через eventFilter: drag-события на детях (viewport дерева,
     кнопка) пересылаются и потребляются (True), не-drag события проходят
     мимо (False), чужие виджеты не трогаются; drop на ребёнке = тот же
     результат, что и на самой вкладке; пустой drop (только каталоги) —
     подсказка drop_no_files.
  4. Ошибки через drop-путь: нет соединения → waiting_connection + в очередь
     ничего; удалённый каталог исчез / нет прав на запись → task_error,
     очередь жива, последующие drop'ы завершаются.
  5. i18n: sftp.drop_queued/sftp.drop_no_files × en/ru/zh (переведены,
     форматирование {count}/{dir}), паритет 427.
  6. Состояние релиза (пины — tests/_common.py).

Запуск:  python tests/test_sftp_dnd.py   (из корня проекта) или python tests/run_all.py
"""
import os
import posixpath
import sys
import threading

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import QEvent, QPoint, Qt, QUrl, QMimeData
try:
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
except ImportError:  # pragma: no cover — страховка на другие сборки PySide6
    from PySide6.QtWidgets import QDragEnterEvent, QDragMoveEvent, QDropEvent  # type: ignore
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

import i18n
from modules.sftp_worker import SftpWorker
from modules.sftp_tab import SftpTab


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
    """In-memory удалённая ФС: dirs (set путей) + files (dict путь→bytes).

    deny_write — пути, где open("wb") бросает PermissionError («нет прав»).
    remove_dir() — имитация удаления каталога НА СЕРВЕРЕ между листингом и
    drop'ом (гонка реального мира: каталог живёт в дереве, а на сервере исчез).
    """

    def __init__(self, deny_write=frozenset()):
        self.dirs = {"/"}
        self.files = {}
        self.mtimes = {}
        self.deny_write = set(deny_write)

    def add_dir(self, path):
        self.dirs.add(_norm(path))

    def remove_dir(self, path):
        self.dirs.discard(_norm(path))

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
            if self._path in fs.deny_write:
                raise PermissionError("Permission denied")
            if self._path not in fs.files:
                fs.files[self._path] = bytearray()
        else:
            if self._path not in fs.files:
                raise IOError("No such file")

    def read(self, n=-1):
        if self._delay:
            import time
            time.sleep(self._delay)
        buf = self._fs.files[self._path]
        end = len(buf) if n < 0 else min(len(buf), self._pos + n)
        data = bytes(buf[self._pos:end])
        self._pos = end
        return data

    def write(self, data):
        if self._delay:
            import time
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
            import time
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
            import time
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


# ── Симуляция drag: QMimeData + синтетические события (см. docstring) ───────

def mime_with(*paths):
    """QMimeData с URL локальных путей (то, что несёт drop из Проводника)."""
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return m


def drag_enter_event(mime, pos=QPoint(10, 10)):
    return QDragEnterEvent(pos, Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def drop_event(mime, pos=QPoint(10, 10)):
    return QDropEvent(pos, Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def upload_starts(log):
    """task_started с kind == 'upload' (порядок очереди)."""
    with log.lock:
        return [e for e in log.events if e[0] == "started" and e[2] == "upload"]


# ════════════════════════════════════════════════════════════
# 1. _local_files(mime): фильтрация URL перетаскивания
# ════════════════════════════════════════════════════════════
print("== 1. _local_files: URL filtering ==")

lf_a = make_local_file("lf_a.bin", 10, b"a")
lf_b = make_local_file("lf_b.bin", 10, b"b")
lf_dir = os.path.join(WORK, "somedir")
os.makedirs(lf_dir, exist_ok=True)

# QUrl.toLocalFile() отдаёт пути со SLASH'ами (F:/...) — сверяем через normpath
def _normpaths(paths):
    return [os.path.normpath(p) for p in paths]


m_mixed = mime_with(lf_a, lf_dir, lf_b)
got = SftpTab._local_files(m_mixed)
check("файлы только (каталог пропущен), порядок сохранён", _normpaths(got) == [lf_a, lf_b],
      f"got={got}")

m_nonlocal = QMimeData()
m_nonlocal.setUrls([QUrl.fromLocalFile(lf_a), QUrl("https://example.com/x.bin")])
got_nl = SftpTab._local_files(m_nonlocal)
check("не-локальный URL (https) пропущен", _normpaths(got_nl) == [lf_a],
      f"got={got_nl}")

m_missing = mime_with(os.path.join(WORK, "no_such_file.bin"))
check("несуществующий локальный путь пропущен", SftpTab._local_files(m_missing) == [])

m_text = QMimeData()
m_text.setText("hello")
check("drag без URL (текст) → пусто", SftpTab._local_files(m_text) == [])
check("None mime → пусто", SftpTab._local_files(None) == [])


# ════════════════════════════════════════════════════════════
# 2. Симуляция drag на вкладке: drop → worker-очередь, строго последовательно
# ════════════════════════════════════════════════════════════
print("== 2. drag simulation: drop -> worker queue, strictly sequential ==")

fs = FakeSftpFS()
fs.add_dir("/data")
client = FakeSftpClient(fs, chunk_delay=0.005)  # задержка на чанк — порядок наблюдаем
worker = SftpWorker(client)
log = EventLog()
wire_worker(worker, log)
worker.start()

tab = SftpTab()
msgs = []
tab.message.connect(msgs.append)
tab.set_worker(worker)  # → _relist("/")

wait_until(lambda: tab.tree.topLevelItemCount() >= 1, timeout_ms=5000)
check("листинг корня (каталог data)",
      [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())] == ["data"],
      f"got={[tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]}")

# Вход в /data — цель drop'а = ТЕКУЩИЙ каталог (не корень)
tab._navigate("/data")
wait_until(lambda: tab.path_label.text() == "/data", timeout_ms=5000)

SIZE_A, SIZE_B = 4 * 32768, 3 * 32768  # 4 и 3 чанка по 32 КБ
drop_a = make_local_file("drop_a.bin", SIZE_A, b"a")
drop_b = make_local_file("drop_b.bin", SIZE_B, b"b")

# dragEnter с файлами → accept; без локальных файлов → не accept
m_ab = mime_with(drop_a, drop_b)
ev_in = drag_enter_event(m_ab)
tab.dragEnterEvent(ev_in)
check("dragEnter с файлами: принято (acceptProposedAction)", ev_in.isAccepted())

m_text2 = QMimeData()
m_text2.setText("no files here")
ev_in2 = drag_enter_event(m_text2)
tab.dragEnterEvent(ev_in2)
check("dragEnter без локальных файлов: НЕ принято", not ev_in2.isAccepted())

# drop → ОБА файла через очередь (последовательные задачи v1.1.3)
msgs.clear()
ev_drop = drop_event(m_ab)
tab.dropEvent(ev_drop)
check("drop с файлами: принят", ev_drop.isAccepted())

wait_until(lambda: len(upload_starts(log)) >= 2, timeout_ms=5000)
starts = upload_starts(log)
check("два upload'а пошли через очередь (task_started × 2)", len(starts) == 2,
      f"got={starts}")
tid_a, tid_b = starts[0][1], starts[1][1]
check("task id последовательные (порядок очереди)", tid_b == tid_a + 1,
      f"a={tid_a} b={tid_b}")
wait_until(lambda: bool(log.of_kind("done", tid_a)) and bool(log.of_kind("done", tid_b)),
           timeout_ms=8000)
app.processEvents()

idx = {}
with log.lock:
    for i, e in enumerate(log.events):
        if len(e) > 1 and e[1] in (tid_a, tid_b):
            idx.setdefault(e[1], []).append(i)
last_a = max(idx.get(tid_a, [0]))
first_b = min(idx.get(tid_b, [len(log.events)]))
check("строго последовательно: ВСЕ события A раньше ЛЮБЫХ B", last_a < first_b,
      f"last_a={last_a} first_b={first_b}")

kinds_a = [log.events[i][0] for i in idx.get(tid_a, [])]
check("A: started → progress* → done", kinds_a[:1] == ["started"]
      and kinds_a[-1] == "done" and all(k == "progress" for k in kinds_a[1:-1]),
      f"kinds={kinds_a}")

prog_a = [e[2] for e in log.of_kind("progress", tid_a)]
check("A: прогресс монотонно растёт",
      prog_a and all(x <= y for x, y in zip(prog_a, prog_a[1:])), f"prog={prog_a}")
check("A: финальный прогресс == total (4 чанка)", prog_a[-1] == SIZE_A,
      f"last={prog_a[-1] if prog_a else None} total={SIZE_A}")
prog_b = [e[2] for e in log.of_kind("progress", tid_b)]
check("B: финальный прогресс == total (3 чанка)", prog_b and prog_b[-1] == SIZE_B,
      f"last={prog_b[-1] if prog_b else None} total={SIZE_B}")

check("контент A на «сервере» в ТЕКУЩЕМ каталоге (/data)",
      fs.files.get("/data/drop_a.bin") == b"a" * SIZE_A)
check("контент B на «сервере» в /data", fs.files.get("/data/drop_b.bin") == b"b" * SIZE_B)

expected_msg = i18n.t("sftp.drop_queued", count=2, dir="/data")
check("подсказка после drop: drop_queued (count=2, dir=/data)", msgs == [expected_msg],
      f"msgs={msgs} expected={[expected_msg]}")


# ════════════════════════════════════════════════════════════
# 3. Маршрутизация через eventFilter: drag-события на детях вкладки
# ════════════════════════════════════════════════════════════
print("== 3. routing via eventFilter: drag events on children ==")

# drop на viewport дерева (ребёнок) — фильтр пересылает в обработчики САМОЙ
# вкладки и потребляет событие (дерево не обрабатывает его «по-своему»)
vp = tab.tree.viewport()
drop_c = make_local_file("drop_child.bin", 1024, b"c")
m_c = mime_with(drop_c)
ev_child = drop_event(m_c)
consumed = tab.eventFilter(vp, ev_child)
check("eventFilter(viewport, Drop): событие потреблено (True)", consumed is True,
      f"got={consumed}")

n_starts_before = len(upload_starts(log))
wait_until(lambda: len(upload_starts(log)) > n_starts_before
           and bool(log.of_kind("done", upload_starts(log)[-1][1])), timeout_ms=5000)
check("drop на ребёнке (viewport): upload завершился в текущем каталоге",
      fs.files.get("/data/drop_child.bin") == b"c" * 1024,
      f"got={fs.files.get('/data/drop_child.bin')!r}")

# dragEnter на кнопке — тоже пересылается (цель drop'а не зависит от точки)
m_c2 = mime_with(drop_c)
ev_btn_in = drag_enter_event(m_c2)
consumed2 = tab.eventFilter(tab.btn_upload, ev_btn_in)
check("eventFilter(btn_upload, DragEnter): переслан и принят",
      consumed2 is True and ev_btn_in.isAccepted(), f"got={consumed2}")

# не-drag событие проходит мимо (False) — обработчики не вызваны
ev_other = QEvent(QEvent.Type.FocusIn)
r = tab.eventFilter(vp, ev_other)
check("eventFilter(viewport, не-drag): проход (False)", r is False, f"got={r}")

# чужой виджет (не потомок вкладки) — не трогаем даже для Drop
foreign = QWidget()
m_f = mime_with(drop_c)
ev_foreign = drop_event(m_f)
r2 = tab.eventFilter(foreign, ev_foreign)
check("eventFilter(чужой виджет, Drop): не потреблено (False), событие не принято",
      r2 is False and not ev_foreign.isAccepted(), f"got={r2}")

# DragMove на ребёнке — тот же ответ, что и dragEnter (иначе Qt сбросит действие)
m_mv = mime_with(drop_c)
ev_move = QDragMoveEvent(QPoint(5, 5), Qt.DropAction.CopyAction, m_mv,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
r3 = tab.eventFilter(vp, ev_move)
check("eventFilter(viewport, DragMove): переслан и принят",
      r3 is True and ev_move.isAccepted(), f"got={r3}")

# пустой drop (только каталоги в перетаскивании) — подсказка, в очередь ничего
msgs.clear()
m_dirs = mime_with(lf_dir)
ev_dirs = drop_event(m_dirs)
tab.dropEvent(ev_dirs)
check("drop без локальных файлов: НЕ принят", not ev_dirs.isAccepted())
check("подсказка drop_no_files (перетаскивание каталогов)",
      msgs == [i18n.t("sftp.drop_no_files")], f"msgs={msgs}")


# ════════════════════════════════════════════════════════════
# 4. Ошибки через drop-путь: очередь не падает (паттерн тестов v1.1.3)
# ════════════════════════════════════════════════════════════
print("== 4. errors via drop path: queue survives ==")

# a) нет соединения: подсказка «ожидание», в очередь ничего не уходит
tab.set_worker(None)
check("без worker: состояние «ожидание» (path_label)",
      tab.path_label.text() == i18n.t("sftp.waiting_connection"),
      f"got={tab.path_label.text()!r}")
msgs.clear()
m_nw = mime_with(drop_c)
ev_nowork = drop_event(m_nw)
tab.dropEvent(ev_nowork)
check("drop без соединения: подсказка waiting_connection",
      msgs == [i18n.t("sftp.waiting_connection")], f"msgs={msgs}")

# b) ошибка пути: удалённый каталог исчез на сервере МЕЖДУ листингом и drop'ом
fs2 = FakeSftpFS()
fs2.add_dir("/data")
worker2 = SftpWorker(FakeSftpClient(fs2))
log2 = EventLog()
wire_worker(worker2, log2)
worker2.start()

tab2 = SftpTab()
msgs2 = []
tab2.message.connect(msgs2.append)
tab2.set_worker(worker2)
wait_until(lambda: tab2.tree.topLevelItemCount() >= 1, timeout_ms=5000)
tab2._navigate("/data")
wait_until(lambda: tab2.path_label.text() == "/data", timeout_ms=5000)

fs2.remove_dir("/data")  # каталог исчез на сервере (гонка листинг → drop)
err_a = make_local_file("err_a.bin", 100, b"e")
err_b = make_local_file("err_b.bin", 100, b"f")
m_err = mime_with(err_a, err_b)
ev_err = drop_event(m_err)
tab2.dropEvent(ev_err)

wait_until(lambda: len(log2.of_kind("error")) >= 2, timeout_ms=8000)
errs = log2.of_kind("error")
check("upload в удалённый (исчезнувший) каталог → task_error × 2", len(errs) == 2,
      f"got={errs}")
check("текст ошибки — «No such file» (SSH_FX_NO_SUCH_FILE)",
      all(len(e) > 3 and "No such file" in e[3] for e in errs),
      f"msgs={[e[3] for e in errs]}")

# очередь жива: каталог «восстановлен» → следующий drop завершается штатно
fs2.add_dir("/data")
err_c = make_local_file("err_c.bin", 100, b"g")
n_before = len(upload_starts(log2))
m_ok = mime_with(err_c)
ev_ok = drop_event(m_ok)
tab2.dropEvent(ev_ok)


def _ok_after_error():
    starts_now = upload_starts(log2)
    return len(starts_now) > n_before and bool(log2.of_kind("done", starts_now[-1][1]))


wait_until(_ok_after_error, timeout_ms=8000)
check("очередь жива после ошибок пути: следующий drop завершился",
      fs2.files.get("/data/err_c.bin") == b"g" * 100)

# c) нет прав: open("wb") → PermissionError; очередь жива для других путей
fs3 = FakeSftpFS(deny_write=frozenset({"/ro/perm.bin"}))
fs3.add_dir("/ro")
fs3.add_dir("/rw")
worker3 = SftpWorker(FakeSftpClient(fs3))
log3 = EventLog()
wire_worker(worker3, log3)
worker3.start()

tab3 = SftpTab()
msgs3 = []
tab3.message.connect(msgs3.append)
tab3.set_worker(worker3)
wait_until(lambda: tab3.tree.topLevelItemCount() >= 2, timeout_ms=5000)
tab3._navigate("/ro")
wait_until(lambda: tab3.path_label.text() == "/ro", timeout_ms=5000)

perm_local = make_local_file("perm.bin", 100, b"h")
m_perm = mime_with(perm_local)
ev_perm = drop_event(m_perm)
tab3.dropEvent(ev_perm)

wait_until(lambda: len(log3.of_kind("error")) >= 1, timeout_ms=8000)
errp = log3.of_kind("error")[0]
check("upload без прав на запись → task_error (PermissionError)",
      len(errp) > 3 and "Permission denied" in errp[3], f"msg={errp[3]!r}")

tab3._navigate("/rw")
wait_until(lambda: tab3.path_label.text() == "/rw", timeout_ms=5000)
m_rw = mime_with(perm_local)
ev_rw = drop_event(m_rw)
tab3.dropEvent(ev_rw)
wait_until(lambda: fs3.files.get("/rw/perm.bin") is not None, timeout_ms=8000)
check("очередь жива после ошибки прав: drop в записываемый каталог завершился",
      fs3.files.get("/rw/perm.bin") == b"h" * 100)

worker2.shutdown(wait_ms=2000)
worker3.shutdown(wait_ms=2000)


# ════════════════════════════════════════════════════════════
# 5. i18n: sftp.drop_* × en/ru/zh, паритет 427
# ════════════════════════════════════════════════════════════
print("== 5. i18n: sftp.drop_* keys x3, parity 427 ==")

for code in ("en", "ru", "zh"):
    i18n.set_language(code)
    q = i18n.t("sftp.drop_queued", count=3, dir="/x")
    check(f"{code}: sftp.drop_queued переведён и отформатирован ({{count}}/{{dir}} подставлены)",
          q != "sftp.drop_queued" and "{count}" not in q and "{dir}" not in q
          and "3" in q and "/x" in q, f"got={q!r}")
    n = i18n.t("sftp.drop_no_files")
    check(f"{code}: sftp.drop_no_files переведён (не пустой, не сырой ключ)",
          n != "sftp.drop_no_files" and bool(n.strip()), f"got={n!r}")

i18n.set_language("en")  # вернуть дефолт для чистоты

check_i18n_parity(load_i18n_langs(ROOT))


# ════════════════════════════════════════════════════════════
# 6. Состояние релиза (пины — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== 6. release state ==")
check_release_state(ROOT)

worker.shutdown(wait_ms=2000)
finish()
