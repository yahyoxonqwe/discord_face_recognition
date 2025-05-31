import sqlite3
from pathlib import Path

DB_PATH = Path("xb_database.db")

def create_database(db_path: Path):
    # Connect (will create the file if it doesn’t exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the users table if it doesn't already exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        arrival_time DATE,
        departure_time DATE,
        image TEXT,
        reason TEXT
    );
    """)

    # Commit changes and close connection
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {db_path.resolve()} with table 'users'.")

if __name__ == "__main__":
    create_database(DB_PATH)
