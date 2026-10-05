# -*- coding: utf-8 -*-
"""The ONE connect builder — every site that opens an SSH session goes through it (AGENTS.md §4.4).

`build_connect_kwargs()` is the PURE branch table: a KEY authenticates first with the password as the
LAST method paramiko tries, a PASSWORD alone refuses to poll the local keys or the ssh-agent, and
neither falls back to the shipped key/agent pair. `connect_client()` is the live half — ONE
`paramiko.SSHClient` with the application's known-hosts policy applied (TOFU on a new key, a refusal
on a CHANGED one) and ONE `connect()` call — and it answers the `(client, policy)` pair, because the
FIRST connection to a host is the one that reports the fingerprint it trusted. A caller keeps its own
timeouts and its own error handling: the builder owns the ARGUMENTS, never the failure, and a password
never reaches a log, a file or an argv. Tests — `tests/test_ssh_connect.py`; mechanism — §16."""

#: The timeout of the two INTERACTIVE sites — the terminal session and the worker beside it.
CONNECT_TIMEOUT_S = 15

try:
    from . import host_key_policy as _host_key_policy
except ImportError:  # flat launch from the project root
    import host_key_policy as _host_key_policy


def build_connect_kwargs(host, user, port, password="", key_path="",
                         timeout=CONNECT_TIMEOUT_S, banner_timeout=None, auth_timeout=None) -> dict:
    """The `paramiko.SSHClient.connect()` arguments of ONE endpoint (PURE).

    THREE branches, and they are the whole contract:
    * a KEY (`key_path`) → `key_filename` beside `look_for_keys=False` / `allow_agent=True`, with the
      password passed as well (`None` when there is none — paramiko tries it LAST, so a host that
      refuses the key alone still authenticates, and a key-only host is untouched);
    * a PASSWORD without a key → `look_for_keys=False` / `allow_agent=False`: no local key and no
      agent is polled before the attempt;
    * neither → the shipped key/agent fallback (`True` / `True`).
    `banner_timeout` / `auth_timeout` travel ONLY when the caller declares them: the diagnostic paths
    bound a black-holed host with all three, the interactive ones ship `timeout` alone.
    """
    kwargs = {"hostname": host, "username": user, "port": port, "timeout": timeout}
    if banner_timeout is not None:
        kwargs["banner_timeout"] = banner_timeout
    if auth_timeout is not None:
        kwargs["auth_timeout"] = auth_timeout
    if key_path:
        kwargs.update(key_filename=key_path, password=(password or None),
                      look_for_keys=False, allow_agent=True)
    elif password:
        kwargs.update(password=password, look_for_keys=False, allow_agent=False)
    else:
        kwargs.update(look_for_keys=True, allow_agent=True)
    return kwargs


def connect_client(host, user, port, password="", key_path="", client=None,
                   timeout=CONNECT_TIMEOUT_S, banner_timeout=None, auth_timeout=None):
    """A CONNECTED client with the application's known-hosts policy applied.

    Answers `(client, policy)`: the caller keeps the policy, because a FIRST connection is the one
    that reports what it trusted (`accepted_new_key`, `last_fingerprint`) and whether the key really
    reached the store (`pinned` — an unreadable file remembers nothing, and the caller says so).
    `client` may be handed IN — the two sites that close their client in a `finally:` build it before
    the `try` — otherwise one is created here through the `paramiko` ATTRIBUTE, so a suite that
    substitutes the class sees the very client the application would use. Never swallows anything:
    every failure is the caller's (a translated sentence, a result object, a closed client).
    """
    import paramiko
    if client is None:
        client = paramiko.SSHClient()
    policy = _host_key_policy.SshKnownHostsPolicy(hostname=host, port=port)
    policy.apply_to_client(client)
    client.connect(**build_connect_kwargs(host, user, port, password, key_path,
                                          timeout=timeout, banner_timeout=banner_timeout,
                                          auth_timeout=auth_timeout))
    return client, policy
