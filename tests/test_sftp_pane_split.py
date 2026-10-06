# -*- coding: utf-8 -*-
"""The two waves of the `sftp_tab.py` split: `_SftpPane` is a FACADE over six pane mixins.

Wave 1 (`1.8rc4`) moved 76 methods into `modules/sftp_pane_walk.py` (the pane-scoped keys and the
mc/far walk), `modules/sftp_pane_listing.py` (the listing, its navigation and its address bar) and
`modules/sftp_pane_viewer.py` (the read-only preview); wave 2 (`1.8rc5`) moved the transfer family
into `modules/sftp_pane_transfer.py`, the drag & drop with the row context menu into
`modules/sftp_pane_dnd.py` and the pure readers into `modules/sftp_pane_helpers.py`. Both waves kept
the same bodies, public names and facade seams. This file pins the STRUCTURE: the family, the MRO,
the one-owner rule, the cycle, the headers, the re-exported facts — and the two defects wave 1
carried (`N46` the cut character, `N57` the ceiling's measured GUI cost).
"""
import ast
import os
import re

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, pane_family_files,
                     pane_family_sources, pane_func_body, pane_func_owner,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import modules.sftp_tab as ST  # noqa: E402
import modules.sftp_pane_walk as PWT  # noqa: E402
import modules.sftp_pane_listing as PLS  # noqa: E402
import modules.sftp_pane_viewer as PVW  # noqa: E402
import modules.sftp_pane_transfer as PTR  # noqa: E402
import modules.sftp_pane_dnd as PDND  # noqa: E402
import modules.sftp_pane_helpers as PH  # noqa: E402
import modules.syntax_highlight as SH  # noqa: E402
from modules.sftp_worker import READ_ERROR_TOO_LARGE  # noqa: E402
from ui.mixin_support import host_attr  # noqa: E402
from version import APP_VERSION, VERSION_FORMAT  # noqa: E402

LANGS = load_i18n_langs(ROOT)

