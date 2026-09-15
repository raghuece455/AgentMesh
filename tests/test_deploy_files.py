from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_compose_override_does_not_reset_data_by_default():
    base = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    override = (ROOT / "docker-compose.postgres.yml").read_text(encoding="utf-8")
    # The base file seeds (and resets) demo data unless AGENTMESH_DEMO_SEED=false...
    assert "AGENTMESH_DEMO_SEED: ${AGENTMESH_DEMO_SEED:-true}" in base and "demo seed --reset" in base
    # ...so the PostgreSQL override, meant for keeping data, must default it off.
    assert "AGENTMESH_DEMO_SEED: ${AGENTMESH_DEMO_SEED:-false}" in override
