import sqlite3

def migrate(conn):
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            magic_token TEXT NOT NULL UNIQUE
        )
    ''')
    conn.commit()