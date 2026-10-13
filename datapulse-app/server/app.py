"""DataPulse API and static UI host (a Databricks App, also runs anywhere FastAPI runs)."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine
from .framework import LEVER_INDEX, QUESTION_INDEX, get_framework, model, validate_framework
from .report import markdown_report
from .store import ConflictError, NotFoundError, make_store

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("datapulse")

problems = validate_framework()
if problems:  # fail fast: an inconsistent framework would silently mis-score
    raise RuntimeError("framework integrity: " + "; ".join(problems))

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="DataPulse", version=model.FRAMEWORK_VERSION)
store = make_store()


def actor(request: Request) -> str:
    # Databricks Apps forwards the signed-in user's identity in these headers.
    h = request.headers
    return h.get("x-forwarded-email") or h.get("x-forwarded-preferred-username") or h.get("x-forwarded-user") or "local-user"


def _publish(doc_id, version, doc, results):
    try:
        store.publish(doc_id, version, doc, results)
    except Exception:  # derived tables are rebuildable; never fail the user's save because of them
        log.exception("publish of derived tables failed for %s v%s", doc_id, version)


def _load(doc_id):
    try:
        return store.get(doc_id)
    except NotFoundError:
        raise HTTPException(404, "Assessment not found")


def _sanitize(doc):
    """Keep only known fields with the right shapes; unknown question or lever ids are dropped."""
    base = engine.new_assessment()
    out = {k: doc.get(k, v) for k, v in base.items()}
    out["mode"] = out["mode"] if out["mode"] in model.ASSESSMENT_MODES else "attested"
    try:
        out["target_level"] = min(5.0, max(2.0, float(out["target_level"])))
    except (TypeError, ValueError):
        out["target_level"] = 3.0
    try:
        out["wave_capacity"] = min(15, max(2, int(out["wave_capacity"])))
    except (TypeError, ValueError):
        out["wave_capacity"] = 6
    out["responses"] = {k: v for k, v in (doc.get("responses") or {}).items() if k in QUESTION_INDEX and isinstance(v, dict)}
    out["levers"] = {k: v for k, v in (doc.get("levers") or {}).items() if k in LEVER_INDEX and isinstance(v, dict)}
    out["use_cases"] = [u for u in (doc.get("use_cases") or []) if isinstance(u, dict)][:50]
    out["meta"] = {**base["meta"], **{k: str(v) for k, v in (doc.get("meta") or {}).items() if isinstance(v, (str, int, float))}}
    return out


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    org: str = ""
    mode: str = "attested"
    target_level: float = 3.0
    platform: str = "generic"


class SaveBody(BaseModel):
    version: int
    doc: dict


class TransitionBody(BaseModel):
    version: int
    to: str
    fields: dict = {}


# --------------------------------------------------------------------------- api

@app.get("/api/health")
def health():
    return {"ok": True, "store": store.describe(), "framework": model.FRAMEWORK_VERSION}


@app.get("/api/me")
def me(request: Request):
    return {"user": actor(request)}


@app.get("/api/framework")
def framework():
    return get_framework()


@app.get("/api/assessments")
def list_assessments():
    return store.list()


@app.post("/api/assessments")
def create_assessment(body: CreateBody, request: Request):
    doc = engine.new_assessment(body.name, body.org, body.mode, body.target_level, body.platform)
    doc_id, version = store.create(doc, actor(request))
    return {"id": doc_id, "version": version}


@app.get("/api/assessments/{doc_id}")
def get_assessment(doc_id: str):
    doc, version, meta = _load(doc_id)
    return {"meta": meta, "version": version, "doc": doc, "results": engine.evaluate(doc)}


@app.put("/api/assessments/{doc_id}")
def save_assessment(doc_id: str, body: SaveBody, request: Request, bg: BackgroundTasks):
    stored, version, _ = _load(doc_id)
    doc = engine.protect_lever_status(_sanitize(body.doc), stored)
    try:
        new_version = store.save(doc_id, doc, body.version, actor(request), "save", _diff(stored, doc))
    except ConflictError as e:
        raise HTTPException(409, f"This assessment was changed by someone else ({e}). Reload to continue.")
    results = engine.evaluate(doc)
    bg.add_task(_publish, doc_id, new_version, doc, results)
    return {"version": new_version, "doc": doc, "results": results}


@app.delete("/api/assessments/{doc_id}")
def delete_assessment(doc_id: str, request: Request):
    _load(doc_id)
    store.delete(doc_id, actor(request))
    return {"ok": True}


@app.post("/api/assessments/{doc_id}/levers/{lever_id}/transition")
def transition(doc_id: str, lever_id: str, body: TransitionBody, request: Request, bg: BackgroundTasks):
    stored, version, _ = _load(doc_id)
    if body.version != version:
        raise HTTPException(409, "This assessment changed since you loaded it. Reload to continue.")
    who = actor(request)
    new_doc, errors = engine.transition_lever(stored, lever_id, body.to, body.fields, actor=who)
    if errors:
        store.audit(doc_id, who, "lever_transition_rejected", {"lever": lever_id, "to": body.to, "errors": errors})
        return JSONResponse(status_code=422, content={"errors": errors})
    try:
        new_version = store.save(doc_id, new_doc, version, who, "lever_transition",
                                 {"lever": lever_id, "from": engine.lever_state(stored, lever_id)["status"], "to": body.to,
                                  "reason": body.fields.get("reason", "")})
    except ConflictError as e:
        raise HTTPException(409, str(e))
    results = engine.evaluate(new_doc)
    bg.add_task(_publish, doc_id, new_version, new_doc, results)
    return {"version": new_version, "doc": new_doc, "results": results}


@app.post("/api/evaluate")
def evaluate_adhoc(doc: dict):
    """Stateless scoring, for notebooks and integrations."""
    return engine.evaluate(_sanitize(doc))


@app.get("/api/assessments/{doc_id}/audit")
def audit(doc_id: str):
    _load(doc_id)
    return store.get_audit(doc_id)


@app.get("/api/assessments/{doc_id}/export.json")
def export_json(doc_id: str):
    doc, version, meta = _load(doc_id)
    payload = {"meta": meta, "framework_version": model.FRAMEWORK_VERSION, "doc": doc, "results": engine.evaluate(doc)}
    return Response(json.dumps(payload, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{_slug(doc)}.json"'})


@app.get("/api/assessments/{doc_id}/export.csv")
def export_csv(doc_id: str):
    doc, _, _ = _load(doc_id)
    res = engine.evaluate(doc)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "id", "name", "claimed", "evidence_backed", "enforced", "detail"])
    for k, d in res["dimensions"].items():
        w.writerow(["dimension", k, model.DIM_INDEX[k]["name"], d["claimed"], d["evidence_backed"], d["enforced"],
                    "; ".join(f"{c['rule']}: {c['reason']}" for c in d["caps"]) + (" [provisional]" if d["provisional"] else "")])
    for qid, q in res["questions"].items():
        r = doc.get("responses", {}).get(qid, {})
        w.writerow(["question", qid, QUESTION_INDEX[qid]["prompt"], q["claimed"], q["evidence_backed"], q["enforced"],
                    ("N/A " if q["na"] else "") + (r.get("note") or "")])
    for wv in res["levers"]["waves"]:
        for lid in wv["levers"]:
            w.writerow(["roadmap", lid, LEVER_INDEX[lid]["name"], "", "", "", wv["name"]])
    for f in res["findings"]:
        w.writerow(["finding", f["rule"], f["severity"], "", "", "", f["message"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{_slug(doc)}.csv"'})


@app.get("/api/assessments/{doc_id}/report.md")
def export_md(doc_id: str):
    doc, _, meta = _load(doc_id)
    md = markdown_report(doc, engine.evaluate(doc), meta)
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{_slug(doc)}.md"'})


def _slug(doc):
    import re
    s = re.sub(r"[^a-z0-9]+", "-", f"datapulse-{doc.get('org') or ''}-{doc.get('name') or ''}".lower()).strip("-")
    return s or "datapulse"


def _diff(old, new):
    """Compact audit detail: which responses, levers and use cases changed."""
    def changed(a, b):
        return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    d = {"responses": changed(old.get("responses", {}), new.get("responses", {})),
         "levers": changed(old.get("levers", {}), new.get("levers", {}))}
    if old.get("use_cases") != new.get("use_cases"):
        d["use_cases"] = True
    for k in ("name", "org", "mode", "target_level", "wave_capacity", "platform", "meta"):
        if old.get(k) != new.get(k):
            d.setdefault("settings", []).append(k)
    return d


# --------------------------------------------------------------------------- ui

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
