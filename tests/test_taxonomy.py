import copy
from pathlib import Path

import pytest
import yaml
from sqlmodel import select

from app.models import Topic, TopicKeyword, TopicLab
from app.taxonomy import (
    get_taxonomy_version,
    import_taxonomy,
    normalize_keyword,
)

SEED = Path(__file__).resolve().parents[1] / "seeds" / "taxonomy.yaml"


def load_seed() -> dict:
    return yaml.safe_load(SEED.read_text(encoding="utf-8"))


def test_normalize_keyword() -> None:
    assert normalize_keyword("  Analisis   Sentimen! ") == "analisis sentimen"
    assert normalize_keyword("UI/UX") == "ui ux"
    assert normalize_keyword("K-Means") == "k means"
    assert normalize_keyword("   ") == ""


def test_import_seed_creates_topics_and_shared_labs(session) -> None:
    summary = import_taxonomy(session, load_seed())
    session.commit()

    assert summary.topics_created == 23
    assert summary.version == 1
    assert get_taxonomy_version(session) == 1

    uiux = session.exec(select(Topic).where(Topic.name == "UI/UX")).one()
    labs = {
        row.lab for row in session.exec(select(TopicLab).where(TopicLab.topic_id == uiux.id)).all()
    }
    assert labs == {"SOLUSI", "MSI"}

    project = session.exec(select(Topic).where(Topic.name == "Manajemen Proyek")).one()
    project_labs = {
        row.lab
        for row in session.exec(select(TopicLab).where(TopicLab.topic_id == project.id)).all()
    }
    assert project_labs == {"SOLUSI", "MSI"}


def test_import_seed_creates_data_mining_subtopics(session) -> None:
    import_taxonomy(session, load_seed())
    session.commit()

    mining = session.exec(select(Topic).where(Topic.name == "Data Mining")).one()
    children = session.exec(select(Topic).where(Topic.parent_id == mining.id)).all()
    assert {child.name for child in children} == {"Analisis Sentimen", "Forecasting", "Umum"}

    umum = next(child for child in children if child.name == "Umum")
    assert session.exec(select(TopicKeyword).where(TopicKeyword.topic_id == umum.id)).all() == []


def test_reimport_without_changes_keeps_version(session) -> None:
    import_taxonomy(session, load_seed())
    session.commit()

    summary = import_taxonomy(session, load_seed())
    session.commit()

    assert summary.changed is False
    assert summary.version == 1
    assert get_taxonomy_version(session) == 1


def test_changed_keyword_bumps_version(session) -> None:
    seed = load_seed()
    import_taxonomy(session, seed)
    session.commit()

    edited = copy.deepcopy(seed)
    edited["topics"][0]["keywords"].append("kata kunci tambahan")
    summary = import_taxonomy(session, edited)
    session.commit()

    assert summary.keywords_added == 1
    assert summary.version == 2
    assert get_taxonomy_version(session) == 2


def test_removed_keyword_bumps_version(session) -> None:
    seed = load_seed()
    import_taxonomy(session, seed)
    session.commit()

    edited = copy.deepcopy(seed)
    edited["topics"][0]["keywords"].pop()
    summary = import_taxonomy(session, edited)
    session.commit()

    assert summary.keywords_removed == 1
    assert summary.version == 2


def test_invalid_lab_is_rejected(session) -> None:
    payload = {"topics": [{"name": "Topik Salah", "labs": ["LAIN"], "keywords": []}]}
    with pytest.raises(ValueError, match="tidak dikenal"):
        import_taxonomy(session, payload)


def test_duplicate_topic_names_rejected(session) -> None:
    payload = {
        "topics": [
            {"name": "Sama", "labs": ["SOLUSI"], "keywords": []},
            {"name": "Sama", "labs": ["MSI"], "keywords": []},
        ]
    }
    with pytest.raises(ValueError, match="lebih dari sekali"):
        import_taxonomy(session, payload)


def test_subtopic_depth_is_limited(session) -> None:
    payload = {
        "topics": [
            {
                "name": "Induk",
                "labs": ["SOLUSI"],
                "keywords": [],
                "subtopics": [
                    {
                        "name": "Anak",
                        "labs": ["SOLUSI"],
                        "keywords": [],
                        "subtopics": [{"name": "Cucu", "labs": ["SOLUSI"], "keywords": []}],
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="terlalu dalam"):
        import_taxonomy(session, payload)
