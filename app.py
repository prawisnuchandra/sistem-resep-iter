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

# ==========================================
# 1. KONFIGURASI UI/UX
# ==========================================
st.set_page_config(page_title="Copy Resep ITER", page_icon="💊", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1, h2, h3 { color: #1E293B; font-family: 'Inter', sans-serif; }
    .stButton>button { background-color: #2563EB; color: white; border-radius: 8px; padding: 10px 24px; font-weight: 600; border: none; width: 100%; transition: 0.2s; }
    .stButton>button:hover { background-color: #1D4ED8; box-shadow: 0 4px 12px rgba(37,99,235,0.2); }
    .btn-delete>button { background-color: #EF4444 !important; color: white !important; padding: 6px 12px !important; border-radius: 6px !important; margin-top: 25px !important; }
    .btn-delete>button:hover { background-color: #DC2626 !important; }
    .status-box { padding: 15px; border-radius: 8px; margin-bottom: 20px; font-weight: 600; text-align: center; }
    .status-success { background-color: #D1FAE5; color: #065F46; border: 1px solid #34D399; }
    .status-warning { background-color: #FEF3C7; color: #92400E; border: 1px solid #FBBF24; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. KONEKSI GOOGLE SHEETS (MODE SERVER & LOKAL)
# ==========================================
def get_gsheets_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Deteksi jika aplikasi berjalan di server Streamlit Cloud
        if "google_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["google_credentials"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        # Deteksi jika berjalan di laptop lokal
        elif os.path.exists("credentials.json"):
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        else:
            return None, "Mode Lokal Berjalan (Offline)"
        
        client = gspread.authorize(creds)
        return client.open("Data Copy Resep Iter").sheet1, "Tersinkronisasi ke Google Sheets"
    except Exception as e:
        return None, f"Gagal terhubung: {e}"

sheet, connection_status = get_gsheets_connection()

if 'db_lokal' not in st.session_state:
    st.session_state['db_lokal'] = []

def simpan_data(data_dict):
    row_data = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_dict["Nama Pasien"], data_dict["Tanggal Resep Asli"],
        data_dict["Nama Dokter"], data_dict["No. Kartu"], 
        data_dict["SEP"], data_dict["Jumlah Iter"], data_dict["Daftar Obat"]
    ]
    if sheet: sheet.append_row(row_data)
    else: st.session_state['db_lokal'].append(row_data)

def ambil_semua_data():
    if sheet: return pd.DataFrame(sheet.get_all_records())
    kolom = ["Tanggal Input", "Nama Pasien", "Tanggal Resep Asli", "Nama Dokter", "No. Kartu", "SEP", "Jumlah Iter", "Daftar Obat"]
    return pd.DataFrame(st.session_state['db_lokal'], columns=kolom)

# ==========================================
# 3. FUNGSI EKSTRAKSI PDF 
# ==========================================
def ekstrak_data_pdf(file_pdf):
    doc = fitz.open(stream=file_pdf.read(), filetype="pdf")
    teks_mentah = ""
    for page in doc: teks_mentah += page.get_text()
    
    hasil = {"nama": "", "no_kartu": "", "sep": "", "tgl_resep": datetime.now(), "dokter": "", "list_obat": []}
    
    m_nama = re.search(r"Nama\s+Lengkap[\s:]*\n?\s*:?\s*\n?\s*([A-Za-z\s\'\.]+)", teks_mentah, re.IGNORECASE)
    if m_nama:
        baris_nama = [b.strip() for b in m_nama.group(1).split('\n') if b.strip() and b.strip() != ':']
        if baris_nama: hasil["nama"] = baris_nama[0]

    m_kartu = re.search(r"(\d{13})\s*/\s*([A-Za-z0-9]{15,25})", teks_mentah)
    if m_kartu:
        hasil["no_kartu"] = m_kartu.group(1).strip()
        hasil["sep"] = m_kartu.group(2).strip()
    else:
        m_kartu_alt = re.search(r"Kartu/SEP[\s:]*\n?\s*:?\s*\n?\s*([\d]+)\s*/\s*([A-Za-z0-9]+)", teks_mentah, re.IGNORECASE)
        if m_kartu_alt:
            hasil["no_kartu"] = m_kartu_alt.group(1).strip()
            hasil["sep"] = m_kartu_alt.group(2).strip()

    m_tgl = re.search(r"Tanggal[\s:]*\n?\s*:?\s*\n?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", teks_mentah, re.IGNORECASE)
    if m_tgl:
        hari, bulan_str, tahun = int(m_tgl.group(1)), m_tgl.group(2).lower(), int(m_tgl.group(3))
        bulan_map = {'jan':1, 'feb':2, 'mar':3, 'apr':4, 'mei':5, 'jun':6, 'jul':7, 'agu':8, 'sep':9, 'okt':10, 'nov':11, 'des':12}
        bulan = next((v for k, v in bulan_map.items() if bulan_str.startswith(k)), datetime.now().month)
        try: hasil["tgl_resep"] = datetime(tahun, bulan, hari)
        except: pass

    m_dok = re.search(r"\(?\s*(dr\.\s*[A-Za-z\.\s\,]+(?:\,\s*[A-Za-z\.\s]+)*)\s*\)?", teks_mentah, re.IGNORECASE)
    if m_dok: hasil["dokter"] = m_dok.group(1).strip()
    
    kata_terlarang = ['TELAAH', 'Tepat', 'Dupikasi', 'Interaksi', 'Kontraindikasi', 'Klinis', 'Farmasetis', 'Petugas', 'Jam', 'Tanggal', 'Identitas', 'Nama']
    bagian_r = teks_mentah.split('R/')
    
    for bagian in bagian_r[1:]:
        baris = [b.strip() for b in bagian.strip().split('\n') if b.strip()]
        if not baris: continue
        nama_obat = baris[0].replace('//', '').strip()
        jumlah, signa = "", ""
        for b in baris[1:]:
            if any(terlarang.lower() in b.lower() for terlarang in kata_terlarang): break 
            if b.startswith('No.'): jumlah = b
            elif 'x' in b.lower() and any(c.isdigit() for c in b): signa = b
        if nama_obat and not any(t.lower() in nama_obat.lower() for t in kata_terlarang):
            hasil["list_obat"].append({"nama": nama_obat, "signa": signa, "jumlah": jumlah, "status": "det orig"})
            
    return hasil

# ==========================================
# 4. SIDEBAR & GRAFIK
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=60)
    st.title("Dashboard")
    
    df_data = ambil_semua_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    total_hari_ini = len(df_data[df_data['Tanggal Input'].astype(str).str.startswith(today_str)]) if not df_data.empty and "Tanggal Input" in df_data.columns else 0
    
    st.metric(label="Masuk Hari Ini", value=f"{total_hari_ini} Resep")
    st.markdown(f'<div class="status-box status-{"success" if sheet else "warning"}">{"✅" if sheet else "⚠️"} {connection_status}</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("### 📈 Tren 7 Hari Terakhir")
    
    last_7_days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    df_chart = pd.DataFrame({"Tanggal": last_7_days, "Jumlah Resep": 0}).set_index("Tanggal")
    
    if not df_data.empty and "Tanggal Input" in df_data.columns:
        df_data['Tgl_Only'] = df_data['Tanggal Input'].str[:10]
        counts = df_data['Tgl_Only'].value_counts()
        for date, count in counts.items():
            if date in df_chart.index:
                df_chart.at[date, "Jumlah Resep"] = count
                
    st.bar_chart(df_chart, use_container_width=True, color="#2563EB")

# ==========================================
# 5. HALAMAN UTAMA
# ==========================================
st.title("💊 Sistem Cetak Copy Resep ITER")

tab1, tab2, tab3, tab4 = st.tabs(["📄 Upload & Proses", "✍️ Input Manual", "🖨️ Cetak A5", "🗃️ Database"])

with tab1:
    st.info("💡 **Langkah 1:** Unggah PDF Resep. **Langkah 2:** Sesuaikan Status/Hapus Obat. **Langkah 3:** Simpan & Cetak.")
    file_upload = st.file_uploader("Unggah File PDF dari Sistem RS", type=['pdf'])
    
    if file_upload:
        if 'hasil_ekstrak' not in st.session_state or st.session_state.get('last_file') != file_upload.name:
            st.session_state['hasil_ekstrak'] = ekstrak_data_pdf(file_upload)
            st.session_state['last_file'] = file_upload.name
        
        hasil = st.session_state['hasil_ekstrak']
        
        with st.container():
            st.subheader("Data Identitas")
            c1, c2 = st.columns(2)
            with c1:
                nama_p = st.text_input("Nama Pasien", value=hasil["nama"])
                tgl_r = st.date_input("Tanggal Resep Asli", value=hasil["tgl_resep"])
                dokter_p = st.text_input("Nama Dokter", value=hasil["dokter"])
            with c2:
                kartu_p = st.text_input("No. Kartu", value=hasil["no_kartu"])
                sep_p = st.text_input("No. SEP", value=hasil["sep"])
                iter_p = st.number_input("Jumlah Iter (Sesuai Resep Asli)", min_value=0, value=2)
            
        st.markdown("---")
        st.subheader("💊 Daftar Obat & Status Penyerahan")
        
        opsi_status = ["det orig", "det", "ne det", "det iter 1x", "det iter 2x", "det iter 3x"]
        
        if 'list_obat_aktif' not in st.session_state or st.session_state.get('last_file_obat') != file_upload.name:
            st.session_state['list_obat_aktif'] = list(hasil["list_obat"])
            st.session_state['last_file_obat'] = file_upload.name

        obat_final_list = []
        indices_to_remove = []

        for idx, item in enumerate(st.session_state['list_obat_aktif']):
            col_nama, col_status, col_hapus = st.columns([7, 3, 1])
            with col_nama:
                st.markdown(f"<div style='padding-top: 8px; font-size: 15px;'><strong>R/</strong> {item['nama']} ({item['signa']} - {item['jumlah']})</div>", unsafe_allow_html=True)
            with col_status:
                selected_status = st.selectbox(f"Status #{idx}", opsi_status, index=opsi_status.index(item.get('status', 'det orig')), key=f"stat_{idx}", label_visibility="collapsed")
                item['status'] = selected_status
            with col_hapus:
                st.markdown('<div class="btn-delete">', unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{idx}"): indices_to_remove.append(idx)
                st.markdown('</div>', unsafe_allow_html=True)
            obat_final_list.append(item)

        if indices_to_remove:
            for i in sorted(indices_to_remove, reverse=True): st.session_state['list_obat_aktif'].pop(i)
            st.rerun()
            
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Simpan Data & Siapkan Cetak Copy Resep A5"):
            teks_db = " | ".join([f"{o['nama']} ({o['signa']} {o['jumlah']}) [{o['status']}]" for o in st.session_state['list_obat_aktif']])
            simpan_data({"Nama Pasien": nama_p, "Tanggal Resep Asli": tgl_r.strftime("%Y-%m-%d"), "Nama Dokter": dokter_p, "No. Kartu": kartu_p, "SEP": sep_p, "Jumlah Iter": iter_p, "Daftar Obat": teks_db})
            
            st.session_state['data_cetak'] = {
                "nama": nama_p, "tgl_resep": tgl_r.strftime("%d %B %Y"), "dokter": dokter_p, "kartu": kartu_p, "sep": sep_p,
                "iter": iter_p, "obat_list": st.session_state['list_obat_aktif'], "tgl_copy": datetime.now().strftime("%d %B %Y")
            }
            st.success("✅ Berhasil disimpan! Silakan buka Tab '🖨️ Cetak A5'.")

with tab2:
    with st.form("form_manual", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            m_nama = st.text_input("Nama Pasien")
            m_tgl = st.date_input("Tanggal Resep Asli")
            m_dok = st.text_input("Nama Dokter")
            m_iter = st.number_input("Jumlah Iter", min_value=0)
        with c2:
            m_kartu = st.text_input("No. Kartu (BPJS)")
            m_sep = st.text_input("No. SEP")
        m_obat = st.text_area("Daftar Obat (Tiap baris tekan Enter):", height=150)
        if st.form_submit_button("Simpan Data Resep") and m_nama and m_obat:
            simpan_data({"Nama Pasien": m_nama, "Tanggal Resep Asli": m_tgl.strftime("%Y-%m-%d"), "Nama Dokter": m_dok, "No. Kartu": m_kartu, "SEP": m_sep, "Jumlah Iter": m_iter, "Daftar Obat": m_obat.replace('\n', ' | ')})
            st.success("✅ Tersimpan!")
            st.rerun()

with tab3:
    if 'data_cetak' in st.session_state:
        d = st.session_state['data_cetak']
        
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
        <!DOCTYPE html>
        <html>
        <head>
            <style>
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
            </style>
        </head>
        <body>
            <div class="kop">
                <h2>RUMAH SAKIT ISLAM MASYITHOH</h2>
                <p>Jl. A.Yani No 6-7 Bangil 67153</p>
                <p>Telefarmasi (WA) 0343-741018</p>
            </div>
            <div class="line-thick"></div>
            <div class="title">SALINAN RESEP (COPY RESEP)</div>
            <table class="meta-table">
                <tr><td width="20%"><strong>Resep Dari</strong></td><td width="35%">: {d['dokter']}</td><td width="15%"><strong>No. Kartu</strong></td><td width="30%">: {d['kartu']}</td></tr>
                <tr><td><strong>Tgl Resep Asli</strong></td><td>: {d['tgl_resep']}</td><td><strong>No. SEP</strong></td><td>: {d['sep']}</td></tr>
                <tr><td><strong>Nama Pasien</strong></td><td>: <strong style="font-size: 13px;">{d['nama']}</strong></td><td><strong>Status Iter</strong></td><td>: <strong>Iter {d['iter']}x</strong></td></tr>
            </table>
            <div class="line-thin"></div>
            <table class="obat-table">{html_rows_obat}</table>
            <div class="footer-box">
                <div class="pcc">p.c.c (Pro Copy Conform)</div>
                <div>_________________________</div>
                <div style="font-size: 10px; margin-top: 4px;">Apoteker Penanggung Jawab</div>
            </div>
            <div class="bottom-text">Kesembuhan Dan Kesehatan Anda Adalah Do'a Yang Kami Panjatkan</div>
        </body>
        </html>
        """
        
        components.html(html_a5, height=520, scrolling=True)
        js_print = f"""
        <script>
        function printDiv() {{ var win = window.open('', '', 'height=700,width=900'); win.document.write(`{html_a5}`); win.document.close(); win.print(); }}
        </script>
        <button onclick="printDiv()" style="background-color: #059669; color: white; border: none; padding: 12px 24px; font-weight: bold; border-radius: 8px; cursor: pointer; width: 100%;">🖨️ Klik Di Sini Untuk Print Kertas A5</button>
        """
        components.html(js_print, height=60)
    else:
        st.info("⚠️ Selesaikan unggah PDF dan klik Simpan Data di Tab 1 terlebih dahulu.")

with tab4:
    if not df_data.empty: st.dataframe(df_data, use_container_width=True, hide_index=True)
    else: st.info("Database kosong.")