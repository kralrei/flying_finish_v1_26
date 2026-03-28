import os
import sqlite3
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime
import time
import threading
import uuid
from dotenv import load_dotenv

load_dotenv()

# Konfigurasi Database
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/flying_finish')
SQLITE_DB = 'kralrei.db'

# Global state
DB_TYPE = None # 'postgres' if online sync is active
pg_pool = None
last_pg_check = 0
PG_COOLDOWN = 20 # Detik untuk tidak mencoba PG jika gagal

def get_pg_pool():
    global pg_pool
    if pg_pool is None and DATABASE_URL:
        try:
            # Perkecil pool size agar tidak kena limit Aiven (max 5 per laptop)
            pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL, connect_timeout=3)
        except Exception as e:
            print(f"Error creating PG pool: {e}")
            return None
    return pg_pool

def get_db_connection():
    """Selalu mengembalikan SQLite untuk kecepatan UI maksimal"""
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

def cloud_execute(sql, params=()):
    """Helper untuk menjalankan write ke cloud secara asinkron (Dual-Write)"""
    global DB_TYPE, last_pg_check
    if DB_TYPE != 'postgres' or not DATABASE_URL:
        return
    
    if time.time() - last_pg_check < PG_COOLDOWN:
        return

    def _sync_task():
        global last_pg_check
        try:
            pool = get_pg_pool()
            if not pool: return
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                # Sesuaikan placeholder ? (SQLite) ke %s (Postgres)
                pg_sql = sql.replace('?', '%s')
                cur.execute(pg_sql, params)
                conn.commit()
                cur.close()
            finally:
                pool.putconn(conn)
        except Exception as e:
            print(f"Cloud sync error: {e}")
            last_pg_check = time.time()

    # Jalankan di background thread agar UI TIDAK BEKU
    threading.Thread(target=_sync_task, daemon=True).start()

def release_db_connection(conn):
    try:
        if isinstance(conn, sqlite3.Connection):
            conn.close()
    except:
        pass

def query_placeholder(sql):
    """Gunakan ? secara default karena primary DB sekarang SQLite"""
    return sql.replace('%s', '?')

