import os
from dotenv import load_dotenv

# Ensure environment variables are loaded when the worker starts
load_dotenv()

from celery import Celery
import logging
import base64
import google.oauth2.credentials
import googleapiclient.discovery
from bs4 import BeautifulSoup

# Import from our other project files
from app import app, parse_sender_info, find_relevant_knowledge, call_gemini, ONTOLOGY_DATA, resolve_component, get_component
from .database import add_pending_draft
from .notifications import send_approval_notification

# --- Celery Configuration ---
celery = Celery(
    app.import_name,
    backend='redis://localhost:6379/1',
    broker='redis://localhost:6379/0'
)
celery.conf.update(app.config)


# --- Helper Function to Extract Email Body ---
def get_email_body(payload):
    """Recursively search for the best text body in an email payload."""
    if "parts" in payload:
        # First, search for a text/plain part
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
        # If no plain text, fall back to HTML
        for part in payload['parts']:
            if part['mimeType'] == 'text/html':
                data = part['body'].get('data')
                if data:
                    html_content = base64.urlsafe_b64decode(data).decode('utf-8')
                    soup = BeautifulSoup(html_content, "html.parser")
                    return soup.get_text(separator='\n', strip=True)
    # Handle non-multipart emails
    elif 'data' in payload.get('body', {}):
        data = payload['body']['data']
        if payload['mimeType'] == 'text/html':
            html_content = base64.urlsafe_b64decode(data).decode('utf-8')
            soup = BeautifulSoup(html_content, "html.parser")
            return soup.get_text(separator='\n', strip=True)
        elif payload['mimeType'] == 'text/plain':
            return base64.urlsafe_b64decode(data).decode('utf-8')
    return "" # Return empty string if no body found


# --- The Main Background Task ---
@celery.task
def process_new_email(thread_id, user_credentials):
    """
    Fetches an email, generates a draft, saves it, and sends a notification.
    """
    logging.info(f"Starting to process new email thread: {thread_id}")
    
    try:
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

        # 1. Fetch the full email thread
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        last_message = thread['messages'][-1]
        payload = last_message.get('payload', {})
        headers = payload.get('headers', [])
        
        original_subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        
        # Use the robust helper function to get the email body
        full_conversation_text = get_email_body(payload)
        
        if not full_conversation_text:
            logging.warning(f"Could not extract a usable text or HTML body from email thread {thread_id}. Skipping.")
            return

        # 2. Run the headless drafting logic
        persona_id = 'rodrigo_novelo_formal'
        persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
        if not persona:
            logging.error(f"Default persona '{persona_id}' not found. Cannot process email.")
            return

        sender_name, sender_email = parse_sender_info(str(headers))
        
        relevant_memories, relevant_corrections = find_relevant_knowledge(
            full_conversation_text, 
            persona.get("personal_knowledge_base", []), 
            persona.get("learned_knowledge_base", [])
        )
        
        prompt_context = [f"Persona Principles: {' '.join(persona.get('style_profile', {}).get('key_principles', []))}"]
        if relevant_memories:
            prompt_context.append(f"Relevant Memory: {', '.join(relevant_memories)}")
        if relevant_corrections:
            prompt_context.append(f"Learned Rules: {', '.join(relevant_corrections)}")

        final_prompt = f"""
        You are an automated email assistant for Rodrigo Novelo.
        Based on the following context and the original email, write a brief, efficient reply.
        
        CONTEXT:
        - {'\n- '.join(prompt_context)}
        
        EMAIL TO REPLY TO:
        ---
        {full_conversation_text}
        ---
        
        DRAFT YOUR REPLY:
        """
        
        llm_response = call_gemini(final_prompt, temperature=0.5)
        if "error" in llm_response:
            logging.error(f"Gemini API error for thread {thread_id}: {llm_response['error']}")
            return

        generated_body = llm_response.get("text", "").strip()
        
        default_ids = persona.get("default_components", {})
        greeting = resolve_component(get_component("greetings", default_ids.get("greeting_id")), sender_name.split()[0])
        closing = resolve_component(get_component("closings", default_ids.get("closing_id")))
        signature = resolve_component(get_component("signatures", default_ids.get("signature_id")))
        
        final_draft_body = f"{greeting}\n\n{generated_body}\n\n{closing}\n{signature}"
        
        # 3. Save the generated draft to the database
        new_draft_id = add_pending_draft(
            thread_id=thread_id,
            recipient=sender_email,
            subject=f"Re: {original_subject}",
            body=final_draft_body
        )
        logging.info(f"Successfully generated and saved draft {new_draft_id} for thread {thread_id}.")
        
        # 4. Send the notification for approval
        draft_details = {
            "recipient": sender_email,
            "subject": f"Re: {original_subject}",
            "body": final_draft_body
        }
        send_approval_notification(new_draft_id, draft_details)

    except Exception as e:
        logging.error(f"An unexpected error occurred while processing thread {thread_id}: {e}", exc_info=True)