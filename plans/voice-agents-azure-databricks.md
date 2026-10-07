# Plan: Voice agents on Azure Databricks (based on DIVA)

Sources:
- Repo: <https://github.com/datasciencemonkey/diva> (reference app + `skills/building-voice-agents-on-databricks`)
- Blog: <https://dsmonk.medium.com/building-voice-agents-on-databricks-f073ce8518a5>
- Skill: <https://github.com/datasciencemonkey/diva/tree/main/skills>

Target: a single **Azure Databricks** workspace (one workspace for dev, data, and the deployed app).

---

## 1. What DIVA is

A browser-to-agent, real-time voice support agent. Apart from the audio pipe, everything runs on Databricks:

| Layer | Component | Where it runs |
|---|---|---|
| Audio transport (WebRTC) | LiveKit Cloud | External SaaS |
| Speech-to-text + default voice | Deepgram | External SaaS |
| Expressive "Halloween" voice (optional) | ElevenLabs | External SaaS |
| Web/token tier (studio UI, LiveKit token mint, world generator) | `app/web_server.py` | Databricks App |
| Voice agent (LiveKit Agents worker: STT → LLM → TTS + tools) | `app/agent.py` | Same Databricks App container |
| LLM + embeddings, per-tier model routing | Unity AI Gateway (`{host}/ai-gateway/openai/v1`, Responses API) | Workspace |
| Data + retrieval (docs, customers, records; ANN + BM25) | Lakebase Postgres + Lakebase Search | Workspace |
| Per-turn "change the experience?" decision (optional) | `ai_decide` (Beta) | Workspace |
| Call traces | OTLP → `/api/2.0/otel/v1/traces` → UC Delta table → MLflow traces | Workspace |

Call flow: **Join** (token mint, LiveKit dispatches agent) → **Bind** (caller tier read from Lakebase, never from speech) →
**Talk** (Deepgram STT → gateway LLM → TTS) → **Ground** (`semantic_search`, `record_lookup` over Lakebase) →
**Decide** (`ai_decide` per turn) → **Show & trace** (evidence over LiveKit data channel, spans to UC/MLflow).

---

## 2. Azure-specific deltas (the things the AWS-flavored repo won't tell you)

DIVA was built and documented on an AWS workspace (`*.cloud.databricks.com`, `docs.databricks.com/aws/...`). The code
is cloud-agnostic (it only uses `DATABRICKS_HOST` + REST paths), but these must be checked/changed for Azure:

| # | Area | Azure action | Risk |
|---|---|---|---|
| A1 | Workspace host | `DATABRICKS_HOST=https://adb-<workspace-id>.<n>.azuredatabricks.net` in `app.yaml` and `.env.local` | Low |
| A2 | Auth | Many Azure tenants **disable PATs** or enforce Entra ID. DIVA's default runs as a user PAT (`DATABRICKS_TOKEN`) and pops the app SP's OAuth creds. Decide early: (a) PAT allowed → follow DIVA as-is; (b) PATs blocked → switch to the **app service principal** (OAuth M2M): keep `DATABRICKS_CLIENT_ID/SECRET`, drop the pop in `start_app.py`, grant the SP Lakebase role + gateway/endpoint `CAN_QUERY` + UC table write for traces. The OTLP exporter and gateway client currently build `Bearer {DATABRICKS_TOKEN}` headers directly — refactor them to take a token from `WorkspaceClient().config.authenticate()` | **High** |
| A3 | Lakebase + Lakebase Search on Azure | Confirm Lakebase (Autoscaling projects/branches/endpoints API used by `databricks-sdk==0.133.0` `w.postgres`) and the `lakebase_vector` / `lakebase_text` / `lakebase_tokenizer` extensions are available in our Azure region. Endpoint host will be an Azure-region host, not `…us-east-1.cloud.databricks.com` | **High** — blocker if missing; fallback is Databricks Vector Search for retrieval |
| A4 | Model names on Unity Gateway | `system.ai.gpt-5-nano`, `gpt-5-5`, `gpt-6-sol`, `gpt-5-4`, `gte-large-en` are what the author's workspace serves. List what *our* Azure workspace serves (`serving_endpoints.list` / gateway UI) and remap `UG_MODEL_*`, `UG_GEN_MODEL`, `UG_EMBED_MODEL`. Agent tool-calling uses the **Responses API**, so tier models must support it (GPT family per the repo's routing contract). Embedding model must be **1024-dim** or change `vector(1024)` in `infra/lakebase_schema.sql` | Medium |
| A5 | `ai_decide` | Beta, region-limited, admin-enabled under Previews. Check availability for our Azure region; otherwise run with `UG_AI_DECIDE=0` (rule-based fallback still works) or use the gateway chat-completions JSON-mode fallback described in the skill | Low (optional) |
| A6 | Serverless egress | The App container must reach `wss://*.livekit.cloud`, `api.deepgram.com`, `api.elevenlabs.io` (optional), and the model CDN used by `agent.py download-files` (Silero VAD / turn detector). If the workspace has **serverless egress control / network policies** or the account uses restricted egress, add these destinations. "Call connects, no agent joins" is the symptom when blocked | **High** in locked-down tenants |
| A7 | Inbound / private link | If the workspace uses front-end Private Link or IP access lists, the Databricks App URL is only reachable from the corporate network/VPN. The browser also needs outbound WebRTC (UDP/TCP 443/7881 etc.) to LiveKit Cloud — corporate firewalls may need TURN/TLS fallback | Medium |
| A8 | Data residency | Audio goes to LiveKit/Deepgram/ElevenLabs (US SaaS by default). If that's not acceptable, **option: swap STT/TTS to Azure AI Speech** via `livekit-plugins-azure` (keeps speech inside our Azure tenant). Needs a small code change: DIVA's `voice_profiles.py` currently rejects an `azure` TTS provider (see `tests/test_voice_profiles.py`) | Decision |
| A9 | Docs links | Use `learn.microsoft.com/azure/databricks/...` equivalents of every `docs.databricks.com/aws/...` reference (Apps, Lakebase, Unity AI Gateway, MLflow 3 tracing to UC) | Low |