# The WAVE-1 plan: the three files, their mixin, their methods — the ONE table this file audits.
WAVE = {
    "modules/sftp_pane_walk.py": ("SftpPaneWalkMixin", PWT.SftpPaneWalkMixin, [
        "_build_pane_shortcuts", "pane_shortcut", "set_pane_keys_enabled", "secondary",
        "hint_text", "_sync_secondary_ui", "focus_listing", "_step_current_row", "_move_cursor",
        "_set_row_marked", "_row_marked", "_mark_current_row", "_on_pane_key", "_switch_pane",
        "_open_current_row", "_leave_current_dir", "_current_row", "_cmd_view", "_cmd_copy",
        "_cmd_move_rename", "_cmd_mkdir", "_cmd_delete", "_on_item_double_clicked"]),
    "modules/sftp_pane_listing.py": ("SftpPaneListingMixin", PLS.SftpPaneListingMixin, [
        "current_dir", "go_up", "_navigate", "follow_directory", "_relist", "_set_path_text",
        "_on_path_entered", "_on_normalize_ready", "_on_path_edited", "_fill_completer",
        "_on_list_ready", "_focus_first_row", "_add_entry_item", "_dir_icon", "_file_icon",
        "_apply_preview_marker", "_blocked_tooltip", "_blocked_icon", "_mark_row", "header_text",
        "_sync_header", "source_header_label", "_on_header_clicked", "apply_sort",
        "_sort_is_default"]),
    "modules/sftp_pane_viewer.py": ("SftpPaneViewerMixin", PVW.SftpPaneViewerMixin, [
        "viewer_cap", "set_viewer_max_bytes", "_mark_rows", "_known_size", "_open_viewer",
        "_on_read_ready", "_show_viewer", "_viewer_splitter", "_layout_viewer_share",
        "viewer_host", "_restore_listing", "present_viewer_in", "restore_viewer",
        "_ensure_highlighter", "_build_viewer_menu", "_on_viewer_menu", "_on_wrap_toggled",
        "_apply_viewer_wrap", "set_viewer_wrap", "viewer_wrap", "_lazy_margin",
        "_viewer_block_range", "_highlight_visible", "_on_viewer_update_request",
        "viewer_highlighter", "viewer_language", "viewer_encoding", "close_viewer"]),
}
# The WAVE-2 plan: the transfers with the conflict question and the batch copy/move, the drag & drop
# with the row context menu, and the pure helpers in their own module.
WAVE2 = {
    "modules/sftp_pane_transfer.py": ("SftpPaneTransferMixin", PTR.SftpPaneTransferMixin, [
        "_on_task_error", "_op_error_text", "_read_error_text", "_on_upload", "_on_download",
        "_refuse_without_provider", "_on_cancel", "_names_in_current_dir", "_ask_conflict",
        "_conflict_decision", "_prompt_name", "_queue_uploads", "_queue_downloads",
        "_remember_transfer", "_rows_for_batch", "_remote_batch", "_pane_source",
        "_batch_provider", "_queue_transfer_batch", "_queue_batch_item", "_open_batch",
        "_count_batch", "_finish_batch", "_answer_batch_task", "_remote_error_text",
        "_on_task_started", "_on_task_done", "_on_task_cancelled", "_on_task_finished"]),
    "modules/sftp_pane_dnd.py": ("SftpPaneDndMixin", PDND.SftpPaneDndMixin, [
        "_on_context_menu", "_build_context_menu", "_build_send_menu", "_op_send_to",
        "eventFilter", "_popup_open", "local_files", "dragEnterEvent", "dragMoveEvent",
        "dropEvent", "_drop_is_move", "_on_pane_drop", "_item_under", "_drop_target_dir",
        "_on_drop"]),
}
# The PURE helpers of the family: no class, five readers the facade re-exports.
HELPERS = ("modules/sftp_pane_helpers.py",
           ["format_size", "format_mtime", "decode_text", "preview_block_reason", "ask_conflict"])
# The SIXTH mixin, added by the release's own feature (`ELEVATED_PANE.md` §1): the two waves did not
# move it, so it carries no method table of its own — the family count below is what it moves.
ELEVATED = "modules/sftp_pane_elevated.py"
#: the names the FACADE keeps — the assembly, the state accessors, the worker/provider binding, the
#: source switching, the theme/re-text walks and the file operations the context menu fires
FACADE_METHODS = [
    "__init__", "source", "paths", "provider", "worker", "session_key", "activate", "set_active",
    "bind_worker", "_disconnect_worker", "_disconnect_current", "_ensure_local_provider",
    "shutdown_provider", "set_source", "_on_source_switch", "_sync_source_availability",
    "_sync_transfer_availability", "release", "refresh_theme", "retranslate",
    "_op_new_folder", "_op_rename", "_op_delete", "_op_copy_path", "_queue_op",
]
PLANNED_MRO = ["_SftpPane", "SftpPaneWalkMixin", "SftpPaneListingMixin", "SftpPaneViewerMixin",
               "SftpPaneTransferMixin", "SftpPaneDndMixin", "SftpPaneElevatedMixin", "QWidget"]


def _owner_of(obj):
    """The `__qualname__` of a function OR of a property's getter (a mixin may own either)."""
    return getattr(obj.fget if isinstance(obj, property) else obj, "__qualname__", "")


