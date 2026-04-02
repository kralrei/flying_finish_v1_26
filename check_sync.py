import sqlite3
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
SQLITE_DB = 'kralrei.db'

def check_sqlite():
    print("--- [SQLITE] LOCAL ---")
    try:
        conn = sqlite3.connect(SQLITE_DB)
        c = conn.cursor()
        c.execute("SELECT key, value FROM settings")
        print("SETTINGS:", dict(c.fetchall()))
        
        c.execute("SELECT race_id, event_name, start_date FROM events")
        evs = c.fetchall()
        print("EVENTS:", evs)
        
        for ev in evs:
            rid = ev[0]
            name = ev[1]
            c.execute("SELECT count(*) FROM timing WHERE race_id = ?", (rid,))
            t_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM starting_list WHERE race_id = ?", (rid,))
            s_count = c.fetchone()[0]
            print(f"  - RACE {rid} ({name}): TIMING: {t_count}, STARTERS: {s_count}")
        
        c.execute("SELECT count(*) FROM timing")
        print("TOTAL TIMING COUNT (SQLITE):", c.fetchone()[0])
        conn.close()
    except Exception as e:
        print(f"Error checking SQLite: {e}")

def check_postgres():
    print("\n--- [POSTGRESQL] CLOUD ---")
    if not DATABASE_URL:
        print("DATABASE_URL not found!")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("SELECT key, value FROM settings")
        print("SETTINGS:", dict(c.fetchall()))
        
        c.execute("SELECT race_id, event_name, start_date FROM events")
        evs = c.fetchall()
        print("EVENTS:", evs)
        
        for ev in evs:
            rid = ev[0]
            name = ev[1]
            c.execute("SELECT count(*) FROM timing WHERE race_id = %s", (rid,))
            t_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM starting_list WHERE race_id = %s", (rid,))
            s_count = c.fetchone()[0]
            print(f"  - RACE {rid} ({name}): TIMING: {t_count}, STARTERS: {s_count}")

        c.execute("SELECT count(*) FROM timing")
        print("TOTAL TIMING COUNT (POSTGRES):", c.fetchone()[0])
        conn.close()
    except Exception as e:
        print(f"Error checking PostgreSQL: {e}")

if __name__ == "__main__":
    check_sqlite()
    check_postgres()
