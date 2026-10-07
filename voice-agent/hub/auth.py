"""One place that turns the app's Databricks identity into a bearer token.

Works for both auth modes the app supports:
  * PAT mode   -- DATABRICKS_TOKEN is set (start_app.py then drops the injected SP OAuth creds);
  * SP mode    -- no PAT; Databricks Apps inject DATABRICKS_CLIENT_ID/SECRET for the app's
                  service principal and the SDK mints short-lived OAuth tokens.
Locally, DATABRICKS_CONFIG_PROFILE works too.
"""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_client = None


def workspace_client():
    global _client
    with _lock:
        if _client is None:
            from databricks.sdk import WorkspaceClient

            _client = WorkspaceClient()
        return _client


def host() -> str:
    h = os.environ.get("DATABRICKS_HOST", "").strip()
    if not h:
        h = workspace_client().config.host or ""
    if h and not h.startswith("http"):
        h = f"https://{h}"
    return h.rstrip("/")


def bearer_token() -> str:
    """A token valid for at least the next several minutes (PAT, or a fresh SDK OAuth token)."""
    pat = os.environ.get("DATABRICKS_TOKEN", "").strip()
    if pat:
        return pat
    header = workspace_client().config.authenticate().get("Authorization", "")
    return header.removeprefix("Bearer ").strip()
