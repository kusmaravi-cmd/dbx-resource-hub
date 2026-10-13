"""DeltaStore against a fake Statement Execution API: checks SQL wiring, parameters and concurrency."""
import json
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("databricks.sdk")
from databricks.sdk.service.sql import StatementState  # noqa: E402

from server import engine  # noqa: E402
from server.store import ConflictError, DeltaStore  # noqa: E402


class FakeSE:
    def __init__(self):
        self.calls, self.rows, self.version = [], {}, {}

    def execute_statement(self, warehouse_id, statement, parameters=None, wait_timeout=None):
        p = {x.name: x.value for x in (parameters or [])}
        types = {x.name: x.type for x in (parameters or [])}
        self.calls.append((statement, p, types))
        cols, data = [], []
        s = " ".join(statement.split())
        if s.startswith("INSERT INTO `main`.`datapulse`.assessments"):
            self.rows[p["id"]] = p["payload"]; self.version[p["id"]] = 1
        elif s.startswith("UPDATE `main`.`datapulse`.assessments SET payload"):
            ok = self.version.get(p["id"]) == int(p["version"])
            if ok:
                self.rows[p["id"]] = p["payload"]; self.version[p["id"]] += 1
            cols, data = ["num_affected_rows"], [[str(int(ok))]]
        elif s.startswith("SELECT version"):
            cols, data = ["version"], [[str(self.version[p["id"]])]]
        elif s.startswith("SELECT payload"):
            cols = ["payload", "version", "created_by", "created_at", "updated_by", "updated_at"]
            data = [[self.rows[p["id"]], str(self.version[p["id"]]), "a", "t", "a", "t"]]
        return NS(statement_id="s", status=NS(state=StatementState.SUCCEEDED, error=None),
                  manifest=NS(schema=NS(columns=[NS(name=c) for c in cols])), result=NS(data_array=data))


@pytest.fixture()
def store():
    s = DeltaStore.__new__(DeltaStore)
    s.w = NS(statement_execution=FakeSE())
    s.warehouse_id, s.catalog, s.schema, s.fq, s._ready = "wh", "main", "datapulse", "`main`.`datapulse`", False
    import threading
    s._lock = threading.Lock()
    return s


def test_roundtrip_conflict_and_publish(store):
    doc = engine.new_assessment("n", "o")
    aid, v = store.create(doc, "me")
    got, ver, meta = store.get(aid)
    assert got["name"] == "n" and ver == 1
    assert store.save(aid, got, 1, "me") == 2
    with pytest.raises(ConflictError):
        store.save(aid, got, 1, "me")
    upd = [c for c in store.w.statement_execution.calls if c[0].startswith("UPDATE")][0]
    assert upd[2]["version"] == "INT"
    doc["responses"]["R1.1"] = {"level": 2}
    doc["use_cases"] = [{"name": "u", "job": "Agent"}]
    store.publish(aid, 2, doc, engine.evaluate(doc))
    inserts = [c for c in store.w.statement_execution.calls if "inline(from_json" in c[0]]
    assert len(inserts) == 4
    assert all(json.loads(c[1]["rows"]) for c in inserts if "dimension_scores" in c[0])
    ddl = [c[0] for c in store.w.statement_execution.calls if c[0].lstrip().startswith("CREATE TABLE")]
    assert len(ddl) == 6


def test_rejects_bad_identifiers(monkeypatch):
    with pytest.raises(ValueError):
        DeltaStore("wh", "main; DROP", "x")
