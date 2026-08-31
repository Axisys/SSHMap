"""Регрессионные тесты v0.8.1 — четыре исправления:

  #3 терминал не печатал   — output_signal = Signal(str) получал bytes;
                              теперь Signal(bytes), pyte получает сырые данные,
                              экран рендерится (E2E-проверка окна).
  #1 «Добавить сервер» падал на bool.x — QAction.triggered шлёт checked=bool
                              в _add_server(at_scene_pos); позиция принимается
                              только если это точка сцены.
  #2 ПКМ→SSH падал на bool.setSelected — замыкания контекстного меню MapView
                              теперь принимают `checked` первым параметром
                              (проверяется настоящий путь: contextMenuEvent →
                              QMenu → trigger()).
  #4 fingerprint «unavailable»/неверный SHA256 — paramiko>=5 asbytes() возвращает
                              сырые wire-байты, а не base64.

Запуск:  python tests/test_ssh_terminal.py   (из корня проекта) или python tests/run_all.py
"""
import os, sys, hashlib, traceback

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QPointF, QTimer, QEventLoop
from PySide6.QtGui import QKeyEvent, QContextMenuEvent
from PySide6.QtWidgets import QApplication, QDialog, QMenu

app = QApplication(sys.argv)


def _key(text="", key_code=None):
    """QKeyEvent в актуальной сигнатуре PySide6 (modifiers — enum'ом, по позиции)."""
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key_code), Qt.NoModifier, text)


def wait_until(cond, timeout_ms=2000, tick_ms=50):
    """Настоящий event loop до cond() или дедлайна (processEvents не гарантирует
    время жизни таймеров — для offscreen-рендера нужен реальный цикл)."""
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


# ════════════════════════════════════════════════════════════
# #3a. Сигнал bytes: сквозная доставка из QThread в GUI-поток
#      (именно этот путь давал «Shiboken::Conversions ... Cannot copy-convert (bytes)»)
# ════════════════════════════════════════════════════════════
print("== terminal signal (bug #3) ==")
from modules.ssh_terminal import SSHTerminalThread, SSHTerminalTextEdit

PAYLOAD = b"\x1b[0m\x1b[31mhello\xff\xfe\r\n"  # ANSI + не-UTF8 байты + CRLF


class _FakeTerm(SSHTerminalThread):
    """Наследуем реальный класс (с реальными сигнатурами сигналов), но без paramiko."""
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        self.status_signal.emit("fake")
        self.output_signal.emit(PAYLOAD)


received = []
t3 = _FakeTerm()
loop = QEventLoop()

def _on_out(data):
    received.append(data)
    if not loop.isRunning():
        return
    loop.quit()

t3.output_signal.connect(_on_out)          # queued (разные потоки) — как в окне терминала
to = QTimer(); to.setSingleShot(True); to.start(4000); to.timeout.connect(loop.quit)
t3.start()
loop.exec()
check("bytes signal delivered cross-thread without loss", received == [PAYLOAD],
      f"got {received!r}")
check("delivered arg is bytes (not str)", bool(received) and isinstance(received[0], bytes),
      f"type={type(received[0]).__name__ if received else 'n/a'}")

# ════════════════════════════════════════════════════════════
# #3b. E2E: SSHTerminalWindow рендерит байты в документ (до фикса — пустой экран)
# ════════════════════════════════════════════════════════════
import modules.ssh_terminal as ST

_orig_thread_cls = ST.SSHTerminalThread

class _FakeTerm2(_FakeTerm):
    pass

ST.SSHTerminalThread = _FakeTerm2  # окно создаст «поток» без сети
from models.server import ServerData
try:
    tdata = ServerData(id="termw1", alias="T", host="127.0.0.1", user="u")
    w3 = ST.SSHTerminalWindow(tdata, None)
    w3.show()
    # ждём, пока render-таймер (33 мс) перерисует экран после emit из потока
    wait_until(lambda: "hello" in w3.edit.toPlainText(), timeout_ms=1500)
    check("terminal window renders streamed bytes into the screen",
          "hello" in w3.edit.toPlainText(), f"text={w3.edit.toPlainText()!r}"[:200])
finally:
    try:
        w3.close()
        app.processEvents()
    except Exception:
        pass
    ST.SSHTerminalThread = _orig_thread_cls

# ════════════════════════════════════════════════════════════
# #3c. Клавиатура: печатные символы/Return/Backspace уходят в канал
# ════════════════════════════════════════════════════════════
sent = []

class _FakeChanThread:
    def send_data(self, b): sent.append(b)
    def stop(self): pass

edit3 = SSHTerminalTextEdit(_FakeChanThread())
for ch in ("h", "é"):
    edit3.keyPressEvent(_key(ch, ord(ch[0])))
edit3.keyPressEvent(_key("\t", Qt.Key_Tab))
edit3.keyPressEvent(_key("\r", Qt.Key_Return))
edit3.keyPressEvent(_key("", Qt.Key_Backspace))
check("key events encode to channel bytes (printable/utf8/tab)",
      sent[:3] == [b"h", "é".encode("utf-8"), b"\t"], f"sent={sent[:3]!r}")
