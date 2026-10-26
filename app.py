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
                rm_record = str(rec.get("No. RM", rec.get("RM", ""))).strip()
                if rm_record == str(data_dict["No. RM"]).strip() and \
                   str(rec.get("Tanggal Resep Asli", "")).strip() == str(data_dict["Tanggal Resep Asli"]).strip():
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
        
        for i, line in enumerate(lines):
            if "Jumlah" in line and i + 1 < len(lines):
                jumlah = lines[i+1].strip()
            if "x" in line.lower() and any(c.isdigit() for c in line):
                signa = line
            if line.lower() in ['pagi', 'siang', 'sore', 'malam', 'pc', 'ac', 'prn', 'pc prn', 'ac prn']:
                waktu = line
        
        if signa and waktu: signa = f"{signa} {waktu}"
        elif waktu and not signa: signa = waktu
            
        if nama_obat and "TELAAH" not in nama_obat.upper():
            # Status bawaan diubah menjadi versi Emoji Warna
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
    today_str = get_waktu_sekarang().strftime("%Y-%m-%d")
    total_hari_ini = len(df_data[df_data['Tanggal Input'].astype(str).str.startswith(today_str)]) if not df_data.empty and "Tanggal Input" in df_data.columns else 0
    
    st.metric(label="Resep Masuk Hari Ini", value=f"{total_hari_ini} Resep", delta="Aktif")
    st.markdown(f'<div class="status-box status-{"success" if sheet else "warning"}">{"✅" if sheet else "⚠️"} {connection_status}</div>', unsafe_allow_html=True)

# ==========================================
# 5. HALAMAN UTAMA (TABS)
# ==========================================
st.title("✨ Sistem Cerdas Copy Resep & Etiket")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Paste Teks Resep", "📂 Upload PDF", "✍️ Input Manual", "🖨️ Pusat Cetak", "🔍 Laporan Data"])

# --- TAB 1: PASTE TEKS ---
with tab1:
    if st.session_state.get('show_success_tab1'):
        st.success("✅ Sukses Disimpan! Data ganda otomatis ditimpa. Buka Tab '🖨️ Pusat Cetak'.")
        st.session_state['show_success_tab1'] = False

    st.info("💡 **Petunjuk:** Buka resep di web iHospital, tekan `Ctrl+A` lalu `Ctrl+C`. Setelah itu, paste (`Ctrl+V`) teksnya di kotak bawah ini lalu tekan tombol Proses.")
    
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
            st.warning("⚠️ Kotak teks masih kosong, silakan paste teks resep terlebih dahulu!")

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
        
        # Opsi Warna Dropdown
        opsi_status = ["🟢 det orig", "🟡 det", "🔴 ne det", "🔵 det iter 1x", "🟣 det iter 2x", "🟤 det iter 3x"]
        
        if not st.session_state['df_obat_teks'].empty:
            # Penambahan 'key' krusial agar checkbox tidak bug saat diklik
            edited_df_obat = st.data_editor(
                st.session_state['df_obat_teks'],
                column_config={
                    "Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False),
                    "Status": st.column_config.SelectboxColumn("Status", options=opsi_status)
                },
                disabled=["Nama Obat", "Aturan Pakai", "Jumlah"],
                hide_index=True,
                use_container_width=True,
                key="editor_obat_teks" 
            )
            
            if st.button("🗑️ Hapus Obat Terpilih"):
                # Simpan ulang state tanpa baris yang dicentang
                st.session_state['df_obat_teks'] = edited_df_obat[edited_df_obat['Hapus'] == False].copy()
                st.session_state['df_obat_teks']['Hapus'] = False 
                st.rerun()
                
            st.markdown("---")
            if st.button("💾 Simpan Data & Siapkan Cetak", key="btn_save_teks"):
                # Animasi Progress Bar untuk Simpan Data
                save_bar = st.progress(0, text="Menyiapkan data...")
                time.sleep(0.3)
                save_bar.progress(40, text="Menghubungkan ke Database...")
                
                obat_siap_cetak = edited_df_obat[edited_df_obat['Hapus'] == False].rename(columns={"Nama Obat": "nama", "Aturan Pakai": "signa", "Jumlah": "jumlah", "Status": "status"}).to_dict('records')
                
                teks_db = " | ".join([f"{o['nama']} ({o['signa']} No. {o['jumlah']}) [{o['status']}]" for o in obat_siap_cetak])
                
                simpan_data({
                    "Nama Pasien": nama_p, "No. RM": rm_p, "Tanggal Resep Asli": tgl_r.strftime("%Y-%m-%d"), 
                    "Nama Dokter": dokter_p, "No. Kartu": kartu_p, "SEP": sep_p, 
                    "Jumlah Iter": iter_p, "Daftar Obat": teks_db
                })
                
                save_bar.progress(80, text="Membuat format cetak...")
                time.sleep(0.3)
                
                st.session_state['data_cetak'] = {
                    "nama": nama_p, "rm": rm_p, "tgl_resep": tgl_r.strftime("%d %B %Y"), 
                    "dokter": dokter_p, "kartu": kartu_p, "sep": sep_p, "iter": iter_p, 
                    "obat_list": obat_siap_cetak, "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")
                }
                
                save_bar.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar.empty()
                st.session_state['show_success_tab1'] = True
                st.rerun()
        else:
            st.warning("Daftar obat kosong.")

