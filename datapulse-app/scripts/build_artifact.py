"""Build the browser-only edition (single self-contained HTML page) published on claude.ai.

    python scripts/build_artifact.py  ->  artifact/dist/DataPulse.html
"""

import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.seed_demo import fill_demo  # noqa: E402
from server import engine  # noqa: E402
from server.framework import get_framework  # noqa: E402

STATIC, ART = ROOT / "static", ROOT / "artifact"


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def safe_json(obj):
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def demo_seed():
    doc = engine.new_assessment("Phase 0 discovery", "Northwind Health (demo)", "attested", 3.0, "databricks")
    fill_demo(doc)
    history = []
    for to, fields in (("Committed", {"owner": "Head of Data Engineering", "wave": "0", "kpi_target": 100}),
                       ("Enforced", {"enforcement_evidence": ["Harvester runs for lake, warehouse and BI"], "kpi_baseline": 40})):
        doc, errors = engine.transition_lever(doc, "L-02", to, fields, actor="Everforth demo")
        assert not errors, errors
        history.append({"event_ts": doc["levers"]["L-02"]["history"][-1]["ts"], "actor": "Everforth demo",
                        "action": "lever_transition", "detail": {"lever": "L-02", "to": to}})
    return {"doc": doc, "history": history}


def main():
    css = (STATIC / "styles.css").read_text()
    html = (STATIC / "index.html").read_text()
    body = html[html.index('<div class="app">'):html.index('<script src="/static/app.js">')]
    lockup = data_uri(STATIC / "everforth-apex-lockup.svg", "image/svg+xml")
    logo = data_uri(STATIC / "everforth-logo.png", "image/png")
    body = body.replace("/static/everforth-apex-lockup.svg", lockup).replace("/static/everforth-logo.png", logo)
    body = body.replace("Confidential · client assessment data", "Browser edition · data stays in this browser")
    scripts = [
        "window.DP_ARTIFACT=true;window.DP_MEMORY_ROUTER=true;",
        f"window.DP_FRAMEWORK={safe_json(get_framework())};",
        f"window.DP_SEED={safe_json(demo_seed())};",
        (ART / "engine.js").read_text(),
        (ART / "api-shim.js").read_text(),
        (STATIC / "app.js").read_text(),
    ]
    for s in scripts:
        assert "</script" not in s.lower(), "script would terminate early"
    page = ("<title>Everforth DataPulse</title>\n"
            '<meta name="description" content="Everforth DataPulse: platform-agnostic data & AI readiness assessment with enforced levers.">\n'
            f"<style>\n{css}\nhtml,body{{background:var(--bg)}}\n</style>\n{body}\n"
            + "\n".join(f"<script>\n{s}\n</script>" for s in scripts) + "\n")
    out = ART / "dist" / "DataPulse.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    print(f"wrote {out} ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
