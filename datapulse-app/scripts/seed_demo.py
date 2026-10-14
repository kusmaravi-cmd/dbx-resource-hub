"""Create a realistic demo assessment through the API.

    python scripts/seed_demo.py                                    # local app, Harbourline Logistics
    python scripts/seed_demo.py https://<app-url> --profile DEFAULT  # deployed Databricks App
    python scripts/seed_demo.py <url> --company northwind            # or: --company all

Against a deployed Databricks App the script authenticates with your Databricks CLI login
(OAuth, `databricks auth login`) via the SDK, or with DATABRICKS_TOKEN if set. Databricks Apps
accept OAuth tokens, not personal access tokens.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

EV = lambda t, ref: {"type": t, "ref": ref}  # noqa: E731

# --------------------------------------------------------------------------- Northwind Health
# A mid-size health insurer: decent platform, weak governance, ambitious agent plans. Attested (Phase 0).
NORTHWIND = {
    "create": {"name": "Phase 0 discovery", "org": "Northwind Health (demo)", "mode": "attested", "platform": "databricks"},
    "meta": dict(date="2026-10-13", assessor="DataPulse demo", attendees="CDO, Head of Data Eng, CISO delegate, Actuarial lead",
                 scope="Claims, Member, Provider domains; 42 CDEs"),
    "use_cases": [
        {"id": "uc1", "name": "Claims triage copilot", "domain": "Claims", "job": "Inference", "outcome": "-20% adjudication time", "owner": "VP Claims"},
        {"id": "uc2", "name": "Readmission risk model", "domain": "Member", "job": "Training", "outcome": "-5% 30-day readmissions", "owner": "CMO office"},
        {"id": "uc3", "name": "Prior-auth agent", "domain": "Provider", "job": "Agent", "outcome": "Same-day decisions for 60% of requests", "owner": "COO"},
    ],
    "answers": {
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
    },
    "metrics": {"M-DISC-1": 12, "M-DISC-2": 34, "M-TRU-1": 36, "M-TRU-2": 96, "M-GOV-1": 15, "M-GOV-2": 41,
                "M-INT-1": 28, "M-PERF-1": 81, "M-OPS-1": 58, "M-VAL-1": 9},
    "levers": [
        ("L-02", "Committed", {"owner": "Head of Data Eng", "wave": "0", "kpi_target": 100}),
        ("L-02", "Enforced", {"enforcement_evidence": ["Harvester runs for lake, warehouse, BI"], "kpi_baseline": 40}),
        ("L-20", "Committed", {}),  # rejected on purpose: shows the lifecycle gate and the audit trail
    ],
}

# --------------------------------------------------------------------------- Harbourline Logistics
# A freight and warehousing group, 18 months into a lakehouse programme. Strong engineering and
# platform, governance catching up, an agent use case that the lever gates correctly hold back.
# Validated mode: every level above 2 carries evidence, so the evidence gates are enforced.
HARBOURLINE = {
    "create": {"name": "Wave 1 readiness review", "org": "Harbourline Logistics (demo)", "mode": "validated",
               "platform": "databricks", "target_level": 3.5},
    "meta": dict(date="2026-10-14", assessor="Everforth DataPulse demo",
                 attendees="CDO, VP Data Platform, Head of Network Planning, CISO delegate, Customs Ops lead, FP&A partner",
                 scope="Shipments, Network, Customs, Finance domains; 36 critical data elements",
                 notes="Fictional company for demonstration. Lakehouse live for 18 months; Unity-style catalog in place; "
                       "governance council still the main enforcement route."),
    "use_cases": [
        {"id": "uc1", "name": "Shipment ETA prediction", "domain": "Network", "job": "Training",
         "outcome": "ETA error under 2 hours for 90% of lanes", "owner": "Head of Network Planning"},
        {"id": "uc2", "name": "Dispatcher copilot (text-to-SQL)", "domain": "Shipments", "job": "Inference",
         "outcome": "-30% time to answer dispatcher queries", "owner": "VP Operations"},
        {"id": "uc3", "name": "Customs document agent", "domain": "Customs", "job": "Agent",
         "outcome": "Auto-file 50% of low-risk customs declarations", "owner": "Customs Ops lead"},
        {"id": "uc4", "name": "Lane profitability insights", "domain": "Finance", "job": "Inference",
         "outcome": "Weekly margin by lane in the exec pack", "owner": "FP&A partner"},
    ],
    "answers": {
        "R1.1": (3, [EV("inspection", "Catalog search for 'proof of delivery' returned certified table with owner in 2 minutes")], "high"),
        "R1.2": (3, [EV("metric", "Catalog export: 62% of scoped CDEs have owner and definition")], "high"),
        "R1.3": (4, [EV("metric", "Harvester logs: 100% of lakehouse schemas scanned nightly"),
                     EV("inspection", "New table appeared in catalog within 1 hour of creation")], "high"),
        "R2.1": (2, [EV("document", "Two definitions of 'on-time delivery' (carrier vs customer promise)")], "high",
                 "Ops and Finance report different on-time %; reconciled manually each month"),
        "R2.2": (3, [EV("artifact", "Column descriptions on the shipments gold tables")], "medium"),
        "R2.3": (3, [EV("inspection", "Column lineage from exec dashboard back to TMS feed")], "high"),
        "R3.1": (3, [EV("document", "Incident log: 11 of 18 incidents caught by monitors")], "high"),
        "R3.2": (3, [EV("artifact", "Expectations on 21 critical tables with freshness and completeness checks")], "high"),
        "R3.3": (2, [], "medium", "Network planners re-pull carrier scans before big decisions"),
        "R4.1": (3, [EV("metric", "Access request system: median 4 business days for sensitive data")], "high"),
        "R4.2": (3, [EV("metric", "Classifier scan: 74% of in-scope assets tagged")], "high"),
        "R4.3": (3, [EV("inspection", "Audit query answered 'who read consignee X' in 25 minutes")], "medium"),
        "R4.4": (2, [], "medium", "Retention defined but deletes not propagated to ML feature tables"),
        "R5.1": (4, [EV("metric", "Last 4 sources onboarded in a median of 9 days"),
                     EV("artifact", "Metadata-driven ingestion config with CDC")], "high"),
        "R5.2": (2, [], "medium", "Customer and carrier masters differ between TMS and ERP"),
        "R5.3": (3, [EV("artifact", "Schema-drift alert on carrier EDI feed, routed to owner")], "medium"),
        "R6.1": (4, [EV("metric", "SLO dashboard: 92% of critical workloads met freshness"),
                     EV("inspection", "Workload isolation by domain on serverless warehouses")], "high"),
        "R6.2": (3, [EV("artifact", "Cost per data product from tagged usage tables")], "medium"),
        "R6.3": (3, [EV("document", "Peak-season runbook with autoscaling limits")], "medium"),
        "R7.1": (2, [EV("artifact", "Pilot agent queries via a shared service principal")], "high",
                 "Agent identity is shared with the ETL service principal"),
        "R7.2": (2, [], "medium", "Prompt logs kept, but no link from agent action to data read"),
        "R7.3": (1, [], "high", "No written rule on what agents may write back"),
        "D1.1": (3, [EV("artifact", "AI-drafted descriptions on 40% of gold tables, steward-approved")], "medium"),
        "D1.2": (2, [], "medium"),
        "D2.1": (3, [EV("artifact", "Profiling-suggested expectations on shipments tables")], "medium"),
        "D2.2": (3, [EV("metric", "Median incident resolution 20 hours")], "medium"),
        "D2.3": (2, [], "medium", "About half of alerts are muted"),
        "D3.1": (2, [EV("document", "Spreadsheet of 9 models; vendor AI not included")], "high"),
        "D3.2": (3, [EV("document", "Model release checklist with sign-off")], "medium"),
        "D3.3": (2, [], "medium"),
        "D4.1": (4, [EV("inspection", "PR, CI tests and asset bundle deploy for last pipeline change"),
                     EV("metric", "96% of production changes through CI/CD")], "high"),
        "D4.2": (3, [EV("document", "On-call rota with automated retries and paging")], "medium"),
        "D5.1": (2, [], "medium", "Metric views exist for finance only"),
        "D5.2": (2, [EV("metric", "Copilot pilot benchmark: 64% correct answers")], "medium"),
        "D6.1": (2, [], "medium"),
        "D6.2": (1, [], "medium"),
        "P1.1": (3, [EV("document", "Pain-ranked domain backlog signed off by COO")], "high"),
        "P1.2": (3, [EV("artifact", "Scoping sheets with CDEs for ETA and copilot use cases")], "medium"),
        "P2.1": (3, [EV("document", "Quarterly wave funding tied to value checkpoints")], "high"),
        "P2.2": (3, [EV("metric", "Fuel-surcharge recovery report validated by Finance, 2 months ago")], "high"),
        "P3.1": (2, [], "high", "Council approves policies; platform enforces masking only on 3 tables"),
        "P3.2": (3, [EV("document", "Restore drill on shipments history, Q3")], "medium"),
        "P4.1": (3, [EV("artifact", "Golden-path template used by 2 domain teams")], "medium"),
        "P4.2": (3, [EV("metric", "New engineers ship first change in 6 days on average")], "medium"),
        "P5.1": (3, [EV("artifact", "AI coding assistant in the pipeline repo with PR review")], "medium"),
        "P5.2": (2, [], "medium", "Policy written; no gateway, usage unknown"),
        "P6.1": (3, [EV("artifact", "Consumer-signed spec for the lane margin product")], "medium"),
        "P6.2": (2, [], "medium"),
        "P7.1": (2, [EV("document", "Time to onboard a source tracked; other velocity measures not baselined")], "high"),
        "P7.2": (2, [], "medium", "Monthly report counts pipelines and tables"),
    },
    "metrics": {"M-DISC-1": 4, "M-DISC-2": 62, "M-UND-1": 9, "M-TRU-1": 61, "M-TRU-2": 20, "M-TRU-3": 44,
                "M-GOV-1": 4, "M-GOV-2": 74, "M-INT-1": 9, "M-PERF-1": 92, "M-ACT-1": 8, "M-ACT-2": 7,
                "M-OPS-1": 34, "M-INS-1": 8, "M-VAL-1": 2},
    "levers": [
        # Foundations already running, now verified against their KPI targets.
        ("L-02", "Committed", {"owner": "VP Data Platform", "wave": "0", "kpi_target": 100}),
        ("L-02", "Enforced", {"enforcement_evidence": ["Nightly harvester logs for lakehouse, ERP replica and BI"], "kpi_baseline": 55}),
        ("L-02", "Verified", {"kpi_current": 100}),
        ("L-16", "Committed", {"owner": "Data Engineering lead", "wave": "0", "kpi_target": 10}),
        ("L-16", "Enforced", {"enforcement_evidence": ["Ingestion framework config; CDC on TMS and ERP"], "kpi_baseline": 35}),
        ("L-16", "Verified", {"kpi_current": 9}),
        ("L-28", "Committed", {"owner": "Platform Engineering", "wave": "0", "kpi_target": 95}),
        ("L-28", "Enforced", {"enforcement_evidence": ["Branch protection + CI on pipeline repo; prod deploys only via bundles"], "kpi_baseline": 60}),
        # Governance mechanisms in flight.
        ("L-03", "Committed", {"owner": "CDO office", "wave": "0", "kpi_target": 95}),
        ("L-03", "Enforced", {"enforcement_evidence": ["Ownership synced nightly from HR system to catalog"], "kpi_baseline": 48}),
        ("L-11", "Committed", {"owner": "CISO delegate", "wave": "0", "kpi_target": 95}),
        ("L-11", "Enforced", {"enforcement_evidence": ["Classifier runs on every new table at ingestion"], "kpi_baseline": 41}),
        ("L-14", "Committed", {"owner": "Security Engineering", "wave": "0", "kpi_target": 1}),
        ("L-14", "Enforced", {"enforcement_evidence": ["System audit tables queried by the standard audit notebook"], "kpi_baseline": 24}),
        ("L-08", "Committed", {"owner": "Data Reliability lead", "wave": "1", "kpi_target": 85}),
        ("L-12", "Committed", {"owner": "CISO delegate", "wave": "1", "kpi_target": 1}),
        ("L-05", "Committed", {"owner": "FP&A partner", "wave": "1", "kpi_target": 90}),
        ("L-25", "Committed", {"owner": "Head of AI", "wave": "1", "kpi_target": 100}),
        # Agent controls: committed, but enforcement is blocked until ABAC is enforced (ENF-08/09).
        ("L-20", "Committed", {"owner": "Head of AI", "wave": "2", "kpi_target": 100}),
        ("L-20", "Enforced", {"enforcement_evidence": ["Draft agent service principal"], "kpi_baseline": 0}),  # rejected on purpose
    ],
}

PROFILES = {"harbourline": HARBOURLINE, "northwind": NORTHWIND}


def fill_demo(doc, company="northwind"):
    """Populate an assessment document with a demo company's answers (shared with the browser-edition build)."""
    p = PROFILES[company]
    doc["meta"].update(p["meta"])
    doc["use_cases"] = [dict(u) for u in p["use_cases"]]
    for qid, ans in p["answers"].items():
        doc["responses"][qid] = {"level": ans[0], "evidence": ans[1], "confidence": ans[2], "note": ans[3] if len(ans) > 3 else ""}
    for qid, v in p["metrics"].items():
        doc["responses"][qid] = {"value": v}
    return doc


