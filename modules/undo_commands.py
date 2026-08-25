"""v0.8.3: Undo/Redo — команды QUndoCommand для операций карты.

Границы undo: изменения статусов узлов (v0.7.1), координаты при загрузке
проекта и результаты автосбора (v0.9) в стек НЕ входят. Перемещение/resize
групп ВХОДЯТ (CmdMoveGroup/CmdResizeGroup ниже; AUDIT v0.8.3 #6) — как и
перемещение узлов (CmdMoveNode). Правка текста заметки — CmdEditTextNote;
перемещение/resize самой StickyNote — вне undo.

Контракт всех команд: сцена изменяется ТОЛЬКО внутри redo()/undo() —
QUndoStack.push() сам вызывает redo(), поэтому точки входа в MainWindow
не выполняют операцию вручную, а только собирают команду и пушат её.

После каждого применения команда дергает win._post_undo_refresh() —
сайдбар/счётчики/план проверок статусов синхронизируются с фактическим
состоянием сцены независимо от того, пришло изменение от пользователя,
undo или redo.

LIFO-инвариант: Qt отменяет команды строго в обратном порядке, поэтому
удаление узла (захватившего свои стрелки) не может быть отменено раньше
отмены операций с этими стрелками — ссылки на объекты остаются валидными.
"""
import copy
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoCommand


class _MapCommand(QUndoCommand):
    """База: ссылка на окно (для refresh-хука и i18n)."""

    def __init__(self, win, text: str = ""):
        super().__init__(text)
        self._win = win

    def _refresh(self):
        """Синхронизировать UI окна с состоянием сцены после применения."""
        try:
            self._win._post_undo_refresh()
        except Exception:  # noqa: BLE001 — refresh косметика, не роняем undo
            pass


# ── MoveNode: перемещение узла (merge перетаскивания одним жестом) ──

class CmdMoveNode(_MapCommand):
    """Перемещение одного узла. Слияние: цепочка команд того же узла
    (жест мыши порождает ровно одну команду на release, но программные
    setPos-цепочки склеиваются) схлопывается в первую команду."""

    MOVE_ID = 1  # id() > 0 включает mergeWith у Qt

    def __init__(self, win, node, old_pos: QPointF, new_pos: QPointF):
        super().__init__(win, "Move node")
        self._node = node
        self._old = QPointF(old_pos)
        self._new = QPointF(new_pos)

    def id(self) -> int:  # noqa: N802 — Qt API
        return self.MOVE_ID

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, CmdMoveNode) or other._node is not self._node:
            return False
        # Поглощаем последующую позицию — жест целиком отменяется одним undo
        self._new = QPointF(other._new)
        return True

    def _apply(self, pos: QPointF):
        try:
            if self._node.scene() is not None:
                self._node.setPos(pos)  # itemChange синхронизирует data/стрелки/группы
        except RuntimeError:
            pass  # Qt teardown — item уничтожен, применять некуда

    def redo(self):
        self._apply(self._new)

    def undo(self):
        self._apply(self._old)


# ── MoveNodes: перемещение нескольких выделенных узлов (v0.9.3) ──

class CmdMoveNodes(_MapCommand):
    """v0.9.3: перемещение НЕСКОЛЬКИХ выделенных узлов одним жестом.

    Один жест группового drag'а → одна undo-команда (а не N отдельных
    CmdMoveNode). moves — список (node, old_pos, new_pos); узлы хранятся
    ссылками, позиции — копиями QPointF. Слияния нет: жест порождает ровно
    одну команду.
    """

    def __init__(self, win, moves):
        super().__init__(win, "Move servers")
        self._moves = [(node, QPointF(old), QPointF(new)) for node, old, new in moves]

    def _apply(self, use_old: bool):
        for node, old, new in self._moves:
            try:
                if node.scene() is not None:
                    node.setPos(old if use_old else new)
            except RuntimeError:
                pass  # Qt teardown — item уничтожен

    def redo(self):
        self._apply(False)

    def undo(self):
        self._apply(True)


# ── MoveGroup: перемещение группы (merge перетаскивания одним жестом) ──
# AUDIT v0.8.3 (#6): раньше перемещение/resize/переименование групп шли только
# в dirty-маркер — Ctrl+Z после сдвига группы ничего не откатывал.

class CmdMoveGroup(_MapCommand):
    """Перемещение группы (+ её членов следуют автоматически). Слияние цепочки
    пошаговых сдвигов одного жеста в первую команду (паттерн CmdMoveNode)."""

    MOVE_GROUP_ID = 2  # уникальный id ≠ CmdMoveNode.MOVE_ID

    def __init__(self, win, group, old_pos: QPointF, new_pos: QPointF):
        super().__init__(win, "Move group")
        self._group = group
        self._old = QPointF(old_pos)
        self._new = QPointF(new_pos)

    def id(self) -> int:  # noqa: N802 — Qt API
        return self.MOVE_GROUP_ID

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, CmdMoveGroup) or other._group is not self._group:
            return False
        self._new = QPointF(other._new)
        return True

    def _apply(self, pos: QPointF):
        try:
            grp = self._group
            if grp.scene() is None:
                return
            delta = QPointF(pos.x() - grp.pos().x(), pos.y() - grp.pos().y())
            # _apply_move двигает группу И членов + resync; itemChange-путь
            # (_applying_move=False) делает то же для программных setPos.
            if hasattr(grp, "_apply_move"):
                grp._apply_move(delta)
            else:
                grp.setPos(pos)
        except RuntimeError:
            pass  # Qt teardown — item уничтожен

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()


