"""Deploy the Hub Concierge to a Databricks (AWS) workspace as a Databricks App.

Follows the DIVA skill's deployment.md, end to end and idempotent:
  stage -> secret scope + secrets -> app -> secret resources -> SP grants -> sync --full -> start -> deploy

    python scripts/deploy.py --profile aws                  # PAT mode (DIVA's tested path)
    python scripts/deploy.py --profile aws --auth sp        # run as the app's service principal
    python scripts/deploy.py --profile aws --dry-run        # print the plan, change nothing

Secret values are read from the env file (default .env.local) and never printed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.catalog import load_catalog, write_compact  # noqa: E402

# (env var, scope key, app resource name)
SECRETS = [
    ("LIVEKIT_URL", "livekit_url", "livekit-url"),
    ("LIVEKIT_API_KEY", "livekit_api_key", "livekit-api-key"),
    ("LIVEKIT_API_SECRET", "livekit_api_secret", "livekit-api-secret"),
    ("DEEPGRAM_API_KEY", "deepgram_api_key", "deepgram-api-key"),
    ("DATABRICKS_TOKEN", "databricks_token", "databricks-token"),  # PAT mode only
]
# Non-secret settings copied from the env file into the staged app.yaml when set there.
PASSTHROUGH = ["HUB_LLM_MODEL", "HUB_LLM_REASONING_EFFORT", "HUB_EMBED_MODEL", "HUB_EMBED_DIM", "HUB_STT_MODEL",
               "HUB_TTS_VOICE", "LAKEBASE_ENDPOINT", "LAKEBASE_DATABASE", "HUB_SCHEMA", "HUB_TRACE_CATALOG",
               "HUB_TRACE_SCHEMA", "HUB_TRACE_TABLE_PREFIX", "AGENT_NAME"]
STAGE_ITEMS = ["app", "hub", "start_app.py", "requirements.txt", "agent-requirements.txt"]


def read_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m:
                env[m.group(1)] = re.sub(r"^(['\"])(.*)\1$", r"\2", m.group(2))
    return env


def render_app_yaml(template: str, env: dict[str, str], auth: str) -> str:
    """Fill `value:` entries from env; drop the PAT entry in SP mode, LAKEBASE_ENDPOINT when unset, and any
    entry whose value would be blank."""
    lines, out, skip_next = template.splitlines(), [], False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        m = re.match(r"^(\s*)- name: ([A-Z_0-9]+)\s*$", line)
        if m:
            name, nxt = m.group(2), lines[i + 1] if i + 1 < len(lines) else ""
            if name == "DATABRICKS_TOKEN" and auth == "sp":
                skip_next = True
                continue
            if name == "LAKEBASE_ENDPOINT" and not env.get(name, "").strip() and "REPLACE_" in nxt:
                skip_next = True
                continue
            if not env.get(name, "").strip() and re.match(r'^\s*value:\s*""\s*$', nxt):
                skip_next = True  # blank values are undocumented in app.yaml: leave the entry out
                continue
            if name in env and env[name].strip() and "value:" in nxt and "valueFrom" not in nxt:
                indent = re.match(r"^(\s*)", nxt).group(1)
                out.append(line)
                out.append(f'{indent}value: {json.dumps(env[name].strip())}')
                skip_next = True
                continue
        out.append(line)
    return "\n".join(out) + "\n"


def check_requirements() -> None:
    reqs = (ROOT / "agent-requirements.txt").read_text()
    m = re.search(r"^numpy==(\d+)\.(\d+)", reqs, re.M)
    if m and (int(m.group(1)), int(m.group(2))) >= (2, 5):
        sys.exit("agent-requirements.txt pins numpy>=2.5 (needs Python 3.12); Apps run 3.11. Recompile:\n"
                 "  uv pip compile agent-requirements.in --python-version 3.11 --python-platform linux "
                 "-o agent-requirements.txt")


def stage(env: dict[str, str], auth: str, catalog: Path) -> Path:
    out = ROOT / ".stage"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for item in STAGE_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(src, out / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, out / item)
    (out / "app.yaml").write_text(render_app_yaml((ROOT / "app.yaml").read_text(), env, auth))
    resources = load_catalog(catalog)
    write_compact(resources, out / "catalog.json")
    print(f"[stage] {out} ({len(resources)} catalog entries, auth={auth})")
    return out


class CLI:
    def __init__(self, profile: str, dry: bool):
        self.profile, self.dry = profile, dry

    def run(self, *args: str, check: bool = True, secret: bool = False, capture: bool = True):
        cmd = ["databricks", *args, "--profile", self.profile]
        shown = " ".join("****" if secret and i > 0 and cmd[i - 1] == "--string-value" else a
                         for i, a in enumerate(cmd))
        print(f"$ {shown}")
        if self.dry:
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        res = subprocess.run(cmd, capture_output=capture, text=True)
        if check and res.returncode != 0:
            sys.exit(f"command failed ({res.returncode}): {(res.stderr or res.stdout or '').strip()[-800:]}")
        return res

    def json(self, *args: str) -> dict:
        res = self.run(*args, "-o", "json")
        return json.loads(res.stdout or "{}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="Databricks CLI profile for the AWS workspace")
    ap.add_argument("--app", default="hub-concierge")
    ap.add_argument("--scope", default="hub-concierge")
    ap.add_argument("--auth", choices=["pat", "sp"], default="pat")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    ap.add_argument("--catalog", type=Path, default=ROOT.parent / "search.json")
    ap.add_argument("--skip-secrets", action="store_true", help="secrets already in the scope")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    check_requirements()
    env = read_env(a.env_file)
    secrets = [s for s in SECRETS if a.auth == "pat" or s[0] != "DATABRICKS_TOKEN"]
    missing = [name for name, _, _ in secrets if not env.get(name)]
    if missing and not a.skip_secrets:
        sys.exit(f"missing in {a.env_file}: {', '.join(missing)} (or pass --skip-secrets)")
    staged = stage(env, a.auth, a.catalog)
    cli = CLI(a.profile, a.dry_run)

    me = cli.json("current-user", "me").get("userName", "me")
    wsp = f"/Workspace/Users/{me}/databricks_apps/{a.app}"

    # 1. secret scope + secrets
    if not a.skip_secrets:
        scopes = cli.run("secrets", "list-scopes", "-o", "json").stdout or "[]"
        if a.scope not in scopes:
            cli.run("secrets", "create-scope", a.scope)
        for name, key, _ in secrets:
            cli.run("secrets", "put-secret", a.scope, key, "--string-value", env[name], secret=True)

    # 2. the app (creating it also creates its service principal and compute)
    if cli.run("apps", "get", a.app, check=False).returncode != 0:
        cli.run("apps", "create", a.app, "--description",
                "Hub Concierge: voice guide to the Databricks Resource Hub", capture=False)

    # 3. secret resources -- attached BEFORE the first deploy (valueFrom only resolves once they exist)
    resources = [{"name": res, "secret": {"scope": a.scope, "key": key, "permission": "READ"}}
                 for _, key, res in secrets]
    cli.run("apps", "update", a.app, "--json", json.dumps({"name": a.app, "resources": resources}))

    # 4. grants for the app's service principal (the CLI, unlike the UI, does not add them)
    sp = cli.json("apps", "get", a.app).get("service_principal_client_id", "<sp-client-id>")
    cli.run("secrets", "put-acl", a.scope, sp, "READ")
    cli.run("workspace", "mkdirs", wsp)
    oid = cli.json("workspace", "get-status", wsp).get("object_id", "<object-id>")
    cli.run("permissions", "update", "directories", str(oid), "--json", json.dumps(
        {"access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_MANAGE"}]}))

    # 5. compute up, upload (sync --full, never import-dir), deploy
    cli.run("apps", "start", a.app, check=False, capture=False)
    cli.run("sync", str(staged), wsp, "--full", capture=False)
    cli.run("apps", "deploy", a.app, "--source-code-path", wsp, capture=False)

    url = cli.json("apps", "get", a.app).get("url", "<app url>")
    print(f"\nDeployed {a.app}: {url}\n"
          f"Watch the worker come up (30-60 s after deploy):\n"
          f"  databricks apps logs {a.app} --tail-lines 100 --profile {a.profile}\n"
          f"Look for '[web] Hub Concierge listening' then 'registered worker'.")
    if a.auth == "sp":
        print(f"\nSP mode: the app runs as service principal {sp}. Grant it query access to the gateway models "
              f"and a Lakebase role (infra/grant_sp.sql) before the first call.")


if __name__ == "__main__":
    main()
