# -*- coding: utf-8 -*-
"""The clause audit of `ELEVATED_PANE.md` (v1.8) against the SHIPPED code — one section per clause
group of the frozen contract: the third provider, the handshake, the surface, the dialogue, the
ONE refusal, the sentences, the refactor boundary and the acceptance.

The audit reads the pane FAMILY as one text (a pin names a method, never a file), and drives the
PURE half and the pane's own doors over the fakes of `tests/_fakes.py` — offscreen, no network.
Run: python tests/test_elevated_pane_contract.py   (from the project root) or python tests/run_all.py"""
import os
import sys

from _common import (bootstrap, check, finish, wait_for, pane_family_text, pane_func_body,
                     pane_func_owner, check_release_state, clear_cfg, load_i18n_langs)

ROOT, WORK = bootstrap()  # BEFORE the app imports (the HOME isolation)

from PySide6.QtWidgets import QApplication, QDialog

app = QApplication(sys.argv)

import dialogs.elevated_dialog as ED
import i18n
import modules.sftp_elevated as ELEV
import modules.sftp_tab as STAB
from modules.sftp_tab import SOURCE_ELEVATED, SOURCE_LOCAL, SOURCE_REMOTE, SftpTab
from modules.sftp_worker import KIND_COPY, KIND_DOWNLOAD, KIND_LIST, KIND_MKDIR, KIND_MOVE, \
    KIND_NORMALIZE, KIND_READ, KIND_RENAME, KIND_DELETE, SftpWorker

from _fakes import EventLog, FakeSftpClient, FakeSftpFS, wire_worker

CONTRACT = os.path.join(ROOT, "ELEVATED_PANE.md")
CONTRACT_TEXT = open(CONTRACT, encoding="utf-8").read() if os.path.isfile(CONTRACT) else ""
FAMILY = pane_family_text(ROOT)
_LISTING_SRC = open(os.path.join(ROOT, "modules", "sftp_pane_listing.py"),
                    encoding="utf-8").read()
LANGS = load_i18n_langs(ROOT)


class _Handshake:
    """The pane-side handshake seam (the contract audit's own stand-in)."""

    def __init__(self, transport, user="", password="", parent=None):
        from PySide6.QtCore import QObject, Signal

        class _H(QObject):
            ready = Signal(object, str)
            failed = Signal(str, str)

        self._h = _H(parent)
        self.ready = self._h.ready
        self.failed = self._h.failed
        self.transport = transport
        self.user = user
        self.password = password
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def isRunning(self):
        return False

    def close(self):
        self.closed = True

    def shutdown(self, wait_ms=0):
        pass

    def deleteLater(self):   # noqa: N802 — the Qt name
        pass


def build(commander=True, fs=None):
    """(tab, worker, the FS) over the fake SFTP surface — the audit's own harness."""
    fs = fs or FakeSftpFS()
    fs.add_dir("/root")
    fs.add_file("/root/secret.txt", b"top secret\n")
    worker = SftpWorker(FakeSftpClient(fs))
    wire_worker(worker, EventLog())
    worker.start()
    tab = SftpTab()
    tab.message.connect(lambda *_a: None)
    if commander:
        tab.set_commander(True)
    tab.set_worker(worker)
    tab.set_session_info(key="k1", label="prod", host="h", port=22, user="root")
    return tab, worker, fs


class _Transport:
    """A live transport stand-in (the pane asks it for the elevation)."""

    def is_active(self):
        return True

    def open_session(self):
        raise AssertionError("the contract audit must never open a real channel")


clear_cfg()

# ════════════════════════════════════════════════════════════
print("== 1. the third provider and the source decision (ELEVATED_PANE.md §1) ==")
# ════════════════════════════════════════════════════════════

check("§1 the elevation is a PROVIDER state, not a third data source (PANE_SOURCES keeps its pair)",
      STAB.PANE_SOURCES == (SOURCE_REMOTE, SOURCE_LOCAL)
      and SOURCE_ELEVATED not in STAB.PANE_SOURCES
      and "SOURCE_ELEVATED = \"elevated\"" in FAMILY)

check("§1 `provider` answers the elevated client while it is bound, and the session's worker after",
      "_elevated_provider is not None" in pane_func_body("provider", ROOT)
      and "return self.worker" in pane_func_body("provider", ROOT))

check("§1 the pane's DATA SOURCE stays the shipped remote one (the dialect never moves)",
      pane_func_body("_switch_state", ROOT).count("SOURCE_ELEVATED") == 1
      and "_source" in pane_func_body("_switch_state", ROOT)
      and STAB.dialect_for(SOURCE_ELEVATED) is STAB.POSIX_PATHS)

