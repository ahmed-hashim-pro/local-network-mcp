import asyncio
import socket
import subprocess
import platform
import os
import psutil
import shutil
from typing import Any, Optional
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server
import json
import paramiko
from io import StringIO
from pathlib import Path

app = Server("local-network-server")

# SSH connection pool to reuse connections
ssh_connections = {}

def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

def get_network_prefix():
    """Get the network prefix (e.g., 192.168.1)"""
    local_ip = get_local_ip()
    return '.'.join(local_ip.split('.')[:-1])

async def scan_network(network_prefix: str, start: int = 1, end: int = 254):
    """Scan the local network for active hosts"""
    active_hosts = []
    
    async def check_host(ip):
        try:
            # Try to connect to common ports
            for port in [80, 443, 22, 445, 8080]:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                    except:
                        hostname = "Unknown"
                    active_hosts.append({
                        "ip": ip,
                        "hostname": hostname,
                        "open_port": port
                    })
                    return
        except Exception:
            pass
    
    tasks = []
    for i in range(start, end + 1):
        ip = f"{network_prefix}.{i}"
        tasks.append(check_host(ip))
    
    await asyncio.gather(*tasks)
    return active_hosts

def ping_host(host: str) -> dict:
    """Ping a specific host to check if it's alive"""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '1', '-W', '1000' if platform.system().lower() == 'windows' else '-W1', host]
    
    try:
        output = subprocess.run(command, capture_output=True, text=True, timeout=2)
        is_alive = output.returncode == 0
        return {
            "host": host,
            "alive": is_alive,
            "output": output.stdout if is_alive else "Host unreachable"
        }
    except Exception as e:
        return {
            "host": host,
            "alive": False,
            "error": str(e)
        }

def check_port(host: str, port: int, timeout: float = 1.0) -> dict:
    """Check if a specific port is open on a host"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        
        is_open = result == 0
        return {
            "host": host,
            "port": port,
            "open": is_open,
            "status": "Open" if is_open else "Closed"
        }
    except Exception as e:
        return {
            "host": host,
            "port": port,
            "open": False,
            "error": str(e)
        }

def scan_ports(host: str, ports: list[int]) -> list[dict]:
    """Scan multiple ports on a host"""
    results = []
    for port in ports:
        results.append(check_port(host, port, timeout=0.5))
    return results

def ssh_connect(host: str, username: str, password: Optional[str] = None, 
                key_filename: Optional[str] = None, port: int = 22) -> dict:
    """Establish SSH connection to a host"""
    connection_key = f"{username}@{host}:{port}"
    
    try:
        # Check if connection already exists and is active
        if connection_key in ssh_connections:
            client = ssh_connections[connection_key]
            try:
                # Test if connection is still alive
                client.exec_command('echo test', timeout=2)
                return {
                    "success": True,
                    "message": f"Already connected to {connection_key}",
                    "connection_key": connection_key
                }
            except:
                # Connection is dead, remove it
                try:
                    client.close()
                except:
                    pass
                del ssh_connections[connection_key]
        
        # Create new connection
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect with password or key
        if key_filename:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                key_filename=key_filename,
                timeout=10
            )
        elif password:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=10
            )
        else:
            return {
                "success": False,
                "error": "Either password or key_filename must be provided"
            }
        
        # Store connection
        ssh_connections[connection_key] = client
        
        return {
            "success": True,
            "message": f"Successfully connected to {connection_key}",
            "connection_key": connection_key
        }
    
    except paramiko.AuthenticationException:
        return {
            "success": False,
            "error": "Authentication failed. Check username/password or key."
        }
    except paramiko.SSHException as e:
        return {
            "success": False,
            "error": f"SSH error: {str(e)}"
        }
    except socket.error as e:
        return {
            "success": False,
            "error": f"Connection error: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

def ssh_execute(host: str, username: str, command: str, 
                password: Optional[str] = None, key_filename: Optional[str] = None,
                port: int = 22, timeout: int = 30) -> dict:
    """Execute a command on a remote host via SSH"""
    connection_key = f"{username}@{host}:{port}"
    
    try:
        # Try to get existing connection or create new one
        if connection_key not in ssh_connections:
            connect_result = ssh_connect(host, username, password, key_filename, port)
            if not connect_result["success"]:
                return connect_result
        
        client = ssh_connections[connection_key]
        
        # Execute command
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        
        # Get output
        exit_status = stdout.channel.recv_exit_status()
        stdout_text = stdout.read().decode('utf-8', errors='replace')
        stderr_text = stderr.read().decode('utf-8', errors='replace')
        
        return {
            "success": True,
            "command": command,
            "exit_status": exit_status,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "connection_key": connection_key
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Command execution failed: {str(e)}",
            "command": command
        }

def ssh_disconnect(host: str, username: str, port: int = 22) -> dict:
    """Close SSH connection to a host"""
    connection_key = f"{username}@{host}:{port}"
    
    try:
        if connection_key in ssh_connections:
            client = ssh_connections[connection_key]
            client.close()
            del ssh_connections[connection_key]
            return {
                "success": True,
                "message": f"Disconnected from {connection_key}"
            }
        else:
            return {
                "success": False,
                "message": f"No active connection to {connection_key}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error disconnecting: {str(e)}"
        }

def ssh_list_connections() -> dict:
    """List all active SSH connections"""
    return {
        "active_connections": list(ssh_connections.keys()),
        "total": len(ssh_connections)
    }

# ============================================
# LOCAL SHELL COMMAND FUNCTIONS
# ============================================

def execute_local_command(command: str, shell: bool = True, timeout: int = 30, 
                          cwd: Optional[str] = None, env: Optional[dict] = None) -> dict:
    """Execute a command on the local machine"""
    try:
        # Merge environment variables if provided
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        
        result = subprocess.run(
            command,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=exec_env
        )
        
        return {
            "success": True,
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "cwd": cwd or os.getcwd()
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "command": command,
            "error": f"Command timed out after {timeout} seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "command": command,
            "error": str(e)
        }

def get_system_info() -> dict:
    """Get comprehensive system information"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version()
            },
            "cpu": {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "current_usage_percent": cpu_percent,
                "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else "N/A"
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "percent_used": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent_used": disk.percent
            },
            "network": {
                "hostname": socket.gethostname(),
                "local_ip": get_local_ip()
            }
        }
    except Exception as e:
        return {
            "error": str(e)
        }

