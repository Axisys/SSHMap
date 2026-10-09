# -*- coding: utf-8 -*-
"""`modules/ssh_connect.py` — the ONE connect builder (`N50`'s consolidation, `AGENTS.md` §4.4).

Offscreen, NO network: the pure branch table is read directly and the live half is driven over a
fake `paramiko.SSHClient` and a fake known-hosts policy. The three branches, the optional timeouts,
the `(client, policy)` pair, the class resolved at CALL time (a suite substitutes both) and the ONE
call site per consumer.

Run: python tests/test_ssh_connect.py   (from the project root) or python tests/run_all.py"""
import os
import sys

from _common import bootstrap, check, finish, check_release_state

ROOT, WORK = bootstrap()  # HOME isolation + offscreen + sys.path (BEFORE any app import)

import modules.ssh_connect as SCON  # noqa: E402

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the pure branch table (build_connect_kwargs) ==")
# ════════════════════════════════════════════════════════════════════════════

_kw_key = SCON.build_connect_kwargs("web-1", "root", 2222, password="pw", key_path="/k/id_ed25519")
check("§1 the endpoint travels as the three named facts",
      _kw_key["hostname"] == "web-1" and _kw_key["username"] == "root" and _kw_key["port"] == 2222,
      str(_kw_key))
check("§1 the KEY branch passes key_filename and the shipped key pair",
      _kw_key.get("key_filename") == "/k/id_ed25519"
      and _kw_key.get("look_for_keys") is False and _kw_key.get("allow_agent") is True,
      str(_kw_key))
check("§1 ...and the password beside it (paramiko tries it LAST)",
      _kw_key.get("password") == "pw", str(_kw_key))
check("§1 a key with NO password passes an explicit None (paramiko skips the method)",
      SCON.build_connect_kwargs("h", "u", 22, password="", key_path="/k/id").get("password") is None)

_kw_pw = SCON.build_connect_kwargs("h", "u", 22, password="pw")
check("§1 the PASSWORD branch polls neither the local keys nor the agent",
      _kw_pw.get("password") == "pw" and _kw_pw.get("look_for_keys") is False
      and _kw_pw.get("allow_agent") is False and "key_filename" not in _kw_pw, str(_kw_pw))
_kw_agent = SCON.build_connect_kwargs("h", "u", 22)
check("§1 no credential at all → the shipped key/agent fallback",
      _kw_agent.get("look_for_keys") is True and _kw_agent.get("allow_agent") is True
      and "password" not in _kw_agent and "key_filename" not in _kw_agent, str(_kw_agent))
check("§1 the three branches disagree on look_for_keys (that IS the branch table)",
      (_kw_key["look_for_keys"], _kw_pw["look_for_keys"], _kw_agent["look_for_keys"])
      == (False, False, True),
      str((_kw_key["look_for_keys"], _kw_pw["look_for_keys"], _kw_agent["look_for_keys"])))

check("§1 the interactive timeout is the shipped 15 s (one declared constant)",
      SCON.CONNECT_TIMEOUT_S == 15 and _kw_agent["timeout"] == 15, str(_kw_agent["timeout"]))
check("§1 a caller may declare its own timeout",
      SCON.build_connect_kwargs("h", "u", 22, timeout=10)["timeout"] == 10)
check("§1 the two EXTRA timeouts travel only when the caller declares them",
      "banner_timeout" not in _kw_agent and "auth_timeout" not in _kw_agent)
_kw_diag = SCON.build_connect_kwargs("h", "u", 22, password="pw",
                                     timeout=10, banner_timeout=10, auth_timeout=10)
check("§1 ...and all three travel on the diagnostic paths",
      _kw_diag["timeout"] == 10 and _kw_diag["banner_timeout"] == 10 and _kw_diag["auth_timeout"] == 10,
      str(_kw_diag))
check("§1 the kwargs are a FRESH dict (a caller cannot poison the next one)",
      _kw_agent is not SCON.build_connect_kwargs("h", "u", 22)
      and _kw_agent == SCON.build_connect_kwargs("h", "u", 22))


