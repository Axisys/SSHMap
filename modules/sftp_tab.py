# -*- coding: utf-8 -*-
"""The Files tab of a terminal session — a CONTAINER of 1–2 PANES over ONE SFTP worker.

`SftpTab` owns the single worker binding, the session's follow switch, the two panes and the ACTIVE
pane; `_SftpPane` owns one listing (its address bar with the completer, its buttons, its tree, its
viewer and its task bookkeeping) and binds the SHARED worker's signals, answering only the task ids IT
queued — so the panes navigate independently, without a second worker or a second channel. The page
talks to the container (`page.sftp_tab`); a shipped attribute read resolves on the ACTIVE pane.

The pane-scoped keys (`F3`/`F5`/`F6`/`F7`/`F8` as `Qt.WidgetWithChildrenShortcut` actions ON the pane,
plus `Tab`/`Shift+Tab` and the walk keys of `_on_pane_key()`) leave the canvas's claim on the F-keys
intact; the Commander spends ONE button row (the first pane) and the second pane's line on the key
hints, and a preview opens IN THE OTHER PANE. Contract — `SFTP_PANES.md`; mechanism — §38, §59-§63."""
import json
import os
import posixpath
from datetime import datetime

from PySide6.QtCore import (QEvent, QItemSelectionModel, QMimeData, QSize, QStringListModel, Qt,
                            Signal)
from PySide6.QtGui import (QAction, QColor, QDrag, QFontDatabase, QIcon,
                           QKeySequence, QPainter, QPixmap)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QCompleter, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # v1.2.5: central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None

try:  # v1.5rc4: the ONE visible-focus indicator (the ACTIVE pane of v1.7rc1)
    from ..ui import focus_ring
except ImportError:
    try:
        from ui import focus_ring
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        focus_ring = None

try:  # v1.3.1: the viewer's shared constants (limit + task_error codes)
    from .sftp_worker import (KIND_COPY, KIND_DELETE, KIND_MKDIR, KIND_MOVE,
                              KIND_NORMALIZE, KIND_READ, KIND_RENAME,
                              MAX_READ_BYTES, MAX_TREE_ENTRIES, MOVE_ERROR_REFUSED,
                              OP_KINDS, PARTIAL_CODE, READ_ERROR_BINARY,
                              READ_ERROR_TOO_LARGE, TREE_ERROR_TOO_BIG,
                              classify_extension, parse_task_payload)
except ImportError:
    from sftp_worker import (KIND_COPY, KIND_DELETE, KIND_MKDIR, KIND_MOVE,
                             KIND_NORMALIZE, KIND_READ, KIND_RENAME,
                             MAX_READ_BYTES, MAX_TREE_ENTRIES, MOVE_ERROR_REFUSED,
                             OP_KINDS, PARTIAL_CODE, READ_ERROR_BINARY,
                             READ_ERROR_TOO_LARGE, TREE_ERROR_TOO_BIG,
                             classify_extension, parse_task_payload)

try:  # v1.4.7 (ROADMAP task 4): detection + tokenizers + the ONE highlighter
    from . import syntax_highlight as syntax
except ImportError:
    import syntax_highlight as syntax

try:  # v1.7.3 (ROADMAP v1.7.3, task 1): the cross-session relay and its dialog
    from . import sftp_send as send
except ImportError:  # flat launch from the project root
    import sftp_send as send

try:  # v1.7.3 (ROADMAP v1.7.3, task 1): the parent-chain host hook of the Send-to provider
    from .terminal_split import find_host_hook
except ImportError:  # flat launch from the project root
    from terminal_split import find_host_hook


# ── the Files Commander — the pane model ───────────
# The state of the two-pane view lives in `~/.sshmap/config.json`, exactly like the terminal SPLIT's
# (`ui_terminal_split` / `ui_terminal_split_ratio`): ONE bool and ONE float, merged into the window's
# geometry write on close. The ratio is a FRACTION of the width, so a window resize keeps the proportion,
# and a foreign/broken value falls back to the default instead of squeezing a pane into unusability.
COMMANDER_CONFIG_BOOL = "ui_sftp_commander"          # bool — the mode was on at the last close
COMMANDER_CONFIG_RATIO = "ui_sftp_commander_ratio"   # float — the FIRST pane's share of the width
COMMANDER_RATIO_DEFAULT = 0.5
COMMANDER_RATIO_MIN = 0.2
COMMANDER_RATIO_MAX = 0.8

#: The narrowest a pane may be dragged, in pixels — installed as `setMinimumWidth`
#: while the mode is on (Qt gotcha #13 forbids `setMaximum*` on a splitter member) and
#: dropped again when it goes off, so the single-pane look costs no floor at all.
COMMANDER_MIN_PANE_PX = 200

#: The pane-scoped key map (SFTP_PANES.md "The key map"). ONE `QAction` per row, owned
#: by the PANE with `Qt.WidgetWithChildrenShortcut`: the key fires while the keyboard is
#: inside THAT pane and nowhere else, so the terminal canvas keeps its own claim on the
#: F-keys and the window's action registry stays the home of the GLOBAL actions (§4.9).
#: `F4` is deliberately absent — the application has no remote editing at all.
PANE_SHORTCUTS = (
    ("F3", "_cmd_view"),
    ("F5", "_cmd_copy"),
    ("F6", "_cmd_move_rename"),
    ("F7", "_cmd_mkdir"),
    ("F8", "_cmd_delete"),
)

#: The ROW the SECOND pane shows where the first one keeps its buttons. In the two-pane view the
#: shipped button row belongs to the FIRST pane (the mc/far look: the commander has ONE button row and
#: the panes are nothing but listings), so the right pane spends that line on the key HINTS of the keys
#: it really answers — the classic commander's bottom line. The pairs travel with `PANE_SHORTCUTS` (the
#: same keys, in the same order) and the two that are not F-keys close the row. A tuple, never a table.
PANE_HINTS = (
    ("F3", "sftp.hint.view"),
    ("F5", "sftp.hint.copy"),
    ("F6", "sftp.hint.move"),
    ("F7", "sftp.hint.mkdir"),
    ("F8", "sftp.hint.delete"),
    ("Tab", "sftp.cmd.switch_pane"),
    ("Ins", "sftp.hint.mark"),
    ("Enter", "sftp.hint.open"),
)

#: The hint row's own layout (v1.7rc3): the separator between two entries and the elide
#: mode of the label — the row is ONE line and never grows with the pane's width or with
#: the number of entries (a wrapped second line would move the listing under the cursor).
HINT_SEPARATOR = "  ·  "

#: The floor of the shared row of the pane (v1.7rc3), in pixels: the button row lives inside ONE
#: wrapper widget (so the two-pane view can hide it as a unit) and a bare `QWidget` would report
#: its layout's WHOLE minimum — a row of five buttons — as the pane's, which raises the terminal
#: WINDOW's own floor. The wrapper is therefore allowed to shrink and CLIP the row, exactly as the
#: row behaved before the wrapper existed.
BUTTONS_BAR_MIN_WIDTH = 0

#: The worker signals a pane binds (the container owns the worker, the pane its slots).
WORKER_SIGNAL_NAMES = ("list_ready", "task_started", "task_done", "task_error",
                       "task_cancelled", "read_ready", "normalize_ready")

#: v1.7.3: the per-server directory memory. ONE key of `~/.sshmap/config.json` holds a map
#: `{server key: directory}` (`history_key()` is the key), written by the window's close and read
#: when a pane is built; the map outlives the servers it names, so it is BOUNDED and evicted
#: oldest-first. A restored path is a HINT: a directory the server refuses falls back to the
#: shipped opening rule with ONE status line.
DIRS_CONFIG = "ui_sftp_dirs"
MAX_REMEMBERED_DIRS = 32

#: v1.7.3: the reader's WORD WRAP — ONE global boolean (`terminal_wheel`'s validation rule): the
#: extension is a HINT, the value is a real JSON bool or the default.
VIEWER_WRAP_CONFIG = "ui_viewer_wrap"

#: v1.7.3: the drag payload of a row that started INSIDE a Files pane. The remote path alone
#: cannot say WHICH pane (two servers show the same path), so the private type carries the session
#: key, the pane's identity and the path while `text/plain` keeps the plain path for every foreign
#: consumer (a terminal, an editor, a chat window).
PANE_DRAG_MIME = "application/x-sshmap-pane-row"


def load_remembered_dirs() -> dict:
    """The per-server directory map from `~/.sshmap/config.json` ({} — nothing to restore).

    FOREIGN content answers `{}` rather than a guess (a string where a map is expected, an entry
    whose path is not absolute): a broken config must never navigate a pane anywhere. Never raises.
    """
    try:
        from i18n import load_config
    except Exception:  # noqa: BLE001 — a build without i18n keeps no memory
        return {}
    try:
        raw = (load_config() or {}).get(DIRS_CONFIG)
    except Exception:  # noqa: BLE001 — a broken config store must not break a pane
        return {}
    return sanitize_dirs(raw)


