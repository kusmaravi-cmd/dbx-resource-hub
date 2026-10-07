"""The Resource Hub catalog: load ../search.json (the site's own index) into clean records.

Each site item is {t: title, d: description, u: url, k: kind, a: area}. The site's area labels are
free text that grew over time ("AI & agents", "AI and agents", "AI, agents and Genie Code", ...), so
we fold them into a small set of topics a caller can say out loud. Launch items carry their release
status and month in the description ("Generally available, September 2026"), which powers "what's new".
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# Ordered: the first topic whose keywords match the raw area (then the title) wins.
TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("AI and agents", ("agent", "ai ", "ai,", "ai&", "llm", "genai", "genie code", "mcp", "rag")),
    ("BI and Genie", ("bi ", "bi,", "bi&", "genie", "sql", "dashboard", "analytics", "metric view", "semantic")),
    ("Machine learning", ("ml ", "ml&", "machine learning", "mlflow", "forecast", "model")),
    ("Apps and Lakebase", ("app", "lakebase", "postgres", "serving", "dev tool")),
    ("Governance and security", ("governance", "security", "unity catalog", "sharing", "privacy", "lineage")),
    ("Data engineering", ("data engineering", "lakeflow", "pipeline", "etl", "streaming", "spark", "delta",
                          "ingest", "iceberg", "lakehouse")),
    ("Migration", ("migration", "migrate", "lakebridge")),
    ("Platform and admin", ("platform", "admin", "devops", "cost", "getting started", "start here", "serverless",
                            "workspace", "compute")),
    ("Industry solutions", ("industry", "geospatial", "iot", "playbook", "use case", "end-to-end")),
    ("Learning and community", ("learning", "community", "people", "writing", "certification", "training")),
]
OTHER = "Other"
SITE_URL = "https://kusmaravi-cmd.github.io/dbx-resource-hub/"  # resolves the site's in-page links (#pb-...)

STATUSES = ("Generally available", "Public Preview", "Private Preview", "Beta", "Deprecated", "Retired")
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], start=1)}
_STATUS_RE = re.compile(r"(?i)\b(" + "|".join(STATUSES) + r")\b")
_MONTH_RE = re.compile(r"(?i)\b(" + "|".join(_MONTHS) + r")\s+(20\d\d)\b")
_URL_MONTH_RE = re.compile(r"/release-notes/[^#]*?/(20\d\d)/(" + "|".join(_MONTHS) + r")\b", re.I)


@dataclass(frozen=True)
class Resource:
    id: str
    title: str
    summary: str
    url: str
    kind: str
    topic: str
    area: str
    status: str | None
    released_on: str | None  # ISO date (first of the month) for launches

    def content(self) -> str:
        """The text we embed and keyword-index."""
        parts = [self.title, self.summary, f"Type: {self.kind}.", f"Topic: {self.topic}."]
        if self.area and self.area != self.topic:
            parts.append(f"Area: {self.area}.")
        if self.status:
            parts.append(f"Status: {self.status}.")
        return " ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)


def resource_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode()).hexdigest()[:12]


def topic_for(area: str, title: str = "", *, kind: str = "", url: str = "") -> str:
    if kind == "Acquisition":
        return "Acquisitions"
    if "databricks-industry-solutions" in url:
        return "Industry solutions"
    if "feature roundup" in area.lower() or "release-notes" in url:
        area = f"{area} {title}"  # roundups/launches: classify by what the feature is about
    for text in (area, title):
        hay = f" {text.lower()} "
        for topic, keys in TOPICS:
            if any(k in hay for k in keys):
                return topic
    return OTHER


def parse_launch(description: str, url: str) -> tuple[str | None, str | None]:
    """(status, ISO first-of-month) from a launch description / release-notes URL, else (None, None)."""
    status = None
    if m := _STATUS_RE.search(description or ""):
        status = next(s for s in STATUSES if s.lower() == m.group(1).lower())
    released = None
    if m := _MONTH_RE.search(description or ""):
        released = dt.date(int(m.group(2)), _MONTHS[m.group(1).lower()], 1).isoformat()
    elif m := _URL_MONTH_RE.search(url or ""):
        released = dt.date(int(m.group(1)), _MONTHS[m.group(2).lower()], 1).isoformat()
    return status, released


def normalize(item: dict) -> Resource | None:
    title = (item.get("t") or "").strip()
    url = (item.get("u") or "").strip()
    if not title or not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = SITE_URL + url.lstrip("/")
    summary = (item.get("d") or "").strip()
    kind = (item.get("k") or "Resource").strip()
    area = (item.get("a") or "").strip()
    status, released = parse_launch(summary, url) if kind == "Launch" else (None, None)
    return Resource(
        id=resource_id(url, title), title=title, summary=summary, url=url, kind=kind,
        topic=topic_for(area, title, kind=kind, url=url), area=area, status=status, released_on=released,
    )


def load_catalog(path: str | Path) -> list[Resource]:
    """Read a search.json (site format, with or without the `emb` block) or a catalog.json (list of
    Resource dicts, as staged for the app) and return de-duplicated resources."""
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, list):  # staged catalog.json
        return [Resource(**r) for r in raw]
    seen: set[str] = set()
    out: list[Resource] = []
    for item in raw.get("items", []):
        r = normalize(item)
        if r is not None and r.id not in seen:
            seen.add(r.id)
            out.append(r)
    return out


def write_compact(resources: list[Resource], path: str | Path) -> None:
    """Write the app's bundled catalog.json (no embeddings; ~1/3 the size of search.json)."""
    Path(path).write_text(json.dumps([r.to_dict() for r in resources], separators=(",", ":")))
