"""LiveKit function tools for the Hub Concierge.

NOTE: deliberately NO `from __future__ import annotations` in this module. LiveKit resolves the
`context: RunContext` hint with typing.get_type_hints() at session start; a stringized annotation
cannot see the RunContext imported inside build_tools and every tool call raises NameError
(DIVA skill, "Gotchas that actually cost hours").
"""

import json

from hub.backend import KINDS, TOPIC_NAMES, HubBackend

_KINDS = ", ".join(KINDS)
_TOPICS = ", ".join(TOPIC_NAMES)


def _out(result: dict) -> str:
    # LiveKit passes a dict result to the model as str(dict) (a Python repr); hand it real JSON instead.
    return json.dumps(result, ensure_ascii=False, default=str)


def build_tools(backend: HubBackend) -> list:
    from livekit.agents import RunContext, function_tool

    async def search_resources(context: RunContext, query: str, type: str = "", topic: str = "") -> str:
        return _out(await backend.search(query, kind=type, topic=topic))

    async def whats_new(context: RunContext, topic: str = "", status: str = "") -> str:
        return _out(await backend.whats_new(topic=topic, status=status))

    async def save_resource(context: RunContext, resource_id: str, note: str = "") -> str:
        return _out(await backend.save(resource_id, note=note))

    async def list_topics(context: RunContext) -> str:
        return _out(backend.topics())

    return [
        function_tool(
            search_resources, name="search_resources",
            description=(
                "Search the Databricks Resource Hub catalog (docs, GitHub repos and solution accelerators, "
                "product launches, videos, articles, demos, tools, playbooks). Use it for any question about "
                "what to read, watch, try or install. `query` is a short keyword phrase. Optional `type` is one "
                f"of: {_KINDS}. Optional `topic` is one of: {_TOPICS}. Results also appear on the caller's "
                "screen with links.")),
        function_tool(
            whats_new, name="whats_new",
            description=(
                "Latest Databricks product launches from the release notes, newest first. Optional `topic` "
                f"(one of: {_TOPICS}) and `status` (Generally available, Public Preview, Beta).")),
        function_tool(
            save_resource, name="save_resource",
            description=(
                "Save one resource to the caller's shortlist when they ask to keep, save or bookmark it. "
                "`resource_id` must be an id from earlier results. Optional short `note`.")),
        function_tool(
            list_topics, name="list_topics",
            description="List the catalog's topics and resource types with counts. Use when asked what's covered."),
    ]
