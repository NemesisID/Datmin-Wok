# Rekomendasi Pembimbing Skripsi

Sistem internal untuk membantu mahasiswa Prodi Sistem Informasi UPN Veteran Jawa Timur memilih
dosen pembimbing skripsi berdasarkan bukti publikasi dan riwayat bimbingan.

Spesifikasi lengkap: `PRD & Rencana Sistem Rekomendasi Dosen Pembimbing Skripsi (Update).md`.

## Menjalankan

```powershell
.\scripts\setup.ps1     # sekali jalan: dependensi, .env, folder data
.\scripts\dev.ps1       # http://127.0.0.1:8000
```

Cek kesehatan di `/health`. Panduan lengkap, termasuk isi `.env` dan persiapan data dosen,
ada di `docs/setup.md`.

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
Halaman publik, klasifikasi, dan unggah skripsi menyusul sesuai bagian 13 PRD.
