# -*- coding: utf-8 -*-
"""v1.8.1 — the trust and keys surface: the first connection ASKS, the store is manageable, a credential
is bound to its endpoint, and a second factor (or a key's passphrase) can be answered.

Offscreen and hermetic: the pure readers are read directly, the credential store is an in-memory fake, the
known_hosts store is a temp file, and the live half runs against an IN-PROCESS paramiko server (a real
transport, `AUTH_PARTIALLY_SUCCESSFUL` after the key and a keyboard-interactive query) — never a network.

Run: python tests/test_trust_surface.py   (from the project root) or python tests/run_all.py"""
import os
import socket
import sys
import threading
import time

from _common import bootstrap, check, finish, check_release_state

ROOT, WORK = bootstrap()  # HOME isolation + offscreen + sys.path (BEFORE any app import)

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import paramiko  # noqa: E402
import modules.host_key_policy as HKP  # noqa: E402
import modules.interactive_ask as IA  # noqa: E402
import modules.local_paths as LP  # noqa: E402
import modules.ssh_connect as SCON  # noqa: E402
import services.credential_manager as CM  # noqa: E402


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the local-path resolver (one reader, `~` and relative paths) ==")
# ════════════════════════════════════════════════════════════════════════════

_HOME = os.path.expanduser("~")
check("§1 an empty value is 'no path', never a directory",
      LP.resolve_local_path("") == "" and LP.resolve_local_path(None) == "")
check("§1 `~` is expanded through the platform",
      LP.resolve_local_path("~") == _HOME
      and LP.resolve_local_path("~/keys/id_ed25519")
      == os.path.join(_HOME, "keys", "id_ed25519"), LP.resolve_local_path("~/keys/id_ed25519"))
check("§1 a RELATIVE path is joined to the caller's base directory",
      LP.resolve_local_path("keys/id", base_dir=os.path.join("C:", os.sep, "base"))
      == os.path.normpath(os.path.join("C:" + os.sep, "base", "keys", "id")),
      LP.resolve_local_path("keys/id", base_dir=os.path.join("C:", os.sep, "base")))
check("§1 ...and to the process's current directory without one",
      os.path.isabs(LP.resolve_local_path("keys/id")))
_abs = os.path.join(os.sep, "k", "id_ed25519")
check("§1 an ABSOLUTE path is answered byte for byte (never re-normalised)",
      LP.resolve_local_path(_abs) == _abs, LP.resolve_local_path(_abs))
check("§1 the function never raises on a hostile value",
      isinstance(LP.resolve_local_path(b"x"), str) and LP.resolve_local_path(object()) != "",
      repr(LP.resolve_local_path(b"x")))
check("§1 the builder resolves `key_path` through it (the ONE connect path)",
      SCON.build_connect_kwargs("h", "u", 22, key_path="~/k/id").get("key_filename")
      == os.path.join(_HOME, "k", "id"),
      str(SCON.build_connect_kwargs("h", "u", 22, key_path="~/k/id").get("key_filename")))


# ════════════════════════════════════════════════════════════════════════════
print("== §2 N47 — a stored credential belongs to the endpoint it was saved for ==")
# ════════════════════════════════════════════════════════════════════════════

check("§2 the ONE spelling of an endpoint is `user@host:port` (PURE)",
      CM.endpoint_scope("root", "web-1", 2222) == "root@web-1:2222"
      and CM.endpoint_scope("root", "web-1", None) == "root@web-1:22"
      and CM.endpoint_scope(" root ", " web-1 ", 0) == "root@web-1:22",
      CM.endpoint_scope("root", "web-1", None))


class _Node:
    def __init__(self, user="root", host="web-1", ssh_port=22, port=None):
        self.user, self.host, self.ssh_port = user, host, ssh_port
        if port is not None:
            self.port = port


