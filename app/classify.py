"""Klasifikasi topik multi-label berbasis aturan kata kunci."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import Paper, PaperTopic, Thesis, ThesisTopic, Topic, TopicKeyword, utcnow
from app.taxonomy import get_taxonomy_version, normalize_keyword

PAPER_THRESHOLD = 0.4
THESIS_THRESHOLD = 0.5


@dataclass(frozen=True)
class TopicPrediction:
    topic_id: int
    subtopic_id: int | None
    confidence: float


@dataclass
class TopicNode:
    id: int
    name: str
    sort_order: int
    keywords: list[str] = field(default_factory=list)
    children: list[TopicNode] = field(default_factory=list)


@dataclass
class ReclassifyStats:
    scanned: int = 0
    labeled: int = 0
    labels: int = 0
    skipped_reviewed: int = 0


def normalize_text(text: str) -> str:
    return normalize_keyword(text)


def count_keyword_matches(normalized_text: str, keywords: list[str]) -> int:
    padded = f" {normalized_text} "
    return sum(1 for keyword in keywords if f" {keyword} " in padded)


def confidence_from_matches(matched: int) -> float:
    return matched / (matched + 2) if matched else 0.0


def _children_by_parent(topics: list[Topic]) -> dict[int | None, list[Topic]]:
    grouped: dict[int | None, list[Topic]] = defaultdict(list)
    for topic in topics:
        grouped[topic.parent_id].append(topic)
    return grouped


class Classifier:
    def __init__(self, roots: list[TopicNode]) -> None:
        self.roots = roots
        self.topic_names = {root.id: root.name for root in roots}
        for root in roots:
            for child in root.children:
                self.topic_names[child.id] = child.name

    @classmethod
    def from_session(cls, session: Session) -> Classifier:
        topics = list(session.exec(select(Topic).where(Topic.active.is_(True))).all())
        keyword_rows = session.exec(select(TopicKeyword)).all()
        keywords: dict[int, list[str]] = defaultdict(list)
        for row in keyword_rows:
            if row.keyword_norm:
                keywords[row.topic_id].append(row.keyword_norm)

        grouped = _children_by_parent(topics)
        roots = []
        for root in sorted(grouped.get(None, []), key=lambda item: (item.sort_order, item.name)):
            children = [
                _node(child, keywords)
                for child in sorted(
                    grouped.get(root.id, []),
                    key=lambda item: (item.sort_order, item.name),
                )
            ]
            node = _node(root, keywords)
            node.children = children
            roots.append(node)
        return cls(roots)

    def classify(self, text: str, threshold: float) -> list[TopicPrediction]:
        normalized = normalize_text(text)
        predictions: list[tuple[float, int, TopicPrediction]] = []
        for root in self.roots:
            confidence = confidence_from_matches(count_keyword_matches(normalized, root.keywords))
            if confidence < threshold:
                continue
            subtopic_id = self._pick_subtopic(root, normalized, threshold)
            predictions.append(
                (
                    confidence,
                    root.sort_order,
                    TopicPrediction(
                        topic_id=root.id,
                        subtopic_id=subtopic_id,
                        confidence=round(confidence, 4),
                    ),
                )
            )
        predictions.sort(key=lambda item: (-item[0], item[1]))
        return [prediction for _, _, prediction in predictions]

    @staticmethod
    def _pick_subtopic(root: TopicNode, normalized: str, threshold: float) -> int | None:
        best: TopicNode | None = None
        best_score = 0.0
        for child in root.children:
            score = confidence_from_matches(count_keyword_matches(normalized, child.keywords))
            if score > best_score:
                best, best_score = child, score
        if best is not None and best_score >= threshold:
            return best.id
        for child in root.children:
            if child.name.strip().lower() == "umum":
                return child.id
        return None


def _node(topic: Topic, keywords: dict[int, list[str]]) -> TopicNode:
    return TopicNode(
        id=topic.id,
        name=topic.name,
        sort_order=topic.sort_order,
        keywords=keywords.get(topic.id, []),
    )


def paper_text(paper: Paper) -> str:
    return " ".join(part for part in (paper.title, paper.venue, paper.abstract) if part)


def _replace_labels(
    session: Session,
    model,
    id_field: str,
    item_id: int,
    predictions: list[TopicPrediction],
    version: int,
) -> int:
    existing = session.exec(select(model).where(getattr(model, id_field) == item_id)).all()
    locked_topics = {row.topic_id for row in existing if row.locked}
    for row in existing:
        if not row.locked:
            session.delete(row)
    # Hapus dulu sebelum insert agar unique (item, topic) tidak bentrok di flush yang sama.
    session.flush()

    created = 0
    for prediction in predictions:
        if prediction.topic_id in locked_topics:
            continue
        payload = {
            id_field: item_id,
            "topic_id": prediction.topic_id,
            "confidence": prediction.confidence,
            "source": "rule",
            "locked": False,
            "taxonomy_version": version,
        }
        if "subtopic_id" in model.model_fields:
            payload["subtopic_id"] = prediction.subtopic_id
        session.add(model(**payload))
        created += 1
    return created


def reclassify_papers(
    session: Session,
    *,
    paper_ids: list[int] | None = None,
    classifier: Classifier | None = None,
    version: int | None = None,
    commit: bool = True,
) -> ReclassifyStats:
    classifier = classifier or Classifier.from_session(session)
    version = get_taxonomy_version(session) if version is None else version
    statement = select(Paper)
    if paper_ids is not None:
        if not paper_ids:
            return ReclassifyStats()
        statement = statement.where(Paper.id.in_(paper_ids))

    stats = ReclassifyStats()
    for paper in session.exec(statement).all():
        if paper.reviewed_at is not None:
            stats.skipped_reviewed += 1
            continue
        predictions = classifier.classify(paper_text(paper), PAPER_THRESHOLD)
        stats.labels += _replace_labels(
            session, PaperTopic, "paper_id", paper.id, predictions, version
        )
        stats.scanned += 1
        if predictions:
            stats.labeled += 1
    if commit:
        session.commit()
    return stats


def reclassify_theses(
    session: Session,
    *,
    thesis_ids: list[int] | None = None,
    classifier: Classifier | None = None,
    version: int | None = None,
    commit: bool = True,
) -> ReclassifyStats:
    classifier = classifier or Classifier.from_session(session)
    version = get_taxonomy_version(session) if version is None else version
    statement = select(Thesis)
    if thesis_ids is not None:
        if not thesis_ids:
            return ReclassifyStats()
        statement = statement.where(Thesis.id.in_(thesis_ids))

    stats = ReclassifyStats()
    for thesis in session.exec(statement).all():
        if thesis.reviewed_at is not None:
            stats.skipped_reviewed += 1
            continue
        predictions = classifier.classify(thesis.title, THESIS_THRESHOLD)
        stats.labels += _replace_labels(
            session, ThesisTopic, "thesis_id", thesis.id, predictions, version
        )
        stats.scanned += 1
        if predictions:
            stats.labeled += 1
    if commit:
        session.commit()
    return stats


def set_manual_label(
    session: Session,
    paper: Paper | None = None,
    thesis: Thesis | None = None,
    *,
    topic_id: int,
    subtopic_id: int | None = None,
) -> None:
    topic = session.get(Topic, topic_id)
    if topic is None or not topic.active or topic.parent_id is not None:
        raise ValueError("Topik harus topik utama yang aktif.")
    if subtopic_id is not None:
        subtopic = session.get(Topic, subtopic_id)
        if subtopic is None or not subtopic.active or subtopic.parent_id != topic_id:
            raise ValueError("Sub-topik harus milik topik yang dipilih.")

    if thesis is not None and subtopic_id is not None:
        raise ValueError("Skripsi hanya memakai topik utama.")

    version = get_taxonomy_version(session)
    if paper is not None:
        for row in session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all():
            session.delete(row)
        session.add(
            PaperTopic(
                paper_id=paper.id,
                topic_id=topic_id,
                subtopic_id=subtopic_id,
                confidence=1.0,
                source="manual",
                locked=True,
                taxonomy_version=version,
            )
        )
        paper.reviewed_at = utcnow()
        session.add(paper)
    elif thesis is not None:
        for row in session.exec(
            select(ThesisTopic).where(ThesisTopic.thesis_id == thesis.id)
        ).all():
            session.delete(row)
        session.add(
            ThesisTopic(
                thesis_id=thesis.id,
                topic_id=topic_id,
                confidence=1.0,
                source="manual",
                locked=True,
                taxonomy_version=version,
            )
        )
        thesis.reviewed_at = utcnow()
        session.add(thesis)
    else:
        raise ValueError("Paper atau skripsi harus dipilih.")
    session.commit()


def mark_not_relevant(
    session: Session, paper: Paper | None = None, thesis: Thesis | None = None
) -> None:
    if paper is not None:
        for row in session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all():
            session.delete(row)
        paper.reviewed_at = utcnow()
        session.add(paper)
    elif thesis is not None:
        for row in session.exec(
            select(ThesisTopic).where(ThesisTopic.thesis_id == thesis.id)
        ).all():
            session.delete(row)
        thesis.reviewed_at = utcnow()
        session.add(thesis)
    else:
        raise ValueError("Paper atau skripsi harus dipilih.")
    session.commit()