def init_db():
    global DB_TYPE
    
    # Init Local SQLite
    conn = sqlite3.connect(SQLITE_DB)
    c = conn.cursor()
    # Menggunakan TEXT untuk UUID agar sinkronisasi antar laptop tidak bertabrakan
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        race_id TEXT PRIMARY KEY,
        event_name TEXT, start_date TEXT, end_date TEXT,
        operator TEXT, koordinat TEXT, total_ss INTEGER DEFAULT 1,
        create_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS timing (
        id TEXT PRIMARY KEY,
        race_id TEXT, no_start TEXT, line_status TEXT,
        time_stamp TEXT, ss TEXT, send INTEGER DEFAULT 0,
        create_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (race_id) REFERENCES events(race_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timing_race_ss ON timing(race_id, ss)')
    
    # MIGRATION: Tambahkan kolom total_ss jika belum ada (SQLite)
    try:
        c.execute("ALTER TABLE events ADD COLUMN total_ss INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass # Berarti kolom sudah ada
    
    # Default settings (Avoid using '0' as default ID)
    default_settings = {'active_race_id': str(uuid.uuid4()), 'current_ss': '1', 'beep_sound': 'on', 'time_precision': '3'}
    for key, value in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    # Migration: Jika ID masih '0' dari versi lama, ganti ke UUID baru agar tidak tabrakan di cloud
    c.execute("SELECT value FROM settings WHERE key = 'active_race_id'")
    row = c.fetchone()
    if row and row[0] == '0':
        new_id = str(uuid.uuid4())
        c.execute("UPDATE settings SET value = ? WHERE key = 'active_race_id'", (new_id,))
    
    conn.commit()
    conn.close()
    print(">>> LOCAL DATABASE (SQLITE) INITIALIZED (UUID MODE) <<<")

    # Init Cloud Postgres (Opsional)
    if DATABASE_URL:
        try:
            pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
            DB_TYPE = 'postgres'
            pg_cur = pg_conn.cursor()
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS events (
                race_id TEXT PRIMARY KEY, event_name TEXT, start_date TEXT, end_date TEXT,
                operator TEXT, koordinat TEXT, total_ss INTEGER DEFAULT 1,
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS timing (
                id TEXT PRIMARY KEY, race_id TEXT REFERENCES events(race_id),
                no_start TEXT, line_status TEXT, time_stamp TEXT, ss TEXT,
                send INTEGER DEFAULT 0, create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # MIGRATION: Tambahkan total_ss ke Cloud jika belum ada
            try:
                pg_cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS total_ss INTEGER DEFAULT 1")
            except:
                pass
            
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS starting_list (
                id TEXT PRIMARY KEY, race_id TEXT REFERENCES events(race_id),
                ns TEXT, driver TEXT, co_driver TEXT, car TEXT, eligibility TEXT,
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
            
            # Default settings Cloud Sync
            default_settings = {'active_race_id': '0', 'current_ss': '1'}
            for key, value in default_settings.items():
                pg_cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", (key, value))
                
            pg_conn.commit()
            pg_cur.close()
            pg_conn.close()
            print(">>> CLOUD SYNC (POSTGRESQL) ACTIVE (UUID MODE) <<<")
        except Exception as e:
            print(f">>> CLOUD SYNC INACTIVE: {e} <<<")
            DB_TYPE = 'sqlite'

    # SQLite Table starting_list
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS starting_list (
        id TEXT PRIMARY KEY, race_id TEXT,
        ns TEXT, driver TEXT, co_driver TEXT, car TEXT, eligibility TEXT,
        create_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (race_id) REFERENCES events(race_id)
    )''')
    conn.commit()
    conn.close()

def _map_event(row):
    """Helper to map row keys to templates' expected casing"""
    if not row: return None
    # SQLite Row objects also support index access and dict conversion
    r = dict(row)
    return {
        'Race_ID': r.get('race_id') or r.get('Race_ID'),
        'Event_Name': r.get('event_name') or r.get('Event_Name'),
        'Start_Date': r.get('start_date') or r.get('Start_Date'),
        'End_Date': r.get('end_date') or r.get('End_Date'),
        'Operator': r.get('operator') or r.get('Operator'),
        'Koordinat': r.get('koordinat') or r.get('Koordinat'),
        'Total_SS': r.get('total_ss') or r.get('Total_SS') or 1,
        'Create_at': r.get('create_at') or r.get('Create_at')
    }

def _map_timing(row):
    """Helper to map row keys to templates' expected casing"""
    if not row: return None
    r = dict(row)
    return {
        'id': r.get('id'),
        'Race_id': r.get('race_id') or r.get('Race_id'),
        'No_start': r.get('no_start') or r.get('No_start'),
        'Line_Status': r.get('line_status') or r.get('Line_Status'),
        'Time_Stamp': r.get('time_stamp') or r.get('Time_Stamp'),
        'SS': r.get('ss') or r.get('SS'),
        'send': r.get('send'),
        'create_at': r.get('create_at')
    }

def create_new_event(data=None):
    if data is None: data = {}
    conn = get_db_connection()
    c = conn.cursor()
    new_id = str(uuid.uuid4()) # Generate UUID Global
    
    event_name = data.get('event_name') or f"New Event {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    start_date = data.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = data.get('end_date') or 'none'
    koordinat = data.get('koordinat') or 'none'
    total_ss = int(data.get('total_ss') or 1)
    
    sql = "INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, total_ss) VALUES (?, ?, ?, ?, ?, ?, ?)"
    params = (new_id, event_name, start_date, end_date, 'none', koordinat, total_ss)
    
    c.execute(sql, params)
    c.execute("UPDATE settings SET value = ? WHERE key = ?", (new_id, 'active_race_id'))
    conn.commit()
    conn.close()
    
    # Sync ke cloud di background
    cloud_execute(sql, params)
    cloud_execute("UPDATE settings SET value = ? WHERE key = ?", (new_id, 'active_race_id'))
    return new_id

def add_timing(race_id, line_status, timestamp, ns_number="", ss_number=""):
    conn = get_db_connection()
    c = conn.cursor()
    
    if not race_id or race_id == '0':
        c.execute("SELECT value FROM settings WHERE key = ?", ('active_race_id',))
        row = c.fetchone()
        race_id = str(row[0]) if row else None

    # Gunakan UUID untuk timing record
    timing_id = str(uuid.uuid4())
    sql = "INSERT INTO timing (id, race_id, line_status, time_stamp, no_start, ss) VALUES (?, ?, ?, ?, ?, ?)"
    params = (timing_id, race_id, line_status, timestamp, ns_number, ss_number)
    c.execute(sql, params)
    conn.commit()
    conn.close()
    
    cloud_execute(sql, params)
    return timing_id

def get_timings(race_id=None, limit=50, ss=None):
    # Trigger sinkronisasi asinkron dari cloud agar tidak membebani UI thread
    if DATABASE_URL:
        threading.Thread(target=pull_timing_from_cloud, args=(race_id, ss), daemon=True).start()

    conn = get_db_connection()
    c = conn.cursor()
    
    query = "SELECT * FROM timing WHERE 1=1"
    params = []
    
    if race_id:
        query += " AND race_id = ?"
        params.append(race_id)
        
    if ss:
        query += " AND ss = ?"
        params.append(str(ss))
        
    query += " ORDER BY create_at DESC LIMIT ?"
    params.append(limit or 50)
    
    c.execute(query, tuple(params))
    rows = [_map_timing(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_starting_list(race_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM starting_list WHERE race_id = ? ORDER BY ns ASC", (race_id,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def upsert_starting_entry(race_id, data):
    conn = get_db_connection()
    c = conn.cursor()
    
    entry_id = data.get('id') or str(uuid.uuid4())
    ns = data.get('ns')
    driver = data.get('driver')
    co_driver = data.get('co_driver')
    car = data.get('car')
    eligibility = data.get('eligibility')
    
    sql = """INSERT INTO starting_list (id, race_id, ns, driver, co_driver, car, eligibility) 
             VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT (id) DO UPDATE SET 
             ns = EXCLUDED.ns, driver = EXCLUDED.driver, co_driver = EXCLUDED.co_driver, car = EXCLUDED.car, eligibility = EXCLUDED.eligibility"""
    params = (entry_id, race_id, ns, driver, co_driver, car, eligibility)
    
    c.execute(sql, params)
    conn.commit()
    conn.close()
    
    cloud_execute(sql, params)
    return entry_id

def bulk_upsert_starting_entries(race_id, entries_list):
    conn = get_db_connection()
    c = conn.cursor()
    
    sql = """INSERT INTO starting_list (id, race_id, ns, driver, co_driver, car, eligibility) 
             VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT (id) DO UPDATE SET 
             ns = EXCLUDED.ns, driver = EXCLUDED.driver, co_driver = EXCLUDED.co_driver, car = EXCLUDED.car, eligibility = EXCLUDED.eligibility"""
    
    successful_params = []
    for entry in entries_list:
        entry_id = entry.get('id') or str(uuid.uuid4())
        params = (entry_id, race_id, entry.get('ns'), entry.get('driver'), 
                  entry.get('co_driver'), entry.get('car'), entry.get('eligibility'))
        c.execute(sql, params)
        successful_params.append(params)
        
    conn.commit()
    conn.close()
    
    # PERBAIKAN: Gunakan satu thread sinkronisasi untuk seluruh list 
    # agar tidak menghabiskan koneksi database (Too Many Clients)
    def _bulk_sync_task():
        try:
            pool = get_pg_pool()
            if not pool: return
            pg_conn = pool.getconn()
            try:
                pg_cur = pg_conn.cursor()
                pg_sql = sql.replace('?', '%s')
                for p in successful_params:
                    pg_cur.execute(pg_sql, p)
                pg_conn.commit()
                pg_cur.close()
            finally:
                pool.putconn(pg_conn)
        except Exception as e:
            print(f"Bulk Cloud sync error: {e}")

    threading.Thread(target=_bulk_sync_task, daemon=True).start()
    return True

def delete_starting_entry(entry_id):
    conn = get_db_connection()
    c = conn.cursor()
    sql = "DELETE FROM starting_list WHERE id = ?"
    c.execute(sql, (entry_id,))
    conn.commit()
    conn.close()
    
    cloud_execute(sql, (entry_id,))
    return True

def get_timing_by_id(timing_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM timing WHERE id = ?", (timing_id,))
    row = c.fetchone()
    conn.close()
    return _map_timing(row)

def update_timing_ns(timing_id, ns_number):
    conn = get_db_connection()
    c = conn.cursor()
    sql = "UPDATE timing SET no_start = ? WHERE id = ?"
    c.execute(sql, (ns_number, timing_id))
    conn.commit()
    conn.close()
    cloud_execute(sql, (ns_number, timing_id))

def mark_timing_sent(timing_id):
    conn = get_db_connection()
    c = conn.cursor()
    sql = "UPDATE timing SET send = 1 WHERE id = ?"
    c.execute(sql, (timing_id,))
    conn.commit()
    conn.close()
    cloud_execute(sql, (timing_id,))

def delete_event(race_id):
    conn = get_db_connection()
    c = conn.cursor()
    # Hapus data timing dan starting_list terkait dulu karena ada Foreign Key
    c.execute("DELETE FROM timing WHERE race_id = ?", (race_id,))
    c.execute("DELETE FROM starting_list WHERE race_id = ?", (race_id,))
    # Hapus event
    sql = "DELETE FROM events WHERE race_id = ?"
    c.execute(sql, (race_id,))
    conn.commit()
    conn.close()
    
    # Sync ke cloud
    cloud_execute("DELETE FROM timing WHERE race_id = ?", (race_id,))
    cloud_execute("DELETE FROM starting_list WHERE race_id = ?", (race_id,))
    cloud_execute(sql, (race_id,))
    return True

def clear_current_timings(race_id):
    conn = get_db_connection()
    c = conn.cursor()
    sql = "DELETE FROM timing WHERE race_id = ?"
    c.execute(sql, (race_id,))
    conn.commit()
    conn.close()
    cloud_execute(sql, (race_id,))

def get_event_by_id(race_id):
    """Alias for get_event_details to maintain naming consistency"""
    return get_event_details(race_id)

def get_event_details(race_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE race_id = ?", (race_id,))
    row = c.fetchone()
    conn.close()
    if row:
        mapped = _map_event(row)
        result = {k.lower(): v for k, v in mapped.items()}
        result.update(mapped)
        # Ensure 'total_ss' is available in lower case too
        result['total_ss'] = mapped['Total_SS']
        return result
    return None

def get_all_events():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events ORDER BY create_at DESC")
    rows = [_map_event(row) for row in c.fetchall()]
    conn.close()
    return rows

def update_event_details(race_id, details):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Pastikan baris event ada di local SQLite (Upsert)
    c.execute("INSERT OR IGNORE INTO events (race_id, event_name) VALUES (?, ?)", (race_id, details.get('event_name', '')))
    
    sql = """UPDATE events SET 
                 event_name = ?, start_date = ?, end_date = ?, 
                 operator = ?, koordinat = ?, total_ss = ?
                 WHERE race_id = ?"""
    params = (details.get('event_name'), details.get('start_date'), details.get('end_date'),
                details.get('operator'), details.get('koordinat'), details.get('total_ss', 1), race_id)
    c.execute(sql, params)
    conn.commit()
    conn.close()
    
    # Gunakan UPSERT untuk PostgreSQL cloud agar data baru otomatis terbuat jika ID belum ada
    sql_cloud = """INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, total_ss)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (race_id) DO UPDATE SET 
                   event_name = EXCLUDED.event_name, start_date = EXCLUDED.start_date, 
                   end_date = EXCLUDED.end_date, operator = EXCLUDED.operator, 
                   koordinat = EXCLUDED.koordinat, total_ss = EXCLUDED.total_ss"""
    params_cloud = (race_id, details.get('event_name'), details.get('start_date'), 
                    details.get('end_date'), details.get('operator'), details.get('koordinat'), details.get('total_ss', 1))
    cloud_execute(sql_cloud, params_cloud)

def get_settings():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    settings = dict(c.fetchall())
    conn.close()
    return settings

def update_settings(settings_dict):
    conn = get_db_connection()
    c = conn.cursor()
    for key, value in settings_dict.items():
        sql = """INSERT INTO settings (key, value) VALUES (?, ?)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"""
        c.execute(sql, (key, value))
        cloud_execute(sql, (key, value))
    conn.commit()
    conn.close()

def get_stats(race_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    racing_statuses = ("F1", "F2", "FM")
    
    if race_id:
        c.execute("SELECT COUNT(*) FROM timing WHERE race_id = ? AND line_status IN (?, ?, ?)", (race_id, *racing_statuses))
        total = c.fetchone()[0]
        c.execute("SELECT line_status, COUNT(*) FROM timing WHERE race_id = ? GROUP BY line_status", (race_id,))
    else:
        c.execute("SELECT COUNT(*) FROM timing WHERE line_status IN (?, ?, ?)", racing_statuses)
        total = c.fetchone()[0]
        c.execute("SELECT line_status, COUNT(*) FROM timing GROUP BY line_status")
    
    counts = dict(c.fetchall())
    conn.close()
    return {'total_events': total, 'event_counts': counts}

def get_full_state(race_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Settings
    c.execute("SELECT key, value FROM settings")
    settings = dict(c.fetchall())
    
    if not race_id:
        race_id = settings.get('active_race_id')
    
    # 2. Event Details
    event_details = {}
    if race_id:
        c.execute("SELECT * FROM events WHERE race_id = ?", (race_id,))
        row = c.fetchone()
        if row:
            event_details = _map_event(row)
            
    # 3. Stats
    racing_statuses = ("F1", "F2", "FM")
    total = 0
    counts = {}
    if race_id:
        c.execute("SELECT COUNT(*) FROM timing WHERE race_id = ? AND line_status IN (?, ?, ?)", (race_id, *racing_statuses))
        total = c.fetchone()[0]
        c.execute("SELECT line_status, COUNT(*) FROM timing WHERE race_id = ? GROUP BY line_status", (race_id,))
        counts = dict(c.fetchall())
    
    conn.close()
    return {
        'settings': settings,
        'event': event_details,
        'stats': {'total_events': total, 'event_counts': counts},
        'active_race_id': race_id
    }

def sync_sqlite_to_postgres():
    """Memindahkan data dari SQLite lokal ke PostgreSQL cloud"""
    global DB_TYPE
    
    # Simpan state awal
    original_type = DB_TYPE
    
    try:
        # Coba buka koneksi Postgres dulu
        pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        pg_cur = pg_conn.cursor()
        
        # Buka koneksi SQLite lokal
        sq_conn = sqlite3.connect(SQLITE_DB)
        sq_conn.row_factory = sqlite3.Row
        sq_cur = sq_conn.cursor()
        
        # 1. Sync Events
        sq_cur.execute("SELECT * FROM events")
        events = sq_cur.fetchall()
        for ev in events:
            # Normalize keys to lowercase
            ev = {k.lower(): v for k, v in dict(ev).items()}
            pg_cur.execute("""
                INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, create_at) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (race_id) DO UPDATE SET 
                event_name = EXCLUDED.event_name, start_date = EXCLUDED.start_date, 
                end_date = EXCLUDED.end_date, operator = EXCLUDED.operator, 
                koordinat = EXCLUDED.koordinat
            """, (ev.get('race_id'), ev.get('event_name'), ev.get('start_date'), ev.get('end_date'), ev.get('operator'), ev.get('koordinat'), ev.get('create_at')))
        
        # 2. Sync Settings
        sq_cur.execute("SELECT * FROM settings")
        settings = sq_cur.fetchall()
        for s in settings:
            s = {k.lower(): v for k, v in dict(s).items()}
            pg_cur.execute("""
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (s.get('key'), s.get('value')))
            
        # 3. Sync Timing
        sq_cur.execute("SELECT * FROM timing")
        timings = sq_cur.fetchall()
        for t in timings:
            t = {k.lower(): v for k, v in dict(t).items()}
            pg_cur.execute("""
                INSERT INTO timing (id, race_id, no_start, line_status, time_stamp, ss, send, create_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (t.get('id'), t.get('race_id'), t.get('no_start'), t.get('line_status'), t.get('time_stamp'), t.get('ss'), t.get('send'), t.get('create_at')))

        pg_conn.commit()
        pg_cur.close()
        pg_conn.close()
        sq_conn.close()
        
        # Jika berhasil, paksa mode ke postgres agar aplikasi langsung pakai cloud
        DB_TYPE = 'postgres'
        return True, "Data berhasil dipindahkan ke cloud!"
        
    except Exception as e:
        DB_TYPE = original_type # Kembalikan tipe
        return False, f"Sync Gagal: {str(e)}"

def pull_events_from_cloud():
    """Menarik daftar Event dari Aiven ke SQLite lokal (untuk sistem HQ)"""
    if not DATABASE_URL:
        return False, "Database URL tidak ditemukan"
    
    try:
        pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        pg_cur = pg_conn.cursor(cursor_factory=RealDictCursor)
        pg_cur.execute("SELECT * FROM events ORDER BY create_at DESC")
        cloud_events = pg_cur.fetchall()
        
        sq_conn = get_db_connection()
        sq_cur = sq_conn.cursor()
        
        for ev in cloud_events:
            ev = {k.lower(): v for k, v in dict(ev).items()}
            sq_cur.execute("""
                INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, create_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (race_id) DO UPDATE SET
                event_name = EXCLUDED.event_name, start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date, operator = EXCLUDED.operator,
                koordinat = EXCLUDED.koordinat
            """, (ev.get('race_id'), ev.get('event_name'), ev.get('start_date'), ev.get('end_date'), 
                  ev.get('operator'), ev.get('koordinat'), ev.get('create_at')))
            
        sq_conn.commit()
        sq_conn.close()
        pg_conn.close()
        return True, f"Berhasil menarik {len(cloud_events)} event dari HQ Cloud."
    except Exception as e:
        return False, f"Gagal menarik data: {str(e)}"

def pull_timing_from_cloud(race_id=None, ss=None):
    """Menarik data timing (TC/Start/dll) dari Aiven ke SQLite lokal"""
    if not DATABASE_URL:
        return False, "Database URL tidak ditemukan"
    
    try:
        # Gunakan koneksi langsung (non-pool) untuk sync task agar tidak diputus pool
        pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        pg_cur = pg_conn.cursor(cursor_factory=RealDictCursor)
        
        query = "SELECT * FROM timing WHERE 1=1"
        params = []
        if race_id:
            query += " AND race_id = %s"
            params.append(race_id)
        if ss:
            query += " AND ss = %s"
            params.append(str(ss))
            
        pg_cur.execute(query, tuple(params))
        cloud_timings = pg_cur.fetchall()
        
        sq_conn = get_db_connection()
        sq_cur = sq_conn.cursor()
        
        count = 0
        for t in cloud_timings:
            t = {k.lower(): v for k, v in dict(t).items()}
            # Insert OR Ignore agar tidak duplikat (UUID as PK)
            sq_cur.execute("""
                INSERT OR IGNORE INTO timing (id, race_id, no_start, line_status, time_stamp, ss, send, create_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (t.get('id'), t.get('race_id'), t.get('no_start'), t.get('line_status'), 
                  t.get('time_stamp'), t.get('ss'), 1, t.get('create_at')))
            if sq_cur.rowcount > 0:
                count += 1
                
        sq_conn.commit()
        sq_cur.close()
        sq_conn.close()
        pg_conn.close()
        if count > 0:
            print(f">>> SYNC CLOUD: Berhasil menarik {count} data baru dari HP ke Laptop. <<<")
        return True, f"Sinkronisasi selesai. Berhasil menarik {count} data baru dari Cloud."
    except Exception as e:
        print(f"FAILED SYNC TIMING: {e}")
        return False, f"Gagal Sinkronisasi: {str(e)}"