def _class_method_names(rel, cls):
    """Every method NAME a family file defines on `cls` (a property counts once)."""
    out = []
    for node in ast.parse(pane_family_sources(ROOT)[rel]).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out.extend(sub.name for sub in node.body
                       if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return out


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the family and the MRO ==")
# ════════════════════════════════════════════════════════════════════════════

_family = pane_family_files(ROOT)
check("§1 the family is the facade, its six pane mixins and the helpers (ONE glob, so a new "
      "mixin joins by itself)",
      _family[0] == "modules/sftp_tab.py" and len(_family) == 8
      and set(WAVE) | set(WAVE2) | {HELPERS[0], ELEVATED, "modules/sftp_tab.py"} == set(_family),
      str(_family))
check("§1 the five wave files exist, one class each, named as the plan says",
      all(os.path.isfile(os.path.join(ROOT, rel)) for rel in list(WAVE) + list(WAVE2))
      and all(cls.__name__ == name
              for rel, (name, cls, _m) in {**WAVE, **WAVE2}.items()),
      str([(rel, name, cls.__name__) for rel, (name, cls, _m) in WAVE.items()]))
check("§1 the helpers module is a module of five PURE readers (no class of its own)",
      all(callable(getattr(PH, name, None)) for name in HELPERS[1])
      and not [n for n in ast.parse(pane_family_sources(ROOT)[HELPERS[0]]).body
               if isinstance(n, ast.ClassDef)],
      str(HELPERS[1]))
check("§1 the MRO is the planned one (the facade, the six mixins, QWidget)",
      [c.__name__ for c in ST._SftpPane.__mro__][:8] == PLANNED_MRO,
      str([c.__name__ for c in ST._SftpPane.__mro__][:9]))
check("§1 `_SftpPane` itself defines no wave method (the facade half of the one-owner rule)",
      not any(m in ST._SftpPane.__dict__ for _rel, (_n, _c, methods) in {**WAVE, **WAVE2}.items()
              for m in methods))
check("§1 the five classes are the SHIPPED objects the pane resolves (not a private copy)",
      all(isinstance(cls, type) and issubclass(ST._SftpPane, cls)
          for _rel, (_n, cls, _m) in {**WAVE, **WAVE2}.items()))
check("§1 the container's own surface is untouched by the waves (SftpTab is not in the family)",
      all(not rel.startswith("modules/sftp_pane") or "class SftpTab" not in src
          for rel, src in pane_family_sources(ROOT).items())
      and ST.SftpTab.VIEWER_TREE_SHARE == ST._SftpPane.VIEWER_TREE_SHARE
      and ST.SftpTab.PATH_ROLE == ST._SftpPane.PATH_ROLE)

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the one-owner rule, method by method ==")
# ════════════════════════════════════════════════════════════════════════════

_family_src = pane_family_sources(ROOT)
_owner_problems = []
for rel, (name, cls, methods) in {**WAVE, **WAVE2}.items():
    for method in methods:
        fn = getattr(ST._SftpPane, method, None)
        if fn is None:
            _owner_problems.append(f"{method}: missing on the pane")
        elif method not in cls.__dict__:
            _owner_problems.append(f"{method}: not defined in {name}")
        elif _owner_of(fn).split(".")[0] != name:
            _owner_problems.append(f"{method}: owner {_owner_of(fn)}")
        elif method not in _class_method_names(rel, name):
            _owner_problems.append(f"{method}: {rel} does not define it on {name}")
check(f"§2 every one of the {sum(len(m) for _r, (_n, _c, m) in {**WAVE, **WAVE2}.items())} "
      f"moved methods has ONE owner", not _owner_problems, "; ".join(_owner_problems[:6]))
check("§2 the AST reader of the family still finds EVERY wave method (its pins travel with the code)",
      all(pane_func_owner(m, ROOT) for _rel, (_n, _c, methods) in {**WAVE, **WAVE2}.items()
          for m in methods))
check("§2 the method counts are the plan's (23 + 25 + 28 in wave 1, 29 + 15 in wave 2, 25 kept)",
      [len(m) for _rel, (_n, _c, m) in WAVE.items()] == [23, 25, 28]
      and [len(m) for _rel, (_n, _c, m) in WAVE2.items()] == [29, 15]
      and len(_class_method_names("modules/sftp_tab.py", "_SftpPane")) == len(FACADE_METHODS),
      str({rel: len(m) for rel, (_n, _c, m) in WAVE2.items()}))
check("§2 the facade keeps the wave's OWNER list and nothing of it moved (the shared machinery)",
      all(m in _class_method_names("modules/sftp_tab.py", "_SftpPane") for m in FACADE_METHODS)
      and not any(f"def {m}" in _family_src[rel] for rel in {**WAVE, **WAVE2}
                  for m in ("bind_worker", "_op_delete", "_queue_op", "retranslate",
                            "set_source", "shutdown_provider")),
      str([m for m in FACADE_METHODS
           if m not in _class_method_names("modules/sftp_tab.py", "_SftpPane")]))
_dupes = sorted({m for m in FACADE_METHODS for rel in {**WAVE, **WAVE2}
                 if m in _class_method_names(rel, {**WAVE, **WAVE2}[rel][0])})
check("§2 no name is defined by BOTH the facade and a mixin (a second truth is a defect)",
      not _dupes, str(_dupes))
_facade_src = _family_src["modules/sftp_tab.py"]
check("§2 the class-level facts moved with their cluster (no second truth in the facade)",
      ST._SftpPane.VIEWER_TREE_SHARE == 0.45 and ST._SftpPane.VIEWER_MIN_TOTAL_PX == 640
      and ST._SftpPane.WRAP_MARGIN_FACTOR == 2
      and ST._SftpPane.VIEWER_LAZY_MARGIN == SH.VIEWER_LAZY_MARGIN
      and "VIEWER_TREE_SHARE = 0.45" not in _facade_src
      and "VIEWER_TREE_SHARE = 0.45" in _family_src["modules/sftp_pane_viewer.py"]
      and "def secondary" not in _facade_src
      and "def pane_shortcut" not in _facade_src)
_moved_module_names = {
    "modules/sftp_pane_walk.py": ("PANE_SHORTCUTS = (", "PANE_HINTS = (", 'HINT_SEPARATOR = "'),
    "modules/sftp_pane_listing.py": ("SORT_DEFAULT_COLUMN = 0", "SORT_COLUMNS = ("),
    "modules/sftp_pane_viewer.py": ('VIEWER_MAX_BYTES_CONFIG = "', "VIEWER_MAX_BYTES_MAX = ",
                                    "VIEWER_FREEZE_MS_PER_MB = "),
    "modules/sftp_pane_transfer.py": ("class SftpPaneTransferMixin:",),
    "modules/sftp_pane_dnd.py": ("class SftpPaneDndMixin:",),
}
check("§2 the module-level tables moved with their cluster, not copied",
      all(marker in _family_src[rel]
          for rel, markers in _moved_module_names.items() for marker in markers)
      and all(marker not in _facade_src
              for markers in _moved_module_names.values() for marker in markers),
      str(sorted(_moved_module_names)))
check("§2 ...and the facade RE-EXPORTS the facts the suite reads on `modules.sftp_tab`",
      all(hasattr(ST, n) for n in ("PANE_SHORTCUTS", "PANE_HINTS", "HINT_SEPARATOR",
                                   "SORT_DEFAULT_COLUMN", "SORT_COLUMNS",
                                   "VIEWER_MAX_BYTES_CONFIG", "VIEWER_MAX_BYTES_MIN",
                                   "VIEWER_MAX_BYTES_MAX", "VIEWER_MAX_BYTES_STEP",
                                   "VIEWER_MAX_BYTES_WARN", "VIEWER_FREEZE_MS_PER_MB",
                                   "viewer_freeze_seconds",
                                   "format_size", "format_mtime", "decode_text",
                                   "preview_block_reason", "ask_conflict"))
      and ST.PANE_SHORTCUTS is PWT.PANE_SHORTCUTS and ST.SORT_COLUMNS is PLS.SORT_COLUMNS
      and ST.viewer_freeze_seconds is PVW.viewer_freeze_seconds
      and ST.format_size is PH.format_size and ST.ask_conflict is PH.ask_conflict,
      str([n for n in ("PANE_SHORTCUTS", "SORT_COLUMNS", "viewer_freeze_seconds", "format_size",
                       "ask_conflict") if not hasattr(ST, n)]))

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the cycle, the headers and the declared seams ==")
# ════════════════════════════════════════════════════════════════════════════

_FACADE_IMPORT = re.compile(
    r"^\s*(?:from\s+(?:\.{1,2}|modules\.)?sftp_tab\s+import\b"
    r"|from\s+(?:\.+|modules)\s+import\s+sftp_tab\b"
    r"|import\s+(?:modules\.)?sftp_tab\b)")
_cycles = [f"{rel}:{i}" for rel, src in _family_src.items()
           if rel != "modules/sftp_tab.py"
           for i, line in enumerate(src.splitlines(), 1) if _FACADE_IMPORT.match(line)]
check("§3 no mixin imports the facade (the gate is blind to a sibling mixin, and §1 of the "
      "split test proves it is RED on the real shape)", not _cycles, ", ".join(_cycles))
_headers = {}
for rel in list(WAVE) + list(WAVE2) + [HELPERS[0]]:
    doc = ast.parse(_family_src[rel]).body[0]
    _headers[rel] = (doc.value.end_lineno - doc.value.lineno + 1
                     if isinstance(doc, ast.Expr) else 0)
check("§3 every wave module carries a header inside the 12-line budget (AGENTS.md §12)",
      _headers and all(1 <= n <= 12 for n in _headers.values()), str(_headers))
_WAVE_ALL = list(WAVE) + list(WAVE2) + [HELPERS[0]]
check("§3 every wave module that resolves a facade global carries the ONE seam import, and none "
      "of them imports the facade's names",
      all(("from ..ui.mixin_support import host_attr" in _family_src[rel]
           or "from ui.mixin_support import host_attr" in _family_src[rel])
          for rel in WAVE if "host_attr(self," in _family_src[rel])
      and all("sftp_tab import" not in _family_src[rel]
              and "import sftp_tab" not in _family_src[rel] for rel in _WAVE_ALL),
      str([rel for rel in WAVE if "host_attr(self," in _family_src[rel]
           and "mixin_support import host_attr" not in _family_src[rel]]))
check("§3 the wave-2 mixin that needs a facade name WITHOUT a `self` uses the module reader "
      "(the `@staticmethod` half of the same seam)",
      "_facade_attr(\"local_files\")" in _family_src["modules/sftp_pane_dnd.py"]
      and "_facade_attr(\"QMessageBox\", QMessageBox)"
      in _family_src["modules/sftp_pane_helpers.py"])
_seams_raw = tuple(getattr(ST, "MODULE_FACADE_SEAMS", ()))
_seams = tuple(getattr(x, "__name__", x) for x in _seams_raw)
check("§3 the declared seams name every facade global the mixins resolve at call time",
      all(n in _seams_raw for n in (ST.format_size, ST.format_mtime, ST.preview_block_reason,
                                    ST.decode_text, ST.ask_conflict, ST.read_was_truncated,
                                    ST.clamp_viewer_max_bytes, ST.save_viewer_wrap,
                                    ST.SOURCE_LOCAL, ST.SOURCE_REMOTE, ST._SftpRowItem,
                                    READ_ERROR_TOO_LARGE, ST.dialect_for, ST.local_error_text,
                                    ST.name_refusal_text, ST.local_files, ST.pane_payload,
                                    ST.QFileDialog, ST.QInputDialog, ST.QMenu)),
      str([n for n in ("format_size", "ask_conflict", "read_was_truncated", "QMenu")
           if not any(getattr(x, "__name__", x) == n for x in _seams_raw)]))
check("§3 every declared seam is REALLY resolved through `host_attr` at a call site",
      all(f'host_attr(self, "{name}")' in "".join(_family_src[rel] for rel in _WAVE_ALL)
          for name in ("format_size", "preview_block_reason", "decode_text",
                       "read_was_truncated", "clamp_viewer_max_bytes", "save_viewer_wrap",
                       "SOURCE_LOCAL", "SOURCE_REMOTE", "_SftpRowItem", "ask_conflict",
                       "dialect_for", "local_error_text", "name_refusal_text", "local_files",
                       "pane_payload", "QFileDialog", "QMenu")),
      str([n for n in ("format_size", "preview_block_reason", "ask_conflict", "QMenu",
                       "pane_payload")
           if f'host_attr(self, "{n}")' not in "".join(_family_src[r] for r in _WAVE_ALL)]))
check("§3 the pane-scoped shortcut actions still resolve their slots through `getattr` "
      "(the walk may not import the methods it fires)",
      "getattr(self, slot_name, None)" in _family_src["modules/sftp_pane_walk.py"]
      and 'self.tree.pane_key = self._on_pane_key' in _facade_src)

_sentinel = type("_Sentinel", (), {})
_orig = ST.format_size
try:
    ST.format_size = _sentinel
    _pane = ST._SftpPane.__new__(ST._SftpPane)
    check("§3 `host_attr` really sees a swapped facade from the mixin (the test seam survives)",
          host_attr(_pane, "format_size") is _sentinel)
finally:
    ST.format_size = _orig
check("§3 every wave method is reachable on the INSTANCE, not only on the class",
      all(callable(getattr(ST._SftpPane, m, None))
          or isinstance(getattr(ST._SftpPane, m, None), property)
          for _rel, (_n, _c, methods) in {**WAVE, **WAVE2}.items() for m in methods))

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the structural pins (a body is read WHEREVER the family defines it) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the reader finds a moved body (the pin that travels with the code)",
      pane_func_owner("_on_pane_key", ROOT) == "modules/sftp_pane_walk.py"
      and "Key_Backtab" in pane_func_body("_on_pane_key", ROOT)
      and pane_func_owner("_on_list_ready", ROOT) == "modules/sftp_pane_listing.py"
      and "sortItems" not in pane_func_body("_on_list_ready", ROOT)
      and pane_func_owner("present_viewer_in", ROOT) == "modules/sftp_pane_viewer.py"
      and "insertWidget" in pane_func_body("present_viewer_in", ROOT))
