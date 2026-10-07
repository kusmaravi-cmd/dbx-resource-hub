from pathlib import Path

import pytest

from hub.catalog import load_catalog
from hub.search import MemoryIndex

SEARCH_JSON = Path(__file__).resolve().parents[2] / "search.json"


@pytest.fixture(scope="session")
def resources():
    return load_catalog(SEARCH_JSON)


@pytest.fixture(scope="session")
def memory(resources):
    return MemoryIndex(resources)
