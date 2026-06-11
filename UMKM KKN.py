import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import hashlib

# Konfigurasi Halaman Streamlit (Harus di paling atas)
st.set_page_config(page_title="Buku Kas & Stok UMKM", page_icon="📊", layout="wide")
st.html('<meta name="google-site-verification" content="9pBgzUWsE_OpR9kBU9EBDHQsIMGUaIsm6GjYxNGscFk" />')

# ============================================================
# 🗄️ DATABASE LAYER (SQLite)
# ============================================================
class Database:
    def __init__(self, db_name="umkm_budget.db"):
        # Menyimpan database di folder sementara server agar tidak macet
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                business_name TEXT DEFAULT 'Usaha Saya'
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                type TEXT CHECK(type IN ('penjualan', 'pembelian', 'biaya')) NOT NULL,
                category TEXT NOT NULL,
                item_name TEXT,
                quantity INTEGER DEFAULT 0,
                unit_price REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                item_name TEXT NOT NULL,
                stock_quantity REAL DEFAULT 0,
                cost_price REAL DEFAULT 0,
                selling_price REAL DEFAULT 0,
                unit TEXT DEFAULT 'pcs',
                last_updated TEXT,
                UNIQUE(username, item_name)
            );
            CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                date TEXT NOT NULL,
                item_name TEXT NOT NULL,
                change_type TEXT CHECK(change_type IN ('masuk', 'keluar', 'penyesuaian')) NOT NULL,
                quantity REAL NOT NULL,
                note TEXT
            );
        """)
        self.conn.commit()

    def hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def register_user(self, username, password, business_name="Usaha Saya"):
        try:
            hashed_pw = self.hash_password(password)
            self.cursor.execute(
                "INSERT INTO users (username, password, business_name) VALUES (?, ?, ?)", 
                (username, hashed_pw, business_name)
            )
            self.conn.commit()
            return True, "Akun berhasil dibuat!"
        except sqlite3.IntegrityError:
            return False, "Username sudah terdaftar!"

    def login_user(self, username, password):
        # 🔒 FITUR AKUN PERMANEN (SOLUSI BIAR TIDAK LOGOUT / ERROR LAGI)
        # Anda bisa langsung masuk memakai Username: chelsea dan Password: 123
        if username.lower() == "chelsea" and password == "123":
            return True, "Usaha Chelsea (KKN)"
            
        hashed_pw = self.hash_password(password)
        self.cursor.execute("SELECT business_name FROM users WHERE username = ? AND password = ?", 
                          (username, hashed_pw))
        result = self.cursor.fetchone()
        if result:
            return True, result[0]
        return False, None

    def add_transaction(self, username, date, desc, amount, trans_type, category, item_name=None):
        self.cursor.execute(
            """INSERT INTO transactions 
               (username, date, description, amount, type, category, item_name) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (username, date, desc, amount, trans_type, category, item_name)
        )
        self.conn.commit()

    def fetch_transactions(self, username):
        query = "SELECT id, date, description, amount, type, category, item_name FROM transactions WHERE username = ? ORDER BY date DESC, id DESC"
        return pd.read_sql_query(query, self.conn, params=[username])

    def delete_transaction(self, trans_id):
        self.cursor.execute("DELETE FROM transactions WHERE id = ?", (trans_id,))
        self.conn.commit()

    def add_inventory_item(self, username, item_name, stock_qty, cost_price, selling_price, unit="pcs"):
        try:
            self.cursor.execute(
                """INSERT INTO inventory (username, item_name, stock_quantity, cost_price, selling_price, unit, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (username, item_name, stock_qty, cost_price, selling_price, unit, datetime.now().strftime("%Y-%m-%d %H:%M"))
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def update_inventory_full(self, item_id, stock_qty, cost_price, selling_price, unit):
        self.cursor.execute(
            """UPDATE inventory 
               SET stock_quantity=?, cost_price=?, selling_price=?, unit=?, last_updated=?
               WHERE id=?""",
            (stock_qty, cost_price, selling_price, unit, datetime.now().strftime("%Y-%m-%d %H:%M"), item_id)
        )
        self.conn.commit()

    def delete_inventory_item(self, item_id):
        self.cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
        self.conn.commit()

    def fetch_inventory(self, username):
        query = "SELECT id, item_name, stock_quantity, cost_price, selling_price, unit, last_updated FROM inventory WHERE username = ? ORDER BY item_name"
        return pd.read_sql_query(query, self.conn, params=[username])

    def get_item_by_name(self, username, item_name):
        self.cursor.execute(
            "SELECT id, stock_quantity, cost_price, selling_price FROM inventory WHERE username = ? AND item_name = ?",
            (username, item_name)
        )
        return self.cursor.fetchone()

    def adjust_stock(self, username, item_name, change_type, quantity, note=""):
        item = self.get_item_by_name(username, item_name)
        if not item:
            return False, "Barang tidak ditemukan!"
        
        item_id, current_stock, cost_price, selling_price = item
        if change_type == 'masuk':
            new_stock = current_stock + quantity
        elif change_type == 'keluar':
            if quantity > current_stock:
                return False, f"Stok tidak cukup! Tersedia: {current_stock}"
            new_stock = current_stock - quantity
        else:
            new_stock = quantity
        
        self.cursor.execute(
            "UPDATE inventory SET stock_quantity=?, last_updated=? WHERE id=?",
            (new_stock, datetime.now().strftime("%Y-%m-%d %H:%M"), item_id)
        )
        self.cursor.execute(
            """INSERT INTO stock_history (username, date, item_name, change_type, quantity, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, datetime.now().strftime("%Y-%m-%d %H:%M"), item_name, change_type, quantity, note)
        )
        self.conn.commit()
        return True, new_stock

