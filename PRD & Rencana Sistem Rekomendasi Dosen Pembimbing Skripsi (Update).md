# PRD & Rencana Pengembangan: Sistem Rekomendasi Dosen Pembimbing Skripsi

Dokumen untuk OpenCode · Versi 1.1 · Oktober 2026

Perubahan dari v1.0: sumber data lewat API resmi, jendela publikasi 3 tahun, deduplikasi berbasis judul saja, skor tanpa angka 0 sampai 100, skripsi ikut diklasifikasi, editor taksonomi pindah ke Fase 1, dan rencana kerja dipadatkan menjadi 7 fase (0 sampai 6) dengan target data siap di hari kerja ke-3.

## 1. Ringkasan

Website internal untuk membantu mahasiswa memilih dosen pembimbing skripsi berdasarkan bidang yang benar-benar dikuasai dosen. Sistem mengumpulkan publikasi dosen **3 tahun terakhir** dari OpenAlex API dan ekspor profil Google Scholar, mengelompokkannya ke topik (bisa multi-topik) pada dua fokus lab (Solusi dan MSI), lalu merekomendasikan dosen berdasarkan bukti: paper yang ditulis dan skripsi yang pernah dibimbing. Data skripsi kakak tingkat bisa diunggah sebagai data tambahan, dengan pengecekan duplikat otomatis agar data lama tidak rusak.

Dua prinsip yang mengikat seluruh keputusan teknis:

- **Sempit tapi yakin.** Hanya publikasi 3 tahun terakhir (`PUBLICATION_WINDOW_YEARS=3`). Volume kecil, klasifikasi cepat, dan seluruh data terkumpul dalam hitungan menit, bukan hari.
- **Terlihat, bukan dinilai.** Hasil rekomendasi menampilkan peringkat dan bukti yang bisa diverifikasi mahasiswa. Tidak ada angka 0 sampai 100 yang menyiratkan presisi yang tidak dimiliki model.

## 2. Tujuan dan Non-Tujuan

**Tujuan**

- Mahasiswa dapat mencari dosen berdasarkan satu atau beberapa topik, sub-topik, atau teks bebas (kata kunci/draf judul).
- Setiap dosen memiliki profil topik: distribusi topik, daftar paper per topik, dan skripsi yang pernah dibimbing.
- Admin dapat menambah dosen (cukup URL atau ID Scholar), menyinkronkan publikasi, meninjau klasifikasi, dan mengunggah data skripsi lama.
- Upload skripsi tidak pernah menimpa atau menduplikasi data yang sudah ada.
- Seluruh data satu prodi terkumpul, terklasifikasi, dan bisa dilihat admin di hari kerja ke-3.

**Non-tujuan (versi 1)**

- Bukan sistem pengajuan/penjadwalan bimbingan, dan tidak mengelola kuota dosen secara resmi.
- Tidak memakai login mahasiswa (halaman publik read-only; hanya admin yang login).
- Tidak mengambil data selain dari OpenAlex API, ekspor Google Scholar, dan file unggahan (SINTA/Scopus hanya opsi masa depan).
- Tidak menilai kinerja dosen. Sistem ini hanya menampilkan bukti publikasi dan bimbingan.

## 3. Pengguna

| Peran | Kebutuhan utama |
| --- | --- |
| Mahasiswa (publik) | Cari dosen sesuai topik skripsi, lihat bukti keahlian, bandingkan beberapa dosen |
| Admin (akun bersama, satu kredensial) | Kelola dosen, sinkronkan publikasi, tinjau klasifikasi, unggah skripsi lama, edit taksonomi |

Catatan: satu akun admin dari env, dipakai bersama oleh satu sampai tiga orang. Tidak ada tabel admin dan tidak ada manajemen peran. Ini keputusan sadar untuk v1.

## 4. Taksonomi Topik (data awal / seed)

Taksonomi disimpan di database dan bisa diedit admin lewat editor di Fase 1, bukan di-hardcode. Seed awal ada di `seeds/taxonomy.yaml` dan diimpor lewat perintah CLI, sehingga repo tetap punya satu sumber kebenaran yang bisa di-review.

Aturan model:

- Satu topik = satu baris di `topics`. Lab tidak disimpan di baris topik, tapi di tabel `topic_labs` (satu topik boleh milik dua lab).
- Topik bersama antar lab (UI/UX dan Manajemen Proyek) adalah **satu baris topik** dengan dua baris `topic_labs`. Kata kuncinya ada di satu tempat dan tidak mungkin melenceng antar lab.
- Sub-topik adalah baris `topics` dengan `parent_id` terisi. Kedalaman maksimal satu tingkat. `paper_topics` hanya menyimpan topik induk, sub-topik disimpan di kolom `subtopic_id`.
- Setiap perubahan topik atau kata kunci menaikkan `taxonomy_version` di tabel `meta`.

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

Catatan: sub-topik selain Data Mining sengaja kosong dulu. Paper Data Mining yang tidak cocok dengan kedua sub-topik masuk ke sub-topik 'Umum'. Batas Data Mining vs AI: data mining untuk metode klasik/tabular, AI untuk deep learning, NLP, computer vision, LLM. Paper boleh masuk keduanya (multi-label).

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

