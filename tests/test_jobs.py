from __future__ import annotations

import json

from factories import make_paper, seed_minimal_taxonomy
from sqlmodel import Session, select

from app import jobs
from app.config import Settings
from app.models import LlmCache, PaperTopic, SyncJob


class FakeProvider:
    name = "fake"

    def __init__(self, topic_id: int, subtopic_id: int | None) -> None:
        self.topic_id = topic_id
        self.subtopic_id = subtopic_id
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return json.dumps(
            {
                "results": [
                    {
                        "index": 0,
                        "labels": [
                            {
                                "topic_id": self.topic_id,
                                "subtopic_id": self.subtopic_id,
                                "confidence": 0.9,
                            }
                        ],
                    }
                ]
            }
        )

    def close(self) -> None:
        return None


def test_sync_reports_invalid_llm_config(monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(use_llm=True, llm_provider="lain", llm_model="model"),
    )

    assert jobs.cmd_sync(False, None) == 1


def test_targeted_reclassify_only_touches_topic_scope(session, engine, monkeypatch) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    mining_id = taxonomy["Data Mining"].id
    matched = make_paper(session, "data mining klasifikasi clustering naive bayes")
    stale = make_paper(session, "Judul lama tanpa kata kunci")
    unrelated = make_paper(session, "usability design thinking")
    session.add(
        PaperTopic(
            paper_id=stale.id,
            topic_id=mining_id,
            confidence=0.8,
            source="rule",
            taxonomy_version=1,
        )
    )
    session.add(SyncJob(source=f"reclassify:{mining_id}", status="pending"))
    session.commit()

    monkeypatch.setattr(jobs, "get_engine", lambda: engine)
    monkeypatch.setattr(jobs, "get_settings", lambda: Settings(use_llm=False))

    assert jobs.cmd_reclassify() == 0

    with Session(engine) as check:
        job = check.exec(select(SyncJob).where(SyncJob.source == f"reclassify:{mining_id}")).one()
        assert job.status == "done"
        assert job.new_papers == 1
        matched_topics = check.exec(
            select(PaperTopic).where(PaperTopic.paper_id == matched.id)
        ).all()
        stale_topics = check.exec(select(PaperTopic).where(PaperTopic.paper_id == stale.id)).all()
        unrelated_topics = check.exec(
            select(PaperTopic).where(PaperTopic.paper_id == unrelated.id)
        ).all()

    assert [row.topic_id for row in matched_topics] == [mining_id]
    assert stale_topics == []
    assert unrelated_topics == []


def test_reclassify_job_uses_llm_and_reuses_cache(session, engine, monkeypatch) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    mining_id = topics["Data Mining"].id
    provider = FakeProvider(mining_id, topics["Umum"].id)
    session.add(SyncJob(source="reclassify", status="pending"))
    session.commit()

    monkeypatch.setattr(jobs, "get_engine", lambda: engine)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(use_llm=True, llm_provider="openai", llm_model="uji"),
    )
    monkeypatch.setattr(jobs, "build_llm_provider", lambda settings: provider)

    assert jobs.cmd_reclassify() == 0
    with Session(engine) as check:
        label = check.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).one()
        assert label.source == "llm"
        assert label.topic_id == mining_id
        assert len(check.exec(select(LlmCache)).all()) == 1

    with Session(engine) as session:
        session.add(SyncJob(source="reclassify", status="pending"))
        session.commit()

    assert jobs.cmd_reclassify() == 0
    assert provider.calls == 1
    with Session(engine) as check:
        assert len(check.exec(select(LlmCache)).all()) == 1
        label = check.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).one()
        assert label.source == "llm"
