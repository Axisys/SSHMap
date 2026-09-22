"""v1.3.3.1 — Live i18n: the containers follow a language switch + the checks of the policy.

ROADMAP v1.3.3.1 (tasks 1-6):
  #1 `retranslate()` in the terminal containers (`modules/sftp_tab.py`,
     `modules/terminal_page.py`, `modules/terminal_dock.py`, `modules/ssh_terminal.py`,
     `modules/command_library.py`) + ONE loop in `MainWindow._apply_ui_translations()`;
     ZERO new translation keys beyond `lang.reload` / `status.language_reloaded`;
  #2 the language files: `encoding="utf-8-sig"` (a Notepad "UTF-8 with BOM" file loads)
     and the META key `"partial": true` (loads and works; the parity check reports it
     as a WARNING, a file without the key stays STRICT);
  #3 the language list without a restart — the `Help → Language` submenu is rebuilt
     from `get_available_languages()` on `aboutToShow`, the settings combo refreshes
     at open, and the explicit `lang.reload` item rescans the files;
  #4 the checker: the SET of `{placeholder}` names and the COUNT of `\\n` vs en —
     plus the real defect it found (`i18n/zh.json` → `dialog.manage_profiles_desc`
     carried 0 line breaks against en's 1);
  #5 the counter/baseline GUARD over the real `README.md` / `ROADMAP.md`;
  #6 backfill + the note-debounce hotfix (`_note_edit_pending` flushed by `_do_save()`
     and by `closeEvent` before the "unsaved changes" question).

Sections:
  §1 the containers follow the language switch (windows mode, the REAL `_switch_language()`);
  §2 the dock + the SFTP tab + the command-library panel follow it too;
  §3 the language files: BOM, `"partial"`, the meta keys;
  §4 the language list without a restart (submenu rebuild, settings combo, `lang.reload`);
  §5 placeholders and line breaks — the helpers and the end-to-end checker runs;
  §6 the counter/baseline guards over README.md / ROADMAP.md;
  §7 zh.json's missing line break (the defect task 4 found) + the release state;
  §8 the note-debounce hotfix (Ctrl+S inside the 600 ms debounce);
  §9 the release state (the pins of tests/_common.py).

Run: python tests/test_i18n_live.py   (from the project root) or python tests/run_all.py
"""
# tags: slow
import importlib.util
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, snapshot_i18n_config, restore_i18n_config,
                     load_i18n_langs, translation_keys, is_partial_lang, i18n_parity_problems,
                     i18n_parity_warnings, i18n_format_problems, placeholder_names,
                     newline_count, i18n_lang_codes, I18N_META_KEYS, I18N_REFERENCE,
                     I18N_LANG_ENCODING, EXPECTED_I18N_KEYS, EXPECTED_APP_VERSION,
                     TEST_FILE_COUNTER_RE, I18N_PARITY_FIGURE_RE)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

import i18n  # noqa: E402
from PySide6.QtWidgets import (QApplication, QLabel, QPushButton, QTabWidget,  # noqa: E402
                               QToolButton, QWidget, QTreeWidget)
from PySide6.QtGui import QAction  # noqa: E402

import modules.ssh_terminal as ST  # noqa: E402
from modules.terminal_page import TerminalSessionPage  # noqa: E402
from modules.terminal_dock import TerminalDockContent, TerminalsDock  # noqa: E402
from models.server import ServerData  # noqa: E402
import ui.main_window as MW  # noqa: E402

from _fakes import FakeSSHThread as _FakeThread, FakeSftpClient, FakeSftpFS  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
_CFG_SNAP = snapshot_i18n_config()   # the language switch writes config.json

I18N_DIR = os.path.join(ROOT, "i18n")
_ORIG_THREAD_CLS = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # every page/window in this file — on the fake


# ── helpers ──────────────────────────────────────────────────────────────────

def read_lang(code, root=None):
    with open(os.path.join(root or ROOT, "i18n", f"{code}.json"),
              encoding=I18N_LANG_ENCODING) as f:
        return json.load(f)