| Topik (satu baris) | Lab | Kata kunci |
| --- | --- | --- |
| UI/UX | SOLUSI, MSI | gabungan kedua daftar di atas, tanpa duplikat |
| Manajemen Proyek | SOLUSI, MSI | manajemen proyek, project management, PMBOK, scrum, agile, manajemen risiko, IT project, risiko proyek, estimasi usaha |

Label "UI/UX dan Pengalaman Pengguna" di MSI dan "Manajemen Proyek TI" di MSI adalah nama tampil, bukan topik terpisah. Di UI, topik yang sama ditampilkan dengan nama yang sama di kedua lab.

## 5. Kebutuhan Fungsional

### F1. Manajemen dosen (admin)

- Tambah dosen dengan: nama, gelar, URL profil Google Scholar (ID di-parse dari parameter `user=`), status aktif.
- Identitas dosen = ID OpenAlex yang dikonfirmasi admin, dengan ID Scholar sebagai identitas sekunder. Bukan nama.
- `scholar_id` boleh kosong dan unik bila ada. Satu dosen boleh punya lebih dari satu ID OpenAlex (identitas terpecah), disimpan di tabel `lecturer_openalex_ids`.
- Alias nama dosen (variasi penulisan, dengan/tanpa gelar) disimpan untuk pencocokan data skripsi dan dibuat otomatis saat admin memetakan nama pembimbing yang tidak dikenali.
- Lab **tidak** disimpan sebagai kolom. Lab dosen diturunkan dari topik tempat ia punya bukti. Dengan begitu filter lab dan filter topik tidak mungkin bertentangan.

### F2. Pengumpulan publikasi (tanpa scraping HTML)

Tiga sumber, di balik satu antarmuka `PublicationProvider`.

**Sumber 1, OpenAlex API (utama).**

- Jendela 3 tahun: `filter=from_publication_date:<hari ini minus 3 tahun>` dan `filter=authorships.author.id:<ID>`, digabung dengan `+`.
- `per_page=100` (batas yang didokumentasikan API). Pengujian Fase 0 menemukan 200 juga diterima, tetapi kode tetap memakai 100 agar sesuai dokumentasi. Loop halaman sampai habis.
- `select` hanya field yang dipakai: `id,doi,display_name,publication_year,primary_location,cited_by_count,abstract_inverted_index,authorships,primary_topic,topics`.
- API key dikirim lewat header `Authorization: Bearer`, **bukan** query string. Kode tidak perlu menyamarkan key di log karena key tidak pernah masuk URL.
- Tanpa API key tetap bisa (10 request/detik). Dengan key gratis: 30 request/detik dan budget harian lebih besar. Key wajib hanya untuk cursor paging.
- Backoff eksponensial saat 429, dan baca `meta.cost` serta header `X-RateLimit-*` untuk mencatat pemakaian di `sync_jobs.credits_used`.
- `abstract_inverted_index` bisa `null` untuk banyak karya. Klasifikasi tidak boleh bergantung pada abstrak selalu ada.

**Sumber 2, ekspor manual Google Scholar.**

- Admin mengunggah CSV atau BibTeX hasil ekspor profil per dosen. Parser toleran terhadap variasi nama kolom.
- Ekspor Scholar umumnya tidak memuat abstrak dan DOI. Karena itu ekspor ini diperlakukan sebagai pelengkap: paper yang tidak ada di OpenAlex tetap masuk, dan abstraknya dicari lewat pencocokan judul ke OpenAlex bila tersedia.
- Tidak ada request ke Google, jadi tidak ada CAPTCHA dan tidak melanggar ToS.

**Sumber 3, scraper Scholar langsung (kerangka, nonaktif).**

- Hanya jika `ENABLE_SCHOLAR_SCRAPER=true`, satu dosen per sesi, jeda panjang, berhenti saat CAPTCHA. Tidak pernah dijadwalkan. Di v1 hanya kerangka kelas, tanpa pemakaian produksi.

**Pemetaan ID OpenAlex.**

- Saat dosen ditambahkan, sistem mencari kandidat penulis (nama, `display_name_alternatives`, afiliasi terakhir, jumlah karya, 3 judul teratas) dan admin memilih yang benar satu kali.
- Kandidat ditampilkan dengan 5 judul teratas dan topik utama. Admin menolak kandidat yang karyanya tidak relevan, karena satu record penulis OpenAlex sering menggabungkan beberapa orang bernama sama.
- Jumlah karya kandidat dibandingkan dengan jumlah paper di ekspor Scholar sebagai pemeriksaan kewajaran.

**Inkremental dan tangguh.**

- Sinkronisasi hanya menambah paper baru dan memperbarui sitasi serta abstrak yang sebelumnya kosong.
- Dosen dengan `last_synced_at` kurang dari 7 hari dilewati kecuali admin memaksa.
- Dijalankan sebagai job di background dengan tabel `sync_jobs` yang resumable. Jika proses mati, job berstatus `running` lebih dari 30 menit dianggap gagal dan bisa diulang.
- Halaman publik tetap melayani data lama selama sinkronisasi berjalan.

### F3. Klasifikasi topik multi-label

