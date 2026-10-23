# PRD & Rencana Pengembangan: Sistem Rekomendasi Dosen Pembimbing Skripsi

Dokumen untuk Claude Code · Versi 1.0 · Oktober 2026

## 1. Ringkasan

Website internal untuk membantu mahasiswa memilih dosen pembimbing skripsi berdasarkan bidang yang benar-benar dikuasai dosen. Sistem mengambil daftar publikasi dosen dari profil Google Scholar, mengelompokkannya ke topik (bisa multi-topik) pada dua fokus lab (Solusi dan MSI), lalu merekomendasikan dosen berdasarkan bukti: paper yang ditulis dan riwayat skripsi yang pernah dibimbing. Data skripsi kakak tingkat bisa diunggah sebagai data tambahan, dengan pengecekan duplikat otomatis agar data lama tidak rusak.

Prinsip utama: **efisien** (scraping inkremental, klasifikasi bertahap, hasil di-cache) namun **tetap akurat** (berbasis ID Scholar, skor kepercayaan, review manual, override admin).

## 2. Tujuan dan Non-Tujuan

**Tujuan**

- Mahasiswa dapat mencari dosen berdasarkan satu atau beberapa topik, sub-topik, atau teks bebas (kata kunci/draf judul).
- Setiap dosen memiliki profil topik: distribusi topik, daftar paper per topik, dan skripsi yang pernah dibimbing.
- Admin dapat menambah dosen (cukup URL/ID Scholar), menjalankan scraping, meninjau klasifikasi, dan mengunggah data skripsi lama.
- Upload skripsi tidak pernah menimpa atau menduplikasi data yang sudah ada.

**Non-tujuan (versi 1)**

- Bukan sistem pengajuan/penjadwalan bimbingan, dan tidak mengelola kuota dosen secara resmi.
- Tidak memakai login mahasiswa (halaman publik bersifat read-only; hanya admin yang login).
- Tidak mengambil data dari sumber selain Google Scholar dan file unggahan (SINTA/Scopus hanya opsi masa depan).

## 3. Pengguna

| Peran | Kebutuhan utama |
| --- | --- |
| Mahasiswa (publik) | Cari dosen sesuai topik skripsi, lihat bukti keahlian, bandingkan beberapa dosen |
| Admin (satu atau beberapa orang) | Kelola dosen, jalankan scraping, tinjau klasifikasi, unggah skripsi lama, edit taksonomi |

## 4. Taksonomi Topik (data awal / seed)

Taksonomi harus **disimpan di database dan bisa diedit admin** (topik, sub-topik, kata kunci), bukan di-hardcode. Kata kunci di bawah adalah seed awal dalam bahasa Indonesia dan Inggris.

### Fokus Lab SOLUSI

| Topik | Sub-topik | Kata kunci contoh |
| --- | --- | --- |
| Rancang Bangun Aplikasi | - | rancang bangun, aplikasi web, aplikasi mobile, sistem informasi, pengembangan aplikasi, prototype, waterfall, Laravel, Flutter |
| Data Mining | Analisis Sentimen; Forecasting; Umum | data mining, klasifikasi, clustering, naive bayes, k-means, random forest, association rule; sentimen: analisis sentimen, sentiment analysis, opinion mining, ulasan, twitter; forecasting: peramalan, forecasting, prediksi, time series, ARIMA, LSTM |
| UI/UX | - | user interface, user experience, usability, SUS, design thinking, Figma, heuristic evaluation |
| Testing | - | software testing, pengujian perangkat lunak, black box, white box, UAT, test case, automation testing, Selenium |
| Manajemen Proyek | - | manajemen proyek, project management, PMBOK, scrum, agile, manajemen risiko, estimasi usaha |
| SPK (Sistem Pendukung Keputusan) | - | sistem pendukung keputusan, decision support, AHP, TOPSIS, SAW, PROMETHEE, VIKOR, MOORA |
| Pemodelan & Simulasi | - | simulasi, system dynamics, agent-based, discrete event, Monte Carlo, pemodelan, Arena, AnyLogic, Vensim |
| Jaringan | - | jaringan komputer, computer network, QoS, routing, SDN, wireless, VLAN, Mikrotik, keamanan jaringan |
| IoT | - | internet of things, IoT, sensor, Arduino, ESP32, Raspberry Pi, smart home, MQTT |
| Customisasi ERP | - | ERP, Odoo, SAP, customisasi, modul ERP, implementasi ERP |
| Manajemen Proses Bisnis | - | proses bisnis, BPMN, business process, process mining, BPR, SOP, workflow |
| Business Intelligence Application | - | business intelligence, dashboard, data warehouse, ETL, OLAP, Power BI, Tableau |
| AI | - | kecerdasan buatan, artificial intelligence, deep learning, neural network, CNN, NLP, computer vision, chatbot, LLM |