check("§2 a node-like record answers its own scope (the call sites' ONE helper)",
      CM.node_scope(_Node()) == "root@web-1:22"
      and CM.node_scope(None) == "" and CM.node_scope(object()) != ""
      and CM.node_scope(_Node(port=2222, ssh_port=None)) == "root@web-1:2222",
      CM.node_scope(_Node(port=2222, ssh_port=None)))


class _FakeBackend:
    """An in-memory stand-in for wincred — the suite never touches the real credential store."""

    def __init__(self):
        self.store = {}
        self.deleted = []

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, value):
        self.store[(service, username)] = value

    def delete_password(self, service, username):
        self.deleted.append((service, username))
        self.store.pop((service, username), None)


def _cm():
    manager = CM.CredentialManager.__new__(CM.CredentialManager)
    manager._keyring_backend = _FakeBackend()
    manager._backend_available = True
    return manager


_c = _cm()
check("§2 a save with a scope stores the secret AND the endpoint",
      _c.save_password("snode001", "S3cret!", scope="root@prod-db:22") is True
      and _c.load_password("snode001", scope="root@prod-db:22") == "S3cret!")
check("§2 ...and a MATCHING endpoint gets the password back",
      _c.load_password("snode001", scope=CM.endpoint_scope("root", "prod-db", 22)) == "S3cret!")
check("§2 a DIFFERENT endpoint gets NOTHING (the silent wrong-host injection is closed)",
      _c.load_password("snode001", scope="root@attacker.example:22") is None)
check("§2 the refusal is reported, not silent: the stored scope is readable",
      _c.stored_scope("snode001") == "root@prod-db:22")
check("§2 the unscoped read still answers the secret (the callers that have no endpoint)",
      _c.load_password("snode001") == "S3cret!" and _c.load_password("snode001", scope="") == "S3cret!")
check("§2 delete drops the secret AND its scope",
      _c.delete_password("snode001") is True
      and _c.load_password("snode001") is None and _c.stored_scope("snode001") == "")

_legacy = _cm()
_legacy._keyring_backend.store[("sshmap:old1", "old1")] = "LegacyPw"
check("§2 a LEGACY entry (no scope) is adopted once for the endpoint that reads it",
      _legacy.load_password("old1", scope="root@web-9:22") == "LegacyPw"
      and _legacy.stored_scope("old1") == "root@web-9:22")
check("§2 ...and the adoption is the LAST time it is host-agnostic (a second host is refused)",
      _legacy.load_password("old1", scope="root@other:22") is None)

_prof = _cm()
check("§2 the PROFILE family stays host-agnostic (a reusable credential, never scoped)",
      _prof.save_password("profile:p1", "ProfPw") is True
      and _prof.stored_scope("profile:p1") == ""
      and _prof.load_password("profile:p1", scope="anyone@anywhere:22") == "ProfPw")
_offline = _cm()
_offline._backend_available = False
check("§2 a refused/unavailable backend still refuses the write (the allowlist is untouched)",
      _offline.save_password("x", "y") is False and _offline.load_password("x", scope="a@b:22") is None
      and _offline.delete_password("x") is True)


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the host-key store: the ask, the refusal, the edits ==")
# ════════════════════════════════════════════════════════════════════════════

STORE_PATH = os.path.join(str(WORK), "known_hosts_v181")
HKP.set_store(HKP.KnownHostsStore(STORE_PATH))
KEY_A = paramiko.ECDSAKey.generate()
KEY_B = paramiko.ECDSAKey.generate()

check("§3 the entry name of an endpoint is ONE pure reader",
      HKP.entry_name_for("web-1", 22) == "web-1"
      and HKP.entry_name_for("web-1", 2222) == "[web-1]:2222"
      and HKP.entry_name_for("", 22) == "unknown"
      and HKP.entry_name_for("web-1", "x") == "web-1")
check("§3 the fingerprint is the OpenSSH SHA256 form",
      HKP.fingerprint(KEY_A).startswith("SHA256:") and HKP.fingerprint(KEY_A) != HKP.fingerprint(KEY_B))

