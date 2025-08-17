import sqlite3
import uuid
import json
from datetime import datetime

DATABASE_FILE = 'automation.db'

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Table to store drafts waiting for approval
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_drafts (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
            created_at TIMESTAMP NOT NULL
        )
    ''')
    
    # New table to store user credentials persistently
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_credentials (
            email TEXT PRIMARY KEY,
            credentials_json TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def add_pending_draft(thread_id, recipient, subject, body):
    """Adds a new generated draft to the database and returns its unique ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    new_id = str(uuid.uuid4())
    created_time = datetime.now()
    
    cursor.execute(
        "INSERT INTO pending_drafts (id, thread_id, recipient, subject, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_id, thread_id, recipient, subject, body, created_time)
    )
    
    conn.commit()
    conn.close()
    return new_id

def get_pending_draft(draft_id):
    """Retrieves a pending draft by its ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM pending_drafts WHERE id = ? AND status = 'pending'", (draft_id,))
    draft = cursor.fetchone()
    
    conn.close()
    return dict(draft) if draft else None

def update_draft_status(draft_id, status):
    """Updates the status of a draft (e.g., to 'approved' or 'rejected')."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("UPDATE pending_drafts SET status = ? WHERE id = ?", (status, draft_id))
    
    conn.commit()
    updated_rows = conn.total_changes
    conn.close()
    return updated_rows > 0

def save_user_credentials(email, credentials):
    """Saves or updates a user's credentials in the database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    credentials_json = json.dumps(credentials)
    # Use REPLACE to handle both new inserts and updates
    cursor.execute("REPLACE INTO user_credentials (email, credentials_json) VALUES (?, ?)", (email, credentials_json))
    conn.commit()
    conn.close()

def get_user_credentials(email):
    """Retrieves a user's credentials from the database by email."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT credentials_json FROM user_credentials WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None