check("§1 the engine is the SHIPPED worker, not a second transfer loop",
      STAB.SftpWorker in STAB.MODULE_FACADE_SEAMS
      and "host_attr(self, 'SftpWorker')(client)" in pane_func_body("_on_elevation_ready", ROOT)
      and not os.path.isfile(os.path.join(ROOT, "modules", "sftp_elevated_worker.py")))

check("§1 `bind_worker()` disconnects the provider the pane REALLY holds (the declared record)",
      "_bound_provider" in pane_func_body("bind_worker", ROOT)
      and "self._elevated_provider is not None" in pane_func_body("bind_worker", ROOT))

check("§1 an elevated pane keeps the container's worker reachable for the SESSION's own paths",
      "return self._container.worker" in pane_func_body("worker", ROOT))

# ════════════════════════════════════════════════════════════
print("== 2. the handshake and its command table (ELEVATED_PANE.md §2) ==")
# ════════════════════════════════════════════════════════════

_HANDSHAKE = open(os.path.join(ROOT, "modules", "sftp_elevated.py"), encoding="utf-8").read()

check("§2 the candidate list, the allowlist and the three command builders live in ONE module",
      all(name in _HANDSHAKE for name in ("SFTP_SERVER_CANDIDATES", "ELEVATED_USER_RE",
                                          "elevated_server_command", "elevated_probe_command",
                                          "sudo_prime_command", "user_problem")))

check("§2 the probe is `sudo -n [-u <user>] -l <binary>` and the server command drops the `-l`",
      ELEV.elevated_probe_command("u", "/b") == "sudo -n -u u -l /b"
      and ELEV.elevated_server_command("u", "/b") == "sudo -n -u u /b"
      and ELEV.elevated_server_command("root", "/b") == "sudo -n /b")

check("§2 the prime is a SEPARATE `sudo -S -v` channel and it is the ONLY place a password goes",
      ELEV.sudo_prime_command() == "sudo -S -v"
      and _HANDSHAKE.count("sendall(") == 1
      and "sudo_prime_command()" in _HANDSHAKE)

check("§2 the password never reaches a log line, a file or an argv",
      not [ln for ln in _HANDSHAKE.splitlines()
           if ln.strip().startswith("log.") and "password" in ln.lower()]
      and "self._password = \"\"" in _HANDSHAKE
      and 'log.' not in _HANDSHAKE.split("def run(")[1].split("def ")[0])

check("§2 the client is created through the `paramiko` ATTRIBUTE (the substitution seam)",
      "mod = paramiko" in _HANDSHAKE and "client_cls = getattr(mod, \"SFTPClient\", None)" in _HANDSHAKE)

check("§2 the five failure codes are the declared table and each names its sentence key",
      set(ELEV.ELEVATED_ERROR_KEYS) == {"no_transport", "password", "refused", "open_failed",
                                        "failed"})

check("§2 the handshake names its thread and has an orphan registry (AGENTS.md §4.8)",
      'setObjectName("ElevatedHandshake")' in _HANDSHAKE
      and "register_orphan_handshake" in _HANDSHAKE
      and "def shutdown(" in _HANDSHAKE)

check("§2 the transport the pane rides is the SESSION's, published by the page that opens SFTP",
      "set_transport" in open(os.path.join(ROOT, "modules", "terminal_page_sftp.py"),
                              encoding="utf-8").read()
      and "def set_transport(" in FAMILY and "def transport(" in FAMILY)

# ════════════════════════════════════════════════════════════
print("== 3. the read-only surface (ELEVATED_PANE.md §3) ==")
# ════════════════════════════════════════════════════════════

check("§3 the header line NAMES the elevation through the listing mixin's ONE reader",
      pane_func_owner("header_text", ROOT) == "modules/sftp_pane_listing.py"
      and "sftp.elevated.header" in pane_func_body("header_text", ROOT))

check("§3 the elevated pane's own transfer reports itself (no session page listens to it)",
      "own_engine" in pane_func_body("_on_task_done", ROOT)
      and "sftp.transfer_done" in pane_func_body("_on_task_done", ROOT))

check("§3 the DOWNLOAD is NOT refused by any door of the pane family",
      "def _on_download" in open(os.path.join(ROOT, "modules", "sftp_pane_transfer.py"),
                                 encoding="utf-8").read()
      and "_refuse_elevated_write" not in
      pane_func_body("_on_download", ROOT))

check("§3 the cwd follow refuses an elevated pane as it refuses a local one",
      'bool(getattr(self, "elevated", False))' in _LISTING_SRC
      and "SOURCE_LOCAL" in _LISTING_SRC)

