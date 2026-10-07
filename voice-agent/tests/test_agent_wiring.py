"""Needs the worker stack (agent-requirements.txt); skipped where LiveKit is not installed."""
import json
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("livekit.agents")


def test_tools_module_has_eager_annotations():
    src = (Path(__file__).resolve().parents[1] / "app" / "tools.py").read_text()
    assert "from __future__ import annotations" not in src.split('"""', 2)[2]


def test_tools_resolve_runcontext_and_build(memory):
    from app.tools import build_tools
    from hub.backend import HubBackend
    tools = build_tools(HubBackend(memory=memory))
    names = sorted(t.info.name for t in tools)
    assert names == ["list_topics", "save_resource", "search_resources", "whats_new"]
    for t in tools:  # what LiveKit does at session start; NameError here = the RunContext gotcha
        typing.get_type_hints(t)


def test_agent_module_imports_and_reads_caller():
    from app import agent
    p = SimpleNamespace(metadata=json.dumps({"user": "ana@corp.com", "first_name": "Ana"}))
    ctx = SimpleNamespace(room=SimpleNamespace(remote_participants={"x": p}))
    assert agent.read_caller(ctx) == ("Ana", "ana@corp.com")
    empty = SimpleNamespace(room=SimpleNamespace(remote_participants={}))
    assert agent.read_caller(empty) == ("", "")
