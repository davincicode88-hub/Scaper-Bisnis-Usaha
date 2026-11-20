import json, math, os, re
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = os.getenv("APP_USER_AGENT", "BusinessAreaScraper/1.0 (contact: admin@example.com)")
OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
with open(ROOT / "data" / "keywords.json", encoding="utf-8") as f:
    KEYWORDS = json.load(f)

OSM_FILTERS = ["shop", "amenity", "office", "craft", "healthcare", "tourism", "leisure", "industrial", "club", "emergency"]


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))


def geocode_place(query):
    """One user-triggered lookup. Cache coordinates in DB; do not bulk-geocode."""
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1, "countrycodes": "id"}
    response = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError("Lokasi tidak ditemukan. Coba nama lokasi dan kabupaten yang lebih lengkap.")
    item = data[0]
    return {"lat": float(item["lat"]), "lon": float(item["lon"]), "display_name": item.get("display_name", query)}


def build_overpass_query(lat, lon, radius_m):
    # One bounded query, not a tiled/grid bulk-harvesting job.
    selectors = "\n".join(f'nwr(around:{radius_m},{lat},{lon})["{tag}"][name];' for tag in OSM_FILTERS)
    return f"[out:json][timeout:120];(\n{selectors}\n);out center tags;"


def _tag(tags, *keys):
    for key in keys:
        value = tags.get(key)
        if value:
            return str(value).strip()
    return ""


def _address(tags):
    direct = _tag(tags, "addr:full")
    if direct:
        return direct
    keys = ["addr:hamlet", "addr:place", "addr:street", "addr:suburb", "addr:neighbourhood", "addr:city", "addr:county", "addr:state", "addr:postcode"]
    parts = []
    for key in keys:
        value = tags.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    return ", ".join(parts)


def classify(tags, name):
    pairs = [(k, v) for k, v in tags.items() if k in OSM_FILTERS]
    value = " ".join([str(v) for _, v in pairs] + [name]).lower().replace("_", " ")
    rules = [
        ("Kesehatan", ["pharmacy", "clinic", "doctors", "dentist", "hospital", "healthcare", "apotek", "apotik", "klinik"]),
        ("Makanan & Minuman", ["restaurant", "cafe", "fast food", "food court", "bar", "bakery", "coffee", "warung", "restoran", "bakso", "mie ayam"]),
        ("Perdagangan & Sembako", ["convenience", "supermarket", "department store", "greengrocer", "butcher", "beverages", "grocery", "mall", "marketplace", "toko", "sembako", "kelontong"]),
        ("Otomotif", ["car_repair", "motorcycle", "tyres", "fuel", "car wash", "bengkel", "sparepart"]),
        ("Bangunan & Material", ["doityourself", "hardware", "building materials", "trade", "toko bangunan"]),
        ("Handphone & Telekomunikasi", ["mobile_phone", "telecommunication", "phone", "pulsa", "handphone"]),
        ("Pakaian & Tekstil", ["clothes", "fabric", "shoes", "tailor", "boutique", "clothing"]),
        ("Kecantikan & Perawatan", ["hairdresser", "beauty", "cosmetics", "barber", "salon"]),
        ("Pendidikan", ["school", "college", "kindergarten", "university", "language_school", "training"]),
        ("Transportasi & Logistik", ["bus_station", "taxi", "travel_agent", "post_office", "courier"]),
        ("Akomodasi & Pariwisata", ["hotel", "hostel", "guest_house", "motel", "attraction", "museum", "camp_site"]),
        ("Keuangan & Asuransi", ["bank", "atm", "bureau_de_change", "insurance", "money_lender", "cooperative"]),
        ("Pertanian", ["agricultural", "farm", "agro", "fertilizer", "seed", "pupuk", "pertanian"]),
        ("Peternakan", ["livestock", "animal_breeding", "feed", "poultry", "peternakan", "ternak", "pakan ternak"]),
        ("Perikanan", ["fishmonger", "fishing", "fish farm", "fishery", "perikanan", "lele", "ikan"]),
        ("Industri & Produksi", ["industrial", "factory", "works", "manufacture", "warehouse", "craft", "mebel", "pabrik"]),
        ("Jasa Rumah Tangga & Personal", ["laundry", "dry_cleaning", "photographer", "copyshop", "print", "repair", "cleaning"]),
        ("Properti & Profesional", ["estate_agent", "lawyer", "notary", "architect", "accountant", "consulting"])
    ]
    for category, needles in rules:
        if any(term in value for term in needles):
            return category
    # Use the editable Indonesian/English master keyword list as a second-pass classifier.
    name_lower = name.lower()
    for category, words in KEYWORDS.items():
        if category == "Lainnya":
            continue
        if any(word.lower() in name_lower for word in words):
            return category
    return "Lainnya"


def fetch_osm_businesses(lat, lon, radius_km):
    query = build_overpass_query(lat, lon, int(radius_km * 1000))
    response = requests.post(OVERPASS_URL, data={"data": query}, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}, timeout=150)
    if response.status_code in (429, 504):
        raise RuntimeError(f"Overpass sedang sibuk (HTTP {response.status_code}). Tunggu beberapa menit sebelum mencoba lagi.")
    response.raise_for_status()
    records = []
    for element in response.json().get("elements", []):
        tags = element.get("tags", {})
        name = _tag(tags, "name", "brand", "operator")
        if not name:
            continue
        if "lat" in element and "lon" in element:
            elat, elon = float(element["lat"]), float(element["lon"])
        elif "center" in element:
            elat, elon = float(element["center"]["lat"]), float(element["center"]["lon"])
        else:
            continue
        distance = haversine_km(lat, lon, elat, elon)
        if distance > radius_km:
            continue
        phone = _tag(tags, "contact:phone", "phone", "contact:mobile", "mobile")
        website = _tag(tags, "contact:website", "website", "contact:url", "url")
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        osm_type, osm_id = element.get("type", ""), element.get("id", "")
        records.append({
            "source": "OpenStreetMap", "source_id": f"{osm_type}/{osm_id}",
            "name": name, "category": classify(tags, name),
            "subcategory": _tag(tags, *OSM_FILTERS), "address": _address(tags),
            "phone": phone, "website": website, "latitude": elat, "longitude": elon,
            "distance_km": round(distance, 3),
            "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "osm_tags": json.dumps(tags, ensure_ascii=False)
        })
    return records


def deduplicate(records):
    seen, result = set(), []
    for row in records:
        if row.get("source_id"):
            key = row["source"] + ":" + row["source_id"]
        else:
            normalized = re.sub(r"[^a-z0-9]", "", row.get("name", "").lower())
            key = f"{normalized}:{round(row.get('latitude', 0), 4)}:{round(row.get('longitude', 0), 4)}"
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result
