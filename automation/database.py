import sqlite3
import uuid
import json
from datetime import datetime

DATABASE_FILE = 'automation.db'

def init_db():
    """Initializes the database and creates all necessary tables if they don't exist."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Schema includes the 'original_message_id' column for correct email threading.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_drafts (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL,
            original_message_id TEXT 
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_credentials (
            email TEXT PRIMARY KEY,
            credentials_json TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_threads (
            thread_id TEXT PRIMARY KEY,
            processed_at TIMESTAMP NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully with the new schema.")

def add_pending_draft(thread_id, recipient, subject, body, original_message_id):
    """Adds a new draft to the database, including the ID of the message being replied to."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    new_id = str(uuid.uuid4())
    created_time = datetime.now()
    cursor.execute(
        "INSERT INTO pending_drafts (id, thread_id, recipient, subject, body, created_at, original_message_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (new_id, thread_id, recipient, subject, body, created_time, original_message_id)
    )
    conn.commit()
    conn.close()
    return new_id

def get_pending_draft(draft_id):
    """Retrieves a single pending draft by its ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_drafts WHERE id = ? AND status = 'pending'", (draft_id,))
    draft = cursor.fetchone()
    conn.close()
    return dict(draft) if draft else None

def update_draft_status(draft_id, status):
    """Updates the status of a draft (e.g., 'approved', 'rejected')."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE pending_drafts SET status = ? WHERE id = ?", (status, draft_id))
    conn.commit()
    updated_rows = conn.total_changes
    conn.close()
    return updated_rows > 0

def get_dashboard_stats():
    """Gathers statistics for the automation dashboard."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM pending_drafts WHERE status = 'pending'")
    pending = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM pending_drafts WHERE status = 'approved'")
    sent = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM pending_drafts WHERE status = 'rejected'")
    rejected = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM pending_drafts")
    total = cursor.fetchone()['count']
    
    cursor.execute("SELECT id, recipient, subject, created_at FROM pending_drafts WHERE status = 'pending' ORDER BY created_at DESC")
    drafts = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        'pending': pending,
        'sent': sent,
        'rejected': rejected,
        'total': total,
        'drafts': drafts
    }

def save_user_credentials(email, credentials):
    """Saves or updates a user's OAuth credentials in the database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    credentials_json = json.dumps(credentials)
    cursor.execute("REPLACE INTO user_credentials (email, credentials_json) VALUES (?, ?)", (email, credentials_json))
    conn.commit()
    conn.close()

def get_user_credentials(email):
    """Retrieves a user's OAuth credentials from the database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT credentials_json FROM user_credentials WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

def is_thread_processed(thread_id):
    """Checks if a thread has already been processed to prevent duplicates."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_threads WHERE thread_id = ?", (thread_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_thread_as_processed(thread_id):
    """Marks a thread as processed."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO processed_threads (thread_id, processed_at) VALUES (?, ?)", (thread_id, datetime.now()))
    conn.commit()
    conn.close()

def get_draft_by_id(draft_id):
    """Busca um rascunho específico pelo seu ID, independentemente do status."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row 
    draft = conn.execute('SELECT * FROM pending_drafts WHERE id = ?', (draft_id,)).fetchone()
    conn.close()
    return dict(draft) if draft else None

def update_draft_body(draft_id, new_body):
    """Atualiza o corpo de um rascunho específico."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute('UPDATE pending_drafts SET body = ? WHERE id = ?', (new_body, draft_id))
    conn.commit()
    conn.close()
    return True

if __name__ == '__main__':
    init_db()