# ── ResizeGroup: изменение размера группы ───────────────────────

class CmdResizeGroup(_MapCommand):
    """Resize группы за угол. Члены репозиционируются set_group_size сама."""

    def __init__(self, win, group, old_size, new_size):
        super().__init__(win, "Resize group")
        self._group = group
        self._old = tuple(old_size)   # (w, h)
        self._new = tuple(new_size)

    def _apply(self, size):
        try:
            if self._group.scene() is not None:
                self._group.set_group_size(size[0], size[1])
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()


# ── EditGroupName: переименование группы ────────────────────────

class CmdEditGroupName(_MapCommand):
    """Правка заголовка группы (двойной клик / контекстное меню)."""

    def __init__(self, win, group, old_name: str, new_name: str):
        super().__init__(win, "Rename group")
        self._group = group
        self._old = old_name
        self._new = new_name

    def _apply(self, name: str):
        try:
            if self._group.scene() is not None:
                self._group.set_title(name)
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()


# ── AddRemoveNode: создание/удаление сервера (с его стрелками) ──

class CmdAddRemoveNode(_MapCommand):
    """Добавление (mode='add') или удаление (mode='remove') узла.

    При удалении захватываются все входящие/исходящие стрелки — undo
    восстанавливает узел вместе с ними. Данные узла хранятся одним объектом:
    повторный redo после undo создаёт узел с тем же id, что сохраняет
    ссылки других команд (стрелки, созданные после добавления).
    """

    def __init__(self, win, scene, data, mode: str = "add",
                 arrows: Optional[List[Tuple[str, str, str, str]]] = None):
        super().__init__(win, "Add server" if mode == "add" else "Delete server")
        self._scene = scene
        self._data = data          # единый ServerData (id стабилен между undo/redo)
        self._mode = mode
        self._arrows = list(arrows or [])  # (source_id, target_id, label, ctype)
        # v0.9.4-fix (орфанные пароли): при удалении узла пароль удаляется из
        # keyring; чтобы Ctrl+Z мог его вернуть, заранее читаем его в память.
        self._stashed_password: Optional[str] = None
        if mode == "remove":
            try:
                from services.credential_manager import get_credential_manager
                self._stashed_password = get_credential_manager().load_password(data.id)
            except Exception:
                self._stashed_password = None

    def _delete_keyring_password(self):
        try:
            from services.credential_manager import get_credential_manager
            get_credential_manager().delete_password(self._data.id)
        except Exception:
            pass

    def _restore_keyring_password(self):
        if self._stashed_password:
            try:
                from services.credential_manager import get_credential_manager
                get_credential_manager().save_password(self._data.id, self._stashed_password)
            except Exception:
                pass

    def redo(self):
        if self._mode == "add":
            self._scene.add_server(self._data)
        else:
            self._scene.remove_server(self._data.id)
            self._delete_keyring_password()
        self._refresh()

    def undo(self):
        if self._mode == "add":
            self._scene.remove_server(self._data.id)
            self._delete_keyring_password()
        else:
            self._scene.add_server(self._data)
            self._restore_keyring_password()
            for src, tgt, lbl, ctype in self._arrows:
                if (self._scene.has_node(src) and self._scene.has_node(tgt)
                        and not self._scene.has_connection(src, tgt)):
                    self._scene.add_connection(src, tgt, lbl, ctype)
        self._refresh()


# ── AddRemoveConnection: создание/удаление связи ────────────────

class CmdAddRemoveConnection(_MapCommand):
    def __init__(self, win, scene, source_id: str, target_id: str,
                 label: str, ctype: str, mode: str = "add"):
        super().__init__(win, "Add connection" if mode == "add" else "Delete connection")
        self._scene = scene
        self._src = source_id
        self._tgt = target_id
        self._label = label
        self._ctype = ctype
        self._mode = mode

    def _find_arrow(self):
        for a in self._scene.arrows():
            if (a.source.data.id == self._src and a.target.data.id == self._tgt):
                return a
        return None

    def redo(self):
        if self._mode == "add":
            self._scene.add_connection(self._src, self._tgt, self._label, self._ctype)
        else:
            arrow = self._find_arrow()
            if arrow is not None:
                self._scene.remove_connection(arrow)
        self._refresh()

    def undo(self):
        if self._mode == "add":
            arrow = self._find_arrow()
            if arrow is not None:
                self._scene.remove_connection(arrow)
        else:
            self._scene.add_connection(self._src, self._tgt, self._label, self._ctype)
        self._refresh()


