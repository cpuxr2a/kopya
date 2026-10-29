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
# WEB ARAYÜZÜ (STREAMLIT)
# -------------------------------------------------------------
st.title("🚚 Çorlu Kurye Dağıtım Haritası")
st.write("DistHub PDF dosyasını yükleyin, haritayı canlı görün veya Yandex'te açın.")

uploaded_file = st.file_uploader("DistHub PDF Dosyasını Yükleyin", type=["pdf"])

if uploaded_file is not None:
    with st.spinner("PDF okunuyor ve paketler ayıklanıyor..."):
        reader = pypdf.PdfReader(uploaded_file)
        raw_items = []
        for pno, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            sira_matches = re.findall(r"^(\d+)\s+\d+\s+", text, re.MULTILINE)
            form_start = text.find("KURYE TESL")
            form_text = text[form_start:] if form_start != -1 else text
            blocks = re.findall(
                r"([^\n]+)\s*\n\s*Kabul:\s*\n?(.*?)(?=(?:[^\n]+\s*\n\s*Kabul:|\Z))",
                form_text,
                re.DOTALL,
            )
            for i, s in enumerate(sira_matches):
                if i < len(blocks):
                    _, addr = blocks[i]
                    raw_items.append((int(s), " ".join(addr.split())))

        raw_items.sort(key=lambda x: x[0])

    if not raw_items:
        st.error("PDF içinde teslimat adresi bulunamadı!")
    else:
        st.success(f"Toplam {len(raw_items)} teslimat paketi okundu!")

        progress_bar = st.progress(0)
        status_text = st.empty()

        grouped = {}
        total = len(raw_items)
        for idx, (sira, raw_addr) in enumerate(raw_items):
            title = extract_site_or_street_label(raw_addr)
            desc = clean_address_description(raw_addr)

            if title not in grouped:
                status_text.text(f"Adres bulunuyor: {title}")
                lat, lon = resolve_coordinates(raw_addr)
                grouped[title] = {
                    "title": title,
                    "lat": lat,
                    "lon": lon,
                    "items": []
                }
            grouped[title]["items"].append(desc)
            progress_bar.progress((idx + 1) / total)

        status_text.empty()
        progress_bar.empty()

        valid = [d for d in grouped.values() if d["lat"]]

        # 1. YANDEX URL
        pts = []
        for i, m in enumerate(valid, 1):
            pts.append(f"{m['lon']:.6f},{m['lat']:.6f},pm2rdm{i}")
        yandex_url = "https://yandex.com.tr/maps/?pt=" + "~".join(pts) + "&z=12"

        # 2. CANLI İNTERAKTİF HARİTA (Tıklanabilir pinler + Navigasyon)
        center_lat = sum(m["lat"] for m in valid) / len(valid) if valid else 41.154
        center_lon = sum(m["lon"] for m in valid) / len(valid) if valid else 27.875

        markers_data = []
        for i, m in enumerate(valid, 1):
            cnt = len(m["items"])
            desc_html = f"<b>{cnt} Paket Bulunuyor</b><br>" + "<br>".join(f"• {x}" for x in m["items"])
            markers_data.append({
                "no": i,
                "title": m["title"],
                "count": cnt,
                "desc": desc_html,
                "lat": m["lat"],
                "lon": m["lon"]
            })

        leaflet_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ width: 100%; height: 500px; border-radius: 12px; }}
                .badge {{
                    background: #2563eb; color: white; border-radius: 50%;
                    width: 26px; height: 26px; display: flex; align-items: center;
                    justify-content: center; font-size: 11px; font-weight: bold;
                    border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                }}
                .badge.multi {{ background: #ef4444; width: 30px; height: 30px; font-size: 13px; }}
                .popup-title {{ font-size: 14px; font-weight: bold; color: #1e293b; margin-bottom: 4px; }}
                .popup-desc {{ font-size: 12px; color: #475569; line-height: 1.4; }}
                .nav-btn {{
                    display: inline-block; margin-top: 8px; padding: 6px 12px;
                    background: #2563eb; color: white; text-decoration: none;
                    border-radius: 4px; font-size: 12px; font-weight: 500;
                }}
            </style>
        </head>
        <body style="margin:0;padding:0;">
            <div id="map"></div>
            <script>
                const markers = {json.dumps(markers_data, ensure_ascii=False)};
                const map = L.map('map').setView([{center_lat:.5f}, {center_lon:.5f}], 13);
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    maxZoom: 19
                }}).addTo(map);

                const bounds = [];
                markers.forEach(m => {{
                    const icon = L.divIcon({{
                        className: 'custom-icon',
                        html: `<div class="badge ${{m.count > 1 ? 'multi' : ''}}">${{m.no}}</div>`,
                        iconSize: [28, 28],
                        iconAnchor: [14, 14]
                    }});
                    const popupContent = `
                        <div class="popup-title">${{m.title}}</div>
                        <div class="popup-desc">${{m.desc}}</div>
                        <a class="nav-btn" href="yandexnavi://build_route_on_map?lat_to=${{m.lat}}&lon_to=${{m.lon}}" target="_blank">Yandex Navigasyon</a>
                        <a class="nav-btn" style="background:#059669;margin-left:4px;" href="https://www.google.com/maps/dir/?api=1&destination=${{m.lat}},${{m.lon}}" target="_blank">Google Maps</a>
                    `;
                    L.marker([m.lat, m.lon], {{icon: icon}}).bindPopup(popupContent).addTo(map);
                    bounds.push([m.lat, m.lon]);
                }});
                if (bounds.length > 0) {{
                    map.fitBounds(bounds, {{padding: [30, 30]}});
                }}
            </script>
        </body>
        </html>
        """

        st.subheader(f"📍 Canlı Harita ({len(valid)} Durak / {len(raw_items)} Paket)")
        st.caption("Aşağıdaki pinlere dokunarak sitenin adını, daire detaylarını ve Yandex Navigasyon butonunu görebilirsiniz:")
        components.html(leaflet_html, height=520)

        col1, col2 = st.columns(2)
        with col1:
            st.link_button("🌐 Yandex Haritalar'da Aç", yandex_url, type="primary", use_container_width=True)

        # 3. CSV İndirme Butonu (Yandex Harita Oluşturucu'da Düzenleme / Taşıma Yapmak İsteyenler İçin)
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer, delimiter=";")
        csv_writer.writerow(["Enlem", "Boylam", "İsim", "Açıklama"])
        for m in valid:
            cnt = len(m["items"])
            desc_str = f"[{cnt} Paket] " + " // ".join(m["items"]) if cnt > 1 else m["items"][0]
            csv_writer.writerow([f"{m['lat']:.6f}", f"{m['lon']:.6f}", m["title"], desc_str])

        with col2:
            st.download_button(
                label="📥 Yandex Düzenleme Dosyası (CSV)",
                data=csv_buffer.getvalue().encode("utf-8-sig"),
                file_name="disthub_yandex.csv",
                mime="text/csv",
                use_container_width=True,
                help="Yandex Harita Oluşturucu'ya yükleyerek noktaların yerini fareyle sürükleyip değiştirebilirsiniz."
            )

        with st.expander("ℹ️ Noktaları Sürükleyip Yerini Değiştirmek Mi İstiyorsunuz?"):
            st.write("""
            1. Yukarıdaki **'Yandex Düzenleme Dosyası (CSV)'** butonuna basarak dosyayı indirin.
            2. [Yandex Harita Oluşturucu](https://yandex.com.tr/map-constructor) sitesini açın.
            3. **'İçe Aktar'** butonuna basıp indirdiğiniz CSV dosyasını seçin.
            4. Artık tüm noktaları fareyle/parmağınızla tutup haritada istediğiniz sokağa sürükleyebilir, adını değiştirebilirsiniz!
            """)
