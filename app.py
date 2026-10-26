import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import fitz
import re
import streamlit.components.v1 as components
import json
import time

# ==========================================
# 0. PENGATURAN ZONA WAKTU (WIB - REALTIME)
# ==========================================
WIB = timezone(timedelta(hours=7))

def get_waktu_sekarang():
    return datetime.now(WIB)

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
    
    .status-box { padding: 15px; border-radius: 15px; margin-bottom: 20px; font-weight: 800; text-align: center; background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2); box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
    .status-success { border-left: 5px solid #10B981; }
    .status-warning { border-left: 5px solid #F59E0B; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. KONEKSI GOOGLE SHEETS & SISTEM DATABASE
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
        get_waktu_sekarang().strftime("%Y-%m-%d %H:%M:%S"), data_dict["Nama Pasien"], data_dict["No. RM"], data_dict["Tanggal Resep Asli"],
        data_dict["Nama Dokter"], data_dict["No. Kartu"], data_dict["SEP"], data_dict["Jumlah Iter"], data_dict["Daftar Obat"]
    ]
    
    if sheet: 
        try:
            records = sheet.get_all_records()
            for i, rec in enumerate(records):
                # Validasi menggunakan list kolom untuk menghindari KeyError
                keys = list(rec.keys())
                rm_key = keys[2] if len(keys) > 2 else next((k for k in keys if 'rm' in k.lower()), 'No. RM')
                tgl_key = keys[3] if len(keys) > 3 else next((k for k in keys if 'tanggal' in k.lower() and 'input' not in k.lower()), 'Tanggal Resep Asli')
                
                rm_record = str(rec.get(rm_key, "")).strip()
                if rm_record == str(data_dict["No. RM"]).strip() and \
                   str(rec.get(tgl_key, "")).strip() == str(data_dict["Tanggal Resep Asli"]).strip():
                    try: sheet.delete_rows(i + 2)
                    except AttributeError: sheet.delete_row(i + 2)
                    break 
        except: pass
        sheet.append_row(row_data)
    else: 
        st.session_state['db_lokal'] = [
            r for r in st.session_state['db_lokal'] 
            if not (str(r[2]).strip() == str(data_dict["No. RM"]).strip() and str(r[3]).strip() == str(data_dict["Tanggal Resep Asli"]).strip())
        ]
        st.session_state['db_lokal'].append(row_data)

def ambil_semua_data():
    if sheet: return pd.DataFrame(sheet.get_all_records())
    kolom = ["Tanggal Input", "Nama Pasien", "RM", "Tanggal Resep Asli", "Nama Dokter", "No. Kartu", "SEP", "Jumlah Iter", "Daftar Obat"]
    return pd.DataFrame(st.session_state['db_lokal'], columns=kolom)

# Ekstraktor Mutlak (Mencegah kolom bergeser)
def ext_val(row, col_names, index_fallback):
    for c in col_names:
        if c in row.index: return row[c]
    if index_fallback < len(row.index): return row.iloc[index_fallback]
    return ""

def parse_db_obat(db_string):
    obat_list = []
    if not db_string or pd.isna(db_string) or str(db_string).strip() == "": 
        return obat_list
        
    items = str(db_string).split(" | ")
    for item in items:
        if not item.strip(): continue
        
        nama, signa, jumlah, status_lama = item.strip(), "", "", "🟢 det orig"
        
        m_status = re.search(r'\[(.*?)\]$', nama)
        if m_status:
            status_lama = m_status.group(1).strip()
            nama = nama[:m_status.start()].strip()
            
        m_detail = re.search(r'\((.*?)\s+No\.\s*(.*?)\)$', nama, re.IGNORECASE)
        if m_detail:
            signa = m_detail.group(1).strip()
            jumlah = m_detail.group(2).strip()
            nama = nama[:m_detail.start()].strip()
        else:
            m_paren = re.search(r'\((.*?)\)$', nama)
            if m_paren:
                signa = m_paren.group(1).strip()
                nama = nama[:m_paren.start()].strip()

        status_baru = "🟢 det orig"
        sl = status_lama.lower()
        if "det orig" in sl: status_baru = "🔵 det iter 1x"
        elif "iter 1x" in sl: status_baru = "🟣 det iter 2x"
        elif "iter 2x" in sl: status_baru = "🟤 det iter 3x"
        elif "ne det" in sl: status_baru = "🔴 ne det"
        elif "det" in sl and "iter" not in sl: status_baru = "🔵 det iter 1x"
        else: status_baru = status_lama

        obat_list.append({"Nama Obat": nama, "Aturan Pakai": signa, "Jumlah": jumlah, "Status": status_baru, "Hapus": False})
        
    return obat_list

# ==========================================
# 3. FUNGSI PARSER KETAT (EKSTRAKSI TEKS CERDAS)
# ==========================================
def parse_teks_resep(teks_mentah):
    hasil = {"nama": "", "rm": "", "no_kartu": "", "sep": "", "tgl_resep": get_waktu_sekarang(), "dokter": "", "iter": 2, "list_obat": []}
    
    m_nama = re.search(r"Nama Lengkap[\s:]*([A-Za-z\'\.\s]+?)(?:Alergi|Tgl|No\.)", teks_mentah, re.IGNORECASE)
    if m_nama: hasil["nama"] = m_nama.group(1).replace(':', '').strip()
    
    m_rm = re.search(r"(?:No\.\s*RM|RM)[\s:]*([a-zA-Z0-9]+)", teks_mentah, re.IGNORECASE)
    if m_rm: hasil["rm"] = m_rm.group(1).strip()

    m_kartu = re.search(r"(\d{13})\s*/\s*([A-Za-z0-9]{15,25})", teks_mentah)
    if m_kartu:
        hasil["no_kartu"] = m_kartu.group(1).strip()
        hasil["sep"] = m_kartu.group(2).strip()

    m_tgl = re.search(r"Tanggal\s*:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", teks_mentah, re.IGNORECASE)
    if m_tgl:
        hari, bulan_str, tahun = int(m_tgl.group(1)), m_tgl.group(2).lower(), int(m_tgl.group(3))
        bulan_map = {'jan':1, 'feb':2, 'mar':3, 'apr':4, 'mei':5, 'jun':6, 'jul':7, 'agu':8, 'sep':9, 'okt':10, 'nov':11, 'des':12}
        try: hasil["tgl_resep"] = datetime(tahun, next((v for k, v in bulan_map.items() if bulan_str.startswith(k)), get_waktu_sekarang().month), hari)
        except: pass

    m_dok = re.search(r"(dr\.[^\n\r]+)", teks_mentah, re.IGNORECASE)
    if m_dok:
        dok_bersih = m_dok.group(1).split("TELAAH")[0].strip()
        hasil["dokter"] = dok_bersih
        
    m_iter = re.search(r"Iter\s+(\d+)", teks_mentah, re.IGNORECASE)
    if m_iter: hasil["iter"] = int(m_iter.group(1))

    blocks = teks_mentah.split("R /")[1:]
    for block in blocks:
        lines = [b.strip() for b in block.strip().split('\n') if b.strip()]
        if not lines: continue
        
        nama_obat = lines[0].replace('//', '').strip()
        jumlah, signa, waktu = "", "", ""
        
        m_jum_inline = re.search(r'Jumlah\s*(\d+)', nama_obat, re.IGNORECASE)
        if m_jum_inline: jumlah = m_jum_inline.group(1)
        nama_obat = re.sub(r'/?\s*Jumlah\s*\d*', '', nama_obat, flags=re.IGNORECASE).strip()
        
        for i, line in enumerate(lines):
            if "Jumlah" in line and not jumlah:
                m_jum = re.search(r'Jumlah\s*(\d+)', line, re.IGNORECASE)
                if m_jum: jumlah = m_jum.group(1)
                elif i + 1 < len(lines): jumlah = lines[i+1].strip()
                    
            if "x" in line.lower() and any(c.isdigit() for c in line) and "jumlah" not in line.lower():
                signa = line
                
            if line.lower() in ['pagi', 'siang', 'sore', 'malam', 'pc', 'ac', 'prn', 'pc prn', 'ac prn']:
                waktu = line
        
        if signa and waktu: signa = f"{signa} {waktu}"
        elif waktu and not signa: signa = waktu
            
        if nama_obat and "TELAAH" not in nama_obat.upper():
            hasil["list_obat"].append({"Nama Obat": nama_obat, "Aturan Pakai": signa, "Jumlah": jumlah, "Status": "🟢 det orig", "Hapus": False})
            
    return hasil

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
    
    col_tgl_input = df_data.columns[0] if not df_data.empty else None
    today_str = get_waktu_sekarang().strftime("%Y-%m-%d")
    total_hari_ini = len(df_data[df_data[col_tgl_input].astype(str).str.startswith(today_str)]) if not df_data.empty and col_tgl_input else 0
    
    st.metric(label="Resep Masuk Hari Ini", value=f"{total_hari_ini} Resep", delta="Aktif")
    st.markdown(f'<div class="status-box status-{"success" if sheet else "warning"}">{"✅" if sheet else "⚠️"} {connection_status}</div>', unsafe_allow_html=True)

opsi_status = ["🟢 det orig", "🟡 det", "🔴 ne det", "🔵 det iter 1x", "🟣 det iter 2x", "🟤 det iter 3x"]

# ==========================================
# 5. HALAMAN UTAMA (TABS)
# ==========================================
st.title("✨ Sistem Cerdas Copy Resep & Etiket")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Paste Teks", "📂 Upload PDF", "✍️ Manual", "🔄 Tarik Data Iter", "🖨️ Pusat Cetak", "🔍 Laporan Data"])

# --- TAB 1: PASTE TEKS ---
with tab1:
    if st.session_state.get('show_success_tab1'):
        st.success("✅ Sukses Disimpan! Buka Tab '🖨️ Pusat Cetak'.")
        st.session_state['show_success_tab1'] = False

    with st.form("form_paste_teks"):
        teks_input_user = st.text_area("📋 Paste Teks Halaman Resep di Sini:", height=150, placeholder="Tekan Ctrl+V di sini...")
        btn_proses = st.form_submit_button("🚀 Proses Data Resep")
    
    if btn_proses:
        if teks_input_user.strip():
            progress_text = "Memulai pemindaian... 0%"
            my_bar = st.progress(0, text=progress_text)
            
            for percent_complete in range(100):
                time.sleep(0.01) 
                if percent_complete == 30: progress_text = f"Menganalisis Identitas Pasien... {percent_complete}%"
                elif percent_complete == 60: progress_text = f"Mengekstrak Rincian Obat... {percent_complete}%"
                elif percent_complete == 90: progress_text = f"Memvalidasi Data... {percent_complete}%"
                my_bar.progress(percent_complete + 1, text=progress_text)
            my_bar.empty() 
            
            st.session_state['hasil_ekstrak_teks'] = parse_teks_resep(teks_input_user)
            st.session_state['df_obat_teks'] = pd.DataFrame(st.session_state['hasil_ekstrak_teks']["list_obat"])
        else:
            st.warning("⚠️ Kotak teks masih kosong!")

    if 'hasil_ekstrak_teks' in st.session_state and 'df_obat_teks' in st.session_state:
        hasil = st.session_state['hasil_ekstrak_teks']

        st.subheader("👤 Identitas Pasien")
        c1, c2, c3 = st.columns(3)
        with c1:
            nama_p = st.text_input("Nama Pasien", value=hasil["nama"], key="p_nama_teks")
            rm_p = st.text_input("No. RM", value=hasil["rm"], key="p_rm_teks")
        with c2:
            kartu_p = st.text_input("No. Kartu BPJS", value=hasil["no_kartu"], key="p_kartu_teks")
            sep_p = st.text_input("No. SEP", value=hasil["sep"], key="p_sep_teks")
        with c3:
            tgl_r = st.date_input("Tanggal Resep Asli", value=hasil["tgl_resep"], key="p_tgl_teks")
            dokter_p = st.text_input("Nama Dokter", value=hasil["dokter"], key="p_dok_teks")
            iter_p = st.number_input("Jumlah Iter", min_value=0, value=hasil["iter"], key="p_iter_teks")
            
        st.markdown("---")
        st.subheader("💊 Rincian Obat")
        
        if not st.session_state['df_obat_teks'].empty:
            edited_df_obat = st.data_editor(
                st.session_state['df_obat_teks'],
                column_config={"Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False), "Status": st.column_config.SelectboxColumn("Status", options=opsi_status)},
                disabled=["Nama Obat"], hide_index=True, use_container_width=True, key="editor_obat_teks" 
            )
            
            if st.button("🗑️ Hapus Obat Terpilih", key="del_tab1"):
                st.session_state['df_obat_teks'] = edited_df_obat[edited_df_obat['Hapus'] == False].copy()
                st.session_state['df_obat_teks']['Hapus'] = False 
                st.rerun()
                
            st.markdown("---")
            if st.button("💾 Simpan Data & Siapkan Cetak", key="btn_save_teks"):
                save_bar = st.progress(0, text="Menyiapkan data...")
                time.sleep(0.3)
                
                obat_siap_cetak = edited_df_obat[edited_df_obat['Hapus'] == False].rename(columns={"Nama Obat": "nama", "Aturan Pakai": "signa", "Jumlah": "jumlah", "Status": "status"}).to_dict('records')
                teks_db = " | ".join([f"{o['nama']} ({o['signa']} No. {o['jumlah']}) [{o['status']}]" for o in obat_siap_cetak])
                
                simpan_data({
                    "Nama Pasien": nama_p, "No. RM": rm_p, "Tanggal Resep Asli": tgl_r.strftime("%Y-%m-%d"), 
                    "Nama Dokter": dokter_p, "No. Kartu": kartu_p, "SEP": sep_p, 
                    "Jumlah Iter": iter_p, "Daftar Obat": teks_db
                })
                
                st.session_state['data_cetak'] = {
                    "nama": nama_p, "rm": rm_p, "tgl_resep": tgl_r.strftime("%d %B %Y"), "dokter": dokter_p, 
                    "kartu": kartu_p, "sep": sep_p, "iter": iter_p, "obat_list": obat_siap_cetak, 
                    "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")
                }
                
                save_bar.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar.empty()
                st.session_state['show_success_tab1'] = True
                st.rerun()
        else: st.warning("Daftar obat kosong.")

# --- TAB 2: UPLOAD PDF ---
with tab2:
    if st.session_state.get('show_success_tab2'):
        st.success("✅ Sukses Disimpan dari PDF! Buka Tab '🖨️ Pusat Cetak'.")
        st.session_state['show_success_tab2'] = False

    file_upload = st.file_uploader("📂 Unggah File PDF Resep", type=['pdf'], key="uploader_pdf")
    
    if file_upload:
        if 'hasil_ekstrak_pdf' not in st.session_state or st.session_state.get('last_file_pdf') != file_upload.name:
            st.session_state['hasil_ekstrak_pdf'] = ekstrak_data_pdf(file_upload)
            st.session_state['df_obat_pdf'] = pd.DataFrame(st.session_state['hasil_ekstrak_pdf']["list_obat"])
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
            iter_p2 = st.number_input("Jumlah Iter", min_value=0, value=hasil["iter"], key="p_iter_pdf")
            
        st.markdown("---")
        st.subheader("💊 Rincian Obat (PDF)")
        
        if not st.session_state['df_obat_pdf'].empty:
            edited_df_obat2 = st.data_editor(
                st.session_state['df_obat_pdf'],
                column_config={"Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False), "Status": st.column_config.SelectboxColumn("Status", options=opsi_status)},
                disabled=["Nama Obat"], hide_index=True, use_container_width=True, key="editor_obat_pdf"
            )
            
            if st.button("🗑️ Hapus Obat Terpilih (PDF)", key="del_tab2"):
                st.session_state['df_obat_pdf'] = edited_df_obat2[edited_df_obat2['Hapus'] == False].copy()
                st.session_state['df_obat_pdf']['Hapus'] = False
                st.rerun()
                
            st.markdown("---")
            if st.button("💾 Simpan Data PDF & Siapkan Cetak", key="btn_save_pdf"):
                save_bar2 = st.progress(0, text="Menyiapkan data PDF...")
                time.sleep(0.3)
                
                obat_siap_cetak2 = edited_df_obat2[edited_df_obat2['Hapus'] == False].rename(columns={"Nama Obat": "nama", "Aturan Pakai": "signa", "Jumlah": "jumlah", "Status": "status"}).to_dict('records')
                teks_db = " | ".join([f"{o['nama']} ({o['signa']} No. {o['jumlah']}) [{o['status']}]" for o in obat_siap_cetak2])
                
                simpan_data({
                    "Nama Pasien": nama_p2, "No. RM": rm_p2, "Tanggal Resep Asli": tgl_r2.strftime("%Y-%m-%d"), 
                    "Nama Dokter": dokter_p2, "No. Kartu": kartu_p2, "SEP": sep_p2, 
                    "Jumlah Iter": iter_p2, "Daftar Obat": teks_db
                })
                
                save_bar2.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar2.empty()
                
                st.session_state['data_cetak'] = {
                    "nama": nama_p2, "rm": rm_p2, "tgl_resep": tgl_r2.strftime("%d %B %Y"), "dokter": dokter_p2, 
                    "kartu": kartu_p2, "sep": sep_p2, "iter": iter_p2, "obat_list": obat_siap_cetak2, 
                    "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")
                }
                st.session_state['show_success_tab2'] = True
                st.rerun()
        else: st.warning("Daftar obat PDF kosong.")

# --- TAB 3: INPUT MANUAL ---
with tab3:
    if st.session_state.get('show_success_tab3'):
        st.success("✅ Sukses Disimpan (Manual)!")
        st.session_state['show_success_tab3'] = False
        
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
        
        btn_manual = st.form_submit_button("💾 Simpan Data Resep (Manual)")
        if btn_manual:
            save_bar3 = st.progress(0, text="Menyimpan data manual...")
            time.sleep(0.5)
            if m_nama and m_obat:
                simpan_data({"Nama Pasien": m_nama, "No. RM": m_rm, "Tanggal Resep Asli": m_tgl.strftime("%Y-%m-%d"), "Nama Dokter": m_dok, "No. Kartu": m_kartu, "SEP": m_sep, "Jumlah Iter": m_iter, "Daftar Obat": m_obat.replace('\n', ' | ')})
                save_bar3.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar3.empty()
                st.session_state['show_success_tab3'] = True
                st.rerun()

# --- TAB 4: TARIK DATA ITER ---
with tab4:
    st.info("💡 **Gunakan fitur ini untuk resep Iterasi (Refill).** Masukkan No. RM pasien, pilih resep sebelumnya, dan sistem akan otomatis menyiapkan etiket untuk hari ini & menaikkan status iter pada copy resep.")
    
    if df_data.empty: 
        st.warning("Database masih kosong.")
    else:
        rm_cari = st.text_input("🔍 Masukkan No. RM untuk mencari riwayat resep:", key="cari_rm_iter")
        if rm_cari:
            # Cari kolom RM secara absolut untuk filter (Index 2 atau nama)
            col_rm_db = "No. RM"
            for c in ['No. RM', 'RM', 'No RM']:
                if c in df_data.columns: col_rm_db = c; break
            if col_rm_db not in df_data.columns and len(df_data.columns) > 2: col_rm_db = df_data.columns[2]
                
            df_match = df_data[df_data[col_rm_db].astype(str).str.contains(rm_cari, case=False)]
            
            if not df_match.empty:
                opsi = []
                for i, r in df_match.iterrows():
                    t_tgl = ext_val(r, ['Tanggal Resep Asli', 'Tanggal', 'Tgl'], 3)
                    t_nama = ext_val(r, ['Nama Pasien', 'Nama Lengkap', 'Nama'], 1)
                    t_dok = ext_val(r, ['Nama Dokter', 'Dokter', 'dr'], 4)
                    opsi.append(f"{t_tgl} - {t_nama} (Dokter: {t_dok})")
                    
                pilihan_riwayat = st.selectbox("📂 Pilih Riwayat Resep Sebelumnya:", opsi)
                idx_terpilih = opsi.index(pilihan_riwayat)
                row_terpilih = df_match.iloc[idx_terpilih]
                
                if st.button("🔽 Tarik & Proses Data Iter Ini"):
                    # Ekstrak data menggunakan indeks mutlak (100% Mencegah Data Tertukar)
                    st.session_state['hasil_ekstrak_iter'] = {
                        "Nama Pasien": ext_val(row_terpilih, ['Nama Pasien', 'Nama Lengkap', 'Nama'], 1),
                        "No. RM": ext_val(row_terpilih, ['No. RM', 'RM'], 2),
                        "Tanggal Resep Asli": ext_val(row_terpilih, ['Tanggal Resep Asli', 'Tanggal', 'Tgl'], 3),
                        "Nama Dokter": ext_val(row_terpilih, ['Nama Dokter', 'Dokter'], 4),
                        "No. Kartu": ext_val(row_terpilih, ['No. Kartu', 'Kartu BPJS', 'Kartu'], 5),
                        "SEP": ext_val(row_terpilih, ['SEP', 'No. SEP'], 6),
                        "Jumlah Iter": ext_val(row_terpilih, ['Jumlah Iter', 'Iter'], 7),
                        "Daftar Obat": ext_val(row_terpilih, ['Daftar Obat', 'Obat', 'Rincian'], 8)
                    }
                    
                    db_obat_str = str(st.session_state['hasil_ekstrak_iter']['Daftar Obat'])
                    st.session_state['df_obat_iter'] = pd.DataFrame(parse_db_obat(db_obat_str))
            else:
                st.error("Data pasien tidak ditemukan.")
                
    if 'hasil_ekstrak_iter' in st.session_state and 'df_obat_iter' in st.session_state:
        if st.session_state.get('show_success_tab4'):
            st.success("✅ Iterasi Sukses Disimpan! Buka Tab '🖨️ Pusat Cetak'.")
            st.session_state['show_success_tab4'] = False
            
        hasil_it = st.session_state['hasil_ekstrak_iter']
        
        st.markdown("---")
        st.subheader("👤 Identitas Pasien (Iterasi)")
        c1, c2, c3 = st.columns(3)
        with c1:
            nama_p3 = st.text_input("Nama Pasien", value=hasil_it["Nama Pasien"], key="p_nama_it")
            rm_p3 = st.text_input("No. RM", value=hasil_it["No. RM"], key="p_rm_it")
        with c2:
            kartu_p3 = st.text_input("No. Kartu BPJS", value=hasil_it["No. Kartu"], key="p_kartu_it")
            sep_p3 = st.text_input("No. SEP", value=hasil_it["SEP"], key="p_sep_it")
        with c3:
            try:
                tgl_str = str(hasil_it["Tanggal Resep Asli"])
                if tgl_str == "": tgl_lama = get_waktu_sekarang().date()
                else: tgl_lama = datetime.strptime(tgl_str, "%Y-%m-%d").date()
            except:
                tgl_lama = get_waktu_sekarang().date()
                
            tgl_r3 = st.date_input("Tanggal Resep Asli", value=tgl_lama, key="p_tgl_it")
            dokter_p3 = st.text_input("Nama Dokter", value=hasil_it["Nama Dokter"], key="p_dok_it")
            
            try: iter_val = int(hasil_it["Jumlah Iter"])
            except: iter_val = 2
            iter_p3 = st.number_input("Jumlah Iter", min_value=0, value=iter_val, key="p_iter_it")
            
        st.subheader("💊 Rincian Obat (Status Otomatis Naik)")
        if not st.session_state['df_obat_iter'].empty:
            edited_df_obat3 = st.data_editor(
                st.session_state['df_obat_iter'],
                column_config={"Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False), "Status": st.column_config.SelectboxColumn("Status", options=opsi_status)},
                disabled=["Nama Obat"], hide_index=True, use_container_width=True, key="editor_obat_iter"
            )
            
            if st.button("🗑️ Hapus Obat Terpilih (Iter)", key="del_tab4"):
                st.session_state['df_obat_iter'] = edited_df_obat3[edited_df_obat3['Hapus'] == False].copy()
                st.session_state['df_obat_iter']['Hapus'] = False
                st.rerun()
                
            st.markdown("---")
            if st.button("💾 Simpan Data Iterasi & Siapkan Cetak", key="btn_save_iter"):
                save_bar4 = st.progress(0, text="Menyiapkan data iterasi...")
                time.sleep(0.3)
                
                obat_siap_cetak3 = edited_df_obat3[edited_df_obat3['Hapus'] == False].rename(columns={"Nama Obat": "nama", "Aturan Pakai": "signa", "Jumlah": "jumlah", "Status": "status"}).to_dict('records')
                teks_db = " | ".join([f"{o['nama']} ({o['signa']} No. {o['jumlah']}) [{o['status']}]" for o in obat_siap_cetak3])
                
                simpan_data({
                    "Nama Pasien": nama_p3, "No. RM": rm_p3, "Tanggal Resep Asli": tgl_r3.strftime("%Y-%m-%d"), 
                    "Nama Dokter": dokter_p3, "No. Kartu": kartu_p3, "SEP": sep_p3, 
                    "Jumlah Iter": iter_p3, "Daftar Obat": teks_db
                })
                
                save_bar4.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar4.empty()
                
                st.session_state['data_cetak'] = {
                    "nama": nama_p3, "rm": rm_p3, "tgl_resep": tgl_r3.strftime("%d %B %Y"), "dokter": dokter_p3, 
                    "kartu": kartu_p3, "sep": sep_p3, "iter": iter_p3, "obat_list": obat_siap_cetak3, 
                    "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")
                }
                st.session_state['show_success_tab4'] = True
                st.rerun()
        else: 
            st.warning("⚠️ Data obat kosong. Pastikan kolom Daftar Obat di database terisi dengan benar.")

# --- TAB 5: PUSAT CETAK ---
with tab5:
    if 'data_cetak' in st.session_state:
        d = st.session_state['data_cetak']
        
        st.subheader("📑 1. Cetak Copy Resep (A5)")
        html_rows_obat = ""
        for o in d['obat_list']:
            status_bersih = o['status'].split(" ", 1)[-1] if " " in o['status'] else o['status']
            html_rows_obat += f"""
            <tr style="vertical-align: top;">
                <td style="padding: 6px 0; font-weight: bold; width: 5%;">R/</td>
                <td style="padding: 6px 0; width: 55%;">{o['nama']}</td>
                <td style="padding: 6px 0; text-align: center; width: 15%;">{o['signa']}</td>
                <td style="padding: 6px 0; text-align: center; width: 10%;">{o['jumlah']}</td>
                <td style="padding: 6px 0; text-align: right; font-style: italic; font-weight: bold; width: 15%;">- {status_bersih} -</td>
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
            <div class="footer-box"><div class="pcc">p.c.c</div><div>_________________________</div></div>
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
        
        st.subheader("🏷️ 2. Cetak Etiket (Kustomisasi Sebelum Print)")
        st.info("💡 **Tips:** Anda bebas mengubah **Aturan Pakai**, **Nama Obat**, atau **Jumlah Obat** di tabel bawah ini. Perubahan ini **hanya untuk print etiket** dan tidak merusak data resep asli di database!")
        
        if 'df_etiket_edit' not in st.session_state or st.session_state.get('last_etiket_pasien') != d['nama'] + d['tgl_copy']:
            df_kustom = pd.DataFrame(d['obat_list'])
            df_kustom['Cetak'] = True 
            st.session_state['df_etiket_edit'] = df_kustom[['Cetak', 'nama', 'signa', 'jumlah']]
            st.session_state['last_etiket_pasien'] = d['nama'] + d['tgl_copy']
            
        edited_etiket = st.data_editor(
            st.session_state['df_etiket_edit'],
            column_config={
                "Cetak": st.column_config.CheckboxColumn("🖨️ Cetak?", default=True),
                "nama": "Nama Obat", "signa": "Aturan Pakai", "jumlah": "Jumlah"
            },
            hide_index=True, use_container_width=True, key="editor_etiket_thermal"
        )
        
        st.session_state['df_etiket_edit'] = edited_etiket
        
        tgl_split = d['tgl_copy'].split(" ")
        tgl_hari = tgl_split[0] if len(tgl_split) > 0 else ""
        tgl_bln_thn = f"{tgl_split[1].upper()}<br>{tgl_split[2]}" if len(tgl_split) > 2 else ""

        html_etiket_pages = ""
        for _, row in edited_etiket[edited_etiket['Cetak'] == True].iterrows():
            html_etiket_pages += f"""
            <div class="etiket-page">
                <div class="e-header">
                    <h3>RUMAH SAKIT ISLAM MASYITHOH</h3>
                    <p>Jl. A.Yani No 6-7 Bangil 67153<br><strong>Telefarmasi (WA) 0343-741018</strong></p>
                </div>
                <table class="e-meta">
                    <tr>
                        <td width="15%">Nama</td><td width="3%">:</td><td width="62%"><strong>{d['nama']}</strong></td>
                        <td width="20%" class="e-date-top">{tgl_hari}</td>
                    </tr>
                    <tr>
                        <td>No RM</td><td>:</td><td>{d['rm']}</td>
                        <td class="e-date-bottom">{tgl_bln_thn}</td>
                    </tr>
                </table>
                
                <div class="e-signa">{row['signa']}</div>
                
                <table class="e-obat-table">
                    <tr><td width="25%">Nama Obat</td><td width="3%">:</td><td width="72%">{row['nama']}</td></tr>
                    <tr><td>Jumlah</td><td>:</td><td>{row['jumlah']}</td></tr>
                </table>
                
                <div class="e-footer">Kesembuhan Dan Kesehatan Anda Adalah Do'a Yang Kami Panjatkan</div>
            </div>
            """
            
        html_thermal = f"""
        <!DOCTYPE html><html><head><style>
            @page {{ size: 70mm 50mm; margin: 0; }}
            body {{ background-color: #FFFFFF !important; color: #000000 !important; font-family: 'Arial', sans-serif; margin: 0; padding: 0; }}
            .etiket-page {{ width: 68mm; height: 48mm; padding: 1mm 2mm; box-sizing: border-box; page-break-after: always; overflow: hidden; position: relative; }}
            
            .e-header {{ text-align: center; border-bottom: 1.5px solid #000; padding-bottom: 2px; margin-bottom: 2px; }}
            .e-header h3 {{ margin: 0; font-size: 11px; font-weight: 900; color: #000; }}
            .e-header p {{ margin: 0; font-size: 9px; color: #333; line-height: 1.2; }}
            
            .e-meta {{ width: 100%; font-size: 10px; margin-bottom: 3px; border-collapse: collapse; }}
            .e-meta td {{ padding: 0; vertical-align: top; }}
            .e-date-top {{ text-align: right; font-size: 11px; padding-right: 2mm !important; }}
            .e-date-bottom {{ text-align: right; font-size: 9px; line-height: 1.1; padding-right: 2mm !important; text-transform: uppercase; }}
            
            .e-signa {{ text-align: center; font-size: 13px; font-weight: 900; border-top: 1.5px solid #000; border-bottom: 1.5px solid #000; padding: 3px 0; margin: 3px 0; text-transform: uppercase; }}
            
            .e-obat-table {{ width: 100%; font-size: 10px; border-collapse: collapse; }}
            .e-obat-table td {{ vertical-align: top; padding: 1px 0; }}
            
            .e-footer {{ text-align: center; font-size: 7px; font-weight: bold; color: #777; border-top: 1px solid #000; padding-top: 2px; position: absolute; bottom: 2mm; width: 64mm; }}
        </style></head><body>{html_etiket_pages}</body></html>
        """
        
        c3, c4 = st.columns([8,2])
        with c3: components.html(html_thermal, height=300, scrolling=True)
        with c4:
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            js_print_thermal = f"""<script>function printThermal() {{ var win = window.open('', '', 'height=400,width=400'); win.document.write(`{html_thermal}`); win.document.close(); win.print(); }}</script>
            <button onclick="printThermal()" style="background: linear-gradient(135deg, #F59E0B, #D97706); color: white; border: none; padding: 15px; font-weight: 800; border-radius: 12px; cursor: pointer; width: 100%; box-shadow: 0 6px 0 #B45309, 0 10px 20px rgba(245,158,11,0.3); transition: all 0.1s;" onmousedown="this.style.transform='translateY(6px)'; this.style.boxShadow='0 0 0 #B45309, 0 5px 5px rgba(245,158,11,0.3)';" onmouseup="this.style.transform='translateY(0)'; this.style.boxShadow='0 6px 0 #B45309, 0 10px 20px rgba(245,158,11,0.3)';">🖨️ PRINT ETIKET THERMAL</button>"""
            components.html(js_print_thermal, height=100)

    else:
        st.info("⚠️ Kosong. Silakan proses data terlebih dahulu.")

# --- TAB 6: LAPORAN & PENCARIAN (DENGAN FITUR HAPUS) ---
with tab6:
    if not df_data.empty:
        st.subheader("🔍 Cari Riwayat Pasien")
        pencarian = st.text_input("Masukkan Nama Pasien atau No. RM:")
        
        if pencarian:
            try:
                df_cari = df_data[df_data.apply(lambda row: row.astype(str).str.contains(pencarian, case=False).any(), axis=1)]
                if not df_cari.empty: st.dataframe(df_cari, use_container_width=True)
                else: st.warning("Data tidak ditemukan.")
            except: pass
            
        st.markdown("---")
        st.subheader("📊 Laporan Bulanan (Unduh & Kelola Data)")
        
        col_tgl_input = df_data.columns[0]
        for c in ['Tanggal Input', 'Tgl Input']:
            if c in df_data.columns: col_tgl_input = c; break
            
        df_data[col_tgl_input] = pd.to_datetime(df_data[col_tgl_input], errors='coerce')
        
        col_tgl1, col_tgl2 = st.columns(2)
        with col_tgl1: start_date = st.date_input("Dari Tanggal", get_waktu_sekarang().date().replace(day=1))
        with col_tgl2: end_date = st.date_input("Sampai Tanggal", get_waktu_sekarang().date())
        
        mask = (df_data[col_tgl_input].dt.date >= start_date) & (df_data[col_tgl_input].dt.date <= end_date)
        df_laporan = df_data.loc[mask].copy()
        
        st.write(f"Total data ditemukan: **{len(df_laporan)} resep**")
        
        if not df_laporan.empty:
            df_laporan.insert(0, 'Hapus', False)
            
            edited_df_laporan = st.data_editor(
                df_laporan,
                column_config={"Hapus": st.column_config.CheckboxColumn("Pilih Hapus", default=False)},
                disabled=df_laporan.columns.drop('Hapus'),
                hide_index=True,
                use_container_width=True,
                key="editor_laporan_data"
            )
            
            baris_terpilih = edited_df_laporan[edited_df_laporan['Hapus'] == True]
            
            if not baris_terpilih.empty:
                if st.button("🗑️ Hapus Data Terpilih", type="primary"):
                    del_bar = st.progress(0, text="Menghapus data dari server...")
                    time.sleep(0.3)
                    
                    col_rm_db = df_data.columns[2]
                    for c in ['No. RM', 'RM']:
                        if c in df_data.columns: col_rm_db = c; break
                    
                    if sheet:
                        all_records = sheet.get_all_records()
                        for i in range(len(all_records) - 1, -1, -1):
                            rec = all_records[i]
                            
                            keys = list(rec.keys())
                            rec_rm_key = keys[2] if len(keys) > 2 else next((k for k in keys if 'rm' in k.lower()), col_rm_db)
                            rec_tgl_key = keys[0] if len(keys) > 0 else next((k for k in keys if 'tanggal' in k.lower() and 'input' in k.lower()), col_tgl_input)
                            
                            for _, row_del in baris_terpilih.iterrows():
                                rm_del = str(row_del.get(col_rm_db, ''))
                                rm_rec = str(rec.get(rec_rm_key, ''))
                                tgl_del = str(row_del.get(col_tgl_input, ''))
                                tgl_rec = str(rec.get(rec_tgl_key, ''))
                                
                                if tgl_rec == tgl_del and rm_rec == rm_del:
                                    try: sheet.delete_rows(i + 2)
                                    except AttributeError: sheet.delete_row(i + 2)
                                    break
                    else:
                        st.session_state['db_lokal'] = [
                            r for r in st.session_state['db_lokal']
                            if not any(
                                (str(r[0]) == str(row_del.get(col_tgl_input, '')) and 
                                 str(r[2]) == str(row_del.get(col_rm_db, ''))) 
                                for _, row_del in baris_terpilih.iterrows()
                            )
                        ]
                    
                    del_bar.progress(100, text="Selesai menghapus!")
                    time.sleep(0.5)
                    del_bar.empty()
                    st.rerun()

            csv = df_laporan.drop(columns=['Hapus']).to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Unduh Laporan Rekap (CSV)", data=csv, file_name=f"Laporan_{start_date}_{end_date}.csv", mime="text/csv")
    else:
        st.info("Database masih kosong. Belum ada resep yang diinput.")