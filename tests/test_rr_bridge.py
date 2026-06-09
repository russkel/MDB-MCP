import os
import shutil
import subprocess
import pytest

from modules.gdb.sessionManager import GDBSessionManager
from modules.gdb.gdbTools import GDBTools

FIX = os.path.expanduser("~/work/binary-debug-plugin/tests/fixtures")
GEF = os.path.expanduser("~/work/gef/gef.py")
TRACE = os.path.join(FIX, "rr-trace", "latest-trace")

pytestmark = pytest.mark.skipif(
    shutil.which("rr") is None or not os.path.isdir(os.path.join(FIX, "rr-trace")),
    reason="rr not installed or no recorded trace (run `make -C tests/fixtures trace`)",
)


def test_rr_replay_enables_reverse_execution():
    sm = GDBSessionManager()
    t = GDBTools(sm)
    sid = sm.create_session("gdb", gef_path=GEF)
    try:
        msg = t.rr_replay(sid, TRACE, port=50607)
        assert not msg.startswith("Error"), msg  # bridge connected successfully
        t.execute_command(sid, "break compute")
        t.execute_command(sid, "continue")
        out = t.execute_command(sid, "reverse-continue")
        assert "does not support" not in out.lower()
    finally:
        sm.terminate_session(sid)
