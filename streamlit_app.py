import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import pypdf
import streamlit as st

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
st.title("🚚 Kurye Dağıtım Haritası")
st.write("DistHub PDF dosyasını yükleyin, otomatik olarak Yandex Harita bağlantısını alın.")

uploaded_file = st.file_uploader("PDF Dosyasını Seçin", type=["pdf"])

if uploaded_file is not None:
    with st.spinner("PDF okunuyor ve teslimat noktaları ayıklanıyor..."):
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
        st.error("PDF içinde geçerli teslimat kaydı bulunamadı!")
    else:
        st.success(f"Toplam {len(raw_items)} paket başarıyla okundu!")

        progress_bar = st.progress(0)
        status_text = st.empty()

        grouped = {}
        total = len(raw_items)
        for idx, (sira, raw_addr) in enumerate(raw_items):
            title = extract_site_or_street_label(raw_addr)
            if title not in grouped:
                status_text.text(f"Haritada aranıyor: {title}")
                lat, lon = resolve_coordinates(raw_addr)
                grouped[title] = {
                    "title": title,
                    "lat": lat,
                    "lon": lon,
                    "count": 0,
                }
            grouped[title]["count"] += 1
            progress_bar.progress((idx + 1) / total)

        status_text.empty()
        progress_bar.empty()

        valid = [d for d in grouped.values() if d["lat"]]

        pts = []
        for i, m in enumerate(valid, 1):
            pts.append(f"{m['lon']:.6f},{m['lat']:.6f},pm2rdm{i}")
        yandex_url = "https://yandex.com.tr/maps/?pt=" + "~".join(pts) + "&z=12"

        st.subheader("🎉 Haritanız Hazır!")
        st.write(f"**{len(valid)} Durak** ({len(raw_items)} Paket) tekil başlıklarda toplandı.")

        st.link_button(
            "👉 YANDEX HARİTALAR'DA AÇ",
            yandex_url,
            type="primary",
            use_container_width=True
        )

        with st.expander("Durak Listesini Gör"):
            for m in valid:
                st.write(f"- **{m['title']}** ({m['count']} Paket)")

