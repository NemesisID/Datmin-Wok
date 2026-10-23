"""Evaluasi classifier terhadap golden set berlabel manual."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from app.classify import PAPER_THRESHOLD, Classifier
from app.taxonomy import normalize_keyword

TOPIC_SEPARATOR = ";"


@dataclass
class GoldenRow:
    title: str
    abstract: str
    topics: set[str]


@dataclass
class TopicScore:
    name: str
    support: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


@dataclass
class EvalReport:
    rows: int
    micro_precision: float
    micro_recall: float
    micro_f1: float
    macro_f1: float
    topics: list[TopicScore] = field(default_factory=list)


def _normalize_topic(name: str) -> str:
    return normalize_keyword(name)


def load_golden(path: Path) -> list[GoldenRow]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = {name.strip().lower(): name for name in (reader.fieldnames or [])}
        if "judul" not in headers or "topik" not in headers:
            raise ValueError("Golden set butuh kolom 'judul' dan 'topik'.")

        rows = []
        for raw in reader:
            title = (raw.get(headers["judul"]) or "").strip()
            if not title:
                continue
            abstract = (raw.get(headers.get("abstrak", "")) or "").strip()
            topics = {
                part.strip()
                for part in (raw.get(headers["topik"]) or "").split(TOPIC_SEPARATOR)
                if part.strip()
            }
            rows.append(GoldenRow(title=title, abstract=abstract, topics=topics))
    if not rows:
        raise ValueError("Golden set tidak punya baris berisi judul.")
    return rows


def _score(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate(
    rows: list[GoldenRow], classifier: Classifier, threshold: float = PAPER_THRESHOLD
) -> EvalReport:
    display_names = {_normalize_topic(name): name for name in classifier.topic_names.values()}
    known = set(display_names)
    unknown = sorted(
        {topic for row in rows for topic in row.topics if _normalize_topic(topic) not in known}
    )
    if unknown:
        raise ValueError("Topik di golden set tidak ada di taksonomi: " + ", ".join(unknown))

    supports: dict[str, int] = {}
    true_positive: dict[str, int] = {}
    false_positive: dict[str, int] = {}
    false_negative: dict[str, int] = {}
    total_tp = total_fp = total_fn = 0

    for row in rows:
        gold = {_normalize_topic(topic) for topic in row.topics}
        predicted = {
            _normalize_topic(classifier.topic_names[prediction.topic_id])
            for prediction in classifier.classify(
                " ".join(part for part in (row.title, row.abstract) if part), threshold
            )
        }
        for topic in gold:
            supports[topic] = supports.get(topic, 0) + 1
        for topic in gold & predicted:
            true_positive[topic] = true_positive.get(topic, 0) + 1
            total_tp += 1
        for topic in predicted - gold:
            false_positive[topic] = false_positive.get(topic, 0) + 1
            total_fp += 1
        for topic in gold - predicted:
            false_negative[topic] = false_negative.get(topic, 0) + 1
            total_fn += 1

    topic_scores = []
    f1_values = []
    for topic in sorted(supports):
        tp = true_positive.get(topic, 0)
        fp = false_positive.get(topic, 0)
        fn = false_negative.get(topic, 0)
        precision, recall, f1 = _score(tp, fp, fn)
        topic_scores.append(
            TopicScore(
                name=display_names.get(topic, topic),
                support=supports[topic],
                tp=tp,
                fp=fp,
                fn=fn,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
        f1_values.append(f1)

    micro_precision, micro_recall, micro_f1 = _score(total_tp, total_fp, total_fn)
    return EvalReport(
        rows=len(rows),
        micro_precision=micro_precision,
        micro_recall=micro_recall,
        micro_f1=micro_f1,
        macro_f1=sum(f1_values) / len(f1_values) if f1_values else 0.0,
        topics=topic_scores,
    )
