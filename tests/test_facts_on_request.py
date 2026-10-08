# -*- coding: utf-8 -*-
"""v1.6.6 — the measurement you asked for: the status round you start, and the data mount that holds the capacity.

The topical file of the release, and of the device choice that joins the same family: ONE theme — what
the application measures is what the user asked for, asked WHEN (the cadence gains a manual-only state)
and OF THE RIGHT FILESYSTEM (the facts read the data mount beside the root, or the DEVICE the card
names). It is hermetic: the window is built with NO status checker and nothing here opens a socket.
§1 the sentinel `status_interval_sec = 0` and the ONE pure reader `resolve_interval_sec()`; §2 the
checker's live switch and the declared manual horizon; §3 the doors and the words (the load-round guard, the checkbox over the remembered spinbox); §4 the two-mount read (the pure parser and the classifier); §5 the model's four additive strings and the ONE dating write path; §6 the dialog's request/answer row; §7 the card line with `LIST_COLUMNS` untouched; §8 the DEVICE choice (`lsblk -d`, the pure device family, the model pair, the dialog combo and the composed card line); §9 the release state."""
import json
import os
import re
import sys
import time

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, cfg_path, write_cfg, clear_cfg,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS,
                     releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation + offscreen)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import version as _version  # noqa: E402
import services.system_info_collector as SIC  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.main_window as MW  # noqa: E402
from dialogs.add_server_dialog import AddServerDialog  # noqa: E402
from models.server import (ServerData, optional_text, server_data_from_dict,  # noqa: E402
                           server_data_to_dict, sanitize_device_list)
from services.status_checker import (  # noqa: E402
    StatusChecker, get_status_settings, resolve_interval_sec, is_manual_interval,
    MANUAL_INTERVAL_SEC, MANUAL_STALE_SEC, STALE_MIN_SEC, DEFAULT_INTERVAL_SEC,
    MIN_INTERVAL_SEC, MAX_INTERVAL_SEC)
from services.system_info_collector import (  # noqa: E402
    build_info_batch, parse_disk_report, parse_disk_presence, resolve_disk_answer,
    resolve_disk_mount, disk_refusal_kind, disk_refusal_text, is_network_fs, sh_quote,
    parse_info_output,
    INFO_BATCH, DISK_MOUNT_DEFAULT, DISK_MOUNT_TOKEN, NETWORK_FS_TYPES,
    DISK_REFUSAL_MISSING, DISK_REFUSAL_NETWORK, DISK_NOTE_MISSING,
    parse_lsblk_report, physical_disks, device_label, device_labels, resolve_disk_device,
    DISK_TYPE_PHYSICAL, DISK_REFUSAL_DEVICE, DISK_NOTE_DEVICE_MISSING)
from ui.settings_dialog import SettingsDialog  # noqa: E402
from ui import sidebar as SB  # noqa: E402

