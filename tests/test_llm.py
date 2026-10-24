from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from factories import make_paper, seed_minimal_taxonomy
from sqlmodel import select

from app.classify import Classifier, reclassify_papers
from app.config import Settings
from app.llm import (
    LlmError,
    OllamaProvider,
    OpenAICompatibleProvider,
    build_llm_provider,
    classify_papers,
    content_hash,
)
from app.models import LlmCache, PaperTopic, utcnow
from app.taxonomy import get_taxonomy_version


class FakeProvider:
    name = "fake"

    def __init__(self, content: str | Callable[[str], str]) -> None:
        self.content = content
        self.calls = 0
        self.prompts: list[str] = []
        self.closed = False

    def complete(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if callable(self.content):
            return self.content(prompt)
        return self.content

    def close(self) -> None:
        self.closed = True


def llm_reply(topic_id: int, subtopic_id: int | None, confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "results": [
                {
                    "index": 0,
                    "labels": [
                        {
                            "topic_id": topic_id,
                            "subtopic_id": subtopic_id,
                            "confidence": confidence,
                        }
                    ],
                }
            ]
        }
    )


def test_content_hash_includes_taxonomy_version() -> None:
    assert content_hash("Judul", "Abstrak", 1) != content_hash("Judul", "Abstrak", 2)
    assert content_hash("Judul", "Abstrak", 1) == content_hash(" Judul ", "Abstrak", 1)


def test_build_provider_disabled() -> None:
    settings = Settings(use_llm=False, llm_provider="openai", llm_model="model")
    assert build_llm_provider(settings) is None


def test_build_provider_requires_model() -> None:
    settings = Settings(use_llm=True, llm_provider="openai", llm_model="")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        build_llm_provider(settings)


def test_build_provider_rejects_unknown_provider() -> None:
    settings = Settings(use_llm=True, llm_provider="lain", llm_model="model")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        build_llm_provider(settings)


def test_openai_compatible_provider_sends_bearer_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization", "")
        payload = json.loads(request.content)
        seen["model"] = payload["model"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            "https://contoh.test/v1", "model-uji", "rahasia", client=client
        )
        assert provider.complete("halo") == '{"ok": true}'

    assert seen == {
        "url": "https://contoh.test/v1/chat/completions",
        "authorization": "Bearer rahasia",
        "model": "model-uji",
    }


def test_ollama_provider_posts_to_chat_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert payload["format"] == "json"
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider("http://127.0.0.1:11434", "qwen", client=client)
        assert provider.complete("halo") == '{"ok": true}'


def test_classify_papers_reuses_cache(session) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci", abstract="isi abstrak")
    classifier = Classifier.from_session(session)
    version = get_taxonomy_version(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, topics["Umum"].id))

    first = classify_papers(session, provider, classifier, [paper], version)
    session.commit()

    assert first.requests == 1
    assert first.cached == 0
    assert first.labels[paper.id][0].topic_id == topics["Data Mining"].id
    assert len(session.exec(select(LlmCache)).all()) == 1

    second = classify_papers(session, provider, classifier, [paper], version)

    assert second.requests == 0
    assert second.cached == 1
    assert provider.calls == 1
    assert second.labels[paper.id][0].topic_id == topics["Data Mining"].id


def test_classify_papers_falls_back_to_umum_subtopic(session) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    classifier = Classifier.from_session(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, None))

    result = classify_papers(session, provider, classifier, [paper], get_taxonomy_version(session))

    assert result.labels[paper.id][0].subtopic_id == topics["Umum"].id


def test_classify_papers_rejects_non_finite_confidence(session) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    classifier = Classifier.from_session(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, None, float("nan")))

    result = classify_papers(session, provider, classifier, [paper], get_taxonomy_version(session))

    assert result.labels[paper.id] == []


def test_classify_papers_ignores_unknown_topic(session) -> None:
    seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    classifier = Classifier.from_session(session)
    provider = FakeProvider(llm_reply(9999, None))

    result = classify_papers(session, provider, classifier, [paper], get_taxonomy_version(session))

    assert result.labels[paper.id] == []


def test_classify_papers_rejects_invalid_json(session) -> None:
    seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    classifier = Classifier.from_session(session)
    provider = FakeProvider("bukan json")

    with pytest.raises(LlmError):
        classify_papers(session, provider, classifier, [paper], get_taxonomy_version(session))


def test_reclassify_uses_llm_only_for_ambiguous(session) -> None:
    topics = seed_minimal_taxonomy(session)
    ambiguous = make_paper(session, "Paper tanpa kata kunci", abstract="tidak ada istilah")
    clear = make_paper(
        session,
        "data mining klasifikasi clustering naive bayes",
        abstract="machine learning",
    )
    classifier = Classifier.from_session(session)
    version = get_taxonomy_version(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, topics["Umum"].id))

    stats = reclassify_papers(session, classifier=classifier, version=version, llm=provider)

    assert stats.llm_requests == 1
    assert stats.llm_labeled == 1
    assert provider.calls == 1
    assert "Paper tanpa kata kunci" in provider.prompts[0]
    assert "data mining klasifikasi clustering naive bayes" not in provider.prompts[0]
    rows = session.exec(select(PaperTopic)).all()
    by_paper = {row.paper_id: row for row in rows}
    assert by_paper[ambiguous.id].source == "llm"
    assert by_paper[clear.id].source == "rule"


def test_reclassify_reuses_llm_cache(session) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    classifier = Classifier.from_session(session)
    version = get_taxonomy_version(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, topics["Umum"].id))

    first = reclassify_papers(session, classifier=classifier, version=version, llm=provider)
    second = reclassify_papers(session, classifier=classifier, version=version, llm=provider)

    assert first.llm_requests == 1
    assert second.llm_requests == 0
    assert second.llm_cached == 1
    assert provider.calls == 1
    row = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).one()
    assert row.source == "llm"


def test_reclassify_keeps_locked_label(session) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    session.add(
        PaperTopic(
            paper_id=paper.id,
            topic_id=topics["Data Mining"].id,
            confidence=0.99,
            source="manual",
            locked=True,
            taxonomy_version=get_taxonomy_version(session),
        )
    )
    session.commit()
    classifier = Classifier.from_session(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, None, 0.7))

    reclassify_papers(
        session,
        classifier=classifier,
        version=get_taxonomy_version(session),
        llm=provider,
    )

    row = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).one()
    assert row.locked is True
    assert row.source == "manual"
    assert row.confidence == pytest.approx(0.99)


def test_reclassify_skips_reviewed_paper_without_llm(session) -> None:
    topics = seed_minimal_taxonomy(session)
    paper = make_paper(session, "Paper tanpa kata kunci")
    paper.reviewed_at = utcnow()
    session.add(paper)
    session.commit()
    classifier = Classifier.from_session(session)
    provider = FakeProvider(llm_reply(topics["Data Mining"].id, None))

    stats = reclassify_papers(
        session,
        classifier=classifier,
        version=get_taxonomy_version(session),
        llm=provider,
    )

    assert stats.skipped_reviewed == 1
    assert stats.llm_requests == 0
    assert provider.calls == 0