_asked = []
IA.set_answerer(lambda req: (_asked.append(req), True)[1])
_policy = HKP.SshKnownHostsPolicy("h-accept", 22)
_policy.missing_host_key(None, "h-accept", KEY_A)
check("§3 a first connection ASKS (the prompt carries the algorithm and the fingerprint)",
      len(_asked) == 1 and _asked[0].kind == IA.KIND_HOST_KEY
      and _asked[0].fields["host"] == "h-accept"
      and _asked[0].fields["keytype"] == KEY_A.get_name()
      and _asked[0].fields["fingerprint"] == HKP.fingerprint(KEY_A), repr(_asked[:1]))
check("§3 an ACCEPTED key is accepted and pinned",
      _policy.accepted_new_key is True and _policy.pinned is True
      and HKP.get_store().lookup("h-accept") is not None)

_asked.clear()
IA.set_answerer(lambda req: (_asked.append(req), False)[1])
_policy_no = HKP.SshKnownHostsPolicy("h-reject", 22)
_raised = ""
try:
    _policy_no.missing_host_key(None, "h-reject", KEY_A)
except HKP.HostKeyRejected as e:
    _raised = str(e)
except Exception as e:  # noqa: BLE001
    _raised = f"WRONG TYPE {type(e).__name__}"
check("§3 a REJECTED key raises HostKeyRejected with a translated sentence",
      _raised and "WRONG TYPE" not in _raised and "h-reject" in _raised, _raised)
check("§3 ...and NOTHING is recorded for it",
      _policy_no.pinned is False and HKP.get_store().lookup("h-reject") is None)

_asked.clear()
IA.set_answerer(None)
_policy_default = HKP.SshKnownHostsPolicy("h-nosurface", 22)
_policy_default.missing_host_key(None, "h-nosurface", KEY_A)
check("§3 without a surface the shipped TOFU fallback accepts (the declared, unchanged behaviour)",
      _policy_default.accepted_new_key is True and _policy_default.pinned is True
      and not _asked, repr(_asked))

_marker = []
IA.set_answerer(lambda req: (_marker.append(req), True)[1])
_exc = paramiko.BadHostKeyException("h-changed", KEY_B, KEY_A)
_replaced = HKP.resolve_changed_key(_exc, "h-changed", 22)
check("§3 a CHANGED key asks with BOTH fingerprints",
      len(_marker) == 1 and _marker[0].kind == IA.KIND_CHANGED_KEY
      and _marker[0].fields["expected"] == HKP.fingerprint(KEY_A)
      and _marker[0].fields["fingerprint"] == HKP.fingerprint(KEY_B), repr(_marker[:1]))
check("§3 ...and a yes REPLACES the stored entry (only a real write answers True)",
      _replaced is True
      and HKP.fingerprint(HKP.get_store().lookup("h-changed")[KEY_B.get_name()])
      == HKP.fingerprint(KEY_B))
IA.set_answerer(lambda req: False)
check("§3 ...and a no leaves the store alone",
      HKP.resolve_changed_key(paramiko.BadHostKeyException("h-changed", KEY_A, KEY_B),
                              "h-changed", 22) is False)
check("§3 an exception without the two keys answers False (never a crash)",
      HKP.resolve_changed_key(ValueError("nope"), "h", 22) is False)

_store = HKP.get_store()
KEY_RSA = paramiko.RSAKey.generate(1024)
check("§3 a host with TWO algorithms is recorded twice (a keytype is replaced, not added)",
      _store.pin("multi", KEY_A.get_name(), KEY_A)
      and _store.pin("multi", KEY_RSA.get_name(), KEY_RSA)
      and len(_store.lookup("multi")) == 2, str(list((_store.lookup("multi") or {}).keys())))
check("§3 delete ONE fingerprint keeps the other keytype of the same host",
      _store.remove("multi", KEY_A.get_name()) is True
      and list(_store.lookup("multi")) == [KEY_RSA.get_name()])