Catatan: sub-topik selain Data Mining sengaja kosong dulu; admin dapat menambah lewat editor taksonomi. Paper Data Mining yang tidak cocok dengan kedua sub-topik masuk ke sub-topik 'Umum'. Batas Data Mining vs AI: data mining untuk metode klasik/tabular, AI untuk deep learning, NLP, computer vision, LLM. Paper boleh masuk keduanya (multi-label).

### Fokus Lab MSI

| Topik | Kata kunci contoh |
| --- | --- |
| Perencanaan dan Strategi TI | perencanaan strategis sistem informasi, ISSP, enterprise architecture, TOGAF, Zachman, roadmap TI, blueprint |
| Audit dan Tata Kelola TI | audit sistem informasi, COBIT, tata kelola TI, IT governance, ISO 27001, risk assessment, capability/maturity level |
| Pengembangan dan Evaluasi Sistem | evaluasi sistem informasi, SDLC, DeLone McLean, kesuksesan sistem, kepuasan pengguna, HOT-Fit, EUCS |
| Manajemen Proyek TI | manajemen proyek TI, IT project, PMBOK, scrum, risiko proyek |
| UI/UX dan Pengalaman Pengguna | usability, user experience, SUS, design thinking, pengalaman pengguna |
| Operasional TI & Infrastruktur | ITIL, ITSM, service desk, infrastruktur TI, data center, cloud, SLA |
| Manajemen Data dan Informasi | manajemen data, data governance, DAMA, kualitas data, master data, keamanan informasi, knowledge management |
| Adopsi Teknologi dan Inovasi | TAM, UTAUT, technology acceptance, adopsi teknologi, niat penggunaan, diffusion of innovation, TOE, transformasi digital |
| Analisis Sistem dan Pemodelan Dinamik | system dynamics, pemodelan dinamik, causal loop, stock and flow, UML, analisis sistem, simulasi dinamik |

### Topik bersama antar lab

UI/UX dan Manajemen Proyek ada di kedua lab. Implementasi: setiap topik punya kolom `lab` dan `shared_key`. Topik dengan `shared_key` sama (mis. `uiux`, `projman`) diperlakukan sebagai satu topik saat klasifikasi (satu set kata kunci), tetapi tampil di kedua lab pada filter. Jangan membuat dua klasifikasi terpisah untuk paper yang sama.

## 5. Kebutuhan Fungsional

**F1. Manajemen dosen (admin)**

- Tambah dosen dengan: nama, gelar, URL atau ID Google Scholar (ID di-parse dari parameter `user=`), lab utama (opsional), status aktif.
- Identitas dosen = ID Scholar, **bukan nama**, untuk menghindari salah orang.
- Alias nama dosen (variasi penulisan, dengan/tanpa gelar) disimpan untuk pencocokan data skripsi.

**F2. Scraping Google Scholar**

- Ambil daftar publikasi: ID paper Scholar, judul, penulis, venue, tahun, jumlah sitasi.
- **Inkremental**: refresh hanya menambah paper baru dan memperbarui sitasi; tidak mengambil ulang yang sudah ada.
- Abstrak **tidak** diambil massal (mahal). Hanya diambil sesuai permintaan untuk paper yang klasifikasinya ambigu.
- Tombol scrape per dosen dan scrape semua; log hasil (berhasil, gagal, jumlah paper baru, waktu).
- Penanganan pembatasan: jeda acak antar request, backoff eksponensial, berhenti rapi jika terkena CAPTCHA, lanjut dari titik terakhir.
- Penyedia data dapat diganti lewat env `SCHOLAR_PROVIDER` = `scholarly` (default, gratis) | `serpapi` (API berbayar, lebih stabil) | `manual` (impor CSV/BibTeX hasil ekspor profil jika scraping diblokir).

**F3. Klasifikasi topik multi-label**

