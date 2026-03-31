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
from datetime import datetime, timedelta
import select

load_dotenv()

# Konfigurasi Database
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/flying_finish')
SQLITE_DB = 'kralrei.db'

# Global state
DB_TYPE = None # 'postgres' if online sync is active
pg_pool = None
last_pg_check = 0
PG_COOLDOWN = 20 # Detik untuk tidak mencoba PG jika gagal
RACE_SETUP_FILE = 'Race_setup.json'

# Global Sync management (untuk PULL/Real-time dari Cloud)
last_pull_sync = 0
is_pulling = False
sync_lock = threading.Lock()

def get_precision():
    """Helper utama untuk mengambil presisi waktu (0, 00, 000) dari berbagai sumber"""
    precision = 3 # Default: Millisecond (.000)
    
    # 1. Cek file lokal (JSON) - Prioritas Tinggi karena Update UI langsung ke sini
    if os.path.exists(RACE_SETUP_FILE):
        try:
            import json
            with open(RACE_SETUP_FILE, 'r') as f:
                data = json.load(f)
                if 'time_precision' in data:
                    return int(data['time_precision'])
        except: pass
        
    # 2. Cek Database (SQLite settings table)
    try:
        conn = sqlite3.connect(SQLITE_DB)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'time_precision'")
        row = c.fetchone()
        if row: precision = int(row[0])
        conn.close()
    except: pass
    
    return precision

