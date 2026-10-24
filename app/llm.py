"""Klasifikasi Tahap 3 opsional lewat LLM dengan cache ber-taxonomy_version."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlmodel import Session, select

from app.classify import Classifier, TopicPrediction
from app.config import Settings, get_settings
from app.models import LlmCache, Paper, utcnow

MAX_ABSTRACT_CHARS = 4000
DEFAULT_BATCH_SIZE = 20


class LlmError(RuntimeError):
    """Kegagalan provider atau respons LLM yang tidak bisa dipakai."""


class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class LlmResult:
    labels: dict[int, list[TopicPrediction]]
    cached: int = 0
    requests: int = 0


@dataclass(frozen=True)
class _PromptItem:
    content_hash: str
    title: str
    abstract: str


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        url = base_url.rstrip("/")
        self.url = url if url.endswith("/chat/completions") else f"{url}/chat/completions"
        self.model = model
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def complete(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = self._client.post(
            self.url,
            headers=headers,
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": "Balas hanya JSON valid tanpa markdown.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LlmError("Respons OpenAI-compatible tidak berisi konten.") from error
        if not isinstance(content, str):
            raise LlmError("Konten LLM bukan teks.")
        return content

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/api/chat"
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def complete(self, prompt: str) -> str:
        response = self._client.post(
            self.url,
            json={
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": "Balas hanya JSON valid tanpa markdown.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as error:
            raise LlmError("Respons Ollama bukan JSON.") from error
        if not isinstance(data, dict):
            raise LlmError("Respons Ollama bukan objek.")
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        content = content or data.get("response")
        if not isinstance(content, str):
            raise LlmError("Respons Ollama tidak berisi konten.")
        return content

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def build_llm_provider(settings: Settings | None = None) -> LLMProvider | None:
    """Kembalikan provider hanya bila USE_LLM=true dan konfigurasinya valid."""
    settings = settings or get_settings()
    if not settings.use_llm:
        return None
    name = settings.llm_provider.strip().lower()
    if not settings.llm_model.strip():
        raise ValueError("LLM_MODEL wajib diisi bila USE_LLM=true.")
    timeout = settings.llm_timeout_seconds
    if name in {"openai", "openai-compatible", "compatible"}:
        return OpenAICompatibleProvider(
            settings.llm_base_url or "https://api.openai.com/v1",
            settings.llm_model.strip(),
            settings.llm_api_key,
            timeout,
        )
    if name == "ollama":
        return OllamaProvider(
            settings.llm_base_url or "http://127.0.0.1:11434",
            settings.llm_model.strip(),
            timeout,
        )
    raise ValueError("LLM_PROVIDER harus 'openai' atau 'ollama' bila USE_LLM=true.")


def content_hash(title: str, abstract: str | None, taxonomy_version: int) -> str:
    raw = f"{title.strip()}\n{(abstract or '').strip()}\n{taxonomy_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prompt_item(paper: Paper, version: int) -> _PromptItem:
    return _PromptItem(
        content_hash=content_hash(paper.title, paper.abstract, version),
        title=paper.title,
        abstract=(paper.abstract or "").strip(),
    )


def _taxonomy_payload(classifier: Classifier) -> list[dict[str, Any]]:
    return [
        {
            "id": root.id,
            "name": root.name,
            "subtopics": [{"id": child.id, "name": child.name} for child in root.children],
        }
        for root in classifier.roots
    ]


def _build_prompt(classifier: Classifier, items: list[_PromptItem]) -> str:
    lines = [
        "Klasifikasikan paper berikut ke taksonomi tetap.",
        "Aturan:",
        "- Gunakan hanya topic_id dan subtopic_id dari taksonomi.",
        "- Satu paper boleh punya lebih dari satu topik.",
        "- confidence berupa angka 0 sampai 1.",
        "- Bila tidak yakin, kosongkan labels.",
        "- Balas JSON saja tanpa markdown.",
        'Bentuk: {"results":[{"index":0,"labels":['
        '{"topic_id":1,"subtopic_id":2,"confidence":0.8}]}]}',
        "",
        "Taksonomi:",
        json.dumps(_taxonomy_payload(classifier), ensure_ascii=False),
        "",
        "Paper:",
    ]
    for index, item in enumerate(items):
        lines.append(f"[{index}]")
        lines.append(f"Judul: {item.title}")
        if item.abstract:
            lines.append(f"Abstrak: {item.abstract[:MAX_ABSTRACT_CHARS]}")
    return "\n".join(lines)


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LlmError("LLM tidak mengembalikan objek JSON.")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise LlmError("JSON dari LLM tidak valid.") from error
    if not isinstance(payload, dict):
        raise LlmError("JSON dari LLM bukan objek.")
    return payload


def _labels_from_raw(
    raw_labels: Any,
    classifier: Classifier,
) -> list[TopicPrediction]:
    if not isinstance(raw_labels, list):
        return []
    topics = {root.id: root for root in classifier.roots}
    order = {root.id: index for index, root in enumerate(classifier.roots)}
    best: dict[int, TopicPrediction] = {}
    for raw in raw_labels:
        if not isinstance(raw, dict):
            continue
        try:
            topic_id = int(raw.get("topic_id"))
        except (TypeError, ValueError):
            continue
        topic = topics.get(topic_id)
        if topic is None:
            continue
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(confidence):
            continue
        confidence = max(0.0, min(1.0, confidence))
        if confidence <= 0:
            continue
        subtopic_id: int | None = None
        try:
            wanted = int(raw.get("subtopic_id"))
        except (TypeError, ValueError):
            wanted = 0
        if any(child.id == wanted for child in topic.children):
            subtopic_id = wanted
        if subtopic_id is None:
            subtopic_id = next(
                (child.id for child in topic.children if child.name.strip().lower() == "umum"),
                None,
            )
        prediction = TopicPrediction(
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            confidence=round(confidence, 4),
        )
        previous = best.get(topic_id)
        if previous is None or prediction.confidence > previous.confidence:
            best[topic_id] = prediction
    return sorted(
        best.values(),
        key=lambda item: (-item.confidence, order.get(item.topic_id, 999)),
    )


def _predictions_from_cache(
    payload: dict[str, Any] | None,
    classifier: Classifier,
) -> list[TopicPrediction] | None:
    if not isinstance(payload, dict):
        return None
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return None
    return _labels_from_raw(labels, classifier)


def _result_payload(predictions: list[TopicPrediction]) -> dict[str, Any]:
    return {
        "labels": [
            {
                "topic_id": prediction.topic_id,
                "subtopic_id": prediction.subtopic_id,
                "confidence": prediction.confidence,
            }
            for prediction in predictions
        ]
    }


def _parse_batch(
    content: str,
    item_hashes: list[str],
    classifier: Classifier,
) -> dict[str, list[TopicPrediction]]:
    payload = _json_object(content)
    results = payload.get("results")
    if not isinstance(results, list):
        raise LlmError("JSON LLM tidak berisi daftar results.")
    parsed: dict[str, list[TopicPrediction]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        try:
            index = int(result.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(item_hashes):
            continue
        parsed[item_hashes[index]] = _labels_from_raw(result.get("labels"), classifier)
    return parsed


def classify_papers(
    session: Session,
    provider: LLMProvider,
    classifier: Classifier,
    papers: list[Paper],
    taxonomy_version: int,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> LlmResult:
    """Klasifikasikan paper ambigu, memakai cache per judul+abstrak+versi."""
    items = [_prompt_item(paper, taxonomy_version) for paper in papers]
    by_hash: dict[str, list[_PromptItem]] = {}
    for item in items:
        by_hash.setdefault(item.content_hash, []).append(item)
    hashes = list(by_hash)
    if not hashes:
        return LlmResult(labels={})

    rows = session.exec(
        select(LlmCache).where(
            LlmCache.taxonomy_version == taxonomy_version,
            LlmCache.content_hash.in_(hashes),
        )
    ).all()
    existing = {row.content_hash: row for row in rows}
    results: dict[str, list[TopicPrediction]] = {}
    cached = 0
    for key, row in existing.items():
        predictions = _predictions_from_cache(row.result_json, classifier)
        if predictions is None:
            continue
        results[key] = predictions
        cached += len(by_hash[key])

    misses = [key for key in hashes if key not in results]
    size = max(1, min(batch_size, 50))
    requests = 0
    for start in range(0, len(misses), size):
        batch = misses[start : start + size]
        prompt_items = [by_hash[key][0] for key in batch]
        content = provider.complete(_build_prompt(classifier, prompt_items))
        requests += 1
        parsed = _parse_batch(content, batch, classifier)
        for key, predictions in parsed.items():
            results[key] = predictions
            payload = _result_payload(predictions)
            row = existing.get(key)
            if row is None:
                session.add(
                    LlmCache(
                        content_hash=key,
                        taxonomy_version=taxonomy_version,
                        result_json=payload,
                    )
                )
            else:
                row.result_json = payload
                row.created_at = utcnow()
                session.add(row)

    labels: dict[int, list[TopicPrediction]] = {}
    for paper, item in zip(papers, items, strict=True):
        if item.content_hash in results:
            labels[paper.id] = results[item.content_hash]
    return LlmResult(labels=labels, cached=cached, requests=requests)