check("§3 `Send to…` rides the SESSION's worker and stays a server row's door",
      "self.worker" in pane_func_body("_op_send_to", ROOT)
      and "start_send" in pane_func_body("_op_send_to", ROOT)
      and "sftp.local.transfer_unavailable" in pane_func_body("_op_send_to", ROOT))

# ════════════════════════════════════════════════════════════
print("== 4. the dialogue, the switch and the lifetime (ELEVATED_PANE.md §4) ==")
# ════════════════════════════════════════════════════════════

_DIALOG = os.path.join(ROOT, "dialogs", "elevated_dialog.py")
_DIALOG_SRC = open(_DIALOG, encoding="utf-8").read() if os.path.isfile(_DIALOG) else ""

check("§4 the dialogue asks for the USER and the PASSWORD and nothing else",
      os.path.isfile(_DIALOG) and "sftp.elevated.user_label" in _DIALOG_SRC
      and "sftp.elevated.password_label" in _DIALOG_SRC
      and "EchoMode.Password" in _DIALOG_SRC)

check("§4 it validates the user with the PURE allowlist INSIDE the dialogue",
      "user_problem" in _DIALOG_SRC and "sftp.elevated.bad_user" in _DIALOG_SRC
      and "def ask_elevation(" in _DIALOG_SRC)


class _CancelledDialog(ED.ElevationDialog):
    """The dialogue of a user who pressed Cancel — a SUBCLASS override (gotcha #7 forbids patching)."""

    def exec(self):
        return QDialog.DialogCode.Rejected


class _AcceptedDialog(_CancelledDialog):
    """The dialogue of a user who pressed Connect with both fields left untouched."""

    def exec(self):
        return QDialog.DialogCode.Accepted


_original_dialog = ED.ElevationDialog
try:
    ED.ElevationDialog = _CancelledDialog
    _cancel_answer = ED.ask_elevation(None, "admin")
    ED.ElevationDialog = _AcceptedDialog
    _empty_answer = ED.ask_elevation(None, "")
finally:
    ED.ElevationDialog = _original_dialog

check("§4 a CANCELLED dialogue is NO answer at all (`None`) — the seam's ONLY refusal",
      _cancel_answer is None and isinstance(_empty_answer, tuple),
      f"cancel={_cancel_answer!r} empty={_empty_answer!r}")
check("§4 ...and the EMPTY pair stays the legal `root` without a password (never a refusal)",
      _empty_answer == ("", "") and ELEV.user_problem(_empty_answer[0]) is None,
      str(_empty_answer))
check("§4 the pane reads the ask the same way: a refusal on `None`, a handshake on the empty pair",
      "if answer is None:" in pane_func_body("begin_elevation", ROOT)
      and "answer is None" in pane_func_body("begin_elevation", ROOT)
      and '== ("", "")' not in pane_func_body("begin_elevation", ROOT),
      pane_func_body("begin_elevation", ROOT)[:200])
check("§4 an answer that outlives its ask is INERT: the posted call goes with the handshake and a "
      "client nobody waits for is closed",
      "removePostedEvents" in pane_func_body("_drop_handshake", ROOT)
      and "_close_unclaimed_client" in pane_func_body("_on_elevation_ready", ROOT)
      and "_elevation_pending" in pane_func_body("_on_elevation_ready", ROOT)
      and "_elevation_pending" in pane_func_body("_on_elevation_failed", ROOT))

check("§4 the ask is a facade global (the shipped substitution seam)",
      STAB.ask_elevation in STAB.MODULE_FACADE_SEAMS
      and STAB.ElevatedHandshake in STAB.MODULE_FACADE_SEAMS
      and "host_attr(self, 'ask_elevation')" in pane_func_body("begin_elevation", ROOT))

check("§4 the three structural answers come BEFORE any channel is opened",
      pane_func_body("begin_elevation", ROOT).index("can_elevate")
      < pane_func_body("begin_elevation", ROOT).index("ask_elevation")
      and pane_func_body("begin_elevation", ROOT).index("_elevation_transport")
      < pane_func_body("begin_elevation", ROOT).index("ask_elevation"))

check("§4 the elevation is NOT a config key (a gesture of the moment, like the local switch)",
      "elevated" not in open(os.path.join(ROOT, "modules", "terminal_config.py"),
                             encoding="utf-8").read().lower()
      and "sftp.elevated" not in open(os.path.join(ROOT, "modules", "terminal_config.py"),
                                      encoding="utf-8").read())

