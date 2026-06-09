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
