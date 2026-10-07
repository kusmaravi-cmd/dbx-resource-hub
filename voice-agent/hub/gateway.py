"""Unity AI Gateway (OpenAI-compatible) helpers used off the voice hot path: embeddings."""
from __future__ import annotations

import os

import requests

from hub.auth import bearer_token, host

BASE_PATH = "/ai-gateway/openai/v1"
EMBED_MODEL = os.getenv("HUB_EMBED_MODEL", "system.ai.gte-large-en")
EMBED_DIM = int(os.getenv("HUB_EMBED_DIM", "1024"))


def base_url() -> str:
    return f"{host()}{BASE_PATH}"


def embed_texts(texts: list[str], *, model: str | None = None, timeout: float = 60.0) -> list[list[float]]:
    if not texts:
        return []
    resp = requests.post(
        f"{base_url()}/embeddings",
        headers={"Authorization": f"Bearer {bearer_token()}", "Content-Type": "application/json"},
        json={"model": model or EMBED_MODEL, "input": texts},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in data]


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"
