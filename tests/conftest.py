import os

import pytest

POSTGRES_URL = os.getenv("AGENTMESH_TEST_POSTGRES_URL")


def _reset_postgres(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("create schema public")


@pytest.fixture(params=["sqlite", "postgres"])
def db_url(request, tmp_path):
    """A fresh database: a SQLite file, and (when AGENTMESH_TEST_POSTGRES_URL is set) an empty PostgreSQL schema."""
    if request.param == "sqlite":
        return str(tmp_path / "agentmesh.db")
    if not POSTGRES_URL:
        pytest.skip("set AGENTMESH_TEST_POSTGRES_URL to run the PostgreSQL variant")
    _reset_postgres(POSTGRES_URL)
    return POSTGRES_URL
