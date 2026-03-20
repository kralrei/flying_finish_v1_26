import sqlite3
import os

DB_NAME = 'c:/Python/Flying_finish_2026/kralrei.db'
if not os.path.exists(DB_NAME):
    print(f"DB not found at {DB_NAME}")
else:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM timing")
    count = c.fetchone()[0]
    print(f"Total rows in timing: {count}")
    
    if count > 0:
        c.execute("SELECT Line_Status, COUNT(*) FROM timing GROUP BY Line_Status")
        for row in c.fetchall():
            print(f"Status {row[0]}: {row[1]}")
    conn.close()