check("§4 `can_elevate()` is the sibling of `can_use_local()` (the same two structural rules)",
      "def can_elevate" in FAMILY and "return self.can_use_local(pane)" in FAMILY
      and '""' not in pane_func_body("can_elevate", ROOT))

check("§4 the SOURCE SWITCH gained a THIRD button and ONE state writer",
      "btn_elevated" in FAMILY and "ELEVATED_SOURCE_LABEL" in FAMILY
      and "self._source = token if token in (SOURCE_LOCAL, SOURCE_ELEVATED) else SOURCE_REMOTE"
      in FAMILY)

check("§4 a switch AWAY from elevated drops it through the pane's ONE door",
      "self.begin_elevation(notify=notify)" in pane_func_body("set_source", ROOT)
      and "self.leave_elevation(target, notify=notify)" in pane_func_body("set_source", ROOT)
      and "self._release_elevated()" in pane_func_body("leave_elevation", ROOT)
      and "self.set_source(host_attr(self, 'SOURCE_LOCAL', 'local'), notify=notify)"
      in pane_func_body("leave_elevation", ROOT))

check("§4 the teardown is idempotent and closes the client (which closes the channel)",
      "self.shutdown_elevated()" in pane_func_body("release", ROOT)
      and "client.close()" in pane_func_body("_release_elevated", ROOT)
      and "provider.shutdown(wait_ms=elevation.ELEVATED_SHUTDOWN_WAIT_MS)"
      in pane_func_body("_release_elevated", ROOT))

check("§4 a lost transport drops the elevation with ONE sentence",
      "def transport_lost" in FAMILY and "sftp.elevated.lost" in FAMILY
      and "set_transport" in FAMILY)

# ════════════════════════════════════════════════════════════
print("== 5. the ONE refusal of the dispatch (ELEVATED_PANE.md §5) ==")
# ════════════════════════════════════════════════════════════

check("§5 the batch's ONE door asks the elevated question FIRST",
      "_elevated_batch_refused" in pane_func_body("_queue_transfer_batch", ROOT)
      and pane_func_body("_queue_transfer_batch", ROOT).index("_elevated_batch_refused")
      < pane_func_body("_queue_transfer_batch", ROOT).index("SOURCE_LOCAL"))

check("§5 ...and the predicate refuses BOTH ends (the source pane and the destination pane)",
      "(self.elevated or other)" in pane_func_body("_elevated_batch_refused", ROOT)
      and "getattr(target_pane, 'elevated', False)"
      in pane_func_body("_elevated_batch_refused", ROOT))

check("§5 every single-item write door of the family asks the same predicate",
      "_refuse_elevated_write" in pane_func_body("_on_upload", ROOT)
      and "_refuse_elevated_write" in pane_func_body("_queue_uploads", ROOT)
      and "_refuse_elevated_write" in pane_func_body("_op_new_folder", ROOT)
      and "_refuse_elevated_write" in pane_func_body("_op_rename", ROOT)
      and "_refuse_elevated_write" in pane_func_body("_op_delete", ROOT)
      and "_refuse_elevated_write" in pane_func_body("_on_drop", ROOT))

check("§5 a DRAG whose source pane is elevated is refused before the batch is built",
      "_elevated_drop_refused" in pane_func_body("_on_pane_drop", ROOT)
      and "id(pane) == pane_id and pane.elevated" in pane_func_body("_elevated_drop_refused", ROOT))

check("§5 the refusal is ONE sentence, and the elevated family owns it",
      FAMILY.count("sftp.elevated.read_only") == 3
      and "sftp.elevated.read_only" not in
      open(os.path.join(ROOT, "modules", "sftp_pane_transfer.py"), encoding="utf-8").read())

check("§5 no write door of the elevated pane can reach a write method of its client",
      all(name not in pane_func_body("_refuse_elevated_write", ROOT)
          for name in ("queue_upload", "queue_mkdir", "queue_rename", "queue_delete")))

# ════════════════════════════════════════════════════════════
print("== 6. the sentences and the codes (ELEVATED_PANE.md §6) ==")
# ════════════════════════════════════════════════════════════

_ELEVATED_KEYS = sorted(k for k in LANGS["en"] if k.startswith("sftp.elevated."))

check("§6 the family of sentences is declared once and every language file carries all of them",
      len(_ELEVATED_KEYS) == 20
      and all(k in LANGS[code] for code in LANGS for k in _ELEVATED_KEYS),
      str(_ELEVATED_KEYS))

check("§6 every code's key is IN that family (a code cannot ship without a sentence)",
      all(key in LANGS["en"] for key in ELEV.ELEVATED_ERROR_KEYS.values())
      and all(key.startswith("sftp.elevated.") for key in ELEV.ELEVATED_ERROR_KEYS.values()))

