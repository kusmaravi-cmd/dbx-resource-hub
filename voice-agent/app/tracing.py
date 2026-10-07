"""LiveKit OpenTelemetry spans -> Databricks OTLP ingest -> Unity Catalog table -> MLflow traces.

Pattern from the DIVA skill (references/observability.md):
  * fail-soft: tracing is off unless HUB_TRACE_CATALOG / _SCHEMA / _TABLE_PREFIX are all set;
  * the provider is installed in the worker's setup_fnc (before LiveKit opens the job's root span,
    or MLflow never lists the trace);
  * spans are enriched at export time so MLflow renders a typed AGENT / LLM / TOOL tree;
  * per-job metadata lands on the root span, keyed by trace id (one process can run several jobs);
  * flush (never shutdown) in the job's shutdown callback.
"""
from __future__ import annotations

import ast
import json
import os
import threading

_SPAN_TYPES = {"job_entrypoint": "AGENT", "agent_session": "AGENT", "llm_node": "LLM",
               "function_tool": "TOOL", "tts_node": "CHAIN", "user_turn": "CHAIN"}
_by_trace: dict[int, dict] = {}
_lock = threading.Lock()


def trace_table() -> str | None:
    cat, sch, pre = (os.getenv(f"HUB_TRACE_{k}", "").strip() for k in ("CATALOG", "SCHEMA", "TABLE_PREFIX"))
    return f"{cat}.{sch}.{pre}_otel_spans" if cat and sch and pre else None


def _json_value(raw, wrap_key):
    if raw in (None, ""):
        return None
    for parse in (json.loads, ast.literal_eval):
        try:
            return json.dumps(parse(raw))
        except Exception:  # noqa: BLE001
            continue
    return json.dumps({wrap_key: str(raw)})


def enrich_attributes(name: str, attrs: dict, *, is_root: bool, root_meta: dict | None) -> dict:
    attrs = dict(attrs)
    if is_root and root_meta:
        attrs.update(root_meta)
    if st := _SPAN_TYPES.get(name):
        attrs["mlflow.spanType"] = json.dumps(st)
    inp = out = None
    if name == "function_tool":
        attrs["gen_ai.operation.name"] = "execute_tool"
        for gk, lk in (("gen_ai.tool.name", "lk.function_tool.name"),
                       ("gen_ai.tool.call.arguments", "lk.function_tool.arguments"),
                       ("gen_ai.tool.call.result", "lk.function_tool.output")):
            if (v := attrs.get(lk)) is not None:
                attrs[gk] = v
        inp = _json_value(attrs.get("lk.function_tool.arguments"), "arguments")
        out = _json_value(attrs.get("lk.function_tool.output"), "output")
    elif name == "llm_node":
        inp = _json_value(attrs.get("lk.chat_ctx"), "input")
        out = _json_value(attrs.get("lk.response.text") or attrs.get("lk.response.function_calls"), "output")
    if inp:
        attrs["mlflow.spanInputs"] = inp
    if out:
        attrs["mlflow.spanOutputs"] = out
    return attrs


def register_job_metadata(meta: dict) -> None:
    """Call from the entrypoint: the current span there is this job's root (job_entrypoint)."""
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if ctx and ctx.trace_id:
        with _lock:
            _by_trace[ctx.trace_id] = meta


def build_tracer_provider():
    table = trace_table()
    if not table:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

        from hub.auth import bearer_token, host

        inner = OTLPSpanExporter(endpoint=f"{host()}/api/2.0/otel/v1/traces",
                                 headers={"X-Databricks-UC-Table-Name": table})

        class _Exporter(SpanExporter):
            def export(self, spans):
                for span in spans:
                    try:
                        with _lock:
                            meta = _by_trace.get(span.context.trace_id)
                            if span.parent is None:
                                _by_trace.pop(span.context.trace_id, None)
                        span._attributes = enrich_attributes(
                            span.name, span.attributes or {}, is_root=span.parent is None, root_meta=meta)
                    except Exception:  # noqa: BLE001 - enrichment never breaks export
                        pass
                try:  # SP OAuth tokens expire hourly: refresh the header on every export
                    inner._session.headers["Authorization"] = f"Bearer {bearer_token()}"
                except Exception:  # noqa: BLE001
                    pass
                return inner.export(spans)

            def force_flush(self, timeout_millis=30000):
                return inner.force_flush(timeout_millis)

            def shutdown(self):
                inner.shutdown()

        provider = TracerProvider(resource=Resource.create(
            {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "hub-concierge")}))
        provider.add_span_processor(BatchSpanProcessor(_Exporter()))
        print(f"[trace] exporting spans to {table}", flush=True)
        return provider
    except Exception as exc:  # noqa: BLE001
        print(f"[trace] disabled: {exc}", flush=True)
        return None
