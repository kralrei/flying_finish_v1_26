import psycopg2
from psycopg2.extras import RealDictCursor

# Link Aiven Anda
DATABASE_URL = 'postgres://avnadmin:AVNS_kBuJkPaOCdYMOCjCU0x@kralreirally2026-ipenk79-a621.j.aivencloud.com:17394/defaultdb?sslmode=require'

def check_schema():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        print("\n--- SCHEMA TABEL 'timing' DI AIVEN ---")
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'timing'")
        cols = cur.fetchall()
        for col in cols:
            print(f"Kolom: {col['column_name']} | Tipe: {col['data_type']}")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    check_schema()