# Inisialisasi Database ke Session State
if 'db' not in st.session_state:
    st.session_state.db = Database()
db = st.session_state.db

# Inisialisasi State Login
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.business_name = None

# ============================================================
# 🔐 HALAMAN AUTENTIKASI (LOGIN / DAFTAR)
# ============================================================
def show_auth_screen():
    st.title("📊 BUKU KAS & STOK UMKM")
    st.subheader("Catat Keuangan & Stok Bisnis dengan Mudah")
    
    tab_login, tab_register = st.tabs(["🔓 Masuk", "📝 Daftar Akun Baru"])
    
    with tab_login:
        st.info("💡 Hubungi Admin atau gunakan akun Default KKN untuk mencoba sistem.")
        with st.form("form_login"):
            username = st.text_input("Nama Pengguna (Username)")
            password = st.text_input("Kata Sandi", type="password")
            btn_login = st.form_submit_button("MASUK KE SISTEM", use_container_width=True)
            
            if btn_login:
                if username and password:
                    success, b_name = db.login_user(username, password)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.username = username
                        st.session_state.business_name = b_name
                        st.success(f"Selamat datang kembali, {b_name}!")
                        st.rerun()
                    else:
                        st.error("Nama pengguna atau kata sandi salah!")
                else:
                    st.warning("Mohon isi semua kolom!")

    with tab_register:
        with st.form("form_register"):
            reg_username = st.text_input("Nama Pengguna Baru")
            reg_password = st.text_input("Kata Sandi Baru", type="password")
            reg_b_name = st.text_input("Nama Usaha / Toko")
            btn_register = st.form_submit_button("DAFTAR AKUN", use_container_width=True)
            
            if btn_register:
                if len(reg_username) < 3 or len(reg_password) < 3:
                    st.error("Username & Kata Sandi minimal 3 karakter!")
                elif reg_username and reg_password:
                    success, msg = db.register_user(reg_username, reg_password, reg_b_name or "Usaha Saya")
                    if success:
                        st.success(msg + " Silakan beralih ke tab Masuk.")
                    else:
                        st.error(msg)
                else:
                    st.warning("Mohon isi semua kolom!")

