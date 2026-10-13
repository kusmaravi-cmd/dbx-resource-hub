"""One-command deploy of DataPulse to a Databricks workspace (Databricks on AWS, Azure or GCP).

    pip install databricks-sdk
    databricks auth login --host https://<workspace>.cloud.databricks.com   # or set DATABRICKS_HOST + DATABRICKS_TOKEN
    python scripts/deploy.py --warehouse-id <id> [--catalog main] [--schema datapulse] [--app-name datapulse]

What it does:
  1. Uploads the app source to /Workspace/Users/<you>/apps/<app-name>
  2. Creates the app (if new) with the SQL warehouse attached as resource "sql-warehouse"
  3. Creates the schema and grants the app's service principal access to it (needs catalog privileges;
     if you lack them it prints the SQL for an admin)
  4. Deploys and starts the app, then prints its URL
"""

import argparse
import io
import re
import sys
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service import apps
from databricks.sdk.service.workspace import ImportFormat

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["app.py", "app.yaml", "requirements.txt", "server", "static"]
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def upload_tree(w, dest):
    w.workspace.mkdirs(dest)
    n = 0
    for item in INCLUDE:
        src = ROOT / item
        files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if rel == "app.yaml":
                continue  # written below with the chosen catalog/schema
            target = f"{dest}/{rel}"
            w.workspace.mkdirs(target.rsplit("/", 1)[0])
            w.workspace.upload(target, io.BytesIO(f.read_bytes()), format=ImportFormat.RAW, overwrite=True)
            n += 1
    return n


def app_yaml(catalog, schema):
    return (f'command: ["python", "app.py"]\nenv:\n  - name: DATAPULSE_WAREHOUSE_ID\n    valueFrom: sql-warehouse\n'
            f'  - name: DATAPULSE_CATALOG\n    value: "{catalog}"\n  - name: DATAPULSE_SCHEMA\n    value: "{schema}"\n')


def run_sql(w, warehouse_id, sql):
    r = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=sql, wait_timeout="50s")
    state = r.status.state.value if r.status and r.status.state else "UNKNOWN"
    if state != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status and r.status.error else state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse-id", required=True)
    ap.add_argument("--catalog", default="main")
    ap.add_argument("--schema", default="datapulse")
    ap.add_argument("--app-name", default="datapulse")
    ap.add_argument("--profile", default=None, help="Databricks CLI profile (optional)")
    a = ap.parse_args()
    for ident in (a.catalog, a.schema):
        if not IDENT.match(ident):
            sys.exit(f"invalid identifier: {ident}")

    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    me = w.current_user.me().user_name
    print(f"Workspace: {w.config.host} as {me}")
    w.warehouses.get(a.warehouse_id)  # fail fast if the warehouse is wrong or not accessible

    dest = f"/Workspace/Users/{me}/apps/{a.app_name}"
    n = upload_tree(w, dest)
    w.workspace.upload(f"{dest}/app.yaml", io.BytesIO(app_yaml(a.catalog, a.schema).encode()), format=ImportFormat.RAW, overwrite=True)
    print(f"Uploaded {n + 1} files to {dest}")

    resource = apps.AppResource(name="sql-warehouse", description="Warehouse for DataPulse Unity Catalog tables",
                                sql_warehouse=apps.AppResourceSqlWarehouse(
                                    id=a.warehouse_id, permission=apps.AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE))
    try:
        app = w.apps.get(a.app_name)
        print(f"App '{a.app_name}' exists; updating resources")
        app = w.apps.update(a.app_name, app=apps.App(name=a.app_name, description=app.description, resources=[resource]))
    except NotFound:
        print(f"Creating app '{a.app_name}' (provisions compute, takes a few minutes)")
        app = w.apps.create_and_wait(app=apps.App(
            name=a.app_name, resources=[resource],
            description="Everforth DataPulse: platform-agnostic data & AI readiness assessment with enforced levers."))

    sp = app.service_principal_client_id
    grants = [f"CREATE SCHEMA IF NOT EXISTS `{a.catalog}`.`{a.schema}` COMMENT 'DataPulse assessment data'",
              f"GRANT USE CATALOG ON CATALOG `{a.catalog}` TO `{sp}`",
              f"GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA `{a.catalog}`.`{a.schema}` TO `{sp}`"]
    try:
        for g in grants:
            run_sql(w, a.warehouse_id, g)
        print(f"Granted the app's service principal ({sp}) access to {a.catalog}.{a.schema}")
    except Exception as e:
        print(f"\nCould not apply grants ({e}). Ask a catalog owner to run:\n  " + ";\n  ".join(grants) + ";\n")

    print("Deploying…")
    dep = w.apps.deploy_and_wait(app_name=a.app_name, app_deployment=apps.AppDeployment(
        source_code_path=dest, mode=apps.AppDeploymentMode.SNAPSHOT))
    print(f"Deployment {dep.deployment_id}: {dep.status.state.value if dep.status else 'unknown'}")
    app = w.apps.get(a.app_name)
    if app.compute_status and app.compute_status.state and app.compute_status.state.value != "ACTIVE":
        app = w.apps.start_and_wait(a.app_name)
    print(f"\nDataPulse is live: {app.url}")
    print("Give colleagues access under Compute > Apps > " + a.app_name + " > Permissions (CAN USE).")


if __name__ == "__main__":
    main()
