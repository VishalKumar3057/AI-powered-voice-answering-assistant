import json
import sqlite3

# Paths
JSON_FILE = 'bookings.json'
DB_FILE = 'bookings.db'

# Connect to SQLite (creates file if not exists)
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# Create table
cursor.execute('''
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    datetime TEXT NOT NULL,
    reason TEXT,
    status TEXT,
    timestamp TEXT
)
''')

# Load JSON data
with open(JSON_FILE, 'r', encoding='utf-8') as f:
    bookings = json.load(f)

# Insert data
for booking in bookings:
    cursor.execute('''
        INSERT OR REPLACE INTO bookings (id, name, datetime, reason, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        booking['id'],
        booking['name'],
        booking['datetime'],
        booking.get('reason'),
        booking.get('status'),
        booking.get('timestamp')
    ))

conn.commit()
conn.close()

print('All bookings from JSON have been stored in bookings.db')
