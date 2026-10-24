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
| `RECENCY_HALF_LIFE_YEARS` | Half-life bobot recency paper | `2` |
| `THESIS_LAMBDA` | Bobot bukti skripsi terhadap paper | `1.5` |
| `STALE_DAYS` | Umur data sebelum ditandai usang | `90` |
| `BACKUP_DIR` | Folder backup SQLite | `data/backups` |
| `BACKUP_DAILY_KEEP` | Jumlah backup harian yang disimpan | `7` |
| `BACKUP_MONTHLY_KEEP` | Jumlah backup bulanan yang disimpan | `1` |
| `ENABLE_SCHOLAR_SCRAPER` | Scraper HTML Scholar. Jangan dinyalakan | `false` |
| `ADMIN_USERNAME` | Nama pengguna admin | `admin` |
| `ADMIN_PASSWORD_HASH` | Hash kata sandi admin, bukan kata sandi asli | kosong |
| `SECRET_KEY` | Kunci penanda tangan cookie sesi | dibuat otomatis |
| `COOKIE_SECURE` | Setel `true` hanya kalau situs memakai HTTPS | `false` |
| `LOGIN_MAX_ATTEMPTS` | Batas percobaan login per IP | `5` |
| `LOGIN_WINDOW_SECONDS` | Jendela waktu pembatasan login | `900` |
| `USE_LLM` | Klasifikasi tahap 3 dengan LLM | `false` |
| `LLM_PROVIDER` | `openai` (OpenAI-compatible) atau `ollama` | kosong |
| `LLM_MODEL` | Nama model yang dipakai provider | kosong |
| `LLM_BASE_URL` | Alamat API provider | tergantung provider |
| `LLM_API_KEY` | Kunci API provider OpenAI-compatible | kosong |
| `LLM_BATCH_SIZE` | Jumlah paper per panggilan LLM | `20` |
| `LLM_TIMEOUT_SECONDS` | Batas waktu satu panggilan LLM | `30` |

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
2. **Taksonomi**: periksa topik, lab, dan kata kunci. Setiap simpan menaikkan versi
   taksonomi. Klasifikasi ulang bisa untuk semua topik atau satu topik saja.
3. **Review**: tinjau paper dan skripsi tanpa topik, dengan keyakinan rendah, atau dua topik
   berdekatan. Pilihan manual dikunci dan tidak ditimpa klasifikasi ulang.
4. **Publikasi**: lihat paper per dosen, buat job sinkronisasi, dan impor ekspor Scholar.
5. **Skripsi**: unggah data skripsi lama lewat pratinjau, petakan pembimbing, lalu konfirmasi.
6. **Duplikat**: periksa judul yang mirip 90 sampai 100 persen pada tahun yang sama.

### Halaman publik

Halaman publik tidak memerlukan login:

- `/` untuk mencari dengan kata kunci, lab, beberapa topik, sub-topik, dan rentang tahun paper.
- `/dosen` untuk daftar dosen dan topik utama.
- `/dosen/{id}` untuk profil, sebaran topik per lab, paper, dan skripsi yang dibimbing.
- `/topik` untuk melihat dosen teratas di setiap topik.
- `/bandingkan?dosen=1&dosen=2` untuk membandingkan maksimal tiga dosen.

Nama mahasiswa dan NIM tidak pernah dikirim ke halaman publik. Hasil rekomendasi memakai
peringkat, label kekuatan bukti (`Lemah`, `Cukup`, `Kuat`), dan daftar bukti, tanpa angka skor.
Dosen yang belum punya bukti masuk grup "belum ada data" di bagian bawah.

### Backup database

Backup memakai `VACUUM INTO`, bukan menyalin file database yang sedang dipakai:

```powershell
uv run python -m app.cli backup
```

Hasilnya ada di `data/backups/harian/app-YYYY-MM-DD.db` dan
`data/backups/bulanan/app-YYYY-MM.db`. Default retensi adalah 7 backup harian dan 1 bulanan.
Jalankan perintah ini lewat cron atau Task Scheduler setiap hari. Panduan container ada di
`docs/deploy.md`.

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

### Impor skripsi lama

Menu **Skripsi** mengisi riwayat bimbingan dari berkas CSV atau XLSX. Berkas maksimal 10 MB.
XLSX dibaca dari lembar kerja pertama. CSV boleh memakai pemisah koma, titik koma, tab, atau
pipa. Kolom wajib hanya judul dan pembimbing 1; kolom opsional adalah pembimbing 2, nama
mahasiswa, NIM, tahun, dan topik. Contoh ada di `seeds/theses.example.csv`.

Alurnya selalu tiga tahap:

1. **Petakan kolom**: sistem menebak nama kolom, admin bisa mengubahnya.
2. **Pratinjau**: tiap baris diberi keputusan baru, duplikat persis, duplikat mirip, perlu
   review, pembimbing tak dikenal, atau tidak valid. Baris review bisa ditambahkan atau
   dilewati satu per satu maupun sekaligus. Nama pembimbing yang belum cocok dipetakan ke
   dosen; alias disimpan untuk impor berikutnya.