check("§3 delete the WHOLE entry drops the host",
      _store.remove("multi") is True and _store.lookup("multi") is None)
check("§3 deleting an unknown entry answers False (nothing to publish)",
      _store.remove("never-seen") is False and _store.remove("never-seen", "ssh-rsa") is False)


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the connect builder: the passphrase, the code, the handler contract ==")
# ════════════════════════════════════════════════════════════════════════════

_kw_key = SCON.build_connect_kwargs("h", "u", 22, password="pw", key_path="/k/id",
                                    passphrase="pp", verification_code="123456")
check("§4 the verification code WINS over the password in the KEY branch (V2 of N63)",
      _kw_key.get("password") == "123456", str(_kw_key.get("password")))
check("§4 the passphrase travels as its OWN argument — never through the password alias",
      _kw_key.get("passphrase") == "pp" and _kw_key.get("password") != "pp")
check("§4 no passphrase → no `passphrase` key at all (paramiko's own fallback stays)",
      "passphrase" not in SCON.build_connect_kwargs("h", "u", 22, key_path="/k/id"))
check("§4 the PASSWORD branch never carries a passphrase or a code",
      "passphrase" not in SCON.build_connect_kwargs("h", "u", 22, password="pw", passphrase="pp")
      and SCON.build_connect_kwargs("h", "u", 22, password="pw")["password"] == "pw")
check("§4 a transport_factory travels only when the caller declares one",
      "transport_factory" not in SCON.build_connect_kwargs("h", "u", 22)
      and "transport_factory" in SCON.build_connect_kwargs("h", "u", 22, transport_factory=lambda *a: None))

_factory = SCON.interactive_transport_factory("h", "u", 22)
_transport_cls = None
for _cell in (_factory.__closure__ or ()):
    if isinstance(_cell.cell_contents, type) and issubclass(_cell.cell_contents, paramiko.Transport):
        _transport_cls = _cell.cell_contents
check("§4 the handler contract is a paramiko.Transport subclass (the ONE seam `connect()` exposes)",
      _transport_cls is not None
      and _transport_cls.auth_interactive_dumb is not paramiko.Transport.auth_interactive_dumb
      and _transport_cls.auth_interactive is not paramiko.Transport.auth_interactive,
      str(_transport_cls))

_ENCRYPTED = os.path.join(str(WORK), "id_enc")
_PLAIN = os.path.join(str(WORK), "id_plain")
paramiko.RSAKey.generate(1024).write_private_key_file(_ENCRYPTED, password="pp")
paramiko.RSAKey.generate(1024).write_private_key_file(_PLAIN)
check("§4 `key_needs_passphrase` reads the FILE, so the ask happens only when it is needed",
      SCON.key_needs_passphrase(_ENCRYPTED) is True
      and SCON.key_needs_passphrase(_PLAIN) is False
      and SCON.key_needs_passphrase(os.path.join(str(WORK), "missing")) is False)
check("§4 ...and it expands `~` through the same resolver",
      SCON.key_needs_passphrase("~/definitely-missing-key") is False)

_asked.clear()
IA.set_answerer(lambda req: (_asked.append(req), "pp")[1])
check("§4 an encrypted key WITH no password asks for its passphrase (the pre-flight ask)",
      SCON.resolve_passphrase("h", "u", 22, _ENCRYPTED) == "pp"
      and _asked and _asked[0].kind == IA.KIND_KEY_PASSPHRASE
      and _asked[0].fields["key_path"] == _ENCRYPTED, repr(_asked[:1]))
_asked.clear()
check("§4 a password (paramiko's own alias) or a given passphrase SKIPS the ask",
      SCON.resolve_passphrase("h", "u", 22, _ENCRYPTED, password="pw") == ""
      and SCON.resolve_passphrase("h", "u", 22, _ENCRYPTED, passphrase="given") == "given"
      and not _asked)
