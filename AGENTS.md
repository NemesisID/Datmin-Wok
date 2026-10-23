# AGENTS.md

## Proyek

Sistem rekomendasi dosen pembimbing skripsi untuk Prodi Sistem Informasi UPN Veteran Jawa Timur.
Sumber kebenaran produk adalah `PRD & Rencana Sistem Rekomendasi Dosen Pembimbing Skripsi (Update).md`.
Baca PRD sebelum mengubah perilaku apa pun.

## Perintah

```bash
uv sync                      # pasang dependensi
uv run uvicorn app.main:app --reload   # jalankan aplikasi
uv run pytest                # tes
uv run ruff check .          # lint
uv run ruff format .         # format
uv run python scripts/spike_openalex.py  # spike API OpenAlex
```

Di Windows, pakai skrip pembungkusnya:

```powershell
.\scripts\setup.ps1   # dependensi, .env, folder data
.\scripts\dev.ps1     # jalankan aplikasi
.\scripts\check.ps1   # lint, format, tes
```

## Aturan yang tidak boleh dilanggar

1. Jangan men-scrape HTML Google Scholar. Sumber data: OpenAlex API, ekspor Scholar, dan file unggahan.
2. Deduplikasi paper hanya memakai DOI, ID OpenAlex, ID Scholar, atau judul. Jangan pernah membandingkan abstrak untuk menentukan duplikat.
3. Jangan menampilkan skor 0 sampai 100 ke mahasiswa. Hasil memakai peringkat, label kekuatan bukti, dan daftar bukti.
4. Jangan menambah tabel atau kolom untuk skor yang diprakomputasi (`lecturer_topic_scores`). Skor dihitung saat query.
5. Jangan memakai `BackgroundTasks` untuk sinkronisasi. Job memakai tabel `sync_jobs` dan CLI `python -m app.jobs`.
6. Jangan menambah tabel `admins` atau sistem peran. Satu akun admin dari env.
7. Jendela publikasi default 3 tahun (`PUBLICATION_WINDOW_YEARS`). Jendela adalah filter pengambilan, bukan aturan hapus.
8. Jangan mengarang data. Dosen tanpa bukti tampil sebagai "belum ada data", bukan skor nol.
9. API key OpenAlex dikirim lewat header `Authorization: Bearer`, tidak pernah di query string atau log.
10. Tambah dependensi hanya kalau stdlib atau dependensi yang sudah ada tidak cukup.

## Konvensi kode

- Python 3.12+, type hint di semua fungsi publik.
- Ruff dengan line length 100. Jalankan `uv run ruff check .` sebelum menyatakan selesai.
- Setiap logika non-trivial (cabang, loop, parser, uang, keamanan) meninggalkan satu tes.
- Tes tidak boleh memanggil jaringan. Pakai fixture JSON di `tests/fixtures/`.
- Komentar hanya untuk menjelaskan "mengapa", bukan "apa".

## Status fase

- [x] Fase 0: fondasi, spike OpenAlex
- [x] Fase 1: skema, taksonomi, admin dasar
- [ ] Fase 2: sinkronisasi publikasi
- [ ] Fase 3: klasifikasi dan review
- [ ] Fase 4: upload skripsi
- [ ] Fase 5: halaman publik, skor, deploy
- [ ] Fase 6: LLM opsional dan poles

Mulai setiap fase dengan rencana singkat, lalu tunggu persetujuan. Akhiri setiap fase dengan tes, ringkasan, dan berhenti.
