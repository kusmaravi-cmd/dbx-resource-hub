# Plan: Voice agents on AWS Databricks (based on DIVA)

Sources: [DIVA repo](https://github.com/datasciencemonkey/diva) ·
[blog](https://dsmonk.medium.com/building-voice-agents-on-databricks-f073ce8518a5) ·
[skill](https://github.com/datasciencemonkey/diva/tree/main/skills/building-voice-agents-on-databricks)

Target: one **AWS Databricks** workspace (`https://<workspace>.cloud.databricks.com`).
DIVA was built and verified on AWS, so the repo, skill and `app.yaml` apply almost as-is.
(The Azure version of this plan, with the extra Azure deltas, is in `voice-agents-azure-databricks.md`.)

## Why AWS is the lower-risk choice
| Concern | AWS |
|---|---|
| Host / docs | Repo defaults already use `*.cloud.databricks.com` and `docs.databricks.com/aws` |
| Auth | DIVA's default (app runs with a user PAT) is the tested path |
| Lakebase + Lakebase Search | Verified by the author (e.g. `us-east-1` endpoint) — still confirm in our region |
| Unity Gateway models | Author's model list (`system.ai.gpt-5-nano`, `gpt-5-5`, `gpt-6-sol`, `gpt-5-4`, `gte-large-en`) came from an AWS workspace |
| Egress | Standard serverless workspace reached LiveKit Cloud / ElevenLabs out of the box |
| `ai_decide` | Beta, region-limited — check Previews in our region |

> **Status:** Phases 1–3 are implemented in [`voice-agent/`](../voice-agent/README.md): the **Hub Concierge**,
> a voice guide over this repo's own catalog (`search.json`), packaged as a Databricks App with a one-command
> deploy (`scripts/deploy.py`). What's left needs workspace access: Phase 0 checks, loading Lakebase, deploying.

## Phase 0 — Readiness check (half a day)
- [ ] CLI profile: `databricks auth login --host https://<ws>.cloud.databricks.com --profile awsdbx`.
- [ ] Can we create a PAT for the app? (if not, use the app service principal — see Gotcha 4).
- [ ] Unity Gateway: list served chat + embedding models; remap `UG_MODEL_*`, `UG_GEN_MODEL`, `UG_EMBED_MODEL` if ours differ (tier models must support the Responses API with tools; embeddings must be 1024-dim).
- [ ] Lakebase: create project/branch/endpoint; confirm `lakebase_vector`, `lakebase_text`, `lakebase_tokenizer` extensions.
- [ ] Databricks Apps enabled; workspace egress not restricted (or allow `*.livekit.cloud`, `api.deepgram.com`, `api.elevenlabs.io`, model CDN).
- [ ] UC catalog/schema for traces + an MLflow experiment + a SQL warehouse.
- [ ] `ai_decide` enabled in Previews (optional — `UG_AI_DECIDE=0` otherwise).
- [ ] External accounts: LiveKit Cloud (URL/key/secret), Deepgram key, ElevenLabs key + voice id (optional).

## Phase 1 — Run locally against the AWS workspace
```bash
git clone https://github.com/datasciencemonkey/diva && cd diva
uv sync
cp .env.example .env.local        # host, token, LiveKit, Deepgram, Lakebase, models
export DATABRICKS_CONFIG_PROFILE=awsdbx
export LAKEBASE_ENDPOINT=projects/<p>/branches/<b>/endpoints/<e> LAKEBASE_DATABASE=databricks_postgres UG_SCHEMA=ug
uv run python infra/apply_schema.py
uv run python generate.py "Northwind Outfitters"
uv run python app/agent.py dev    # terminal 1 — wait for "registered worker"
uv run python app/web_server.py   # terminal 2 — http://localhost:8000
uv run pytest -q --ignore=tests/test_integration_data_plane.py
```
Test a call: order question (Context), Standard vs VIP caller (Choice), "switch to the spooky voice" (AI Decide).

## Phase 2 — Deploy as a Databricks App
Per `references/deployment.md`:
- [ ] `uv pip compile agent-requirements.in --python-version 3.11 -o agent-requirements.txt` (numpy 2.4.x).
- [ ] Secret scope `diva-voice`: `livekit_url`, `livekit_api_key`, `livekit_api_secret`, `deepgram_api_key`, `databricks_token`, `elevenlabs_api_key` (optional).
- [ ] `databricks apps create diva-voice`; attach all secret resources **before** first deploy.
- [ ] Grant app SP `READ` on the scope and `CAN_MANAGE` on `/Workspace/Users/<me>/databricks_apps/diva-voice`.
- [ ] Edit `app.yaml`: `DATABRICKS_HOST`, `LAKEBASE_ENDPOINT`, `UG_MODEL_*`, trace catalog/schema/prefix, MLflow experiment + warehouse id.
- [ ] `databricks apps start` → `databricks sync ./stage <WSP> --full` → `databricks apps deploy diva-voice --source-code-path <WSP>`.
- [ ] `databricks apps logs diva-voice`: `[web] listening`, then `registered worker` 30–60 s later.

## Phase 3 — Make it ours
- [ ] Load our KB into `{schema}.documents` (chunk + embed via gateway) and customers/tiers into `{schema}.customers` (or Lakebase synced tables from UC).
- [ ] Rewrite `src/agent_prompt.py` and `app/tools.py` for our use case.
- [ ] Tune tier→model routing (`src/policy/routing.py`, `tiers.py`) for cost/latency.
- [ ] Gateway guardrails, rate limits, usage tracking.

## Phase 4 — Observability & hardening
- [ ] Traces visible in MLflow with a root span (provider set in `setup_fnc`; `force_flush`, not `shutdown`).
- [ ] Dashboards: cost/tokens by tier, per-turn latency.
- [ ] MLflow GenAI evaluation on transcripts; PII/retention review for traces; CI with the 3.11 compile check.

## Gotchas (from the skill)
1. Worker deps compiled for **Python 3.11**, or no agent ever joins.
2. No `from __future__ import annotations` in LiveKit tool modules.
3. `databricks sync --full`, not `workspace import-dir`.
4. PAT path: `start_app.py` pops `DATABRICKS_CLIENT_ID/SECRET`. No PATs → run as the app SP and grant it Lakebase, gateway and UC trace-table access.
5. App SP needs `CAN_MANAGE` on the source folder + `READ` on the scope.
6. Don't test until logs show `registered worker`.
7. Generic `App deployment failed unexpectedly` on a bare hello-world = platform issue; retry later.

## Open questions
- AWS region of the workspace (Lakebase, `ai_decide`, model availability)?
- PAT allowed for the app?
- First real use case + data source?
