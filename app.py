import os, sqlite3, json, io, time
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, abort
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
from app.services import KEYWORDS, geocode_place, fetch_osm_businesses, deduplicate
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
DB_PATH = ROOT / "business_area.db"
DEFAULT_CENTER = os.getenv("DEFAULT_CENTER_NAME", "Pasar Mandiraja, Banjarnegara, Jawa Tengah, Indonesia")
DEFAULT_RADIUS = float(os.getenv("DEFAULT_RADIUS_KM", "10"))
_LAST_GEOCODE_AT = 0.0


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, center_name TEXT, display_name TEXT,
            latitude REAL, longitude REAL, radius_km REAL, created_at TEXT, result_count INTEGER
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS geocode_cache (
            query_key TEXT PRIMARY KEY, display_name TEXT, latitude REAL, longitude REAL, cached_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, search_id INTEGER, source TEXT, source_id TEXT,
            name TEXT, category TEXT, subcategory TEXT, address TEXT, phone TEXT, website TEXT,
            latitude REAL, longitude REAL, distance_km REAL, source_url TEXT, osm_tags TEXT,
            FOREIGN KEY(search_id) REFERENCES searches(id)
        )""")


@app.get("/")
def index():
    with db() as conn:
        recent = conn.execute("SELECT * FROM searches ORDER BY id DESC LIMIT 8").fetchall()
    keyword_counts = {k: len(v) for k, v in KEYWORDS.items()}
    return render_template("index.html", default_center=DEFAULT_CENTER, default_radius=DEFAULT_RADIUS,
                           categories=list(KEYWORDS.keys()), keyword_counts=keyword_counts, recent=recent)


@app.get("/api/keywords")
def keywords():
    return jsonify(KEYWORDS)


@app.post("/api/geocode")
def geocode():
    body = request.get_json(force=True)
    query = (body.get("query") or "").strip()
    if len(query) < 4:
        return jsonify(error="Masukkan nama lokasi yang lebih lengkap."), 400
    global _LAST_GEOCODE_AT
    key = query.casefold().strip()
    with db() as conn:
        cached = conn.execute("SELECT * FROM geocode_cache WHERE query_key=?", (key,)).fetchone()
    if cached:
        return jsonify(lat=cached["latitude"], lon=cached["longitude"], display_name=cached["display_name"], cached=True)
    wait = 1.05 - (time.time() - _LAST_GEOCODE_AT)
    if wait > 0:
        return jsonify(error="Mohon tunggu sebentar sebelum permintaan geocoding berikutnya."), 429
    try:
        result = geocode_place(query)
        _LAST_GEOCODE_AT = time.time()
        with db() as conn:
            conn.execute("INSERT OR REPLACE INTO geocode_cache(query_key,display_name,latitude,longitude,cached_at) VALUES(?,?,?,?,?)",
                         (key, result["display_name"], result["lat"], result["lon"], datetime.now().isoformat(timespec="seconds")))
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=f"Geocoding gagal: {exc}"), 502


@app.post("/api/search")
def search():
    body = request.get_json(force=True)
    center_name = (body.get("center_name") or DEFAULT_CENTER).strip()
    radius = float(body.get("radius_km", DEFAULT_RADIUS))
    if radius <= 0 or radius > 50:
        return jsonify(error="Radius harus lebih dari 0 dan maksimal 50 km pada versi ini."), 400
    try:
        if body.get("latitude") is not None and body.get("longitude") is not None:
            lat, lon = float(body["latitude"]), float(body["longitude"])
            display_name = center_name
        else:
            place = geocode_place(center_name)
            lat, lon, display_name = place["lat"], place["lon"], place["display_name"]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify(error="Koordinat tidak valid."), 400
        # Reuse an identical recent search to avoid repeatedly querying the shared Overpass service.
        with db() as conn:
            recent = conn.execute("SELECT * FROM searches ORDER BY id DESC LIMIT 30").fetchall()
            for previous in recent:
                try:
                    age = datetime.now() - datetime.strptime(previous["created_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if age.total_seconds() < 3600 and abs(previous["latitude"]-lat) < 0.000001 and abs(previous["longitude"]-lon) < 0.000001 and abs(previous["radius_km"]-radius) < 0.0001:
                    grouped = conn.execute("SELECT category, COUNT(*) AS total FROM businesses WHERE search_id=? GROUP BY category", (previous["id"],)).fetchall()
                    cached_counts = {row["category"]: row["total"] for row in grouped}
                    return jsonify(search_id=previous["id"], count=previous["result_count"], categories=cached_counts,
                                   center={"name": previous["display_name"], "latitude": lat, "longitude": lon},
                                   cached=True, message="Menggunakan hasil pencarian yang tersimpan (cache 1 jam).")
        records = deduplicate(fetch_osm_businesses(lat, lon, radius))
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db() as conn:
            cur = conn.execute("INSERT INTO searches(center_name,display_name,latitude,longitude,radius_km,created_at,result_count) VALUES(?,?,?,?,?,?,?)",
                               (center_name, display_name, lat, lon, radius, created, len(records)))
            search_id = cur.lastrowid
            for r in records:
                conn.execute("""INSERT INTO businesses(search_id,source,source_id,name,category,subcategory,address,phone,website,latitude,longitude,distance_km,source_url,osm_tags)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (search_id, r.get("source"), r.get("source_id"), r.get("name"), r.get("category"), r.get("subcategory"),
                     r.get("address"), r.get("phone"), r.get("website"), r.get("latitude"), r.get("longitude"),
                     r.get("distance_km"), r.get("source_url"), r.get("osm_tags")))
        counts = {}
        for r in records:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
        return jsonify(search_id=search_id, count=len(records), categories=counts,
                       center={"name": display_name, "latitude": lat, "longitude": lon},
                       message="Pencarian selesai. Data yang ditemukan berasal dari OpenStreetMap.")
    except Exception as exc:
        return jsonify(error=f"Pencarian gagal: {exc}"), 502