check("§4 ...and it finds the wave-2 clusters where they MOVED to",
      pane_func_owner("_queue_transfer_batch", ROOT) == "modules/sftp_pane_transfer.py"
      and "queue_upload" in pane_func_body("_queue_batch_item", ROOT)
      and pane_func_owner("_on_task_error", ROOT) == "modules/sftp_pane_transfer.py"
      and pane_func_owner("_build_context_menu", ROOT) == "modules/sftp_pane_dnd.py"
      and pane_func_owner("_on_drop", ROOT) == "modules/sftp_pane_dnd.py")
check("§4 ...and it still finds the methods the facade kept",
      pane_func_owner("_popup_open", ROOT) == "modules/sftp_pane_dnd.py"
      and pane_func_owner("bind_worker", ROOT) == "modules/sftp_tab.py"
      and pane_func_owner("_op_delete", ROOT) == "modules/sftp_tab.py")
try:
    pane_func_body("_no_such_method_8rc5", ROOT)
    _missing_raised = False
except KeyError:
    _missing_raised = True
check("§4 ...and it answers KeyError for a method no file of the family defines", _missing_raised)
_pin_files = ("tests/test_files_followup.py", "tests/test_local_pane_contract.py")
_pin_text = {rel: open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()
             for rel in _pin_files}
