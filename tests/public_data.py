from __future__ import annotations

from sqlmodel import Session

from app.dedupe import compute_title_hash
from app.models import (
    Lecturer,
    LecturerPaper,
    Paper,
    PaperTopic,
    Thesis,
    ThesisTopic,
    Topic,
    TopicLab,
)
from tests.factories import make_lecturer, make_thesis, seed_minimal_taxonomy


def seed_public(session: Session) -> dict[str, Topic]:
    topics = seed_minimal_taxonomy(session)
    labs = {
        "Data Mining": ["SOLUSI"],
        "UI/UX": ["SOLUSI", "MSI"],
        "Analisis Sentimen": ["SOLUSI"],
        "Umum": ["SOLUSI"],
    }
    for name, values in labs.items():
        for lab in values:
            session.add(TopicLab(topic_id=topics[name].id, lab=lab))
    session.commit()
    return topics


def add_lecturer(session: Session, name: str) -> Lecturer:
    return make_lecturer(session, name)


def add_paper(
    session: Session,
    lecturer: Lecturer,
    title: str,
    *,
    year: int = 2024,
    venue: str = "",
    labels: list[tuple[Topic, float, int | None]] | None = None,
) -> Paper:
    paper = Paper(
        title=title,
        title_hash=compute_title_hash(title),
        year=year,
        venue=venue,
    )
    session.add(paper)
    session.flush()
    session.add(LecturerPaper(lecturer_id=lecturer.id, paper_id=paper.id))
    for topic, confidence, subtopic_id in labels or []:
        session.add(
            PaperTopic(
                paper_id=paper.id,
                topic_id=topic.id,
                subtopic_id=subtopic_id,
                confidence=confidence,
                source="rule",
                taxonomy_version=1,
            )
        )
    session.commit()
    session.refresh(paper)
    return paper


def add_thesis(
    session: Session,
    lecturer: Lecturer,
    title: str,
    *,
    year: int = 2024,
    student_name: str = "",
    nim: str = "",
    labels: list[tuple[Topic, float]] | None = None,
) -> Thesis:
    thesis = make_thesis(
        session,
        title,
        year=year,
        student_name=student_name,
        nim=nim,
        supervisors=[lecturer],
    )
    for topic, confidence in labels or []:
        session.add(
            ThesisTopic(
                thesis_id=thesis.id,
                topic_id=topic.id,
                confidence=confidence,
                source="rule",
                taxonomy_version=1,
            )
        )
    session.commit()
    return thesis


def set_last_sync(lecturer: Lecturer, session: Session, *, days_ago: int) -> None:
    from datetime import UTC, datetime, timedelta

    lecturer.last_synced_at = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(lecturer)
    session.commit()