- Satu paper bisa punya banyak topik, masing-masing dengan skor kepercayaan 0 sampai 1 dan sub-topik jika ada.
- Pipeline bertahap (lihat bagian 6.2).
- Override manual admin tersimpan permanen dan tidak pernah ditimpa oleh klasifikasi ulang.
- Antrean review: paper berkepercayaan rendah atau tanpa topik ditampilkan agar admin cukup mengoreksi yang bermasalah.

**F4. Data skripsi lama (upload)**

- Unggah CSV/XLSX dengan kolom: judul (wajib), pembimbing 1 (wajib), pembimbing 2, nama mahasiswa, NIM, tahun, lab/topik (opsional). Pemetaan kolom ditampilkan agar admin bisa menyesuaikan nama kolom.
- Alur **pratinjau dulu, baru simpan**: sistem menampilkan jumlah baris Baru, Duplikat (dilewati), Perlu Review, dan Pembimbing Tidak Dikenali. Tidak ada yang tersimpan sebelum admin menekan Konfirmasi.
- Setiap unggahan punya `import_batch_id` sehingga bisa di-**rollback** seluruhnya.
- Aturan deteksi duplikat di bagian 6.3.

**F5. Pencarian dan rekomendasi (publik)**

- Filter: lab, topik (multi-pilih), sub-topik, rentang tahun paper.
- Kotak teks bebas: ketik minat atau draf judul; teks diklasifikasi dengan classifier yang sama lalu dicocokkan ke dosen.
- Hasil berupa daftar dosen terurut skor, disertai **bukti**: paper relevan dan skripsi serupa yang pernah dibimbing.
- Bandingkan hingga 3 dosen berdampingan.

**F6. Profil dosen**

- Diagram distribusi topik (dibagi per lab), daftar paper (filter per topik/tahun), daftar skripsi yang dibimbing, link ke profil Scholar, tanggal data terakhir diperbarui.

**F7. Editor taksonomi (admin)**

- Tambah/ubah/nonaktifkan topik, sub-topik, kata kunci. Setelah perubahan, tawarkan klasifikasi ulang hanya untuk paper yang terdampak (kecuali yang sudah di-override manual).

## 6. Pipeline Data

### 6.1 Scraping (efisien)

1. Ambil profil dosen, bandingkan daftar ID paper dengan database.
2. Hanya paper baru yang diproses lebih lanjut.
3. Simpan `last_scraped_at` per dosen; jangan scrape ulang jika baru diperbarui (mis. kurang dari 7 hari) kecuali dipaksa admin.
4. Jumlah dosen satu prodi relatif kecil, sehingga total request ringan jika inkremental dan ada jeda.

### 6.2 Klasifikasi bertahap (hemat biaya, tetap akurat)

- **Tahap 1, aturan kata kunci (gratis, deterministik).** Normalisasi teks (huruf kecil, hapus tanda baca, stemming ringan bahasa Indonesia opsional). Cocokkan kata kunci pada judul dan venue. Skor per topik = jumlah bobot kata kunci yang cocok, dinormalisasi menjadi kepercayaan. Ambil semua topik di atas ambang (default 0,4). Sub-topik ditentukan dengan cara yang sama di dalam topiknya.
- **Tahap 2, pengayaan.** Untuk paper tanpa topik atau ambigu (kepercayaan rendah atau dua topik teratas sangat dekat): ambil abstrak, ulangi aturan.
- **Tahap 3, LLM (opsional, dikendalikan flag `USE_LLM=true`).** Untuk yang masih ambigu, kirim dalam **batch** (sekitar 20 paper per permintaan) ke Claude API dengan model murah (nilai model di env, default `claude-haiku-5-5`). Prompt berisi taksonomi dan meminta keluaran JSON saja: topik, sub-topik, kepercayaan. Hasil di-cache berdasarkan hash (judul + abstrak) sehingga tidak pernah diklasifikasi dua kali.
- **Tahap 4, review manual** untuk sisa yang berkepercayaan rendah. Override admin = sumber kebenaran tertinggi.
- Setiap label menyimpan `source` (rule / llm / manual) agar dapat diaudit.

### 6.3 Deteksi duplikat (data skripsi dan paper)

**Normalisasi judul**: huruf kecil, hapus tanda baca dan spasi ganda, hapus stopword umum, normalisasi Unicode. Dari hasilnya buat `title_hash`.

