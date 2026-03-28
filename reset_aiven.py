import psycopg2

# Link Aiven Anda
DATABASE_URL = 'postgres://avnadmin:AVNS_kBuJkPaOCdYMOCjCU0x@kralreirally2026-ipenk79-a621.j.aivencloud.com:17394/defaultdb?sslmode=require'

def reset_database():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        print("\n--- MEMBERSIHKAN TABEL LAMA DI AIVEN ---")
        cur.execute("DROP TABLE IF EXISTS timing CASCADE")
        cur.execute("DROP TABLE IF EXISTS events CASCADE")
        cur.execute("DROP TABLE IF EXISTS settings CASCADE")
        conn.commit()
        print(">>> TABEL LAMA BERHASIL DIHAPUS. <<<")
        
        print("\n--- MEMBUAT TABEL BARU (VERSI 2026 UUID) ---")
        cur.execute('''CREATE TABLE IF NOT EXISTS events (
            race_id TEXT PRIMARY KEY,
            event_name TEXT, start_date TEXT, end_date TEXT,
            operator TEXT, koordinat TEXT, create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS timing (
            id TEXT PRIMARY KEY,
            race_id TEXT REFERENCES events(race_id),
            no_start TEXT, line_status TEXT, time_stamp TEXT, ss TEXT,
            send INTEGER DEFAULT 1, create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        
        conn.commit()
        cur.close()
        conn.close()
        print(">>> DATABASE AIVEN BERHASIL DIRISE T DAN SIAP DIGUNAKAN! <<<")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    reset_database()