check("§4 the converted pins call the FAMILY reader (not a hand-written file path)",
      all("pane_family_text(" in src for src in _pin_text.values())
      and not any('open(os.path.join(ROOT, "modules", "sftp_tab.py")' in src
                  for src in _pin_text.values()),
      "; ".join(f"{rel}: {src.count('pane_family_text(')}" for rel, src in _pin_text.items()))
check("§4 no test of the suite slices the pane facade's text by hand any more",
      not [name for name in sorted(os.listdir(os.path.join(ROOT, "tests")))
           if name.startswith("test_") and name.endswith(".py")
           and re.search(r'"sftp_tab\.py"[^\n]*\)[^\n]*\.split\("def _',
                         open(os.path.join(ROOT, "tests", name), encoding="utf-8").read())])

# ════════════════════════════════════════════════════════════════════════════
print("== §5 N46 — a byte cut at the ceiling is not a different encoding ==")
# ════════════════════════════════════════════════════════════════════════════

TEXT = "\u0421\u0435\u0440\u0432\u0435\u0440: \u043f\u0440\u043e\u0434\u0430\u043a\u0448\u043d\n" * 4
BUF = TEXT.encode("utf-8")
_CUT = 0
for _n in range(len(BUF), 0, -1):
    try:
        BUF[:_n].decode("utf-8-sig")
    except UnicodeDecodeError:
        _CUT = _n
        break
