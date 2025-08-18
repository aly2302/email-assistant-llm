import os
import chump
from dotenv import load_dotenv

load_dotenv()

# Load keys from .env file
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
FLASK_BASE_URL = os.environ.get("FLASK_BASE_URL")

def send_approval_notification(draft_id, draft_details):
    """Sends a push notification to your phone with approve/reject links."""
    if not all([PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN]):
        print("Pushover keys not configured. Skipping notification.")
        return

    try:
        # CORRECTED: Initialize the Application with your API TOKEN
        app = chump.Application(PUSHOVER_API_TOKEN)
        
        # Get the user object with your USER KEY
        user = app.get_user(PUSHOVER_USER_KEY)
        
        # Construct the message content
        title = f"New Draft for: {draft_details['recipient']}"
        message_body = f"Subject: {draft_details['subject']}\n---\n{draft_details['body']}"
        
        # Construct the URLs that will be attached to the notification
        approve_url = f"{FLASK_BASE_URL}/approve/{draft_id}"
        reject_url = f"{FLASK_BASE_URL}/reject/{draft_id}"
        
        # Create the message object
        message = user.create_message(
            message=f"{message_body}\n\nReject here: {reject_url}",
            title=title,
            url=approve_url,
            url_title="✅ Approve & Send"
        )
        
        # Now, send the message
        if message.send():
            print(f"Sent approval notification for draft {draft_id}")
        else:
            print(f"Failed to send notification for draft {draft_id}. Errors: {message.errors}")
            
    except Exception as e:
        print(f"An error occurred in the notification function: {e}")