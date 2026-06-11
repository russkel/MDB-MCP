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


def test_guardrail_caps_rendered_lines_in_single_payload():
    one_big = [{"type": "console",
                "payload": "\n".join(f"row {i}" for i in range(5000))}]
    out = format_gdb_response(one_big, max_lines=200)
    assert out.count("\n") <= 210
    assert "lines elided" in out


class _FakeProc:
    def __init__(self):
        self.alive = True
        self.terminated = False
    def poll(self):
        return None if self.alive else 0
    def terminate(self):
        self.terminated = True
        self.alive = False
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.alive = False


def test_terminate_session_kills_rr_process():
    sm = GDBSessionManager()
    class _FakeGdb:
        def exit(self):
            pass
    fake = _FakeProc()
    sm.sessions["sid-x"] = _FakeGdb()
    sm.rr_processes["sid-x"] = fake
    assert sm.terminate_session("sid-x") is True
    assert fake.terminated is True
    assert "sid-x" not in sm.rr_processes


def test_create_session_passes_nx_and_gef_source(monkeypatch):
    import modules.gdb.sessionManager as smmod
    monkeypatch.delenv("MDB_PYTHONPATH", raising=False)
    captured = {}

    class _FakeController:
        def __init__(self, command=None):
            captured["command"] = command

    monkeypatch.setattr(smmod, "GdbController", _FakeController)
    sm = smmod.GDBSessionManager()
    sm.create_session("gdb", gef_path="/x/gef.py")
    assert captured["command"] == [
        "gdb", "-nx", "--interpreter=mi3", "-ex", "source /x/gef.py"]


def test_create_session_injects_mdb_pythonpath(monkeypatch):
    import modules.gdb.sessionManager as smmod
    monkeypatch.setenv("MDB_PYTHONPATH", os.pathsep.join(["/opt/venv/site-packages", "/extra"]))
    captured = {}

    class _FakeController:
        def __init__(self, command=None):
            captured["command"] = command

    monkeypatch.setattr(smmod, "GdbController", _FakeController)
    sm = smmod.GDBSessionManager()
    sm.create_session("gdb", gef_path="/x/gef.py")
    cmd = captured["command"]
    # the sys.path injection is present and ordered BEFORE the gef source
    inject = "python import sys; sys.path[:0] = ['/opt/venv/site-packages', '/extra']"
    assert inject in cmd
    assert cmd.index(inject) < cmd.index("source /x/gef.py")


def test_create_session_no_pythonpath_when_unset(monkeypatch):
    import modules.gdb.sessionManager as smmod
    monkeypatch.delenv("MDB_PYTHONPATH", raising=False)
    captured = {}

    class _FakeController:
        def __init__(self, command=None):
            captured["command"] = command

    monkeypatch.setattr(smmod, "GdbController", _FakeController)
    sm = smmod.GDBSessionManager()
    sm.create_session("gdb")
    assert not any("sys.path" in str(a) for a in captured["command"])
