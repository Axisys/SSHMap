# -*- coding: utf-8 -*-
"""The Files tab of a terminal session — a CONTAINER of 1–2 PANES over ONE SFTP worker.

`SftpTab` owns the single worker binding, the session's follow switch, the two panes and the ACTIVE
pane; `_SftpPane` is a FACADE whose clusters live in `sftp_pane_walk.py` (the pane-scoped keys and
the mc/far walk), `sftp_pane_listing.py` (the listing, its navigation and its address bar),
`sftp_pane_viewer.py` (the read-only preview), `sftp_pane_transfer.py` (the transfers, the conflict
question and the batch copy/move) and `sftp_pane_dnd.py` (the drag & drop and the row context menu),
over the PURE helpers of `sftp_pane_helpers.py`. A pane binds the SHARED worker's signals and answers
only the task ids IT queued — so the panes navigate independently, without a second worker or a
second channel. The page talks to the container (`page.sftp_tab`); a shipped attribute read resolves
on the ACTIVE pane. Contract — `SFTP_PANES.md`; mechanism — §38, §59-§63."""

import json
import os
import posixpath

from PySide6.QtCore import (QCoreApplication, QEvent, QMimeData, QSize,
                            QStringListModel, Qt, QUrl, Signal)
from PySide6.QtGui import QAction, QDrag, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QCompleter, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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

try:  # v1.3.1: the operation kinds THIS module still queues and the task payload readers
    from .sftp_worker import (KIND_DELETE, KIND_MKDIR, KIND_RENAME, NAME_ERROR_UNSAFE,
                              READ_ERROR_TOO_LARGE, SftpWorker, parse_task_payload,
                              register_orphan_sftp_worker)
except ImportError:
    from sftp_worker import (KIND_DELETE, KIND_MKDIR, KIND_RENAME, NAME_ERROR_UNSAFE,
                             READ_ERROR_TOO_LARGE, SftpWorker, parse_task_payload,
                             register_orphan_sftp_worker)

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

try:  # v1.7.4rc1: the LOCAL provider of a pane and the machine codes of its refusals
    from . import local_fs_worker as local_fs
except ImportError:  # flat launch from the project root
    import local_fs_worker as local_fs

try:  # v1.8: the ELEVATED provider of a pane — the handshake the pane starts
    from .sftp_elevated import ElevatedHandshake
except ImportError:  # flat launch from the project root
    from sftp_elevated import ElevatedHandshake

try:  # v1.8: the elevation dialogue (the pane resolves it as a facade global, the shipped seam)
    from ..dialogs.elevated_dialog import ask_elevation
except ImportError:  # flat launch from the project root
    from dialogs.elevated_dialog import ask_elevation

# v1.8rc4/rc5: `_SftpPane` is a FACADE over its pane mixins — the pane-scoped keys and the walk, the
# listing with its address bar, the read-only preview, the transfers with the batch copy/move, and
# the drag & drop with the row context menu. The module-level facts of a cluster travel WITH it and
# are imported back here, so `modules.sftp_tab` keeps the shipped surface a caller and the suite
# already read (`PANE_SHORTCUTS`, `SORT_COLUMNS`, `format_size`, `ask_conflict`, …).
try:
    from .sftp_pane_walk import (PANE_HINTS, PANE_SHORTCUTS, HINT_SEPARATOR,
                                 SftpPaneWalkMixin)
    from .sftp_pane_listing import (SORT_COLUMNS, SORT_DEFAULT_COLUMN,
                                    SftpPaneListingMixin)
    from .sftp_pane_viewer import (VIEWER_FREEZE_MS_PER_MB, VIEWER_MAX_BYTES_CONFIG,
                                   VIEWER_MAX_BYTES_MAX, VIEWER_MAX_BYTES_MIN,
                                   VIEWER_MAX_BYTES_STEP, VIEWER_MAX_BYTES_WARN,
                                   SftpPaneViewerMixin, viewer_freeze_seconds)
    from .sftp_pane_helpers import (VIEWER_ENCODING_CONFIG, VIEWER_ENCODING_DEFAULT,
                                    VIEWER_ENCODINGS, VIEWER_WRAP_CONFIG, ask_conflict, decode_text,
                                    format_mtime, format_size, normalize_viewer_encoding,
                                    preview_block_reason, resolve_viewer_encoding,
                                    resolve_viewer_wrap, save_viewer_encoding, save_viewer_wrap)
    from .sftp_pane_transfer import SftpPaneTransferMixin
    from .sftp_pane_dnd import SftpPaneDndMixin
    from .sftp_pane_elevated import SftpPaneElevatedMixin
except ImportError:  # flat launch from the project root
    from sftp_pane_walk import PANE_HINTS, PANE_SHORTCUTS, HINT_SEPARATOR, SftpPaneWalkMixin
    from sftp_pane_listing import SORT_COLUMNS, SORT_DEFAULT_COLUMN, SftpPaneListingMixin
    from sftp_pane_viewer import (VIEWER_FREEZE_MS_PER_MB, VIEWER_MAX_BYTES_CONFIG,
                                  VIEWER_MAX_BYTES_MAX, VIEWER_MAX_BYTES_MIN,
                                  VIEWER_MAX_BYTES_STEP, VIEWER_MAX_BYTES_WARN,
                                  SftpPaneViewerMixin, viewer_freeze_seconds)
    from sftp_pane_helpers import (VIEWER_ENCODING_CONFIG, VIEWER_ENCODING_DEFAULT,
                                   VIEWER_ENCODINGS, VIEWER_WRAP_CONFIG, ask_conflict, decode_text,
                                   format_mtime, format_size, normalize_viewer_encoding,
                                   preview_block_reason, resolve_viewer_encoding,
                                   resolve_viewer_wrap, save_viewer_encoding, save_viewer_wrap)
    from sftp_pane_transfer import SftpPaneTransferMixin
    from sftp_pane_dnd import SftpPaneDndMixin
    from sftp_pane_elevated import SftpPaneElevatedMixin


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
#: extension is a HINT, the value is a real JSON bool or the default. The pair of readers and the
#: ENCODING choice beside them live in `modules/sftp_pane_helpers.py` and are re-exported at the end
#: of this file (`VIEWER_WRAP_CONFIG`, `resolve_viewer_wrap`, `save_viewer_wrap`).

#: v1.7.3: the drag payload of a row that started INSIDE a Files pane. The remote path alone
#: cannot say WHICH pane (two servers show the same path), so the private type carries the session
#: key, the pane's identity and the path while `text/plain` keeps the plain path for every foreign
#: consumer (a terminal, an editor, a chat window).
PANE_DRAG_MIME = "application/x-sshmap-pane-row"

#: v1.7.4rc1: the two DATA SOURCES of a pane. A pane is typed to ONE of them (its provider);
#: `SOURCE_REMOTE` is the session's own transport (`SftpTab._worker`) and `SOURCE_LOCAL` is the OS
#: disk of this machine, read through `modules/local_fs_worker.py` on its OWN thread. The source is
#: a property of the PANE (LOCAL_PANE.md §1), never of the container: ONE pane of the Commander may
#: read the local disk while the other one reads the server.
SOURCE_REMOTE = "remote"
SOURCE_LOCAL = "local"
PANE_SOURCES = (SOURCE_REMOTE, SOURCE_LOCAL)

