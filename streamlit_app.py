import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import streamlit as st
import streamlit.components.v1 as components

try:
    import pypdf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pypdf"])
    import pypdf

st.set_page_config(
    page_title="Kurye Dağıtım Haritası",
    page_icon="🚚",
    layout="centered"
)

# -------------------------------------------------------------
# SİTE VE EV İSİMLERİ SÖZLÜĞÜ
# -------------------------------------------------------------
KNOWN_PLACES = [
    (r"İnvest\s+Önerler", "İnvest Önerler"),
    (r"Uysal\s+Flora", "Uysal Flora"),
    (r"erguvan\s+villalar[ıi]", "Erguvan Villaları"),
    (r"(?:yesilkoy\s+villalari|Yeş[iı]lk[öo]y\s+Villalar[ıi])", "Yeşilköy Villaları"),
    (r"Gazi\s+lojmanlar[ıi]", "Gazi Lojmanları"),
    (r"Gloria\s+Park\s+villa\w*", "Gloria Park Villaları"),
    (r"karaca\s+villant\s+evleri", "Karaca Villant Evleri"),
    (r"Sakura\s+garden(?:\s+sitesi)?", "Sakura Garden Sitesi"),
    (r"(?:Ballıoğlu\s+)?Casa\s+Mia(?:\s+sitesi)?", "Casa Mia Sitesi"),
    (r"PANORAMA\s+SİTESİ", "Panorama Sitesi"),
    (r"Emirgan\s*su\s+villalar[ıi]", "Emirgan Su Villaları"),
    (r"uniq\s+koru(?:\s+sitesi)?", "Uniq Koru Sitesi"),
    (r"Serenity\s+Villalar[ıi]", "Serenity Villaları"),
    (r"Kervanc[ıi]\s+Oto\s+Center", "Kervancı Oto Center"),
    (r"Togg\s+deneyim\s+merkezi", "Togg Deneyim Merkezi"),
    (r"GÜMÜŞ\s+VİLLAGE\s+SİTESİ", "Gümüş Village Sitesi"),
    (r"Gürsoy\s+villalar[ıi]", "Gürsoy Villaları"),
    (r"Rüya\s+Bahçesi\s+Evleri", "Rüya Bahçesi Evleri"),
    (r"Milenyum\s+Konaklar[ıi]", "Milenyum Konakları"),
    (r"siesta\s+villas?", "Siesta Villas"),
    (r"doğakent\s+sitesi", "Doğakent Sitesi"),
    (r"Çolakoğlu\s+vitrin\s+sitesi", "Çolakoğlu Vitrin Sitesi"),
    (r"Natura\s+konaklar[ıi]", "Natura Konakları"),
    (r"cevizlibah[cç]e\s+evleri", "Cevizlibahçe Evleri"),
    (r"Gloria\s+Garden\s+sitesi", "Gloria Garden Sitesi"),
    (r"villa\s+sert", "Villa Sert"),
    (r"Say\s+Garden(?:\s+villalar[ıi])?", "Say Garden Villaları"),
    (r"elite\s+homes\s+sitesi", "Elite Homes Sitesi"),
    (r"RAM\s+Polimer", "RAM Polimer"),
    (r"Orsan\s+Ticari\s+Araç[^,\n]+", "Orsan Fren Sistemleri"),
    (r"Ata\s+Ekmek\s+fırını", "Ata Ekmek Fırını"),
    (r"YESILKORU\s+SITESI|Yeşilkoru\s+Sitesi", "Yeşilkoru Sitesi"),
]

CORLU_BBOX = "27.75,41.08,27.92,41.20"
ONERLER_CENTER = (41.1540, 27.8750)
TURKGUCU_CENTER = (41.0961, 27.8179)


