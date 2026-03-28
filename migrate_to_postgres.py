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
        # Map SQLite keys (case-sensitive sometimes) to Postgres columns (lowercase)
        # SQLite columns are 'Race_ID', 'Event_Name', etc.
        # We need to use ID because it's a PK
        pg_cur.execute("""
            INSERT INTO events (race_id, event_name, start_date, end_date, operator, koordinat, create_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (ev['Race_ID'], ev['Event_Name'], ev['Start_Date'], ev['End_Date'], ev['Operator'], ev['Koordinat'], ev['Create_at']))
    
    # 3. Reset Event Serial
    if events:
        pg_cur.execute("SELECT setval('events_race_id_seq', (SELECT max(race_id) FROM events))")

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
            INSERT INTO timing (id, race_id, no_start, line_status, time_stamp, ss, send, create_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (t['id'], t['Race_id'], t['No_start'], t['Line_Status'], t['Time_Stamp'], t['SS'], t['send'], t['create_at']))

    # Reset Timing Serial
    if timings:
        pg_cur.execute("SELECT setval('timing_id_seq', (SELECT max(id) FROM timing))")

    pg_conn.commit()
    print("Migration successful!")
    
    sqlite_conn.close()
    pg_conn.close()

if __name__ == '__main__':
    migrate()
