import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

# Current SQLite DB
SQLITE_DB = 'kralrei.db'
# Postgres URL from .env
POSTGRES_URL = os.getenv('DATABASE_URL')

def migrate():
    if not os.path.exists(SQLITE_DB):
        print(f"SQLite database {SQLITE_DB} not found. Skipping migration.")
        return

    if not POSTGRES_URL:
        print("DATABASE_URL not found in .env file.")
        return

    print(f"Migrating data from {SQLITE_DB} to PostgreSQL...")
    
    # Connect
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()
    
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cur = pg_conn.cursor()
    
    # 1. Clear Postgres tables first or handle conflicts
    print("Clearing existing data in Postgres (optional, but clean start recommended)...")
    pg_cur.execute("TRUNCATE TABLE timing, events, settings CASCADE")
    
    # 2. Migrate Events
    print("Migrating Events...")
    sqlite_cur.execute("SELECT * FROM events")
    events = sqlite_cur.fetchall()
    for ev in events:
        # SQLite columns may be 'Race_ID', 'Event_Name', etc.
        # Postgres columns are lowercase 'race_id', 'event_name', etc.
        pg_cur.execute("""
            INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, total_ss, create_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (ev['Race_ID'], ev['Event_Name'], ev['Start_Date'], ev['End_Date'], 
              ev['Operator'], ev['Koordinat'], ev.get('Total_SS', 1), ev['Create_at']))
    
    # 3. Migrate Starting List
    print("Migrating Starting List...")
    sqlite_cur.execute("SELECT * FROM starting_list")
    entries = sqlite_cur.fetchall()
    for en in entries:
        pg_cur.execute("""
            INSERT INTO starting_list (id, race_id, ns, driver, co_driver, car, eligibility, create_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (en['id'], en['race_id'], en['ns'], en['driver'], en['co_driver'], 
              en['car'], en['eligibility'], en['create_at']))

    # 4. Migrate Settings
    print("Migrating Settings...")
    sqlite_cur.execute("SELECT * FROM settings")
    settings = sqlite_cur.fetchall()
    for s in settings:
        pg_cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (s['key'], s['value']))

    # 5. Migrate Timing
    print("Migrating Timing...")
    sqlite_cur.execute("SELECT * FROM timing")
    timings = sqlite_cur.fetchall()
    for t in timings:
        pg_cur.execute("""
            INSERT INTO timing (id, race_id, no_start, line_status, time_stamp, ss, elapsed, send, create_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (t['id'], t['Race_id'], t['No_start'], t['Line_Status'], 
              t['Time_Stamp'], t['SS'], t.get('elapsed' or t.get('Elapsed')), t['send'], t['create_at']))

    # 6. Success Notification
    if timings:
        print(f"Migrated {len(timings)} timing records.")

    pg_conn.commit()
    print("Migration successful!")
    
    sqlite_conn.close()
    pg_conn.close()

if __name__ == '__main__':
    migrate()
