"""DataPulse scoring and enforcement engine.

Pure functions over plain dicts so the same logic runs in the app, in tests
and in a notebook. Every cap and gate emits a finding that names the rule
(ENF-xx) that produced it, so each score can be explained.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone

from .framework import LEVER_INDEX, LEVERS, QUESTIONS, metric_level, model

EVIDENCE_STRENGTH = {e["id"]: e["strength"] for e in model.EVIDENCE_TYPES}
EFFORT_COST = {"S": 1.0, "M": 1.6, "L": 2.4}
ENFORCED_STATES = ("Enforced", "Verified")
VERIFY_DAYS = 90
MAX_EXCEPTION_DAYS = 180


# --------------------------------------------------------------------------- helpers

def _today(today=None) -> date:
    if today is None:
        return date.today()
    if isinstance(today, str):
        return date.fromisoformat(today[:10])
    return today


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _wmean(pairs):
    tw = sum(w for _, w in pairs)
    if not tw:
        return None
    return sum(v * w for v, w in pairs) / tw


def _r(x):
    return None if x is None else round(x, 2)


def new_assessment(name="", org="", mode="attested", target_level=3.0, platform="generic"):
    return {
        "name": name, "org": org, "mode": mode if mode in model.ASSESSMENT_MODES else "attested",
        "target_level": float(target_level), "wave_capacity": 6, "platform": platform,
        "meta": {"date": "", "assessor": "", "attendees": "", "scope": "", "notes": ""},
        "responses": {}, "use_cases": [], "levers": {},
    }


def lever_state(assessment, lever_id):
    st = assessment.get("levers", {}).get(lever_id) or {}
    st.setdefault("status", "Proposed")
    return st


def exception_active(st, today):
    ex = st.get("exception") or {}
    exp = _parse_date(ex.get("expires"))
    return bool(ex.get("approver") and ex.get("justification") and exp and exp >= today)


# --------------------------------------------------------------------------- questions

def score_question(q, resp, mode):
    """Return per-question scoring with evidence gates (ENF-01, ENF-02) and confidence (ENF-12)."""
    resp = resp or {}
    out = {"id": q["id"], "dim": q["dim"], "kind": q["kind"], "na": bool(resp.get("na")),
           "claimed": None, "evidence_backed": None, "enforced": None, "findings": []}
    if out["na"]:
        return out
    if q["kind"] == "metric":
        lvl = metric_level(q, resp.get("value"))
        out.update(claimed=lvl, evidence_backed=lvl, enforced=lvl, value=resp.get("value"))
        return out
    lvl = resp.get("level")
    if lvl in (None, ""):
        return out
    lvl = max(1, min(5, int(lvl)))
    ev = resp.get("evidence") or []
    strengths = [EVIDENCE_STRENGTH.get(e.get("type"), 0) for e in ev if (e.get("ref") or "").strip()]
    strong = [s for s in strengths if s >= 1]
    operating = [s for s in strengths if s >= 2]
    cap, rule, why = 5, None, None
    if lvl >= 3 and not strong:
        cap, rule, why = 2, "ENF-01", "Level 3+ claimed with no evidence beyond verbal attestation."
    elif lvl >= 4 and not operating:
        cap, rule, why = 3, "ENF-02", "Level 4+ claimed without a system metric or platform inspection."
    elif lvl == 5 and len(strong) < 2:
        cap, rule, why = 4, "ENF-02", "Level 5 needs two independent pieces of evidence."
    backed = min(lvl, cap)
    enforced = backed if mode == "validated" else lvl
    out.update(claimed=lvl, evidence_backed=backed, enforced=enforced)
    if rule:
        out["findings"].append({
            "rule": rule, "severity": "cap" if mode == "validated" else "warning",
            "scope": "question", "ref": q["id"], "dim": q["dim"],
            "message": f"{q['id']}: {why} " + (f"Capped {lvl} to {backed}." if mode == "validated"
                                              else f"Would cap {lvl} to {backed} when validated."),
        })
    if lvl >= 4 and resp.get("confidence") == "low":
        out["findings"].append({"rule": "ENF-12", "severity": "warning", "scope": "question", "ref": q["id"],
                                "dim": q["dim"], "message": f"{q['id']}: level {lvl} recorded with low confidence. Validate before relying on it."})
    return out


# --------------------------------------------------------------------------- dimensions

def _dimension_base(dim, qscores):
    qs = [q for q in QUESTIONS if q["dim"] == dim]
    att = [q for q in qs if q["kind"] == "attested"]
    met = [q for q in qs if q["kind"] == "metric"]
    applicable = [q for q in att if not qscores[q["id"]]["na"]]
    answered = [q for q in applicable if qscores[q["id"]]["claimed"] is not None]
    w = model.WEIGHTS
    res = {
        "id": dim, "total": len(att), "applicable": len(applicable), "answered": len(answered),
        "coverage": (len(answered) / len(applicable)) if applicable else 0.0,
        "claimed": _wmean([(qscores[q["id"]]["claimed"], w[q["weight"]]) for q in answered]),
        "evidence_backed": _wmean([(qscores[q["id"]]["evidence_backed"], w[q["weight"]]) for q in answered]),
        "enforced": _wmean([(qscores[q["id"]]["enforced"], w[q["weight"]]) for q in answered]),
        "metric_level": None, "metrics": [], "caps": [],
    }
    mlv = [(qscores[q["id"]]["claimed"], q["id"]) for q in met if qscores[q["id"]]["claimed"] is not None]
    if mlv:
        res["metric_level"] = sum(v for v, _ in mlv) / len(mlv)
        res["metrics"] = [{"id": i, "level": v} for v, i in mlv]
    res["provisional"] = res["answered"] == 0 or res["coverage"] < 0.5
    res["critical_floor"] = [q["id"] for q in answered
                             if q["weight"] == "Critical" and qscores[q["id"]]["enforced"] == 1]
    res["critical_floor_backed"] = [q["id"] for q in answered
                                    if q["weight"] == "Critical" and qscores[q["id"]]["evidence_backed"] == 1]
    return res


def _cap(dimres, key, limit, rule, reason, findings, severity="cap", record=True):
    cur = dimres[key]
    if cur is None or cur <= limit + 1e-9:
        return
    dimres[key] = limit
    if record:
        dimres["caps"].append({"rule": rule, "from": _r(cur), "to": _r(limit), "reason": reason})
        findings.append({"rule": rule, "severity": severity, "scope": "dimension", "ref": dimres["id"],
                         "dim": dimres["id"], "message": f"{dimres['id']} capped {cur:.1f} to {limit:.1f}: {reason}"})


def score_dimensions(assessment, qscores, findings):
    dims = {d["id"]: _dimension_base(d["id"], qscores) for d in model.DIMENSIONS}
    for key in ("enforced", "evidence_backed"):
        record = key == "enforced"
        for dr in dims.values():
            floor = dr["critical_floor"] if key == "enforced" else dr["critical_floor_backed"]
            if floor:
                _cap(dr, key, 2.0, "ENF-04", f"critical question(s) {', '.join(floor)} at level 1.", findings,
                     severity="blocker", record=record)
            if dr["metric_level"] is not None:
                _cap(dr, key, dr["metric_level"] + 1.0, "ENF-03",
                     f"measured metrics imply level {dr['metric_level']:.1f}; attested score may not exceed it by more than 1.",
                     findings, record=record)
        for dep in model.DEPENDENCIES:
            dr = dims[dep["dim"]]
            ups = [dims[u][key] for u in dep["upon"] if dims[u][key] is not None and not dims[u]["provisional"]]
            if len(ups) != len(dep["upon"]):
                continue
            limit = min(ups) + dep["slack"]
            _cap(dr, key, limit, "ENF-05", f"depends on {', '.join(dep['upon'])}. {dep['why']}", findings, record=record)
    for dr in dims.values():
        if dr["provisional"] and dr["answered"]:
            findings.append({"rule": "ENF-11", "severity": "warning", "scope": "dimension", "ref": dr["id"], "dim": dr["id"],
                             "message": f"{dr['id']} is provisional: {dr['answered']} of {dr['applicable']} applicable questions answered. Excluded from tier scores."})
    return dims


# --------------------------------------------------------------------------- tiers / velocity

def score_tiers(dims, findings):
    def scored(ids, key="enforced"):
        return {i: dims[i][key] for i in ids if dims[i][key] is not None and not dims[i]["provisional"]}

    r_ids = ["R1", "R2", "R3", "R4", "R5", "R6"]
    t1 = scored(r_ids)
    t1b = scored(r_ids, "evidence_backed")
    ceiling = min(t1.values()) if t1 else None
    binding = sorted([k for k, v in t1.items() if ceiling is not None and v - ceiling < 0.05])
    missing = [i for i in r_ids if i not in t1]
    tiers = {"T1": {"ceiling": _r(ceiling), "ceiling_evidence_backed": _r(min(t1b.values()) if t1b else None),
                    "binding": binding, "mean": _r(sum(t1.values()) / len(t1) if t1 else None),
                    "r7": _r(dims["R7"]["enforced"]), "missing": missing, "complete": not missing}}
    if ceiling is not None:
        findings.append({"rule": "ENF-06", "severity": "info", "scope": "tier", "ref": "T1",
                         "message": f"Readiness ceiling {ceiling:.1f}, bound by {', '.join(binding)}. "
                                    f"No AI outcome can exceed this until {', '.join(binding)} improve."
                                    + (f" Not yet assessed: {', '.join(missing)}." if missing else "")})
    d = scored(["D1", "D2", "D3", "D4", "D5", "D6"])
    t2 = None
    if d:
        wsum = sum(model.DIM_INDEX[k]["weight"] for k in d)
        t2 = sum(v * model.DIM_INDEX[k]["weight"] for k, v in d.items()) / wsum
    if t2 is None:
        fly = None
    elif t2 >= 4 and ceiling is not None and ceiling >= 4:
        fly = "Compounding"
    elif t2 >= 3:
        fly = "Active"
    elif t2 >= 2:
        fly = "Emerging"
    else:
        fly = "Not Engaged"
    tiers["T2"] = {"score": _r(t2), "flywheel": fly, "scored": sorted(d)}
    p = scored(["P1", "P2", "P3", "P4", "P5", "P6", "P7"])
    crit = sorted([k for k, v in p.items() if v < 1.5])
    tiers["T3"] = {"score": _r(sum(p.values()) / len(p) if p else None), "critical": crit, "scored": sorted(p)}
    for c in crit:
        findings.append({"rule": "ENF-07", "severity": "blocker", "scope": "tier", "ref": c, "dim": c,
                         "message": f"Execution principle {c} ({model.DIM_INDEX[c]['name']}) is critical (below 1.5). Wave 0 must address it."})
    return tiers


def score_velocity(qscores):
    out = {}
    for v in model.VELOCITY:
        mets = [qscores[q["id"]]["claimed"] for q in QUESTIONS
                if q["kind"] == "metric" and q.get("velocity") == v["id"] and qscores[q["id"]]["claimed"] is not None]
        if mets:
            out[v["id"]] = {"level": _r(sum(mets) / len(mets)), "source": "measured", "n": len(mets)}
            continue
        att = [qscores[q["id"]]["enforced"] for q in QUESTIONS
               if q["kind"] == "attested" and q.get("velocity") == v["id"] and qscores[q["id"]]["enforced"] is not None]
        out[v["id"]] = ({"level": _r(sum(att) / len(att)), "source": "attested", "n": len(att)} if att
                        else {"level": None, "source": None, "n": 0})
    return out


# --------------------------------------------------------------------------- use cases

def score_use_cases(assessment, dims, findings, today):
    out = []
    for uc in assessment.get("use_cases", []):
        job = uc.get("job")
        if job not in model.JOBS:
            out.append({**uc, "status": "Unscoped", "readiness": None, "blocking": [], "gate_missing": [],
                        "reason": "Choose an AI job type (Inference, Training or Agent) to evaluate readiness."})
            continue
        path = model.JOBS[job]["path"]
        vals = {d: dims[d]["enforced"] for d in path}
        unknown = [d for d, v in vals.items() if v is None]
        gate = [lid for lid in model.JOB_LEVER_GATES.get(job, [])
                if lever_state(assessment, lid)["status"] not in ENFORCED_STATES]
        if unknown:
            out.append({**uc, "status": "Insufficient data", "readiness": None, "path": path, "blocking": unknown,
                        "gate_missing": gate, "reason": f"Assess {', '.join(unknown)} to evaluate this use case."})
            continue
        readiness = min(vals.values())
        blocking = sorted([d for d, v in vals.items() if v < 3], key=lambda d: vals[d])
        if readiness < 2 or gate:
            status = "Blocked"
        elif readiness < 3:
            status = "Conditional"
        else:
            status = "Go"
        reason = []
        if blocking:
            reason.append("Below 3 on " + ", ".join(f"{d} ({vals[d]:.1f})" for d in blocking) + ".")
        if gate:
            reason.append(f"{job} gate: lever(s) {', '.join(gate)} not yet Enforced (ENF-08).")
        out.append({**uc, "status": status, "readiness": _r(readiness), "path": path,
                    "path_scores": {d: _r(v) for d, v in vals.items()}, "blocking": blocking,
                    "gate_missing": gate, "reason": " ".join(reason) or "All critical-path dimensions at 3 or above."})
        if status != "Go":
            findings.append({"rule": "ENF-08", "severity": "blocker" if status == "Blocked" else "warning",
                             "scope": "use_case", "ref": uc.get("id") or uc.get("name"),
                             "message": f"Use case '{uc.get('name') or uc.get('id')}' ({job}) is {status}. {' '.join(reason)}"})
    return out


# --------------------------------------------------------------------------- levers

def _importance(dims, tiers, use_cases):
    imp = {}
    binding = set(tiers["T1"]["binding"])
    crit = set(tiers["T3"]["critical"])
    for d in model.DIMENSIONS:
        i = 1.0
        if d["id"] in binding:
            i += 1.5
        i += 0.5 * sum(1 for uc in use_cases if d["id"] in uc.get("blocking", []))
        if d["tier"] == "T2":
            i += d["weight"] * 2
        if d["id"] in crit:
            i += 1.0
        if dims[d["id"]]["enforced"] is None:
            i *= 0.5
        imp[d["id"]] = i
    return imp


def _current(dims):
    return {k: (v["enforced"] if v["enforced"] is not None else 1.0) for k, v in dims.items()}


def prioritise_levers(assessment, dims, tiers, use_cases):
    target = float(assessment.get("target_level") or 3.0)
    cur = _current(dims)
    imp = _importance(dims, tiers, use_cases)
    gate_jobs = {uc.get("job") for uc in use_cases if uc.get("gate_missing")}
    gate_levers = {lid for j in gate_jobs for lid in model.JOB_LEVER_GATES.get(j, [])}
    crit = set(tiers["T3"]["critical"])
    pr = {}
    for lv in LEVERS:
        st = lever_state(assessment, lv["id"])["status"]
        applicable = any(cur[t] < lv["trigger_below"] for t in lv["targets"])
        v, reasons = 0.0, []
        for t, lift in lv["targets"].items():
            gap = max(0.0, target - cur[t])
            head = max(0.0, 5.0 - cur[t])
            to_target = min(lift, gap)
            v += imp[t] * to_target + 0.2 * min(lift, head)
            if to_target > 0:
                reasons.append(f"lifts {t} toward target ({cur[t]:.1f} to {target:.0f})")
        if lv["id"] in gate_levers:
            v += 2.0
            reasons.append("required by a use-case gate (ENF-08)")
        if crit & set(lv["targets"]):
            reasons.append("addresses a critical execution principle (ENF-07)")
        if set(tiers["T1"]["binding"]) & set(lv["targets"]):
            reasons.append("moves the readiness ceiling's binding constraint (ENF-06)")
        pr[lv["id"]] = {"id": lv["id"], "status": st, "applicable": applicable or lv["id"] in gate_levers,
                        "own_priority": v / EFFORT_COST[lv["effort"]], "reasons": reasons}
    # unblocking value: prerequisites inherit half the priority of their dependents (transitive)
    eff = {k: p["own_priority"] for k, p in pr.items()}
    for _ in range(3):
        nxt = dict((k, pr[k]["own_priority"]) for k in pr)
        for lv in LEVERS:
            if not pr[lv["id"]]["applicable"] or pr[lv["id"]]["status"] in ENFORCED_STATES + ("Retired",):
                continue
            for r in lv["requires"]:
                if pr[r]["status"] not in ENFORCED_STATES:
                    nxt[r] += 0.5 * eff[lv["id"]]
        eff = nxt
    for k, p in pr.items():
        p["priority"] = round(eff[k], 2)
        p["rank_score"] = eff[k]  # unrounded, used for ordering so ties break identically everywhere
        if eff[k] - p["own_priority"] > 0.05:
            p["reasons"].append("prerequisite that unblocks other high-value levers")
            p["applicable"] = True
    return pr


def plan_waves(assessment, dims, tiers, pr, findings):
    cap = int(assessment.get("wave_capacity") or 6)
    proj = _current(dims)
    done = {lid for lid in LEVER_INDEX if lever_state(assessment, lid)["status"] in ENFORCED_STATES}
    retired = {lid for lid in LEVER_INDEX if lever_state(assessment, lid)["status"] == "Retired"}
    planned = {}
    waves = []
    pending = [lid for lid, p in pr.items() if p["applicable"] and lid not in done and lid not in retired]

    def eligible(lid, avail, projection):
        lv = LEVER_INDEX[lid]
        miss_l = [r for r in lv["requires"] if r not in avail]
        miss_d = {d: m for d, m in lv["preconditions"].items() if projection[d] + 1e-9 < m}
        return miss_l, miss_d

    for w in model.WAVES:
        wid = w["id"]
        avail = done | {k for k, v in planned.items() if v < wid}
        chosen, violations = [], []
        # committed levers pinned to this wave by the plan owner
        for lid in pending:
            st = lever_state(assessment, lid)
            if st["status"] == "Committed" and str(st.get("wave")) == str(wid) and lid not in planned:
                miss_l, miss_d = eligible(lid, avail, proj)
                if miss_l or miss_d:
                    violations.append({"rule": "ENF-09", "lever": lid,
                                       "message": f"{lid} committed to {w['name']} before its prerequisites: "
                                                  + ", ".join(miss_l + [f"{d}>={m}" for d, m in miss_d.items()])})
                chosen.append(lid)
        cands = [lid for lid in pending if lid not in planned and lid not in chosen
                 and not (lever_state(assessment, lid)["status"] == "Committed" and lever_state(assessment, lid).get("wave") not in (None, "", wid, str(wid)))]
        cands = [lid for lid in cands if not any(eligible(lid, avail, proj))]
        cands.sort(key=lambda lid: -pr[lid]["rank_score"])
        for lid in cands:
            if len(chosen) >= cap:
                break
            chosen.append(lid)
        # ENF-07: wave 0 must touch every critical execution principle
        if wid == 0:
            for c in tiers["T3"]["critical"]:
                if not any(c in LEVER_INDEX[l]["targets"] for l in chosen):
                    fix = next((l for l in cands if c in LEVER_INDEX[l]["targets"] and l not in chosen), None)
                    if fix:
                        if len(chosen) >= cap:
                            chosen.pop()
                        chosen.append(fix)
                    else:
                        violations.append({"rule": "ENF-07", "message": f"No eligible lever for critical principle {c} in Wave 0."})
        # ENF-10: every wave pays for itself
        if chosen and not any(LEVER_INDEX[l]["ttv_days"] <= 90 for l in chosen):
            quick = next((l for l in cands if LEVER_INDEX[l]["ttv_days"] <= 90 and l not in chosen), None)
            if quick:
                chosen[-1] = quick
            else:
                violations.append({"rule": "ENF-10", "message": f"{w['name']} has no lever with time-to-value of 90 days or less."})
        if len(chosen) > cap:
            violations.append({"rule": "ENF-10", "message": f"{w['name']} exceeds capacity ({len(chosen)} > {cap})."})
        for lid in chosen:
            planned[lid] = wid
            for t, lift in LEVER_INDEX[lid]["targets"].items():
                # diminishing returns: the same lever moves a weak dimension more than a strong one
                proj[t] = min(5.0, proj[t] + lift * (5.0 - proj[t]) / 4.0)
        waves.append({**w, "levers": chosen, "violations": violations,
                      "projected": {k: _r(v) for k, v in proj.items()}})
        for v in violations:
            findings.append({"rule": v["rule"], "severity": "warning", "scope": "roadmap", "ref": w["name"], "message": v["message"]})
    backlog = []
    final_avail = done | set(planned)
    for lid in pending:
        if lid in planned:
            continue
        miss_l, miss_d = eligible(lid, final_avail, proj)
        backlog.append({"id": lid, "blocked_by_levers": miss_l, "blocked_by_dims": miss_d})
    return waves, backlog, planned


def lever_plan_findings(assessment, dims, findings, today):
    status = {}
    for lid, lv in LEVER_INDEX.items():
        st = lever_state(assessment, lid)
        info = {"status": st["status"], "stale": False, "exception_active": exception_active(st, today), "issues": []}
        if st["status"] == "Verified":
            va = _parse_date(st.get("verified_at"))
            if not va or (today - va).days > VERIFY_DAYS:
                info["stale"] = True
                info["issues"].append("verification older than 90 days")
                findings.append({"rule": "ENF-13", "severity": "warning", "scope": "lever", "ref": lid,
                                 "message": f"{lid} {lv['name']}: verification is stale. Re-measure the KPI."})
        if st["status"] in ENFORCED_STATES:
            reg = [r for r in lv["requires"] if lever_state(assessment, r)["status"] not in ENFORCED_STATES]
            if reg:
                info["issues"].append("prerequisite regressed: " + ", ".join(reg))
                findings.append({"rule": "ENF-09", "severity": "warning", "scope": "lever", "ref": lid,
                                 "message": f"{lid} is {st['status']} but prerequisite(s) {', '.join(reg)} are no longer enforced."})
            unmet = {d: m for d, m in lv["preconditions"].items()
                     if (dims[d]["enforced"] or 0) + 1e-9 < m}
            if unmet and not info["exception_active"]:
                ex = st.get("exception") or {}
                msg = ("exception expired" if ex else "preconditions no longer met") + ": " + \
                      ", ".join(f"{d} >= {m}" for d, m in unmet.items())
                info["issues"].append(msg)
                findings.append({"rule": "ENF-13" if ex else "ENF-09", "severity": "blocker" if ex else "warning",
                                 "scope": "lever", "ref": lid, "message": f"{lid} {lv['name']}: {msg}."})
            if lv["mode"] == "directive" and not any(lever_state(assessment, p)["status"] in ENFORCED_STATES for p in lv["pair_with"]):
                info["issues"].append("directive lever without an enforced pair")
        status[lid] = info
    return status


# --------------------------------------------------------------------------- evaluate

SEVERITY_ORDER = {"blocker": 0, "cap": 1, "warning": 2, "info": 3}


def evaluate(assessment, today=None):
    today = _today(today)
    mode = assessment.get("mode", "attested")
    findings = []
    responses = assessment.get("responses", {})
    qscores = {q["id"]: score_question(q, responses.get(q["id"]), mode) for q in QUESTIONS}
    for qs in qscores.values():
        findings.extend(qs.pop("findings"))
    dims = score_dimensions(assessment, qscores, findings)
    tiers = score_tiers(dims, findings)
    velocity = score_velocity(qscores)
    use_cases = score_use_cases(assessment, dims, findings, today)
    pr = prioritise_levers(assessment, dims, tiers, use_cases)
    plan_status = lever_plan_findings(assessment, dims, findings, today)
    waves, backlog, planned = plan_waves(assessment, dims, tiers, pr, findings)
    for lid, p in pr.items():
        p["wave"] = planned.get(lid)
    att_total = sum(1 for q in QUESTIONS if q["kind"] == "attested")
    att_answered = sum(1 for q in QUESTIONS if q["kind"] == "attested" and
                       (qscores[q["id"]]["claimed"] is not None or qscores[q["id"]]["na"]))
    met_total = sum(1 for q in QUESTIONS if q["kind"] == "metric")
    met_answered = sum(1 for q in QUESTIONS if q["kind"] == "metric" and qscores[q["id"]]["claimed"] is not None)
    inflation = [d for d, r in dims.items() if r["claimed"] is not None and r["enforced"] is not None
                 and r["claimed"] - r["enforced"] >= 0.5]
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["rule"]))
    for d in dims.values():
        for k in ("claimed", "evidence_backed", "enforced", "metric_level", "coverage"):
            d[k] = _r(d[k])
        d.pop("critical_floor_backed", None)
    return {
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "framework_version": model.FRAMEWORK_VERSION,
        "mode": mode,
        "progress": {"attested": att_answered, "attested_total": att_total, "metrics": met_answered, "metrics_total": met_total},
        "questions": qscores,
        "dimensions": dims,
        "tiers": tiers,
        "velocity": velocity,
        "use_cases": use_cases,
        "levers": {"priorities": pr, "waves": waves, "backlog": backlog, "plan": plan_status},
        "inflation": inflation,
        "findings": findings,
        "counts": {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER},
    }


# --------------------------------------------------------------------------- lever transitions (ENF-09)

def _kpi_met(direction, current, target):
    try:
        c, t = float(current), float(target)
    except (TypeError, ValueError):
        return False
    return c <= t if direction == "lower_better" else c >= t


def transition_lever(assessment, lever_id, to, fields=None, actor="unknown", today=None):
    """Validate and apply a lever status transition.

    Returns (new_assessment, errors). When errors is non-empty the assessment is unchanged.
    Status can only change through this function; the app rejects status edits elsewhere.
    """
    today = _today(today)
    fields = fields or {}
    lv = LEVER_INDEX.get(lever_id)
    if not lv:
        return assessment, [f"Unknown lever {lever_id}."]
    a = copy.deepcopy(assessment)
    a.setdefault("levers", {})
    st = copy.deepcopy(lever_state(a, lever_id))
    frm = st["status"]
    if to not in model.LEVER_TRANSITIONS.get(frm, []):
        return assessment, [f"{frm} to {to} is not an allowed transition. Allowed: {', '.join(model.LEVER_TRANSITIONS.get(frm, []))}."]
    # merge editable fields supplied with the transition
    for k in ("owner", "wave", "kpi_baseline", "kpi_target", "kpi_current", "notes"):
        if k in fields and fields[k] not in (None,):
            st[k] = fields[k]
    if "enforcement_evidence" in fields:
        st["enforcement_evidence"] = [e for e in (fields["enforcement_evidence"] or []) if str(e).strip()]
    if "exception" in fields and fields["exception"]:
        st["exception"] = fields["exception"]
    reason = (fields.get("reason") or "").strip()
    errors = []
    backward = model.LEVER_STATUSES.index(to) < model.LEVER_STATUSES.index(frm) if to != "Retired" else False

    if to == "Committed" and not backward:
        if not (st.get("owner") or "").strip():
            errors.append("An accountable owner is required to commit.")
        if str(st.get("wave", "")) not in ("0", "1", "2"):
            errors.append("Choose a wave (0, 1 or 2).")
        if st.get("kpi_target") in (None, ""):
            errors.append(f"Set a KPI target for '{lv['kpi']['name']}' ({lv['kpi']['unit']}).")
    if to == "Enforced" and not backward:
        if not st.get("enforcement_evidence"):
            errors.append("Record at least one piece of enforcement evidence, for example: " + "; ".join(lv["evidence"]) + ".")
        if st.get("kpi_baseline") in (None, ""):
            errors.append("Record the KPI baseline before enforcement, so the effect can be verified.")
        reqs = [r for r in lv["requires"] if lever_state(a, r)["status"] not in ENFORCED_STATES]
        if reqs:
            errors.append("Prerequisite lever(s) not yet Enforced: " + ", ".join(f"{r} {LEVER_INDEX[r]['name']}" for r in reqs) + ".")
        if lv["mode"] == "directive" and not any(lever_state(a, p)["status"] in ENFORCED_STATES for p in lv["pair_with"]):
            errors.append("Directive lever: at least one paired detective/preventive lever must be Enforced first ("
                          + ", ".join(lv["pair_with"]) + "). A standard without a mechanism is a suggestion (A3).")
        if lv["preconditions"]:
            res = evaluate(a, today)
            unmet = {d: m for d, m in lv["preconditions"].items()
                     if (res["dimensions"][d]["enforced"] or 0) + 1e-9 < m}
            if unmet:
                ex = st.get("exception") or {}
                exp = _parse_date(ex.get("expires"))
                if ex:
                    if not (ex.get("approver") and ex.get("justification")):
                        errors.append("Exception needs an approver and a justification.")
                    elif not exp or exp < today:
                        errors.append("Exception expiry must be a future date.")
                    elif exp > today + timedelta(days=MAX_EXCEPTION_DAYS):
                        errors.append(f"Exception expiry may be at most {MAX_EXCEPTION_DAYS} days away.")
                else:
                    errors.append("Precondition level(s) not met: " + ", ".join(
                        f"{d} is {res['dimensions'][d]['enforced'] or 'unassessed'}, needs {m}" for d, m in unmet.items())
                        + ". Raise them first or record a time-bound exception.")
    if to == "Verified":
        if st.get("kpi_current") in (None, ""):
            errors.append("Record the current KPI value to verify.")
        elif not _kpi_met(lv["kpi"]["direction"], st.get("kpi_current"), st.get("kpi_target")):
            errors.append(f"KPI not at target: current {st.get('kpi_current')} vs target {st.get('kpi_target')} "
                          f"({'lower' if lv['kpi']['direction'] == 'lower_better' else 'higher'} is better).")
        st["verified_at"] = today.isoformat()
    if (to == "Retired" or backward) and not reason:
        errors.append("A reason is required to retire a lever or move it backwards.")
    if errors:
        return assessment, errors
    st["status"] = to
    st.setdefault("history", []).append({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                         "actor": actor, "from": frm, "to": to, "reason": reason})
    a["levers"][lever_id] = st
    return a, []


def protect_lever_status(incoming, stored):
    """Status and history are only changed by transition_lever; ignore client edits to them."""
    out = copy.deepcopy(incoming)
    out.setdefault("levers", {})
    stored_levers = (stored or {}).get("levers", {})
    for lid in set(out["levers"]) | set(stored_levers):
        prev = stored_levers.get(lid, {})
        cur = out["levers"].setdefault(lid, {})
        cur["status"] = prev.get("status", "Proposed")
        cur["history"] = prev.get("history", [])
        if "verified_at" in prev:
            cur["verified_at"] = prev["verified_at"]
        else:
            cur.pop("verified_at", None)
    return out