IA.set_answerer(lambda req: None)
_cancelled = ""
try:
    SCON.resolve_passphrase("h", "u", 22, _ENCRYPTED)
except SCON.ConnectionCancelled as e:
    _cancelled = str(e)
check("§4 an UNANSWERED passphrase is an honest refusal, not a paramiko PasswordRequiredException",
      "h" in _cancelled and "cancelled" in _cancelled.lower(), _cancelled)

_fake_made = []


class _RetryClient:
    """A client that raises the CHANGED-key failure on the FIRST connect overall, then succeeds."""

    attempts = 0

    def __init__(self):
        self.policy = None
        self.host_keys = paramiko.HostKeys()
        self.closed = False
        _fake_made.append(self)

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def get_host_keys(self):
        return self.host_keys

    def connect(self, *a, **kw):
        _RetryClient.attempts += 1
        if _RetryClient.attempts == 1:
            raise paramiko.BadHostKeyException("h-retry", KEY_B, KEY_A)

    def close(self):
        self.closed = True


IA.set_answerer(lambda req: True)
_ORIG_CLIENT = paramiko.SSHClient
_RetryClient.attempts = 0
paramiko.SSHClient = _RetryClient
try:
    _client, _pol = SCON.connect_client("h-retry", "u", 22, key_path="/k/id")
    _ok = True
except Exception as e:  # noqa: BLE001
    _ok, _client = False, f"{type(e).__name__}: {e}"
finally:
    paramiko.SSHClient = _ORIG_CLIENT
check("§4 a CHANGED key the user replaced is retried ONCE on a FRESH client",
      _ok and len(_fake_made) == 2 and _RetryClient.attempts == 2 and _fake_made[0].closed is True,
      f"ok={_ok} made={len(_fake_made)} attempts={_RetryClient.attempts} {_client}")
check("§4 ...and the replaced key really reached the store",
      HKP.get_store().lookup("h-retry") is not None)


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the REAL second factor on an in-process paramiko server ==")
# ════════════════════════════════════════════════════════════════════════════

HOST_KEY = paramiko.RSAKey.generate(2048)
USER_KEY = paramiko.RSAKey.generate(2048)
USER_KEY_FILE = os.path.join(str(WORK), "id_2fa")
USER_KEY.write_private_key_file(USER_KEY_FILE)
CODE = "654321"
SESSIONS = []


class _TwoFactorServer(paramiko.ServerInterface):
    """A key is accepted PARTIALLY and the second factor is a keyboard-interactive query."""

    def __init__(self):
        self.events = []

    def check_auth_publickey(self, username, key):
        self.events.append("publickey")
        return paramiko.AUTH_PARTIALLY_SUCCESSFUL

    def check_auth_interactive(self, username, submethods):
        self.events.append("keyboard-interactive")
        return paramiko.InteractiveQuery("Verification code", "Enter the code", ("Code: ", False))

    def check_auth_interactive_response(self, responses):
        self.events.append(f"answers={list(responses)}")
        return paramiko.AUTH_SUCCESSFUL if list(responses) == [CODE] else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "publickey,keyboard-interactive"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED


_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_listener.bind(("127.0.0.1", 0))
SERVER_PORT = _listener.getsockname()[1]
_listener.listen(8)


def _handle(conn):
    try:
        transport = paramiko.Transport(conn)
        transport.add_server_key(HOST_KEY)
        server = _TwoFactorServer()
        SESSIONS.append(server)
        transport.start_server(server=server)
        event = threading.Event()
        transport.completion_event = event
        event.wait(30)
    except Exception:  # noqa: BLE001 — the harness must not crash the test
        pass


def _serve():
    while True:
        try:
            conn, _addr = _listener.accept()
        except OSError:
            return
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


threading.Thread(target=_serve, daemon=True).start()