_HEAD = BUF[:_CUT]
_INTACT = TEXT[:len(_HEAD.decode("utf-8", errors="ignore"))]
check("§5 the probe really cuts a multi-byte character (the case the fix exists for)",
      _CUT and _HEAD[-1] >= 0xC0 and _INTACT, f"cut={_CUT} last={_HEAD[-1]:#x}")
check("§5 the SHIPPED rule still answers latin-1 for that buffer (the defect, pinned)",
      ST.decode_text(_HEAD)[1] == "latin-1")
check("§5 ...and `truncated=True` answers utf-8 with the text of the real prefix",
      ST.decode_text(_HEAD, truncated=True) == (_INTACT, "utf-8"),
      ST.decode_text(_HEAD, truncated=True)[1])
check("§5 a COMPLETE Latin-1 file whose last byte is a lead byte keeps its character "
      "(the counter-case that forbids a blanket decoder)",
      ST.decode_text(b"caf\xe9") == ("caf\xe9", "latin-1")
      and ST.decode_text(b"caf\xe9", truncated=True)[0] != "caf\xe9")
check("§5 a genuinely invalid byte still falls back, truncated or not",
      ST.decode_text(_HEAD + b"\xff\xfe", truncated=True)[1] == "latin-1"
      and ST.decode_text(b"\xff\xfe")[1] == "latin-1")
