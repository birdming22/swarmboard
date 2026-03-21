"""
SwarmBoard MCP Server

Usage:
    uv run python -m swarmboard.mcp

This MCP server provides tools to interact with SwarmBoard instances.
"""

import json
import subprocess
import os
import threading
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SwarmBoard")

WORKDIR = Path("/home/k200/workspace/swarmboard")

processes: dict[str, subprocess.Popen] = {}


def run_command(cmd: list[str], name: str) -> str:
    """Run a command in the background and return status."""
    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        cwd=str(WORKDIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    processes[name] = proc
    return f"Started {name} with PID {proc.pid}"


@mcp.tool()
def start_server() -> str:
    """Start the SwarmBoard server."""
    return run_command(["uv", "run", "swarmboard-server"], "server")


@mcp.tool()
def start_client(model: str, instance_id: Optional[str] = None) -> str:
    """Start an AI client instance."""
    cmd = ["uv", "run", "swarmboard-client", "--model", model]
    if instance_id:
        cmd.extend(["--instance-id", instance_id])
    name = f"client-{model}"
    return run_command(cmd, name)


@mcp.tool()
def start_commander(name: str = "commander") -> str:
    """Start a human commander instance."""
    cmd = ["uv", "run", "swarmboard-commander", "--name", name]
    return run_command(cmd, f"commander-{name}")


@mcp.tool()
def stop_instance(instance_name: str) -> str:
    """Stop a running SwarmBoard instance."""
    if instance_name in processes:
        proc = processes[instance_name]
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        del processes[instance_name]
        return f"Stopped {instance_name}"
    return f"Instance {instance_name} not found"


@mcp.tool()
def list_instances() -> str:
    """List all running SwarmBoard instances."""
    if not processes:
        return "No running instances"
    
    status = []
    for name, proc in processes.items():
        if proc.poll() is None:
            status.append(f"- {name}: running (PID {proc.pid})")
        else:
            status.append(f"- {name}: stopped")
    
    return "\n".join(status) if status else "No running instances"


@mcp.tool()
def stop_all() -> str:
    """Stop all running SwarmBoard instances."""
    count = 0
    for name, proc in list(processes.items()):
        proc.terminate()
        count += 1
    
    for name, proc in processes.items():
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    
    processes.clear()
    return f"Stopped {count} instances"


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
