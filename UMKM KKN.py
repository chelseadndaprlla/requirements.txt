import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import hashlib

# ============================================================
# 🗄️ DATABASE LAYER (UMKM + Stok + Multi-User)
# ============================================================
class Database:
    def __init__(self, db_name="umkm_budget.db"):
        self.conn = sqlite3.connect(db_name)
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

    # === TRANSAKSI ===
    def add_transaction(self, username, date, desc, amount, trans_type, category, 
                       item_name=None, quantity=0, unit_price=0):
        self.cursor.execute(
            """INSERT INTO transactions 
               (username, date, description, amount, type, category, item_name, quantity, unit_price) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, date, desc, amount, trans_type, category, item_name, quantity, unit_price)
        )
        self.conn.commit()

    def fetch_transactions(self, username, date_filter=None, trans_type=None):
        query = "SELECT id, date, description, amount, type, category, item_name, quantity FROM transactions WHERE username = ?"
        params = [username]
        
        if date_filter:
            query += " AND date = ?"
            params.append(date_filter)
        if trans_type:
            query += " AND type = ?"
            params.append(trans_type)
            
        query += " ORDER BY date DESC, id DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def delete_transaction(self, trans_id):
        self.cursor.execute("DELETE FROM transactions WHERE id = ?", (trans_id,))
        self.conn.commit()

    # === INVENTORI / STOK ===
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

    def update_inventory_item(self, item_id, stock_qty, cost_price, selling_price, unit):
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
        self.cursor.execute(
            "SELECT id, item_name, stock_quantity, cost_price, selling_price, unit, last_updated FROM inventory WHERE username = ? ORDER BY item_name",
            (username,)
        )
        return self.cursor.fetchall()

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
                return False, f"Stok tidak cukup! Stok tersedia: {current_stock}"
            new_stock = current_stock - quantity
        else:  # penyesuaian
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

    def fetch_stock_history(self, username, days=7):
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        self.cursor.execute(
            """SELECT date, item_name, change_type, quantity, note 
               FROM stock_history WHERE username = ? AND date >= ?
               ORDER BY date DESC""",
            (username, cutoff_date)
        )
        return self.cursor.fetchall()

    def export_csv(self, username, filepath):
        df = pd.read_sql_query(
            f"""SELECT date, description, amount, type, category, item_name, quantity 
                FROM transactions WHERE username = '{username}'""", 
            self.conn
        )
        df.to_csv(filepath, index=False, encoding='utf-8-sig')

    def close(self):
        self.conn.close()


# ============================================================
# 🖥️ GUI APLIKASI UMKM - RAMAH ORANG TUA
# ============================================================
class UMKMBudgetApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📊 Buku Kas & Stok UMKM")
        self.root.configure(bg="#f0f4f8")
        self.root.geometry("1200x800")
        
        self.db = Database()
        self.current_user = None
        self.business_name = None
        
        self.setup_styles()
        self.show_auth_screen()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Font besar untuk orang tua
        style.configure("TNotebook", background="#f0f4f8", borderwidth=0)
        style.configure("TNotebook.Tab", background="#CFD8DC", padding=[20, 12], 
                       font=("Segoe UI", 13, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#10B981")], 
                 foreground=[("selected", "white")])
        
        style.configure("Treeview", background="white", foreground="#333333", 
                       rowheight=40, fieldbackground="white", font=("Segoe UI", 12))
        style.configure("Treeview.Heading", font=("Segoe UI", 12, "bold"), 
                       background="#10B981", foreground="white", padding=8)
        style.map("Treeview", background=[('selected', '#A7F3D0')], foreground=[('selected', 'black')])

    # ========================================
    # 🔐 LOGIN & REGISTER
    # ========================================
    def show_auth_screen(self):
        for widget in self.root.winfo_children(): 
            widget.destroy()
            
        frame = tk.Frame(self.root, bg="#f0f4f8")
        frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        card = tk.Frame(frame, bg="white", padx=50, pady=50, 
                       highlightbackground="#E2E8F0", highlightthickness=2)
        card.pack(pady=20)

        tk.Label(card, text="📊 BUKU KAS UMKM", font=("Segoe UI", 28, "bold"), 
                fg="#10B981", bg="white").pack(pady=(0, 10))
        tk.Label(card, text="Catat Keuangan & Stok dengan Mudah", 
                font=("Segoe UI", 13), fg="#64748B", bg="white").pack(pady=(0, 40))

        tk.Label(card, text="Nama Pengguna:", font=("Segoe UI", 12, "bold"), 
                bg="white", fg="#333").pack(anchor=tk.W)
        self.ent_user = tk.Entry(card, font=("Segoe UI", 14), width=35, 
                                bg="#F8FAFC", relief=tk.SOLID, bd=2)
        self.ent_user.pack(pady=(5, 20), ipady=8)

        tk.Label(card, text="Kata Sandi:", font=("Segoe UI", 12, "bold"), 
                bg="white", fg="#333").pack(anchor=tk.W)
        self.ent_pass = tk.Entry(card, font=("Segoe UI", 14), width=35, show="*", 
                                bg="#F8FAFC", relief=tk.SOLID, bd=2)
        self.ent_pass.pack(pady=(5, 20), ipady=8)

        tk.Label(card, text="Nama Usaha (untuk daftar baru):", font=("Segoe UI", 11), 
                bg="white", fg="#64748B").pack(anchor=tk.W)
        self.ent_business = tk.Entry(card, font=("Segoe UI", 13), width=35, 
                                    bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_business.pack(pady=(5, 30), ipady=6)

        btn_frame = tk.Frame(card, bg="white")
        btn_frame.pack(fill=tk.X)
        
        tk.Button(btn_frame, text="🔓 MASUK", command=self.process_login, 
                 bg="#10B981", fg="white", font=("Segoe UI", 14, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=20, pady=10).pack(fill=tk.X, pady=8)
        
        tk.Button(btn_frame, text="📝 DAFTAR AKUN BARU", command=self.process_register, 
                 bg="#3B82F6", fg="white", font=("Segoe UI", 13, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=20, pady=8).pack(fill=tk.X, pady=8)

    def process_login(self):
        username = self.ent_user.get().strip()
        password = self.ent_pass.get().strip()
        
        if not username or not password:
            messagebox.showwarning("Peringatan", "Isi nama pengguna dan kata sandi!")
            return
            
        success, business_name = self.db.login_user(username, password)
        if success:
            self.current_user = username
            self.business_name = business_name
            self.show_main_app()
        else:
            messagebox.showerror("Gagal", "Nama pengguna atau kata sandi salah!")

    def process_register(self):
        username = self.ent_user.get().strip()
        password = self.ent_pass.get().strip()
        business_name = self.ent_business.get().strip() or "Usaha Saya"
        
        if len(username) < 3 or len(password) < 4:
            messagebox.showwarning("Peringatan", 
                                 "Nama pengguna minimal 3 huruf, kata sandi minimal 4 huruf!")
            return
            
        success, msg = self.db.register_user(username, password, business_name)
        if success:
            messagebox.showinfo("Sukses", "Akun berhasil dibuat! Silakan masuk.")
        else:
            messagebox.showerror("Gagal", msg)

    def logout(self):
        if messagebox.askyesno("Keluar", "Yakin ingin keluar?"):
            self.current_user = None
            self.show_auth_screen()

    # ========================================
    # 🏠 APLIKASI UTAMA
    # ========================================
    def show_main_app(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        # Header
        header = tk.Frame(self.root, bg="#10B981", height=80)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text=f"📊 {self.business_name}", 
                font=("Segoe UI", 20, "bold"), bg="#10B981", fg="white").pack(side=tk.LEFT, padx=30, pady=20)
        
        tk.Button(header, text="🚪 Keluar", command=self.logout, 
                 bg="#EF4444", fg="white", font=("Segoe UI", 12, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=15, pady=5).pack(side=tk.RIGHT, padx=30)

        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        self.tab_dashboard = tk.Frame(self.notebook, bg="#f0f4f8")
        self.tab_transactions = tk.Frame(self.notebook, bg="#f0f4f8")
        self.tab_inventory = tk.Frame(self.notebook, bg="#f0f4f8")
        self.tab_calculator = tk.Frame(self.notebook, bg="#f0f4f8")

        self.notebook.add(self.tab_dashboard, text=" 🏠 Beranda  ")
        self.notebook.add(self.tab_transactions, text=" 💰 Catat Keuangan  ")
        self.notebook.add(self.tab_inventory, text=" 📦 Stok Barang  ")
        self.notebook.add(self.tab_calculator, text=" 🧮 Hitung HPP & Harga  ")

        self.build_dashboard_tab()
        self.build_transactions_tab()
        self.build_inventory_tab()
        self.build_calculator_tab()

        self.refresh_data()

    # ========================================
    # 🏠 TAB 1: BERANDA / DASHBOARD
    # ========================================
    def build_dashboard_tab(self):
        # Ringkasan Hari Ini
        today_frame = tk.Frame(self.tab_dashboard, bg="white", padx=30, pady=20,
                              highlightbackground="#E2E8F0", highlightthickness=2)
        today_frame.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        tk.Label(today_frame, text=f"📅 Ringkasan Hari Ini - {datetime.now().strftime('%d %B %Y')}", 
                font=("Segoe UI", 16, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W)
        
        summary_frame = tk.Frame(today_frame, bg="white")
        summary_frame.pack(fill=tk.X, pady=15)
        
        self.card_today_income = tk.Frame(summary_frame, bg="#10B981", padx=25, pady=20)
        self.card_today_income.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        tk.Label(self.card_today_income, text="💵 Penjualan Hari Ini", 
                font=("Segoe UI", 12), bg="#10B981", fg="white").pack()
        self.lbl_today_income = tk.Label(self.card_today_income, text="Rp 0", 
                                        font=("Segoe UI", 18, "bold"), bg="#10B981", fg="white")
        self.lbl_today_income.pack()
        
        self.card_today_expense = tk.Frame(summary_frame, bg="#EF4444", padx=25, pady=20)
        self.card_today_expense.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        tk.Label(self.card_today_expense, text="💸 Pembelian & Biaya Hari Ini", 
                font=("Segoe UI", 12), bg="#EF4444", fg="white").pack()
        self.lbl_today_expense = tk.Label(self.card_today_expense, text="Rp 0", 
                                         font=("Segoe UI", 18, "bold"), bg="#EF4444", fg="white")
        self.lbl_today_expense.pack()
        
        self.card_today_profit = tk.Frame(summary_frame, bg="#3B82F6", padx=25, pady=20)
        self.card_today_profit.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        tk.Label(self.card_today_profit, text="💰 Untung Hari Ini", 
                font=("Segoe UI", 12), bg="#3B82F6", fg="white").pack()
        self.lbl_today_profit = tk.Label(self.card_today_profit, text="Rp 0", 
                                        font=("Segoe UI", 18, "bold"), bg="#3B82F6", fg="white")
        self.lbl_today_profit.pack()

        # Stok Menipis
        stock_frame = tk.Frame(self.tab_dashboard, bg="white", padx=30, pady=20,
                              highlightbackground="#E2E8F0", highlightthickness=2)
        stock_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        tk.Label(stock_frame, text="⚠️ Peringatan Stok Menipis", 
                font=("Segoe UI", 14, "bold"), bg="white", fg="#F59E0B").pack(anchor=tk.W)
        
        self.tree_low_stock = ttk.Treeview(stock_frame, columns=("Item", "Stok", "Satuan"), 
                                          show="headings", height=5)
        self.tree_low_stock.heading("Item", text="Nama Barang")
        self.tree_low_stock.heading("Stok", text="Jumlah Stok")
        self.tree_low_stock.heading("Satuan", text="Satuan")
        self.tree_low_stock.column("Item", width=300, anchor=tk.W)
        self.tree_low_stock.column("Stok", width=150, anchor=tk.CENTER)
        self.tree_low_stock.column("Satuan", width=100, anchor=tk.CENTER)
        self.tree_low_stock.pack(fill=tk.BOTH, expand=True, pady=10)

        # Transaksi Terakhir
        recent_frame = tk.Frame(self.tab_dashboard, bg="white", padx=30, pady=20,
                               highlightbackground="#E2E8F0", highlightthickness=2)
        recent_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 20))
        
        tk.Label(recent_frame, text="📋 Transaksi Terakhir", 
                font=("Segoe UI", 14, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W)
        
        self.tree_recent = ttk.Treeview(recent_frame, 
                                       columns=("Tanggal", "Keterangan", "Jumlah", "Tipe"), 
                                       show="headings", height=6)
        self.tree_recent.heading("Tanggal", text="Tanggal")
        self.tree_recent.heading("Keterangan", text="Keterangan")
        self.tree_recent.heading("Jumlah", text="Jumlah (Rp)")
        self.tree_recent.heading("Tipe", text="Tipe")
        self.tree_recent.column("Tanggal", width=120, anchor=tk.CENTER)
        self.tree_recent.column("Keterangan", width=350, anchor=tk.W)
        self.tree_recent.column("Jumlah", width=150, anchor=tk.E)
        self.tree_recent.column("Tipe", width=120, anchor=tk.CENTER)
        self.tree_recent.pack(fill=tk.BOTH, expand=True, pady=10)

    # ========================================
    # 💰 TAB 2: CATAT KEUANGAN
    # ========================================
    def build_transactions_tab(self):
        main_pane = tk.PanedWindow(self.tab_transactions, orient=tk.HORIZONTAL, 
                                  bg="#f0f4f8", sashwidth=10)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Form Input
        form_card = tk.Frame(main_pane, bg="white", padx=30, pady=30,
                            highlightbackground="#E2E8F0", highlightthickness=2)
        main_pane.add(form_card, minsize=400)

        tk.Label(form_card, text="✍️ Catat Transaksi Baru", 
                font=("Segoe UI", 16, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W, pady=(0, 20))

        def make_entry(parent, label_text, default_val=""):
            tk.Label(parent, text=label_text, font=("Segoe UI", 12, "bold"), 
                    bg="white", fg="#64748B").pack(anchor=tk.W, pady=(10, 5))
            ent = tk.Entry(parent, font=("Segoe UI", 13), bg="#F8FAFC", relief=tk.SOLID, bd=2)
            ent.pack(fill=tk.X, ipady=8)
            if default_val: 
                ent.insert(0, default_val)
            return ent

        self.ent_date = make_entry(form_card, "📅 Tanggal (TTTT-BB-HH)", 
                                  datetime.now().strftime("%Y-%m-%d"))
        self.ent_desc = make_entry(form_card, "📝 Keterangan")
        self.ent_amount = make_entry(form_card, "💰 Jumlah Uang (Rp)")
        
        tk.Label(form_card, text="📌 Jenis Transaksi:", font=("Segoe UI", 12, "bold"), 
                bg="white", fg="#64748B").pack(anchor=tk.W, pady=(15, 5))
        
        type_frame = tk.Frame(form_card, bg="white")
        type_frame.pack(fill=tk.X)
        self.var_type = tk.StringVar(value="penjualan")
        
        tk.Radiobutton(type_frame, text="💵 Penjualan", variable=self.var_type, 
                      value="penjualan", bg="white", font=("Segoe UI", 12),
                      activebackground="white").pack(side=tk.LEFT, padx=(0, 15))
        tk.Radiobutton(type_frame, text="🛒 Pembelian", variable=self.var_type, 
                      value="pembelian", bg="white", font=("Segoe UI", 12),
                      activebackground="white").pack(side=tk.LEFT, padx=(0, 15))
        tk.Radiobutton(type_frame, text="💸 Biaya Lain", variable=self.var_type, 
                      value="biaya", bg="white", font=("Segoe UI", 12),
                      activebackground="white").pack(side=tk.LEFT)

        tk.Label(form_card, text="📦 Nama Barang (opsional):", 
                font=("Segoe UI", 11), bg="white", fg="#64748B").pack(anchor=tk.W, pady=(15, 5))
        self.ent_item = tk.Entry(form_card, font=("Segoe UI", 12), 
                                bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_item.pack(fill=tk.X, ipady=6)

        tk.Button(form_card, text="✔️ SIMPAN TRANSAKSI", command=self.save_transaction, 
                 bg="#10B981", fg="white", font=("Segoe UI", 14, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=20, pady=12).pack(fill=tk.X, pady=(30, 10))

        # Tabel Riwayat
        table_card = tk.Frame(main_pane, bg="white", padx=20, pady=20,
                             highlightbackground="#E2E8F0", highlightthickness=2)
        main_pane.add(table_card, minsize=600)

        action_frame = tk.Frame(table_card, bg="white")
        action_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(action_frame, text="📋 Riwayat Transaksi", 
                font=("Segoe UI", 16, "bold"), bg="white", fg="#1F2937").pack(side=tk.LEFT)
        
        btn_style = {"font": ("Segoe UI", 11, "bold"), "fg": "white", "relief": tk.FLAT, 
                    "cursor": "hand2", "padx": 12, "pady": 5}
        
        tk.Button(action_frame, text="🗑️ Hapus", command=self.delete_selected, 
                 bg="#EF4444", **btn_style).pack(side=tk.RIGHT, padx=3)
        tk.Button(action_frame, text="📤 Export CSV", command=self.export_data, 
                 bg="#F59E0B", **btn_style).pack(side=tk.RIGHT, padx=3)
        tk.Button(action_frame, text="🔄 Refresh", command=self.refresh_data, 
                 bg="#64748B", **btn_style).pack(side=tk.RIGHT, padx=3)

        self.tree_trans = ttk.Treeview(table_card, 
                                      columns=("ID", "Tanggal", "Keterangan", "Jumlah", "Tipe", "Kategori", "Barang"), 
                                      show="headings", height=18)
        self.tree_trans["displaycolumns"] = ("Tanggal", "Keterangan", "Jumlah", "Tipe", "Kategori", "Barang")
        
        cols = {"Tanggal": 110, "Keterangan": 250, "Jumlah": 130, "Tipe": 100, "Kategori": 120, "Barang": 150}
        for col, width in cols.items():
            self.tree_trans.heading(col, text=col.upper())
            self.tree_trans.column(col, width=width, anchor=tk.CENTER if col != "Keterangan" else tk.W)
        
        scrollbar = ttk.Scrollbar(table_card, orient=tk.VERTICAL, command=self.tree_trans.yview)
        self.tree_trans.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_trans.pack(fill=tk.BOTH, expand=True)

    # ========================================
    # 📦 TAB 3: STOK BARANG
    # ========================================
    def build_inventory_tab(self):
        main_frame = tk.Frame(self.tab_inventory, bg="#f0f4f8")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Form Tambah/Edit Barang
        form_card = tk.Frame(main_frame, bg="white", padx=30, pady=25,
                            highlightbackground="#E2E8F0", highlightthickness=2)
        form_card.pack(fill=tk.X, pady=(0, 15))

        tk.Label(form_card, text="📦 Kelola Stok Barang", 
                font=("Segoe UI", 16, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W, pady=(0, 15))

        input_row1 = tk.Frame(form_card, bg="white")
        input_row1.pack(fill=tk.X, pady=5)
        
        tk.Label(input_row1, text="Nama Barang:", font=("Segoe UI", 11, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_inv_name = tk.Entry(input_row1, font=("Segoe UI", 12), width=25, 
                                    bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_inv_name.pack(side=tk.LEFT, padx=5, ipady=5)
        
        tk.Label(input_row1, text="Stok:", font=("Segoe UI", 11, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_inv_stock = tk.Entry(input_row1, font=("Segoe UI", 12), width=10, 
                                     bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_inv_stock.pack(side=tk.LEFT, padx=5, ipady=5)
        
        tk.Label(input_row1, text="Satuan:", font=("Segoe UI", 11, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_inv_unit = tk.Entry(input_row1, font=("Segoe UI", 12), width=10, 
                                    bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_inv_unit.insert(0, "pcs")
        self.ent_inv_unit.pack(side=tk.LEFT, padx=5, ipady=5)

        input_row2 = tk.Frame(form_card, bg="white")
        input_row2.pack(fill=tk.X, pady=5)
        
        tk.Label(input_row2, text="Harga Beli (Rp):", font=("Segoe UI", 11, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_inv_cost = tk.Entry(input_row2, font=("Segoe UI", 12), width=15, 
                                    bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_inv_cost.pack(side=tk.LEFT, padx=5, ipady=5)
        
        tk.Label(input_row2, text="Harga Jual (Rp):", font=("Segoe UI", 11, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_inv_sell = tk.Entry(input_row2, font=("Segoe UI", 12), width=15, 
                                    bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_inv_sell.pack(side=tk.LEFT, padx=5, ipady=5)

        btn_row = tk.Frame(form_card, bg="white")
        btn_row.pack(fill=tk.X, pady=10)
        
        tk.Button(btn_row, text="➕ Tambah Barang", command=self.add_inventory_item, 
                 bg="#10B981", fg="white", font=("Segoe UI", 12, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=15, pady=8).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_row, text="🔄 Update Stok", command=self.update_stock_dialog, 
                 bg="#3B82F6", fg="white", font=("Segoe UI", 12, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=15, pady=8).pack(side=tk.LEFT, padx=5)

        # Tabel Inventori
        table_card = tk.Frame(main_frame, bg="white", padx=20, pady=20,
                             highlightbackground="#E2E8F0", highlightthickness=2)
        table_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(table_card, text="📋 Daftar Barang & Stok", 
                font=("Segoe UI", 14, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W, pady=(0, 10))

        self.tree_inv = ttk.Treeview(table_card, 
                                    columns=("ID", "Nama", "Stok", "Satuan", "Harga Beli", "Harga Jual", "Terakhir Update"), 
                                    show="headings", height=12)
        self.tree_inv["displaycolumns"] = ("Nama", "Stok", "Satuan", "Harga Beli", "Harga Jual", "Terakhir Update")
        
        cols = {"Nama": 250, "Stok": 100, "Satuan": 80, "Harga Beli": 130, "Harga Jual": 130, "Terakhir Update": 150}
        for col, width in cols.items():
            self.tree_inv.heading(col, text=col.upper())
            self.tree_inv.column(col, width=width, anchor=tk.CENTER if col != "Nama" else tk.W)
        
        scrollbar = ttk.Scrollbar(table_card, orient=tk.VERTICAL, command=self.tree_inv.yview)
        self.tree_inv.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_inv.pack(fill=tk.BOTH, expand=True)

        btn_frame = tk.Frame(table_card, bg="white")
        btn_frame.pack(fill=tk.X, pady=10)
        
        tk.Button(btn_frame, text="✏️ Edit Barang", command=self.edit_inventory_item, 
                 bg="#F59E0B", fg="white", font=("Segoe UI", 11, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=15, pady=6).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="🗑️ Hapus Barang", command=self.delete_inventory_item, 
                 bg="#EF4444", fg="white", font=("Segoe UI", 11, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=15, pady=6).pack(side=tk.LEFT, padx=5)

    # ========================================
    # 🧮 TAB 4: KALKULATOR HPP & HARGA JUAL
    # ========================================
    def build_calculator_tab(self):
        main_frame = tk.Frame(self.tab_calculator, bg="#f0f4f8")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Kalkulator HPP
        hpp_card = tk.Frame(main_frame, bg="white", padx=30, pady=25,
                           highlightbackground="#E2E8F0", highlightthickness=2)
        hpp_card.pack(fill=tk.X, pady=(0, 15))

        tk.Label(hpp_card, text="🧮 Kalkulator HPP (Harga Pokok Produksi)", 
                font=("Segoe UI", 16, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W, pady=(0, 15))

        tk.Label(hpp_card, text="Hitung modal yang dibutuhkan untuk membuat 1 produk:", 
                font=("Segoe UI", 11), bg="white", fg="#64748B").pack(anchor=tk.W, pady=(0, 15))

        input_frame = tk.Frame(hpp_card, bg="white")
        input_frame.pack(fill=tk.X, pady=5)

        tk.Label(input_frame, text="💰 Total Biaya Bahan Baku (Rp):", 
                font=("Segoe UI", 12, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_hpp_material = tk.Entry(input_frame, font=("Segoe UI", 13), width=15, 
                                        bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_hpp_material.pack(side=tk.LEFT, padx=5, ipady=6)

        input_frame2 = tk.Frame(hpp_card, bg="white")
        input_frame2.pack(fill=tk.X, pady=5)

        tk.Label(input_frame2, text="⏰ Total Biaya Tenaga Kerja (Rp):", 
                font=("Segoe UI", 12, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_hpp_labor = tk.Entry(input_frame2, font=("Segoe UI", 13), width=15, 
                                     bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_hpp_labor.pack(side=tk.LEFT, padx=5, ipady=6)

        input_frame3 = tk.Frame(hpp_card, bg="white")
        input_frame3.pack(fill=tk.X, pady=5)

        tk.Label(input_frame3, text="🏭 Total Biaya Operasional (Rp):", 
                font=("Segoe UI", 12, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_hpp_overhead = tk.Entry(input_frame3, font=("Segoe UI", 13), width=15, 
                                        bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_hpp_overhead.pack(side=tk.LEFT, padx=5, ipady=6)

        input_frame4 = tk.Frame(hpp_card, bg="white")
        input_frame4.pack(fill=tk.X, pady=5)

        tk.Label(input_frame4, text="📦 Jumlah Produk yang Dihasilkan:", 
                font=("Segoe UI", 12, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_hpp_qty = tk.Entry(input_frame4, font=("Segoe UI", 13), width=15, 
                                   bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_hpp_qty.pack(side=tk.LEFT, padx=5, ipady=6)

        tk.Button(hpp_card, text="🔢 HITUNG HPP", command=self.calculate_hpp, 
                 bg="#8B5CF6", fg="white", font=("Segoe UI", 13, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=20, pady=10).pack(pady=15)

        self.lbl_hpp_result = tk.Label(hpp_card, text="", font=("Segoe UI", 14, "bold"), 
                                      bg="#F0FDF4", fg="#10B981", padx=20, pady=15, 
                                      relief=tk.RAISED, justify=tk.LEFT)
        self.lbl_hpp_result.pack(fill=tk.X, pady=10)

        # Kalkulator Harga Jual
        sell_card = tk.Frame(main_frame, bg="white", padx=30, pady=25,
                            highlightbackground="#E2E8F0", highlightthickness=2)
        sell_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(sell_card, text="💵 Kalkulator Harga Jual & Keuntungan", 
                font=("Segoe UI", 16, "bold"), bg="white", fg="#1F2937").pack(anchor=tk.W, pady=(0, 15))

        input_frame5 = tk.Frame(sell_card, bg="white")
        input_frame5.pack(fill=tk.X, pady=5)

        tk.Label(input_frame5, text="💰 HPP per Produk (Rp):", 
                font=("Segoe UI", 12, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_sell_hpp = tk.Entry(input_frame5, font=("Segoe UI", 13), width=15, 
                                    bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_sell_hpp.pack(side=tk.LEFT, padx=5, ipady=6)

        tk.Label(input_frame5, text="📈 Persen Keuntungan (%):", 
                font=("Segoe UI", 12, "bold"), bg="white").pack(side=tk.LEFT, padx=5)
        self.ent_sell_margin = tk.Entry(input_frame5, font=("Segoe UI", 13), width=10, 
                                       bg="#F8FAFC", relief=tk.SOLID, bd=1)
        self.ent_sell_margin.insert(0, "30")
        self.ent_sell_margin.pack(side=tk.LEFT, padx=5, ipady=6)

        tk.Button(sell_card, text="💵 HITUNG HARGA JUAL", command=self.calculate_selling_price, 
                 bg="#10B981", fg="white", font=("Segoe UI", 13, "bold"), 
                 relief=tk.FLAT, cursor="hand2", padx=20, pady=10).pack(pady=15)

        self.lbl_sell_result = tk.Label(sell_card, text="", font=("Segoe UI", 14, "bold"), 
                                       bg="#F0FDF4", fg="#10B981", padx=20, pady=15, 
                                       relief=tk.RAISED, justify=tk.LEFT)
        self.lbl_sell_result.pack(fill=tk.X, pady=10)

    # ========================================
    # 🔧 FUNGSI-FUNGSI
    # ========================================
    def save_transaction(self):
        date = self.ent_date.get()
        desc = self.ent_desc.get()
        amount_str = self.ent_amount.get()
        trans_type = self.var_type.get()
        item_name = self.ent_item.get().strip()
        
        if not all([date, desc, amount_str]):
            messagebox.showwarning("Peringatan", "Isi Tanggal, Keterangan, dan Jumlah!")
            return
        
        try:
            amount = float(amount_str)
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Format Salah", "Tanggal harus TTTT-BB-HH dan Jumlah harus angka!")
            return
        
        category_map = {
            "penjualan": "Penjualan",
            "pembelian": "Pembelian Bahan",
            "biaya": "Biaya Operasional"
        }
        category = category_map.get(trans_type, "Lainnya")
        
        self.db.add_transaction(self.current_user, date, desc, amount, trans_type, 
                               category, item_name if item_name else None)
        
        # Jika ada nama barang dan transaksi penjualan, kurangi stok otomatis
        if item_name and trans_type == "penjualan":
            success, msg = self.db.adjust_stock(self.current_user, item_name, "keluar", 1, 
                                               f"Penjualan: {desc}")
            if not success:
                messagebox.showwarning("Stok", f"Peringatan: {msg}")
        
        messagebox.showinfo("Sukses", "Transaksi berhasil disimpan!")
        
        self.ent_desc.delete(0, tk.END)
        self.ent_amount.delete(0, tk.END)
        self.ent_item.delete(0, tk.END)
        
        self.refresh_data()

    def delete_selected(self):
        selected = self.tree_trans.selection()
        if not selected:
            messagebox.showwarning("Peringatan", "Pilih transaksi yang ingin dihapus!")
            return
        if messagebox.askyesno("Konfirmasi", "Yakin ingin menghapus transaksi ini?"):
            for item in selected:
                trans_id = self.tree_trans.item(item, "values")[0]
                self.db.delete_transaction(trans_id)
            self.refresh_data()

    def refresh_data(self):
        # Refresh tabel transaksi
        for row in self.tree_trans.get_children():
            self.tree_trans.delete(row)
        
        data = self.db.fetch_transactions(self.current_user)
        for row in data:
            rp_amount = f"Rp {row[3]:,.0f}".replace(",", ".")
            item_info = f" [{row[6]}]" if row[6] else ""
            self.tree_trans.insert("", tk.END, values=(row[0], row[1], row[2], rp_amount, 
                                                      row[4].capitalize(), row[5], item_info))
        
        # Refresh inventori
        for row in self.tree_inv.get_children():
            self.tree_inv.delete(row)
        
        inventory = self.db.fetch_inventory(self.current_user)
        for item in inventory:
            cost_rp = f"Rp {item[3]:,.0f}".replace(",", ".")
            sell_rp = f"Rp {item[4]:,.0f}".replace(",", ".")
            self.tree_inv.insert("", tk.END, values=(item[0], item[1], item[2], item[5], 
                                                    cost_rp, sell_rp, item[6]))
        
        # Update dashboard
        self.update_dashboard()

    def update_dashboard(self):
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Transaksi hari ini
        today_data = self.db.fetch_transactions(self.current_user, date_filter=today)
        
        today_income = sum(t[3] for t in today_data if t[4] == 'penjualan')
        today_expense = sum(t[3] for t in today_data if t[4] in ['pembelian', 'biaya'])
        today_profit = today_income - today_expense
        
        self.lbl_today_income.config(text=f"Rp {today_income:,.0f}".replace(",", "."))
        self.lbl_today_expense.config(text=f"Rp {today_expense:,.0f}".replace(",", "."))
        self.lbl_today_profit.config(text=f"Rp {today_profit:,.0f}".replace(",", "."))
        
        # Stok menipis (< 10)
        for row in self.tree_low_stock.get_children():
            self.tree_low_stock.delete(row)
        
        inventory = self.db.fetch_inventory(self.current_user)
        for item in inventory:
            if item[2] < 10:  # Stok < 10
                self.tree_low_stock.insert("", tk.END, values=(item[1], item[2], item[5]))
        
        # Transaksi terakhir (5 terakhir)
        for row in self.tree_recent.get_children():
            self.tree_recent.delete(row)
        
        recent_data = self.db.fetch_transactions(self.current_user)[:5]
        for row in recent_data:
            rp_amount = f"Rp {row[3]:,.0f}".replace(",", ".")
            self.tree_recent.insert("", tk.END, values=(row[1], row[2], rp_amount, row[4].capitalize()))

    def add_inventory_item(self):
        name = self.ent_inv_name.get().strip()
        stock_str = self.ent_inv_stock.get().strip()
        unit = self.ent_inv_unit.get().strip() or "pcs"
        cost_str = self.ent_inv_cost.get().strip()
        sell_str = self.ent_inv_sell.get().strip()
        
        if not name:
            messagebox.showwarning("Peringatan", "Isi nama barang!")
            return
        
        try:
            stock = float(stock_str) if stock_str else 0
            cost = float(cost_str) if cost_str else 0
            sell = float(sell_str) if sell_str else 0
        except ValueError:
            messagebox.showerror("Format Salah", "Stok dan harga harus angka!")
            return
        
        success = self.db.add_inventory_item(self.current_user, name, stock, cost, sell, unit)
        if success:
            messagebox.showinfo("Sukses", f"Barang '{name}' berhasil ditambahkan!")
            self.ent_inv_name.delete(0, tk.END)
            self.ent_inv_stock.delete(0, tk.END)
            self.ent_inv_cost.delete(0, tk.END)
            self.ent_inv_sell.delete(0, tk.END)
            self.refresh_data()
        else:
            messagebox.showerror("Gagal", "Barang sudah ada! Gunakan fitur Edit untuk mengubah.")

    def update_stock_dialog(self):
        selected = self.tree_inv.selection()
        if not selected:
            messagebox.showwarning("Peringatan", "Pilih barang yang ingin diupdate stoknya!")
            return
        
        item = self.tree_inv.item(selected[0], "values")
        item_name = item[1]
        current_stock = item[2]
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Update Stok - {item_name}")
        dialog.geometry("400x250")
        dialog.configure(bg="white")
        
        tk.Label(dialog, text=f"📦 {item_name}", font=("Segoe UI", 14, "bold"), 
                bg="white").pack(pady=10)
        tk.Label(dialog, text=f"Stok saat ini: {current_stock}", 
                font=("Segoe UI", 12), bg="white").pack(pady=5)
        
        tk.Label(dialog, text="Jenis Perubahan:", font=("Segoe UI", 11, "bold"), 
                bg="white").pack(pady=5)
        
        var_type = tk.StringVar(value="masuk")
        tk.Radiobutton(dialog, text="➕ Stok Masuk (Pembelian)", variable=var_type, 
                      value="masuk", bg="white", font=("Segoe UI", 11)).pack(anchor=tk.W, padx=30)
        tk.Radiobutton(dialog, text="➖ Stok Keluar (Penjualan/Pemakaian)", variable=var_type, 
                      value="keluar", bg="white", font=("Segoe UI", 11)).pack(anchor=tk.W, padx=30)
        tk.Radiobutton(dialog, text="✏️ Penyesuaian Manual", variable=var_type, 
                      value="penyesuaian", bg="white", font=("Segoe UI", 11)).pack(anchor=tk.W, padx=30)
        
        tk.Label(dialog, text="Jumlah:", font=("Segoe UI", 11, "bold"), bg="white").pack(pady=5)
        ent_qty = tk.Entry(dialog, font=("Segoe UI", 12), width=15)
        ent_qty.pack(pady=5)
        
        def do_update():
            try:
                qty = float(ent_qty.get())
                if qty <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Jumlah harus angka positif!")
                return
            
            success, result = self.db.adjust_stock(self.current_user, item_name, var_type.get(), qty)
            if success:
                messagebox.showinfo("Sukses", f"Stok berhasil diupdate menjadi {result}!")
                dialog.destroy()
                self.refresh_data()
            else:
                messagebox.showerror("Gagal", result)
        
        tk.Button(dialog, text="✔️ Update", command=do_update, 
                 bg="#10B981", fg="white", font=("Segoe UI", 12, "bold"), 
                 relief=tk.FLAT, padx=20, pady=8).pack(pady=10)

    def edit_inventory_item(self):
        selected = self.tree_inv.selection()
        if not selected:
            messagebox.showwarning("Peringatan", "Pilih barang yang ingin diedit!")
            return
        
        item = self.tree_inv.item(selected[0], "values")
        item_id = item[0]
        
        # Isi form dengan data yang dipilih
        self.ent_inv_name.delete(0, tk.END)
        self.ent_inv_name.insert(0, item[1])
        self.ent_inv_stock.delete(0, tk.END)
        self.ent_inv_stock.insert(0, item[2])
        self.ent_inv_unit.delete(0, tk.END)
        self.ent_inv_unit.insert(0, item[3])
        
        # Hapus "Rp" dan "." dari harga
        cost_clean = item[4].replace("Rp ", "").replace(".", "").replace(",", "")
        sell_clean = item[5].replace("Rp ", "").replace(".", "").replace(",", "")
        
        self.ent_inv_cost.delete(0, tk.END)
        self.ent_inv_cost.insert(0, cost_clean)
        self.ent_inv_sell.delete(0, tk.END)
        self.ent_inv_sell.insert(0, sell_clean)
        
        messagebox.showinfo("Info", "Data barang sudah diisi di form. Ubah sesuai kebutuhan, lalu klik 'Tambah Barang' untuk update.")

    def delete_inventory_item(self):
        selected = self.tree_inv.selection()
        if not selected:
            messagebox.showwarning("Peringatan", "Pilih barang yang ingin dihapus!")
            return
        
        if messagebox.askyesno("Konfirmasi", "Yakin ingin menghapus barang ini?"):
            item = self.tree_inv.item(selected[0], "values")
            item_id = item[0]
            self.db.delete_inventory_item(item_id)
            self.refresh_data()

    def calculate_hpp(self):
        try:
            material = float(self.ent_hpp_material.get() or 0)
            labor = float(self.ent_hpp_labor.get() or 0)
            overhead = float(self.ent_hpp_overhead.get() or 0)
            qty = float(self.ent_hpp_qty.get() or 1)
            
            if qty <= 0:
                raise ValueError
            
            total_cost = material + labor + overhead
            hpp_per_unit = total_cost / qty
            
            result = f"💰 TOTAL BIAYA PRODUKSI: Rp {total_cost:,.0f}\n".replace(",", ".")
            result += f"📦 JUMLAH PRODUK: {qty:.0f} unit\n"
            result += f"🎯 HPP PER UNIT: Rp {hpp_per_unit:,.0f}".replace(",", ".")
            
            self.lbl_hpp_result.config(text=result)
            
            # Auto-fill ke kalkulator harga jual
            self.ent_sell_hpp.delete(0, tk.END)
            self.ent_sell_hpp.insert(0, str(int(hpp_per_unit)))
            
        except ValueError:
            messagebox.showerror("Error", "Isi semua field dengan angka yang benar!")

    def calculate_selling_price(self):
        try:
            hpp = float(self.ent_sell_hpp.get() or 0)
            margin = float(self.ent_sell_margin.get() or 0)
            
            profit = hpp * (margin / 100)
            selling_price = hpp + profit
            
            result = f"💰 HPP: Rp {hpp:,.0f}\n".replace(",", ".")
            result += f"📈 KEUNTUNGAN ({margin:.0f}%): Rp {profit:,.0f}\n".replace(",", ".")
            result += f"💵 HARGA JUAL: Rp {selling_price:,.0f}".replace(",", ".")
            
            self.lbl_sell_result.config(text=result)
            
        except ValueError:
            messagebox.showerror("Error", "Isi HPP dan persentase keuntungan!")

    def export_data(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".csv", 
                                               filetypes=[("CSV Files", "*.csv")])
        if filepath:
            self.db.export_csv(self.current_user, filepath)
            messagebox.showinfo("Sukses", f"Data berhasil diekspor ke:\n{filepath}")


def main():
    root = tk.Tk()
    app = UMKMBudgetApp(root)
    root.mainloop()
    app.db.close()

if __name__ == "__main__":
    main()