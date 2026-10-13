from . import model
from .levers import LEVER_INDEX, LEVERS, PLATFORMS
from .questions import QUESTION_INDEX, QUESTIONS, ROLES, metric_level


def get_framework():
    """Full framework as a JSON-serialisable document (served to the UI and exportable)."""
    return {
        "version": model.FRAMEWORK_VERSION,
        "axioms": model.AXIOMS,
        "levels": model.LEVELS,
        "weights": model.WEIGHTS,
        "tiers": model.TIERS,
        "dimensions": model.DIMENSIONS,
        "velocity": model.VELOCITY,
        "dependencies": model.DEPENDENCIES,
        "jobs": model.JOBS,
        "job_lever_gates": model.JOB_LEVER_GATES,
        "flywheel": model.FLYWHEEL,
        "evidence_types": model.EVIDENCE_TYPES,
        "lever_statuses": model.LEVER_STATUSES,
        "lever_transitions": model.LEVER_TRANSITIONS,
        "enforcement_modes": model.ENFORCEMENT_MODES,
        "rules": model.RULES,
        "modes": model.ASSESSMENT_MODES,
        "waves": model.WAVES,
        "roles": ROLES,
        "questions": QUESTIONS,
        "levers": LEVERS,
        "platforms": PLATFORMS,
    }


def validate_framework():
    """Referential integrity checks. Returns a list of problems (empty when consistent)."""
    problems = []
    dims = set(model.DIM_INDEX)
    seen = set()
    for q in QUESTIONS:
        if q["id"] in seen:
            problems.append(f"duplicate question id {q['id']}")
        seen.add(q["id"])
        if q["dim"] not in dims:
            problems.append(f"{q['id']}: unknown dim {q['dim']}")
        if q["weight"] not in model.WEIGHTS:
            problems.append(f"{q['id']}: unknown weight {q['weight']}")
        if q.get("velocity") and q["velocity"] not in {v["id"] for v in model.VELOCITY}:
            problems.append(f"{q['id']}: unknown velocity {q['velocity']}")
        for r in q.get("roles", []):
            if r not in ROLES:
                problems.append(f"{q['id']}: unknown role {r}")
        for j in q.get("jobs", []):
            if j not in model.JOBS:
                problems.append(f"{q['id']}: unknown job {j}")
        if q["kind"] == "metric":
            b = q["bands"]
            asc = all(b[i] < b[i + 1] for i in range(3))
            desc = all(b[i] > b[i + 1] for i in range(3))
            if q["direction"] == "higher_better" and not asc:
                problems.append(f"{q['id']}: higher_better bands must ascend")
            if q["direction"] == "lower_better" and not desc:
                problems.append(f"{q['id']}: lower_better bands must descend")
    for d in dims:
        if not any(q["dim"] == d and q["kind"] == "attested" for q in QUESTIONS):
            problems.append(f"dimension {d} has no attested questions")
    lids = set(LEVER_INDEX)
    if len(lids) != len(LEVERS):
        problems.append("duplicate lever ids")
    for lv in LEVERS:
        for t in list(lv["targets"]) + list(lv["preconditions"]):
            if t not in dims:
                problems.append(f"{lv['id']}: unknown dim {t}")
        for r in lv["requires"] + lv["pair_with"]:
            if r not in lids:
                problems.append(f"{lv['id']}: unknown lever {r}")
        if lv["mode"] not in model.ENFORCEMENT_MODES:
            problems.append(f"{lv['id']}: unknown mode {lv['mode']}")
        if lv["mode"] == "directive" and not lv["pair_with"]:
            problems.append(f"{lv['id']}: directive lever needs pair_with")
        for p in PLATFORMS:
            if p not in lv["impl"]:
                problems.append(f"{lv['id']}: missing impl for {p}")
    for job, gate in model.JOB_LEVER_GATES.items():
        for g in gate:
            if g not in lids:
                problems.append(f"job gate {job}: unknown lever {g}")
    for d in dims:
        if not any(d in lv["targets"] for lv in LEVERS):
            problems.append(f"dimension {d} has no lever")
    # requires graph must be acyclic
    state = {}

    def visit(n, stack):
        if state.get(n) == 1:
            problems.append(f"lever dependency cycle: {' -> '.join(stack + [n])}")
            return
        if state.get(n) == 2:
            return
        state[n] = 1
        for r in LEVER_INDEX[n]["requires"]:
            visit(r, stack + [n])
        state[n] = 2

    for n in lids:
        visit(n, [])
    return problems
