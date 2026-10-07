# Hub Concierge: a voice agent for the Databricks Resource Hub

A voice guide to this repo's own catalog: 837 Databricks docs, GitHub repos and solution accelerators,
product launches, videos, articles, demos and tools (`../search.json`, the same index the website
searches). You open the app, click **Start call** and ask out loud:

- "What's new in Lakebase this month?" → newest launches, with GA / Preview / Beta status
- "Find me a solution accelerator for record linkage" → repos and accelerators
- "Where do I start building agents?" / "Any videos on Genie?" → docs, videos, learning paths
- "Save the first one" → written to your shortlist in Lakebase, shown next to the call

The concierge answers in two or three spoken sentences. The full results with links appear on screen,
because a voice agent should never read URLs aloud.

Built on the [DIVA](https://github.com/datasciencemonkey/diva) blueprint and its
`building-voice-agents-on-databricks` skill, targeting an **AWS Databricks workspace**.

## Architecture

```
Browser ──WebRTC──▶ LiveKit Cloud ◀──WebSocket── Agent worker  (app/agent.py)
   ▲                                               │  Deepgram STT → LLM on Unity AI Gateway → Deepgram TTS
   │ GET /api/token (HS256, agent dispatch)        │  tools → Lakebase (hybrid search, shortlist)
   │ GET /api/shortlist                            │  OTel spans → Unity Catalog table → MLflow traces
   └──────── Web tier (app/web_server.py, stdlib) ─┘
                 both started by start_app.py in ONE Databricks App container
```

| Piece | Where | Notes |
|---|---|---|
| Web/token tier | Databricks App | stdlib only; takes the signed-in user from `X-Forwarded-Email` |
| Voice worker | Same app container | LiveKit Agents 1.8.3 in an isolated `/tmp/agent-venv` (Python 3.11 pins) |
| LLM | Unity AI Gateway | `HUB_LLM_MODEL` (default `system.ai.gpt-5-nano`), Responses API with tool calling |
| Embeddings | Unity AI Gateway | `HUB_EMBED_MODEL` (default `system.ai.gte-large-en`, 1024-dim) |
| Data | Lakebase | `hub.resources` (ANN + BM25 indexes), `hub.shortlist` |
| Fallback data | Bundled `catalog.json` | in-memory BM25; the agent still works if Lakebase is down or not set up yet |
| Traces | UC table + MLflow | on when `HUB_TRACE_CATALOG/_SCHEMA/_TABLE_PREFIX` are set |
| Audio | LiveKit Cloud + Deepgram | external SaaS (the only non-Databricks pieces) |

Agent tools (`app/tools.py` → `hub/backend.py`):

| Tool | Does |
|---|---|
| `search_resources(query, type?, topic?)` | Lakebase hybrid search (vector + BM25, rank fusion); keyword-only if embeddings fail; bundled catalog if Lakebase fails |
| `whats_new(topic?, status?)` | Latest launches from the release notes, newest first |
| `save_resource(resource_id, note?)` | Adds to the caller's shortlist in Lakebase |
| `list_topics()` | What the catalog covers |

## What you need

- An **AWS Databricks workspace** with Databricks Apps, Unity AI Gateway models, and (recommended) Lakebase
- **Databricks CLI** ≥ 1.0 with a profile for that workspace: `databricks auth login --host https://<ws>.cloud.databricks.com --profile aws`
- [`uv`](https://docs.astral.sh/uv/) and Python 3.11+
- A **LiveKit Cloud** project (free tier is fine): URL, API key, API secret
- A **Deepgram** API key
- A Databricks **PAT** for the app (or use service-principal mode, see below)

## Runbook

### 1. Check the models (5 min)
In the workspace, open **AI Gateway** (or Serving) and note a fast chat model that supports tool calling
through the Responses API, and a 1024-dim embedding model. If the names differ from the defaults, set
`HUB_LLM_MODEL` / `HUB_EMBED_MODEL` in `.env.local` (the deploy script copies them into `app.yaml`).

### 2. Configure
```bash
cd voice-agent
cp .env.example .env.local     # LiveKit, Deepgram, DATABRICKS_HOST/TOKEN, models, LAKEBASE_ENDPOINT
uv venv --python 3.11 && uv pip install -r agent-requirements.txt pytest   # same pins as the app
```

### 3. Load the catalog into Lakebase (recommended)
Create a Lakebase project in the workspace (**Compute → Lakebase**, or `databricks postgres create-project`),
then copy its endpoint path (`projects/<p>/branches/<b>/endpoints/<e>`) into `LAKEBASE_ENDPOINT`.
```bash
export DATABRICKS_CONFIG_PROFILE=aws
export LAKEBASE_ENDPOINT=projects/<p>/branches/production/endpoints/<e>
.venv/bin/python infra/load_catalog.py
```
This creates `hub.resources` + `hub.shortlist` with Lakebase Search indexes, upserts 837 rows and
embeds them through the gateway. Re-run it whenever `search.json` changes (it only re-embeds changed rows).
Skip this step to start on the bundled catalog: the app runs fine, just with keyword search and a
session-only shortlist.

### 4. Try it locally (optional)
```bash
.venv/bin/python app/agent.py dev       # terminal 1: wait for "registered worker"
.venv/bin/python app/web_server.py      # terminal 2: http://localhost:8000
.venv/bin/python -m pytest -q           # 37 tests (2 need a local Postgres, else skipped)
```

### 5. Deploy to Databricks Apps
```bash
python scripts/deploy.py --profile aws --dry-run   # review the plan
python scripts/deploy.py --profile aws             # do it
```
The script follows the DIVA deployment guide end to end and is safe to re-run: it stages a clean folder
(code + `catalog.json` + a rendered `app.yaml`), creates the secret scope and secrets (values never
printed), creates the app, attaches the secret resources **before** the first deploy, grants the app's
service principal `READ` on the scope and `CAN_MANAGE` on the source folder, then
`apps start` → `sync --full` → `apps deploy`.

### 6. Verify
```bash
databricks apps logs hub-concierge --tail-lines 100 --profile aws
```
Expect `[web] Hub Concierge listening`, then 30–60 s later `installing agent deps` → `downloading model files`
→ **`registered worker`**. Only then open the app URL and start a call. A call that connects but gets no
agent almost always means the worker is still booting, its deps failed (check for a Python 3.12 pin), or
the workspace blocks outbound traffic to `*.livekit.cloud` / `api.deepgram.com`.

### 7. Turn on tracing (optional)
Set `HUB_TRACE_CATALOG`, `HUB_TRACE_SCHEMA` (and keep `HUB_TRACE_TABLE_PREFIX`) in `.env.local` and redeploy.
Each call then lands in `<catalog>.<schema>.hub_concierge_otel_spans` and shows as an MLflow trace with
typed AGENT / LLM / TOOL spans, the model, the data source and the caller (`user.id`).

## Service principal mode (no PAT)
`python scripts/deploy.py --profile aws --auth sp` leaves the PAT out: the app runs as its own service
principal. Before the first call, grant that principal query access to the two gateway models and a
Lakebase role (`infra/grant_sp.sql`). PAT mode is DIVA's tested path, so start with it unless your
workspace disallows PATs.

## Layout
```
app/agent.py         LiveKit worker: session, LLM over the gateway, tools, data channel, usage
app/tools.py         function tools (eager annotations on purpose, see the RunContext gotcha)
app/prompt.py        voice-first system prompt and greeting
app/tracing.py       OTLP → UC/MLflow, span enrichment, per-job root metadata
app/web_server.py    stdlib web tier: page, token mint, shortlist, config, health
app/web/public/      call UI (vendored livekit-client 2.22.3, no CDN needed)
hub/                 catalog normalization, Lakebase pool, gateway, hybrid + in-memory search, backend
infra/               Lakebase schema, catalog loader, SP grants
scripts/deploy.py    one-command, idempotent Databricks Apps deploy
start_app.py         single-container launcher (web tier first, worker venv behind it)
tests/               37 tests: real AgentSession turns with a scripted LLM, web tier, deploy, Postgres SQL
```

## Next steps
- Point `load_catalog.py` at a Unity Catalog table instead of `search.json` (or use a Lakebase synced table)
  so the catalog refreshes from a pipeline.
- Add an evaluation set of spoken questions and score answers with MLflow GenAI evaluation over the traces.
- Route by question type (cheap model for "what's new", stronger model for "help me plan a migration").
