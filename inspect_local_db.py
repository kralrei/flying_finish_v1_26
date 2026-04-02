import sqlite3
import os

SQLITE_DB = 'kralrei.db'

def inspect_db():
    if not os.path.exists(SQLITE_DB):
        print(f"{SQLITE_DB} NOT FOUND")
        return
        
    conn = sqlite3.connect(SQLITE_DB)
    c = conn.cursor()
    
    print("--- TABLES ---")
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in c.fetchall()]
    print(tables)
    
    for table in tables:
        c.execute(f"SELECT count(*) FROM {table}")
        count = c.fetchone()[0]
        print(f"Table {table}: {count} rows")
        if count > 0:
            c.execute(f"SELECT * FROM {table} LIMIT 5")
            print(f"Sample data from {table}:")
            for row in c.fetchall():
                print(row)
    
    conn.close()

if __name__ == "__main__":
    inspect_db()
