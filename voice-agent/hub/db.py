"""Lakebase (Postgres) pool. Credential pattern from DIVA: the endpoint host comes from the SDK and
the password is a short-lived (~1h) database credential minted for the app's own identity."""
from __future__ import annotations

import asyncio
import os

SCHEMA = os.getenv("HUB_SCHEMA", "hub")
_QUERY_TIMEOUT_S = float(os.getenv("HUB_QUERY_TIMEOUT_S", "3.0"))


class QueryError(RuntimeError):
    pass


def lakebase_configured() -> bool:
    return bool(os.getenv("LAKEBASE_ENDPOINT"))


def build_conninfo() -> str:
    from hub.auth import workspace_client

    w = workspace_client()
    ep = os.environ["LAKEBASE_ENDPOINT"]  # projects/<p>/branches/<b>/endpoints/<e>
    database = os.getenv("LAKEBASE_DATABASE", "databricks_postgres")
    host = w.postgres.get_endpoint(ep).as_dict()["status"]["hosts"]["host"]
    cred = w.postgres.generate_database_credential(ep)
    token = getattr(cred, "token", None) or cred.as_dict().get("token")
    user = w.current_user.me().user_name  # PAT user email, or the SP's application id
    return f"host={host} user={user} dbname={database} password={token} sslmode=require"


async def create_pool(min_size: int = 1, max_size: int = 4):
    from psycopg_pool import AsyncConnectionPool

    # The SDK calls block; keep them off the event loop (they stall a live voice job otherwise).
    conninfo = await asyncio.to_thread(build_conninfo)
    pool = AsyncConnectionPool(conninfo, min_size=min_size, max_size=max_size, open=False)
    await pool.open(timeout=15)  # explicit open so the timeout applies
    return pool


async def create_pool_soft():
    """Pool, or None when Lakebase is not configured / unreachable (callers degrade, never crash)."""
    if not lakebase_configured():
        return None
    try:
        return await create_pool()
    except Exception as exc:  # noqa: BLE001
        print(f"[hub] Lakebase unavailable, using the bundled catalog: {exc}", flush=True)
        return None


async def run_query(pool, sql: str, params: dict | None = None, *, retries: int = 1) -> list[dict]:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            async def _go():
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, params)
                        if cur.description is None:
                            return []
                        cols = [d[0] for d in cur.description]
                        return [dict(zip(cols, row)) for row in await cur.fetchall()]

            return await asyncio.wait_for(_go(), timeout=_QUERY_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise QueryError(str(last))
