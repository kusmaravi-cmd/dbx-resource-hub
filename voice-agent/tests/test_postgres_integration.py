"""Runs the real loader and SQL against a plain Postgres + pgvector (Lakebase-only extensions and the
lakebase_bm25 index are stubbed out). Skipped unless HUB_TEST_PG_DSN is set, e.g.
    HUB_TEST_PG_DSN="host=/tmp port=5499 user=postgres dbname=postgres" pytest tests/test_postgres_integration.py
"""
import asyncio
import hashlib
import importlib.util
import os
import re
from pathlib import Path

import pytest

DSN = os.getenv("HUB_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="HUB_TEST_PG_DSN not set")
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hub_test"
DIM = 8


def fake_embed(texts):
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        out.append([b / 255 for b in h[:DIM]])
    return out


def pg_ddl(raw: str) -> str:
    ddl = raw.replace("{schema}", SCHEMA).replace("{dim}", str(DIM))
    ddl = re.sub(r"CREATE EXTENSION IF NOT EXISTS lakebase_\w+ CASCADE;", "", ddl)
    ddl = ddl.replace("USING lakebase_ann (embedding vector_cosine_ops)", "USING hnsw (embedding vector_cosine_ops)")
    ddl = re.sub(r"CREATE INDEX IF NOT EXISTS resources_bm25[^;]*;", "", ddl)
    return "CREATE EXTENSION IF NOT EXISTS vector;\n" + ddl


@pytest.fixture
def loader(monkeypatch):
    spec = importlib.util.spec_from_file_location("load_catalog", ROOT / "infra" / "load_catalog.py")
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)
    from psycopg_pool import AsyncConnectionPool

    async def pool():
        p = AsyncConnectionPool(DSN, min_size=1, max_size=2, open=False)
        await p.open(timeout=10)
        return p

    calls = []

    def counting_embed(texts):
        calls.append(len(texts))
        return fake_embed(texts)

    monkeypatch.setattr(lc, "SCHEMA", SCHEMA)
    monkeypatch.setattr(lc, "EMBED_DIM", DIM)
    monkeypatch.setattr(lc, "create_pool", pool)
    monkeypatch.setattr(lc, "embed_texts", counting_embed)
    monkeypatch.setattr(lc, "schema_ddl", lambda: pg_ddl((ROOT / "infra" / "schema.sql").read_text()))
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    return lc, pool, calls


def test_load_search_and_shortlist(loader, tmp_path):
    lc, pool, calls = loader
    catalog = ROOT.parent / "search.json"
    asyncio.run(lc.main(catalog, False, 200))
    assert sum(calls) > 800

    calls.clear()
    asyncio.run(lc.main(catalog, False, 200))  # idempotent: nothing changed, nothing re-embedded
    assert sum(calls) == 0

    from hub import search as S
    from hub import shortlist

    async def checks():
        p = await pool()
        try:
            from hub.db import run_query
            n = await run_query(p, f"SELECT count(*) AS n, count(embedding) AS e FROM {SCHEMA}.resources")
            assert n[0]["n"] == n[0]["e"] > 800
            # BM25 branch fails here (no lakebase_bm25), so this also proves the ANN-only path still answers.
            q = "lakebase"
            rows = await S.lakebase_search(p, SCHEMA, q, fake_embed([q])[0], kind="Launch", k=5)
            assert len(rows) == 5 and all(r["kind"] == "Launch" for r in rows)
            new = await S.lakebase_whats_new(p, SCHEMA, topic="Apps and Lakebase", k=5)
            assert new and all(r["topic"] == "Apps and Lakebase" for r in new)
            assert [r["released_on"] for r in new] == sorted((r["released_on"] for r in new), reverse=True)
            rid = new[0]["id"]
            assert await shortlist.save(p, SCHEMA, "ana@corp.com", rid, "for the app team")
            assert await shortlist.save(p, SCHEMA, "ana@corp.com", rid, "updated note")  # upsert
            assert not await shortlist.save(p, SCHEMA, "ana@corp.com", "does-not-exist")
            mine = await run_query(p, shortlist.list_sql(SCHEMA), {"u": "ana@corp.com"})
            assert [(m["id"], m["note"]) for m in mine] == [(rid, "updated note")]
            assert await run_query(p, shortlist.list_sql(SCHEMA), {"u": "bob@corp.com"}) == []
        finally:
            await p.close()
    asyncio.run(checks())

    # a changed entry is re-embedded, everything else keeps its vector
    import json
    raw = json.loads(catalog.read_text())
    raw["items"][0]["d"] = "edited description"
    edited = tmp_path / "search.json"
    edited.write_text(json.dumps({"items": raw["items"]}))
    calls.clear()
    asyncio.run(lc.main(edited, False, 200))
    assert sum(calls) == 1


def test_web_tier_reads_the_shortlist(loader, monkeypatch):
    lc, pool, _ = loader
    asyncio.run(lc.main(ROOT.parent / "search.json", False, 400))
    from hub import shortlist

    async def save():
        p = await pool()
        try:
            from hub.db import run_query
            rid = (await run_query(p, f"SELECT id FROM {SCHEMA}.resources ORDER BY id LIMIT 1"))[0]["id"]
            await shortlist.save(p, SCHEMA, "ana@corp.com", rid, "n")
            return rid
        finally:
            await p.close()
    rid = asyncio.run(save())

    from app import web_server as W
    import hub.db
    monkeypatch.setenv("LAKEBASE_ENDPOINT", "projects/x/branches/y/endpoints/z")
    monkeypatch.setattr(hub.db, "SCHEMA", SCHEMA)
    monkeypatch.setattr(W._conninfo, "get", lambda: DSN)
    items = W.fetch_shortlist("ana@corp.com")
    assert [i["id"] for i in items] == [rid] and isinstance(items[0]["added_at"], str)
