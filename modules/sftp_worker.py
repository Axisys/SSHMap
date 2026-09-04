# -*- coding: utf-8 -*-
"""SFTP worker-поток окна терминала (v1.1.3, ROADMAP задача 1).

Один worker-поток на сессию с FIFO-очередью задач (list/upload/download):
paramiko SFTPClient НЕ гарантирует thread-safety — все операции над клиентом
выполняются строго в этом потоке, N потоков на один клиент запрещены. Клиент
окно открывает поверх живого transport'а (`terminal_thread.client.open_sftp()`)
— без второй аутентификации и второго known_hosts-прохода (ROADMAP задача 3);
транспорт одновременно обслуживает и терминальный канал — это штатный режим
paramiko (разные каналы одного Transport, внутренние lock'и transport'а).

Отмена: флаг (_cancel_event), проверяемый МЕЖДУ операциями — перед каждым
чанком передачи и перед стартом каждой задачи из очереди. Отменённая передача
прекращается на ближайшем чанке; оставшиеся в очереди задачи пропускаются с
сигналом task_cancelled (GUI-состояние ведётся только по сигналам). Флаг
автосбрасывается, когда очередь опустела — следующие операции работают.

Корректный shutdown: stop_event + cancel_event + wait(); SFTPClient
закрывается в finally run() ВНУТРИ worker-потока (канал не закрывается из
чужого потока под летящими запросами). Если окно закрылось, пока передача
встаёт на мёртвой сети (closeEvent ждёт ограниченное время), поток живёт
дальше: смерть transport'а (terminal client.close() в finally терминального
потока) разрывает SFTP-канал, операция падает с исключением → except →
стоп. Реестр орфано-worker'ов (_orphan_workers, паттерн _orphan_threads из
ssh_terminal.py v1.1.2RC1 N4) держит такой поток до finished() — QThread без
QObject parent нельзя оставлять на GC («QThread: Destroyed while thread is
still running»); все слоты окна отвязаны в closeEvent, поздние emit без
приёмников — безопасный no-op (Qt сам удаляет подключения к уничтоженному
C++-объекту).

Сигналы (эмитятся из worker-потока; доставка в GUI — queued):
    list_ready(task_id, remote_dir, entries)  — entries: [{name,is_dir,size,mtime}]
                                                (каталоги первыми, далее по имени)
    task_started(task_id, kind, label)        — kind: "list" | "upload" | "download"
    progress(task_id, done_bytes, total_bytes)
    task_done(task_id, detail)                — detail: итоговый путь (файл/каталог)
    task_error(task_id, kind, message)        — ошибка задачи; ОЧЕРЕДЬ НЕ ПАДАЕТ
    task_cancelled(task_id, kind)             — отмена (не ошибка)

Методы queue_* предназначены для вызова из GUI-потока (счётчик task id не
синхронизируется — все вызовы приходят от одного потока).
"""
import os
import posixpath
import queue
import stat
import threading
from typing import List, Optional

from PySide6.QtCore import QThread, Signal


# Размер чанка передачи: 32 КБ = SFTP_MAX_REQUEST_SIZE paramiko — тот же
# размер, что у штатных sftp.get/put (эквивалентная пропускная способность,
# но полный контроль над отменой и прогрессом между операциями).
CHUNK_SIZE = 32 * 1024

KIND_LIST = "list"
KIND_UPLOAD = "upload"
KIND_DOWNLOAD = "download"


class _SftpCancelled(Exception):
    """Внутренний: отмена/стоп запрошен во время передачи (не ошибка)."""


class _SftpTask:
    """Задача очереди. remote_path/local_path — семантика зависит от kind:

      list     : remote_path = каталог для листинга
      upload   : local_path  = локальный файл, remote_path = ЦЕЛЕВОЙ каталог
      download : remote_path = удалённый файл, local_path = целевой каталог
    """
    __slots__ = ("id", "kind", "label", "remote_path", "local_path",
                 "total_size", "detail")

    def __init__(self, task_id: int, kind: str, label: str, remote_path: str,
                 local_path: str = "", total_size: int = 0, detail: str = ""):
        self.id = task_id
        self.kind = kind
        self.label = label          # для GUI (имя файла / путь каталога)
        self.remote_path = remote_path
        self.local_path = local_path
        self.total_size = total_size  # 0 — неизвестно (индетерминированный прогресс)
        self.detail = detail


