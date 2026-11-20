# Business Area Scraper 1.0

Aplikasi web Flask untuk mencari objek usaha/tempat bernama dari OpenStreetMap dalam radius titik pusat, menyimpan hasil di SQLite, menampilkan daftar, dan mengekspor Excel dengan sheet kategori.

## Konfigurasi awal

- Titik pusat: Pasar Mandiraja, Banjarnegara, Jawa Tengah, Indonesia
- Radius awal: 10 km
- Sumber aktif: OpenStreetMap melalui Overpass API
- Geocoding: Nominatim untuk satu pencarian lokasi yang dipicu pengguna
- Output: XLSX, sheet `MASTER_DATA`, 20 sheet kategori, `STATISTIK`, `METADATA`

## Batasan sumber gratis (wajib dibaca)

1. **OpenStreetMap bukan direktori bisnis lengkap.** Hasil hanya objek yang telah dipetakan dan memiliki tag relevan serta nama. Usaha yang belum dimasukkan kontributor OSM tidak akan muncul.
2. Telepon, website, dan alamat hanya terisi bila kontributor OSM menambahkannya. Aplikasi tidak menebak atau membuat data kontak.
3. Versi ini hanya mengaktifkan OSM/Overpass. Google Maps/Places tidak memiliki API bisnis massal yang gratis tanpa batas; Google Search tidak menyediakan API pencarian web umum gratis yang bisa diasumsikan tersedia; Facebook Graph API memerlukan izin dan akses aplikasi yang sesuai. Tidak ada scraping login/circumvention.
4. Nominatim publik digunakan hanya untuk geocoding satu lokasi yang diminta pengguna. Jangan menggunakannya untuk reverse-geocoding massal atau mengambil POI secara sistematis.
5. Overpass publik adalah layanan bersama. Jalankan pencarian manual satu per satu, jangan paralel atau berulang-ulang. Jika server sibuk/429/504, tunggu sebelum mencoba lagi. Untuk pemakaian besar/terjadwal, gunakan extract OSM atau server/provider sendiri.
6. Data OpenStreetMap dilisensikan di bawah ODbL. Pertahankan atribusi OpenStreetMap ketika menggunakan atau membagikan hasil. Periksa ketentuan lisensi untuk penggunaan database turunan.
7. Peta menggunakan tile standar OpenStreetMap. Tampilkan atribusi dan patuhi Tile Usage Policy; jangan mengunduh atau melakukan prefetch tile.

## Menjalankan di Replit

1. Buat Repl baru dengan template **Python**.
2. Upload seluruh isi folder proyek ini (atau upload ZIP lalu extract di Replit).
3. Pastikan `app.py`, `requirements.txt`, `.replit`, folder `app/`, dan `data/` berada di root proyek.
4. Buka **Secrets** di Replit dan tambahkan:
   - `APP_USER_AGENT` = `BusinessAreaScraper/1.0 (contact: email-anda@example.com)` (ganti dengan kontak yang valid)
   - `SECRET_KEY` = string acak panjang
   - (opsional) `DEFAULT_CENTER_NAME` = `Pasar Mandiraja, Banjarnegara, Jawa Tengah, Indonesia`
   - (opsional) `DEFAULT_RADIUS_KM` = `10`
5. Klik **Run**. Aplikasi berjalan pada port 5000 dan Replit akan menampilkan preview web.
6. Di aplikasi, klik **Cari titik** untuk mendapatkan koordinat Pasar Mandiraja. Periksa pin pada peta.
7. Atur radius 10 km, lalu klik **Mulai scraping**. Tunggu satu permintaan Overpass selesai.
8. Klik **Download Excel** untuk mengunduh workbook.

## Menjalankan lokal (opsional)

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit APP_USER_AGENT di .env dengan kontak valid
python app.py
```

Buka `http://127.0.0.1:5000`.

## Isi Excel

- `MASTER_DATA`: seluruh hasil.
- 20 sheet kategori dari master keyword (sheet kosong tetap dibuat bila tidak ada hasil).
- `STATISTIK`: jumlah hasil per kategori dan parameter pencarian.
- `METADATA`: titik pusat, koordinat, radius, sumber, lisensi, tanggal.

Kolom data: nama, kategori, subkategori OSM, alamat, telepon, website, latitude, longitude, jarak, sumber, ID OSM, URL sumber.

## API internal

- `GET /health` — status aplikasi.
- `GET /api/keywords` — master keyword.
- `POST /api/geocode` — geocode satu lokasi: `{ "query": "Pasar Mandiraja, Banjarnegara, Indonesia" }`.
- `POST /api/search` — jalankan pencarian: `{ "center_name": "...", "latitude": -7.45, "longitude": 109.55, "radius_km": 10 }`.
- `GET /api/search/<id>` — hasil pencarian.
- `GET /export/<id>.xlsx` — unduh Excel.

## Pengembangan berikutnya

- Tambahkan pencocokan fuzzy lintas sumber dengan review manual.
- Tambahkan sumber data lain hanya melalui API/feeds yang mengizinkan pengambilan dan ekspor.
- Pertimbangkan unduhan extract OSM regional (misalnya Geofabrik) untuk pencarian area luas/berulang daripada membebani server publik.
- Tambahkan autentikasi sebelum aplikasi dibuka untuk umum.

## Lisensi & atribusi

Aplikasi ini adalah perangkat lunak contoh. Data OSM © OpenStreetMap contributors, ODbL. Lihat https://www.openstreetmap.org/copyright.