- **Paper dan skripsi sama-sama diklasifikasi.** Ini yang membuat bobot skripsi di bagian 8 punya isi.
- Satu paper bisa punya banyak topik, masing-masing dengan `confidence` 0 sampai 1 dan `subtopic_id` bila ada.
- Pipeline bertahap di bagian 6.2. Hasil deterministik: input sama + `taxonomy_version` sama = output sama.
- Override manual (`locked=true`, `source='manual'`) tersimpan permanen dan tidak pernah ditimpa klasifikasi ulang.
- Antrean review menampilkan paper dan skripsi dengan `confidence` rendah atau tanpa topik. Layar ini dirancang untuk keyboard (bagian 9).

### F4. Data skripsi lama (upload)

- Unggah CSV/XLSX dengan kolom: judul (wajib), pembimbing 1 (wajib), pembimbing 2, nama mahasiswa, NIM, tahun, topik (opsional). Pemetaan kolom ditampilkan agar admin bisa menyesuaikan nama kolom.
- Alur **pratinjau dulu, baru simpan**: hasil parsing disimpan di `import_rows` dengan `batch_id`, lalu ditampilkan sebagai ringkasan Baru, Duplikat (dilewati), Perlu Review, Pembimbing Tidak Dikenali.
- Tidak ada yang masuk ke `theses` sebelum admin menekan Konfirmasi. Batch pratinjau kedaluwarsa setelah 24 jam.
- Setiap unggahan punya `import_batch_id` sehingga bisa di-rollback. Rollback menghapus skripsi batch itu **dan** alias dosen yang dibuat oleh batch itu.
- Aturan deteksi duplikat di bagian 6.3.

### F5. Pencarian dan rekomendasi (publik)

- Filter: lab, topik (multi-pilih), sub-topik, rentang tahun paper.
- Kotak teks bebas, dua jalur:
  1. **Pencocokan judul langsung** (utama): query dicocokkan ke judul paper dan venue lewat SQLite FTS5. Dosen muncul karena papernya mirip draf judul mahasiswa.
  2. **Klasifikasi topik** (pelengkap): query diklasifikasi dengan classifier yang sama; topik dengan `confidence` di atas ambang ikut menambah skor.
- Hasil berupa daftar dosen terurut, disertai peringkat, label kekuatan bukti, dan daftar bukti (maksimal 5 paper dan 3 skripsi).
- Dosen tanpa data tetap tampil di bagian bawah dengan label "belum ada data", bukan skor nol.
- Bandingkan hingga 3 dosen berdampingan (fitur tetap ada, dikerjakan di Fase 5).

### F6. Profil dosen

- Distribusi topik per lab, daftar paper (filter topik/tahun), daftar skripsi yang dibimbing, link profil Scholar dan OpenAlex, tanggal data terakhir disinkronkan, dan cakupan jendela data ("publikasi 3 tahun terakhir").

### F7. Editor taksonomi (admin, Fase 1)

- Tambah/ubah/nonaktifkan topik, atur lab (checkbox SOLUSI/MSI), tambah sub-topik, kelola kata kunci beserta bobot.
- Setiap simpan menaikkan `taxonomy_version` dan menawarkan klasifikasi ulang hanya untuk paper dan skripsi yang terdampak (kecuali `locked=true`).
- Klasifikasi ulang berjalan sebagai job, bukan di dalam request.

## 6. Pipeline Data

### 6.1 Pengumpulan data (target: seluruh prodi selesai di bawah 5 menit)

1. Admin menambahkan dosen, mengonfirmasi ID OpenAlex. Bila ada, ekspor Scholar diunggah sekali.
2. Sinkronisasi OpenAlex per dosen dengan jendela 3 tahun: biasanya 1 request untuk satu halaman 100 karya.
3. Setiap karya dinormalisasi lalu dicocokkan dengan database memakai aturan bagian 6.3. Hanya paper baru yang masuk antrean klasifikasi; paper lama hanya diperbarui sitasi dan abstraknya.
4. Skala: di bawah 50 dosen x 1 sampai 2 request = di bawah 100 request per sinkronisasi penuh. Pemakaian kredit dicatat di `sync_jobs.credits_used`. Pengukuran Fase 0 pada 10 dosen Prodi SI: 408 karya dalam 3 tahun, satu halaman per dosen, biaya 0,0001 USD per request.
5. Jadwal: mingguan otomatis lewat cron yang memanggil `python -m app.jobs sync`, atau tombol admin. Tidak ada scheduler di dalam aplikasi.
6. Kegagalan satu dosen tidak menggagalkan yang lain. Setiap job mencatat status, sumber, jumlah paper baru, galat, dan kredit terpakai.

Catatan penting soal jendela 3 tahun: paper di luar jendela tidak diambil, tetapi data lama yang sudah ada tidak dihapus. Jendela adalah filter pengambilan, bukan aturan hapus. Dosen yang penelitiannya berhenti 5 tahun lalu akan tampil sebagai "belum ada data 3 tahun terakhir", dan itu memang informasi yang benar.

### 6.2 Klasifikasi bertahap (paper dan skripsi)

**Normalisasi teks.** Huruf kecil, normalisasi Unicode, hapus tanda baca, rapikan spasi ganda. Tanpa stemming di v1 (Sastrawi menambah dependensi dan waktu tanpa manfaat terbukti pada judul pendek).

