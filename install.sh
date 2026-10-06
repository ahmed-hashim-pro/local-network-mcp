#!/usr/bin/env bash
# Creates a virtualenv and installs the server into it.
set -euo pipefail

cd "$(dirname "$0")"

python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e .

cat <<EOF

Installed. Point your MCP client at:

  command: $(pwd)/.venv/bin/python
  args:    ["$(pwd)/network_mcp_server.py"]

The opt-in tools (execute_local_command, ssh_connect, ssh_execute,
kill_process) are denied by default, and SSH refuses hosts that are not in
known_hosts. See the Security model section of README.md to opt in to the
ones you want.
EOF