_cjk = "\u65e5\u672c\u8a9e\u306e\u30c6\u30ad\u30b9\u30c8".encode("utf-8")
check("§5 a 3-byte character is cut the same way (the CJK half of the report)",
      ST.decode_text(_cjk[:-1], truncated=True) == (
          _cjk[:-1].decode("utf-8", errors="ignore"), "utf-8"))
check("§5 `read_was_truncated()` is the ONE pure reader of the cut fact",
      ST.read_was_truncated(5, 1024, 9) is True
      and ST.read_was_truncated(9, 1024, 9) is False
      and ST.read_was_truncated(1024, 1024, 0) is True
      and ST.read_was_truncated(10, 1024, 0) is False
      and ST.read_was_truncated(None, None, None) is False)
check("§5 the viewer resolves the cut fact from the CAP and the listing's size, and passes it on",
      "read_was_truncated" in pane_func_body("_on_read_ready", ROOT)
      and "self._known_size(path)" in pane_func_body("_on_read_ready", ROOT)
      and "truncated=truncated" in pane_func_body("_on_read_ready", ROOT))
check("§5 `decode_text` keeps ONE caller and the new argument is the contract of a capped read",
      sum(src.count("decode_text(") for src in _family_src.values()
          if "def decode_text" not in src) == 1,
      str({rel: src.count("decode_text(") for rel, src in _family_src.items()}))

# ════════════════════════════════════════════════════════════════════════════
print("== §6 N57 — the ceiling's GUI cost is a MEASURED number ==")
# ════════════════════════════════════════════════════════════════════════════