**Tahap 1, aturan kata kunci (gratis, deterministik).**

- Cocokkan frasa kata kunci pada judul, venue, dan abstrak bila ada. Frasa multi-kata dicocokkan sebagai substring setelah normalisasi.
- `matched` = jumlah kata kunci berbeda yang cocok untuk topik itu.
- `confidence = matched / (matched + 2)`. Ambang topik = 0,4, artinya minimal 2 kata kunci cocok.
- Ambil semua topik di atas ambang (multi-label), urutkan menurun.
- Sub-topik ditentukan dengan cara yang sama di dalam topik induk. Bila tidak ada yang melewati ambang, masuk ke sub-topik 'Umum' bila topik itu punya sub-topik tersebut.
- Skripsi memakai classifier yang sama dengan ambang lebih tinggi (0,5) karena hanya judul yang tersedia.

**Tahap 2, pengayaan abstrak.**

- Untuk paper tanpa topik atau ambigu (topik teratas di bawah 0,5, atau selisih dua teratas kurang dari 0,1): bila abstrak masih kosong, coba ambil abstrak dari OpenAlex lewat pencocokan judul atau DOI.
- Ulangi Tahap 1 dengan abstrak. Jangan mengulang klasifikasi yang sudah `locked=true`.

**Tahap 3, LLM (opsional, `USE_LLM=true`).**

- Hanya untuk sisa yang masih ambigu. Batch sekitar 20 paper per permintaan lewat `LLMProvider` yang bisa diganti (`LLM_PROVIDER`, `LLM_MODEL` di env, termasuk Ollama untuk model lokal).
- Prompt berisi taksonomi dan meminta JSON saja: topik, sub-topik, confidence.
- Cache key = `sha256(judul + abstrak + taxonomy_version)`. Tanpa `taxonomy_version`, hasil lama akan dipakai setelah taksonomi berubah dan label jadi salah permanen.
- Dengan jendela 3 tahun, volume paper kecil, sehingga Tahap 3 kemungkinan besar tidak dibutuhkan. Fitur tetap ada, tapi default mati.

**Tahap 4, review manual.**

- Semua yang masih di bawah ambang masuk antrean. Override admin adalah sumber kebenaran tertinggi.

Setiap label menyimpan `source` (`rule`/`llm`/`manual`), `confidence`, `locked`, dan `taxonomy_version`.

### 6.3 Deduplikasi (berbasis judul)

**Normalisasi judul.** Huruf kecil, normalisasi Unicode, hapus tanda baca dan spasi ganda, hapus stopword umum. Hasilnya `title_hash`.

**Urutan kunci kanonik untuk paper.**

1. DOI ternormalisasi (`doi_norm`), bila ada.
2. ID OpenAlex, bila ada.
3. ID publikasi Scholar, bila ada.
4. `(title_hash, year)`.

**Penggabungan antar-sumber: judul saja.** Sesuai keputusan produk, isi paper (abstrak) tidak pernah dibandingkan untuk menentukan duplikat. Aturannya:

- DOI atau ID OpenAlex sama: satu paper, otomatis.
- `title_hash` sama dan selisih tahun maksimal 1: satu paper, otomatis. Simpan semua ID sumbernya di kolom `sources` dan ambil data terkaya (abstrak dari OpenAlex, sitasi tertinggi, DOI bila ada).
- Kemiripan judul 90 sampai 100 persen (`rapidfuzz` token-set ratio) dan tahun sama: masuk antrean "kemungkinan duplikat", tidak digabung otomatis.
- Di bawah itu: paper baru.

**Skripsi.** Dievaluasi berurutan dari atas ke bawah, aturan pertama yang cocok yang menang.

| Urutan | Kondisi | Keputusan |
| --- | --- | --- |
| 1 | `(title_hash, year)` sama, atau NIM sama | Duplikat pasti, dilewati otomatis |
| 2 | `title_hash` sama tetapi tahun berbeda lebih dari 1 | **Perlu review**, bukan dilewati (dua angkatan bisa berjudul identik) |
| 3 | Kemiripan judul di atas 90 persen dan pembimbing atau tahun sama | Duplikat mirip, dilewati dan dilaporkan |
| 4 | Kemiripan judul 80 sampai 90 persen | Perlu review, admin pilih Lewati atau Tetap Tambahkan |
| 5 | Selain itu | Data baru |

Aturan keras: **tidak pernah menimpa atau mengubah data yang sudah ada** lewat jalur upload. Duplikat di dalam file yang sama juga dideteksi. Semua keputusan dicatat di `import_rows.decision` dan bisa di-rollback per batch.

**Pencocokan nama pembimbing.** Normalisasi gelar (Dr., Prof., Ir., S.Kom., M.T., M.Kom., dan sejenisnya), cocokkan ke nama atau alias dosen. Kemiripan lemah ditandai "tidak dikenali" dan diminta dipetakan sekali oleh admin. Alias baru dicatat dengan `created_by_batch_id` supaya ikut terhapus saat rollback.