@app.get("/api/search/<int:search_id>")
def search_detail(search_id):
    with db() as conn:
        search_row = conn.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
        if not search_row:
            abort(404)
        rows = conn.execute("SELECT * FROM businesses WHERE search_id=? ORDER BY category,name", (search_id,)).fetchall()
    return jsonify(search=dict(search_row), businesses=[dict(r) for r in rows])


@app.get("/export/<int:search_id>.xlsx")
def export(search_id):
    with db() as conn:
        s = conn.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
        if not s:
            abort(404)
        rows = conn.execute("SELECT * FROM businesses WHERE search_id=? ORDER BY category,name", (search_id,)).fetchall()
    wb = Workbook()
    ws = wb.active
    ws.title = "MASTER_DATA"
    headers = ["No", "Nama Usaha", "Kategori", "Subkategori OSM", "Alamat", "Nomor HP/Telepon", "Website", "Latitude", "Longitude", "Jarak KM", "Sumber", "ID Sumber", "URL Sumber"]
    def style_sheet(sheet):
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        widths = [7, 30, 28, 20, 42, 22, 35, 14, 14, 12, 18, 20, 42]
        for i, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(i)].width = width
        sheet.row_dimensions[1].height = 30
    def write_rows(sheet, data):
        sheet.append(headers)
        for i, r in enumerate(data, 1):
            sheet.append([i, r["name"], r["category"], r["subcategory"], r["address"], r["phone"], r["website"],
                          r["latitude"], r["longitude"], r["distance_km"], r["source"], r["source_id"], r["source_url"]])
        style_sheet(sheet)
    write_rows(ws, rows)
    categories = list(KEYWORDS.keys())
    for cat in categories:
        title = cat.replace("&", "dan").replace("/", "-")[:31]
        # Excel sheet names must be unique.
        base, n = title, 2
        while title in wb.sheetnames:
            suffix = f"_{n}"
            title, n = base[:31-len(suffix)] + suffix, n+1
        cat_rows = [r for r in rows if (r["category"] or "Lainnya") == cat]
        write_rows(wb.create_sheet(title), cat_rows)
    stat = wb.create_sheet("STATISTIK")
    stat.append(["Kategori", "Jumlah Usaha"])
    from collections import Counter
    for cat, count in Counter(r["category"] or "Lainnya" for r in rows).most_common():
        stat.append([cat, count])
    stat.append([])
    stat.append(["Titik Pusat", s["display_name"]])
    stat.append(["Latitude", s["latitude"]])
    stat.append(["Longitude", s["longitude"]])
    stat.append(["Radius KM", s["radius_km"]])
    stat.append(["Tanggal Pencarian", s["created_at"]])
    style_sheet(stat)
    meta = wb.create_sheet("METADATA")
    meta.append(["Parameter", "Nilai"])
    for pair in [("Titik pusat", s["display_name"]), ("Latitude", s["latitude"]), ("Longitude", s["longitude"]),
                 ("Radius KM", s["radius_km"]), ("Sumber", "OpenStreetMap / Overpass API"),
                 ("Lisensi", "Open Database License (ODbL) - atribusi OpenStreetMap"),
                 ("Tanggal", s["created_at"]), ("Jumlah hasil", s["result_count"])]:
        meta.append(list(pair))
    style_sheet(meta)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"database_usaha_radius_{search_id}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/health")
def health():
    return jsonify(status="ok", app="Business Area Scraper", version="1.0.0")


init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
