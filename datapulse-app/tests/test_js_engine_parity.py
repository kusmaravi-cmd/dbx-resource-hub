"""The browser edition's JS engine must agree with the Python engine. Skipped when node is absent."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from server import engine
from server.framework import LEVERS, QUESTIONS, get_framework

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
TODAY = "2026-10-13"


def random_assessment(seed):
    rnd = random.Random(seed)
    a = engine.new_assessment("r", "o", rnd.choice(["attested", "validated"]))
    a["target_level"] = rnd.choice([3.0, 3.5, 4.0])
    a["wave_capacity"] = rnd.choice([4, 6, 8])
    types = ["attestation", "document", "artifact", "metric", "inspection"]
    for q in QUESTIONS:
        if rnd.random() < 0.15:
            continue
        if q["kind"] == "metric":
            a["responses"][q["id"]] = {"value": rnd.choice([q["bands"][0] * 1.5, q["bands"][1], q["bands"][2], q["bands"][3] * 0.5])}
        else:
            ev = [{"type": rnd.choice(types), "ref": "x"} for _ in range(rnd.randint(0, 2))]
            a["responses"][q["id"]] = {"level": rnd.randint(1, 5), "evidence": ev, "na": rnd.random() < 0.05,
                                       "confidence": rnd.choice(["low", "medium", "high"])}
    a["use_cases"] = [{"id": f"u{i}", "name": f"uc{i}", "job": rnd.choice(["Inference", "Training", "Agent", ""])} for i in range(3)]
    for lv in rnd.sample(LEVERS, 6):
        a["levers"][lv["id"]] = {"status": rnd.choice(["Committed", "Enforced", "Verified", "Retired"]), "wave": rnd.choice(["0", "1", "2"]),
                                 "verified_at": rnd.choice(["2026-01-01", "2026-09-30"])}
    return a


def summary(r):
    return {
        "dims": {k: [v["claimed"], v["evidence_backed"], v["enforced"], v["provisional"]] for k, v in r["dimensions"].items()},
        "tiers": [r["tiers"]["T1"]["ceiling"], r["tiers"]["T1"]["binding"], r["tiers"]["T2"]["score"], r["tiers"]["T2"]["flywheel"], r["tiers"]["T3"]["critical"]],
        "ucs": [[u["status"], u.get("readiness"), u.get("gate_missing")] for u in r["use_cases"]],
        "waves": [w["levers"] for w in r["levers"]["waves"]],
        "rules": sorted(f["rule"] + f["severity"] for f in r["findings"]),
    }


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_js_engine_matches_python(tmp_path):
    cases = [random_assessment(s) for s in range(40)]
    (tmp_path / "fw.json").write_text(json.dumps(get_framework()))
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    script = f"""
const E = require({json.dumps(str(ROOT / 'artifact' / 'engine.js'))});
const fs = require('fs');
E.init(JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'fw.json'))})));
const cases = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'cases.json'))}));
console.log(JSON.stringify(cases.map(c => E.evaluate(c, '{TODAY}'))));
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    for i, (case, jr) in enumerate(zip(cases, js)):
        py, j = summary(engine.evaluate(case, TODAY)), summary(jr)
        for k in py["dims"]:
            for a, b in zip(py["dims"][k], j["dims"][k]):
                assert (a is None and b is None) or a == b or abs(a - b) <= 0.011, (i, k, py["dims"][k], j["dims"][k])
        assert py["tiers"][1:] == j["tiers"][1:] or abs((py["tiers"][2] or 0) - (j["tiers"][2] or 0)) <= 0.011, (i, py["tiers"], j["tiers"])
        for a, b in zip(py["ucs"], j["ucs"]):
            assert a[0] == b[0] and a[2] == b[2], (i, a, b)
            assert (a[1] is None and b[1] is None) or abs(a[1] - b[1]) <= 0.011, (i, a, b)
        assert py["waves"] == j["waves"], (i, py["waves"], j["waves"])
        assert py["rules"] == j["rules"], i