def get_pg_pool():
    global pg_pool
    if pg_pool is None and DATABASE_URL:
        try:
            # Perkecil pool size agar tidak kena limit Aiven (max 5 per laptop)
            pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL, connect_timeout=10)
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
        time_stamp TEXT, ss TEXT, elapsed TEXT, send INTEGER DEFAULT 0,
        create_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (race_id) REFERENCES events(race_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timing_race_ss ON timing(race_id, ss)')
    
    try:
        c.execute("ALTER TABLE timing ADD COLUMN elapsed TEXT")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE timing ADD COLUMN penalty INTEGER DEFAULT 0") # Penalty in seconds
    except sqlite3.OperationalError:
        pass
    
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
            pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            DB_TYPE = 'postgres'
            pg_cur = pg_conn.cursor()
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS events (
                race_id TEXT PRIMARY KEY, event_name TEXT, start_date TEXT, end_date TEXT,
                operator TEXT, koordinat TEXT, total_ss INTEGER DEFAULT 1,
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS timing (
                id TEXT PRIMARY KEY, race_id TEXT REFERENCES events(race_id),
                no_start TEXT, line_status TEXT, time_stamp TEXT, ss TEXT, elapsed TEXT,
                send INTEGER DEFAULT 0, create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            try:
                pg_cur.execute("ALTER TABLE timing ADD COLUMN IF NOT EXISTS elapsed TEXT")
                pg_cur.execute("ALTER TABLE timing ADD COLUMN IF NOT EXISTS penalty INTEGER DEFAULT 0")
                pg_cur.execute("ALTER TABLE starting_list ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'OK'") # OK, DNF, DNS
            except:
                pass
            
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS starting_list (
                id TEXT PRIMARY KEY, race_id TEXT REFERENCES events(race_id),
                ns TEXT, driver TEXT, co_driver TEXT, car TEXT, eligibility TEXT,
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            pg_cur.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
            
            # Setup Real-time Triggers (Postgres)
            cur = pg_cur
            cur.execute("""
                CREATE OR REPLACE FUNCTION notify_timing_change() RETURNS TRIGGER AS $$
                BEGIN
                    PERFORM pg_notify('timing_changed', '');
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            cur.execute("""
                DROP TRIGGER IF EXISTS timing_notify_trig ON timing;
                CREATE TRIGGER timing_notify_trig 
                AFTER INSERT OR UPDATE OR DELETE ON timing
                FOR EACH STATEMENT EXECUTE FUNCTION notify_timing_change();
            """)
            
            cur.execute("""
                DROP TRIGGER IF EXISTS starting_notify_trig ON starting_list;
                CREATE TRIGGER starting_notify_trig 
                AFTER INSERT OR UPDATE OR DELETE ON starting_list
                FOR EACH STATEMENT EXECUTE FUNCTION notify_timing_change();
            """)
                
            pg_conn.commit()
            pg_cur.close()
            pg_conn.close()
            print(">>> CLOUD SYNC (POSTGRESQL) ACTIVE & TRIGGERS INSTALLED <<<")
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
        'elapsed': r.get('elapsed') or r.get('Elapsed'),
        'penalty': r.get('penalty') or 0,
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

    # Calculate elapsed if this is a finish record with an NS number
    elapsed = None
    if ns_number and line_status in ('FF', 'F1', 'F2', 'FM'):
        # Normalize SS as done in results
        raw_ss = str(ss_number or '1').strip().lstrip('0')
        if not raw_ss: raw_ss = '0'
        
        c.execute("""SELECT time_stamp FROM timing 
                     WHERE race_id = ? AND no_start = ? 
                     AND (ss = ? OR ss = ?) 
                     AND line_status IN ('START', 'ST') 
                     ORDER BY time_stamp ASC LIMIT 1""", 
                  (race_id, ns_number, raw_ss, raw_ss.zfill(2)))
        start_row = c.fetchone()
        if start_row:
            precision = 3
            try:
                c.execute("SELECT value FROM settings WHERE key = 'time_precision'")
                s_row = c.fetchone()
                if s_row: precision = int(s_row[0])
            except: pass
            elapsed = calculate_elapsed_time(start_row[0], timestamp, precision=precision)

    timing_id = str(uuid.uuid4())
    sql = "INSERT INTO timing (id, race_id, line_status, time_stamp, no_start, ss, elapsed) VALUES (?, ?, ?, ?, ?, ?, ?)"
    params = (timing_id, race_id, line_status, timestamp, ns_number, ss_number, elapsed)
    c.execute(sql, params)
    conn.commit()
    conn.close()
    
    cloud_execute(sql, params)
    return timing_id

def get_timings(race_id=None, limit=50, ss=None):
    # Penarikan data (PULL) otomatis dihapus sesuai permintaan agar terminal bersih.
    # Sinkronisasi kini hanya terjadi saat Startup atau Event-Driven (Update NS).
    
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
        c.execute(sql, (key, str(value)))
        cloud_execute(sql, (key, str(value)))
    conn.commit()
    conn.close()
    return True

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

def delete_timing_record(timing_id):
    # 1. DELETE LOKAL (Instant)
    conn = get_db_connection()
    c = conn.cursor()
    sql = "DELETE FROM timing WHERE id = ?"
    c.execute(sql, (timing_id,))
    conn.commit()
    conn.close()
    
    # 2. DELETE CLOUD (Async but bypass cooldown to ensure sync consistency)
    def _sync_delete():
        if DB_TYPE != 'postgres' or not DATABASE_URL: return
        try:
            pool = get_pg_pool()
            if not pool: return
            pg_conn = pool.getconn()
            try:
                pg_cur = pg_conn.cursor()
                pg_cur.execute("DELETE FROM timing WHERE id = %s", (timing_id,))
                pg_conn.commit()
                pg_cur.close()
                # print(f">>> CLOUD SYNC: Record {timing_id[:8]} deleted. <<<")
            finally:
                pool.putconn(pg_conn)
        except Exception as e:
            print(f"Cloud delete error: {e}")

    threading.Thread(target=_sync_delete, daemon=True).start()
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
    
    # Update NS
    sql = "UPDATE timing SET no_start = ? WHERE id = ?"
    c.execute(sql, (ns_number, timing_id))
    
    # Calculate elapsed if this is a finish record
    elapsed = None
    if ns_number:
        # Get current record details
        c.execute("SELECT * FROM timing WHERE id = ?", (timing_id,))
        curr = _map_timing(c.fetchone())
        
        if curr and curr['Line_Status'] in ('FF', 'F1', 'F2', 'FM'):
            # Look for matching START in the same SS
            # Normalize SS for matching as done in results
            raw_ss = str(curr['SS'] or '1').strip().lstrip('0')
            if not raw_ss: raw_ss = '0'
            
            # Get precision
            precision = 3
            c.execute("SELECT value FROM settings WHERE key = 'time_precision'")
            p_row = c.fetchone()
            if p_row: precision = int(p_row[0])

            # Since SS might be stored as '1' or '01', we check both
            c.execute("""SELECT time_stamp FROM timing 
                         WHERE race_id = ? AND no_start = ? 
                         AND (ss = ? OR ss = ?) 
                         AND line_status IN ('START', 'ST') 
                         ORDER BY time_stamp ASC LIMIT 1""", 
                      (curr['Race_id'], ns_number, raw_ss, raw_ss.zfill(2)))
            start_row = c.fetchone()
            
            if start_row:
                elapsed = calculate_elapsed_time(start_row[0], curr['Time_Stamp'], precision=precision)
                if elapsed and not ('--:--' in elapsed):
                    c.execute("UPDATE timing SET elapsed = ? WHERE id = ?", (elapsed, timing_id))
    
    conn.commit()
    conn.close()
    
    # Sync changes to cloud
    cloud_execute(sql, (ns_number, timing_id))
    if elapsed and elapsed != '--:--.---':
        # Use %s for cloud_execute (Postgres)
        cloud_execute("UPDATE timing SET elapsed = %s WHERE id = %s", (elapsed, timing_id))

def update_timing_penalty(timing_id, penalty):
    conn = get_db_connection()
    c = conn.cursor()
    sql = "UPDATE timing SET penalty = ? WHERE id = ?"
    c.execute(sql, (penalty, timing_id))
    conn.commit()
    conn.close()
    
    # Sync cloud
    cloud_execute("UPDATE timing SET penalty = %s WHERE id = %s", (penalty, timing_id))

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
    # 1. Hapus data lokal (Order matters for FK)
    c.execute("DELETE FROM timing WHERE race_id = ?", (race_id,))
    c.execute("DELETE FROM starting_list WHERE race_id = ?", (race_id,))
    c.execute("DELETE FROM events WHERE race_id = ?", (race_id,))
    conn.commit()
    conn.close()
    
    # 2. Sync ke cloud dalam SATU transaksi agar tidak kena FK violation di background threads
    def _sync_delete_task():
        if DB_TYPE != 'postgres' or not DATABASE_URL: return
        try:
            pool = get_pg_pool()
            if not pool: return
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                # Hapus anak dulu baru bapak
                cur.execute("DELETE FROM timing WHERE race_id = %s", (race_id,))
                cur.execute("DELETE FROM starting_list WHERE race_id = %s", (race_id,))
                cur.execute("DELETE FROM events WHERE race_id = %s", (race_id,))
                conn.commit()
                cur.close()
                print(f">>> CLOUD SYNC: Event {race_id[:8]} deleted successfully. <<<")
            finally:
                pool.putconn(conn)
        except Exception as e:
            print(f"Cloud delete error: {e}")

    threading.Thread(target=_sync_delete_task, daemon=True).start()
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
                INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, total_ss, create_at) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (race_id) DO UPDATE SET 
                event_name = EXCLUDED.event_name, start_date = EXCLUDED.start_date, 
                end_date = EXCLUDED.end_date, operator = EXCLUDED.operator, 
                koordinat = EXCLUDED.koordinat, total_ss = EXCLUDED.total_ss
            """, (ev.get('race_id'), ev.get('event_name'), ev.get('start_date'), ev.get('end_date'), 
                  ev.get('operator'), ev.get('koordinat'), ev.get('total_ss', 1), ev.get('create_at')))
        
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
                INSERT INTO timing (id, race_id, no_start, line_status, time_stamp, ss, elapsed, send, create_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                no_start = EXCLUDED.no_start, elapsed = EXCLUDED.elapsed
            """, (t.get('id'), t.get('race_id'), t.get('no_start'), t.get('line_status'), 
                  t.get('time_stamp'), t.get('ss'), t.get('elapsed'), t.get('send'), t.get('create_at')))

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
        pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
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

def pull_timing_from_cloud(race_id=None, ss=None, on_sync_callback=None):
    """Menarik data timing (TC/Start/dll) dari Aiven ke SQLite lokal"""
    global is_pulling
    if not DATABASE_URL:
        return False, "Database URL tidak ditemukan"
    
    with sync_lock:
        if is_pulling: return False, "Sudah dalam proses sinkronisasi"
        is_pulling = True
        
    try:
        # Gunakan koneksi langsung (non-pool) untuk sync task agar tidak diputus pool
        pg_conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
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
        
        # 1. DELETE LOCAL GHOSTS: Hapus data di SQLite yang sudah tidak ada di Cloud
        # (Hanya untuk race_id ini, dan hanya jika data > 30 detik agar tidak menghapus data yang baru input)
        cloud_ids = [t['id'] for t in cloud_timings]
        
        del_query = "DELETE FROM timing WHERE race_id = ?"
        del_params = [race_id]
        if ss:
            del_query += " AND ss = ?"
            del_params.append(str(ss))
            
        # Proteksi: Jangan hapus data yang umurnya belum 30 detik (menghindari race condition saat baru input)
        del_query += " AND create_at < datetime('now', '-30 seconds')"
        
        if cloud_ids:
            # Gunakan split chunks jika cloud_ids terlalu besar (> 900), tapi di rally biasanya sedikit.
            placeholders = ','.join(['?'] * len(cloud_ids))
            del_query += f" AND id NOT IN ({placeholders})"
            sq_cur.execute(del_query, tuple(del_params + cloud_ids))
        else:
            # Jika di cloud kosong sama sekali untuk race ini, hapus semua yang sudah lewat 30 detik
            sq_cur.execute(del_query, tuple(del_params))
            
        # 2. INSERT/UPDATE FROM CLOUD
        count = 0
        for t in cloud_timings:
            t = {k.lower(): v for k, v in dict(t).items()}
            # SILENT SYNC: Hanya update/anggap berubah jika ada perbedaan konten (NoStart atau Elapsed)
            # SQLite ON CONFLICT DO UPDATE mendukung WHERE mulai versi 3.24
            sq_cur.execute("""
                INSERT INTO timing (id, race_id, no_start, line_status, time_stamp, ss, elapsed, send, create_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                no_start = EXCLUDED.no_start, elapsed = EXCLUDED.elapsed
                WHERE (no_start IS NOT EXCLUDED.no_start OR elapsed IS NOT EXCLUDED.elapsed)
            """, (t.get('id'), t.get('race_id'), t.get('no_start'), t.get('line_status'), 
                  t.get('time_stamp'), t.get('ss'), t.get('elapsed'), 1, t.get('create_at')))
            if sq_cur.rowcount > 0:
                count += 1
                
        sq_conn.commit()
        sq_cur.close()
        sq_conn.close()
        pg_conn.close()
        
        if count > 0 and on_sync_callback:
            on_sync_callback(count)
            
        return True, f"Sinkronisasi selesai. Berhasil menarik {count} data baru dari Cloud."
    except Exception as e:
        print(f"FAILED SYNC TIMING: {e}")
        return False, f"Gagal Sinkronisasi: {str(e)}"
    finally:
        is_pulling = False

def start_cloud_listener(race_id=None, on_sync_callback=None):
    """
    Background Listener: Mendengarkan sinyal LISTEN/NOTIFY dari PostgreSQL 
    untuk sinkronisasi real-time tanpa polling.
    """
    if not DATABASE_URL:
        print(">>> LISTENER: SKIP (No DB URL) <<<")
        return

    def _listen_task():
        print(">>> LISTENER: Memulai PostgreSQL LISTEN (Real-time mode)... <<<")
        while True:
            conn = None
            try:
                # Perlu koneksi stabil yang panjang
                conn = psycopg2.connect(DATABASE_URL)
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cur = conn.cursor()
                cur.execute("LISTEN timing_changed;")
                
                while True:
                    if select.select([conn], [], [], 10) == ([], [], []):
                        # Timeout 10s: check if still alive
                        cur.execute("SELECT 1")
                    else:
                        conn.poll()
                        while conn.notifies:
                            # Notifikasi diterima!
                            notify = conn.notifies.pop(0)
                            # Langsung tarik data baru
                            pull_timing_from_cloud(race_id, on_sync_callback=on_sync_callback)
            except Exception as e:
                print(f">>> LISTENER ERROR (Retrying in 5s): {e} <<<")
                if conn: 
                    try: conn.close()
                    except: pass
                time.sleep(5)
    
    t = threading.Thread(target=_listen_task, daemon=True)
    t.start()
    return t

def parse_time_robust(t_str):
    if not t_str: return None
    t_str = t_str.strip()
    # Try different formats from most specific to least
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            # We use a dummy date (1900-01-01) but it's only for time diff
            return datetime.strptime(t_str, fmt)
        except:
            continue
    return None

def calculate_elapsed_time(start_time_str, finish_time_str, precision=None):
    if not start_time_str or not finish_time_str:
        return "--:--" + ("." + "-" * (precision or 3) if (precision or 3) > 0 else "")
    
    start_dt = parse_time_robust(start_time_str)
    finish_dt = parse_time_robust(finish_time_str)
    
    if not start_dt or not finish_dt:
        return "--:--" + ("." + "-" * (precision or 3) if (precision or 3) > 0 else "")
        
    start_dt = start_dt.replace(second=0, microsecond=0)
        
    if finish_dt < start_dt:
        finish_dt += timedelta(days=1)
            
    total_seconds = (finish_dt - start_dt).total_seconds()
    # If not provided, get_precision() will be used by format_seconds_to_time
    return format_seconds_to_time(total_seconds, precision=precision)

def get_seconds(elapsed_str):
    if not elapsed_str or '--:--' in elapsed_str: return 999999.999
    try:
        parts = elapsed_str.split(':')
        if len(parts) == 3: return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
        if len(parts) == 2: return float(parts[0])*60 + float(parts[1])
        return float(parts[0])
    except: return 999999.999

def format_seconds_to_time(total_seconds, precision=None):
    if precision is None:
        precision = get_precision()

    if total_seconds >= 999999:
        p_dots = "." + ("-" * precision) if precision > 0 else ""
        return f"--:--{p_dots}"
        
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    
    width = 2
    if precision > 0:
        width = 2 + 1 + precision # 2 digits, dot, precision decimals
        
    sec_format = f"{seconds:0{width}.{precision}f}"
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{sec_format}"
    else:
        return f"{minutes:02d}:{sec_format}"

def get_stage_results(race_id, ss=None):
    conn = get_db_connection()
    c = conn.cursor()
    
    query = "SELECT * FROM timing WHERE race_id = ?"
    params = [race_id]
    if ss and ss != 'all' and ss != 'overall':
        # Match both '1' and '01' if ss is 1
        ss_str = str(ss)
        ss_padded = ss_str.zfill(2)
        if ss_str != ss_padded:
            query += " AND (ss = ? OR ss = ?)"
            params.append(ss_str)
            params.append(ss_padded)
        else:
            query += " AND ss = ?"
            params.append(ss_str)
            
    query += " ORDER BY time_stamp ASC"
    
    c.execute(query, tuple(params))
    timings = [_map_timing(row) for row in c.fetchall()]
    
    c.execute("SELECT * FROM starting_list WHERE race_id = ?", (race_id,))
    starting_data = {str(row['ns']).strip(): dict(row) for row in c.fetchall()}
    
    # Get precision once
    c.execute("SELECT value FROM settings WHERE key = 'time_precision'")
    p_row = c.fetchone()
    precision = int(p_row[0]) if p_row else 3
    conn.close()
    
    results_map = {}
    for t in timings:
        ns = str(t['No_start']).strip()
        if not ns or ns == '-' or ns == '': continue
        
        # Normalize SS to integer-like string (strip leading zeros)
        ss_val = str(t['SS'] or '1').strip().lstrip('0')
        if not ss_val: ss_val = '0'
        
        key = (ns, ss_val)
        
        if key not in results_map:
            results_map[key] = {
                'ns': ns,
                'ss': ss_val,
                'driver': starting_data.get(ns, {}).get('driver', 'Unknown'),
                'co_driver': starting_data.get(ns, {}).get('co_driver', '-'),
                'car': starting_data.get(ns, {}).get('car', '-'),
                'eligibility': starting_data.get(ns, {}).get('eligibility', '-'),
                'start_time': None,
                'ff_time': None,
                'stop_time': None,
                'elapsed_time': '--:--.---',
                'penalty': 0,
                'penalty_str': '-',
                'rank': 0
            }
            
        status = t['Line_Status'].upper().strip()
        # START can be ST or START
        if status in ('START', 'ST') and not results_map[key]['start_time']:
            st = str(t['Time_Stamp'] or '')
            results_map[key]['start_time'] = st[:5] if ':' in st and len(st) >= 5 else st
        # FINISH can be any of these
        elif status in ('FF', 'F1', 'F2', 'FM') and not results_map[key]['ff_time']:
            results_map[key]['ff_time'] = t['Time_Stamp']
            
            # Handle penalty
            pen = t.get('penalty') or 0
            results_map[key]['penalty'] = pen
            if pen > 0:
                results_map[key]['penalty_str'] = f"+{pen}s"

            # AMBIL DARI DATABASE (Hasil perhitungan sebelumnya di Finish Stop / add_timing / update_ns)
            if t.get('elapsed'):
                elapsed_val = t['elapsed']
                if pen > 0:
                    # Calculate total with penalty
                    base_sec = get_seconds(elapsed_val)
                    total_sec = base_sec + pen
                    elapsed_val = format_seconds_to_time(total_sec, precision=precision)
                results_map[key]['elapsed_time'] = elapsed_val
            # Fallback jika kolom elapsed di DB masih kosong tetapi data waktu ada
            elif results_map[key]['start_time'] and results_map[key]['ff_time']:
                base_sec = get_seconds(calculate_elapsed_time(results_map[key]['start_time'], results_map[key]['ff_time']))
                total_sec = base_sec + pen
                results_map[key]['elapsed_time'] = format_seconds_to_time(total_sec, precision=precision)
        # STOP specifically for TC/Finish Stop
        elif status == 'STOP' and not results_map[key]['stop_time']:
            results_map[key]['stop_time'] = t['Time_Stamp']
            
    # Filter: Hanya tampilkan jika terdaftar di start list (driver != Unknown) 
    # ATAU setidaknya sudah finish (punya FF time)
    final_results = [res for res in results_map.values() if res['driver'] != 'Unknown' or res['ff_time'] is not None]
        
    final_results.sort(key=lambda x: (x['ss'], get_seconds(x['elapsed_time'])))
    
    current_ss = None
    rank = 0
    for res in final_results:
        if res['ss'] != current_ss:
            current_ss = res['ss']
            rank = 1
        else:
            rank = rank + 1 if res['elapsed_time'] != '--:--.---' else rank
        
        res['rank'] = rank if res['elapsed_time'] != '--:--.---' else '-'
    
    return final_results

def get_overall_results(race_id):
    # Get all stage results for the event
    all_res = get_stage_results(race_id)
    
    overall = {}
    for res in all_res:
        ns = res['ns']
        if ns not in overall:
            overall[ns] = {
                'ns': ns,
                'driver': res['driver'],
                'co_driver': res.get('co_driver', '-'),
                'car': res['car'],
                'eligibility': res['eligibility'],
                'total_seconds': 0.0,
                'ss_completed': 0,
                'rank': 0
            }
        
        if res['elapsed_time'] != '--:--.---':
            overall[ns]['total_seconds'] += get_seconds(res['elapsed_time'])
            overall[ns]['ss_completed'] += 1
            
    # Get precision once
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'time_precision'")
    p_row = c.fetchone()
    precision = int(p_row[0]) if p_row else 3
    conn.close()

    final_overall = []
    for ns, data in overall.items():
        # Filter: Hanya tampilkan jika terdaftar di start list (driver != Unknown) 
        # ATAU setidaknya sudah menyelesaikan 1 SS
        if data['driver'] != 'Unknown' or data['ss_completed'] > 0:
            data['elapsed_time'] = format_seconds_to_time(data['total_seconds'], precision=precision)
            final_overall.append(data)
        
    # Sort by ss_completed (desc) then total_seconds (asc)
    final_overall.sort(key=lambda x: (-x['ss_completed'], x['total_seconds']))
    
    # Rank them
    for i, res in enumerate(final_overall):
        res['rank'] = i + 1 if res['ss_completed'] > 0 else '-'
        
    return final_overall

def update_timing_time(timing_id, new_timestamp):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Update Timestamp
    sql = "UPDATE timing SET time_stamp = ? WHERE id = ?"
    c.execute(sql, (new_timestamp, timing_id))
    
    # Recalculate elapsed if it's a finish record
    c.execute("SELECT * FROM timing WHERE id = ?", (timing_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False
        
    curr = _map_timing(row)
    
    elapsed = None
    if curr and curr['No_start'] and curr['Line_Status'] in ('FF', 'F1', 'F2', 'FM'):
        raw_ss = str(curr['SS'] or '1').strip().lstrip('0')
        if not raw_ss: raw_ss = '0'
        precision = get_precision()
        
        # Cari START yang sesuai
        c.execute("""SELECT time_stamp FROM timing 
                     WHERE race_id = ? AND no_start = ? 
                     AND (ss = ? OR ss = ?) 
                     AND line_status IN ('START', 'ST') 
                     ORDER BY time_stamp ASC LIMIT 1""", 
                  (curr['Race_id'], curr['No_start'], raw_ss, raw_ss.zfill(2)))
        start_row = c.fetchone()
        
        if start_row:
            elapsed = calculate_elapsed_time(start_row[0], new_timestamp, precision=precision)
            if elapsed and not ('--:--' in elapsed):
                c.execute("UPDATE timing SET elapsed = ? WHERE id = ?", (elapsed, timing_id))

    conn.commit()
    conn.close()
    
    # Sync Cloud
    cloud_execute(sql, (new_timestamp, timing_id))
    if elapsed:
        cloud_execute("UPDATE timing SET elapsed = %s WHERE id = %s", (elapsed, timing_id))
    return True