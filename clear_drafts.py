import sqlite3

def clear_pending_drafts():
    """Safely deletes all records from the pending_drafts table."""
    try:
        conn = sqlite3.connect('automation.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_drafts")
        conn.commit()
        # Get the number of deleted rows
        deleted_count = cursor.rowcount
        conn.close()
        print(f"Success! The 'pending_drafts' table has been cleared. ({deleted_count} rows deleted)")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    clear_pending_drafts()