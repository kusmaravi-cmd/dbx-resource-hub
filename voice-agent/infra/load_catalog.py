"""Load the Resource Hub catalog (../search.json) into Lakebase, with gateway embeddings.

Idempotent: upserts every resource, re-embeds only rows whose content changed, deletes rows that left
the catalog. Run it locally (or from a Databricks job) whenever search.json changes:

    export DATABRICKS_CONFIG_PROFILE=<profile>
    export LAKEBASE_ENDPOINT=projects/<p>/branches/<b>/endpoints/<e>
    uv run python infra/load_catalog.py               # schema + data
    uv run python infra/load_catalog.py --schema-only # just DDL
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.catalog import load_catalog  # noqa: E402
from hub.db import SCHEMA, create_pool  # noqa: E402
from hub.gateway import EMBED_DIM, EMBED_MODEL, embed_texts, to_pgvector  # noqa: E402

UPSERT = """
INSERT INTO {s}.resources (id, title, summary, url, kind, topic, area, status, released_on, content,
                           content_tsv)
VALUES (%(id)s, %(title)s, %(summary)s, %(url)s, %(kind)s, %(topic)s, %(area)s, %(status)s,
        %(released_on)s, %(content)s, to_tsvector('english', %(content)s))
ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title, summary = EXCLUDED.summary, url = EXCLUDED.url, kind = EXCLUDED.kind,
    topic = EXCLUDED.topic, area = EXCLUDED.area, status = EXCLUDED.status,
    released_on = EXCLUDED.released_on, loaded_at = now(),
    embedding = CASE WHEN {s}.resources.content = EXCLUDED.content THEN {s}.resources.embedding END,
    content = EXCLUDED.content, content_tsv = EXCLUDED.content_tsv
"""


def schema_ddl() -> str:
    return (ROOT / "infra" / "schema.sql").read_text().replace("{schema}", SCHEMA).replace("{dim}", str(EMBED_DIM))


async def main(catalog_path: Path, schema_only: bool, batch: int) -> None:
    pool = await create_pool()
    try:
        async with pool.connection() as conn:
            await conn.execute(schema_ddl())
            await conn.commit()
        print(f"[schema] {SCHEMA}.resources + {SCHEMA}.shortlist ready")
        if schema_only:
            return

        resources = load_catalog(catalog_path)
        print(f"[load] {len(resources)} resources from {catalog_path}")
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                for r in resources:
                    await cur.execute(UPSERT.format(s=SCHEMA), {**r.to_dict(), "content": r.content()})
                await cur.execute(f"DELETE FROM {SCHEMA}.resources WHERE NOT (id = ANY(%(ids)s))",
                                  {"ids": [r.id for r in resources]})
                print(f"[load] upserted; removed {cur.rowcount} stale rows")
            await conn.commit()

        async with pool.connection() as conn:
            todo = await (await conn.execute(
                f"SELECT id, content FROM {SCHEMA}.resources WHERE embedding IS NULL ORDER BY id")).fetchall()
        print(f"[embed] {len(todo)} rows need embeddings ({EMBED_MODEL}, dim {EMBED_DIM})")
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            vecs = await asyncio.to_thread(embed_texts, [c for _, c in chunk])
            if vecs and len(vecs[0]) != EMBED_DIM:
                raise SystemExit(f"{EMBED_MODEL} returned dim {len(vecs[0])}, schema expects {EMBED_DIM}. "
                                 "Set HUB_EMBED_DIM and recreate the table.")
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for (rid, _), v in zip(chunk, vecs):
                        await cur.execute(f"UPDATE {SCHEMA}.resources SET embedding = %(v)s::vector WHERE id = %(id)s",
                                          {"v": to_pgvector(v), "id": rid})
                await conn.commit()
            print(f"[embed] {min(i + batch, len(todo))}/{len(todo)}")
        print("[done]")
    finally:
        await pool.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, default=ROOT.parent / "search.json")
    ap.add_argument("--schema-only", action="store_true")
    ap.add_argument("--batch", type=int, default=64)
    a = ap.parse_args()
    asyncio.run(main(a.catalog, a.schema_only, a.batch))