**Skripsi** dianggap:

1. **Duplikat pasti** jika `title_hash` sama, atau NIM sama (bila ada). Dilewati otomatis.
2. **Duplikat mirip** jika kemiripan fuzzy judul (token-set ratio, mis. pustaka `rapidfuzz`) di atas 90 persen **dan** pembimbing atau tahun sama. Dilewati dan dilaporkan.
3. **Perlu review** jika kemiripan 80 sampai 90 persen. Admin memilih Lewati atau Tetap Tambahkan.
4. Selain itu dianggap data baru.

Aturan keras: **tidak pernah menimpa atau mengubah data yang sudah ada** lewat jalur upload. Duplikat di dalam file yang sama juga dideteksi. Semua keputusan dicatat di log impor.

**Pencocokan nama pembimbing**: normalisasi (hapus gelar seperti Dr., Ir., S.Kom., M.T., M.Kom.), cocokkan ke nama/alias dosen; jika kecocokan fuzzy lemah, tandai 'tidak dikenali' dan minta admin memetakan sekali, lalu simpan sebagai alias baru.

**Paper**: kunci unik = (dosen, ID paper Scholar). Paper yang ditulis bersama beberapa dosen prodi hanya disimpan **satu kali** (kecocokan `title_hash` + tahun) dan dihubungkan ke banyak dosen.

## 7. Model Data (ringkas)

| Tabel | Kolom penting |
| --- | --- |
| lecturers | id, name, title, scholar\_id (unik), main\_lab, active, last\_scraped\_at |
| lecturer\_aliases | lecturer\_id, alias\_normalized |
| papers | id, title, title\_hash, year, venue, abstract (nullable), citations, scholar\_pub\_id |
| lecturer\_papers | lecturer\_id, paper\_id (unik gabungan) |
| topics | id, lab (SOLUSI/MSI), name, parent\_id (sub-topik), shared\_key, active |
| topic\_keywords | topic\_id, keyword, weight, lang |
| paper\_topics | paper\_id, topic\_id, confidence, source (rule/llm/manual), locked (bool) |
| theses | id, title, title\_hash, student\_name, nim, year, import\_batch\_id |
| thesis\_supervisors | thesis\_id, lecturer\_id, role (1/2) |
| thesis\_topics | thesis\_id, topic\_id, confidence, source |
| import\_batches | id, filename, created\_at, summary\_json, status (preview/committed/rolled\_back) |
| scrape\_logs | id, lecturer\_id, started\_at, status, new\_papers, error |
| llm\_cache | content\_hash, result\_json |
| lecturer\_topic\_scores | lecturer\_id, topic\_id, score (hasil prakomputasi) |

Indeks wajib: `lecturers.scholar_id`, `papers.title_hash`, `theses.title_hash`, `paper_topics(topic_id)`.

## 8. Algoritma Rekomendasi

Skor dosen d untuk topik t:

`score(d,t) = sum_paper( recency * confidence(paper,t) ) + LAMBDA * sum_skripsi( confidence(skripsi,t) )`

- `recency = 0.5 ^ (umur_paper_tahun / 5)` (paper terbaru lebih berbobot; setengah-hidup 5 tahun, dapat dikonfigurasi).
- `LAMBDA` default 1,5: skripsi yang pernah dibimbing dianggap bukti kuat. Dapat dikonfigurasi.
- Beberapa topik dipilih: jumlahkan skor, beri bonus untuk dosen yang mencakup **semua** topik terpilih.
- Teks bebas: klasifikasi teks menjadi topik berbobot, lalu hitung seperti di atas.
- Skor dinormalisasi ke 0 sampai 100 untuk tampilan. Hasil prakomputasi di `lecturer_topic_scores` dan dihitung ulang hanya untuk dosen yang datanya berubah.
- Setiap hasil wajib menampilkan bukti (maks. 5 paper dan 3 skripsi teratas) agar mahasiswa bisa memverifikasi sendiri.

## 9. Halaman

