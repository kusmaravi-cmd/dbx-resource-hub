import asyncio

import pytest

from hub import backend as B
from hub import search as S


def run(coro):
    return asyncio.run(coro)


class Sink:
    def __init__(self):
        self.events = []

    async def __call__(self, frag):
        self.events.append(frag)


def test_pick_normalizes_and_ignores_unknown():
    assert B.pick("repos", B.KINDS) == "Repo"
    assert B.pick("VIDEO", B.KINDS) == "Video"
    assert B.pick("tutorials", B.KINDS) is None
    assert B.pick("", B.KINDS) is None
    assert B.pick("apps and lakebase", B.TOPIC_NAMES) == "Apps and Lakebase"


def test_search_without_lakebase_uses_catalog_and_hides_urls(memory):
    sink = Sink()
    be = B.HubBackend(memory=memory, sink=sink)
    out = run(be.search("record linkage", kind="repos"))
    assert out["source"] == "catalog" and out["filters"]["type"] == "Repo"
    assert out["results"] and all("url" not in r for r in out["results"])
    shown = sink.events[0]["results"]
    assert shown["items"][0]["url"].startswith("https://")


def test_lakebase_failure_falls_back_to_catalog(memory, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(S, "lakebase_search", boom)
    be = B.HubBackend(memory=memory, pool=object(), embed=lambda xs: [[0.0] * 4])
    out = run(be.search("lakebase"))
    assert out["source"] == "catalog" and out["results"]


def test_lakebase_keyword_only_when_embedding_fails(memory, monkeypatch):
    seen = {}

    async def fake(pool, schema, query, vec, **k):
        seen["vec"] = vec
        return [{"id": "x", "title": "T", "summary": "", "url": "https://x", "kind": "Docs", "topic": "Other",
                 "area": "", "status": None, "released_on": None}]
    monkeypatch.setattr(S, "lakebase_search", fake)

    def bad_embed(_):
        raise RuntimeError("gateway 500")
    be = B.HubBackend(memory=memory, pool=object(), embed=bad_embed)
    out = run(be.search("anything"))
    assert out["source"] == "lakebase-keyword" and seen["vec"] is None


def test_save_requires_a_seen_or_known_id(memory):
    sink = Sink()
    be = B.HubBackend(memory=memory, sink=sink, user_key="a@b.com")
    assert run(be.save("nope"))["saved"] is False
    rid = run(be.search("record linkage"))["results"][0]["id"]
    out = run(be.save(rid, note="for the MDM project"))
    assert out == {"saved": True, "title": out["title"], "persisted": False}
    assert sink.events[-1]["saved"]["id"] == rid


def test_whats_new_topic(memory):
    out = run(B.HubBackend(memory=memory).whats_new(topic="apps and lakebase"))
    assert out["results"] and all(r["topic"] == "Apps and Lakebase" for r in out["results"])


def test_sink_errors_never_break_a_turn(memory):
    async def broken(_):
        raise RuntimeError("room gone")
    out = run(B.HubBackend(memory=memory, sink=broken).search("genie"))
    assert out["results"]


@pytest.mark.parametrize("rows,expected", [([], 0)])
def test_for_llm_empty(rows, expected):
    assert len(B.for_llm(rows)) == expected
