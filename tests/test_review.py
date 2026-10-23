from __future__ import annotations

from factories import make_paper, make_thesis, seed_minimal_taxonomy
from sqlmodel import select

from app.classify import mark_not_relevant, set_manual_label
from app.models import PaperTopic, ThesisTopic
from app.review import LabelView, pending_papers, pending_theses, review_counts, review_reason


def label(topic_id: int, confidence: float, *, locked: bool = False) -> LabelView:
    return LabelView(
        topic_id=topic_id,
        topic_name="Topik",
        subtopic_name=None,
        confidence=confidence,
        source="manual" if locked else "rule",
        locked=locked,
    )


def test_review_reason_flags_missing_and_low_confidence() -> None:
    assert review_reason([]) == "belum ada topik"
    assert review_reason([label(1, 0.45)]) == "keyakinan rendah"
    assert review_reason([label(1, 0.5), label(2, 0.45)]) == "dua topik berdekatan"
    assert review_reason([label(1, 0.7)]) is None


def test_pending_papers_includes_no_label_and_ambiguous(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    empty = make_paper(session, "Tanpa label")
    ambiguous = make_paper(session, "Dua topik")
    session.add_all(
        [
            PaperTopic(
                paper_id=ambiguous.id,
                topic_id=taxonomy["Data Mining"].id,
                confidence=0.5,
            ),
            PaperTopic(
                paper_id=ambiguous.id,
                topic_id=taxonomy["UI/UX"].id,
                confidence=0.45,
            ),
        ]
    )
    confident = make_paper(session, "Sudah yakin")
    session.add(
        PaperTopic(
            paper_id=confident.id,
            topic_id=taxonomy["Data Mining"].id,
            confidence=0.75,
        )
    )
    session.commit()

    items, total = pending_papers(session)

    assert total == 2
    assert {item.id for item in items} == {empty.id, ambiguous.id}
    assert {item.reason for item in items} == {"belum ada topik", "dua topik berdekatan"}


def test_reviewed_paper_leaves_queue(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Tanpa label")

    assert pending_papers(session)[1] == 1
    set_manual_label(session, paper=paper, topic_id=taxonomy["UI/UX"].id)

    assert pending_papers(session)[1] == 0
    assert pending_theses(session)[1] == 0
    assert review_counts(session) == (0, 0)


def test_mark_not_relevant_clears_labels_and_queue(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Tidak relevan")
    session.add(
        PaperTopic(
            paper_id=paper.id,
            topic_id=taxonomy["Data Mining"].id,
            confidence=0.5,
            locked=True,
            source="manual",
        )
    )
    session.commit()

    mark_not_relevant(session, paper=paper)

    assert session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all() == []
    session.refresh(paper)
    assert paper.reviewed_at is not None
    assert pending_papers(session)[1] == 0


def test_pending_theses_uses_same_rules(session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    thesis = make_thesis(session, "Skripsi tanpa topik")
    low = make_thesis(session, "Skripsi keyakinan rendah")
    session.add(
        ThesisTopic(
            thesis_id=low.id,
            topic_id=taxonomy["Data Mining"].id,
            confidence=0.4,
        )
    )
    session.commit()

    items, total = pending_theses(session)

    assert total == 2
    assert {item.id for item in items} == {thesis.id, low.id}
    assert all(item.kind == "thesis" for item in items)