check("Return -> CR, Backspace -> DEL(0x7f)", sent[3:] == [b"\r", b"\x7f"], f"sent={sent[3:]!r}")

# ════════════════════════════════════════════════════════════
# #1. MainWindow._add_server(True) — bool из QAction.triggered не роняет метод
#     и точка сцены всё ещё уважается
# ════════════════════════════════════════════════════════════
print("== _add_server (bug #1) ==")
import ui.main_window as MW

added = []

class _FakeAddDlg:
    def __init__(self, parent=None): pass
    def exec(self): return QDialog.Accepted
    def get_data(self):
        d = ServerData(id=f"add{len(added)}", alias=f"srv{len(added)}", host="10.0.0.1", user="u")
        added.append(d)
        return d

_orig_add_dlg = MW.AddServerDialog
MW.AddServerDialog = _FakeAddDlg
try:
    win = MW.MainWindow()
    win.show(); app.processEvents()

    # (a) ровно то, что шлёт QAction.triggered из тулбара/меню: bool
    try:
        win._add_server(True)
        check("_add_server(True) does not raise", True)
    except AttributeError as e:
        check("_add_server(True) does not raise", False, repr(e))
    check("_add_server(True) created node at viewport center", len(added) == 1 and len(win.scene._nodes) == 1,
          f"added={len(added)}, nodes={list(win.scene._nodes)}")
    if added and win.scene._nodes:
        # Ревью-фикс v0.8.0 (#1): узел центрируется под курсором — оффсеты равны
        # половинам MIN_NODE_WIDTH/MIN_NODE_HEIGHT (90/65), а не старым -70/-55.
        exp = win.view.mapToScene(win.view.viewport().rect().center())
        nd = list(win.scene._nodes.values())[0]
        check("node centered under viewport center (x-90, y-65)",
              abs(nd.data.x - (exp.x() - 90)) < 0.6 and abs(nd.data.y - (exp.y() - 65)) < 0.6,
              f"got ({nd.data.x},{nd.data.y}) want ({exp.x()-90:.1f},{exp.y()-65:.1f})")

    # (b) настоящая точка сцены (путь ПКМ-меню по пустому месту)
    win.scene.clear_all()
    added.clear()
    win._add_server(QPointF(500, 400))
    ok_pos = len(added) == 1 and list(win.scene._nodes.values())[0].data.x == 410 \
             and list(win.scene._nodes.values())[0].data.y == 335
    check("_add_server(QPointF(500,400)) -> node centered at (410,335)", ok_pos)
finally:
    MW.AddServerDialog = _orig_add_dlg

# ════════════════════════════════════════════════════════════
# #2. Контекстное меню MapView: настоящий путь ПКМ → QMenu → trigger()
#     (до фикса замыкания получали checked=True вместо объекта)
# ════════════════════════════════════════════════════════════
print("== map context menu (bug #2) ==")
import graphics.map_view as MVm
from i18n import t as it

captured_menus = []

class _CaptureMenu(QMenu):
    def exec(self, *a, **k):           # Qt6: exec(pos) — перехватываем, не блокируемся
        captured_menus.append(self)
        return 0
    def exec_(self, *a, **k):          # legacy-имя — тот же перехват
        captured_menus.append(self)
        return 0

_orig_menu_cls = MVm.QMenu
MVm.QMenu = _CaptureMenu


def _ctx(view, scene_pos):
    """Синтетический QContextMenuEvent в координатах viewport.

    PySide6 6.11: конструктор (reason, pos: QPoint [, globalPos: QPoint]).
    """
    from PySide6.QtCore import QPoint
    vp = view.mapFromScene(scene_pos)   # Qt6/PySide: -> QPoint
    x, y = int(vp.x()), int(vp.y())
    ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(x, y), QPoint(x + 5, y + 5))
    view.contextMenuEvent(ev)


def _trigger(menu, key):
    for act in menu.actions():
        if act.text() == it(key):
            act.trigger()
            return True
    return False

