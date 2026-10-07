"""What the voice tools call. LiveKit-free so it unit-tests without a room.

Order of preference for every read: Lakebase hybrid (ANN + BM25) -> Lakebase BM25 only (embedding
call failed or slow) -> the bundled catalog in memory (Lakebase down). Each answer says which
source served it, so the UI and the trace show when the app is degraded.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from hub import search as S
from hub import shortlist
from hub.catalog import TOPICS, Resource

log = logging.getLogger(__name__)

KINDS = ("Docs", "Repo", "Launch", "Video", "Article", "Tool", "Demo", "Acquisition", "Playbook",
         "Community", "Learning path")
TOPIC_NAMES = tuple(t for t, _ in TOPICS) + ("Acquisitions",)
_EMBED_TIMEOUT_S = float(os.getenv("HUB_EMBED_TIMEOUT_S", "2.5"))
_SPOKEN_SUMMARY = 160

Sink = Callable[[dict], Awaitable[None]]


def pick(value: str | None, allowed: tuple[str, ...]) -> str | None:
    """Case-insensitive match to an allowed filter value; unknown values become None (no filter),
    so an LLM guess like 'tutorials' never empties the result set."""
    v = (value or "").strip().lower()
    if not v:
        return None
    for a in allowed:
        if a.lower() == v or a.lower().rstrip("s") == v.rstrip("s"):
            return a
    return None


def _as_dict(r: Resource | dict) -> dict:
    return r if isinstance(r, dict) else {c: getattr(r, c) for c in S.RESULT_COLUMNS.split(", ")}


def for_llm(rows: list[dict]) -> list[dict]:
    """What the model sees: no URLs (they go to the screen, never into speech)."""
    out = []
    for r in rows:
        item = {"id": r["id"], "title": r["title"], "type": r["kind"], "topic": r["topic"]}
        if r.get("summary"):
            item["summary"] = r["summary"][:_SPOKEN_SUMMARY]
        if r.get("status"):
            item["status"] = r["status"]
        if r.get("released_on"):
            item["released"] = r["released_on"][:7]
        out.append(item)
    return out


@dataclass
class HubBackend:
    memory: S.MemoryIndex
    pool: object | None = None
    schema: str = "hub"
    user_key: str = ""
    embed: Callable[[list[str]], list[list[float]]] | None = None
    sink: Sink | None = None
    seen: dict[str, dict] = field(default_factory=dict)  # id -> row, for "save that one"

    async def _publish(self, fragment: dict) -> None:
        if self.sink is None:
            return
        try:
            await self.sink(fragment)
        except Exception:  # noqa: BLE001 - the screen is cosmetic; never break a turn
            pass

    async def _embed_query(self, query: str) -> list[float] | None:
        if self.embed is None:
            return None
        try:
            vecs = await asyncio.wait_for(asyncio.to_thread(self.embed, [query]), timeout=_EMBED_TIMEOUT_S)
            return vecs[0] if vecs else None
        except Exception as exc:  # noqa: BLE001
            log.warning("query embedding failed, BM25 only: %s", exc)
            return None

    def _remember(self, rows: list[dict]) -> None:
        for r in rows:
            self.seen[r["id"]] = r

    async def search(self, query: str, kind: str = "", topic: str = "", k: int = 5) -> dict:
        kind_f, topic_f = pick(kind, KINDS), pick(topic, TOPIC_NAMES)
        rows, source = [], "catalog"
        if self.pool is not None:
            try:
                vec = await self._embed_query(query)
                rows = await S.lakebase_search(self.pool, self.schema, query, vec, kind=kind_f, topic=topic_f, k=k)
                source = "lakebase" if vec is not None else "lakebase-keyword"
            except Exception as exc:  # noqa: BLE001
                log.warning("lakebase search failed, using bundled catalog: %s", exc)
                rows = []
                source = "catalog"
        if source == "catalog":
            rows = [_as_dict(r) for r in self.memory.search(query, kind=kind_f, topic=topic_f, k=k)]
        self._remember(rows)
        await self._publish({"results": {"title": f"Results for “{query}”", "source": source,
                                         "filters": {"type": kind_f, "topic": topic_f}, "items": rows}})
        return {"source": source, "filters": {"type": kind_f, "topic": topic_f}, "results": for_llm(rows)}

    async def whats_new(self, topic: str = "", status: str = "", k: int = 8) -> dict:
        topic_f = pick(topic, TOPIC_NAMES)
        status_f = pick(status, ("Generally available", "Public Preview", "Beta", "Private Preview"))
        rows, source = [], "catalog"
        if self.pool is not None:
            try:
                rows = await S.lakebase_whats_new(self.pool, self.schema, topic=topic_f, status=status_f, k=k)
                source = "lakebase"
            except Exception as exc:  # noqa: BLE001
                log.warning("lakebase whats_new failed: %s", exc)
        if source == "catalog":
            rows = [_as_dict(r) for r in self.memory.whats_new(topic=topic_f, status=status_f, k=k)]
        self._remember(rows)
        label = f"Latest launches{f' in {topic_f}' if topic_f else ''}"
        await self._publish({"results": {"title": label, "source": source,
                                         "filters": {"topic": topic_f, "status": status_f}, "items": rows}})
        return {"source": source, "results": for_llm(rows)}

    async def save(self, resource_id: str, note: str = "") -> dict:
        row = self.seen.get(resource_id) or (
            _as_dict(self.memory.by_id[resource_id]) if resource_id in self.memory.by_id else None)
        if row is None:
            return {"saved": False, "reason": "unknown id; search first and use an id from the results"}
        persisted = False
        if self.pool is not None and self.user_key:
            try:
                persisted = await shortlist.save(self.pool, self.schema, self.user_key, resource_id, note)
            except Exception as exc:  # noqa: BLE001
                log.warning("shortlist save failed: %s", exc)
        await self._publish({"saved": {**row, "note": note[:200], "persisted": persisted}})
        return {"saved": True, "title": row["title"], "persisted": persisted}

    def topics(self) -> dict:
        return {"topics": self.memory.topics(), "types": list(KINDS)}
