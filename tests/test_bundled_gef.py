import os
import server


def test_resolve_returns_explicit_path_unchanged():
    assert server._resolve_gef_path("/some/explicit/gef.py") == "/some/explicit/gef.py"


def test_resolve_uses_sibling_gef_when_present(monkeypatch, tmp_path):
    # Simulate a sibling ../gef/gef.py relative to server.py's directory.
    fake = tmp_path / "gef" / "gef.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("# fake gef\n")
    monkeypatch.setattr(server, "_BUNDLED_GEF", str(fake))
    assert server._resolve_gef_path(None) == str(fake)


def test_resolve_returns_none_when_no_sibling(monkeypatch):
    monkeypatch.setattr(server, "_BUNDLED_GEF", "/definitely/does/not/exist/gef.py")
    assert server._resolve_gef_path(None) is None