try:
    win2 = MW.MainWindow()
    win2.show(); app.processEvents()
    view2 = win2.view
    view2.resize(900, 700); app.processEvents()

    # (a) ПКМ по пустому месту → «Добавить сервер» (позиция клика должна дойти)
    added.clear()
    MW.AddServerDialog = _FakeAddDlg
    captured_menus.clear()
    click_scene = QPointF(450, 320)   # точка сцены в пределах viewport
    _ctx(view2, click_scene)
    check("context menu on empty space captured", len(captured_menus) == 1)
    if captured_menus:
        ok_trig = _trigger(captured_menus[-1], "btn.add_server")
        check("empty-space menu has 'add server' action and it triggers", ok_trig,
              f"actions={[a.text() for a in captured_menus[-1].actions()]}")
        check("ctx add-server created node centered under click (450-90, 320-65)",
              len(added) == 1 and list(win2.scene._nodes.values())[0].data.x == 360
              and list(win2.scene._nodes.values())[0].data.y == 255,
              f"nodes={[(n.data.alias, n.data.x, n.data.y) for n in win2.scene._nodes.values()]}")
    MW.AddServerDialog = _orig_add_dlg

    # (b) ПКМ по узлу → «Подключить SSH» — раньше: 'bool' has no setSelected
    ndata = ServerData(id="ctxnode1", alias="N1", host="10.0.0.2", user="u")
    win2.scene.clear_all()
    node2 = win2.scene.add_server(ndata)
    node2.setPos(300, 200)

    ssh_calls = []
    class _FakeSSHDialog:
        def __init__(self, data, parent=None): self._d = data
        def exec(self): ssh_calls.append(self._d); return QDialog.Rejected
    _orig_ssh_dlg = MW.SSHConnectDialog
    MW.SSHConnectDialog = _FakeSSHDialog
    captured_menus.clear()
    try:
        _ctx(view2, node2.sceneBoundingRect().center())
        check("context menu over node captured", len(captured_menus) == 1)
        if captured_menus:
            ok_trig = _trigger(captured_menus[-1], "ctx.ssh_connect")
            check("node menu has 'ssh connect' and it triggers without crash", ok_trig,
                  f"actions={[a.text() for a in captured_menus[-1].actions()]}")
            check("ssh action selected the real node (not bool)",
                  len(ssh_calls) == 1 and win2.scene.get_selected_node() is node2,
                  f"selected={win2.scene.get_selected_node()}")
    except Exception as e:
        check("node menu 'ssh connect' triggers without crash", False, repr(e))
    finally:
        MW.SSHConnectDialog = _orig_ssh_dlg

    # (c) ПКМ по заметке → «Удалить» — раньше n затирался checked=True
    note_id_box = {}
    note2 = win2.scene.add_note("tmp", x=600, y=150)
    note_id_box["id"] = note2.note_id
    captured_menus.clear()
    _ctx(view2, note2.sceneBoundingRect().center())
    if captured_menus:
        ok_trig = _trigger(captured_menus[-1], "ctx.delete_note")
        check("note menu 'delete' triggers and removes the note",
              ok_trig and win2.scene.get_note_by_id(note2.note_id) is None,
              f"notes={[n.note_id for n in win2.scene._notes]}")
    else:
        check("context menu over note captured", False)

    # (d) ПКМ по узлу → «Удалить сервер» — guarded-путь с подтверждением
    from PySide6.QtWidgets import QMessageBox as _QMB
    _orig_question = _QMB.question
    _QMB.question = staticmethod(lambda *a, **k: _QMB.Yes)
    try:
        win2b_node_id = node2.data.id
        captured_menus.clear()
        _ctx(view2, node2.sceneBoundingRect().center())
        if captured_menus:
            ok_trig = _trigger(captured_menus[-1], "ctx.delete_server")
            check("node menu 'delete server' triggers and removes the node",
                  ok_trig and win2b_node_id not in win2.scene._nodes,
                  f"nodes={list(win2.scene._nodes)}")
    except Exception as e:
        check("node menu 'delete server' triggers without crash", False, repr(e))
    finally:
        _QMB.question = _orig_question
finally:
    MVm.QMenu = _orig_menu_cls

# ════════════════════════════════════════════════════════════
# #4. fingerprint(): paramiko>=5 (asbytes -> bytes) и legacy (asbytes -> base64 str)
# ════════════════════════════════════════════════════════════
print("== host key fingerprint (bug #4) ==")
from modules.host_key_policy import fingerprint

import base64 as _b64

def _sha256_fp(blob: bytes) -> str:
    return "SHA256:" + _b64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")


try:
    from paramiko import RSAKey
    rk = RSAKey.generate(2048)
    raw_bytes = rk.asbytes()  # paramiko>=5: сырые wire-байты
    fp_new = fingerprint(rk)
    check("fingerprint works for real key (paramiko>=5, asbytes->bytes)",
          fp_new.startswith("SHA256:") and len(fp_new) > 10, fp_new)
    if isinstance(raw_bytes, bytes):
        check("fingerprint == SHA256 of wire blob (matches ssh-keygen semantics)",
              fp_new == _sha256_fp(raw_bytes), f"{fp_new} vs {_sha256_fp(raw_bytes)}")
except Exception as e:
    check("fingerprint with real paramiko key", False, repr(e))

# legacy-компонента: asbytes() возвращает base64-строку (paramiko<5)
class _LegacyKey:
    def __init__(self, blob): self._blob = blob
    def asbytes(self): return _b64.b64encode(self._blob).decode("ascii")

legacy_blob = bytes(range(200))
fp_leg = fingerprint(_LegacyKey(legacy_blob))
check("fingerprint legacy base64-string path", fp_leg == _sha256_fp(legacy_blob), fp_leg)

# только get_base64() (asbytes отсутствует/падает)
class _B64Only:
    def get_base64(self): return _b64.b64encode(legacy_blob).decode("ascii")
check("fingerprint falls back to get_base64()", fingerprint(_B64Only()) == _sha256_fp(legacy_blob))

# совсем без данных — честный fallback-текст, а не ложный SHA256
class _DeadKey: pass
check("fingerprint '<unavailable>' only when nothing usable",
      fingerprint(_DeadKey()) == "<fingerprint unavailable>")

# ════════════════════════════════════════════════════════════
finish()
