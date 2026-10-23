import json
from pathlib import Path
from typing import Any

from app.providers.openalex import normalize_work, reconstruct_abstract

FIXTURE = Path(__file__).parent / "fixtures" / "openalex_works_page.json"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_reconstruct_abstract_orders_words() -> None:
    assert reconstruct_abstract({"b": [1], "a": [0]}) == "a b"


def test_reconstruct_abstract_empty() -> None:
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_normalize_work_survives_null_author_id() -> None:
    raw = {
        "id": "https://openalex.org/W1",
        "display_name": "Judul",
        "authorships": [{"author": {"id": None}}, {"author": {"id": "https://openalex.org/A1"}}],
    }
    work = normalize_work(raw)
    assert work["openalex_id"] == "W1"
    assert work["author_ids"] == ["A1"]


def test_fixture_normalizes_to_expected_shape() -> None:
    data = load_fixture()
    works = [normalize_work(raw) for raw in data["results"]]

    assert len(works) == len(data["results"])
    assert all(work["title"] for work in works)
    assert all(work["year"] for work in works)
    assert all(work["openalex_id"].startswith("W") for work in works)
    assert any(work["abstract"] for work in works)
