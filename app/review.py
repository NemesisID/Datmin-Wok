"""Antrean review klasifikasi dan ringkasan label."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.classify import REVIEW_CONFIDENCE, REVIEW_GAP
from app.models import Paper, PaperTopic, Thesis, ThesisTopic, Topic


@dataclass
class LabelView:
    topic_id: int
    topic_name: str
    subtopic_name: str | None
    confidence: float
    source: str
    locked: bool


@dataclass
class ReviewItem:
    kind: str
    id: int
    title: str
    year: int | None
    labels: list[LabelView] = field(default_factory=list)
    reason: str = ""


def _topic_names(session: Session) -> dict[int, Topic]:
    return {topic.id: topic for topic in session.exec(select(Topic)).all()}


def _labels(
    rows: list[PaperTopic] | list[ThesisTopic], topics: dict[int, Topic]
) -> list[LabelView]:
    labels = []
    for row in rows:
        topic = topics.get(row.topic_id)
        if topic is None:
            continue
        subtopic_id = getattr(row, "subtopic_id", None)
        subtopic = topics.get(subtopic_id) if subtopic_id else None
        labels.append(
            LabelView(
                topic_id=row.topic_id,
                topic_name=topic.name,
                subtopic_name=subtopic.name if subtopic else None,
                confidence=row.confidence,
                source=row.source,
                locked=row.locked,
            )
        )
    labels.sort(key=lambda label: (-label.confidence, label.topic_name))
    return labels


def review_reason(labels: list[LabelView]) -> str | None:
    if not labels:
        return "belum ada topik"
    if labels[0].confidence < REVIEW_CONFIDENCE:
        return "keyakinan rendah"
    if len(labels) >= 2 and labels[0].confidence - labels[1].confidence < REVIEW_GAP:
        return "dua topik berdekatan"
    return None


def _collect(
    items: list[ReviewItem], offset: int, limit: int | None
) -> tuple[list[ReviewItem], int]:
    total = len(items)
    if limit is None:
        return items[offset:], total
    return items[offset : offset + limit], total


def pending_papers(
    session: Session, offset: int = 0, limit: int | None = 50
) -> tuple[list[ReviewItem], int]:
    topics = _topic_names(session)
    papers = session.exec(
        select(Paper)
        .where(Paper.reviewed_at.is_(None))
        .order_by(Paper.year.desc(), Paper.id.desc())
    ).all()
    paper_ids = [paper.id for paper in papers]
    rows = (
        session.exec(select(PaperTopic).where(PaperTopic.paper_id.in_(paper_ids))).all()
        if paper_ids
        else []
    )
    grouped: dict[int, list[PaperTopic]] = {}
    for row in rows:
        grouped.setdefault(row.paper_id, []).append(row)

    items = []
    for paper in papers:
        labels = _labels(grouped.get(paper.id, []), topics)
        reason = review_reason(labels)
        if reason is None:
            continue
        items.append(
            ReviewItem(
                kind="paper",
                id=paper.id,
                title=paper.title,
                year=paper.year,
                labels=labels,
                reason=reason,
            )
        )
    return _collect(items, offset, limit)


def pending_theses(
    session: Session, offset: int = 0, limit: int | None = 50
) -> tuple[list[ReviewItem], int]:
    topics = _topic_names(session)
    theses = session.exec(
        select(Thesis)
        .where(Thesis.reviewed_at.is_(None))
        .order_by(Thesis.year.desc(), Thesis.id.desc())
    ).all()
    thesis_ids = [thesis.id for thesis in theses]
    rows = (
        session.exec(select(ThesisTopic).where(ThesisTopic.thesis_id.in_(thesis_ids))).all()
        if thesis_ids
        else []
    )
    grouped: dict[int, list[ThesisTopic]] = {}
    for row in rows:
        grouped.setdefault(row.thesis_id, []).append(row)

    items = []
    for thesis in theses:
        labels = _labels(grouped.get(thesis.id, []), topics)
        reason = review_reason(labels)
        if reason is None:
            continue
        items.append(
            ReviewItem(
                kind="thesis",
                id=thesis.id,
                title=thesis.title,
                year=thesis.year,
                labels=labels,
                reason=reason,
            )
        )
    return _collect(items, offset, limit)


def review_counts(session: Session) -> tuple[int, int]:
    _, papers = pending_papers(session, limit=0)
    _, theses = pending_theses(session, limit=0)
    return papers, theses
