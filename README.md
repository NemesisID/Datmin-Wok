# Rekomendasi Pembimbing Skripsi

Sistem internal untuk membantu mahasiswa Prodi Sistem Informasi UPN Veteran Jawa Timur memilih
dosen pembimbing skripsi berdasarkan bukti publikasi dan riwayat bimbingan.

Spesifikasi lengkap: `PRD & Rencana Sistem Rekomendasi Dosen Pembimbing Skripsi (Update).md`.

## Menjalankan

```powershell
.\scripts\setup.ps1     # dependensi, .env, migrasi, seed taksonomi
uv run python -m app.cli hash-password   # buat hash kata sandi admin, tempel ke .env
.\scripts\dev.ps1       # http://127.0.0.1:8000
```

Panel admin: http://127.0.0.1:8000/admin. Cek kesehatan di `/health`.
Panduan lengkap, termasuk isi `.env` dan persiapan data dosen, ada di `docs/setup.md`.

## Tes dan lint

```powershell
.\scripts\check.ps1
```

Isinya `ruff check`, `ruff format --check`, dan `pytest`.

## Spike OpenAlex

```bash
uv run python scripts/spike_openalex.py
```

Menulis laporan ke `docs/openalex-spike.md` dan fixture ke `tests/fixtures/openalex_works_page.json`.
Tanpa API key tetap jalan dengan batas 10 request per detik.

## Status

Fase 0 selesai: kerangka aplikasi, konfigurasi, klien OpenAlex, dan hasil spike.

Fase 1 selesai: skema 17 tabel dengan Alembic, seed taksonomi 23 topik dan 166 kata kunci,
login admin dengan CSRF dan pembatas percobaan, CRUD dosen, pemetaan ID OpenAlex,
editor taksonomi dengan `taxonomy_version`.

Fase 2 selesai: sinkronisasi OpenAlex lewat `sync_jobs` dan CLI `python -m app.jobs`,
impor CSV/BibTeX Scholar, deduplikasi berbasis DOI/ID/judul, serta antrean duplikat
untuk judul yang mirip 90 sampai 100 persen pada tahun yang sama.

Fase 3 selesai: klasifikasi topik multi-label deterministik untuk paper dan skripsi,
sub-topik dengan fallback "Umum", antrean review dengan navigasi keyboard, override
manual terkunci, FTS5 untuk pencarian judul, dan skrip evaluasi golden set (micro/macro F1).

Fase 4 selesai: impor skripsi lama dari CSV/XLSX lewat pemetaan kolom dan pratinjau,
deteksi duplikat berbasis judul/tahun/NIM/kemiripan dengan blok pembimbing, pemetaan alias
pembimbing, konfirmasi atomik, rollback batch, dan pembersihan pratinjau kedaluwarsa.

Fase 5 sampai 6 menyusul sesuai bagian 13 PRD.