| Halaman | Isi |
| --- | --- |
| Beranda / Cari | Filter lab-topik-sub-topik, kotak teks bebas, hasil rekomendasi bersama bukti |
| Daftar Dosen | Kartu dosen dengan topik teratas, filter lab |
| Detail Dosen | Distribusi topik, paper, skripsi dibimbing |
| Jelajah Topik | Pohon topik per lab dan dosen teratas di tiap topik |
| Admin: Dosen | CRUD dosen, tombol scrape, log |
| Admin: Review Klasifikasi | Antrean paper berkepercayaan rendah, koreksi cepat |
| Admin: Upload Skripsi | Unggah, pemetaan kolom, pratinjau duplikat, konfirmasi, rollback |
| Admin: Taksonomi | Editor topik, sub-topik, kata kunci |

## 10. Arsitektur dan Tech Stack (rekomendasi)

Satu bahasa agar sederhana dan mudah dirawat mahasiswa: **Python monolit**.

- Backend/web: FastAPI + Jinja2 + HTMX + Tailwind CSS (halaman ringan, tanpa build frontend rumit).
- Database: SQLite untuk awal (satu file, mudah dicadangkan), skema kompatibel PostgreSQL lewat SQLModel/SQLAlchemy + Alembic untuk migrasi.
- Scraping: pustaka `scholarly` (default), adaptor SerpApi opsional, semuanya di balik satu antarmuka `ScholarProvider`.
- Impor dan dedup: pandas/openpyxl + `rapidfuzz`.
- Tugas latar (scraping, klasifikasi): worker sederhana dengan antrean di database (tanpa Redis) atau `BackgroundTasks`.
- Autentikasi admin: satu akun dari env (hash kata sandi) dengan sesi cookie.
- Deploy: satu container Docker (Railway, Render, atau VPS kampus). Cadangan harian file database.
- Jika lebih nyaman memakai Next.js + Postgres, Claude Code boleh menyesuaikan selama semua kebutuhan di dokumen ini terpenuhi.

## 11. Kebutuhan Non-Fungsional

**Efisiensi**

- Scraping inkremental, tanpa pengambilan ulang; abstrak hanya sesuai kebutuhan.
- Klasifikasi hanya untuk paper baru atau yang terdampak perubahan taksonomi.
- Skor prakomputasi; halaman publik dimuat kurang dari 1 detik pada data satu prodi.
- Panggilan LLM di-batch dan di-cache; biaya per paper mendekati nol karena mayoritas selesai di Tahap 1.

**Akurasi**

- Identitas dosen lewat ID Scholar. Setiap label menyimpan kepercayaan dan sumbernya.
- Siapkan **golden set** minimal 50 paper berlabel manual oleh admin; target F1 klasifikasi di atas 0,80 sebelum dipakai publik. Skrip evaluasi dijalankan setiap taksonomi diubah.
- Override manual tidak pernah tertimpa. Semua impor dapat di-rollback.
- Tampilkan 'data terakhir diperbarui' dan peringatan bahwa Scholar bisa tidak lengkap.

**Keamanan dan etika**

- Hanya data publik yang diambil; tidak ada data pribadi mahasiswa di halaman publik (nama mahasiswa dan NIM disembunyikan, tampilkan hanya judul, tahun, pembimbing).
- Rute admin dilindungi; validasi tipe dan ukuran file unggahan.
- Catatan penting: ketentuan layanan Google Scholar melarang scraping otomatis. Mitigasi: pakai sangat sedikit request, jeda panjang, cache, penggunaan internal; sediakan jalur `serpapi` dan `manual` sebagai alternatif yang lebih aman.

## 12. Risiko dan Mitigasi

| Risiko | Mitigasi |
| --- | --- |
| Diblokir/CAPTCHA oleh Scholar | Jeda acak, backoff, berhenti dan lanjut nanti; adaptor SerpApi; impor manual |
| Profil Scholar dosen tidak lengkap | Tampilkan jumlah paper; skripsi dibimbing menjadi bukti kedua |
| Judul paper berbahasa Indonesia/Inggris bercampur | Kata kunci dwibahasa; LLM tahap 3 |
| Salah klasifikasi | Kepercayaan, antrean review, override manual, golden set |
| Duplikat merusak data lama | Pratinjau wajib, aturan duplikat berlapis, rollback per batch |
| Nama pembimbing beda penulisan | Normalisasi gelar, alias, pemetaan manual sekali jalan |

## 13. Rencana Pengembangan (kerjakan berurutan, berhenti dan tes di akhir tiap fase)

**Fase 0: Fondasi**

