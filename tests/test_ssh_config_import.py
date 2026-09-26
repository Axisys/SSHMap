# -*- coding: utf-8 -*-
"""v1.4.1 — Import from ~/.ssh/config (ROADMAP v1.4.1, tasks 1–6).

Sections:
  §1 the parser: the directives, ssh's own defaults, case, `=`, quoting, continuations, comments;
  §2 first-obtained-wins: a repeated `Host` alias fills only the gaps;
  §3 the skip / note records (a wildcard pattern, a `Match` block, `ProxyJump`, an extra `IdentityFile`);
  §4 `Include`: relative to ~/.ssh, nested, a glob, a missing file, a cycle, the depth cap;
  §5 the loader and the path helpers (`default_config_path`, the token expansion, missing/unreadable);
  §6 the TXT parser stops losing data (the v1.3.3 audit) — unit + end to end through the window;
  §7 the picker dialog (checkboxes, the all/none buttons, `selected_hosts()`, the report);
  §8 the window wiring (the menu item, the registry action, the end-to-end import, duplicates, cancel);
  §9 the release state (the registry counters, i18n parity, the pins, the ROADMAP figures).

Run: python tests/test_ssh_config_import.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, check_i18n_parity, check_release_state,
                     load_i18n_langs, i18n_lang_codes, translation_keys, wait_until)

ROOT, WORK = bootstrap()  # HOME isolation + offscreen Qt — BEFORE the app imports

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox  # noqa: E402

import i18n  # noqa: E402
import services.ssh_config_importer as SCI  # noqa: E402
import services.host_importer as HI  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

HOME = os.path.expanduser("~")            # the sandbox HOME of this run


def write(path, text, encoding="utf-8"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        f.write(text)
    return path


def by_alias(result):
    return {h.alias: h for h in result.hosts}


def reasons(issues):
    return [(i.subject, i.reason) for i in issues]


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the parser: the directives and the ssh defaults ==")
# ════════════════════════════════════════════════════════════════════════════

CONFIG = (
    "# a leading comment\n"
    "\n"
    "Host web-1\n"
    "    HostName 10.0.0.5\n"
    "    User ubuntu\n"
    "    Port 2222\n"
    "    IdentityFile ~/.ssh/keys/web_ed25519\n"
    "\n"
    "HOST db-1\n"
    "    hostname = 10.0.0.6        # an inline comment\n"
    "    IdentityFile \"/tmp/my keys/db key\"\n"
    "\n"
    "Host bare\n"
    "    Port \\\n"
    "        2200\n"
    "\n"
    "Host quoted\n"
    '    HostName "web.example.com"\n'
    "    User \"deploy user\"\n"
    "\n"
    "Host noname\n"
    "    User root\n"
)

_res = SCI.parse_ssh_config(CONFIG, "fixture", home=HOME, local_user="localme")
_hosts = by_alias(_res)
check("§1 five aliases parsed from the fixture", len(_res.hosts) == 5, str(sorted(_hosts)))
check("§1 HostName/User/Port land in the record",
      _hosts["web-1"].host == "10.0.0.5" and _hosts["web-1"].user == "ubuntu"
      and _hosts["web-1"].port == 2222,
      str(_hosts["web-1"]))
check("§1 IdentityFile → key_path (a ~ path expanded against HOME)",
      _hosts["web-1"].key_path == os.path.join(HOME, ".ssh", "keys", "web_ed25519"),
      _hosts["web-1"].key_path)
check("§1 the directive keyword is case-insensitive (HOST/hostname)",
      _hosts["db-1"].host == "10.0.0.6", str(_hosts["db-1"]))
check("§1 '=' works as the separator and an inline comment ends the line",
      _hosts["db-1"].user == "localme" and "comment" not in _hosts["db-1"].host,
      str(_hosts["db-1"]))
check("§1 a quoted value keeps its space and loses the quotes",
      _hosts["db-1"].key_path == "/tmp/my keys/db key",
      _hosts["db-1"].key_path)
check("§1 a trailing backslash continues the line (Port on the next line)",
      _hosts["bare"].port == 2200, str(_hosts["bare"].port))
check("§1 a host without HostName uses the ALIAS as the host",
      _hosts["bare"].host == "bare" and _hosts["noname"].host == "noname",
      f"{_hosts['bare'].host!r} / {_hosts['noname'].host!r}")
check("§1 a host without User gets the LOCAL user name (the ssh default)",
      _hosts["bare"].user == "localme" and _hosts["noname"].user == "root",
      str({a: h.user for a, h in _hosts.items()}))
check("§1 a host without Port gets 22",
      _hosts["noname"].port == 22 and _hosts["bare"].key_path == "",
      str({a: (h.port, h.key_path) for a, h in _hosts.items()}))
check("§1 a quoted HostName is unquoted",
      _hosts["quoted"].host == "web.example.com", _hosts["quoted"].host)
check("§1 the source and the line of an alias are recorded",
      _hosts["web-1"].source == "fixture" and _hosts["web-1"].line == 3,
      f"{_hosts['web-1'].source}:{_hosts['web-1'].line}")
check("§1 the files list carries the source that was read", _res.files == ("fixture",),
      str(_res.files))

check("§1 a malformed Port is ignored (the ssh default stays)",
      SCI.parse_ssh_config("Host x\n  Port abc\n", "f", home=HOME,
                           local_user="u").hosts[0].port == 22)
check("§1 an empty config yields no hosts and no records",
      SCI.parse_ssh_config("", "f", home=HOME, local_user="u").hosts == ())
check("§1 a config without a single Host block yields nothing",
      SCI.parse_ssh_config("# only a comment\nUser nobody\n",
                           "f", home=HOME, local_user="u").hosts == ())
check("§1 a global directive before the first Host block is ignored (documented)",
      SCI.parse_ssh_config("User globalonly\nHost a\n", "f", home=HOME,
                           local_user="u").hosts[0].user == "u")
check("§1 `Host a b c` opens ONE block for THREE aliases",
      [h.alias for h in SCI.parse_ssh_config(
          "Host a b c\n  HostName 10.5.5.5\n", "f", home=HOME, local_user="u").hosts]
      == ["a", "b", "c"])
check("§1 a `!`-pattern is an exclusion, not a host (and not a skip record)",
      [h.alias for h in SCI.parse_ssh_config(
          "Host safe !unsafe\n  HostName 10.6.6.6\n", "f", home=HOME, local_user="u").hosts]
      == ["safe"])
check("§1 `IdentityFile none` clears the key (and is not a note)",
      SCI.parse_ssh_config("Host k\n  IdentityFile ~/.ssh/a\n  IdentityFile none\n",
                           "f", home=HOME, local_user="u").hosts[0].key_path == "")


# ════════════════════════════════════════════════════════════════════════════
print("== §2 first obtained wins (a repeated Host alias) ==")
# ════════════════════════════════════════════════════════════════════════════

DUP = (
    "Host srv\n"
    "    HostName 10.0.0.1\n"
    "    User first\n"
    "\n"
    "Host srv\n"
    "    HostName 10.0.0.99\n"
    "    User second\n"
    "    Port 2222\n"
    "    IdentityFile ~/.ssh/second_key\n"
)
_dup = SCI.parse_ssh_config(DUP, "f", home=HOME, local_user="u")
check("§2 a repeated alias is ONE host, not two", len(_dup.hosts) == 1, str(len(_dup.hosts)))
check("§2 the FIRST HostName wins", _dup.hosts[0].host == "10.0.0.1", _dup.hosts[0].host)
check("§2 the FIRST User wins", _dup.hosts[0].user == "first", _dup.hosts[0].user)
check("§2 an option the first block did not set is filled from the second "
      "(Port + IdentityFile)", _dup.hosts[0].port == 2222
      and _dup.hosts[0].key_path.endswith("second_key"), str(_dup.hosts[0]))
check("§2 no skip record for a repeated alias (that is a normal config)",
      _dup.skipped == (), str(_dup.skipped))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the skip records and the notes ==")
# ════════════════════════════════════════════════════════════════════════════

SKIPS = (
    "Host *\n"
    "    User globaluser\n"
    "    IdentityFile ~/.ssh/id_global\n"
    "\n"
    "Host *.example.com\n"
    "    User wildcarduser\n"
    "\n"
    "Host jump-1\n"
    "    HostName 10.0.0.7\n"
    "    ProxyJump bastion.example.com\n"
    "    ProxyCommand ssh -W %h:%p bastion\n"
    "    IdentityFile ~/.ssh/one\n"
    "    IdentityFile ~/.ssh/two\n"
    "\n"
    "Match host internal\n"
    "    User matchuser\n"
    "    HostName 10.0.0.8\n"
    "\n"
    "Host after-match\n"
    "    HostName 10.0.0.9\n"
    "    Include nope.conf\n"
)
_sk = SCI.parse_ssh_config(SKIPS, "f", home=HOME, local_user="u")
_skh = by_alias(_sk)
check("§3 only the concrete hosts are imported (jump-1 + after-match)",
      sorted(_skh) == ["after-match", "jump-1"], str(sorted(_skh)))
check("§3 a `Host *` block is NOT applied to the other hosts (its User is lost, by decision)",
      _skh["jump-1"].user == "u" and _skh["after-match"].user == "u",
      str({a: h.user for a, h in _skh.items()}))
check("§3 `Host *` and `Host *.example.com` are skip records (wildcard)",
      ("*", SCI.REASON_WILDCARD) in reasons(_sk.skipped)
      and ("*.example.com", SCI.REASON_WILDCARD) in reasons(_sk.skipped),
      str(reasons(_sk.skipped)))
check("§3 a Match block is a skip record and its inside is NOT imported",
      ("host internal", SCI.REASON_MATCH) in reasons(_sk.skipped)
      and "internal" not in _skh, str(reasons(_sk.skipped)))
check("§3 a directive after the Match block is read again (the block ends at Host)",
      _skh["after-match"].host == "10.0.0.9", str(_skh["after-match"]))
check("§3 ProxyJump AND ProxyCommand are notes — the host stays imported",
      reasons(_sk.notes).count(("jump-1", SCI.NOTE_PROXY)) == 2, str(reasons(_sk.notes)))
check("§3 an extra IdentityFile is a note carrying the dropped path",
      ("jump-1", SCI.NOTE_IDENTITY_EXTRA) in reasons(_sk.notes)
      and any(i.detail.endswith("two") for i in _sk.notes), str(reasons(_sk.notes)))
check("§3 the first IdentityFile is the one that is kept",
      _skh["jump-1"].key_path.endswith("one"), _skh["jump-1"].key_path)
check("§3 an unreadable Include is a skip record, not a failure",
      ("nope.conf", SCI.REASON_INCLUDE_MISSING) in reasons(_sk.skipped),
      str(reasons(_sk.skipped)))
check("§3 the host that carried the broken Include is still imported",
      _skh["after-match"].host == "10.0.0.9")
check("§3 one host with a proxy directive yields ONE record per directive, not per host",
      len([i for i in _sk.notes if i.reason == SCI.NOTE_PROXY]) == 2,
      str(len(_sk.notes)))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 Include: the simple recursion ==")
# ════════════════════════════════════════════════════════════════════════════

INC_HOME = os.path.join(WORK, "inc_home")
SSH_DIR = os.path.join(INC_HOME, ".ssh")
write(os.path.join(SSH_DIR, "conf.d", "web.conf"),
      "Host inc-web\n    HostName 10.7.7.1\nInclude conf.d/deep.conf\n")
write(os.path.join(SSH_DIR, "conf.d", "deep.conf"),
      "Host inc-deep\n    HostName 10.7.7.2\n")
write(os.path.join(SSH_DIR, "extra.conf"), "Host inc-extra\n    HostName 10.7.7.3\n")
MAIN = write(os.path.join(SSH_DIR, "config"),
             "Host inc-top\n    HostName 10.7.7.0\n"
             "Include conf.d/web.conf\n"
             "Include extra.conf\n"
             "Include missing.conf\n"
             "Include abs.conf\n")
# a cycle: abs.conf includes the main config again
write(os.path.join(SSH_DIR, "abs.conf"),
      "Host inc-abs\n    HostName 10.7.7.4\nInclude config\n")

_loaded = SCI.load_ssh_config(home=INC_HOME, local_user="u")
_lh = by_alias(_loaded)
check("§4 the loader reads ~/.ssh/config of the given HOME",
      SCI.default_config_path(INC_HOME) == MAIN and _loaded.path == MAIN, _loaded.path)
check("§4 the entry file + two nested includes + the cycle file are all read",
      sorted(_lh) == ["inc-abs", "inc-deep", "inc-extra", "inc-top", "inc-web"],
      str(sorted(_lh)))
check("§4 an Include resolves RELATIVE TO ~/.ssh (not to the including file)",
      _lh["inc-web"].host == "10.7.7.1" and _lh["inc-web"].source.endswith("web.conf")
      and _lh["inc-deep"].source.endswith("deep.conf"),
      str(_lh["inc-web"]))
check("§4 the include chain is read at the point of the directive (nested includes work)",
      _lh["inc-deep"].source.endswith("deep.conf"), _lh["inc-deep"].source)
check("§4 a file including the entry file again is a CYCLE, not an endless loop",
      _lh["inc-abs"].host == "10.7.7.4")
check("§4 a missing Include is a skip record with its pattern",
      ("missing.conf", SCI.REASON_INCLUDE_MISSING) in reasons(_loaded.skipped),
      str(reasons(_loaded.skipped)))
check("§4 the files list names everything that was really read",
      len(_loaded.files) == 5 and all(os.path.isfile(p) for p in _loaded.files),
      str([os.path.basename(p) for p in _loaded.files]))

GLOB_HOME = os.path.join(WORK, "glob_home")
write(os.path.join(GLOB_HOME, ".ssh", "config"), "Include conf.d/*.conf\n")
write(os.path.join(GLOB_HOME, ".ssh", "conf.d", "a.conf"), "Host ga\n    HostName 10.8.8.1\n")
write(os.path.join(GLOB_HOME, ".ssh", "conf.d", "b.conf"), "Host gb\n    HostName 10.8.8.2\n")
_g = SCI.load_ssh_config(home=GLOB_HOME, local_user="u")
check("§4 a glob Include reads every match",
      sorted(by_alias(_g)) == ["ga", "gb"], str(sorted(by_alias(_g))))
check("§4 an Include glob matching nothing is a skip record",
      ("conf.d/*.nomatch", SCI.REASON_INCLUDE_MISSING) in reasons(
          SCI.parse_ssh_config("Include conf.d/*.nomatch\n", "f",
                               home=GLOB_HOME, local_user="u").skipped))

# the depth cap: each file includes the next one
CAP_HOME = os.path.join(WORK, "cap_home")
DEEP = SCI.MAX_INCLUDE_DEPTH + 3
for i in range(DEEP):
    write(os.path.join(CAP_HOME, ".ssh", f"lvl{i}.conf"),
          f"Host lvl{i}\n    HostName 10.9.{i}.1\nInclude lvl{i + 1}.conf\n")
write(os.path.join(CAP_HOME, ".ssh", "config"), "Include lvl0.conf\n")
_cap = SCI.load_ssh_config(home=CAP_HOME, local_user="u")
check("§4 the depth cap stops the chain (no RecursionError, the cap is real)",
      len(_cap.hosts) <= SCI.MAX_INCLUDE_DEPTH + 1 and len(_cap.hosts) >= 2,
      f"hosts={len(_cap.hosts)} (cap {SCI.MAX_INCLUDE_DEPTH})")
check("§4 the chain cut at the cap is reported",
      any(i.reason == SCI.REASON_INCLUDE_MISSING for i in _cap.skipped),
      str(reasons(_cap.skipped)))


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the loader and the path helpers ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 default_config_path() is ~/.ssh/config",
      SCI.default_config_path("/home/x") == os.path.join("/home/x", ".ssh", "config"),
      SCI.default_config_path("/home/x"))
try:
    SCI.load_ssh_config(os.path.join(WORK, "no_such_config"), home=HOME, local_user="u")
    _missing_ok = False
except SCI.SshConfigError as e:
    _missing_ok = e.code == SCI.ERROR_MISSING and e.detail.endswith("no_such_config")
check("§5 a missing ENTRY file raises SshConfigError('missing')", _missing_ok)
_dir_path = os.path.join(WORK, "a_directory")
os.makedirs(_dir_path, exist_ok=True)
try:
    SCI.load_ssh_config(_dir_path, home=HOME, local_user="u")
    _unreadable_ok = False
except SCI.SshConfigError as e:
    _unreadable_ok = e.code in (SCI.ERROR_UNREADABLE, SCI.ERROR_MISSING)
check("§5 an unreadable ENTRY file raises a coded SshConfigError", _unreadable_ok)
check("§5 SshConfigError carries a code and a detail for the caller",
      SCI.SshConfigError("x", "why").detail == "why"
      and "x" in str(SCI.SshConfigError("x")), str(SCI.SshConfigError("x", "why")))

check("§5 the ~ token expands against HOME",
      SCI.expand_path_tokens("~/k", home="/h") == os.path.normpath(os.path.join("/h", "k")),
      SCI.expand_path_tokens("~/k", home="/h"))
check("§5 %d and %u expand to the local home and user",
      SCI.expand_path_tokens("%d/%u/key", home="/h", local_user="me") == "/h/me/key",
      SCI.expand_path_tokens("%d/%u/key", home="/h", local_user="me"))
check("§5 %h and %r expand to the block's host and user",
      SCI.expand_path_tokens("/k/%r@%h", host="10.0.0.1", user="root") == "/k/root@10.0.0.1")
check("§5 %% is a literal percent and an unknown %x stays as written",
      SCI.expand_path_tokens("%%h %z", host="h") == "%h %z",
      SCI.expand_path_tokens("%%h %z", host="h"))
_tok = SCI.parse_ssh_config(
    "Host t\n  HostName 10.0.0.2\n  User deploy\n  IdentityFile %d/keys/%h_%r\n",
    "f", home="/home/x", local_user="localme")
check("§5 the tokens of an IdentityFile resolve against the BLOCK's host/user",
      _tok.hosts[0].key_path == "/home/x/keys/10.0.0.2_deploy", _tok.hosts[0].key_path)

# dedupe_hosts: the window's rule, unit-tested
_h = [SCI.SshConfigHost("a", "10.0.0.1", "root", 22),
      SCI.SshConfigHost("b", "10.0.0.1", "root", 22),
      SCI.SshConfigHost("c", "10.0.0.1", "root", 2222),
      SCI.SshConfigHost("d", "10.0.0.1", "other", 22)]
_fresh, _dups = SCI.dedupe_hosts(_h)
check("§5 dedupe_hosts keys on (host, port, user) — the port separates two entries",
      [x.alias for x in _fresh] == ["a", "c", "d"] and [x.alias for x in _dups] == ["b"],
      f"{[x.alias for x in _fresh]} / {[x.alias for x in _dups]}")
check("§5 the comparison is case-insensitive for the host and the user",
      SCI.dedupe_hosts([SCI.SshConfigHost("x", "WEB.example", "Root", 22)],
                       [("web.example", 22, "root")])[0] == [])
check("§5 a caller's key set is mutated (the map's keys + the config's own duplicates)",
      SCI.dedupe_hosts(_h, [("10.0.0.1", 22, "root")])[0][0].alias == "c")


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the TXT parser stops losing data (the v1.3.3 audit) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§6 a multi-word line yields ALL the words (web-1 web-2 db-master)",
      HI.parse_hosts_file("web-1 web-2 db-master\n") == ["web-1", "web-2", "db-master"],
      str(HI.parse_hosts_file("web-1 web-2 db-master\n")))
check("§6 the historical 'host ip' form yields both entries",
      HI.parse_hosts_file("web-1 10.0.0.5\n") == ["web-1", "10.0.0.5"])
check("§6 tabs separate entries as well",
      HI.parse_hosts_file("a\tb   c\n") == ["a", "b", "c"])
check("§6 an inline '#' comment is not a host",
      HI.parse_hosts_file("web-1 web-2 # prod pair\n") == ["web-1", "web-2"],
      str(HI.parse_hosts_file("web-1 web-2 # prod pair\n")))
check("§6 an inline '//' comment is not a host",
      HI.parse_hosts_file("db-1 // the master\n") == ["db-1"])
check("§6 a whole-line comment is still skipped",
      HI.parse_hosts_file("# web-9\n// db-9\n") == [])
check("§6 empty lines and blank input yield nothing",
      HI.parse_hosts_file("\n   \n\n") == [] and HI.parse_hosts_file("") == [])
check("§6 the multi-word reading is pinned in the docstring (no silent loss)",
      "multi-host" in (HI.parse_hosts_file.__doc__ or "")
      or "EVERY whitespace-separated word" in (HI.parse_hosts_file.__doc__ or ""),
      (HI.parse_hosts_file.__doc__ or "")[:60])

# end to end through the window: a real file with a multi-word line
import ui.main_window as MW  # noqa: E402
from modules.undo_commands import CmdAddRemoveNodeBatch  # noqa: E402

mw = MW.MainWindow()
mw.show()
app.processEvents()

txt_path = write(os.path.join(WORK, "multi_hosts.txt"),
                 "10.1.1.1 10.1.1.2 # a pair\ndb-master\n")
_orig_open = QFileDialog.getOpenFileName
_orig_info = QMessageBox.information
_orig_resolve = HI.resolve_host
_txt_info = []
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (txt_path, ""))
QMessageBox.information = staticmethod(lambda *a, **k: _txt_info.append(a) or QMessageBox.Ok)
HI.resolve_host = lambda name: None            # the DNS step is not the subject here
try:
    mw._import_servers_from_txt()
    wait_until(lambda: len(mw.scene.nodes()) == 3, timeout_ms=8000)
    app.processEvents()
finally:
    HI.resolve_host = _orig_resolve
    QFileDialog.getOpenFileName = _orig_open
    QMessageBox.information = _orig_info
check("§6 E2E: three words on one line → three nodes (no silent loss)",
      len(mw.scene.nodes()) == 3, str(sorted(n.data.alias for n in mw.scene.nodes())))
check("§6 E2E: the trailing comment produced no node",
      all("prod" not in n.data.alias for n in mw.scene.nodes()))
check("§6 E2E: the words are the aliases and the IPs got their ip field",
      sorted(n.data.alias for n in mw.scene.nodes()) == ["10.1.1.1", "10.1.1.2", "db-master"]
      and all(n.data.ip == n.data.alias for n in mw.scene.nodes()
              if n.data.alias.startswith("10.")),
      str([(n.data.alias, n.data.ip) for n in mw.scene.nodes()]))
check("§6 E2E: the whole batch is ONE undo command",
      isinstance(mw.undo_stack.command(mw.undo_stack.count() - 1), CmdAddRemoveNodeBatch))
check("§6 E2E: the report counted no skipped entry",
      _txt_info and _txt_info[0][2] == mw.t("msg.import_servers_result", added=3, skipped=0),
      str(_txt_info[:1]))
mw._undo()
check("§6 E2E: Ctrl+Z removes the whole batch", len(mw.scene.nodes()) == 0)


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the picker dialog ==")
# ════════════════════════════════════════════════════════════════════════════

from dialogs.ssh_config_import_dialog import SshConfigImportDialog, reason_text  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

DH = [SCI.SshConfigHost("web-1", "10.0.0.5", "ubuntu", 2222,
                        os.path.join(HOME, ".ssh", "k1"), "cfg", 3),
      SCI.SshConfigHost("db-1", "10.0.0.6", "postgres", 22, "", "cfg", 9)]
D_SKIP = [SCI.SshConfigIssue("*", SCI.REASON_WILDCARD, "", "cfg", 1),
          SCI.SshConfigIssue("old", SCI.REASON_DUPLICATE, "10.0.0.5", "cfg", 12)]
D_NOTE = [SCI.SshConfigIssue("web-1", SCI.NOTE_PROXY, "", "cfg", 5)]
dlg = SshConfigImportDialog(DH, D_SKIP, D_NOTE, "cfg", None)

check("§7 one row per host", dlg.item_count() == 2, str(dlg.item_count()))
check("§7 the columns carry the parsed values",
      [dlg.tree.topLevelItem(0).text(i) for i in range(5)]
      == ["web-1", "10.0.0.5", "2222", "ubuntu", DH[0].key_path],
      str([dlg.tree.topLevelItem(0).text(i) for i in range(5)]))
check("§7 every row starts CHECKED (one OK imports everything)",
      dlg.checked_count() == 2 and all(
          dlg.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked for i in range(2)))
check("§7 selected_hosts() returns the live records of the checked rows",
      dlg.selected_hosts() == DH and dlg.selected_hosts()[0] is DH[0],
      str(dlg.selected_hosts()))
check("§7 the import button is enabled while something is checked", dlg.btn_import.isEnabled())

dlg.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
app.processEvents()
check("§7 unchecking a row removes it from the selection",
      [h.alias for h in dlg.selected_hosts()] == ["db-1"], str(dlg.selected_hosts()))
check("§7 the import button stays enabled while one row is left", dlg.btn_import.isEnabled())
dlg.btn_none.click()
app.processEvents()
check("§7 'Uncheck all' empties the selection and DISABLES the import button",
      dlg.checked_count() == 0 and not dlg.btn_import.isEnabled())
check("§7 selected_hosts() is empty — there is nothing to confirm (no dead OK)",
      dlg.selected_hosts() == [])
dlg.btn_all.click()
app.processEvents()
check("§7 'Check all' restores the selection and the button",
      dlg.checked_count() == 2 and dlg.btn_import.isEnabled())

_rep = dlg.report_text()
check("§7 the report names the skipped hosts and their reasons",
      "*" in _rep and "old" in _rep
      and i18n.t("sshconfig.reason.wildcard") in _rep
      and i18n.t("sshconfig.reason.duplicate") in _rep, _rep)
check("§7 the report names the dropped directive of an imported host",
      "web-1" in _rep and i18n.t("sshconfig.note.proxy") in _rep, _rep)
check("§7 the two report groups carry their counts",
      i18n.t("sshconfig.skipped", count=2) in _rep
      and i18n.t("sshconfig.notes", count=1) in _rep, _rep)
check("§7 a clean import hides the report (nothing to tell)",
      SshConfigImportDialog(DH).report.isHidden())
check("§7 reason_text() falls back to the code pair for an unknown reason",
      reason_text(SCI.SshConfigIssue("s", "nope", "d")) == "s (nope)",
      reason_text(SCI.SshConfigIssue("s", "nope", "d")))
check("§7 reason_text() substitutes the {detail} of a note",
      ": " in reason_text(SCI.SshConfigIssue("s", SCI.NOTE_IDENTITY_EXTRA, "/k/id_x")),
      reason_text(SCI.SshConfigIssue("s", SCI.NOTE_IDENTITY_EXTRA, "/k/id_x")))
dlg.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §8 the window: the menu, the registry action and the import ==")
# ════════════════════════════════════════════════════════════════════════════

from ui import hotkey_registry as HR  # noqa: E402

check("§8 the action is in the registry with an EMPTY default",
      HR.default_sequence("file.import_ssh_config") == ""
      and "file.import_ssh_config" in HR.HOTKEY_ACTIONS)
check("§8 the registry grew 43 → 44 (v1.4.2 added view.toggle_minimap → 45; "
      "v1.4.5 added view.toggle_legend → 46; v1.5rc3 added help.cheatsheet + help.example → 48; "
      "v1.5rc4 added view.focus_map → 49; v1.5.1 → 51; v1.5.2 added view.toggle_activity → 52; "
      "v1.5.3 added node.collect_info + node.diagnose → 54; "
      "v1.5.5 added file.copy_list + file.export_list → 56, v1.6 the bulk edit / arrangement / "
      "connection report trio → 59)",
      len(HR.HOTKEY_ACTIONS) == 59, str(len(HR.HOTKEY_ACTIONS)))
check("§8 …and the empty defaults 21 → 22 (v1.4.2: 23; v1.4.5: 24; v1.5rc3: 25; v1.5rc4: 26; "
      "v1.5.1: 28; v1.5.2: 29; v1.5.3: 31; v1.5.5: 33)",
      len(HR.empty_default_action_ids()) == 36, str(len(HR.empty_default_action_ids())))


def menu_action(win, action_id):
    targets = getattr(win, "_hotkey_targets", {}).get(action_id) or []
    return targets[0] if targets else None


_act = menu_action(mw, "file.import_ssh_config")
check("§8 the File menu carries the item and it is registered as a hotkey target",
      _act is not None and _act.text() == mw.t("file.import_ssh_config"),
      _act.text() if _act else "None")
check("§8 the item carries no sequence out of the box",
      _act is not None and _act.shortcut().toString() == "")

# the real config of the sandbox HOME
CONFIG_PATH = SCI.default_config_path()
write(CONFIG_PATH,
      "Host web-1\n    HostName 10.0.0.5\n    User ubuntu\n    Port 2222\n"
      "    IdentityFile %d/.ssh/k1\n"
      "Host db-1\n    HostName 10.0.0.6\n    User postgres\n"
      "Host *\n    User globaluser\n"
      "Host mapped-1\n    HostName 10.0.0.7\n    User root\n"
      "Host dup-1\n    HostName 10.0.0.5\n    User ubuntu\n    Port 2222\n")

# a node the map already knows: mapped-1 points at the SAME host/port/user
from models.server import ServerData  # noqa: E402

mw.scene.add_server(ServerData(id="existing1", alias="mapped-1", host="10.0.0.7",
                               user="root", ssh_port=22, x=10, y=10))
app.processEvents()
check("§8 the fixture node is on the map (it is the 'already known' case)",
      any(n.data.alias == "mapped-1" for n in mw.scene.nodes()))

_orig_dlg_cls = MW.SshConfigImportDialog
_info_calls = []
QMessageBox.information = staticmethod(lambda *a, **k: _info_calls.append(a) or QMessageBox.Ok)


class _FakeDialog:
    """The dialog seam: records its arguments and accepts with a chosen subset."""

    last = {}

    def __init__(self, hosts, skipped, notes, source, parent=None):
        _FakeDialog.last = {"hosts": list(hosts), "skipped": list(skipped),
                            "notes": list(notes), "source": source}
        self._selected = list(hosts)
        self.accept_on_exec = True

    def exec(self):
        return QDialog.Accepted if self.accept_on_exec else QDialog.Rejected

    def selected_hosts(self):
        return list(self._selected)


try:
    MW.SshConfigImportDialog = _FakeDialog
    mw._import_servers_from_ssh_config()
    app.processEvents()
finally:
    MW.SshConfigImportDialog = _orig_dlg_cls
    QMessageBox.information = _orig_info

_nodes = {n.data.alias: n.data for n in mw.scene.nodes()}
check("§8 the dialog received the config hosts and the file it read",
      _FakeDialog.last["source"] == CONFIG_PATH and len(_FakeDialog.last["hosts"]) == 2,
      f"{_FakeDialog.last.get('source')} / {len(_FakeDialog.last.get('hosts', []))}")
check("§8 a host already on the map is NOT offered again (mapped-1 → the skip report)",
      sorted(h.alias for h in _FakeDialog.last["hosts"]) == ["db-1", "web-1"]
      and any(i.reason == SCI.REASON_DUPLICATE and i.subject == "mapped-1"
              for i in _FakeDialog.last["skipped"]),
      str([(i.subject, i.reason) for i in _FakeDialog.last["skipped"]]))
check("§8 a duplicate INSIDE the config is reported too (dup-1 → same host/port/user as web-1)",
      any(i.reason == SCI.REASON_DUPLICATE and i.subject == "dup-1"
          for i in _FakeDialog.last["skipped"]),
      str([(i.subject, i.reason) for i in _FakeDialog.last["skipped"]]))
check("§8 a wildcard block reaches the dialog as a skip record",
      any(i.reason == SCI.REASON_WILDCARD for i in _FakeDialog.last["skipped"]))
check("§8 the imported node carries host/user/port/key_path of its block",
      _nodes["web-1"].host == "10.0.0.5" and _nodes["web-1"].user == "ubuntu"
      and _nodes["web-1"].ssh_port == 2222 and _nodes["web-1"].key_path.endswith("k1"),
      str(_nodes.get("web-1")))
check("§8 a HostName that is an IP fills the ip field",
      _nodes["web-1"].ip == "10.0.0.5" and _nodes["db-1"].ip == "10.0.0.6",
      str({a: d.ip for a, d in _nodes.items()}))
check("§8 the password of an imported node is empty (the keyring owns secrets)",
      all(d.password == "" for d in _nodes.values()))
check("§8 the whole import is ONE undo command",
      isinstance(mw.undo_stack.command(mw.undo_stack.count() - 1), CmdAddRemoveNodeBatch))
check("§8 the status bar reported the import",
      mw.t("status.servers_imported", count=2) in mw.statusBar().currentMessage(),
      mw.statusBar().currentMessage())
check("§8 the result dialog counted the skipped entries",
      _info_calls and _info_calls[-1][2] == mw.t("msg.import_ssh_config_result",
                                                added=2, skipped=3),
      str(_info_calls[-1:]))

mw._undo()
app.processEvents()
check("§8 Ctrl+Z removes the imported batch at once",
      all(n.data.alias not in ("web-1", "db-1") for n in mw.scene.nodes()),
      str(sorted(n.data.alias for n in mw.scene.nodes())))

# a cancelled dialog imports nothing
_undo_before = mw.undo_stack.count()
_nodes_before = len(mw.scene.nodes())


class _CancelDialog(_FakeDialog):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.accept_on_exec = False


try:
    MW.SshConfigImportDialog = _CancelDialog
    mw._import_servers_from_ssh_config()
    app.processEvents()
finally:
    MW.SshConfigImportDialog = _orig_dlg_cls
check("§8 a cancelled dialog adds nothing and pushes no command",
      len(mw.scene.nodes()) == _nodes_before and mw.undo_stack.count() == _undo_before)

# a missing config: a hint, nothing else
os.remove(CONFIG_PATH)
_info_calls.clear()
QMessageBox.information = staticmethod(lambda *a, **k: _info_calls.append(a) or QMessageBox.Ok)
try:
    mw._import_servers_from_ssh_config()
    app.processEvents()
finally:
    QMessageBox.information = _orig_info
check("§8 a missing ~/.ssh/config shows sshconfig.not_found with the path",
      _info_calls and _info_calls[-1][2] == mw.t("sshconfig.not_found", path=CONFIG_PATH),
      str(_info_calls[-1:]))
check("§8 …and the map is untouched by the failed import",
      len(mw.scene.nodes()) == _nodes_before)

# an empty config (no Host block): the "nothing to import" report
write(CONFIG_PATH, "# nothing here\n")
_info_calls.clear()
QMessageBox.information = staticmethod(lambda *a, **k: _info_calls.append(a) or QMessageBox.Ok)
try:
    mw._import_servers_from_ssh_config()
    app.processEvents()
finally:
    QMessageBox.information = _orig_info
check("§8 an empty config reports zero added and adds nothing",
      _info_calls and _info_calls[-1][2] == mw.t("msg.import_ssh_config_result",
                                                added=0, skipped=0),
      str(_info_calls[-1:]))


# ════════════════════════════════════════════════════════════════════════════
print("== §9 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

from _common import EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS  # noqa: E402

check("§9 the version pin is the version this test file describes",
      EXPECTED_APP_VERSION == "1.6.1", EXPECTED_APP_VERSION)
check("§9 the key pin counts the SHIPPED release (545 + 21 of v1.4.1 + 4 of v1.4.2 + 16 of v1.4.3"
      " — v1.4.4 adds none: motion is behaviour only; v1.4.5 adds 17: the panel/grid UI;"
      " v1.4.6 adds 9: the sidebar.list.* column headers + the minimap title band;"
      " v1.4.7 adds 1: the SFTP viewer's heuristic-highlighting note;"
      " v1.5rc1 adds 3: the Auto mode and the Reduce-motion switch of the Appearance tab;"
      " v1.5rc2 adds 3: the export-options dialog and its two strings; v1.5rc3 adds 11: the demo map, the undo affordance, the freshness line and the first screen; v1.5rc4 adds 13: the settings search, the hotkey filter/counts/families and the toolbar overflow; v1.5rc5 adds NONE: the review batch reuses the existing ssh.* messages; v1.5 adds 1: node.status.emulated, the marker of the demo's emulated statuses; v1.5.1 adds 4: the two map-image actions and their two reports; v1.5.2 adds 13: the chrome of the activity panel; v1.5.3 adds 20: the age of the collected facts, the batch collection and the reachability report; v1.5.4 adds 11: the two group-aggregate captions, the three strings of the problems-only chip and the six of the active-filter plaque; v1.5.5 adds 14: the five inventory columns, the four compact age captions, the two report actions and their three reports; v1.5.6 adds 2: the Export menu and the third first-run door; v1.5.7 adds 29: the "
      "command-history tab, the panel chrome and the six menu items with their reports)",
      EXPECTED_I18N_KEYS == 778, str(EXPECTED_I18N_KEYS))
check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)
for _code in i18n_lang_codes(ROOT):
    _data = json.load(open(os.path.join(ROOT, "i18n", f"{_code}.json"),
                           encoding="utf-8-sig"))
    _keys = translation_keys(_data)
    for _key in ("file.import_ssh_config", "sshconfig.title", "sshconfig.hint",
                 "sshconfig.col_alias", "sshconfig.reason.wildcard",
                 "sshconfig.note.proxy", "sshconfig.not_found",
                 "msg.import_ssh_config_result", "btn.import"):
        check(f"§9 i18n/{_code}.json carries {_key}", _key in _keys)
check("§9 the hint and the result carry their placeholders",
      "{path}" in json.load(open(os.path.join(ROOT, "i18n", "en.json"),
                                 encoding="utf-8-sig"))["sshconfig.hint"]
      and "{detail}" in json.load(open(os.path.join(ROOT, "i18n", "en.json"),
                                       encoding="utf-8-sig"))["sshconfig.reason.include_missing"])

# The documentation guards that used to sit here (the ROADMAP baseline, the released-section
# rule, the changelog entry) are about the DOCUMENTS, not about this importer: they moved to
# tests/test_docs.py §1/§2. A topical test must not read the gitignored docs at all — a fresh
# clone has none of them, so such a check is a crash waiting for the first person without them.

# the window is dirty after the imports — clean it before close, or closeEvent asks
mw._dirty = False
mw._undo_baseline_dirty = False
mw.close()
finish()
