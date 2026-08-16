# Local Network MCP Server

A Model Context Protocol (MCP) server that allows Claude to interact with your local network, execute local shell commands, monitor system resources, and manage remote devices via SSH.

It turns "can you check why the Raspberry Pi dropped off the network" into a workflow the agent executes itself: `scan_network` → `ping_host` → `ssh_connect` → `ssh_execute` → diagnosis. Persistent SSH sessions mean the agent connects once and runs multi-step remote workflows (inspect logs, restart a service, verify) in a single conversation.

## Features

### Local System Tools
- **Execute Local Commands**: Run shell commands on your local machine
- **System Information**: Get CPU, memory, disk, and network details
- **Process Management**: List, monitor, and kill processes
- **Environment Variables**: View and filter environment variables
- **Directory Operations**: List, search, and navigate directories
- **Disk Usage**: Monitor disk space usage
- **File Search**: Find files matching patterns
- **Network Connections**: Monitor active network connections

### Network Tools
- **Get Local IP**: Find your machine's IP address and network range
- **Network Scanning**: Discover all active devices on your local network
- **Ping Hosts**: Check if specific devices are online
- **Port Checking**: See if specific ports are open on any device
- **Port Scanning**: Scan multiple ports on any device at once

### SSH Tools
- **SSH Connect**: Establish persistent SSH connections to remote devices
- **SSH Execute**: Run commands on remote devices via SSH
- **SSH Disconnect**: Close SSH connections
- **SSH List Connections**: View all active SSH sessions

## Installation

1. Clone and install dependencies:
```bash
git clone https://github.com/YOUR_USERNAME/local-network-mcp.git
cd local-network-mcp
pip3 install -r requirements.txt
```

Or run the install script:
```bash
./install.sh
```

2. Test the server (optional):
```bash
python3 network_mcp_server.py
```

## Configuration