- Inisialisasi repo, struktur proyek, `CLAUDE.md` (ringkasan aturan dan perintah), `.env.example`, lint, pytest.
- Selesai jika: aplikasi kosong berjalan, tes dasar lolos.

**Fase 1: Database, taksonomi, admin dasar**

- Skema + migrasi, seed taksonomi bagian 4, login admin, CRUD dosen (parse ID Scholar dari URL).
- Selesai jika: dosen bisa ditambah/diubah; seed 2 lab, topik, dan sub-topik Data Mining terisi.

**Fase 2: Scraper inkremental**

- Antarmuka `ScholarProvider` + implementasi `scholarly`, jeda/backoff, log scrape, tombol scrape.
- Selesai jika: scrape dua kali berturut-turut kedua kalinya menambah 0 paper dan tidak mengulang request paper lama.

**Fase 3: Klasifikasi tahap 1 dan review**

- Normalisasi teks, pencocokan kata kunci, multi-label + kepercayaan, sub-topik, antrean review, override manual, skrip evaluasi golden set.
- Selesai jika: tes unit lolos, override tidak tertimpa saat klasifikasi ulang.

**Fase 4: Upload skripsi dan deduplikasi**

- Parser CSV/XLSX, pemetaan kolom, normalisasi judul, pencocokan pembimbing, aturan duplikat tiga level, pratinjau, konfirmasi, rollback.
- Selesai jika: mengunggah file yang sama dua kali menghasilkan 0 baris baru; tes mencakup duplikat pasti, mirip, dan dalam-file.

**Fase 5: Halaman publik**

- Cari/filter, daftar dosen, detail dosen, jelajah topik, bandingkan dosen.
- Selesai jika: semua halaman bekerja di ponsel dan desktop.

**Fase 6: Mesin rekomendasi**

- Skor dengan recency dan bobot skripsi, multi-topik, teks bebas, tampilan bukti, prakomputasi skor.
- Selesai jika: kueri tipikal menampilkan dosen dan bukti yang masuk akal menurut admin.

**Fase 7: LLM opsional, poles, deploy**

- Tahap 3 klasifikasi (batch + cache, bisa dimatikan), editor taksonomi dengan klasifikasi ulang terarah, Docker, cadangan, dokumentasi README.
- Selesai jika: aplikasi berjalan di server, cadangan harian aktif, README menjelaskan penambahan dosen dan unggah skripsi.

## 14. Kriteria Penerimaan Akhir

- Menambah dosen cukup dengan URL Scholar, lalu paper terkumpul dan terklasifikasi tanpa input tambahan.
- Refresh data tidak mengulang pekerjaan yang sudah selesai.
- Setiap paper dapat berstatus multi-topik; setiap topik ada pada lab yang benar (Solusi/MSI), UI/UX dan Manajemen Proyek tampil di keduanya.
- Upload skripsi tidak pernah menghasilkan duplikat maupun mengubah data lama; ada pratinjau dan rollback.
- Hasil rekomendasi selalu disertai bukti yang bisa diverifikasi.
- F1 pada golden set di atas 0,80.

## 15. Prompt Pembuka untuk Claude Code

Salin prompt berikut ke Claude Code setelah menyimpan dokumen ini sebagai `PRD.md` di folder proyek:

> Baca PRD.md sampai habis. Buat CLAUDE.md berisi ringkasan aturan penting dan perintah proyek. Kerjakan rencana pada bagian 13 per fase, mulai Fase 0. Di akhir setiap fase: jalankan tes, tampilkan ringkasan apa yang selesai dan cara mengujinya, lalu berhenti dan tunggu konfirmasi sebelum lanjut. Jangan menambah fitur di luar PRD. Utamakan efisiensi (inkremental, cache) tanpa mengorbankan akurasi. Jika ada keputusan yang ambigu, tanyakan satu pertanyaan singkat.

## 16. Yang Perlu Disiapkan Pengguna

- Daftar dosen prodi beserta URL profil Google Scholar masing-masing.
- File data skripsi lama (CSV/XLSX) dengan minimal kolom judul dan pembimbing; makin lengkap (tahun, NIM) makin akurat deteksi duplikatnya.
- Sekitar 50 paper yang sudah Anda beri label topik secara manual (atau minta dosen/teman bantu) sebagai golden set.
- Opsional: API key Anthropic (untuk klasifikasi tahap 3) dan/atau SerpApi (jika scraping gratis sering terblokir).
