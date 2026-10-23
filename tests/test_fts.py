from __future__ import annotations

from factories import make_paper

from app.fts import search_paper_ids


def test_fts_tracks_insert_update_and_delete(session) -> None:
    paper = make_paper(
        session,
        "Sistem Informasi Geografis untuk Pertanian",
        venue="Jurnal Sistem Informasi",
    )

    assert search_paper_ids(session, "sistem informasi") == [paper.id]
    assert search_paper_ids(session, "geografis") == [paper.id]
    assert search_paper_ids(session, "prediksi") == []

    paper.title = "Model Prediksi Curah Hujan"
    session.add(paper)
    session.commit()

    assert search_paper_ids(session, "geografis") == []
    assert search_paper_ids(session, "prediksi curah") == [paper.id]

    session.delete(paper)
    session.commit()

    assert search_paper_ids(session, "prediksi") == []


def test_fts_ignores_empty_query(session) -> None:
    make_paper(session, "Paper Apa Saja")
    assert search_paper_ids(session, "   ") == []


def test_fts_treats_operators_as_literal_words(session) -> None:
    make_paper(session, "Analisis Sentimen Ulasan")
    assert search_paper_ids(session, "sentimen OR twitter") == []
    assert search_paper_ids(session, 'sentimen AND "ulasan') == []
