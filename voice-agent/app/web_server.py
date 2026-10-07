"""Hub Concierge web tier: stdlib HTTP server, no LiveKit SDK.

Serves the call page, mints LiveKit tokens with agent dispatch, and lists the caller's shortlist from
Lakebase. On Databricks Apps every request arrives through the Apps proxy after workspace sign-in, with
the user in X-Forwarded-Email; that identity (not anything typed or said) goes into the token metadata.

Routes: GET /  /api/token  /api/config  /api/shortlist  /healthz
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = Path(__file__).resolve().parent / "web" / "public"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_env_local(path: Path = ROOT / ".env.local") -> None:
    """Local-dev parity with the worker (python-dotenv is not installed in the web tier's env)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            os.environ.setdefault(m.group(1), re.sub(r"^(['\"])(.*)\1$", r"\2", m.group(2)))


load_env_local()

from hub.shortlist import clean_user, list_sql  # noqa: E402

AGENT_NAME = os.getenv("AGENT_NAME", "hub-concierge")
TOKEN_TTL_S = 900
LOCAL_USER = os.getenv("HUB_LOCAL_USER", "local-dev@example.com")


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def first_name_from(user: str, preferred: str = "") -> str:
    base = (preferred or user).split("@")[0]
    word = re.split(r"[._\-+ ]", base)[0]
    word = "".join(ch for ch in word if ch.isalpha())[:20]
    return word.capitalize() if len(word) > 1 else ""


def mint_token(user: str, first_name: str, *, api_key: str, api_secret: str, agent_name: str = AGENT_NAME,
               now: int | None = None) -> dict:
    """HS256 LiveKit access token for a brand-new room (agent dispatch fires only on room creation)."""
    now = int(now or time.time())
    room = f"hub-{format(int(time.time() * 1000), 'x')}-{secrets.token_hex(2)}"
    identity = f"caller-{secrets.token_hex(3)}"
    claims = {
        "exp": now + TOKEN_TTL_S, "nbf": now - 10, "iss": api_key, "sub": identity,
        "video": {"roomJoin": True, "room": room, "canPublish": True, "canSubscribe": True,
                  "canPublishData": True},
        "roomConfig": {"agents": [{"agentName": agent_name}]},
        "metadata": json.dumps({"user": clean_user(user), "first_name": first_name}),
    }
    if first_name:
        claims["name"] = first_name
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode()) + b"."
                     + _b64url(json.dumps(claims, separators=(",", ":")).encode()))
    sig = hmac.new(api_secret.encode(), signing_input, hashlib.sha256).digest()
    return {"token": (signing_input + b"." + _b64url(sig)).decode(), "room": room, "identity": identity}


class _Conninfo:
    """Lakebase conninfo cached below the ~1h credential lifetime."""
    def __init__(self, ttl_s: float = 40 * 60):
        self._value, self._at, self._ttl, self._lock = None, 0.0, ttl_s, threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._value is None or time.time() - self._at > self._ttl:
                from hub.db import build_conninfo

                self._value, self._at = build_conninfo(), time.time()
            return self._value


_conninfo = _Conninfo()


def fetch_shortlist(user: str) -> list[dict]:
    if not os.getenv("LAKEBASE_ENDPOINT") or not user:
        return []
    import psycopg
    from psycopg.rows import dict_row

    from hub.db import SCHEMA

    with psycopg.connect(_conninfo.get(), connect_timeout=5, row_factory=dict_row) as conn:
        rows = conn.execute(list_sql(SCHEMA), {"u": user}).fetchall()
    return [{k: (str(v) if k in ("released_on", "added_at") and v is not None else v) for k, v in r.items()}
            for r in rows]


class Handler(SimpleHTTPRequestHandler):
    server_version = "HubConcierge/1.0"

    def _user(self) -> tuple[str, str]:
        user = self.headers.get("X-Forwarded-Email") or self.headers.get("X-Forwarded-User") or LOCAL_USER
        return clean_user(user), self.headers.get("X-Forwarded-Preferred-Username", "")

    def _json(self, status: int, body) -> None:
        raw = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            return self._json(200, {"ok": True})
        if path == "/api/config":
            user, _ = self._user()
            return self._json(200, {
                "agent": AGENT_NAME, "model": os.getenv("HUB_LLM_MODEL", "system.ai.gpt-5-nano"),
                "lakebase": bool(os.getenv("LAKEBASE_ENDPOINT")), "user": user,
                "livekit_configured": all(os.getenv(k) for k in
                                          ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")),
            })
        if path == "/api/token":
            url, key, secret = (os.getenv(k, "") for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
            if not (url and key and secret):
                return self._json(503, {"error": "LiveKit is not configured (LIVEKIT_URL / _API_KEY / _API_SECRET)"})
            user, preferred = self._user()
            tok = mint_token(user, first_name_from(user, preferred), api_key=key, api_secret=secret)
            return self._json(200, {"serverUrl": url, **tok})
        if path == "/api/shortlist":
            user, _ = self._user()
            try:
                return self._json(200, {"items": fetch_shortlist(user)})
            except Exception as exc:  # noqa: BLE001
                return self._json(200, {"items": [], "error": f"shortlist unavailable: {type(exc).__name__}"})
        if path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "/healthz" not in msg:
            sys.stderr.write(f"[web] {self.address_string()} {msg}\n")


def make_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("0.0.0.0", port), partial(Handler, directory=str(PUBLIC)))


def main() -> None:
    port = int(os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT") or 8000)
    httpd = make_server(port)
    print(f"[web] Hub Concierge listening on 0.0.0.0:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
