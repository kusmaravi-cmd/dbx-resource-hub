import base64
import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.request

import pytest

from app import web_server as W


def _decode(token, secret):
    head, body, sig = token.split(".")
    want = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256)
                                    .digest()).rstrip(b"=").decode()
    assert sig == want
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def test_mint_token_dispatches_the_agent_to_a_fresh_room():
    t1 = W.mint_token("jane.doe@corp.com", "Jane", api_key="k", api_secret="s", agent_name="hub-concierge")
    t2 = W.mint_token("jane.doe@corp.com", "Jane", api_key="k", api_secret="s")
    claims = _decode(t1["token"], "s")
    assert claims["roomConfig"]["agents"] == [{"agentName": "hub-concierge"}]
    assert claims["video"]["room"] == t1["room"] != t2["room"]
    assert json.loads(claims["metadata"]) == {"user": "jane.doe@corp.com", "first_name": "Jane"}
    assert claims["exp"] - claims["nbf"] <= 910


def test_first_name_from():
    assert W.first_name_from("jane.doe@corp.com") == "Jane"
    assert W.first_name_from("x@corp.com") == ""
    assert W.first_name_from("svc", "Raj Kumar") == "Raj"


@pytest.fixture
def server(monkeypatch):
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LAKEBASE_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    httpd = W.make_server(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_routes(server, monkeypatch):
    assert get(server + "/healthz")[0] == 200
    assert get(server + "/favicon.ico")[0] == 404  # a 404 must be answered, not crash the handler
    status, body = get(server + "/")
    assert status == 200 and b"Hub Concierge" in body
    assert get(server + "/vendor/livekit-client-2.22.3.umd.js")[0] == 200
    assert get(server + "/api/token")[0] == 503  # LiveKit not configured
    assert json.loads(get(server + "/api/shortlist")[1]) == {"items": []}

    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")
    cfg = json.loads(get(server + "/api/config", {"X-Forwarded-Email": "ana@corp.com"})[1])
    assert cfg["user"] == "ana@corp.com" and cfg["livekit_configured"] and not cfg["lakebase"]
    status, body = get(server + "/api/token", {"X-Forwarded-Email": "ana@corp.com"})
    tok = json.loads(body)
    assert status == 200 and tok["serverUrl"] == "wss://x.livekit.cloud"
    assert json.loads(_decode(tok["token"], "secret")["metadata"])["user"] == "ana@corp.com"
