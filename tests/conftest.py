import pathlib

import pytest

from dossier_agent import storage

DEMO_CASES = pathlib.Path(__file__).resolve().parent.parent / "demo-data" / "config" / "seller_cases.md"


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path_factory, monkeypatch):
    """Every test gets its own local storage, never data/storage. It holds
    the demo config/seller_cases.md, which every run requires."""
    s = storage.LocalStorage(tmp_path_factory.mktemp("storage"))   # not tmp_path: tests own it
    s.write_text("config/seller_cases.md", DEMO_CASES.read_text(encoding="utf-8"))
    monkeypatch.setattr(storage, "_storage", s)
    return s


@pytest.fixture(autouse=True)
def gemini_api_backend(monkeypatch):
    """Prices are per backend: tests use the Gemini API table unless they set
    the variables themselves (the local .env may point to Vertex AI)."""
    for name in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE"):
        monkeypatch.delenv(name, raising=False)