---

## 3. Phased plan

### Phase 0 — Feasibility spike on the Azure workspace (go/no-go)
Goal: prove every Databricks dependency exists in our Azure workspace/region before writing code.

- [ ] Create CLI profile: `databricks auth login --host https://adb-….azuredatabricks.net --profile azdbx` (never rely on DEFAULT; DIVA's scripts take `DATABRICKS_CONFIG_PROFILE`).
- [ ] **Auth decision (A2):** can we mint a PAT for the app? If not, plan the SP path.
- [ ] **Unity Gateway:** list served chat + embedding models; one `POST {host}/ai-gateway/openai/v1/responses` with a function tool per candidate tier model; one `/embeddings` call (check dim = 1024).
- [ ] **Lakebase (A3):** create a Lakebase project/branch/endpoint; run `CREATE EXTENSION lakebase_vector/lakebase_text/lakebase_tokenizer`.
- [ ] **Databricks Apps:** deploy a hello-world app; confirm it starts and we can open it from our network (A7).
- [ ] **Egress (A6):** from the hello-world app, `curl`/socket test to `*.livekit.cloud`, `api.deepgram.com`, `api.elevenlabs.io`, and the model CDN.
- [ ] **Tracing:** pick catalog/schema for trace tables; confirm OTLP ingest endpoint `/api/2.0/otel/v1/traces` works on Azure (POST a test span).
- [ ] **ai_decide (A5):** check Previews page.
- [ ] External accounts: LiveKit Cloud project (URL/key/secret), Deepgram key, (optional) ElevenLabs key + voice id.

Exit criteria: all "High" rows in §2 green, or a documented fallback chosen.

### Phase 1 — Local run against Azure
- [ ] Fork DIVA (or vendor it into a new repo in our org); `uv sync` (Python 3.12+ locally).
- [ ] `.env.local`: Azure host, token/SP creds, LiveKit, Deepgram, `LAKEBASE_ENDPOINT=projects/<p>/branches/<b>/endpoints/<e>`, remapped `UG_MODEL_*`.
- [ ] `export DATABRICKS_CONFIG_PROFILE=azdbx LAKEBASE_*=… UG_SCHEMA=ug` → `uv run python infra/apply_schema.py`.
- [ ] `uv run python generate.py "Contoso Support"` (generate a world).
- [ ] Terminal 1: `uv run python app/agent.py dev` (wait for `registered worker`); terminal 2: `uv run python app/web_server.py`.
- [ ] Unit tests: `uv run pytest -q --ignore=tests/test_integration_data_plane.py`.
- [ ] Manual call: order question (Context), Standard vs VIP caller (Choice), "switch to the spooky voice" (Decide).

### Phase 2 — Deploy as a Databricks App on Azure
Follow `skills/building-voice-agents-on-databricks/references/deployment.md`, with Azure values:
- [ ] Recompile worker deps for the **Apps Python 3.11**: `uv pip compile agent-requirements.in --python-version 3.11 -o agent-requirements.txt` (numpy must be 2.4.x). Verify install in a 3.11 venv.
- [ ] Secret scope `diva-voice`: `livekit_url`, `livekit_api_key`, `livekit_api_secret`, `deepgram_api_key`, `databricks_token` (PAT path only), `elevenlabs_api_key` (optional).
- [ ] `databricks apps create diva-voice --profile azdbx`; attach **all** secret resources before first deploy (`valueFrom` only resolves once attached).
- [ ] Grant app SP: `READ` on the scope; `CAN_MANAGE` on the workspace source folder (CLI doesn't auto-grant). SP path: also Lakebase role, gateway `CAN_QUERY`, UC `USE/MODIFY` on trace schema.
- [ ] Edit `app.yaml`: `DATABRICKS_HOST` → Azure URL; `LAKEBASE_ENDPOINT`; `UG_MODEL_*`; trace catalog/schema/prefix, `MLFLOW_EXPERIMENT_NAME`, `MLFLOW_TRACING_SQL_WAREHOUSE_ID`. Remove `ELEVEN_API_KEY` entry if not using ElevenLabs.
- [ ] `databricks apps start` → `databricks sync ./stage /Workspace/Users/<me>/databricks_apps/diva-voice --full` (not `import-dir`) → `databricks apps deploy`.
- [ ] `databricks apps logs diva-voice --tail-lines 100`: expect `[web] listening`, then 30–60 s later `registered worker … wss://…livekit.cloud`.

### Phase 3 — Make it ours
- [ ] Replace generated "worlds" with real data: load our KB docs into `{schema}.documents` (chunk + embed via gateway) and customer/tier data into `{schema}.customers` (or sync from UC tables into Lakebase via synced tables).
- [ ] Rewrite `src/agent_prompt.py` and tools in `app/tools.py` for our use case (keep eager annotations — **no `from __future__ import annotations`** in tool modules).
- [ ] Tier→model routing in `src/policy/routing.py` / `tiers.py`: map to our cost/latency targets.
- [ ] Gateway guardrails, rate limits and usage tracking (Unity AI Gateway policies) per endpoint.
- [ ] Optional (A8): Azure AI Speech STT/TTS via `livekit-plugins-azure`; add to `agent-requirements.in`, extend `voice_profiles.py`, add secret `azure_speech_key` + region.

### Phase 4 — Observability, eval, hardening
- [ ] Verify traces show in the MLflow experiment with a root span (tracer provider set in `setup_fnc`, flush not shutdown — per `observability.md`).
- [ ] Dashboards: tokens/cost by tier from gateway usage tables; latency per turn from trace table.
- [ ] Latency budget: measure STT→first-token→first-audio; pick smallest tier model that meets ~<1 s.
- [ ] MLflow GenAI evaluation over recorded transcripts (groundedness, tool correctness).
- [ ] Security review: PII in transcripts/traces, retention on trace tables, scoped Lakebase role for the app.
- [ ] CI: unit tests + the 3.11 compile check + `app.yaml` lint before deploy.

---

## 4. Use the DIVA skill with Claude Code
Copy `skills/building-voice-agents-on-databricks` into this project's `.claude/skills/` (or `~/.claude/skills/`).
It encodes the deploy steps and the hard-won gotchas. Add an Azure note to it (§2 above) so the agent doesn't assume
`*.cloud.databricks.com` or PAT auth.

## 5. Top gotchas carried over from the skill
1. Worker deps must be compiled for **Python 3.11** (Apps runtime) — else no agent ever joins.
2. No `from __future__ import annotations` in LiveKit tool modules (`NameError: RunContext`).
3. `databricks sync --full`, not `workspace import-dir`.
4. Pop `DATABRICKS_CLIENT_ID/SECRET` when using a PAT (ambiguous auth), or don't use a PAT at all (Azure SP path).
5. App SP needs `CAN_MANAGE` on the source folder + `READ` on the secret scope.
6. Worker registers 30–60 s after deploy — don't test before `registered worker`.
7. Egress to LiveKit/Deepgram/model CDN is required — biggest Azure-specific risk.

## 6. Open questions for us
- Which Azure region is the workspace in (drives Lakebase, `ai_decide`, model availability)?
- Are PATs allowed for apps, or must we use the SP / Entra ID path?
- Is serverless egress restricted / is front-end Private Link on?
- Is sending audio to LiveKit Cloud + Deepgram acceptable, or do we need Azure AI Speech (and possibly self-hosted LiveKit)?
- First real use case + data source to replace the generated worlds?
