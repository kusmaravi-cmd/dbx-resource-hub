"""End-to-end in text mode: a real LiveKit AgentSession with the real tools and prompt, driven by a
scripted LLM (no network). Proves the tool schemas, the RunContext wiring and the backend agree."""
import asyncio
import json

import pytest

pytest.importorskip("livekit.agents")

from livekit.agents import Agent, AgentSession  # noqa: E402
from livekit.agents import llm as lk_llm  # noqa: E402
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS  # noqa: E402

from app.prompt import INSTRUCTIONS  # noqa: E402
from app.tools import build_tools  # noqa: E402
from hub.backend import HubBackend  # noqa: E402


class _Stream(lk_llm.LLMStream):
    def __init__(self, llm, *, chat_ctx, tools, conn_options, chunk):
        super().__init__(llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._chunk = chunk

    async def _run(self) -> None:
        self._event_ch.send_nowait(self._chunk)


class ScriptedLLM(lk_llm.LLM):
    """Turn 1: call the given tool. After the tool output is in the context: answer from it."""

    def __init__(self, tool_name, args):
        super().__init__()
        self.tool_name, self.args, self.seen_tools, self.tool_output = tool_name, args, [], None

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_):
        self.seen_tools = [getattr(t, "info", t).name for t in (tools or [])]
        outputs = [i for i in chat_ctx.items if i.type == "function_call_output"]
        if outputs:
            self.tool_output = json.loads(outputs[-1].output)
            delta = lk_llm.ChoiceDelta(role="assistant", content="I've put the latest launches on your screen.")
        else:
            delta = lk_llm.ChoiceDelta(role="assistant", tool_calls=[lk_llm.FunctionToolCall(
                name=self.tool_name, arguments=json.dumps(self.args), call_id="call_1")])
        return _Stream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options,
                       chunk=lk_llm.ChatChunk(id="c1", delta=delta))


class Sink:
    def __init__(self):
        self.events = []

    async def __call__(self, frag):
        self.events.append(frag)


def _run_turn(memory, tool, args, user_input):
    async def go():
        sink = Sink()
        backend = HubBackend(memory=memory, sink=sink, user_key="ana@corp.com")
        fake = ScriptedLLM(tool, args)
        async with AgentSession(llm=fake, tools=build_tools(backend)) as session:
            await session.start(Agent(instructions=INSTRUCTIONS))
            result = await session.run(user_input=user_input)
        return fake, sink, result
    return asyncio.run(go())


def test_whats_new_turn(memory):
    fake, sink, result = _run_turn(memory, "whats_new", {"topic": "Apps and Lakebase"},
                                   "What's new in Lakebase this month?")
    assert set(fake.seen_tools) >= {"search_resources", "whats_new", "save_resource", "list_topics"}
    kinds = [type(e).__name__ for e in result.events]
    assert "FunctionCallEvent" in kinds and "FunctionCallOutputEvent" in kinds
    out = next(e for e in result.events if type(e).__name__ == "FunctionCallOutputEvent").item
    payload = json.loads(out.output)
    assert not out.is_error and payload["results"]
    assert all(r["topic"] == "Apps and Lakebase" for r in payload["results"])
    assert fake.tool_output == payload
    assert result.events[-1].item.text_content.startswith("I've put the latest launches")
    assert sink.events and sink.events[0]["results"]["items"][0]["url"].startswith("https://")
    assert "https://" not in out.output  # the model never gets URLs to read aloud


def test_search_turn_with_filters(memory):
    fake, sink, result = _run_turn(memory, "search_resources", {"query": "genie", "type": "videos"},
                                   "Any videos on Genie?")
    out = next(e for e in result.events if type(e).__name__ == "FunctionCallOutputEvent").item
    payload = json.loads(out.output)
    assert not out.is_error and payload["filters"]["type"] == "Video"
    assert payload["results"] and all(r["type"] == "Video" for r in payload["results"])