def sanitize_dirs(raw) -> dict:
    """The usable entries of a stored map: a string key and an ABSOLUTE path, or nothing."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, path in raw.items():
        name, value = str(key or ""), str(path or "")
        if name and value.startswith("/"):
            out[name] = value
    return out


def remember_dir(mapping, key, path, limit: int = MAX_REMEMBERED_DIRS) -> dict:
    """Move ONE `{server key: directory}` entry to the END, evicting the OLDEST over the cap (PURE).

    Insertion order IS the age, so the eviction needs no timestamp and the map stays a plain JSON
    object; a blank key or a relative path changes NOTHING (a remote directory is absolute).
    """
    out = dict(mapping or {})
    name, value = str(key or ""), str(path or "")
    if name and value.startswith("/"):
        out.pop(name, None)
        out[name] = value
    while len(out) > max(1, int(limit)):
        out.pop(next(iter(out)))
    return out


def remembered_dir_for(mapping, key) -> str:
    """The directory remembered for ONE server key ("" — never visited / no memory)."""
    try:
        return str((mapping or {}).get(str(key or "")) or "")
    except Exception:  # noqa: BLE001 — a foreign mapping is simply "no memory"
        return ""


def resolve_viewer_wrap(cfg: dict = None) -> bool:
    """The reader's word wrap as a PURE value (v1.7.3).

    Only a real JSON `true`/`false` counts; anything else — a string `"true"`, a number, a missing
    key, an unreadable config — answers the DEFAULT (`False`: the shipped no-wrap look).
    """
    if not isinstance(cfg, dict):
        try:
            from i18n import load_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the default
            return False
        try:
            cfg = load_config() or {}
        except Exception:  # noqa: BLE001 — a broken config store keeps the default
            cfg = {}
    value = cfg.get(VIEWER_WRAP_CONFIG) if isinstance(cfg, dict) else None
    return value if isinstance(value, bool) else False


def save_viewer_wrap(on) -> bool:
    """Write the ONE word-wrap key (merge-write; False — the config could not be written)."""
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — a build without i18n cannot remember it
        return False
    try:
        return bool(save_config({VIEWER_WRAP_CONFIG: bool(on)}))
    except Exception:  # noqa: BLE001 — a write failure must not break the reader
        return False


def pane_payload(mime_data):
    """The `{session, pane, path}` payload of a drag that started inside a pane (None — foreign).

    A malformed payload (not JSON, not an object, no path) is a FOREIGN drag: the pane then behaves
    exactly as it did before the private type existed.
    """
    if mime_data is None or not mime_data.hasFormat(PANE_DRAG_MIME):
        return None
    try:
        data = json.loads(bytes(mime_data.data(PANE_DRAG_MIME)).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    path = str(data.get("path") or "")
    if not path:
        return None
    return {"session": str(data.get("session") or ""), "pane": data.get("pane"), "path": path}


def load_commander_settings():
    """v1.7rc1: the Files Commander state/ratio from ~/.sshmap/config.json.

    The `load_split_settings()` shape (§4.3): every key is optional, a foreign type (a
    string "true", a bool where a float is expected, a non-finite number) answers the
    DEFAULT — a broken config must never open a second pane or squeeze the two into
    unusability. Never raises. Returns `{"commander": bool, "ratio": float}`.
    """
    defaults = {"commander": False, "ratio": COMMANDER_RATIO_DEFAULT}
    try:
        from i18n import load_config
    except Exception:  # noqa: BLE001 — a build without i18n keeps the defaults
        return dict(defaults)
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — a broken config store must not break the tab
        return dict(defaults)

    v = cfg.get(COMMANDER_CONFIG_BOOL)
    if isinstance(v, bool):
        defaults["commander"] = v

    v = cfg.get(COMMANDER_CONFIG_RATIO)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            ratio = float(v)
        except (TypeError, ValueError):
            ratio = COMMANDER_RATIO_DEFAULT
        if ratio == ratio and ratio not in (float("inf"), float("-inf")):  # not NaN/inf
            defaults["ratio"] = max(COMMANDER_RATIO_MIN, min(COMMANDER_RATIO_MAX, ratio))
    return defaults


def _apply_status_style(widget, key: str) -> None:
    """v1.4.3 (ROADMAP task 4): apply a muted status-label style from the registry.

    Falls back to the pre-v1.4.3 inline string when the Qt theme module is not
    importable (a flat run outside the project tree), so a status label is styled
    either way. Never raises: a missing registry key yields an empty stylesheet.
    """
    if theme_qss is not None:
        widget.setStyleSheet(theme_qss.style(key))
    else:
        widget.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 2px 0;")


def format_size(n) -> str:
    """Human-readable size: 0 → "0 B", 1536 → "1.5 KB" (no locales)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n < 0:
        return "?"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def format_mtime(ts) -> str:
    """Local mtime time "%Y-%m-%d %H:%M"; broken/zero → ""."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def decode_text(data: bytes):
    """v1.3.1 (ROADMAP task 3): bytes → (text, encoding).

    UTF-8 (BOM-aware — "utf-8-sig" strips an UTF-8 BOM) first; on a decode
    failure the Latin-1 fallback, which never fails and always yields a string
    (mojibake instead of an exception — the header carries the encoding note).
    """
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), "latin-1"


def preview_block_reason(path: str, size, facts=None) -> str:
    """v1.3.1.1: will the viewer refuse this file? "" (no) | "binary" | "too_large".

    The order of the answers is the point of this function — from the certain to
    the guessed:

      1. `facts` — the results of REAL read attempts of this session (path →
         reason): the worker is the only one who sees the content, so its verdict
         wins. A `.txt` with a null byte looks like text by name and is refused by
         the worker — the row is marked only after the attempt, and from then on
         the mark is the truth;
      2. the SIZE from the listing (always known, never a guess): over
         MAX_READ_BYTES the task is refused before the file is opened;
      3. the extension (a GUESS — the null-byte screen can still refuse the file,
         and a file with an unknown/absent extension usually reads fine).

    A broken/absent size is treated as unknown (0) — it never marks a row.
    """
    if facts:
        known = facts.get(path)
        if known:
            return known
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        size = 0
    if size > MAX_READ_BYTES:
        return READ_ERROR_TOO_LARGE
    if classify_extension(path) == "binary":
        return READ_ERROR_BINARY
    return ""


def ask_conflict(parent, name: str, target: str, remaining: int = 0, facts: str = ""):
    """v1.3.3.2 (ROADMAP task 2): the overwrite question for ONE item of a batch.

    Returns `(action, apply_all)`, where action is one of

      * `"overwrite"` — replace the existing destination;
      * `"skip"` — leave the destination alone and go on with the batch;
      * `"rename"` — ask for another name (the caller prompts, then uploads /
        downloads under it) — `apply_all` is never set for it: a batch rename needs
        a name per file;
      * a cancelled dialog (Esc / the window's X) is reported as `"skip"`.

    `remaining` is the number of conflicts still to come in this batch — "Apply to
    all" is offered only when there is anything left to apply it to.

    `facts` is the ONE optional line the cross-session send adds (v1.7.3): both sides'
    size and date, rendered as the message box's informative text when it is non-empty.

    The QMessageBox is taken as a MODULE ATTRIBUTE at call time
    (`STAB.QMessageBox = <fake>` is the test seam — the command-library pattern);
    the pane's `_ask_conflict()` is the caller, so a test can also replace the whole
    decision.
    """
    box = QMessageBox(parent)   # a module attribute — the monkeypatch seam
    box.setWindowTitle(_t("sftp.conflict.title"))
    try:
        box.setIcon(QMessageBox.Icon.Question)
    except Exception:   # noqa: BLE001 — an exotic Qt build without the enum
        pass
    box.setText(_t("sftp.conflict.message", name=name, target=target))
    if facts:
        try:
            box.setInformativeText(str(facts))
        except Exception:   # noqa: BLE001 — a build without the setter keeps the question
            pass
    btn_over = box.addButton(_t("sftp.conflict.overwrite"),
                             QMessageBox.ButtonRole.AcceptRole)
    box.addButton(_t("sftp.conflict.skip"),
                  QMessageBox.ButtonRole.RejectRole)
    btn_rename = box.addButton(_t("sftp.conflict.rename"),
                               QMessageBox.ButtonRole.ActionRole)
    check = QCheckBox(_t("sftp.conflict.apply_all"))
    check.setEnabled(int(remaining or 0) > 0)
    box.setCheckBox(check)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_over:
        action = "overwrite"
    elif clicked is btn_rename:
        action = "rename"
    else:
        action = "skip"        # Skip, or a cancelled dialog (clickedButton() is None)
    apply_all = bool(check.isChecked()) and action in ("overwrite", "skip")
    return action, apply_all


def local_files(mime_data) -> list:
    """Existing local files from the dragged URLs. Directories, deleted/
    nonexistent paths, and non-file data — are skipped.

    A MODULE function (v1.7rc1): the drag payload is a property of a PANE and the
    container keeps the same name as a `staticmethod` because the shipped suite reads
    it off the CLASS (`SftpTab._local_files(mime)`).
    """
    out = []
    if mime_data is None or not mime_data.hasUrls():
        return out
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if os.path.isfile(path):
            out.append(path)
    return out


class _SftpTree(QTreeWidget):
    """The listing tree of a PANE (v1.3.3.2, ROADMAP task 5): drag-OUT.

    A row can be dragged into a terminal, an editor or a chat window: the drag
    payload is the REMOTE PATH of the row as `text/plain` (the file itself is not
    transferred). A SUBCLASS, because `startDrag()` is a C++ slot — runtime
    monkey-patching is forbidden (Qt gotcha #7).

    `drag_mime(item)` builds the payload on its own, which is the seam the tests
    read (a real drag needs an event loop and a drop target).

    v1.7rc1: the tree also REPORTS the keyboard focus (`focus_in`), which is what makes
    a pane become the ACTIVE pane of the container — the ring is drawn on the tree, so
    a click in a pane has to move it.

    v1.7rc3: the tree hands the KEYS it does not own to the pane (`pane_key`), so the walk of
    the two-pane view (`Tab`/`Shift+Tab`, `Enter`, `Insert`/`Space`, `Left`) is decided in ONE
    place (`_SftpPane._on_pane_key`) whether the event comes from the tree or from the pane's
    `eventFilter`. The tree's own navigation (the arrows, `Home`/`End`, type-ahead, the
    multi-selection modifiers) stays Qt's.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.focus_in = None   # a zero-argument callable — set by the owning pane
        self.pane_key = None   # a one-argument callable (the key event) — set by the pane
        self.pane = None       # v1.7.3: the pane this tree lists (the drag payload's identity)

    def keyPressEvent(self, event):
        """Hand the key to the pane first (v1.7rc3); False — Qt's own tree behaviour."""
        hook = self.pane_key
        if hook is not None:
            try:
                if hook(event):
                    return
            except RuntimeError:
                pass  # Qt teardown — the owner is already gone
        super().keyPressEvent(event)

    def event(self, event):
        """Catch `Tab`/`Shift+Tab` BEFORE Qt's focus walk consumes them (v1.7rc3).

        A shown `QTreeWidget` never hands `Tab` to `keyPressEvent()`: Qt's own focus framework
        answers the key first, so the mc/far pane toggle has to be intercepted one level higher,
        in `event()` — the SAME seam the terminal canvas uses for its claimed keys
        (`QEvent.ShortcutOverride` / `_owns_shortcut()`, §4.3). The pane's hook answers False for
        everything that is not part of the walk, so `Tab` in a SINGLE-pane tab still moves the
        focus the ordinary way.
        """
        hook = self.pane_key
        if hook is not None and event.type() in (QEvent.Type.KeyPress,
                                                 QEvent.Type.ShortcutOverride):
            try:
                key = int(event.key())
            except (AttributeError, TypeError, ValueError):
                key = -1
            if key in (int(Qt.Key.Key_Tab), int(Qt.Key.Key_Backtab)):
                try:
                    if hook(event):
                        event.accept()
                        return True
                except RuntimeError:
                    pass  # Qt teardown — the owner is already gone
        return super().event(event)

    def startDrag(self, supported_actions):
        mime = self.drag_mime(self.currentItem())
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def drag_mime(self, item):
        """The drag payload of a row: the remote path as text/plain, plus the PANE identity.

        None — nothing to drag (no row / a row without a path). v1.7.3: the private
        `PANE_DRAG_MIME` carries `{session, pane, path}` so a drop INSIDE a pane can tell which
        pane the row came from (two servers can show the same path) and refuse a foreign session —
        while `text/plain` keeps the plain path for every foreign target.
        """
        if item is None:
            return None
        path = item.data(0, _SftpPane.PATH_ROLE)
        if not path:
            return None
        mime = QMimeData()
        mime.setText(str(path))
        pane = self.pane
        if pane is not None:
            payload = {"session": pane.session_key(), "pane": id(pane), "path": str(path)}
            mime.setData(PANE_DRAG_MIME, json.dumps(payload).encode("utf-8"))
        return mime

    def focusInEvent(self, event):
        """v1.7rc1: the tree took the keyboard — tell the pane (the ACTIVE pane rule)."""
        super().focusInEvent(event)
        hook = self.focus_in
        if hook is not None:
            try:
                hook()
            except RuntimeError:
                pass  # Qt teardown — the owner is already gone


class _ButtonRow(QWidget):
    """The row of the pane's buttons as ONE widget (v1.7rc3).

    The two-pane view needs the row as a unit: the FIRST pane keeps it and the SECOND one hides it
    and shows the key hints in the same line. A bare `QWidget` would report its LAYOUT's whole
    minimum size — a row of five buttons — and that number travels up into the terminal window's own
    floor, so a narrow window that would clip the row refuses to shrink instead. The row is
    therefore allowed to shrink and clip, exactly as it behaved while it was a plain layout of the
    pane (`BUTTONS_BAR_MIN_WIDTH` is the declared floor, and the HEIGHT keeps the layout's hint so
    the hint row can borrow it).
    """

    def minimumSizeHint(self):  # noqa: N802 — Qt's own spelling
        try:
            height = self.layout().minimumSize().height() if self.layout() is not None else 0
        except RuntimeError:
            height = 0
        return QSize(BUTTONS_BAR_MIN_WIDTH, height)


class _SftpPane(QWidget):
    """v1.7rc1 (ROADMAP v1.7rc1, task 2): ONE directory pane of the "Files" tab.

    The mechanical split of the shipped `SftpTab`: the address bar (an editable
    `QLineEdit` whose Enter is answered by the SERVER), the button row, the listing tree
    with drag-OUT and the "no preview" markers, the read-only preview viewer with its
    lazy highlighter, and the D&D handlers of a drop INTO the pane. Everything a pane
    owns is per-listing state; the WORKER is the container's (`self.worker` reads it), so
    a second pane costs a second listing and never a second channel.

    The pane answers only the task ids IT queued: the shared worker signals every pane,
    and the one that does not own a task returns without rendering or reporting anything
    (task ids are unique, so the split is exact).
    """

    PATH_ROLE = Qt.ItemDataRole.UserRole       # full remote path of the entry
    ISDIR_ROLE = Qt.ItemDataRole.UserRole + 1  # bool — is it a directory?
    SIZE_ROLE = Qt.ItemDataRole.UserRole + 2   # int — file size (0 for a directory)
    MTIME_ROLE = Qt.ItemDataRole.UserRole + 3  # int — unix mtime

    # v1.3.1: the preview panel — the tree's share of the splitter on the first open.
    VIEWER_TREE_SHARE = 0.45

    # v1.3.1: the width the share above is measured against while the splitter is not laid out yet
    # (a panel opened on a never-shown tab measured 0 — the share is computed for SOMETHING).
    VIEWER_MIN_TOTAL_PX = 640

    # v1.4.7: the blocks formatted AROUND the viewport on either side (the lazy
    # window of the highlighter — a small scroll costs nothing because the
    # neighbours are already done).
    VIEWER_LAZY_MARGIN = syntax.VIEWER_LAZY_MARGIN

    # v1.7.3: the multiplier of that margin while the reader WRAPS — one block is several visual
    # rows there, so the window has to reach further to cover the same distance on the screen.
    WRAP_MARGIN_FACTOR = 2

    # Local hints in the window's status bar (waiting for connection, no selection).
    # Worker errors/progress are shown by the window itself via its signals.
    message = Signal(str)

    def __init__(self, container, parent=None):
        super().__init__(parent)
        self._container = container
        self._current_dir = "/"
        self._pending_lists = {}     # task_id → requested path (staleness filter)
        self._transfer_tasks = set()  # task ids of active upload/download
        self._own_transfers = set()   # the transfer ids THIS pane queued (v1.7rc1)
        self._up_item = None          # the ".." row (identified by object)
        # v1.3.1: the viewer's read tasks — task_id → remote path, and the id of
        # the LAST requested read (only its answer fills the panel: a fast double
        # click on two files must end up showing the SECOND one).
        self._read_tasks = {}
        self._last_read = None
        self._viewer_encoding = "utf-8"
        # v1.4.7: ONE highlighter per pane (created on the first preview), the
        # language of what is on the screen, and the block window the last
        # formatting pass covered (so a repeated scroll is free).
        self._highlighter = None
        self._viewer_language = syntax.LANG_NUMBERS
        self._highlight_range = None
        # v1.3.1.1: the FACTS about previewability — path → READ_ERROR_* of a read
        # that the worker really refused (see preview_block_reason); per session.
        self._blocked = {}
        self._blocked_icon_cache = None
        # v1.3.3.2 (ROADMAP task 1): the file operations — task_id → kind, so an
        # answer refreshes the listing and an error is reported as an OPERATION
        # error (the queue itself is untouched), and the pre-flight listings of a
        # drop on a directory row — task_id → (target dir, local files).
        self._op_tasks = {}
        self._pending_batches = {}
        # v1.7.3: the pane-to-pane drops whose target directory is NOT on the screen — the task id
        # of the pre-flight listing → (the (source, name) pairs, the kind, the destination).
        self._pending_drops = {}
        self._drag_source = None      # the widget the current drag event came from
        # v1.7rc3: the viewer's MOVE (the mc preview of the two-pane view). `_viewer_home` is the
        # pane the viewer widget belongs to, and the pane currently CARRYING it is the one whose
        # `_viewer_host is None` → the viewer answers "which pane is showing a preview" ONCE.
        self._viewer_home = self
        self._viewer_host = None      # set on the pane that borrowed the viewer
        self._viewer_from = None      # the pane whose row opened the borrowed preview
        self._viewer_borrowed = False  # set on the pane that is CARRYING a borrowed preview
        # The DECLARED "a preview is open" flag: `QWidget.isVisible()` answers False for a pane
        # that is not on screen yet (a dock tab that was never shown, the offscreen test
        # platform), so the preview state is never read off the widgets.
        self._viewer_open = False
        # v1.6.3 (ROADMAP task 4): the address bar's own bookkeeping — the normalize tasks
        # in flight (task_id → the text the user typed) and the completer's listings
        # (task_id → the directory they answer). `_completer_dir` is the directory the
        # completer is currently fed with, so the typed directory is listed at most ONCE
        # per directory change.
        self._normalize_tasks = {}
        self._completer_lists = {}
        self._completer_dir = None
        # v1.7rc2: the copy/move BATCHES — `_op_batches` maps a queued task id to the
        # batch it belongs to, `_batches` holds the counters of every batch still waiting
        # for an answer, and `_batch_seq` numbers them. The counters are what makes ONE
        # report ("copied / skipped / failed") possible over an asynchronous queue.
        self._op_batches = {}
        self._batches = {}
        self._batch_seq = 0
        # v1.7.3 (ROADMAP v1.7.3, task 2): the remembered directory of this session — the hint the
        # FIRST transport of each pane opens, and the flag that keeps a second list from re-asking.
        self._restored = False
        self._restore_dir = ""
        # v1.7.3 (ROADMAP v1.7.3, task 4): the reader's word wrap — ONE global setting, read at
        # construction so both panes and every session agree.
        self._viewer_wrap = resolve_viewer_wrap()
        # v1.7rc1: the pane-scoped keys (the F-actions) and the ACTIVE-pane ring.
        self._pane_actions = []
        self._ring = focus_ring.FocusRing(styled_widget=None) if focus_ring is not None else None

        t = _t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Path row — the current directory (the "address bar").
        # v1.6.3 (ROADMAP task 4): it is an EDITABLE QLineEdit now — Enter navigates through
        # the SERVER's own resolution (the worker's queue_normalize), so `~`, a relative path
        # and a symlink stay the remote's business. Before the connection it is read-only and
        # carries the waiting text (the pre-connection state of the old QLabel).
        self.path_label = QLineEdit(t("sftp.waiting_connection"))
        _apply_status_style(self.path_label, "status.sftp_row")
        self.path_label.setReadOnly(True)   # until set_worker() binds a transport
        self.path_label.setPlaceholderText(t("sftp.path_placeholder"))
        self.path_label.setClearButtonEnabled(True)
        self.path_label.returnPressed.connect(self._on_path_entered)
        self.path_label.textEdited.connect(self._on_path_edited)
        self.path_completer_model = QStringListModel([], self)
        self.path_completer = QCompleter(self.path_completer_model, self)
        self.path_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.path_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.path_completer.setCompletionRole(Qt.ItemDataRole.DisplayRole)
        self.path_label.setCompleter(self.path_completer)
        outer.addWidget(self.path_label)

        # Buttons: navigation | operations.
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_up = QPushButton(t("sftp.up"))
        self.btn_refresh = QPushButton(t("sftp.refresh"))
        self.btn_upload = QPushButton(t("sftp.upload"))
        self.btn_download = QPushButton(t("sftp.download"))
        self.btn_cancel = QPushButton(t("sftp.cancel"))
        self.btn_cancel.setEnabled(False)  # active while transfers are running
        for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                  self.btn_download):
            b.setEnabled(False)  # until set_worker()
        bar.addWidget(self.btn_up)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        bar.addWidget(self.btn_upload)
        bar.addWidget(self.btn_download)
        bar.addWidget(self.btn_cancel)
        # The button row as ONE widget, so the SECOND pane of the two-pane view can hide it (a commander
        # has ONE button row) and show the key hints in the same line. The layout is built INTO the widget
        # (never `addLayout` on the pane and then a re-parent — Qt refuses a layout that already has an
        # owner), and the wrapper carries a DELIBERATELY small minimum width: a bare QWidget reports its
        # layout's whole minimum (a row of five buttons) and would raise the WINDOW's own floor by that row.
        self.buttons_bar = _ButtonRow()
        self.buttons_bar.setLayout(bar)
        outer.addWidget(self.buttons_bar)
        # v1.7rc3: the hint row of the right pane — hidden in the shipped single-pane look and
        # in the FIRST pane; elided (ONE line, never a reflow of the listing) with the whole
        # text in the tooltip.
        self.hints_label = QLabel("")
        _apply_status_style(self.hints_label, "status.sftp_row")
        self.hints_label.setWordWrap(False)
        self.hints_label.setTextFormat(Qt.TextFormat.PlainText)
        self.hints_label.hide()
        outer.addWidget(self.hints_label)
        # The pane's role in the container (v1.7rc3): a SECONDARY pane keeps no button row.
        self._secondary = False
        self._sync_secondary_ui()

        # Listing: Name | Size | Modified.
        self.tree = _SftpTree()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("sftp.column_name"), t("sftp.column_size"),
                                   t("sftp.column_modified")])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 320)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        # v1.3.3.2: the operations live in the context menu (the QActions are built
        # by _build_context_menu — the test seam; exec() never runs in the tests).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # v1.3.3.2: drag-OUT — a dragged row hands out its remote path as text/plain
        # (DragOnly: the tree never accepts its own drops; D&D INTO the tab is
        # handled by the pane's own eventFilter, which consumes those events first).
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.tree.setToolTip(t("sftp.drag_hint"))
        # v1.7rc1: the focus inside a pane makes it the ACTIVE pane of the container.
        self.tree.focus_in = self.activate

        # v1.3.1 (ROADMAP task 1): the preview panel — QSplitter [tree | viewer].
        # The panel starts hidden (it appears on a double click on a text file);
        # the splitter is a horizontal pair, the viewer is collapsible — but the
        # size is only fixed via minimumWidth + setSizes (Qt gotcha #13:
        # setMaximumWidth on a splitter member breaks the size accounting).
        self.viewer = QWidget()
        self.viewer.setMinimumWidth(240)
        viewer_box = QVBoxLayout(self.viewer)
        viewer_box.setContentsMargins(4, 0, 0, 0)
        viewer_box.setSpacing(2)
        viewer_head = QHBoxLayout()
        viewer_head.setSpacing(6)
        self.viewer_label = QLabel("")
        _apply_status_style(self.viewer_label, "status.sftp_row")
        self.viewer_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.viewer_label.setWordWrap(False)
        self.btn_viewer_close = QPushButton("\u00d7")  # × — the panel header's close cross
        self.btn_viewer_close.setFixedWidth(24)
        self.btn_viewer_close.setToolTip(t("sftp.viewer.close_tooltip"))
        # v1.7rc3: the cross must never take the KEYBOARD. A preview belongs to the pane whose
        # listing it was opened from, so `←`/`→` must keep reaching that tree instead of walking
        # into this button (a focusable child of the panel is the one way the walk could be lost).
        self.btn_viewer_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        viewer_head.addWidget(self.viewer_label, 1)
        viewer_head.addWidget(self.btn_viewer_close, 0)
        viewer_box.addLayout(viewer_head)
        self.viewer_text = QPlainTextEdit()
        self.viewer_text.setReadOnly(True)          # v1.3.1: read-only (editing is rejected)
        self.viewer_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # v1.7.3: the reader's OWN context menu — Qt's standard one PLUS the "Word wrap" row, which
        # is why the menu is built by a method (the `_build_context_menu` test seam).
        self.viewer_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewer_text.customContextMenuRequested.connect(self._on_viewer_menu)
        self.viewer_text.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        # v1.4.7: the lazy hook — updateRequest fires on a scroll AND on a
        # resize, which is exactly the two moments new blocks become visible.
        self.viewer_text.updateRequest.connect(self._on_viewer_update_request)
        viewer_box.addWidget(self.viewer_text, 1)
        self.viewer.hide()
        self.set_viewer_wrap(self._viewer_wrap, persist=False)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.viewer)
        # setCollapsible AFTER addWidget (Qt: an out-of-range index otherwise):
        # the tree must never vanish, the viewer may be dragged shut.
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        outer.addWidget(self.splitter, 1)

        self.btn_up.clicked.connect(self.go_up)
        self.btn_refresh.clicked.connect(lambda: self._relist(self._current_dir))
        self.btn_upload.clicked.connect(self._on_upload)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_viewer_close.clicked.connect(self.close_viewer)

        # v1.2.8: D&D — files from Explorer into any spot of the pane. Qt delivers
        # drag events to the widget under the cursor (the tree covers almost the
        # whole pane), so the handlers live here, and eventFilter forwards events
        # from the CHILDREN (tree/viewport/header/buttons) to the same handlers.
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)
        self.installEventFilter(self)

        self._build_pane_shortcuts()
        # v1.7rc3: the tree hands its keys to the pane (the walk of the two-pane view).
        self.tree.pane_key = self._on_pane_key
        # v1.7.3: the tree hands out the pane's IDENTITY with a dragged row (the pane-to-pane drop).
        self.tree.pane = self
        if self._ring is not None:
            self._ring.styled_widget = self.tree
            self._ring.apply()

    # ── v1.7rc1: the pane identity, the ACTIVE-pane hook and the pane-scoped keys ──

    @property
    def worker(self):
        """The SHARED worker — the CONTAINER owns the binding (SFTP_PANES.md §2)."""
        return self._container.worker

    def session_key(self) -> str:
        """The stable identity of the SESSION this pane lists (the container's, v1.7.3)."""
        try:
            return str(self._container.session_key() or "")
        except (AttributeError, RuntimeError):
            return ""

    def activate(self):
        """Tell the container that the keyboard entered THIS pane (the ACTIVE pane)."""
        try:
            self._container.set_active_pane(self)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a bare pane in a unit test — never raises

    def set_active(self, on: bool):
        """Draw (or drop) the focus ring of the ACTIVE pane. Never raises."""
        if self._ring is None:
            return
        try:
            self._ring.set_active(bool(on))
        except RuntimeError:
            pass  # Qt teardown — the tree is already destroyed

    def _build_pane_shortcuts(self):
        """The pane-scoped key map: ONE `WidgetWithChildrenShortcut` action per row.

        The context is what keeps the contract: the shortcut fires while the keyboard is
        inside THIS pane, so `F5` typed into the terminal canvas never reaches the pane
        and the canvas keeps sending it to the shell (§4.3).
        """
        for seq, slot_name in PANE_SHORTCUTS:
            slot = getattr(self, slot_name, None)
            if not callable(slot):
                continue
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            act.triggered.connect(slot)
            self.addAction(act)
            self._pane_actions.append((seq, act))

    def pane_shortcut(self, seq: str):
        """The QAction of a pane-scoped key (None — the key is not part of the map)."""
        for key, act in self._pane_actions:
            if key == seq:
                return act
        return None

    def set_pane_keys_enabled(self, on: bool):
        """Arm/disarm the pane-scoped keys of THIS pane (v1.7). Never raises.

        A pane CARRYING a borrowed panel is a PANEL and its own listing is off the screen
        (`present_viewer_in()` hides the tree), so its `F3`-`F8` would act on rows nobody can see —
        the keys are disarmed for as long as the panel is there and re-armed with the listing.
        """
        for _seq, act in self._pane_actions:
            try:
                act.setEnabled(bool(on))
            except RuntimeError:
                continue   # Qt teardown — the action's pane is already gone

    # ── v1.7rc3: the SECOND pane — the button row that moves out, the hints that move in ──

    @property
    def secondary(self) -> bool:
        """True — this pane is the RIGHT pane of the two-pane view. Set by the CONTAINER."""
        return bool(self.__dict__.get("_secondary", False))

    @secondary.setter
    def secondary(self, on):
        self._secondary = bool(on)
        self._sync_secondary_ui()

    def hint_text(self) -> str:
        """The key hints of this pane as ONE line (the commander's bottom line).

        Built from `PANE_HINTS` — the SAME keys the pane really binds (`PANE_SHORTCUTS`) plus
        the three that are not `QAction`s (the pane toggle, the mark key and the open key) —
        so the row can never advertise a key the pane does not answer, and a translation is
        read at call time (a language switch re-texts through `retranslate()`).
        """
        parts = []
        for key, label in PANE_HINTS:
            try:
                text = _t(label)
            except Exception:  # noqa: BLE001 — a build without i18n keeps the key itself
                text = label
            parts.append(f"{key} {text}")
        return HINT_SEPARATOR.join(parts)

    def _sync_secondary_ui(self):
        """Show the button row OR the hints row according to this pane's role. Never raises.

        The two rows share ONE line of the layout: the pane that keeps the buttons hides the
        hints, and the RIGHT pane of the two-pane view hides the buttons (the shipped row
        belongs to the first pane — the mc/far look) and shows the hints. The row is never
        BOTH and never NEITHER, so the listing never jumps by a line.

        v1.7rc3: a pane CARRYING a borrowed preview (`_viewer_borrowed`) is a PANEL, not a
        listing — it then shows NO row at all (and no address bar), because the row would act on
        a listing nobody can see.
        """
        secondary = self.secondary
        borrowed = bool(getattr(self, "_viewer_borrowed", False))
        try:
            self.buttons_bar.setVisible(not secondary and not borrowed)
            self.hints_label.setVisible(secondary and not borrowed)
            if secondary:
                self.hints_label.setText(self.hint_text())
                self.hints_label.setToolTip(self.hint_text())
                # ONE line whose height is the button row's: switching panes must not resize the
                # listing by a few pixels (the ring's rule: a state change never reflows).
                height = self.buttons_bar.sizeHint().height()
                if height > 0:
                    self.hints_label.setFixedHeight(height)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a pane built before the row exists

    def focus_listing(self):
        """Give the keyboard to this pane's listing (the mc/far walk's landing point).

        The tree is the pane's keyboard domain, so a pane switch lands there and the arrows
        work at once; a listing with no current row gets its first navigable one, so `F3`/`F5`
        and the walk have a subject. Never raises.
        """
        try:
            self.tree.setFocus(Qt.FocusReason.OtherFocusReason)
        except (RuntimeError, AttributeError):
            return
        try:
            if self.tree.currentItem() is None:
                count = self.tree.topLevelItemCount()
                for i in range(count):
                    item = self.tree.topLevelItem(i)
                    if item is not None and item is not self._up_item:
                        self.tree.setCurrentItem(item)
                        break
        except RuntimeError:
            pass  # Qt teardown — nothing to select

    def _step_current_row(self, delta: int):
        """Move the current row by `delta` over the navigable rows of the listing.

        Only the rows a batch can act on take part (the ".." row is skipped — it is navigation,
        not a subject), which is what makes `Insert`/`Space` the mc/far MARK: the cursor walks
        the files and never lands on "..".

        Qt marks the row it is told to make CURRENT (`setCurrentItem` selects it and DROPS the
        rest of the selection), which is exactly the wrong half for a MARK: the walk therefore
        moves the CURRENT INDEX through the selection model (`CursorPosition` — no selection is
        touched at all), so a marked row stays marked while the cursor travels over it. The
        plain walk of `Enter`/`Left` never needs the selection half either. Never raises.
        """
        try:
            rows = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        except RuntimeError:
            return
        rows = [r for r in rows if r is not None and r is not self._up_item]
        current = self.tree.currentItem()
        if not rows:
            # an off-tree ".." row is the only thing on the screen: leave it, so a mark never
            # stays parked on navigation
            if current is self._up_item:
                self._move_cursor(self.tree.topLevelItem(0) if self.tree.topLevelItemCount()
                                  else None)
            return
        index = rows.index(current) if current in rows else -1
        if index < 0:
            index = 0 if delta > 0 else len(rows) - 1
        else:
            index = max(0, min(len(rows) - 1, index + delta))
        self._move_cursor(rows[index])

    def _move_cursor(self, item):
        """Make `item` the CURRENT row WITHOUT touching the selection (v1.7rc3). Never raises.

        `QTreeWidget.setCurrentItem()` selects the row and clears the rest of the selection —
        fine for a click, fatal for a MARK (`Insert` would unmark what it just marked and every
        earlier mark would be dropped on the next step). The cursor moves through the selection
        model instead, which is what the tree's own keyboard walk uses internally.
        """
        if item is None:
            return
        try:
            model = self.tree.selectionModel()
            index = self.tree.indexFromItem(item)
            if model is None or not index.isValid():
                return
            model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the model is gone

    def _set_row_marked(self, item, marked: bool):
        """Mark/unmark ONE row through the SELECTION MODEL (v1.7rc3). Never raises.

        `QTreeWidgetItem.setSelected()` is the item-level API and it does not reliably update the
        view's selection model on the CURRENT row (the mark of the row the cursor sits on is
        exactly what `Insert` toggles, so it is the one that matters). The model is the storage
        the batch READS (`tree.selectedItems()`), so the mark is written there.
        """
        if item is None:
            return
        try:
            model = self.tree.selectionModel()
            index = self.tree.indexFromItem(item)
            if model is None or not index.isValid():
                return
            flag = (QItemSelectionModel.SelectionFlag.Select if marked
                    else QItemSelectionModel.SelectionFlag.Deselect)
            model.select(index, flag | QItemSelectionModel.SelectionFlag.Rows)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the model is gone

    def _row_marked(self, item) -> bool:
        """True — THIS row carries the mark (read from the SAME selection model)."""
        if item is None:
            return False
        try:
            model = self.tree.selectionModel()
            index = self.tree.indexFromItem(item)
            if model is None or not index.isValid():
                return False
            return bool(model.isSelected(index))
        except (RuntimeError, AttributeError):
            return False

    def _mark_current_row(self):
        """v1.7rc3: `Insert`/`Space` — MARK the current row and step down (the mc/far mark).

        The mark IS the tree's selection (`ExtendedSelection`), which is what the batch of
        `F5`/`F6` reads (`_rows_for_batch()`), so marking needs no second state and no second
        truth. The cursor travels through `_move_cursor()` (never `setCurrentItem`, which would
        drop the marks already made), so the same key really means "mark" and "unmark" in turn.
        With no row at all the pane answers the shipped "select a row first" sentence.
        """
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return
        if item is None or item is self._up_item or not item.data(0, self.PATH_ROLE):
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._set_row_marked(item, not self._row_marked(item))
        # The mark walks DOWN, like every commander: the next key marks the next row.
        self._step_current_row(1)

    def _on_pane_key(self, event) -> bool:
        """v1.7rc3: the mc/far walk of the two-pane view; True — the pane consumed the key.

        ONE decision point for every widget of the pane: the tree calls it from its own
        `keyPressEvent`, the pane's `eventFilter` calls it for the address bar and the buttons,
        so `Tab` switches the panes from wherever the keyboard is (the buttons of the SHIPPED
        single-pane look sit in the tab order otherwise, and a `Tab` there would walk them one
        by one instead of changing the pane).

        Keys handled here: `Tab`/`Backtab` (the pane toggle), `Enter`/`Return` (the shipped
        double-click), `Insert`/`Space` (the mark), `Backspace` (one level up), `Left` (leave
        a directory for its parent row) and `Esc` (close the open preview — wherever it is
        shown). Everything else falls through to Qt — the arrows, the type-ahead and the
        selection modifiers are the tree's own and are deliberately not re-implemented.
        """
        if event is None or event.type() != QEvent.Type.KeyPress:
            return False
        try:
            key = int(event.key())
        except (AttributeError, TypeError, ValueError):
            return False
        mods = event.modifiers()
        plain = mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
        if key == int(Qt.Key.Key_Tab) and plain:
            return self._switch_pane(back=False)
        if key == int(Qt.Key.Key_Backtab) and mods in (
                Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            return self._switch_pane(back=True)
        if key == int(Qt.Key.Key_Escape) and mods == Qt.KeyboardModifier.NoModifier:
            # v1.7rc3: `Esc` leaves the preview. The panel may belong to the OTHER pane (the
            # mc preview of the two-pane view) — the container closes whichever one is open, so
            # the key works from the listing the file was opened from. False with no preview:
            # `Esc` stays the widget's own key (a completer popup, a dialog).
            return self._container.close_preview()
        if key in (int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter)) and plain:
            return self._open_current_row()
        if key in (int(Qt.Key.Key_Insert), int(Qt.Key.Key_Space)) and plain:
            self._mark_current_row()
            return True
        if key == int(Qt.Key.Key_Backspace) and plain:
            self.go_up()
            return True
        if key == int(Qt.Key.Key_Left) and plain:
            return self._leave_current_dir()
        return False

    def _switch_pane(self, back: bool) -> bool:
        """`Tab`/`Shift+Tab` — the pane toggle; True — the key is CONSUMED (v1.7).

        While the OTHER pane carries a borrowed panel there is no second LISTING to switch to — the
        panel is not a listing — so the key is consumed and NOTHING moves: the reading pane keeps
        its listing, its cursor and the keyboard (the contract's rule for the preview), instead of
        the focus walking onto a widget nobody can see.
        """
        if self._container.preview_in_other_pane(self):
            return True
        return bool(self._container.focus_other_pane(self, back=back))

    def _open_current_row(self) -> bool:
        """`Enter` — the shipped double-click on the current row (True — there was a row).

        A directory is entered, a file opens the read-only preview and ".." goes one level up;
        with no row the pane answers the shipped sentence, exactly like `F3`.
        """
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return True
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return True
        if item is self._up_item:
            self.go_up()
            return True
        self._on_item_double_clicked(item, 0)
        return True

    def _leave_current_dir(self) -> bool:
        """`Left` — leave a directory for its parent row instead of collapsing it (mc/far).

        True only when the current row IS a directory and its parent could be resolved: a file
        row, ".." and "/" answer False, so `Left` keeps Qt's own behaviour there (the selection
        moves one column left, which is what the shipped look does).
        """
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return False
        if item is None or item is self._up_item:
            return False
        if not item.data(0, self.ISDIR_ROLE):
            return False
        parent = posixpath.dirname(self._current_dir)
        if not parent or parent == self._current_dir:
            return False
        self._relist(parent)
        return True

    def _current_row(self):
        """The row a pane-scoped key acts on: the CURRENT row of the listing (None — none)."""
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return None
        if item is None or item is self._up_item or not item.data(0, self.PATH_ROLE):
            return None
        return item

    def _cmd_view(self):
        """`F3` — view: the double-click behaviour on the current row (a directory is
        entered, a file opens the read-only preview, ".." goes up)."""
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._on_item_double_clicked(item, 0)

    def _cmd_copy(self):
        """`F5` — copy the current row (or the whole selection) to the OTHER pane's directory.

        v1.7rc2: the reserved half of the frozen contract is shipped. With ONE pane there is
        no destination, and the honest answer is ONE sentence (the corner control is what
        opens the second pane) — never a silent no-op.
        """
        target = self._container.other_pane(self)
        if target is None:
            self.message.emit(_t("sftp.cmd.copy_no_target"))
            return
        self._remote_batch(KIND_COPY, target)

    def _cmd_move_rename(self):
        """`F6` — move the row(s) to the other pane, or rename in place.

        The cross-directory MOVE (v1.7rc2) runs when the OTHER pane shows another
        directory; with a single pane — or when both panes are in the SAME directory — the
        shipped same-directory rename happens instead, so the key keeps the meaning it had
        in the single-listing tab.
        """
        target = self._container.other_pane(self)
        if target is not None and target.current_dir != self._current_dir:
            self._remote_batch(KIND_MOVE, target)
            return
        item = self._current_row()
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._op_rename(item)

    def _cmd_mkdir(self):
        """`F7` — new folder in THIS pane's current directory."""
        self._op_new_folder()

    def _cmd_delete(self):
        """`F8` — delete the current row (with the shipped confirmation)."""
        item = self._current_row()
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._op_delete(item)

    # ── Worker binding (the container calls these) ───────────────────────

    def bind_worker(self, old_worker, new_worker):
        """Bind/unbind the SHARED worker: `None` — the "waiting for connection" state.

        The OLD worker is passed explicitly because the container has already replaced its
        own reference when this runs — the pane must disconnect from the transport it was
        really listening to, not from the new one.

        A pane's bookkeeping belongs to ONE transport, so every task map is cleared here: a
        listing, a read, an operation or a completer answer of the previous server must
        never land in this one.
        """
        self._disconnect_worker(old_worker)
        self._transfer_tasks.clear()
        self._own_transfers.clear()
        # v1.3.3.2: the operation answers and the pre-flight listings belong to the
        # transport that was asked — a new worker starts with a clean bookkeeping.
        self._op_tasks.clear()
        self._pending_batches.clear()
        # v1.7.3: the dropped rows waiting for a listing belong to ONE transport as well.
        self._pending_drops.clear()
        # v1.6.3: the address bar's tasks and the completer's listings belong to ONE
        # transport as well (a normalize of the previous server must not navigate THIS one).
        self._normalize_tasks.clear()
        self._completer_lists.clear()
        self._completer_dir = None
        # v1.7rc2: the batch bookkeeping belongs to ONE transport as well (an answer of
        # the previous server must not be counted into a batch of this one).
        self._op_batches.clear()
        self._batches.clear()
        self.path_completer_model.setStringList([])
        # v1.3.1.1: the previewability facts belong to ONE transport/session — a new
        # worker (a new connection, possibly another server on the same paths) starts
        # with a clean listing.
        self._blocked.clear()
        self.btn_cancel.setEnabled(False)

        if new_worker is None:
            self._current_dir = "/"
            self._pending_lists.clear()
            self.tree.clear()
            self._up_item = None
            # v1.3.1: the preview belongs to the session's transport — the content
            # of a dead worker must not stay on the screen.
            self.close_viewer()
            self._set_path_text(_t("sftp.waiting_connection"))
            self.path_label.setReadOnly(True)
            for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                      self.btn_download):
                b.setEnabled(False)
            return

        for name in WORKER_SIGNAL_NAMES:
            sig = getattr(new_worker, name, None)
            slot = getattr(self, "_on_" + name, None)
            if sig is None or slot is None:
                continue
            sig.connect(slot)
        for b in (self.btn_up, self.btn_refresh, self.btn_upload,
                  self.btn_download):
            b.setEnabled(True)
        self.path_label.setReadOnly(False)
        # v1.7.3 (task 2): the FIRST transport of this pane opens the directory the server was
        # left in (ONE per-server key, a HINT): the answer may be a refusal, and `_on_task_error`
        # then says so and falls back to the shipped opening rule.
        start = self._current_dir
        try:
            hint = "" if self._restored else self._container.remembered_dir()
        except (AttributeError, RuntimeError):
            hint = ""   # a foreign container without the memory — the shipped opening rule
        if hint:
            self._restored = True
            self._restore_dir = hint
            start = hint
        self._relist(start)

    def _disconnect_worker(self, worker):
        """Drop this pane's slots from a worker (idempotent — a not-connected slot is a no-op)."""
        if worker is None:
            return
        for name in WORKER_SIGNAL_NAMES:
            sig = getattr(worker, name, None)
            if sig is None:
                continue
            try:
                sig.disconnect(self)
            except (TypeError, RuntimeError):
                pass  # no connection existed / the worker is already gone

    def release(self):
        """Detach the pane: unbind the worker and drop the preview (the pane is going away)."""
        self._disconnect_worker(self.worker)
        self.close_viewer()

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to this pane's own labels.

        Both label styles come from the ONE registry (`_apply_status_style`), so
        the switch is the same call the constructor made. Never raises.

        v1.4.7: the syntax colours are read LIVE from the active `Theme` by the
        highlighter (its format cache is keyed by the instance), but the formats
        already APPLIED to the visible blocks are values — so the highlighter is
        asked to drop them and repaint the window.

        v1.7rc1: the ACTIVE-pane ring is a stylesheet — re-applied here as well.
        """
        for widget in (getattr(self, "path_label", None),
                       getattr(self, "viewer_label", None),
                       getattr(self, "hints_label", None)):
            if widget is None:
                continue
            try:
                _apply_status_style(widget, "status.sftp_row")
            except RuntimeError:
                continue  # Qt teardown — this label is already destroyed
        if self._ring is not None:
            try:
                self._ring.refresh_theme()
            except RuntimeError:
                pass  # Qt teardown — the tree is already destroyed
        if self._highlighter is not None:
            try:
                self._highlighter.refresh_theme()
            except RuntimeError:
                pass  # Qt teardown — the document is already gone

    def retranslate(self):
        """v1.3.3.1: re-text the pane's own strings in the current language.

        Every string already has an i18n key: the five buttons, the three column headers,
        the viewer's close tooltip and the "no preview" row tooltips. The module translator
        (`i18n.t`) is looked up at call time, so no cache has to be invalidated.

        v1.3.3.2: the drag-out hint of the tree (the context menu is rebuilt on
        every right click and needs nothing here).

        v1.4.7: the heuristic-highlighting note of the viewer header
        (`sftp.viewer.syntax_heuristic`) is deliberately NOT re-texted here — like
        the path and the size it describes the file ON THE SCREEN; the next
        preview renders it in the active language.

        Deliberately NOT touched: the path label and the viewer header — they carry
        the CURRENT directory / file (data, not UI text); the "waiting connection"
        state is re-texted by `bind_worker(None)` on the next call. Never raises —
        the dead-C++-object discipline of every container method.
        """
        try:
            self.btn_up.setText(_t("sftp.up"))
            self.btn_refresh.setText(_t("sftp.refresh"))
            self.btn_upload.setText(_t("sftp.upload"))
            self.btn_download.setText(_t("sftp.download"))
            self.btn_cancel.setText(_t("sftp.cancel"))
            self.tree.setHeaderLabels([_t("sftp.column_name"), _t("sftp.column_size"),
                                       _t("sftp.column_modified")])
            self.tree.setToolTip(_t("sftp.drag_hint"))
            self.btn_viewer_close.setToolTip(_t("sftp.viewer.close_tooltip"))
            # v1.6.3: the address bar's placeholder.
            self.path_label.setPlaceholderText(_t("sftp.path_placeholder"))
            # v1.7rc3: the hint row of the SECOND pane (five `sftp.hint.*` keys + the pane
            # toggle, the mark key and the open key) — re-read in the active language. The
            # row is re-elided by the layout on the next pass, so nothing else is needed.
            self._sync_secondary_ui()
            # The row markers carry the refusal text in the tooltip — re-text the
            # rows of the CURRENT listing that are really marked (the facts of this
            # session; the marker itself is re-applied by the next listing).
            for path, reason in list(getattr(self, "_blocked", {}).items()):
                if not reason:
                    continue
                for i in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(i)
                    if item.data(0, self.PATH_ROLE) == path:
                        item.setToolTip(0, self._blocked_tooltip(reason))
                        break
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    @property
    def current_dir(self) -> str:
        """The currently shown directory (upload target) of THIS pane."""
        return self._current_dir

    # ── Navigation and listing ───────────────────────────────────────────

    def go_up(self):
        """".." — one level up (no-op from "/")."""
        if self._current_dir == "/":
            return
        parent = posixpath.dirname(self._current_dir) or "/"
        self._relist(parent)

    def _navigate(self, path: str):
        """Enter a directory (double-click on a directory row)."""
        self._relist(path)

    def follow_directory(self, path: str) -> bool:
        """v1.6.3 (ROADMAP task 5): the SHELL moved — move the listing with it.

        The caller is the session's OSC 7 scanner, so the path comes from the remote: an
        empty / relative / NUL-carrying report is refused here (a "no follow", never an
        error), a directory already on the screen is a no-op, and everything else goes
        through the ORDINARY `_relist()` — the same listing, the same staleness filter and
        the same `message` signal a click uses. Returns True when the view moved.
        """
        if self.worker is None:
            return False
        target = str(path or "")
        if not target.startswith("/") or "\x00" in target or target == self._current_dir:
            return False
        self._relist(target)
        return True

    def _relist(self, path: str):
        """Redraw the listing for the new current directory."""
        self._current_dir = path or "/"
        self.tree.clear()
        self._up_item = None
        self._set_path_text(self._current_dir)
        self.btn_up.setEnabled(self._current_dir != "/")
        if self.worker is None:
            return
        tid = self.worker.queue_list(self._current_dir)
        if tid is not None:
            self._pending_lists[tid] = self._current_dir

    # ── v1.6.3 (ROADMAP task 4): the address bar ─────────────────────────────

    def _set_path_text(self, text: str):
        """Write the address bar WITHOUT echoing it back as an edit.

        `setText` on a QLineEdit does not emit `textEdited` (only `textChanged`), so no
        loop exists — the guard is here because the completer's directory bookkeeping is
        driven by `textEdited` alone and a programmatic write must never look like typing.
        """
        try:
            self.path_label.setText(text or "")
        except RuntimeError:
            pass  # Qt teardown — the bar is already destroyed

    def _on_path_entered(self):
        """Enter in the address bar: navigate through the SERVER's own resolution.

        The text goes to the worker AS TYPED (a `~`, a relative path, a symlink are the
        remote's business — a local guess would be a second, worse truth); a path the server
        cannot resolve answers `task_error` and is reported through the `message` signal,
        never as a traceback. The bar keeps the typed text until the answer arrives, so a
        failure leaves the user with what they typed.
        """
        if self.worker is None:
            return
        typed = self.path_label.text() or ""
        if not typed.strip() or typed.strip() == _t("sftp.waiting_connection"):
            return
        tid = self.worker.queue_normalize(typed, self._current_dir)
        if tid is not None:
            self._normalize_tasks[tid] = typed

    def _on_normalize_ready(self, task_id: int, requested: str, resolved: str):
        """The server's REALPATH of a typed path → navigate there (v1.6.3)."""
        if self._normalize_tasks.pop(task_id, None) is None:
            return   # not this pane's task (v1.7rc1: the shared worker signals every pane)
        target = resolved or requested
        if not target:
            return
        self._relist(target)

    def _on_path_edited(self, text: str):
        """Feed the completer from the SAME async listing the pane already uses.

        The directory part of what is being typed decides the listing — at most ONE
        `queue_list()` per directory CHANGE (a keystroke inside the same directory costs
        nothing), its answer fills the model with the directories first (a trailing `/`
        makes the completion continue into them) and the files after. A relative directory
        is resolved against the directory on the screen, exactly as Enter will resolve it.
        """
        if self.worker is None:
            return
        directory = posixpath.dirname(text)
        if not directory:
            directory = self._current_dir
        elif not directory.startswith(("/", "~")):
            directory = posixpath.join(self._current_dir, directory)
        try:
            self.path_completer.setCompletionPrefix(posixpath.basename(text))
        except RuntimeError:
            return  # Qt teardown
        if directory == self._completer_dir:
            return
        self._completer_dir = directory
        tid = self.worker.queue_list(directory)
        if tid is not None:
            self._completer_lists[tid] = directory

    def _fill_completer(self, entries: list):
        """The completion model: directories first with a trailing `/`, then the files."""
        names = sorted(
            [(str(e.get("name", "")) + "/") if e.get("is_dir") else str(e.get("name", ""))
             for e in entries if e.get("name")],
            key=lambda n: (not n.endswith("/"), n.lower()))
        try:
            self.path_completer_model.setStringList(names)
        except RuntimeError:
            pass  # Qt teardown — the model is gone with the pane

    def _on_list_ready(self, task_id: int, remote_dir: str, entries: list):
        # v1.6.3: the completer's listing — it feeds the completion model and is NEVER
        # rendered (that directory is not on the screen); it is checked FIRST, because the
        # answer may belong to the directory the user is typing while the tree shows another.
        if self._completer_lists.pop(task_id, None) is not None:
            self._fill_completer(entries)
            return
        # v1.3.3.2: the pre-flight listing of a drop on a directory row — the answer
        # is NOT rendered (that directory is not on the screen), it only feeds the
        # conflict check of the batch that is waiting for it.
        pending = self._pending_batches.pop(task_id, None)
        if pending is not None:
            target, files = pending
            self._queue_uploads(files, target, {e["name"] for e in entries})
            self.message.emit(
                _t("sftp.drop_queued", count=len(files), dir=target))
            return
        # v1.7.3: the pre-flight listing of a PANE-to-pane drop — the same rule as above, for the
        # copy/move batch whose destination is not the directory on the screen.
        dropped = self._pending_drops.pop(task_id, None)
        if dropped is not None:
            items, kind, target = dropped
            self._queue_transfer_batch(items, kind, target, {e["name"] for e in entries})
            return
        requested = self._pending_lists.pop(task_id, None)
        # Staleness filter: render only the response for the CURRENT directory
        # (navigation or Refresh while an old listing was in flight — ignored).
        # v1.7rc1: a task id of the OTHER pane is not in this pane's map at all, so the
        # two panes list independently over the one worker (task ids are unique).
        if requested is None or requested != self._current_dir \
                or remote_dir != self._current_dir:
            return
        self.tree.clear()
        self._up_item = None
        if self._current_dir != "/":
            up = QTreeWidgetItem(self.tree)
            up.setText(0, "..")
            up.setIcon(0, self._dir_icon())
            up.setData(0, self.PATH_ROLE, posixpath.dirname(self._current_dir) or "/")
            up.setData(0, self.ISDIR_ROLE, True)
            up.setData(0, self.SIZE_ROLE, 0)
            up.setData(0, self.MTIME_ROLE, 0)
            self._up_item = up
        for e in entries:
            self._add_entry_item(e)
        self._focus_first_row()
        # v1.7.3 (task 2): a directory the SERVER really answered for is what memory keeps — and
        # the restored hint has arrived, so it is no longer pending.
        self._restore_dir = ""
        self._container.remember_dir(self._current_dir)

    def _focus_first_row(self):
        """Put the CURSOR on the first navigable row of a freshly rendered listing.

        A commander is driven by the keyboard, so a listing that came back with no current row
        would answer `Select a row first` to the first `F3`/`Enter` — the cursor lands on the
        first file or directory instead (never on the ".." row, which is navigation). Called
        after a listing is rendered; a row the user already picked is never moved. Never raises.
        """
        try:
            if self.tree.currentItem() is not None:
                return
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is not None and item is not self._up_item and item.data(0, self.PATH_ROLE):
                    self.tree.setCurrentItem(item)
                    return
        except RuntimeError:
            pass  # Qt teardown — nothing to focus

    def _add_entry_item(self, entry: dict) -> QTreeWidgetItem:
        full = posixpath.join(self._current_dir, entry["name"])
        item = QTreeWidgetItem(self.tree)
        item.setText(0, entry["name"])
        item.setIcon(0, self._dir_icon() if entry["is_dir"] else self._file_icon())
        item.setData(0, self.PATH_ROLE, full)
        item.setData(0, self.ISDIR_ROLE, bool(entry["is_dir"]))
        item.setData(0, self.SIZE_ROLE, int(entry.get("size") or 0))
        item.setData(0, self.MTIME_ROLE, int(entry.get("mtime") or 0))
        item.setText(1, "" if entry["is_dir"] else format_size(entry.get("size")))
        item.setText(2, "" if entry["is_dir"] else format_mtime(entry.get("mtime")))
        self._apply_preview_marker(item, full)   # v1.3.1.1: "no preview" markers
        return item

    def _dir_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    def _file_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    # ── v1.3.1.1: the "no preview" markers of the listing ────────────────

    def _apply_preview_marker(self, item: QTreeWidgetItem, path: str):
        """Mark a row the viewer cannot preview (a recoloured file icon + the
        reason in the tooltip); a previewable row is left with the plain icon and
        without a tooltip (the call is idempotent — it also CLEARS a stale mark).

        Directories are never marked. The name colour is deliberately untouched:
        an explicit setForeground() would overcome the selection colours of the
        style, while the recoloured glyph survives selection and does not rely on
        the colour alone (the tooltip spells the reason out).
        """
        if item.data(0, self.ISDIR_ROLE):
            return
        reason = preview_block_reason(path, item.data(0, self.SIZE_ROLE),
                                      self._blocked)
        if not reason:
            item.setIcon(0, self._file_icon())
            item.setToolTip(0, "")
            return
        item.setIcon(0, self._blocked_icon())
        item.setToolTip(0, self._blocked_tooltip(reason))

    def _blocked_tooltip(self, reason: str) -> str:
        """The reason of a marked row — the SAME texts the refusal itself shows."""
        if reason == READ_ERROR_TOO_LARGE:
            return _t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES))
        return _t("sftp.viewer.binary")

    def _blocked_icon(self):
        """The file icon of a marked row: the style's file glyph recoloured to the
        theme's "no preview" tone (cached).

        CompositionMode_SourceIn keeps the SHAPE and replaces the colour — the
        marker is visible as a shape, not only as a colour. A style that returns
        no pixmap for the standard icon (an exotic platform) falls back to the
        plain glyph: the tooltip still explains the row.
        """
        if self._blocked_icon_cache is not None:
            return self._blocked_icon_cache
        base = self._file_icon()
        pixmap = base.pixmap(16, 16)
        if pixmap.isNull():
            self._blocked_icon_cache = base
            return self._blocked_icon_cache
        pixmap = QPixmap(pixmap)   # a copy: the style may keep/share the pixmap
        painter = QPainter(pixmap)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(theme.SFTP_PREVIEW_BLOCKED))
        painter.end()
        self._blocked_icon_cache = QIcon(pixmap)
        return self._blocked_icon_cache

    def _mark_row(self, path: str):
        """Re-apply the marker of the row showing `path`; no such row in the
        current listing (another directory / a refreshed one) — nothing to do."""
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, self.PATH_ROLE) == path:
                    self._apply_preview_marker(item, path)
                    return
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── Tree events ──────────────────────────────────────────────────────

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        if not item.data(0, self.ISDIR_ROLE):
            self._open_viewer(item)   # v1.3.1: a file — the read-only preview
            return
        if item is self._up_item:
            self.go_up()
        else:
            self._navigate(item.data(0, self.PATH_ROLE))

    # ── v1.3.1: the preview panel (ROADMAP task 1) ───────────────────────

    def _open_viewer(self, item: QTreeWidgetItem):
        """A double click on a file → read it through the worker queue and show it.

        The pane never touches the remote file itself: the read is a "read" task
        of the existing queue (32 KB chunks, the limit and the binary check are
        the worker's job), the answer arrives via read_ready. The panel opens
        only when the answer is there — a refusal (binary / too large) stays a
        message in the status bar (task_error → _on_task_error).

        v1.7rc3: in the TWO-PANE view the preview is shown WHERE THE OTHER PANE IS (the mc
        behaviour) and THIS pane keeps the keyboard and the cursor; the reading pane stays the
        owner of the task and of the message, so a refusal is reported exactly as before.
        """
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        # v1.7rc3: the GATE is asked first — ONE preview exists at a time, and a file opened while
        # the OTHER pane shows a panel is refused with ONE sentence. A panel THIS pane owns is not
        # in the way: the new file is read into it (walking the listing with F3 is the whole point
        # of a commander, so a second open from the reading pane must never be refused as "busy").
        if not self._container.preview_allowed(self):
            return
        # Opening a file ALWAYS starts from a clean look: a preview already open in the two-pane
        # view (whichever pane lent or carries its panel) closes first, so a new preview can never
        # share a splitter with the old one, and a re-open of the SAME file re-reads it. The panel
        # is MOVED to the other pane only once the content is there (`_show_viewer()`): a read the
        # worker refuses must not leave the other pane dressed as a panel that shows nothing.
        self._container.close_preview()
        tid = self.worker.queue_read(path, int(item.data(0, self.SIZE_ROLE) or 0))
        if tid is None:
            return  # the worker is finished — there is nobody to read
        self._read_tasks[tid] = path
        self._last_read = tid
        self.viewer_label.setText(_t("sftp.viewer.reading", name=posixpath.basename(path)))

    def _on_read_ready(self, task_id: int, remote_path: str, data: bytes):
        """The read answer (already on the GUI thread): render it in the panel."""
        path = self._read_tasks.pop(task_id, remote_path)
        if task_id != self._last_read:
            return  # an outdated answer (another file was opened since) — dropped
        self._last_read = None
        # v1.3.1.1: a successful read is a FACT too — drop a stale mark of this row
        # (defensive: the two heuristics agree today, and the state must not drift).
        if self._blocked.pop(path, None) is not None:
            self._mark_row(path)
        text, encoding = decode_text(bytes(data))
        self._show_viewer(path, len(data), text, encoding)

    def _on_task_error(self, task_id: int, kind: str, message: str):
        """task_error: for a "read" task the message is a MACHINE code — the pane
        turns it into an i18n hint (the window's status bar stays silent about
        reads: terminal_page skips them, the pane owns the message).

        The QUEUE is untouched (the worker contract): a refusal of one file does
        not break the listing or the transfers.

        v1.3.1.1: a refusal is also a FACT for the session — only the worker sees
        the content, so its verdict marks the row (a null byte inside a `.txt`
        cannot be guessed from the name) and the mark survives re-listing.

        v1.7rc1: the ONE worker signals EVERY pane, so a pane that does not own the task
        returns at once — otherwise the other pane would report a stranger's failure (or
        draw a stranger's row).
        """
        if kind == KIND_READ:
            if task_id not in self._read_tasks:
                return   # another pane's read (or the command history's) — not ours
            path = self._read_tasks.pop(task_id, "")
            if task_id == self._last_read:
                self._last_read = None
            if path and message in (READ_ERROR_BINARY, READ_ERROR_TOO_LARGE):
                self._blocked[path] = message
                self._mark_row(path)
            self.message.emit(self._read_error_text(message, path))
        elif kind in OP_KINDS:
            # v1.3.3.2: a file operation failed (the queue lives on) — the pane owns
            # the message (the page stays silent about the operation kinds), and the
            # listing is NOT refreshed: nothing changed on the server.
            if self._op_tasks.pop(task_id, None) is None:
                return   # another pane's operation
            if kind in (KIND_COPY, KIND_MOVE):
                # v1.7rc2: a remote copy/move — the machine payload becomes a translated
                # sentence (a partial tree, a refused rename, a tree over its bound) and
                # the batch counts ONE failure (the v1.1.3 rule: the rest goes on).
                self.message.emit(self._remote_error_text(message))
                self._answer_batch_task(task_id, "failed")
            else:
                self.message.emit(_t("sftp.op.error", error=message))
        elif kind == KIND_NORMALIZE:
            # v1.6.3: the address bar asked for a path the server cannot resolve — the bar
            # keeps the typed text (nothing navigated) and the reason is a sentence.
            typed = self._normalize_tasks.pop(task_id, None)
            if typed is None:
                return   # another pane's normalize
            self.message.emit(_t("sftp.path_error", path=typed, error=message))
        elif kind == "list":
            # v1.3.3.2: the pre-flight listing of a drop on a row failed (the
            # directory vanished / no permission) — the batch is dropped, the pane
            # reports the reason instead of uploading into nowhere.
            failed_dir = self._pending_lists.pop(task_id, None)
            # v1.7.3 (task 2): the REMEMBERED directory may be the one that is gone — a restored
            # path is a hint, so the pane says so and opens the shipped starting directory.
            if failed_dir and failed_dir == self._restore_dir:
                self._restore_dir = ""
                self._restored = True
                self.message.emit(_t("sftp.dir_missing", path=failed_dir, fallback="/"))
                self._relist("/")
                self._on_task_finished(task_id)
                return
            pending = self._pending_batches.pop(task_id, None)
            if pending is not None:
                self.message.emit(_t("sftp.op.error", error=message))
            if self._pending_drops.pop(task_id, None) is not None:
                self.message.emit(_t("sftp.op.error", error=message))
        self._on_task_finished(task_id)

    def _read_error_text(self, code: str, path: str = "") -> str:
        """READ_ERROR_* → the translated hint.

        Any OTHER message is a real failure reported by the worker (a path or
        permission error, str(exception)) — it goes through the same translated
        line with the file name, so the reader always gets a readable sentence.
        """
        if code == READ_ERROR_BINARY:
            return _t("sftp.viewer.binary")
        if code == READ_ERROR_TOO_LARGE:
            return _t("sftp.viewer.too_large", limit=format_size(MAX_READ_BYTES))
        return _t("sftp.viewer.read_failed",
                  name=posixpath.basename(path) if path else "?",
                  error=code or "unknown error")

    def _show_viewer(self, path: str, size: int, text: str, encoding: str = "utf-8"):
        """Fill the panel with the file and show it (an unshown panel gets sizes).

        v1.4.7: the language is decided from the path AND the content
        (`syntax.detect_syntax` — the honesty rule: a `.json`/`.xml` hint is
        accepted only after a real parse) and the pane's ONE highlighter colours
        the blocks around the viewport. The header carries the heuristic note
        for the modes no parser verified (YAML), exactly like the encoding note.

        v1.7rc3: the panel may have been MOVED to the other pane before this call
        (`present_viewer_in()`), so the share is computed for the splitter that really carries it
        and the READING pane keeps the keyboard (its listing stays under the cursor while the
        preview appears beside it — the mc behaviour).
        """
        language = syntax.detect_syntax(path, text)
        head = _t("sftp.viewer.header", path=path, size=format_size(size))
        if encoding != "utf-8":
            head = f"{head} · {_t('sftp.viewer.encoding_note', encoding=encoding)}"
        if syntax.is_heuristic(language):
            head = f"{head} · {_t('sftp.viewer.syntax_heuristic', language=language)}"
        self.viewer_label.setText(head)
        self.viewer_label.setToolTip(path)
        self._viewer_encoding = encoding
        self._viewer_language = language
        highlighter = self._ensure_highlighter()
        if highlighter is not None:
            highlighter.set_language(language)
            # BEFORE setPlainText: Qt reformats the WHOLE changed range, and with
            # an EMPTY window that pass applies no format at all — which is what
            # keeps the previous file from bleeding into this one.
            highlighter.reset_for_document()
        self._highlight_range = None
        self.viewer_text.setPlainText(text)   # the cursor lands at the start by itself
        self._viewer_open = True
        # The panel is where the FILE is: with two panes it takes the OTHER pane's slot (mc/far),
        # with one it stays inside this one (the shipped look). The move happens HERE — with the
        # content already in the widget — so a read the worker refused leaves every pane alone.
        self._container.present_viewer(self)
        self.viewer.show()
        self._layout_viewer_share()
        self._highlight_visible(force=True)

    # ── v1.7rc3: the preview moved to the other pane (the mc F3 of the two-pane view) ──

    def _viewer_splitter(self):
        """The splitter that really carries the viewer (its HOME pane's by default)."""
        parent = self.viewer.parent()
        return parent if parent is not None else self.splitter

    def _layout_viewer_share(self):
        """Give the panel its declared share of the splitter that REALLY carries it. Never raises.

        Qt gotcha #13: a splitter member's share is set via `setSizes()` only. The splitter can hold
        a THIRD member — a pane carrying a borrowed panel keeps its OWN one in the layout (hidden,
        so it lands nowhere) while the borrowed one takes the slot it left — which is why the share
        is computed over the members BY NAME: the listing takes `VIEWER_TREE_SHARE`, the viewer that
        is really on screen takes the rest and a panel that stepped aside answers 0. A share handed
        out by POSITION would give the column to the hidden member and leave the borrowed panel zero
        pixels wide: the borrowing pane changed its look and showed nothing at all.
        """
        splitter = self._viewer_splitter()
        try:
            count = splitter.count()
            index = splitter.indexOf(self.viewer)
        except RuntimeError:
            return   # Qt teardown — the splitter or the viewer is already gone
        if count <= 0 or index < 0:
            return
        total = max(splitter.width(), self.VIEWER_MIN_TOTAL_PX)
        left = int(total * self.VIEWER_TREE_SHARE)
        try:
            # v1.7: a pane CARRYING a borrowed panel is a PANEL — its own listing left the layout
            # (`present_viewer_in()` hides it), so the panel takes the WHOLE pane.
            listing = splitter.widget(0)
            if listing is not None and listing.isHidden():
                left = 0
        except RuntimeError:
            pass   # Qt teardown — the splitter is already gone
        sizes = [0] * count
        sizes[0] = left                                   # the listing is the first member
        sizes[index] = max(total - left, 0)               # the panel is the one that is showing
        splitter.setSizes(sizes)

    def viewer_host(self):
        """The pane whose splitter currently carries the viewer (None — no preview is open).

        ONE answer for the whole container: the pane that BORROWED the viewer registers itself in
        `_viewer_host`, so "close the preview and restore the listing" has a single subject and
        the pane that opened it never has to guess. The state is the DECLARED `_viewer_open` flag,
        never `QWidget.isVisible()` — a pane that is not on screen yet (a never-shown dock tab, the
        offscreen test platform) reports its widgets as invisible while its preview is really open.
        """
        if not getattr(self, "_viewer_open", False):
            return None
        if self._viewer_host is not None:
            return self._viewer_host
        return self._viewer_home or self

    def _restore_listing(self):
        """Put the tree and the pane's own rows back after a borrowed viewer leaves it.

        Called with `_viewer_host` ALREADY cleared (the owner has taken its panel home), so the
        only question is whether this pane was CARRYING it — a pane that never did must keep its
        own panel's look untouched. Never raises.
        """
        try:
            if not getattr(self, "_viewer_borrowed", False):
                return
            self._viewer_borrowed = False
            self.path_label.show()
            self.tree.show()                  # v1.7: the listing comes back with the rows
            self.splitter.setCollapsible(0, False)   # the tree is never draggable shut again
            self.set_pane_keys_enabled(True)
            self._sync_secondary_ui()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a pane built before the rows exist

    def present_viewer_in(self, host, source=None) -> bool:
        """Move THIS pane's viewer into `host`'s splitter; True — it really moved.

        The two-pane view shows a preview WHERE THE OTHER PANE IS (mc and far do the same): the
        listing that opened it keeps the cursor and the keyboard, and the panel takes the other
        pane's place for as long as it is open. The viewer is ONE widget owned by the pane it was
        built in, so the move is a re-parent (`QSplitter.insertWidget()`) instead of a second
        `QPlainTextEdit` per pane — the highlighter, the content and the × belong to the same
        object, and closing the preview puts it back where it came from.

        **The host is a PANEL for as long as it carries the preview**: its address bar and its key
        row were already gone, and since v1.7 its LISTING leaves the layout too (`tree.hide()`), so
        the panel gets the whole pane instead of sharing it with a listing nobody is looking at.
        That is also why the pane's own pane-scoped keys are disarmed here: a key that acts on a
        listing off the screen would act on rows nobody can see.

        Refused (False) for the pane itself and for a foreign pane: the container asks
        `preview_allowed()` BEFORE the read (the ONE-preview rule) and `present_viewer()` decides
        whether the move is still wanted when the answer is there, this method only performs it.
        """
        if host is None or host is self or host is not self._container.other_pane(self):
            return False
        try:
            # The host's OWN panel steps aside — it stays in the splitter, hidden (a hidden member
            # takes no room) — and the borrowed one is inserted in the very slot it left, so the
            # panel is the pane's RIGHT column and not a third member squeezed to nothing.
            index = host.splitter.indexOf(host.viewer)
            if index < 0:
                index = host.splitter.count()
            else:
                host.viewer.hide()
            host.splitter.insertWidget(index, self.viewer)
        except RuntimeError:
            return False
        self._viewer_host = host
        self._viewer_from = source if source is not None else self
        # The host is a PREVIEW now: its address bar belongs to a listing nobody can see and the
        # key row of a pane that carries a panel is hidden (see `_sync_secondary_ui`). Since v1.7
        # its LISTING leaves the layout as well — the panel takes the WHOLE pane (the mc/far quick
        # view), and the tree's own keys (`Tab` into it, `F3`-`F8` on a row) are disarmed with it.
        host._viewer_borrowed = True
        try:
            host.path_label.hide()
            host.tree.hide()
            host.splitter.setCollapsible(0, True)   # a HIDDEN listing may really collapse to 0
            host.set_pane_keys_enabled(False)
            host._sync_secondary_ui()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a pane built before the rows exist
        return True

    def restore_viewer(self) -> bool:
        """Move the viewer back to its HOME pane; True — it really moved. Never raises.

        The home splitter shows the panel again (hidden) and the borrowing pane gets its listing
        rows back; a pane that is being TORN DOWN never takes the viewer with it (the container
        calls this before it destroys the pane).
        """
        host = self._viewer_host
        if host is None:
            return False
        self._viewer_host = None
        self._viewer_from = None
        try:
            self.viewer.hide()
        except RuntimeError:
            pass  # Qt teardown — the panel is already gone
        home = self._viewer_home
        if home is not None and home is not host:
            try:
                home.splitter.addWidget(self.viewer)
            except RuntimeError:
                pass  # Qt teardown — the home pane is already gone
        try:
            # `_restore_listing()` clears the borrowing flag itself and puts the host's own rows
            # (its address bar, its buttons or its hints) back.
            host._restore_listing()
        except (RuntimeError, AttributeError):
            pass
        try:
            if home is not None:
                home._sync_secondary_ui()
        except (RuntimeError, AttributeError):
            pass  # the home pane is gone / has no rows yet
        return True

    # ── v1.4.7 (ROADMAP task 3/4): the lazy syntax highlighting ─────────────

    def _ensure_highlighter(self):
        """The pane's ONE highlighter (built on the first preview, reused after).

        A viewer must keep working when the highlighter cannot be built (an
        exotic Qt build): the preview then stays monochrome, which is exactly
        the v1.3.1 behaviour.
        """
        if self._highlighter is None:
            try:
                self._highlighter = syntax.create_highlighter(
                    self.viewer_text.document())
            except Exception:   # noqa: BLE001 — highlighting is never critical
                self._highlighter = None
        return self._highlighter

    # ── v1.7.3 (task 4): the reader's word wrap ─────────────────────────────

    def _build_viewer_menu(self):
        """The reader's menu: Qt's OWN standard one PLUS the ONE app row (`Word wrap`).

        `createStandardContextMenu()` carries Copy / Select All translated by Qt itself (no i18n
        key of ours), so the app row is APPENDED after a separator — the same seam shape as
        `_build_context_menu()`: the tests trigger the QAction directly and never run `exec()`.
        """
        menu = self.viewer_text.createStandardContextMenu()
        menu.addSeparator()
        act = QAction(_t("sftp.viewer.word_wrap"), menu)
        act.setCheckable(True)
        act.setChecked(bool(self._viewer_wrap))
        act.toggled.connect(self._on_wrap_toggled)
        menu.addAction(act)
        self._wrap_action = act
        return menu

    def _on_viewer_menu(self, pos):
        """Show the reader's menu at the click (the event is the only caller of the seam)."""
        try:
            menu = self._build_viewer_menu()
            menu.exec(self.viewer_text.viewport().mapToGlobal(pos))
            menu.deleteLater()
        except RuntimeError:
            return   # Qt teardown — the panel is already gone

    def _on_wrap_toggled(self, on: bool):
        """The row was toggled: the CONTAINER owns the ONE global setting (v1.7.3)."""
        apply_all = getattr(self._container, "apply_viewer_wrap", None)
        if callable(apply_all):
            try:
                apply_all(bool(on))
                return
            except RuntimeError:
                return   # Qt teardown — nothing left to re-text
        self.set_viewer_wrap(on)

    def _apply_viewer_wrap(self):
        """Write the mode into the widget and re-run the lazy pass (the wrap changes the window).

        Never raises: a viewer without the enum (an exotic Qt build) keeps the shipped no-wrap look.
        """
        mode = (QPlainTextEdit.LineWrapMode.WidgetWidth if self._viewer_wrap
                else QPlainTextEdit.LineWrapMode.NoWrap)
        try:
            self.viewer_text.setLineWrapMode(mode)
        except (RuntimeError, AttributeError):
            return
        self._highlight_range = None
        self._highlight_visible(force=True)

    def set_viewer_wrap(self, on, persist: bool = True) -> bool:
        """Set the reader's word wrap for THIS pane (the container walks the rest)."""
        self._viewer_wrap = bool(on)
        self._apply_viewer_wrap()
        act = getattr(self, "_wrap_action", None)
        if act is not None:
            try:
                act.setChecked(self._viewer_wrap)
            except RuntimeError:
                pass   # Qt teardown — the menu is already gone
        if persist:
            return save_viewer_wrap(self._viewer_wrap)
        return True

    @property
    def viewer_wrap(self) -> bool:
        """Is the reader wrapping long lines (the topical seam)?"""
        return bool(self._viewer_wrap)

    def _lazy_margin(self) -> int:
        """The blocks the lazy window keeps around the viewport.

        Under wrapping ONE block covers SEVERAL visual rows, so the block margin is widened: the
        same visual distance stays formatted around the viewport (the measured seam of the mode).
        """
        if self._viewer_wrap:
            return self.VIEWER_LAZY_MARGIN * self.WRAP_MARGIN_FACTOR
        return self.VIEWER_LAZY_MARGIN

    def _viewer_block_range(self):
        """The block numbers on the screen → `(first, last)`, or None.

        Measured from the LAYOUT (`blockBoundingGeometry` + `contentOffset`), so
        it answers correctly for a hidden panel too (it degrades to block 0).
        """
        edit = self.viewer_text
        try:
            block = edit.firstVisibleBlock()
            if not block.isValid():
                return None
            height = edit.viewport().height()
            offset = edit.contentOffset()
            first = last = block.blockNumber()
            while block.isValid():
                if edit.blockBoundingGeometry(block).translated(offset).top() > height:
                    break
                last = block.blockNumber()
                block = block.next()
            return first, last
        except RuntimeError:
            return None   # the C++ object was already destroyed (a close race)

    def _highlight_visible(self, force: bool = False) -> int:
        """Format the blocks around the viewport (v1.4.7 task 4 — the lazy half).

        A 1 MB file is ~20 000 blocks and `setPlainText()` marks every one of
        them dirty, so the EXPENSIVE half (turning spans into text formats) is
        applied only to the visible window ± `VIEWER_LAZY_MARGIN`; the block
        STATE is still computed for every line, because the state of a line
        depends on the line before it. A repeated call whose window is already
        done costs one comparison.

        Returns the number of blocks really rehighlighted.
        """
        highlighter = self._highlighter
        if highlighter is None:
            return 0
        window = self._viewer_block_range()
        if window is None:
            return 0
        margin = self._lazy_margin()
        first = max(0, window[0] - margin)
        last = window[1] + margin
        if not force and (first, last) == self._highlight_range:
            return 0
        self._highlight_range = (first, last)
        highlighter.set_window(first, last)
        return highlighter.highlight_window(force=force)

    def _on_viewer_update_request(self, _rect, dy):
        """`QPlainTextEdit.updateRequest`: a scroll (`dy != 0`) or a resize.

        A hidden panel is skipped: the content of a closed viewer is gone, and
        `clear()` fires the signal while it empties the document — formatting a
        block nobody can see would only leave a mark behind.
        """
        if self.viewer.isHidden():
            return
        self._highlight_visible()

    @property
    def viewer_highlighter(self):
        """The pane's highlighter (None until the first preview — the test seam)."""
        return self._highlighter

    @property
    def viewer_language(self) -> str:
        """The language the shown content was detected as (v1.4.7)."""
        return self._viewer_language

    @property
    def viewer_encoding(self) -> str:
        """The encoding of the shown content ("utf-8" | "latin-1")."""
        return self._viewer_encoding

    def close_viewer(self):
        """v1.3.1: hide the panel and drop its content.

        Idempotent and never raises: it is called by the header's ×, by the
        container's `set_worker(None)` (the worker died) and by the single page
        teardown (page.shutdown()) — the preview closes together with the session.

        v1.7rc3: a BORROWED panel goes back to the pane it belongs to first (the other pane gets
        its listing and its address bar back), so closing the preview always restores the two-pane
        look the user had before it.
        """
        self._read_tasks.clear()
        self._last_read = None
        # v1.4.7: the panel is empty → the formatting pass has nothing to cover.
        self._highlight_range = None
        self._viewer_open = False
        if self._highlighter is not None:
            self._highlighter.reset_for_document()
        self.restore_viewer()
        try:
            self.viewer.hide()
            self.viewer_text.clear()
            self.viewer_label.clear()
            self.viewer_label.setToolTip("")
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race) — nothing to hide
        # v1.7rc3: this pane may have been the CARRYING one while the panel belonged to its
        # sibling — its own path row and key hints come back with the panel's closing.
        if getattr(self, "_viewer_borrowed", False):
            self._viewer_borrowed = False
            self._viewer_host = None
            try:
                self.path_label.show()
            except RuntimeError:
                pass
            self._sync_secondary_ui()

    # ── Operations (buttons) ─────────────────────────────────────────────

    def _on_upload(self):
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, _t("sftp.upload_dialog_title"))
        if not files:
            return   # the dialog was cancelled
        self._queue_uploads(files, self._current_dir,
                            self._names_in_current_dir())

    def _on_download(self):
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        items = [i for i in self.tree.selectedItems()
                 if not i.data(0, self.ISDIR_ROLE)]
        if not items:
            self.message.emit(_t("sftp.no_selection"))
            return
        local_dir = QFileDialog.getExistingDirectory(
            self, _t("sftp.download_dir_title"))
        if not local_dir:  # dialog cancelled — quietly do nothing
            return
        self._queue_downloads(items, local_dir)

    def _on_cancel(self):
        # v1.7.3: a running `Send to…` is cancelled with the queue it uses — the relay drops its
        # spool on the way out (a cancel must never leave a plaintext copy behind).
        cancel_sends = getattr(self._container, "cancel_sends", None)
        if callable(cancel_sends):
            try:
                cancel_sends()
            except RuntimeError:
                pass   # Qt teardown — the container is already gone
        if self.worker is not None:
            self.worker.cancel()

    # ── v1.3.3.2: the batch + the overwrite conflict (ROADMAP task 2) ────

    def _names_in_current_dir(self) -> set:
        """The names the CURRENT listing shows.

        The conflict check must never be a guess, and the tree is exactly what the
        server last answered for the shown directory (a row of another directory
        cannot be in it).
        """
        names = set()
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is self._up_item:
                    continue
                names.add(item.text(0))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        return names

    def _ask_conflict(self, name: str, target: str, remaining: int, facts: str = ""):
        """The overwrite question — a method so a test can replace the whole policy."""
        return ask_conflict(self, name, target, remaining, facts)

    def _conflict_decision(self, name: str, target: str, remaining: int):
        """The decision of ONE conflict → `(action, apply_all)`.

        action ∈ `"overwrite" | "skip" | "rename"`; a cancelled dialog — and any
        broken answer of a replaced seam — is a SKIP: the destination is left alone
        and the batch goes on. `apply_all` asks to reuse the decision for the REST
        of this batch (never for "rename": a batch rename needs a name per file).
        """
        try:
            action, apply_all = self._ask_conflict(name, target, remaining)
        except Exception:   # noqa: BLE001 — a dialog must never break a transfer
            return "skip", False
        if action not in ("overwrite", "skip", "rename"):
            return "skip", False
        if action == "rename":
            return action, False
        return action, bool(apply_all)

    def _prompt_name(self, title: str, current: str = "") -> str:
        """The name input of New folder / Rename (QInputDialog — a module attribute:
        `STAB.QInputDialog = <fake>` is the test seam).

        Returns the validated name; "" — cancelled or invalid (empty, ".", "..",
        a path separator): the caller quietly does nothing. The worker never sees a
        name it would have to sanitize.
        """
        try:
            text, ok = QInputDialog.getText(self, title, _t("sftp.op.name_prompt"),
                                            text=current)
        except Exception:   # noqa: BLE001 — a dialog must never break the pane
            return ""
        if not ok:
            return ""
        name = (text or "").strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            self.message.emit(_t("sftp.op.invalid_name"))
            return ""
        return name

    def _queue_uploads(self, files: list, target_dir: str, known: set):
        """Queue a batch of local files into target_dir, resolving the conflicts.

        `known` — the names already present in target_dir (from a LISTING of that
        directory: the current listing for the Upload button and for a drop on the
        body, the pre-flight listing for a drop on a directory row). "Apply to all"
        of the dialog is remembered for the REST of this batch only — the question is
        asked ONCE per batch, whichever pane started it.
        """
        worker = self.worker
        if worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        apply_all = ""
        total = len(files)
        for index, local_path in enumerate(files):
            name = os.path.basename(local_path)
            if name in known:
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, target_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        continue   # cancelled → this file is skipped
                    name = new_name
            self._remember_transfer(worker.queue_upload(local_path, target_dir,
                                                        remote_name=name))

    def _queue_downloads(self, items: list, local_dir: str):
        """Queue a batch of remote files into local_dir, resolving the conflicts.

        The local existence check is a plain `os.path.exists` — no listing and no
        network, so it can never be stale.
        """
        worker = self.worker
        if worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        apply_all = ""
        total = len(items)
        for index, item in enumerate(items):
            remote_path = item.data(0, self.PATH_ROLE)
            name = posixpath.basename(remote_path)
            if os.path.exists(os.path.join(local_dir, name)):
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, local_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        continue
                    name = new_name
            self._remember_transfer(worker.queue_download(remote_path, local_dir,
                                                          item.data(0, self.SIZE_ROLE),
                                                          local_name=name))

    def _remember_transfer(self, task_id):
        """v1.7rc1: remember a transfer THIS pane queued.

        The "Cancel" button is per pane while the QUEUE is one: only the pane that
        started the transfer lights its button up, so a pane never offers to cancel a
        batch the user began in the other one (the click still cancels the SHARED queue —
        that is what "Cancel" means).
        """
        if task_id is not None:
            self._own_transfers.add(task_id)

    # ── v1.7rc2: the remote copy / move of a batch (ROADMAP v1.7rc2) ─────

    def _rows_for_batch(self) -> list:
        """The rows a copy/move batch acts on (v1.7rc2).

        The SELECTION is the batch — the classic commander behaviour, and the reason the
        overwrite question can be answered "apply to all" ONCE for the whole run. An empty
        selection falls back to the CURRENT row (one click selects a row anyway); the ".."
        row and any row without a path are never part of a batch.
        """
        rows = []
        try:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item is self._up_item or not item.data(0, self.PATH_ROLE):
                    continue
                if item.isSelected():
                    rows.append(item)
        except RuntimeError:
            return []   # Qt teardown — the tree is already gone
        if not rows:
            current = self._current_row()
            if current is not None:
                rows = [current]
        return rows

    def _remote_batch(self, kind: str, target_pane):
        """Queue ONE copy/move batch of the selection into the OTHER pane's directory.

        The destination directory IS the other pane's listing, so the conflict check needs
        no listing of its own (the shipped `_names_in_current_dir()` rule: what the server
        last answered for that directory). A DIRECTORY row is part of the batch — v1.7rc2
        copies and moves trees recursively — and a row whose destination would be ITSELF
        is skipped, because copying or moving a file onto itself is not an operation. The
        overwrite/skip/rename question is asked through the SHIPPED machinery and its "apply
        to all" answer holds for the rest of this batch only.

        v1.7.3: the body moved into `_queue_transfer_batch()` — the pane-to-pane drop needs
        exactly the same batch over a SOURCE LIST that is not the selection.
        """
        worker = self.worker
        if worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        rows = self._rows_for_batch()
        if not rows:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        items = [(row.data(0, self.PATH_ROLE), row.text(0)) for row in rows]
        self._queue_transfer_batch(items, kind, target_pane.current_dir,
                                   target_pane._names_in_current_dir())

    def _queue_transfer_batch(self, items: list, kind: str, target_dir: str, known: set):
        """ONE copy/move batch of `(source, row_name)` pairs into `target_dir` (v1.7rc2/v1.7.3).

        `known` is the destination's listing as it is on the screen (never a guess), the ".."
        row and a pathless row are never part of a batch, a row that already IS the destination
        is skipped, and the ONE closing report counts copied / skipped / failed.
        """
        worker = self.worker
        if worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        total = len(items)
        skipped = 0
        queued = []
        apply_all = ""
        for index, (source, row_name) in enumerate(items):
            if not source:
                skipped += 1
                continue
            name = posixpath.basename(source)
            if posixpath.join(target_dir or "/", name) == source:
                skipped += 1   # the row already IS the destination — never an operation
                continue
            if name in known:
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, target_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    skipped += 1
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        skipped += 1
                        continue
                    name = new_name
            queued.append((source, name))
        batch_id = self._open_batch(kind, len(queued), skipped)
        for source, name in queued:
            if kind == KIND_COPY:
                task_id = worker.queue_copy(source, target_dir, name)
            else:
                task_id = worker.queue_move(source, target_dir, name)
            if task_id is None:
                self._count_batch(batch_id, "failed")   # the worker is gone — still an answer
                continue
            self._op_batches[task_id] = batch_id
            self._queue_op(task_id, kind)
            if kind == KIND_COPY:
                self._remember_transfer(task_id)   # the progress bar + the Cancel button
        if not queued:
            self._finish_batch(batch_id)   # everything was skipped — the report says so
            return
        self.message.emit(_t("sftp.cmd.batch_started", count=len(queued), dir=target_dir))

    def _open_batch(self, kind: str, total: int, skipped: int) -> int:
        """Open a batch record and return its id (the counters of ONE report, v1.7rc2)."""
        self._batch_seq += 1
        self._batches[self._batch_seq] = {"op": kind, "total": int(total), "done": 0,
                                          "failed": 0, "skipped": int(skipped), "answers": 0}
        return self._batch_seq

    def _count_batch(self, batch_id, key: str):
        """Count ONE answer of a batch; the last answer emits the ONE report (v1.7rc2).

        Every queued item produces exactly one answer (done / failed / cancelled — a
        cancelled item counts as failed, it was not transferred), so the report cannot be
        emitted early or stay silent.
        """
        record = self._batches.get(batch_id)
        if record is None:
            return
        record[key] = int(record.get(key, 0)) + 1
        record["answers"] = int(record.get("answers", 0)) + 1
        if record["answers"] >= record["total"]:
            self._finish_batch(batch_id)

    def _finish_batch(self, batch_id):
        """Emit the ONE closing report of a batch and forget it (v1.7rc2)."""
        record = self._batches.pop(batch_id, None)
        if record is None:
            return
        key = "sftp.cmd.copy_report" if record.get("op") == KIND_COPY else "sftp.cmd.move_report"
        self.message.emit(_t(key, done=record.get("done", 0), skipped=record.get("skipped", 0),
                             failed=record.get("failed", 0)))

    def _answer_batch_task(self, task_id, outcome: str):
        """Count the answer of ONE queued copy/move task into its batch (v1.7rc2)."""
        batch_id = self._op_batches.pop(task_id, None)
        if batch_id is None:
            return   # not a batch task of this pane (another pane's, or already counted)
        self._count_batch(batch_id, outcome)

    def _remote_error_text(self, message: str) -> str:
        """The task_error of a copy/move → a translated sentence (v1.7rc2).

        The worker reports a MACHINE payload for the three cases it knows (`parse_task_payload`):
        a PARTIALLY transferred tree (with its counters), a REFUSED cross-directory rename (the
        sentence names the fallback: copy + delete) and a tree over its declared bound. Any
        other message is the server's own error and goes through the shipped `sftp.op.error`.
        """
        data = parse_task_payload(message)
        code = data.get("code") if data else None
        if code == PARTIAL_CODE:
            copied = data.get("copied", 0)
            path = str(data.get("path") or "")
            return _t("sftp.cmd.partial", name=posixpath.basename(path) or path,
                      copied=copied, error=str(data.get("error") or ""))
        if code == MOVE_ERROR_REFUSED:
            return _t("sftp.cmd.move_refused", error=str(data.get("error") or ""))
        if code == TREE_ERROR_TOO_BIG:
            return _t("sftp.cmd.tree_too_big",
                      limit=int(data.get("limit") or MAX_TREE_ENTRIES))
        return _t("sftp.op.error", error=message)

    # ── v1.3.3.2: the file operations (ROADMAP task 1) ───────────────────

    def _on_context_menu(self, pos):
        """The tree's context menu (the seam is `_build_context_menu(item)`)."""
        try:
            item = self.tree.itemAt(pos)
        except RuntimeError:
            return   # the C++ object is already deleted (a close race)
        self.activate()   # the row menu belongs to the pane it was opened in
        menu = self._build_context_menu(item)
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, item=None):
        """New folder / Rename / Delete / Copy remote path (a test seam: the tests
        trigger the QActions directly — `menu.exec()` never runs offscreen).

        Rename/Delete/Copy are enabled only for a REAL row of the current listing
        (never for the ".." row, never for empty space) — a disabled item is the
        hint, the actions themselves stay defensive.
        """
        menu = QMenu(self)
        act_new = menu.addAction(_t("sftp.op.new_folder"))
        act_rename = menu.addAction(_t("sftp.op.rename"))
        act_delete = menu.addAction(_t("sftp.op.delete"))
        act_copy = menu.addAction(_t("sftp.op.copy_path"))
        # v1.7.3 (task 1): `Send to ▸ <session>` — the rows of the sessions open RIGHT NOW.
        sub = self._build_send_menu(item)
        if sub is not None:
            menu.addMenu(sub)
        menu.addSeparator()
        act_refresh = menu.addAction(_t("sftp.refresh"))

        real = (item is not None and item is not self._up_item
                and bool(item.data(0, self.PATH_ROLE)))
        for act in (act_rename, act_delete, act_copy):
            act.setEnabled(bool(real))

        act_new.triggered.connect(lambda: self._op_new_folder())
        act_refresh.triggered.connect(lambda: self._relist(self._current_dir))
        if real:
            act_rename.triggered.connect(lambda: self._op_rename(item))
            act_delete.triggered.connect(lambda: self._op_delete(item))
            act_copy.triggered.connect(lambda: self._op_copy_path(item))
        return menu

    # ── v1.7.3 (task 1): `Send to ▸ <session>` — the cross-session relay ──

    def _build_send_menu(self, item):
        """The `Send to ▸ <session>` submenu of one row (None — an empty space, no row at all).

        The sessions come from the CONTAINER's provider, so this module never learns where a window
        keeps its registry. A row that is not a FILE answers ONE sentence (a directory crosses
        through the two panes, the relay carries files) and a session list that is empty says so
        instead of offering a dead menu — both are DISABLED rows, which is the shipped hint rule.
        """
        if item is None or item is self._up_item or not item.data(0, self.PATH_ROLE):
            return None
        menu = QMenu(_t("sftp.send.menu"), self)
        if item.data(0, self.ISDIR_ROLE):
            menu.addAction(_t("sftp.send.no_file")).setEnabled(False)
            return menu
        targets = self._container.send_targets() if self._container is not None else []
        if not targets:
            menu.addAction(_t("sftp.send.no_targets")).setEnabled(False)
            return menu
        for target in targets:
            label = target.label or target.host or "?"
            act = menu.addAction(f"{label} ({target.directory or '/'})")
            act.triggered.connect(lambda _checked=False, t=target, i=item: self._op_send_to(i, t))
        return menu

    def _op_send_to(self, item, target):
        """Send ONE file row to another session (the size gate, then the container's relay)."""
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE) if item is not None else ""
        if not path or (item is not None and item.data(0, self.ISDIR_ROLE)):
            self.message.emit(_t("sftp.send.no_file"))
            return
        size = int(item.data(0, self.SIZE_ROLE) or 0)
        # The declared ceiling is checked BEFORE anything is transferred (the ask's own number).
        if not send.size_allowed(size):
            self.message.emit(_t("sftp.send.too_big", name=posixpath.basename(path),
                                 size=format_size(size), limit=format_size(send.MAX_SEND_BYTES)))
            return
        entry = {"path": path, "name": posixpath.basename(path), "size": size,
                 "mtime": int(item.data(0, self.MTIME_ROLE) or 0)}
        if self._container is None:
            return
        self._container.start_send(self, target, entry)

    def _op_new_folder(self):
        """New folder in the CURRENT directory (mkdir through the worker queue)."""
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        name = self._prompt_name(_t("sftp.op.new_folder"))
        if not name:
            return
        self._queue_op(self.worker.queue_mkdir(self._current_dir, name), KIND_MKDIR)

    def _op_rename(self, item):
        """Rename a row inside its own directory (only the NAME changes)."""
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        current = posixpath.basename(path)
        name = self._prompt_name(_t("sftp.op.rename"), current)
        if not name or name == current:
            return   # cancelled, or the name did not change — nothing to do
        self._queue_op(self.worker.queue_rename(path, name), KIND_RENAME)

    def _op_delete(self, item):
        """Delete a row — with a confirmation (QMessageBox — a module attribute).

        A directory is removed with rmdir: a NON-EMPTY one reports the server's
        error (recursive delete is not in this version).
        """
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        is_dir = bool(item.data(0, self.ISDIR_ROLE))
        box = QMessageBox   # the monkeypatch STAB.QMessageBox works in the tests
        reply = box.question(
            self, _t("sftp.op.delete"),
            _t("sftp.op.delete_confirm", name=posixpath.basename(path)),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return
        self._queue_op(self.worker.queue_delete(path, is_dir), KIND_DELETE)

    def _op_copy_path(self, item):
        """Copy the REMOTE path of the row to the clipboard (never a URL)."""
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        try:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(str(path))
        except Exception:   # noqa: BLE001 — the clipboard is not critical
            pass
        self.message.emit(_t("sftp.op.path_copied"))

    def _queue_op(self, task_id, kind: str):
        """Remember an operation task: its answer refreshes the listing (task_done)
        or reports a message (task_error)."""
        if task_id is not None:
            self._op_tasks[task_id] = kind

    # ── D&D: files from Explorer (v1.2.8) ────────────────────────────────

    _DRAG_TYPES = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)

    def eventFilter(self, obj, event):
        """Drag events on the pane's children are forwarded to the pane's OWN
        handlers. Returning True = the event is consumed (QTreeWidget does not
        process it "its own way").

        v1.3.3.2: the SOURCE widget of the event is remembered for the drop — the
        directory under the cursor is resolved in the tree's coordinates whatever
        child (viewport, header, button) received the event.

        v1.7rc1: a keyboard FocusIn anywhere inside the pane makes it the ACTIVE pane of
        the container (the event is NOT consumed — the widget keeps the focus).

        v1.7rc3: a KEY of the pane's walk (`Tab`/`Shift+Tab`, `Enter`, `Insert`/`Space`,
        `Backspace`, `Left`) is answered here too, so it fires from the address bar, a button
        or the hint row and not only from the tree. The completer's popup is the ONE exception:
        while it is open `Tab`/`Enter` complete the typed path (the shipped behaviour), so the
        popup's events are left to Qt.
        """
        etype = event.type()
        # `obj is self._container` is "the tab itself" — the shipped production path (with DragOnly
        # the tree's viewport refuses drops, so Qt hands them to the tab), where the point is in the
        # TAB's coordinates and is mapped back to the tree. The pane's OWN viewer counts as this pane
        # even while it is BORROWED by the other one (a re-parented widget is nobody's descendant any
        # more), so a key typed into the open panel still reaches the walk (`AGENTS.md` §4.24).
        mine = (obj is self or obj is self._container or self.isAncestorOf(obj)
                or obj is self.viewer or self.viewer.isAncestorOf(obj))
        if etype in self._DRAG_TYPES and mine:
            self._drag_source = obj
            try:
                if etype == QEvent.Type.DragEnter:
                    self.dragEnterEvent(event)
                elif etype == QEvent.Type.DragMove:
                    self.dragMoveEvent(event)
                else:  # Drop
                    self.dropEvent(event)
            finally:
                self._drag_source = None
            return True
        if etype == QEvent.Type.FocusIn and mine:
            self.activate()
        # v1.7rc3: the walk of the two-pane view — the tree has its own `keyPressEvent` hook,
        # the pane answers for every OTHER widget it owns (Tab must switch the panes from the
        # address bar or a button as well).
        if etype == QEvent.Type.KeyPress and mine and obj is not self.tree and not self._popup_open():
            if self._on_pane_key(event):
                return True
        return False

    def _popup_open(self) -> bool:
        """True while the address bar's completer popup has the keyboard (v1.7rc3)."""
        try:
            popup = self.path_completer.popup()
            return popup is not None and popup.isVisible()
        except (RuntimeError, AttributeError):
            return False

    @staticmethod
    def local_files(mime_data) -> list:
        """The module function of the same name (the drag payload of a drop)."""
        return local_files(mime_data)

    def dragEnterEvent(self, event):
        # v1.7.3: a row of ANOTHER Files pane is a payload of its own (the private mime type) —
        # `local_files()` cannot see it and the drop below is a copy or a move.
        if local_files(event.mimeData()) or pane_payload(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # Same answer as dragEnter — otherwise Qt will reset the action before Drop.
        if local_files(event.mimeData()) or pane_payload(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        # v1.7.3 (task 3): a row dragged out of a pane and dropped INTO a pane is the v1.7rc2
        # copy (a MOVE with `Shift`) with a PANE as its destination.
        payload = pane_payload(event.mimeData())
        if payload is not None:
            event.acceptProposedAction()
            self._on_pane_drop(payload, event)
            return
        target = self._drop_target_dir(event)
        files = local_files(event.mimeData())
        if files:
            event.acceptProposedAction()
        self._on_drop(files, target)

    @staticmethod
    def _drop_is_move(event) -> bool:
        """Is this drop a MOVE? `Shift`+drop is one (the classic commander reading)."""
        try:
            if event.dropAction() == Qt.DropAction.MoveAction:
                return True
        except (AttributeError, RuntimeError):
            pass   # an exotic event object without the action — the modifier decides
        try:
            return bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        except (AttributeError, RuntimeError):
            return False

    def _on_pane_drop(self, payload: dict, event):
        """A row of a pane dropped into THIS pane: copy, or move with `Shift` (v1.7.3).

        TWO refusals are declared and each answers ONE sentence: the row may come from THIS pane
        (nothing to copy), and it may belong to ANOTHER session — there is no server-to-server
        path, so a file crosses between servers through `Send to…`, never through a drag.
        """
        if payload.get("pane") == id(self):
            self.message.emit(_t("sftp.cmd.drop_same_pane"))
            return
        if not self.session_key() or payload.get("session") != self.session_key():
            self.message.emit(_t("sftp.cmd.drop_other_session"))
            return
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        source = str(payload.get("path") or "")
        if not source:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        items = [(source, posixpath.basename(source))]
        kind = KIND_MOVE if self._drop_is_move(event) else KIND_COPY
        target_dir = self._drop_target_dir(event) or self._current_dir
        if target_dir == self._current_dir:
            self._queue_transfer_batch(items, kind, target_dir, self._names_in_current_dir())
            return
        # The destination row is not on the screen: LIST it first (the shipped pre-flight rule) so
        # the conflict question is the server's own answer.
        task_id = self.worker.queue_list(target_dir)
        if task_id is None:
            self._queue_transfer_batch(items, kind, target_dir, set())
            return
        self._pending_drops[task_id] = (items, kind, target_dir)

    def _item_under(self, event):
        """The listing row under a drag event (None — empty space / outside the tree).

        The event may arrive from any child (the pane's eventFilter forwards it): the
        point is mapped into the viewport's coordinates first, so the row is found
        regardless of who received the event.
        """
        try:
            pos = event.position().toPoint()
        except AttributeError:   # an older event object without position()
            pos = event.pos()
        source = self._drag_source or self
        try:
            if source is not self.tree.viewport():
                pos = self.tree.viewport().mapFrom(source, pos)
            return self.tree.itemAt(pos)
        except (RuntimeError, TypeError):
            return None   # the C++ object is gone / the source is not an ancestor

    def _drop_target_dir(self, event) -> str:
        """v1.3.3.2 (ROADMAP task 4): the directory UNDER THE CURSOR.

        A directory row (including "..") is the target; a file row and empty space
        keep the current directory — the second half of the "drop into a specific
        row" promise quoted in the goal of the version.
        """
        item = self._item_under(event)
        if item is not None and item.data(0, self.ISDIR_ROLE):
            return item.data(0, self.PATH_ROLE) or self._current_dir
        return self._current_dir

    def _on_drop(self, files: list, target_dir: str = ""):
        """Drop result: upload into the directory under the cursor.

        The conflict check must not be a guess, so a target directory that is NOT on
        the screen is LISTED first (a "list" task of the same queue) and the batch is
        queued when the answer arrives — see `_on_list_ready`.
        """
        target = target_dir or self._current_dir
        if not files:
            # No local files in the drag (directories/other data).
            self.message.emit(_t("sftp.drop_no_files"))
            return
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        if target == self._current_dir:
            # The listing on the screen IS the answer of the server for that
            # directory — the conflict check needs nothing else.
            self._queue_uploads(files, target, self._names_in_current_dir())
        else:
            task_id = self.worker.queue_list(target)
            if task_id is not None:
                self._pending_batches[task_id] = (target, files)
                return   # the hint + the uploads follow the listing answer
            self._queue_uploads(files, target, set())
        self.message.emit(_t("sftp.drop_queued", count=len(files), dir=target))

    # ── Transfer state (the "Cancel" button) ─────────────────────────────

    def _on_task_started(self, task_id: int, kind: str, _label: str):
        if kind in ("upload", "download", "copy") and task_id in self._own_transfers:
            self._transfer_tasks.add(task_id)
            self.btn_cancel.setEnabled(True)

    def _on_task_done(self, task_id: int, detail: str):
        """task_done: an OPERATION refreshes the listing (v1.3.3.2) and reports the
        result; a transfer and a read keep their v1.1.3/v1.3.1 handling.

        v1.7rc2: a remote copy/move reports through its BATCH (one closing report instead
        of one line per file) and re-lists EVERY pane showing a directory it touched — the
        destination changed, and a move also emptied the source.
        """
        kind = self._op_tasks.pop(task_id, None)
        if kind in (KIND_COPY, KIND_MOVE):
            self._container.relist_dir(posixpath.dirname(detail))
            if kind == KIND_MOVE:
                self._container.relist_dir(self._current_dir)
            self._answer_batch_task(task_id, "done")
            self._on_task_finished(task_id)
            return
        if kind is not None:
            self.message.emit(_t("sftp.op.done", name=detail))
            self._relist(self._current_dir)
        self._on_task_finished(task_id)

    def _on_task_cancelled(self, task_id: int, _kind: str):
        kind = self._op_tasks.pop(task_id, None)
        # A cancelled pre-flight listing: its batch will never be queued (the
        # bookkeeping must not leak into the next transport).
        self._pending_batches.pop(task_id, None)
        if kind in (KIND_COPY, KIND_MOVE):
            # v1.7rc2: the item was not transferred — it counts as a failure of its batch
            # (the window's status bar has already said "Transfer cancelled").
            self._answer_batch_task(task_id, "failed")
        self._on_task_finished(task_id)

    def _on_task_finished(self, task_id: int):
        # v1.3.1: a read task that ended without an answer (cancelled) leaves no trace.
        self._read_tasks.pop(task_id, None)
        # v1.6.3: the same for the address bar's tasks and the completer's listings.
        self._normalize_tasks.pop(task_id, None)
        self._completer_lists.pop(task_id, None)
        self._own_transfers.discard(task_id)
        if task_id in self._transfer_tasks:
            self._transfer_tasks.discard(task_id)
            if not self._transfer_tasks:
                self.btn_cancel.setEnabled(False)


class CommanderCorner(QWidget):
    """v1.7rc1 (ROADMAP v1.7rc1, task 3): the tab-bar corner control of the two-pane view.

    ONE checkable QAction (`sftp.commander`) drives a BUTTON in the corner of the session
    tab bar next to the split button — the `act_split` pattern: the action is the single
    source of truth and the button is a view of it, so the checkmark and the pane state can
    never diverge.

    The control belongs to the CONTAINER (the corner is the tab bar's), while the STATE is
    the SESSION's (each `SftpTab` knows whether it shows two panes): the container calls
    `set_state()` whenever the active session changes, and the action is DISABLED while the
    active session has no Files tab (a split pane). The corner holds exactly TWO controls —
    the split button and this one — and the Files panel of the WINDOW is NOT a third: since
    v1.7.1.1 that mode is a SETTING (`terminal_files_mode`, the settings hub's "Files display
    mode"), so the pair keeps the floor the window's own minimum width is built on and this
    action is disabled only while the panel is on for another reason (the panel mode is
    single-pane). Never raises — the corner is chrome.
    """

    def __init__(self, parent=None, split_button=None):
        super().__init__(parent)
        self.setObjectName("sftpCommanderCorner")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.act = QAction(_t("sftp.commander"), self)
        self.act.setCheckable(True)
        self.act.setToolTip(_t("sftp.commander_tooltip"))
        self.btn = QPushButton(_t("sftp.commander"))
        self.btn.setCheckable(True)
        self.btn.setToolTip(_t("sftp.commander_tooltip"))
        self.btn.clicked.connect(self._on_button_clicked)
        self.act.toggled.connect(self._sync_button)
        if split_button is not None:
            row.addWidget(split_button)
        row.addWidget(self.btn)
        self.set_enabled(False)   # until a session tells us what it has

    def _on_button_clicked(self, _checked=False):
        """The BUTTON asks the ACTION (one source of truth), exactly like `btn_split`."""
        self.act.setChecked(bool(self.btn.isChecked()))

    def _sync_button(self, checked=None):
        """Keep the button in step with the action WITHOUT re-entering the slot."""
        try:
            if checked is None:
                checked = bool(self.act.isChecked())
            self.btn.blockSignals(True)
            self.btn.setChecked(bool(checked))
            self.btn.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown — the button is gone

    def is_commander(self) -> bool:
        """The action's state — the ONE answer the container reads."""
        return bool(self.act.isChecked())

    def set_enabled(self, on: bool):
        """Enable/disable both views (a session without a Files tab disables the action)."""
        on = bool(on)
        try:
            self.act.setEnabled(on)
            self.btn.setEnabled(on)
        except RuntimeError:
            pass  # Qt teardown

    def set_state(self, on: bool):
        """Show a session's mode WITHOUT reporting it back (the `_set_split_action_checked`
        discipline: the action's signals stay blocked, so the container is never re-entered)."""
        on = bool(on)
        try:
            self.act.blockSignals(True)
            self.act.setChecked(on)
            self.act.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown
        self._sync_button(on)

    def retranslate(self):
        """Re-text the label and the tooltip of both views (one key each)."""
        try:
            self.act.setText(_t("sftp.commander"))
            self.act.setToolTip(_t("sftp.commander_tooltip"))
            self.btn.setText(_t("sftp.commander"))
            self.btn.setToolTip(_t("sftp.commander_tooltip"))
        except RuntimeError:
            pass  # Qt teardown — the corner is already destroyed


class SftpTab(QWidget):
    """The "Files" tab: a container of 1–2 directory PANES over the queue (v1.7rc1).

    The shipped single-listing tab is the ONE-pane case of this container: the pane holds
    the widgets and the listing state, the container holds the worker binding, the session's
    "follow the shell's directory" switch, the pane splitter, the ACTIVE pane and the
    persisted mode. A shipped attribute read (`tab.tree`, `tab._blocked`, `tab._relist()`)
    resolves on the ACTIVE pane, which is what keeps every earlier contract — and the whole
    shipped suite — true.
    """

    PATH_ROLE = _SftpPane.PATH_ROLE       # the pane's row roles (class-level compatibility)
    ISDIR_ROLE = _SftpPane.ISDIR_ROLE
    SIZE_ROLE = _SftpPane.SIZE_ROLE
    MTIME_ROLE = _SftpPane.MTIME_ROLE

    VIEWER_TREE_SHARE = _SftpPane.VIEWER_TREE_SHARE
    VIEWER_LAZY_MARGIN = _SftpPane.VIEWER_LAZY_MARGIN

    #: The pane-owned state the container FORWARDS to the ACTIVE pane: a name in this set is
    #: the PANE's bookkeeping (a test writes `tab._blocked = {…}` and reads it back from the
    #: pane that really holds it), everything else on the tab address is the container's.
    PANE_STATE = frozenset({
        "_current_dir", "_pending_lists", "_transfer_tasks", "_own_transfers", "_up_item",
        "_read_tasks", "_last_read", "_viewer_encoding", "_highlighter", "_viewer_language",
        "_highlight_range", "_blocked", "_blocked_icon_cache", "_op_tasks",
        "_pending_batches", "_drag_source", "_normalize_tasks", "_completer_lists",
        "_completer_dir", "_op_batches", "_batches", "_batch_seq", "_pending_drops",
    })

    # Local hints in the window's status bar (waiting for connection, no selection).
    message = Signal(str)
    # v1.6.3 (ROADMAP task 5): the user switched the cwd follow. The TAB only reports it —
    # the session (TerminalSessionPage) installs the hook, applies it live and persists the
    # `terminal_follow_cwd` key, because the follow is a state of the SESSION, not of a view.
    follow_cwd_changed = Signal(bool)

    # The drag-payload helper of the pane, kept on the CLASS for the shipped suite
    # (`SftpTab._local_files(mime)` — a class-level read, which `__getattr__` cannot serve).
    _local_files = staticmethod(local_files)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._panes = []
        self._pane_b = None
        self._active_pane = None
        self._commander = False
        self._commander_ratio = COMMANDER_RATIO_DEFAULT
        # v1.6.3/v1.7rc1: the follow state of the SESSION — the checkbox is a VIEW of it and
        # lives on the container (one OSC 7 report, one answer).
        self._follow_cwd = False
        # v1.7.3 (task 1): the session's identity and the live sends. The KEY is the `history_key()`
        # of the server (the per-server memory uses it too), the label/host/port are what the
        # `Send to…` dialog prints and what decides the SAME-host (server-side) path; `_sends`
        # holds ONE running send per TARGET session.
        self._session_key = ""
        self._session_label = ""
        self._session_host = ""
        self._session_port = None
        self._sends = {}
        # v1.7.3 (task 2): the per-server directory memory — the map read at construction (so a
        # pane can restore a directory before anybody navigates) and the entries THIS container
        # really moved, which are the ones its own write merges into the live config.
        self._dirs = load_remembered_dirs()
        self._dirs_touched = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # v1.6.3 (ROADMAP task 5): "follow the shell's directory" — the OSC 7 switch of THIS
        # session. It is a SESSION state: the page installs the hook and persists the key, and
        # the switch belongs to the CONTAINER (v1.7rc1) so the two-pane mode cannot offer two
        # answers to the one OSC 7 report the session receives.
        self.chk_follow_cwd = QCheckBox(_t("sftp.follow_cwd"))
        self.chk_follow_cwd.setToolTip(_t("sftp.follow_cwd_tooltip"))
        self.chk_follow_cwd.setEnabled(False)   # until a transport exists
        self.chk_follow_cwd.toggled.connect(self._on_follow_toggled)
        outer.addWidget(self.chk_follow_cwd)

        # The panes: ONE pane is the shipped look, TWO are the Files Commander. The splitter
        # is present in both cases (a QSplitter with a single member draws no handle), so the
        # refactor has ONE code path.
        self.pane_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.pane_splitter.setChildrenCollapsible(False)
        self.pane_splitter.splitterMoved.connect(self._on_pane_splitter_moved)
        outer.addWidget(self.pane_splitter, 1)

        # v1.2.8/v1.7rc1: a drop that misses every pane (the follow switch, the splitter
        # handle) is still the tab's — the container forwards it to the ACTIVE pane, exactly
        # the way the shipped single-pane tab handled a drop on any of its children.
        self.setAcceptDrops(True)
        self.chk_follow_cwd.installEventFilter(self)

        pane_a = self._new_pane()
        self._active_pane = pane_a

        settings = load_commander_settings()
        self._commander_ratio = settings["ratio"]
        if settings["commander"]:
            # The mode the user left behind is restored — through the SAME path the action
            # uses, so the panes, the ratio and the persisted state cannot diverge.
            self.set_commander(True)

    # ── the pane list and the ACTIVE pane ────────────────────────────────

    @property
    def panes(self) -> list:
        """The live panes, in splitter order (the FIRST one is the shipped listing)."""
        return list(self._panes)

    @property
    def active_pane(self):
        """The pane that owns the buttons and the keys (never None while a pane exists)."""
        return self._active_pane

    @property
    def commander(self) -> bool:
        """The two-pane view is ON (the persisted `ui_sftp_commander` state)."""
        return bool(self._commander)

    # ── v1.7.3 (task 1): the session's identity and the cross-session relay ──

    def set_session_info(self, key: str = "", label: str = "", host: str = "", port=None):
        """The SESSION this container lists (called once by the page that builds it).

        The key is the `history_key()` of the server — the same fact the per-server directory
        memory is filed under — and `(host, port)` is what turns a send into the server-side
        `queue_copy()` path instead of a relay. A bare container (a unit test) simply has no
        identity: no target is offered and no directory is remembered.
        """
        self._session_key = str(key or "")
        self._session_label = str(label or "")
        self._session_host = str(host or "")
        self._session_port = port

    def session_key(self) -> str:
        """The stable identity of this session ("" — a container nobody identified)."""
        return str(self._session_key or "")

    def send_targets(self):
        """The sessions `Send to ▸` offers — resolved through the PARENT CHAIN (v1.7.3).

        The provider is the WINDOW's (`_send_session_targets`, the `_adopt_split_session`
        precedent): `modules/*` never imports `ui.main_window` (§4.1), so the hook is found by
        `find_host_hook()` and a detached container simply offers nothing. A target without a live
        SFTP worker cannot receive a file and is skipped here, once, for every caller.
        """
        provider = find_host_hook(self, "_send_session_targets")
        if not callable(provider):
            return []
        try:
            targets = provider(self.session_key()) or []
        except Exception:  # noqa: BLE001 — a broken provider must not break the menu
            return []
        return [t for t in targets if t is not None and getattr(t, "worker", None) is not None]

    def start_send(self, pane, target, entry: dict) -> bool:
        """Hand ONE row to the TARGET session's relay (v1.7.3). ONE send per session pair.

        The conversation itself lives in `modules/sftp_send.py`; the container owns the two things
        that must be true once per application state: the session's identity (the source endpoint)
        and the guard that a second send to the same target is refused with ONE sentence while the
        first one runs. The pane the user started from carries the reports.
        """
        if self._worker is None:
            pane.message.emit(_t("sftp.waiting_connection"))
            return False
        if target is None or getattr(target, "worker", None) is None:
            pane.message.emit(_t("sftp.send.no_targets"))
            return False
        key = str(getattr(target, "key", "") or "") or str(id(target))
        if key in self._sends:
            pane.message.emit(_t("sftp.send.busy",
                                 alias=getattr(target, "label", "") or getattr(target, "host", "") or "?"))
            return False
        coordinator = send.SendCoordinator(self._source_endpoint(pane), target, entry, parent=self,
                                           asker=self._send_asker(pane))
        coordinator.report.connect(pane.message.emit)
        coordinator.progress.connect(self._progress_reporter(pane, target, entry))
        coordinator.finished.connect(
            lambda result, p=pane, t=target, k=key: self._finish_send(p, t, k, result))
        self._sends[key] = coordinator
        if not coordinator.start():
            self._sends.pop(key, None)
            return False
        return True

    def _source_endpoint(self, pane) -> "send.SendEndpoint":
        """The endpoint of THIS session: its identity, its worker and the pane's directory."""
        return send.SendEndpoint(key=self.session_key(), label=self._session_label,
                                 host=self._session_host, port=self._session_port,
                                 worker=self._worker,
                                 directory=(pane.current_dir if pane is not None else "/"))

    @staticmethod
    def _send_asker(pane):
        """The pane's OWN overwrite question, adapted to the relay's `(parent, name, target, facts)`.

        The pane keeps its `_ask_conflict()` seam (the tests replace it, and the shipped dialog behind
        it), so the relay asks through the pane instead of reaching for `ask_conflict()` itself —
        the container owns the session, the PANE owns the question. "Apply to all" is never offered
        here: ONE file crosses per send.
        """
        def _ask(_parent, name, target_dir, facts=""):
            try:
                action, _apply_all = pane._ask_conflict(name, target_dir, 0, facts)
            except Exception:  # noqa: BLE001 — a dialog must never break a transfer
                return False
            return action == "overwrite"

        return _ask

    def _progress_reporter(self, pane, target, entry):
        """ONE composed progress line on the pane the user started from (1% steps at most)."""
        alias = str(getattr(target, "label", "") or getattr(target, "host", "") or "?")
        name = str(entry.get("name") or "")
        state = {"pct": -1}

        def _report(done: int, total: int):
            pct = int(done * 100 / total) if total else 0
            if pct == state["pct"]:
                return   # one line per percent — a status bar is not a progress log
            state["pct"] = pct
            try:
                pane.message.emit(_t("sftp.send.progress", name=name, alias=alias, pct=pct,
                                     done=format_size(done), total=format_size(total)))
            except RuntimeError:
                return   # Qt teardown — the pane is already gone

        return _report

    def _finish_send(self, pane, target, key: str, result: dict):
        """The ONE closing answer: forget the guard and re-list the directory that changed."""
        self._sends.pop(key, None)
        if not result.get("ok"):
            return
        refresh = getattr(target, "refresh", None)
        if not callable(refresh):
            return
        try:
            refresh(str(result.get("dir") or getattr(target, "directory", "") or ""))
        except Exception:  # noqa: BLE001 — a stale listing is not a failed send
            return

    def cancel_sends(self):
        """Cancel every send this container started (the pane's Cancel covers the relay too)."""
        for coordinator in list(self._sends.values()):
            try:
                coordinator.cancel()
            except Exception:  # noqa: BLE001 — a dead coordinator is already cancelled
                continue

    # ── v1.7.3 (task 2): the per-server directory memory ────────────────────

    def remember_dir(self, path: str) -> bool:
        """Remember the directory this session was left in (the server really answered for it)."""
        key = self.session_key()
        if not key or not str(path or "").startswith("/"):
            return False
        self._dirs = remember_dir(self._dirs, key, path)
        self._dirs_touched = remember_dir(self._dirs_touched, key, path)
        return True

    def remembered_dir(self) -> str:
        """The directory to OPEN with ("" — there is no memory / nobody identified this session)."""
        return remembered_dir_for(self._dirs, self.session_key())

    def merge_dirs_into(self, payload: dict = None) -> dict:
        """Merge the per-server memory into the window's ONE config write (v1.7.3).

        MERGE-on-write: the live config is re-read (another session may have moved meanwhile), this
        container's own entries are filed into it, and the map — capped and evicted oldest-first —
        rides out under ONE key. The commander's own payload is deliberately NOT touched here:
        `SFTP_PANES.md` §5 declares those two keys, and a third one would change that contract.
        """
        out = dict(payload) if isinstance(payload, dict) else {}
        current = out.get(DIRS_CONFIG)
        if not isinstance(current, dict):
            current = load_remembered_dirs()
        merged = dict(current)
        for key, path in self._dirs_touched.items():
            merged = remember_dir(merged, key, path)
        out[DIRS_CONFIG] = merged
        return out

    # ── v1.7.3 (task 4): the ONE global word-wrap setting ───────────────────

    def apply_viewer_wrap(self, on) -> bool:
        """Write the ONE word-wrap key and apply it to EVERY pane of this container (v1.7.3)."""
        saved = save_viewer_wrap(bool(on))
        for pane in list(self._panes):
            try:
                pane.set_viewer_wrap(on, persist=False)
            except RuntimeError:
                continue   # Qt teardown — the pane is already gone
        return saved

    def other_pane(self, pane=None):
        """The pane that is NOT `pane` — the DESTINATION of F5/F6 (v1.7rc2).

        None while the mode is off (one pane has nothing to copy to): the key then answers
        ONE honest sentence instead of a silent no-op. `pane` defaults to the ACTIVE one.
        """
        pane = pane if pane is not None else self._active_pane
        for other in list(self._panes):
            if other is not pane:
                return other
        return None

    def relist_dir(self, path: str):
        """Re-list EVERY pane that is SHOWING `path` (v1.7rc2).

        A remote copy/move changes a directory that may be on either screen: the pane that
        ran the operation owns the report, the LISTINGS are the container's business. A pane
        showing another directory is left alone (its answer is still true).
        """
        if not path:
            return
        for pane in list(self._panes):
            try:
                if pane.current_dir == path:
                    pane._relist(path)
            except RuntimeError:
                continue   # Qt teardown — the pane is already gone

    def set_active_pane(self, pane) -> bool:
        """Make `pane` the ACTIVE pane; True — the state really changed.

        The ring is drawn only in the two-pane mode: a single pane has nothing to compete
        with, and the shipped look carries no frame. Never raises.
        """
        if pane is None or pane not in self._panes:
            return False
        changed = pane is not self._active_pane
        self._active_pane = pane
        if self._commander:
            for p in self._panes:
                p.set_active(p is pane)
        return changed

    # ── v1.7rc3: the mc/far pane toggle ──────────────────────────────────

    def focus_pane(self, pane):
        """Make `pane` the ACTIVE pane AND give it the keyboard; None — it is not a pane.

        The second half is the v1.7rc3 half: the mc/far `Tab` is a PANE switch, so the keyboard
        has to land in the other pane's listing (the ring alone would leave the keys where they
        were). The ring, the buttons and the shipped tab-level reads all follow `set_active_pane`.
        """
        if pane is None or pane not in self._panes:
            return None
        self.set_active_pane(pane)
        try:
            pane.focus_listing()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the pane has no listing left to focus
        return pane

    def focus_other_pane(self, pane, back: bool = False):
        """`Tab` / `Shift+Tab` (v1.7rc3): give the keyboard to the OTHER pane.

        With ONE pane there is nothing to switch to and the answer is None — the key falls
        through to the widget (the shipped single-pane look keeps its tab order). With TWO panes
        the walk is a two-item CYCLE: from either pane the key lands on the other one, so `Tab`
        and `Shift+Tab` are inverses of each other and neither can walk out of the Files tab.
        `back` reverses the direction (the pane BEFORE this one in the splitter).
        """
        panes = list(self._panes)
        if pane not in panes or len(panes) < 2:
            return None
        index = panes.index(pane)
        step = -1 if back else 1
        return self.focus_pane(panes[(index + step) % len(panes)])

    def _sync_hint_rows(self):
        """v1.7rc3: the button row belongs to the FIRST pane, the hint row to the second.

        ONE rule for the container: in the two-pane mode only the left pane keeps the shipped
        button row (and the right one shows the key hints), in the single-pane mode the only
        pane keeps them. `_panes[0]` is the FIRST pane for the whole life of the tab — the
        second one is the one that comes and goes — which is what makes the rule idempotent.
        """
        panes = list(self._panes)
        if not panes:
            return
        first = panes[0]
        for p in panes:
            try:
                p.secondary = self._commander and p is not first
            except RuntimeError:
                continue  # Qt teardown — the pane is already gone

    # ── v1.7rc3/v1.7: the preview of the two-pane view (the mc F3) ───────

    def preview_pane(self):
        """The pane whose splitter carries an open preview (None — nothing is being previewed).

        The viewer widget is OWNED by the pane it was built in but may be CARRIED by the other one
        (`present_viewer_in()`), so the reader is asked of every pane: that single answer is what
        `close_preview()` closes and what the pane switch must not lose.
        """
        for pane in list(self._panes):
            try:
                if pane.viewer_host() is not None:
                    return pane
            except RuntimeError:
                continue  # Qt teardown — the pane is already gone
        return None

    def preview_source(self):
        """The pane whose listing opened the open preview (None — nothing is being previewed)."""
        pane = self.preview_pane()
        if pane is None:
            return None
        return pane._viewer_from or pane

    def preview_in_other_pane(self, pane) -> bool:
        """True while the OTHER pane carries a borrowed panel — a PANEL, not a listing (v1.7).

        The walk asks this before a pane switch: a pane whose listing is off the screen is not a
        destination for `Tab`/`Shift+Tab`, so the key is consumed and the reading pane keeps the
        keyboard until `Esc` closes the preview.
        """
        other = self.other_pane(pane)
        return bool(other is not None and getattr(other, "_viewer_borrowed", False))

    def preview_allowed(self, pane, report=True) -> bool:
        """May `pane` open — or be shown — a preview now? False — a panel of the OTHER pane is up.

        **ONE preview exists at a time**, and the rule is about the OWNER of the open panel: a pane
        that opens a file while its OWN panel is displayed (in its splitter or in the other pane's)
        is never in its own way — the new read replaces the content of the same widget, which is
        what walking a listing with `F3` does all day long. A file opened while the OTHER pane owns
        the open panel is REFUSED with ONE sentence (`sftp.cmd.preview_busy`), because the two
        panels would have to share one splitter.

        `report=False` is the SHOW path (`present_viewer()`): the sentence belongs to the user's key,
        and by the time an asynchronous read answers, that key is long gone — the panel then simply
        stays in its own pane instead of dressing the other one.
        """
        if pane is None or pane not in self._panes:
            return True   # a foreign pane: nothing to route, the caller keeps its in-pane panel
        if self._pane_b is None:
            return True   # ONE pane: its preview stays inside it (the shipped look)
        owner = self.preview_pane()
        if owner is None or owner is pane:
            return True
        if report:
            pane.message.emit(_t("sftp.cmd.preview_busy"))
        return False

    def present_viewer(self, pane) -> bool:
        """Show `pane`'s panel WHERE THE OTHER PANE IS (the mc `F3`); False — it stays in its own.

        Called from `_show_viewer()` — with the content already in the widget — so the OTHER pane
        only ever turns into a panel when there is really something to read in it. False for the
        ONE-pane case (the shipped in-pane panel) and for a read whose answer lost the race against
        a preview the other pane opened meanwhile (there the panel shows in its OWN pane: honest,
        and it keeps the one-preview rule true).
        """
        if pane is None or pane not in self._panes:
            return False
        other = self.other_pane(pane)
        if other is None:
            return False
        if not self.preview_allowed(pane, report=False):
            return False
        moved = bool(pane.present_viewer_in(other, source=pane))
        if moved:
            try:
                other._sync_secondary_ui()
            except RuntimeError:
                pass  # Qt teardown
        return moved

    def close_preview(self) -> bool:
        """`Esc` — close the open preview, wherever it is shown; False — there was none.

        The panel goes back to the pane it belongs to and that pane's listing (its address bar,
        its buttons or its hints) comes back; the focus stays where the keyboard was, which is the
        listing the file was opened from. False lets `Esc` fall through to the focused widget.
        """
        pane = self.preview_pane()
        if pane is None:
            return False
        try:
            pane.close_viewer()
        except RuntimeError:
            return False  # Qt teardown — there is nothing left to close
        return True

    def _restore_borrowed_viewer(self, pane):
        """Hand a borrowed preview back to its OWNER before `pane` goes away. Never raises.

        Called from `_close_viewer_of()`: the pane that is dying may be the pane CARRYING the
        viewer (then the owner takes it home) or the pane that LENT it (then the borrower gets its
        listing back). A pane with no preview involved changes nothing.
        """
        try:
            host = pane.viewer_host()
        except (RuntimeError, AttributeError):
            return
        if host is None:
            return
        for owner in list(self._panes):
            if owner is pane:
                continue
            try:
                if owner.viewer_host() is host:
                    owner.restore_viewer()
                    return
            except (RuntimeError, AttributeError):
                continue

    def _sync_active_ring(self):
        """Draw the ring on the ACTIVE pane (and only in the two-pane mode)."""
        for p in self._panes:
            p.set_active(self._commander and p is self._active_pane)

    def _new_pane(self):
        """Create a pane, wire it up and put it in the splitter (ONE construction path)."""
        pane = _SftpPane(self, self)
        pane.message.connect(self.message)
        index = self.pane_splitter.count()
        self.pane_splitter.addWidget(pane)
        self.pane_splitter.setCollapsible(index, False)
        self._panes.append(pane)
        pane.bind_worker(None, self._worker)
        return pane

    # ── v1.7rc1: the two-pane mode ───────────────────────────────────────

    def set_commander(self, on) -> bool:
        """Turn the two-pane view on/off; False — it could not be created (the caller
        puts its checkmark back, the `set_split_enabled()` discipline).

        ON — a SECOND pane appears to the right of the first, starting WHERE the first one
        is (a commander's second pane that starts somewhere else is a puzzle, not a tool),
        the ratio is applied and the ACTIVE pane is ringed. **The cwd follow is switched OFF
        here and stays off**: one OSC 7 report cannot say which of the two panes should move,
        and a listing that walks under the keyboard is worse than no follow — the owner (the
        session) is told through `follow_cwd_changed`, so the checkbox and the session state
        cannot diverge.

        OFF — the second pane is torn down; the FIRST one keeps its directory, its listing
        and its viewer.
        """
        on = bool(on)
        if on == self._commander:
            return True
        if on:
            pane = self._ensure_second_pane()
            if pane is None:
                return False
            self._commander = True
            self._apply_commander_sizes()
            self.set_active_pane(self._active_pane or self._panes[0])
            self._sync_active_ring()
            self._sync_hint_rows()
            if self._follow_cwd:
                # the mode cannot honour the follow: OFF, and the session is told
                self._follow_cwd = False
                self._set_follow_checkbox(False)
                try:
                    self.follow_cwd_changed.emit(False)
                except RuntimeError:
                    pass  # Qt teardown
            self._sync_follow_availability()
            self.message.emit(_t("sftp.commander_hint"))
            return True
        # OFF
        pane = self._pane_b
        self._pane_b = None
        self._commander = False
        if pane is not None:
            self._close_viewer_of(pane)
            self._destroy_pane(pane)
        self.set_active_pane(self._panes[0] if self._panes else None)
        for p in self._panes:
            p.set_active(False)
        self._sync_hint_rows()
        self._sync_follow_availability()
        return True

    def _close_viewer_of(self, pane):
        """Close the preview a pane OWNS or CARRIES, keeping the viewer widget alive.

        The panel is a widget of its OWNER: a pane that merely CARRIES it must hand it back
        before it goes away (and the owner must let go of its own panel), so the sibling always
        ends up with a clean listing. Called when the two-pane mode goes off and when a pane is
        torn down. Never raises.
        """
        for owner in list(self._panes):
            try:
                if owner.viewer_host() == pane:
                    owner.close_viewer()
            except (RuntimeError, AttributeError):
                continue  # Qt teardown — that pane is already gone

    def _ensure_second_pane(self):
        """Create the second pane (idempotent) and start it in the first pane's directory."""
        if self._pane_b is not None:
            return self._pane_b
        first = self._panes[0] if self._panes else None
        pane = self._new_pane()
        if first is not None:
            pane._current_dir = first.current_dir
        pane.bind_worker(None, self._worker)   # the new pane lists its directory too
        self._pane_b = pane
        for p in self._panes:
            p.setMinimumWidth(COMMANDER_MIN_PANE_PX)
        # v1.7rc3: the role of every pane follows the mode (the right one loses the button row).
        self._sync_hint_rows()
        return pane

    def _destroy_pane(self, pane):
        """Tear ONE pane down: unbind its worker, drop its preview, remove it. Never raises.

        v1.7rc3: a preview this pane LENT or BORROWED is closed FIRST — the viewer widget belongs
        to its owner and must not be destroyed together with a pane that was only showing it.
        """
        try:
            self._close_viewer_of(pane)
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        try:
            pane.release()
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        try:
            self.pane_splitter.setCollapsible(self.pane_splitter.indexOf(pane), True)
        except (RuntimeError, TypeError):
            pass
        if pane in self._panes:
            self._panes.remove(pane)
        try:
            pane.setParent(None)
            pane.deleteLater()
        except RuntimeError:
            pass  # teardown race — the pane dies with its parent anyway
        for p in self._panes:
            p.setMinimumWidth(0)
        if self._active_pane is pane:
            self._active_pane = self._panes[0] if self._panes else None

    def commander_ratio(self):
        """The FIRST pane's CURRENT share of the width (None — nothing to measure).

        None while the mode is off: a ratio measured on a hidden member would be 0 and would
        overwrite the proportion the user left behind (the split's rule, §4.3).
        """
        if not self._commander or self._pane_b is None:
            return None
        try:
            sizes = self.pane_splitter.sizes()
        except RuntimeError:
            return None
        if len(sizes) < 2:
            return None
        total = sum(sizes)
        if total <= 0 or sizes[0] <= 0:
            return None
        return sizes[0] / float(total)

    def _on_commander_moved(self, _pos=None, _index=None):
        """The user dragged the pane divider — the new proportion becomes THE ratio."""
        ratio = self.commander_ratio()
        if ratio is None:
            return
        self._commander_ratio = max(COMMANDER_RATIO_MIN,
                                    min(COMMANDER_RATIO_MAX, ratio))

    def _apply_commander_sizes(self):
        """Apply the stored proportion through `setSizes` only (Qt gotcha #13). Never raises."""
        if self._pane_b is None:
            return
        try:
            total = self.pane_splitter.width() - self.pane_splitter.handleWidth()
        except RuntimeError:
            return
        if total <= 0:
            return  # not laid out yet — the ratio is applied on the next pass
        left = int(round(total * self._commander_ratio))
        left = max(1, min(left, total - 1))
        try:
            self.pane_splitter.setSizes([left, total - left])
        except RuntimeError:
            pass  # C++ teardown — nothing to size

    def commander_extra_config(self, extra: dict = None) -> dict:
        """The two-pane state as CONFIG keys, for the window's SINGLE geometry write.

        The `_save_split_state()` shape: the ratio is re-read from the live splitter (a
        hidden/never-shown mode keeps the last real proportion) and clamped.
        """
        ratio = self.commander_ratio()
        if ratio is not None:
            self._commander_ratio = max(COMMANDER_RATIO_MIN,
                                        min(COMMANDER_RATIO_MAX, ratio))
        payload = {
            COMMANDER_CONFIG_BOOL: bool(self._commander),
            COMMANDER_CONFIG_RATIO: round(float(self._commander_ratio), 4),
        }
        if isinstance(extra, dict):
            extra.update(payload)
            return extra
        return payload

    # ── Worker binding (called by the page) ──────────────────────────────

    def set_worker(self, worker):
        """Bind/unbind the ONE SftpWorker of this session; None — the "waiting" state.

        The worker is the CONTAINER's (SFTP_PANES.md §2): one transport, one queue, two
        panes. Each pane re-binds its own slots, so the two listings stay independent.
        """
        old = self._worker
        self._worker = worker
        for pane in list(self._panes):
            pane.bind_worker(old, worker)
        self._sync_follow_availability()

    @property
    def worker(self):
        """The bound SftpWorker (None before the connection / after it died)."""
        return self._worker

    # ── v1.6.3: the follow switch (a SESSION state, the container's) ─────

    def _set_follow_checkbox(self, checked: bool):
        """Write the checkbox WITHOUT reporting it back (the checkbox is a VIEW of the state)."""
        try:
            was = self.chk_follow_cwd.blockSignals(True)
            self.chk_follow_cwd.setChecked(bool(checked))
            self.chk_follow_cwd.blockSignals(was)
        except RuntimeError:
            pass  # Qt teardown

    def _sync_follow_availability(self):
        """The follow is available with a transport and NOT in the two-pane mode.

        One OSC 7 report cannot answer "which of the two panes" — in the Commander the
        switch is greyed (SFTP_PANES.md "The follow rule").
        """
        try:
            self.chk_follow_cwd.setEnabled(self._worker is not None and not self._commander)
        except RuntimeError:
            pass  # Qt teardown

    def _on_follow_toggled(self, checked: bool):
        """The follow checkbox → the session (which owns the hook and the config key)."""
        self._follow_cwd = bool(checked)
        try:
            self.follow_cwd_changed.emit(self._follow_cwd)
        except RuntimeError:
            pass  # Qt teardown — the tab is already gone

    def set_follow_cwd(self, enabled: bool):
        """Install the follow state in the checkbox WITHOUT reporting it back (v1.6.3).

        The page owns the state; this is its write path (the checkbox is a VIEW of it), so
        the signal is blocked — otherwise opening a session would "toggle" the setting.
        """
        self._follow_cwd = bool(enabled)
        self._set_follow_checkbox(self._follow_cwd)

    def follow_directory(self, path: str) -> bool:
        """v1.6.3: the shell moved — move the FIRST pane's listing with it.

        Refused in the two-pane mode (the follow is off there by construction) and forwarded
        to the FIRST pane otherwise: the OSC 7 report is a property of the SESSION, and the
        first pane is the one the shell was following.
        """
        if self._commander or not self._panes:
            return False
        return bool(self._panes[0].follow_directory(path))

    @property
    def current_dir(self) -> str:
        """The ACTIVE pane's directory (the upload target of the shipped single-pane read)."""
        pane = self._active_pane
        return pane.current_dir if pane is not None else "/"

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — the walk over BOTH panes ──

    def retranslate(self):
        """v1.3.3.1: re-text the container and EVERY pane in the current language.

        The container owns the follow switch (one label + one tooltip) and walks its panes,
        so a language switch re-texts the second pane as well. Never raises.
        """
        try:
            self.chk_follow_cwd.setText(_t("sftp.follow_cwd"))
            self.chk_follow_cwd.setToolTip(_t("sftp.follow_cwd_tooltip"))
        except RuntimeError:
            pass  # Qt teardown — the switch is already destroyed
        for pane in list(self._panes):
            try:
                pane.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the pane is already destroyed

    def refresh_theme(self):
        """v1.4.3: re-apply the theme to the container and EVERY pane. Never raises."""
        for pane in list(self._panes):
            hook = getattr(pane, "refresh_theme", None)
            if not callable(hook):
                continue
            try:
                hook()
            except RuntimeError:
                pass  # Qt teardown — the pane is already destroyed

    def close_viewer(self):
        """v1.3.1: close the preview of EVERY pane (the page teardown path). Never raises."""
        for pane in list(self._panes):
            try:
                pane.close_viewer()
            except RuntimeError:
                pass  # Qt teardown — the pane is already destroyed

    def resizeEvent(self, event):
        """v1.7rc1: a resize re-applies the pane proportion (the split's rule)."""
        super().resizeEvent(event)
        if self._commander:
            self._apply_commander_sizes()

    def _on_pane_splitter_moved(self, _pos=None, _index=None):
        """The user dragged the pane divider — the new proportion becomes THE ratio."""
        self._on_commander_moved()

    # ── D&D: the CONTAINER's own surface (a drag that misses every pane) ──

    def _pane_for_widget(self, obj):
        """The pane a widget belongs to; the container's OWN chrome answers the ACTIVE pane.

        `__getattr__` cannot serve the drag/filter family: `dragEnterEvent`, `dropEvent` and
        `eventFilter` exist on QWidget itself, so an ordinary lookup finds the (empty) base
        implementation and never reaches the pane. The container therefore DELEGATES them —
        and it resolves the pane by ANCESTRY, which is what keeps the shipped test seam
        (`tab.dropEvent(ev)`, `tab.eventFilter(tab.tree.viewport(), ev)`) working.
        """
        for pane in list(self._panes):
            try:
                if obj is pane or pane.isAncestorOf(obj):
                    return pane
            except RuntimeError:
                continue  # Qt teardown — the pane is already destroyed
        return self._active_pane

    def eventFilter(self, obj, event):
        """Forward a child's event to the pane it belongs to (the shipped seam)."""
        pane = self._pane_for_widget(obj)
        if pane is None:
            return False
        try:
            return bool(pane.eventFilter(obj, event))
        except RuntimeError:
            return False  # Qt teardown — nothing to forward to

    def _pane_under_drag(self, event):
        """The pane the cursor is really OVER (None — nobody is under it).

        The parent chain is not the answer: the v1.7.1 Files panel borrows the whole widget and a
        Commander borrows its sibling's viewer, so the target is resolved from the WIDGET UNDER THE
        CURSOR first and only then by ancestry (`_pane_for_widget` as the fallback). Never raises.
        """
        try:
            try:
                point = event.globalPosition().toPoint()
            except AttributeError:   # an older event object without globalPosition()
                point = event.globalPos()
            widget = QApplication.widgetAt(point)
        except (RuntimeError, AttributeError, TypeError):
            widget = None
        hops = 0
        while widget is not None and hops < 32:
            for pane in list(self._panes):
                if widget is pane:
                    return pane
            try:
                widget = widget.parentWidget()
            except RuntimeError:
                break
            hops += 1
        return None

    def _forward_drag(self, event, name: str):
        """Deliver a drag event that reached the CONTAINER to the pane UNDER THE CURSOR."""
        pane = self._pane_under_drag(event) or self._pane_for_widget(self._drag_source or self)
        if pane is None:
            return
        pane._drag_source = pane
        try:
            getattr(pane, name)(event)
        finally:
            pane._drag_source = None

    def dragEnterEvent(self, event):
        """A drag over the tab's own chrome (the follow switch, the splitter handle)."""
        self._forward_drag(event, "dragEnterEvent")

    def dragMoveEvent(self, event):
        """Same answer as dragEnter — otherwise Qt resets the action before Drop."""
        self._forward_drag(event, "dragMoveEvent")

    def dropEvent(self, event):
        """A drop on the tab's own chrome lands in the ACTIVE pane's current directory."""
        self._forward_drag(event, "dropEvent")

    # ── The shipped single-pane surface (resolved on the ACTIVE pane) ────

    def __getattr__(self, name):
        """Forward an unknown attribute to the ACTIVE pane (the shipped tab surface).

        `tab.tree`, `tab.path_label`, `tab._relist(...)`, `tab._blocked` — every name the
        page, the window or a test reads from the shipped single-pane tab resolves on the
        pane that really owns it. Container attributes and methods win by construction
        (`__getattr__` runs only when the ordinary lookup fails), and a name NOBODY owns
        still raises `AttributeError`, so `hasattr()` keeps answering honestly.
        """
        pane = self.__dict__.get("_active_pane")
        if pane is not None:
            try:
                return getattr(pane, name)
            except AttributeError:
                pass
        raise AttributeError(name)

    def __setattr__(self, name, value):
        """Write a PANE-owned name through to the ACTIVE pane (`PANE_STATE`).

        Without it `tab._blocked = {...}` would shadow the pane's dictionary on the
        container and the pane would keep answering from its own — a second truth. Every
        other name is the container's and lands here as usual.
        """
        if name in SftpTab.PANE_STATE:
            pane = self.__dict__.get("_active_pane")
            if pane is not None:
                setattr(pane, name, value)
                return
        super().__setattr__(name, value)
