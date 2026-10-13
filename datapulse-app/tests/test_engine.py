import pytest

from server import engine
from server.framework import LEVERS, QUESTIONS, validate_framework

TODAY = "2026-10-13"


def answer_all(level, evidence=None, mode="attested"):
    a = engine.new_assessment("t", "o", mode)
    for q in QUESTIONS:
        if q["kind"] == "attested":
            a["responses"][q["id"]] = {"level": level, "evidence": evidence or []}
    return a


def test_framework_is_consistent():
    assert validate_framework() == []


def test_every_question_has_five_anchors_and_metrics_have_bands():
    for q in QUESTIONS:
        if q["kind"] == "attested":
            assert len(q["levels"]) == 5 and q["intent"]
        else:
            assert len(q["bands"]) == 4


def test_evidence_gate_caps_only_in_validated_mode():
    att = engine.evaluate(answer_all(4), TODAY)
    val = engine.evaluate(answer_all(4, mode="validated"), TODAY)
    assert att["dimensions"]["R1"]["claimed"] == 4
    assert att["dimensions"]["R1"]["enforced"] == 4  # attested: warn only
    assert att["dimensions"]["R1"]["evidence_backed"] == 2
    assert val["dimensions"]["R1"]["enforced"] == 2
    assert any(f["rule"] == "ENF-01" and f["severity"] == "cap" for f in val["findings"])


def test_level_four_needs_operating_evidence():
    doc = answer_all(4, [{"type": "document", "ref": "policy.pdf"}], mode="validated")
    r = engine.evaluate(doc, TODAY)
    assert r["dimensions"]["R1"]["enforced"] == 3
    doc = answer_all(4, [{"type": "metric", "ref": "coverage export"}], mode="validated")
    assert engine.evaluate(doc, TODAY)["dimensions"]["R1"]["enforced"] == 4


def test_level_five_needs_two_pieces_of_evidence():
    one = answer_all(5, [{"type": "metric", "ref": "a"}], mode="validated")
    two = answer_all(5, [{"type": "metric", "ref": "a"}, {"type": "inspection", "ref": "b"}], mode="validated")
    assert engine.evaluate(one, TODAY)["dimensions"]["R1"]["enforced"] == 4
    assert engine.evaluate(two, TODAY)["dimensions"]["R1"]["enforced"] == 5


def test_evidence_without_reference_does_not_count():
    doc = answer_all(3, [{"type": "metric", "ref": "  "}], mode="validated")
    assert engine.evaluate(doc, TODAY)["dimensions"]["R1"]["enforced"] == 2


def test_metric_triangulation_caps_dimension():
    doc = answer_all(4)
    doc["responses"]["M-INT-1"] = {"value": 120}  # > 90 days onboarding => level 1
    r = engine.evaluate(doc, TODAY)
    assert r["dimensions"]["R5"]["metric_level"] == 1
    assert r["dimensions"]["R5"]["enforced"] == 2
    assert any(c["rule"] == "ENF-03" for c in r["dimensions"]["R5"]["caps"])


def test_critical_question_at_one_caps_dimension():
    doc = answer_all(4)
    doc["responses"]["R4.1"]["level"] = 1
    r = engine.evaluate(doc, TODAY)
    assert r["dimensions"]["R4"]["enforced"] == 2
    assert any(f["rule"] == "ENF-04" and f["severity"] == "blocker" for f in r["findings"])


def test_dependency_precedence_and_readiness_ceiling():
    doc = answer_all(4)
    for q in ("R1.1", "R1.2", "R1.3"):
        doc["responses"][q]["level"] = 2
    r = engine.evaluate(doc, TODAY)
    assert r["dimensions"]["R2"]["enforced"] == 3  # R1 + 1
    assert r["dimensions"]["R7"]["enforced"] == 2  # min(R1..R4) + 0
    assert r["dimensions"]["D1"]["enforced"] == 3
    assert r["tiers"]["T1"]["ceiling"] == 2 and r["tiers"]["T1"]["binding"] == ["R1"]