def list_processes(filter_name: Optional[str] = None, limit: int = 50) -> dict:
    """List running processes"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status']):
            try:
                pinfo = proc.info
                if filter_name and filter_name.lower() not in pinfo['name'].lower():
                    continue
                    
                processes.append({
                    "pid": pinfo['pid'],
                    "name": pinfo['name'],
                    "username": pinfo['username'],
                    "cpu_percent": round(pinfo['cpu_percent'], 2),
                    "memory_percent": round(pinfo['memory_percent'], 2),
                    "status": pinfo['status']
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Sort by CPU usage
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        
        return {
            "total_processes": len(processes),
            "processes": processes[:limit]
        }
    except Exception as e:
        return {
            "error": str(e)
        }

def kill_process(pid: int, force: bool = False) -> dict:
    """Kill a process by PID"""
    try:
        process = psutil.Process(pid)
        process_name = process.name()
        
        if force:
            process.kill()  # SIGKILL
        else:
            process.terminate()  # SIGTERM
        
        # Wait for process to terminate
        process.wait(timeout=5)
        
        return {
            "success": True,
            "pid": pid,
            "process_name": process_name,
            "message": f"Process {pid} ({process_name}) {'killed' if force else 'terminated'} successfully"
        }
    except psutil.NoSuchProcess:
        return {
            "success": False,
            "error": f"Process with PID {pid} not found"
        }
    except psutil.AccessDenied:
        return {
            "success": False,
            "error": f"Access denied to kill process {pid}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def get_environment_variables(filter_key: Optional[str] = None) -> dict:
    """Get environment variables"""
    try:
        env_vars = dict(os.environ)
        
        if filter_key:
            env_vars = {k: v for k, v in env_vars.items() if filter_key.lower() in k.lower()}
        
        return {
            "total_variables": len(env_vars),
            "variables": env_vars
        }
    except Exception as e:
        return {
            "error": str(e)
        }

def get_directory_listing(path: str = ".", recursive: bool = False, 
                         show_hidden: bool = False, max_depth: int = 3) -> dict:
    """List directory contents"""
    try:
        path_obj = Path(path).resolve()
        
        if not path_obj.exists():
            return {
                "success": False,
                "error": f"Path does not exist: {path}"
            }
        
        if not path_obj.is_dir():
            return {
                "success": False,
                "error": f"Path is not a directory: {path}"
            }
        
        items = []
        
        if recursive:
            for item in path_obj.rglob('*'):
                if not show_hidden and any(part.startswith('.') for part in item.parts):
                    continue
                
                # Check depth
                try:
                    relative_depth = len(item.relative_to(path_obj).parts)
                    if relative_depth > max_depth:
                        continue
                except ValueError:
                    continue
                
                try:
                    stat = item.stat()
                    items.append({
                        "path": str(item),
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size_bytes": stat.st_size if item.is_file() else 0,
                        "modified": stat.st_mtime
                    })
                except (PermissionError, OSError):
                    continue
        else:
            for item in path_obj.iterdir():
                if not show_hidden and item.name.startswith('.'):
                    continue
                
                try:
                    stat = item.stat()
                    items.append({
                        "path": str(item),
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size_bytes": stat.st_size if item.is_file() else 0,
                        "modified": stat.st_mtime
                    })
                except (PermissionError, OSError):
                    continue
        
        return {
            "success": True,
            "path": str(path_obj),
            "total_items": len(items),
            "items": items
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def get_disk_usage(path: str = "/") -> dict:
    """Get disk usage information for a path"""
    try:
        usage = shutil.disk_usage(path)
        
        return {
            "path": path,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "percent_used": round((usage.used / usage.total) * 100, 2)
        }
    except Exception as e:
        return {
            "error": str(e)
        }

def find_files(path: str, pattern: str, recursive: bool = True, 
               file_type: Optional[str] = None, max_results: int = 100) -> dict:
    """Search for files matching a pattern"""
    try:
        path_obj = Path(path).resolve()
        
        if not path_obj.exists():
            return {
                "success": False,
                "error": f"Path does not exist: {path}"
            }
        
        results = []
        
        if recursive:
            items = path_obj.rglob(pattern)
        else:
            items = path_obj.glob(pattern)
        
        for item in items:
            if len(results) >= max_results:
                break
            
            # Filter by file type if specified
            if file_type:
                if file_type == "file" and not item.is_file():
                    continue
                elif file_type == "directory" and not item.is_dir():
                    continue
            
            try:
                stat = item.stat()
                results.append({
                    "path": str(item),
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size_bytes": stat.st_size if item.is_file() else 0,
                    "modified": stat.st_mtime
                })
            except (PermissionError, OSError):
                continue
        
        return {
            "success": True,
            "search_path": str(path_obj),
            "pattern": pattern,
            "total_found": len(results),
            "results": results
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def get_network_connections(filter_type: Optional[str] = None) -> dict:
    """Get active network connections"""
    try:
        connections = []
        
        for conn in psutil.net_connections(kind='inet'):
            if filter_type and conn.type.name.lower() != filter_type.lower():
                continue
            
            try:
                process = psutil.Process(conn.pid) if conn.pid else None
                process_name = process.name() if process else "N/A"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process_name = "N/A"
            
            connections.append({
                "fd": conn.fd,
                "family": conn.family.name,
                "type": conn.type.name,
                "local_address": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "N/A",
                "remote_address": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                "status": conn.status,
                "pid": conn.pid,
                "process_name": process_name
            })
        
        return {
            "total_connections": len(connections),
            "connections": connections
        }
    except Exception as e:
        return {
            "error": str(e)
        }

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # Network tools
        Tool(
            name="get_local_ip",
            description="Get the local IP address of this machine",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="scan_network",
            description="Scan the local network to discover active devices. Returns IP addresses, hostnames, and open ports.",
            inputSchema={
                "type": "object",
                "properties": {
                    "network_prefix": {
                        "type": "string",
                        "description": "Network prefix (e.g., 192.168.1). Leave empty to auto-detect."
                    },
                    "start_ip": {
                        "type": "integer",
                        "description": "Starting IP address (last octet, default: 1)",
                        "default": 1
                    },
                    "end_ip": {
                        "type": "integer",
                        "description": "Ending IP address (last octet, default: 254)",
                        "default": 254
                    }
                }
            }
        ),
        Tool(
            name="ping_host",
            description="Ping a specific host to check if it's reachable",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP address or hostname to ping"
                    }
                },
                "required": ["host"]
            }
        ),
        Tool(
            name="check_port",
            description="Check if a specific port is open on a host",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP address or hostname"
                    },
                    "port": {
                        "type": "integer",
                        "description": "Port number to check"
                    }
                },
                "required": ["host", "port"]
            }
        ),
        Tool(
            name="scan_ports",
            description="Scan multiple ports on a specific host",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP address or hostname"
                    },
                    "ports": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of port numbers to scan (e.g., [80, 443, 22, 8080])"
                    }
                },
                "required": ["host", "ports"]
            }
        ),
        # SSH tools
        Tool(
            name="ssh_connect",
            description="Establish an SSH connection to a remote host. Connection is kept alive for subsequent commands.",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP address or hostname"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username"
                    },
                    "password": {
                        "type": "string",
                        "description": "SSH password (optional if using key)"
                    },
                    "key_filename": {
                        "type": "string",
                        "description": "Path to SSH private key file (optional if using password)"
                    },
                    "port": {
                        "type": "integer",
                        "description": "SSH port (default: 22)",
                        "default": 22
                    }
                },
                "required": ["host", "username"]
            }
        ),
        Tool(
            name="ssh_execute",
            description="Execute a command on a remote host via SSH. Will create connection if not exists.",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP address or hostname"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username"
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute on remote host"
                    },
                    "password": {
                        "type": "string",
                        "description": "SSH password (optional if using key or existing connection)"
                    },
                    "key_filename": {
                        "type": "string",
                        "description": "Path to SSH private key file (optional)"
                    },
                    "port": {
                        "type": "integer",
                        "description": "SSH port (default: 22)",
                        "default": 22
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout in seconds (default: 30)",
                        "default": 30
                    }
                },
                "required": ["host", "username", "command"]
            }
        ),
        Tool(
            name="ssh_disconnect",
            description="Close an SSH connection to a remote host",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP address or hostname"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username"
                    },
                    "port": {
                        "type": "integer",
                        "description": "SSH port (default: 22)",
                        "default": 22
                    }
                },
                "required": ["host", "username"]
            }
        ),
        Tool(
            name="ssh_list_connections",
            description="List all active SSH connections",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        # Local shell command tools
        Tool(
            name="execute_local_command",
            description="Execute a shell command on the local machine. Returns stdout, stderr, and exit code.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    },
                    "shell": {
                        "type": "boolean",
                        "description": "Use shell interpretation (default: true)",
                        "default": True
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout in seconds (default: 30)",
                        "default": 30
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for command execution (optional)"
                    },
                    "env": {
                        "type": "object",
                        "description": "Additional environment variables (optional)",
                        "additionalProperties": {"type": "string"}
                    }
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="get_system_info",
            description="Get comprehensive system information including CPU, memory, disk, and network details",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="list_processes",
            description="List running processes with CPU and memory usage",
            inputSchema={
                "type": "object",
                "properties": {
                    "filter_name": {
                        "type": "string",
                        "description": "Filter processes by name (optional)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of processes to return (default: 50)",
                        "default": 50
                    }
                }
            }
        ),
        Tool(
            name="kill_process",
            description="Terminate or kill a process by PID",
            inputSchema={
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "Process ID to kill"
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force kill (SIGKILL) instead of graceful termination (SIGTERM)",
                        "default": False
                    }
                },
                "required": ["pid"]
            }
        ),
        Tool(
            name="get_environment_variables",
            description="Get system environment variables",
            inputSchema={
                "type": "object",
                "properties": {
                    "filter_key": {
                        "type": "string",
                        "description": "Filter environment variables by key name (optional)"
                    }
                }
            }
        ),
        Tool(
            name="get_directory_listing",
            description="List contents of a directory with detailed information",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list (default: current directory)",
                        "default": "."
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively (default: false)",
                        "default": False
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "Show hidden files (default: false)",
                        "default": False
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth for recursive listing (default: 3)",
                        "default": 3
                    }
                }
            }
        ),
        Tool(
            name="get_disk_usage",
            description="Get disk usage information for a path",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to check disk usage (default: /)",
                        "default": "/"
                    }
                }
            }
        ),
        Tool(
            name="find_files",
            description="Search for files matching a pattern in a directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Starting directory path"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "File pattern to match (e.g., '*.py', 'test*.txt')"
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Search recursively (default: true)",
                        "default": True
                    },
                    "file_type": {
                        "type": "string",
                        "description": "Filter by type: 'file' or 'directory' (optional)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 100)",
                        "default": 100
                    }
                },
                "required": ["path", "pattern"]
            }
        ),
        Tool(
            name="get_network_connections",
            description="Get active network connections and listening ports",
            inputSchema={
                "type": "object",
                "properties": {
                    "filter_type": {
                        "type": "string",
                        "description": "Filter by connection type: 'tcp' or 'udp' (optional)"
                    }
                }
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "get_local_ip":
            local_ip = get_local_ip()
            network_prefix = get_network_prefix()
            result = {
                "local_ip": local_ip,
                "network_prefix": network_prefix,
                "network_range": f"{network_prefix}.1-254"
            }
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "scan_network":
            network_prefix = arguments.get("network_prefix") or get_network_prefix()
            start_ip = arguments.get("start_ip", 1)
            end_ip = arguments.get("end_ip", 254)
            
            hosts = await scan_network(network_prefix, start_ip, end_ip)
            result = {
                "network_scanned": f"{network_prefix}.{start_ip}-{end_ip}",
                "active_hosts": hosts,
                "total_found": len(hosts)
            }
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "ping_host":
            host = arguments["host"]
            result = ping_host(host)
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "check_port":
            host = arguments["host"]
            port = arguments["port"]
            result = check_port(host, port)
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "scan_ports":
            host = arguments["host"]
            ports = arguments["ports"]
            results = scan_ports(host, ports)
            return [TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )]
        
        elif name == "ssh_connect":
            result = ssh_connect(
                host=arguments["host"],
                username=arguments["username"],
                password=arguments.get("password"),
                key_filename=arguments.get("key_filename"),
                port=arguments.get("port", 22)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "ssh_execute":
            result = ssh_execute(
                host=arguments["host"],
                username=arguments["username"],
                command=arguments["command"],
                password=arguments.get("password"),
                key_filename=arguments.get("key_filename"),
                port=arguments.get("port", 22),
                timeout=arguments.get("timeout", 30)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "ssh_disconnect":
            result = ssh_disconnect(
                host=arguments["host"],
                username=arguments["username"],
                port=arguments.get("port", 22)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "ssh_list_connections":
            result = ssh_list_connections()
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        # Local command tools
        elif name == "execute_local_command":
            result = execute_local_command(
                command=arguments["command"],
                shell=arguments.get("shell", True),
                timeout=arguments.get("timeout", 30),
                cwd=arguments.get("cwd"),
                env=arguments.get("env")
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "get_system_info":
            result = get_system_info()
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "list_processes":
            result = list_processes(
                filter_name=arguments.get("filter_name"),
                limit=arguments.get("limit", 50)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "kill_process":
            result = kill_process(
                pid=arguments["pid"],
                force=arguments.get("force", False)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "get_environment_variables":
            result = get_environment_variables(
                filter_key=arguments.get("filter_key")
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "get_directory_listing":
            result = get_directory_listing(
                path=arguments.get("path", "."),
                recursive=arguments.get("recursive", False),
                show_hidden=arguments.get("show_hidden", False),
                max_depth=arguments.get("max_depth", 3)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "get_disk_usage":
            result = get_disk_usage(
                path=arguments.get("path", "/")
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "find_files":
            result = find_files(
                path=arguments["path"],
                pattern=arguments["pattern"],
                recursive=arguments.get("recursive", True),
                file_type=arguments.get("file_type"),
                max_results=arguments.get("max_results", 100)
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        elif name == "get_network_connections":
            result = get_network_connections(
                filter_type=arguments.get("filter_type")
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        
        else:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]
    
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"Error executing {name}: {str(e)}"
        )]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