# ── Реестр орфано-worker'ов (паттерн _orphan_threads, ssh_terminal.py N4) ───
# Окно имеет WA_DeleteOnClose: если closeEvent не дождался worker'а (сеть
# встала, wait() исчерпан), поток без parent нельзя оставлять на GC. Реестр
# держит его до finished(); самовычищается по сигналу finished().
_orphan_workers: List["SftpWorker"] = []


def register_orphan_sftp_worker(worker: "SftpWorker"):
    """Держать ещё работающий SftpWorker до finished() (идемпотентно)."""
    if worker not in _orphan_workers:
        _orphan_workers.append(worker)

        def _drop(_=None, w=worker):
            try:
                _orphan_workers.remove(w)
            except ValueError:
                pass  # уже удалён (двойной finished — на практике не бывает)
        worker.finished.connect(_drop)


class SftpWorker(QThread):
    """Один worker-поток с очередью задач поверх живого SFTPClient."""

    list_ready = Signal(int, str, list)      # task_id, remote_dir, entries
    task_started = Signal(int, str, str)     # task_id, kind, label
    progress = Signal(int, int, int)         # task_id, done_bytes, total_bytes
    task_done = Signal(int, str)             # task_id, detail
    task_error = Signal(int, str, str)       # task_id, kind, message
    task_cancelled = Signal(int, str)        # task_id, kind

    def __init__(self, sftp_client, parent=None):
        super().__init__(parent)
        self._sftp = sftp_client
        self._queue: "queue.Queue[_SftpTask]" = queue.Queue()
        self._stop_event = threading.Event()
        self._cancel_event = threading.Event()
        self._next_id = 1

    # ── Публичный API (GUI-поток) ────────────────────────────────────────

    def queue_list(self, remote_dir: str) -> Optional[int]:
        """Листинг каталога. Возвращает task id (None — поток не запущен)."""
        return self._queue_task(_SftpTask(
            self._next_id, KIND_LIST, remote_dir, remote_path=remote_dir,
            detail=remote_dir))

    def queue_upload(self, local_path: str, remote_dir: str) -> Optional[int]:
        """Upload локального файла в удалённый каталог (имя = basename)."""
        name = os.path.basename(local_path)
        remote_path = posixpath.join(remote_dir or "/", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_UPLOAD, name, remote_path=remote_path,
            local_path=local_path, detail=remote_path))

    def queue_download(self, remote_path: str, local_dir: str,
                       total_size: int = 0) -> Optional[int]:
        """Download удалённого файла в локальный каталог (имя = basename)."""
        name = posixpath.basename(remote_path)
        local_path = os.path.join(local_dir or ".", name)
        return self._queue_task(_SftpTask(
            self._next_id, KIND_DOWNLOAD, name, remote_path=remote_path,
            local_path=local_path, total_size=int(total_size or 0),
            detail=local_path))

    def cancel(self):
        """Отменить текущую передачу и всё ещё стоящее в очереди.

        Флаг проверяется между операциями (чанк/задача); после опустошения
        очереди автосбрасывается — новые операции работают без повторного
        «разблокирования».
        """
        self._cancel_event.set()

    def shutdown(self, wait_ms: int = 2500):
        """Корректная остановка: отмена текущего + стоп, ожидание ≤ wait_ms.

        SFTPClient закрывается в finally run() (внутри worker-потока). Если
        wait исчерпан (сеть встала), поток остаётся живым — его держит
        реестр орфано-worker'ов, а смерть transport'а разорвёт канал.
        """
        self._cancel_event.set()
        self._stop_event.set()
        if self.isRunning():
            self.wait(wait_ms)

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    # ── Внутреннее ───────────────────────────────────────────────────────

    def _queue_task(self, task: _SftpTask) -> Optional[int]:
        # Guard по isFinished(), а НЕ isRunning(): у свежего start() есть окно,
        # где поток ещё не начал run() (isRunning() False) — отказ в задаче
        # в этот момент оставил бы вкладку без корневого листинга. Завершённый
        # worker задачи уже не принимает.
        if self.isFinished():
            return None  # поток завершился — тихо игнор
        self._next_id += 1
        self._queue.put(task)
        return task.id

    def _emit(self, signal, *args):
        """Emit с guard'ом на teardown: C++-объекты приёмников могли быть
        уничтожены (гонка WA_DeleteOnClose) — поздний emit без приёмников
        безопасный no-op, а не RuntimeError."""
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def run(self):
        try:
            while not self._stop_event.is_set():
                # Мёртвый транспорт — делать нечего (окно закрывается либо
                # сессия умерла; window сбросит worker по finished()).
                try:
                    channel = self._sftp.get_channel()
                except Exception:
                    channel = None
                if channel is not None and getattr(channel, "closed", False):
                    break

                try:
                    task = self._queue.get(timeout=0.1)
                except queue.Empty:
                    # Очередь пуста и отмена запрошена (cancel в простое) —
                    # сброс флага: отменять было нечего, новые операции работают.
                    if self._cancel_event.is_set():
                        self._cancel_event.clear()
                    continue

                if self._cancel_event.is_set():
                    # Задача ещё не начиналась — пропускаем (GUI узнаёт по
                    # task_cancelled и не ждёт её никогда). Отмена действует на
                    # всё, что стояло в очереди В МОМЕНТ клика: флаг сбрасываем
                    # сразу и отчитываемся о прочем содержимом очереди.
                    self._emit(self.task_cancelled, task.id, task.kind)
                    self._apply_cancel()
                    continue

                try:
                    self._emit(self.task_started, task.id, task.kind, task.label)
                    if task.kind == KIND_LIST:
                        self._do_list(task)
                    elif task.kind == KIND_UPLOAD:
                        self._do_upload(task)
                    else:
                        self._do_download(task)
                    self._emit(self.task_done, task.id, task.detail)
                except _SftpCancelled:
                    self._emit(self.task_cancelled, task.id, task.kind)
                    self._apply_cancel()
                except Exception as e:  # noqa: BLE001 — ошибка пути/прав/сети
                    # ОЧЕРЕДЬ НЕ ПАДАЕТ: задача отчиталась ошибкой, цикл идёт
                    # дальше (требование ROADMAP задача 5).
                    self._emit(self.task_error, task.id, task.kind, str(e))
        finally:
            try:
                self._sftp.close()
            except Exception:
                pass

    def _check_cancel(self):
        if self._cancel_event.is_set() or self._stop_event.is_set():
            raise _SftpCancelled()

    def _apply_cancel(self):
        """Сбросить флаг отмены и отчитаться о прочем содержимом очереди.

        Семантика: cancel действует на всё, что было в полёте/в очереди В МОМЕНТ
        клика; задачи, поставленные ПОСЛЕ (когда очередь уже опустела), выполняются
        штатно — иначе «Отмена» одной передачи отменяла бы и следующую, поставленную
        тут же. Вызывается из worker-потока после прерванной/пропущенной задачи.
        """
        self._cancel_event.clear()
        while True:
            try:
                skipped = self._queue.get_nowait()
            except queue.Empty:
                break
            self._emit(self.task_cancelled, skipped.id, skipped.kind)

    def _do_list(self, task: _SftpTask):
        entries = []
        for attr in self._sftp.listdir_attr(task.remote_path):
            try:
                is_dir = bool(stat.S_ISDIR(attr.st_mode))
            except (AttributeError, TypeError):
                is_dir = False
            entries.append({
                "name": attr.filename,
                "is_dir": is_dir,
                "size": int(getattr(attr, "st_size", 0) or 0),
                "mtime": int(getattr(attr, "st_mtime", 0) or 0),
            })
        # Каталоги первыми, далее по имени (регистронезависимо).
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        self._check_cancel()
        self._emit(self.list_ready, task.id, task.remote_path, entries)

    def _do_upload(self, task: _SftpTask):
        total = os.path.getsize(task.local_path)  # FileNotFoundError → task_error
        remote_fh = self._sftp.open(task.remote_path, "wb")
        try:
            with open(task.local_path, "rb") as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = local.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    remote_fh.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done, total)
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass

    def _do_download(self, task: _SftpTask):
        remote_fh = self._sftp.open(task.remote_path, "rb")  # нет файла → ошибка
        try:
            with open(task.local_path, "wb") as local:
                done = 0
                while True:
                    self._check_cancel()
                    chunk = remote_fh.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    local.write(chunk)
                    done += len(chunk)
                    self._emit(self.progress, task.id, done, task.total_size)
        finally:
            try:
                remote_fh.close()
            except Exception:
                pass
