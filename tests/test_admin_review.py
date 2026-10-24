from __future__ import annotations

from conftest import csrf_from, login
from factories import make_paper, make_thesis, seed_minimal_taxonomy
from sqlmodel import Session, select

from app.models import Paper, PaperTopic, SyncJob, Thesis, ThesisTopic, Topic


def test_review_page_lists_pending_paper(client, engine) -> None:
    with Session(engine) as session:
        seed_minimal_taxonomy(session)
        paper = make_paper(session, "Paper Tanpa Topik")
        paper_id = paper.id

    login(client)
    response = client.get("/admin/review")

    assert response.status_code == 200
    assert "Paper Tanpa Topik" in response.text
    assert "Tidak relevan" in response.text
    assert "Keyboard:" in response.text
    assert f"/admin/review/paper/{paper_id}" in response.text


def test_manual_assignment_locks_label(client, engine) -> None:
    with Session(engine) as session:
        taxonomy = seed_minimal_taxonomy(session)
        paper = make_paper(session, "Paper Tanpa Topik")
        paper_id = paper.id
        topic_id = taxonomy["UI/UX"].id

    login(client)
    page = client.get("/admin/review")
    response = client.post(
        f"/admin/review/paper/{paper_id}",
        data={
            "csrf_token": csrf_from(page),
            "topic_id": str(topic_id),
            "subtopic_id": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
        assert paper.reviewed_at is not None
        labels = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper_id)).all()
        assert len(labels) == 1
        assert labels[0].topic_id == topic_id
        assert labels[0].source == "manual"
        assert labels[0].locked is True


def test_mark_paper_not_relevant(client, engine) -> None:
    with Session(engine) as session:
        seed_minimal_taxonomy(session)
        paper = make_paper(session, "Paper Tidak Relevan")
        paper_id = paper.id

    login(client)
    page = client.get("/admin/review")
    response = client.post(
        f"/admin/review/paper/{paper_id}",
        data={
            "csrf_token": csrf_from(page),
            "topic_id": "",
            "subtopic_id": "",
            "tidak_relevan": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
        assert paper.reviewed_at is not None
        assert session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper_id)).all() == []
    assert "Paper Tidak Relevan" not in client.get("/admin/review").text


def test_review_rejects_subtopic_from_other_topic(client, engine) -> None:
    with Session(engine) as session:
        taxonomy = seed_minimal_taxonomy(session)
        paper = make_paper(session, "Paper Tanpa Topik")
        paper_id = paper.id
        wrong_topic = taxonomy["UI/UX"].id
        wrong_subtopic = taxonomy["Analisis Sentimen"].id

    login(client)
    page = client.get("/admin/review")
    response = client.post(
        f"/admin/review/paper/{paper_id}",
        data={
            "csrf_token": csrf_from(page),
            "topic_id": str(wrong_topic),
            "subtopic_id": str(wrong_subtopic),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Sub-topik" in response.text
    with Session(engine) as session:
        assert session.get(Paper, paper_id).reviewed_at is None


def test_taxonomy_reclassify_button_enqueues_job(client, engine) -> None:
    login(client)
    page = client.get("/admin/taksonomi")
    response = client.post(
        "/admin/taksonomi/reklasifikasi",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        job = session.exec(select(SyncJob).where(SyncJob.source == "reclassify")).one()
    assert job.status == "pending"


def test_topic_reclassify_button_enqueues_scoped_job(client, engine) -> None:
    with Session(engine) as session:
        topic = Topic(name="Data Mining", sort_order=10)
        session.add(topic)
        session.commit()
        session.refresh(topic)
        topic_id = topic.id

    login(client)
    page = client.get(f"/admin/taksonomi/{topic_id}")
    response = client.post(
        "/admin/taksonomi/reklasifikasi",
        data={"csrf_token": csrf_from(page), "topik": str(topic_id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/taksonomi/{topic_id}"
    with Session(engine) as session:
        job = session.exec(select(SyncJob).where(SyncJob.source == f"reclassify:{topic_id}")).one()
    assert job.status == "pending"


def test_thesis_can_be_reviewed_without_subtopic(client, engine) -> None:
    with Session(engine) as session:
        taxonomy = seed_minimal_taxonomy(session)
        thesis = make_thesis(session, "Skripsi Tanpa Topik")
        thesis_id = thesis.id
        topic_id = taxonomy["Data Mining"].id

    login(client)
    page = client.get("/admin/review")
    assert "Skripsi Tanpa Topik" in page.text
    response = client.post(
        f"/admin/review/thesis/{thesis_id}",
        data={"csrf_token": csrf_from(page), "topic_id": str(topic_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        thesis = session.get(Thesis, thesis_id)
        assert thesis.reviewed_at is not None
        labels = session.exec(select(ThesisTopic).where(ThesisTopic.thesis_id == thesis_id)).all()
        assert [label.topic_id for label in labels] == [topic_id]
        assert labels[0].locked is True


def test_navigation_links_review(client) -> None:
    login(client)
    assert 'href="/admin/review"' in client.get("/admin").text
