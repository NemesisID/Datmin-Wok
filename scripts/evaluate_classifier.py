"""Evaluasi classifier terhadap golden set berlabel manual.

Jalankan: uv run python scripts/evaluate_classifier.py [path.csv]
Default: seeds/golden_set.csv (buat dari seeds/golden_set.example.csv).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

from app.classify import Classifier  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.evaluation import evaluate, load_golden  # noqa: E402
from app.taxonomy import get_taxonomy_version  # noqa: E402

DEFAULT_PATH = Path("seeds/golden_set.csv")
EXAMPLE_PATH = Path("seeds/golden_set.example.csv")
TARGET_ROWS = 150


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluasi classifier terhadap golden set.")
    parser.add_argument("path", nargs="?", type=Path, help="CSV golden set.")
    args = parser.parse_args(argv)

    path = args.path
    if path is None:
        if not DEFAULT_PATH.exists():
            print(f"Golden set belum ada: {DEFAULT_PATH}")
            print(f"Mulai dari contoh: {EXAMPLE_PATH}")
            print("Salin, lalu ganti label sesuai keputusan manual minimal 150 paper.")
            return 1
        path = DEFAULT_PATH

    try:
        rows = load_golden(path)
    except (FileNotFoundError, ValueError) as error:
        print(f"Gagal membaca golden set: {error}")
        return 1

    with Session(get_engine()) as session:
        classifier = Classifier.from_session(session)
        version = get_taxonomy_version(session)
        try:
            report = evaluate(rows, classifier)
        except ValueError as error:
            print(str(error))
            print("Impor taksonomi dulu: uv run python -m app.cli import-taxonomy")
            return 1

    print(f"Golden set: {path} ({report.rows} baris)")
    print(f"taxonomy_version: {version}")
    if path == EXAMPLE_PATH or report.rows < TARGET_ROWS:
        print(
            f"Catatan: target PRD minimal {TARGET_ROWS} paper berlabel manual. "
            "Angka ini baru sinyal awal."
        )
    print()
    print(f"Micro precision: {report.micro_precision:.3f}")
    print(f"Micro recall:    {report.micro_recall:.3f}")
    print(f"Micro F1:        {report.micro_f1:.3f}")
    print(f"Macro F1:        {report.macro_f1:.3f}")
    print()
    print(f"{'Topik':42} {'N':>4} {'TP':>4} {'FP':>4} {'FN':>4} {'P':>6} {'R':>6} {'F1':>6}")
    for score in report.topics:
        print(
            f"{score.name[:42]:42} {score.support:>4} {score.tp:>4} {score.fp:>4} "
            f"{score.fn:>4} {score.precision:>6.3f} {score.recall:>6.3f} {score.f1:>6.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
