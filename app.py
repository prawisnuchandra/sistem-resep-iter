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
# 1. KONFIGURASI UI/UX
# ==========================================
st.set_page_config(page_title="Sistem Farmasi 3D", page_icon="🚀", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 800; }
    
    .stRadio > div[role="radiogroup"] { flex-direction: row; background-color: #1E293B; padding: 5px; border-radius: 12px; gap: 5px; }
    .stRadio > div[role="radiogroup"] > label { flex: 1; text-align: center; background-color: transparent; border-radius: 8px; padding: 10px 0; cursor: pointer; transition: all 0.2s ease; }
    .stRadio > div[role="radiogroup"] > label:hover { background-color: rgba(255,255,255,0.1); }
    .stRadio > div[role="radiogroup"] > label[data-checked="true"] { background: linear-gradient(135deg, #4F46E5, #3B82F6); box-shadow: 0 4px 6px rgba(0,0,0,0.2); }
    .stRadio > div[role="radiogroup"] > label > div:first-child { display: none; }
    .stRadio > div[role="radiogroup"] > label > div:last-child { font-weight: 800 !important; color: white !important; font-size: 16px; margin: 0; padding: 0; }
    
    .stButton>button { background: linear-gradient(135deg, #4F46E5, #3B82F6); color: white !important; border-radius: 12px; padding: 12px 24px; font-weight: 800; border: none; box-shadow: 0 6px 0 #312E81, 0 15px 20px rgba(0,0,0,0.2); transition: all 0.1s; text-transform: uppercase; letter-spacing: 1px; }
    .stButton>button:active, .stButton>button:focus { transform: translateY(6px); box-shadow: 0 0 0 #312E81, 0 5px 5px rgba(0,0,0,0.2); outline: none; }
    
    .status-box { padding: 15px; border-radius: 15px; margin-bottom: 20px; font-weight: 800; text-align: center; background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2); box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
    .status-success { border-left: 5px solid #10B981; }
    .status-warning { border-left: 5px solid #F59E0B; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. KONEKSI GOOGLE SHEETS & AUTO-HEAL
# ==========================================
KOLOM_ITER = ["Tanggal Input", "Nama Pasien", "RM", "Tanggal Resep Asli", "Nama Dokter", "No. Kartu", "SEP", "Jumlah Iter", "Daftar Obat"]
KOLOM_PRB = ["Tanggal Input", "Nama Pasien", "RM", "Tanggal Resep Asli", "Nama Dokter", "No. Kartu", "SEP", "Daftar Obat"]

def get_gsheets_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        has_secrets = False
        try:
            if "google_credentials" in st.secrets: has_secrets = True
        except: pass

        if has_secrets: creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(st.secrets["google_credentials"]), scope)
        elif os.path.exists("credentials.json"): creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        else: return None, None, "Offline (Lokal) 🔌"
        
        sh = gspread.authorize(creds).open("Data Copy Resep Iter")
        sheet_iter = sh.sheet1
        
        try: sheet_prb = sh.worksheet("Data PRB")
        except: 
            try: sheet_prb = sh.add_worksheet(title="Data PRB", rows="1000", cols="20")
            except: sheet_prb = None
            
        return sheet_iter, sheet_prb, "Online (Tersinkron) 🌐"
    except Exception as e:
        return None, None, f"Koneksi Gagal: {e}"

sheet_iter, sheet_prb, connection_status = get_gsheets_connection()

if 'db_lokal_iter' not in st.session_state: st.session_state['db_lokal_iter'] = []
if 'db_lokal_prb' not in st.session_state: st.session_state['db_lokal_prb'] = []

def pastikan_database_sehat(sht, is_prb):
    if sht:
        try:
            standar_headers = KOLOM_PRB if is_prb else KOLOM_ITER
            headers_sekarang = sht.row_values(1)
            if headers_sekarang != standar_headers:
                try: sht.update('A1:I1' if not is_prb else 'A1:H1', [standar_headers])
                except: sht.update([standar_headers], 'A1:I1' if not is_prb else 'A1:H1')
        except: pass

pastikan_database_sehat(sheet_iter, False)
pastikan_database_sehat(sheet_prb, True)

def simpan_data(data_dict, is_prb):
    waktu = get_waktu_sekarang().strftime("%Y-%m-%d %H:%M:%S")
    nama = str(data_dict.get("Nama Pasien", ""))
    rm = str(data_dict.get("No. RM", "")).strip()
    tgl_resep = str(data_dict.get("Tanggal Resep Asli", ""))
    dokter = str(data_dict.get("Nama Dokter", ""))
    kartu = str(data_dict.get("No. Kartu", "")).strip()
    sep = str(data_dict.get("SEP", "")).strip()
    obat = str(data_dict.get("Daftar Obat", ""))
    
    if is_prb:
        row_data_lokal = [waktu, nama, rm, tgl_resep, dokter, kartu, sep, obat]
        row_data_gsheets = [waktu, nama, f"'{rm}", tgl_resep, dokter, f"'{kartu}", f"'{sep}", obat]
    else:
        iter_val = str(data_dict.get("Jumlah Iter", ""))
        row_data_lokal = [waktu, nama, rm, tgl_resep, dokter, kartu, sep, iter_val, obat]
        row_data_gsheets = [waktu, nama, f"'{rm}", tgl_resep, dokter, f"'{kartu}", f"'{sep}", iter_val, obat]
    
    sheet_target = sheet_prb if is_prb else sheet_iter
    db_lokal_key = 'db_lokal_prb' if is_prb else 'db_lokal_iter'
    
    if sheet_target: 
        try:
            records = sheet_target.get_all_records()
            for i, rec in enumerate(records):
                keys = list(rec.keys())
                rm_key = next((k for k in keys if 'rm' in k.lower()), keys[2] if len(keys) > 2 else 'RM')
                tgl_key = next((k for k in keys if 'tanggal' in k.lower() and 'input' not in k.lower()), keys[3] if len(keys) > 3 else 'Tanggal Resep Asli')
                
                if str(rec.get(rm_key, "")).strip() == rm and str(rec.get(tgl_key, "")).strip() == tgl_resep.strip():
                    try: sheet_target.delete_rows(i + 2)
                    except AttributeError: sheet_target.delete_row(i + 2)
                    break 
        except: pass
        sheet_target.append_row(row_data_gsheets, value_input_option='USER_ENTERED')
    else: 
        st.session_state[db_lokal_key] = [r for r in st.session_state[db_lokal_key] if not (str(r[2]).strip() == rm and str(r[3]).strip() == tgl_resep.strip())]
        st.session_state[db_lokal_key].append(row_data_lokal)

def ambil_semua_data(is_prb):
    sheet_target = sheet_prb if is_prb else sheet_iter
    db_lokal_key = 'db_lokal_prb' if is_prb else 'db_lokal_iter'
    kolom_standar = KOLOM_PRB if is_prb else KOLOM_ITER
    
    if sheet_target: 
        try:
            data_mentah = sheet_target.get_all_values()
            if len(data_mentah) > 1:
                df = pd.DataFrame(data_mentah[1:], columns=data_mentah[0])
                df = df.loc[:, ~df.columns.duplicated()] 
                for col in ["RM", "No. Kartu", "SEP", "Jumlah Iter"]:
                    if col in df.columns: df[col] = df[col].astype(str).str.replace("'", "", regex=False).str.strip()
                return df
        except: pass
        df_fb = pd.DataFrame(sheet_target.get_all_records()).astype(str)
        return df_fb.loc[:, ~df_fb.columns.duplicated()]
        
    return pd.DataFrame(st.session_state[db_lokal_key], columns=kolom_standar).astype(str)

def cari_kolom(df_columns, keywords, excludes=[]):
    for kw in keywords:
        for col in df_columns:
            cl = str(col).lower().strip()
            if kw.lower() == cl and not any(ex.lower() in cl for ex in excludes): return col
    for kw in keywords:
        for col in df_columns:
            cl = str(col).lower().strip()
            if kw.lower() in cl and not any(ex.lower() in cl for ex in excludes): return col
    return None

def parse_db_obat(db_string, is_prb):
    obat_list = []
    if pd.isna(db_string) or not str(db_string).strip(): return obat_list
        
    items = str(db_string).split(" | ")
    for item in items:
        if not item.strip(): continue
        nama, signa, jumlah, status_lama = item.strip(), "", "", ("det 30" if is_prb else "🟢 det orig")
        
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

        if is_prb: status_baru = status_lama
        else:
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

def parse_teks_resep(teks_mentah, is_prb):
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
    if m_dok: hasil["dokter"] = m_dok.group(1).split("TELAAH")[0].strip()
        
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
                
            if line.lower() in ['pagi', 'siang', 'sore', 'malam', 'pc', 'ac', 'prn', 'pc prn', 'ac prn']: waktu = line
        
        if signa and waktu: signa = f"{signa} {waktu}"
        elif waktu and not signa: signa = waktu
            
        if nama_obat and "TELAAH" not in nama_obat.upper():
            status_def = f"det {jumlah}" if is_prb else "🟢 det orig"
            hasil["list_obat"].append({"Nama Obat": nama_obat, "Aturan Pakai": signa, "Jumlah": jumlah, "Status": status_def, "Hapus": False})
            
    return hasil

def ekstrak_data_pdf(file_pdf, is_prb):
    teks_mentah = "".join(page.get_text() for page in fitz.open(stream=file_pdf.read(), filetype="pdf"))
    return parse_teks_resep(teks_mentah, is_prb)

# ==========================================
# 4. SIDEBAR SELECTION & JAM 3D LIVE
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=80)
    st.title("Pusat Kendali")
    
    st.markdown("<p style='font-size: 14px; font-weight: 600; margin-bottom: 5px; color: #94A3B8;'>Pilih Modul Aplikasi:</p>", unsafe_allow_html=True)
    modul = st.radio("", ["🔄 ITER", "🏥 PRB"], label_visibility="collapsed")
    is_prb = (modul == "🏥 PRB")
    
    if st.session_state.get('last_modul') != modul:
        for k in ['hasil_ekstrak_teks', 'df_obat_teks', 'hasil_ekstrak_pdf', 'df_obat_pdf', 'hasil_ekstrak_iter', 'df_obat_iter', 'data_cetak', 'df_etiket_edit', 'last_etiket_pasien']:
            if k in st.session_state: del st.session_state[k]
        st.session_state['last_modul'] = modul
        
    components.html("""
    <div style="font-family: 'Arial', sans-serif; text-align: center; padding: 15px; background: linear-gradient(145deg, #ffffff, #e6e6e6); box-shadow: 5px 5px 10px rgba(0,0,0,0.1); border-radius: 15px; margin-bottom: 20px; margin-top: 15px;">
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
    """, height=130)
    
    df_data = ambil_semua_data(is_prb)
    col_tgl_input = cari_kolom(df_data.columns, ["input"], ["asli"]) if not df_data.empty else None
    if col_tgl_input is None and not df_data.empty: col_tgl_input = df_data.columns[0]
        
    today_str = get_waktu_sekarang().strftime("%Y-%m-%d")
    total_hari_ini = len(df_data[df_data[col_tgl_input].astype(str).str.startswith(today_str)]) if not df_data.empty and col_tgl_input else 0
    
    st.metric(label=f"Resep {('PRB' if is_prb else 'Iter')} Hari Ini", value=f"{total_hari_ini} Resep", delta="Aktif")
    st.markdown(f'<div class="status-box status-{"success" if sheet_iter else "warning"}">{"✅" if sheet_iter else "⚠️"} {connection_status}</div>', unsafe_allow_html=True)
    
    # --- FITUR GRAFIK TREN 7 HARI ---
    st.markdown("---")
    st.markdown(f"<p style='font-size: 14px; font-weight: 600; margin-bottom: 5px; color: #94A3B8;'>Tren 7 Hari Terakhir ({'PRB' if is_prb else 'Iter'})</p>", unsafe_allow_html=True)
    
    if not df_data.empty and col_tgl_input:
        df_chart = df_data.copy()
        df_chart[col_tgl_input] = pd.to_datetime(df_chart[col_tgl_input], errors='coerce')
        
        hari_ini = get_waktu_sekarang().date()
        tujuh_hari_lalu = hari_ini - timedelta(days=6)
        
        mask_7_hari = (df_chart[col_tgl_input].dt.date >= tujuh_hari_lalu) & (df_chart[col_tgl_input].dt.date <= hari_ini)
        df_7_hari = df_chart.loc[mask_7_hari]
        
        list_tanggal = [(tujuh_hari_lalu + timedelta(days=i)).strftime('%d %b') for i in range(7)]
        df_lengkap = pd.DataFrame({'Tanggal': list_tanggal})
        
        if not df_7_hari.empty:
            df_7_hari['Tanggal'] = df_7_hari[col_tgl_input].dt.strftime('%d %b')
            tren_harian = df_7_hari.groupby('Tanggal').size().reset_index(name='Jumlah Pasien')
            df_final = pd.merge(df_lengkap, tren_harian, on='Tanggal', how='left').fillna(0)
        else:
            df_final = df_lengkap
            df_final['Jumlah Pasien'] = 0
            
        df_final = df_final.set_index('Tanggal')
        st.bar_chart(df_final, color="#3B82F6", height=150)
    else:
        st.info("Belum ada data.")

opsi_status_iter = ["🟢 det orig", "🟡 det", "🔴 ne det", "🔵 det iter 1x", "🟣 det iter 2x", "🟤 det iter 3x"]
def get_col_config():
    if is_prb: return {"Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False), "Status": st.column_config.TextColumn("Status (Bisa diedit)")}
    else: return {"Hapus": st.column_config.CheckboxColumn("🗑️ Hapus", default=False), "Status": st.column_config.SelectboxColumn("Status", options=opsi_status_iter)}

# ==========================================
# 5. HALAMAN UTAMA (TABS)
# ==========================================
st.title(f"✨ Sistem Cerdas Copy Resep {'PRB' if is_prb else 'Iter'}")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Paste Teks", "📂 Upload PDF", "✍️ Manual", "🔄 Tarik Data", "🖨️ Pusat Cetak", "🔍 Laporan Data"])

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
            my_bar = st.progress(0, text="Memulai pemindaian... 0%")
            for percent_complete in range(100):
                time.sleep(0.01) 
                my_bar.progress(percent_complete + 1, text=f"Memproses data... {percent_complete}%")
            my_bar.empty() 
            
            st.session_state['hasil_ekstrak_teks'] = parse_teks_resep(teks_input_user, is_prb)
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
            if not is_prb: iter_p = st.number_input("Jumlah Iter", min_value=0, value=hasil["iter"], key="p_iter_teks")
            
        st.markdown("---")
        st.subheader("💊 Rincian Obat")
        
        if not st.session_state['df_obat_teks'].empty:
            edited_df_obat = st.data_editor(
                st.session_state['df_obat_teks'],
                column_config=get_col_config(),
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
                
                data_dict = {"Nama Pasien": nama_p, "No. RM": rm_p, "Tanggal Resep Asli": tgl_r.strftime("%Y-%m-%d"), "Nama Dokter": dokter_p, "No. Kartu": kartu_p, "SEP": sep_p, "Daftar Obat": teks_db}
                if not is_prb: data_dict["Jumlah Iter"] = iter_p
                
                simpan_data(data_dict, is_prb)
                
                st.session_state['data_cetak'] = {"is_prb": is_prb, "nama": nama_p, "rm": rm_p, "tgl_resep": tgl_r.strftime("%d %B %Y"), "dokter": dokter_p, "kartu": kartu_p, "sep": sep_p, "iter": iter_p if not is_prb else "", "obat_list": obat_siap_cetak, "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")}
                
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
            st.session_state['hasil_ekstrak_pdf'] = ekstrak_data_pdf(file_upload, is_prb)
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
            if not is_prb: iter_p2 = st.number_input("Jumlah Iter", min_value=0, value=hasil["iter"], key="p_iter_pdf")
            
        st.markdown("---")
        st.subheader("💊 Rincian Obat (PDF)")
        
        if not st.session_state['df_obat_pdf'].empty:
            edited_df_obat2 = st.data_editor(
                st.session_state['df_obat_pdf'],
                column_config=get_col_config(),
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
                
                data_dict = {"Nama Pasien": nama_p2, "No. RM": rm_p2, "Tanggal Resep Asli": tgl_r2.strftime("%Y-%m-%d"), "Nama Dokter": dokter_p2, "No. Kartu": kartu_p2, "SEP": sep_p2, "Daftar Obat": teks_db}
                if not is_prb: data_dict["Jumlah Iter"] = iter_p2
                
                simpan_data(data_dict, is_prb)
                
                st.session_state['data_cetak'] = {"is_prb": is_prb, "nama": nama_p2, "rm": rm_p2, "tgl_resep": tgl_r2.strftime("%d %B %Y"), "dokter": dokter_p2, "kartu": kartu_p2, "sep": sep_p2, "iter": iter_p2 if not is_prb else "", "obat_list": obat_siap_cetak2, "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")}
                
                save_bar2.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar2.empty()
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
            if not is_prb: m_iter = st.number_input("Jumlah Iter", min_value=0)
        m_obat = st.text_area("Daftar Obat (Tiap baris tekan Enter):", height=150)
        
        btn_manual = st.form_submit_button("💾 Simpan Data Resep (Manual)")
        if btn_manual:
            save_bar3 = st.progress(0, text="Menyimpan data manual...")
            time.sleep(0.5)
            if m_nama and m_obat:
                data_dict = {"Nama Pasien": m_nama, "No. RM": m_rm, "Tanggal Resep Asli": m_tgl.strftime("%Y-%m-%d"), "Nama Dokter": m_dok, "No. Kartu": m_kartu, "SEP": m_sep, "Daftar Obat": m_obat.replace('\n', ' | ')}
                if not is_prb: data_dict["Jumlah Iter"] = m_iter
                
                simpan_data(data_dict, is_prb)
                save_bar3.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar3.empty()
                st.session_state['show_success_tab3'] = True
                st.rerun()

# --- TAB 4: TARIK DATA (ITER / PRB) ---
with tab4:
    st.info(f"💡 **Gunakan fitur ini untuk resep {'PRB' if is_prb else 'Iterasi (Refill)'}.** Sistem akan menarik data dari Database {'PRB' if is_prb else 'Iter'}.")
    
    if df_data.empty: 
        st.warning("Database masih kosong.")
    else:
        rm_cari = st.text_input("🔍 Masukkan No. RM untuk mencari riwayat resep:", key="cari_rm_iter")
        
        col_rm_db = cari_kolom(df_data.columns, ["rm", "rekam"]) or df_data.columns[2]
        col_tgl_db = cari_kolom(df_data.columns, ["asli", "resep"], ["input"]) or df_data.columns[3]
        col_nama_db = cari_kolom(df_data.columns, ["pasien", "nama"], ["dokter"]) or df_data.columns[1]
        col_dok_db = cari_kolom(df_data.columns, ["dokter", "dr"]) or df_data.columns[4]
        col_kartu_db = cari_kolom(df_data.columns, ["kartu", "bpjs"]) or df_data.columns[5]
        col_sep_db = cari_kolom(df_data.columns, ["sep"]) or df_data.columns[6]
        col_obat_db = cari_kolom(df_data.columns, ["obat", "daftar", "rincian", "resep"]) or (df_data.columns[7] if is_prb else df_data.columns[8])
        if not is_prb: col_iter_db = cari_kolom(df_data.columns, ["iter", "jumlah"]) or df_data.columns[7]
        
        if rm_cari:
            df_match = df_data[df_data[col_rm_db].astype(str).str.contains(rm_cari, case=False)]
            
            if not df_match.empty:
                opsi = []
                for _, r in df_match.iterrows():
                    tgl_text = str(r.get(col_tgl_db, "Unknown Date"))
                    nama_text = str(r.get(col_nama_db, "Unknown Pasien"))
                    dok_text = str(r.get(col_dok_db, "Unknown Dokter"))
                    opsi.append(f"{tgl_text} - {nama_text} (Dokter: {dok_text})")
                    
                pilihan_riwayat = st.selectbox("📂 Pilih Riwayat Resep Sebelumnya:", opsi)
                idx_terpilih = opsi.index(pilihan_riwayat)
                row_terpilih = df_match.iloc[idx_terpilih]
                
                if st.button("🔽 Tarik & Proses Data Ini"):
                    bar_tarik = st.progress(0, text="Mengambil data riwayat pasien...")
                    time.sleep(0.2)
                    bar_tarik.progress(40, text="Memetakan susunan kolom ke formulir...")
                    
                    st.session_state['hasil_ekstrak_iter'] = {
                        "Nama Pasien": str(row_terpilih.get(col_nama_db, "")),
                        "No. RM": str(row_terpilih.get(col_rm_db, "")),
                        "Tanggal Resep Asli": str(row_terpilih.get(col_tgl_db, "")),
                        "Nama Dokter": str(row_terpilih.get(col_dok_db, "")),
                        "No. Kartu": str(row_terpilih.get(col_kartu_db, "")),
                        "SEP": str(row_terpilih.get(col_sep_db, "")),
                        "Daftar Obat": str(row_terpilih.get(col_obat_db, ""))
                    }
                    if not is_prb: st.session_state['hasil_ekstrak_iter']["Jumlah Iter"] = str(row_terpilih.get(col_iter_db, 2))
                    
                    bar_tarik.progress(70, text="Mengekstrak rincian & status obat...")
                    db_obat_str = st.session_state['hasil_ekstrak_iter']['Daftar Obat']
                    st.session_state['df_obat_iter'] = pd.DataFrame(parse_db_obat(db_obat_str, is_prb))
                    
                    time.sleep(0.3)
                    bar_tarik.progress(100, text="Selesai!")
                    time.sleep(0.3)
                    bar_tarik.empty()
            else:
                st.error("Data pasien tidak ditemukan.")
                
    if 'hasil_ekstrak_iter' in st.session_state and 'df_obat_iter' in st.session_state:
        if st.session_state.get('show_success_tab4'):
            st.success("✅ Sukses Ditarik & Disimpan! Buka Tab '🖨️ Pusat Cetak'.")
            st.session_state['show_success_tab4'] = False
            
        hasil_it = st.session_state['hasil_ekstrak_iter']
        
        st.markdown("---")
        st.subheader(f"👤 Identitas Pasien ({'PRB' if is_prb else 'Iterasi'})")
        c1, c2, c3 = st.columns(3)
        with c1:
            nama_p3 = st.text_input("Nama Pasien", value=hasil_it.get("Nama Pasien", ""), key="p_nama_it")
            rm_p3 = st.text_input("No. RM", value=hasil_it.get("No. RM", ""), key="p_rm_it")
        with c2:
            kartu_p3 = st.text_input("No. Kartu BPJS", value=hasil_it.get("No. Kartu", ""), key="p_kartu_it")
            sep_p3 = st.text_input("No. SEP", value=hasil_it.get("SEP", ""), key="p_sep_it")
        with c3:
            try:
                tgl_str = str(hasil_it.get("Tanggal Resep Asli", ""))
                if tgl_str == "": tgl_lama = get_waktu_sekarang().date()
                else: tgl_lama = datetime.strptime(tgl_str, "%Y-%m-%d").date()
            except:
                tgl_lama = get_waktu_sekarang().date()
                
            tgl_r3 = st.date_input("Tanggal Resep Asli", value=tgl_lama, key="p_tgl_it")
            dokter_p3 = st.text_input("Nama Dokter", value=hasil_it.get("Nama Dokter", ""), key="p_dok_it")
            
            if not is_prb:
                try: iter_val = int(float(hasil_it.get("Jumlah Iter", 2)))
                except: iter_val = 2
                iter_p3 = st.number_input("Jumlah Iter", min_value=0, value=iter_val, key="p_iter_it")
            
        st.subheader("💊 Rincian Obat")
        if not st.session_state['df_obat_iter'].empty:
            edited_df_obat3 = st.data_editor(
                st.session_state['df_obat_iter'],
                column_config=get_col_config(),
                disabled=["Nama Obat"], hide_index=True, use_container_width=True, key="editor_obat_iter"
            )
            
            if st.button("🗑️ Hapus Obat Terpilih", key="del_tab4"):
                st.session_state['df_obat_iter'] = edited_df_obat3[edited_df_obat3['Hapus'] == False].copy()
                st.session_state['df_obat_iter']['Hapus'] = False
                st.rerun()
                
            st.markdown("---")
            if st.button(f"💾 Simpan Data {'PRB' if is_prb else 'Iter'} & Siapkan Cetak", key="btn_save_iter"):
                save_bar4 = st.progress(0, text="Menyiapkan data...")
                time.sleep(0.3)
                
                obat_siap_cetak3 = edited_df_obat3[edited_df_obat3['Hapus'] == False].rename(columns={"Nama Obat": "nama", "Aturan Pakai": "signa", "Jumlah": "jumlah", "Status": "status"}).to_dict('records')
                teks_db = " | ".join([f"{o['nama']} ({o['signa']} No. {o['jumlah']}) [{o['status']}]" for o in obat_siap_cetak3])
                
                data_dict = {"Nama Pasien": nama_p3, "No. RM": rm_p3, "Tanggal Resep Asli": tgl_r3.strftime("%Y-%m-%d"), "Nama Dokter": dokter_p3, "No. Kartu": kartu_p3, "SEP": sep_p3, "Daftar Obat": teks_db}
                if not is_prb: data_dict["Jumlah Iter"] = iter_p3
                
                simpan_data(data_dict, is_prb)
                
                st.session_state['data_cetak'] = {"is_prb": is_prb, "nama": nama_p3, "rm": rm_p3, "tgl_resep": tgl_r3.strftime("%d %B %Y"), "dokter": dokter_p3, "kartu": kartu_p3, "sep": sep_p3, "iter": iter_p3 if not is_prb else "", "obat_list": obat_siap_cetak3, "tgl_copy": get_waktu_sekarang().strftime("%d %B %Y")}
                
                save_bar4.progress(100, text="Selesai!")
                time.sleep(0.4)
                save_bar4.empty()
                st.session_state['show_success_tab4'] = True
                st.rerun()
        else: 
            st.warning("⚠️ Data obat kosong. (Hapus dan input ulang pasien ini).")

# --- TAB 5: PUSAT CETAK ---
with tab5:
    if 'data_cetak' in st.session_state:
        d = st.session_state['data_cetak']
        
        st.subheader("📑 1. Cetak Copy Resep (A5)")
        html_rows_obat = ""
        for o in d['obat_list']:
            status_bersih = o['status'].split(" ", 1)[-1] if (" " in o['status'] and not d.get('is_prb')) else o['status']
            html_rows_obat += f"""
            <tr style="vertical-align: top;">
                <td style="padding: 6px 0; font-weight: bold; width: 5%;">R/</td>
                <td style="padding: 6px 0; width: 55%;">{o['nama']}</td>
                <td style="padding: 6px 0; text-align: center; width: 15%;">{o['signa']}</td>
                <td style="padding: 6px 0; text-align: center; width: 10%;">{o['jumlah']}</td>
                <td style="padding: 6px 0; text-align: right; font-style: italic; font-weight: bold; width: 15%;">- {status_bersih} -</td>
            </tr>
            """
            
        baris_iter_html = f"<tr><td><strong>Nama Pasien</strong></td><td>: <strong style='font-size: 13px;'>{d['nama']}</strong></td><td><strong>Status Iter</strong></td><td>: <strong>Iter {d['iter']}x</strong></td></tr>" if not d.get('is_prb') else f"<tr><td><strong>Nama Pasien</strong></td><td>: <strong style='font-size: 13px;'>{d['nama']}</strong></td><td></td><td></td></tr>"
        stamp_prb_html = '<div style="position: absolute; left: 0px; bottom: 0px; font-size: 32px; font-weight: 900; color: #000; border: 3px solid #000; padding: 4px 12px; border-radius: 6px; transform: rotate(-5deg); opacity: 0.8; letter-spacing: 2px;">PRB</div>' if d.get('is_prb') else ''
            
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
            .footer-container {{ position: relative; margin-top: 40px; height: 100px; }}
            .footer-box {{ float: right; text-align: center; width: 200px; color: #000000; }}
            .pcc {{ font-weight: bold; margin-bottom: 50px; }}
            .bottom-text {{ clear: both; text-align: center; font-style: italic; font-size: 10px; color: #333333; margin-top: 40px; border-top: 1px solid #000; padding-top: 5px; }}
        </style></head><body>
            <div class="kop"><h2>RUMAH SAKIT ISLAM MASYITHOH</h2><p>Jl. A.Yani No 6-7 Bangil 67153</p><p>Telefarmasi (WA) 0343-741018</p></div>
            <div class="line-thick"></div>
            <div class="title">SALINAN RESEP (COPY RESEP)</div>
            <table class="meta-table">
                <tr><td width="20%"><strong>Resep Dari</strong></td><td width="35%">: {d['dokter']}</td><td width="15%"><strong>No. RM</strong></td><td width="30%">: {d['rm']}</td></tr>
                <tr><td><strong>Tgl Resep Asli</strong></td><td>: {d['tgl_resep']}</td><td><strong>No. Kartu</strong></td><td>: {d['kartu']}</td></tr>
                {baris_iter_html}
            </table>
            <div class="line-thin"></div>
            <table class="obat-table">{html_rows_obat}</table>
            <div class="footer-container">
                {stamp_prb_html}
                <div class="footer-box"><div class="pcc">p.c.c</div><div>_________________________</div></div>
            </div>
            <div class="bottom-text">Kesembuhan Dan Kesehatan Anda Adalah Do'a Yang Kami Panjatkan</div>
        </body></html>
        """
        
        c1, c2 = st.columns([8,2])
        with c1: components.html(html_a5, height=350, scrolling=True)
        with c2: 
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            js_print_a5 = f"""<script>function printA5() {{ var win = window.open('', '', 'height=700,width=900'); win.document.write(`{html_a5}`); win.document.close(); win.print(); }}</script>
            <button onclick="printA5()" style="background: linear-gradient(135deg, #10B981, #059669); color: white; border: none; padding: 15px; font-weight: 800; border-radius: 12px; cursor: pointer; width: 100%; box-shadow: 0 6px 0 #047857, 0 10px 20px rgba(16,185,129,0.3); transition: all 0.1s;" onmousedown="this.style.transform='translateY(6px)'; this.style.boxShadow='0 0 0 #047857, 0 5px 5px rgba(16,185,129,0.3)';" onmouseup="this.style.transform='translateY(0)'; this.style.boxShadow='0 6px 0 #047857, 0 10px 20px rgba(16,185,129,0.3)';">🖨️ PRINT COPY RESEP</button>"""
            components.html(js_print_a5, height=100)

        st.markdown("---")
        
        st.subheader("🏷️ 2. Cetak Etiket (Kustomisasi Sebelum Print)")
        
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

# --- TAB 6: LAPORAN & PENCARIAN ---
with tab6:
    if not df_data.empty:
        st.subheader("🔍 Cari Riwayat Pasien")
        pencarian = st.text_input("Masukkan Nama Pasien atau No. RM:")
        
        if pencarian:
            try:
                df_cari = df_data[df_data.apply(lambda row: row.astype(str).str.contains(pencarian, case=False).any(), axis=1)]
                if not df_cari.empty: 
                    st.dataframe(df_cari, use_container_width=True)
                else: st.warning("Data tidak ditemukan.")
            except: pass
            
        st.markdown("---")
        st.subheader(f"📊 Laporan Bulanan (Database {'PRB' if is_prb else 'Iter'})")
        
        col_tgl_input = cari_kolom(df_data.columns, ["input"], ["asli"]) or df_data.columns[0]
        df_data[col_tgl_input] = pd.to_datetime(df_data[col_tgl_input], errors='coerce')
        
        col_tgl1, col_tgl2 = st.columns(2)
        with col_tgl1: start_date = st.date_input("Dari Tanggal", get_waktu_sekarang().date().replace(day=1))
        with col_tgl2: end_date = st.date_input("Sampai Tanggal", get_waktu_sekarang().date())
        
        mask = (df_data[col_tgl_input].dt.date >= start_date) & (df_data[col_tgl_input].dt.date <= end_date)
        df_laporan = df_data.loc[mask].copy()
        
        st.write(f"Total data ditemukan: **{len(df_laporan)} resep**")
        
        if not df_laporan.empty:
            df_laporan.insert(0, 'Hapus', False)
            
            df_laporan = df_laporan.loc[:, ~df_laporan.columns.duplicated()]
            
            edited_df_laporan = st.data_editor(
                df_laporan,
                column_config={"Hapus": st.column_config.CheckboxColumn("Pilih Hapus", default=False)},
                disabled=df_laporan.columns.drop('Hapus').tolist(),
                hide_index=True,
                use_container_width=True,
                key="editor_laporan_data"
            )
            
            baris_terpilih = edited_df_laporan[edited_df_laporan['Hapus'] == True]
            
            if not baris_terpilih.empty:
                if st.button("🗑️ Hapus Data Terpilih", type="primary"):
                    del_bar = st.progress(0, text="Menghapus data dari server...")
                    time.sleep(0.3)
                    
                    col_rm_db = cari_kolom(df_data.columns, ["rm", "rekam"]) or df_data.columns[2]
                    sheet_target = sheet_prb if is_prb else sheet_iter
                    
                    if sheet_target:
                        all_records = sheet_target.get_all_records()
                        for i in range(len(all_records) - 1, -1, -1):
                            rec = all_records[i]
                            keys = list(rec.keys())
                            rec_rm_key = cari_kolom(keys, ["rm", "rekam"]) or (keys[2] if len(keys)>2 else 'RM')
                            rec_tgl_key = cari_kolom(keys, ["input"], ["asli"]) or (keys[0] if len(keys)>0 else 'Tanggal Input')
                            
                            for _, row_del in baris_terpilih.iterrows():
                                rm_del = str(row_del.get(col_rm_db, ''))
                                rm_rec = str(rec.get(rec_rm_key, ''))
                                tgl_del = str(row_del.get(col_tgl_input, ''))
                                tgl_rec = str(rec.get(rec_tgl_key, ''))
                                
                                if tgl_rec == tgl_del and rm_rec == rm_del:
                                    try: sheet_target.delete_rows(i + 2)
                                    except AttributeError: sheet_target.delete_row(i + 2)
                                    break
                    else:
                        db_lokal_key = 'db_lokal_prb' if is_prb else 'db_lokal_iter'
                        st.session_state[db_lokal_key] = [
                            r for r in st.session_state[db_lokal_key]
                            if not any((str(r[0]) == str(row_del.get(col_tgl_input, '')) and str(r[2]) == str(row_del.get(col_rm_db, ''))) for _, row_del in baris_terpilih.iterrows())
                        ]
                    
                    del_bar.progress(100, text="Selesai menghapus!")
                    time.sleep(0.5)
                    del_bar.empty()
                    st.rerun()

            csv = df_laporan.drop(columns=['Hapus']).to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Unduh Laporan Rekap (CSV)", data=csv, file_name=f"Laporan_{'PRB' if is_prb else 'Iter'}_{start_date}.csv", mime="text/csv")
    else:
        st.info("Database masih kosong. Belum ada resep yang diinput.")