# --------------------------------------------------------------------------- API client

def auth_headers(base, profile):
    if os.environ.get("DATABRICKS_TOKEN"):
        return {"Authorization": "Bearer " + os.environ["DATABRICKS_TOKEN"]}
    if base.startswith(("http://localhost", "http://127.0.0.1")):
        return {}
    from databricks.sdk.core import Config  # only needed for a deployed app
    return Config(profile=profile).authenticate() if profile else Config().authenticate()


def make_call(base, headers):
    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            sys.exit(f"{method} {path} returned HTTP {status} and a non-JSON page. If this is a Databricks App, "
                     "authenticate with OAuth (`databricks auth login`) and pass --profile; personal access tokens are not accepted.")
        if status >= 400 and status != 422:
            sys.exit(f"{method} {path} failed with HTTP {status}: {data}")
        return {"status": status, **data} if isinstance(data, dict) else data
    return call


def seed(call, company):
    p = PROFILES[company]
    created = call("POST", "/api/assessments", p["create"])
    aid = created["id"]
    a = call("GET", f"/api/assessments/{aid}")
    r = call("PUT", f"/api/assessments/{aid}", {"version": a["version"], "doc": fill_demo(a["doc"], company)})
    v = r["version"]
    for lever, to, fields in p["levers"]:
        r = call("POST", f"/api/assessments/{aid}/levers/{lever}/transition", {"version": v, "to": to, "fields": fields})
        if r.get("errors"):
            print(f"  {lever} -> {to}: rejected (expected for the demo, and audited): {r['errors'][0]}")
        else:
            v = r["version"]
            print(f"  {lever} -> {to}")
    res = call("GET", f"/api/assessments/{aid}")["results"]
    t1 = res["tiers"]["T1"]
    print(f"Created {p['create']['org']}: id {aid}")
    print(f"  readiness ceiling {t1['ceiling']} (binding: {', '.join(t1['binding'])}), {len(res['findings'])} findings")
    return aid


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", default="http://localhost:8000", help="app URL (default: local)")
    ap.add_argument("--company", choices=[*PROFILES, "all"], default="harbourline")
    ap.add_argument("--profile", default=None, help="Databricks CLI profile for a deployed app")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    call = make_call(base, auth_headers(base, a.profile))
    for company in (PROFILES if a.company == "all" else [a.company]):
        seed(call, company)
    print(f"\nOpen {base} to see the assessment(s).")


if __name__ == "__main__":
    main()