3. **Konfirmasi**: hanya baris baru dan baris yang ditambahkan manual yang disimpan. Insert dan
   klasifikasi topik berjalan dalam satu transaksi. Sebelum konfirmasi tidak ada skripsi yang
   masuk ke basis data.

Aturan duplikat:

- Judul dan tahun sama, atau NIM sama: dilewati sebagai duplikat persis.
- Judul sama dengan selisih tahun lebih dari satu: perlu review.
- Kemiripan judul di atas 90 persen dan ada pembimbing yang sama pada tahun berdekatan:
  dilewati sebagai duplikat mirip.
- Kemiripan 80 sampai 90 persen pada blok pembimbing yang sama dan tahun berdekatan: perlu
  review.
- Duplikat di dalam satu berkas juga dideteksi.

Kolom topik hanya dipakai kalau namanya persis sama dengan topik aktif. Label dari impor
dikunci dengan `source="import"`; kalau tidak cocok, classifier tetap berjalan dari judul.
Pratinjau yang tidak dikonfirmasi dalam 24 jam dibersihkan. **Rollback** pada batch selesai
menghapus skripsi batch itu beserta alias yang dibuatnya, tanpa menyentuh batch lain.

### Review dan klasifikasi ulang

Paper baru langsung diklasifikasi saat sinkronisasi atau impor. Halaman **Review** menampung
paper dan skripsi yang belum punya topik, keyakinannya di bawah 0,5, atau selisih dua topik
teratasnya kurang dari 0,1. Pintasan keyboard: `j`/`k` pindah kartu, `1`–`9` pilih topik,
`x` tandai tidak relevan, `Enter` simpan.

Setelah mengubah kata kunci di halaman **Taksonomi**, tekan **Buat job klasifikasi ulang** lalu
jalankan:

```powershell
uv run python -m app.jobs reclassify
```

Tombol di halaman taksonomi memproses semua topik. Untuk cakupan lebih kecil, buka satu topik
dan tekan **Buat job untuk topik ini**. Job bertopik hanya memeriksa paper dan skripsi yang
punya label lama pada topik itu atau teksnya cocok dengan kata kunci topik saat ini; topik anak
diproses bersama topik induk.

Job ini mengklasifikasi ulang paper dan skripsi yang belum ditinjau. Label `locked=true` dan
keputusan "tidak relevan" tetap dipertahankan. Versi taksonomi ikut dicatat di setiap label.
Setelah memperbarui dari Fase 2, jalankan sekali agar paper lama ikut berlabel.

### LLM opsional (Tahap 3)

Aturan kata kunci tetap berjalan lebih dulu. LLM hanya dipanggil untuk paper yang masih ambigu:
tanpa topik, keyakinan di bawah 0,5, atau selisih dua topik teratas kurang dari 0,1. Hasil LLM
disimpan dengan `source="llm"`. Label manual yang dikunci dan paper yang sudah ditinjau tidak
pernah ditimpa.

Default `USE_LLM=false`, jadi aplikasi berjalan tanpa jaringan ke LLM. Untuk menyalakan
provider OpenAI-compatible:

```dotenv
USE_LLM=true
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=isi-kunci
```

Untuk Ollama lokal:

```dotenv
USE_LLM=true
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
LLM_BASE_URL=http://127.0.0.1:11434
```

Setelah itu jalankan `uv run python -m app.jobs sync` atau
`uv run python -m app.jobs reclassify`. Hanya judul dan abstrak yang dikirim ke provider.

Hasil disimpan di tabel `llm_cache` dengan kunci
`sha256(judul + abstrak + taxonomy_version)`. Paper dengan isi dan versi taksonomi yang sama
tidak memanggil LLM lagi. Mengubah kata kunci menaikkan versi taksonomi, sehingga cache lama
tidak dipakai. Bila provider gagal, job ditandai gagal dan label dari proses itu tidak
setengah tersimpan. Kunci API tidak pernah ditulis ke log atau query string.

Perintah CLI yang tersedia:

```powershell
uv run python -m app.cli init-db            # migrasi database
uv run python -m app.cli hash-password      # hash kata sandi admin
uv run python -m app.cli import-taxonomy    # impor ulang seeds/taxonomy.yaml
uv run python -m app.jobs sync              # sinkronisasi publikasi OpenAlex
uv run python -m app.jobs reclassify        # klasifikasi ulang paper dan skripsi
```

## 5. Tes dan lint

```powershell
.\scripts\check.ps1
```

Isinya: `ruff check .`, `ruff format --check .`, lalu `pytest -q`.
Tes tidak boleh memanggil jaringan. Data uji ada di `tests/fixtures/`.

Evaluasi classifier memakai golden set berlabel manual (minimal 150 paper sesuai PRD):

```powershell
Copy-Item seeds\golden_set.example.csv seeds\golden_set.csv
# isi kolom judul, abstrak, topik (pisahkan topik dengan ;)
uv run python scripts\evaluate_classifier.py
```

Skrip mencetak micro precision/recall/F1, macro F1, dan skor per topik. Jalankan setiap
`taxonomy_version` berubah. Contoh 22 baris hanya untuk memastikan skrip berjalan, bukan
golden set final.

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
