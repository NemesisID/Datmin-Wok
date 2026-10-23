from __future__ import annotations

import pytest
from factories import make_paper, make_thesis, seed_minimal_taxonomy
from sqlmodel import select

from app.classify import (
    Classifier,
    mark_not_relevant,
    normalize_text,
    reclassify_papers,
    reclassify_theses,
    set_manual_label,
)
from app.models import PaperTopic, ThesisTopic, utcnow
from app.taxonomy import set_taxonomy_version


def test_normalize_text_handles_punctuation_and_case() -> None:
    assert normalize_text("  K-Means & Naive Bayes! ") == "k means naive bayes"
    assert normalize_text("UI/UX") == "ui ux"


def test_classifier_requires_two_keywords(session) -> None:
    seed_minimal_taxonomy(session)
    classifier = Classifier.from_session(session)

    assert classifier.classify("data mining", 0.4) == []
    predictions = classifier.classify("data mining dan klasifikasi", 0.4)
    assert len(predictions) == 1
    assert predictions[0].confidence == pytest.approx(0.5)


def test_classifier_picks_matching_subtopic(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    classifier = Classifier.from_session(session)

    predictions = classifier.classify(
        "data mining klasifikasi analisis sentimen ulasan twitter", 0.4
    )
    assert len(predictions) == 1
    assert predictions[0].topic_id == taxonomy["Data Mining"].id
    assert predictions[0].subtopic_id == taxonomy["Analisis Sentimen"].id


def test_classifier_falls_back_to_umum_subtopic(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    classifier = Classifier.from_session(session)

    predictions = classifier.classify("data mining klasifikasi", 0.4)
    assert predictions[0].subtopic_id == taxonomy["Umum"].id


def test_classifier_supports_multiple_topics(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    classifier = Classifier.from_session(session)

    predictions = classifier.classify("data mining klasifikasi usability user experience", 0.4)
    assert {prediction.topic_id for prediction in predictions} == {
        taxonomy["Data Mining"].id,
        taxonomy["UI/UX"].id,
    }


def test_classifier_is_deterministic(session) -> None:
    seed_minimal_taxonomy(session)
    classifier = Classifier.from_session(session)
    text = "data mining klasifikasi analisis sentimen ulasan twitter"
    assert classifier.classify(text, 0.4) == classifier.classify(text, 0.4)


def test_paper_classification_uses_abstract_and_venue(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(
        session, "Studi Kasus", abstract="data mining dan klasifikasi", venue="Jurnal"
    )

    stats = reclassify_papers(session, paper_ids=[paper.id])

    assert stats.labels == 1
    label = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).one()
    assert label.topic_id == taxonomy["Data Mining"].id
    assert label.source == "rule"
    assert label.locked is False
    assert label.taxonomy_version == 1


def test_reclassify_replaces_stale_rule_labels(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(session, "data mining klasifikasi usability user experience")
    reclassify_papers(session, paper_ids=[paper.id])

    paper.title = "clustering dan naive bayes"
    session.add(paper)
    set_taxonomy_version(session, 2)
    session.commit()
    stats = reclassify_papers(session, paper_ids=[paper.id])

    labels = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all()
    assert [label.topic_id for label in labels] == [taxonomy["Data Mining"].id]
    assert labels[0].taxonomy_version == 2
    assert stats.labels == 1


def test_manual_override_survives_taxonomy_version_bump(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(session, "data mining klasifikasi")
    reclassify_papers(session, paper_ids=[paper.id])

    set_manual_label(session, paper=paper, topic_id=taxonomy["UI/UX"].id)
    session.refresh(paper)
    assert paper.reviewed_at is not None

    set_taxonomy_version(session, 2)
    session.commit()
    stats = reclassify_papers(session, paper_ids=[paper.id])

    labels = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all()
    assert len(labels) == 1
    assert labels[0].topic_id == taxonomy["UI/UX"].id
    assert labels[0].source == "manual"
    assert labels[0].locked is True
    assert labels[0].confidence == 1.0
    assert stats.skipped_reviewed == 1


def test_reclassify_skips_reviewed_paper_without_labels(session) -> None:
    seed_minimal_taxonomy(session)
    paper = make_paper(session, "data mining klasifikasi")
    mark_not_relevant(session, paper=paper)

    stats = reclassify_papers(session, paper_ids=[paper.id])

    assert stats.skipped_reviewed == 1
    assert session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all() == []


def test_thesis_uses_title_and_higher_threshold(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    strong = make_thesis(session, "Klasifikasi data mining untuk UMKM")
    weak = make_thesis(session, "data mining")

    stats = reclassify_theses(session)

    assert stats.scanned == 2
    strong_labels = session.exec(
        select(ThesisTopic).where(ThesisTopic.thesis_id == strong.id)
    ).all()
    assert [label.topic_id for label in strong_labels] == [taxonomy["Data Mining"].id]
    assert session.exec(select(ThesisTopic).where(ThesisTopic.thesis_id == weak.id)).all() == []


def test_manual_label_validates_subtopic_parent(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(session, "data mining klasifikasi")
    reclassify_papers(session, paper_ids=[paper.id])

    with pytest.raises(ValueError, match="Sub-topik"):
        set_manual_label(
            session,
            paper=paper,
            topic_id=taxonomy["UI/UX"].id,
            subtopic_id=taxonomy["Analisis Sentimen"].id,
        )

    labels = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all()
    assert len(labels) == 1
    assert labels[0].source == "rule"


def test_manual_label_rejects_subtopic_as_main_topic(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(session, "data mining klasifikasi")

    with pytest.raises(ValueError, match="Topik"):
        set_manual_label(session, paper=paper, topic_id=taxonomy["Analisis Sentimen"].id)
    session.refresh(paper)
    assert paper.reviewed_at is None


def test_reviewed_at_excludes_paper_from_reclassification(session) -> None:
    seed_minimal_taxonomy(session)
    paper = make_paper(session, "data mining klasifikasi")
    paper.reviewed_at = utcnow()
    session.add(paper)
    session.commit()

    stats = reclassify_papers(session, paper_ids=[paper.id])

    assert stats.scanned == 0
    assert stats.skipped_reviewed == 1
