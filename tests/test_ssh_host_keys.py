"""SSH host-key verification.

Each test runs a paramiko server in-process over a socketpair, so the real
client-side check runs end to end with no network and no sshd. HOME and the
system known_hosts path point into tmp_path, so a developer's own trust store
is never read or written.
"""

from __future__ import annotations

import contextlib
import socket
import threading

import paramiko
import pytest

import network_mcp_server as server

HOST = "192.0.2.1"


class _AcceptAnyPassword(paramiko.ServerInterface):
    def get_allowed_auths(self, username):
        return "password"

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv(server.SSH_KNOWN_HOSTS_ENV, raising=False)
    monkeypatch.delenv(server.SSH_TOFU_ENV, raising=False)
    monkeypatch.setattr(server, "SYSTEM_KNOWN_HOSTS", tmp_path / "etc" / "ssh_known_hosts")
    monkeypatch.setenv("LNMCP_ENABLE_SSH_EXEC", "1")
    yield
    for client in server.ssh_connections.values():
        client.close()
    server.ssh_connections.clear()


@pytest.fixture
def ssh_server(monkeypatch):
    """Serve `host_key` to the next ssh_connect, over a socketpair."""
    transports = []
    real_new_client = server.new_ssh_client

    def serve(host_key):
        client_sock, server_sock = socket.socketpair()
        transport = paramiko.Transport(server_sock)
        transport.add_server_key(host_key)
        transports.append(transport)

        def run():
            # A refused client hangs up mid-handshake; that is the expected outcome here.
            with contextlib.suppress(Exception):
                transport.start_server(server=_AcceptAnyPassword())

        threading.Thread(target=run, daemon=True).start()

        def new_client():
            client = real_new_client()
            connect = client.connect
            client.connect = lambda **kwargs: connect(sock=client_sock, **kwargs)
            return client

        monkeypatch.setattr(server, "new_ssh_client", new_client)

    yield serve
    for transport in transports:
        transport.close()


def _key(bits=256):
    return paramiko.ECDSAKey.generate(bits=bits)


def _user_known_hosts():
    return server.Path.home() / ".ssh" / "known_hosts"


def _write_known_hosts(path, hostname, key):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(paramiko.hostkeys.HostKeyEntry([hostname], key).to_line())


def _connect(port=22):
    return server.ssh_connect(HOST, "nobody", password="x", port=port)


class TestKnownHosts:
    def test_known_host_with_matching_key_connects(self, ssh_server):
        key = _key()
        _write_known_hosts(_user_known_hosts(), HOST, key)
        ssh_server(key)
        assert _connect()["success"] is True

    def test_system_known_hosts_is_read(self, ssh_server):
        key = _key()
        _write_known_hosts(server.SYSTEM_KNOWN_HOSTS, HOST, key)
        ssh_server(key)
        assert _connect()["success"] is True

    def test_unknown_host_is_refused_by_default(self, ssh_server):
        key = _key()
        ssh_server(key)
        result = _connect()
        assert result["success"] is False
        assert "not in any known_hosts file" in result["error"]
        assert key.fingerprint in result["error"]
        assert server.SSH_TOFU_ENV in result["error"]
        assert server.ssh_connections == {}
        assert not server.server_known_hosts_path().exists()

    @pytest.mark.parametrize("tofu", ["", "1"])
    def test_changed_key_is_refused_whatever_the_tofu_setting(self, monkeypatch, ssh_server, tofu):
        """Trust on first use is about the first contact, never about a key that changed."""
        monkeypatch.setenv(server.SSH_TOFU_ENV, tofu)
        expected, presented = _key(), _key()
        _write_known_hosts(_user_known_hosts(), HOST, expected)
        ssh_server(presented)
        result = _connect()
        assert result["success"] is False
        assert "does not match" in result["error"]
        assert expected.fingerprint in result["error"]
        assert presented.fingerprint in result["error"]
        assert f"ssh-keygen -R {HOST}" in result["error"]
        assert server.ssh_connections == {}
        assert not server.server_known_hosts_path().exists()

    def test_known_host_presenting_another_key_type_is_refused(self, monkeypatch, ssh_server):
        monkeypatch.setenv(server.SSH_TOFU_ENV, "1")
        _write_known_hosts(_user_known_hosts(), HOST, _key(256))
        ssh_server(_key(384))
        result = _connect()
        assert result["success"] is False
        assert "does not match" in result["error"]


class TestTrustOnFirstUse:
    def test_records_the_key_in_the_server_file_only(self, monkeypatch, ssh_server):
        """The agent must not be able to add trust to the user's own known_hosts."""
        monkeypatch.setenv(server.SSH_TOFU_ENV, "1")
        key = _key()
        ssh_server(key)
        assert _connect()["success"] is True

        recorded = paramiko.HostKeys(str(server.server_known_hosts_path()))
        assert recorded.lookup(HOST)[key.get_name()] == key
        assert not _user_known_hosts().exists()

    def test_recorded_key_is_trusted_after_tofu_is_turned_off(self, monkeypatch, ssh_server):
        monkeypatch.setenv(server.SSH_TOFU_ENV, "1")
        key = _key()
        ssh_server(key)
        assert _connect()["success"] is True
        server.ssh_disconnect(HOST, "nobody")

        monkeypatch.delenv(server.SSH_TOFU_ENV)
        ssh_server(key)
        assert _connect()["success"] is True

    def test_non_default_port_is_recorded_like_openssh(self, monkeypatch, ssh_server):
        monkeypatch.setenv(server.SSH_TOFU_ENV, "1")
        ssh_server(_key())
        assert _connect(port=2222)["success"] is True
        assert server.server_known_hosts_path().read_text().startswith(f"[{HOST}]:2222 ")

    def test_store_location_can_be_overridden(self, monkeypatch, tmp_path):
        monkeypatch.setenv(server.SSH_KNOWN_HOSTS_ENV, str(tmp_path / "custom_known_hosts"))
        assert server.server_known_hosts_path() == tmp_path / "custom_known_hosts"
        assert server.server_known_hosts_path() in server.known_hosts_files()

    def test_default_store_is_not_the_users_known_hosts(self):
        assert server.server_known_hosts_path() != _user_known_hosts()


def test_no_policy_accepts_every_key():
    """AutoAddPolicy (and WarningPolicy) would silently undo all of the above."""
    import inspect

    source = inspect.getsource(server)
    assert "AutoAddPolicy" not in source
    assert "WarningPolicy" not in source
