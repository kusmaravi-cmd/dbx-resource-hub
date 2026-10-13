"""Persistence for DataPulse.

DeltaStore   Unity Catalog Delta tables through a SQL warehouse (Statement
             Execution API). Used when DATAPULSE_WAREHOUSE_ID is set, which a
             Databricks App does through its `sql-warehouse` resource.
LocalStore   JSON files on disk. Used for local development and tests.

The assessment document is the source of truth (one row, JSON payload, with an
optimistic-concurrency version). Flattened, BI-friendly tables (scores, lever
plan, findings, use-case readiness) are rewritten after each save so the
portfolio can be analysed with SQL and dashboards. Every change is appended to
an audit log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("datapulse.store")


class ConflictError(Exception):
    pass


class NotFoundError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _summary(doc_id, doc, version, created_by, created_at, updated_by, updated_at):
    return {"id": doc_id, "name": doc.get("name", ""), "org": doc.get("org", ""), "mode": doc.get("mode", "attested"),
            "version": version, "created_by": created_by, "created_at": created_at,
            "updated_by": updated_by, "updated_at": updated_at}


# --------------------------------------------------------------------------- local

class LocalStore:
    kind = "local"

    def __init__(self, root):
        self.root = Path(root)
        (self.root / "assessments").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def describe(self):
        return {"kind": self.kind, "location": str(self.root.resolve())}

    def _path(self, doc_id):
        if not re.fullmatch(r"[a-f0-9-]{8,64}", doc_id):
            raise NotFoundError(doc_id)
        return self.root / "assessments" / f"{doc_id}.json"

    def list(self):
        out = []
        for p in sorted(self.root.glob("assessments/*.json")):
            rec = json.loads(p.read_text())
            if not rec.get("deleted"):
                out.append(_summary(rec["id"], rec["doc"], rec["version"], rec["created_by"], rec["created_at"],
                                    rec["updated_by"], rec["updated_at"]))
        return sorted(out, key=lambda r: r["updated_at"], reverse=True)

    def get(self, doc_id):
        p = self._path(doc_id)
        if not p.exists():
            raise NotFoundError(doc_id)
        rec = json.loads(p.read_text())
        if rec.get("deleted"):
            raise NotFoundError(doc_id)
        return rec["doc"], rec["version"], _summary(doc_id, rec["doc"], rec["version"], rec["created_by"],
                                                    rec["created_at"], rec["updated_by"], rec["updated_at"])

    def create(self, doc, actor):
        doc_id = str(uuid.uuid4())
        now = _now()
        rec = {"id": doc_id, "doc": doc, "version": 1, "created_by": actor, "created_at": now,
               "updated_by": actor, "updated_at": now}
        with self._lock:
            self._path(doc_id).write_text(json.dumps(rec))
        self.audit(doc_id, actor, "create", {"name": doc.get("name")})
        return doc_id, 1

    def save(self, doc_id, doc, version, actor, action="save", detail=None):
        with self._lock:
            p = self._path(doc_id)
            if not p.exists():
                raise NotFoundError(doc_id)
            rec = json.loads(p.read_text())
            if rec.get("deleted"):
                raise NotFoundError(doc_id)
            if int(rec["version"]) != int(version):
                raise ConflictError(f"version {version} is stale; current is {rec['version']}")
            rec.update(doc=doc, version=rec["version"] + 1, updated_by=actor, updated_at=_now())
            p.write_text(json.dumps(rec))
        self.audit(doc_id, actor, action, detail or {})
        return rec["version"]

    def delete(self, doc_id, actor):
        with self._lock:
            p = self._path(doc_id)
            if not p.exists():
                raise NotFoundError(doc_id)
            rec = json.loads(p.read_text())
            rec["deleted"] = True
            p.write_text(json.dumps(rec))
        self.audit(doc_id, actor, "delete", {})

    def audit(self, doc_id, actor, action, detail):
        line = json.dumps({"event_ts": _now(), "assessment_id": doc_id, "actor": actor, "action": action, "detail": detail})
        with self._lock, open(self.root / "audit.jsonl", "a") as f:
            f.write(line + "\n")

    def get_audit(self, doc_id, limit=200):
        p = self.root / "audit.jsonl"
        if not p.exists():
            return []
        rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
        return [r for r in rows if r["assessment_id"] == doc_id][-limit:][::-1]

    def publish(self, doc_id, version, doc, results):
        (self.root / "results").mkdir(exist_ok=True)
        (self.root / "results" / f"{doc_id}.json").write_text(json.dumps({"version": version, "results": results}))


# --------------------------------------------------------------------------- delta

DDL = [
    """CREATE TABLE IF NOT EXISTS {fq}.assessments (
        assessment_id STRING NOT NULL, name STRING, org STRING, mode STRING, version INT,
        payload STRING, created_by STRING, created_at TIMESTAMP, updated_by STRING,
        updated_at TIMESTAMP, deleted BOOLEAN)
       COMMENT 'DataPulse assessments. payload is the full assessment document (JSON).'""",
    """CREATE TABLE IF NOT EXISTS {fq}.dimension_scores (
        assessment_id STRING, version INT, dimension STRING, dimension_name STRING, tier STRING,
        claimed DOUBLE, evidence_backed DOUBLE, enforced DOUBLE, metric_level DOUBLE,
        coverage DOUBLE, provisional BOOLEAN, caps STRING, computed_at TIMESTAMP)
       COMMENT 'Claimed vs evidence-backed vs enforced score per dimension.'""",
    """CREATE TABLE IF NOT EXISTS {fq}.lever_plan (
        assessment_id STRING, version INT, lever_id STRING, lever_name STRING, category STRING,
        mode STRING, status STRING, committed_wave STRING, recommended_wave INT, priority DOUBLE,
        owner STRING, kpi_name STRING, kpi_unit STRING, kpi_baseline STRING, kpi_target STRING,
        kpi_current STRING, verified_at STRING, stale BOOLEAN, exception_expires STRING,
        issues STRING, computed_at TIMESTAMP)
       COMMENT 'Lever plan and enforcement status per assessment.'""",
    """CREATE TABLE IF NOT EXISTS {fq}.findings (
        assessment_id STRING, version INT, rule STRING, severity STRING, scope STRING,
        ref STRING, message STRING, computed_at TIMESTAMP)
       COMMENT 'Enforcement findings (ENF rules) per assessment.'""",
    """CREATE TABLE IF NOT EXISTS {fq}.use_case_readiness (
        assessment_id STRING, version INT, use_case STRING, domain STRING, job STRING, status STRING,
        readiness DOUBLE, blocking STRING, gate_missing STRING, computed_at TIMESTAMP)
       COMMENT 'AI use-case readiness by job critical path (ENF-08).'""",
    """CREATE TABLE IF NOT EXISTS {fq}.audit_log (
        event_ts TIMESTAMP, assessment_id STRING, actor STRING, action STRING, detail STRING)
       COMMENT 'Append-only audit of every change and lever transition.'""",
]

DERIVED = {
    "dimension_scores": "assessment_id STRING, version INT, dimension STRING, dimension_name STRING, tier STRING, claimed DOUBLE, evidence_backed DOUBLE, enforced DOUBLE, metric_level DOUBLE, coverage DOUBLE, provisional BOOLEAN, caps STRING",
    "lever_plan": "assessment_id STRING, version INT, lever_id STRING, lever_name STRING, category STRING, mode STRING, status STRING, committed_wave STRING, recommended_wave INT, priority DOUBLE, owner STRING, kpi_name STRING, kpi_unit STRING, kpi_baseline STRING, kpi_target STRING, kpi_current STRING, verified_at STRING, stale BOOLEAN, exception_expires STRING, issues STRING",
    "findings": "assessment_id STRING, version INT, rule STRING, severity STRING, scope STRING, ref STRING, message STRING",
    "use_case_readiness": "assessment_id STRING, version INT, use_case STRING, domain STRING, job STRING, status STRING, readiness DOUBLE, blocking STRING, gate_missing STRING",
}

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DeltaStore:
    kind = "delta"

    def __init__(self, warehouse_id, catalog, schema):
        from databricks.sdk import WorkspaceClient  # imported lazily so local dev needs no SDK

        for ident in (catalog, schema):
            if not _IDENT.match(ident or ""):
                raise ValueError(f"invalid identifier: {ident!r}")
        self.w = WorkspaceClient()
        self.warehouse_id = warehouse_id
        self.catalog, self.schema = catalog, schema
        self.fq = f"`{catalog}`.`{schema}`"
        self._ready = False
        self._lock = threading.Lock()

    def describe(self):
        return {"kind": self.kind, "location": f"{self.catalog}.{self.schema}", "warehouse_id": self.warehouse_id}

    # -- low level
    def _sql(self, statement, params=None):
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        plist = [StatementParameterListItem(name=k, value=None if v is None else str(v),
                                            type="INT" if isinstance(v, int) and not isinstance(v, bool) else None)
                 for k, v in (params or {}).items()]
        resp = self.w.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=statement, parameters=plist or None, wait_timeout="30s")
        deadline = time.time() + 120
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.time() > deadline:
                self.w.statement_execution.cancel_execution(resp.statement_id)
                raise TimeoutError("SQL statement timed out")
            time.sleep(0.5)
            resp = self.w.statement_execution.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if resp.status.error else resp.status.state
            raise RuntimeError(f"SQL failed: {msg}")
        cols = [c.name for c in (resp.manifest.schema.columns or [])] if resp.manifest and resp.manifest.schema else []
        rows = (resp.result.data_array if resp.result and resp.result.data_array else [])
        return [dict(zip(cols, r)) for r in rows]

    def ensure(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            try:
                self._sql(f"CREATE SCHEMA IF NOT EXISTS {self.fq} COMMENT 'DataPulse assessment data'")
            except Exception as e:  # schema may be pre-created by an admin without CREATE SCHEMA grant
                log.warning("create schema skipped: %s", e)
            for ddl in DDL:
                self._sql(ddl.format(fq=self.fq))
            self._ready = True

    # -- documents
    def list(self):
        self.ensure()
        rows = self._sql(f"SELECT assessment_id, payload, version, created_by, CAST(created_at AS STRING) created_at, "
                         f"updated_by, CAST(updated_at AS STRING) updated_at FROM {self.fq}.assessments "
                         f"WHERE NOT coalesce(deleted, false) ORDER BY updated_at DESC")
        return [_summary(r["assessment_id"], json.loads(r["payload"]), int(r["version"]), r["created_by"],
                         r["created_at"], r["updated_by"], r["updated_at"]) for r in rows]

    def get(self, doc_id):
        self.ensure()
        rows = self._sql(f"SELECT payload, version, created_by, CAST(created_at AS STRING) created_at, updated_by, "
                         f"CAST(updated_at AS STRING) updated_at FROM {self.fq}.assessments "
                         f"WHERE assessment_id = :id AND NOT coalesce(deleted, false)", {"id": doc_id})
        if not rows:
            raise NotFoundError(doc_id)
        r = rows[0]
        doc = json.loads(r["payload"])
        v = int(r["version"])
        return doc, v, _summary(doc_id, doc, v, r["created_by"], r["created_at"], r["updated_by"], r["updated_at"])

    def create(self, doc, actor):
        self.ensure()
        doc_id = str(uuid.uuid4())
        self._sql(f"INSERT INTO {self.fq}.assessments VALUES (:id, :name, :org, :mode, 1, :payload, :actor, "
                  f"current_timestamp(), :actor, current_timestamp(), false)",
                  {"id": doc_id, "name": doc.get("name", ""), "org": doc.get("org", ""), "mode": doc.get("mode", ""),
                   "payload": json.dumps(doc), "actor": actor})
        self.audit(doc_id, actor, "create", {"name": doc.get("name")})
        return doc_id, 1

    def save(self, doc_id, doc, version, actor, action="save", detail=None):
        self.ensure()
        rows = self._sql(f"UPDATE {self.fq}.assessments SET payload = :payload, name = :name, org = :org, mode = :mode, "
                         f"version = version + 1, updated_by = :actor, updated_at = current_timestamp() "
                         f"WHERE assessment_id = :id AND version = :version AND NOT coalesce(deleted, false)",
                         {"payload": json.dumps(doc), "name": doc.get("name", ""), "org": doc.get("org", ""),
                          "mode": doc.get("mode", ""), "actor": actor, "id": doc_id, "version": int(version)})
        affected = int(next(iter(rows[0].values()))) if rows else 0
        if affected != 1:
            cur = self._sql(f"SELECT version FROM {self.fq}.assessments WHERE assessment_id = :id AND NOT coalesce(deleted, false)",
                            {"id": doc_id})
            if not cur:
                raise NotFoundError(doc_id)
            raise ConflictError(f"version {version} is stale; current is {cur[0]['version']}")
        self.audit(doc_id, actor, action, detail or {})
        return int(version) + 1

    def delete(self, doc_id, actor):
        self.ensure()
        self._sql(f"UPDATE {self.fq}.assessments SET deleted = true, updated_by = :actor, updated_at = current_timestamp() "
                  f"WHERE assessment_id = :id", {"id": doc_id, "actor": actor})
        self.audit(doc_id, actor, "delete", {})

    def audit(self, doc_id, actor, action, detail):
        try:
            self._sql(f"INSERT INTO {self.fq}.audit_log VALUES (current_timestamp(), :id, :actor, :action, :detail)",
                      {"id": doc_id, "actor": actor, "action": action, "detail": json.dumps(detail)})
        except Exception as e:  # audit must never be silently lost: surface in logs
            log.error("audit write failed for %s %s: %s", doc_id, action, e)
            raise

    def get_audit(self, doc_id, limit=200):
        self.ensure()
        rows = self._sql(f"SELECT CAST(event_ts AS STRING) event_ts, actor, action, detail FROM {self.fq}.audit_log "
                         f"WHERE assessment_id = :id ORDER BY event_ts DESC LIMIT {int(limit)}", {"id": doc_id})
        for r in rows:
            r["assessment_id"] = doc_id
            try:
                r["detail"] = json.loads(r["detail"])
            except (TypeError, ValueError):
                pass
        return rows

    def publish(self, doc_id, version, doc, results):
        """Rewrite the flattened tables for one assessment. Runs in the background after a save."""
        self.ensure()
        for table, rows in flatten(doc_id, version, doc, results).items():
            self._sql(f"DELETE FROM {self.fq}.{table} WHERE assessment_id = :id", {"id": doc_id})
            if rows:
                self._sql(f"INSERT INTO {self.fq}.{table} SELECT *, current_timestamp() AS computed_at FROM "
                          f"(SELECT inline(from_json(:rows, 'ARRAY<STRUCT<{DERIVED[table]}>>')))",
                          {"rows": json.dumps(rows)})


def flatten(doc_id, version, doc, results):
    from .framework import LEVER_INDEX, model

    dims = [{"assessment_id": doc_id, "version": version, "dimension": k, "dimension_name": model.DIM_INDEX[k]["name"],
             "tier": model.DIM_INDEX[k]["tier"], "claimed": d["claimed"], "evidence_backed": d["evidence_backed"],
             "enforced": d["enforced"], "metric_level": d["metric_level"], "coverage": d["coverage"],
             "provisional": d["provisional"], "caps": json.dumps(d["caps"])} for k, d in results["dimensions"].items()]
    levers = []
    for lid, p in results["levers"]["priorities"].items():
        st = (doc.get("levers") or {}).get(lid, {})
        plan = results["levers"]["plan"][lid]
        if not (p["applicable"] or plan["status"] != "Proposed"):
            continue
        lv = LEVER_INDEX[lid]
        levers.append({"assessment_id": doc_id, "version": version, "lever_id": lid, "lever_name": lv["name"],
                       "category": lv["category"], "mode": lv["mode"], "status": plan["status"],
                       "committed_wave": None if st.get("wave") in (None, "") else str(st.get("wave")),
                       "recommended_wave": p.get("wave"), "priority": p["priority"], "owner": st.get("owner"),
                       "kpi_name": lv["kpi"]["name"], "kpi_unit": lv["kpi"]["unit"],
                       "kpi_baseline": _s(st.get("kpi_baseline")), "kpi_target": _s(st.get("kpi_target")),
                       "kpi_current": _s(st.get("kpi_current")), "verified_at": st.get("verified_at"),
                       "stale": plan["stale"], "exception_expires": (st.get("exception") or {}).get("expires"),
                       "issues": json.dumps(plan["issues"])})
    finds = [{"assessment_id": doc_id, "version": version, "rule": f["rule"], "severity": f["severity"],
              "scope": f["scope"], "ref": str(f.get("ref")), "message": f["message"]} for f in results["findings"]]
    ucs = [{"assessment_id": doc_id, "version": version, "use_case": u.get("name"), "domain": u.get("domain"),
            "job": u.get("job"), "status": u["status"], "readiness": u.get("readiness"),
            "blocking": json.dumps(u.get("blocking", [])), "gate_missing": json.dumps(u.get("gate_missing", []))}
           for u in results["use_cases"]]
    return {"dimension_scores": dims, "lever_plan": levers, "findings": finds, "use_case_readiness": ucs}


def _s(v):
    return None if v in (None, "") else str(v)


def make_store():
    wh = os.environ.get("DATAPULSE_WAREHOUSE_ID") or os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if wh:
        return DeltaStore(wh, os.environ.get("DATAPULSE_CATALOG", "main"), os.environ.get("DATAPULSE_SCHEMA", "datapulse"))
    return LocalStore(os.environ.get("DATAPULSE_DATA_DIR", ".data"))