**Blocking.** Pencocokan fuzzy hanya dilakukan dalam blok tahun yang sama atau tahun berselisih 1, dan untuk skripsi juga dalam blok pembimbing yang sama. Ini menjaga perbandingan tetap cepat dan hasilnya deterministik.

## 7. Model Data

| Tabel | Kolom penting |
| --- | --- |
| `lecturers` | id, name, title, scholar_id (unik, nullable), active, notes, last_synced_at, updated_at |
| `lecturer_openalex_ids` | id, lecturer_id, openalex_author_id, display_name, works_count, confirmed_at. Unik (lecturer_id, openalex_author_id) |
| `lecturer_aliases` | id, lecturer_id, alias_normalized, created_by_batch_id (nullable). Unik (lecturer_id, alias_normalized) |
| `papers` | id, title, title_hash, year, venue, doi, doi_norm, abstract (nullable), citations, scholar_pub_id, openalex_id, sources, created_at, updated_at. Unik `doi_norm`, unik `openalex_id` |
| `lecturer_papers` | lecturer_id, paper_id. Unik gabungan |
| `topics` | id, name, parent_id (nullable), active, sort_order |
| `topic_labs` | topic_id, lab. Unik gabungan |
| `topic_keywords` | id, topic_id, keyword, keyword_norm, weight, lang. Unik (topic_id, keyword_norm) |
| `paper_topics` | paper_id, topic_id, subtopic_id (nullable), confidence, source, locked, taxonomy_version. Unik (paper_id, topic_id) |
| `theses` | id, title, title_hash, student_name, nim, year, import_batch_id, created_at, updated_at |
| `thesis_supervisors` | thesis_id, lecturer_id, role (1/2). Unik gabungan |
| `thesis_topics` | thesis_id, topic_id, confidence, source, locked, taxonomy_version. Unik gabungan |
| `import_batches` | id, filename, file_hash, created_at, confirmed_at, summary_json, status (preview/committed/rolled_back) |
| `import_rows` | id, batch_id, row_number, raw_json, normalized_json, decision, thesis_id (nullable), note |
| `sync_jobs` | id, lecturer_id, source, status, attempts, started_at, finished_at, new_papers, credits_used, error |
| `llm_cache` | content_hash, taxonomy_version, result_json, created_at. Unik gabungan |
| `meta` | key, value (menyimpan `taxonomy_version` dan pengaturan) |
| `papers_fts` | FTS5 pada title, venue (tokenizer unicode61, remove_diacritics 2) |

Indeks: `papers(title_hash)`, `papers(year)`, `papers(doi_norm)`, `theses(title_hash)`, `theses(year)`, `paper_topics(topic_id)`, `thesis_topics(topic_id)`, `thesis_supervisors(lecturer_id)`, `lecturer_papers(paper_id)`, `sync_jobs(status)`.

Tidak ada tabel `lecturer_topic_scores`. Skor dihitung saat query. Jumlah barisnya kecil (di bawah 50 dosen x sekitar 20 topik), jadi prakomputasi tidak diperlukan; waktu aktualnya diukur di Fase 3.

## 8. Algoritma Rekomendasi

Skor per topik memakai bentuk *shrinkage*, bukan penjumlahan mentah dan bukan skala 0 sampai 100:

```
strength(d,t) = Σ_paper(recency_p × conf_p,t) + LAMBDA × Σ_skripsi(conf_s,t)
score(d,t)    = strength / (strength + 2)
recency_p     = 0.5 ^ (umur_paper_tahun / RECENCY_HALF_LIFE_YEARS)
```

- `RECENCY_HALF_LIFE_YEARS` default **2**, bukan 5. Dengan jendela data 3 tahun, half-life 5 tahun membuat seluruh paper berbobot hampir sama (0,66 sampai 1,0) sehingga faktor recency tidak berfungsi.
- `LAMBDA` default 1,5: skripsi yang pernah dibimbing dianggap bukti kuat. Skripsi tidak dibatasi jendela 3 tahun, karena riwayat bimbingan tetap relevan.
- `score` selalu 0 sampai 1 dan otomatis mengecilkan dosen dengan bukti tipis: 1 paper berbobot 0,4 menghasilkan 0,17; 8 paper berbobot total 3,2 menghasilkan 0,62.
- Beberapa topik dipilih: jumlahkan `score` per topik, lalu kalikan faktor cakupan:

```
coverage = jumlah topik terpilih yang punya strength ≥ 0,3 / jumlah topik terpilih
final    = Σ score(d,t) × (0,6 + 0,4 × coverage)
```

- Teks bebas: paper yang cocok dengan FTS5 dihitung sebagai bukti langsung (bobot 1 per paper, dikali recency), lalu ditambah skor topik hasil klasifikasi query bila ada. Dosen yang punya paper berjudul mirip draf mahasiswa naik, dan buktinya bisa langsung dibaca.
- Urutan hasil: `final` menurun, lalu jumlah bukti menurun, lalu nama. Dosen tanpa bukti sama sekali masuk grup "belum ada data" di bawah, bukan skor nol di tengah daftar.
- Tampilan hasil: peringkat, label kekuatan bukti (`Lemah` < 0,20, `Cukup` 0,20 sampai 0,45, `Kuat` > 0,45), dan bukti (maksimal 5 paper dan 3 skripsi teratas). **Tidak ada angka skor di UI.**
- Skor tidak diprakomputasi dan tidak disimpan. Dihitung per request; hasil satu query tidak pernah dibandingkan dengan query lain.

