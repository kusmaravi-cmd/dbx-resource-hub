"""Create a realistic demo assessment through the API.

    python scripts/seed_demo.py [base_url]

Against a deployed Databricks App, pass the app URL and set DATABRICKS_TOKEN
(an OAuth token with access to the app), e.g. from `databricks auth token`.
"""

import json
import os
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if os.environ.get("DATABRICKS_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["DATABRICKS_TOKEN"])
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


DOC = "doc"
EV = lambda t, ref: {"type": t, "ref": ref}  # noqa: E731

# A mid-size health insurer: decent platform, weak governance, ambitious agent plans.
ANSWERS = {
    "R1.1": (3, [EV("inspection", "Live catalog search for 'claims adjudication' found certified asset")], "medium"),
    "R1.2": (2, [EV("metric", "Catalog export: 34% of CDEs have owner+definition")], "high"),
    "R1.3": (3, [EV("document", "Harvester config for warehouse + lake")], "medium"),
    "R2.1": (2, [], "high", "'Member months' has 3 definitions across finance and actuarial"),
    "R2.2": (2, [], "medium"),
    "R2.3": (3, [EV("inspection", "Table-level lineage shown for claims mart")], "medium"),
    "R3.1": (2, [EV("document", "Incident log: 9 of 14 found by business users")], "high"),
    "R3.2": (3, [EV("artifact", "Freshness SLOs on 12 critical tables")], "medium"),
    "R3.3": (2, [], "medium", "Actuarial keeps its own reconciliation workbook"),
    "R4.1": (4, [], "low", "Claimed ABAC everywhere; no evidence offered"),
    "R4.2": (2, [EV("metric", "Scanner covers lake only; 41% classified")], "high"),
    "R4.3": (2, [], "medium"),
    "R4.4": (1, [], "high", "Erasure not propagated to sandboxes"),
    "R5.1": (3, [EV("artifact", "Ingestion framework config for last 3 sources")], "medium"),
    "R5.2": (2, [], "medium"),
    "R5.3": (2, [], "medium"),
    "R6.1": (3, [EV("metric", "SLO dashboard: 81% met")], "high"),
    "R6.2": (2, [], "medium"),
    "R6.3": (3, [EV("document", "Workload isolation design")], "medium"),
    "R7.1": (2, [], "medium", "Pilot agent uses a shared service credential"),
    "R7.2": (1, [], "high"),
    "R7.3": (2, [], "medium"),
    "D1.1": (2, [], "medium"),
    "D1.2": (2, [], "medium"),
    "D2.1": (3, [EV("artifact", "Profiling-suggested rules on claims tables")], "medium"),
    "D2.2": (2, [], "medium"),
    "D3.1": (2, [], "high", "Vendor AI in CRM and call centre not inventoried"),
    "D3.2": (3, [EV("document", "Model release checklist")], "medium"),
    "D4.1": (3, [EV("inspection", "PR + CI run for last pipeline change")], "high"),
    "D4.2": (2, [], "medium"),
    "D5.1": (2, [], "medium"),
    "D5.2": (1, [], "high"),
    "D6.1": (2, [], "medium"),
    "P1.1": (3, [EV("document", "Domain value backlog")], "medium"),
    "P1.2": (2, [], "medium"),
    "P2.1": (2, [], "high", "Single three-year program, value promised in year 3"),
    "P2.2": (2, [], "medium"),
    "P3.1": (2, [], "high", "Data governance council is the enforcement mechanism"),
    "P3.2": (3, [EV("document", "Restore drill record, Q2")], "medium"),
    "P4.1": (2, [], "medium"),
    "P5.1": (2, [], "medium"),
    "P6.1": (3, [EV("artifact", "Consumer-signed spec for claims product")], "medium"),
    "P7.1": (1, [], "high"),
    "P7.2": (2, [], "medium"),
}
METRICS = {"M-DISC-1": 12, "M-DISC-2": 34, "M-TRU-1": 36, "M-TRU-2": 96, "M-GOV-1": 15, "M-GOV-2": 41,
           "M-INT-1": 28, "M-PERF-1": 81, "M-OPS-1": 58, "M-VAL-1": 9}


def fill_demo(doc):
    """Populate an assessment document with the demo answers (shared with the browser-edition build)."""
    doc["meta"].update(date="2026-10-13", assessor="DataPulse demo", attendees="CDO, Head of Data Eng, CISO delegate, Actuarial lead",
                       scope="Claims, Member, Provider domains; 42 CDEs")
    doc["use_cases"] = [
        {"id": "uc1", "name": "Claims triage copilot", "domain": "Claims", "job": "Inference", "outcome": "-20% adjudication time", "owner": "VP Claims"},
        {"id": "uc2", "name": "Readmission risk model", "domain": "Member", "job": "Training", "outcome": "-5% 30-day readmissions", "owner": "CMO office"},
        {"id": "uc3", "name": "Prior-auth agent", "domain": "Provider", "job": "Agent", "outcome": "Same-day decisions for 60% of requests", "owner": "COO"},
    ]
    for qid, ans in ANSWERS.items():
        lvl, ev, conf = ans[0], ans[1], ans[2]
        doc["responses"][qid] = {"level": lvl, "evidence": ev, "confidence": conf, "note": ans[3] if len(ans) > 3 else ""}
    for qid, v in METRICS.items():
        doc["responses"][qid] = {"value": v}
    return doc


def main():
    created = call("POST", "/api/assessments", {"name": "Phase 0 discovery", "org": "Northwind Health (demo)",
                                                "mode": "attested", "platform": "databricks"})
    aid = created["id"]
    a = call("GET", f"/api/assessments/{aid}")
    doc = fill_demo(a[DOC])
    r = call("PUT", f"/api/assessments/{aid}", {"version": a["version"], "doc": doc})
    v = r["version"]
    # Commit and enforce a first lever, showing the lifecycle gates.
    r = call("POST", f"/api/assessments/{aid}/levers/L-02/transition",
             {"version": v, "to": "Committed", "fields": {"owner": "Head of Data Eng", "wave": "0", "kpi_target": 100}})
    v = r["version"]
    r = call("POST", f"/api/assessments/{aid}/levers/L-02/transition",
             {"version": v, "to": "Enforced", "fields": {"enforcement_evidence": ["Harvester runs for lake, warehouse, BI"], "kpi_baseline": 40}})
    v = r.get("version", v)
    rej = call("POST", f"/api/assessments/{aid}/levers/L-20/transition", {"version": v, "to": "Committed", "fields": {}})
    print("created", aid)
    print("example rejected transition:", rej.get("errors"))


if __name__ == "__main__":
    main()
