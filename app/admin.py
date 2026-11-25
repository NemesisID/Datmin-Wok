"""Rute admin: login, dosen, dan editor taksonomi."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.classify import mark_not_relevant, reclassify_papers, set_manual_label
from app.config import get_settings
from app.db import get_session
from app.dedupe import merge_paper_into
from app.lecturer_import import import_lecturers
from app.models import (
    LABS,
    ImportBatch,
    ImportRow,
    Lecturer,
    LecturerOpenAlexId,
    LecturerPaper,
    Paper,
    PaperDuplicate,
    PaperTopic,
    SyncJob,
    Thesis,
    Topic,
    TopicKeyword,
    TopicLab,
    utcnow,
)
from app.providers.manual import ManualImportProvider
from app.providers.openalex import build_client
from app.review import pending_papers, pending_theses, review_counts
from app.security import (
    LoginRateLimiter,
    csrf_ok,
    new_csrf_token,
    normalize_openalex_id,
    parse_scholar_id,
    verify_password,
)
from app.sync import enqueue_job, publication_window_start, store_papers
from app.taxonomy import bump_taxonomy_version, get_taxonomy_version, normalize_keyword
from app.templating import flash, render
from app.thesis_import import (
    MAPPING_FIELDS,
    add_alias,
    apply_mapping,
    cleanup_expired_batches,
    confirm_batch,
    create_batch,
    headers_of,
    mapping_of,
    rollback_batch,
    set_all_review_decisions,
    set_row_decision,
    summary_of,
)


async def csrf_guard(request: Request) -> None:
    """Tolak POST tanpa token yang cocok dengan sesi."""
    if request.method != "POST":
        return
    form = await request.form()
    if not csrf_ok(request.session.get("csrf"), form.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Token CSRF tidak valid.")


router = APIRouter(prefix="/admin", dependencies=[Depends(csrf_guard)])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMPORT_BYTES = MAX_UPLOAD_BYTES
IMPORT_SUFFIXES = (".csv", ".bib", ".bibtex")
THESIS_SUFFIXES = (".csv", ".xlsx")
THESIS_PAGE_SIZE = 100
BATCH_STATUS_LABELS = {
    "mapping": "Pemetaan kolom",
    "preview": "Pratinjau",
    "committed": "Selesai",
    "rolled_back": "Dibatalkan",
}
DECISION_LABELS = {
    "new": "Baru",
    "keep": "Ditambahkan (manual)",
    "skip": "Dilewati (manual)",
    "exact": "Duplikat persis",
    "similar": "Duplikat mirip",
    "review": "Perlu review",
    "unknown_supervisor": "Pembimbing tak dikenal",
    "invalid": "Tidak valid",
}

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
    duplicates = session.exec(
        select(PaperDuplicate).where(PaperDuplicate.status == "pending")
    ).all()
    pending_jobs = session.exec(select(SyncJob).where(SyncJob.status == "pending")).all()
    review_paper_count, review_thesis_count = review_counts(session)
    return render(
        request,
        "admin/dashboard.html",
        counts={
            "lecturers": len(lecturers),
            "active_lecturers": sum(1 for item in lecturers if item.active),
            "topics": sum(1 for item in topics if item.active),
            "keywords": len(keywords),
            "papers": len(session.exec(select(Paper)).all()),
            "theses": len(session.exec(select(Thesis)).all()),
            "duplicates": len(duplicates),
            "pending_jobs": len(pending_jobs),
            "review": review_paper_count + review_thesis_count,
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


@router.get("/dosen/impor")
def lecturer_csv_import_form(request: Request):
    return render(request, "admin/lecturer_import.html")


@router.post("/dosen/impor")
def lecturer_csv_import(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Impor dosen dari CSV langsung ke data web."""
    filename = (file.filename or "").casefold()
    if not filename.endswith(".csv"):
        flash(request, "Berkas harus berupa CSV dengan baris data dosen.")
        return _redirect("/admin/dosen/impor")

    content = file.file.read(MAX_IMPORT_BYTES + 1)
    if not content:
        flash(request, "Berkas kosong.")
        return _redirect("/admin/dosen/impor")
    if len(content) > MAX_IMPORT_BYTES:
        flash(request, "Berkas terlalu besar. Misalnya maksimal 10 MB.")
        return _redirect("/admin/dosen/impor")

    try:
        summary = import_lecturers(session, content)
    except ValueError as error:
        flash(request, str(error))
        return _redirect("/admin/dosen/impor")
    if summary.created or summary.updated:
        details = [
            f"{summary.created} dosen baru",
            f"{summary.updated} dosen diperbarui",
            f"{summary.openalex_added} ID OpenAlex dipetakan",
        ]
        flash(request, "Impor dosen selesai. " + ", ".join(details) + ".")
    if summary.errors:
        flash(request, "Beberapa baris dilewati. Lihat catatan di halaman ini.")
        for error in summary.errors[:5]:
            flash(request, error)
        if len(summary.errors) > 5:
            flash(request, f"... dan {len(summary.errors) - 5} galat lainnya.")
    if not summary.created and not summary.updated and not summary.errors:
        flash(request, "Tidak ada baris dosen yang bisa diimpor.")
    return _redirect("/admin/dosen")


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
    papers = session.exec(
        select(Paper)
        .join(LecturerPaper, LecturerPaper.paper_id == Paper.id)
        .where(LecturerPaper.lecturer_id == lecturer_id)
        .order_by(Paper.year.desc(), Paper.citations.desc(), Paper.title)
    ).all()
    jobs = session.exec(
        select(SyncJob)
        .where(SyncJob.lecturer_id == lecturer_id)
        .order_by(SyncJob.id.desc())
        .limit(10)
    ).all()
    return render(
        request,
        "admin/lecturer_form.html",
        lecturer=lecturer,
        openalex_ids=openalex_ids,
        papers=papers,
        jobs=jobs,
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


def _fail_job(session: Session, job_id: int | None, message: str) -> None:
    session.rollback()
    job = session.get(SyncJob, job_id) if job_id else None
    if job is not None:
        job.status = "failed"
        job.finished_at = utcnow()
        job.error = message[:500]
        session.add(job)
        session.commit()


@router.post("/dosen/{lecturer_id}/sinkronkan")
def lecturer_sync(
    request: Request,
    lecturer_id: int,
    session: Session = Depends(get_session),
):
    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        flash(request, "Dosen tidak ditemukan.")
        return _redirect("/admin/dosen")

    openalex_ids = session.exec(
        select(LecturerOpenAlexId).where(LecturerOpenAlexId.lecturer_id == lecturer_id)
    ).all()
    if not openalex_ids:
        flash(request, "Dosen ini belum punya ID OpenAlex. Petakan dulu sebelum sinkronisasi.")
        return _redirect(f"/admin/dosen/{lecturer_id}")

    job = enqueue_job(session, lecturer_id)
    flash(
        request,
        f"Job sinkronisasi #{job.id} dibuat. Jalankan "
        "`uv run python -m app.jobs sync` untuk memproses.",
    )
    return _redirect(f"/admin/dosen/{lecturer_id}")


@router.get("/dosen/{lecturer_id}/impor")
def lecturer_import_form(
    request: Request,
    lecturer_id: int,
    session: Session = Depends(get_session),
):
    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        flash(request, "Dosen tidak ditemukan.")
        return _redirect("/admin/dosen")
    return render(
        request,
        "admin/import.html",
        lecturer=lecturer,
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    )


@router.post("/dosen/{lecturer_id}/impor")
async def lecturer_import(
    request: Request,
    lecturer_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        flash(request, "Dosen tidak ditemukan.")
        return _redirect("/admin/dosen")

    filename = (file.filename or "").strip()
    if not filename.lower().endswith(IMPORT_SUFFIXES):
        flash(request, "Berkas harus .csv, .bib, atau .bibtex.")
        return _redirect(f"/admin/dosen/{lecturer_id}/impor")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        flash(request, "Berkas lebih dari 10 MB.")
        return _redirect(f"/admin/dosen/{lecturer_id}/impor")
    if not content:
        flash(request, "Berkas kosong.")
        return _redirect(f"/admin/dosen/{lecturer_id}/impor")

    settings = get_settings()
    client = build_client(settings.openalex_base_url, settings.openalex_api_key)
    job = SyncJob(
        lecturer_id=lecturer_id,
        source="manual",
        status="running",
        attempts=1,
        started_at=utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    job_id = job.id

    try:
        provider = ManualImportProvider(filename, content, client=client)
        result = provider.fetch(lecturer, [], publication_window_start(settings))
        stats = store_papers(session, lecturer, result.papers, provider.name)
        reclassify_papers(session, paper_ids=stats.touched)
    except ValueError as error:
        _fail_job(session, job_id, str(error))
        flash(request, str(error))
        return _redirect(f"/admin/dosen/{lecturer_id}/impor")
    except Exception as error:
        _fail_job(session, job_id, f"Impor gagal: {error}")
        flash(request, f"Impor gagal: {error}")
        return _redirect(f"/admin/dosen/{lecturer_id}/impor")
    finally:
        if client is not None:
            client.close()

    done = session.get(SyncJob, job_id)
    if done is not None:
        done.status = "done"
        done.finished_at = utcnow()
        done.new_papers = stats.new
        done.credits_used = float(result.credits)
        session.add(done)
    lecturer.last_synced_at = utcnow()
    lecturer.updated_at = utcnow()
    session.add(lecturer)
    session.commit()

    flash(
        request,
        f"Impor {filename}: {stats.new} paper baru, {stats.merged} diperbarui, "
        f"{stats.duplicates} kandidat duplikat.",
    )
    return _redirect(f"/admin/dosen/{lecturer_id}")


@router.get("/duplikat")
def duplicate_list(request: Request, session: Session = Depends(get_session)):
    rows = session.exec(
        select(PaperDuplicate)
        .where(PaperDuplicate.status == "pending")
        .order_by(PaperDuplicate.created_at.desc())
    ).all()
    items = []
    for row in rows:
        paper = session.get(Paper, row.paper_id)
        candidate = session.get(Paper, row.candidate_id)
        if paper is None or candidate is None:
            continue
        items.append(
            {
                "row": row,
                "paper": paper,
                "candidate": candidate,
                "percent": round(row.similarity * 100, 1),
            }
        )
    return render(request, "admin/duplicates.html", items=items)


@router.post("/duplikat/{duplicate_id}/gabung")
def duplicate_merge(
    request: Request,
    duplicate_id: int,
    session: Session = Depends(get_session),
):
    duplicate = session.get(PaperDuplicate, duplicate_id)
    if duplicate is None or duplicate.status != "pending":
        flash(request, "Kandidat duplikat tidak ditemukan atau sudah diproses.")
        return _redirect("/admin/duplikat")

    paper = session.get(Paper, duplicate.paper_id)
    candidate = session.get(Paper, duplicate.candidate_id)
    if paper is None or candidate is None:
        flash(request, "Salah satu paper sudah tidak ada.")
        return _redirect("/admin/duplikat")

    for link in session.exec(select(LecturerPaper).where(LecturerPaper.paper_id == paper.id)).all():
        exists = session.exec(
            select(LecturerPaper).where(
                LecturerPaper.lecturer_id == link.lecturer_id,
                LecturerPaper.paper_id == candidate.id,
            )
        ).first()
        if exists:
            session.delete(link)
        else:
            link.paper_id = candidate.id
            session.add(link)

    for topic_link in session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all():
        exists = session.exec(
            select(PaperTopic).where(
                PaperTopic.paper_id == candidate.id,
                PaperTopic.topic_id == topic_link.topic_id,
            )
        ).first()
        if exists:
            session.delete(topic_link)
        else:
            topic_link.paper_id = candidate.id
            session.add(topic_link)

    merge_paper_into(candidate, paper)
    session.add(candidate)

    for row in session.exec(
        select(PaperDuplicate).where(
            (PaperDuplicate.paper_id == paper.id) | (PaperDuplicate.candidate_id == paper.id)
        )
    ).all():
        session.delete(row)

    session.flush()
    session.delete(paper)
    session.commit()
    flash(request, "Paper digabung. Paper yang lebih lengkap dipertahankan.")
    return _redirect("/admin/duplikat")


@router.post("/duplikat/{duplicate_id}/biarkan")
def duplicate_keep(
    request: Request,
    duplicate_id: int,
    session: Session = Depends(get_session),
):
    duplicate = session.get(PaperDuplicate, duplicate_id)
    if duplicate is not None and duplicate.status == "pending":
        duplicate.status = "kept"
        session.add(duplicate)
        session.commit()
        flash(request, "Kandidat ditandai bukan duplikat.")
    return _redirect("/admin/duplikat")


def _review_options(session: Session) -> tuple[list[Topic], list[dict[str, object]]]:
    roots = sorted(
        session.exec(select(Topic).where(Topic.parent_id.is_(None), Topic.active.is_(True))).all(),
        key=lambda item: (item.sort_order, item.name),
    )
    children = session.exec(
        select(Topic)
        .where(Topic.parent_id.is_not(None), Topic.active.is_(True))
        .order_by(Topic.sort_order, Topic.name)
    ).all()
    names = {topic.id: topic.name for topic in roots}
    subtopics = [
        {
            "id": child.id,
            "name": child.name,
            "parent_name": names.get(child.parent_id, ""),
        }
        for child in children
    ]
    return roots, subtopics


@router.get("/review")
def review_page(
    request: Request,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    limit = 50
    papers, paper_total = pending_papers(session, offset=max(offset, 0), limit=limit)
    theses, thesis_total = pending_theses(session, offset=max(offset, 0), limit=limit)
    roots, subtopics = _review_options(session)
    return render(
        request,
        "admin/review.html",
        papers=papers,
        theses=theses,
        paper_total=paper_total,
        thesis_total=thesis_total,
        offset=offset,
        limit=limit,
        roots=roots,
        subtopics=subtopics,
        taxonomy_version=get_taxonomy_version(session),
    )


def _manual_topic_from_form(
    request: Request, session: Session, topic_id: str, subtopic_id: str
) -> tuple[int, int | None] | None:
    try:
        topic = int(topic_id)
    except ValueError:
        flash(request, "Pilih topik terlebih dahulu.")
        return None
    subtopic = None
    if subtopic_id.strip():
        try:
            subtopic = int(subtopic_id)
        except ValueError:
            flash(request, "Sub-topik tidak valid.")
            return None
    if session.get(Topic, topic) is None:
        flash(request, "Topik tidak ditemukan.")
        return None
    return topic, subtopic


@router.post("/review/paper/{paper_id}")
def review_paper(
    request: Request,
    paper_id: int,
    topic_id: str = Form(""),
    subtopic_id: str = Form(""),
    tidak_relevan: str = Form(""),
    session: Session = Depends(get_session),
):
    paper = session.get(Paper, paper_id)
    if paper is None:
        flash(request, "Paper tidak ditemukan.")
        return _redirect("/admin/review")
    if tidak_relevan:
        mark_not_relevant(session, paper=paper)
        flash(request, "Paper ditandai tidak relevan dengan topik mana pun.")
        return _redirect("/admin/review")

    parsed = _manual_topic_from_form(request, session, topic_id, subtopic_id)
    if parsed is None:
        return _redirect("/admin/review")
    topic, subtopic = parsed
    try:
        set_manual_label(session, paper=paper, topic_id=topic, subtopic_id=subtopic)
    except ValueError as error:
        flash(request, str(error))
        return _redirect("/admin/review")
    flash(request, "Topik manual disimpan dan dikunci.")
    return _redirect("/admin/review")


@router.post("/review/thesis/{thesis_id}")
def review_thesis(
    request: Request,
    thesis_id: int,
    topic_id: str = Form(""),
    subtopic_id: str = Form(""),
    tidak_relevan: str = Form(""),
    session: Session = Depends(get_session),
):
    thesis = session.get(Thesis, thesis_id)
    if thesis is None:
        flash(request, "Skripsi tidak ditemukan.")
        return _redirect("/admin/review")
    if tidak_relevan:
        mark_not_relevant(session, thesis=thesis)
        flash(request, "Skripsi ditandai tidak relevan dengan topik mana pun.")
        return _redirect("/admin/review")

    parsed = _manual_topic_from_form(request, session, topic_id, subtopic_id)
    if parsed is None:
        return _redirect("/admin/review")
    topic, subtopic = parsed
    try:
        set_manual_label(session, thesis=thesis, topic_id=topic, subtopic_id=subtopic)
    except ValueError as error:
        flash(request, str(error))
        return _redirect("/admin/review")
    flash(request, "Topik manual disimpan dan dikunci.")
    return _redirect("/admin/review")


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


@router.post("/taksonomi/reklasifikasi")
def taxonomy_reclassify(
    request: Request,
    topik: str = Form(""),
    session: Session = Depends(get_session),
):
    topic_id: int | None = None
    if topik.strip():
        try:
            topic_id = int(topik)
        except ValueError:
            flash(request, "Topik untuk klasifikasi ulang tidak valid.")
            return _redirect("/admin/taksonomi")
        if session.get(Topic, topic_id) is None:
            flash(request, "Topik untuk klasifikasi ulang tidak ditemukan.")
            return _redirect("/admin/taksonomi")

    source = "reclassify" if topic_id is None else f"reclassify:{topic_id}"
    existing = session.exec(
        select(SyncJob).where(SyncJob.source == source, SyncJob.status == "pending")
    ).first()
    job = existing
    if job is None:
        job = SyncJob(source=source, status="pending")
        session.add(job)
        session.commit()
        session.refresh(job)
    target = "semua topik" if topic_id is None else f"topik #{topic_id}"
    flash(
        request,
        f"Job klasifikasi ulang #{job.id} untuk {target} dibuat. Jalankan "
        "`uv run python -m app.jobs reclassify` untuk memproses.",
    )
    return _redirect(f"/admin/taksonomi/{topic_id}" if topic_id is not None else "/admin/taksonomi")


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


def _batch_redirect(batch_id: int) -> str:
    return f"/admin/skripsi/{batch_id}"


@router.get("/skripsi")
def thesis_batch_list(request: Request, session: Session = Depends(get_session)):
    cleanup_expired_batches(session)
    batches = session.exec(
        select(ImportBatch).order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()).limit(50)
    ).all()
    items = [{"batch": batch, "summary": summary_of(batch)} for batch in batches]
    return render(
        request,
        "admin/thesis_upload.html",
        items=items,
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
        status_labels=BATCH_STATUS_LABELS,
    )


@router.post("/skripsi/unggah")
async def thesis_upload(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(THESIS_SUFFIXES):
        flash(request, "Berkas skripsi harus .csv atau .xlsx.")
        return _redirect("/admin/skripsi")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        flash(request, "Berkas lebih dari 10 MB.")
        return _redirect("/admin/skripsi")
    try:
        batch = create_batch(session, filename, content)
    except ValueError as error:
        flash(request, str(error))
        return _redirect("/admin/skripsi")

    flash(
        request,
        f"Berkas {batch.filename} dibaca. Petakan kolom sebelum melihat pratinjau.",
    )
    return _redirect(f"/admin/skripsi/{batch.id}/petakan")


@router.get("/skripsi/{batch_id}/petakan")
def thesis_mapping_form(
    request: Request,
    batch_id: int,
    session: Session = Depends(get_session),
):
    cleanup_expired_batches(session)
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan atau sudah kedaluwarsa.")
        return _redirect("/admin/skripsi")
    if batch.status != "mapping":
        return _redirect(_batch_redirect(batch_id))

    rows = session.exec(
        select(ImportRow)
        .where(ImportRow.batch_id == batch_id)
        .order_by(ImportRow.row_number, ImportRow.id)
        .limit(5)
    ).all()
    return render(
        request,
        "admin/thesis_mapping.html",
        batch=batch,
        headers=headers_of(batch),
        mapping=mapping_of(batch),
        fields=MAPPING_FIELDS,
        samples=rows,
    )


@router.post("/skripsi/{batch_id}/petakan")
def thesis_mapping_save(
    request: Request,
    batch_id: int,
    map_judul: str = Form(""),
    map_pembimbing1: str = Form(""),
    map_pembimbing2: str = Form(""),
    map_nama: str = Form(""),
    map_nim: str = Form(""),
    map_tahun: str = Form(""),
    map_topik: str = Form(""),
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan.")
        return _redirect("/admin/skripsi")
    if batch.status != "mapping":
        flash(request, "Pemetaan kolom batch ini sudah disimpan.")
        return _redirect(_batch_redirect(batch_id))

    mapping = {
        "judul": map_judul,
        "pembimbing1": map_pembimbing1,
        "pembimbing2": map_pembimbing2,
        "nama": map_nama,
        "nim": map_nim,
        "tahun": map_tahun,
        "topik": map_topik,
    }
    try:
        summary = apply_mapping(session, batch, mapping)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(f"/admin/skripsi/{batch_id}/petakan")

    flash(
        request,
        f"Pratinjau siap: {summary['new']} baru, {summary['duplicate']} duplikat, "
        f"{summary['review']} perlu review, {summary['unknown']} pembimbing tak dikenal.",
    )
    return _redirect(_batch_redirect(batch_id))


@router.get("/skripsi/{batch_id}")
def thesis_batch_detail(
    request: Request,
    batch_id: int,
    page: int = 1,
    session: Session = Depends(get_session),
):
    cleanup_expired_batches(session)
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan atau sudah kedaluwarsa.")
        return _redirect("/admin/skripsi")
    if batch.status == "mapping":
        return _redirect(f"/admin/skripsi/{batch_id}/petakan")

    summary = summary_of(batch)
    total = int(summary["total"])
    pages = max(1, (total + THESIS_PAGE_SIZE - 1) // THESIS_PAGE_SIZE)
    page = max(1, min(page, pages))
    rows = session.exec(
        select(ImportRow)
        .where(ImportRow.batch_id == batch_id)
        .order_by(ImportRow.row_number, ImportRow.id)
        .offset((page - 1) * THESIS_PAGE_SIZE)
        .limit(THESIS_PAGE_SIZE)
    ).all()
    lecturers = session.exec(select(Lecturer).order_by(Lecturer.name)).all()
    return render(
        request,
        "admin/thesis_batch.html",
        batch=batch,
        summary=summary,
        rows=rows,
        page=page,
        pages=pages,
        lecturers=lecturers,
        status_label=BATCH_STATUS_LABELS.get(batch.status, batch.status),
        decision_labels=DECISION_LABELS,
        rollback=(batch.summary_json or {}).get("rollback"),
    )


@router.post("/skripsi/{batch_id}/baris/{row_id}")
def thesis_row_decision(
    request: Request,
    batch_id: int,
    row_id: int,
    keputusan: str = Form(""),
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    row = session.get(ImportRow, row_id)
    if batch is None or row is None or row.batch_id != batch_id:
        flash(request, "Baris impor tidak ditemukan.")
        return _redirect("/admin/skripsi")
    try:
        set_row_decision(session, batch, row, keputusan)
    except ValueError as error:
        flash(request, str(error))
    return _redirect(_batch_redirect(batch_id))


@router.post("/skripsi/{batch_id}/putuskan")
def thesis_bulk_decision(
    request: Request,
    batch_id: int,
    aksi: str = Form(""),
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan.")
        return _redirect("/admin/skripsi")
    decision = {"lewati": "skip", "tambahkan": "keep"}.get(aksi)
    if decision is None:
        flash(request, "Pilihan keputusan tidak dikenal.")
        return _redirect(_batch_redirect(batch_id))
    try:
        count = set_all_review_decisions(session, batch, decision)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(_batch_redirect(batch_id))
    flash(request, f"{count} baris review diputuskan.")
    return _redirect(_batch_redirect(batch_id))


@router.post("/skripsi/{batch_id}/alias")
def thesis_alias(
    request: Request,
    batch_id: int,
    nama: str = Form(""),
    dosen_id: str = Form(""),
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan.")
        return _redirect("/admin/skripsi")
    try:
        lecturer_id = int(dosen_id)
    except ValueError:
        flash(request, "Pilih dosen untuk nama pembimbing itu.")
        return _redirect(_batch_redirect(batch_id))
    try:
        add_alias(session, batch, nama, lecturer_id)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(_batch_redirect(batch_id))
    flash(request, f"Nama {nama} dipetakan ke dosen.")
    return _redirect(_batch_redirect(batch_id))


@router.post("/skripsi/{batch_id}/konfirmasi")
def thesis_confirm(
    request: Request,
    batch_id: int,
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan.")
        return _redirect("/admin/skripsi")
    try:
        summary = confirm_batch(session, batch)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(_batch_redirect(batch_id))
    flash(
        request,
        f"Batch #{batch_id} dikonfirmasi: {summary['inserted']} skripsi masuk, "
        f"{summary['duplicate']} dilewati, {summary['invalid']} tidak valid.",
    )
    return _redirect(_batch_redirect(batch_id))


@router.post("/skripsi/{batch_id}/rollback")
def thesis_rollback(
    request: Request,
    batch_id: int,
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        flash(request, "Batch impor tidak ditemukan.")
        return _redirect("/admin/skripsi")
    try:
        count = rollback_batch(session, batch)
    except ValueError as error:
        flash(request, str(error))
        return _redirect(_batch_redirect(batch_id))
    flash(request, f"Batch #{batch_id} dibatalkan; {count} skripsi dihapus.")
    return _redirect(_batch_redirect(batch_id))
