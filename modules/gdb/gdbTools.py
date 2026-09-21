"""GDB debugging tools and utilities."""

import json
import logging
import socket
import subprocess
import tempfile
import time
import shutil
from pathlib import Path
from typing import List, Dict, Any, Callable
from functools import wraps
from .sessionManager import GDBSessionManager
from .toon import encode_table, encode_hexdump
from ..base.debuggerBase import DebuggerTools

logger = logging.getLogger(__name__)

# Marker used to fish a JSON payload back out of gdb's console stream when we run a
# Python snippet inside gdb. json.dumps emits a single line (no newlines), so the
# payload is everything between the marker and the next newline.
_JSON_MARK = "MDBJSON:"

# Bounds — structured tools must never flood the model's context.
_READ_MEM_MAX = 4096      # bytes per gdb_read_mem call
_MAPS_MAX_ROWS = 500      # rows per gdb_maps call

def handle_gdb_errors(operation: str) -> Callable:
    """Decorator to handle GDB operation errors consistently."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> str:
            try:
                return func(*args, **kwargs)
            except BrokenPipeError:
                return f"Error {operation}: GDB session connection lost (broken pipe). The session may have crashed."
            except ValueError as e:
                if "not found" in str(e) or "not active" in str(e):
                    return f"Error {operation}: {str(e)}"
                return f"Error {operation}: Invalid parameter - {str(e)}"
            except Exception as e:
                error_msg = str(e)
                if "Broken pipe" in error_msg:
                    return f"Error {operation}: GDB session connection lost. The session may have crashed."
                return f"Error {operation}: {error_msg}"
        return wrapper
    return decorator

def format_gdb_response(response: List[Dict[str, Any]], max_lines: int = 400) -> str:
    """Format GDB response for better readability, capping total lines."""
    if not response:
        return "No response from GDB"
    
    formatted_lines = []
    for msg in response:
        msg_type = msg.get('type', 'unknown')
        payload = str(msg.get('payload', '')).rstrip("\n")
        
        if msg_type == 'console':
            formatted_lines.append(f"Console: {payload}")
        elif msg_type == 'log':
            formatted_lines.append(f"Log: {payload}")
        elif msg_type == 'target':
            formatted_lines.append(f"Target: {payload}")
        elif msg_type == 'result':
            message = msg.get('message', '')
            if message == 'done':
                payload_str = str(payload) if payload else "Command completed successfully"
                formatted_lines.append(f"Result: {payload_str}")
            else:
                formatted_lines.append(f"Result ({message}): {payload}")
        else:
            formatted_lines.append(f"{msg_type.title()}: {payload}")
    
    if not formatted_lines:
        return "Command executed"
    lines = '\n'.join(formatted_lines).split('\n')
    if len(lines) > max_lines:
        elided = len(lines) - max_lines
        lines = lines[:max_lines]
        lines.append(
            f"…[{elided} lines elided — re-run with an explicit range/length]")
    return '\n'.join(lines)

class GDBTools(DebuggerTools):
    """Collection of GDB debugging tools."""
    
    def __init__(self, session_manager: GDBSessionManager):
        super().__init__(session_manager)
        self.sessionManager = session_manager
    
    @handle_gdb_errors("starting GDB session")
    def start_session(self, gdb_path: str = "gdb", gef_path: str = None) -> str:
        session_id = self.sessionManager.create_session(gdb_path, gef_path)
        return f"GDB session started successfully. Session ID: {session_id}"
    
    @handle_gdb_errors("terminating session")
    def terminate_session(self, session_id: str) -> str:
        if self.sessionManager.terminate_session(session_id):
            return f"GDB session '{session_id}' terminated successfully"
        return f"GDB session '{session_id}' not found"
    
    def list_sessions(self) -> str:
        sessions = self.sessionManager.list_sessions()
        if not sessions:
            return "No active GDB sessions"
        return "Active GDB sessions:\n" + "\n".join(f"- {sid}" for sid in sessions)
    
    @handle_gdb_errors("loading program")
    def load_program(self, session_id: str, program_path: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        if not Path(program_path).exists():
            return f"Error: Program file '{program_path}' does not exist"
        response = gdb.write(f"file {program_path}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("executing command")
    def execute_command(self, session_id: str, command: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        try:
            response = gdb.write(command)
            return format_gdb_response(response)
        except BrokenPipeError:
            self.sessionManager._cleanup_dead_session(session_id)
            raise BrokenPipeError("GDB session connection lost")
    
    @handle_gdb_errors("attaching to process")
    def attach_to_process(self, session_id: str, pid: int) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"attach {pid}")
        return format_gdb_response(response)

    @handle_gdb_errors("starting rr replay")
    def rr_replay(self, session_id: str, trace_dir: str, port: int = 50505) -> str:
        """Start `rr replay` as a gdbserver on `port` and connect this session to it.

        Recording (`rr record`) is a manual user step; `trace_dir` is an existing trace.
        """
        gdb = self.sessionManager.get_session(session_id)
        if shutil.which("rr") is None:
            return "Error: rr is not installed"
        if not Path(trace_dir).exists():
            return f"Error: trace dir '{trace_dir}' does not exist"
        proc = subprocess.Popen(
            ["rr", "replay", "-s", str(port), "--keep-listening", trace_dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.sessionManager.attach_rr_process(session_id, proc)
        # Wait for rr's gdbserver to bind the port (deterministic, no fixed sleep).
        for _ in range(50):  # ~10s max at 0.2s/iter
            if proc.poll() is not None:
                self.sessionManager._kill_rr_process(session_id)
                return f"Error: rr replay exited early (code {proc.returncode})"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            self.sessionManager._kill_rr_process(session_id)
            return f"Error: rr gdbserver did not bind port {port} in time"
        # Must precede the connect: rr's gdbinit does `set non-stop off`, which gdb
        # refuses once an inferior is running. rr's own launch line sources it first too.
        note = self._source_rr_gdbinit(gdb)
        response = gdb.write(f"target extended-remote :{port}")
        # pygdbmi does NOT raise on a gdb-level error; detect a failed connect.
        connected = not any(
            m.get("type") == "result" and m.get("message") == "error"
            for m in response
        )
        if not connected:
            self.sessionManager._kill_rr_process(session_id)
            return f"Error: failed to connect to rr gdbserver on :{port}: {format_gdb_response(response)}"
        # Local-architecture trace: point sysroot at the local fs to avoid slow
        # remote file transfers (matches rr's own gdb launch line).
        gdb.write("set sysroot /")
        return format_gdb_response(response) + note

    @staticmethod
    def _source_rr_gdbinit(gdb) -> str:
        """Define rr's own gdb commands in this session.

        `when`, `when-ticks`, `when-tid`, `elapsed-time`, `checkpoint`, `restart`,
        `seek-ticks` and `back`/`forward` are not gdb builtins and are not part of the
        remote protocol -- `rr gdbinit` emits Python that defines them as wrappers around
        `maint packet qRRCmd:<cmd>:<tid>`. rr only installs it when rr itself launches
        gdb, so a session that connects with `target extended-remote` has none of them
        until we source it here.

        Best effort: a failure costs the navigation commands, not the replay session.
        """
        try:
            init = subprocess.run(
                ["rr", "gdbinit"], capture_output=True, text=True, timeout=30,
            )
            if init.returncode != 0 or not init.stdout:
                return "\nWarning: `rr gdbinit` produced nothing; `when`/`seek-ticks` unavailable."
            # gdb reads the file synchronously, so it can go away right after.
            with tempfile.NamedTemporaryFile(
                "w", suffix=".gdbinit", delete=True
            ) as f:
                f.write(init.stdout)
                f.flush()
                out = gdb.write(f"source {f.name}")
            if any(
                m.get("type") == "result" and m.get("message") == "error" for m in out
            ):
                return f"\nWarning: sourcing rr's gdbinit failed: {format_gdb_response(out)}"
            return ""
        except (OSError, subprocess.SubprocessError) as e:
            return f"\nWarning: could not load rr's gdb commands ({e}); `when`/`seek-ticks` unavailable."
    
    @handle_gdb_errors("loading core dump")
    def load_core_dump(self, session_id: str, core_file: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        if not Path(core_file).exists():
            return f"Error: Core file '{core_file}' does not exist"
        response = gdb.write(f"core {core_file}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("setting breakpoint")
    def set_breakpoint(self, session_id: str, location: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"break {location}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("continuing execution")
    def continue_execution(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("continue")
        return format_gdb_response(response)
    
    @handle_gdb_errors("stepping execution")
    def step_execution(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("step")
        return format_gdb_response(response)
    
    @handle_gdb_errors("stepping to next line")
    def next_execution(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("next")
        return format_gdb_response(response)
    
    @handle_gdb_errors("finishing function")
    def finish_function(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("finish")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting backtrace")
    def get_backtrace(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("backtrace")
        return format_gdb_response(response)
    
    @handle_gdb_errors("printing expression")
    def print_expression(self, session_id: str, expression: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"print {expression}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("examining memory")
    def examine_memory(self, session_id: str, address: str, format_spec: str = "x") -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"x/{format_spec} {address}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting register info")
    def get_registers(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("info registers")
        return format_gdb_response(response)
    
    @handle_gdb_errors("disassembling function")
    def disassemble_function(self, session_id: str, function_name: str, mixed_mode: bool = False) -> str:
        gdb = self.sessionManager.get_session(session_id)
        mode = "1" if mixed_mode else "0"
        response = gdb.write(f"-data-disassemble -f {function_name} -- {mode}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("disassembling address range")
    def disassemble_address_range(self, session_id: str, start_addr: str, end_addr: str, mixed_mode: bool = False) -> str:
        gdb = self.sessionManager.get_session(session_id)
        mode = "1" if mixed_mode else "0"
        response = gdb.write(f"-data-disassemble -s {start_addr} -e {end_addr} -- {mode}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("disassembling around PC")
    def disassemble_around_pc(self, session_id: str, instruction_count: int = 10, mixed_mode: bool = False) -> str:
        gdb = self.sessionManager.get_session(session_id)
        mode = "1" if mixed_mode else "0"
        response = gdb.write(f"-data-disassemble -s $pc -e \"$pc + {instruction_count * 4}\" -- {mode}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting local variables")
    def get_local_variables(self, session_id: str, print_values: bool = True) -> str:
        gdb = self.sessionManager.get_session(session_id)
        values_flag = "1" if print_values else "0"
        response = gdb.write(f"-stack-list-locals {values_flag}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting function arguments")
    def get_function_arguments(self, session_id: str, print_values: bool = True) -> str:
        gdb = self.sessionManager.get_session(session_id)
        values_flag = "1" if print_values else "0"
        response = gdb.write(f"-stack-list-arguments {values_flag}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting stack frames")
    def get_stack_frames(self, session_id: str, low_frame: int = None, high_frame: int = None) -> str:
        gdb = self.sessionManager.get_session(session_id)
        if low_frame is not None and high_frame is not None:
            response = gdb.write(f"-stack-list-frames {low_frame} {high_frame}")
        else:
            response = gdb.write("-stack-list-frames")
        return format_gdb_response(response)
    
    @handle_gdb_errors("evaluating expression")
    def evaluate_expression(self, session_id: str, expression: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-data-evaluate-expression \"{expression}\"")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting register names")
    def get_register_names(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("-data-list-register-names")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting register values")
    def get_register_values(self, session_id: str, register_numbers: list = None) -> str:
        gdb = self.sessionManager.get_session(session_id)
        if register_numbers:
            reg_list = " ".join(map(str, register_numbers))
            response = gdb.write(f"-data-list-register-values x {reg_list}")
        else:
            response = gdb.write("-data-list-register-values x")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting changed registers")
    def get_changed_registers(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("-data-list-changed-registers")
        return format_gdb_response(response)
    
    @handle_gdb_errors("reading memory bytes")
    def read_memory_bytes(self, session_id: str, address: str, byte_count: int) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-data-read-memory-bytes {address} {byte_count}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting thread info")
    def get_thread_info(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("-thread-info")
        return format_gdb_response(response)
    
    @handle_gdb_errors("switching thread")
    def switch_thread(self, session_id: str, thread_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-thread-select {thread_id}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting breakpoint list")
    def get_breakpoint_list(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("-break-list")
        return format_gdb_response(response)
    
    @handle_gdb_errors("deleting breakpoint")
    def delete_breakpoint(self, session_id: str, breakpoint_number: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-break-delete {breakpoint_number}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("enabling breakpoint")
    def enable_breakpoint(self, session_id: str, breakpoint_number: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-break-enable {breakpoint_number}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("disabling breakpoint")
    def disable_breakpoint(self, session_id: str, breakpoint_number: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-break-disable {breakpoint_number}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("setting watchpoint")
    def set_watchpoint(self, session_id: str, expression: str, watch_type: str = "write") -> str:
        gdb = self.sessionManager.get_session(session_id)
        if watch_type == "read":
            response = gdb.write(f"-break-watch -r {expression}")
        elif watch_type == "access":
            response = gdb.write(f"-break-watch -a {expression}")
        else:
            response = gdb.write(f"-break-watch {expression}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("getting symbol info")
    def get_symbol_info(self, session_id: str, symbol_name: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write(f"-symbol-info-functions --name {symbol_name}")
        return format_gdb_response(response)
    
    @handle_gdb_errors("listing source files")
    def list_source_files(self, session_id: str) -> str:
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("-file-list-exec-source-files")
        return format_gdb_response(response)

    # --- Structured tools (gdb/GEF Python API -> TOON) -------------------------
    # These run a Python snippet inside gdb that builds a JSON-able object in the
    # variable `__mdb_out`, ship it back via the JSON marker, and re-encode it as a
    # compact TOON table for the model. Registers/memory use gdb's *native* Python
    # API (stable, and works even if GEF didn't load); maps use GEF's richer view.

    def _run_python_json(self, session_id: str, snippet: str):
        """Execute `snippet` (which must set `__mdb_out`) inside gdb and return
        (ok, parsed_obj_or_error_text)."""
        gdb = self.sessionManager.get_session(session_id)
        # `set width 0` stops gdb wrapping the printed JSON across multiple lines
        # (which would otherwise split our single-line payload); pagination off
        # avoids a "---Type <return>---" prompt on long output.
        program = (
            "import gdb as _gdb\n"
            "_gdb.execute('set width 0', to_string=True)\n"
            "_gdb.execute('set pagination off', to_string=True)\n"
            + snippet
            + f"\nimport json as _j\nprint({_JSON_MARK!r} + _j.dumps(__mdb_out))"
        )

        def _find_blob(records):
            # Scan only program output, NOT 'log' records — gdb echoes the MI command
            # there, and the echoed source literally contains "MDBJSON:" + the marker,
            # which would otherwise match before the real printed line.
            text = "".join(str(m.get("payload", "")) for m in records
                           if m.get("type") != "log")
            i = text.find(_JSON_MARK)
            if i == -1:
                return None
            return text[i + len(_JSON_MARK):].split("\n", 1)[0].strip()

        # `python exec(<repr>)` keeps the whole multi-line program on one MI line.
        # pygdbmi returns at the command's `^done`, but the snippet's `print` console
        # line can land in a *later* read — so drain follow-up responses until the
        # marker appears (or we settle).
        records = list(gdb.write("python exec(%r)" % program,
                                 timeout_sec=2, raise_error_on_timeout=False))
        blob = _find_blob(records)
        attempts = 0
        while blob is None and attempts < 15:
            more = gdb.get_gdb_response(timeout_sec=0.2, raise_error_on_timeout=False)
            attempts += 1
            if more:
                records += more
                blob = _find_blob(records)
        if blob is None:
            return False, format_gdb_response(records)
        try:
            return True, json.loads(blob)
        except json.JSONDecodeError:
            return False, format_gdb_response(records)

    @handle_gdb_errors("reading registers")
    def registers_toon(self, session_id: str, names: List[str] = None) -> str:
        """Registers as a `regs[N]{reg,val}:` TOON table. Defaults to the 'general'
        register group (skips the hundreds of vector/segment regs); pass `names` to
        filter. Native gdb API — works on a coredump and without GEF."""
        snippet = (
            "import gdb\n"
            "frame = gdb.selected_frame()\n"
            "arch = frame.architecture()\n"
            f"want = {repr(list(names) if names else None)}\n"
            "rows = []\n"
            "for rd in arch.registers('general'):\n"
            "    nm = rd.name\n"
            "    if want and nm not in want:\n"
            "        continue\n"
            "    try:\n"
            "        v = int(frame.read_register(nm)) & ((1 << 64) - 1)\n"
            "        rows.append([nm, hex(v)])\n"
            "    except Exception:\n"
            "        pass\n"
            "__mdb_out = rows\n"
        )
        ok, obj = self._run_python_json(session_id, snippet)
        if not ok:
            return f"Error reading registers (is a frame selected / program loaded?): {obj}"
        return encode_table("regs", ["reg", "val"], obj)

    @handle_gdb_errors("reading memory")
    def read_memory_toon(self, session_id: str, address: str, count: int) -> str:
        """Read `count` bytes at `address` (any gdb expression, e.g. `$pc`, `$sp+0x20`,
        a symbol) and render GEF-style `hex[N]{addr,bytes,ascii}:`. Native gdb API."""
        n = max(0, min(int(count), _READ_MEM_MAX))
        if n == 0:
            return encode_hexdump(0, b"")  # -> "hex[0]:"
        snippet = (
            "import gdb\n"
            f"addr = int(gdb.parse_and_eval({address!r})) & ((1 << 64) - 1)\n"
            f"data = bytes(gdb.selected_inferior().read_memory(addr, {n}))\n"
            "__mdb_out = {'base': addr, 'hex': data.hex()}\n"
        )
        ok, obj = self._run_python_json(session_id, snippet)
        if not ok:
            return f"Error reading memory at {address}: {obj}"
        out = encode_hexdump(obj["base"], bytes.fromhex(obj["hex"]))
        if int(count) > _READ_MEM_MAX:
            out += f"\n  …[capped at {_READ_MEM_MAX} bytes — re-run from a higher address for more]"
        return out

    @handle_gdb_errors("listing memory maps")
    def maps_toon(self, session_id: str, name_filter: str = None) -> str:
        """Memory map as `maps[N]{start,end,perm,path}:` via GEF's `gef.memory.maps`
        (richer than scraping `info proc mappings`). Requires GEF to be loaded;
        `name_filter` keeps only rows whose path contains that substring."""
        snippet = (
            f"flt = {repr(name_filter)}\n"
            "rows = []\n"
            "for s in gef.memory.maps:\n"
            "    p = s.path or ''\n"
            "    if flt and flt not in p:\n"
            "        continue\n"
            "    perm = ('r' if s.is_readable() else '-') + ('w' if s.is_writable() else '-') + ('x' if s.is_executable() else '-')\n"
            "    rows.append([hex(s.page_start), hex(s.page_end), perm, p])\n"
            "__mdb_out = rows\n"
        )
        ok, obj = self._run_python_json(session_id, snippet)
        if not ok:
            return ("Error listing maps. `gdb_maps` needs GEF loaded (it uses "
                    f"gef.memory.maps); start the session with a gef_path. Detail: {obj}")
        return encode_table("maps", ["start", "end", "perm", "path"], obj,
                            max_rows=_MAPS_MAX_ROWS)

    @handle_gdb_errors("running python")
    def run_python(self, session_id: str, code: str) -> str:
        """Escape hatch: run an arbitrary Python `code` snippet inside gdb and return
        its stdout. `gdb` and (if loaded) `gef` are in scope, so the full GEF Python
        API is reachable for one-off structured extraction the dedicated tools don't
        cover. Keep what you print small."""
        gdb = self.sessionManager.get_session(session_id)
        response = gdb.write("python exec(%r)" % code)
        return format_gdb_response(response)