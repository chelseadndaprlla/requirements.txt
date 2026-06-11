import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import hashlib

# Konfigurasi Halaman Streamlit
st.set_page_config(page_title="Buku Kas & Stok UMKM", page_icon="📊", layout="wide")

# ============================================================
# 🗄️ DATABASE LAYER (SQLite)
# ============================================================
class Database:
    def __init__(self, db_name="umkm_budget.db"):
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

# Inisialisasi Database
if 'db' not in st.session_state:
    st.session_state.db = Database()
db = st.session_state.db

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.business_name = None

def show_auth_screen():
    st.title("📊 BUKU KAS & STOK UMKM")
    st.subheader("Catat Keuangan & Stok Bisnis dengan Mudah")
    tab_login, tab_register = st.tabs(["🔓 Masuk", "📝 Daftar Akun Baru"])
    with tab_login:
        with st.form("form_login"):
            username = st.text_input("Nama Pengguna (Username)")
            password = st.text_input("Kata Sandi", type="password")
            btn_login = st.form_submit_button("MASUK", use_container_width=True)
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
                if len(reg_username) < 3 or len(reg_password) < 4:
                    st.error("Username minimal 3 karakter, Kata Sandi minimal 4 karakter!")
                elif reg_username and reg_password:
                    success, msg = db.register_user(reg_username, reg_password, reg_b_name or "Usaha Saya")
                    if success:
                        st.success(msg + " Silakan beralih ke tab Masuk.")
                    else:
                        st.error(msg)
                else:
                    st.warning("Mohon isi semua kolom!")

def show_main_app():
    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.title(f"📊 {st.session_state.business_name}")
    with col_h2:
        st.write("")
        if st.button("🚪 Keluar", type="primary", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.business_name = None
            st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["🏠 Beranda", "💰 Catat Keuangan", "📦 Stok Barang", "🧮 Hitung HPP"])

    with tab1:
        st.header(f"📅 Ringkasan Hari Ini ({datetime.now().strftime('%d %B %Y')})")
        df_trans = db.fetch_transactions(st.session_state.username)
        df_inv = db.fetch_inventory(st.session_state.username)
        today_str = datetime.now().strftime("%Y-%m-%d")
        df_today = df_trans[df_trans['date'] == today_str] if not df_trans.empty else pd.DataFrame()
        income_today = df_today[df_today['type'] == 'penjualan']['amount'].sum() if not df_today.empty else 0
        expense_today = df_today[df_today['type'].isin(['pembelian', 'biaya'])]['amount'].sum() if not df_today.empty else 0
        profit_today = income_today - expense_today
        
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
                    st.success("Semua stok aman!")
            else:
                st.info("Belum ada data barang.")
        with col_b2:
            st.subheader("📋 5 Transaksi Terakhir")
            if not df_trans.empty:
                st.dataframe(df_trans.head(5)[['date', 'description', 'amount', 'type']], use_container_width=True, hide_index=True)
            else:
                st.info("Belum ada transaksi.")

    with tab2:
        st.header("💰 Buku Kas")
        col_t1, col_t2 = st.columns([1, 2])
        with col_t1:
            st.subheader("✍️ Tambah Transaksi")
            with st.form("form_trans", clear_on_submit=True):
                t_date = st.date_input("Tanggal", datetime.now())
                t_desc = st.text_input("Keterangan")
                t_amount = st.number_input("Jumlah (Rp)", min_value=0.0, step=500.0)
                t_type = st.radio("Jenis", ["penjualan", "pembelian", "biaya"])
                t_item = st.text_input("Nama Barang (Opsional)")
                if st.form_submit_button("SIMPAN"):
                    if t_desc and t_amount > 0:
                        cat_map = {"penjualan": "Penjualan", "pembelian": "Pembelian", "biaya": "Biaya"}
                        db.add_transaction(st.session_state.username, t_date.strftime("%Y-%m-%d"), t_desc, t_amount, t_type, cat_map[t_type], t_item if t_item else None)
                        if t_item and t_type == "penjualan":
                            db.adjust_stock(st.session_state.username, t_item, "keluar", 1, f"Penjualan: {t_desc}")
                        st.success("Transaksi disimpan!")
                        st.rerun()
        with col_t2:
            st.subheader("📋 Riwayat")
            df_trans_view = db.fetch_transactions(st.session_state.username)
            if not df_trans_view.empty:
                st.dataframe(df_trans_view, use_container_width=True, hide_index=True)
                id_to_delete = st.number_input("ID untuk dihapus", min_value=1, step=1)
                if st.button("Hapus"):
                    db.delete_transaction(id_to_delete)
                    st.rerun()

    with tab3:
        st.header("📦 Gudang Stok")
        stok_menu = st.radio("Menu Gudang:", ["📋 Lihat Barang", "➕ Tambah Baru", "🔄 Mutasi Stok"], horizontal=True)
        df_inv_view = db.fetch_inventory(st.session_state.username)
        if stok_menu == "📋 Lihat Barang":
            if not df_inv_view.empty:
                st.dataframe(df_inv_view, use_container_width=True, hide_index=True)
            else:
                st.info("Gudang kosong.")
        elif stok_menu == "➕ Tambah Baru":
            with st.form("add_new"):
                i_name = st.text_input("Nama Barang")
                i_stock = st.number_input("Stok Awal", min_value=0.0)
                i_unit = st.text_input("Satuan", value="pcs")
                i_cost = st.number_input("Harga Beli", min_value=0.0)
                i_sell = st.number_input("Harga Jual", min_value=0.0)
                if st.form_submit_button("TAMBAH"):
                    if i_name and db.add_inventory_item(st.session_state.username, i_name, i_stock, i_cost, i_sell, i_unit):
                        st.success("Barang ditambah!")
                        st.rerun()
        elif stok_menu == "🔄 Mutasi Stok":
            if not df_inv_view.empty:
                with st.form("mutasi"):
                    item_select = st.selectbox("Barang", df_inv_view['item_name'].tolist())
                    adjust_type = st.radio("Aksi", ["masuk", "keluar"])
                    adjust_qty = st.number_input("Jumlah", min_value=0.0)
                    if st.form_submit_button("PROSES"):
                        db.adjust_stock(st.session_state.username, item_select, adjust_type, adjust_qty, "Manual")
                        st.success("Stok diubah!")
                        st.rerun()

    with tab4:
        st.header("🧮 Kalkulator")
        mat_cost = st.number_input("Bahan Baku", min_value=0.0)
        lab_cost = st.number_input("Tenaga Kerja", min_value=0.0)
        prod_qty = st.number_input("Jumlah Hasil", min_value=1.0, value=1.0)
        hpp = (mat_cost + lab_cost) / prod_qty
        st.info(f"HPP per Unit: Rp {hpp:,.0f}")

if not st.session_state.logged_in:
    show_auth_screen()
else:
    show_main_app()
