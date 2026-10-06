"""The default-deny policy on the opt-in tools.

These tests assert the *policy*, never that an arbitrary shell string runs.
The distinction matters: the value of this server is that an agent cannot
reach `rm -rf` unless a human put the opt-in in the client config first.
"""

from __future__ import annotations

import asyncio

import pytest

import network_mcp_server as server

DESTRUCTIVE = sorted(server.DESTRUCTIVE_TOOLS)

# One representative call per destructive tool. Arguments are deliberately
# harmless: if a gate ever regressed, the test would fail rather than do damage.
CALLS = {
    "execute_local_command": lambda: server.execute_local_command("echo hello"),
    "ssh_connect": lambda: server.ssh_connect("192.0.2.1", "nobody", password="x"),
    "ssh_execute": lambda: server.ssh_execute("192.0.2.1", "nobody", "echo hello"),
    "kill_process": lambda: server.kill_process(999_999_999),
}


@pytest.fixture(autouse=True)
def _no_opt_ins(monkeypatch):
    """Start every test from the shipped default, whatever the dev's shell has."""
    for env_var in server.DESTRUCTIVE_TOOLS.values():
        monkeypatch.delenv(env_var, raising=False)


class TestDefaultDeny:
    @pytest.mark.parametrize("tool", DESTRUCTIVE)
    def test_denied_with_no_environment(self, tool):
        result = CALLS[tool]()
        assert result["success"] is False
        assert result["policy"] == "default-deny"

    @pytest.mark.parametrize("tool", DESTRUCTIVE)
    def test_refusal_names_the_variable_that_would_allow_it(self, tool):
        """A refusal an operator cannot act on is a bug report, not a guardrail."""
        assert server.DESTRUCTIVE_TOOLS[tool] in CALLS[tool]()["error"]

    @pytest.mark.parametrize("tool", DESTRUCTIVE)
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_opt_in_values_enable(self, monkeypatch, tool, value):
        monkeypatch.setenv(server.DESTRUCTIVE_TOOLS[tool], value)
        assert server.is_tool_enabled(tool) is True

    @pytest.mark.parametrize("tool", DESTRUCTIVE)
    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", "2"])
    def test_everything_else_stays_denied(self, monkeypatch, tool, value):
        """Anything not clearly an opt-in is a refusal — a typo must not open the gate."""
        monkeypatch.setenv(server.DESTRUCTIVE_TOOLS[tool], value)
        assert server.is_tool_enabled(tool) is False

    @pytest.mark.parametrize(
        "tool",
        [
            "ping_host",
            "scan_network",
            "get_system_info",
            "list_processes",
            "find_files",
            "ssh_disconnect",
            "ssh_list_connections",
        ],
    )
    def test_read_only_tools_are_never_gated(self, tool):
        assert server.is_tool_enabled(tool) is True


