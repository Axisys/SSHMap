"""ui/sidebar.py: SidebarPanel — a MainWindow facade + retranslate (v0.9.9.4).

ROADMAP v0.9.9.4 — phase 1 of the "Hygiene of main_window.py" series: the sidebar cluster
(the buttons, the header, the search, the tag filter, the tree with the status markers, the context
menu) was moved from ui/main_window.py into ui/sidebar.py (SidebarPanel(QWidget)).
The public API of MainWindow stays the facade — the existing tests were not touched.

  * the facade: win.tree/win.tag_filter/win.search_edit/win.btn_* — the references to the
    panel's widgets; refresh_sidebar/_sync_selection_state/_on_tree_item_clicked etc. — the window's methods;
  * the hygiene: the tree/markers/rows are built by the panel, their code is not in main_window.py;
  * the panel at the unit level: translate_fn=None → the English fallback literals, the retranslate is a no-op;
    a missing action callback → ValueError; fill_context_menu — 9 items + 4 separators;
  * THE REGRESSION OF THE BUG v0.9.2 (the i18n registry via a callback): on the language switch the sidebar rows
    (the buttons, the header, the placeholder, "All tags") are NOT lost and do not stay on the old
    language; the tag filter choice survives the retranslate.

Run: python tests/test_sidebar_panel.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData
from i18n import t as _t
import ui.sidebar as SB


# ══ 1. The MainWindow facade: the panel is built in, the public API is unchanged ═══════
print("== v0.9.9.4 sidebar panel: facade ==")

win = MW.MainWindow()
check("MainWindow owns a ui.sidebar.SidebarPanel",
      isinstance(getattr(win, "sidebar", None), SB.SidebarPanel),
      repr(type(getattr(win, "sidebar", None))))

# The facade references — the same objects as inside the panel (the tests go through win.tree, etc.)
check("facade: win.tree is panel.tree", win.tree is win.sidebar.tree)
check("facade: win.tag_filter is panel.tag_filter", win.tag_filter is win.sidebar.tag_filter)
check("facade: win.search_edit is panel.search_edit", win.search_edit is win.sidebar.search_edit)
for _attr in ("btn_add", "btn_connect", "btn_connect_ssh", "btn_props", "btn_delete"):
    check(f"facade: win.{_attr} is panel.{_attr}", getattr(win, _attr) is getattr(win.sidebar, _attr))
check("facade: win._sidebar_title is panel.title_label",
      win._sidebar_title is win.sidebar.title_label)

# The public API of the window (used by the existing tests) — the MainWindow methods, not the panel's
for _m in ("refresh_sidebar", "_sync_selection_state", "_on_tree_item_clicked",
           "_on_tree_item_double_click", "_on_sidebar_context_menu", "_reveal_node_on_map",
           "_update_sidebar_status_marker", "_active_tag_filter", "_on_tag_filter_changed"):
    check(f"facade: MainWindow has method {_m}",
          callable(getattr(MW.MainWindow, _m, None)), _m)

# The panel button signals are connected to the window slots. A SignalInstance in PySide6 has no
# .receivers() (and QObject.receivers('name') returns 0 for new-style signals), hence
# the connection is checked at the source level — the same pattern as the hygiene checks below:
# the facade references win.btn_* — the panel's widgets (checked above), the click emits exactly these
# signals, and connect() in main_window.py closes the chain.
_mw_src_signals = open(sys.modules[MW.__name__].__file__, encoding="utf-8").read()
for _sig in ("add_server_clicked", "add_connection_clicked", "connect_ssh_clicked",
             "show_properties_clicked", "delete_selected_clicked"):
    check(f"main_window.py wires sidebar.{_sig} to a window slot",
          f"self.sidebar.{_sig}.connect(" in _mw_src_signals)

# Hygiene: the cluster code in main_window.py is gone (the tree/markers/rows — in the panel)
_mw_src = open(sys.modules[MW.__name__].__file__, encoding="utf-8").read()
check("main_window.py: no 'self.tree = QTreeWidget()' left", "self.tree = QTreeWidget()" not in _mw_src)
check("main_window.py: no '_status_dot_icon' definition left", "def _status_dot_icon" not in _mw_src)
check("main_window.py: no '_apply_status_marker' definition left", "def _apply_status_marker" not in _mw_src)
check("main_window.py: no '_sync_tag_filter_items' definition left", "def _sync_tag_filter_items" not in _mw_src)
_sb_src = open(sys.modules[SB.__name__].__file__, encoding="utf-8").read()
check("ui/sidebar.py defines SidebarPanel(QWidget)", "class SidebarPanel(QWidget)" in _sb_src)

# ══ 2. refresh_sidebar via the facade: the rows, the markers, the search, the tag filter ═════
print("== v0.9.9.4 sidebar panel: refresh via facade ==")

n1 = win.scene.add_server(ServerData(id="sp7a", alias="web-1", host="10.30.0.1",
                                     user="ops", ip="10.30.0.1", tags=["prod"], x=100, y=100))
n2 = win.scene.add_server(ServerData(id="sp7b", alias="db-1", host="db.internal",
                                     user="dba", x=500, y=300))
win.refresh_sidebar()
check("refresh_sidebar builds a row per node (facade)", win.tree.topLevelItemCount() == 2,
      f"rows={win.tree.topLevelItemCount()}")
row1 = None
for i in range(win.tree.topLevelItemCount()):
    if win.tree.topLevelItem(i).data(0, Qt.UserRole) == "sp7a":
        row1 = win.tree.topLevelItem(i)
check("row text is 'alias  (host)' + tag suffix",
      row1 is not None and row1.text(0) == "web-1  (10.30.0.1)  [prod]",
      row1.text(0) if row1 else "no row")
check("row carries a status marker icon (idle dot)",
      row1 is not None and not row1.icon(0).isNull())

# Search: the panel search field filters the rows (textChanged → refresh_sidebar)
win.search_edit.setText("db.internal")  # the host of node db-1 (the search — a substring over alias/host/ip/comment/tags)
check("search query filters rows", win.tree.topLevelItemCount() == 1,
      f"rows={win.tree.topLevelItemCount()}")
win.search_edit.setText("")

# The tag filter: the panel combobox (unique tags + "All tags"), the selection filters the rows
_tags = [win.tag_filter.itemText(i) for i in range(win.tag_filter.count())]
check("tag filter lists 'All tags' + unique tag", _tags[0] == _t("filter.all_tags") and "prod" in _tags[1],
      str(_tags))
idx_prod = win.tag_filter.findData("prod")
win.tag_filter.setCurrentIndex(idx_prod)
check("selecting a tag filters rows (db-1 hidden)",
      win.tree.topLevelItemCount() == 1, f"rows={win.tree.topLevelItemCount()}")
check("the tag filter dims the non-matching node on the map (the AND semantics v0.9.8)",
      getattr(n2, "_dimmed", False) is True and getattr(n1, "_dimmed", False) is False,
      f"n1={getattr(n1, '_dimmed', '?')} n2={getattr(n2, '_dimmed', '?')}")
win.tag_filter.setCurrentIndex(0)

# The status marker is updated in place (without rebuilding the tree — the v0.8.0 #3 pattern)
_rows_before = win.tree.topLevelItemCount()
n1.set_status("online")
win._update_sidebar_status_marker("sp7a")
check("status marker updates in place (row count unchanged)",
      win.tree.topLevelItemCount() == _rows_before, f"{_rows_before} -> {win.tree.topLevelItemCount()}")

# A click on a row — the window slot selects the node on the scene
for i in range(win.tree.topLevelItemCount()):
    if win.tree.topLevelItem(i).data(0, Qt.UserRole) == "sp7b":
        win._on_tree_item_clicked(win.tree.topLevelItem(i), 0)
check("tree row click selects the node on the scene (window slot)",
      win.scene.get_selected_node() is n2, repr(win.scene.get_selected_node()))

# ══ 3. The panel at the unit level: the callbacks, i18n=None, the context menu ═══════════
print("== v0.9.9.4 sidebar panel: unit level ==")

# Without i18n (translate_fn=None): the English fallback literals from construction, retranslate is a no-op
panel_ru = SB.SidebarPanel(translate_fn=None, actions={k: (lambda n: None) for k in
                                 ("ssh", "external", "edit", "copy_ip", "copy_hostname",
                                  "ping", "collect_info", "reveal", "delete")}, show_title=False)
check("panel without i18n keeps the English fallback button literals", panel_ru.btn_add.text() == "Add Server",
      panel_ru.btn_add.text())
check("panel without i18n: no title label (as before v0.9.9.4)", panel_ru.title_label is None)
panel_ru.retranslate()  # a no-op — it must not fall and change nothing
check("panel without i18n: retranslate is a safe no-op", panel_ru.btn_add.text() == "Add Server")

# A missing action callback → ValueError (fail fast on a wrong build)
try:
    SB.SidebarPanel(translate_fn=None, actions={"ssh": lambda n: None}, show_title=False)
    check("panel raises ValueError on missing action callback", False, "no exception")
except ValueError as e:
    check("panel raises ValueError on missing action callback", "ssh" in str(e) or "no callbacks" in str(e), str(e))

# fill_context_menu: 9 items + 4 separators in the ROADMAP v0.9.6 order, the labels — i18n
_calls = []
panel_ctx = SB.SidebarPanel(translate_fn=_t, actions={k: (lambda n, _k=k: _calls.append(_k))
                                   for k in ("ssh", "external", "edit", "copy_ip",
                                             "copy_hostname", "ping", "collect_info",
                                             "reveal", "delete")}, show_title=False)
# The fill_context_menu/refresh_rows contract: node — a wrapper with .data (in production it is
# A ServerNode from the scene: MainWindow._on_sidebar_context_menu passes scene.get_node()).
# A bare ServerData is not passed here — the fake repeats the contract, not a subset of it.
class _FakeNode:
    def __init__(self, data):
        self.data = data


fake_node = _FakeNode(ServerData(id="sp7c", alias="ctx", host="10.30.0.9", user="u"))
menu = QMenu()
panel_ctx.fill_context_menu(menu, fake_node)
_actions = [a for a in menu.actions() if not a.isSeparator()]
_seps = sum(1 for a in menu.actions() if a.isSeparator())
check("fill_context_menu: exactly 9 actions", len(_actions) == 9, f"got {len(_actions)}")
check("fill_context_menu: grouped by 4 separators", _seps == 4, f"separators={_seps}")
_expected = [_t(k) for k in ("ctx.ssh_connect", "ctx.ssh_external", "ctx.edit_server",
                             "ctx.copy_ip", "ctx.copy_hostname", "ctx.ping",
                             "ctx.collect_info", "ctx.reveal_on_map", "ctx.delete_server")]
check("fill_context_menu: action order + i18n labels per ROADMAP v0.9.6",
      [a.text() for a in _actions] == _expected, str([a.text() for a in _actions]))
_actions[3].trigger()  # ctx.copy_ip
check("context menu action triggers its callback with the node", _calls == ["copy_ip"], str(_calls))

# ══ v1.0RC4: the "Quick launch" submenu as the first item (ql_entry/ql_configure) ══
print("== v1.0RC4 quick launch submenu ==")

_ql_calls = []
panel_ql = SB.SidebarPanel(translate_fn=_t, actions={k: (lambda n, _k=k: None) for k in
                                   ("ssh", "external", "edit", "copy_ip", "copy_hostname",
                                    "ping", "collect_info", "reveal", "delete")},
                          show_title=False)
# The optional callbacks outside CONTEXT_MENU_ITEMS — the panel without them does not change the menu.
panel_ql._actions["ql_entry"] = lambda n, e: _ql_calls.append(("entry", n.data.id, dict(e)))
panel_ql._actions["ql_configure"] = lambda n: _ql_calls.append(("configure", n.data.id))

fake_node_ql = _FakeNode(ServerData(id="sp7d", alias="ql-ctx", host="10.30.0.10", user="u",
                                    quick_launch=[
                                        {"type": "url", "name": "Webmin", "value": "http://10.30.0.10:10000/"},
                                        {"type": "command", "name": "K9S", "value": "k9s"}]))
menu_ql = QMenu()
panel_ql.fill_context_menu(menu_ql, fake_node_ql)
# PySide6 6.11/shiboken (the same bug as _qaction_guard v0.9.8 in main_window.py):
# the temporary Python QAction wrappers with an attached QMenu + the GC drop the C++ menu —
# the action/submenu are kept alive by references (caching the wrappers: a repeated access
# returns the same object, see the "IMPORTANT" note in tests/test_map_search.py at line ~95).
first = menu_ql.actions()[0]
ql_sub = first.menu()
check("quick launch: submenu is the FIRST item (above SSH)",
      ql_sub is not None and first.text() == _t("ctx.quick_launch"),
      f"first={first.text()!r} has_sub={ql_sub is not None}")
if ql_sub is not None:
    _ql_sub_actions = list(ql_sub.actions())
    ql_items = [a.text() for a in _ql_sub_actions if not a.isSeparator()]
    check("quick launch: entries + separator + 'Configure…'",
          ql_items == ["Webmin", "K9S", _t("ql.configure")]
          and sum(1 for a in _ql_sub_actions if a.isSeparator()) == 1, str(ql_items))
    # The item trigger — the callback gets (node, entry)
    ql_sub.actions()[0].trigger()
    check("quick launch: entry triggers ql_entry(node, entry)",
          _ql_calls == [("entry", "sp7d", {"type": "url", "name": "Webmin",
                                            "value": "http://10.30.0.10:10000/"})], str(_ql_calls))
    # "Configure…" is looked up BY TEXT: the index is unstable — a separator between the items
    # (previously actions()[2] pointed at the separator, and the trigger silently failed).
    _cfg_act = next((a for a in ql_sub.actions() if a.text() == _t("ql.configure")), None)
    if _cfg_act is not None:
        _cfg_act.trigger()
    check("quick launch: 'Configure…' triggers ql_configure(node)",
          _ql_calls[-1] == ("configure", "sp7d"), str(_ql_calls))

# A node WITHOUT items: the submenu exists, inside only "Configure…" (discoverability)
fake_node_empty = _FakeNode(ServerData(id="sp7e", alias="ql-empty", host="10.30.0.11", user="u"))
menu_ql2 = QMenu()
panel_ql.fill_context_menu(menu_ql2, fake_node_empty)
first2 = menu_ql2.actions()[0]
sub2 = first2.menu()
check("quick launch: empty node → submenu with only 'Configure…'",
      sub2 is not None and [a.text() for a in sub2.actions() if not a.isSeparator()] == [_t("ql.configure")],
      str([a.text() for a in (sub2.actions() if sub2 else [])]))

# The panel WITHOUT the ql callbacks: the menu as in v0.9.6 (backward-compat): no submenu,
# SSH goes first; with the ql callbacks — a submenu + a separator before SSH.
_ql_texts = [a.text() for a in menu.actions()]              # without the ql callbacks (the panel_ctx menu)
check("quick launch: panel without ql callbacks keeps the v0.9.6 menu",
      _ql_texts[0] == _t("ctx.ssh_connect"), str(_ql_texts[:3]))
_ql_texts2 = [a for a in menu_ql2.actions() if not a.isSeparator()]
check("quick launch: with ql callbacks — submenu first, then SSH",
      _ql_texts2[0].text() == _t("ctx.quick_launch") and _ql_texts2[1].text() == _t("ctx.ssh_connect"),
      str([a.text() for a in _ql_texts2[:3]]))

# ══ 4. THE REGRESSION OF THE BUG v0.9.2: the sidebar rows survive the language switch ═══════
print("== v0.9.9.4 sidebar panel: retranslate on language switch ==")

# The basic lines in Russian: since v1.1.1 the default language — en (new users),
# that is why we set ru explicitly via the full window path (and also check the retranslate before the baseline).
win._switch_language("ru")
btn_ru = win.btn_add.text()
title_ru = win._sidebar_title.text()
ph_ru = win.search_edit.placeholderText()
alltags_ru = win.tag_filter.itemText(0)
check("baseline: sidebar strings are translated (not raw keys)",
      btn_ru == _t("btn.add_server") and title_ru == _t("server.title")
      and ph_ru == _t("search.placeholder") and alltags_ru == _t("filter.all_tags"),
      f"{btn_ru!r}/{title_ru!r}")

# The tag-filter selection, which must survive a retranslate
win.tag_filter.setCurrentIndex(win.tag_filter.findData("prod"))

# A language switch — the full window path (set_language → _apply_ui_translations → panel.retranslate)
win._switch_language("en")
check("after switch to en: button label retranslated", win.btn_add.text() == _t("btn.add_server"),
      f"{win.btn_add.text()!r} want {_t('btn.add_server')!r}")
check("after switch to en: title retranslated", win._sidebar_title.text() == _t("server.title"),
      repr(win._sidebar_title.text()))
check("after switch to en: search placeholder retranslated",
      win.search_edit.placeholderText() == _t("search.placeholder"),
      repr(win.search_edit.placeholderText()))
check("after switch to en: 'All tags' label retranslated (not lost)",
      win.tag_filter.itemText(0) == _t("filter.all_tags"), repr(win.tag_filter.itemText(0)))
check("tag filter selection survives retranslate",
      win.tag_filter.currentData() == "prod", repr(win.tag_filter.currentData()))

# Back: the rows return to Russian (the registry is applied again)
win._switch_language("ru")
check("back to ru: button label restored", win.btn_add.text() == btn_ru, f"{win.btn_add.text()!r} want {btn_ru!r}")
check("back to ru: title restored", win._sidebar_title.text() == title_ru)
check("back to ru: placeholder restored", win.search_edit.placeholderText() == ph_ru)
check("back to ru: 'All tags' label restored", win.tag_filter.itemText(0) == alltags_ru)
win.tag_filter.setCurrentIndex(0)

finish()