# --- TAB 2: UPLOAD PDF ---
with tab2:
    if st.session_state.get('show_success_tab2'):
        st.success("✅ Sukses Disimpan dari PDF! Buka Tab '🖨️ Pusat Cetak'.")
        st.session_state['show_success_tab2'] = False

    file_upload = st.file_uploader("📂 Unggah File PDF Resep", type=['pdf'], key="uploader_pdf")
    
    if file_upload:
        if 'hasil_ekstrak_pdf' not in st.session_state or st.session_state.get('last_file_pdf') != file_upload.name:
            progress_text_pdf = "Membaca file PDF... 0%"
            my_bar2 = st.progress(0, text=progress_text_pdf)
            for i in range(100):
                time.sleep(0.01)
                my_bar2.progress(i + 1, text=f"Mengekstrak teks dokumen... {i+1}%")
            my_bar2.empty()
            
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
        
        opsi_status = ["🟢 det orig", "🟡 det", "🔴 ne det", "🔵 det iter 1x", "🟣 det iter 2x", "🟤 det iter 3x"]

        if not st.session_state['df_obat_pdf'].empty:
            edited_df_obat2 = st.data_editor(
                st.session_state['df_obat_pdf'],
                column_config={
                    "Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False),
                    "Status": st.column_config.SelectboxColumn("Status", options=opsi_status)
                },
                disabled=["Nama Obat", "Aturan Pakai", "Jumlah"],
                hide_index=True,
                use_container_width=True,
                key="editor_obat_pdf"
            )
            
            if st.button("🗑️ Hapus Obat Terpilih (PDF)"):
                st.session_state['df_obat_pdf'] = edited_df_obat2[edited_df_obat2['Hapus'] == False].copy()
                st.session_state['df_obat_pdf']['Hapus'] = False
                st.rerun()
                
            st.markdown("---")
            if st.button("💾 Simpan Data PDF & Siapkan Cetak", key="btn_save_pdf"):
                save_bar2 = st.progress(0, text="Menyiapkan data PDF...")
                time.sleep(0.3)
                save_bar2.progress(50, text="Menyimpan ke Database...")
                
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
                    "nama": nama_p2, "rm": rm_p2, "tgl_resep": tgl_r2.strftime("%d %B %Y"), 
                    "dokter": dokter_p2, "kartu": kartu_p2, "sep": sep_p2, "iter": iter_p2, 
                    "obat_list": obat_siap_cetak2, "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")
                }
                st.session_state['show_success_tab2'] = True
                st.rerun()
        else:
            st.warning("Daftar obat PDF kosong.")

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
        
        st.subheader("🏷️ 2. Cetak Etiket (Kustomisasi Sebelum Print)")
        st.info("💡 **Tips:** Anda bebas mengubah **Aturan Pakai** (Misal: tambah 'Sesudah Makan') atau **Nama Obat** di tabel bawah ini. Perubahan ini **hanya untuk print etiket** dan tidak merusak data resep di database!")
        
        # Buat DataFrame khusus untuk diedit sebelum cetak etiket
        if 'df_etiket_edit' not in st.session_state or st.session_state.get('last_etiket_pasien') != d['nama']:
            df_kustom = pd.DataFrame(d['obat_list'])
            df_kustom['Cetak'] = True # Opsi untuk memilih obat mana yg di print
            st.session_state['df_etiket_edit'] = df_kustom[['Cetak', 'nama', 'signa']]
            st.session_state['last_etiket_pasien'] = d['nama']
            
        edited_etiket = st.data_editor(
            st.session_state['df_etiket_edit'],
            column_config={
                "Cetak": st.column_config.CheckboxColumn("🖨️ Cetak?", default=True),
                "nama": "Nama Obat (Bisa Diedit)",
                "signa": "Aturan Pakai (Bisa Diedit)"
            },
            hide_index=True,
            use_container_width=True,
            key="editor_etiket_thermal"
        )
        
        # Simpan state terbaru setiap ada ketikan
        st.session_state['df_etiket_edit'] = edited_etiket
        
        # Logika pembagian format tanggal persis seperti gambar (Atas: Tanggal, Bawah: Bulan Tahun)
        tgl_split = d['tgl_copy'].split(" ")
        tgl_hari = tgl_split[0] if len(tgl_split) > 0 else ""
        tgl_bln_thn = f"{tgl_split[1].upper()} {tgl_split[2]}" if len(tgl_split) > 2 else ""

        html_etiket_pages = ""
        # Hanya loop obat yang dicentang 'Cetak'
        for _, row in edited_etiket[edited_etiket['Cetak'] == True].iterrows():
            html_etiket_pages += f"""
            <div class="etiket-page">
                <div class="e-header">
                    <div style="flex: 4; text-align: center; color: #555;">
                        <span style="font-size: 11px; font-weight: 900;">RUMAH SAKIT ISLAM MASYITHOH</span><br>
                        <span style="font-size: 9px;">Jl. A.Yani No 6-7 Bangil 67153</span><br>
                        <span style="font-size: 10px; font-weight: bold;">Telefarmasi (WA) 0343-741018</span>
                    </div>
                </div>
                <table class="e-meta">
                    <tr>
                        <td width="20%">Nama</td><td width="55%">: <strong>{d['nama']}</strong></td>
                        <td width="25%" style="text-align: right; vertical-align: top;">
                            <div style="font-size: 11px;">{tgl_hari}</div>
                        </td>
                    </tr>
                    <tr>
                        <td>No RM</td><td>: {d['rm']}</td>
                        <td style="text-align: right;">
                            <div style="font-size: 9px; line-height: 1;">{tgl_bln_thn}</div>
                        </td>
                    </tr>
                </table>
                <div class="e-signa">{row['signa']}</div>
                <table class="e-obat-table">
                    <tr><td width="20%">Nama<br>Obat</td><td width="80%">: <span style="font-size: 11px;">{row['nama']}</span></td></tr>
                </table>
                <div class="e-footer">Kesembuhan Dan Kesehatan Anda Adalah Do'a Yang Kami Panjatkan</div>
            </div>
            """
            
        html_thermal = f"""
        <!DOCTYPE html><html><head><style>
            @page {{ size: 70mm 50mm; margin: 0; }}
            body {{ background-color: #FFFFFF !important; color: #000000 !important; font-family: 'Arial', sans-serif; margin: 0; padding: 0; }}
            .etiket-page {{ width: 68mm; height: 48mm; padding: 1mm 2mm; box-sizing: border-box; page-break-after: always; overflow: hidden; position: relative; }}
            .e-header {{ display: flex; align-items: center; border-bottom: 2px solid #aaa; padding-bottom: 3px; margin-bottom: 3px; }}
            .e-meta {{ width: 100%; font-size: 10px; margin-bottom: 5px; border-collapse: collapse; }}
            .e-meta td {{ padding: 1px 0; vertical-align: top; }}
            .e-signa {{ text-align: center; font-size: 13px; font-weight: 900; border-top: 2px solid #000; border-bottom: 2px solid #000; padding: 5px 0; margin-bottom: 5px; text-transform: uppercase; }}
            .e-obat-table {{ width: 100%; font-size: 10px; border-collapse: collapse; margin-bottom: 2px; }}
            .e-obat-table td {{ vertical-align: top; padding: 1px 0; }}
            .e-footer {{ text-align: center; font-size: 7px; font-weight: bold; color: #777; border-top: 1px solid #000; padding-top: 3px; position: absolute; bottom: 3mm; width: 64mm; }}
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
        st.info("⚠️ Kosong. Silakan proses data melalui tab Paste Teks atau Upload PDF terlebih dahulu.")

# --- TAB 5: LAPORAN & PENCARIAN (DENGAN FITUR HAPUS) ---
with tab5:
    if not df_data.empty:
        st.subheader("🔍 Cari Riwayat Pasien")
        pencarian = st.text_input("Masukkan Nama Pasien atau No. RM:")
        
        if pencarian:
            df_cari = df_data[df_data.apply(lambda row: row.astype(str).str.contains(pencarian, case=False).any(), axis=1)]
            if not df_cari.empty: st.dataframe(df_cari, use_container_width=True)
            else: st.warning("Data tidak ditemukan.")
            
        st.markdown("---")
        st.subheader("📊 Laporan Bulanan (Unduh & Kelola Data)")
        
        df_data['Tanggal Input'] = pd.to_datetime(df_data['Tanggal Input'], errors='coerce')
        col_tgl1, col_tgl2 = st.columns(2)
        with col_tgl1: start_date = st.date_input("Dari Tanggal", get_waktu_sekarang().date().replace(day=1))
        with col_tgl2: end_date = st.date_input("Sampai Tanggal", get_waktu_sekarang().date())
        
        mask = (df_data['Tanggal Input'].dt.date >= start_date) & (df_data['Tanggal Input'].dt.date <= end_date)
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
                key="editor_laporan_data" # Key wajib untuk hindari bug double click
            )
            
            baris_terpilih = edited_df_laporan[edited_df_laporan['Hapus'] == True]
            
            if not baris_terpilih.empty:
                if st.button("🗑️ Hapus Data Terpilih", type="primary"):
                    del_bar = st.progress(0, text="Menghapus data dari server...")
                    time.sleep(0.3)
                    if sheet:
                        all_records = sheet.get_all_records()
                        for i in range(len(all_records) - 1, -1, -1):
                            rec = all_records[i]
                            for _, row_del in baris_terpilih.iterrows():
                                rm_del = str(row_del.get('No. RM', row_del.get('RM', '')))
                                rm_rec = str(rec.get('No. RM', rec.get('RM', '')))
                                tgl_del = str(row_del.get('Tanggal Input', ''))
                                tgl_rec = str(rec.get('Tanggal Input', ''))
                                
                                if tgl_rec == tgl_del and rm_rec == rm_del:
                                    try:
                                        sheet.delete_rows(i + 2)
                                    except AttributeError:
                                        sheet.delete_row(i + 2)
                                    break
                    else:
                        st.session_state['db_lokal'] = [
                            r for r in st.session_state['db_lokal']
                            if not any((str(r[0]) == str(row_del.get('Tanggal Input', '')) and str(r[2]) == str(row_del.get('No. RM', row_del.get('RM', '')))) for _, row_del in baris_terpilih.iterrows())
                        ]
                    
                    del_bar.progress(100, text="Selesai menghapus!")
                    time.sleep(0.5)
                    del_bar.empty()
                    st.rerun()

            csv = df_laporan.drop(columns=['Hapus']).to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Unduh Laporan Rekap (CSV)", data=csv, file_name=f"Laporan_{start_date}_{end_date}.csv", mime="text/csv")
    else:
        st.info("Database masih kosong. Belum ada resep yang diinput.")