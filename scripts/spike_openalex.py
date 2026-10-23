"""Spike Fase 0: verifikasi perilaku OpenAlex pada dosen Prodi Sistem Informasi UPNVJT.

Menjawab tiga pertanyaan yang menentukan Fase 2:
1. Berapa kandidat penulis per dosen dan apakah record-nya bisa dipercaya.
2. Berapa karya dalam jendela 3 tahun dan berapa yang punya abstrak.
3. Berapa biaya kredit per request dan apakah per_page=100 benar-benar berlaku.

Jalankan: uv run python scripts/spike_openalex.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers.openalex import fetch_author_works, find_author_candidates  # noqa: E402

BASE_URL = os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org")
API_KEY = os.getenv("OPENALEX_API_KEY", "")
WINDOW_YEARS = int(os.getenv("PUBLICATION_WINDOW_YEARS", "3"))
FIXTURE = Path("tests/fixtures/openalex_works_page.json")
REPORT = Path("docs/openalex-spike.md")

# Dosen Prodi Sistem Informasi UPNVJT (sumber: sisfo.upnjatim.ac.id/dosen dan
# fasilkom.upnjatim.ac.id/dosen-staff). Nama tanpa gelar agar cocok dengan OpenAlex.
LECTURERS = [
    "Nur Cahyo Wibowo",
    "Tri Lathif Mardi Suryanto",
    "Asif Faroqi",
    "Reisa Permatasari",
    "Imroatul Ajizah",
    "Anindo Saka Fitri",
    "Seftin Fitri Ana Wati",
    "Iqbal Ramadhani Mukhlis",
    "Doddy Ridwandono",
    "Mohamad Irwan Afandi",
]

UPN_HINTS = ("pembangunan nasional", "upn", "veteran")


def client() -> httpx.Client:
    headers = {"User-Agent": "rekomendasi-pembimbing/0.1 (spike fase 0)"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0)


def is_upn(institutions: list[str]) -> bool:
    joined = " ".join(institutions).lower()
    return any(hint in joined for hint in UPN_HINTS)


def pick_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pilih kandidat yang paling masuk akal: afiliasi UPN dulu, lalu karya terbanyak."""
    upn = [candidate for candidate in candidates if is_upn(candidate["institutions"])]
    pool = upn or candidates
    if not pool:
        return None
    return max(pool, key=lambda item: item["works_count"] or 0)


def main() -> int:
    since = date.today().replace(year=date.today().year - WINDOW_YEARS)
    rows: list[dict[str, Any]] = []
    fixture_saved = False
    first_page_raw: dict[str, Any] | None = None

    with client() as http:
        for name in LECTURERS:
            candidates = find_author_candidates(http, name)
            chosen = pick_candidate(candidates)
            row: dict[str, Any] = {
                "name": name,
                "candidates": len(candidates),
                "upn_candidates": sum(1 for c in candidates if is_upn(c["institutions"])),
                "chosen": chosen["openalex_id"] if chosen else None,
                "chosen_name": chosen["name"] if chosen else None,
                "chosen_works_total": chosen["works_count"] if chosen else None,
                "chosen_institutions": len(chosen["institutions"]) if chosen else 0,
                "chosen_topics": ", ".join(chosen["topics"]) if chosen else "",
                "works_in_window": 0,
                "abstracts": 0,
                "pages": 0,
                "cost_usd": 0.0,
            }
            if chosen:
                works, meta = fetch_author_works(http, chosen["openalex_id"], since)
                row["works_in_window"] = len(works)
                row["abstracts"] = sum(1 for work in works if work["abstract"])
                row["pages"] = meta["pages"]
                row["cost_usd"] = round(meta["cost_usd"], 6)
                row["page_sizes"] = meta["page_sizes"]
                row["credits_used"] = meta["credits_used"]
                row["titles"] = [work["title"] for work in works[:3]]
                if not fixture_saved and meta["page_sizes"] and meta["page_sizes"][0] > 0:
                    response = http.get(
                        "/works",
                        params={
                            "filter": (
                                f"authorships.author.id:{chosen['openalex_id']},"
                                f"from_publication_date:{since.isoformat()}"
                            ),
                            "select": ",".join(
                                [
                                    "id",
                                    "doi",
                                    "display_name",
                                    "publication_year",
                                    "cited_by_count",
                                    "abstract_inverted_index",
                                    "authorships",
                                    "primary_location",
                                ]
                            ),
                            "per_page": 25,
                        },
                    )
                    response.raise_for_status()
                    first_page_raw = response.json()
                    fixture_saved = True
            rows.append(row)
            print(
                f"{name:32} kandidat={row['candidates']:2} "
                f"3thn={row['works_in_window']:3} abstrak={row['abstracts']:3}"
            )
            time.sleep(0.2)

    if first_page_raw:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(
            json.dumps(first_page_raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    total_works = sum(row["works_in_window"] for row in rows)
    total_abstracts = sum(row["abstracts"] for row in rows)
    coverage = (total_abstracts / total_works * 100) if total_works else 0
    big_pages = [row for row in rows if max(row.get("page_sizes") or [0]) >= 100]

    lines = [
        "# Spike OpenAlex, Fase 0",
        "",
        f"Tanggal: {date.today().isoformat()}  ",
        f"Jendela: sejak {since.isoformat()} ({WINDOW_YEARS} tahun)  ",
        f"API key dipakai: {'ya' if API_KEY else 'tidak'}",
        "",
        "## Hasil per dosen",
        "",
        "| Dosen | Kandidat | Kandidat UPN | ID terpilih | Karya 3 tahun | Berabstrak | "
        "Halaman | Biaya USD |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['candidates']} | {row['upn_candidates']} | "
            f"{row['chosen'] or '-'} | {row['works_in_window']} | {row['abstracts']} | "
            f"{row['pages']} | {row['cost_usd']} |"
        )
    lines += [
        "",
        f"Total karya dalam jendela: **{total_works}**  ",
        f"Berabstrak: **{total_abstracts}** ({coverage:.1f} persen)  ",
        f"Dosen dengan halaman berisi 100 karya: **{len(big_pages)}**  ",
        "",
        "## Catatan",
        "",
    ]
    no_data = [row["name"] for row in rows if row["works_in_window"] == 0]
    if no_data:
        lines.append(f"- Tanpa karya di jendela: {', '.join(no_data)}.")
    low = [row["name"] for row in rows if 0 < row["works_in_window"] < 3]
    if low:
        lines.append(f"- Bukti sangat tipis (1 sampai 2 karya): {', '.join(low)}.")
    lines.append(
        "- Kandidat UPN berasal dari `last_known_institutions`, yang bisa menggabungkan "
        "beberapa orang. Judul karya tetap harus diperiksa admin sebelum dikonfirmasi."
    )
    if not big_pages:
        lines.append(
            "- Tidak ada dosen yang melewati 100 karya di jendela ini, jadi paging lebih dari "
            "satu halaman tidak teruji pada korpus prodi. Batas `per_page` diuji terpisah."
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    print(f"Karya {total_works}, abstrak {total_abstracts} ({coverage:.1f} persen)")
    print(f"Laporan: {REPORT}")
    print(f"Fixture: {FIXTURE if fixture_saved else 'tidak tersimpan'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
