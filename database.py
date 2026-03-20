import sqlite3
from datetime import datetime

DB_NAME = 'kralrei.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Rombak Total: Drop old events table if it's the old schema
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
    if c.fetchone():
        c.execute("PRAGMA table_info(events)")
        cols = [col[1] for col in c.fetchall()]
        if 'Race_ID' not in cols:
            print("Detected old Events schema. Dropping for total overhaul...")
            c.execute("DROP TABLE events")
            c.execute("DROP TABLE IF EXISTS timing") # Also fresh timing

    # Table Events: Race Session metadata
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        Race_ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Event_Name TEXT,
        Start_Date TEXT,
        End_Date TEXT,
        Operator TEXT,
        Koordinat TEXT,
        Create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Table Timing: Capture logs
    c.execute('''CREATE TABLE IF NOT EXISTS timing (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        Race_id INTEGER,
        No_start TEXT,
        Line_Status TEXT,
        Time_Stamp TEXT,
        SS TEXT,
        send INTEGER DEFAULT 0,
        create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(Race_id) REFERENCES events(Race_ID)
    )''')
    try:
        c.execute("ALTER TABLE timing ADD COLUMN SS TEXT")
    except: pass
    
    # Table Settings: Global settings and active state
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # Default settings
    default_settings = {
        'active_race_id': '0', # 0 means none or default
        'current_ss': '1',
        'beep_sound': 'on',
        'time_precision': '3'
    }
    
    for key, value in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    # Insert default initial event if none exist
    c.execute("SELECT COUNT(*) FROM events")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO events (Event_Name, Start_Date) VALUES (?, ?)", ('', datetime.now().strftime('%Y-%m-%d')))
        last_id = c.lastrowid
        c.execute("UPDATE settings SET value = ? WHERE key = ?", (str(last_id), 'active_race_id'))

    conn.commit()
    conn.close()

def create_new_event():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO events (Event_Name, Start_Date) VALUES (?, ?)", ('', datetime.now().strftime('%Y-%m-%d')))
    new_id = c.lastrowid
    c.execute("UPDATE settings SET value = ? WHERE key = ?", (str(new_id), 'active_race_id'))
    conn.commit()
    conn.close()
    return new_id

def add_timing(race_id, line_status, timestamp, ns_number="", ss_number=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO timing (Race_id, Line_Status, Time_Stamp, No_start, SS) VALUES (?, ?, ?, ?, ?)",
              (race_id, line_status, timestamp, ns_number, ss_number))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_timings(race_id=None, limit=50, ss=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT * FROM timing WHERE 1=1"
    params = []
    
    if race_id:
        query += " AND Race_id = ?"
        params.append(race_id)
        
    if ss:
        query += " AND SS = ?"
        params.append(str(ss))
        
    query += " ORDER BY create_at DESC LIMIT ?"
    params.append(limit)
    
    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_timing_by_id(timing_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM timing WHERE id = ?", (timing_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_timing_ns(timing_id, ns_number):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE timing SET No_start = ? WHERE id = ?", (ns_number, timing_id))
    conn.commit()
    conn.close()

def mark_timing_sent(timing_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE timing SET send = 1 WHERE id = ?", (timing_id,))
    conn.commit()
    conn.close()

def clear_current_timings(race_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM timing WHERE Race_id = ?", (race_id,))
    conn.commit()
    conn.close()

def get_event_details(race_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE Race_ID = ?", (race_id,))
    row = c.fetchone()
    conn.close()
    if row:
        # Convert all keys to lowercase to match template expectations
        return {k.lower(): v for k, v in dict(row).items()}
    return None

def get_all_events():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM events ORDER BY Create_at DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def update_event_details(race_id, details):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""UPDATE events SET 
                 Event_Name = ?, Start_Date = ?, End_Date = ?, 
                 Operator = ?, Koordinat = ? 
                 WHERE Race_ID = ?""",
              (details.get('event_name'), details.get('start_date'), details.get('end_date'),
               details.get('operator'), details.get('koordinat'), race_id))
    conn.commit()
    conn.close()

def get_settings():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    settings = dict(c.fetchall())
    conn.close()
    return settings

def update_settings(settings_dict):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for key, value in settings_dict.items():
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_stats(race_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if race_id:
        c.execute("SELECT COUNT(*) FROM timing WHERE Race_id = ?", (race_id,))
        total = c.fetchone()[0]
        c.execute("SELECT Line_Status, COUNT(*) FROM timing WHERE Race_id = ? GROUP BY Line_Status", (race_id,))
    else:
        c.execute("SELECT COUNT(*) FROM timing")
        total = c.fetchone()[0]
        c.execute("SELECT Line_Status, COUNT(*) FROM timing GROUP BY Line_Status")
    counts = dict(c.fetchall())
    conn.close()
    return {'total_events': total, 'event_counts': counts}