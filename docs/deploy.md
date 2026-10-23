# Deploy

Panduan ini memakai satu container aplikasi. Database SQLite dan backup disimpan di volume
host, bukan di dalam image.

## 1. Siapkan environment

Dari folder proyek di server:

```bash
cp .env.example .env
```

Isi minimal:

```dotenv
APP_NAME=Rekomendasi Pembimbing Skripsi
SECRET_KEY=ganti-dengan-string-acak-panjang
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=scrypt$...
COOKIE_SECURE=true
DATABASE_PATH=/data/app.db
BACKUP_DIR=/backups
PUBLICATION_WINDOW_YEARS=3
OPENALEX_API_KEY=...
```

Buat hash kata sandi dengan salah satu cara berikut:

```bash
uv run python -m app.cli hash-password
```

atau setelah image dibangun:

```bash
docker compose run --rm app python -m app.cli hash-password
```

`COOKIE_SECURE=true` hanya dipakai di belakang HTTPS. Untuk uji lokal tanpa HTTPS, biarkan
`false`.

## 2. Build dan jalankan

```bash
docker compose build
docker compose up -d
docker compose ps
```

Saat start, container menjalankan migrasi Alembic lalu Uvicorn di port `8000`. Cek:

```bash
curl http://127.0.0.1:8000/health
```

Setelah container hidup, impor taksonomi sekali:

```bash
docker compose exec app python -m app.cli import-taxonomy
```

Buka panel admin di `/admin`, tambahkan dosen dan ID OpenAlex, lalu jalankan sinkronisasi.
Halaman publik tersedia di `/`, `/dosen`, `/topik`, dan `/bandingkan`.

## 3. HTTPS di depan container

Jangan buka port aplikasi langsung ke internet. Pasang reverse proxy seperti Nginx atau Caddy
di depan `127.0.0.1:8000`, lalu:

- Teruskan header `Host` dan `X-Forwarded-Proto`.
- Aktifkan HTTPS dengan sertifikat yang valid.
- Set `COOKIE_SECURE=true` setelah HTTPS aktif.
- Batasi akses panel `/admin` bila memungkinkan.

Contoh lokasi Nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

## 4. Backup harian

Backup memakai `VACUUM INTO`, sehingga aman dijalankan saat aplikasi hidup. File disimpan di:

- `/backups/harian/app-YYYY-MM-DD.db`
- `/backups/bulanan/app-YYYY-MM.db`

Default retensi: 7 backup harian dan 1 backup bulanan. Ubah lewat
`BACKUP_DAILY_KEEP` dan `BACKUP_MONTHLY_KEEP`.

Jalankan manual:

```bash
docker compose exec -T app python -m app.cli backup
```

Jadwalkan lewat cron host setiap hari, misalnya pukul 02.00:

```cron
0 2 * * * cd /opt/rekomendasi && docker compose exec -T app python -m app.cli backup >> /var/log/rekomendasi-backup.log 2>&1
```

Folder `./data` dan `./backups` harus bisa ditulis oleh user container (UID `10001`). Jika
volume host dibuat manual, atur kepemilikannya sebelum start.

## 5. Restore

Hentikan aplikasi, ganti database dengan file backup, lalu start lagi:

```bash
docker compose stop app
cp backups/harian/app-2026-10-23.db data/app.db
docker compose start app
curl http://127.0.0.1:8000/health
```

Jangan menyalin file database saat aplikasi masih menulis. `VACUUM INTO` menghasilkan file
berisi data yang sudah ter-commit, jadi tidak perlu menyalin `-wal` atau `-shm` secara manual.

## 6. Pemeriksaan setelah deploy

- `/health` mengembalikan `{"status":"ok","phase":5}`.
- Halaman publik bisa dibuka di ponsel dan desktop.
- Pencarian dengan topik, kata kunci, lab, dan tahun menampilkan peringkat serta bukti.
- Dosen tanpa bukti muncul di grup "belum ada data".
- `/admin` meminta login dan berfungsi setelah `ADMIN_PASSWORD_HASH` diisi.
- Backup baru muncul di `backups/harian`.
