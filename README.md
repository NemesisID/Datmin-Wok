# Rekomendasi Pembimbing Skripsi

Sistem internal untuk membantu mahasiswa Prodi Sistem Informasi UPN Veteran Jawa Timur memilih
dosen pembimbing skripsi berdasarkan bukti publikasi dan riwayat bimbingan.

Spesifikasi lengkap: `PRD & Rencana Sistem Rekomendasi Dosen Pembimbing Skripsi (Update).md`.

## Menjalankan

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Buka http://127.0.0.1:8000. Cek kesehatan di `/health`.

## Tes dan lint

```bash
uv run pytest
uv run ruff check .
```

## Spike OpenAlex

```bash
uv run python scripts/spike_openalex.py
```

Menulis laporan ke `docs/openalex-spike.md` dan fixture ke `tests/fixtures/openalex_works_page.json`.
Tanpa API key tetap jalan dengan batas 10 request per detik.

## Status

Fase 0 selesai: kerangka aplikasi, konfigurasi, klien OpenAlex, dan hasil spike.
Halaman publik, klasifikasi, dan unggah skripsi menyusul sesuai bagian 13 PRD.
