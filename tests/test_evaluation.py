from __future__ import annotations

import pytest

from app.classify import TopicPrediction
from app.evaluation import GoldenRow, evaluate, load_golden


class StubClassifier:
    topic_names = {1: "Data Mining", 2: "UI/UX"}

    def __init__(self, predictions: dict[str, list[int]]) -> None:
        self.predictions = predictions

    def classify(self, text: str, threshold: float) -> list[TopicPrediction]:
        return [
            TopicPrediction(topic_id=topic_id, subtopic_id=None, confidence=1.0)
            for topic_id in self.predictions.get(text, [])
        ]


def test_micro_and_macro_f1() -> None:
    rows = [
        GoldenRow(title="a", abstract="", topics={"Data Mining"}),
        GoldenRow(title="b", abstract="", topics={"Data Mining", "UI/UX"}),
        GoldenRow(title="c", abstract="", topics={"UI/UX"}),
    ]
    classifier = StubClassifier({"a": [1], "b": [1], "c": [1]})

    report = evaluate(rows, classifier)  # type: ignore[arg-type]

    assert report.rows == 3
    assert report.micro_precision == pytest.approx(2 / 3)
    assert report.micro_recall == pytest.approx(0.5)
    assert report.micro_f1 == pytest.approx(4 / 7)
    assert report.macro_f1 == pytest.approx(0.4)
    mining = next(score for score in report.topics if score.name == "Data Mining")
    assert (mining.support, mining.tp, mining.fp, mining.fn) == (2, 2, 1, 0)
    assert mining.f1 == pytest.approx(0.8)


def test_evaluate_rejects_unknown_topic() -> None:
    rows = [GoldenRow(title="a", abstract="", topics={"Topik Hilang"})]

    with pytest.raises(ValueError, match="Topik Hilang"):
        evaluate(rows, StubClassifier({}))  # type: ignore[arg-type]


def test_load_golden_reads_semicolon_topics(tmp_path) -> None:
    path = tmp_path / "golden.csv"
    path.write_text(
        'Judul,Abstrak,Topik\n"Judul Satu","Abstrak satu","Data Mining;UI/UX"\n"Judul Dua","",\n',
        encoding="utf-8",
    )

    rows = load_golden(path)

    assert rows[0].topics == {"Data Mining", "UI/UX"}
    assert rows[0].abstract == "Abstrak satu"
    assert rows[1].topics == set()


def test_load_golden_requires_headers(tmp_path) -> None:
    path = tmp_path / "salah.csv"
    path.write_text("title,topics\na,b\n", encoding="utf-8")

    with pytest.raises(ValueError, match="judul"):
        load_golden(path)
