# DataPulse App

A platform-agnostic data & AI readiness assessment that **enforces** its answers and its levers, packaged as a **Databricks App** on Databricks on AWS. It persists to Unity Catalog Delta tables and runs anywhere FastAPI runs.

DataPulse Browser Lite v1.1 was a reference browser with ten velocity questions. This app turns that framework into a working, auditable assessment:

| | Browser Lite v1.1 | DataPulse App |
|---|---|---|
| Questions | 10 velocity prompts | **50 episodic questions** across 20 dimensions + **15 measured metrics** |
| Answers | Self-reported level | Claimed → evidence-backed → **enforced**, with every cap explained |
| Levers | Not modelled | **39 levers**, each with an enforcement mechanism, KPI, prerequisites and lifecycle |
| Use cases | Scoping protocol text | Use cases scored on their job's critical path, with **lever gates** |
| Platform | Browser only | Databricks App + Unity Catalog, audit log, portfolio views |

## What makes the questions better

Every question follows the same design rules (see `server/framework/questions.py`):

- **Episodic, not aspirational.** "Walk me through the last time…" rather than "Do you have a catalog?". Policies show intent; episodes show what actually happens.
- **Five behaviourally anchored levels.** Each level is observable and mutually exclusive, so two assessors reach the same answer.
- **Intent, probes and red flags.** Every question says why it is asked, how to dig deeper and which answers usually signal inflation.
- **Scoped denominators.** Coverage is measured against the critical data elements of the prioritised use cases, not the whole estate.
- **Measured metrics triangulate.** For example, median days to onboard a source or the share of incidents caught by monitoring. A dimension cannot claim more than one level above what its metrics show.
- **Role-targeted.** Filter the interview by the role in the room (executive, steward, engineer, security, finance…).
- **Platform-agnostic.** No product names in prompts or anchors.

## Enforcement rules

| Rule | What it enforces |
|---|---|
| ENF-01/02 | Evidence gates: L3+ needs more than verbal attestation; L4+ needs a system metric or inspection; L5 needs two pieces of evidence |
| ENF-03 | Metric triangulation caps a dimension at measured level + 1 |
| ENF-04 | Any Critical question at L1 caps its dimension at 2 |
| ENF-05 | Dimension precedence (for example R3 ≤ R2 + 1; R7 ≤ min(R1..R4); D2 ≤ R3 + 1) |
| ENF-06 | Readiness ceiling = min(R1..R6), with the binding constraint named (A5) |
| ENF-07 | Any execution principle below 1.5 is critical and must be addressed in Wave 0 |
| ENF-08 | Use-case gate: critical path ≥ 3 for Go; Agent use cases also need L-20/21/22 Enforced, Training needs L-11 |
| ENF-09 | Lever lifecycle (see below) |
| ENF-10 | Every wave contains a lever that pays back within 90 days and respects capacity (A6) |
| ENF-11–13 | Coverage, confidence, verification decay and exception expiry |

**Attested** mode (Phase 0) treats evidence gates as warnings and shows what the score would be once validated. **Validated** mode caps.

## Levers are enforced, not just planned

Each lever declares its enforcement **mode**: preventive (blocks), detective (detects and routes), corrective (remediates) or directive (sets the standard). It also declares the **mechanism**, the **evidence** that proves it, a **KPI**, the **dimensions it lifts**, **prerequisite levers** and **precondition levels**. Reference implementations are given for platform-agnostic, open source, Databricks, Snowflake, AWS, Microsoft and Google.

The status can only change through the transition API, which enforces:

- **Proposed → Committed**: an owner, a wave and a KPI target.
- **Committed → Enforced**: enforcement evidence, a KPI baseline, prerequisite levers Enforced, and precondition levels met. A time-bound exception (approver, justification, ≤ 180 days) is the only override. Directive levers also need an enforced paired lever.
- **Enforced → Verified**: the KPI current value meets its target.
- Moving back or retiring requires a reason. Stale verifications (> 90 days) and expired exceptions are raised as findings.

Clients cannot set a status by editing the document (the server ignores it). Every transition, including rejected ones, is written to the audit log.

The roadmap generator ranks levers by lift toward the target. It weights the lift toward the binding constraint, blocked use cases and critical principles, and divides by effort. Prerequisites inherit priority from the levers they unblock. Levers are then sequenced into three waves under ENF-07/09/10.

## Architecture