## 9. Halaman

| Halaman | Isi dan catatan |
| --- | --- |
| Beranda / Cari | Filter lab-topik-sub-topik, kotak teks bebas, hasil berperingkat dengan bukti. Tanpa hero dan tanpa kartu statistik |
| Daftar Dosen | Baris dosen dengan 2 sampai 3 topik teratas dan jumlah bukti, filter lab |
| Detail Dosen | Distribusi topik per lab, paper, skripsi dibimbing, status sinkronisasi, peringatan cakupan 3 tahun |
| Jelajah Topik | Daftar topik per lab dan dosen teratas di tiap topik. Tanpa visualisasi pohon |
| Admin: Dosen | CRUD dosen, pemetaan ID OpenAlex massal (antrean kandidat, konfirmasi satu layar), tombol Sinkronkan, riwayat `sync_jobs` |
| Admin: Review Klasifikasi | Antrean paper dan skripsi berkepercayaan rendah. Keyboard: `j`/`k` pindah, `1..9` pilih topik, `x` tandai tidak relevan, `Enter` simpan dan lanjut |
| Admin: Upload Skripsi | Unggah, pemetaan kolom, pratinjau per baris, konfirmasi, rollback, riwayat batch |
| Admin: Taksonomi | CRUD topik, sub-topik, lab, kata kunci dan bobot, tombol klasifikasi ulang |

Aturan tampilan yang mengikat semua halaman:

- Empat state wajib ada: belum ada data ("admin belum menyinkronkan"), nol hasil ("longgarkan filter"), data usang (sinkron terakhir lebih dari 90 hari), dan galat.
- Mobile: tanpa overflow horizontal, tabel paper berubah jadi daftar, target sentuh minimal 44px.
- Kontras teks minimal 4,5:1, fokus keyboard selalu terlihat, semua kontrol bisa dicapai dengan Tab.
- Tanpa angka statistik yang tidak punya sumber. Jumlah paper dan skripsi dihitung dari database, bukan dikarang.
- CTA spesifik ("Cari pembimbing", "Lihat bukti"), bukan "Get Started".

## 10. Arsitektur dan Tech Stack

Python monolit, satu bahasa, satu container.

- **Web:** FastAPI + Jinja2 + HTMX. Tailwind dibangun sekali dengan standalone CLI dan file CSS hasil build di-commit, sehingga runtime tidak butuh Node.
- **Database:** SQLite mode WAL + FTS5. Skema kompatibel PostgreSQL lewat SQLModel/SQLAlchemy dan Alembic. Satu writer (worker) dan WAL mencegah "database is locked".
- **Sumber data:** satu antarmuka `PublicationProvider` dengan `OpenAlexProvider` (httpx, aktif), `ManualImportProvider` (CSV/BibTeX), `ScholarScraperProvider` (kerangka, nonaktif).
- **Impor dan dedup:** pandas/openpyxl (mode read-only), `bibtexparser`, `rapidfuzz`.
- **Job:** tabel `sync_jobs` sebagai antrean. Dijalankan lewat CLI `python -m app.jobs sync` dan `python -m app.jobs reclassify`, dipanggil cron atau tombol admin. Tanpa Redis, tanpa Celery, tanpa APScheduler.
- **Auth:** satu akun admin dari env (hash kata sandi), sesi cookie `HttpOnly`, `SameSite=Lax`, `Secure` di produksi, token CSRF pada semua POST, rate limit login (5 percobaan per 15 menit per IP).
- **Upload:** batas 10 MB, hanya `.csv`, `.xlsx`, `.bib`, validasi tipe isi, tolak file yang tidak bisa diparse.
- **Deploy:** satu container Docker. Backup harian dengan `VACUUM INTO` ke folder terpisah, simpan 7 salinan terakhir plus satu salinan bulanan.

## 11. Kebutuhan Non-Fungsional

**Efisiensi**

- Jendela 3 tahun dan sinkronisasi inkremental: 1 sampai 2 request per dosen, seluruh prodi di bawah 5 menit (estimasi, dikonfirmasi di Fase 0).
- Klasifikasi hanya untuk paper atau skripsi baru, atau yang terdampak perubahan `taxonomy_version`.
- Skor dihitung saat query, tanpa tabel prakomputasi dan tanpa invalidasi.
- Halaman publik dimuat di bawah 1 detik untuk data satu prodi.

**Akurasi**

- Identitas dosen lewat ID OpenAlex yang dikonfirmasi admin, dengan ID Scholar sebagai identitas sekunder.
- Setiap label menyimpan `confidence`, `source`, `locked`, dan `taxonomy_version`.
- Golden set minimal **150** paper berlabel manual (50 cukup untuk mulai, 150 untuk menyimpulkan). Evaluasi melaporkan micro-F1 dan macro-F1 beserta support per topik. Target: micro-F1 di atas 0,80 dengan setiap topik yang dievaluasi punya minimal 5 contoh. Skrip evaluasi dijalankan setiap `taxonomy_version` berubah.
- Override manual tidak pernah tertimpa. Semua impor bisa di-rollback.
- "Data terakhir diperbarui" ditampilkan per dosen, dan cakupan 3 tahun dinyatakan terang-terangan di UI.

