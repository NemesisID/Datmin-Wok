"""Halaman publik: pencarian, profil dosen, jelajah topik, dan perbandingan."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from app.db import get_session
from app.recommend import (
    MAX_COMPARE,
    SearchFilters,
    compare_profiles,
    filter_options,
    lecturer_profile,
    recommend,
    topic_explorer,
)
from app.templating import render

router = APIRouter()


def _year_range(
    year_from: int | None, year_to: int | None, current_year: int
) -> tuple[int | None, int | None]:
    for year in (year_from, year_to):
        if year is not None and (year < 1900 or year > current_year + 1):
            raise HTTPException(status_code=400, detail="Rentang tahun tidak wajar.")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise HTTPException(status_code=400, detail="Tahun awal tidak boleh melebihi tahun akhir.")
    return year_from, year_to


def _topic_choices(
    topik: list[int] | None, subtopik: list[int] | None
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return tuple(topik or []), tuple(subtopik or [])


@router.get("/")
def home(
    request: Request,
    q: str = "",
    lab: str = "",
    topik: list[int] | None = Query(default=None),
    subtopik: list[int] | None = Query(default=None),
    tahun_dari: int | None = None,
    tahun_sampai: int | None = None,
    session: Session = Depends(get_session),
):
    current_year = date.today().year
    tahun_dari, tahun_sampai = _year_range(tahun_dari, tahun_sampai, current_year)
    topic_ids, subtopic_ids = _topic_choices(topik, subtopik)
    filters = SearchFilters(
        lab=lab,
        topic_ids=topic_ids,
        subtopic_ids=subtopic_ids,
        year_from=tahun_dari,
        year_to=tahun_sampai,
        query=(q or "").strip()[:200],
        current_year=current_year,
    )
    try:
        result = recommend(session, filters)
        options = filter_options(session, lab)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return render(
        request,
        "public/home.html",
        result=result,
        options=options,
        filters=filters,
        current_year=current_year,
        max_compare=MAX_COMPARE,
    )


@router.get("/dosen")
def lecturers(
    request: Request,
    lab: str = "",
    session: Session = Depends(get_session),
):
    try:
        result = recommend(session, SearchFilters(lab=lab))
        options = filter_options(session, lab)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return render(
        request,
        "public/lecturers.html",
        result=result,
        options=options,
        lab=lab,
        max_compare=MAX_COMPARE,
    )


@router.get("/dosen/{lecturer_id}")
def lecturer_detail(
    request: Request,
    lecturer_id: int,
    topik: int | None = None,
    tahun_dari: int | None = None,
    tahun_sampai: int | None = None,
    session: Session = Depends(get_session),
):
    current_year = date.today().year
    tahun_dari, tahun_sampai = _year_range(tahun_dari, tahun_sampai, current_year)
    options = filter_options(session, "")
    if topik is not None and not any(topic.id == topik for topic in options.roots):
        raise HTTPException(status_code=404, detail="Topik tidak ditemukan.")
    profile = lecturer_profile(
        session,
        lecturer_id,
        topic_id=topik,
        year_from=tahun_dari,
        year_to=tahun_sampai,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Dosen tidak ditemukan.")
    return render(
        request,
        "public/lecturer.html",
        profile=profile,
        options=options,
        selected_topic=topik,
        year_from=tahun_dari,
        year_to=tahun_sampai,
        current_year=current_year,
    )


@router.get("/topik")
def topics(
    request: Request,
    lab: str = "",
    session: Session = Depends(get_session),
):
    try:
        explorer = topic_explorer(session, lab=lab)
        options = filter_options(session, lab)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return render(
        request,
        "public/topics.html",
        explorer=explorer,
        options=options,
        lab=lab,
        current_year=date.today().year,
    )


@router.get("/bandingkan")
def compare(
    request: Request,
    dosen: list[int] | None = Query(default=None),
    session: Session = Depends(get_session),
):
    ids = list(dict.fromkeys(dosen or []))
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Pilih setidaknya dua dosen.")
    if len(ids) > MAX_COMPARE:
        raise HTTPException(
            status_code=400,
            detail=f"Maksimal {MAX_COMPARE} dosen untuk dibandingkan.",
        )
    try:
        profiles = compare_profiles(session, ids)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return render(
        request,
        "public/compare.html",
        profiles=profiles,
        current_year=date.today().year,
    )