```
static/            no-build web UI (vanilla JS)
server/app.py      FastAPI: REST API + static hosting
server/engine.py   scoring & enforcement engine (pure functions, unit-tested)
server/framework/  model (axioms, dimensions, rules), questions, levers
server/store.py    DeltaStore (Unity Catalog via SQL Statement API) | LocalStore (JSON)
server/report.py   executive summary (Markdown)
sql/               grants and portfolio views
databricks.yml     Asset Bundle for deployment
app.yaml           Databricks App runtime config
```

The Unity Catalog tables are created on first start in `main.datapulse`, which you can change in `app.yaml`:

- `assessments`: one row per assessment, full JSON document, optimistic-concurrency `version`
- `dimension_scores`, `lever_plan`, `findings`, `use_case_readiness`: flattened, rewritten after each save
- `audit_log`: append-only record of every change and lever transition, with the user's identity from Databricks Apps headers

## Deploy to Databricks on AWS

**Quickest:** one command with the Python SDK. It uploads the app, attaches the warehouse, grants the app's service principal access to the schema and starts the app:

```bash
pip install databricks-sdk
databricks auth login --host https://<workspace>.cloud.databricks.com    # or export DATABRICKS_HOST / DATABRICKS_TOKEN
python scripts/deploy.py --warehouse-id <warehouse-id> --catalog main --schema datapulse
```

**Or with Asset Bundles:**

Prerequisites: Databricks Apps enabled in the workspace, Databricks CLI ≥ 0.250 authenticated to the workspace (`databricks auth login --host https://<workspace>.cloud.databricks.com`), and a SQL warehouse (serverless recommended).

1. Set `workspace.host` in `databricks.yml`.
2. Deploy and start:
   ```bash
   cd datapulse-app
   databricks bundle deploy -t aws --var warehouse_id=<warehouse-id>
   databricks bundle run datapulse -t aws
   ```
3. Grant the app's service principal access to the schema. Run `sql/01_setup_grants.sql` with the principal's application ID from the app's Authorization tab.
4. Open the app URL from the Apps page. Then create `sql/02_portfolio_views.sql` for portfolio dashboards (AI/BI or Genie).
5. Give users access via the app's **Permissions** (CAN USE). Everyone with access sees all assessments in the schema; use separate schemas or apps per client if you need isolation.

Without bundles, you can create the app in the UI (Compute → Apps → Create → Custom), add a SQL warehouse resource with the key `sql-warehouse`, and `databricks apps deploy datapulse --source-code-path /Workspace/Users/<you>/datapulse-app`.

## Demo assessments

`scripts/seed_demo.py` creates fictional companies through the API, so every step is validated and audited like a real one:

- **Harbourline Logistics (demo)** (default): validated mode, 50/50 questions and 15/15 metrics, four use cases. Shows verified and enforced levers, a readiness ceiling bound by R2, and a customs agent blocked by the agent lever gates, including a rejected L-20 transition in the audit log.
- **Northwind Health (demo)**: attested Phase 0 discovery with weaker governance.

Against the deployed app, using your Databricks CLI OAuth login:

```bash
python scripts/seed_demo.py https://<app-url> --profile <profile> --company all
```

## Run locally

```bash
cd datapulse-app
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python app.py                        # http://localhost:8000, data in ./.data
python scripts/seed_demo.py --company all   # optional demo assessments
pytest -q                            # engine, API and Delta store tests
```

To use Unity Catalog from your laptop, set `DATAPULSE_WAREHOUSE_ID` and authenticate the Databricks SDK (for example, `DATABRICKS_CONFIG_PROFILE`).

## Browser edition (no server)

`artifact/` holds a single-page edition for demos: the same UI, framework and enforcement rules, with the engine ported to JavaScript (`artifact/engine.js`) and an in-page API (`artifact/api-shim.js`) that keeps data in the viewer's browser. `tests/test_js_engine_parity.py` checks that both engines agree on random assessments.

```bash
python scripts/build_artifact.py     # -> artifact/dist/DataPulse.html (open in any browser)
```

## API

`GET /api/framework` · `GET|POST /api/assessments` · `GET|PUT|DELETE /api/assessments/{id}` · `POST /api/assessments/{id}/levers/{lever}/transition` · `GET /api/assessments/{id}/audit` · `GET /api/assessments/{id}/report.md|export.csv|export.json` · `POST /api/evaluate` (stateless scoring for notebooks).

## Extending the framework

Add questions with `Q(...)` or `M(...)` in `questions.py` and levers with `L(...)` in `levers.py`. On startup the app refuses to run if referential integrity fails: unknown dimensions or levers, dependency cycles, directive levers with no pair, missing platform implementations, or metric bands in the wrong order. `pytest` checks the same.
