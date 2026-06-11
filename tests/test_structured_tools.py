"""Integration tests for the structured (TOON-emitting) GDB tools.

Mirrors test_headless_mcp's live pattern: source the GEF fork, load the fixture
target, break at main, run, then exercise the structured tools against real state.
"""

import os
import pytest

from modules.gdb.sessionManager import GDBSessionManager
from modules.gdb.gdbTools import GDBTools

GEF = os.path.expanduser("~/work/gef/gef.py")
TGT = os.path.expanduser("~/work/binary-debug-plugin/tests/fixtures/target")


@pytest.fixture
def live_session():
    sm = GDBSessionManager()
    t = GDBTools(sm)
    sid = sm.create_session("gdb", gef_path=GEF)
    t.execute_command(sid, "gef config gef.headless on")
    t.execute_command(sid, f"file {TGT}")
    t.execute_command(sid, "break main")
    t.execute_command(sid, "run")
    try:
        yield t, sid
    finally:
        sm.terminate_session(sid)


@pytest.mark.requires_gdb
def test_registers_toon_emits_table(live_session):
    t, sid = live_session
    out = t.registers_toon(sid)
    assert out.startswith("regs[")
    assert "{reg,val}:" in out
    assert "rsp" in out          # rsp is in the 'general' group on x86-64
    # every value column is a hex literal
    rows = [l for l in out.splitlines()[1:] if l.strip()]
    assert rows and all(",0x" in r for r in rows)


@pytest.mark.requires_gdb
def test_registers_toon_filters_by_name(live_session):
    t, sid = live_session
    out = t.registers_toon(sid, ["rsp"])
    assert out.startswith("regs[1]{reg,val}:")
    assert out.splitlines()[1].strip().startswith("rsp,0x")


@pytest.mark.requires_gdb
def test_read_mem_toon_emits_hexdump(live_session):
    t, sid = live_session
    out = t.read_memory_toon(sid, "$pc", 16)
    assert out.startswith("hex[1]{addr,bytes,ascii}:")
    row = out.splitlines()[1].strip()
    assert row.startswith("0x")
    assert row.endswith("`")     # ascii column is backtick-wrapped


@pytest.mark.requires_gdb
def test_read_mem_toon_caps_count(live_session):
    t, sid = live_session
    out = t.read_memory_toon(sid, "$sp", 99999)
    assert "capped at 4096 bytes" in out


@pytest.mark.requires_gdb
def test_maps_toon_via_gef(live_session):
    t, sid = live_session
    out = t.maps_toon(sid)
    assert out.startswith("maps[")
    assert "{start,end,perm,path}:" in out
    # filtering to the target's own path should keep at least one row
    filtered = t.maps_toon(sid, "target")
    assert filtered.startswith("maps[")


@pytest.mark.requires_gdb
def test_python_escape_hatch_reaches_gef(live_session):
    t, sid = live_session
    out = t.run_python(sid, "print(hex(gef.arch.pc))")
    assert "0x" in out