**Keamanan dan etika**

- Hanya data publik. Nama mahasiswa dan NIM tidak pernah tampil di halaman publik; yang tampil hanya judul, tahun, dan pembimbing.
- Rute admin dilindungi. Kredensial dan API key hanya di env, tidak pernah di kode atau log.
- API key OpenAlex lewat header `Authorization`, sehingga tidak muncul di URL maupun access log.
- Tidak ada scraping HTML Google Scholar secara default. Mode `scholarly` hanya kerangka dan tidak dijadwalkan.
- Tidak ada ranking "dosen terbaik". Framing UI selalu "bukti publikasi dan bimbingan", bukan penilaian kinerja.

## 12. Risiko dan Mitigasi

| Risiko | Mitigasi |
| --- | --- |
| Dosen senior tampak kosong karena jendela 3 tahun | Tampilkan label cakupan di profil; jendela bisa diperlebar lewat env; data lama tidak dihapus |
| Abstrak OpenAlex null untuk banyak karya | Pada 10 dosen Prodi SI, seluruh 408 karya dalam 3 tahun punya abstrak, tetapi jangan mengandalkan itu untuk dosen lain. Klasifikasi tetap dirancang untuk judul dan venue; abstrak hanya penguat |
| Judul sangat pendek sehingga kata kunci tidak cocok | Confidence minimal 2 kata kunci, review manual, dan FTS5 untuk pencarian langsung |
| Duplikat palsu dari pencocokan judul | Auto-merge hanya pada `title_hash` dengan selisih tahun maksimal 1; kemiripan 90 sampai 100 persen masuk antrean review |
| Salah klasifikasi | Kepercayaan, antrean review, override manual, golden set |
| Duplikat skripsi merusak data lama | Kunci `(title_hash, year)` dan NIM, pratinjau wajib, rollback per batch |
| Nama pembimbing beda penulisan | Normalisasi gelar, alias, pemetaan manual sekali jalan, alias ikut rollback |
| ID penulis OpenAlex salah atau terpecah | Admin memilih dari kandidat sekali; boleh beberapa ID per dosen; jumlah karya dibandingkan dengan ekspor Scholar |
| Record penulis OpenAlex menggabungkan beberapa orang bernama sama | Nama Indonesia umum (mis. "Siti Aminah", "Sugiarto") sering tergabung dalam satu record dengan puluhan afiliasi. Kandidat wajib divalidasi lewat judul karya, bukan hanya nama dan afiliasi. Bila karya tercampur, pakai beberapa ID atau andalkan ekspor Scholar untuk dosen itu |
| Admin berhenti me-review | Antrean review dirancang untuk keyboard, bukan mouse |
| Job mati di tengah sinkronisasi | `sync_jobs` resumable, status `running` lebih dari 30 menit dianggap gagal dan bisa diulang |

## 13. Rencana Pengembangan

Semua fitur di bagian 9 tetap ada. Yang dipadatkan adalah urutan dan ukuran datanya. Tujuh fase (0 sampai 6), estimasi total 7 sampai 8 hari kerja, dan **data satu prodi sudah bisa dilihat admin di akhir Fase 2, yaitu hari kerja ke-3**.

**Fase 0: Fondasi dan spike OpenAlex (0,5 hari)**

- Inisialisasi repo, `AGENTS.md` (dibuat dengan `/init` lalu disunting), `.env.example`, lint, pytest.
- Spike wajib satu dosen nyata: verifikasi `per_page=100`, `select`, `from_publication_date`, cakupan `abstract_inverted_index`, dan biaya kredit per request dari `meta.cost` serta header `X-RateLimit-*`.
- Spike disambiguasi: cari 3 nama dosen SI yang paling umum, catat jumlah kandidat dan apakah karya di tiap kandidat relevan dengan bidangnya. Hasilnya menentukan berapa lama pemetaan 50 dosen sebenarnya.
- Rekam respons spike sebagai fixture JSON untuk tes.
- Selesai jika: aplikasi kosong berjalan, tes dasar lolos, dan tiga angka OpenAlex di dokumen ini dikonfirmasi atau dikoreksi.

**Fase 1: Skema, taksonomi, admin dasar (1,5 hari)**

- Skema dan migrasi, seed `taxonomy.yaml`, `topic_labs`, login admin dengan CSRF, CRUD dosen, pemetaan ID OpenAlex, editor taksonomi.
- Selesai jika: dosen bisa ditambah dan dipetakan; topik UI/UX tampil di dua lab dari satu baris data; mengubah kata kunci menaikkan `taxonomy_version`.

**Fase 2: Sinkronisasi publikasi (1 hari)**

- `PublicationProvider`, `OpenAlexProvider` (jendela 3 tahun, Bearer, paging, backoff, kredit tercatat), `ManualImportProvider` (CSV/BibTeX), deduplikasi judul, `sync_jobs`, tombol Sinkronkan, tabel data admin dengan status per dosen.
- Selesai jika: sinkron kedua menambah 0 paper; seluruh dosen selesai di bawah 5 menit; paper yang sama dari OpenAlex dan ekspor Scholar menjadi satu baris; admin bisa melihat daftar paper per dosen hari itu juga.

