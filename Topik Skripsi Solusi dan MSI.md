# List Topik Skripsi — Lab SOLUSI dan Lab MSI

Daftar topik skripsi di Prodi Sistem Informasi, dikelompokkan ke dua fokus lab: **SOLUSI** dan **MSI**. Semua topik diambil dari taksonomi yang dipakai **Sistem Rekomendasi Dosen Pembimbing Skripsi** (proyek ini), jadi setiap topik langsung bisa dicocokkan dengan bukti kepakaran dosen: paper 3 tahun terakhir dan skripsi yang pernah dibimbing.

Proyek Sistem Rekomendasi Dosen Pembimbing Skripsi sendiri adalah contoh skripsi penuh di lab SOLUSI (rancang bangun aplikasi + data mining + AI).

---

## Lab SOLUSI

Topik yang berfokus membangun solusi aplikasi, sistem, dan model.

| No | Topik | Contoh Judul Skripsi |
| --- | --- | --- |
| 1 | Rancang Bangun Aplikasi | Rancang bangun aplikasi web pengelolaan peminjaman alat di laboratorium (metode prototype) |
| 2 | Rancang Bangun Aplikasi | Pengembangan aplikasi mobile pencatatan kegiatan UKM menggunakan Flutter |
| 3 | Data Mining — Analisis Sentimen | Analisis sentimen ulasan aplikasi e-wallet pada Twitter menggunakan Naive Bayes |
| 4 | Data Mining — Forecasting | Peramalan permintaan produk UMKM menggunakan metode time series (ARIMA/LSTM) |
| 5 | Data Mining — Umum | Klasifikasi kelayakan penerima bantuan menggunakan algoritme Random Forest |
| 6 | UI/UX | Evaluasi usability aplikasi e-commerce menggunakan System Usability Scale (SUS) |
| 7 | Testing | Pengujian black box dan automation testing (Selenium) pada modul administrasi akademik |
| 8 | Manajemen Proyek *(topik bersama dengan MSI)* | Penerapan Scrum pada pengembangan sistem informasi manajemen jadwal kuliah |
| 9 | SPK (Sistem Pendukung Keputusan) | Sistem pendukung keputusan pemilihan dosen pembimbing skripsi menggunakan metode TOPSIS |
| 10 | Pemodelan & Simulasi | Simulasi system dynamics pelayanan satu pintu perizinan (Vensim) |
| 11 | Jaringan | Analisis QoS jaringan hotel dan perancangan VLAN dengan Mikrotik |
| 12 | IoT | Sistem monitoring kelembapan tanah hidroponik berbasis ESP32 dengan protokol MQTT |
| 13 | Customisasi ERP | Customisasi modul penggajian pada Odoo untuk UKM manufaktur |
| 14 | Manajemen Proses Bisnis | Pemodelan BPMN dan perancangan ulang (BPR) proses layanan koperasi |
| 15 | Business Intelligence Application | Perancangan dashboard penjualan berbasis Power BI untuk UMKM |
| 16 | AI | Chatbot FAQ akademik berbasis NLP dan pengembangan aplikasi klasifikasi gambar dengan CNN |

**Contoh nyata di lab SOLUSI (proyek ini):**

- **Sistem Rekomendasi Dosen Pembimbing Skripsi** — website internal yang mengumpulkan publikasi dosen 3 tahun terakhir dari OpenAlex API dan ekspor Google Scholar, mengklasifikasikan paper ke topik taksonomi (multi-label), lalu merekomendasikan dosen berdasarkan bukti publikasi dan riwayat bimbingan. Mencakup topik **Rancang Bangun Aplikasi** (web app), **Data Mining** (klasifikasi multi-topik), dan **AI** (klasifikasi teks, integrasi LLM opsional).

---

## Lab MSI

Topik komplementer SOLUSI; fokus pada perencanaan, pengelolaan, audit, dan evaluasi TI.

| No | Topik | Contoh Judul Skripsi |
| --- | --- | --- |
| 1 | Perencanaan dan Strategi TI | Perencanaan strategis SI/TI kampus menggunakan framework TOGAF dan blueprint tiga tahun |
| 2 | Audit dan Tata Kelola TI | Audit tata kelola TI layanan sistem informasi akademik (COBIT, maturity level) |
| 3 | Pengembangan dan Evaluasi Sistem | Evaluasi keberhasilan sistem informasi UKM menggunakan model DeLone & McLean |
| 4 | Manajemen Proyek TI *(topik bersama dengan SOLUSI)* | Analisis risiko proyek TI menggunakan PMBOK pada proyek digitalisasi layanan |
| 5 | UI/UX dan Pengalaman Pengguna *(topik bersama dengan SOLUSI)* | Pengukuran pengalaman pengguna aplikasi layanan publik dengan Pendekatan EUCS |
| 6 | Operasional TI & Infrastruktur | Perancangan ITSM service desk pemerintah daerah berdasarkan ITIL |
| 7 | Manajemen Data dan Informasi | Perancangan tata kelola data (data governance) dan kualitas data master di dinas |
| 8 | Adopsi Teknologi dan Inovasi | Analisis adopsi teknologi digital pembayaran menggunakan UTAUT |
| 9 | Analisis Sistem dan Pemodelan Dinamik | Pemodelan system dynamics alur layanan perizinan dengan causal loop dan stock-flow |

---

## Keselarasan dengan Sistem

- Topik **UI/UX** dan **Manajemen Proyek** bersifat lintas lab: satu topik, dua lab. Sistem menampilkan nama spesifik lab ("UI/UX dan Pengalaman Pengguna" di MSI), tetapi data topiknya satu sumber.
- Mahasiswa tinggal mencari topik pada halaman publik; sistem menampilkan **peringkat dosen** berdasarkan bukti, tanpa skor 0–100.
- Taksonomi dapat diupdate admin lewat editor taksonomi (setiap perubahan menaikkan `taxonomy_version`).
