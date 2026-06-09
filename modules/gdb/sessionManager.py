"""GDB session management module."""

import logging
import uuid
import subprocess
from typing import Dict
from pygdbmi.gdbcontroller import GdbController
from ..base.debuggerBase import DebuggerSessionManager

logger = logging.getLogger(__name__)

class GDBSessionManager(DebuggerSessionManager):
    
    def __init__(self):
        self.sessions: Dict[str, GdbController] = {}
        self.rr_processes: Dict[str, "subprocess.Popen"] = {}
    
    def create_session(self, gdb_path: str = "gdb", gef_path: str = None) -> str:
        session_id = str(uuid.uuid4())
        command = [gdb_path, "-nx", "--interpreter=mi3"]
        if gef_path:
            command += ["-ex", f"source {gef_path}"]
        try:
            gdb_controller = GdbController(command=command)
            self.sessions[session_id] = gdb_controller
            logger.info(f"Started GDB session: {session_id} (gef_path={gef_path})")
            return session_id
        except Exception as e:
            logger.error(f"Failed to start GDB session: {e}")
            raise
    
    def get_session(self, session_id: str) -> GdbController:
        if session_id not in self.sessions:
            raise ValueError(f"GDB session '{session_id}' not found. Use gdb_list_sessions to see active sessions.")
        
        gdb = self.sessions[session_id]
        if not self._is_session_alive(gdb):
            logger.warning(f"Session {session_id} appears to be dead, cleaning up")
            self._cleanup_dead_session(session_id)
            raise ValueError(f"GDB session '{session_id}' is no longer active")
        
        return gdb
    
    def terminate_session(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        try:
            self._kill_rr_process(session_id)
            gdb = self.sessions[session_id]
            gdb.exit()
            del self.sessions[session_id]
            logger.info(f"Terminated GDB session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to terminate GDB session: {e}")
            return False
    
    def list_sessions(self) -> list:
        self._cleanup_dead_sessions()
        return list(self.sessions.keys())
    
    def has_session(self, session_id: str) -> bool:
        return session_id in self.sessions

    def attach_rr_process(self, session_id: str, proc: "subprocess.Popen") -> None:
        """Track an rr replay gdbserver bound to a session, for teardown."""
        self.rr_processes[session_id] = proc

    def _kill_rr_process(self, session_id: str) -> None:
        proc = self.rr_processes.pop(session_id, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    
    def _is_session_alive(self, gdb: GdbController) -> bool:
        """Check if a GDB session is still alive."""
        try:
            if hasattr(gdb, 'gdb_process') and gdb.gdb_process:
                return gdb.gdb_process.poll() is None
            return False
        except Exception:
            return False
    
    def _cleanup_dead_session(self, session_id: str):
        """Clean up a single dead session."""
        try:
            if session_id in self.sessions:
                self._kill_rr_process(session_id)
                gdb = self.sessions[session_id]
                try:
                    gdb.exit()
                except Exception:
                    pass  # Session might already be dead
                del self.sessions[session_id]
                logger.info(f"Cleaned up dead session: {session_id}")
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")
    
    def _cleanup_dead_sessions(self):
        """Clean up all dead sessions."""
        dead_sessions = []
        for session_id, gdb in self.sessions.items():
            if not self._is_session_alive(gdb):
                dead_sessions.append(session_id)
        
        for session_id in dead_sessions:
            self._cleanup_dead_session(session_id)
    
    @staticmethod
    def is_available() -> bool:
        """Check if GDB is available on this system."""
        import subprocess
        try:
            result = subprocess.run(['gdb', '--version'], capture_output=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False