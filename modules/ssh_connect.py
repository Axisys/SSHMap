# -*- coding: utf-8 -*-
"""The ONE connect builder — every site that opens an SSH session goes through it (AGENTS.md §4.4).

`build_connect_kwargs()` is the PURE branch table: a KEY authenticates first with a password (or a
verification code) as the LAST method paramiko tries, a PASSWORD alone refuses to poll the local keys or
the ssh-agent, and neither falls back to the shipped key/agent pair. `connect_client()` is the live half —
ONE `paramiko.SSHClient` with the application's known-hosts policy applied, the ANSWERING transport that
owns the keyboard-interactive contract (a second factor is answered by the user, never by the process's
stdin) and the ONE retry after a CHANGED host key was replaced.

A caller keeps its own timeouts and its own error handling: the builder owns the ARGUMENTS, never the
failure, and a password, a passphrase or a code never reaches a log, a file or an argv.
Tests — `tests/test_ssh_connect.py`, `tests/test_trust_surface.py`; mechanism — §16."""

import os

import paramiko

try:
    from . import host_key_policy as _host_key_policy
    from . import interactive_ask as _ask
    from .local_paths import resolve_local_path
except ImportError:  # flat launch from the project root
    import host_key_policy as _host_key_policy
    import interactive_ask as _ask
    from local_paths import resolve_local_path

#: The timeout of the two INTERACTIVE sites — the terminal session and the worker beside it.
CONNECT_TIMEOUT_S = 15

#: ONE connect + ONE retry: the retry exists for a CHANGED host key the user chose to replace.
KEY_RETRY_ATTEMPTS = 2


def _t(key, **kwargs) -> str:
    """A translated sentence — the builder reports a rejection the user must be able to read."""
    try:
        from i18n import t as _translate
    except Exception:  # noqa: BLE001
        return key
    try:
        return _translate(key, **kwargs) if kwargs else _translate(key)
    except Exception:  # noqa: BLE001
        return key


class ConnectionCancelled(paramiko.SSHException):
    """The connection was cancelled BY THE USER — a refused host key, or an unanswered prompt.

    It is an `SSHException`, so the shipped branches of the four call sites already handle it, and its
    message is a finished translated sentence (the caller shows it, it does not re-wrap it).
    """


#: The refusal `missing_host_key()` raises — re-exported so a call site gets both from ONE import.
HostKeyRejected = _host_key_policy.HostKeyRejected


def build_connect_kwargs(host, user, port, password="", key_path="", passphrase="",
                         verification_code="", timeout=CONNECT_TIMEOUT_S,
                         banner_timeout=None, auth_timeout=None, transport_factory=None) -> dict:
    """The `paramiko.SSHClient.connect()` arguments of ONE endpoint (PURE).

    THREE branches, and they are the whole contract:
    * a KEY (`key_path`, resolved through `modules/local_paths.py`) → `key_filename` beside
      `look_for_keys=False` / `allow_agent=True`, with the password passed as well (`None` when there is
      none — paramiko tries it LAST, so a host that refuses the key alone still authenticates, and a
      key-only host is untouched). `verification_code` WINS over the password there: a code is collected
      only on the user's word that the host demands a second factor, and `password is not None` is what
      keeps paramiko away from its stdin-reading handler. `passphrase` travels only when it was given.
    * a PASSWORD without a key → `look_for_keys=False` / `allow_agent=False`: no local key and no
      agent is polled before the attempt;
    * neither → the shipped key/agent fallback (`True` / `True`).
    `banner_timeout` / `auth_timeout` and `transport_factory` travel ONLY when the caller declares
    them: the diagnostic paths bound a black-holed host with all three, the interactive ones ship
    `timeout` alone.
    """
    kwargs = {"hostname": host, "username": user, "port": port, "timeout": timeout}
    if banner_timeout is not None:
        kwargs["banner_timeout"] = banner_timeout
    if auth_timeout is not None:
        kwargs["auth_timeout"] = auth_timeout
    if transport_factory is not None:
        kwargs["transport_factory"] = transport_factory
    resolved_key = resolve_local_path(key_path) if key_path else ""
    if resolved_key:
        kwargs.update(key_filename=resolved_key,
                      password=(verification_code or password or None),
                      look_for_keys=False, allow_agent=True)
        if passphrase:
            kwargs["passphrase"] = passphrase
    elif password:
        kwargs.update(password=password, look_for_keys=False, allow_agent=False)
    else:
        kwargs.update(look_for_keys=True, allow_agent=True)
    return kwargs


def key_needs_passphrase(key_path) -> bool:
    """Is this private key file ENCRYPTED — i.e. does opening it demand a passphrase? Never raises.

    It is the pre-flight of the ask: the file is opened WITHOUT a passphrase right here, so the user is
    asked only when the answer is really needed, and a readable key (or a missing one) costs nothing.
    """
    path = resolve_local_path(key_path) if key_path else ""
    if not path:
        return False
    try:
        if not os.path.isfile(path):
            return False
    except OSError:  # noqa: BLE001 — an unusable path is not an encrypted key
        return False
    # Each key class is asked in turn (paramiko's own `_auth` order): the one that matches the file
    # either loads it or answers the ONE exception that means "encrypted".
    for loader in (paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key):
        try:
            loader.from_private_key_file(path)
            return False
        except paramiko.PasswordRequiredException:
            return True
        except Exception:  # noqa: BLE001 — the wrong class for this file: try the next one
            continue
    return False


