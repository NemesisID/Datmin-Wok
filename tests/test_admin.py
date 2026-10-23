from conftest import csrf_from, login
from sqlmodel import Session, select
from test_taxonomy import load_seed

from app.models import Lecturer, LecturerOpenAlexId, Topic, TopicLab
from app.taxonomy import get_taxonomy_version, import_taxonomy


def test_admin_requires_login(client) -> None:
    response = client.get("/admin/dosen", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_login_rejects_wrong_password(client) -> None:
    page = client.get("/admin/login")
    response = client.post(
        "/admin/login",
        data={"csrf_token": csrf_from(page), "username": "admin", "password": "salah"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "salah" in response.text


def test_login_sets_session(client) -> None:
    login(client)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Dasbor" in response.text


def test_post_without_csrf_is_rejected(client) -> None:
    login(client)
    response = client.post(
        "/admin/dosen/baru",
        data={"name": "Tanpa Token"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_create_lecturer_parses_scholar_url(client, engine) -> None:
    login(client)
    page = client.get("/admin/dosen/baru")
    response = client.post(
        "/admin/dosen/baru",
        data={
            "csrf_token": csrf_from(page),
            "name": "Nur Cahyo Wibowo",
            "title": "S.Kom., M.Kom.",
            "scholar": "https://scholar.google.com/citations?user=AbC123xyz_9",
            "notes": "",
            "active": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        lecturer = session.exec(select(Lecturer)).one()
    assert lecturer.name == "Nur Cahyo Wibowo"
    assert lecturer.scholar_id == "AbC123xyz_9"
    assert lecturer.active is True


def test_duplicate_scholar_id_is_refused(client, engine) -> None:
    login(client)
    page = client.get("/admin/dosen/baru")
    payload = {
        "csrf_token": csrf_from(page),
        "name": "Dosen Satu",
        "scholar": "AbC123xyz_9",
        "active": "true",
    }
    client.post("/admin/dosen/baru", data=payload)

    page = client.get("/admin/dosen/baru")
    payload["csrf_token"] = csrf_from(page)
    payload["name"] = "Dosen Dua"
    client.post("/admin/dosen/baru", data=payload)

    with Session(engine) as session:
        assert len(session.exec(select(Lecturer)).all()) == 1


def test_map_openalex_id(client, engine) -> None:
    login(client)
    page = client.get("/admin/dosen/baru")
    client.post(
        "/admin/dosen/baru",
        data={"csrf_token": csrf_from(page), "name": "Asif Faroqi", "active": "true"},
    )
    with Session(engine) as session:
        lecturer = session.exec(select(Lecturer)).one()

    page = client.get(f"/admin/dosen/{lecturer.id}")
    response = client.post(
        f"/admin/dosen/{lecturer.id}/openalex",
        data={
            "csrf_token": csrf_from(page),
            "openalex_author_id": "https://openalex.org/A5002063329",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        row = session.exec(select(LecturerOpenAlexId)).one()
    assert row.openalex_author_id == "A5002063329"


def test_taxonomy_page_shows_shared_topic_in_two_labs(client, engine) -> None:
    login(client)
    with Session(engine) as session:
        import_taxonomy(session, load_seed())
        session.commit()

    response = client.get("/admin/taksonomi")
    assert response.status_code == 200
    assert "UI/UX" in response.text
    assert "SOLUSI" in response.text
    assert "MSI" in response.text

    with Session(engine) as session:
        topic = session.exec(select(Topic).where(Topic.name == "UI/UX")).one()
        labs = {
            row.lab
            for row in session.exec(select(TopicLab).where(TopicLab.topic_id == topic.id)).all()
        }
    assert labs == {"SOLUSI", "MSI"}


def test_adding_keyword_bumps_taxonomy_version(client, engine) -> None:
    login(client)
    with Session(engine) as session:
        import_taxonomy(session, load_seed())
        session.commit()
        topic = session.exec(select(Topic).where(Topic.name == "UI/UX")).one()
        topic_id = topic.id
        before = get_taxonomy_version(session)
    assert before == 1

    page = client.get(f"/admin/taksonomi/{topic_id}")
    response = client.post(
        f"/admin/taksonomi/{topic_id}/kata-kunci",
        data={"csrf_token": csrf_from(page), "keyword": "wireframe", "weight": "1.0", "lang": "en"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        assert get_taxonomy_version(session) == 2


def test_create_topic_with_two_labs(client, engine) -> None:
    login(client)
    page = client.get("/admin/taksonomi/baru")
    response = client.post(
        "/admin/taksonomi/baru",
        data={
            "csrf_token": csrf_from(page),
            "name": "Topik Baru",
            "parent_id": "",
            "sort_order": "999",
            "active": "true",
            "labs": ["SOLUSI", "MSI"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        topic = session.exec(select(Topic).where(Topic.name == "Topik Baru")).one()
        labs = {
            row.lab
            for row in session.exec(select(TopicLab).where(TopicLab.topic_id == topic.id)).all()
        }
        assert labs == {"SOLUSI", "MSI"}
        assert get_taxonomy_version(session) == 1


def test_topic_requires_at_least_one_lab(client, engine) -> None:
    login(client)
    page = client.get("/admin/taksonomi/baru")
    client.post(
        "/admin/taksonomi/baru",
        data={"csrf_token": csrf_from(page), "name": "Tanpa Lab", "labs": []},
    )
    with Session(engine) as session:
        assert session.exec(select(Topic).where(Topic.name == "Tanpa Lab")).first() is None