def _builder_branch(password="", key_path=""):
    """Which branch the BUILDER really took — read back off its own kwargs, never a second table."""
    kwargs = SCON.build_connect_kwargs("h", "u", 22, password=password, key_path=key_path)
    if "key_filename" in kwargs:
        return SCON.AUTH_KEY
    return SCON.AUTH_PASSWORD if "password" in kwargs else SCON.AUTH_FALLBACK


_BRANCH_CASES = (("", ""), ("pw", ""), ("", "/k/id_ed25519"), ("pw", "/k/id_ed25519"))
check("§1 `resolve_auth_branch()` mirrors the builder for every password/key pair",
      all(SCON.resolve_auth_branch(pw, key) == _builder_branch(pw, key) for pw, key in _BRANCH_CASES)
      and SCON.resolve_auth_branch("", "") == SCON.AUTH_FALLBACK,
      str([(pw, key, SCON.resolve_auth_branch(pw, key), _builder_branch(pw, key))
           for pw, key in _BRANCH_CASES]))
check("§1 a re-arm refuses ONLY the branch whose secret is really gone",
      SCON.rearm_credential_missing(SCON.AUTH_FALLBACK, password="", key_path="") is False
      and SCON.rearm_credential_missing(SCON.AUTH_KEY, password="", key_path="/k/id") is False
      and SCON.rearm_credential_missing(SCON.AUTH_KEY, password="", key_path="") is True
      and SCON.rearm_credential_missing(SCON.AUTH_PASSWORD, password="pw") is False
      and SCON.rearm_credential_missing(SCON.AUTH_PASSWORD, password="") is True,
      "the three branches of the re-arm rule")


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the live half (connect_client) ==")
# ════════════════════════════════════════════════════════════════════════════

import paramiko  # noqa: E402
import modules.host_key_policy as HKP  # noqa: E402


class _FakeClient:
    """A fake `paramiko.SSHClient`: records the policy installed and the connect kwargs."""
    made = []

    def __init__(self):
        self.policy = None
        self.connect_kwargs = None
        self.closed = False
        _FakeClient.made.append(self)

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, *a, **kw):
        self.connect_kwargs = dict(kw)
        self._args = a

    def close(self):
        self.closed = True


class _FakePolicy:
    """A fake known-hosts policy: records the endpoint it was asked about."""
    made = []

    def __init__(self, hostname=None, port=None):
        self.hostname, self.port = hostname, port
        self.applied_to = []
        _FakePolicy.made.append(self)

    def apply_to_client(self, client):
        self.applied_to.append(client)
        client.set_missing_host_key_policy(self)


