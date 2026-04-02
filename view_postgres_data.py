import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from datetime import datetime

# Load configuration from .env file
load_dotenv()

# Get Database URL from environment variable
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user_flying:password_flying_finish@localhost:5432/flying_finish_db')

def format_row(row):
    """Helper to format a row for cleaner output"""
    return " | ".join(f"{k}: {v}" for k, v in row.items())

def view_data():
    conn = None
    try:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Connecting to PostgreSQL Cloud...")
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. View ACTIVE RACE (from settings)
        print("\n" + "="*60)
        print(" STATUS SETTINGS (ACTIVE RACE) ".center(60, "="))
        print("="*60)
        cur.execute("SELECT key, value FROM settings WHERE key = 'active_race_id'")
        active_race = cur.fetchone()
        active_id = active_race['value'] if active_race else '0'
        print(f"Active Race ID: {active_id}")

        # 2. View EVENTS
        print("\n" + "="*60)
        print(" DAFTAR EVENT (5 TERBARU) ".center(60, "="))
        print("="*60)
        cur.execute("SELECT race_id, event_name, start_date, operator, total_ss FROM events ORDER BY create_at DESC LIMIT 5")
        events = cur.fetchall()
        if not events:
            print("Belum ada data event.")
        for ev in events:
            indicator = ">>> " if ev['race_id'] == active_id else "    "
            print(f"{indicator}Nama: {ev['event_name'] or 'none'} | ID: {ev['race_id']} | SS: {ev['total_ss']} | Op: {ev['operator']}")

        # 3. View TIMING (the core data)
        print("\n" + "="*60)
        print(f" DATA TIMING (SS TERBARU UNTUK RACE ID: {active_id}) ".center(60, "="))
        print("="*60)
        # Search for the latest SS recorded
        cur.execute("SELECT ss FROM timing WHERE race_id = %s ORDER BY create_at DESC LIMIT 1", (active_id,))
        latest_ss_row = cur.fetchone()
        latest_ss = latest_ss_row['ss'] if latest_ss_row else None

        query = "SELECT no_start, line_status, time_stamp, ss, elapsed, send, create_at FROM timing WHERE race_id = %s"
        params = [active_id]
        
        if latest_ss:
            query += " AND ss = %s"
            params.append(latest_ss)
            print(f"Menampilkan Data SS: {latest_ss}")
            
        query += " ORDER BY create_at DESC LIMIT 15"
        
        cur.execute(query, tuple(params))
        timings = cur.fetchall()
        
        if not timings:
            print(f"Belum ada data timing untuk Race ID ini.")
        else:
            print(f"{'NS':<5} | {'LINE':<6} | {'TIME STAMP':<15} | {'ELAPSED':<12} | {'SS':<3} | {'SYNC':<5} | {'CREATED AT'}")
            print("-" * 88)
            for t in timings:
                sync_status = "Cloud" if t['send'] == 1 else "Local"
                elapsed = t['elapsed'] or "--:--.---"
                created_at = t['create_at'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(t['create_at'], datetime) else t['create_at']
                print(f"{str(t['no_start']):<5} | {t['line_status']:<6} | {t['time_stamp']:<15} | {elapsed:<12} | {t['ss']:<3} | {sync_status:<5} | {created_at}")

        cur.close()
    except Exception as e:
        print(f"\n[!] ERROR: {e}")
    finally:
        if conn:
            conn.close()
            print("\nConnection closed.")

if __name__ == "__main__":
    view_data()
    print("\nTekan Enter untuk keluar...")
    input()