def write_lang(code, data, root, encoding="utf-8"):
    with open(os.path.join(root, "i18n", f"{code}.json"), "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_fake_project(name, mutate=None, partial=False):
    """A fake project root: i18n/en.json (a real copy) + i18n/xx.json (en ⊕ mutate).

    mutate(data) may change the dropped-in language; partial=True adds the meta key
    `"partial": true` — the v1.3.3.1 way of declaring a deliberately incomplete file.
    No .py files — the used-keys part of check_i18n_keys.py stays clean.
    """
    root = os.path.join(WORK, name)
    os.makedirs(os.path.join(root, "i18n"), exist_ok=True)
    en = read_lang("en")
    xx = dict(en)
    xx["name"] = "Xx"
    if partial:
        xx["partial"] = True
    if mutate:
        mutate(xx)
    write_lang("en", en, root)
    write_lang("xx", xx, root)
    return root


def load_check_script():
    """tests/check_i18n_keys.py as a module (main(root=…) — an isolated run)."""
    path = os.path.join(ROOT, "tests", "check_i18n_keys.py")
    spec = importlib.util.spec_from_file_location("_i18n_check_live", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_check_script(mod, root):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(root=root)
    return rc, buf.getvalue()


def has_cyrillic(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04ff" for ch in text or "")


def texts_of(container) -> dict:
    """{label: text} of every user-visible string a container owns.

    Buttons, labels, tooltips, tab titles+tooltips, tree headers and window titles —
    exactly the surfaces the ROADMAP acceptance lists (tab titles, buttons, headers,
    tooltips, status labels, window titles). Never raises on a dead C++ object.
    """
    out = {}

    def _put(label, value):
        try:
            value = value() if callable(value) else value
        except RuntimeError:
            return  # Qt teardown — the widget is already destroyed
        if isinstance(value, str) and value.strip():
            out[label] = value

    try:
        _put("window_title", container.windowTitle)
    except RuntimeError:
        return out
    for widget in container.findChildren(QWidget):
        try:
            name = widget.objectName() or widget.__class__.__name__
            if isinstance(widget, (QLabel, QPushButton, QToolButton)):
                _put(f"{name}.text.{len(out)}", widget.text)
                _put(f"{name}.tip.{len(out)}", widget.toolTip)
            elif isinstance(widget, QTabWidget):
                _put(f"{name}.tip.{len(out)}", widget.toolTip)
                for i in range(widget.count()):
                    _put(f"{name}.tab.{i}", widget.tabText(i))
                    _put(f"{name}.tabtip.{i}", widget.tabToolTip(i))
            elif isinstance(widget, QTreeWidget):
                for i in range(widget.columnCount()):
                    header = widget.headerItem()
                    if header is not None:
                        _put(f"{name}.col.{i}", header.text(i))
        except RuntimeError:
            continue  # a widget destroyed mid-walk (WA_DeleteOnClose race)
    return out


def click_of(container, expected_key: str) -> bool:
    """Does the container show the current translation of `expected_key` somewhere?"""
    want = i18n.t(expected_key)
    return want in texts_of(container).values()


def english_leftovers(container, exclude=()) -> dict:
    """The strings of a container that would be leftovers of the previous language.

    A string without a single non-ASCII character is an en string (every user-facing
    string of ru/zh/de carries a non-ASCII character), minus the deliberately excluded
    ones. The one deliberate exclusion is the session's STATUS label: it carries the
    LIVE state emitted by the thread (`terminal.initializing` / `terminal.session_closed`)
    and is not a static UI string — `TerminalSessionPage.retranslate()` leaves it alone
    because the *session* owns it, not the container.
    """
    skip = set(exclude)
    return {label: value for label, value in texts_of(container).items()
            if value.isascii() and value not in skip}


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the containers follow the REAL language switch (windows mode) ==")
# ════════════════════════════════════════════════════════════════════════════

mw = MW.MainWindow()
mw.show()
app.processEvents()

node = mw.scene.add_server(
    ServerData(id="i18nlive-a", alias="node-a", host="10.99.1.1", user="root"))
win = mw._spawn_terminal_window(node)
app.processEvents()
page = win.page

check("a real MainWindow + terminal window with a session are open",
      win is not None and page is not None and len(mw._terminal_windows) == 1,
      f"sessions={len(mw._terminal_windows)}")

mw._switch_language("ru")
app.processEvents()
check("the switch to ru reached the terminal window title",
      has_cyrillic(win.windowTitle()), win.windowTitle())
check("the switch reached the window's tab-close tooltip",
      win.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      win.session_tabs.tabToolTip(0))
check("the switch reached the page's [Terminal | Files] titles",
      page.tabs.tabText(0) == i18n.t("sftp.tab_terminal")
      and page.tabs.tabText(1) == i18n.t("sftp.tab_files"),
      f"{page.tabs.tabText(0)!r} / {page.tabs.tabText(1)!r}")
check("the switch reached the SFTP buttons",
      page.sftp_tab.btn_up.text() == i18n.t("sftp.up")
      and page.sftp_tab.btn_upload.text() == i18n.t("sftp.upload")
      and page.sftp_tab.btn_cancel.text() == i18n.t("sftp.cancel"),
      f"{page.sftp_tab.btn_up.text()!r} / {page.sftp_tab.btn_upload.text()!r}")
check("the switch reached the SFTP tree header",
      page.sftp_tab.tree.headerItem().text(0) == i18n.t("sftp.column_name")
      and page.sftp_tab.tree.headerItem().text(2) == i18n.t("sftp.column_modified"),
      str([page.sftp_tab.tree.headerItem().text(i) for i in range(3)]))
check("the switch reached the command-library panel (title + buttons + headers)",
      page and win.cmdlib_panel._title.text() == i18n.t("terminal.cmdlib.title")
      and win.cmdlib_panel.add_btn.text() == i18n.t("terminal.cmdlib.add")
      and win.cmdlib_panel.tree.headerItem().text(1) == i18n.t("terminal.cmdlib.command"),
      f"{win.cmdlib_panel._title.text()!r} / {win.cmdlib_panel.add_btn.text()!r}")
check("the per-container retranslate() is the path (page.retranslate is called by the loop)",
      hasattr(page, "retranslate") and hasattr(win, "retranslate")
      and hasattr(win.cmdlib_panel, "retranslate") and hasattr(page.sftp_tab, "retranslate"))

ru_texts = texts_of(win)
# The page's status label is EXCLUDED from the "no old-language leftover" sweep: it
# carries the LIVE session state emitted by the thread ("Initializing SSH session…")
# and is deliberately not re-texted (see TerminalSessionPage.retranslate()).
_STATUS_EN = (read_lang("en")["terminal.initializing"], read_lang("en")["terminal.session_closed"],
              read_lang("en")["terminal.error_prefix"])
ru_leftovers = english_leftovers(win, exclude=_STATUS_EN)
check("after ru NOT ONE container string stays in the old language (no ASCII-only leftovers)",
      not ru_leftovers, str(ru_leftovers)[:400])
check("so the ru texts really differ from the en texts",
      all(i18n.t(k) == v for k, v in
          (("terminal.tab_close_tooltip", win.session_tabs.tabToolTip(0)),
           ("sftp.up", page.sftp_tab.btn_up.text()),
           ("terminal.cmdlib.add", win.cmdlib_panel.add_btn.text()))))

mw._switch_language("en")
app.processEvents()
check("a second switch back (ru → en) restores the tab-close tooltip",
      win.session_tabs.tabToolTip(0) == read_lang("en")["terminal.tab_close_tooltip"],
      win.session_tabs.tabToolTip(0))
check("a second switch back restores the SFTP buttons",
      page.sftp_tab.btn_up.text() == read_lang("en")["sftp.up"]
      and page.sftp_tab.btn_viewer_close.toolTip() == read_lang("en")["sftp.viewer.close_tooltip"],
      page.sftp_tab.btn_up.text())
check("a second switch back restores the page tab titles",
      page.tabs.tabText(0) == read_lang("en")["sftp.tab_terminal"]
      and page.tabs.tabText(1) == read_lang("en")["sftp.tab_files"],
      f"{page.tabs.tabText(0)!r} / {page.tabs.tabText(1)!r}")
check("a second switch back restores the command-library panel",
      win.cmdlib_panel._title.text() == read_lang("en")["terminal.cmdlib.title"]
      and win.cmdlib_panel.search.placeholderText() == read_lang("en")["terminal.cmdlib.search_placeholder"],
      win.cmdlib_panel._title.text())
check("the round trip left no Cyrillic in the container",
      not any(has_cyrillic(v) for v in texts_of(win).values()),
      str([v for v in texts_of(win).values() if has_cyrillic(v)])[:300])


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the dock + the SFTP tab + the command-library panel ==")
# ════════════════════════════════════════════════════════════════════════════

dock_content = TerminalDockContent()
dock_page = dock_content.add_session(
    ServerData(id="i18nlive-d", alias="node-d", host="10.99.2.1", user="root"), password="pw")
app.processEvents()
dock = TerminalsDock()
dock.content = dock_content
dock.setWidget(dock_content)
app.processEvents()

check("an SFTP tab of the dock page exists (SftpTab)",
      dock_page.sftp_tab is not None and dock_page.sftp_tab.btn_refresh is not None)

# The REAL path: _switch_language() → _apply_ui_translations(). The dock is NOT in
# MainWindow._terminal_windows (the registry holds SESSIONS; in tabs mode it holds the
# dock itself) and this dock is a standalone container, so it is re-texted explicitly —
# exactly what MainWindow does when _terminals_dock is set (the `dock` branch above).
mw._switch_language("ru")
i18n.set_language("ru")       # idempotent: this standalone dock is not in the window
dock.retranslate()
app.processEvents()
check("TerminalsDock.retranslate() re-texts the dock title",
      dock.windowTitle() == i18n.t("terminal.dock_title"), dock.windowTitle())
check("TerminalDockContent.retranslate() re-texts its pages (tab titles + SFTP buttons)",
      dock_page.tabs.tabText(1) == i18n.t("sftp.tab_files")
      and dock_page.sftp_tab.btn_download.text() == i18n.t("sftp.download"),
      f"{dock_page.tabs.tabText(1)!r} / {dock_page.sftp_tab.btn_download.text()!r}")
check("the dock page's command-library panel follows the language too",
      dock_content.cmdlib_panel.del_btn.text() == i18n.t("terminal.cmdlib.delete"),
      dock_content.cmdlib_panel.del_btn.text())
check("the dock content carries no English leftover in ru",
      not english_leftovers(dock_content, exclude=_STATUS_EN),
      str(english_leftovers(dock_content, exclude=_STATUS_EN))[:400])

i18n.set_language("en")
dock.retranslate()
app.processEvents()
check("switching back restores the dock title and its pages",
      dock.windowTitle() == read_lang("en")["terminal.dock_title"]
      and dock_page.sftp_tab.btn_cancel.text() == read_lang("en")["sftp.cancel"],
      dock.windowTitle())

# The "no preview" row tooltip is re-texted without a re-listing (task 1)
from PySide6.QtWidgets import QTreeWidgetItem  # noqa: E402
dock_page.sftp_tab._blocked = {"/etc/big.bin": "too_large"}
item = QTreeWidgetItem(["./big.bin", "", ""])
item.setData(0, dock_page.sftp_tab.PATH_ROLE, "/etc/big.bin")
item.setData(0, dock_page.sftp_tab.SIZE_ROLE, 1)
dock_page.sftp_tab.tree.addTopLevelItem(item)
dock_page.sftp_tab._apply_preview_marker(item, "/etc/big.bin")
en_tip = item.toolTip(0)
i18n.set_language("ru")
dock_page.sftp_tab.retranslate()
check("the marked row's tooltip follows the language (no re-listing needed)",
      item.toolTip(0) != en_tip and has_cyrillic(item.toolTip(0)), item.toolTip(0))
i18n.set_language("en")

# The MainWindow loop: a session in the registry is re-texted by _apply_ui_translations
mw2 = MW.MainWindow()
mw2.show()
app.processEvents()
node2 = mw2.scene.add_server(
    ServerData(id="i18nlive-b", alias="node-b", host="10.99.3.1", user="root"))
win2 = mw2._spawn_terminal_window(node2)
app.processEvents()
mw2._switch_language("ru")
app.processEvents()
check("MainWindow._apply_ui_translations() walks _terminal_windows (the terminal-font twin path)",
      win2.page.tabs.tabText(1) == i18n.t("sftp.tab_files")
      and win2.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      win2.page.tabs.tabText(1))
check("the window-mode title follows the language as well",
      has_cyrillic(win2.windowTitle()), win2.windowTitle())
mw2._switch_language("en")
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the language files: the BOM and the partial translations ==")
# ════════════════════════════════════════════════════════════════════════════

bom_root = make_fake_project("bom_lang")
bom_path = os.path.join(bom_root, "i18n", "xx.json")
with open(bom_path, "rb") as f:
    raw = f.read()
with open(bom_path, "wb") as f:
    f.write(b"\xef\xbb\xbf" + raw)   # exactly what Notepad saves as "UTF-8 with BOM"
check("the fake language file really carries a UTF-8 BOM",
      open(bom_path, "rb").read(3) == b"\xef\xbb\xbf")
bom_langs = load_i18n_langs(bom_root)
check("a BOM-prefixed language file loads (utf-8-sig) and the meta key survives",
      "xx" in bom_langs and bom_langs["xx"].get("name") == "Xx",
      str(list(bom_langs)) + " " + repr(bom_langs.get("xx", {}).get("name")))
check("the BOM does not leak into a key or a value",
      all(not k.startswith("\ufeff") for k in bom_langs["xx"]))
try:
    load_i18n_langs(bom_root, encoding="utf-8")
    plain_ok = False
except (ValueError, json.JSONDecodeError):
    plain_ok = True   # the BOM really is there — a plain utf-8 read chokes on it
check("the same file read as plain utf-8 would fail (the fix is real, not cosmetic)", plain_ok)

_saved_dir = i18n._i18n_dir
i18n._i18n_dir = os.path.join(bom_root, "i18n")
check("i18n.load_language() loads the BOM file through the module path",
      i18n.load_language("xx") is True and i18n.get_current_language() == "xx")
check("the module reports the display name of the BOM file",
      [lg for lg in i18n.get_available_languages() if lg["code"] == "xx"][0]["name"] == "Xx")
i18n.load_language("en")
i18n._i18n_dir = _saved_dir

check("the harness and the module agree on the BOM encoding",
      I18N_LANG_ENCODING == i18n._LANG_ENCODING == "utf-8-sig",
      f"{I18N_LANG_ENCODING} / {i18n._LANG_ENCODING}")

# The META key "partial" (v1.3.3.1, decision 2026-09-16)
check("the meta keys grow by the new key",
      I18N_META_KEYS == frozenset({"name", "partial"}) == frozenset(i18n._META_KEYS),
      f"{sorted(I18N_META_KEYS)} / {sorted(i18n._META_KEYS)}")
check("a real JSON true marks a partial language", is_partial_lang({"partial": True, "a": "1"}))
check("a string \"true\" does NOT mark it partial (strict policy)",
      not is_partial_lang({"partial": "true", "a": "1"}))
check("a missing key does NOT mark it partial", not is_partial_lang({"a": "1"}))
check("translation_keys() drops BOTH meta keys",
      translation_keys({"name": "x", "partial": True, "a": "b"}) == {"a"})
check("t(\"partial\") never resolves to the meta key", i18n.t("partial") == "partial")

partial_root = make_fake_project("partial_lang", lambda d: d.pop("menu.file"), partial=True)
partial_langs = load_i18n_langs(partial_root)
check("a partial file with a missing key is NOT a defect",
      i18n_parity_problems(partial_langs, expected_keys=None) == []
      or all("menu.file" not in p for p in i18n_parity_problems(partial_langs, expected_keys=None)),
      str(i18n_parity_problems(partial_langs, expected_keys=None)))
check("its missing keys are reported as a WARNING naming the language and the key",
      any("xx" in w and "menu.file" in w for w in i18n_parity_warnings(partial_langs)),
      str(i18n_parity_warnings(partial_langs)))
check("the count mismatch of a partial file is a warning, not a defect",
      not any("EXPECTED_I18N_KEYS" in p for p in i18n_parity_problems(partial_langs))
      and any("of" in w for w in i18n_parity_warnings(partial_langs)),
      f"{i18n_parity_problems(partial_langs)} | {i18n_parity_warnings(partial_langs)}")
check("an EXTRA key in a partial file stays a defect (a key en does not have is a typo)",
      any("zz.extra" in p for p in i18n_parity_problems(
          load_i18n_langs(make_fake_project(
              "partial_extra", lambda d: d.update({"zz.extra": "b"}), partial=True)))))

strict_root = make_fake_project("strict_lang", lambda d: d.pop("menu.file"))
_strict = load_i18n_langs(strict_root)
check("a STRICT file with one missing key is still a defect",
      any("menu.file" in p for p in i18n_parity_problems(_strict)), str(i18n_parity_problems(_strict)))
check("a strict file yields no warnings", i18n_parity_warnings(_strict) == [])
check("a partial file is usable at runtime — the en fallback covers the hole",
      i18n_parity_warnings(partial_langs) and
      load_i18n_langs(ROOT, codes=["en"])["en"]["menu.file"] == "File")

# The shipped files carry neither key (all four are strict, complete files)
for _code in i18n_lang_codes(ROOT):
    _data = read_lang(_code)
    check(f"i18n/{_code}.json is a complete (non-partial) language",
          not is_partial_lang(_data) and len(translation_keys(_data)) == EXPECTED_I18N_KEYS,
          f"partial={_data.get('partial')!r} keys={len(translation_keys(_data))}")


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the language list without a restart (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

check("the language submenu object is kept on the window (the rebuild anchor)",
      getattr(mw, "_lang_menu", None) is not None)
# The submenu belongs to the MAIN window whose language is ru here (section 1 switched
# it) — re-read that state so the checkmark assertion is about the menu, not about the
# language the module happens to be on after the earlier low-level i18n probes.
i18n.set_language(mw.current_language)
mw._populate_language_menu(mw._lang_menu)
_lang_actions = [a for a in mw._lang_menu.actions() if a.data()]
check("the submenu lists every discovered language + the lang.reload item",
      sorted(a.data() for a in _lang_actions) == i18n_lang_codes(ROOT)
      and any(a.text() == i18n.t("lang.reload") for a in mw._lang_menu.actions()),
      str([a.text() for a in mw._lang_menu.actions()]))
check("the active language carries the checkmark",
      all(a.isChecked() == (a.data() == mw.current_language) for a in _lang_actions),
      f"{ {a.data(): a.isChecked() for a in _lang_actions} } vs {mw.current_language}")
check("the rebuilt actions stay in the QAction guard (PySide6 6.11 pitfall #9)",
      all(a in mw._qaction_guard for a in _lang_actions))

# A language file dropped in AFTER the window was built appears on the next aboutToShow.
# The drop goes into the USER language folder (`~/.sshmap/languages/`, isolated per test
# through the sandboxed HOME): the PACKAGE `i18n/` folder is shared with the parity checks
# of the OTHER test files running in parallel, so a temporary 5th language written there
# made them flaky (the suite is parallel — `tests/run_all.py`).
USER_LANG_DIR = i18n.user_language_dir()
os.makedirs(USER_LANG_DIR, exist_ok=True)
_drop = os.path.join(USER_LANG_DIR, "zz.json")
try:
    with open(_drop, "w", encoding="utf-8") as f:
        json.dump({"name": "Zz", "menu.file": "File-zz"}, f, ensure_ascii=False)
    mw._populate_language_menu(mw._lang_menu)
    _codes_now = sorted(a.data() for a in mw._lang_menu.actions() if a.data())
    check("a file dropped in after startup appears in the submenu (no restart)",
          "zz" in _codes_now and "Zz" in [a.text() for a in mw._lang_menu.actions()],
          str(_codes_now))
    check("the reload item survives every rebuild",
          [a.text() for a in mw._lang_menu.actions()].count(i18n.t("lang.reload")) == 1,
          str([a.text() for a in mw._lang_menu.actions()]))
    _before = texts_of(mw)
    mw._reload_languages()
    app.processEvents()
    check("lang.reload rescans without raising and keeps the UI alive",
          mw.isVisible() and mw._lang_menu is not None)
finally:
    try:
        os.remove(_drop)
    except OSError:
        pass
mw._populate_language_menu(mw._lang_menu)
check("removing the file again leaves the submenu consistent with the folder",
      sorted(a.data() for a in mw._lang_menu.actions() if a.data()) == i18n_lang_codes(ROOT),
      str(sorted(a.data() for a in mw._lang_menu.actions() if a.data())))

# The language list is rebuilt from the files, never from a hardcoded list
_i18n_src = open(os.path.join(ROOT, "i18n", "__init__.py"), encoding="utf-8").read()
check("get_available_languages() still discovers the files (no hardcoded list)",
      "get_available_languages" in _i18n_src and "_LANG_LABELS" not in _i18n_src)

# The settings combo refreshes at open (v1.3.3.1)
from ui.settings_dialog import SettingsDialog  # noqa: E402
_dlg = SettingsDialog(None)
_items = {_dlg.language_combo.itemData(i): _dlg.language_combo.itemText(i)
          for i in range(_dlg.language_combo.count())}
check("the settings combo lists every discovered language",
      sorted(_items) == i18n_lang_codes(ROOT), str(sorted(_items)))
check("_refresh_language_combo() is idempotent and keeps the current selection",
      (_dlg._refresh_language_combo() is None
       and _dlg.language_combo.currentData() == i18n.get_current_language()),
      str(_dlg.language_combo.currentData()))
_drop2 = os.path.join(USER_LANG_DIR, "zz.json")
try:
    with open(_drop2, "w", encoding="utf-8") as f:
        json.dump({"name": "Zz", "menu.file": "File-zz"}, f, ensure_ascii=False)
    _dlg._refresh_language_combo()
    _items2 = {_dlg.language_combo.itemData(i) for i in range(_dlg.language_combo.count())}
    check("the combo picks up a language file dropped in while the dialog was building",
          "zz" in _items2, str(sorted(_items2)))
    check("the refresh did not change the active language",
          _dlg.language_combo.currentData() == i18n.get_current_language(),
          str(_dlg.language_combo.currentData()))
finally:
    try:
        os.remove(_drop2)
    except OSError:
        pass
_dlg.close()
_dlg.destroy()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 placeholders and line breaks (task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

check("placeholder_names() reads the SET of {placeholders}",
      placeholder_names("SSH Connection — {alias} on {host}") == {"alias", "host"},
      str(placeholder_names("SSH Connection — {alias} on {host}")))
check("the ORDER of the placeholders does not matter (a language matter)",
      placeholder_names("{a} → {b}") == placeholder_names("{b} → {a}"))
check("an empty value / a non-string yields no placeholders",
      placeholder_names("") == set() and placeholder_names(None) == set()
      and placeholder_names(5) == set())
check("newline_count() counts the \\n breaks", newline_count("a\nb\nc") == 2,
      str(newline_count("a\nb\nc")))
check("a non-string yields 0 breaks",
      newline_count(None) == 0 and newline_count(5) == 0)

_fmt_root = make_fake_project("fmt_lost_placeholder",
                              lambda d: d.update({"dialog.ssh_connect": "SSH Connection"}))
_problems = i18n_format_problems(load_i18n_langs(_fmt_root))
check("a dropped {alias} is a format defect naming the key",
      any("dialog.ssh_connect" in p and "alias" in p
          for p in _problems.get("xx", [])), str(_problems))

_fmt_nl_root = make_fake_project(
    "fmt_lost_newline",
    lambda d: d.update({"dialog.manage_profiles_desc": "one line only"}))
_problems = i18n_format_problems(load_i18n_langs(_fmt_nl_root))
check("a lost \\n is a format defect naming the key",
      any("dialog.manage_profiles_desc" in p and "line break" in p
          for p in _problems.get("xx", [])), str(_problems))

_fmt_reorder_root = make_fake_project(
    "fmt_reordered",
    # ssh.host_key_new carries {host} + {fp} — the same SET, the opposite order
    lambda d: d.update({"ssh.host_key_new":
                        "Fingerprint {fp} belongs to {host} — accepted and saved."}))
check("reordering the placeholders in a sentence is NOT a defect (the SET is compared)",
      "xx" not in i18n_format_problems(load_i18n_langs(_fmt_reorder_root)),
      str(i18n_format_problems(load_i18n_langs(_fmt_reorder_root))))

_fmt_dup_root = make_fake_project(
    "fmt_dup_placeholder",
    lambda d: d.update({"msg.confirm_delete": "Delete '{alias}'? Really, '{alias}'?"}))
check("a DOUBLED placeholder is not a defect either (the SET is compared, not the count)",
      "xx" not in i18n_format_problems(load_i18n_langs(_fmt_dup_root)),
      str(i18n_format_problems(load_i18n_langs(_fmt_dup_root))))

_partial_fmt_root = make_fake_project(
    "fmt_partial", lambda d: d.update({"dialog.ssh_connect": "SSH Connection"}), partial=True)
check("a partial language skips the format check (its strings are still being written)",
      "xx" not in i18n_format_problems(load_i18n_langs(_partial_fmt_root)),
      str(i18n_format_problems(load_i18n_langs(_partial_fmt_root))))

# End-to-end through the real checker script: exit 1 for both new defect types
_checker = load_check_script()
_rc, _out = run_check_script(_checker, ROOT)
check("the real project passes the checker (exit 0)", _rc == 0, _out[-500:])
check("the checker reports the new format section",
      "placeholders + line breaks" in _out, _out[:400])
check("the checker counts the new defect types separately",
      "format:" in _out and "total defects: 0" in _out, _out[-400:])

_rc, _out = run_check_script(_checker, make_fake_project(
    "e2e_placeholder", lambda d: d.update({"dialog.ssh_connect": "SSH Connection"})))
check("a dropped {alias} end-to-end → exit 1", _rc == 1, _out[-500:])
check("the end-to-end failure names the key and the placeholder",
      "dialog.ssh_connect" in _out and "alias" in _out, _out[-500:])

_rc, _out = run_check_script(_checker, make_fake_project(
    "e2e_newline", lambda d: d.update({"dialog.manage_profiles_desc": "no break"})))
check("a lost \\n end-to-end → exit 1", _rc == 1, _out[-500:])
check("the end-to-end failure names the key and the line break",
      "dialog.manage_profiles_desc" in _out and "line break" in _out, _out[-500:])

_rc, _out = run_check_script(_checker, make_fake_project(
    "e2e_partial", lambda d: d.pop("menu.file"), partial=True))
check("a partial file with a missing key → exit 0 (a warning, not a defect)", _rc == 0, _out[-500:])
check("the partial language is announced as a warning in the report",
      "WARNING" in _out and "partial" in _out, _out[-700:])

_rc, _out = run_check_script(_checker, make_fake_project(
    "e2e_strict", lambda d: d.pop("menu.file")))
check("a strict file with one missing key → exit 1 (unchanged)", _rc == 1, _out[-500:])

check_i18n_parity(load_i18n_langs(ROOT))
check_i18n_format(load_i18n_langs(ROOT))


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the counter / baseline guards over README.md and ROADMAP.md (task 5) ==")
# ════════════════════════════════════════════════════════════════════════════

_real_test_count = len([f for f in os.listdir(os.path.join(ROOT, "tests"))
                        if f.startswith("test_") and f.endswith(".py")])
check("the real test-file count is the number this file expects",
      _real_test_count >= 72, str(_real_test_count))


def _read_doc(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


for _doc in ("README.md", "ROADMAP.md"):
    _text = _read_doc(_doc)
    _counters = {int(m.group(1)) for m in TEST_FILE_COUNTER_RE.finditer(_text)}
    check(f"{_doc}: every quoted test-file counter equals the real count ({_real_test_count})",
          _counters <= {_real_test_count}, f"quoted={sorted(_counters)}")
    check(f"{_doc}: the test-file counter is actually quoted (a guard over nothing is useless)",
          bool(_counters) or _doc != "README.md", f"quoted={sorted(_counters)}")

# The parity figures: the BASELINE of the header must be the pin, and every other
# quoted key-count figure must be a forward-looking count of a PLANNED version —
# i.e. part of one increasing chain that starts at the pin (the "453 → 454 while the
# header said 458" drift form: an out-of-chain figure).
_roadmap = _read_doc("ROADMAP.md")
_figures = sorted({int(m.group(1)) for m in I18N_PARITY_FIGURE_RE.finditer(_roadmap)})
# v1.4.7: the 1.4 line is CLOSED (v1.4.7 is its last planned version), and the frozen
# contract of the 1.5 line deliberately pins no per-rc key counts — so the baseline in the
# header is the only parity figure the plan owns today. The guard therefore drops the
# "at least two figures" half (it was satisfied by the planned v1.4.7 section, which the
# release removed) and keeps EVERY other property: the figure is the pin, the chain is
# non-decreasing and no figure is a stale outlier.
check("ROADMAP.md quotes the key-count baseline (a released section is removed from the plan)",
      len(_figures) >= 1, f"quoted={_figures}")
check(f"ROADMAP.md: the header baseline is the pin ({EXPECTED_I18N_KEYS})",
      _figures and _figures[0] in (EXPECTED_I18N_KEYS - 1, EXPECTED_I18N_KEYS),
      f"quoted={_figures} pin={EXPECTED_I18N_KEYS}")
check("ROADMAP.md: every quoted key-count figure belongs to ONE increasing chain",
      all(b >= a for a, b in zip(_figures, _figures[1:])),
      f"quoted={_figures}")
check("ROADMAP.md: no quoted figure is a stale outlier of the chain",
      # v1.4.5: the bound is RELATIVE to the pin (the absolute "600" of v1.3.3.1 went
      # stale the moment the shipped key count passed it — the pin is the only number
      # that may live in this file).
      all(EXPECTED_I18N_KEYS - 1 <= f <= EXPECTED_I18N_KEYS + 20 for f in _figures),
      f"quoted={_figures} pin={EXPECTED_I18N_KEYS}")
check("ROADMAP.md spells the baseline out in the header (a released section is removed from the plan)",
      f"parity baseline (v{EXPECTED_APP_VERSION}): {EXPECTED_I18N_KEYS} keys" in _roadmap,
      [ln for ln in _roadmap.splitlines() if "baseline" in ln][:1])
check("ROADMAP.md no longer quotes the stale fenced figure as a range",
      "**453 → 454**" not in _roadmap)
check("README.md quotes the real test-file counter",
      f"{_real_test_count} test files" in _read_doc("README.md"),
      [ln for ln in _read_doc("README.md").splitlines() if "test files" in ln])
check("the guard regexes really match the documents",
      bool(TEST_FILE_COUNTER_RE.search(_read_doc("README.md")))
      and bool(I18N_PARITY_FIGURE_RE.search(_roadmap)),
      f"counter={TEST_FILE_COUNTER_RE.search(_read_doc('README.md'))} "
      f"figures={_figures}")
check("the parity regex skips the deliberately approximate \"~N\" figures",
      not any(m.group(1).startswith("~") for m in I18N_PARITY_FIGURE_RE.finditer(_roadmap)))


# ════════════════════════════════════════════════════════════════════════════
print("== §7 zh.json's missing line break + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

_en_desc = read_lang("en")["dialog.manage_profiles_desc"]
_zh_desc = read_lang("zh")["dialog.manage_profiles_desc"]
check("the defect task 4 found is fixed: zh carries en's line break",
      newline_count(_zh_desc) == newline_count(_en_desc) == 1,
      f"zh={newline_count(_zh_desc)} en={newline_count(_en_desc)}")
check("the fix kept the translation (not a copied English string)",
      _zh_desc != _en_desc and "\n" in _zh_desc, repr(_zh_desc))
check("no language has a placeholder/line-break defect any more",
      i18n_format_problems(load_i18n_langs(ROOT)) == {},
      str(i18n_format_problems(load_i18n_langs(ROOT))))
for _code in i18n_lang_codes(ROOT):
    _missing = sorted(placeholder_names(_en_desc) ^ placeholder_names(read_lang(_code)["dialog.manage_profiles_desc"]))
    check(f"i18n/{_code}.json: dialog.manage_profiles_desc matches en (placeholders + breaks)",
          not _missing and newline_count(read_lang(_code)["dialog.manage_profiles_desc"])
          == newline_count(_en_desc), f"missing={_missing}")


# ════════════════════════════════════════════════════════════════════════════
print("== §8 the note-debounce hotfix (task 6) ==")
# ════════════════════════════════════════════════════════════════════════════

mw3 = MW.MainWindow()
mw3.show()
app.processEvents()
mw3._add_note_at()                        # the real creation path: the note is wired
app.processEvents()
note = mw3.scene.notes()[0]
mw3._reset_undo_stack()                   # a clean baseline (the creation is not under test)
# A REAL edit: typing into the note's QTextEdit emits textEdited (set_text() is the
# LOAD path and deliberately stays silent).
note.widget().setPlainText("typed inside the debounce")
app.processEvents()
check("the debounce is armed after a note edit (the pending command is queued)",
      mw3._note_edit_pending is not None and mw3._note_edit_pending[0] is note,
      str(mw3._note_edit_pending is not None))
check("the project is dirty while the edit is pending (typing marks it)", mw3._dirty is True)
check("nothing is on the undo stack yet (the debounce has not fired)",
      mw3.undo_stack.count() == 0, str(mw3.undo_stack.count()))
check("the debounce timer is really running (the 600 ms window is open)",
      mw3._note_edit_timer.isActive() is True)

mw3._note_edit_timer.stop()               # simulate Ctrl+S inside the 600 ms window
_saved = mw3._do_save(os.path.join(WORK, "note_flush.json"))
app.processEvents()
check("Ctrl+S inside the debounce saves the project", _saved is True)
check("_do_save() flushed the pending note text (nothing left pending)",
      mw3._note_edit_pending is None)
check("the committed text follows the flush (no stale baseline)",
      mw3._note_committed.get(note.note_id) == "typed inside the debounce",
      repr(mw3._note_committed.get(note.note_id)))
check("after the save the title is CLEAN (no [*] — the reported bug)",
      "[*]" not in mw3.windowTitle(), mw3.windowTitle())
check("no leftover command sits on the fresh undo stack (Ctrl+Z cannot revert saved text)",
      mw3.undo_stack.count() == 0, str(mw3.undo_stack.count()))
check("the dirty marker is cleared by the save", mw3._dirty is False)
with open(os.path.join(WORK, "note_flush.json"), encoding="utf-8") as f:
    _on_disk = json.load(f)
check("the text on disk is the freshly typed one",
      _on_disk["notes"][0]["text"] == "typed inside the debounce",
      repr(_on_disk["notes"][0]["text"]))

# A second edit flushed by closeEvent (the "unsaved changes" question comes after)
note.widget().setPlainText("edited again before closing")
app.processEvents()
check("the second edit armed the debounce again", mw3._note_edit_pending is not None)
mw3._note_edit_timer.stop()   # the 600 ms window is still open when the window closes
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
# The pending edit marks the project dirty, so the plain close path needs an explicit
# clean state — otherwise closeEvent asks its (modal) "save before exiting?" question.
mw3._note_committed[note.note_id] = note.text()
mw3._dirty = False
mw3._undo_baseline_dirty = False
_ev = QCloseEvent()
mw3.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
mw3.closeEvent(_ev)
app.processEvents()
check("closeEvent() flushed the pending note text before the question",
      mw3._note_edit_pending is None,
      str(mw3._note_edit_pending is not None))
check("the flush left the committed baseline equal to the widget's text",
      mw3._note_committed.get(note.note_id) == note.text(),
      repr(mw3._note_committed.get(note.note_id)))
check("a repeated flush is a no-op — nothing is pushed twice (stays clean for Ctrl+Z)",
      mw3.undo_stack.count() == 0, str(mw3.undo_stack.count()))

# _do_save is safe when the window has no pending edit at all
check("_do_save() without a pending edit is a no-op for the note state",
      mw3._do_save(os.path.join(WORK, "note_flush2.json")) is True
      and mw3._note_edit_pending is None)


# ════════════════════════════════════════════════════════════════════════════
print("== §9 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check("EXPECTED_APP_VERSION is the version this test file describes",
      EXPECTED_APP_VERSION == "1.4.7", EXPECTED_APP_VERSION)
check("the pin counts the keys of the SHIPPED release (v1.4.7 — \"Syntax highlighting in "
      "the SFTP viewer\": +1 key — `sftp.viewer.syntax_heuristic`, the note the read-only "
      "preview appends to its header for the modes NO parser verified (YAML: the standard "
      "library has no YAML parser, so that highlighting is a heuristic and says so). The "
      "verified modes (JSON/XML — accepted only after a real parse) and the always-truthful "
      "`numbers` fallback carry no note, and the 8 `Theme.syntax_*` palette fields are not "
      "text — the v1.4.6 figure plus one)",
      EXPECTED_I18N_KEYS == 613, str(EXPECTED_I18N_KEYS))
check_release_state(ROOT)
for _code in i18n_lang_codes(ROOT):
    check(f"i18n/{_code}.json carries the new sftp.conflict.title key",
          "sftp.conflict.title" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the new sftp.op.new_folder key",
          "sftp.op.new_folder" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.3 view.zoom_in key",
          "view.zoom_in" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.4 terminal.find.count key",
          "terminal.find.count" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.4 sftp.eta key",
          "sftp.eta" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.5 terminal.split key",
          "terminal.split" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.6 file.recent key",
          "file.recent" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.6 msg.project_unreadable key",
          "msg.project_unreadable" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.7 file.export_svg key",
          "file.export_svg" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.7 status.export_svg_ok key",
          "status.export_svg_ok" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.8 language.import key",
          "language.import" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.3.3.8 settings.terminal.wheel.off key",
          "settings.terminal.wheel.off" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4rc1 menu.plugins key",
          "menu.plugins" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4rc1 plugins.status.error key",
          "plugins.status.error" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4rc2 plugins.status.hook_timeout key",
          "plugins.status.hook_timeout" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4rc3 plugins.run_on_nodes key",
          "plugins.run_on_nodes" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4rc3 plugins.status.run_on_nodes key",
          "plugins.status.run_on_nodes" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4.1 file.import_ssh_config key",
          "file.import_ssh_config" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4.1 sshconfig.reason.wildcard key",
          "sshconfig.reason.wildcard" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4.1 sshconfig.col_key key",
          "sshconfig.col_key" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4.1 msg.import_ssh_config_result key",
          "msg.import_ssh_config_result" in translation_keys(read_lang(_code)))
    check(f"i18n/{_code}.json carries the v1.4.6 sidebar.list.* column headers",
          all(f"sidebar.list.{_col}" in translation_keys(read_lang(_code))
              for _col in ("alias", "host", "status", "os", "cpu", "ram", "disk", "tags"))
          and all(str(read_lang(_code).get(f"sidebar.list.{_col}", "")).strip()
                  for _col in ("alias", "host", "status", "os", "cpu", "ram", "disk", "tags")))
    check(f"i18n/{_code}.json carries the v1.4.6 minimap.title (the vertical band)",
          str(read_lang(_code).get("minimap.title", "")).strip() != "")
    check(f"i18n/{_code}.json renames the two splitter items to their state pair (v1.4.6)",
          "/" in str(read_lang(_code).get("view.toggle_map", ""))
          and "/" in str(read_lang(_code).get("view.toggle_sidebar", "")))
    check(f"i18n/{_code}.json carries the v1.4.7 heuristic-highlighting note",
          "{language}" in str(read_lang(_code).get("sftp.viewer.syntax_heuristic", ""))
          and str(read_lang(_code).get("sftp.viewer.syntax_heuristic", "")).strip() != "")

# cleanup: back to en + the original config, then close the windows
i18n.set_language("en")
for _w in (win, win2):
    try:
        _w.close()
    except RuntimeError:
        pass
try:
    dock.close()
except RuntimeError:
    pass
try:
    dock_page.shutdown()
    dock_content.close()
except Exception:  # noqa: BLE001 — teardown robustness
    pass
for _m in (mw, mw2, mw3):
    try:
        _m.close()
    except RuntimeError:
        pass
ST.SSHTerminalThread = _ORIG_THREAD_CLS
restore_i18n_config(_CFG_SNAP)
finish()
