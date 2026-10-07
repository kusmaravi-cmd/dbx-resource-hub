import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deploy", ROOT / "scripts" / "deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
TEMPLATE = (ROOT / "app.yaml").read_text()


def test_render_pat_mode_fills_values():
    out = deploy.render_app_yaml(TEMPLATE, {"HUB_LLM_MODEL": "system.ai.gpt-5-5",
                                            "LAKEBASE_ENDPOINT": "projects/p/branches/b/endpoints/e"}, "pat")
    assert 'value: "system.ai.gpt-5-5"' in out
    assert 'value: "projects/p/branches/b/endpoints/e"' in out
    assert "valueFrom: databricks-token" in out


def test_render_sp_mode_drops_pat_and_unset_lakebase():
    out = deploy.render_app_yaml(TEMPLATE, {}, "sp")
    assert "DATABRICKS_TOKEN" not in out and "databricks-token" not in out
    assert "- name: LAKEBASE_ENDPOINT" not in out and "REPLACE_" not in out
    assert "LIVEKIT_URL" in out


def test_render_never_ships_blank_values():
    out = deploy.render_app_yaml(TEMPLATE, {}, "pat")
    assert 'value: ""' not in out and "HUB_TRACE_CATALOG" not in out
    out = deploy.render_app_yaml(TEMPLATE, {"HUB_TRACE_CATALOG": "main", "HUB_TRACE_SCHEMA": "voice"}, "pat")
    assert 'value: "main"' in out and 'value: "voice"' in out


def test_requirements_are_resolved_for_python_311():
    deploy.check_requirements()  # exits on numpy >= 2.5


def test_tracing_is_off_without_config(monkeypatch):
    from app import tracing
    for k in ("HUB_TRACE_CATALOG", "HUB_TRACE_SCHEMA", "HUB_TRACE_TABLE_PREFIX"):
        monkeypatch.delenv(k, raising=False)
    assert tracing.trace_table() is None and tracing.build_tracer_provider() is None
    monkeypatch.setenv("HUB_TRACE_CATALOG", "main")
    monkeypatch.setenv("HUB_TRACE_SCHEMA", "voice")
    monkeypatch.setenv("HUB_TRACE_TABLE_PREFIX", "hub")
    assert tracing.trace_table() == "main.voice.hub_otel_spans"


def test_tool_spans_are_typed_for_mlflow():
    from app.tracing import enrich_attributes
    a = enrich_attributes("function_tool", {"lk.function_tool.name": "whats_new",
                                            "lk.function_tool.arguments": '{"topic": "x"}'},
                          is_root=False, root_meta=None)
    assert a["mlflow.spanType"] == '"TOOL"' and a["gen_ai.tool.name"] == "whats_new"
    root = enrich_attributes("job_entrypoint", {}, is_root=True, root_meta={"user.id": "u"})
    assert root["user.id"] == "u" and root["mlflow.spanType"] == '"AGENT"'
