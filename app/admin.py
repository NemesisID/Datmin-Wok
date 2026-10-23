"""Rute admin: login, dosen, dan editor taksonomi."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.models import (
    LABS,
    Lecturer,
    LecturerOpenAlexId,
    Topic,
    TopicKeyword,
    TopicLab,
    utcnow,
)
from app.security import (
    LoginRateLimiter,
    csrf_ok,
    new_csrf_token,
    normalize_openalex_id,
    parse_scholar_id,
    verify_password,
)
from app.taxonomy import bump_taxonomy_version, get_taxonomy_version, normalize_keyword
from app.templating import flash, render


async def csrf_guard(request: Request) -> None:
    """Tolak POST tanpa token yang cocok dengan sesi."""
    if request.method != "POST":
        return
    form = await request.form()
    if not csrf_ok(request.session.get("csrf"), form.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Token CSRF tidak valid.")


router = APIRouter(prefix="/admin", dependencies=[Depends(csrf_guard)])

_limiter: LoginRateLimiter | None = None


def limiter() -> LoginRateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = LoginRateLimiter(
            max_attempts=settings.login_max_attempts,
            window_seconds=settings.login_window_seconds,
        )
    return _limiter


def reset_limiter() -> None:
    global _limiter
    _limiter = None


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


@router.get("/login")
def login_form(request: Request):
    if _is_admin(request):
        return _redirect("/admin")
    request.session.setdefault("csrf", new_csrf_token())
    has_password = bool(get_settings().admin_password_hash)
    return render(request, "admin/login.html", has_password=has_password)


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
):
    ip = request.client.host if request.client else "lokal"
    if not limiter().allowed(ip):
        return render(
            request,
            "admin/login.html",
            has_password=bool(get_settings().admin_password_hash),
            error="Terlalu banyak percobaan. Coba lagi dalam 15 menit.",
            status_code=429,
        )

    settings = get_settings()
    if (
        settings.admin_password_hash
        and username.strip() == settings.admin_username
        and verify_password(password, settings.admin_password_hash)
    ):
        request.session.clear()
        request.session["admin"] = settings.admin_username
        request.session["csrf"] = new_csrf_token()
        limiter().reset(ip)
        return _redirect("/admin")

    limiter().record_failure(ip)
    return render(
        request,
        "admin/login.html",
        has_password=bool(settings.admin_password_hash),
        error="Nama pengguna atau kata sandi salah.",
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return _redirect("/admin/login")


@router.get("")
def dashboard(request: Request, session: Session = Depends(get_session)):
    lecturers = session.exec(select(Lecturer)).all()
    topics = session.exec(select(Topic)).all()
    keywords = session.exec(select(TopicKeyword)).all()
    return render(
        request,
        "admin/dashboard.html",
        counts={
            "lecturers": len(lecturers),
            "active_lecturers": sum(1 for item in lecturers if item.active),
            "topics": sum(1 for item in topics if item.active),
            "keywords": len(keywords),
            "taxonomy_version": get_taxonomy_version(session),
        },
    )


@router.get("/dosen")
def lecturer_list(request: Request, session: Session = Depends(get_session)):
    lecturers = session.exec(select(Lecturer).order_by(Lecturer.name)).all()
    openalex = session.exec(select(LecturerOpenAlexId)).all()
    counts: dict[int, int] = defaultdict(int)
    for row in openalex:
        counts[row.lecturer_id] += 1
    return render(
        request,
        "admin/lecturers.html",
        lecturers=lecturers,
        openalex_counts=counts,
    )


@router.get("/dosen/baru")
def lecturer_new_form(request: Request):
    return render(request, "admin/lecturer_form.html", lecturer=None, openalex_ids=[])


@router.post("/dosen/baru")
def lecturer_create(
    request: Request,
    name: str = Form(""),
    title: str = Form(""),
    scholar: str = Form(""),
    notes: str = Form(""),
    active: bool = Form(False),
    session: Session = Depends(get_session),
):
    name = name.strip()
    if not name:
        flash(request, "Nama dosen wajib diisi.")
        return _redirect("/admin/dosen/baru")
    try:
        scholar_id = parse_scholar_id(scholar)
    except ValueError as error:
        flash(request, str(error))
        return _redirect("/admin/dosen/baru")
    if (
        scholar_id
        and session.exec(select(Lecturer).where(Lecturer.scholar_id == scholar_id)).first()
    ):
        flash(request, "ID Scholar itu sudah dipakai dosen lain.")
        return _redirect("/admin/dosen/baru")

    lecturer = Lecturer(
        name=name,
        title=title.strip(),
        scholar_id=scholar_id,
        notes=notes.strip(),
        active=active,
    )
    session.add(lecturer)
    session.commit()
    session.refresh(lecturer)
    flash(
        request,
        f"Dosen {lecturer.name} ditambahkan. Tambahkan ID OpenAlex agar bisa disinkronkan.",
    )
    return _redirect(f"/admin/dosen/{lecturer.id}")


@router.get("/dosen/{lecturer_id}")
def lecturer_edit_form(request: Request, lecturer_id: int, session: Session = Depends(get_session)):
    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        flash(request, "Dosen tidak ditemukan.")
        return _redirect("/admin/dosen")
    openalex_ids = session.exec(
        select(LecturerOpenAlexId)
        .where(LecturerOpenAlexId.lecturer_id == lecturer_id)
        .order_by(LecturerOpenAlexId.confirmed_at)
    ).all()
    return render(
        request,
        "admin/lecturer_form.html",
        lecturer=lecturer,
        openalex_ids=openalex_ids,
    )


@router.post("/dosen/{lecturer_id}")
def lecturer_update(
    request: Request,
    lecturer_id: int,
    name: str = Form(""),
    title: str = Form(""),
    scholar: str = Form(""),
    notes: str = Form(""),
    active: bool = Form(False),
    session: Session = Depends(get_session),
):
    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        flash(request, "Dosen tidak ditemukan.")
        return _redirect("/admin/dosen")
    name = name.strip()
    if not name:
        flash(request, "Nama dosen wajib diisi.")
        return _redirect(f"/admin/dosen/{lecturer_id}")
    try:
        scholar_id = parse_scholar_id(scholar)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(f"/admin/dosen/{lecturer_id}")

    duplicate = session.exec(select(Lecturer).where(Lecturer.scholar_id == scholar_id)).first()
    if scholar_id and duplicate and duplicate.id != lecturer_id:
        flash(request, "ID Scholar itu sudah dipakai dosen lain.")
        return _redirect(f"/admin/dosen/{lecturer_id}")

    lecturer.name = name
    lecturer.title = title.strip()
    lecturer.scholar_id = scholar_id
    lecturer.notes = notes.strip()
    lecturer.active = active
    lecturer.updated_at = utcnow()
    session.add(lecturer)
    session.commit()
    flash(request, "Perubahan dosen disimpan.")
    return _redirect(f"/admin/dosen/{lecturer_id}")


@router.post("/dosen/{lecturer_id}/openalex")
def openalex_add(
    request: Request,
    lecturer_id: int,
    openalex_author_id: str = Form(""),
    session: Session = Depends(get_session),
):
    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        flash(request, "Dosen tidak ditemukan.")
        return _redirect("/admin/dosen")
    try:
        normalized = normalize_openalex_id(openalex_author_id)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(f"/admin/dosen/{lecturer_id}")

    exists = session.exec(
        select(LecturerOpenAlexId).where(
            LecturerOpenAlexId.lecturer_id == lecturer_id,
            LecturerOpenAlexId.openalex_author_id == normalized,
        )
    ).first()
    if exists:
        flash(request, "ID OpenAlex itu sudah terpasang di dosen ini.")
        return _redirect(f"/admin/dosen/{lecturer_id}")

    session.add(LecturerOpenAlexId(lecturer_id=lecturer_id, openalex_author_id=normalized))
    session.commit()
    flash(request, f"ID OpenAlex {normalized} dipetakan.")
    return _redirect(f"/admin/dosen/{lecturer_id}")


@router.post("/dosen/{lecturer_id}/openalex/{openalex_author_id}/hapus")
def openalex_remove(
    request: Request,
    lecturer_id: int,
    openalex_author_id: str,
    session: Session = Depends(get_session),
):
    row = session.exec(
        select(LecturerOpenAlexId).where(
            LecturerOpenAlexId.lecturer_id == lecturer_id,
            LecturerOpenAlexId.openalex_author_id == openalex_author_id,
        )
    ).first()
    if row:
        session.delete(row)
        session.commit()
        flash(request, "Pemetaan ID OpenAlex dihapus.")
    return _redirect(f"/admin/dosen/{lecturer_id}")


def _taxonomy_rows(session: Session) -> list[dict[str, object]]:
    topics = session.exec(select(Topic).order_by(Topic.sort_order, Topic.name)).all()
    labs: dict[int, list[str]] = defaultdict(list)
    for row in session.exec(select(TopicLab)).all():
        labs[row.topic_id].append(row.lab)
    keyword_counts: dict[int, int] = defaultdict(int)
    for row in session.exec(select(TopicKeyword)).all():
        keyword_counts[row.topic_id] += 1

    children: dict[int | None, list[Topic]] = defaultdict(list)
    for topic in topics:
        children[topic.parent_id].append(topic)

    rows = []
    for root in children[None]:
        rows.append(
            {
                "topic": root,
                "labs": sorted(labs[root.id] or []),
                "keywords": keyword_counts[root.id],
                "children": [
                    {
                        "topic": child,
                        "labs": sorted(labs[child.id] or []),
                        "keywords": keyword_counts[child.id],
                    }
                    for child in children[root.id]
                ],
            }
        )
    return rows


@router.get("/taksonomi")
def taxonomy_list(request: Request, session: Session = Depends(get_session)):
    roots = session.exec(select(Topic).where(Topic.parent_id.is_(None))).all()
    return render(
        request,
        "admin/taxonomy.html",
        rows=_taxonomy_rows(session),
        roots=sorted(roots, key=lambda item: (item.sort_order, item.name)),
        taxonomy_version=get_taxonomy_version(session),
    )


@router.get("/taksonomi/baru")
def topic_new_form(request: Request, session: Session = Depends(get_session)):
    roots = session.exec(select(Topic).where(Topic.parent_id.is_(None))).all()
    return render(
        request,
        "admin/topic_form.html",
        topic=None,
        labs=[],
        keywords=[],
        roots=sorted(roots, key=lambda item: (item.sort_order, item.name)),
        has_children=False,
        taxonomy_version=get_taxonomy_version(session),
    )


def _parse_labs(request: Request, labs: list[str]) -> list[str] | None:
    chosen = [lab for lab in LABS if lab in labs]
    if not chosen:
        flash(request, "Pilih minimal satu lab.")
        return None
    return chosen


def _parent_from_form(
    request: Request, session: Session, parent_id: str, topic: Topic | None
) -> Topic | None | bool:
    if not parent_id:
        return None
    try:
        wanted = int(parent_id)
    except ValueError:
        flash(request, "Induk topik tidak valid.")
        return False
    parent = session.get(Topic, wanted)
    if parent is None or parent.parent_id is not None:
        flash(request, "Induk topik harus topik utama.")
        return False
    if topic and parent.id == topic.id:
        flash(request, "Topik tidak boleh menjadi induk dirinya sendiri.")
        return False
    return parent


@router.post("/taksonomi/baru")
def topic_create(
    request: Request,
    name: str = Form(""),
    parent_id: str = Form(""),
    sort_order: int = Form(0),
    active: bool = Form(False),
    labs: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    name = name.strip()
    if not name:
        flash(request, "Nama topik wajib diisi.")
        return _redirect("/admin/taksonomi/baru")
    if session.exec(select(Topic).where(Topic.name == name)).first():
        flash(request, "Nama topik sudah dipakai.")
        return _redirect("/admin/taksonomi/baru")
    chosen_labs = _parse_labs(request, labs)
    if chosen_labs is None:
        return _redirect("/admin/taksonomi/baru")
    parent = _parent_from_form(request, session, parent_id, None)
    if parent is False:
        return _redirect("/admin/taksonomi/baru")

    topic = Topic(
        name=name,
        parent_id=parent.id if parent else None,
        sort_order=sort_order,
        active=active,
    )
    session.add(topic)
    session.flush()
    for lab in chosen_labs:
        session.add(TopicLab(topic_id=topic.id, lab=lab))
    bump_taxonomy_version(session)
    session.commit()
    flash(request, f"Topik {topic.name} dibuat.")
    return _redirect(f"/admin/taksonomi/{topic.id}")


@router.get("/taksonomi/{topic_id}")
def topic_edit_form(request: Request, topic_id: int, session: Session = Depends(get_session)):
    topic = session.get(Topic, topic_id)
    if topic is None:
        flash(request, "Topik tidak ditemukan.")
        return _redirect("/admin/taksonomi")
    labs = [
        row.lab for row in session.exec(select(TopicLab).where(TopicLab.topic_id == topic_id)).all()
    ]
    keywords = session.exec(
        select(TopicKeyword).where(TopicKeyword.topic_id == topic_id).order_by(TopicKeyword.keyword)
    ).all()
    roots = session.exec(select(Topic).where(Topic.parent_id.is_(None))).all()
    has_children = bool(session.exec(select(Topic).where(Topic.parent_id == topic_id)).first())
    return render(
        request,
        "admin/topic_form.html",
        topic=topic,
        labs=labs,
        keywords=keywords,
        roots=[item for item in roots if item.id != topic_id],
        has_children=has_children,
        taxonomy_version=get_taxonomy_version(session),
    )


@router.post("/taksonomi/{topic_id}")
def topic_update(
    request: Request,
    topic_id: int,
    name: str = Form(""),
    parent_id: str = Form(""),
    sort_order: int = Form(0),
    active: bool = Form(False),
    labs: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    topic = session.get(Topic, topic_id)
    if topic is None:
        flash(request, "Topik tidak ditemukan.")
        return _redirect("/admin/taksonomi")
    name = name.strip()
    if not name:
        flash(request, "Nama topik wajib diisi.")
        return _redirect(f"/admin/taksonomi/{topic_id}")
    duplicate = session.exec(select(Topic).where(Topic.name == name)).first()
    if duplicate and duplicate.id != topic_id:
        flash(request, "Nama topik sudah dipakai.")
        return _redirect(f"/admin/taksonomi/{topic_id}")
    chosen_labs = _parse_labs(request, labs)
    if chosen_labs is None:
        return _redirect(f"/admin/taksonomi/{topic_id}")

    has_children = bool(session.exec(select(Topic).where(Topic.parent_id == topic_id)).first())
    if has_children and parent_id:
        flash(request, "Topik yang punya sub-topik harus tetap jadi topik utama.")
        return _redirect(f"/admin/taksonomi/{topic_id}")
    parent = _parent_from_form(request, session, parent_id, topic)
    if parent is False:
        return _redirect(f"/admin/taksonomi/{topic_id}")

    topic.name = name
    topic.parent_id = parent.id if parent else None
    topic.sort_order = sort_order
    topic.active = active
    session.add(topic)

    current_labs = {
        row.lab for row in session.exec(select(TopicLab).where(TopicLab.topic_id == topic_id)).all()
    }
    for lab in chosen_labs:
        if lab not in current_labs:
            session.add(TopicLab(topic_id=topic_id, lab=lab))
    for lab in current_labs - set(chosen_labs):
        row = session.exec(
            select(TopicLab).where(TopicLab.topic_id == topic_id, TopicLab.lab == lab)
        ).first()
        if row:
            session.delete(row)

    bump_taxonomy_version(session)
    session.commit()
    flash(request, "Topik disimpan.")
    return _redirect(f"/admin/taksonomi/{topic_id}")


@router.post("/taksonomi/{topic_id}/kata-kunci")
def keyword_add(
    request: Request,
    topic_id: int,
    keyword: str = Form(""),
    weight: float = Form(1.0),
    lang: str = Form(""),
    session: Session = Depends(get_session),
):
    topic = session.get(Topic, topic_id)
    if topic is None:
        flash(request, "Topik tidak ditemukan.")
        return _redirect("/admin/taksonomi")
    norm = normalize_keyword(keyword)
    if not norm:
        flash(request, "Kata kunci tidak boleh kosong.")
        return _redirect(f"/admin/taksonomi/{topic_id}")
    if not 0.1 <= weight <= 10:
        flash(request, "Bobot harus antara 0,1 dan 10.")
        return _redirect(f"/admin/taksonomi/{topic_id}")

    existing = session.exec(
        select(TopicKeyword).where(
            TopicKeyword.topic_id == topic_id, TopicKeyword.keyword_norm == norm
        )
    ).first()
    if existing:
        existing.weight = weight
        existing.lang = lang.strip()
        existing.keyword = keyword.strip()
        session.add(existing)
    else:
        session.add(
            TopicKeyword(
                topic_id=topic_id,
                keyword=keyword.strip(),
                keyword_norm=norm,
                weight=weight,
                lang=lang.strip(),
            )
        )
    bump_taxonomy_version(session)
    session.commit()
    flash(request, "Kata kunci disimpan.")
    return _redirect(f"/admin/taksonomi/{topic_id}")


@router.post("/taksonomi/{topic_id}/kata-kunci/{keyword_id}/hapus")
def keyword_remove(
    request: Request,
    topic_id: int,
    keyword_id: int,
    session: Session = Depends(get_session),
):
    row = session.get(TopicKeyword, keyword_id)
    if row and row.topic_id == topic_id:
        session.delete(row)
        bump_taxonomy_version(session)
        session.commit()
        flash(request, "Kata kunci dihapus.")
    return _redirect(f"/admin/taksonomi/{topic_id}")
