"""Finding resources: Lakebase hybrid search with an in-memory fallback.

Lakebase path (preferred): ANN over gateway embeddings (lakebase_ann, cosine) + BM25 (lakebase_bm25),
fused with reciprocal-rank fusion. Fallback path: a small BM25 over the bundled catalog.json, so the
agent still answers when Lakebase or the embedding model is unavailable.
"""
from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from hub.catalog import Resource

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an and are about for from how i in is it me my of on or show tell the to what with "
                  "any some find give need want can do does there this that".split())
RESULT_COLUMNS = "id, title, summary, url, kind, topic, area, status, released_on"


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal-rank fusion of several ranked id lists."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, rid in enumerate(ranking):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda r: (-scores[r], r))


def _matches(r: dict | Resource, kind: str | None, topic: str | None) -> bool:
    get = r.get if isinstance(r, dict) else (lambda k: getattr(r, k))
    if kind and (get("kind") or "").lower() != kind.lower():
        return False
    if topic and (get("topic") or "").lower() != topic.lower():
        return False
    return True


@dataclass
class MemoryIndex:
    """BM25 over title (weighted x2) + content. ~800 docs: instant, no deps."""
    resources: list[Resource]
    k1: float = 1.4
    b: float = 0.75
    _docs: list[Counter] = field(default_factory=list, init=False)
    _df: Counter = field(default_factory=Counter, init=False)
    _avg: float = field(default=1.0, init=False)

    def __post_init__(self):
        for r in self.resources:
            toks = tokenize(r.title) * 2 + tokenize(r.content())
            c = Counter(toks)
            self._docs.append(c)
            self._df.update(c.keys())
        self._avg = (sum(sum(c.values()) for c in self._docs) / len(self._docs)) if self._docs else 1.0
        self.by_id = {r.id: r for r in self.resources}

    def search(self, query: str, *, kind: str | None = None, topic: str | None = None, k: int = 5) -> list[Resource]:
        q = tokenize(query)
        n = len(self._docs)
        scored = []
        for r, doc in zip(self.resources, self._docs):
            if not _matches(r, kind, topic):
                continue
            dl = sum(doc.values())
            s = 0.0
            for t in q:
                f = doc.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self._avg))
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: (-x[0], x[1].title))
        return [r for _, r in scored[:k]]

    def whats_new(self, *, topic: str | None = None, status: str | None = None, k: int = 8) -> list[Resource]:
        launches = [r for r in self.resources if r.kind == "Launch" and r.released_on and _matches(r, None, topic)
                    and (not status or (r.status or "").lower() == status.lower())]
        launches.sort(key=lambda r: (r.released_on, r.title), reverse=True)
        return launches[:k]

    def topics(self) -> dict[str, int]:
        return dict(Counter(r.topic for r in self.resources).most_common())


# ---------------------------------------------------------------- Lakebase (async, pool-backed)

async def lakebase_search(pool, schema: str, query: str, query_vec: list[float] | None, *,
                          kind: str | None = None, topic: str | None = None, k: int = 5) -> list[dict]:
    from hub.db import run_query
    from hub.gateway import to_pgvector

    where, params = ["TRUE"], {"q": query, "k": k * 3}
    if kind:
        where.append("lower(kind) = lower(%(kind)s)")
        params["kind"] = kind
    if topic:
        where.append("lower(topic) = lower(%(topic)s)")
        params["topic"] = topic
    filt = " AND ".join(where)

    bm25_expr = (f"content_tsv <@> to_bm25query(to_tsvector('english', %(q)s), "
                 f"'{schema}.resources_bm25'::regclass)")
    bm25_sql = (f"SELECT {RESULT_COLUMNS}, {bm25_expr} AS score FROM {schema}.resources "
                f"WHERE {filt} ORDER BY score ASC LIMIT %(k)s")
    tasks = [run_query(pool, bm25_sql, params)]
    if query_vec is not None:
        ann_sql = (f"SELECT {RESULT_COLUMNS}, 1 - (embedding <=> %(v)s::vector) AS score "
                   f"FROM {schema}.resources WHERE {filt} AND embedding IS NOT NULL "
                   f"ORDER BY embedding <=> %(v)s::vector LIMIT %(k)s")
        tasks.append(run_query(pool, ann_sql, {**params, "v": to_pgvector(query_vec)}))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    if all(isinstance(r, Exception) for r in results):
        raise results[0]
    rows: dict[str, dict] = {}
    rankings = []
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            continue
        if i == 0:  # BM25: real matches score negative, non-matches ~0
            res = [r for r in res if (r.get("score") or 0) < 0]
        rankings.append([r["id"] for r in res])
        for r in res:
            rows.setdefault(r["id"], r)
    return [_clean(rows[i]) for i in rrf(rankings)[:k]]


async def lakebase_whats_new(pool, schema: str, *, topic: str | None = None, status: str | None = None,
                             k: int = 8) -> list[dict]:
    from hub.db import run_query

    where, params = ["kind = 'Launch'", "released_on IS NOT NULL"], {"k": k}
    if topic:
        where.append("lower(topic) = lower(%(topic)s)")
        params["topic"] = topic
    if status:
        where.append("lower(status) = lower(%(status)s)")
        params["status"] = status
    sql = (f"SELECT {RESULT_COLUMNS} FROM {schema}.resources WHERE {' AND '.join(where)} "
           f"ORDER BY released_on DESC, title LIMIT %(k)s")
    return [_clean(r) for r in await run_query(pool, sql, params)]


def _clean(row: dict) -> dict:
    out = {c: row.get(c) for c in RESULT_COLUMNS.split(", ")}
    if out.get("released_on") is not None:
        out["released_on"] = str(out["released_on"])
    return out
