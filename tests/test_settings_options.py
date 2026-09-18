# -*- coding: utf-8 -*-
"""v1.1.1 — Small options around the hub: the release's themed test (ROADMAP v1.1.1).

The items of ROADMAP v1.1.1 (each is independently shippable, here each is covered by its own block):
  #1 The fonts — ui_font_family/ui_font_size (the UI) + terminal_font (the terminal, the key
    was read since v1.0, the UI for the first time); the apply on the fly without a restart:
    QApplication.setFont + widget.set_font() into the open terminal windows;
  #2 English by default — i18n._default_language "ru" → "en": it affects only
    the new users (without config.json); for the existing ones get_last_language()
    returns the saved language;
  #3 The limit of one's own terminals = 4 — terminal_max_open (the default 4); on reaching it
    not a refusal, but the offer to close the OLDEST session / a cancel (_spawn_terminal_window);
  #4 The double click on a node — ui_node_double_click "properties"|"connect"
    ("connect" → _run_ssh_connect(node) opens the SSHConnectDialog immediately);
  #5 The hiding of the button block of the sidebar — ui_show_sidebar_buttons (the default True) +
    SidebarPanel.set_buttons_visible(bool); the whole sidebar — the menu item "View → Sidebar";
  #6 The connection plaque — the type on the plaque (ui_show_connection_type: "SSH · <label>") +
    the 20-character limit of the label (setMaxLength(20) in ConnectionDialog/EditConnectionDialog,
    only on the input — the old projects with the long labels are read unchanged).

The storage — the SINGLE ~/.sshmap/config.json; all the keys are optional, the defaults = the behavior
of v1.1. i18n: +14 keys × en/ru/zh (the parity 359 → 373).

Run: python tests/test_settings_options.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication(sys.argv)

# IMPORTANT: i18n is imported BEFORE any write to config.json — a fresh HOME sandbox
# without ~/.sshmap/config.json = a "new user" (the item #2 check).
import i18n
from models.server import ServerData
from graphics.map_scene import MapScene
from graphics.connection_arrow import ConnectionArrow, label_display_text
from dialogs.connection_dialog import ConnectionDialog, EditConnectionDialog
from ui.settings_dialog import SettingsDialog, load_ui_settings
from modules.ssh_terminal import load_terminal_settings

CFG_PATH = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def read_cfg():
    if not os.path.isfile(CFG_PATH):
        return None
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_cfg(d):
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


def clear_cfg():
    try:
        os.remove(CFG_PATH)
    except OSError:
        pass


# ════════════════════════════════════════════════════════════
# 0. i18n: +14 keys × en/ru/zh (v1.1.1), parity 359 → 375 → 377 (+2 in v1.1.2 final)
# ════════════════════════════════════════════════════════════
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = [
    "settings.general.ui_font_family", "settings.general.ui_font_size",
    "settings.ui_font_system", "settings.terminal.font_family",
    "settings.terminal.max_open", "msg.terminal_limit_title",
    "msg.terminal_limit_close_oldest", "settings.map.node_double_click",
    "settings.map.node_double_click.properties", "settings.map.node_double_click.connect",
    "settings.general.sidebar_buttons", "view.toggle_sidebar",
    "settings.map.show_connection_type", "connection.label_hint",
]
missing = [k for k in new_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 14 new v1.1.1 keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

# ════════════════════════════════════════════════════════════
# 1. Item #2: English by default (only for new users)
# ════════════════════════════════════════════════════════════
print("== default language ==")
check("a new user (no config.json): the default language is en",
      i18n.get_current_language() == "en", i18n.get_current_language())
check("i18n._default_language == 'en' (was 'ru')", i18n._default_language == "en")
write_cfg({"language": "ru"})
check("an existing user: the saved language ru is read (get_last_language)",
      i18n.get_last_language() == "ru", i18n.get_last_language())
clear_cfg()

# ════════════════════════════════════════════════════════════
# 2. Item #1: fonts — load_ui_settings() (the validator) + live application
# ════════════════════════════════════════════════════════════
print("== fonts ==")
clear_cfg()
s = load_ui_settings()
check("load_ui_settings: the defaults (no config)",
      s == {"font_family": "", "font_size": None, "node_double_click": "properties",
            "show_sidebar_buttons": True, "show_connection_type": False}, str(s))

write_cfg({"ui_font_family": " Courier New ", "ui_font_size": 14,
           "ui_node_double_click": " connect ", "ui_show_sidebar_buttons": False,
           "ui_show_connection_type": True})
s = load_ui_settings()
check("load_ui_settings: the valid values are read (the trimming of the spaces)",
      s == {"font_family": "Courier New", "font_size": 14, "node_double_click": "connect",
            "show_sidebar_buttons": False, "show_connection_type": True}, str(s))

write_cfg({"ui_font_family": 42, "ui_font_size": "big", "ui_node_double_click": "yell",
           "ui_show_sidebar_buttons": "yes", "ui_show_connection_type": 1})
s = load_ui_settings()
check("load_ui_settings: the broken values (the foreign types) → the defaults",
      s == {"font_family": "", "font_size": None, "node_double_click": "properties",
            "show_sidebar_buttons": True, "show_connection_type": False}, str(s))

write_cfg({"ui_font_size": 0})
check("load_ui_settings: the ui_font_size=0 → the system size (None)",
      load_ui_settings()["font_size"] is None)
write_cfg({"ui_font_size": 99})
check("load_ui_settings: the ui_font_size out of the range (99) → None",
      load_ui_settings()["font_size"] is None)
clear_cfg()

# The settings dialog: the new fields + a prefill + collect()
write_cfg({"ui_font_family": "Consolas", "ui_font_size": 12, "terminal_font": "JetBrains Mono",
           "terminal_max_open": 6, "ui_node_double_click": "connect",
           "ui_show_sidebar_buttons": False, "ui_show_connection_type": True})
dlg = SettingsDialog(None)
check("'General': the UI font family field + the size spin (0 = the system one)",
      dlg.ui_font_family_edit.text() == "Consolas" and dlg.ui_font_size_spin.value() == 12
      and dlg.ui_font_size_spin.minimum() == 0)
check("'Terminal': the terminal font family field + the limit spin (1..32 — the v1.3.3.8 range unification)",
      dlg.term_font_family_edit.text() == "JetBrains Mono"
      and dlg.max_open_spin.value() == 6
      and dlg.max_open_spin.minimum() == 1 and dlg.max_open_spin.maximum() == 32)
check("'Map': the double-click combo (properties/connect) + the 'the type on the plaque' checkbox",
      [dlg.node_dblclick_combo.itemData(i) for i in range(dlg.node_dblclick_combo.count())]
      == ["properties", "connect"]
      and dlg.node_dblclick_combo.currentData() == "connect"
      and dlg.show_conn_type_chk.isChecked() is True)
check("'General': the sidebar buttons checkbox (the prefill is False from the config)",
      dlg.sidebar_buttons_chk.isChecked() is False)
c = dlg.collect()
check("collect(): the new v1.1.1 keys with the values",
      c.get("ui_font_family") == "Consolas" and c.get("ui_font_size") == 12
      and c.get("terminal_font") == "JetBrains Mono" and c.get("terminal_max_open") == 6
      and c.get("ui_node_double_click") == "connect"
      and c.get("ui_show_sidebar_buttons") is False
      and c.get("ui_show_connection_type") is True, str(c))

# Live application: MainWindow + QApplication.setFont + the font of open terminal windows
import ui.main_window as MW

clear_cfg()
win = MW.MainWindow()
win.show()
app.processEvents()

write_cfg({"ui_font_family": "Consolas", "ui_font_size": 14,
           "terminal_font": "DejaVu Sans Mono", "terminal_font_size": 13})


class _FakeTermWidget:
    def __init__(self):
        self.font_calls = []

    def set_font(self, family="", size=10):
        self.font_calls.append((family, size))


class _FakeTermWindow(QObject):
    """The fake terminal window (without the SSH): only what MainWindow touches."""
    destroyed = QtSignal()

    def __init__(self, server_data, parent=None, password=None, initial_command=""):
        super().__init__()
        self.server_data = server_data
        self.widget = _FakeTermWidget()
        self.closed = False
        self._force_close = False

    def show(self):
        pass

    def close_terminal(self):
        self.closed = True


win._terminal_windows.append(
    _FakeTermWindow(ServerData(id="fw1", alias="font-win", host="10.99.0.1", user="root")))
win._apply_settings_from_dialog()
app_font = app.font()
check("live: the UI font is applied to the QApplication (Consolas 14) without a restart",
      app_font.family() == "Consolas" and app_font.pointSize() == 14,
      f"{app_font.family()} {app_font.pointSize()}")
fw = win._terminal_windows[0]
check("live: the terminal font is applied into the open window (DejaVu Sans Mono 13)",
      fw.widget.font_calls == [("DejaVu Sans Mono", 13)], str(fw.widget.font_calls))

# Without the font keys — the app does not touch the current font
clear_cfg()
app.setFont(app.font())  # we remember the "current" (Consolas 14) as the base
base_family, base_size = app_font.family(), app_font.pointSize()
win._apply_settings_from_dialog()
check("live: without the font keys in the config — the font is unchanged",
      app.font().family() == base_family and app.font().pointSize() == base_size)
win._terminal_windows.clear()

# ════════════════════════════════════════════════════════════
# 3. Item #3: the limit of own terminals (terminal_max_open, default 4)
# ════════════════════════════════════════════════════════════
print("== terminal limit ==")
clear_cfg()
check("load_terminal_settings: the max_open default 4", load_terminal_settings()["max_open"] == 4)

win2 = MW.MainWindow()
win2.show()
app.processEvents()


def _mk(alias, host="10.98.0.1"):
    return _FakeTermWindow(ServerData(id=f"lim-{alias}", alias=alias, host=host, user="root"))


asked = []
_limit_result = [QMessageBox.Close]
_orig_question = MW.QMessageBox.question
_orig_win_cls = MW.SSHTerminalWindow  # BEFORE try: finally restores even on a body crash


def _fake_question(parent, title, text, buttons=0, default=0):
    asked.append((title, text))
    return _limit_result[0]


MW.QMessageBox.question = staticmethod(_fake_question)
try:
    # Below the limit (3 < 4) — no dialog, the window is created directly
    win2._terminal_windows.extend([_mk("a"), _mk("b"), _mk("c")])

    class _SpawnedRecorder(_FakeTermWindow):
        created = []

        def __init__(self, server_data, parent=None, password=None, initial_command=""):
            super().__init__(server_data, parent, password, initial_command)
            _SpawnedRecorder.created.append(self)

    MW.SSHTerminalWindow = _SpawnedRecorder
    node3 = win2.scene.add_server(
        ServerData(id="lim-d", alias="d", host="10.98.0.4", user="root"))
    asked.clear()
    w_new = win2._spawn_terminal_window(node3)
    check("below the limit (3<4): the dialog is not shown, the window is created",
          len(asked) == 0 and w_new is not None and len(win2._terminal_windows) == 4)

    # At the limit (4 >= 4): a proposal to close the oldest → Close → the oldest is closed
    asked.clear()
    _limit_result[0] = QMessageBox.Close
    node4 = win2.scene.add_server(
        ServerData(id="lim-e", alias="e", host="10.98.0.5", user="root"))
    oldest_before = win2._terminal_windows[0]
    w_new2 = win2._spawn_terminal_window(node4)
    check("at the limit (4>=4): the dialog about the oldest session is shown",
          len(asked) == 1 and asked[0][0] == i18n.t("msg.terminal_limit_title"),
          str(asked))
    check("the dialog's text: the limit + the alias of the oldest («a»)",
          "4" in asked[0][1] and "«a»" in asked[0][1], asked[0][1])
    check("Close: the oldest is closed (close_terminal + _force_close against the repeated 'ask')",
          oldest_before.closed is True and oldest_before._force_close is True)
    check("Close: the oldest is removed from the registry, the new window is created (again 4)",
          w_new2 is not None and win2._terminal_windows[0] is not oldest_before
          and len(win2._terminal_windows) == 4
          and win2._terminal_windows[-1] is w_new2)

    # At the limit: Cancel → the window is not created, the registry is untouched
    asked.clear()
    _limit_result[0] = QMessageBox.Cancel
    node5 = win2.scene.add_server(
        ServerData(id="lim-f", alias="f", host="10.98.0.6", user="root"))
    list_before = list(win2._terminal_windows)
    w_cancel = win2._spawn_terminal_window(node5)
    check("Cancel: the new window is NOT created (None), the registry is unchanged, the dialog was shown",
          w_cancel is None and len(asked) == 1
          and list(win2._terminal_windows) == list_before)

    # The limit from the config (terminal_max_open=2): it fires earlier
    write_cfg({"terminal_max_open": 2})
    asked.clear()
    _limit_result[0] = QMessageBox.Close
    node6 = win2.scene.add_server(
        ServerData(id="lim-g", alias="g", host="10.98.0.7", user="root"))
    w_new3 = win2._spawn_terminal_window(node6)
    check("the terminal_max_open=2: the limit is read from the config (the dialog at 4 open ones)",
          len(asked) == 1 and "2" in asked[0][1] and w_new3 is not None, str(asked))
finally:
    MW.QMessageBox.question = _orig_question
    MW.SSHTerminalWindow = _orig_win_cls
    clear_cfg()

# ════════════════════════════════════════════════════════════
# 4. Item #4: a double click on a node (ui_node_double_click)
# ════════════════════════════════════════════════════════════
print("== node double-click mode ==")
clear_cfg()
win3 = MW.MainWindow()
win3.show()
app.processEvents()
node_dc = win3.scene.add_server(
    ServerData(id="dc1", alias="dblclick", host="10.97.0.1", user="root"))

check("the default (no config): the 'properties' mode (the v1.1 behavior)",
      win3._node_double_click_mode == "properties")

# connect: a double click → _run_ssh_connect(node)
write_cfg({"ui_node_double_click": "connect"})
win3._apply_ui_options_from_config()
check("the config 'connect': the mode's cache is updated", win3._node_double_click_mode == "connect")
dc_calls = []
win3._run_ssh_connect = lambda n, **kw: dc_calls.append(n.data.id)  # noqa: E731
win3._on_node_double_click_direct(node_dc)
check("'connect': the double click opened the _run_ssh_connect(node)",
      dc_calls == ["dc1"], str(dc_calls))

# properties (the default): the properties dialog, the SSH dialog is NOT opened
clear_cfg()
win3._apply_ui_options_from_config()


class _FakeAddServerDialog(QDialog):
    def __init__(self, parent=None, edit_data=None):
        super().__init__(parent)
        self.edit_data = edit_data

    def exec(self):  # noqa: A003 — simulating a user refusal
        return QDialog.Rejected


_orig_add_dlg = MW.AddServerDialog
MW.AddServerDialog = _FakeAddServerDialog
try:
    win3._on_node_double_click_direct(node_dc)
    check("'properties': the properties dialog, the _run_ssh_connect is not called",
          dc_calls == ["dc1"])  # the list did not grow
finally:
    MW.AddServerDialog = _orig_add_dlg
    del win3._run_ssh_connect

# A corrupt value → the default properties
write_cfg({"ui_node_double_click": "yell"})
win3._apply_ui_options_from_config()
check("the broken ui_node_double_click ('yell') → the default 'properties'",
      win3._node_double_click_mode == "properties")
clear_cfg()

# ════════════════════════════════════════════════════════════
# 5. Item #5: the sidebar button block + the "View → Sidebar" menu item
# ════════════════════════════════════════════════════════════
print("== sidebar buttons ==")
from ui.sidebar import SidebarPanel, _BUTTONS, CONTEXT_MENU_ITEMS

# v1.3.3.3: the action keys of the panel's own context menu (it refuses to build without
# a callback for every entry) — read from the module, never a frozen list.
panel = SidebarPanel(translate_fn=i18n.t, actions={
    e[0]: (lambda n, _k=e[0]: None) for e in CONTEXT_MENU_ITEMS if e is not None})
panel.show()
app.processEvents()
panel.set_buttons_visible(False)
app.processEvents()
check("set_buttons_visible(False): all the 6 buttons are hidden",
      all(not getattr(panel, attr).isVisible() for attr, *_ in _BUTTONS))
panel.set_buttons_visible(True)
app.processEvents()
check("set_buttons_visible(True): all the 6 buttons are visible again (the layout is rebuilt)",
      all(getattr(panel, attr).isVisible() for attr, *_ in _BUTTONS))

# MainWindow: the setting + the menu item
clear_cfg()
win4 = MW.MainWindow()
win4.show()
app.processEvents()
check("the 'View' menu: the checkable 'Sidebar' item (checked by default)",
      getattr(win4, "act_show_sidebar", None) is not None
      and win4.act_show_sidebar.isCheckable() and win4.act_show_sidebar.isChecked())

write_cfg({"ui_show_sidebar_buttons": False})
win4._apply_settings_from_dialog()
app.processEvents()
check("the config ui_show_sidebar_buttons=False: the button block is hidden",
      all(not getattr(win4, attr).isVisible() for attr, *_ in _BUTTONS))
check("the tree/the search of the sidebar are still visible (only the button block is hidden)",
      win4.tree.isVisible() and win4.search_edit.isVisible())

write_cfg({"ui_show_sidebar_buttons": True})
win4._apply_settings_from_dialog()
app.processEvents()
check("the config ui_show_sidebar_buttons=True: the buttons are back",
      all(getattr(win4, attr).isVisible() for attr, *_ in _BUTTONS))

# The menu item — a way to restore the WHOLE sidebar. PySide6 6.11: trigger() on a checkable-
# action = a click on the item (it inverts checked itself and emits triggered with the NEW
# state), so setChecked+trigger here would be a double inversion — a single trigger().
win4.act_show_sidebar.trigger()
app.processEvents()
check("the 'View → Sidebar' menu (uncheck): the whole sidebar is hidden", win4.sidebar.isHidden())
win4.act_show_sidebar.trigger()
app.processEvents()
check("the 'View → Sidebar' menu (check): the sidebar is back", not win4.sidebar.isHidden())
clear_cfg()

# ════════════════════════════════════════════════════════════
# 6. Item #6: the connection plaque — the type on the plaque + a 20-character label limit
# ════════════════════════════════════════════════════════════
print("== connection label ==")
clear_cfg()
check("label_display_text: the option is off → only the label",
      label_display_text("ssh", "web") == "web")
write_cfg({"ui_show_connection_type": True})
check("label_display_text: the option is on → 'SSH · web'",
      label_display_text("ssh", "web") == f"{i18n.t('connection.type.ssh')} · web")
check("label_display_text: without a label → the type itself ('VPN')",
      label_display_text("vpn", "") == i18n.t("connection.type.vpn"))

# E2E: the arrow on the scene + refresh_label() after switching the option (no re-creation).
# We clear the config: the arrow is created with the option OFF (only the label on the plaque) —
# otherwise it would inherit ui_show_connection_type=True from the functional checks above.
clear_cfg()
scene = MapScene()
na = scene.add_server(ServerData(id="ca", alias="A", host="10.96.0.1", user="root"))
nb = scene.add_server(ServerData(id="cb", alias="B", host="10.96.0.2", user="root"))
arrow = scene.add_connection("ca", "cb", label="web", ctype="ssh")
check("the arrow: the option is off → the label text 'web'",
      arrow._label.toPlainText() == "web", arrow._label.toPlainText())
write_cfg({"ui_show_connection_type": True})
arrow.refresh_label()
check("refresh_label(): after the option is enabled → 'SSH · web' (no re-creation)",
      arrow._label.toPlainText() == f"{i18n.t('connection.type.ssh')} · web",
      arrow._label.toPlainText())
clear_cfg()
arrow.refresh_label()
check("refresh_label(): after the option is disabled → 'web' again",
      arrow._label.toPlainText() == "web")

# Dialogs: the 20-character limit — only on input
nodes = [na, nb]
cdlg = ConnectionDialog(nodes, None)
check("the ConnectionDialog: label.maxLength() == 20 + the hint in the i18n",
      cdlg.label.maxLength() == 20
      and cdlg.label.placeholderText() == i18n.t("connection.label_hint"))

long_label = "x" * 30  # an old label from a foreign project, longer than the limit
arrow_long = scene.add_connection("cb", "ca", label=long_label, ctype="vpn")
edlg = EditConnectionDialog(arrow_long, None)
check("EditConnectionDialog: maxLength() == 20", edlg.label.maxLength() == 20)
check("the EditConnectionDialog: the old long label (30 characters) is NOT trimmed",
      edlg.label.text() == long_label and len(edlg.label.text()) == 30,
      f"len={len(edlg.label.text())}")

# ════════════════════════════════════════════════════════════
# 7. Release state (pins — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

clear_cfg()
finish()
