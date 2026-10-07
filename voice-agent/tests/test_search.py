from hub.search import rrf, tokenize


def test_tokenize_drops_stopwords():
    assert tokenize("What is the latest in Lakebase?") == ["latest", "lakebase"]


def test_finds_a_record_linkage_accelerator(memory):
    titles = [r.title for r in memory.search("customer record linkage de-duplication")]
    assert "auto-data-linkage" in titles[:3]


def test_kind_and_topic_filters(memory):
    hits = memory.search("genie", kind="Video", k=10)
    assert hits and all(r.kind == "Video" for r in hits)
    hits = memory.search("lakebase", topic="Apps and Lakebase", k=10)
    assert hits and all(r.topic == "Apps and Lakebase" for r in hits)


def test_no_match_returns_nothing(memory):
    assert memory.search("zzqxv nonsenseword") == []


def test_whats_new_is_newest_first(memory):
    rows = memory.whats_new(k=20)
    dates = [r.released_on for r in rows]
    assert dates == sorted(dates, reverse=True) and all(r.kind == "Launch" for r in rows)
    ga = memory.whats_new(status="Generally available", k=50)
    assert ga and all(r.status == "Generally available" for r in ga)


def test_rrf_rewards_agreement():
    assert rrf([["a", "b", "c"], ["b", "a", "d"]])[:2] in (["a", "b"], ["b", "a"])
    assert rrf([["x"], ["y", "x"]])[0] == "x"