class TestTheGateIsReal:
    """A refusal that still performs the side effect is worse than no gate.

    Each tool wraps its body in ``except Exception``, which would swallow a
    probe's ``AssertionError`` and return ``success: False`` regardless. So
    these assert the ``policy`` marker, which only the gate sets.
    """

    def test_denied_exec_never_reaches_subprocess(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("subprocess.run was called despite a refusal")

        monkeypatch.setattr(server.subprocess, "run", explode)
        result = server.execute_local_command("echo hello")
        assert result["policy"] == "default-deny"

    def test_denied_kill_never_reaches_psutil(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("psutil.Process was constructed despite a refusal")

        monkeypatch.setattr(server.psutil, "Process", explode)
        assert server.kill_process(999_999_999)["policy"] == "default-deny"

    def test_denied_ssh_never_opens_a_connection(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("an SSH connection was opened despite a refusal")

        monkeypatch.setattr(server, "ssh_connect", explode)
        monkeypatch.setattr(server.paramiko, "SSHClient", explode)
        result = server.ssh_execute("192.0.2.1", "nobody", "echo hello")
        assert result["policy"] == "default-deny"

    def test_denied_ssh_connect_never_builds_a_client(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("an SSH client was built despite a refusal")

        monkeypatch.setattr(server.paramiko, "SSHClient", explode)
        result = server.ssh_connect("192.0.2.1", "nobody", password="x")
        assert result["policy"] == "default-deny"
        assert server.ssh_connections == {}

    def test_ssh_connect_and_ssh_execute_share_one_opt_in(self, monkeypatch):
        """Two switches for one capability would let them drift apart."""
        assert server.DESTRUCTIVE_TOOLS["ssh_connect"] == server.DESTRUCTIVE_TOOLS["ssh_execute"]
        monkeypatch.setenv("LNMCP_ENABLE_SSH_EXEC", "1")
        assert server.is_tool_enabled("ssh_connect") is True
        assert server.is_tool_enabled("ssh_execute") is True

    def test_gate_reads_the_environment_at_call_time(self, monkeypatch):
        """Import order must not decide policy — a stale snapshot would be a real bug."""
        assert server.is_tool_enabled("kill_process") is False
        monkeypatch.setenv("LNMCP_ENABLE_KILL", "1")
        assert server.is_tool_enabled("kill_process") is True

    def test_the_gate_is_not_reachable_from_a_tool_argument(self):
        """The opt-in lives in the server env, so the agent cannot flip it itself."""
        env_arg_result = server.execute_local_command(
            "echo hello", env={"LNMCP_ENABLE_EXEC": "1"}
        )
        assert env_arg_result["success"] is False
        assert env_arg_result["policy"] == "default-deny"


class TestToolListing:
    @staticmethod
    def _tools():
        return asyncio.run(server.list_tools())

    def test_disabled_tools_are_advertised_as_disabled(self):
        """The agent should know a tool is off before spending a turn on it."""
        for tool in self._tools():
            if tool.name in server.DESTRUCTIVE_TOOLS:
                assert tool.description.startswith("[DISABLED")
                assert server.DESTRUCTIVE_TOOLS[tool.name] in tool.description

    def test_enabled_tools_carry_no_marker(self, monkeypatch):
        monkeypatch.setenv("LNMCP_ENABLE_EXEC", "1")
        listed = {tool.name: tool.description for tool in self._tools()}
        assert not listed["execute_local_command"].startswith("[DISABLED")
        assert listed["kill_process"].startswith("[DISABLED")

    def test_read_only_tools_are_never_marked(self):
        for tool in self._tools():
            if tool.name not in server.DESTRUCTIVE_TOOLS:
                assert not tool.description.startswith("[DISABLED")


class TestNoDrift:
    """Guards against the failure mode where the policy and the code diverge."""

    def test_every_governed_name_is_a_real_tool(self):
        listed = {tool.name for tool in asyncio.run(server.list_tools())}
        assert set(server.DESTRUCTIVE_TOOLS) <= listed

    def test_every_governed_name_is_a_callable(self):
        for tool in server.DESTRUCTIVE_TOOLS:
            assert callable(getattr(server, tool))

    def test_every_advertised_tool_has_a_dispatch_branch(self):
        """A tool the model can see but the server cannot route is a dead end."""
        import inspect

        dispatch = inspect.getsource(server.call_tool)
        for tool in asyncio.run(server.list_tools()):
            assert f'"{tool.name}"' in dispatch, f"{tool.name} is advertised but never dispatched"

    def test_every_setting_the_server_reads_is_documented(self):
        """An opt-in the README does not name is one an operator cannot find."""
        import inspect
        import re
        from pathlib import Path

        readme = (Path(__file__).parent.parent / "README.md").read_text()
        for env_var in set(re.findall(r"LNMCP_[A-Z_]+", inspect.getsource(server))):
            assert env_var in readme, f"{env_var} is read by the server but not in the README"

    def test_entry_point_declared_in_pyproject_exists(self):
        assert callable(server.run)
