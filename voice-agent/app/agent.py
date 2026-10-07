"""Hub Concierge: the LiveKit agent worker.

Deepgram STT -> a Databricks-served LLM over Unity AI Gateway (Responses API, tool calling) ->
Deepgram TTS, with tools over the Resource Hub catalog in Lakebase. Results stream to the caller's
screen over the LiveKit data channel (topic "hub").

Run:  python app/agent.py dev            (local, hot reload)
      python app/agent.py start          (production; start_app.py does this on Databricks Apps)
      python app/agent.py download-files (fetch VAD model files; start_app.py runs it at boot)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env.local", override=False)

import httpx  # noqa: E402
from livekit import agents  # noqa: E402
from livekit.agents import Agent, AgentServer, AgentSession  # noqa: E402
from livekit.agents.telemetry import set_tracer_provider  # noqa: E402
from livekit.plugins import deepgram, openai, silero  # noqa: E402
from openai.types import Reasoning  # noqa: E402
from opentelemetry import trace as otel_trace  # noqa: E402

from app.prompt import INSTRUCTIONS, greeting  # noqa: E402
from app.tools import build_tools  # noqa: E402
from app.tracing import build_tracer_provider, register_job_metadata  # noqa: E402
from hub.auth import bearer_token  # noqa: E402
from hub.backend import HubBackend  # noqa: E402
from hub.catalog import load_catalog  # noqa: E402
from hub.db import SCHEMA, create_pool_soft  # noqa: E402
from hub.gateway import base_url, embed_texts  # noqa: E402
from hub.search import MemoryIndex  # noqa: E402

log = logging.getLogger("hub-concierge")

AGENT_NAME = os.getenv("AGENT_NAME", "hub-concierge")
LLM_MODEL = os.getenv("HUB_LLM_MODEL", "system.ai.gpt-5-nano")
LLM_REASONING = os.getenv("HUB_LLM_REASONING_EFFORT", "low").strip()  # blank = model default
STT_MODEL = os.getenv("HUB_STT_MODEL", "nova-3")
TTS_VOICE = os.getenv("HUB_TTS_VOICE", "aura-2-thalia-en")
CATALOG_PATH = Path(os.getenv("HUB_CATALOG_PATH", str(ROOT / "catalog.json")))
if not CATALOG_PATH.exists():  # local dev: read the site's index directly
    CATALOG_PATH = ROOT.parent / "search.json"

_trace_provider = None


def _setup_process(proc: agents.JobProcess) -> None:
    """Runs once per worker process, before it takes a job. Tracing MUST be installed here: LiveKit
    opens the job's root span before the entrypoint runs, and MLflow lists only traces with a root."""
    global _trace_provider
    _trace_provider = build_tracer_provider()
    if _trace_provider is not None:
        otel_trace.set_tracer_provider(_trace_provider)
        set_tracer_provider(_trace_provider, metadata={"livekit.agent_name": AGENT_NAME})
    proc.userdata["memory"] = MemoryIndex(load_catalog(CATALOG_PATH))
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception as exc:  # noqa: BLE001 - STT endpointing still works without it
        print(f"[agent] silero VAD unavailable: {exc}", flush=True)
    import databricks.sdk  # noqa: F401  - warm the slow first import outside a live call


server = AgentServer(setup_fnc=_setup_process)


def read_caller(ctx: agents.JobContext) -> tuple[str, str]:
    """(first name, user key) from the caller's token metadata. Both minted by the web tier from the
    Databricks Apps identity headers, never from anything said on the call."""
    for p in ctx.room.remote_participants.values():
        try:
            meta = json.loads(getattr(p, "metadata", "") or "{}")
        except ValueError:
            meta = {}
        return str(meta.get("first_name", ""))[:40], str(meta.get("user", ""))[:128]
    return "", ""


def make_sink(room):
    async def sink(fragment: dict) -> None:
        data = json.dumps({"type": "hub", **fragment}, default=str).encode()
        await room.local_participant.publish_data(data, reliable=True, topic="hub")
    return sink


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: agents.JobContext):
    trace_meta: dict = {"hub.llm_model": LLM_MODEL}
    if _trace_provider is not None:
        register_job_metadata(trace_meta)  # the current span here is this job's root

        async def _flush() -> None:
            _trace_provider.force_flush()  # flush, never shutdown (the root span ends after this)
        ctx.add_shutdown_callback(_flush)

    pool = await create_pool_soft()
    if pool is not None:
        async def _close_pool() -> None:
            await pool.close()
        ctx.add_shutdown_callback(_close_pool)

    await ctx.connect()
    try:
        await asyncio.wait_for(ctx.wait_for_participant(), timeout=30)
    except asyncio.TimeoutError:
        pass
    first_name, user_key = read_caller(ctx)
    trace_meta.update({"hub.data_source": "lakebase" if pool is not None else "catalog"})
    if user_key:
        trace_meta["user.id"] = user_key  # MLflow's standard user attribute

    sink = make_sink(ctx.room)
    backend = HubBackend(memory=ctx.proc.userdata["memory"], pool=pool, schema=SCHEMA,
                         user_key=user_key, embed=embed_texts if pool is not None else None, sink=sink)

    llm_kwargs = dict(
        model=LLM_MODEL,
        api_key=await asyncio.to_thread(bearer_token),
        base_url=await asyncio.to_thread(base_url),
        use_websocket=False,
        store=False,
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0),
    )
    if LLM_REASONING:
        llm_kwargs["reasoning"] = Reasoning(effort=LLM_REASONING)

    session = AgentSession(
        stt=deepgram.STT(model=STT_MODEL, language="en-US"),
        llm=openai.responses.LLM(**llm_kwargs),
        tts=deepgram.TTS(model=TTS_VOICE),
        vad=ctx.proc.userdata.get("vad"),
        tools=build_tools(backend),
        max_tool_steps=4,
    )

    @session.on("session_usage_updated")
    def _on_usage(ev) -> None:
        try:
            llm = [u for u in ev.usage.model_usage if getattr(u, "type", "") == "llm_usage"]
            if llm:
                usage = {"input_tokens": sum(int(u.input_tokens) for u in llm),
                         "output_tokens": sum(int(u.output_tokens) for u in llm)}
                asyncio.ensure_future(sink({"usage": usage}))
        except Exception:  # noqa: BLE001
            pass

    await sink({"session": {"model": LLM_MODEL, "source": "lakebase" if pool is not None else "catalog",
                            "user": user_key or None}})
    await session.start(room=ctx.room, agent=Agent(instructions=INSTRUCTIONS))
    await session.generate_reply(instructions=greeting(first_name))


if __name__ == "__main__":
    agents.cli.run_app(server)