Add this server to your Claude Desktop configuration:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "local-network": {
      "command": "python3",
      "args": ["/path/to/local-network-mcp/network_mcp_server.py"]
    }
  }
}
```

(A template is provided in `claude_desktop_config.json` — update the path to where you cloned the repo.)

Or register with Claude Code:

```bash
claude mcp add local-network -- python3 /path/to/local-network-mcp/network_mcp_server.py
```

After adding the configuration, restart Claude Desktop.

## Usage Examples

### Local Command Execution
- "Execute 'ls -la' on my local machine"
- "Run 'git status' in ~/projects"
- "Execute 'npm install' with a 60 second timeout"
- "Run 'python script.py' with custom environment variables"

### System Monitoring
- "What's my system information?"
- "Show me CPU and memory usage"
- "List all running processes"
- "Show me processes using the most CPU"
- "What processes are running that match 'python'?"
- "Show my environment variables"
- "Find all PATH-related environment variables"

### Process Management
- "Kill process with PID 12345"
- "Force kill the stuck process 9876"
- "List all Python processes"

### Directory & File Operations
- "List files in ~/Documents"
- "Show me all files in the current directory recursively"
- "Find all Python files in my projects folder"
- "Search for '*.log' files in /var/log"
- "What's the disk usage of my home directory?"
- "Show hidden files in my home directory"

### Network Monitoring
- "Show all active network connections"
- "List all TCP connections"
- "What ports are currently listening on my machine?"

### Network Operations
- "What devices are on my network?"
- "Is 192.168.1.100 online?"
- "Check if port 8080 is open on my server"
- "Scan common ports on 192.168.1.50"
- "What's my local IP address?"

### SSH Operations
- "Connect to my Raspberry Pi at 192.168.1.100 with username pi"
- "Execute 'df -h' on 192.168.1.100"
- "Check disk space on my server"
- "List running processes on the remote machine"
- "Show all active SSH connections"
- "Disconnect from 192.168.1.100"

## Available Tools

### Local System Tools

#### `execute_local_command`
Execute shell commands on your local machine with full control.

**Parameters:**
- `command` (required): Shell command to execute
- `shell` (optional): Use shell interpretation (default: true)
- `timeout` (optional): Command timeout in seconds (default: 30)
- `cwd` (optional): Working directory for execution
- `env` (optional): Additional environment variables

**Example:**
```
Execute 'git status' in ~/projects/myapp
```

#### `get_system_info`
Get comprehensive system information including platform, CPU, memory, disk, and network details.

**Example:**
```
Show me my system information
```

#### `list_processes`
List running processes with CPU and memory usage, sorted by CPU usage.

**Parameters:**
- `filter_name` (optional): Filter processes by name
- `limit` (optional): Maximum number of results (default: 50)

**Example:**
```
List all Python processes
Show me the top 20 processes by CPU usage
```

#### `kill_process`
Terminate or force kill a process by PID.

**Parameters:**
- `pid` (required): Process ID to kill
- `force` (optional): Use SIGKILL instead of SIGTERM (default: false)

**Example:**
```
Kill process 12345
Force kill process 9876
```

#### `get_environment_variables`
View system environment variables with optional filtering.

**Parameters:**
- `filter_key` (optional): Filter by key name

**Example:**
```
Show all environment variables
Find PATH-related environment variables
```

#### `get_directory_listing`
List directory contents with detailed file information.

**Parameters:**
- `path` (optional): Directory path (default: current directory)
- `recursive` (optional): List recursively (default: false)
- `show_hidden` (optional): Show hidden files (default: false)
- `max_depth` (optional): Maximum recursion depth (default: 3)

**Example:**
```
List files in ~/Documents
Show all files recursively in my projects folder
```

#### `get_disk_usage`
Get disk usage information for any path.

**Parameters:**
- `path` (optional): Path to check (default: /)

**Example:**
```
What's the disk usage of my home directory?
Show disk space for /var
```

#### `find_files`
Search for files matching a pattern.

**Parameters:**
- `path` (required): Starting directory
- `pattern` (required): File pattern (e.g., "*.py", "test*.txt")
- `recursive` (optional): Search recursively (default: true)
- `file_type` (optional): Filter by "file" or "directory"
- `max_results` (optional): Maximum results (default: 100)

**Example:**
```
Find all Python files in ~/projects
Search for log files in /var/log
```

#### `get_network_connections`
View active network connections and listening ports.

**Parameters:**
- `filter_type` (optional): Filter by "tcp" or "udp"

**Example:**
```
Show all TCP connections
What ports are listening on my machine?
```

## SSH Authentication

The server supports two authentication methods:

### 1. Password Authentication
```python
# Claude will prompt for credentials
"Connect to 192.168.1.100 with username admin and password mypassword"
```

### 2. SSH Key Authentication
```python
# Using SSH key file
"Connect to 192.168.1.100 with username admin using key ~/.ssh/id_rsa"
```

## SSH Connection Management

The server maintains persistent SSH connections for better performance:
- Connections are reused across multiple command executions
- No need to reconnect for each command
- Automatic connection recovery if a connection drops
- Manual disconnect when done

## Security Notes

### Local Command Security
- **IMPORTANT**: This server can execute ANY command on your local machine
- Commands run with the same permissions as the Python process
- Be extremely careful with destructive commands (rm, dd, etc.)
- Always review commands before execution
- Consider running the MCP server with limited permissions
- Never execute untrusted commands

### Network Security
- This server only works on your **local network**
- Requires appropriate network permissions
- Make sure you have permission to scan devices on your network
- Network scanning may be detected by security tools

### SSH Security
- SSH credentials are handled securely in memory
- Connections are encrypted using SSH protocol
- Uses Paramiko library with industry-standard security
- Consider using SSH keys instead of passwords for better security
- The server accepts host keys automatically (AutoAddPolicy) - be cautious on untrusted networks

**IMPORTANT**: Never share your SSH passwords or private keys. This tool should only be used on trusted networks and by trusted users.

## Common Local Commands

### System Information
- `uname -a` - System information
- `hostname` - Get hostname
- `uptime` - System uptime
- `df -h` - Disk usage
- `free -h` - Memory usage (Linux)
- `top -l 1` - CPU snapshot (macOS)

### Process Management
- `ps aux` - List all processes
- `htop` - Interactive process viewer
- `lsof` - List open files

### File Operations
- `ls -la /path` - List files
- `cat /path/to/file` - Read file contents
- `pwd` - Current directory
- `du -sh /path` - Directory size
- `find /path -name "*.txt"` - Find files

### Network Operations
- `ifconfig` or `ip addr` - Network interfaces
- `netstat -an` - Network connections
- `lsof -i` - Network files
- `ping -c 4 google.com` - Test connectivity

### Development Commands
- `git status` - Git repository status
- `npm install` - Install Node.js packages
- `python --version` - Check Python version
- `docker ps` - List Docker containers

## Troubleshooting

### Server Issues
1. Check that Python is in your PATH
2. Verify the full path in the config file
3. Check Claude Desktop logs
4. Ensure you have required permissions
5. Try running the script manually first
6. Install missing dependencies: `pip install -r requirements.txt`

### Command Execution Issues
1. Verify you have permissions to execute the command
2. Check if the command exists in PATH
3. Try running the command manually in terminal
4. Increase timeout for long-running commands
5. Check working directory is correct
6. Verify environment variables are set properly

### SSH Connection Issues
1. Verify the host is reachable (`ping_host` tool)
2. Check if SSH port (22) is open (`check_port` tool)
3. Verify username and credentials
4. Check SSH server is running on target
5. Ensure firewall allows SSH connections
6. For key auth, check key file permissions (should be 600)

### Common Error Messages
- **"Command not found"**: Command not in PATH or doesn't exist
- **"Permission denied"**: Insufficient permissions to execute
- **"Timeout"**: Command took too long, increase timeout value
- **"Authentication failed"**: Wrong SSH username/password or key
- **"Connection refused"**: SSH server not running or firewall blocking

## Requirements

- Python 3.7+
- mcp library
- paramiko library (for SSH)
- psutil library (for system monitoring)
- Network access permissions
- SSH access to target devices (for remote operations)

## Example Workflows

### Local System Management
```
1. Check system resources
   "Show me my system information"

2. Monitor processes
   "List all running processes"

3. Find resource-heavy processes
   "Show me the top 10 processes by CPU"

4. Kill problematic process
   "Kill process 12345"

5. Check disk space
   "What's my disk usage?"
```

### Remote Server Management
```
1. Scan your network to find devices
   "Scan my network"

2. Check if SSH is available
   "Check if port 22 is open on 192.168.1.100"

3. Connect to the device
   "Connect to 192.168.1.100 with username pi"

4. Execute commands
   "Show disk space on 192.168.1.100"
   "List running processes on 192.168.1.100"

5. When done, disconnect
   "Disconnect from 192.168.1.100"
```

### Development Workflow
```
1. Check project status
   "Execute 'git status' in ~/projects/myapp"

2. Run tests
   "Execute 'npm test' in my project directory with 120s timeout"

3. Monitor logs
   "Find all log files in my project"
   "Execute 'tail -n 50 app.log' in my project"

4. Check processes
   "List all node processes"
```

## Performance Notes

- Network scanning can take 30-60 seconds for full range (254 IPs)
- Process listing is fast but may return many results
- File search with recursive option can be slow on large directories
- SSH connections are persistent and reused for better performance
- Command timeouts prevent hanging on stuck commands
