import pytest


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """테스트가 실제 프로젝트 보관함(~/Movies/BlurFace)·앱 폴더를 건드리지 않게."""
    from blurface import projects
    monkeypatch.setenv("BLURFACE_PROJECTS", str(tmp_path / "_projects"))
    monkeypatch.setenv("BLURFACE_HOME", str(tmp_path / "_home"))
    projects._found.clear()
    yield
    projects._found.clear()