def test_metric_level_bands():
    from server.framework import QUESTION_INDEX, metric_level
    q = QUESTION_INDEX["M-INT-1"]  # lower is better: 90/30/10/2
    assert [metric_level(q, v) for v in (100, 45, 20, 5, 1)] == [1, 2, 3, 4, 5]
    q = QUESTION_INDEX["M-GOV-2"]  # higher is better: 10/50/80/95
    assert [metric_level(q, v) for v in (5, 20, 60, 90, 99)] == [1, 2, 3, 4, 5]
    assert metric_level(q, "") is None


def test_coverage_makes_dimension_provisional():
    doc = engine.new_assessment()
    doc["responses"]["R4.1"] = {"level": 3}
    r = engine.evaluate(doc, TODAY)
    assert r["dimensions"]["R4"]["provisional"]
    assert "R4" in r["tiers"]["T1"]["missing"]


def test_agent_use_case_blocked_until_levers_enforced():
    doc = answer_all(4, [{"type": "metric", "ref": "x"}])
    doc["use_cases"] = [{"name": "agent", "job": "Agent"}]
    r = engine.evaluate(doc, TODAY)
    uc = r["use_cases"][0]
    assert uc["status"] == "Blocked" and set(uc["gate_missing"]) == {"L-20", "L-21", "L-22"}
    for lid in ("L-20", "L-21", "L-22"):
        doc["levers"][lid] = {"status": "Enforced"}
    assert engine.evaluate(doc, TODAY)["use_cases"][0]["status"] == "Go"


def test_execution_critical_flag_forces_wave_zero_lever():
    doc = answer_all(3)
    for q in QUESTIONS:
        if q["dim"] == "P7" and q["kind"] == "attested":
            doc["responses"][q["id"]]["level"] = 1
    r = engine.evaluate(doc, TODAY)
    assert "P7" in r["tiers"]["T3"]["critical"]
    w0 = r["levers"]["waves"][0]["levers"]
    assert any("P7" in next(l for l in LEVERS if l["id"] == lid)["targets"] for lid in w0)


def test_waves_respect_prerequisites_and_payback():
    r = engine.evaluate(answer_all(2), TODAY)
    index = {l["id"]: l for l in LEVERS}
    placed = {}
    for w in r["levers"]["waves"]:
        assert any(index[l]["ttv_days"] <= 90 for l in w["levers"])
        assert len(w["levers"]) <= 6
        for lid in w["levers"]:
            for req in index[lid]["requires"]:
                assert req in placed and placed[req] < w["id"], f"{lid} before {req}"
            placed[lid] = w["id"]


def test_lever_lifecycle_is_enforced():
    doc = answer_all(2)
    _, errs = engine.transition_lever(doc, "L-02", "Enforced", {}, today=TODAY)
    assert errs and "not an allowed transition" in errs[0]
    _, errs = engine.transition_lever(doc, "L-02", "Committed", {}, today=TODAY)
    assert len(errs) == 3
    doc, errs = engine.transition_lever(doc, "L-02", "Committed", {"owner": "a", "wave": 0, "kpi_target": 90}, today=TODAY)
    assert not errs
    _, errs = engine.transition_lever(doc, "L-02", "Enforced", {}, today=TODAY)
    assert any("enforcement evidence" in e for e in errs) and any("baseline" in e for e in errs)
    doc, errs = engine.transition_lever(doc, "L-02", "Enforced", {"enforcement_evidence": ["runs"], "kpi_baseline": 20}, today=TODAY)
    assert not errs
    _, errs = engine.transition_lever(doc, "L-02", "Verified", {"kpi_current": 80}, today=TODAY)
    assert any("not at target" in e for e in errs)
    doc, errs = engine.transition_lever(doc, "L-02", "Verified", {"kpi_current": 95}, today=TODAY)
    assert not errs and doc["levers"]["L-02"]["verified_at"] == TODAY
    _, errs = engine.transition_lever(doc, "L-02", "Enforced", {}, today=TODAY)
    assert any("reason" in e for e in errs)


