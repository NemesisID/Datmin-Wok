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
2. Membuat `.env` dari `.env.example` kalau belum ada, dan mengisi `SECRET_KEY` acak.
3. Membuat folder `data/` untuk database SQLite.
4. Menjalankan migrasi Alembic.
5. Mengimpor `seeds/taxonomy.yaml` (idempoten).

Kalau PowerShell menolak menjalankan skrip:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

## 3. Mengisi `.env`

Buka `.env` dan sesuaikan. Bagian yang wajib diisi hanya kata sandi admin.
`SECRET_KEY` sudah dibuat otomatis oleh skrip setup, tetapi ganti sendiri sebelum deploy.

| Variabel | Arti | Default |
| --- | --- | --- |
| `APP_NAME` | Judul aplikasi | Rekomendasi Pembimbing Skripsi |
| `DATABASE_PATH` | Lokasi file SQLite | `data/app.db` |
| `OPENALEX_API_KEY` | Kunci API OpenAlex. Dikirim lewat header `Authorization: Bearer` | kosong |
| `OPENALEX_BASE_URL` | Alamat API | `https://api.openalex.org` |
| `PUBLICATION_WINDOW_YEARS` | Jendela publikasi yang diambil | `3` |
| `ENABLE_SCHOLAR_SCRAPER` | Scraper HTML Scholar. Jangan dinyalakan | `false` |
| `ADMIN_USERNAME` | Nama pengguna admin | `admin` |
| `ADMIN_PASSWORD_HASH` | Hash kata sandi admin, bukan kata sandi asli | kosong |
| `SECRET_KEY` | Kunci penanda tangan cookie sesi | dibuat otomatis |
| `COOKIE_SECURE` | Setel `true` hanya kalau situs memakai HTTPS | `false` |
| `LOGIN_MAX_ATTEMPTS` | Batas percobaan login per IP | `5` |
| `LOGIN_WINDOW_SECONDS` | Jendela waktu pembatasan login | `900` |
| `USE_LLM` | Klasifikasi tahap 3 dengan LLM | `false` |

Tanpa API key aplikasi tetap jalan, tetapi dibatasi sekitar 10 request per detik.

### Membuat kata sandi admin

```powershell
uv run python -m app.cli hash-password
```

Masukkan kata sandi dua kali, lalu tempel baris `ADMIN_PASSWORD_HASH=...` yang tercetak ke `.env`.
Jalankan `.\scripts\setup.ps1` lagi atau restart aplikasi. Kata sandi asli tidak disimpan di mana pun.

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

Panel admin ada di http://127.0.0.1:8000/admin. Di dalamnya:

1. **Dosen**: tambah dosen, tempel URL Scholar, lalu petakan ID OpenAlex.
2. **Taksonomi**: periksa topik, lab, dan kata kunci. Setiap simpan menaikkan versi taksonomi.
3. **Publikasi**: lihat paper per dosen, buat job sinkronisasi, dan impor ekspor Scholar.
4. **Duplikat**: periksa judul yang mirip 90 sampai 100 persen pada tahun yang sama.

### Menyinkronkan publikasi

Tombol **Sinkronkan sekarang** di halaman dosen hanya membuat job `pending`. Prosesnya
dijalankan dari terminal supaya tidak ada pekerjaan jaringan di dalam request:

```powershell
uv run python -m app.jobs sync                # semua dosen aktif yang punya ID OpenAlex
uv run python -m app.jobs sync --force        # abaikan jeda 7 hari
uv run python -m app.jobs sync --lecturer 3   # satu dosen saja
```

Dosen yang disinkronkan dalam 7 hari terakhir dilewati, kecuali job dibuat lewat tombol admin
atau memakai `--force`. Job yang berstatus `running` lebih dari 30 menit dianggap gagal dan
bisa diulang. Jumlah paper baru, kredit OpenAlex, dan galat tercatat di tabel `sync_jobs` dan
tampil di halaman dosen.

### Impor ekspor Scholar

Halaman dosen punya tombol **Impor CSV/BibTeX Scholar**. Berkas maksimal 10 MB, format `.csv`,
`.bib`, atau `.bibtex`. CSV minimal punya kolom `title` atau `judul`; kolom `year`, `venue`,
`doi`, dan `citations` dipakai kalau ada. Paper digabung berdasarkan DOI, ID OpenAlex, ID
Scholar, atau judul. Judul yang mirip 90 sampai 100 persen pada tahun yang sama tidak digabung
otomatis, tetapi masuk antrean **Duplikat** untuk diputuskan admin. Abstrak yang kosong dicari
ke OpenAlex lewat pencocokan judul.

Perintah CLI yang tersedia:

```powershell
uv run python -m app.cli init-db            # migrasi database
uv run python -m app.cli hash-password      # hash kata sandi admin
uv run python -m app.cli import-taxonomy    # impor ulang seeds/taxonomy.yaml
uv run python -m app.jobs sync              # sinkronisasi publikasi OpenAlex
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

**Ingin mulai dari database kosong.**
Hentikan aplikasi, hapus `data/app.db`, `data/app.db-wal`, dan `data/app.db-shm`, lalu jalankan:

```powershell
uv run python -m app.cli init-db
uv run python -m app.cli import-taxonomy
```

Semua dosen dan pemetaan ID OpenAlex ikut terhapus. Taksonomi dikembalikan dari seed.

**Lupa kata sandi admin.**
Jalankan `uv run python -m app.cli hash-password`, ganti `ADMIN_PASSWORD_HASH` di `.env`, lalu
restart aplikasi.

**Skrip diblokir kebijakan eksekusi.**
Jalankan dengan `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1`.