# ============================================================
# 🏠 APLIKASI UTAMA (SETELAH LOGIN)
# ============================================================
def show_main_app():
    # Header Atas
    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.title(f"📊 {st.session_state.business_name}")
    with col_h2:
        st.write("")
        if st.button("🚪 Keluar Akun", type="primary", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.business_name = None
            st.rerun()

    # Menu Tab Utama Website
    tab1, tab2, tab3, tab4 = st.tabs([
        "🏠 Beranda / Dashboard", 
        "💰 Catat Keuangan", 
        "📦 Stok Barang (Inventori)", 
        "🧮 Hitung HPP & Harga Jual"
    ])

    # --------------------------------------------------------
    # TAB 1: BERANDA
    # --------------------------------------------------------
    with tab1:
        st.header(f"📅 Ringkasan Hari Ini ({datetime.now().strftime('%d %B %Y')})")
        
        # Ambil Data
        df_trans = db.fetch_transactions(st.session_state.username)
        df_inv = db.fetch_inventory(st.session_state.username)
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        df_today = df_trans[df_trans['date'] == today_str] if not df_trans.empty else pd.DataFrame()
        
        income_today = df_today[df_today['type'] == 'penjualan']['amount'].sum() if not df_today.empty else 0
        expense_today = df_today[df_today['type'].isin(['pembelian', 'biaya'])]['amount'].sum() if not df_today.empty else 0
        profit_today = income_today - expense_today
        
        # Menampilkan Metrik/Card Angka
        c1, c2, c3 = st.columns(3)
        c1.metric("💵 Penjualan Hari Ini", f"Rp {income_today:,.0f}".replace(",", "."))
        c2.metric("💸 Pengeluaran Hari Ini", f"Rp {expense_today:,.0f}".replace(",", "."))
        c3.metric("💰 Untung Hari Ini", f"Rp {profit_today:,.0f}".replace(",", "."), delta=float(profit_today))
        
        st.divider()
        
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            st.subheader("⚠️ Peringatan Stok Menipis (< 10)")
            if not df_inv.empty:
                low_stock = df_inv[df_inv['stock_quantity'] < 10]
                if not low_stock.empty:
                    st.dataframe(low_stock[['item_name', 'stock_quantity', 'unit']], use_container_width=True, hide_index=True)
                else:
                    st.success("Semua stok aman dan cukup!")
            else:
                st.info("Belum ada data barang.")
                
        with col_b2:
            st.subheader("📋 5 Transaksi Terakhir")
            if not df_trans.empty:
                st.dataframe(df_trans.head(5)[['date', 'description', 'amount', 'type']], use_container_width=True, hide_index=True)
            else:
                st.info("Belum ada transaksi dicatat.")

    # --------------------------------------------------------
    # TAB 2: CATAT KEUANGAN
    # --------------------------------------------------------
    with tab2:
        st.header("💰 Buku Kas & Transaksi")
        col_t1, col_t2 = st.columns([1, 2])
        
        with col_t1:
            st.subheader("✍️ Tambah Transaksi")
            with st.form("form_trans", clear_on_submit=True):
                t_date = st.date_input("Tanggal Transaksi", datetime.now())
                t_desc = st.text_input("Keterangan Singkat")
                t_amount = st.number_input("Jumlah Uang (Rp)", min_value=0.0, step=500.0)
                t_type = st.radio("Jenis Transaksi", ["penjualan", "pembelian", "biaya"], format_func=lambda x: x.capitalize())
                t_item = st.text_input("Nama Barang (Opsional, otomatis potong stok jika Penjualan)")
                
                btn_save_trans = st.form_submit_button("SIMPAN TRANSAKSI", use_container_width=True)
                if btn_save_trans:
                    if t_desc and t_amount > 0:
                        cat_map = {"penjualan": "Penjualan", "pembelian": "Pembelian Bahan", "biaya": "Biaya Operasional"}
                        category = cat_map[t_type]
                        
                        # Simpan transaksi
                        db.add_transaction(st.session_state.username, t_date.strftime("%Y-%m-%d"), t_desc, t_amount, t_type, category, t_item if t_item else None)
                        
                        # Logika kurangi stok otomatis
                        if t_item and t_type == "penjualan":
                            success, msg = db.adjust_stock(st.session_state.username, t_item, "keluar", 1, f"Penjualan Otomatis: {t_desc}")
                        
                        st.success("Transaksi berhasil dicatat!")
                        st.rerun()
                    else:
                        st.error("Keterangan dan Jumlah Uang wajib diisi!")
                        
        with col_t2:
            st.subheader("📋 Riwayat Buku Kas")
            df_trans_view = db.fetch_transactions(st.session_state.username)
            
            if not df_trans_view.empty:
                # Fitur Export CSV
                csv_data = df_trans_view.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(label="📤 Download File Excel/CSV", data=csv_data, file_name=f"transaksi_{st.session_state.username}.csv", mime="text/csv")
                
                # Tabel Transaksi
                st.dataframe(df_trans_view, use_container_width=True, hide_index=True)
                
                # Fitur Hapus Transaksi
                st.write("---")
                st.caption("🗑️ Fitur Hapus Transaksi")
                id_to_delete = st.number_input("Masukkan ID Transaksi untuk dihapus", min_value=1, step=1)
                if st.button("Hapus Transaksi Terpilih"):
                    db.delete_transaction(id_to_delete)
                    st.success(f"Transaksi ID {id_to_delete} berhasil dihapus!")
                    st.rerun()
            else:
                st.info("Belum ada riwayat transaksi.")

    # --------------------------------------------------------
    # TAB 3: STOK BARANG (INVENTORI)
    # --------------------------------------------------------
    with tab3:
        st.header("📦 Gudang & Stok Barang")
        stok_menu = st.radio("Pilih Tindakan Gudang:", ["📋 Lihat & Kelola Barang", "➕ Daftarkan Barang Baru", "🔄 Update Keluar/Masuk Stok"], horizontal=True)
        
        df_inv_view = db.fetch_inventory(st.session_state.username)
        
        if stok_menu == "📋 Lihat & Kelola Barang":
            if not df_inv_view.empty:
                st.dataframe(df_inv_view, use_container_width=True, hide_index=True)
                
                st.write("---")
                c_edit, c_del = st.columns(2)
                with c_edit:
                    st.subheader("✏️ Edit Cepat Data Barang")
                    with st.form("form_edit_inv"):
                        edit_id = st.number_input("Masukkan ID Barang yang ingin diedit", min_value=1, step=1)
                        edit_stock = st.number_input("Jumlah Stok Baru", min_value=0.0)
                        edit_cost = st.number_input("Harga Beli Baru (Rp)", min_value=0.0)
                        edit_sell = st.number_input("Harga Jual Baru (Rp)", min_value=0.0)
                        edit_unit = st.text_input("Satuan Baru", value="pcs")
                        
                        if st.form_submit_button("Simpan Perubahan Data"):
                            db.update_inventory_full(edit_id, edit_stock, edit_cost, edit_sell, edit_unit)
                            st.success("Data barang berhasil diubah!")
                            st.rerun()
                with c_del:
                    st.subheader("🗑️ Hapus Barang dari Sistem")
                    del_id = st.number_input("Masukkan ID Barang yang ingin dihapus total", min_value=1, step=1)
                    if st.button("Hapus Barang Selamanya", type="primary"):
                        db.delete_inventory_item(del_id)
                        st.success("Barang berhasil dihapus!")
                        st.rerun()
            else:
                st.info("Belum ada barang di gudang.")
                
        elif stok_menu == "➕ Daftarkan Barang Baru":
            st.subheader("Form Registrasi Barang Baru")
            with st.form("form_add_inv", clear_on_submit=True):
                i_name = st.text_input("Nama Barang")
                col_i1, col_i2, col_i3 = st.columns(3)
                i_stock = col_i1.number_input("Stok Awal", min_value=0.0, value=0.0)
                i_unit = col_i2.text_input("Satuan (contoh: pcs, kg, botol)", value="pcs")
                i_cost = col_i3.number_input("Harga Modal/Beli (Rp)", min_value=0.0)
                i_sell = st.number_input("Harga Jual Pokok (Rp)", min_value=0.0)
                
                if st.form_submit_button("`TAMBAHKAN BARANG KE GUDANG`"):
                    if i_name:
                        success = db.add_inventory_item(st.session_state.username, i_name, i_stock, i_cost, i_sell, i_unit)
                        if success:
                            st.success(f"Barang '{i_name}' berhasil ditambahkan!")
                            st.rerun()
                        else:
                            st.error("Nama barang sudah ada di sistem!")
                    else:
                        st.error("Nama barang wajib diisi!")
                        
        elif stok_menu == "🔄 Update Keluar/Masuk Stok":
            st.subheader("Log Mutasi Keluar Masuk Barang")
            if not df_inv_view.empty:
                with st.form("form_adjust_stock"):
                    item_select = st.selectbox("Pilih Barang:", df_inv_view['item_name'].tolist())
                    adjust_type = st.radio("Jenis Perubahan:", ["masuk", "keluar"], format_func=lambda x: "➕ Stok Masuk (Pembelian)" if x=='masuk' else "➖ Stok Keluar")
                    adjust_qty = st.number_input("Jumlah Kuantitas", min_value=0.0, step=1.0)
                    
                    if st.form_submit_button("Proses Update Stok"):
                        success, res = db.adjust_stock(st.session_state.username, item_select, adjust_type, adjust_qty, "Penyesuaian Web")
                        if success:
                            st.success(f"Stok berhasil diubah! Stok saat ini: {res}")
                            st.rerun()
                        else:
                            st.error(res)
            else:
                st.info("Daftarkan produk Anda terlebih dahulu.")

    # --------------------------------------------------------
    # TAB 4: KALKULATOR BISNIS
    # --------------------------------------------------------
    with tab4:
        st.header("🧮 Alat Bantu Hitung Keuangan (Kalkulator)")
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.subheader("💵 1. Hitung Harga Pokok Produksi (HPP)")
            mat_cost = st.number_input("Total Biaya Bahan Baku (Rp)", min_value=0.0, step=1000.0)
            lab_cost = st.number_input("Total Biaya Tenaga Kerja (Rp)", min_value=0.0, step=1000.0)
            prod_qty = st.number_input("Jumlah Produk yang Dihasilkan", min_value=1.0, value=1.0, step=1.0)
            
            total_prod_cost = mat_cost + lab_cost
            hpp_per_unit = total_prod_cost / prod_qty
            st.info(f"**🎯 Hasil HPP per Unit:** Rp {hpp_per_unit:,.0f}".replace(",", "."))
            
        with col_c2:
            st.subheader("📈 2. Hitung Rekomendasi Harga Jual")
            base_hpp = st.number_input("Masukkan Modal / HPP per Produk (Rp)", min_value=0.0, value=hpp_per_unit, step=1000.0)
            margin_pct = st.number_input("Target Margin Keuntungan (%)", min_value=0.0, value=30.0, step=5.0)
            
            profit_nominal = base_hpp * (margin_pct / 100)
            rec_selling_price = base_hpp + profit_nominal
            st.success(f"**💵 Rekomendasi Harga Jual:** Rp {rec_selling_price:,.0f}".replace(",", "."))

# ============================================================
# RUN LOGIC
# ============================================================
if not st.session_state.logged_in:
    show_auth_screen()
else:
    show_main_app()
