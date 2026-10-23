from __future__ import annotations

from sqlmodel import Session

from app.dedupe import compute_title_hash
from app.models import Paper, Thesis, Topic, TopicKeyword
from app.taxonomy import normalize_keyword, set_taxonomy_version

MINIMAL_KEYWORDS = {
    "Data Mining": ["data mining", "klasifikasi", "clustering", "naive bayes"],
    "UI/UX": ["usability", "user experience", "design thinking"],
    "Analisis Sentimen": ["analisis sentimen", "sentiment analysis", "ulasan", "twitter"],
}


def seed_minimal_taxonomy(session: Session) -> dict[str, Topic]:
    mining = Topic(name="Data Mining", sort_order=10)
    uiux = Topic(name="UI/UX", sort_order=20)
    session.add_all([mining, uiux])
    session.commit()
    session.refresh(mining)
    session.refresh(uiux)

    sentiment = Topic(name="Analisis Sentimen", parent_id=mining.id, sort_order=11)
    umum = Topic(name="Umum", parent_id=mining.id, sort_order=12)
    session.add_all([sentiment, umum])
    session.commit()
    session.refresh(sentiment)
    session.refresh(umum)

    by_name = {
        "Data Mining": mining,
        "UI/UX": uiux,
        "Analisis Sentimen": sentiment,
        "Umum": umum,
    }
    for name, keywords in MINIMAL_KEYWORDS.items():
        topic = by_name[name]
        for keyword in keywords:
            session.add(
                TopicKeyword(
                    topic_id=topic.id,
                    keyword=keyword,
                    keyword_norm=normalize_keyword(keyword),
                )
            )
    set_taxonomy_version(session, 1)
    session.commit()
    return by_name


def make_paper(
    session: Session, title: str, *, abstract: str | None = None, venue: str = "", year: int = 2024
) -> Paper:
    paper = Paper(
        title=title,
        title_hash=compute_title_hash(title),
        year=year,
        venue=venue,
        abstract=abstract,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def make_thesis(session: Session, title: str, *, year: int = 2024) -> Thesis:
    thesis = Thesis(title=title, title_hash=compute_title_hash(title), year=year)
    session.add(thesis)
    session.commit()
    session.refresh(thesis)
    return thesis
