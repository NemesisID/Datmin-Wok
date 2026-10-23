"""Taksonomi: versi, normalisasi kata kunci, dan impor seed YAML."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app.models import LABS, Meta, Topic, TopicKeyword, TopicLab

TAXONOMY_VERSION_KEY = "taxonomy_version"
NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")


def normalize_keyword(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    normalized = NON_WORD_RE.sub(" ", normalized)
    normalized = normalized.replace("_", " ")
    return SPACE_RE.sub(" ", normalized).strip()


def get_taxonomy_version(session: Session) -> int:
    row = session.get(Meta, TAXONOMY_VERSION_KEY)
    return int(row.value) if row and row.value else 0


def set_taxonomy_version(session: Session, value: int) -> None:
    row = session.get(Meta, TAXONOMY_VERSION_KEY)
    if row:
        row.value = str(value)
    else:
        session.add(Meta(key=TAXONOMY_VERSION_KEY, value=str(value)))
    session.flush()


def bump_taxonomy_version(session: Session) -> int:
    version = get_taxonomy_version(session) + 1
    set_taxonomy_version(session, version)
    return version


@dataclass
class ImportSummary:
    topics_created: int = 0
    topics_updated: int = 0
    keywords_added: int = 0
    keywords_updated: int = 0
    keywords_removed: int = 0
    labs_added: int = 0
    labs_removed: int = 0
    version: int = 0
    changed: bool = False
    warnings: list[str] = field(default_factory=list)


def import_taxonomy(session: Session, data: dict[str, Any]) -> ImportSummary:
    topics = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(topics, list) or not topics:
        raise ValueError("Seed taksonomi harus punya daftar 'topics' yang tidak kosong.")

    summary = ImportSummary()
    seen: set[str] = set()
    for item in topics:
        _import_topic(session, item, parent=None, summary=summary, seen=seen)

    summary.changed = any(
        [
            summary.topics_created,
            summary.topics_updated,
            summary.keywords_added,
            summary.keywords_updated,
            summary.keywords_removed,
            summary.labs_added,
            summary.labs_removed,
        ]
    )
    summary.version = (
        bump_taxonomy_version(session) if summary.changed else get_taxonomy_version(session)
    )
    session.flush()
    return summary


def _require_str(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Topik butuh '{key}' berupa teks tidak kosong.")
    return value.strip()


def _import_topic(
    session: Session,
    item: dict[str, Any],
    *,
    parent: Topic | None,
    summary: ImportSummary,
    seen: set[str],
) -> Topic:
    name = _require_str(item, "name")
    if name in seen:
        raise ValueError(f"Topik '{name}' muncul lebih dari sekali di seed.")
    seen.add(name)
    if parent is not None and parent.parent_id is not None:
        raise ValueError(f"Subtopik '{name}' terlalu dalam. Kedalaman maksimal satu tingkat.")

    topic = session.exec(select(Topic).where(Topic.name == name)).first()
    is_new = topic is None
    if topic is None:
        topic = Topic(name=name, parent_id=parent.id if parent else None)
        session.add(topic)
        session.flush()
        summary.topics_created += 1
        changed = False
    else:
        changed = False
        wanted_parent = parent.id if parent else None
        if topic.parent_id != wanted_parent:
            topic.parent_id = wanted_parent
            changed = True
        if not topic.active:
            topic.active = True
            changed = True

    sort_order = item.get("sort_order")
    if isinstance(sort_order, int) and topic.sort_order != sort_order:
        topic.sort_order = sort_order
        changed = True
    if changed and not is_new:
        summary.topics_updated += 1
        session.add(topic)

    _sync_labs(session, topic, item.get("labs"), summary)
    _sync_keywords(session, topic, item.get("keywords"), summary)

    subtopics = item.get("subtopics") or []
    if not isinstance(subtopics, list):
        raise ValueError(f"Subtopik '{name}' harus berupa daftar.")
    for child in subtopics:
        _import_topic(session, child, parent=topic, summary=summary, seen=seen)
    return topic


def _sync_labs(session: Session, topic: Topic, labs: Any, summary: ImportSummary) -> None:
    if labs is None:
        labs = []
    if not isinstance(labs, list):
        raise ValueError(f"Lab topik '{topic.name}' harus berupa daftar.")
    wanted = []
    for lab in labs:
        if lab not in LABS:
            raise ValueError(f"Lab '{lab}' tidak dikenal. Pilihan: {', '.join(LABS)}.")
        if lab not in wanted:
            wanted.append(lab)

    current = {
        row.lab for row in session.exec(select(TopicLab).where(TopicLab.topic_id == topic.id)).all()
    }
    for lab in wanted:
        if lab not in current:
            session.add(TopicLab(topic_id=topic.id, lab=lab))
            summary.labs_added += 1
    for lab in current - set(wanted):
        row = session.exec(
            select(TopicLab).where(TopicLab.topic_id == topic.id, TopicLab.lab == lab)
        ).first()
        if row:
            session.delete(row)
            summary.labs_removed += 1


def _parse_keyword(item: Any) -> tuple[str, float, str]:
    if isinstance(item, str):
        return item, 1.0, ""
    if not isinstance(item, dict):
        raise ValueError("Kata kunci harus berupa teks atau objek dengan 'keyword'.")
    keyword = item.get("keyword")
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("Kata kunci butuh 'keyword' berupa teks tidak kosong.")
    weight = item.get("weight", 1.0)
    lang = item.get("lang", "")
    return keyword, float(weight), str(lang)


def _sync_keywords(session: Session, topic: Topic, keywords: Any, summary: ImportSummary) -> None:
    if keywords is None:
        keywords = []
    if not isinstance(keywords, list):
        raise ValueError(f"Kata kunci topik '{topic.name}' harus berupa daftar.")

    wanted: dict[str, tuple[str, float, str]] = {}
    for item in keywords:
        keyword, weight, lang = _parse_keyword(item)
        norm = normalize_keyword(keyword)
        if not norm:
            raise ValueError(f"Kata kunci '{keyword}' kosong setelah normalisasi.")
        wanted.setdefault(norm, (keyword.strip(), weight, lang))

    current = {
        row.keyword_norm: row
        for row in session.exec(select(TopicKeyword).where(TopicKeyword.topic_id == topic.id)).all()
    }
    for norm, (keyword, weight, lang) in wanted.items():
        row = current.get(norm)
        if row is None:
            session.add(
                TopicKeyword(
                    topic_id=topic.id,
                    keyword=keyword,
                    keyword_norm=norm,
                    weight=weight,
                    lang=lang,
                )
            )
            summary.keywords_added += 1
        elif row.weight != weight or row.lang != lang or row.keyword != keyword:
            row.weight = weight
            row.lang = lang
            row.keyword = keyword
            session.add(row)
            summary.keywords_updated += 1
    for norm, row in current.items():
        if norm not in wanted:
            session.delete(row)
            summary.keywords_removed += 1