# ── The harness: no modal box may ever block an offscreen run ────────────────
BOXES = []
MW.QMessageBox.critical = staticmethod(lambda *a, **k: BOXES.append(("critical", a)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: BOXES.append(("warning", a)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: BOXES.append(("information", a)))

LANGS = load_i18n_langs(ROOT)

# The eleven keys of the release — the ONE list the i18n section iterates.
NEW_KEYS = (
    "settings.statuses.manual_only", "settings.statuses.manual_only.hint",
    "server.disk_mount", "server.disk_mount_hint", "server.disk_path_hint",
    "server.disk_free_hint", "server.disk_size_hint", "server.disk_mount_tooltip",
    "node.disk_mount",
    "status.disk_mount_network", "status.disk_mount_missing",
)

# The four keys of the DEVICE choice (§8) — the ONE list the second i18n block iterates.
DEVICE_KEYS = (
    "server.disk_device_hint", "server.disk_device_tooltip",
    "node.disk_devices", "status.disk_device_missing",
)

# The colleagues' two measured hosts (the ROADMAP's own numbers): the root is 9.8 G on BOTH,
# while `/opt` (an LVM logical volume, `/dev/mapper/optvg-optlv`, ext4) carries 59 G with 48 G
# free on one and 79 G with 45 G free on the other.
_DF_HEADER = "Filesystem Type 1B-blocks Avail Mounted on"
# 9.8 G of capacity and 4.5 G free — the ROADMAP's own root figure (bytes_to_gb → "9.8 gb").
_ROOT_ROW = "/dev/mapper/rootvg-rootlv ext4 10522669875 4831838208 /"
_HOST_A_ROW = "/dev/mapper/optvg-optlv ext4 63350767616 51539607552 /opt"
_HOST_B_ROW = "/dev/mapper/optvg-optlv ext4 84825604096 48318382080 /opt"


def disk_output(rows, present="present"):
    """A collection output carrying ONE disk report (the v1.6.6 shape)."""
    return "\n".join(["---DISK---"] + rows + ["---DISKMOUNT---", present, "---END---"])


def make_main(checker=None):
    """An offscreen MainWindow that opens no socket (the test_first_run pattern)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = checker
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


class RoundRecorder(StatusChecker):
    """A checker that RECORDS a round instead of starting a probe thread.

    Everything the window asks of a checker is the real implementation — only `start_round()`
    is replaced, so the load-round guard is measured without a single socket.
    """

    def __init__(self, interval_ms=30_000):
        super().__init__(interval_ms=interval_ms)
        self.rounds = []

    def start_round(self, server_ids=None):
        self.rounds.append(server_ids)
        return True


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the sentinel and its reader (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the sentinel is the DECLARED zero (one setting keeps one home, no second key)",
      MANUAL_INTERVAL_SEC == 0 and is_manual_interval(0) is True,
      str(MANUAL_INTERVAL_SEC))
check("§1 exactly 0 selects the manual mode",
      resolve_interval_sec(0) == 0 and resolve_interval_sec("0") == 0
      and resolve_interval_sec(0.0) == 0,
      str([resolve_interval_sec(0), resolve_interval_sec("0"), resolve_interval_sec(0.0)]))
check("§1 ... and the reader answers 0 for nothing else",
      all(resolve_interval_sec(v) != 0 for v in (1, 0.4, -1, 5, "abc", None, True, "", [], {}, 86400)),
      str([resolve_interval_sec(v) for v in (1, 0.4, -1, 5, "abc", None, True, "", [], {}, 86400)]))
check("§1 a MISSING value is the default interval, never the sentinel",
      resolve_interval_sec(None) == DEFAULT_INTERVAL_SEC == 30,
      str(resolve_interval_sec(None)))
check("§1 a non-numeric / boolean value is the default too (the _num pattern)",
      resolve_interval_sec("abc") == 30 and resolve_interval_sec(True) == 30
      and resolve_interval_sec(False) == 30 and resolve_interval_sec([]) == 30,
      str([resolve_interval_sec("abc"), resolve_interval_sec(True), resolve_interval_sec([])]))
check("§1 NaN / ±inf are the default (never a mode change)",
      resolve_interval_sec(float("nan")) == 30
      and resolve_interval_sec(float("inf")) == 30
      and resolve_interval_sec(float("-inf")) == 30)
check("§1 the clamp is untouched for every other number",
      resolve_interval_sec(1) == MIN_INTERVAL_SEC == 5
      and resolve_interval_sec(45) == 45
      and resolve_interval_sec(10 ** 9) == MAX_INTERVAL_SEC == 86400,
      str([resolve_interval_sec(1), resolve_interval_sec(45), resolve_interval_sec(10 ** 9)]))
check("§1 a NEGATIVE number is an out-of-range interval, not a way into the manual mode",
      resolve_interval_sec(-7) == 5 and is_manual_interval(resolve_interval_sec(-7)) is False,
      str(resolve_interval_sec(-7)))
check("§1 is_manual_interval() is total (a foreign value is not manual)",
      is_manual_interval(None) is False and is_manual_interval("x") is False
      and is_manual_interval(0) is True and is_manual_interval(30) is False)

clear_cfg()
st = get_status_settings()
check("§1 get_status_settings() answers the RESOLVED PAIR beside the two clamps",
      st == {"interval_sec": 30, "manual": False, "probe_timeout_sec": 3.0, "max_parallel": 16},
      str(st))
write_cfg({"status_interval_sec": MANUAL_INTERVAL_SEC})
st = get_status_settings()
check("§1 ... the pair says manual when the key holds the sentinel",
      st["interval_sec"] == 0 and st["manual"] is True, str(st))
check("§1 ... and the manual flag is DERIVED, never a second config key",
      "manual" not in (json.load(open(cfg_path(), encoding="utf-8")) or {}))
write_cfg({"status_interval_sec": -3})
check("§1 ... a negative value still reads as a clamped REAL interval",
      get_status_settings()["interval_sec"] == 5 and get_status_settings()["manual"] is False)
clear_cfg()


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the checker's live switch (task 2) ==")
# ════════════════════════════════════════════════════════════════════════════

chk = StatusChecker(interval_ms=30_000, probe_timeout=0.2)
check("§2 a fresh checker is NOT manual (the mode is opt-in)", chk.manual_only is False)

chk.set_manual_only(True)
check("§2 switching the mode ON before start() arms nothing", chk._timer.isActive() is False
      and chk.manual_only is True)
chk.start()
check("§2 start() in the manual mode arms NO timer",
      chk._timer.isActive() is False and chk._enabled is True)
_fired = []
chk.start_round = lambda *a, **k: _fired.append(a) or True
chk._deferred_first_round()
check("§2 ... and the deferred first round is NEUTRALISED when it fires",
      _fired == [], str(_fired))

chk.set_manual_only(False)
check("§2 switching it OFF resumes the periodic rounds the window had enabled",
      chk._timer.isActive() is True and chk.manual_only is False)
chk.start_round = lambda *a, **k: _fired.append(a) or True
chk._deferred_first_round()
check("§2 ... and the same slot really starts a round when the mode is off",
      _fired == [()], str(_fired))
chk.set_manual_only(True)
check("§2 switching it back ON stops the running timer IMMEDIATELY",
      chk._timer.isActive() is False and chk.manual_only is True)
chk.set_manual_only(True)
check("§2 the switch is idempotent (a second ON changes nothing)",
      chk.manual_only is True and chk._timer.isActive() is False)

chk2 = StatusChecker(interval_ms=30_000)
chk2.set_manual_only(True)
check("§2 a stopped checker is NOT resumed by switching the mode OFF (stop() wins)",
      chk2.stop() is None and chk2.set_manual_only(False) is None
      and chk2._timer.isActive() is False,
      str(chk2._timer.isActive()))
chk2.set_manual_only(True)
chk2.shutdown()
chk.shutdown()

chk3 = StatusChecker(interval_ms=30_000)
check("§2 the AUTOMATIC horizon is unchanged: max(2 × interval, 90 s)",
      chk3.stale_threshold_s() == STALE_MIN_SEC == 90.0, str(chk3.stale_threshold_s()))
chk3.set_manual_only(True)
check("§2 the MANUAL horizon is the DECLARED day (there are no rounds to miss)",
      chk3.stale_threshold_s() == MANUAL_STALE_SEC == 86400.0,
      str(chk3.stale_threshold_s()))
check("§2 ... and it is LONGER than the automatic one (the promise of the mode)",
      MANUAL_STALE_SEC > STALE_MIN_SEC)
_now = time.time()
chk3._last_times["s1"] = _now - 90000.0        # 25 h — older than the declared day
check("§2 a 25-hour-old manual result IS stale",
      chk3.is_stale("s1", now=_now) is True)
chk3._last_times["s2"] = _now - 3600.0         # 1 h — younger than the declared day
check("§2 ... and a one-hour-old one is NOT (the horizon is a day, not the 90 s of the auto mode)",
      chk3.is_stale("s2", now=_now) is False)
_auto = StatusChecker(interval_ms=30_000)
_auto._last_times["s2"] = _now - 3600.0
check("§2 ... while the AUTOMATIC mode marks the very same datum stale (the horizon is the mode's)",
      _auto.is_stale("s2", now=_now) is True)
check("§2 a never-probed id is stale in NEITHER mode (it has no datum to age)",
      chk3.is_stale("never", now=_now) is False and _auto.is_stale("never", now=_now) is False)
chk3.set_manual_only(False)
check("§2 leaving the mode gives the automatic horizon back",
      chk3.stale_threshold_s() == STALE_MIN_SEC)
_auto.shutdown()
chk3.shutdown()

chk4 = StatusChecker(interval_ms=30_000)
chk4.set_servers([("a", "10.0.0.1", 22), ("b", "10.0.0.2", 22)])
chk4.set_manual_only(True)
check("§2 the MANUAL doors are untouched: the target plan and _subset() are the same",
      chk4.target_count == 2 and [t[0] for t in chk4._subset()] == ["a", "b"]
      and [t[0] for t in chk4._subset(["b"])] == ["b"],
      str(chk4._subset()))
check("§2 ... the skip set still filters them, and last_status() still answers",
      (chk4.set_skip_ids(["a"]) or True)
      and [t[0] for t in chk4._subset()] == ["b"]
      and chk4.last_status("nope") == "")
chk4.set_skip_ids([])
check("§2 ... and a manual round is refused for an EMPTY selection, exactly as before",
      chk4.start_round([]) is False and chk4.is_busy is False)
chk4.shutdown()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the doors and the words (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

_rec = RoundRecorder()
win = make_main(checker=_rec)
win.scene.add_server(ServerData(id="n1", alias="web-1", host="10.4.0.1", user="root"))
ok = win._load_project_at("", skip_autosave_prompt=True, raw={
    "version": "0.9", "servers": [{"id": "n1", "alias": "web-1", "host": "10.4.0.1", "user": "root"}]})
check("§3 a project load opens normally with a checker installed", ok is True, str(ok))
check("§3 ... and the AUTOMATIC mode starts the load round exactly as before",
      _rec.rounds == [None], str(_rec.rounds))

_rec.rounds = []
_rec.set_manual_only(True)
ok = win._load_project_at("", skip_autosave_prompt=True, raw={
    "version": "0.9", "servers": [{"id": "n1", "alias": "web-1", "host": "10.4.0.1", "user": "root"}]})
check("§3 opening a project in the MANUAL mode loads it", ok is True, str(ok))
check("§3 ... and starts NO round (File → Open is not 'check my servers now')",
      _rec.rounds == [] and _rec.is_busy is False, str(_rec.rounds))
check("§3 the guard is the checker's OWN predicate (one fact, one home)",
      _rec.manual_only is True
      and "manual_only" in open(os.path.join(ROOT, "ui", "main_window_project_io.py"),
                                encoding="utf-8").read())
_rec.rounds = []
_rec.start_round(["n1"])
check("§3 ... while the manual door still probes on request",
      _rec.rounds == [["n1"]], str(_rec.rounds))

# The LIVE application: `_apply_settings_from_dialog()` reads the resolved pair back and installs it.
_rec.set_manual_only(False)
_rec.rounds = []
_rec.start()                       # the app's own launch path (main.py → start_status_checks)
check("§3 start() arms the periodic timer in the automatic mode",
      _rec._timer.isActive() is True and _rec.manual_only is False)
write_cfg({"status_interval_sec": MANUAL_INTERVAL_SEC})
win._apply_settings_from_dialog()
check("§3 the config holding the sentinel is applied LIVE — the run stops at once",
      _rec.manual_only is True and _rec._timer.isActive() is False,
      str(_rec.manual_only))
_rec.rounds = []
ok = win._load_project_at("", skip_autosave_prompt=True, raw={
    "version": "0.9", "servers": [{"id": "n1", "alias": "web-1", "host": "10.4.0.1", "user": "root"}]})
check("§3 ... and after that live switch a project load probes NOTHING",
      ok is True and _rec.rounds == [], str(_rec.rounds))
write_cfg({"status_interval_sec": 45})
win._apply_settings_from_dialog()
check("§3 a real interval applied live resumes the rounds (no restart needed)",
      _rec.manual_only is False and _rec._timer.isActive() is True
      and _rec.interval_ms == 45000,
      f"manual={_rec.manual_only} active={_rec._timer.isActive()} ms={_rec.interval_ms}")
clear_cfg()
win._dirty = False
win.close()
app.processEvents()

# The "Status Checks" tab: the checkbox over the REMEMBERED, DISABLED spinbox.
clear_cfg()
dlg = SettingsDialog(None)
check("§3 the tab carries the manual-only checkbox, OFF by default",
      dlg.manual_only_chk.isChecked() is False and dlg.status_interval_spin.isEnabled() is True)
check("§3 ... and the sentence explaining the mode is hidden while it is off",
      dlg.manual_only_hint.isHidden() is True)
dlg.manual_only_chk.setChecked(True)
check("§3 ticking it DISABLES the interval spinbox and keeps its value (remembered, never zeroed)",
      dlg.status_interval_spin.isEnabled() is False
      and dlg.status_interval_spin.value() == 30,
      str(dlg.status_interval_spin.value()))
check("§3 ... and shows the sentence that spells the mode out",
      dlg.manual_only_hint.isHidden() is False)
check("§3 collect() writes the DECLARED sentinel for the manual mode",
      dlg.collect()["status_interval_sec"] == MANUAL_INTERVAL_SEC == 0,
      str(dlg.collect()["status_interval_sec"]))
dlg.manual_only_chk.setChecked(False)
check("§3 un-ticking gives the user their number back and writes it again",
      dlg.status_interval_spin.isEnabled() is True
      and dlg.collect()["status_interval_sec"] == 30,
      str(dlg.collect()["status_interval_sec"]))
dlg.close()
write_cfg({"status_interval_sec": 0})
dlg2 = SettingsDialog(None)
check("§3 a config holding the sentinel opens the tab in the manual state",
      dlg2.manual_only_chk.isChecked() is True
      and dlg2.status_interval_spin.isEnabled() is False
      and dlg2.collect()["status_interval_sec"] == 0)
write_cfg({"status_interval_sec": 45})
dlg3 = SettingsDialog(None)
check("§3 a config holding a real interval opens it OFF, with that interval",
      dlg3.manual_only_chk.isChecked() is False and dlg3.status_interval_spin.value() == 45
      and dlg3.collect()["status_interval_sec"] == 45)
dlg2.close()
dlg3.close()
clear_cfg()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the two-mount read (task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the request has ONE home and a DECLARED default",
      DISK_MOUNT_DEFAULT == "/opt" and resolve_disk_mount("") == "/opt"
      and resolve_disk_mount("   ") == "/opt" and resolve_disk_mount(None) == "/opt"
      and resolve_disk_mount(" /data ") == "/data",
      str([resolve_disk_mount(""), resolve_disk_mount(" /data ")]))
check("§4 the path is QUOTED into the command, never interpolated bare",
      sh_quote("/opt") == "'/opt'" and sh_quote("/o'pt") == "'/o'\\''pt'"
      and sh_quote(None) == "''",
      sh_quote("/o'pt"))

_batch = build_info_batch("")
check("§4 the batch carries the requested mount THREE times (the df argument, the test and df -i)",
      _batch.count("'/opt'") == 3 and DISK_MOUNT_TOKEN not in _batch,
      str(_batch.count("'/opt'")))
_batch2 = build_info_batch("/data/opt'x")
check("§4 ... quoted as ONE shell word even when the path holds a quote",
      _batch2.count("'/data/opt'\\''x'") == 3 and "'/opt'" not in _batch2)
check("§4 the module constant stays a usable template (the markers are pinned)",
      all(m in INFO_BATCH for m in ("---OS---", "---CPU---", "---RAM---", "---DISK---",
                                    "---END---", DISK_MOUNT_TOKEN)))

check("§4 the classifier is DECLARED and named",
      NETWORK_FS_TYPES == ("nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs")
      and is_network_fs("NFS4") is True and is_network_fs(" cifs ") is True
      and is_network_fs("ext4") is False and is_network_fs("") is False
      and is_network_fs(None) is False,
      str(NETWORK_FS_TYPES))

_rows_a = parse_disk_report("\n".join([_DF_HEADER, _ROOT_ROW, _HOST_A_ROW]))
_rows_b = parse_disk_report("\n".join([_DF_HEADER, _ROOT_ROW, _HOST_B_ROW]))
check("§4 the parser splits the report into rows (source, fstype, size, avail, target)",
      _rows_a == [("/dev/mapper/rootvg-rootlv", "ext4", 10522669875, 4831838208, "/"),
                  ("/dev/mapper/optvg-optlv", "ext4", 63350767616, 51539607552, "/opt")],
      str(_rows_a))
check("§4 ... the header line is dropped, never read as a row",
      all(r[1] != "Type" for r in _rows_a) and len(_rows_a) == 2)
check("§4 ... and a df that refuses --output prints nothing (no crash, no row)",
      parse_disk_report("") == [] and parse_disk_report("df: invalid option") == []
      and parse_disk_report("---DISK---\n---END---") == [])
check("§4 a mount point with a space survives the split",
      parse_disk_report(_DF_HEADER + "\n/dev/sdb1 xfs 10 5 /media/My Data\n")
      == [("/dev/sdb1", "xfs", 10, 5, "/media/My Data")])

check("§4 the colleague's FIRST host: /opt answers 59 gb with 48 gb free",
      resolve_disk_answer(_rows_a) == {"path": "/opt", "free": "48 gb", "size": "59 gb",
                                       "note": ""},
      str(resolve_disk_answer(_rows_a)))
check("§4 the colleague's SECOND host: /opt answers 79 gb with 45 gb free",
      resolve_disk_answer(_rows_b) == {"path": "/opt", "free": "45 gb", "size": "79 gb",
                                       "note": ""},
      str(resolve_disk_answer(_rows_b)))
check("§4 the ANSWER is the mount point df reported, never the typed request",
      resolve_disk_answer(parse_disk_report("\n".join([_DF_HEADER, _ROOT_ROW])))["path"] == "/",
      str(resolve_disk_answer(parse_disk_report("\n".join([_DF_HEADER, _ROOT_ROW])))))
check("§4 a requested path that does NOT exist measures nothing (and says so)",
      resolve_disk_answer(_rows_a, present=False)
      == {"path": "", "free": "", "size": "", "note": DISK_NOTE_MISSING}
      and disk_refusal_kind(DISK_NOTE_MISSING) == DISK_REFUSAL_MISSING,
      str(resolve_disk_answer(_rows_a, present=False)))
check("§4 a report with no usable row at all is a refusal, not an error",
      resolve_disk_answer([])["note"] == DISK_NOTE_MISSING
      and resolve_disk_answer([("x", "ext4", 1, 1, "/opt")], present=False)["path"] == "")

_cifs_rows = parse_disk_report(
    "\n".join([_DF_HEADER, _ROOT_ROW, "//srv/share cifs 2199023255552 1099511627776 /opt"]))
check("§4 a cifs mount is REFUSED BY NAME and no figure is written for it",
      resolve_disk_answer(_cifs_rows)
      == {"path": "", "free": "", "size": "", "note": "cifs"}
      and disk_refusal_kind("cifs") == DISK_REFUSAL_NETWORK,
      str(resolve_disk_answer(_cifs_rows)))
_sshfs_rows = parse_disk_report(
    "\n".join([_DF_HEADER, _ROOT_ROW, "u@h:/data fuse.sshfs 1099511627776 1099511627776 /opt"]))
check("§4 a fuse.sshfs mount is refused too (a mounted share is not local disk)",
      resolve_disk_answer(_sshfs_rows)["note"] == "fuse.sshfs"
      and resolve_disk_answer(_sshfs_rows)["free"] == ""
      and disk_refusal_kind("fuse.sshfs") == DISK_REFUSAL_NETWORK)
check("§4 ... and an nfs4 mount follows the same declared rule",
      resolve_disk_answer(parse_disk_report(
          "\n".join([_DF_HEADER, _ROOT_ROW, "srv:/e nfs4 100 50 /opt"])))["note"] == "nfs4")
check("§4 disk_refusal_kind() is total and NAMES nothing it does not know",
      disk_refusal_kind("") == "" and disk_refusal_kind(None) == ""
      and disk_refusal_kind("btrfs") == "" and disk_refusal_kind("missing") == "missing")
# N35 — the ONE composer both surfaces read (the status line and the card's durable tooltip).
_note_t = lambda k, **kw: LANGS["en"][k].format(**kw)   # noqa: E731 — the shipped en wording
check("§4 N35 disk_refusal_text() composes the shipped sentence for every refusal kind",
      disk_refusal_text(_note_t, DISK_NOTE_MISSING, "web-1", mount="/opt")
      == LANGS["en"]["status.disk_mount_missing"].format(mount="/opt", alias="web-1")
      and disk_refusal_text(_note_t, "cifs", "web-1", mount="/opt")
      == LANGS["en"]["status.disk_mount_network"].format(mount="/opt", alias="web-1", type="cifs")
      and disk_refusal_text(_note_t, DISK_NOTE_DEVICE_MISSING, "web-1", device="sdb")
      == LANGS["en"]["status.disk_device_missing"].format(device="sdb", alias="web-1"),
      str(disk_refusal_text(_note_t, "cifs", "web-1", mount="/opt")))
check("§4 N35 ...and answers '' for a note that is no refusal (a measured mount)",
      disk_refusal_text(_note_t, "", "web-1", mount="/opt") == ""
      and disk_refusal_text(_note_t, None, "web-1", mount="/opt") == ""
      and disk_refusal_text(_note_t, "ext4", "web-1", mount="/opt") == "")

check("§4 the shell's own existence token decides the missing case",
      parse_disk_presence("present") is True and parse_disk_presence("absent") is False)
check("§4 a section without a token is assumed PRESENT (a measurement is never turned into a refusal)",
      parse_disk_presence("") is True and parse_disk_presence("junk") is True)

_info_a = parse_info_output(disk_output([_DF_HEADER, _ROOT_ROW, _HOST_A_ROW]))
check("§4 the whole batch output yields the ROOT figure and the DATA-mount pair",
      _info_a["disk_gb"] == "9.8 gb" and _info_a["disk_path"] == "/opt"
      and _info_a["disk_free"] == "48 gb" and _info_a["disk_size"] == "59 gb"
      and _info_a["disk_note"] == "",
      str(_info_a))
def _disk_key(text):
    return SB.list_sort_key("disk", ServerData(id="k", alias="a", host="h", user="u",
                                               disk=text))


check("§4 the root keeps the figure it ships (the inventory's sort key still parses it)",
      _info_a["disk_gb"] == "9.8 gb"
      and _disk_key("512 mb") < _disk_key("9.8 gb") < _disk_key("59 gb"),
      str([_disk_key("512 mb"), _disk_key("9.8 gb"), _disk_key("59 gb")]))
_info_cifs = parse_info_output(
    disk_output([_DF_HEADER, _ROOT_ROW, "//srv/share cifs 2199023255552 1099511627776 /opt"]))
check("§4 a refused share still reports the ROOT and leaves the pair EMPTY",
      _info_cifs["disk_gb"] == "9.8 gb" and _info_cifs["disk_path"] == ""
      and _info_cifs["disk_free"] == "" and _info_cifs["disk_size"] == ""
      and _info_cifs["disk_note"] == "cifs",
      str(_info_cifs))
_info_missing = parse_info_output(disk_output([_DF_HEADER, _ROOT_ROW], present="absent"))
check("§4 an absent path is reported as missing, with no figure",
      _info_missing["disk_note"] == DISK_NOTE_MISSING and _info_missing["disk_path"] == ""
      and _info_missing["disk_free"] == "")
_legacy = parse_info_output('---DISK---\n107374182400\n---END---\n')
check("§4 an old-style (single number) report still answers the root alone",
      _legacy.get("disk_gb") == "100 gb" and "disk_note" not in _legacy
      and "disk_path" not in _legacy,
      str(_legacy))
check("§4 ... so a host that cannot report a data mount is never 'measured'",
      "disk_mount" not in _legacy and "disk_free" not in _legacy)

_collector = SIC.SystemInfoCollector(ServerData(id="c1", alias="a", host="h", user="u",
                                               disk_mount="/data"))
check("§4 the collector builds its batch from the NODE's own request",
      "'/data'" in build_info_batch(getattr(_collector.data, "disk_mount", ""))
      and build_info_batch("").count("'/opt'") == 3)
check("§4 the collector names the refusal in its own report (the activity history's half)",
      callable(getattr(_collector, "_log_disk_note", None))
      and _collector._log_disk_note({"disk_note": "cifs"}) is None
      and _collector._log_disk_note({"disk_note": ""}) is None)


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the model (task 5) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 the four optional strings exist with the declared defaults",
      all(getattr(ServerData(id="x", alias="a", host="h", user="u"), f) == ""
          for f in ("disk_mount", "disk_path", "disk_free", "disk_size")))
check("§5 optional_text() is the ONE coercion rule (a foreign value is not stringified)",
      optional_text(" /opt ") == "/opt" and optional_text(None) == ""
      and optional_text(22) == "" and optional_text(True) == ""
      and optional_text(["a"]) == "" and optional_text({"a": 1}) == "",
      repr([optional_text(" /opt "), optional_text(22), optional_text(True)]))
_bad = server_data_from_dict({"id": "bad", "alias": "a", "host": "h", "user": "u",
                              "disk_mount": " /opt ", "disk_path": 12,
                              "disk_free": None, "disk_size": ["x"]})
check("§5 a hand-edited junk value degrades to '' ('never measured')",
      _bad.disk_mount == "/opt" and _bad.disk_path == "" and _bad.disk_free == ""
      and _bad.disk_size == "", str(_bad))
_old = server_data_from_dict({"id": "old", "alias": "a", "host": "h", "user": "u"})
check("§5 a project written before the release loads as NEVER MEASURED",
      _old.disk_mount == "" and _old.disk_path == "" and _old.disk_free == ""
      and _old.disk_size == "")
_meas = server_data_from_dict({"id": "m", "alias": "a", "host": "h", "user": "u",
                               "disk_mount": "/opt", "disk_path": "/opt",
                               "disk_free": "48 gb", "disk_size": "59 gb"})
check("§5 the measured set round-trips through save → load byte for byte",
      server_data_from_dict(server_data_to_dict(_meas)).disk_path == "/opt"
      and server_data_from_dict(server_data_to_dict(_meas)).disk_free == "48 gb"
      and server_data_from_dict(server_data_to_dict(_meas)).disk_size == "59 gb")
check("§5 an unmeasured map writes the REQUEST but NO answer key (nothing is claimed)",
      server_data_to_dict(_old)["disk_mount"] == ""
      and "disk_path" not in server_data_to_dict(_old)
      and "disk_free" not in server_data_to_dict(_old)
      and "disk_size" not in server_data_to_dict(_old),
      str(sorted(server_data_to_dict(_old))))
check("§5 a measured map writes all four",
      all(k in server_data_to_dict(_meas)
          for k in ("disk_mount", "disk_path", "disk_free", "disk_size")))
check("§5 the schema does NOT move (an optional field with a default is not a change)",
      _version.VERSION_FORMAT == "0.9")
# N35 — the two refusal NOTES have a HOME in the model.
check("§5 N35 the two note fields exist with the declared default",
      ServerData(id="x", alias="a", host="h", user="u").disk_note == ""
      and ServerData(id="x", alias="a", host="h", user="u").disk_device_note == "")
_note_meas = server_data_from_dict({"id": "nm", "alias": "a", "host": "h", "user": "u",
                                    "disk_note": " cifs ", "disk_device_note": 22})
check("§5 N35 a note round-trips and a foreign value degrades to ''",
      _note_meas.disk_note == "cifs" and _note_meas.disk_device_note == ""
      and server_data_from_dict(server_data_to_dict(_note_meas)).disk_note == "cifs")
check("§5 N35 a card with NO refusal writes no note key (nothing is claimed)",
      "disk_note" not in server_data_to_dict(_meas)
      and "disk_device_note" not in server_data_to_dict(_meas)
      and server_data_to_dict(_note_meas)["disk_note"] == "cifs")

_rec2 = RoundRecorder()
win2 = make_main(checker=_rec2)
win2.scene.add_server(ServerData(id="n1", alias="web-1", host="10.4.0.1", user="root"))
_node = win2.scene.get_node("n1")
check("§5 the ONE write path takes the measured pair and DATING them together",
      win2._apply_info_result("n1", {"disk_gb": "9.8 gb", "disk_path": "/opt",
                                     "disk_free": "48 gb", "disk_size": "59 gb",
                                     "disk_note": ""}) is True
      and _node.data.disk_path == "/opt" and _node.data.disk_free == "48 gb"
      and _node.data.disk_size == "59 gb" and _node.data.info_collected_at > 0,
      str(_node.data.info_collected_at))
check("§5 the measured line reaches the CARD through that one write",
      "48 gb" in _node._info.toPlainText(), _node._info.toPlainText())
check("§5 a REFUSED mount CLEARS the pair (never a stale figure beside a new request)",
      win2._apply_info_result("n1", {"disk_gb": "9.8 gb", "disk_path": "", "disk_free": "",
                                     "disk_size": "", "disk_note": "cifs"}) is True
      and _node.data.disk_path == "" and _node.data.disk_free == ""
      and _node.data.disk_size == "")
check("§5 ... and the refusal is REPORTED (the status bar carries the sentence)",
      "cifs" in win2.statusBar().currentMessage()
      and "web-1" in win2.statusBar().currentMessage(),
      win2.statusBar().currentMessage())
check("§5 a collection silent about a data mount leaves the pair ALONE",
      win2._apply_info_result("n1", {"disk_path": "/opt", "disk_free": "48 gb",
                                     "disk_size": "59 gb"}) is True
      and win2._apply_info_result("n1", {"os_name": "Debian GNU/Linux 12"}) is True
      and _node.data.disk_path == "/opt" and _node.data.disk_free == "48 gb",
      str((_node.data.disk_path, _node.data.disk_free)))
check("§5 a node that vanished during the collection writes nothing (and dates nothing)",
      win2._apply_info_result("nope", {"disk_path": "/opt", "disk_free": "1 gb"}) is False)
check("§5 N34 a `disk_gb` KEY answers the root — an explicit '' CLEARS a figure collected earlier",
      win2._apply_info_result("n1", {"disk_gb": "9.8 gb"}) is True
      and _node.data.disk == "9.8 gb"
      and win2._apply_info_result("n1", {"disk_gb": ""}) is True
      and _node.data.disk == "",
      str(_node.data.disk))
check("§5 N34 ...while a collection with NO `disk_gb` key at all leaves the figure where it is",
      win2._apply_info_result("n1", {"disk_gb": "9.8 gb"}) is True
      and win2._apply_info_result("n1", {"os_name": "Debian GNU/Linux 12"}) is True
      and _node.data.disk == "9.8 gb",
      str(_node.data.disk))
check("§5 the missing-path refusal has its own sentence",
      win2._apply_info_result("n1", {"disk_path": "", "disk_free": "", "disk_size": "",
                                     "disk_note": DISK_NOTE_MISSING}) is True
      and "not found" in win2.statusBar().currentMessage(),
      win2.statusBar().currentMessage())
win2._dirty = False
win2.close()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the dialog (task 6) ==")
# ════════════════════════════════════════════════════════════════════════════

dlg4 = AddServerDialog()
check("§6 the dialog carries the data-mount row (the request + the measured answer)",
      all(hasattr(dlg4, f) for f in ("disk_mount", "disk_path", "disk_free", "disk_size",
                                     "disk_mount_row", "_disk_arrow")))
check("§6 the request field names the DECLARED default as its placeholder",
      dlg4.disk_mount.placeholderText() == LANGS["en"]["server.disk_mount_hint"]
      and "/opt" in dlg4.disk_mount.placeholderText()
      and dlg4.disk_mount.text() == "",
      repr(dlg4.disk_mount.placeholderText()))
check("§6 a NEW card measures nothing (all four fields start empty)",
      all(getattr(dlg4, f).text() == ""
          for f in ("disk_mount", "disk_path", "disk_free", "disk_size")))
_new_data = dlg4.get_data()
check("§6 get_data() passes the four fields into the model",
      _new_data.disk_mount == "" and _new_data.disk_path == ""
      and _new_data.disk_free == "" and _new_data.disk_size == "")
dlg4.close()

_edit = ServerData(id="e1", alias="data-1", host="10.4.0.9", user="root",
                   disk_mount="/opt", disk_path="/opt", disk_free="48 gb", disk_size="59 gb")
dlg5 = AddServerDialog(edit_data=_edit)
check("§6 an EDIT loads the request and the measured answer into their own fields",
      dlg5.disk_mount.text() == "/opt" and dlg5.disk_path.text() == "/opt"
      and dlg5.disk_free.text() == "48 gb" and dlg5.disk_size.text() == "59 gb",
      str((dlg5.disk_mount.text(), dlg5.disk_path.text(), dlg5.disk_free.text())))
check("§6 ... and the values stay EDITABLE (the ram / disk precedent)",
      dlg5.disk_path.isEnabled() and dlg5.disk_free.isEnabled()
      and dlg5.disk_size.isEnabled())
dlg5.disk_mount.setText("/data")
dlg5.disk_free.setText("10 gb")
_round_trip = dlg5.get_data()
check("§6 ... and an edit of them round-trips through the dialog",
      _round_trip.disk_mount == "/data" and _round_trip.disk_free == "10 gb"
      and _round_trip.disk_path == "/opt" and _round_trip.disk_size == "59 gb")
dlg5.close()

_refused = ServerData(id="e2", alias="data-2", host="10.4.0.10", user="root",
                      disk_mount="/opt", disk_path="", disk_free="", disk_size="")
dlg6 = AddServerDialog(edit_data=_refused)
check("§6 a REFUSED mount leaves the measured fields EMPTY",
      dlg6.disk_mount.text() == "/opt"
      and dlg6.disk_path.text() == "" and dlg6.disk_free.text() == ""
      and dlg6.disk_size.text() == "",
      str((dlg6.disk_path.text(), dlg6.disk_free.text(), dlg6.disk_size.text())))
check("§6 ... so the dialog shows exactly what was measured and never a declined figure",
      dlg6.get_data().disk_path == "" and dlg6.get_data().disk_free == "")
dlg6.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the card and the table (task 7) ==")
# ════════════════════════════════════════════════════════════════════════════

from graphics.server_node import ServerNode  # noqa: E402
from ui import theme  # noqa: E402

_bare = ServerNode(ServerData(id="c-bare", alias="bare", host="10.0.0.1", user="u",
                              os_name="Ubuntu 24.04 LTS", cpu="4 core", ram="16 gb",
                              disk="9.8 gb"))
_with = ServerNode(ServerData(id="c-with", alias="bare", host="10.0.0.1", user="u",
                              os_name="Ubuntu 24.04 LTS", cpu="4 core", ram="16 gb",
                              disk="9.8 gb", disk_mount="/opt", disk_path="/opt",
                              disk_free="48 gb", disk_size="59 gb"))
_bare.update_appearance()
_with.update_appearance()
check("§7 the card builds ONE more info line from the measured pair",
      "DISK /opt: 48 gb free of 59 gb" in _with._info_tip_full
      and "DISK /opt" in _with._info.toPlainText(),
      (_with._info_tip_full or _with._info.toPlainText()).replace("\n", " | "))
check("§7 ... ELIDED on the card, the FULL line in its tooltip",
      _with._info.toPlainText().count("DISK /opt") == 1
      and "DISK /opt: 48 gb free of 59 gb" in _with._info.toolTip(),
      _with._info.toolTip().replace("\n", " | "))
check("§7 ... and a card with no measurement writes none of it",
      "DISK /opt" not in _bare._info.toPlainText()
      and "59 gb" not in _bare._info.toPlainText(),
      _bare._info.toPlainText().replace("\n", " | "))
check("§7 the measured HEIGHT formula follows the line count exactly (58 + info + 12)",
      _with._current_height > _bare._current_height
      and _with._current_height - _bare._current_height
      == int(_with._info.boundingRect().height() - _bare._info.boundingRect().height()),
      f"{_bare._current_height} -> {_with._current_height}")
check("§7 the root's DISK line keeps its own figure beside the data mount",
      "DISK: 9.8 gb" in _with._info.toPlainText())

theme.set_card_density(theme.DENSITY_COMPACT)
try:
    _bare.refresh_theme()
    _with.refresh_theme()
    app.processEvents()
    check("§7 the COMPACT density drops it with the rest of the block",
          _with._info.isVisible() is False and _with.density() == theme.DENSITY_COMPACT,
          f"density={_with.density()} info_visible={_with._info.isVisible()}")
finally:
    theme.set_card_density(theme.DENSITY_NORMAL)
    _bare.refresh_theme()
    _with.refresh_theme()
    app.processEvents()
check("§7 back in the ordinary density the line is there again (a density, not a state)",
      _with._info.isVisible() is True and "DISK /opt" in _with._info.toPlainText())

_partial = ServerNode(ServerData(id="c-part", alias="p", host="10.0.0.2", user="u",
                                 disk_path="/opt", disk_free="48 gb"))
_partial.update_appearance()
check("§7 a HALF-measured pair writes NO line (the card claims nothing incomplete)",
      "DISK /opt" not in _partial._info.toPlainText()
      and "48 gb" not in _partial._info.toPlainText(),
      _partial._info.toPlainText().replace("\n", " | "))

check("§7 LIST_COLUMNS still holds thirteen columns (no pinned figure moves)",
      len(SB.LIST_COLUMNS) == 13 and SB.list_column_index("status") == 4,
      str(len(SB.LIST_COLUMNS)))
check("§7 ... and the data mount is deliberately NOT a column",
      "disk_mount" not in [f for f, _k in SB.LIST_COLUMNS]
      and "disk_free" not in [f for f, _k in SB.LIST_COLUMNS],
      str([f for f, _k in SB.LIST_COLUMNS]))

# ── N35 — the refusal is DURABLE: the card says WHY long after the status line is gone ────────
_refused = ServerNode(ServerData(id="c-ref", alias="web-1", host="10.0.0.3", user="u",
                                 os_name="Ubuntu 24.04 LTS", disk_mount="/opt",
                                 disk_note=DISK_NOTE_MISSING))
_refused.update_appearance()
check("§7 N35 a refused data mount leaves a durable WHY on the card's tooltip",
      LANGS["en"]["status.disk_mount_missing"].format(mount="/opt", alias="web-1")
      in _refused._info.toolTip()
      and "DISK /opt" not in _refused._info.toPlainText(),
      _refused._info.toolTip().replace("\n", " | "))
_refused_dev = ServerNode(ServerData(id="c-ref2", alias="web-1", host="10.0.0.4", user="u",
                                     disk_device="sdb",
                                     disk_device_note=DISK_NOTE_DEVICE_MISSING))
_refused_dev.update_appearance()
check("§7 N35 ...the same channel carries a vanished DEVICE",
      LANGS["en"]["status.disk_device_missing"].format(device="sdb", alias="web-1")
      in _refused_dev._info.toolTip(),
      _refused_dev._info.toolTip().replace("\n", " | "))
check("§7 N35 ...and an ANSWERED card carries no note at all",
      "not found" not in _with._info.toolTip(), _with._info.toolTip().replace("\n", " | "))
_refused.data.disk_note = ""
_refused.update_appearance()
check("§7 N35 a later collection that ANSWERS clears the note with the data",
      LANGS["en"]["status.disk_mount_missing"].format(mount="/opt", alias="web-1")
      not in _refused._info.toolTip(), _refused._info.toolTip().replace("\n", " | "))


# ════════════════════════════════════════════════════════════════════════════
print("== §8 the DEVICE choice — `lsblk -d` names them, the user picks one ==")
# ════════════════════════════════════════════════════════════════════════════

# The colleague's own box one level DOWN: the root lives on `sda` (9.8 gb) while the volume the card
# is about is `sdb` (100 gb). Every other row carries a TYPE of its own — a candidate is DECLARED by
# `TYPE == "disk"`, never by the shape of its name.
_LSBLK_HEADER = "NAME SIZE TYPE"
_LSBLK_DISKS = [
    "sda 10522669875 disk",
    "sdb 107374182400 disk",
    "nvme0n1 512110190592 disk",
    "mmcblk0 31914983424 disk",
    "vda 10737418240 disk",
    "loop0 1024 loop",
    "sr0 1073741824 rom",
    "dm-0 63350767616 lvm",
    "md0 214748364800 raid1",
]
_LSBLK_ROWS = [_LSBLK_HEADER] + _LSBLK_DISKS
_DEVICE_LABELS = ["sda 9.8 gb", "sdb 100 gb", "nvme0n1 476.9 gb",
                  "mmcblk0 29.7 gb", "vda 10 gb"]


def device_output(rows, present="present", lsblk=None):
    """A collection output carrying the disk report AND the `lsblk` device listing."""
    listing = _LSBLK_ROWS if lsblk is None else lsblk
    return "\n".join(["---DISK---"] + list(rows) + ["---DISKS---"] + list(listing)
                     + ["---DISKMOUNT---", present, "---END---"])


check("§8 the batch asks for the devices in their OWN section (no user input in that command)",
      "---DISKS---" in INFO_BATCH and "lsblk -d -n -b -o NAME,SIZE,TYPE" in INFO_BATCH
      and DISK_MOUNT_TOKEN not in INFO_BATCH.split("---DISKS---")[1].split("---DISKMOUNT---")[0])
check("§8 ... and it still carries the requested mount (three reads, the shipped two plus df -i)",
      build_info_batch("").count("'/opt'") == 3 and build_info_batch("").count("---DISKS---") == 1)

_dev_rows = parse_lsblk_report("\n".join(_LSBLK_ROWS))
check("§8 the parser splits the listing into rows (name, size, type) with the size as an int",
      _dev_rows[0] == ("sda", 10522669875, "disk")
      and _dev_rows[1] == ("sdb", 107374182400, "disk")
      and len(_dev_rows) == 9, str(_dev_rows[:2]))
check("§8 ... dropping the header, an empty line and every unparsable row",
      all(row[0] != "NAME" for row in _dev_rows)
      and parse_lsblk_report("") == [] and parse_lsblk_report("---DISKS---\n---END---") == []
      and parse_lsblk_report("lsblk: not found") == []
      and parse_lsblk_report("sda notanumber disk") == [])
check("§8 an lsblk too old for the column list yields NOTHING (a degradation, never an error)",
      parse_lsblk_report("sda 107374182400") == []
      and physical_disks(parse_lsblk_report("sda 107374182400")) == [])

check("§8 the TYPE is the DECLARATION: only `disk` is a candidate",
      DISK_TYPE_PHYSICAL == "disk"
      and [name for name, _size in physical_disks(_dev_rows)]
      == ["sda", "sdb", "nvme0n1", "mmcblk0", "vda"],
      str(physical_disks(_dev_rows)))
check("§8 ... so a loop device, a CD-ROM, an LVM volume and an array are dropped BY TYPE",
      all(name not in [n for n, _s in physical_disks(_dev_rows)]
          for name in ("loop0", "sr0", "dm-0", "md0")))
check("§8 physical_disks() is total (a malformed row is skipped, never raised)",
      physical_disks([None, ("sda",), ("sdb", "x", "disk"), ("sdc", 10, "DISK"), "junk"])
      == [("sdc", 10)])
check("§8 a device is LABELLED through one function (the list, the combo and the tooltip)",
      device_label("sdb", 107374182400) == "sdb 100 gb"
      and device_label(" sda ", 10522669875) == "sda 9.8 gb"
      and device_label(None, 5) == "" and device_label("sdz", 0) == "sdz")
check("§8 the stored LIST is those labels, in the order lsblk printed them",
      device_labels(_dev_rows) == _DEVICE_LABELS, str(device_labels(_dev_rows)))

check("§8 no choice answers NOTHING (the root's df figure stays the figure `disk` carries)",
      resolve_disk_device(_dev_rows, "") == {"name": "", "size": "", "note": ""}
      and resolve_disk_device(_dev_rows, None) == {"name": "", "size": "", "note": ""}
      and resolve_disk_device(_dev_rows, "   ")["name"] == "")
check("§8 the chosen device answers ITS capacity — the number the field asked for",
      resolve_disk_device(_dev_rows, "sdb") == {"name": "sdb", "size": "100 gb", "note": ""}
      and resolve_disk_device(_dev_rows, "sda")["size"] == "9.8 gb",
      str(resolve_disk_device(_dev_rows, "sdb")))
check("§8 the match is by NAME and case-insensitive (a user may type SDB)",
      resolve_disk_device(_dev_rows, "SDB")["size"] == "100 gb"
      and resolve_disk_device(_dev_rows, " NVME0N1 ")["size"] == "476.9 gb"
      and resolve_disk_device(_dev_rows, "SDB")["name"] == "SDB")
check("§8 a name the listing does NOT hold is a REPORTED miss, never another disk's number",
      resolve_disk_device(_dev_rows, "sdz")
      == {"name": "sdz", "size": "", "note": DISK_NOTE_DEVICE_MISSING}
      and resolve_disk_device(_dev_rows, "loop0")["note"] == DISK_NOTE_DEVICE_MISSING,
      str(resolve_disk_device(_dev_rows, "sdz")))
check("§8 ... and an EMPTY listing is the same miss (an lsblk-less host invents nothing)",
      resolve_disk_device([], "sdb")["size"] == ""
      and resolve_disk_device([], "sdb")["note"] == DISK_NOTE_DEVICE_MISSING)
check("§8 the ONE classifier names the third refusal kind",
      disk_refusal_kind(DISK_NOTE_DEVICE_MISSING) == DISK_REFUSAL_DEVICE == "device"
      and disk_refusal_kind("") == "" and disk_refusal_kind(DISK_NOTE_MISSING) == DISK_REFUSAL_MISSING
      and disk_refusal_kind("cifs") == DISK_REFUSAL_NETWORK)

_info_dev = parse_info_output(device_output([_DF_HEADER, _ROOT_ROW, _HOST_A_ROW]), "sdb")
check("§8 the whole batch yields the DEVICE's capacity, the listing and the data mount",
      _info_dev["disk_gb"] == "100 gb" and _info_dev["disk_devices"] == _DEVICE_LABELS
      and _info_dev["disk_device_note"] == "" and _info_dev["disk_path"] == "/opt"
      and _info_dev["disk_free"] == "48 gb" and _info_dev["disk_size"] == "59 gb",
      str(_info_dev))
_info_nodev = parse_info_output(device_output([_DF_HEADER, _ROOT_ROW, _HOST_A_ROW]))
check("§8 a card with NO choice keeps the root's figure byte for byte (the feature is opt-in)",
      _info_nodev["disk_gb"] == "9.8 gb" and "disk_device_note" not in _info_nodev
      and _info_nodev["disk_devices"] == _DEVICE_LABELS,
      str(_info_nodev.get("disk_gb")))
_info_gone = parse_info_output(device_output([_DF_HEADER, _ROOT_ROW], lsblk=[_LSBLK_HEADER]), "sdb")
check("§8 a chosen device the listing lost leaves NO figure and says WHICH device",
      "disk_gb" not in _info_gone and _info_gone["disk_device_note"] == DISK_NOTE_DEVICE_MISSING
      and "disk_devices" not in _info_gone,
      str(_info_gone))
_info_old = parse_info_output(disk_output([_DF_HEADER, _ROOT_ROW]), "sdb")
check("§8 an output without the section says NOTHING about a device (a pre-release batch/fixture)",
      "disk_devices" not in _info_old and "disk_device_note" not in _info_old
      and _info_old["disk_gb"] == "9.8 gb",
      str(_info_old))
check("§8 the collector builds its answer from the NODE's own choice",
      callable(getattr(SIC.SystemInfoCollector(
          ServerData(id="c2", alias="a", host="h", user="u", disk_device="sdb")), "_log_disk_note", None)))
_dev_collector = SIC.SystemInfoCollector(ServerData(id="c3", alias="a", host="h", user="u",
                                                    disk_device="sdb"))
check("§8 the collector names a vanished device in its own report (the activity history's half)",
      _dev_collector._log_disk_note({"disk_device_note": DISK_NOTE_DEVICE_MISSING}) is None
      and _dev_collector._log_disk_note({"disk_note": "cifs",
                                         "disk_device_note": DISK_NOTE_DEVICE_MISSING}) is None
      and _dev_collector._log_disk_note({"disk_device_note": ""}) is None)

check("§8 the two model fields exist with the declared defaults",
      ServerData(id="x", alias="a", host="h", user="u").disk_device == ""
      and ServerData(id="x", alias="a", host="h", user="u").disk_devices == [])
check("§8 sanitize_device_list() is the tags rule applied to a MEASUREMENT",
      sanitize_device_list([" sda 9.8 gb ", "sdb 100 gb", "", "  ", 22, None, ["x"]])
      == ["sda 9.8 gb", "sdb 100 gb"]
      and sanitize_device_list(None) == [] and sanitize_device_list("sdb") == []
      and sanitize_device_list({"a": 1}) == [] and sanitize_device_list((1, 2)) == [],
      str(sanitize_device_list([" sda 9.8 gb ", 22, None])))
_dev_bad = server_data_from_dict({"id": "devbad", "alias": "a", "host": "h", "user": "u",
                                  "disk_device": " sdb ", "disk_devices": ["sda 9.8 gb", 7, None]})
check("§8 a hand-edited device field degrades without breaking the load",
      _dev_bad.disk_device == "sdb" and _dev_bad.disk_devices == ["sda 9.8 gb"], str(_dev_bad))
check("§8 a project written before the release loads with NO choice and NO listing",
      _old.disk_device == "" and _old.disk_devices == [])
_dev_meas = server_data_from_dict({"id": "devm", "alias": "a", "host": "h", "user": "u",
                                   "disk_device": "sdb", "disk_devices": _DEVICE_LABELS})
_dev_rt = server_data_from_dict(server_data_to_dict(_dev_meas))
check("§8 the pair round-trips through save → load", _dev_rt.disk_device == "sdb"
      and _dev_rt.disk_devices == _DEVICE_LABELS, str(_dev_rt.disk_devices))
check("§8 an unmeasured map writes the REQUEST but NO list key (nothing is claimed)",
      server_data_to_dict(_old)["disk_device"] == ""
      and "disk_devices" not in server_data_to_dict(_old))
check("§8 ... the schema does NOT move with them", _version.VERSION_FORMAT == "0.9")
check("§8 the model keeps `disk` a PURE size string (the inventory's own sort key parses it whole)",
      _dev_meas.disk == "" and _disk_key("512 mb") < _disk_key("9.8 gb") < _disk_key("100 gb")
      and SB.list_cell_values(server_data_from_dict(
          {"id": "v", "alias": "a", "host": "h", "user": "u", "disk": "100 gb",
           "disk_device": "sdb"}))[SB.list_column_index("disk")] == "100 gb")

_rec3 = RoundRecorder()
win3 = make_main(checker=_rec3)
win3.scene.add_server(ServerData(id="d1", alias="data-1", host="10.4.0.9", user="root",
                                 disk_device="sdb"))
_node3 = win3.scene.get_node("d1")
check("§8 the ONE write path takes the DEVICE's capacity and the listing TOGETHER",
      win3._apply_info_result("d1", {"disk_gb": "100 gb", "disk_devices": _DEVICE_LABELS,
                                     "disk_device_note": ""}) is True
      and _node3.data.disk == "100 gb" and _node3.data.disk_devices == _DEVICE_LABELS,
      str((_node3.data.disk, _node3.data.disk_devices)))
check("§8 the composed line and the listing reach the CARD through that one write",
      "DISK: SDB 100 gb" in _node3._info.toPlainText()
      and "Devices: sda 9.8 gb · sdb 100 gb" in _node3._info.toolTip(),
      _node3._info.toolTip().replace("\n", " | "))
check("§8 a device that VANISHED clears the figure and is REPORTED (never another disk's number)",
      win3._apply_info_result("d1", {"disk_devices": ["sda 9.8 gb"],
                                     "disk_device_note": DISK_NOTE_DEVICE_MISSING}) is True
      and _node3.data.disk == "" and _node3.data.disk_devices == ["sda 9.8 gb"]
      and "sdb" in win3.statusBar().currentMessage(),
      win3.statusBar().currentMessage())
check("§8 ... and the card claims NO line rather than an empty one",
      _node3._disk_line() == "" and "DISK" not in _node3._info.toPlainText())
check("§8 a collection silent about a device leaves the figure and the list where they are",
      win3._apply_info_result("d1", {"os_name": "Debian GNU/Linux 12"}) is True
      and _node3.data.disk == "" and _node3.data.disk_devices == ["sda 9.8 gb"])
check("§8 ... while a payload written before the section keeps the plain figure rule",
      win3._apply_info_result("d1", {"disk_gb": "9.8 gb"}) is True and _node3.data.disk == "9.8 gb")
check("§8 ... and the choice itself is NEVER erased by a collection",
      _node3.data.disk_device == "sdb")
check("§8 a node that vanished during the collection still writes nothing",
      win3._apply_info_result("nope", {"disk_devices": _DEVICE_LABELS}) is False)
win3._dirty = False
win3.close()
app.processEvents()

dlg7 = AddServerDialog(edit_data=ServerData(id="e3", alias="data-3", host="10.4.0.11", user="root",
                                            disk="100 gb", disk_device="sdb",
                                            disk_devices=_DEVICE_LABELS))
check("§8 the DISK row carries the device REQUEST beside the measured figure",
      all(hasattr(dlg7, f) for f in ("disk_device", "disk_device_row", "_disk_device_arrow", "disk"))
      and dlg7.disk.text() == "100 gb")
check("§8 the choice is an EDITABLE combo over the REAL devices the collection read",
      dlg7.disk_device.isEditable() and dlg7.disk_device.count() == len(_DEVICE_LABELS)
      and [dlg7.disk_device.itemText(i) for i in range(dlg7.disk_device.count())] == _DEVICE_LABELS,
      str([dlg7.disk_device.itemText(i) for i in range(dlg7.disk_device.count())]))
check("§8 the request field names the choice and its precedence in its placeholder",
      dlg7.disk_device.lineEdit().placeholderText() == LANGS["en"]["server.disk_device_hint"]
      and dlg7.disk_device.currentText() == "sdb",
      repr(dlg7.disk_device.lineEdit().placeholderText()))
check("§8 the row's tooltip spells the precedence out (the choice wins over the typed number)",
      "WINS" in dlg7.disk_device.toolTip() and dlg7.disk_device.toolTip().strip() != "")
check("§8 the stored request is the NAME alone — the figure shown beside it never enters the model",
      dlg7.get_data().disk_device == "sdb"
      and dlg7.get_data().disk_devices == _DEVICE_LABELS
      and dlg7.get_data().disk == "100 gb")
dlg7.disk_device.setCurrentText("sdb 100 gb")
check("§8 picking a row takes its name, not its label", dlg7.get_data().disk_device == "sdb")
dlg7.disk_device.setEditText("sdz")
check("§8 a name the last collection did not see can still be TYPED (the field stays editable)",
      dlg7.get_data().disk_device == "sdz" and dlg7.disk_device.isEditable())
dlg7.close()
_dlg_new = AddServerDialog()
check("§8 a NEW card starts with no choice and no listing (and an empty combo)",
      _dlg_new.disk_device.count() == 0 and _dlg_new.get_data().disk_device == ""
      and _dlg_new.get_data().disk_devices == [])
_dlg_new.close()

_dev_card = ServerNode(ServerData(id="c-dev", alias="data", host="10.0.0.1", user="u",
                                  os_name="Ubuntu 24.04 LTS", ram="16 gb", disk="100 gb",
                                  disk_device="sdb", disk_devices=_DEVICE_LABELS))
_dev_plain = ServerNode(ServerData(id="c-plain", alias="plain", host="10.0.0.2", user="u",
                                   os_name="Ubuntu 24.04 LTS", ram="16 gb", disk="9.8 gb"))
_dev_card.update_appearance()
_dev_plain.update_appearance()
check("§8 the card COMPOSES the name into its line, UPPERCASED, beside the pure figure",
      "DISK: SDB 100 gb" in _dev_card._info.toPlainText()
      and _dev_card._info.toPlainText().count("DISK") == 1,
      _dev_card._info.toPlainText().replace("\n", " | "))
check("§8 ... while a card with no choice renders exactly the shipped line",
      _dev_plain._info.toPlainText().endswith("DISK: 9.8 gb")
      and "SDB" not in _dev_plain._info.toPlainText(),
      _dev_plain._info.toPlainText().replace("\n", " | "))
check("§8 the listing rides the TOOLTIP as ONE line (no second card line, no elision pressure)",
      "Devices: " + " · ".join(_DEVICE_LABELS) in _dev_card._info.toolTip()
      and "Devices:" not in _dev_card._info.toPlainText()
      and _dev_card._info_tip_full == "",
      _dev_card._info.toolTip().replace("\n", " | "))
check("§8 ... so the measured height formula does not move (58 + info + 12)",
      _dev_card._current_height == _dev_plain._current_height == 130,
      f"{_dev_card._current_height} / {_dev_plain._current_height}")
check("§8 a card whose device vanished claims NO capacity line at all",
      ServerNode(ServerData(id="c-gone", alias="gone", host="10.0.0.3", user="u",
                            os_name="Ubuntu 24.04 LTS", ram="16 gb", disk="", disk_device="sdb",
                            disk_devices=["sda 9.8 gb"]))._disk_line() == "")
_dev_gone = ServerNode(ServerData(id="c-gone2", alias="gone", host="10.0.0.3", user="u",
                                  disk="", disk_device="sdb", disk_devices=["sda 9.8 gb"]))
_dev_gone.update_appearance()
check("§8 ... and its tooltip still names what the listing DID find",
      "Devices: sda 9.8 gb" in _dev_gone._info.toolTip()
      and "DISK" not in _dev_gone._info.toPlainText())
check("§8 a card with no listing keeps its empty tooltip (nothing to say)",
      ServerNode(ServerData(id="c-t", alias="t", host="10.0.0.4", user="u",
                            ram="16 gb"))._disk_devices_text() == "")
check("§8 the device list is deliberately NOT an inventory column (13 columns stay)",
      len(SB.LIST_COLUMNS) == 13
      and "disk_device" not in [f for f, _k in SB.LIST_COLUMNS]
      and "disk_devices" not in [f for f, _k in SB.LIST_COLUMNS])


# ════════════════════════════════════════════════════════════════════════════
print("== §9 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
check("§9 the version pin is the version this file describes",
      releases_at_least(EXPECTED_APP_VERSION, "1.7") and releases_at_least(_version.APP_VERSION, "1.7"),
      f"{EXPECTED_APP_VERSION} / {_version.APP_VERSION}")
check("§9 the i18n pin counts the SHIPPED release (811 + 17 of v1.6.7 + 13 of v1.6.8 + 5 of v1.7rc1"
      " + 8 of v1.7rc2 + 9 of v1.7rc3 + 4 of v1.7.1 + 3 of v1.7.1.1 + 4 of the v1.7.1.2 device choice "
      "+ the 4 of v1.7.2: the third row of the display mode (the single window), the merge action with its one closing report and the remote title of a tab"
      " + the 19 of v1.7.3: the Send-to row and its dialog, the busy/progress/done/failed reports,"
      " the two-sided conflict facts, the remembered-folder sentence, the two drop refusals and Word wrap"
      " + the 17 of v1.7.4rc1: the local source switch of a pane, its two refusals, the permanent-"
      " delete warning and the local file-surface sentences, and v1.7.4rc2 adds 1: the refusal of"
      " a move that would cross the two sources, and v1.8 adds TWENTY: the elevated pane and the"
      " 41 of v1.8.1: the trust surface; v1.8.1.1 adds ONE: the send identity sentence) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact, and v1.9 adds FOUR: the production-tag guard — its title, the broadcast sentence and the paste sentence — and the notice of a checked selection that has left the map, and v1.9.1 adds ELEVEN: the reconnect and its `tmux attach`",
      EXPECTED_I18N_KEYS == 811 + 17 + 13 + 5 + 8 + 9 + 4 + 3 + 4 + 4 + 19 + 17 + 1 + 4 + 6 + 20 + 41 + 1 + 16 + 23 + 10 + 4 + 11, str(EXPECTED_I18N_KEYS))
check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check("§9 the ELEVEN new keys are present and non-empty in every language",
      all(str(LANGS[c].get(k, "")).strip() for k in NEW_KEYS for c in LANGS)
      and len(NEW_KEYS) == 11,
      str([k for k in NEW_KEYS for c in LANGS if not str(LANGS[c].get(k, "")).strip()]))
check("§9 the placeholders of the new keys match en in every language",
      all({m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS[c][k])}
          == {m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS["en"][k])}
          for k in NEW_KEYS for c in LANGS))
check("§9 the card's measured line carries the three placeholders it renders",
      {"mount", "free", "size"}
      <= {m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS["en"]["node.disk_mount"])})
check("§9 the FOUR device keys are present and non-empty in every language",
      all(str(LANGS[c].get(k, "")).strip() for k in DEVICE_KEYS for c in LANGS)
      and len(DEVICE_KEYS) == 4,
      str([k for k in DEVICE_KEYS for c in LANGS if not str(LANGS[c].get(k, "")).strip()]))
check("§9 the placeholders of the device keys match en in every language",
      all({m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS[c][k])}
          == {m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS["en"][k])}
          for k in DEVICE_KEYS for c in LANGS))
check("§9 the tooltip line renders {devices} and the sentence renders {device} + {alias}",
      {"devices"} <= {m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
                                            LANGS["en"]["node.disk_devices"])}
      and {"device", "alias"} <= {m for m in re.findall(
          r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS["en"]["status.disk_device_missing"])})
check("§9 the registry moved only by the closing release's ONE export action",
      len(HR.HOTKEY_ACTIONS) == 62 and len(HR.empty_default_action_ids()) == 39,
      f"{len(HR.HOTKEY_ACTIONS)}/{len(HR.empty_default_action_ids())}")
check("§9 the settings hub still collects 25 keys (a per-card choice is not a new row)",
      len(SettingsDialog(None).collect()) == 25)
check("§9 no new dependency (requirements.txt keeps its four)",
      len([ln for ln in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8")
           if ln.strip() and not ln.startswith("#")]) == 4
      or all(x in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
             for x in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("§9 no new colour field (the theme stays the 60-field palette it ships)",
      len(list(theme.Theme.__dataclass_fields__)) == 60
      and "MANUAL_STALE_SEC" in open(os.path.join(ROOT, "services", "status_checker.py"),
                                     encoding="utf-8").read(),
      str(len(list(theme.Theme.__dataclass_fields__))))

finish()
