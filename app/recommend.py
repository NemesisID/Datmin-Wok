"""Rekomendasi dosen dari bukti publikasi dan bimbingan, dihitung saat query."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.classify import PAPER_THRESHOLD, Classifier
from app.config import get_settings
from app.fts import search_paper_ids
from app.models import (
    LABS,
    Lecturer,
    LecturerOpenAlexId,
    LecturerPaper,
    Paper,
    PaperTopic,
    Thesis,
    ThesisSupervisor,
    ThesisTopic,
    Topic,
    TopicLab,
    utcnow,
)

WEAK_BELOW = 0.20
STRONG_ABOVE = 0.45
COVERAGE_MIN_STRENGTH = 0.30
MAX_EVIDENCE_PAPERS = 5
MAX_EVIDENCE_THESES = 3
MAX_COMPARE = 3
FTS_RESULT_LIMIT = 100


@dataclass(frozen=True)
class TopicView:
    id: int
    name: str
    parent_id: int | None
    sort_order: int
    labs: tuple[str, ...] = ()

    @property
    def is_root(self) -> bool:
        return self.parent_id is None


@dataclass(frozen=True)
class SearchFilters:
    lab: str = ""
    topic_ids: tuple[int, ...] = ()
    subtopic_ids: tuple[int, ...] = ()
    year_from: int | None = None
    year_to: int | None = None
    query: str = ""
    current_year: int | None = None


@dataclass
class FilterOptions:
    roots: list[TopicView]
    subtopics: list[TopicView]
    labs: tuple[str, ...] = LABS


@dataclass
class TopicScore:
    topic: TopicView
    strength: float
    score: float
    label: str
    paper_count: int = 0
    thesis_count: int = 0


@dataclass
class PaperEvidence:
    paper: Paper
    topics: list[TopicView]
    relevance: float = 0.0
    direct: bool = False


@dataclass
class ThesisEvidence:
    thesis: Thesis
    topics: list[TopicView]
    relevance: float = 0.0


@dataclass
class LecturerView:
    lecturer: Lecturer
    rank: int = 0
    final: float = 0.0
    label: str = "Belum ada data"
    topics: list[TopicScore] = field(default_factory=list)
    papers: list[PaperEvidence] = field(default_factory=list)
    theses: list[ThesisEvidence] = field(default_factory=list)
    evidence_count: int = 0
    has_data: bool = True


@dataclass
class Recommendation:
    results: list[LecturerView] = field(default_factory=list)
    all_lecturers: list[LecturerView] = field(default_factory=list)
    no_data: list[LecturerView] = field(default_factory=list)
    effective_topics: list[TopicView] = field(default_factory=list)
    query_topics: list[TopicView] = field(default_factory=list)
    has_criteria: bool = False
    no_data_state: bool = False
    stale: bool = False
    stale_days: int = 90
    latest_sync: datetime | None = None


@dataclass
class LecturerProfile:
    lecturer: Lecturer
    topics_by_lab: dict[str, list[TopicScore]]
    top_topics: list[TopicScore]
    papers: list[PaperEvidence]
    theses: list[ThesisEvidence]
    paper_count: int
    thesis_count: int
    openalex_ids: list[LecturerOpenAlexId]
    last_synced_at: datetime | None
    stale: bool
    stale_days: int
    has_data: bool
    coverage_years: int
    scholar_url: str | None


@dataclass
class TopicLecturer:
    lecturer: Lecturer
    topic: TopicView
    label: str
    paper_count: int
    thesis_count: int
    score: float = 0.0


@dataclass
class TopicEntry:
    topic: TopicView
    lecturers: list[TopicLecturer] = field(default_factory=list)


@dataclass
class TopicExplorer:
    groups: dict[str, list[TopicEntry]] = field(default_factory=dict)
    no_data_state: bool = False
    stale: bool = False
    stale_days: int = 90
    latest_sync: datetime | None = None


@dataclass
class _Index:
    lecturers: list[Lecturer]
    topics: dict[int, TopicView]
    papers: dict[int, Paper]
    theses: dict[int, Thesis]
    paper_lecturers: dict[int, set[int]]
    paper_labels: dict[int, list[PaperTopic]]
    thesis_labels: dict[int, list[ThesisTopic]]
    papers_by_lecturer: dict[int, list[int]]
    theses_by_lecturer: dict[int, list[int]]
    openalex_ids: dict[int, list[LecturerOpenAlexId]]


@dataclass
class _Resolved:
    allowed_topic_ids: set[int]
    requested_topic_ids: set[int]
    subtopic_ids: set[int]
    effective_topic_ids: set[int]
    effective_topics: list[TopicView]
    query_topics: list[TopicView]
    has_criteria: bool


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def load_taxonomy(session: Session) -> list[TopicView]:
    topics = session.exec(select(Topic).where(Topic.active.is_(True))).all()
    labs: dict[int, list[str]] = defaultdict(list)
    for row in session.exec(select(TopicLab)).all():
        if row.lab in LABS:
            labs[row.topic_id].append(row.lab)
    views = [
        TopicView(
            id=topic.id,
            name=topic.name,
            parent_id=topic.parent_id,
            sort_order=topic.sort_order,
            labs=tuple(lab for lab in LABS if lab in labs.get(topic.id, [])),
        )
        for topic in topics
    ]
    return sorted(views, key=lambda item: (item.parent_id is not None, item.sort_order, item.name))


def filter_options(session: Session, lab: str = "") -> FilterOptions:
    if lab and lab not in LABS:
        raise ValueError("Lab tidak dikenal.")
    topics = load_taxonomy(session)
    roots = [topic for topic in topics if topic.is_root and (not lab or lab in topic.labs)]
    root_ids = {topic.id for topic in roots}
    subtopics = [topic for topic in topics if topic.parent_id in root_ids]
    return FilterOptions(roots=roots, subtopics=subtopics)


def recency(year: int | None, current_year: int, half_life: float) -> float:
    if year is None:
        return 1.0
    age = max(0, current_year - year)
    return 0.5 ** (age / half_life) if half_life > 0 else 0.0


def shrink(strength: float) -> float:
    return strength / (strength + 2) if strength > 0 else 0.0


def evidence_label(score: float) -> str:
    if score < WEAK_BELOW:
        return "Lemah"
    if score <= STRONG_ABOVE:
        return "Cukup"
    return "Kuat"


def _index(session: Session) -> _Index:
    lecturers = list(
        session.exec(
            select(Lecturer).where(Lecturer.active.is_(True)).order_by(Lecturer.name)
        ).all()
    )
    lecturer_ids = {lecturer.id for lecturer in lecturers if lecturer.id is not None}
    topics = {topic.id: topic for topic in load_taxonomy(session)}

    paper_lecturers: dict[int, set[int]] = defaultdict(set)
    papers_by_lecturer: dict[int, list[int]] = defaultdict(list)
    if lecturer_ids:
        links = session.exec(
            select(LecturerPaper).where(LecturerPaper.lecturer_id.in_(lecturer_ids))
        ).all()
        for link in links:
            paper_lecturers[link.paper_id].add(link.lecturer_id)
            papers_by_lecturer[link.lecturer_id].append(link.paper_id)

    paper_ids = set(paper_lecturers)
    papers = {
        paper.id: paper
        for paper in (
            session.exec(select(Paper).where(Paper.id.in_(paper_ids))).all() if paper_ids else []
        )
    }
    paper_labels: dict[int, list[PaperTopic]] = defaultdict(list)
    if paper_ids:
        for row in session.exec(select(PaperTopic).where(PaperTopic.paper_id.in_(paper_ids))).all():
            paper_labels[row.paper_id].append(row)

    theses_by_lecturer: dict[int, list[int]] = defaultdict(list)
    thesis_ids: set[int] = set()
    if lecturer_ids:
        thesis_links = session.exec(
            select(ThesisSupervisor).where(ThesisSupervisor.lecturer_id.in_(lecturer_ids))
        ).all()
        for link in thesis_links:
            thesis_ids.add(link.thesis_id)
            theses_by_lecturer[link.lecturer_id].append(link.thesis_id)

    theses = {
        thesis.id: thesis
        for thesis in (
            session.exec(select(Thesis).where(Thesis.id.in_(thesis_ids))).all()
            if thesis_ids
            else []
        )
    }
    thesis_labels: dict[int, list[ThesisTopic]] = defaultdict(list)
    if thesis_ids:
        for row in session.exec(
            select(ThesisTopic).where(ThesisTopic.thesis_id.in_(thesis_ids))
        ).all():
            thesis_labels[row.thesis_id].append(row)

    openalex_ids: dict[int, list[LecturerOpenAlexId]] = defaultdict(list)
    if lecturer_ids:
        for row in session.exec(
            select(LecturerOpenAlexId).where(LecturerOpenAlexId.lecturer_id.in_(lecturer_ids))
        ).all():
            openalex_ids[row.lecturer_id].append(row)

    return _Index(
        lecturers=lecturers,
        topics=topics,
        papers=papers,
        theses=theses,
        paper_lecturers=paper_lecturers,
        paper_labels=paper_labels,
        thesis_labels=thesis_labels,
        papers_by_lecturer=papers_by_lecturer,
        theses_by_lecturer=theses_by_lecturer,
        openalex_ids=openalex_ids,
    )


def _resolve(session: Session, index: _Index, filters: SearchFilters) -> _Resolved:
    if filters.lab and filters.lab not in LABS:
        raise ValueError("Lab tidak dikenal.")

    roots = [topic for topic in index.topics.values() if topic.is_root]
    allowed = {topic.id for topic in roots if not filters.lab or filters.lab in topic.labs}

    requested: set[int] = set()
    for topic_id in dict.fromkeys(filters.topic_ids):
        topic = index.topics.get(topic_id)
        if topic is None or not topic.is_root:
            raise ValueError("Topik yang dipilih tidak aktif.")
        if topic.id not in allowed:
            raise ValueError(f"Topik {topic.name} tidak ada di lab yang dipilih.")
        requested.add(topic.id)

    subtopics: set[int] = set()
    for topic_id in dict.fromkeys(filters.subtopic_ids):
        topic = index.topics.get(topic_id)
        if topic is None or topic.parent_id is None:
            raise ValueError("Sub-topik yang dipilih tidak aktif.")
        if topic.parent_id not in allowed:
            raise ValueError(f"Sub-topik {topic.name} tidak ada di lab yang dipilih.")
        subtopics.add(topic.id)
        requested.add(topic.parent_id)

    query_topics: list[TopicView] = []
    if filters.query.strip():
        classifier = Classifier.from_session(session)
        predictions = classifier.classify(filters.query, PAPER_THRESHOLD)
        for prediction in predictions:
            topic = index.topics.get(prediction.topic_id)
            if topic is not None and topic.id in allowed:
                query_topics.append(topic)

    effective_ids = set(requested)
    effective_ids.update(topic.id for topic in query_topics)
    effective_topics = sorted(
        (index.topics[topic_id] for topic_id in effective_ids),
        key=lambda item: (item.sort_order, item.name),
    )
    has_criteria = bool(filters.query.strip() or requested or subtopics)
    return _Resolved(
        allowed_topic_ids=allowed,
        requested_topic_ids=requested,
        subtopic_ids=subtopics,
        effective_topic_ids=effective_ids,
        effective_topics=effective_topics,
        query_topics=query_topics,
        has_criteria=has_criteria,
    )


def _year_ok(paper: Paper, filters: SearchFilters) -> bool:
    if filters.year_from is not None and (paper.year is None or paper.year < filters.year_from):
        return False
    return not (
        filters.year_to is not None and (paper.year is None or paper.year > filters.year_to)
    )


def _subtopic_ok(label: PaperTopic, filters: SearchFilters) -> bool:
    return not filters.subtopic_ids or label.subtopic_id in filters.subtopic_ids


def _topic_scores(
    index: _Index,
    lecturer_id: int,
    topic_ids: set[int],
    filters: SearchFilters,
    current_year: int,
    half_life: float,
    thesis_lambda: float,
) -> dict[int, TopicScore]:
    values = {
        topic_id: TopicScore(
            topic=index.topics[topic_id],
            strength=0.0,
            score=0.0,
            label="Lemah",
        )
        for topic_id in topic_ids
        if topic_id in index.topics
    }
    for paper_id in index.papers_by_lecturer.get(lecturer_id, []):
        paper = index.papers.get(paper_id)
        if paper is None or not _year_ok(paper, filters):
            continue
        weight = recency(paper.year, current_year, half_life)
        for label in index.paper_labels.get(paper_id, []):
            item = values.get(label.topic_id)
            if item is None or not _subtopic_ok(label, filters):
                continue
            item.strength += weight * max(0.0, label.confidence)
            item.paper_count += 1

    if not filters.subtopic_ids:
        for thesis_id in index.theses_by_lecturer.get(lecturer_id, []):
            for label in index.thesis_labels.get(thesis_id, []):
                item = values.get(label.topic_id)
                if item is None:
                    continue
                item.strength += thesis_lambda * max(0.0, label.confidence)
                item.thesis_count += 1

    for item in values.values():
        item.score = shrink(item.strength)
        item.label = evidence_label(item.score)
    return values


def _aggregate_topic_score(scores: dict[int, TopicScore], topic_ids: set[int]) -> float:
    if not topic_ids:
        return 0.0
    covered = sum(
        1
        for topic_id in topic_ids
        if topic_id in scores and scores[topic_id].strength >= COVERAGE_MIN_STRENGTH
    )
    coverage = covered / len(topic_ids)
    total = sum(item.score for item in scores.values())
    return total * (0.6 + 0.4 * coverage)


def _top_topics(scores: dict[int, TopicScore], limit: int = 3) -> list[TopicScore]:
    items = [item for item in scores.values() if item.strength > 0]
    items.sort(key=lambda item: (-item.score, -item.strength, item.topic.name))
    return items[:limit]


def _topic_views(index: _Index, topic_ids: set[int]) -> list[TopicView]:
    topics = [index.topics[topic_id] for topic_id in topic_ids if topic_id in index.topics]
    return sorted(topics, key=lambda item: (item.sort_order, item.name))


def _direct_matches(
    session: Session,
    index: _Index,
    filters: SearchFilters,
    resolved: _Resolved,
) -> dict[int, set[int]]:
    if not filters.query.strip():
        return {}
    matched_ids = search_paper_ids(session, filters.query, limit=FTS_RESULT_LIMIT)
    direct: dict[int, set[int]] = defaultdict(set)
    for paper_id in matched_ids:
        paper = index.papers.get(paper_id)
        if paper is None or not _year_ok(paper, filters):
            continue
        labels = index.paper_labels.get(paper_id, [])
        if resolved.subtopic_ids and not any(_subtopic_ok(label, filters) for label in labels):
            continue
        if filters.lab and not any(
            index.topics.get(label.topic_id) and filters.lab in index.topics[label.topic_id].labs
            for label in labels
        ):
            continue
        if resolved.requested_topic_ids and not any(
            label.topic_id in resolved.requested_topic_ids for label in labels
        ):
            continue
        for lecturer_id in index.paper_lecturers.get(paper_id, set()):
            direct[lecturer_id].add(paper_id)
    return direct


def _evidence(
    index: _Index,
    lecturer_id: int,
    filters: SearchFilters,
    resolved: _Resolved,
    direct_ids: set[int],
    current_year: int,
    half_life: float,
) -> tuple[list[PaperEvidence], list[ThesisEvidence], int]:
    papers: list[PaperEvidence] = []
    for paper_id in index.papers_by_lecturer.get(lecturer_id, []):
        paper = index.papers.get(paper_id)
        if paper is None or not _year_ok(paper, filters):
            continue
        labels = index.paper_labels.get(paper_id, [])
        if resolved.subtopic_ids and not any(_subtopic_ok(label, filters) for label in labels):
            continue
        if filters.lab and not any(
            index.topics.get(label.topic_id) and filters.lab in index.topics[label.topic_id].labs
            for label in labels
        ):
            continue
        if resolved.requested_topic_ids and not any(
            label.topic_id in resolved.requested_topic_ids for label in labels
        ):
            continue

        label_topics = {
            label.topic_id
            for label in labels
            if label.topic_id in resolved.effective_topic_ids and _subtopic_ok(label, filters)
        }
        direct = paper_id in direct_ids
        if not label_topics and not direct:
            continue
        weight = recency(paper.year, current_year, half_life)
        relevance = max(
            (
                weight * max(0.0, label.confidence)
                for label in labels
                if label.topic_id in label_topics
            ),
            default=0.0,
        )
        if direct:
            relevance += weight
        topics = _topic_views(index, label_topics or {label.topic_id for label in labels})
        papers.append(
            PaperEvidence(
                paper=paper,
                topics=topics,
                relevance=relevance,
                direct=direct,
            )
        )

    theses: list[ThesisEvidence] = []
    if not filters.subtopic_ids:
        for thesis_id in index.theses_by_lecturer.get(lecturer_id, []):
            thesis = index.theses.get(thesis_id)
            if thesis is None:
                continue
            labels = index.thesis_labels.get(thesis_id, [])
            label_topics = {
                label.topic_id for label in labels if label.topic_id in resolved.effective_topic_ids
            }
            if not label_topics:
                continue
            relevance = max(
                (max(0.0, label.confidence) for label in labels if label.topic_id in label_topics),
                default=0.0,
            )
            theses.append(
                ThesisEvidence(
                    thesis=thesis,
                    topics=_topic_views(index, label_topics),
                    relevance=relevance,
                )
            )

    papers.sort(
        key=lambda item: (
            not item.direct,
            -item.relevance,
            -(item.paper.year or 0),
            item.paper.title,
        )
    )
    theses.sort(key=lambda item: (-item.relevance, -(item.thesis.year or 0), item.thesis.title))
    return papers, theses, len(papers) + len(theses)


def _latest_sync(index: _Index) -> datetime | None:
    values = [_aware(lecturer.last_synced_at) for lecturer in index.lecturers]
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _stale(latest: datetime | None, now: datetime, days: int) -> bool:
    return latest is None or latest < now - timedelta(days=days)


def _no_data_view(lecturer: Lecturer) -> LecturerView:
    return LecturerView(lecturer=lecturer, has_data=False)


def _build_view(
    index: _Index,
    lecturer: Lecturer,
    scores: dict[int, TopicScore],
    filters: SearchFilters,
    resolved: _Resolved,
    direct_ids: set[int],
    current_year: int,
    half_life: float,
) -> LecturerView:
    papers, theses, evidence_count = _evidence(
        index,
        lecturer.id,
        filters,
        resolved,
        direct_ids,
        current_year,
        half_life,
    )
    all_papers = index.papers_by_lecturer.get(lecturer.id, [])
    all_theses = index.theses_by_lecturer.get(lecturer.id, [])
    return LecturerView(
        lecturer=lecturer,
        topics=_top_topics(scores),
        papers=papers[:MAX_EVIDENCE_PAPERS],
        theses=theses[:MAX_EVIDENCE_THESES],
        evidence_count=evidence_count,
        has_data=bool(all_papers or all_theses),
    )


def _browse_views(
    index: _Index,
    filters: SearchFilters,
    resolved: _Resolved,
    current_year: int,
    half_life: float,
    thesis_lambda: float,
) -> list[LecturerView]:
    views: list[LecturerView] = []
    browse_resolved = _Resolved(
        allowed_topic_ids=resolved.allowed_topic_ids,
        requested_topic_ids=set(),
        subtopic_ids=set(),
        effective_topic_ids=resolved.allowed_topic_ids,
        effective_topics=resolved.effective_topics,
        query_topics=[],
        has_criteria=False,
    )
    for lecturer in index.lecturers:
        scores = _topic_scores(
            index,
            lecturer.id,
            resolved.allowed_topic_ids,
            filters,
            current_year,
            half_life,
            thesis_lambda,
        )
        top = _top_topics(scores)
        has_data = bool(
            index.papers_by_lecturer.get(lecturer.id) or index.theses_by_lecturer.get(lecturer.id)
        )
        if not has_data:
            views.append(_no_data_view(lecturer))
            continue
        if (
            filters.lab or filters.year_from is not None or filters.year_to is not None
        ) and not top:
            continue
        _, _, evidence_count = _evidence(
            index,
            lecturer.id,
            filters,
            browse_resolved,
            set(),
            current_year,
            half_life,
        )
        views.append(
            LecturerView(
                lecturer=lecturer,
                topics=top,
                evidence_count=evidence_count,
                has_data=True,
            )
        )
    views.sort(key=lambda item: (not item.has_data, item.lecturer.name))
    return views


def recommend(
    session: Session,
    filters: SearchFilters,
    *,
    now: datetime | None = None,
) -> Recommendation:
    index = _index(session)
    resolved = _resolve(session, index, filters)
    settings = get_settings()
    now = now or utcnow()
    current_year = filters.current_year or now.year
    half_life = settings.recency_half_life_years
    thesis_lambda = settings.thesis_lambda
    latest = _latest_sync(index)
    no_data_state = not any(
        index.papers_by_lecturer.get(lecturer.id) or index.theses_by_lecturer.get(lecturer.id)
        for lecturer in index.lecturers
    )

    if not resolved.has_criteria:
        all_views = _browse_views(index, filters, resolved, current_year, half_life, thesis_lambda)
        return Recommendation(
            all_lecturers=all_views,
            no_data=[view for view in all_views if not view.has_data],
            effective_topics=resolved.effective_topics,
            has_criteria=False,
            no_data_state=no_data_state,
            stale=_stale(latest, now, settings.stale_days) and not no_data_state,
            stale_days=settings.stale_days,
            latest_sync=latest,
        )

    direct = _direct_matches(session, index, filters, resolved)
    results: list[LecturerView] = []
    for lecturer in index.lecturers:
        scores = _topic_scores(
            index,
            lecturer.id,
            resolved.effective_topic_ids,
            filters,
            current_year,
            half_life,
            thesis_lambda,
        )
        topic_part = _aggregate_topic_score(scores, resolved.effective_topic_ids)
        direct_strength = 0.0
        for paper_id in direct.get(lecturer.id, set()):
            paper = index.papers.get(paper_id)
            if paper is not None:
                direct_strength += recency(paper.year, current_year, half_life)
        final = topic_part + shrink(direct_strength)
        if final <= 0:
            continue
        view = _build_view(
            index,
            lecturer,
            scores,
            filters,
            resolved,
            direct.get(lecturer.id, set()),
            current_year,
            half_life,
        )
        view.final = final
        view.label = evidence_label(final)
        results.append(view)

    results.sort(
        key=lambda item: (
            -item.final,
            -item.evidence_count,
            item.lecturer.name,
        )
    )
    for rank, view in enumerate(results, start=1):
        view.rank = rank

    no_data = [
        _no_data_view(lecturer)
        for lecturer in index.lecturers
        if not index.papers_by_lecturer.get(lecturer.id)
        and not index.theses_by_lecturer.get(lecturer.id)
    ]
    return Recommendation(
        results=results,
        no_data=no_data,
        effective_topics=resolved.effective_topics,
        query_topics=resolved.query_topics,
        has_criteria=True,
        no_data_state=no_data_state,
        stale=_stale(latest, now, settings.stale_days) and not no_data_state,
        stale_days=settings.stale_days,
        latest_sync=latest,
    )


def _paper_evidence_for_profile(
    index: _Index,
    paper_id: int,
    current_year: int,
    half_life: float,
) -> PaperEvidence:
    paper = index.papers[paper_id]
    labels = index.paper_labels.get(paper_id, [])
    weight = recency(paper.year, current_year, half_life)
    relevance = max(
        (weight * max(0.0, label.confidence) for label in labels),
        default=weight,
    )
    topics = _topic_views(index, {label.topic_id for label in labels})
    return PaperEvidence(paper=paper, topics=topics, relevance=relevance)


def _profile_from_index(
    index: _Index,
    lecturer: Lecturer,
    *,
    topic_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    now: datetime | None = None,
) -> LecturerProfile:
    settings = get_settings()
    now = now or utcnow()
    current_year = now.year
    filters = SearchFilters(current_year=current_year)
    scores = _topic_scores(
        index,
        lecturer.id,
        set(index.topics),
        filters,
        current_year,
        settings.recency_half_life_years,
        settings.thesis_lambda,
    )
    topics_by_lab: dict[str, list[TopicScore]] = {}
    for lab in LABS:
        items = [
            item
            for item in scores.values()
            if item.strength > 0 and lab in item.topic.labs and item.topic.is_root
        ]
        items.sort(key=lambda item: (-item.score, -item.strength, item.topic.name))
        topics_by_lab[lab] = items

    all_paper_ids = sorted(
        index.papers_by_lecturer.get(lecturer.id, []),
        key=lambda paper_id: (
            -(index.papers[paper_id].year or 0),
            index.papers[paper_id].title,
        ),
    )
    papers: list[PaperEvidence] = []
    for paper_id in all_paper_ids:
        paper = index.papers[paper_id]
        if year_from is not None and (paper.year is None or paper.year < year_from):
            continue
        if year_to is not None and (paper.year is None or paper.year > year_to):
            continue
        labels = index.paper_labels.get(paper_id, [])
        if topic_id is not None and not any(label.topic_id == topic_id for label in labels):
            continue
        papers.append(
            _paper_evidence_for_profile(
                index,
                paper_id,
                current_year,
                settings.recency_half_life_years,
            )
        )

    thesis_ids = sorted(
        index.theses_by_lecturer.get(lecturer.id, []),
        key=lambda thesis_id: (
            -(index.theses[thesis_id].year or 0),
            index.theses[thesis_id].title,
        ),
    )
    theses = [
        ThesisEvidence(
            thesis=index.theses[thesis_id],
            topics=_topic_views(
                index,
                {label.topic_id for label in index.thesis_labels.get(thesis_id, [])},
            ),
            relevance=max(
                (max(0.0, label.confidence) for label in index.thesis_labels.get(thesis_id, [])),
                default=0.0,
            ),
        )
        for thesis_id in thesis_ids
    ]

    last_synced = _aware(lecturer.last_synced_at)
    top = _top_topics(scores)
    has_data = bool(
        index.papers_by_lecturer.get(lecturer.id) or index.theses_by_lecturer.get(lecturer.id)
    )
    return LecturerProfile(
        lecturer=lecturer,
        topics_by_lab=topics_by_lab,
        top_topics=top,
        papers=papers,
        theses=theses,
        paper_count=len(index.papers_by_lecturer.get(lecturer.id, [])),
        thesis_count=len(index.theses_by_lecturer.get(lecturer.id, [])),
        openalex_ids=index.openalex_ids.get(lecturer.id, []),
        last_synced_at=last_synced,
        stale=_stale(last_synced, now, settings.stale_days) and has_data,
        stale_days=settings.stale_days,
        has_data=has_data,
        coverage_years=settings.publication_window_years,
        scholar_url=(
            f"https://scholar.google.com/citations?user={lecturer.scholar_id}"
            if lecturer.scholar_id
            else None
        ),
    )


def lecturer_profile(
    session: Session,
    lecturer_id: int,
    *,
    topic_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    now: datetime | None = None,
) -> LecturerProfile | None:
    index = _index(session)
    lecturer = next((item for item in index.lecturers if item.id == lecturer_id), None)
    if lecturer is None:
        return None
    return _profile_from_index(
        index,
        lecturer,
        topic_id=topic_id,
        year_from=year_from,
        year_to=year_to,
        now=now,
    )


def compare_profiles(
    session: Session,
    lecturer_ids: list[int],
    *,
    now: datetime | None = None,
) -> list[LecturerProfile]:
    if len(lecturer_ids) > MAX_COMPARE:
        raise ValueError(f"Maksimal {MAX_COMPARE} dosen untuk dibandingkan.")
    index = _index(session)
    by_id = {lecturer.id: lecturer for lecturer in index.lecturers}
    profiles = []
    for lecturer_id in dict.fromkeys(lecturer_ids):
        lecturer = by_id.get(lecturer_id)
        if lecturer is None:
            raise ValueError(f"Dosen {lecturer_id} tidak ditemukan.")
        profiles.append(_profile_from_index(index, lecturer, now=now))
    return profiles


def topic_explorer(
    session: Session,
    *,
    lab: str = "",
    now: datetime | None = None,
    limit: int = 5,
) -> TopicExplorer:
    if lab and lab not in LABS:
        raise ValueError("Lab tidak dikenal.")
    index = _index(session)
    settings = get_settings()
    now = now or utcnow()
    current_year = now.year
    latest = _latest_sync(index)
    roots = [
        topic for topic in index.topics.values() if topic.is_root and (not lab or lab in topic.labs)
    ]
    roots.sort(key=lambda item: (item.sort_order, item.name))
    groups: dict[str, list[TopicEntry]] = {}
    for group_lab in [lab] if lab else list(LABS):
        entries: list[TopicEntry] = []
        for topic in roots:
            if group_lab not in topic.labs:
                continue
            candidates: list[TopicLecturer] = []
            for lecturer in index.lecturers:
                scores = _topic_scores(
                    index,
                    lecturer.id,
                    {topic.id},
                    SearchFilters(current_year=current_year),
                    current_year,
                    settings.recency_half_life_years,
                    settings.thesis_lambda,
                )
                score = scores[topic.id]
                if score.strength <= 0:
                    continue
                candidates.append(
                    TopicLecturer(
                        lecturer=lecturer,
                        topic=topic,
                        label=score.label,
                        paper_count=score.paper_count,
                        thesis_count=score.thesis_count,
                        score=score.score,
                    )
                )
            candidates.sort(
                key=lambda item: (
                    -item.score,
                    -item.paper_count - item.thesis_count,
                    item.lecturer.name,
                )
            )
            entries.append(TopicEntry(topic=topic, lecturers=candidates[:limit]))
        groups[group_lab] = entries

    no_data_state = not any(
        index.papers_by_lecturer.get(lecturer.id) or index.theses_by_lecturer.get(lecturer.id)
        for lecturer in index.lecturers
    )
    return TopicExplorer(
        groups=groups,
        no_data_state=no_data_state,
        stale=_stale(latest, now, settings.stale_days) and not no_data_state,
        stale_days=settings.stale_days,
        latest_sync=latest,
    )