check("§6 the sentences the contract QUOTES really exist (the document is not ahead of the code)",
      all(key in LANGS["en"] for key in
          ("sftp.elevated.unavailable", "sftp.elevated.bad_user", "sftp.elevated.read_only",
           "sftp.elevated.working", "sftp.elevated.header", "sftp.elevated.lost"))
      and CONTRACT_TEXT.count("sftp.elevated.") >= 6)

check("§6 no sentence of the elevated family leaked into the local pane's family (18 keys)",
      len([k for k in LANGS["en"] if k.startswith("sftp.local.")]) == 18)

# ════════════════════════════════════════════════════════════
print("== 7. the refactor boundary — what does NOT move (ELEVATED_PANE.md §7) ==")
# ════════════════════════════════════════════════════════════

check("§7 the pane family is the facade plus its SIX mixins (the elevation joined by itself)",
      pane_func_owner("begin_elevation", ROOT) == "modules/sftp_pane_elevated.py"
      and pane_func_owner("set_source", ROOT) == "modules/sftp_tab.py"
      and pane_func_owner("_queue_transfer_batch", ROOT) == "modules/sftp_pane_transfer.py"
      and pane_func_owner("header_text", ROOT) == "modules/sftp_pane_listing.py")

check("§7 the drag payload keeps its four fields (no third dialect travelled with the elevation)",
      "PANE_DRAG_MIME" in FAMILY
      and "\"source\": source if source in PANE_SOURCES else SOURCE_REMOTE" in FAMILY)

check("§7 §5's four-pair dispatch kept its four rows (the elevation added no fifth)",
      "SOURCE_ELEVATED" not in pane_func_body("_queue_batch_item", ROOT)
      and "SOURCE_ELEVATED" not in pane_func_body("_batch_provider", ROOT)
      and "SOURCE_ELEVATED" not in pane_func_body("_pane_source", ROOT))

check("§7 the container's shipped surface is unchanged (the elevation ADDS two methods)",
      all(name in FAMILY for name in ("def set_worker(", "def relist_dir(", "def relist_pane(",
                                       "def pane_for_provider(", "def send_targets(",
                                       "def can_use_local(", "def can_elevate(",
                                       "def set_transport(", "def transport(")))

check("§7 the elevation never imports the facade module (no cycle)",
      "import modules.sftp_tab" not in open(os.path.join(ROOT, "modules",
                                                         "sftp_pane_elevated.py"),
                                            encoding="utf-8").read()
      and "from .sftp_tab" not in open(os.path.join(ROOT, "modules", "sftp_pane_elevated.py"),
                                       encoding="utf-8").read())

check("§7 the elevated pane's provider is started by the pane and stopped by its release()",
      "provider.start()" in pane_func_body("_on_elevation_ready", ROOT)
      and "provider.shutdown(" in pane_func_body("_release_elevated", ROOT))

# ════════════════════════════════════════════════════════════
print("== 8. acceptance (ELEVATED_PANE.md §8) ==")
# ════════════════════════════════════════════════════════════

check("§8 the frozen contract and its two gates are in the tree",
      os.path.isfile(CONTRACT)
      and os.path.isfile(os.path.join(ROOT, "tests", "test_elevated_pane.py"))
      and os.path.isfile(os.path.join(ROOT, "tests", "test_elevated_pane_contract.py")))

check("§8 the contract declares the read-only half and the ONE refusal it ships",
      "READ-ONLY" in CONTRACT_TEXT
      and "sftp.elevated.read_only" in CONTRACT_TEXT
      and "SEPARATE version" in CONTRACT_TEXT)

_IMPORTS = [ln.strip() for ln in _HANDSHAKE.splitlines()
            if ln.strip().startswith(("import ", "from "))]
check("§8 no new dependency came with the feature (stdlib, PySide6 and the shipped paramiko)",
      all(any(token in ln for token in ("re", "threading", "time", "typing", "logging", "PySide6",
                                        "paramiko", "logger"))
          for ln in _IMPORTS),
      str(_IMPORTS))
check("§8 VERSION_FORMAT stays the shipped 0.9 (an elevation is not project state)",
      __import__("version").VERSION_FORMAT == "0.9")

check("§8 the documents name the contract (the reference docs point a reader at it)",
      "ELEVATED_PANE.md" in open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8").read()
      and "ELEVATED_PANE.md" in open(os.path.join(ROOT, "DOCUMENTATION.md"),
                                     encoding="utf-8").read())

check_release_state(ROOT)

finish()