_MIB = 1024 * 1024
check("§6 the freeze estimate is PURE and monotone in the cap",
      ST.viewer_freeze_seconds(_MIB) == ST.VIEWER_FREEZE_MS_PER_MB / 1000.0
      and ST.viewer_freeze_seconds(32 * _MIB) > ST.viewer_freeze_seconds(3 * _MIB) > 0.0)
check("§6 ...and a foreign value answers 0.0 instead of raising",
      ST.viewer_freeze_seconds(None) == 0.0 and ST.viewer_freeze_seconds("x") == 0.0
      and ST.viewer_freeze_seconds(-5) == 0.0)
check("§6 the slope is the release's own measurement (the probe's 32 MB was 5.1 s)",
      4.5 <= ST.viewer_freeze_seconds(32 * _MIB) <= 6.0,
      f"{ST.viewer_freeze_seconds(32 * _MIB):.1f} s")
check("§6 the settings row BUILDS its warning from that number (never a frozen adjective)",
      "viewer_freeze_seconds" in open(
          os.path.join(ROOT, "ui", "settings_dialog.py"), encoding="utf-8").read()
      and "{seconds}" in LANGS["en"]["settings.files.max_bytes_warning"])
check("§6 every language carries the SAME placeholder set for the re-worded key",
      all(set(re.findall(r"\{(\w+)\}", data["settings.files.max_bytes_warning"])) == {"seconds"}
          for data in LANGS.values()),
      {code: sorted(re.findall(r"\{(\w+)\}", data["settings.files.max_bytes_warning"]))
       for code, data in LANGS.items()})
check("§6 the parser has a DECLARED budget and asks for it before parsing",
      SH.within_verify_budget("x" * 10) is True
      and SH.within_verify_budget("x" * (SH.SYNTAX_VERIFY_MAX_CHARS + 1)) is False
      and SH.within_verify_budget(None) is True)
_big = "x" * (SH.SYNTAX_VERIFY_MAX_CHARS + 1)
check("§6 a `.json` over the budget is accepted UNVERIFIED, never parsed (the honesty trade)",
      SH.detect_syntax("/etc/big.json", _big, verify=False) == SH.LANG_JSON
      and SH.detect_syntax("/etc/big.json", _big) == SH.LANG_NUMBERS)
check("§6 ...and the shipped verdict is untouched inside the budget",
      SH.detect_syntax("/etc/app.json", '{"a": 1}') == SH.LANG_JSON
      and SH.detect_syntax("/etc/app.json", '{"a": ') == SH.LANG_NUMBERS
      and SH.detect_syntax("/etc/k8s.yaml", "a: 1") == SH.LANG_YAML)
check("§6 the viewer asks the budget and OWES the heuristic note when it skipped the parse",
      "within_verify_budget" in pane_func_body("_show_viewer", ROOT)
      and "or not verifiable" in pane_func_body("_show_viewer", ROOT))

# ════════════════════════════════════════════════════════════════════════════
print("== §7 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)
check("§7 the waves add NO i18n key and NO schema move (the release's OWN feature adds its 20, "
      "`ELEVATED_PANE.md`; v1.8.1 adds its 41 and v1.8.1.1 ONE)",
      EXPECTED_I18N_KEYS == 925 + 20 + 41 + 1 and VERSION_FORMAT == "0.9",
      f"{EXPECTED_I18N_KEYS} / {VERSION_FORMAT}")
check("§7 the pin names this release", releases_at_least(EXPECTED_APP_VERSION, "1.8"),
      EXPECTED_APP_VERSION)
check("§7 the shipped version is the one the pin names", APP_VERSION == EXPECTED_APP_VERSION,
      f"{APP_VERSION} / {EXPECTED_APP_VERSION}")
check("§7 the pane facade is under 3 000 lines after both waves",
      len(_facade_src.splitlines()) < 3000, f"{len(_facade_src.splitlines())} lines")
finish()