#: v1.8: the THIRD position of a pane's SOURCE CONTROL — a REMOTE pane whose PROVIDER reads the
#: server as another user (`ELEVATED_PANE.md` §1). It is deliberately NOT a third data source: the
#: dialect stays POSIX, `PANE_SOURCES` keeps its pair and §5's four-pair dispatch keeps its rows.
SOURCE_ELEVATED = "elevated"

#: The local pane's control and the sentence of its two structural refusals — declared ONCE.
LOCAL_SOURCE_LABEL = "sftp.local.source"
LOCAL_UNAVAILABLE_HINT = "sftp.local.unavailable"

#: v1.8: the elevated pane's third button of the SAME control (`ELEVATED_PANE.md` §4).
ELEVATED_SOURCE_LABEL = "sftp.elevated.button"
ELEVATED_SOURCE_TOOLTIP = "sftp.elevated.tooltip"


def _win_standard_path(path: str) -> str:
    """`os.path.normcase` on every OS (a PURE helper, so the dialect stays testable everywhere).

    The LOCAL dialect is case-insensitive on Windows and case-SENSITIVE elsewhere; the shipped
    `os.path.normcase` is an identity on POSIX, so it is used directly and the fallback keeps the
    same answer when the platform module cannot be asked.
    """
    try:
        return os.path.normcase(str(path or ""))
    except Exception:  # noqa: BLE001 — never break a listing over a path comparison
        return str(path or "")


class PathDialect:
    """The PATH RULES of one data source — the ONE adapter a pane resolves paths through.

    A remote pane speaks POSIX (`posixpath`, the "/" root) and a LOCAL pane speaks the OS disk
    (backslashes, a drive or UNC root, case-insensitive names). Every join, split, root test and
    name comparison of the pane goes through its dialect, so a second dialect costs ONE object and
    not a second pane (LOCAL_PANE.md §2). PURE: no Qt, no IO, no i18n.
    """

    def __init__(self, kind: str, label: str):
        self.kind = str(kind)
        self.label = str(label)

    @property
    def is_local(self) -> bool:
        return self.kind == SOURCE_LOCAL

    @property
    def separator(self) -> str:
        """The character that continues INTO a directory (the completer's trailing one)."""
        return "\\" if self.is_local else "/"

    def dirname(self, path: str) -> str:
        """The parent of `path` — "" at the root (the root itself for the LOCAL dialect)."""
        text = str(path or "")
        if self.is_local:
            return os.path.dirname(text)
        return posixpath.dirname(text)

    def join(self, base: str, name: str) -> str:
        """`base` + `name` as ONE path."""
        text, child = str(base or ""), str(name or "")
        if self.is_local:
            return os.path.join(text, child)
        return posixpath.join(text or "/", child)

    def basename(self, path: str) -> str:
        """The LAST component of `path` (the name a row, a dialog or a sentence shows)."""
        text = str(path or "")
        if self.is_local:
            return os.path.basename(text)
        return posixpath.basename(text)

    def is_root(self, path: str) -> bool:
        """Is `path` a ROOT (nothing above it)? A bare drive name and `~` are NOT.

        For the LOCAL dialect a root is the path its own parent already is — a drive root
        (`C:\\`), a UNC share root, `/` — which is exactly what the pane's "go up" test needs:
        answering True for the bare `C:` would send the listing to the process's current
        directory of that drive, and answering False for `C:\\` would render a ".." row that
        cannot be resolved.
        """
        text = str(path or "")
        if not text:
            return False
        if self.is_local:
            if not os.path.isabs(text):
                return False
            return os.path.dirname(text) == text
        return text == "/"

    def is_absolute(self, path: str) -> bool:
        """Is `path` already anchored? `~` counts as absolute: it resolves to a home."""
        text = str(path or "")
        if text.startswith("~"):
            return True
        if self.is_local:
            return os.path.isabs(text)
        return text.startswith("/")

    def same(self, left: str, right: str) -> bool:
        """Are the two paths the SAME subject? Case-insensitively on the OS disk."""
        if self.is_local:
            return _win_standard_path(left) == _win_standard_path(right)
        return str(left or "") == str(right or "")

    def root(self) -> str:
        """The value a LOCAL pane opens with when nothing else is known — the OS home."""
        return os.path.expanduser("~") if self.is_local else "/"


#: The two dialects, declared ONCE (the pane resolves one from its source).
POSIX_PATHS = PathDialect(SOURCE_REMOTE, "/")
LOCAL_PATHS = PathDialect(SOURCE_LOCAL, os.sep)


def dialect_for(source: str) -> PathDialect:
    """The dialect of a pane's SOURCE (`SOURCE_REMOTE` unless the source really is local)."""
    return LOCAL_PATHS if str(source or "") == SOURCE_LOCAL else POSIX_PATHS


def local_error_text(message: str) -> str:
    """A LOCAL `task_error` payload → its translated sentence (a plain message passes through).

    The provider names the MACHINE code and the OS's own text (LOCAL_PANE.md §3); the sentence is
    the tab's, so a refusal reads like every other message of the window. A payload the tab does
    not know falls back to the shipped generic operation sentence.
    """
    data = parse_task_payload(message)
    if not data:
        return _t("sftp.op.error", error=message)
    code = str(data.get("code") or "")
    if code == local_fs.KIND_LIST_PARTIAL:
        return _t(local_fs.LOCAL_ERROR_KEYS[local_fs.KIND_LIST_PARTIAL],
                  count=int(data.get("count") or 0), names=str(data.get("names") or ""))
    key = local_fs.LOCAL_ERROR_KEYS.get(code)
    if not key:
        return _t("sftp.op.error", error=str(data.get("error") or message))
    return _t(key, error=str(data.get("error") or ""))


def name_refusal_text(message: str) -> str:
    """A NAME_ERROR_UNSAFE payload → its translated sentence; "" — another message (v1.7.5.1).

    ONE renderer for the two surfaces that can see the code (the pane's own message line and the
    session's status line), so a refused download name reads the same wherever it is reported.
    """
    data = parse_task_payload(message)
    if not data or str(data.get("code") or "") != NAME_ERROR_UNSAFE:
        return ""
    return _t("sftp.name_refused", name=str(data.get("name") or ""))


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


def clamp_viewer_max_bytes(value) -> int:
    """PURE: a cap into the DECLARED range `[VIEWER_MAX_BYTES_MIN, VIEWER_MAX_BYTES_MAX]`.

    A foreign value (a string, `None`, a bool, a negative number) answers the DEFAULT — the
    shipped `MAX_READ_BYTES`. The range is ONE declaration, so the slider, the value box and
    the reader can never disagree about what a legal cap is.
    """
    if isinstance(value, bool):
        return VIEWER_MAX_BYTES_MIN
    try:
        number = int(value)
    except (TypeError, ValueError):
        return VIEWER_MAX_BYTES_MIN
    return max(VIEWER_MAX_BYTES_MIN, min(VIEWER_MAX_BYTES_MAX, number))