def resolve_passphrase(host, user, port, key_path, passphrase="", password="", verification_code=""):
    """The passphrase the connect will use: the caller's, or the user's answer, or none.

    The ask happens ONLY where paramiko's own `passphrase = password` alias cannot help — no
    passphrase, no password and no code were given AND the key file is encrypted. A `None` answer (a
    cancelled dialog, or a build without a surface) is the declared refusal, not a silent no-op:
    without it the connection dies inside paramiko with a `PasswordRequiredException` nobody explains.
    """
    if passphrase or password or verification_code:
        return passphrase
    if not key_needs_passphrase(key_path):
        return passphrase
    answer = _ask.ask(_ask.KIND_KEY_PASSPHRASE, host=host, user=user, port=port,
                      key_path=resolve_local_path(key_path))
    if answer is None:
        raise ConnectionCancelled(_t("ssh.key_passphrase_required", host=host))
    return str(answer)


def _ask_for_second_factor(host, user, port):
    """The handler of the keyboard-interactive prompt: the USER answers, never the process's stdin.

    Returns the list paramiko expects. Raising is the honest answer for "nobody could answer": it
    reaches the caller as this module's `ConnectionCancelled` (`None` on the ask means a cancelled
    dialog, and no installed surface means the build cannot ask at all).
    """
    def handler(title, instructions, prompt_list):
        if not prompt_list:
            return []
        if not _ask.has_answerer():
            raise ConnectionCancelled(_t("ssh.second_factor_unsupported", host=host, port=port))
        answers = []
        for prompt, show_input in prompt_list:
            value = _ask.ask(_ask.KIND_SECOND_FACTOR, host=host, user=user, port=port,
                             title=title or "", instructions=instructions or "",
                             prompt=prompt or "", secret=not bool(show_input))
            if value is None:
                raise ConnectionCancelled(_t("ssh.auth_cancelled", host=host, port=port))
            answers.append(str(value))
        return answers

    return handler


def interactive_transport_factory(host, user, port):
    """A `transport_factory` whose keyboard-interactive prompt is OUR handler. THE handler contract.

    `SSHClient.connect()` exposes no handler, and paramiko's own fallback prints the prompt to stdout
    and reads the process's stdin — an `EOFError` under a GUI and a prompt in the wrong window in a
    console. Substituting the transport is the ONE seam that closes it: the handler runs on the
    transport thread and marshals its question through `modules/interactive_ask.py`.
    """
    class _AnsweringTransport(paramiko.Transport):
        """A transport that never lets a second factor reach the process's stdin."""

        def auth_interactive_dumb(self, username, handler=None, submethods=""):
            if handler is None:
                handler = _ask_for_second_factor(host, user, port)
            return super().auth_interactive_dumb(username, handler, submethods)

        def auth_interactive(self, username, handler=None, submethods=""):
            if handler is None:
                handler = _ask_for_second_factor(host, user, port)
            return paramiko.Transport.auth_interactive(self, username, handler, submethods)

    def factory(sock, disabled_algorithms=None):
        return _AnsweringTransport(sock, disabled_algorithms=disabled_algorithms)

    return factory


def connect_client(host, user, port, password="", key_path="", client=None,
                   timeout=CONNECT_TIMEOUT_S, banner_timeout=None, auth_timeout=None,
                   passphrase="", verification_code="", transport_factory=None):
    """A CONNECTED client with the application's known-hosts policy applied.

    Answers `(client, policy)`: the caller keeps the policy, because a FIRST connection is the one
    that reports what it trusted (`accepted_new_key`, `last_fingerprint`) and whether the key really
    reached the store (`pinned` — an unreadable file remembers nothing, and the caller says so).
    `client` may be handed IN — the two sites that close their client in a `finally:` build it before
    the `try` — otherwise one is created here through the `paramiko` ATTRIBUTE, so a suite that
    substitutes the class sees the very client the application would use.

    A CHANGED host key is ONE question, not a failure: `resolve_changed_key()` asks the user, and a yes
    replaces the stored entry and reconnects on a FRESH client (the failed one is closed here, so a
    caller that closes what it got back never leaks one). A no re-raises the original exception.
    """
    kwargs = build_connect_kwargs(
        host, user, port, password, key_path,
        passphrase=resolve_passphrase(host, user, port, key_path, passphrase,
                                      password=password, verification_code=verification_code),
        verification_code=verification_code, timeout=timeout,
        banner_timeout=banner_timeout, auth_timeout=auth_timeout,
        transport_factory=(transport_factory or interactive_transport_factory(host, user, port)))
    attempts_left = KEY_RETRY_ATTEMPTS
    while True:
        if client is None:
            client = paramiko.SSHClient()
        policy = _host_key_policy.SshKnownHostsPolicy(hostname=host, port=port)
        policy.apply_to_client(client)
        try:
            client.connect(**kwargs)
            return client, policy
        except paramiko.BadHostKeyException as exc:
            attempts_left -= 1
            if attempts_left <= 0 or not _host_key_policy.resolve_changed_key(exc, host, port):
                raise
            try:
                client.close()
            except Exception:  # noqa: BLE001 — a half-open client is not the failure to report
                pass
            client = None
