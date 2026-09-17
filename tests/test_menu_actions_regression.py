# -*- coding: utf-8 -*-
"""v1.2.4-fix — REGRESSION: the real click path on checkable menu items (QAction.trigger()).

The incident: the manual testing did not confirm the multi-input — "I put the check in
View → Multi-input, and nothing happens: no frame, no badges, no plaque". The root
(the empirics on PySide6 6.11.1, offscreen): the auto-connection of QMenu.addAction(text, slot)
— what MainWindow._add_menu_action does — emits QAction.triggered into the Python slot
WITHOUT arguments (an explicit action.triggered.connect(slot) passes the new state, and
the auto-connection — not). _toggle_multi_input(checked=None) fell into the no-op branch
(target = the current state) — the mode from the menu was not enabled nor disabled at all;
only the checkmark moved (Qt itself flips it), F12 was silent (the shortcut is attached
only in the active mode).

The fix: the item is connected to toggled(bool) (the new state — the same as with the explicit
triggered.connect); the checked=None in _toggle_multi_input — now a real toggle.

This test goes EXACTLY the path of a user click: act.trigger() — Qt itself
inverts the checked and emits the signals (that is how both the menu item and the F12 shortcut on
the same QAction work). SSH is not needed: the hub/provider/the plaque live without the terminals; for
the check of the frame/badge one duck-typed fake container is put into the registry.

Run:  python tests/test_menu_actions_regression.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import ui.main_window as MW  # noqa: E402
from modules.multi_input import get_hub, MULTI_FRAME_OBJECT_NAME  # noqa: E402


class _FakePageData:
    alias = "fake-a"


class _FakePage:
    """The registry record (duck-typing TerminalSessionPage): only what
    _on_multi_changed/_multi_refresh_ui (_host_window) use. terminal_thread=None —
    the broadcast is not checked here (covered by test_multi_input_e2e.py)."""

    def __init__(self, host):
        self._host_window = host
        self.widget = None
        self.terminal_thread = None


class _FakeHost(QWidget):
    """Duck-typing of SSHTerminalWindow/TerminalDockContent for apply_container_highlight:
    session_tabs (QTabWidget) + the pages with .server_data.alias + _multi_base_title."""

    def __init__(self):
        super().__init__()
        self.session_tabs = QTabWidget()
        page = QWidget()
        page.server_data = _FakePageData()
        self.session_tabs.addTab(page, "fake-a")
        self._multi_base_title = "fake host"


hub = get_hub()   # the process singleton (the same one as in MainWindow and the widgets)
hub.reset()

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("precondition: the mode is off, the plaque is hidden, the item is unchecked",
      hub.active is False and mw._multi_plaque.isHidden()
      and not mw.act_multi_input.isChecked())

# One fake session in the registry — for the counter/badge/frame
host = _FakeHost()
mw._terminal_windows.append(_FakePage(host))
app.processEvents()

# ════════════════════════════════════════════════════════════
# 1. THE THING THAT BROKE: the "View → Multi Input" click (act.trigger() = a user click)
# ════════════════════════════════════════════════════════════
print("== 1. the click on the menu item (the real Qt-event path) ==")
mw.act_multi_input.trigger()
app.processEvents()

check("the click: the hub is ACTIVE (before the fix — a no-op, the mode was not enabled)",
      hub.active is True, f"active={hub.active}")
check("the click: the checkmark on the item", mw.act_multi_input.isChecked())
check("the click: the plaque 'MULTI: 1 sessions' is visible with the counter",
      not mw._multi_plaque.isHidden()
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=1),
      repr(mw._multi_label.text()))
check("the click: the container's frame (the objectName) + the tab's badge 'MULTI · fake-a'",
      host.session_tabs.objectName() == MULTI_FRAME_OBJECT_NAME
      and host.session_tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="fake-a"),
      f"objectName={host.session_tabs.objectName()!r} tab={host.session_tabs.tabText(0)!r}")
check("the click: the prefix of the session window's title",
      host.windowTitle() == i18n.t("terminal.multi_title_prefix") + "fake host",
      repr(host.windowTitle()))
check("the click: the status message (status.multi_enabled)",
      mw.statusBar().currentMessage() == i18n.t("status.multi_enabled"),
      repr(mw.statusBar().currentMessage()))
check("the click: the F12 shortcut is ATTACHED (the exit from the mode)",
      mw.act_multi_input.shortcut().toString() == "F12",
      repr(mw.act_multi_input.shortcut().toString()))

# ════════════════════════════════════════════════════════════
# 2. Exit: a second click = what F12 does (the shortcut on the same QAction)
# ════════════════════════════════════════════════════════════
print("== 2. the exit by a second click / F12 ==")
mw.act_multi_input.trigger()
app.processEvents()

check("the exit: the mode is off, the checkmark is removed",
      hub.active is False and not mw.act_multi_input.isChecked())
check("the exit: the plaque is hidden, the highlight is reset (the frame / the badge / the title)",
      mw._multi_plaque.isHidden()
      and host.session_tabs.objectName() == ""
      and host.session_tabs.tabText(0) == "fake-a"
      and host.windowTitle() == "fake host",
      f"objectName={host.session_tabs.objectName()!r} tab={host.session_tabs.tabText(0)!r} "
      f"title={host.windowTitle()!r}")
check("the exit: the F12 shortcut is removed (the key goes back to the shell)",
      mw.act_multi_input.shortcut().toString() == "")

# ════════════════════════════════════════════════════════════
# 3. The fallback path: an argumentless call — a real toggle (before the fix — a no-op)
# ════════════════════════════════════════════════════════════
print("== 3. _toggle_multi_input() without an argument ==")
mw._toggle_multi_input()
check("the argumentless call: the mode is ON (before the fix — a no-op)", hub.active is True)
mw._toggle_multi_input()
check("the repeated argumentless call: the mode is off", hub.active is False)

# ════════════════════════════════════════════════════════════
# 4. The ✕ exit button on the plaque (an explicit False) — with the mode active
# ════════════════════════════════════════════════════════════
print("== 4. the ✕ button on the plaque ==")
mw.act_multi_input.trigger()   # enabling via the menu path
app.processEvents()
check("✕: the mode is active before the click on the button", hub.active is True)
mw._multi_exit_btn.click()
app.processEvents()
check("✕: the mode is off, the checkmark is removed, the plaque is hidden",
      hub.active is False and not mw.act_multi_input.isChecked()
      and mw._multi_plaque.isHidden())

# cleanup: we remove the fake from the registry (the real teardown does this on destroyed)
mw._terminal_windows.clear()
finish()