def test_lower_better_kpi_verification():
    doc = engine.new_assessment()
    doc["levers"]["L-13"] = {"status": "Enforced", "kpi_target": 5}
    _, errs = engine.transition_lever(doc, "L-13", "Verified", {"kpi_current": 6}, today=TODAY)
    assert errs
    doc["levers"]["L-12"] = {"status": "Enforced", "kpi_target": 3}
    _, errs = engine.transition_lever(doc, "L-12", "Verified", {"kpi_current": 2}, today=TODAY)
    assert not errs


def test_prerequisites_preconditions_and_exceptions():
    doc = answer_all(2)
    commit = {"owner": "a", "wave": 1, "kpi_target": 100}
    doc, _ = engine.transition_lever(doc, "L-20", "Committed", commit, today=TODAY)
    _, errs = engine.transition_lever(doc, "L-20", "Enforced", {"enforcement_evidence": ["x"], "kpi_baseline": 0}, today=TODAY)
    assert any("Prerequisite" in e for e in errs) and any("Precondition" in e for e in errs)
    doc["levers"]["L-12"] = {"status": "Enforced"}
    doc["levers"]["L-14"] = {"status": "Enforced"}
    bad = {"approver": "CISO", "justification": "pilot", "expires": "2027-12-31"}
    _, errs = engine.transition_lever(doc, "L-20", "Enforced", {"enforcement_evidence": ["x"], "kpi_baseline": 0, "exception": bad}, today=TODAY)
    assert any("180 days" in e for e in errs)
    ok = {**bad, "expires": "2027-01-31"}
    doc, errs = engine.transition_lever(doc, "L-20", "Enforced", {"enforcement_evidence": ["x"], "kpi_baseline": 0, "exception": ok}, today=TODAY)
    assert not errs
    # after the exception expires the lever is flagged as a blocker
    r = engine.evaluate(doc, "2027-02-15")
    assert any(f["rule"] == "ENF-13" and f["ref"] == "L-20" and f["severity"] == "blocker" for f in r["findings"])


def test_directive_lever_needs_enforced_pair():
    doc = engine.new_assessment()
    doc["levers"]["L-03"] = {"status": "Committed", "owner": "a", "wave": 0, "kpi_target": 90}
    _, errs = engine.transition_lever(doc, "L-03", "Enforced", {"enforcement_evidence": ["raci"], "kpi_baseline": 10}, today=TODAY)
    assert any("Directive" in e for e in errs)


def test_stale_verification_flagged():
    doc = engine.new_assessment()
    doc["levers"]["L-02"] = {"status": "Verified", "verified_at": "2026-01-01"}
    r = engine.evaluate(doc, TODAY)
    assert r["levers"]["plan"]["L-02"]["stale"]


def test_client_cannot_change_lever_status():
    stored = engine.new_assessment()
    stored["levers"]["L-02"] = {"status": "Committed", "history": [{"to": "Committed"}]}
    incoming = {**stored, "levers": {"L-02": {"status": "Verified", "owner": "x"}, "L-20": {"status": "Enforced"}}}
    out = engine.protect_lever_status(incoming, stored)
    assert out["levers"]["L-02"]["status"] == "Committed" and out["levers"]["L-02"]["owner"] == "x"
    assert out["levers"]["L-20"]["status"] == "Proposed"


@pytest.mark.parametrize("mode", ["attested", "validated"])
def test_empty_assessment_evaluates(mode):
    r = engine.evaluate(engine.new_assessment(mode=mode), TODAY)
    assert r["tiers"]["T1"]["ceiling"] is None and r["progress"]["attested"] == 0
