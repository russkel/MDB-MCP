from modules.gdb.gdbTools import format_gdb_response


def test_guardrail_truncates_huge_console_flood():
    big = [{"type": "console", "payload": f"line {i}\n"} for i in range(5000)]
    out = format_gdb_response(big, max_lines=200)
    assert out.count("\n") <= 210
    assert "lines elided" in out


def test_guardrail_keeps_small_output_intact():
    small = [{"type": "console", "payload": "hello\n"}]
    out = format_gdb_response(small, max_lines=200)
    assert "hello" in out
    assert "lines elided" not in out


import os
from modules.gdb.sessionManager import GDBSessionManager
from modules.gdb.gdbTools import GDBTools

GEF = os.path.expanduser("~/work/gef/gef.py")
TGT = os.path.expanduser("~/work/binary-debug-plugin/tests/fixtures/target")


def test_session_sources_gef_fork_and_headless_works():
    sm = GDBSessionManager()
    t = GDBTools(sm)
    sid = sm.create_session("gdb", gef_path=GEF)
    try:
        t.execute_command(sid, "gef config gef.headless on")
        t.execute_command(sid, f"file {TGT}")
        t.execute_command(sid, "break main")
        t.execute_command(sid, "run")
        out = t.execute_command(sid, "registers")
        assert "regs[" in out
    finally:
        sm.terminate_session(sid)
