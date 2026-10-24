import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import fitz
import re
import streamlit.components.v1 as components
import json
import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. KONFIGURASI UI/UX (ADAPTIF DARK/LIGHT 3D)
# ==========================================
st.set_page_config(page_title="Sistem Copy Resep 3D", page_icon="🚀", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 800; }
    
    .stButton>button { background: linear-gradient(135deg, #4F46E5, #3B82F6); color: white !important; border-radius: 12px; padding: 12px 24px; font-weight: 800; border: none; box-shadow: 0 6px 0 #312E81, 0 15px 20px rgba(0,0,0,0.2); transition: all 0.1s; text-transform: uppercase; letter-spacing: 1px; }
    .stButton>button:active, .stButton>button:focus { transform: translateY(6px); box-shadow: 0 0 0 #312E81, 0 5px 5px rgba(0,0,0,0.2); outline: none; }
    
    .btn-delete>button { background: linear-gradient(135deg, #EF4444, #F87171) !important; box-shadow: 0 6px 0 #991B1B, 0 10px 15px rgba(239,68,68,0.3) !important; margin-top: 15px !important; }
    .btn-delete>button:active { transform: translateY(6px); box-shadow: 0 0 0 #991B1B, 0 3px 3px rgba(239,68,68,0.3) !important; }
    
    .chat-bubble { background: linear-gradient(145deg, #ffffff, #f0f0f0); border-radius: 0px 20px 20px 20px; padding: 18px 25px; margin-bottom: 12px; box-shadow: 5px 5px 15px rgba(0,0,0,0.1), -5px -5px 15px rgba(255,255,255,0.05); border-left: 6px solid #0EA5E9; color: #0F172A !important; }
    .bubble-header { font-size: 17px; font-weight: 900; color: #0369A1 !important; margin-bottom: 8px; }
    .bubble-body { font-size: 15px; font-weight: 600; color: #334155 !important; }
    
    .status-box { padding: 15px; border-radius: 15px; margin-bottom: 20px; font-weight: 800; text-align: center; background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2); box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
    .status-success { border-left: 5px solid #10B981; }
    .status-warning { border-left: 5px solid #F59E0B; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. KONEKSI GOOGLE SHEETS & SISTEM HAPUS DUPLIKAT
# ==========================================
def get_gsheets_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        has_secrets = False
        try:
            if "google_credentials" in st.secrets: has_secrets = True
        except: pass

        if has_secrets: creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["google_credentials"]), scope)
        elif os.path.exists("credentials.json"): creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        else: return None, "Offline (Lokal) 🔌"
        
        return gspread.authorize(creds).open("Data Copy Resep Iter").sheet1, "Online (Tersinkron) 🌐"
    except Exception as e:
        return None, f"Koneksi Gagal: {e}"

sheet, connection_status = get_gsheets_connection()
if 'db_lokal' not in st.session_state: st.session_state['db_lokal'] = []

def simpan_data(data_dict):
    row_data = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data_dict["Nama Pasien"], data_dict["No. RM"], data_dict["Tanggal Resep Asli"],
        data_dict["Nama Dokter"], data_dict["No. Kartu"], data_dict["SEP"], data_dict["Jumlah Iter"], data_dict["Daftar Obat"]
    ]
    
    # SISTEM DETEKSI & HAPUS DATA GANDA OTOMATIS
    if sheet: 
        try:
            records = sheet.get_all_records()
            for i, rec in enumerate(records):
                # Jika No. RM dan Tanggal Resep Asli sama persis, hapus data lama di G-Sheets
                if str(rec.get("No. RM", "")).strip() == str(data_dict["No. RM"]).strip() and \
                   str(rec.get("Tanggal Resep Asli", "")).strip() == str(data_dict["Tanggal Resep Asli"]).strip():
                    sheet.delete_row(i + 2)
                    break 
        except: pass
        sheet.append_row(row_data)
    else: 
        # Hapus duplikat untuk penyimpanan lokal
        st.session_state['db_lokal'] = [
            r for r in st.session_state['db_lokal'] 
            if not (str(r[2]).strip() == str(data_dict["No. RM"]).strip() and str(r[3]).strip() == str(data_dict["Tanggal Resep Asli"]).strip())
        ]
        st.session_state['db_lokal'].append(row_data)

def ambil_semua_data():
    if sheet: return pd.DataFrame(sheet.get_all_records())
    kolom = ["Tanggal Input", "Nama Pasien", "No. RM", "Tanggal Resep Asli", "Nama Dokter", "No. Kartu", "SEP", "Jumlah Iter", "Daftar Obat"]
    return pd.DataFrame(st.session_state['db_lokal'], columns=kolom)

# ==========================================
# 3. FUNGSI PARSER (URL iHOSPITAL DENGAN LOGIN & PDF)
# ==========================================
def parse_teks_resep(teks_mentah):
    hasil = {"nama": "", "rm": "", "no_kartu": "", "sep": "", "tgl_resep": datetime.now(), "dokter": "", "list_obat": []}
    
    m_nama = re.search(r"Nama\s+Lengkap[\s:]*\n?\s*:?\s*\n?\s*([A-Za-z\s\'\.]+)", teks_mentah, re.IGNORECASE)
    if m_nama:
        baris_nama = [b.strip() for b in m_nama.group(1).split('\n') if b.strip() and b.strip() != ':']
        if baris_nama: hasil["nama"] = baris_nama[0]

    m_rm = re.search(r"RM\s*[\s:]*\n?\s*:?\s*\n?\s*([a-zA-Z0-9]+)", teks_mentah, re.IGNORECASE)
    if m_rm: hasil["rm"] = m_rm.group(1).strip()

    m_kartu = re.search(r"(\d{13})\s*/\s*([A-Za-z0-9]{15,25})", teks_mentah)
    if m_kartu:
        hasil["no_kartu"] = m_kartu.group(1).strip(); hasil["sep"] = m_kartu.group(2).strip()
    else:
        m_kartu_alt = re.search(r"Kartu/SEP[\s:]*\n?\s*:?\s*\n?\s*([\d]+)\s*/\s*([A-Za-z0-9]+)", teks_mentah, re.IGNORECASE)
        if m_kartu_alt: hasil["no_kartu"] = m_kartu_alt.group(1).strip(); hasil["sep"] = m_kartu_alt.group(2).strip()

    m_tgl = re.search(r"Tanggal[\s:]*\n?\s*:?\s*\n?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", teks_mentah, re.IGNORECASE)
    if m_tgl:
        hari, bulan_str, tahun = int(m_tgl.group(1)), m_tgl.group(2).lower(), int(m_tgl.group(3))
        bulan_map = {'jan':1, 'feb':2, 'mar':3, 'apr':4, 'mei':5, 'jun':6, 'jul':7, 'agu':8, 'sep':9, 'okt':10, 'nov':11, 'des':12}
        try: hasil["tgl_resep"] = datetime(tahun, next((v for k, v in bulan_map.items() if bulan_str.startswith(k)), datetime.now().month), hari)
        except: pass

    m_dok = re.search(r"\(?\s*(dr\.\s*[A-Za-z\.\s\,]+(?:\,\s*[A-Za-z\.\s]+)*)\s*\)?", teks_mentah, re.IGNORECASE)
    if m_dok: hasil["dokter"] = m_dok.group(1).strip()
    
    kata_terlarang = ['TELAAH', 'Tepat', 'Dupikasi', 'Interaksi', 'Kontraindikasi', 'Klinis', 'Farmasetis', 'Petugas', 'Jam', 'Tanggal', 'Identitas', 'Nama']
    try:
        for bagian in teks_mentah.split('R/')[1:]:
            baris = [b.strip() for b in bagian.strip().split('\n') if b.strip()]
            if not baris: continue
            nama_obat = baris[0].replace('//', '').strip()
            jumlah, signa = "", ""
            for b in baris[1:]:
                if any(t.lower() in b.lower() for t in kata_terlarang): break 
                if b.startswith('No.'): jumlah = b
                elif 'x' in b.lower() and any(c.isdigit() for c in b): signa = b
            if nama_obat and not any(t.lower() in nama_obat.lower() for t in kata_terlarang):
                hasil["list_obat"].append({"nama": nama_obat, "signa": signa, "jumlah": jumlah, "status": "det orig"})
    except: pass
            
    return hasil

def ambil_data_dari_url(url_target):
    teks_mentah = ""
    try:
        session = requests.Session()
        
        # MENGGUNAKAN DATA LOGIN OTOMATIS
        # Akan mencoba mengambil dari secrets terlebih dahulu, jika tidak ada akan menggunakan kredensial yang Anda berikan
        user_login = st.secrets.get("ihospital_username", "wisnuchandra")
        pass_login = st.secrets.get("ihospital_password", "Rsimp-20241")
        
        login_url = "https://ihospital.rsimasyithoh.com/index.php?r=site/login"
        payload = {
            "LoginForm[username]": user_login,
            "LoginForm[password]": pass_login
        }
        
        # Proses eksekusi login ke sistem RS
        session.post(login_url, data=payload, timeout=5)
        
        # Ambil data dari link resep
        response = session.get(url_target, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            teks_mentah = soup.get_text()
        else:
            teks_mentah = f"Error HTTP: {response.status_code}"
    except Exception as e:
        teks_mentah = f"Gagal mengambil URL: {e}"

    return parse_teks_resep(teks_mentah), teks_mentah

def ekstrak_data_pdf(file_pdf):
    teks_mentah = "".join(page.get_text() for page in fitz.open(stream=file_pdf.read(), filetype="pdf"))
    return parse_teks_resep(teks_mentah)

# ==========================================
# 4. SIDEBAR & JAM 3D LIVE
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=80)
    st.title("Pusat Kendali")
    
    components.html("""
    <div style="font-family: 'Arial', sans-serif; text-align: center; padding: 15px; background: linear-gradient(145deg, #ffffff, #e6e6e6); box-shadow: 5px 5px 10px rgba(0,0,0,0.1); border-radius: 15px; margin-bottom: 20px;">
        <div id="date" style="font-size: 13px; font-weight: bold; color: #64748B; text-transform: uppercase;"></div>
        <div id="time" style="font-size: 26px; font-weight: 900; color: #2563EB; letter-spacing: 2px;"></div>
    </div>
    <script>
        function updateTime() {
            var now = new Date();
            var options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
            document.getElementById('date').innerText = now.toLocaleDateString('id-ID', options);
            document.getElementById('time').innerText = now.toLocaleTimeString('id-ID');
        }
        setInterval(updateTime, 1000); updateTime();
    </script>
    """, height=120)
    
    df_data = ambil_semua_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    total_hari_ini = len(df_data[df_data['Tanggal Input'].astype(str).str.startswith(today_str)]) if not df_data.empty and "Tanggal Input" in df_data.columns else 0
    
    st.metric(label="Resep Masuk Hari Ini", value=f"{total_hari_ini} Resep", delta="Aktif")
    st.markdown(f'<div class="status-box status-{"success" if sheet else "warning"}">{"✅" if sheet else "⚠️"} {connection_status}</div>', unsafe_allow_html=True)
    
    st.markdown("### 📈 Grafik 7 Hari")
    last_7_days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    df_chart = pd.DataFrame({"Tanggal": last_7_days, "Jumlah": 0}).set_index("Tanggal")
    if not df_data.empty and "Tanggal Input" in df_data.columns:
        counts = df_data['Tanggal Input'].str[:10].value_counts()
        for date, count in counts.items():
            if date in df_chart.index: df_chart.at[date, "Jumlah"] = count
    st.bar_chart(df_chart, use_container_width=True, color="#8B5CF6")

# ==========================================
# 5. HALAMAN UTAMA (TABS)
# ==========================================
st.title("✨ Sistem Cerdas Copy Resep & Etiket")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔗 Ambil via Link iHospital", "📂 Upload PDF Resep", "✍️ Input Manual", "🖨️ Pusat Cetak", "🔍 Laporan Data"])

# --- TAB 1: LINK iHOSPITAL ---
with tab1:
    if st.session_state.get('show_success_tab1'):
        st.success("✅ Sukses Disimpan! Data ganda otomatis dihapus dan diperbarui. Buka Tab '🖨️ Pusat Cetak'.")
        st.session_state['show_success_tab1'] = False

    st.info("💡 **Petunjuk:** Tempel tautan URL iHospital resep pasien di bawah ini. Sistem akan otomatis login.")
    url_input = st.text_input("🔗 Link URL iHospital:", placeholder="https://ihospital.rsimasyithoh.com/...")
    
    if url_input.strip():
        if 'hasil_ekstrak_url' not in st.session_state or st.session_state.get('last_url') != url_input:
            hasil, raw_text = ambil_data_dari_url(url_input)
            st.session_state['hasil_ekstrak_url'] = hasil
            st.session_state['last_url'] = url_input
            st.session_state['raw_text_url'] = raw_text
        
        hasil = st.session_state['hasil_ekstrak_url']
        
        if not hasil["nama"] or "Gagal" in st.session_state.get('raw_text_url', ''):
            st.warning("⚠️ Data otomatis dari link gagal terbaca. Periksa koneksi internet atau gunakan tab **Upload PDF Resep**.")

        st.subheader("👤 Identitas Pasien")
        c1, c2, c3 = st.columns(3)
        with c1:
            nama_p = st.text_input("Nama Pasien", value=hasil["nama"], key="p_nama_url")
            rm_p = st.text_input("No. RM", value=hasil["rm"], key="p_rm_url")
        with c2:
            kartu_p = st.text_input("No. Kartu BPJS", value=hasil["no_kartu"], key="p_kartu_url")
            sep_p = st.text_input("No. SEP", value=hasil["sep"], key="p_sep_url")
        with c3:
            tgl_r = st.date_input("Tanggal Resep Asli", value=hasil["tgl_resep"], key="p_tgl_url")
            dokter_p = st.text_input("Nama Dokter", value=hasil["dokter"], key="p_dok_url")
            iter_p = st.number_input("Jumlah Iter", min_value=0, value=2, key="p_iter_url")
            
        st.markdown("---")
        st.subheader("💊 Rincian Obat")
        
        opsi_status = ["det orig", "det", "ne det", "det iter 1x", "det iter 2x", "det iter 3x"]
        if 'list_obat_url' not in st.session_state or st.session_state.get('last_url_obat') != url_input:
            st.session_state['list_obat_url'] = list(hasil["list_obat"])
            st.session_state['last_url_obat'] = url_input

        indices_to_remove = []
        for idx, item in enumerate(st.session_state['list_obat_url']):
            col_buble, col_aksi = st.columns([7, 3])
            with col_buble:
                st.markdown(f"""
                <div class="chat-bubble">
                    <div class="bubble-header">💊 R/ {item['nama']}</div>
                    <div class="bubble-body">📋 Aturan Pakai: <strong>{item['signa']}</strong> &nbsp;&nbsp;|&nbsp;&nbsp; 📦 Jumlah: <strong>{item['jumlah']}</strong></div>
                </div>
                """, unsafe_allow_html=True)
            with col_aksi:
                st.write("") 
                item['status'] = st.selectbox(f"Status:", opsi_status, index=opsi_status.index(item.get('status', 'det orig')), key=f"stat_u_{idx}")
                st.markdown('<div class="btn-delete">', unsafe_allow_html=True)
                if st.button("🗑️ Hapus", key=f"del_u_{idx}"): indices_to_remove.append(idx)
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

        if indices_to_remove:
            for i in sorted(indices_to_remove, reverse=True): st.session_state['list_obat_url'].pop(i)
            st.rerun()
            
        st.markdown("---")
        if st.button("💾 Simpan Data Link & Siapkan Cetak", key="btn_save_url"):
            teks_db = " | ".join([f"{o['nama']} ({o['signa']} {o['jumlah']}) [{o['status']}]" for o in st.session_state['list_obat_url']])
            simpan_data({
                "Nama Pasien": nama_p, "No. RM": rm_p, "Tanggal Resep Asli": tgl_r.strftime("%Y-%m-%d"), 
                "Nama Dokter": dokter_p, "No. Kartu": kartu_p, "SEP": sep_p, 
                "Jumlah Iter": iter_p, "Daftar Obat": teks_db
            })
            st.session_state['data_cetak'] = {
                "nama": nama_p, "rm": rm_p, "tgl_resep": tgl_r.strftime("%d %B %Y"), 
                "dokter": dokter_p, "kartu": kartu_p, "sep": sep_p, "iter": iter_p, 
                "obat_list": st.session_state['list_obat_url'], "tgl_copy": datetime.now().strftime("%d %B %Y")
            }
            st.session_state['show_success_tab1'] = True
            st.rerun()

# --- TAB 2: UPLOAD PDF ---
with tab2:
    if st.session_state.get('show_success_tab2'):
        st.success("✅ Sukses Disimpan dari PDF! Data ganda otomatis dihapus dan diperbarui. Buka Tab '🖨️ Pusat Cetak'.")
        st.session_state['show_success_tab2'] = False

    st.info("💡 **Petunjuk:** Jalur alternatif unggah dokumen PDF resep.")
    file_upload = st.file_uploader("📂 Unggah File PDF Resep", type=['pdf'], key="uploader_pdf")
    
    if file_upload:
        if 'hasil_ekstrak_pdf' not in st.session_state or st.session_state.get('last_file_pdf') != file_upload.name:
            st.session_state['hasil_ekstrak_pdf'] = ekstrak_data_pdf(file_upload)
            st.session_state['last_file_pdf'] = file_upload.name
        
        hasil = st.session_state['hasil_ekstrak_pdf']
        
        st.subheader("👤 Identitas Pasien (PDF)")
        c1, c2, c3 = st.columns(3)
        with c1:
            nama_p2 = st.text_input("Nama Pasien", value=hasil["nama"], key="p_nama_pdf")
            rm_p2 = st.text_input("No. RM", value=hasil["rm"], key="p_rm_pdf")
        with c2:
            kartu_p2 = st.text_input("No. Kartu BPJS", value=hasil["no_kartu"], key="p_kartu_pdf")
            sep_p2 = st.text_input("No. SEP", value=hasil["sep"], key="p_sep_pdf")
        with c3:
            tgl_r2 = st.date_input("Tanggal Resep Asli", value=hasil["tgl_resep"], key="p_tgl_pdf")
            dokter_p2 = st.text_input("Nama Dokter", value=hasil["dokter"], key="p_dok_pdf")
            iter_p2 = st.number_input("Jumlah Iter", min_value=0, value=2, key="p_iter_pdf")
            
        st.markdown("---")
        st.subheader("💊 Rincian Obat (PDF)")
        
        opsi_status = ["det orig", "det", "ne det", "det iter 1x", "det iter 2x", "det iter 3x"]
        if 'list_obat_pdf' not in st.session_state or st.session_state.get('last_file_obat_pdf') != file_upload.name:
            st.session_state['list_obat_pdf'] = list(hasil["list_obat"])
            st.session_state['last_file_obat_pdf'] = file_upload.name

        indices_to_remove2 = []
        for idx, item in enumerate(st.session_state['list_obat_pdf']):
            col_buble, col_aksi = st.columns([7, 3])
            with col_buble:
                st.markdown(f"""
                <div class="chat-bubble">
                    <div class="bubble-header">💊 R/ {item['nama']}</div>
                    <div class="bubble-body">📋 Aturan Pakai: <strong>{item['signa']}</strong> &nbsp;&nbsp;|&nbsp;&nbsp; 📦 Jumlah: <strong>{item['jumlah']}</strong></div>
                </div>
                """, unsafe_allow_html=True)
            with col_aksi:
                st.write("") 
                item['status'] = st.selectbox(f"Status:", opsi_status, index=opsi_status.index(item.get('status', 'det orig')), key=f"stat_p_{idx}")
                st.markdown('<div class="btn-delete">', unsafe_allow_html=True)
                if st.button("🗑️ Hapus", key=f"del_p_{idx}"): indices_to_remove2.append(idx)
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

        if indices_to_remove2:
            for i in sorted(indices_to_remove2, reverse=True): st.session_state['list_obat_pdf'].pop(i)
            st.rerun()
            
        st.markdown("---")
        if st.button("💾 Simpan Data PDF & Siapkan Cetak", key="btn_save_pdf"):
            teks_db = " | ".join([f"{o['nama']} ({o['signa']} {o['jumlah']}) [{o['status']}]" for o in st.session_state['list_obat_pdf']])
            simpan_data({
                "Nama Pasien": nama_p2, "No. RM": rm_p2, "Tanggal Resep Asli": tgl_r2.strftime("%Y-%m-%d"), 
                "Nama Dokter": dokter_p2, "No. Kartu": kartu_p2, "SEP": sep_p2, 
                "Jumlah Iter": iter_p2, "Daftar Obat": teks_db
            })
            st.session_state['data_cetak'] = {
                "nama": nama_p2, "rm": rm_p2, "tgl_resep": tgl_r2.strftime("%d %B %Y"), 
                "dokter": dokter_p2, "kartu": kartu_p2, "sep": sep_p2, "iter": iter_p2, 
                "obat_list": st.session_state['list_obat_pdf'], "tgl_copy": datetime.now().strftime("%d %B %Y")
            }
            st.session_state['show_success_tab2'] = True
            st.rerun()

# --- TAB 3: INPUT MANUAL ---
with tab3:
    if st.session_state.get('show_success_tab3'):
        st.success("✅ Sukses Disimpan (Manual)! Data ganda otomatis ditimpa.")
        st.session_state['show_success_tab3'] = False
        
    st.info("✍️ Input data secara manual jika diperlukan.")
    with st.form("form_manual", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            m_nama = st.text_input("Nama Pasien")
            m_rm = st.text_input("No. RM")
        with c2:
            m_kartu = st.text_input("No. Kartu BPJS")
            m_sep = st.text_input("No. SEP")
        with c3:
            m_tgl = st.date_input("Tanggal Resep Asli")
            m_dok = st.text_input("Nama Dokter")
            m_iter = st.number_input("Jumlah Iter", min_value=0)
        m_obat = st.text_area("Daftar Obat (Tiap baris tekan Enter):", height=150)
        
        if st.form_submit_button("💾 Simpan Data Resep (Manual)"):
            if m_nama and m_obat:
                simpan_data({"Nama Pasien": m_nama, "No. RM": m_rm, "Tanggal Resep Asli": m_tgl.strftime("%Y-%m-%d"), "Nama Dokter": m_dok, "No. Kartu": m_kartu, "SEP": m_sep, "Jumlah Iter": m_iter, "Daftar Obat": m_obat.replace('\n', ' | ')})
                st.session_state['show_success_tab3'] = True
                st.rerun()
            else:
                st.error("Nama dan Daftar Obat wajib diisi!")

# --- TAB 4: PUSAT CETAK ---
with tab4:
    if 'data_cetak' in st.session_state:
        d = st.session_state['data_cetak']
        
        st.subheader("📑 1. Cetak Copy Resep (A5)")
        html_rows_obat = ""
        for o in d['obat_list']:
            html_rows_obat += f"""
            <tr style="vertical-align: top;">
                <td style="padding: 6px 0; font-weight: bold; width: 5%;">R/</td>
                <td style="padding: 6px 0; width: 55%;">{o['nama']}</td>
                <td style="padding: 6px 0; text-align: center; width: 15%;">{o['signa']}</td>
                <td style="padding: 6px 0; text-align: center; width: 10%;">{o['jumlah']}</td>
                <td style="padding: 6px 0; text-align: right; font-style: italic; font-weight: bold; width: 15%;">-{o['status']}-</td>
            </tr>
            """
            
        html_a5 = f"""
        <!DOCTYPE html><html><head><style>
            @page {{ size: A5 portrait; margin: 10mm; }}
            body {{ background-color: #FFFFFF !important; color: #000000 !important; font-family: 'Arial', sans-serif; font-size: 12px; margin: 0; padding: 20px; }}
            .kop {{ text-align: center; font-weight: bold; }}
            .kop h2 {{ margin: 0; font-size: 15px; color: #000000; text-transform: uppercase; }}
            .kop p {{ margin: 2px 0; font-size: 11px; font-weight: normal; color: #000000; }}
            .line-thick {{ border-bottom: 2px solid #000; margin-top: 5px; margin-bottom: 10px; }}
            .line-thin {{ border-bottom: 1px solid #000; margin-top: 10px; margin-bottom: 10px; }}
            .title {{ text-align: center; font-weight: bold; font-size: 14px; text-decoration: underline; margin-bottom: 15px; color: #000000; }}
            .meta-table {{ width: 100%; font-size: 11px; margin-bottom: 15px; color: #000000; border-collapse: collapse; }}
            .meta-table td {{ padding: 3px 0; }}
            .obat-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 12px; color: #000000; }}
            .footer-box {{ margin-top: 40px; float: right; text-align: center; width: 200px; color: #000000; }}
            .pcc {{ font-weight: bold; margin-bottom: 50px; }}
            .bottom-text {{ clear: both; text-align: center; font-style: italic; font-size: 10px; color: #333333; margin-top: 40px; border-top: 1px solid #000; padding-top: 5px; }}
        </style></head><body>
            <div class="kop"><h2>RUMAH SAKIT ISLAM MASYITHOH</h2><p>Jl. A.Yani No 6-7 Bangil 67153</p><p>Telefarmasi (WA) 0343-741018</p></div>
            <div class="line-thick"></div><div class="title">SALINAN RESEP (COPY RESEP)</div>
            <table class="meta-table">
                <tr><td width="20%"><strong>Resep Dari</strong></td><td width="35%">: {d['dokter']}</td><td width="15%"><strong>No. RM</strong></td><td width="30%">: {d['rm']}</td></tr>
                <tr><td><strong>Tgl Resep Asli</strong></td><td>: {d['tgl_resep']}</td><td><strong>No. Kartu</strong></td><td>: {d['kartu']}</td></tr>
                <tr><td><strong>Nama Pasien</strong></td><td>: <strong style="font-size: 13px;">{d['nama']}</strong></td><td><strong>Status Iter</strong></td><td>: <strong>Iter {d['iter']}x</strong></td></tr>
            </table>
            <div class="line-thin"></div>
            <table class="obat-table">{html_rows_obat}</table>
            <div class="footer-box"><div class="pcc">p.c.c (Pro Copy Conform)</div><div>_________________________</div><div style="font-size: 10px; margin-top: 4px;">Apoteker Penanggung Jawab</div></div>
            <div class="bottom-text">Kesembuhan Dan Kesehatan Anda Adalah Do'a Yang Kami Panjatkan</div>
        </body></html>
        """
        
        c1, c2 = st.columns([8,2])
        with c1: components.html(html_a5, height=300, scrolling=True)
        with c2: 
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            js_print_a5 = f"""<script>function printA5() {{ var win = window.open('', '', 'height=700,width=900'); win.document.write(`{html_a5}`); win.document.close(); win.print(); }}</script>
            <button onclick="printA5()" style="background: linear-gradient(135deg, #10B981, #059669); color: white; border: none; padding: 15px; font-weight: 800; border-radius: 12px; cursor: pointer; width: 100%; box-shadow: 0 6px 0 #047857, 0 10px 20px rgba(16,185,129,0.3); transition: all 0.1s;" onmousedown="this.style.transform='translateY(6px)'; this.style.boxShadow='0 0 0 #047857, 0 5px 5px rgba(16,185,129,0.3)';" onmouseup="this.style.transform='translateY(0)'; this.style.boxShadow='0 6px 0 #047857, 0 10px 20px rgba(16,185,129,0.3)';">🖨️ PRINT COPY RESEP</button>"""
            components.html(js_print_a5, height=100)

        st.markdown("---")
        
        st.subheader("🏷️ 2. Cetak Etiket (Thermal 7x5 cm)")
        html_etiket_pages = ""
        for o in d['obat_list']:
            html_etiket_pages += f"""
            <div class="etiket-page">
                <div class="e-kop">RSI MASYITHOH BANGIL<br><span style="font-weight: normal; font-size: 7px;">Telefarmasi (WA) 0343-741018</span></div>
                <div class="e-line"></div>
                <table class="e-meta">
                    <tr><td width="30%">Nama</td><td>: <strong>{d['nama']}</strong></td></tr>
                    <tr><td width="30%">No. RM</td><td>: {d['rm']}</td></tr>
                    <tr><td>Tanggal</td><td>: {d['tgl_copy']}</td></tr>
                </table>
                <div class="e-signa">{o['signa']}</div>
                <div class="e-obat">Nama Obat: <strong>{o['nama']}</strong></div>
                <div class="e-footer">Semoga Lekas Sembuh</div>
            </div>
            """
            
        html_thermal = f"""
        <!DOCTYPE html><html><head><style>
            @page {{ size: 70mm 50mm; margin: 0; }}
            body {{ background-color: #FFFFFF !important; color: #000000 !important; font-family: 'Arial', sans-serif; margin: 0; padding: 0; }}
            .etiket-page {{ width: 66mm; height: 46mm; padding: 2mm; box-sizing: border-box; page-break-after: always; overflow: hidden; }}
            .e-kop {{ text-align: center; font-size: 9px; font-weight: bold; margin-bottom: 2px; }}
            .e-line {{ border-bottom: 1px solid #000; margin-bottom: 3px; }}
            .e-meta {{ width: 100%; font-size: 8px; margin-bottom: 5px; }}
            .e-meta td {{ padding: 1px 0; vertical-align: top; }}
            .e-signa {{ text-align: center; font-size: 11px; font-weight: bold; border-top: 1px solid #000; border-bottom: 1px solid #000; padding: 4px 0; margin-bottom: 5px; }}
            .e-obat {{ font-size: 8px; padding-left: 2px; }}
            .e-footer {{ text-align: center; font-size: 7px; font-style: italic; margin-top: 5px; border-top: 1px dashed #aaa; padding-top: 3px; }}
        </style></head><body>{html_etiket_pages}</body></html>
        """
        
        c3, c4 = st.columns([8,2])
        with c3: components.html(html_thermal, height=200, scrolling=True)
        with c4:
            st.markdown("<br><br>", unsafe_allow_html=True)
            js_print_thermal = f"""<script>function printThermal() {{ var win = window.open('', '', 'height=400,width=400'); win.document.write(`{html_thermal}`); win.document.close(); win.print(); }}</script>
            <button onclick="printThermal()" style="background: linear-gradient(135deg, #F59E0B, #D97706); color: white; border: none; padding: 15px; font-weight: 800; border-radius: 12px; cursor: pointer; width: 100%; box-shadow: 0 6px 0 #B45309, 0 10px 20px rgba(245,158,11,0.3); transition: all 0.1s;" onmousedown="this.style.transform='translateY(6px)'; this.style.boxShadow='0 0 0 #B45309, 0 5px 5px rgba(245,158,11,0.3)';" onmouseup="this.style.transform='translateY(0)'; this.style.boxShadow='0 6px 0 #B45309, 0 10px 20px rgba(245,158,11,0.3)';">🖨️ PRINT ETIKET THERMAL</button>"""
            components.html(js_print_thermal, height=100)

    else:
        st.info("⚠️ Kosong. Silakan proses data melalui tab Link iHospital atau Upload PDF terlebih dahulu.")

# --- TAB 5: LAPORAN & PENCARIAN ---
with tab5:
    if not df_data.empty:
        st.subheader("🔍 Cari Riwayat Pasien")
        pencarian = st.text_input("Masukkan Nama Pasien atau No. RM:")
        
        if pencarian:
            df_cari = df_data[df_data.apply(lambda row: row.astype(str).str.contains(pencarian, case=False).any(), axis=1)]
            if not df_cari.empty: st.dataframe(df_cari, use_container_width=True)
            else: st.warning("Data tidak ditemukan.")
            
        st.markdown("---")
        st.subheader("📊 Laporan Bulanan (Unduh Data)")
        
        df_data['Tanggal Input'] = pd.to_datetime(df_data['Tanggal Input'], errors='coerce')
        col_tgl1, col_tgl2 = st.columns(2)
        with col_tgl1: start_date = st.date_input("Dari Tanggal", datetime.now().date().replace(day=1))
        with col_tgl2: end_date = st.date_input("Sampai Tanggal", datetime.now().date())
        
        mask = (df_data['Tanggal Input'].dt.date >= start_date) & (df_data['Tanggal Input'].dt.date <= end_date)
        df_laporan = df_data.loc[mask].copy()
        
        st.write(f"Total data ditemukan: **{len(df_laporan)} resep**")
        st.dataframe(df_laporan, use_container_width=True, hide_index=True)
        
        if not df_laporan.empty:
            csv = df_laporan.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Unduh Laporan Rekap (CSV)", data=csv, file_name=f"Laporan_{start_date}_{end_date}.csv", mime="text/csv")
    else:
        st.info("Database masih kosong. Belum ada resep yang diinput.")