import os
import server


def test_resolve_returns_explicit_path_unchanged():
    assert server._resolve_gef_path("/some/explicit/gef.py") == "/some/explicit/gef.py"


def test_resolve_uses_env_var_when_set(monkeypatch, tmp_path):
    # MDB_GEF_PATH is the reliable override under uvx/pipx where no sibling exists.
    fake = tmp_path / "env-gef.py"
    fake.write_text("# fake gef\n")
    monkeypatch.setenv("MDB_GEF_PATH", str(fake))
    monkeypatch.setattr(server, "_BUNDLED_GEF", "/definitely/does/not/exist/gef.py")
    assert server._resolve_gef_path(None) == str(fake)


def test_explicit_arg_beats_env_var(monkeypatch, tmp_path):
    fake = tmp_path / "env-gef.py"
    fake.write_text("# fake gef\n")
    monkeypatch.setenv("MDB_GEF_PATH", str(fake))
    assert server._resolve_gef_path("/explicit/gef.py") == "/explicit/gef.py"


def test_resolve_ignores_missing_env_var_file(monkeypatch, tmp_path):
    # A set-but-nonexistent MDB_GEF_PATH must not win; fall through to the sibling.
    monkeypatch.setenv("MDB_GEF_PATH", "/no/such/gef.py")
    fake = tmp_path / "gef" / "gef.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("# fake gef\n")
    monkeypatch.setattr(server, "_BUNDLED_GEF", str(fake))
    assert server._resolve_gef_path(None) == str(fake)


def test_resolve_uses_sibling_gef_when_present(monkeypatch, tmp_path):
    # Simulate a sibling ../gef/gef.py relative to server.py's directory.
    monkeypatch.delenv("MDB_GEF_PATH", raising=False)
    fake = tmp_path / "gef" / "gef.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("# fake gef\n")
    monkeypatch.setattr(server, "_BUNDLED_GEF", str(fake))
    assert server._resolve_gef_path(None) == str(fake)


def test_resolve_returns_none_when_no_sibling(monkeypatch):
    monkeypatch.delenv("MDB_GEF_PATH", raising=False)
    monkeypatch.setattr(server, "_BUNDLED_GEF", "/definitely/does/not/exist/gef.py")
    assert server._resolve_gef_path(None) is None
