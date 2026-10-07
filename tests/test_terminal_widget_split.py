# -*- coding: utf-8 -*-
"""`1.8rc5` — the `terminal_widget.py` split: `TerminalWidget` becomes a facade over five canvas mixins.

The wave moved the key map and the input point into `modules/terminal_widget_input.py`, the mouse family
into `modules/terminal_widget_mouse.py`, the find bar into `modules/terminal_widget_find.py`, the
transcript into `modules/terminal_widget_transcript.py` and the local selection into
`modules/terminal_widget_selection.py` — the same bodies, public names and facade seams.
`CURSOR_STYLES` / `resolve_cursor_style()` / `cursor_shape_rect()` and the `FONT_GRID_*` family STAY in
`modules/terminal_widget.py`, where `AGENTS.md` §4.3 declares them. This file pins that structure.
"""
import ast
import os
import re

from _common import (bootstrap, check, finish, canvas_family_files, canvas_family_sources,
                     canvas_func_body, canvas_func_owner, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, EXPECTED_APP_VERSION,
                     EXPECTED_I18N_KEYS, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import modules.terminal_widget as TW  # noqa: E402
import modules.terminal_widget_input as TWI  # noqa: E402
import modules.terminal_widget_mouse as TWM  # noqa: E402
import modules.terminal_widget_find as TWF  # noqa: E402
import modules.terminal_widget_transcript as TWT  # noqa: E402
import modules.terminal_widget_selection as TWS  # noqa: E402
from version import APP_VERSION, VERSION_FORMAT  # noqa: E402

LANGS = load_i18n_langs(ROOT)

# The wave's PLAN: the five files, their mixin, their methods — the ONE table this file audits.
WAVE = {
    "modules/terminal_widget_input.py": ("TerminalInputMixin", TWI.TerminalInputMixin, [
        "event", "_owns_shortcut", "keyPressEvent", "_cursor_key_seq", "_resolve_multi_hub",
        "_multi_active", "_multi_exit", "_send", "_bracketed_paste", "_paste_mode_enabled",
        "send_macro", "multi_excluded", "set_multi_excluded"]),
    "modules/terminal_widget_mouse.py": ("TerminalMouseMixin", TWM.TerminalMouseMixin, [
        "wheelEvent", "_send_wheel_to_pty", "_event_cell", "_send_mouse", "_xterm_button",
        "_held_button", "_mouse_local_override", "_mouse_reports_to_pty", "mousePressEvent",
        "mouseMoveEvent", "mouseReleaseEvent", "select_all", "_build_context_menu",
        "contextMenuEvent"]),
    "modules/terminal_widget_find.py": ("TerminalFindMixin", TWF.TerminalFindMixin, [
        "_ensure_find_bar", "open_find", "close_find", "find_active", "find_state",
        "_on_find_query", "_find_document_lines", "_refresh_find_matches", "_update_find_counter",
        "_reveal_find_match", "find_next", "find_prev", "_step_find", "_visible_find_cells",
        "_drop_find_state"]),
    "modules/terminal_widget_transcript.py": ("TerminalTranscriptMixin",
                                              TWT.TerminalTranscriptMixin, [
        "transcript_active", "transcript_path", "start_transcript", "stop_transcript",
        "write_transcript", "_suggested_transcript_name", "set_transcript_host",
        "toggle_transcript"]),
    "modules/terminal_widget_selection.py": ("TerminalSelectionMixin",
                                             TWS.TerminalSelectionMixin, [
        "_cell_at", "has_selection", "_selected_cells", "clear_selection", "selected_text",
        "copy_selection", "_select_word", "_select_line"]),
}
#: the names the FACADE keeps — the assembly, the metrics, the painting, the cursor, the scrollback,
#: the focus ring, the theme/re-text walks and the window events
FACADE_METHODS = [
    "__init__", "_update_metrics", "grid_metrics", "cell_size", "set_palette", "set_font",
    "font_size", "zoom_font", "cursor_style", "set_cursor_style", "sizeHint", "_format_for",
    "_resolved_colors", "paintEvent", "_paint", "focus_ring_active", "focusInEvent",
    "focusOutEvent", "visible_text", "scroll_page_up", "scroll_page_down", "_release_pin",
    "pinned", "clear_scrollback", "reset_screen", "refresh_theme", "retranslate", "resizeEvent",
    "showEvent", "hideEvent", "_toggle_cursor_blink",
]
#: the module-level facts §4.3 keeps HERE: the cursor SHAPE and the glyph-grid gate's family.
KEPT_FACTS = ("CURSOR_STYLE_BLOCK", "CURSOR_STYLE_BAR", "CURSOR_STYLE_UNDERLINE", "CURSOR_STYLES",
              "CURSOR_STYLE_DEFAULT", "CURSOR_BAR_WIDTH", "CURSOR_UNDERLINE_HEIGHT",
              "resolve_cursor_style", "cursor_shape_rect", "FONT_GRID_SAMPLE", "FONT_GRID_RUN_CELLS",
              "FONT_GRID_TOLERANCE_PX", "font_grid_problems", "run_glyphs", "glyph_label",
              "FontGridMetrics", "FONT_SIZE_MIN", "FONT_SIZE_MAX")
PLANNED_MRO = ["TerminalWidget", "TerminalInputMixin", "TerminalMouseMixin", "TerminalFindMixin",
               "TerminalTranscriptMixin", "TerminalSelectionMixin", "QWidget"]


def _owner_of(obj):
    """The `__qualname__` of a function OR of a property's getter (a mixin may own either)."""
    return getattr(obj.fget if isinstance(obj, property) else obj, "__qualname__", "")


def _class_method_names(rel, cls):
    """Every method NAME a family file defines on `cls` (a property counts once)."""
    out = []
    for node in ast.parse(canvas_family_sources(ROOT)[rel]).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out.extend(sub.name for sub in node.body
                       if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return out


_FAMILY_SRC = canvas_family_sources(ROOT)
_FACADE_SRC = _FAMILY_SRC["modules/terminal_widget.py"]

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the family and the MRO ==")
# ════════════════════════════════════════════════════════════════════════════

_family = canvas_family_files(ROOT)
check("§1 the family is the facade plus its five mixins (ONE glob, so a new mixin joins by itself)",
      _family[0] == "modules/terminal_widget.py" and len(_family) == 6
      and set(WAVE) | {"modules/terminal_widget.py"} == set(_family), str(_family))
check("§1 the five wave files exist, one class each, named as the plan says",
      all(os.path.isfile(os.path.join(ROOT, rel)) for rel in WAVE)
      and all(cls.__name__ == name for rel, (name, cls, _m) in WAVE.items()),
      str([(rel, name, cls.__name__) for rel, (name, cls, _m) in WAVE.items()]))
check("§1 the MRO is the planned one (the facade, the five mixins, QWidget)",
      [c.__name__ for c in TW.TerminalWidget.__mro__][:7] == PLANNED_MRO,
      str([c.__name__ for c in TW.TerminalWidget.__mro__][:8]))
check("§1 `TerminalWidget` itself defines no wave method (the facade half of the one-owner rule)",
      not any(m in TW.TerminalWidget.__dict__ for _rel, (_n, _c, methods) in WAVE.items()
              for m in methods))
check("§1 the five classes are the SHIPPED objects the canvas resolves (not a private copy)",
      all(isinstance(cls, type) and issubclass(TW.TerminalWidget, cls)
          for _rel, (_n, cls, _m) in WAVE.items()))
check("§1 the module-level surface outside the clusters is untouched (the canvas stays ONE module "
      "for its pure readers)",
      all(hasattr(TW, n) for n in KEPT_FACTS)
      and all(callable(getattr(TW, n, None)) for n in
              ("char_width", "is_wide_char", "run_glyphs", "split_row_runs", "selection_cells",
               "word_units", "build_macro_payload", "strip_paste_markers", "get_translator",
               "font_grid_problems", "resolve_cursor_style", "cursor_shape_rect")),
      str([n for n in KEPT_FACTS if not hasattr(TW, n)]))

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the one-owner rule, method by method ==")
# ════════════════════════════════════════════════════════════════════════════

_owner_problems = []
for rel, (name, cls, methods) in WAVE.items():
    for method in methods:
        fn = getattr(TW.TerminalWidget, method, None)
        if fn is None:
            _owner_problems.append(f"{method}: missing on the canvas")
        elif method not in cls.__dict__:
            _owner_problems.append(f"{method}: not defined in {name}")
        elif _owner_of(fn).split(".")[0] != name:
            _owner_problems.append(f"{method}: owner {_owner_of(fn)}")
        elif method not in _class_method_names(rel, name):
            _owner_problems.append(f"{method}: {rel} does not define it on {name}")
check(f"§2 every one of the {sum(len(m) for _r, (_n, _c, m) in WAVE.items())} moved methods has "
      f"ONE owner", not _owner_problems, "; ".join(_owner_problems[:6]))
check("§2 the AST reader of the family finds EVERY wave method (its pins travel with the code)",
      all(canvas_func_owner(m, ROOT) for _rel, (_n, _c, methods) in WAVE.items() for m in methods))
check("§2 the method counts are the plan's (13 + 14 + 15 + 8 + 8 moved, 31 kept by the facade)",
      [len(m) for _rel, (_n, _c, m) in WAVE.items()] == [13, 14, 15, 8, 8]
      and len(_class_method_names("modules/terminal_widget.py", "TerminalWidget"))
      == len(FACADE_METHODS),
      str({rel: len(m) for rel, (_n, _c, m) in WAVE.items()}))
check("§2 the facade keeps the wave's OWNER list and nothing of it moved",
      all(m in _class_method_names("modules/terminal_widget.py", "TerminalWidget")
          for m in FACADE_METHODS)
      and not any(f"def {m}" in _FAMILY_SRC[rel] for rel in WAVE
                  for m in ("_paint", "_release_pin", "set_cursor_style", "clear_scrollback",
                            "_format_for", "zoom_font")),
      str([m for m in FACADE_METHODS
           if m not in _class_method_names("modules/terminal_widget.py", "TerminalWidget")]))
_dupes = sorted({m for m in FACADE_METHODS for rel in WAVE
                 if m in _class_method_names(rel, WAVE[rel][0])})
check("§2 no name is defined by BOTH the facade and a mixin (a second truth is a defect)",
      not _dupes, str(_dupes))
_moved_facts = {
    "modules/terminal_widget_input.py": ("_F_KEY_SEQUENCES = {", "_CLAIMED_KEYS = frozenset({"),
    "modules/terminal_widget_mouse.py": ("MOUSE_BUTTON_LEFT = 0", "MOUSE_X10_LIMIT = 223",
                                         "MOUSE_MOTION_FLAG = 32"),
}
check("§2 the cluster's own tables moved with it, not copied",
      all(marker in _FAMILY_SRC[rel]
          for rel, markers in _moved_facts.items() for marker in markers)
      and all(marker not in _FACADE_SRC
              for markers in _moved_facts.values() for marker in markers),
      str(sorted(_moved_facts)))
check("§2 ...and the facts the suite reads on the CLASS still resolve through the MRO",
      TW.TerminalWidget.MOUSE_X10_LIMIT == 223
      and TW.TerminalWidget.MOUSE_MOTION_FLAG == 32
      and TW.TerminalWidget.CURSOR_COLOR == "#e2e8f0"
      and TW.TerminalWidget.FIND_MATCH_COLOR == TW.TerminalWidget.__mro__[0].__dict__.get(
          "FIND_MATCH_COLOR", TW.TerminalWidget.FIND_MATCH_COLOR)
      and isinstance(TW.TerminalWidget.DOUBLE_CLICK_MS, int))
check("§2 the cursor SHAPE and the glyph-grid gate STAY in `modules/terminal_widget.py` "
      "(AGENTS.md §4.3 declares them there)",
      all(f"def {name}" in _FACADE_SRC or f"{name} = " in _FACADE_SRC
          for name in ("resolve_cursor_style", "cursor_shape_rect", "font_grid_problems",
                       "run_glyphs"))
      and "CURSOR_STYLES = (CURSOR_STYLE_BLOCK" in _FACADE_SRC
      and "FONT_GRID_SAMPLE = " in _FACADE_SRC
      and all(f"def {name}" not in src for rel, src in _FAMILY_SRC.items()
              if rel != "modules/terminal_widget.py"
              for name in ("resolve_cursor_style", "cursor_shape_rect", "font_grid_problems",
                           "run_glyphs")))

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the cycle, the headers and the declared seams ==")
# ════════════════════════════════════════════════════════════════════════════

_FACADE_IMPORT = re.compile(
    r"^\s*(?:from\s+(?:\.{1,2}|modules\.)?terminal_widget\s+import\b"
    r"|from\s+(?:\.+|modules)\s+import\s+terminal_widget\b"
    r"|import\s+(?:modules\.)?terminal_widget\b)")
_cycles = [f"{rel}:{i}" for rel, src in _FAMILY_SRC.items()
           if rel != "modules/terminal_widget.py"
           for i, line in enumerate(src.splitlines(), 1) if _FACADE_IMPORT.match(line)]
check("§3 no mixin imports the facade (the gate is blind to a sibling mixin, and §1 of the split "
      "test proves it is RED on the real shape)", not _cycles, ", ".join(_cycles))
_headers = {}
for rel in WAVE:
    doc = ast.parse(_FAMILY_SRC[rel]).body[0]
    _headers[rel] = (doc.value.end_lineno - doc.value.lineno + 1
                     if isinstance(doc, ast.Expr) else 0)
check("§3 every wave module carries a header inside the 12-line budget (AGENTS.md §12)",
      _headers and all(1 <= n <= 12 for n in _headers.values()), str(_headers))
check("§3 every wave module that resolves a facade global carries the ONE seam import",
      all("mixin_support import host_attr" in _FAMILY_SRC[rel]
          for rel in WAVE if "host_attr(self," in _FAMILY_SRC[rel])
      and all("terminal_widget import" not in _FAMILY_SRC[rel]
              and "import terminal_widget" not in _FAMILY_SRC[rel] for rel in WAVE),
      str([rel for rel in WAVE if "host_attr(self," in _FAMILY_SRC[rel]
           and "mixin_support import host_attr" not in _FAMILY_SRC[rel]]))
_seams_raw = tuple(getattr(TW, "MODULE_FACADE_SEAMS", ()))
check("§3 the declared seams name every facade global the mixins resolve at call time",
      all(n in _seams_raw for n in (TW.QFileDialog, TW.QMenu, TW._get_multi_hub, TW._get_app_log,
                                    TW.get_translator, TW.selection_cells, TW.word_units,
                                    TW.build_macro_payload, TW.strip_paste_markers)),
      str([getattr(x, "__name__", str(x)) for x in _seams_raw]))
check("§3 every declared seam is REALLY resolved through `host_attr` at a call site",
      all(f'host_attr(self, "{name}")' in "".join(_FAMILY_SRC[rel] for rel in WAVE)
          for name in ("QFileDialog", "QMenu", "_get_multi_hub", "_get_app_log", "get_translator",
                       "selection_cells", "word_units", "build_macro_payload",
                       "strip_paste_markers")),
      str([n for n in ("QFileDialog", "QMenu", "_get_multi_hub", "_get_app_log",
                       "get_translator", "selection_cells", "word_units", "build_macro_payload",
                       "strip_paste_markers")
           if f'host_attr(self, "{n}")' not in "".join(_FAMILY_SRC[r] for r in WAVE)]))
check("§3 a Qt class the mixins need but nothing substitutes is a plain import (not a fake seam)",
      "from PySide6.QtCore import QEvent, Qt" in _FAMILY_SRC["modules/terminal_widget_input.py"]
      and "from PySide6.QtWidgets import QApplication"
      in _FAMILY_SRC["modules/terminal_widget_selection.py"]
      and "QEvent" not in [getattr(x, "__name__", str(x)) for x in _seams_raw]
      and "QApplication" not in [getattr(x, "__name__", str(x)) for x in _seams_raw])
check("§3 the two mouse BUTTON tables are resolved on the MIXIN class (a @staticmethod has no "
      "`self` for the seam)",
      "TerminalMouseMixin.MOUSE_BUTTON_LEFT" in _FAMILY_SRC["modules/terminal_widget_mouse.py"]
      and "MOUSE_BUTTON_NONE" in _FAMILY_SRC["modules/terminal_widget_mouse.py"])
check("§3 every wave method is reachable on the INSTANCE, not only on the class",
      all(callable(getattr(TW.TerminalWidget, m, None))
          or isinstance(getattr(TW.TerminalWidget, m, None), property)
          for _rel, (_n, _c, methods) in WAVE.items() for m in methods))

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the structural pins (a body is read WHEREVER the family defines it) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the reader finds a moved body (the pin that travels with the code)",
      canvas_func_owner("keyPressEvent", ROOT) == "modules/terminal_widget_input.py"
      and "Key_F12" in canvas_func_body("keyPressEvent", ROOT)
      and canvas_func_owner("_send", ROOT) == "modules/terminal_widget_input.py"
      and "self._release_pin()" in canvas_func_body("_send", ROOT)
      and canvas_func_owner("_send_mouse", ROOT) == "modules/terminal_widget_mouse.py"
      and canvas_func_owner("_refresh_find_matches", ROOT) == "modules/terminal_widget_find.py"
      and canvas_func_owner("write_transcript", ROOT)
      == "modules/terminal_widget_transcript.py"
      and canvas_func_owner("selected_text", ROOT) == "modules/terminal_widget_selection.py")
check("§4 ...and it still finds the methods the facade kept",
      canvas_func_owner("_paint", ROOT) == "modules/terminal_widget.py"
      and canvas_func_owner("_release_pin", ROOT) == "modules/terminal_widget.py"
      and canvas_func_owner("set_cursor_style", ROOT) == "modules/terminal_widget.py")
try:
    canvas_func_body("_no_such_method_8rc5", ROOT)
    _missing_raised = False
except KeyError:
    _missing_raised = True
check("§4 ...and it answers KeyError for a method no file of the family defines", _missing_raised)
check("§4 the ONE input point keeps its THREE bypasses (the mouse reports, `send_macro` and the "
      "excluded session) and the clipboard path still goes through `_send`",
      "_bracketed_paste" in canvas_func_body("keyPressEvent", ROOT)
      and "send_data" in canvas_func_body("send_macro", ROOT)
      and "_send(" not in canvas_func_body("send_macro", ROOT)
      and "_send(" not in canvas_func_body("_send_mouse", ROOT)
      and "_send(" not in canvas_func_body("_send_wheel_to_pty", ROOT))
check("§4 no test of the suite slices the canvas facade's text by hand any more",
      not [name for name in sorted(os.listdir(os.path.join(ROOT, "tests")))
           if name.startswith("test_") and name.endswith(".py")
           and re.search(r'"terminal_widget\.py"[^\n]*\)[^\n]*\.(?:split|find)\(',
                         open(os.path.join(ROOT, "tests", name), encoding="utf-8").read())])

# ════════════════════════════════════════════════════════════════════════════
print("== §5 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)
check("§5 the wave adds NO i18n key and NO schema move (pure structure; the release's own feature "
      "adds the elevated pane's TWENTY, v1.8.1 its 41 and v1.8.1.1 ONE) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact",
      EXPECTED_I18N_KEYS == 925 + 20 + 41 + 1 + 16 + 23 + 10 and VERSION_FORMAT == "0.9",
      f"{EXPECTED_I18N_KEYS} / {VERSION_FORMAT}")
check("§5 the pin names this release", releases_at_least(EXPECTED_APP_VERSION, "1.8"),
      EXPECTED_APP_VERSION)
check("§5 the shipped version is the one the pin names", APP_VERSION == EXPECTED_APP_VERSION,
      f"{APP_VERSION} / {EXPECTED_APP_VERSION}")
check("§5 the canvas facade is under 1 300 lines after the wave",
      len(_FACADE_SRC.splitlines()) < 1300, f"{len(_FACADE_SRC.splitlines())} lines")
finish()
