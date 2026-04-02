import sqlite3

conn = sqlite3.connect('kralrei.db')
c = conn.cursor()
c.execute("PRAGMA table_info(timing)")
print("TIMING COLUMNS:")
for col in c.fetchall():
    print(col)

c.execute("PRAGMA table_info(events)")
print("\nEVENTS COLUMNS:")
for col in c.fetchall():
    print(col)
conn.close()
