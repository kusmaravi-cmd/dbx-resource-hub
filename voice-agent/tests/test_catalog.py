from hub.catalog import TOPICS, load_catalog, normalize, parse_launch, topic_for, write_compact


def test_loads_the_whole_site_index(resources):
    assert len(resources) > 800
    assert len({r.id for r in resources}) == len(resources)
    assert all(r.title and r.url.startswith("http") for r in resources)


def test_topics_are_speakable_and_rarely_other(resources):
    allowed = {t for t, _ in TOPICS} | {"Acquisitions", "Other"}
    assert {r.topic for r in resources} <= allowed
    assert sum(r.topic == "Other" for r in resources) < 10


def test_every_launch_has_a_month(resources):
    launches = [r for r in resources if r.kind == "Launch"]
    assert launches and all(r.released_on for r in launches)


def test_parse_launch():
    assert parse_launch("Generally available, September 2026", "") == ("Generally available", "2026-09-01")
    assert parse_launch("Beta, August 2026", "") == ("Beta", "2026-08-01")
    assert parse_launch("", "https://docs.databricks.com/aws/en/release-notes/product/2026/october#x") == (
        None, "2026-10-01")
    assert parse_launch("nothing here", "https://example.com") == (None, None)


def test_topic_for():
    assert topic_for("AI & agents") == "AI and agents"
    assert topic_for("", "Row Zero acquisition", kind="Acquisition") == "Acquisitions"
    assert topic_for("Other", "x", url="https://github.com/databricks-industry-solutions/x") == "Industry solutions"
    assert topic_for("Apps & Lakebase") == "Apps and Lakebase"


def test_normalize_skips_incomplete_items():
    assert normalize({"t": "", "u": "https://x"}) is None
    assert normalize({"t": "x", "u": ""}) is None


def test_compact_roundtrip(resources, tmp_path):
    p = tmp_path / "catalog.json"
    write_compact(resources, p)
    assert load_catalog(p) == resources
    assert p.stat().st_size < 600_000
