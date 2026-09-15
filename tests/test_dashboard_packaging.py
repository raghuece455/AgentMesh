from pathlib import Path

from fastapi.testclient import TestClient

import agentmesh.dashboard as dashboard
from agentmesh.dashboard import create_app, dashboard_dist_dir

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_dist(root: Path, marker: str) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(f'<div id="root"></div><!-- {marker} -->', encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('dashboard')", encoding="utf-8")
    return root


def test_override_directory_wins(tmp_path, monkeypatch):
    override = _fake_dist(tmp_path / "custom", "override")
    monkeypatch.setenv("AGENTMESH_DASHBOARD_DIR", str(override))
    assert dashboard_dist_dir() == override


def test_missing_override_falls_back_to_checkout_then_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_DASHBOARD_DIR", str(tmp_path / "does-not-exist"))
    resolved = dashboard_dist_dir()
    checkout = REPO_ROOT / "dashboard" / "dist"
    if (checkout / "index.html").is_file():
        assert resolved == checkout
    else:
        bundled = Path(dashboard.__file__).resolve().parent / "dashboard_dist"
        assert resolved == (bundled if (bundled / "index.html").is_file() else None)


def test_app_serves_react_build_and_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTMESH_DASHBOARD_DIR", str(_fake_dist(tmp_path / "dist", "served")))
    client = TestClient(create_app(tmp_path / "agentmesh.db"))

    assert "served" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log('dashboard')"


def test_app_falls_back_to_minimal_page_without_a_build(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "dashboard_dist_dir", lambda: None)
    client = TestClient(create_app(tmp_path / "agentmesh.db"))

    page = client.get("/")
    assert page.status_code == 200 and "AgentMesh Dashboard" in page.text and 'id="root"' not in page.text
    assert client.get("/assets/app.js").status_code == 404
