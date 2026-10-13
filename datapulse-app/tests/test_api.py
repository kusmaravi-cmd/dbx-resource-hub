import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAPULSE_WAREHOUSE_ID", raising=False)
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    monkeypatch.setenv("DATAPULSE_DATA_DIR", str(tmp_path))
    import server.app as appmod
    importlib.reload(appmod)
    return TestClient(appmod.app)


def test_end_to_end(client):
    assert client.get("/api/health").json()["store"]["kind"] == "local"
    fw = client.get("/api/framework").json()
    assert len(fw["questions"]) > 60 and len(fw["levers"]) > 30
    created = client.post("/api/assessments", json={"name": "A", "org": "O"}, headers={"x-forwarded-email": "u@x.com"}).json()
    aid, v = created["id"], created["version"]
    got = client.get(f"/api/assessments/{aid}").json()
    doc = got["doc"]
    doc["responses"]["R1.1"] = {"level": 3}
    doc["levers"]["L-02"] = {"status": "Verified", "owner": "me"}  # status edit must be ignored
    r = client.put(f"/api/assessments/{aid}", json={"version": v, "doc": doc})
    assert r.status_code == 200
    body = r.json()
    assert body["doc"]["levers"]["L-02"]["status"] == "Proposed"
    assert body["results"]["questions"]["R1.1"]["claimed"] == 3
    # stale version is rejected
    assert client.put(f"/api/assessments/{aid}", json={"version": v, "doc": doc}).status_code == 409
    v = body["version"]
    bad = client.post(f"/api/assessments/{aid}/levers/L-02/transition", json={"version": v, "to": "Enforced", "fields": {}})
    assert bad.status_code == 422 and bad.json()["errors"]
    ok = client.post(f"/api/assessments/{aid}/levers/L-02/transition",
                     json={"version": v, "to": "Committed", "fields": {"owner": "me", "wave": "0", "kpi_target": 100}})
    assert ok.status_code == 200 and ok.json()["doc"]["levers"]["L-02"]["status"] == "Committed"
    audit = client.get(f"/api/assessments/{aid}/audit").json()
    actions = [a["action"] for a in audit]
    assert "lever_transition" in actions and "lever_transition_rejected" in actions and "create" in actions
    assert audit[-1]["actor"] == "u@x.com"
    assert client.get(f"/api/assessments/{aid}/report.md").text.startswith("# DataPulse assessment")
    assert "dimension" in client.get(f"/api/assessments/{aid}/export.csv").text
    assert client.get("/").status_code == 200
    assert client.delete(f"/api/assessments/{aid}").status_code == 200
    assert client.get(f"/api/assessments/{aid}").status_code == 404


def test_unknown_ids_dropped(client):
    aid = client.post("/api/assessments", json={"name": "A"}).json()["id"]
    r = client.put(f"/api/assessments/{aid}", json={"version": 1, "doc": {"responses": {"NOPE": {"level": 5}}, "mode": "weird"}}).json()
    assert "NOPE" not in r["doc"]["responses"] and r["doc"]["mode"] == "attested"


def test_flatten_shapes():
    from server import engine
    from server.store import DERIVED, flatten
    doc = engine.new_assessment("a")
    doc["responses"]["R1.1"] = {"level": 2}
    doc["use_cases"] = [{"name": "u", "job": "Agent"}]
    out = flatten("id", 1, doc, engine.evaluate(doc))
    for table, rows in out.items():
        cols = [c.strip().split(" ")[0] for c in DERIVED[table].split(",")]
        for row in rows:
            assert list(row) == cols, table
