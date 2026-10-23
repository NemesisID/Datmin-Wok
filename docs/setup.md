# Panduan Setup

Panduan ini untuk Windows dengan PowerShell. Linux dan macOS memakai perintah `uv` yang sama,
hanya skrip `.ps1` yang diganti perintah manual.

## 1. Prasyarat

- Windows 10 atau lebih baru.
- [uv](https://docs.astral.sh/uv/) untuk mengelola Python dan dependensi.
- Git.

Kalau `uv` belum ada:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Tutup PowerShell, buka lagi, lalu cek:

```powershell
uv --version
```

Python tidak perlu dipasang manual. `uv` mengunduh versi yang sesuai saat `uv sync`.

## 2. Setup pertama

Dari folder proyek:

```powershell
.\scripts\setup.ps1
```

Skrip ini, dan aman dijalankan berulang:

1. Memasang dependensi dari `pyproject.toml` ke `.venv`.
2. Membuat `.env` dari `.env.example` kalau belum ada.
3. Membuat folder `data/` untuk database SQLite.
4. Memeriksa bahwa paket inti bisa diimpor.

Kalau PowerShell menolak menjalankan skrip:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

## 3. Mengisi `.env`

Buka `.env` dan sesuaikan. Hanya `OPENALEX_API_KEY` yang perlu diisi kalau Anda punya kuncinya.

| Variabel | Arti | Default |
| --- | --- | --- |
| `APP_NAME` | Judul aplikasi | Rekomendasi Pembimbing Skripsi |
| `DATABASE_PATH` | Lokasi file SQLite | `data/app.db` |
| `OPENALEX_API_KEY` | Kunci API OpenAlex. Dikirim lewat header `Authorization: Bearer` | kosong |
| `OPENALEX_BASE_URL` | Alamat API | `https://api.openalex.org` |
| `PUBLICATION_WINDOW_YEARS` | Jendela publikasi yang diambil | `3` |
| `ENABLE_SCHOLAR_SCRAPER` | Scraper HTML Scholar. Jangan dinyalakan | `false` |
| `USE_LLM` | Klasifikasi tahap 3 dengan LLM | `false` |

Tanpa API key aplikasi tetap jalan, tetapi dibatasi sekitar 10 request per detik.

## 4. Menjalankan

```powershell
.\scripts\dev.ps1              # http://127.0.0.1:8000
.\scripts\dev.ps1 -Port 8001   # port lain
.\scripts\dev.ps1 -NoReload    # tanpa auto-reload
```

Cek kesehatan:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
```

## 5. Tes dan lint

```powershell
.\scripts\check.ps1
```

Isinya: `ruff check .`, `ruff format --check .`, lalu `pytest -q`.
Tes tidak boleh memanggil jaringan. Data uji ada di `tests/fixtures/`.

## 6. Persiapan data dosen

Isi `seeds/lecturers.example.csv` lalu simpan sebagai `seeds/lecturers.csv`. File contoh sudah
berisi 10 dosen Prodi Sistem Informasi dan ID OpenAlex hasil spike Fase 0.

| Kolom | Isi |
| --- | --- |
| `nama` | Nama tanpa gelar, sama seperti di OpenAlex |
| `nidn` | Boleh kosong |
| `url_scholar` | URL profil Google Scholar, untuk impor manual |
| `openalex_id` | ID penulis OpenAlex, misalnya `A5056916903` |
| `catatan` | Catatan bebas, misalnya alasan memilih kandidat |

ID di file contoh masih berupa kandidat. Cek satu per satu sebelum dipakai:

1. Buka `https://api.openalex.org/authors/A5056916903` di browser.
2. Cocokkan nama, institusi, dan tiga topik teratas dengan dosen yang dimaksud.
3. Kalau salah orang, cari ulang lewat `https://api.openalex.org/authors?search=Nama%20Dosen`.

Nama yang punya banyak kandidat (Reisa Permatasari 6, Anindo Saka Fitri 7) wajib dicek manual.
Rincian per dosen ada di `docs/openalex-spike.md`.

Yang masih perlu Anda siapkan:

- Daftar dosen tetap prodi, termasuk yang belum punya publikasi.
- URL profil Google Scholar tiap dosen, kalau ada.
- Ekspor CSV atau BibTeX dari Scholar, hanya untuk paper yang tidak ada di OpenAlex.

## 7. Mengulang spike OpenAlex

Opsional, untuk memperbarui angka dan fixture:

```powershell
uv run python scripts/spike_openalex.py
```

Menulis `docs/openalex-spike.md` dan `tests/fixtures/openalex_works_page.json`.

## 8. Kalau ada masalah

**`uv sync` seperti gagal padahal berhasil.**
PowerShell menandai tulisan `uv` di stderr sebagai error. Lihat baris terakhir: kalau tertulis
`Checked ... packages`, semuanya baik. Pastikan dengan:

```powershell
uv run python -c "import fastapi; print('ok')"
```

**`uv` tidak ditemukan padahal baru dipasang.**
Tutup dan buka lagi PowerShell, atau jalankan `refreshenv`.

**Port sudah dipakai.**
Pakai port lain: `.\scripts\dev.ps1 -Port 8001`.

**Dependensi rusak setelah ganti versi Python.**
Hapus `.venv` lalu jalankan `.\scripts\setup.ps1` lagi. Jangan hapus `uv.lock`.

**Skrip diblokir kebijakan eksekusi.**
Jalankan dengan `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1`.