def _connect_offthread(**kwargs):
    """Run `connect_client` on a worker while the GUI thread pumps — the REAL marshal shape."""
    box = {}

    def _worker():
        try:
            box["client"], box["policy"] = SCON.connect_client(
                "127.0.0.1", "root", SERVER_PORT, timeout=10, **kwargs)
        except BaseException as e:  # noqa: BLE001 — the failure IS the result here
            box["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while thread.is_alive() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    thread.join(3)
    return box


_surface_calls = []


def _surface(req):
    _surface_calls.append(req.kind)
    if req.kind == IA.KIND_HOST_KEY:
        return True
    if req.kind == IA.KIND_SECOND_FACTOR:
        return CODE
    return None


IA.set_answerer(_surface)
_box = _connect_offthread(key_path=USER_KEY_FILE)
check("§5 a KEY that returns AUTH_PARTIAL is answered by the USER, and the session authenticates",
      "client" in _box and "error" not in _box, str(_box.get("error"))[:180])
check("§5 ...the answer reached the server as the CODE (the handler's contract works end to end)",
      SESSIONS and "answers=['654321']" in SESSIONS[-1].events, str(SESSIONS[-1].events if SESSIONS else None))
check("§5 ...and the prompt was delivered to the GUI thread through the ask surface",
      IA.KIND_HOST_KEY in _surface_calls and IA.KIND_SECOND_FACTOR in _surface_calls,
      str(_surface_calls))
if "client" in _box:
    _box["client"].close()

IA.set_answerer(None)
_box2 = _connect_offthread(key_path=USER_KEY_FILE)
check("§5 without a surface the SAME server gives a TRANSLATED refusal — never EOFError, never a hang",
      "error" in _box2 and "ConnectionCancelled" in _box2["error"]
      and "EOFError" not in _box2["error"], str(_box2.get("error"))[:200])

_probe_key, _probe_err = HKP.read_server_host_key("127.0.0.1", SERVER_PORT, timeout=10)
check("§5 the manager's 'replace' reads the server's key WITHOUT authenticating",
      _probe_key is not None and not _probe_err
      and HKP.fingerprint(_probe_key) == HKP.fingerprint(HOST_KEY),
      f"{_probe_err} {HKP.fingerprint(_probe_key) if _probe_key else ''}")
_probe_missing, _missing_err = HKP.read_server_host_key("127.0.0.1", 1, timeout=2)
check("§5 ...and a refused read is data, never an exception",
      _probe_missing is None and bool(_missing_err), _missing_err)


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the windows of the surface (offscreen, no exec) ==")
# ════════════════════════════════════════════════════════════════════════════

import dialogs.host_key_dialog as HKD  # noqa: E402
import dialogs.auth_prompt_dialog as APD  # noqa: E402
import ui.trust_surface as TS  # noqa: E402

_rows = HKD.host_key_rows({"web-1": {KEY_A.get_name(): KEY_A},
                           "[db]:2222": {KEY_B.get_name(): KEY_B}})
check("§6 the manager's row model is PURE and carries the three facts",
      len(_rows) == 2 and set(_rows[0]) == {"host", "keytype", "fingerprint"}
      and _rows[0]["host"] == "[db]:2222" and "[db]:2222" in _rows[0]["fingerprint"] + _rows[0]["host"],
      str(_rows[:1]))
check("§6 a broken store object answers an empty list (never a crash)",
      HKD.host_key_rows(None) == [] and HKD.host_key_rows({"h": None}) == [])
check("§6 the `[host]:port` entry spelling is read back by ONE reader",
      HKD._split_entry("[db]:2222") == ("db", 2222) and HKD._split_entry("web-1") == ("web-1", 22)
      and HKD._split_entry("[db]:x") == ("db", 22))

_dlg = HKD.HostKeyDialog(None, host="web-1", port=22, keytype=KEY_A.get_name(),
                         fingerprint=HKP.fingerprint(KEY_A))
check("§6 the first-connection window builds and says it is the NEW-key case",
      _dlg.changed is False and _dlg.windowTitle() != "")
check("§6 ...and the answer in the policy's vocabulary is False until it is accepted",
      _dlg.asked_host_key() is False)
_dlg2 = HKD.HostKeyDialog(None, host="web-1", port=22, keytype=KEY_B.get_name(),
                          fingerprint=HKP.fingerprint(KEY_B), expected=HKP.fingerprint(KEY_A))
check("§6 the CHANGED-key case is the same window with the stored fingerprint beside the new one",
      _dlg2.changed is True and _dlg2.windowTitle() != _dlg.windowTitle())
_dlg.close()
_dlg2.close()

_mgr = HKD.KnownHostsManagerDialog(None, store=HKP.get_store())
check("§6 the manager lists what the store records",
      _mgr.table.rowCount() == len(HKD.host_key_rows(HKP.get_store().entries()))
      and _mgr.table.columnCount() == 3, str(_mgr.table.rowCount()))
check("§6 a row that exists enables the two edits; no selection disables them",
      _mgr.table.rowCount() > 0 and _mgr.selected_row() is None
      and _mgr.btn_delete.isEnabled() is False and _mgr.btn_replace.isEnabled() is False)
_mgr.table.setCurrentCell(0, 0)
_mgr._sync_buttons()
check("§6 ...and selecting one enables them",
      _mgr.selected_row() is not None and _mgr.btn_delete.isEnabled() is True
      and _mgr.btn_replace.isEnabled() is True, str(_mgr.selected_row()))
_mgr.close()

_prompt = APD.AuthPromptDialog(None, title="T", label="L", hint="H", secret=True)
check("§6 the credential prompt masks the field and answers the typed value",
      _prompt.value() == "" and _prompt.value_edit.echoMode().name == "Password")
_prompt.value_edit.setText("typed")
check("§6 ...and `value()` is that text",
      _prompt.value() == "typed")
_prompt.close()
check("§6 the surface dispatches an UNKNOWN kind to None (never a stray window)",
      TS.answer(IA.AskRequest("something-else", {})) is None)


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the ask primitive (the worker → GUI boundary) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§7 without an answerer an ask is None AT ONCE (the caller's declared fallback)",
      IA.set_answerer(None) is None and IA.has_answerer() is False
      and IA.ask(IA.KIND_HOST_KEY, host="h") is None)
_request = IA.AskRequest("k", {"a": 1})
_request.answer("v")
check("§7 the request object carries the kind, the fields and the answer",
      _request.result == "v" and _request.answered is True
      and _request.done.is_set() and _request.fields == {"a": 1})

_seen = []
IA.set_answerer(lambda req: (_seen.append(threading.current_thread().name), "ok")[1])
check("§7 on the GUI thread the answerer runs INLINE",
      IA.ask("k") == "ok" and _seen == [threading.current_thread().name], str(_seen))

_delivered = []


def _asking_thread():
    _delivered.append(("asked", threading.current_thread().name))
    _delivered.append(("answer", IA.ask("k", timeout=10)))


_worker = threading.Thread(target=_asking_thread, name="trust-worker")
_worker.start()
_deadline = time.time() + 10
while _worker.is_alive() and time.time() < _deadline:
    app.processEvents()
    time.sleep(0.01)
_worker.join(2)
check("§7 a WORKER's question is answered on the GUI thread (the §4.8 marshalling)",
      ("answer", "ok") in _delivered and len(_seen) == 2,
      f"delivered={_delivered} seen={_seen}")
def _boom(_request):
    raise RuntimeError("boom")


IA.set_answerer(_boom)
check("§7 a surface that raises is an UNANSWERED question, never a crashed connect thread",
      IA.ask("k") is None)
IA.set_answerer(lambda req: None)
check("§7 ...and a surface that answers None is the same answer",
      IA.ask("k") is None)
IA.set_answerer(None)


# ════════════════════════════════════════════════════════════════════════════
print("== §8 release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)

_listener.close()
finish()
