#!/usr/bin/env python3
"""
Multi-Debugger MCP Server

A Model Context Protocol server that provides debugging functionality
for GDB and LLDB debuggers, for use with Claude Desktop, VSCode Copilot, 
or other AI assistants.
"""

import logging
import os
from mcp.server.fastmcp import FastMCP
from modules import DebuggerFactory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to a GEF fork bundled as a sibling of this server (e.g. the plugin's
# vendor/gef next to vendor/MDB-MCP). Used as the default gef_path for gdb_start.
# NOTE: this sibling only exists for in-place runs. When the server is installed
# as a wheel and run via `uvx`/`pipx`, server.py lands in site-packages and the
# sibling `../gef` is NOT packaged with it (it lives outside this repo), so this
# path won't exist — hence the MDB_GEF_PATH env override below.
_BUNDLED_GEF = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gef", "gef.py"))


def _resolve_gef_path(gef_path):
    """Resolve the headless GEF fork when no explicit gef_path is given.

    Order: explicit arg > MDB_GEF_PATH env var > bundled sibling gef.py. The env
    var is the reliable option under uvx/pipx, where the sibling doesn't exist.
    Returns None if nothing resolves — gdb then starts WITHOUT GEF (losing TOON
    compaction), so we log a visible warning rather than failing silently.
    """
    if gef_path:
        return gef_path
    env_path = os.environ.get("MDB_GEF_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    if os.path.isfile(_BUNDLED_GEF):
        return _BUNDLED_GEF
    logger.warning(
        "GEF fork not found (MDB_GEF_PATH=%r, bundled=%r); starting gdb WITHOUT "
        "GEF. Output will be verbose/uncompacted — pass gef_path=... to gdb_start "
        "or set MDB_GEF_PATH to the headless gef.py.", env_path, _BUNDLED_GEF)
    return None

try:
    debugger_tools, debugger_type = DebuggerFactory.create_tools()
    logger.info(f"Using {debugger_type.upper()} debugger")
    mcp = FastMCP(f"{debugger_type.upper()} Debugger")
except Exception as e:
    logger.error(f"No debuggers available: {e}")
    logger.info("Available debuggers:")
    logger.info(DebuggerFactory.list_debuggers())
    mcp = FastMCP("Debugger MCP (No Debuggers Available)")
    debugger_tools = None
    debugger_type = None

_gdb_tools_instance = None

def _get_gdb_tools():
    """Helper function to get GDB tools with error handling and singleton pattern."""
    global _gdb_tools_instance
    if _gdb_tools_instance is None:
        try:
            _gdb_tools_instance, _ = DebuggerFactory.create_tools('gdb')
        except Exception as e:
            raise RuntimeError(f"GDB not available: {str(e)}")
    return _gdb_tools_instance

# Unified debugger tools (work with any available debugger)
@mcp.tool()
def debugger_status() -> str:
    """Get status of available debuggers."""
    return DebuggerFactory.list_debuggers()

@mcp.tool()
def debugger_start(debugger_type_param: str = None, debugger_path: str = None) -> str:
    """Start a debugging session with auto-detection or specified debugger type."""
    if not debugger_tools:
        return "Error: No debuggers are available on this system"
    
    if debugger_path is None:
        debugger_path = "gdb"  # Default to gdb
    
    return debugger_tools.start_session(debugger_path)

@mcp.tool()
def debugger_terminate(session_id: str) -> str:
    """Terminate a debugging session."""
    if not debugger_tools:
        return "Error: No debuggers are available on this system"
    return debugger_tools.terminate_session(session_id)

@mcp.tool()
def debugger_list_sessions() -> str:
    """List all active debugging sessions."""
    if not debugger_tools:
        return "Error: No debuggers are available on this system"
    return debugger_tools.list_sessions()

@mcp.tool()
def debugger_command(session_id: str, command: str) -> str:
    """Execute an arbitrary debugger command."""
    if not debugger_tools:
        return "Error: No debuggers are available on this system"
    return debugger_tools.execute_command(session_id, command)
    
# GDB-specific tools (use gdb_command for advanced features)
@mcp.tool()
def gdb_start(gdb_path: str = "gdb", gef_path: str = None) -> str:
    """Start a new GDB session. Sources a headless GEF fork: the explicit gef_path
    if given, else a bundled sibling gef.py if present. gdb launches with `-nx`."""
    try:
        return _get_gdb_tools().start_session(gdb_path, _resolve_gef_path(gef_path))
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def gdb_terminate(session_id: str) -> str:
    """Terminate a GDB debugging session."""
    try:
        return _get_gdb_tools().terminate_session(session_id)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def gdb_list_sessions() -> str:
    """List all active GDB sessions."""
    try:
        return _get_gdb_tools().list_sessions()
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def gdb_command(session_id: str, command: str) -> str:
    """Execute any arbitrary GDB command. Use this for all GDB operations."""
    try:
        return _get_gdb_tools().execute_command(session_id, command)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def gdb_rr_replay(session_id: str, trace_dir: str, port: int = 50505) -> str:
    """Connect a GDB session to an rr time-travel trace via the gdbserver bridge.

    Enables reverse-continue / reverse-step / reverse-next and backwards watchpoints.
    `trace_dir` must be an existing rr trace (record it beforehand with `rr record`).
    """
    try:
        return _get_gdb_tools().rr_replay(session_id, trace_dir, port)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.resource("gdb://sessions")
def list_gdb_sessions() -> str:
    """Resource that provides information about active GDB sessions."""
    try:
        tools, _ = DebuggerFactory.create_tools('gdb')
        sessions = tools.list_sessions()
        if not sessions:
            return "No active GDB sessions"
        
        session_info = [f"Session ID: {session_id}" for session_id in sessions]
        return "Active GDB Sessions:\n" + "\n".join(session_info)
    except Exception as e:
        return f"Error: {str(e)}"

_lldb_tools_instance = None

def _get_lldb_tools():
    """Helper function to get LLDB tools with error handling and singleton pattern."""
    global _lldb_tools_instance
    if _lldb_tools_instance is None:
        try:
            _lldb_tools_instance, _ = DebuggerFactory.create_tools('lldb')
        except Exception as e:
            raise RuntimeError(f"LLDB not available: {str(e)}")
    return _lldb_tools_instance

# LLDB-specific tools
@mcp.tool()
def lldb_start(lldb_path: str = None) -> str:
    """Start a new LLDB debugging session."""
    try:
        return _get_lldb_tools().start_session(lldb_path)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def lldb_terminate(session_id: str) -> str:
    """Terminate an LLDB debugging session."""
    try:
        return _get_lldb_tools().terminate_session(session_id)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def lldb_list_sessions() -> str:
    """List all active LLDB sessions."""
    try:
        return _get_lldb_tools().list_sessions()
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def lldb_command(session_id: str, command: str) -> str:
    """Execute an arbitrary LLDB command."""
    try:
        return _get_lldb_tools().execute_command(session_id, command)
    except Exception as e:
        return f"Error: {str(e)}"

def main():
    """Console-script entry point so the server is runnable via uvx/uv tool."""
    mcp.run()


if __name__ == "__main__":
    main()