def extract_site_or_street_label(raw_addr: str) -> str:
    for pat, name in KNOWN_PLACES:
        if re.search(pat, raw_addr, re.IGNORECASE):
            return name

    m_armada = re.search(r"(Armada\s+City(?:\s*\d+)?)", raw_addr, re.IGNORECASE)
    if m_armada:
        return m_armada.group(1).title()

    m_gen = re.search(
        r"([A-Za-zÇĞİÖŞÜçğıöşü0-9\s]+?\s+(?:sitesi|villalar[ıi]|konaklar[ıi]|evleri|lojmanlar[ıi]|rezidans\w*|city(?:\s*\d+)?|center|plaza))",
        raw_addr,
        re.IGNORECASE,
    )
    if m_gen:
        cand = m_gen.group(1).strip()
        cand = re.sub(r"^(?:mahalle\w*|mh\.?|sokak|sok|cadde\w*)\s*", "", cand, flags=re.IGNORECASE).strip()
        cand = re.sub(r"\s+[A-Za-z0-9]\s*(?:blok|giriş|etap)\b.*$", "", cand, flags=re.IGNORECASE).strip()
        cand = re.sub(r"\s+(?:blok|giriş|daire|kat)\b.*$", "", cand, flags=re.IGNORECASE).strip()
        if len(cand) > 3:
            return cand.strip()

    if "Türkgücü 6" in raw_addr or "6.Sokak" in raw_addr:
        return "Türkgücü 6. Sokak No:13"
    if "Timur 9" in raw_addr:
        return "Timur 9. Sokak No:11"
    if "Timur 1" in raw_addr:
        return "Timur 1. Sokak No:8/D"
    if "istikbal 11" in raw_addr.lower():
        return "İstikbal 11. Sokak No:52"
    if "istikbal sok" in raw_addr.lower():
        return "İstikbal Sokak No:16"
    if "mehmetçik" in raw_addr.lower():
        return "Mehmetçik Sokak No:35b"
    if "4.sokak" in raw_addr.lower():
        return "4. Sokak"

    c = raw_addr
    c = re.sub(r"(Standart|Ertesi Gün|Aynı Gün|Randevulu)\s+Teslimat\s*$", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"\bTEKİRDAĞ\s+ÇORLU\b.*$", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"\bÇorlu/Tekirdağ\b.*$", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"\bÇorlu\b.*$", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"^[A-Za-zÇĞİÖŞÜçğıöşü\.]+\s+(?:mah\w*|mh\.?)\s*", "", c, flags=re.IGNORECASE).strip()

    m = re.search(
        r"((?:[A-Za-zÇĞİÖŞÜçğıöşü0-9\.]+\s+)?(?:Sokak|sok\.?|sk\.?|Caddesi|cad\.?)\s*(?:(?:no[:\.\s]*\d+[/A-Za-z0-9]*|\d+[/A-Za-z0-9]*))?)",
        c,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().lstrip(".- ")

    return c[:25].strip()


def clean_address_description(raw_addr: str) -> str:
    c = raw_addr
    c = re.sub(r"^Kabul:\s*", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"(Standart|Ertesi Gün|Aynı Gün|Randevulu)\s+Teslimat\s*$", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"\bTEKİRDAĞ\s+ÇORLU\b", "", c, flags=re.IGNORECASE)
    c = re.sub(r"\bÇorlu/Tekirdağ\b", "", c, flags=re.IGNORECASE)
    c = re.sub(r"\bTEKİRDAĞ\b", "", c, flags=re.IGNORECASE)

    mahalle_patterns = [
        r"\b(?:Önerler|Öneler)\s+(?:mahallesi|mah\w*|mh\.?)\b[,.]?",
        r"\bTürkgücü\s+(?:Osb\s+)?(?:mahallesi(?:/köyü)?|mah\w*|mh\.?)\b[,.]?",
        r"\bTürkgücü\s+Mahallesi/Köyü\.\b",
        r"\b[A-Za-zÇĞİÖŞÜçğıöşü0-9\.\-]+\s+(?:Mahallesi|Mah\.?|Mh\.?)\b[,.]?",
        r"\b(?:Havuzlar|Zafer|Hatip|Çınarlı)\s+(?:Mahallesi|Mah\.?|Mh\.?)?\b[,.]?",
    ]
    for p in mahalle_patterns:
        c = re.sub(p, "", c, flags=re.IGNORECASE)

    c = re.sub(r"\bÇorlu\b[,.]?", "", c, flags=re.IGNORECASE)
    return " ".join(c.split()).strip(",.- ")


def build_geocoding_query(raw_addr: str) -> str:
    a = raw_addr
    a = re.sub(r"^Kabul:\s*", "", a, flags=re.IGNORECASE).strip()
    a = re.sub(r"(Standart|Ertesi Gün|Aynı Gün|Randevulu)\s+Teslimat\s*$", "", a, flags=re.IGNORECASE).strip()
    a = re.sub(r"\bTEKİRDAĞ\s+ÇORLU\b", "", a, flags=re.IGNORECASE)
    a = re.sub(r"\bÇorlu/Tekirdağ\b", "", a, flags=re.IGNORECASE)
    a = re.sub(r"\bTEKİRDAĞ\b", "", a, flags=re.IGNORECASE)
    a = re.sub(r"\bÖneler\b", "Önerler", a, flags=re.IGNORECASE)
    a = re.sub(r"\bziyagökalp\b", "Ziya Gökalp", a, flags=re.IGNORECASE)
    clean_text = " ".join(a.split()).strip(",.- ")
    return f"{clean_text}, Çorlu, Tekirdağ"


def geocode_exact(query: str):
    url = (
        "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?"
        f"f=json&singleLine={urllib.parse.quote(query)}&maxLocations=1"
        f"&bbox={CORLU_BBOX}&location=27.85,41.15"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "DistHubWeb/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8")
            j = json.loads(data)
            cands = j.get("candidates", [])
            if cands:
                loc = cands[0]["location"]
                lat, lon = loc["y"], loc["x"]
                if 41.07 <= lat <= 41.22 and 27.74 <= lon <= 27.95:
                    return lat, lon
    except Exception:
        pass
    return None, None


def resolve_coordinates(raw_addr: str):
    q1 = build_geocoding_query(raw_addr)
    lat, lon = geocode_exact(q1)
    if lat:
        return lat, lon

    is_turkgucu = "türkgücü" in raw_addr.lower()
    mah = "Türkgücü Mahallesi" if is_turkgucu else "Önerler Mahallesi"
    for pat, name in KNOWN_PLACES:
        if re.search(pat, raw_addr, re.IGNORECASE):
            lat, lon = geocode_exact(f"{mah} {name}, Çorlu, Tekirdağ")
            if lat:
                return lat, lon
            break

    m_st = re.search(
        r"((?:Önerler|Türkgücü|Zafer)\s+(?:Mahallesi|Mh\.?)?\s+[A-Za-z0-9\.\s]+?(?:Sokak|sok|Cad\w*))",
        raw_addr,
        re.IGNORECASE,
    )
    if m_st:
        lat, lon = geocode_exact(f"{m_st.group(1)}, Çorlu, Tekirdağ")
        if lat:
            return lat, lon

    if is_turkgucu:
        return TURKGUCU_CENTER[0], TURKGUCU_CENTER[1]
    return ONERLER_CENTER[0], ONERLER_CENTER[1]



# -------------------------------------------------------------
# WEB ARAYÜZÜ: HARİTADA NOKTA SEÇME VE DÜZENLEME
# -------------------------------------------------------------
import hashlib

try:
    import folium
    from streamlit_folium import st_folium
except ImportError:
    st.error("Harita bileşenleri eksik. requirements.txt dosyasındaki paketleri yükleyin.")
    st.stop()

st.title("🚚 Çorlu Kurye Dağıtım Haritası")
st.write("Kurye Teslim Formu PDF'sini yükleyin. Bulunan noktaları haritadan seçip düzenleyebilir, silebilir veya yeni nokta ekleyebilirsiniz.")

uploaded_file = st.file_uploader("Kurye Teslim Formu (PDF)", type=["pdf"])

def make_yandex_url(points):
    pts = [f"{m['lon']:.6f},{m['lat']:.6f},pm2rdm{i}" for i, m in enumerate(points, 1)]
    return "https://yandex.com.tr/maps/?pt=" + "~".join(pts) + "&z=12"

# YALNIZCA BU LİSTEDEKİ YERLER GRUPLANDIRILIR.
# Diğer tüm teslimatlar, adres/başlıkları aynı olsa bile ayrı noktalar olarak kalır.
GROUP_RULES = [
    (r"armada\s*city", "Armada City"),
    (r"kervanc[ıi]\s+park\s+orman", "Kervancı Park Orman"),
    (r"emirgan\s*su|emirgansu", "Emirgansu"),
    (r"uniq\s+koru", "Uniq Koru"),
    (r"serenity", "Serenity"),
    (r"semilyon\s+park", "Semilyon Park"),
    (r"devlet\s+hastanesi", "Devlet Hastanesi"),
    (r"adliye|adalet\s+sarayı|adalet\s+sarayi", "Adliye / Adalet Sarayı"),
    (r"casa\s+mia", "Casa Mia"),
    (r"global\s+city", "Global City"),
    (r"gloria\s+park", "Gloria Park"),
    (r"gloria\s+garden", "Gloria Garden"),
]


def get_allowed_group(raw_addr: str):
    """Dönerse yalnızca kullanıcının izin verdiği 12 gruptan birinin adını döndürür."""
    for pattern, canonical_name in GROUP_RULES:
        if re.search(pattern, raw_addr, re.IGNORECASE):
            return canonical_name
    return None


def process_pdf(file_bytes):
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    raw_items = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        sira_matches = re.findall(r"^(\d+)\s+\d+\s+", page_text, re.MULTILINE)
        form_start = page_text.find("KURYE TESL")
        form_text = page_text[form_start:] if form_start != -1 else page_text
        blocks = re.findall(
            r"([^\n]+)\s*\n\s*Kabul:\s*\n?(.*?)(?=(?:[^\n]+\s*\n\s*Kabul:|\Z))",
            form_text, re.DOTALL
        )
        for i, s in enumerate(sira_matches):
            if i < len(blocks):
                _, addr = blocks[i]
                raw_items.append((int(s), " ".join(addr.split())))
    raw_items.sort(key=lambda x: x[0])
    if not raw_items:
        return []

    # Yalnızca izin verilen 12 yer ortak durağa dönüştürülür.
    grouped = {}
    points = []
    total = len(raw_items)
    progress = st.progress(0, text="Adresler bulunuyor...")

    for idx, (sira, raw_addr) in enumerate(raw_items):
        allowed_group = get_allowed_group(raw_addr)
        desc = clean_address_description(raw_addr) or raw_addr

        if allowed_group:
            if allowed_group not in grouped:
                progress.progress((idx + 1) / total, text=f"Adres bulunuyor: {allowed_group}")
                lat, lon = resolve_coordinates(raw_addr)
                grouped[allowed_group] = {
                    "id": f"p{len(points) + len(grouped) + 1}",
                    "title": allowed_group,
                    "lat": float(lat),
                    "lon": float(lon),
                    "items": [],
                    "raw_address": raw_addr,
                }
            grouped[allowed_group]["items"].append(desc)
        else:
            # İzin verilen liste dışında kalan her teslimat ayrı bir pin olur.
            progress.progress((idx + 1) / total, text=f"Adres bulunuyor: Teslimat {sira}")
            lat, lon = resolve_coordinates(raw_addr)
            display_title = desc or f"Teslimat {sira}"
            points.append({
                "id": f"delivery_{sira}_{idx + 1}",
                "title": display_title,
                "lat": float(lat),
                "lon": float(lon),
                "items": [desc],
                "raw_address": raw_addr,
            })

        progress.progress((idx + 1) / total, text=f"Adresler işleniyor: {idx + 1}/{total}")

    progress.empty()
    # Grup noktalarını da sonuç listesine ekle; grupların sırası ilk görüldükleri teslimata göre korunur.
    # Her grubun ilk sıra numarası, listedeki ilk görünümünden hesaplanır.
    group_first_order = {}
    for order, (_, raw_addr) in enumerate(raw_items):
        group_name = get_allowed_group(raw_addr)
        if group_name and group_name not in group_first_order:
            group_first_order[group_name] = order

    combined = [(group_first_order[name], point) for name, point in grouped.items()]
    # Diğer teslimatların sıralamasını koruyarak grupları da ilk görüldükleri konuma yakın sırala.
    # Noktalar için orijinal sıra bilgisi kimlik üzerinden tutulur.
    delivery_order = {}
    for order, (sira, raw_addr) in enumerate(raw_items):
        if not get_allowed_group(raw_addr):
            delivery_order[f"delivery_{sira}_{order + 1}"] = order
    combined.extend((delivery_order.get(point["id"], len(raw_items)), point) for point in points)
    combined.sort(key=lambda item: item[0])
    return [point for _, point in combined]

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    if st.session_state.get("active_pdf_hash") != file_hash:
        with st.spinner("PDF okunuyor ve adresler bulunuyor..."):
            try:
                points = process_pdf(file_bytes)
                st.session_state["points"] = points
                st.session_state["active_pdf_hash"] = file_hash
                st.session_state["selected_point_id"] = points[0]["id"] if points else None
                st.session_state["move_selected_point"] = False
            except Exception as exc:
                st.error(f"PDF işlenirken hata oluştu: {exc}")
                st.stop()

    points = st.session_state.get("points", [])
    if not points:
        st.error("PDF içinde teslimat adresi bulunamadı veya adresler okunamadı.")
        st.stop()

    # Her noktanın sabit kimliği olur; silme/düzenleme sonrası seçim kaybolmaz.
    for i, point in enumerate(points):
        point.setdefault("id", f"p{i+1}")
        point.setdefault("items", [])
        point.setdefault("raw_address", point.get("title", ""))

    st.success(f"{len(points)} durak düzenlenebilir durumda. Bir noktaya tıklayarak seçin.")
    st.caption("İpucu: Haritada bir pin seçildiğinde aşağıdaki düzenleme alanı o noktaya geçer. Konum değiştirmek için 'Konumu haritaya tıklayarak taşı' seçeneğini açın ve haritada yeni yeri tıklayın.")

    selected_id = st.session_state.get("selected_point_id")
    selected = next((p for p in points if p["id"] == selected_id), points[0])
    st.session_state["selected_point_id"] = selected["id"]

    map_center = [sum(float(p["lat"]) for p in points)/len(points), sum(float(p["lon"]) for p in points)/len(points)]
    fmap = folium.Map(location=map_center, zoom_start=13, control_scale=True)
    for i, p in enumerate(points, 1):
        is_selected = p["id"] == st.session_state["selected_point_id"]
        color = "red" if is_selected else ("orange" if len(p.get("items", [])) > 1 else "blue")
        popup_text = f"<b>{p['title']}</b><br>{len(p.get('items', []))} paket<br>{p['lat']:.6f}, {p['lon']:.6f}"
        folium.Marker(
            location=[float(p["lat"]), float(p["lon"])],
            tooltip=f"{i}. {p['title']} — seçmek için tıklayın",
            popup=folium.Popup(popup_text, max_width=300),
            icon=folium.Icon(color=color, icon="map-marker", prefix="fa"),
        ).add_to(fmap)

    # Konum taşıma modu açıkken haritada boş bir noktaya tıklama yeni koordinatı seçili noktaya uygular.
    map_result = st_folium(
        fmap, height=540, use_container_width=True,
        returned_objects=["last_object_clicked", "last_object_clicked_popup", "last_clicked"]
    )

    clicked = (map_result or {}).get("last_object_clicked")
    if clicked and not st.session_state.get("move_selected_point", False):
        try:
            click_lat, click_lon = float(clicked["lat"]), float(clicked["lng"])
            nearest = min(points, key=lambda p: (float(p["lat"])-click_lat)**2 + (float(p["lon"])-click_lon)**2)
            # Yalnızca bir pinin hemen yakınına tıklanmışsa seçimi değiştir.
            if ((float(nearest["lat"])-click_lat)**2 + (float(nearest["lon"])-click_lon)**2) < 0.00002:
                if st.session_state.get("selected_point_id") != nearest["id"]:
                    st.session_state["selected_point_id"] = nearest["id"]
                    st.rerun()
        except (KeyError, TypeError, ValueError):
            pass

    # Harita tıklamasıyla konum taşıma: seçili noktanın koordinatlarını güncelle.
    if st.session_state.get("move_selected_point", False):
        last_clicked = (map_result or {}).get("last_clicked")
        if last_clicked and isinstance(last_clicked, (list, tuple)) and len(last_clicked) == 2:
            new_lat, new_lon = float(last_clicked[0]), float(last_clicked[1])
            if 41.07 <= new_lat <= 41.22 and 27.74 <= new_lon <= 27.95:
                selected["lat"], selected["lon"] = new_lat, new_lon
                st.session_state["points"] = points
                st.session_state["move_selected_point"] = False
                st.success("Konum güncellendi.")
                st.rerun()
            else:
                st.warning("Lütfen Çorlu çevresinde, harita sınırları içindeki bir konum seçin.")

    st.divider()
    st.subheader("✏️ Seçili Noktayı Düzenle")
    # Widget anahtarları sabit nokta ID'sine bağlıdır.
    with st.form(key=f"edit_form_{selected['id']}"):
        edited_title = st.text_input("Nokta / site adı", value=selected["title"], key=f"title_{selected['id']}")
        edited_items_text = st.text_area(
            "Paket / daire açıklamaları (her satıra bir açıklama)",
            value="\n".join(selected.get("items", [])),
            height=130, key=f"items_{selected['id']}"
        )
        c1, c2 = st.columns(2)
        with c1:
            edited_lat = st.number_input("Enlem (latitude)", min_value=41.07, max_value=41.22, value=float(selected["lat"]), format="%.6f", key=f"lat_{selected['id']}")
        with c2:
            edited_lon = st.number_input("Boylam (longitude)", min_value=27.74, max_value=27.95, value=float(selected["lon"]), format="%.6f", key=f"lon_{selected['id']}")
        save_edit = st.form_submit_button("💾 Değişiklikleri Kaydet", type="primary", use_container_width=True)
    if save_edit:
        selected["title"] = edited_title.strip() or selected["title"]
        selected["items"] = [x.strip() for x in edited_items_text.splitlines() if x.strip()]
        selected["lat"], selected["lon"] = float(edited_lat), float(edited_lon)
        st.session_state["points"] = points
        st.success("Nokta güncellendi.")
        st.rerun()

    c_move, c_delete = st.columns(2)
    with c_move:
        if st.button("📍 Konumu haritaya tıklayarak taşı", use_container_width=True, key=f"move_{selected['id']}"):
            st.session_state["move_selected_point"] = True
            st.info("Şimdi haritada yeni konumu tıklayın.")
            st.rerun()
    with c_delete:
        if st.button("🗑️ Seçili noktayı sil", type="secondary", use_container_width=True, key=f"delete_{selected['id']}"):
            st.session_state["points"] = [p for p in points if p["id"] != selected["id"]]
            remaining = st.session_state["points"]
            st.session_state["selected_point_id"] = remaining[0]["id"] if remaining else None
            st.session_state["move_selected_point"] = False
            st.rerun()

    with st.expander("➕ Yeni teslimat noktası ekle"):
        with st.form("add_point_form", clear_on_submit=True):
            new_title = st.text_input("Nokta / site adı", placeholder="Örn. Yeni teslimat noktası")
            new_address = st.text_input("Adres (isteğe bağlı; koordinat bulmak için)", placeholder="Mahalle, sokak, bina no...")
            add_c1, add_c2 = st.columns(2)
            with add_c1:
                new_lat = st.number_input("Enlem", min_value=41.07, max_value=41.22, value=41.1540, format="%.6f")
            with add_c2:
                new_lon = st.number_input("Boylam", min_value=27.74, max_value=27.95, value=27.8750, format="%.6f")
            new_desc = st.text_area("Paket / daire açıklamaları", placeholder="Her satıra bir açıklama")
            add_submit = st.form_submit_button("➕ Noktayı ekle", use_container_width=True)
        if add_submit:
            title = new_title.strip() or new_address.strip() or f"Yeni nokta {len(points)+1}"
            lat, lon = float(new_lat), float(new_lon)
            if new_address.strip():
                found_lat, found_lon = resolve_coordinates(new_address.strip())
                if found_lat is not None and found_lon is not None:
                    lat, lon = float(found_lat), float(found_lon)
            new_point = {
                "id": f"manual_{int(time.time()*1000)}", "title": title,
                "lat": lat, "lon": lon,
                "items": [x.strip() for x in new_desc.splitlines() if x.strip()],
                "raw_address": new_address.strip() or title
            }
            st.session_state["points"] = points + [new_point]
            st.session_state["selected_point_id"] = new_point["id"]
            st.rerun()

    points = st.session_state.get("points", [])
    if not points:
        st.warning("Tüm noktalar silindi. Yeni nokta eklemek için yukarıdaki bölümü kullanabilirsiniz.")
        st.stop()

    # Dışa aktarma bağlantıları ve CSV her zaman düzenlenmiş son listeyi kullanır.
    yandex_url = make_yandex_url(points)
    st.divider()
    st.subheader(f"📦 Son liste: {len(points)} durak")
    st.link_button("🌐 Düzenlenmiş noktaları Yandex Haritalar'da aç", yandex_url, type="primary", use_container_width=True)

    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer, delimiter=";")
    csv_writer.writerow(["Enlem", "Boylam", "İsim", "Açıklama"])
    for p in points:
        items = p.get("items", [])
        desc = f"[{len(items)} Paket] " + " // ".join(items) if len(items) > 1 else (items[0] if items else "")
        csv_writer.writerow([f"{p['lat']:.6f}", f"{p['lon']:.6f}", p["title"], desc])
    st.download_button(
        label="📥 Düzenlenmiş Yandex CSV dosyasını indir",
        data=csv_buffer.getvalue().encode("utf-8-sig"),
        file_name="disthub_yandex_duzenlenmis.csv",
        mime="text/csv", use_container_width=True
    )

    with st.expander("Noktaları liste halinde gör"):
        for i, p in enumerate(points, 1):
            a, b = st.columns([5, 1])
            with a:
                st.write(f"**{i}. {p['title']}** — {len(p.get('items', []))} paket · {p['lat']:.6f}, {p['lon']:.6f}")
            with b:
                if st.button("Seç", key=f"select_{p['id']}"):
                    st.session_state["selected_point_id"] = p["id"]
                    st.rerun()
else:
    st.info("Başlamak için Kurye Teslim Formu PDF dosyasını yükleyin.")