**Fase 3: Klasifikasi dan review (1,5 hari)**

- Normalisasi teks, classifier deterministik untuk paper dan skripsi, multi-label, sub-topik, FTS5, antrean review dengan navigasi keyboard, override manual, skrip evaluasi golden set.
- Selesai jika: tes unit lolos, override tidak tertimpa saat `taxonomy_version` berubah, dan skrip evaluasi menghasilkan micro-F1 serta macro-F1 yang bisa dibaca.

**Fase 4: Upload skripsi (1 hari)**

- Parser CSV/XLSX, pemetaan kolom, `import_rows`, pratinjau, aturan duplikat, pencocokan pembimbing, konfirmasi, rollback termasuk alias.
- Selesai jika: mengunggah file yang sama dua kali menghasilkan 0 baris baru; rollback mengembalikan database ke kondisi sebelum batch; tes mencakup duplikat pasti, mirip, dalam-file, dan judul sama beda angkatan.

**Fase 5: Halaman publik, skor, dan deploy (1,5 hari)**

- Cari/filter, FTS5 sebagai jalur teks bebas, halaman dosen, jelajah topik, bandingkan 3 dosen, skor shrinkage, label kekuatan bukti, empat state, mobile, deploy Docker, backup harian.
- Selesai jika: semua halaman bekerja di ponsel dan desktop, kontras dan fokus keyboard lolos, dosen tanpa data muncul di grup "belum ada data".

**Fase 6: LLM opsional dan poles (0,5 hari)**

- Tahap 3 klasifikasi dengan cache ber-`taxonomy_version`, klasifikasi ulang terarah, README.
- Selesai jika: `USE_LLM=false` tidak meninggalkan jalur kode yang error, dan `USE_LLM=true` berjalan pada batch kecil dengan cache yang terbukti dipakai ulang.

## 14. Kriteria Penerimaan Akhir

- Menambah dosen cukup dengan URL Scholar dan satu konfirmasi ID OpenAlex, lalu publikasi 3 tahun terakhir terkumpul dan terklasifikasi tanpa input tambahan.
- Data satu prodi sudah bisa dilihat admin di hari kerja ke-3, dan sinkron penuh berjalan di bawah 5 menit.
- Sinkron ulang tidak mengulang pekerjaan yang sudah selesai.
- Paper dan skripsi sama-sama punya topik ber-`confidence`; setiap topik berada di lab yang benar; UI/UX dan Manajemen Proyek tampil di dua lab dari satu baris data.
- Penggabungan antar-sumber hanya memakai judul, DOI, atau ID, tidak pernah membandingkan isi paper.
- Upload skripsi tidak pernah menghasilkan duplikat maupun mengubah data lama; ada pratinjau dan rollback.
- Hasil rekomendasi menampilkan peringkat dan bukti, tanpa skor 0 sampai 100.
- Micro-F1 pada golden set di atas 0,80, dilaporkan bersama macro-F1 dan support per topik.

## 15. Prompt Pembuka untuk OpenCode

Simpan dokumen ini sebagai `PRD.md` di folder proyek, jalankan opencode di folder itu, hubungkan penyedia model dengan `/connect`, lalu jalankan `/init` (commit `AGENTS.md` yang dihasilkan ke git).

> Baca PRD.md sampai habis. Pastikan AGENTS.md berisi ringkasan aturan penting dan perintah proyek. Kerjakan bagian 13 per fase, mulai Fase 0, dan mulai tiap fase dengan rencana singkat lalu tunggu persetujuan saya. Di akhir setiap fase: jalankan tes, tampilkan ringkasan apa yang selesai dan cara mengujinya, lalu berhenti.
>
> Aturan yang tidak boleh dilanggar: jangan men-scrape HTML Google Scholar; jangan membandingkan abstrak untuk mendeteksi duplikat (judul, DOI, atau ID saja); jangan menampilkan skor 0 sampai 100 ke mahasiswa; jangan memakai `lecturer_topic_scores` atau prakomputasi skor; jangan memakai `BackgroundTasks` untuk job sinkronisasi; jangan menambah tabel `admins` atau sistem peran.
>
> Jangan menambah fitur di luar PRD. Jika ada keputusan yang ambigu, tanyakan satu pertanyaan singkat sebelum menulis kode.

## 16. Yang Perlu Disiapkan Pengguna

- Daftar dosen prodi beserta URL profil Google Scholar. Ekspor CSV/BibTeX per dosen bersifat opsional dan hanya untuk paper yang tidak terindeks OpenAlex.
- Akun OpenAlex untuk API key (disarankan, bukan wajib): openalex.org/settings/api.
- File data skripsi lama (CSV/XLSX) dengan minimal kolom judul dan pembimbing; makin lengkap (tahun, NIM) makin akurat deteksi duplikatnya.
- Sekitar 150 paper berlabel topik manual sebagai golden set (50 cukup untuk mulai mengukur).
- Opsional: kredensial LLM (penyedia mana saja atau Ollama lokal) untuk klasifikasi Tahap 3.