# ── ConnectSelected: связи между всеми выделенными узлами (v0.9.3) ──

class CmdConnectSelected(_MapCommand):
    """v0.9.3: создать полный граф связей между выделенными узлами одной
    операцией (пары (source_id, target_id) уже отфильтрованы точкой входа).
    Undo удаляет все созданные стрелки, redo восстанавливает их."""

    def __init__(self, win, scene, pairs):
        super().__init__(win, "Connect servers")
        self._scene = scene
        self._pairs = list(pairs)

    def _apply(self, present: bool):
        for src, tgt in self._pairs:
            has = self._scene.has_connection(src, tgt)
            if present and not has:
                self._scene.add_connection(src, tgt)
            elif not present and has:
                for a in self._scene.arrows():
                    if a.source.data.id == src and a.target.data.id == tgt:
                        self._scene.remove_connection(a)
                        break

    def redo(self):
        self._apply(True)
        self._refresh()

    def undo(self):
        self._apply(False)
        self._refresh()


# ── AddRemoveNote: создание/удаление заметки ────────────────────

class CmdAddRemoveNote(_MapCommand):
    def __init__(self, win, scene, raw: dict, mode: str = "add"):
        super().__init__(win, "Add note" if mode == "add" else "Delete note")
        self._scene = scene
        self._raw = dict(raw)   # {text,x,y,width,height[,id]}
        self._mode = mode
        self._note_id = raw.get("id")

    def redo(self):
        # Идемпотентность: окно уже создало заметку перед push — не дублируем
        if self._mode == "add" and self._scene.get_note_by_id(self._note_id) is not None:
            self._refresh()
            return
        if self._mode == "add":
            note = self._scene.add_note(
                text=str(self._raw.get("text") or ""),
                x=float(self._raw.get("x") or 0.0),
                y=float(self._raw.get("y") or 0.0),
                width=float(self._raw.get("width") or 240.0),
                height=float(self._raw.get("height") or 160.0),
                note_id=self._note_id,
            )
            self._note_id = note.note_id  # id мог сгенерироваться при первом redo
            try:
                self._win._attach_note(note)  # сигналы + committed-текст
            except Exception:  # noqa: BLE001
                pass
        else:
            self._scene.remove_note(self._note_id)
        self._refresh()

    def undo(self):
        if self._mode == "add":
            self._scene.remove_note(self._note_id)
        else:
            note = self._scene.add_note(
                text=str(self._raw.get("text") or ""),
                x=float(self._raw.get("x") or 0.0),
                y=float(self._raw.get("y") or 0.0),
                width=float(self._raw.get("width") or 240.0),
                height=float(self._raw.get("height") or 160.0),
                note_id=self._note_id,
            )
            self._note_id = note.note_id
            try:
                self._win._attach_note(note)
            except Exception:  # noqa: BLE001
                pass
        self._refresh()


# ── EditTextNote: правка текста заметки (дебаунс на стороне окна) ──

class CmdEditTextNote(_MapCommand):
    def __init__(self, win, note, old_text: str, new_text: str):
        super().__init__(win, "Edit note")
        self._note = note
        self._note_id = getattr(note, "note_id", None)
        self._old = old_text
        self._new = new_text

    def _apply(self, value: str):
        try:
            if self._note.scene() is not None:
                self._note.set_text(value)
            committed = getattr(self._win, "_note_committed", None)
            if committed is not None and self._note_id:
                committed[self._note_id] = value
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)

    def undo(self):
        self._apply(self._old)


# ── EditConnection: правка метки/типа связи ─────────────────────

class CmdEditConnection(_MapCommand):
    def __init__(self, win, arrow, old_label: str, old_type: str,
                 new_label: str, new_type: str):
        super().__init__(win, "Edit connection")
        self._arrow = arrow
        self._old = (old_label, old_type)
        self._new = (new_label, new_type)

    def _apply(self, label: str, ctype: str):
        try:
            if self._arrow.scene() is None:
                return
            if label != self._arrow.label_text:
                self._arrow.set_label(label)
            if ctype != self._arrow.connection_type:
                self._arrow.set_type(ctype)
        except RuntimeError:
            pass

    def redo(self):
        self._apply(*self._new)

    def undo(self):
        self._apply(*self._old)


# ── EditNodeData: правка данных сервера через диалог свойств ────

class CmdEditNodeData(_MapCommand):
    def __init__(self, win, node, old_data, new_data):
        super().__init__(win, "Edit server")
        self._node = node
        self._old = old_data
        self._new = new_data

    def _apply(self, data):
        try:
            if self._node.scene() is None:
                return
            self._node.data = data
            self._node.update_appearance()
            # v0.9.4: теги могли измениться — полоска пересобирается (update_appearance
            # трогает её только при смене геометрии)
            self._node.refresh_tags()
            # host/порт могли измениться — статус больше неактуален (паттерн диалога)
            self._node.reset_status()
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()