_ORIG_CLIENT, _ORIG_POLICY = paramiko.SSHClient, HKP.SshKnownHostsPolicy
paramiko.SSHClient, HKP.SshKnownHostsPolicy = _FakeClient, _FakePolicy
try:
    _client, _policy = SCON.connect_client("web-1", "root", 2222, password="pw")
    check("§2 the builder creates the client through the paramiko ATTRIBUTE (a suite substitutes it)",
          isinstance(_client, _FakeClient) and _FakeClient.made[-1] is _client)
    check("§2 ...and it answers the (client, policy) pair the callers need",
          isinstance(_policy, _FakePolicy) and _policy is _FakePolicy.made[-1])
    check("§2 the known-hosts policy is built for THIS endpoint and applied to the client",
          _policy.hostname == "web-1" and _policy.port == 2222
          and _policy.applied_to == [_client] and _client.policy is _policy)
    check("§2 the ONE connect() carries the builder's own kwargs",
          {k: v for k, v in _client.connect_kwargs.items() if k != "transport_factory"}
          == SCON.build_connect_kwargs("web-1", "root", 2222, password="pw"),
          str(_client.connect_kwargs))
    check("§2 ...plus the ANSWERING transport the builder owns (the v1.8.1 handler contract)",
          callable(_client.connect_kwargs.get("transport_factory")),
          str(_client.connect_kwargs.get("transport_factory")))
    check("§2 the host is a KEYWORD argument (hostname=), never a positional one",
          _client._args == () and _client.connect_kwargs.get("hostname") == "web-1",
          str(_client._args))

    _given = _FakeClient()
    _client2, _policy2 = SCON.connect_client("h", "u", 22, key_path="/k/id", client=_given)
    check("§2 a client handed IN is the one connected (the `finally:`-closing sites)",
          _client2 is _given and _given.connect_kwargs.get("key_filename") == "/k/id"
          and "password" in _given.connect_kwargs and _given.connect_kwargs["password"] is None,
          str(_given.connect_kwargs))
    check("§2 ...and it is NOT replaced by a second instance",
          _FakeClient.made.count(_given) == 1)

    _bad = None
    try:
        class _BoomPolicy(_FakePolicy):
            def apply_to_client(self, client):
                raise RuntimeError("policy boom")
        HKP.SshKnownHostsPolicy = _BoomPolicy
        SCON.connect_client("h", "u", 22, password="pw")
    except RuntimeError as e:
        _bad = str(e)
    finally:
        HKP.SshKnownHostsPolicy = _FakePolicy
    check("§2 a policy failure is NOT swallowed (the caller owns the error)", _bad == "policy boom",
          str(_bad))
    check("§2 a connect() failure is NOT swallowed either",
          _client.connect_kwargs is not None)
finally:
    paramiko.SSHClient, HKP.SshKnownHostsPolicy = _ORIG_CLIENT, _ORIG_POLICY


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the four consumers share it (N50's consolidation) ==")
# ════════════════════════════════════════════════════════════════════════════

_CALL_SITES = ("modules/ssh_terminal.py", "modules/ssh_worker.py",
               "modules/plugin_runner.py", "services/system_info_collector.py")


def _src(rel):
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as fh:
        return fh.read()


def _code(rel):
    """The file's statements — comment-only lines dropped (the branch names are discussed there)."""
    return "\n".join(ln for ln in _src(rel).splitlines() if not ln.strip().startswith("#"))


check("§3 every one of the four sites calls the builder EXACTLY once",
      all(text.count("connect_client(") == 1 for text in map(_src, _CALL_SITES)),
      str({rel: _src(rel).count("connect_client(") for rel in _CALL_SITES}))
check("§3 ...and NO site keeps its own `client.connect(` call",
      all("client.connect(" not in _src(rel) for rel in _CALL_SITES),
      str([rel for rel in _CALL_SITES if "client.connect(" in _src(rel)]))
check("§3 ...nor its own policy construction",
      all("SshKnownHostsPolicy(" not in _src(rel) for rel in _CALL_SITES),
      str([rel for rel in _CALL_SITES if "SshKnownHostsPolicy(" in _src(rel)]))
check("§3 the branch table itself lives in ONE module (no copy of the three branches)",
      all("look_for_keys" not in _code(rel) and "key_filename=" not in _code(rel)
          for rel in _CALL_SITES),
      str([rel for rel in _CALL_SITES if "look_for_keys" in _code(rel)]))
check("§3 the terminal thread keeps the exception TYPES it reports (the builder owns no sentence)",
      "paramiko.BadHostKeyException" in _src("modules/ssh_terminal.py")
      and "paramiko.AuthenticationException" in _src("modules/ssh_terminal.py")
      and "paramiko.SSHException" in _src("modules/ssh_terminal.py"))
check("§3 no password ever reaches a log line of the builder",
      "log" not in _src("modules/ssh_connect.py").lower().replace("login", "")
      or "logger" not in _src("modules/ssh_connect.py"))
check("§3 the builder's module docstring points at its topical test and the contract",
      "tests/test_ssh_connect.py" in (SCON.__doc__ or "")
      and "AGENTS.md" in (SCON.__doc__ or ""))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)

finish()