def resolve_viewer_max_bytes(cfg: dict = None) -> int:
    """The reader's ceiling as a PURE value (v1.7.5): the config's cap, clamped, else the default.

    Only a real number counts; a missing key, a string, a bool or an unreadable config answers
    `MAX_READ_BYTES` — the shipped read policy is what a user who never touched the setting has.
    """
    if not isinstance(cfg, dict):
        try:
            from i18n import load_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the default
            return VIEWER_MAX_BYTES_MIN
        try:
            cfg = load_config() or {}
        except Exception:  # noqa: BLE001 — a broken config store keeps the default
            cfg = {}
    value = cfg.get(VIEWER_MAX_BYTES_CONFIG) if isinstance(cfg, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return VIEWER_MAX_BYTES_MIN
    return clamp_viewer_max_bytes(value)


def save_viewer_max_bytes(value) -> bool:
    """Write the ONE cap key, CLAMPED (merge-write; False — the config could not be written)."""
    try:
        from i18n import save_config
    except Exception:  # noqa: BLE001 — a build without i18n cannot remember it
        return False
    try:
        return bool(save_config({VIEWER_MAX_BYTES_CONFIG: clamp_viewer_max_bytes(value)}))
    except Exception:  # noqa: BLE001 — a write failure must not break the reader
        return False


def pane_payload(mime_data):
    """The `{session, pane, path}` payload of a drag that started inside a pane (None — foreign).

    A malformed payload (not JSON, not an object, no path) is a FOREIGN drag: the pane then behaves
    exactly as it did before the private type existed. v1.7.4rc2 adds the SOURCE dialect of the row
    (`source`, `size`): a local row and a remote one carry paths of two different spellings, so a
    drop resolves the basename with the dialect that really produced it.
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
    source = str(data.get("source") or SOURCE_REMOTE)
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return {"session": str(data.get("session") or ""), "pane": data.get("pane"), "path": path,
            "source": source if source in PANE_SOURCES else SOURCE_REMOTE, "size": size}


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


def read_was_truncated(data_len, cap, known_size=0) -> bool:
    """PURE (N46): did a read stop at the pane's ceiling — i.e. is the tail cut?

    The listing's own size is the CERTAIN signal (`known_size > data_len` — the very condition the
    panel already reports as `sftp.viewer.truncated`); the ceiling is the fallback for a file the
    listing does not know, where a read that returned the whole cap can only have been cut. A file
    the listing measures as COMPLETE is never called truncated, whatever the cap is.
    """
    try:
        known = int(known_size or 0)
        length = int(data_len or 0)
    except (TypeError, ValueError):
        return False
    if known > 0:
        return known > length
    try:
        cap = int(cap or 0)
    except (TypeError, ValueError):
        return False
    return cap > 0 and length >= cap


def row_path(item) -> str:
    """The FULL path a listing row carries in its PATH_ROLE ("" — no role, a dead item). PURE."""
    try:
        return str(item.data(0, _SftpPane.PATH_ROLE) or "")
    except (RuntimeError, AttributeError):
        return ""


def row_name(item) -> str:
    """The NAME a listing row sorts by — the basename of its PATH_ROLE, in EITHER dialect (PURE).

    The sort key is read off the ROLE and never off the widget text, so the comparison cannot be
    moved by a re-text pass; the split accepts both separators because a LOCAL row and a REMOTE one
    spell the same shape of path two ways (LOCAL_PANE.md §2).
    """
    path = row_path(item)
    for separator in ("/", "\\"):
        if separator in path:
            path = path.rsplit(separator, 1)[-1]
    if path:
        return path
    try:
        return str(item.text(0) or "")
    except (RuntimeError, AttributeError):
        return ""


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


class _SftpRowItem(QTreeWidgetItem):
    """ONE row of a pane's listing, ordered by the ROLES (v1.7.5 — the sortable listing).

    `QTreeWidget`'s own item ordering is the ONLY sorter (`sortItems()` calls this `__lt__` through
    the tree's model), so the sorting costs no re-listing and no second sort table. The order is
    declared in the ROLES, which both SOURCES fill identically, so a LOCAL pane sorts exactly like a
    remote one (`LOCAL_PANE.md` §3) and a column that means nothing for a directory keeps the two
    GROUP rules intact:

      * the ".." row (`pinned`) is FIRST whatever the column and the direction;
      * DIRECTORIES stay grouped ABOVE the files, whatever the column and the direction;
      * inside one group the chosen COLUMN decides, then the path breaks a tie deterministically.

    Two rules the pane must keep for this to hold: Qt is always asked for `AscendingOrder` (its
    `DescendingOrder` REVERSES the comparator, which would put the files above the directories) and
    the real direction lives on the PANE (`_sort_column` / `_sort_desc`), where this comparison
    reads it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: the ".." row — the ONE row no order may move (rule 1).
        self.pinned = False

    def sort_state(self):
        """`(column, descending)` of the pane this row is listed by — the DECLARED view state."""
        pane = getattr(self.treeWidget(), "pane", None)
        if pane is None:
            return SORT_DEFAULT_COLUMN, False
        column = getattr(pane, "_sort_column", SORT_DEFAULT_COLUMN)
        try:
            column = int(column)
        except (TypeError, ValueError):
            column = SORT_DEFAULT_COLUMN
        return (column if column in SORT_COLUMNS else SORT_DEFAULT_COLUMN,
                bool(getattr(pane, "_sort_desc", False)))

    def group_rank(self) -> int:
        """The GROUP of a row: 0 — the pinned ".." row, 1 — a directory, 2 — a file."""
        if getattr(self, "pinned", False):
            return 0
        try:
            return 1 if self.data(0, _SftpPane.ISDIR_ROLE) else 2
        except (RuntimeError, AttributeError):
            return 2

    def sort_key(self, column: int):
        """The value of THIS row in `column`: the NAME, the SIZE or the MTIME, read off the ROLES."""
        pane = _SftpPane
        role = {1: pane.SIZE_ROLE, 2: pane.MTIME_ROLE}.get(int(column))
        if role is not None:
            try:
                return int(self.data(0, role) or 0)
            except (RuntimeError, AttributeError, TypeError, ValueError):
                return 0
        try:
            # `lower()` is the provider's own key (`local_entries`, the worker's listing), so the
            # default order of a fresh listing and a click on the Name header agree to the character.
            return row_name(self).lower()
        except (RuntimeError, AttributeError):
            return ""

    def __lt__(self, other) -> bool:
        if not isinstance(other, _SftpRowItem):
            return False
        mine, theirs = self.group_rank(), other.group_rank()
        if mine != theirs:
            return mine < theirs          # the two GROUP rules, whatever the direction
        if mine == 0:
            return False                  # two pinned rows — the ".." row never moves
        column, descending = self.sort_state()
        my_key = self.sort_key(column)
        other_key = other.sort_key(column)
        if my_key == other_key:
            # A stable tie-break: the full PATH of the row, so two rows that share a size or an
            # mtime keep ONE deterministic order (the direction applies to it as well).
            my_key, other_key = row_path(self), row_path(other)
        return (my_key > other_key) if descending else (my_key < other_key)


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
        """The drag payload of a row: the path as text/plain, plus the PANE identity.

        None — nothing to drag (no row / a row without a path). v1.7.3: the private
        `PANE_DRAG_MIME` carries `{session, pane, path}` so a drop INSIDE a pane can tell which
        pane the row came from (two servers can show the same path) and refuse a foreign session —
        while `text/plain` keeps the plain path for every foreign target. v1.7.4rc2: a LOCAL row
        also hands out a real OS path (`text/uri-list`, the Explorer contract) and the payload
        DECLARES its source dialect, so the drop never guesses which spelling it received.
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
            payload = {"session": pane.session_key(), "pane": id(pane), "path": str(path),
                       "source": pane.source,
                       "size": int(item.data(0, _SftpPane.SIZE_ROLE) or 0)}
            mime.setData(PANE_DRAG_MIME, json.dumps(payload).encode("utf-8"))
            if pane.source == SOURCE_LOCAL:
                mime.setUrls([QUrl.fromLocalFile(str(path))])
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


class _SourceSwitch(QWidget):
    """The `Server | Local | Elevated` control of the pane's address row (v1.7.4rc1, LOCAL_PANE.md §4).

    ONE checkable group driving ONE state (the `CommanderCorner` discipline: the buttons are
    views of `source`, so the look can never disagree with the provider the pane bound), and the
    label spells out WHAT is being switched — the pane's own source, not the session's. The widget
    only EMITS: the container decides whether the local and the elevated sources are available at
    all, and the pane translates the elevated token into "a REMOTE pane whose provider is elevated".
    """

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = SOURCE_REMOTE
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.lbl = QLabel(_t(LOCAL_SOURCE_LABEL))
        _apply_status_style(self.lbl, "status.sftp_row")
        row.addWidget(self.lbl)
        self.btn_server = QToolButton()
        self.btn_local = QToolButton()
        self.btn_elevated = QToolButton()
        for button, source, key in ((self.btn_server, SOURCE_REMOTE, "sftp.local.server"),
                                    (self.btn_local, SOURCE_LOCAL, "sftp.local.local"),
                                    (self.btn_elevated, SOURCE_ELEVATED, ELEVATED_SOURCE_LABEL)):
            button.setText(_t(key))
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, s=source: self._on_clicked(s))
            row.addWidget(button)
        self.btn_elevated.setToolTip(_t(ELEVATED_SOURCE_TOOLTIP))
        self.apply(SOURCE_REMOTE)

    def _on_clicked(self, source: str):
        if source == self._source:
            self.apply(source)   # a click on the state that already holds — the look is re-synced
            return
        self.changed.emit(source)

    def source(self) -> str:
        return self._source

    def apply(self, source: str):
        """Show ONE source as the live one (the state is written HERE and nowhere else)."""
        token = str(source or "")
        self._source = token if token in (SOURCE_LOCAL, SOURCE_ELEVATED) else SOURCE_REMOTE
        for button, value in ((self.btn_server, SOURCE_REMOTE), (self.btn_local, SOURCE_LOCAL),
                              (self.btn_elevated, SOURCE_ELEVATED)):
            try:
                button.setChecked(self._source == value)
            except RuntimeError:
                pass  # Qt teardown — the button is already gone

    def set_available(self, enabled: bool, available: bool = True):
        """Enable/disable the group and say WHY through the tooltip (never a silent dead control).

        The WIDGET itself is disabled as well as its parts, so the whole control reads as one
        (a disabled container with enabled children would be an ambiguous answer).
        """
        on = bool(enabled) and bool(available)
        for widget in (self, self.lbl, self.btn_server, self.btn_local, self.btn_elevated):
            try:
                widget.setEnabled(on)
            except RuntimeError:
                continue
        try:
            self.setToolTip("" if available else _t(LOCAL_UNAVAILABLE_HINT))
        except RuntimeError:
            pass

    def retranslate(self):
        try:
            self.lbl.setText(_t(LOCAL_SOURCE_LABEL))
            self.btn_server.setText(_t("sftp.local.server"))
            self.btn_local.setText(_t("sftp.local.local"))
            self.btn_elevated.setText(_t(ELEVATED_SOURCE_LABEL))
            self.btn_elevated.setToolTip(_t(ELEVATED_SOURCE_TOOLTIP))
            self.apply(self._source)
        except RuntimeError:
            pass  # Qt teardown


def _sync_source_switch(switch, source: str, enabled: bool = True, available: bool = True):
    """Show a source and the availability of the switch (the ONE call of every state change)."""
    if switch is None:
        return
    try:
        if source:
            switch.apply(source)
        switch.set_available(enabled, available)
    except (RuntimeError, AttributeError):
        pass  # Qt teardown / a bare stub in a unit test — never raises


class _SftpPane(SftpPaneWalkMixin, SftpPaneListingMixin, SftpPaneViewerMixin,
                SftpPaneTransferMixin, SftpPaneDndMixin, SftpPaneElevatedMixin, QWidget):
    """ONE directory pane of the "Files" tab — a FACADE over its six pane mixins.

    The facade keeps what ONE pane is: the assembly (`__init__` with the address bar, the button
    row, the tree and the viewer widgets), the worker binding and the source switch, the file
    operations, the copy/move batches, the context menu, the drag & drop handlers, the worker
    slots and the theme/re-text walks. The clusters live in their own modules: the pane-scoped
    keys and the mc/far walk (`sftp_pane_walk.py`), the listing and the address bar
    (`sftp_pane_listing.py`), the read-only preview (`sftp_pane_viewer.py`), the transfers with
    the batch copy/move (`sftp_pane_transfer.py`), the drag & drop with the row context menu
    (`sftp_pane_dnd.py`) and the ELEVATED source (`sftp_pane_elevated.py`, `AGENTS.md` §4.25).

    A mixin never imports this module — it duck-types the instance and resolves a facade global
    through `host_attr()` at call time (`MODULE_FACADE_SEAMS` below DECLARES them, `AGENTS.md`
    §4.1, §4.3). Everything a pane owns is per-listing state; the WORKER is the container's
    (`self.worker` reads it), so a second pane costs a second listing and never a second channel.

    The pane answers only the task ids IT queued: the shared worker signals every pane,
    and the one that does not own a task returns without rendering or reporting anything
    (task ids are unique, so the split is exact).
    """

    PATH_ROLE = Qt.ItemDataRole.UserRole       # full remote path of the entry
    ISDIR_ROLE = Qt.ItemDataRole.UserRole + 1  # bool — is it a directory?
    SIZE_ROLE = Qt.ItemDataRole.UserRole + 2   # int — file size (0 for a directory)
    MTIME_ROLE = Qt.ItemDataRole.UserRole + 3  # int — unix mtime

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
        # of the pre-flight listing → (the (source, name, size) triples, the kind, the destination,
        # the SOURCE dialect of the rows). v1.7.4rc2: the dialect rides along, because a local row
        # and a remote one carry two spellings of "the same" path.
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
        # v1.7rc2: the copy/move BATCHES — `_op_batches` maps a queued task id to its batch and
        # `_batches` holds the counters that make ONE report over an asynchronous queue. v1.7.4rc2:
        # `_op_targets` names the DESTINATION of a batch task (its pane and its directory), because
        # the provider that ANSWERS may belong to the OTHER pane.
        self._op_batches = {}
        self._op_targets = {}
        self._batches = {}
        self._batch_seq = 0
        # v1.7.3 (ROADMAP v1.7.3, task 2): the remembered directory of this session — the hint the
        # FIRST transport of each pane opens, and the flag that keeps a second list from re-asking.
        self._restored = False
        self._restore_dir = ""
        # v1.7.3 (ROADMAP v1.7.3, task 4): the reader's word wrap — ONE global setting, read at
        # construction so both panes and every session agree.
        self._viewer_wrap = resolve_viewer_wrap()
        # v1.9.3: the reader's ENCODING choice — the SAME "one global setting, resolved ONCE" rule
        # as the wrap above, plus the path the preview holds (the choice re-reads THAT file).
        self._viewer_encoding_choice = resolve_viewer_encoding()
        self._viewer_path = ""
        # v1.7.5: the reader's CEILING — the SAME "one global setting, resolved ONCE" rule as the
        # wrap above. The value travels into every read task, so the worker never reads a config.
        self._viewer_cap = resolve_viewer_max_bytes()
        # v1.7.5: the LISTING's sort — a VIEW state of this pane (never a config key): the column
        # the header click chose and its direction. The default IS the provider's own order
        # (directories first, then case-insensitive by name), so a listing nobody sorted stays
        # exactly as the source answered it.
        self._sort_column = SORT_DEFAULT_COLUMN
        self._sort_desc = False
        # v1.7rc1: the pane-scoped keys (the F-actions) and the ACTIVE-pane ring.
        self._pane_actions = []
        self._ring = focus_ring.FocusRing(styled_widget=None) if focus_ring is not None else None
        # v1.7.4rc1: the DATA SOURCE of this pane (LOCAL_PANE.md §1). The provider is the object
        # the pane binds — the container's shipped worker for a remote pane, and ONE
        # `LocalFsWorker` of its own for a local one, created on the first switch to Local and
        # kept alive for the pane's whole life (a switch back and forth costs no thread).
        self._source = SOURCE_REMOTE
        self._local_provider = None
        #: The provider this pane's slots are CONNECTED to (`bind_worker` is the ONE writer):
        #: a disconnect asks for it by name, so a provider the pane never bound is never asked.
        self._bound_provider = None
        #: The local directory this pane really sat in — the OS look survives a round trip
        #: through the server (LOCAL_PANE.md §4), while the REMOTE side is re-opened by the
        #: session's own rule (the per-server memory, then "/").
        self._local_dir = ""
        # v1.8: the ELEVATED provider of this pane (ELEVATED_PANE.md §1) — the SHIPPED
        # `SftpWorker` over the client the handshake opened as another user, plus its client (the
        # object that closes the channel), the target user, the in-flight flag and the handshake
        # thread. The SOURCE stays `SOURCE_REMOTE`; only the provider the pane binds changes.
        self._elevated_provider = None
        self._elevated_client = None
        self._elevation_user = ""
        self._elevation_pending = False
        self._handshake = None
        self._waiting = True   # no provider bound yet: the shipped "waiting for connection" state

        t = _t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # v1.7.5 (LOCAL_PANE.md §3): the pane's SOURCE HEADER LINE — the FIRST row, naming WHAT
        # this pane READS ("This computer" for the OS disk, the session's alias for a server). It
        # is a VIEW of the source: ONE line, never focusable, never a drop target — the keyboard
        # walk of §4 belongs to the tree and a drop is resolved in the tree's viewport.
        self.header_label = QLabel("")
        _apply_status_style(self.header_label, "status.sftp_row")
        self.header_label.setWordWrap(False)
        self.header_label.setTextFormat(Qt.TextFormat.PlainText)
        self.header_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer.addWidget(self.header_label)
        self._sync_header()

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
        # v1.7.4rc1: the SOURCE SWITCH of the pane (LOCAL_PANE.md §4) — the leading control of the
        # address row, a one-line pair so it costs the bar no height. It is the SECOND pane's
        # control alone: the first pane is the session's own remote tree, the local source is what
        # makes the OTHER side of a commander a choice, and with one pane there is no other side.
        self.source_switch = _SourceSwitch()
        self.source_switch.changed.connect(self._on_source_switch)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        path_row.addWidget(self.source_switch, 0)
        path_row.addWidget(self.path_label, 1)
        outer.addLayout(path_row)
        _sync_source_switch(self.source_switch, self._source, enabled=False, available=False)

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
        # v1.7.5: the header is a real SORT CONTROL. Qt's automatic sorting stays OFF: it sorts with
        # the direction it is given, and `DescendingOrder` REVERSES the comparator — which would drop
        # the files above the directories and break the two GROUP rules of `_SftpRowItem`. The pane
        # drives `sortItems()` itself, always ASCENDING, and sets the arrow afterwards with the
        # signals blocked.
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().setSortIndicator(SORT_DEFAULT_COLUMN, Qt.SortOrder.AscendingOrder)
        self.tree.header().sectionClicked.connect(self._on_header_clicked)
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

    # ── v1.7rc1: the pane identity and the ACTIVE-pane hook ──────────────

    @property
    def source(self) -> str:
        """This pane's DATA SOURCE (`SOURCE_REMOTE` | `SOURCE_LOCAL`, LOCAL_PANE.md §1)."""
        return self._source

    @property
    def paths(self) -> PathDialect:
        """The path rules of this pane's source — every join, split and root test goes through it."""
        return dialect_for(self._source)

    @property
    def provider(self):
        """The object this pane binds (the shipped worker, the local provider, or the elevated one).

        `None` — no provider yet: a remote pane waiting for the session's connection. A LOCAL pane
        and an ELEVATED one always have theirs, which is why the waiting state is a REMOTE state.
        """
        if self._source == SOURCE_LOCAL:
            return self._local_provider
        if self._elevated_provider is not None:
            return self._elevated_provider
        return self.worker

    @property
    def worker(self):
        """The SHARED transport worker — the CONTAINER owns the binding (SFTP_PANES.md §2).

        A LOCAL pane reads the OS disk through its OWN provider and never through this one: the
        property answers the session's worker whatever the source, so a remote call site keeps
        its shipped meaning (LOCAL_PANE.md §1).
        """
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

    # ── Worker binding (the container calls these) ───────────────────────

    def bind_worker(self, old_worker, new_worker, source: str = ""):
        """Bind/unbind the pane's PROVIDER: `None` — the "waiting for connection" state.

        The OLD provider is passed explicitly because the container has already replaced its
        own reference when this runs — the pane must disconnect from the transport it was
        really listening to, not from the new one. `_bound_provider` is the DECLARED record of
        what this pane is really connected to, so it WINS over the argument: a pane that bound a
        provider of its OWN (a LOCAL or an ELEVATED one) is never left listening to two.

        A pane's bookkeeping belongs to ONE provider, so every task map is cleared here: a
        listing, a read, an operation or a completer answer of the previous server must
        never land in this one. The `source` keyword (v1.7.4rc1) is what a SWITCH passes: the
        pane adopts the source and binds the provider that goes with it, while the container's
        own call (`bind_worker(None, worker)`) keeps every pane on the source it holds.
        """
        if source:
            self._source = SOURCE_LOCAL if str(source) == SOURCE_LOCAL else SOURCE_REMOTE
        old = self._bound_provider if self._bound_provider is not None else old_worker
        if old is None:
            old = self._disconnect_current()
        if self._source == SOURCE_LOCAL:
            # A LOCAL pane reads the OS disk and NOTHING else (LOCAL_PANE.md §1), however often the
            # session re-binds its transport: the container's worker never lands on this pane.
            new_worker = self._ensure_local_provider()
        elif self._elevated_provider is not None:
            # The same rule for the ELEVATED pane (ELEVATED_PANE.md §1): its provider is the
            # client of another user, and the session's transport never lands on it.
            new_worker = self._elevated_provider
        self._disconnect_worker(old)
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
        self._op_targets.clear()
        self._batches.clear()
        self.path_completer_model.setStringList([])
        # v1.3.1.1: the previewability facts belong to ONE transport/session — a new
        # worker (a new connection, possibly another server on the same paths) starts
        # with a clean listing.
        self._blocked.clear()
        self.btn_cancel.setEnabled(False)

        if new_worker is None:
            self._waiting = True
            self._bound_provider = None
            self._current_dir = self.paths.root()
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
            self._sync_source_availability()
            return

        self._waiting = False
        for name in WORKER_SIGNAL_NAMES:
            sig = getattr(new_worker, name, None)
            slot = getattr(self, "_on_" + name, None)
            if sig is None or slot is None:
                continue
            sig.connect(slot)
        self._bound_provider = new_worker
        self._sync_transfer_availability()
        self.path_label.setReadOnly(False)
        self._sync_source_availability()
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
        """Drop this pane's slots from the provider it is REALLY bound to (idempotent).

        The EXACT bound slot is what disconnects: `signal.disconnect(<the receiver QObject>)` is a
        TypeError in PySide6 6.11, and swallowing it left the pane listening to the provider it had
        just left — whose task ids then collided with the new one's. A provider this pane never
        bound is not asked (`_bound_provider` is the ONE record of the connection).
        """
        if worker is None or worker is not self._bound_provider:
            return
        self._bound_provider = None
        # A QUEUED emission of the provider just left is delivered even after the disconnect (Qt
        # does not cancel a posted call), and task ids are per provider: the late answer would pop
        # the fresh entry of the new one. The pane's pending calls go with the provider.
        try:
            QCoreApplication.removePostedEvents(self, QEvent.Type.MetaCall)
        except (RuntimeError, TypeError):
            pass  # no event loop yet (a bare construction) — nothing is queued anyway
        for name in WORKER_SIGNAL_NAMES:
            sig = getattr(worker, name, None)
            slot = getattr(self, "_on_" + name, None)
            if sig is None or slot is None:
                continue
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass  # no connection existed / the worker is already gone

    def _disconnect_current(self):
        """The provider this pane is REALLY bound to — read BEFORE a source change (v1.7.4rc1).

        The shipped `worker` property answers the container's transport whatever the source, so
        a local pane needs this to find the object it must disconnect from.
        """
        return self.provider

    def _ensure_local_provider(self):
        """The pane's OWN provider, created once and kept for the pane's whole life.

        The thread starts with the first Local switch (a pane that never goes local costs no
        thread at all) and lives until `release()`: a switch back and forth therefore keeps the
        local directory, the listing and the costs of nothing.
        """
        if self._local_provider is None:
            self._local_provider = local_fs.LocalFsWorker(root=self.paths.root(), parent=self)
            self._local_provider.start()
        return self._local_provider

    def shutdown_provider(self):
        """Stop the pane's local provider (the pane is going away). Never raises.

        A thread that outlives its wait budget is registered as an ORPHAN instead of being left
        to GC (`AGENTS.md` §4.8); the shipped worker of the session belongs to the page and is
        NOT touched here.
        """
        provider = self._local_provider
        self._local_provider = None
        if provider is None:
            return
        try:
            provider.shutdown(local_fs.LOCAL_SHUTDOWN_WAIT_MS)
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        try:
            if provider.isRunning():
                local_fs.register_orphan_local_provider(provider)
        except RuntimeError:
            pass   # the C++ object is already gone

    def set_source(self, source: str, notify: bool = True) -> bool:
        """Switch this pane's DATA SOURCE and re-bind its provider (v1.7.4rc1).

        The pane's own bookkeeping belongs to ONE provider, so the switch goes through the SAME
        `bind_worker()` path a new connection takes: the old provider is disconnected, every task
        map is cleared and the new provider is bound and listed. `False` — the switch was refused
        (the source is unknown, or it is not allowed on this pane at all), and the caller puts its
        control back; a refusal that is asked for is SAID, never a silent no-op.

        v1.8: the control has a THIRD position. `SOURCE_ELEVATED` is the CLIENT's token and not a
        data source (`ELEVATED_PANE.md` §1), so it is delegated to the elevation cluster and the
        data source below stays the shipped pair.
        """
        token = str(source or "")
        if token == SOURCE_ELEVATED:
            return bool(self.begin_elevation(notify=notify))
        target = SOURCE_LOCAL if token == SOURCE_LOCAL else SOURCE_REMOTE
        if self._elevated_provider is not None or self._elevation_pending:
            # A switch AWAY from the elevated source drops the elevation first (its provider and
            # its client are not the session's), then continues on the shipped path.
            return bool(self.leave_elevation(target, notify=notify))
        if target == self._source:
            self._sync_source_availability()
            return True
        allowed = True
        can_use = getattr(self._container, "can_use_local", None)
        if target == SOURCE_LOCAL and callable(can_use):
            allowed = bool(can_use(self))
        if not allowed:
            if notify:
                self.message.emit(_t(LOCAL_UNAVAILABLE_HINT))
            self._sync_source_availability()
            return False
        old = self._disconnect_current()
        # The directory belongs to the SOURCE (LOCAL_PANE.md §4): the OS look this pane already
        # had survives a round trip, while the way back is the session's opening rule — never the
        # other dialect's path, and never the per-server memory on the OS disk.
        if self._source == SOURCE_LOCAL and self._current_dir:
            self._local_dir = self._current_dir
        self._source = target
        self._current_dir = self._local_dir if target == SOURCE_LOCAL and self._local_dir \
            else self.paths.root()
        self._restored = target == SOURCE_LOCAL
        # v1.7.5: the header line names the SOURCE — it moves with the switch, while the ADDRESS BAR
        # keeps the shipped wording (the current directory; `bind_worker` writes the waiting line
        # when there is no transport), so "This computer" never lands in a path.
        self._sync_header()
        self._set_path_text(self._current_dir)
        # The way BACK re-binds the SESSION's transport (a remote pane IS the session's tree,
        # §1): without it the pane would sit in the "waiting" state with an empty listing.
        self.bind_worker(old, None if target == SOURCE_LOCAL else self.worker, source=target)
        self._sync_source_availability()
        return True

    def _on_source_switch(self, source: str):
        """The switch widget asked for a source: try it and put the control back on a refusal."""
        if not self.set_source(source):
            self._sync_source_availability()

    def _sync_source_availability(self):
        """Show the pane's source on its switch and say whether it may be switched at all.

        The LOCAL and the ELEVATED sources are refused for the FIRST pane and while the container
        holds ONE pane (`LOCAL_PANE.md` §4, `ELEVATED_PANE.md` §4): the commander is what makes "the
        other side" a concept. The switch itself stays visible in the shipped look — it is the
        pane's own control — and is simply not offered until it can do something.
        """
        switch = getattr(self, "source_switch", None)
        if switch is None:
            return
        enabled = bool(getattr(self, "_secondary", False))
        available = True
        can_use = getattr(self._container, "can_use_local", None)
        if callable(can_use):
            try:
                available = bool(can_use(self))
            except (RuntimeError, AttributeError):
                available = True
        _sync_source_switch(switch, self._switch_state(), enabled=enabled, available=available)

    def _sync_transfer_availability(self):
        """Enable the shared row for a bound provider (v1.7.4rc2: a local pane transfers too).

        The row follows the PROVIDER and not the source: both panes move bytes now — a remote one
        through the session's transport, a local one through its own engine (LOCAL_PANE.md §5/§6) —
        and a pane with no provider at all keeps the shipped "waiting" row.
        """
        bound = not self._waiting and self.provider is not None
        try:
            self.btn_up.setEnabled(bound)
            self.btn_refresh.setEnabled(bound)
            self.btn_upload.setEnabled(bound)
            self.btn_download.setEnabled(bound)
        except RuntimeError:
            pass  # Qt teardown — the row is already gone

    def release(self):
        """Detach the pane: unbind the provider, stop a local or an ELEVATED one, drop the preview."""
        self._disconnect_worker(self._disconnect_current())
        self.shutdown_elevated()
        self.shutdown_provider()
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
                       getattr(self, "hints_label", None),
                       getattr(self, "header_label", None)):
            if widget is None:
                continue
            try:
                _apply_status_style(widget, "status.sftp_row")
            except RuntimeError:
                continue  # Qt teardown — this label is already destroyed
        switch = getattr(self, "source_switch", None)
        if switch is not None:
            try:
                _apply_status_style(switch.lbl, "status.sftp_row")
            except RuntimeError:
                pass  # Qt teardown — the switch is already gone
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
            # v1.7.4rc1: the source switch of the pane (its label, its two buttons and the
            # availability tooltip) is UI text like every other row of this bar.
            switch = getattr(self, "source_switch", None)
            if switch is not None:
                switch.retranslate()
                self._sync_source_availability()
            # v1.7rc3: the hint row of the SECOND pane (five `sftp.hint.*` keys + the pane
            # toggle, the mark key and the open key) — re-read in the active language. The
            # row is re-elided by the layout on the next pass, so nothing else is needed.
            self._sync_secondary_ui()
            # v1.7.5: the SOURCE header line — its local wording is the shipped key, and an alias
            # is data that is simply put back unchanged (never translated).
            self._sync_header()
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

    # ── the file operations the row context menu fires (ROADMAP task 1) ───────────────

    def _op_new_folder(self):
        """New folder in the CURRENT directory (mkdir through THIS pane's provider queue)."""
        if self._refuse_elevated_write() or self._refuse_without_provider():
            return
        name = self._prompt_name(_t("sftp.op.new_folder"))
        if not name:
            return
        self._queue_op(self.provider.queue_mkdir(self._current_dir, name), KIND_MKDIR)

    def _op_rename(self, item):
        """Rename a row inside its own directory (only the NAME changes)."""
        if self._refuse_elevated_write() or self._refuse_without_provider():
            return
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        current = self.paths.basename(path)
        name = self._prompt_name(_t("sftp.op.rename"), current)
        if not name or name == current:
            return   # cancelled, or the name did not change — nothing to do
        self._queue_op(self.provider.queue_rename(path, name), KIND_RENAME)

    def _op_delete(self, item):
        """Delete a row — with a confirmation (QMessageBox — a module attribute).

        A directory is removed with rmdir: a NON-EMPTY one reports the provider's error
        (a recursive delete is not in this version). v1.7.4rc1: the confirmation of a LOCAL
        row SAYS that the delete is permanent — there is no recycle bin (LOCAL_PANE.md §4).
        v1.8: an ELEVATED pane refuses the delete before the question (ELEVATED_PANE.md §5).
        """
        if self._refuse_elevated_write() or self._refuse_without_provider():
            return
        path = item.data(0, self.PATH_ROLE)
        if not path:
            return
        is_dir = bool(item.data(0, self.ISDIR_ROLE))
        key = "sftp.local.delete_confirm" if self.source == SOURCE_LOCAL \
            else "sftp.op.delete_confirm"
        box = QMessageBox   # the monkeypatch STAB.QMessageBox works in the tests
        reply = box.question(
            self, _t("sftp.op.delete"),
            _t(key, name=self.paths.basename(path)),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return
        self._queue_op(self.provider.queue_delete(path, is_dir), KIND_DELETE)

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
        # v1.7.5: the listing's sort (a view state) and the reader's ceiling belong to the PANE.
        "_sort_column", "_sort_desc", "_viewer_cap",
        # v1.9.3: the reader's ENCODING choice and the path its preview holds (the choice re-reads it).
        "_viewer_encoding_choice", "_viewer_path",
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
        #: v1.8: the session's live `paramiko.Transport`, published by the page (`set_transport`)
        #: because the elevated channel rides it (`ELEVATED_PANE.md` §2).
        self._transport = None
        self._released = False
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
        #: v1.7.5: the login user — the `user@host` fallback of a pane's SOURCE header line.
        self._session_user = ""
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

    def set_session_info(self, key: str = "", label: str = "", host: str = "", port=None,
                         user: str = ""):
        """The SESSION this container lists (called once by the page that builds it).

        The key is the `history_key()` of the server — the same fact the per-server directory
        memory is filed under — and `(host, port)` is what turns a send into the server-side
        `queue_copy()` path instead of a relay. A bare container (a unit test) simply has no
        identity: no target is offered and no directory is remembered.

        v1.7.5: `user` joins the identity because the pane's SOURCE HEADER LINE falls back to
        `user@host` when the session was never identified (LOCAL_PANE.md §3) — and every pane
        re-reads its header here, which is what makes the line say the session it belongs to.
        """
        self._session_key = str(key or "")
        self._session_label = str(label or "")
        self._session_host = str(host or "")
        self._session_port = port
        self._session_user = str(user or "")
        self._sync_pane_headers()

    #: The session identity the pane's header line reads — ONE reader per fact (v1.7.5).
    def session_key(self) -> str:
        """The stable identity of this session ("" — a container nobody identified)."""
        return str(self._session_key or "")

    def session_label(self) -> str:
        """The session's ALIAS (`set_session_info`), or "" when it was never identified."""
        return str(self._session_label or "")

    def session_user(self) -> str:
        """The login user of the session (the `user@host` fallback of the header line)."""
        return str(self._session_user or "")

    def session_host(self) -> str:
        """The host of the session (the `user@host` fallback of the header line)."""
        return str(self._session_host or "")

    def _sync_pane_headers(self):
        """Let every pane re-read its SOURCE header line (the identity just changed). Never raises."""
        for pane in list(self._panes):
            try:
                pane._sync_header()
            except (RuntimeError, AttributeError):
                pass  # Qt teardown / a bare stub — the line keeps what it has

    def apply_viewer_max_bytes(self, value) -> int:
        """Apply a new preview CEILING to every pane of this container (v1.7.5).

        The settings hub owns the key (it writes it on OK); the live containers are told here, so
        an OPEN tab reads with the new cap at once and the "no preview" facts of the old one are
        dropped pane by pane (`set_viewer_max_bytes`). Never raises.
        """
        cap = clamp_viewer_max_bytes(value)
        for pane in list(self._panes):
            try:
                cap = pane.set_viewer_max_bytes(cap)
            except (RuntimeError, AttributeError):
                pass  # Qt teardown / a bare stub — the pane keeps its own
        return cap

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
                                 user=self._session_user, worker=self._worker,
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

    def apply_viewer_encoding(self, codec) -> str:
        """Write the ONE encoding key and apply it to EVERY pane of this container (v1.9.3).

        The reader's second global setting, on the word-wrap rule: ONE resolved value for both
        panes and every session, and a pane whose preview is open RE-READS its file (the shown text
        was decoded with the previous choice). Returns the NORMALISED value that was applied.
        """
        resolved = normalize_viewer_encoding(codec)
        save_viewer_encoding(resolved)
        for pane in list(self._panes):
            try:
                pane.set_viewer_encoding(resolved, persist=False)
            except RuntimeError:
                continue   # Qt teardown — the pane is already gone
        return resolved

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

    def pane_for_provider(self, provider):
        """The pane whose slots are BOUND to `provider` (`None` — no pane holds it, v1.7.4).

        ONE pane answers ONE provider (§1), so a batch that runs on a provider the pane that
        STARTED it no longer holds — a local pane uploading through the session's transport — is
        COUNTED by the pane bound to that transport.
        """
        if provider is None:
            return None
        for pane in list(self._panes):
            try:
                if pane._bound_provider is provider:
                    return pane
            except RuntimeError:
                continue   # Qt teardown — that pane is already gone
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
                if pane.source != SOURCE_REMOTE:
                    continue   # v1.7.4rc1: a LOCAL pane owns its listing (LOCAL_PANE.md §1)
                if pane.current_dir == path:
                    pane._relist(path)
            except RuntimeError:
                continue   # Qt teardown — the pane is already gone

    def relist_pane(self, pane, path: str):
        """Re-list the ONE listing a finished transfer really CHANGED (v1.7.4rc2).

        The destination of a batch answers through the dialect of the pane it belongs to: a REMOTE
        path keeps the shipped rule (`relist_dir` re-lists every remote pane showing it, and the
        copy may have been started in either one), while a LOCAL path belongs to the pane whose
        provider owns it and to nobody else — the OS disk is nobody's server, and re-listing
        another pane there would navigate it to a path of the wrong dialect.
        """
        if not path or pane is None:
            return
        try:
            local = getattr(pane, "source", SOURCE_REMOTE) == SOURCE_LOCAL
        except RuntimeError:
            return   # Qt teardown — the pane is already gone
        if not local:
            self.relist_dir(path)
            return
        try:
            if pane in list(self._panes) and pane.paths.same(pane.current_dir, path):
                pane._relist(path)
        except (RuntimeError, AttributeError):
            return   # Qt teardown — the pane is already gone

    # ── v1.7.4rc1: the source of a pane (LOCAL_PANE.md §4) ───────────────

    def can_use_local(self, pane) -> bool:
        """May THIS pane read the OS disk? The ONE question the switch and the pane ask.

        TWO conditions, both structural (LOCAL_PANE.md §4): the container must hold TWO panes —
        the Commander is what makes "the other side" a concept, so with one pane there is
        nothing to browse the local disk BESIDE — and the pane must be the SECOND one, because
        the first is the SESSION's own remote tree (the cwd follow, the `Send to…` provider and
        the Files panel all address it).

        A single-pane view of a SESSION (`terminal_mode = "tabs"`'s dock and the v1.7.1 Files
        PANEL) therefore answers False by construction: it holds ONE pane, and the ask is refused
        with ONE sentence instead of a dead control.
        """
        if pane is None or pane not in self._panes:
            return False
        if len(self._panes) < 2:
            return False
        return pane is not self._panes[0]

    def can_elevate(self, pane) -> bool:
        """May THIS pane read the server as ANOTHER user? The sibling of `can_use_local()`.

        The SAME two structural conditions, for the same reasons (`ELEVATED_PANE.md` §4): the
        elevation replaces the provider of a pane BESIDE the session's own tree, so it is offered
        on the SECOND pane of a two-pane container alone — the first pane, the dock's single-pane
        view and the Files panel answer False and are refused with ONE sentence.
        """
        return self.can_use_local(pane)

    # ── v1.8: the SESSION's transport, published for the elevation (ELEVATED_PANE.md §2) ──

    def set_transport(self, transport):
        """Publish the live `paramiko.Transport` of this session (the page's ONE call).

        The elevated channel rides the transport the Files tab already uses, so the pane needs the
        object and may not reach into the session's worker for it. `None` — the transport is gone:
        every pane drops an elevation that has no channel left, instead of listing through a dead
        one. Never raises.
        """
        self._transport = transport
        if transport is not None:
            return
        for pane in list(self._panes):
            try:
                pane.transport_lost()
            except (RuntimeError, AttributeError):
                continue   # Qt teardown / a bare stub — nothing to drop

    def transport(self):
        """The live transport of this session (`None` — never connected / already gone)."""
        return getattr(self, "_transport", None)

    def pane_source(self, pane) -> str:
        """The source a pane reads (`SOURCE_REMOTE` for a pane this container does not hold)."""
        try:
            return str(pane.source)
        except (AttributeError, RuntimeError):
            return SOURCE_REMOTE

    def set_pane_source(self, pane, source: str, notify: bool = True) -> bool:
        """Switch ONE pane's source through the pane (the container's door, v1.7.4rc1)."""
        if pane is None or pane not in self._panes:
            return False
        try:
            return bool(pane.set_source(source, notify=notify))
        except (RuntimeError, AttributeError):
            return False

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

        v1.7.4rc1: the SECOND pane is also the ONE pane whose source may be switched to the OS
        disk (LOCAL_PANE.md §4) — the switch is enabled by `_sync_hint_rows()` below, which is
        why the pane is created and then told its role.

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

    def release(self):
        """The container is going away: stop EVERY pane's provider and drop its preview.

        The tab's ONE teardown door (the page's idempotent `shutdown()` calls it, and so does a
        pane that leaves): a LOCAL pane owns a QThread of its own (`LOCAL_PANE.md` §1), and a
        thread that is still running when the widget tree dies takes the process with it
        (AGENTS.md §4.8). Idempotent, never raises, and the SESSION's worker is NOT touched.
        """
        if self._released:
            return
        self._released = True
        for pane in list(self._panes):
            try:
                self._close_viewer_of(pane)
            except Exception:  # noqa: BLE001 — teardown robustness
                pass
            try:
                pane.release()
            except Exception:  # noqa: BLE001 — teardown robustness
                pass

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


# The LIVE-NAMESPACE SEAMS, declared once: every name a `sftp_pane_*.py` mixin resolves on THIS
# module at call time (`host_attr`). The declaration IS the seam — it keeps the name importable, it
# is the substitution point a suite patches, and it stops a static analyser from reading a live seam
# as a dead import (`AGENTS.md` §4.1, §4.3), so it comes LAST.
MODULE_FACADE_SEAMS = (
    # ── the pure readers the listing and the viewer resolve here (rc5 moved them to their own
    # ── module and re-exports them from this path, so the seam outlives the wave) ──
    format_size, format_mtime, preview_block_reason, decode_text, ask_conflict, read_was_truncated,
    clamp_viewer_max_bytes, save_viewer_wrap, save_viewer_encoding, normalize_viewer_encoding,
    VIEWER_WRAP_CONFIG, VIEWER_ENCODING_CONFIG, VIEWER_ENCODING_DEFAULT, VIEWER_ENCODINGS,
    resolve_viewer_wrap, resolve_viewer_encoding,
    # ── the Qt surfaces the transfer and the drag & drop mixins resolve here: a suite substitutes
    # ── them on THIS module (`STAB.QFileDialog = <fake>` and its two siblings) ──
    QFileDialog, QInputDialog, QMenu,
    # ── the pane's source vocabulary, the batch's dispatcher and the listing's row class ──
    SOURCE_REMOTE, SOURCE_LOCAL, SOURCE_ELEVATED, PANE_SOURCES, dialect_for, local_error_text,
    name_refusal_text, local_files, pane_payload, _SftpRowItem, READ_ERROR_TOO_LARGE,
    # ── v1.8: the ELEVATION seams the `sftp_pane_elevated.py` mixin resolves here (the handshake
    # ── class, the dialogue, the shipped engine over the elevated client and its orphan registry)
    ElevatedHandshake, ask_elevation, SftpWorker, register_orphan_sftp_worker,
    # ── the cluster facts the waves moved OUT of this module and RE-EXPORTS: the shipped surface a
    # ── caller and the suite read on `modules.sftp_tab` (`PANE_SHORTCUTS`, the cap's range, the
    # ── measured freeze slope) stays importable HERE ──
    PANE_SHORTCUTS, PANE_HINTS, HINT_SEPARATOR, VIEWER_MAX_BYTES_STEP, VIEWER_MAX_BYTES_WARN,
    VIEWER_FREEZE_MS_PER_MB, viewer_freeze_seconds,
)
