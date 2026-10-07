"""Per-user shortlist in Lakebase. The agent saves; the web tier lists."""
from __future__ import annotations

import re

from hub.search import RESULT_COLUMNS

_USER_RE = re.compile(r"[^A-Za-z0-9@._+-]")


def clean_user(raw: str | None) -> str:
    return _USER_RE.sub("", raw or "")[:128]


def save_sql(schema: str) -> str:
    return (f"INSERT INTO {schema}.shortlist (user_key, resource_id, note) "
            f"SELECT %(u)s, id, %(note)s FROM {schema}.resources WHERE id = %(rid)s "
            f"ON CONFLICT (user_key, resource_id) DO UPDATE SET note = EXCLUDED.note, added_at = now() "
            f"RETURNING resource_id")


def list_sql(schema: str) -> str:
    cols = ", ".join(f"r.{c}" for c in RESULT_COLUMNS.split(", "))
    return (f"SELECT {cols}, s.note, s.added_at FROM {schema}.shortlist s "
            f"JOIN {schema}.resources r ON r.id = s.resource_id "
            f"WHERE s.user_key = %(u)s ORDER BY s.added_at DESC LIMIT 50")


async def save(pool, schema: str, user_key: str, resource_id: str, note: str = "") -> bool:
    from hub.db import run_query

    rows = await run_query(pool, save_sql(schema), {"u": user_key, "rid": resource_id, "note": note[:200]},
                           retries=0)
    return bool(rows)
