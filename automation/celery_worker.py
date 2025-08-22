# automation/celery_worker.py

import os
from dotenv import load_dotenv
import logging
import base64
import google.oauth2.credentials
import googleapiclient.discovery
from bs4 import BeautifulSoup
import re

# Make sure environment variables are loaded when the worker starts
load_dotenv()

from celery import Celery

# Import from other files in our project
from app import (
    app, parse_sender_info, find_relevant_knowledge, call_gemini,
    ONTOLOGY_DATA, resolve_component, get_component
)
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
    """Recursively searches for the best text body in an email payload."""
    if "parts" in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
        # Fallback to HTML if no plain text is found
        for part in payload['parts']:
            if part['mimeType'] == 'text/html':
                data = part['body'].get('data')
                if data:
                    html_content = base64.urlsafe_b64decode(data).decode('utf-8')
                    soup = BeautifulSoup(html_content, "html.parser")
                    return soup.get_text(separator='\n', strip=True)
    elif 'data' in payload.get('body', {}):
        data = payload['body']['data']
        if payload['mimeType'] == 'text/html':
            html_content = base64.urlsafe_b64decode(data).decode('utf-8')
            soup = BeautifulSoup(html_content, "html.parser")
            return soup.get_text(separator='\n', strip=True)
        elif payload['mimeType'] == 'text/plain':
            return base64.urlsafe_b64decode(data).decode('utf-8')
    return ""


# --- The Main Background Task ---
@celery.task
def process_new_email(thread_id, user_credentials):
    """
    Fetches an email, generates a high-quality draft, and saves it for approval.
    This logic now mirrors the /draft route from app.py for full consistency.
    """
    logging.info(f"Starting processing of new email from thread: {thread_id}")
    
    try:
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        last_message = thread['messages'][-1]
        if 'SENT' in last_message.get('labelIds', []):
            logging.info(f"Thread {thread_id} skipped (loop prevention).")
            return

        payload = last_message.get('payload', {})
        headers = payload.get('headers', [])
        
        original_message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
        original_subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        email_body_text = get_email_body(payload)
        
        if not email_body_text:
            logging.warning(f"Could not extract a text body from thread {thread_id}. Skipping.")
            return

        # --- STEP 1: SUMMARY FOR NOTIFICATION (Quick and Simple) ---
        summary_prompt = f"Summarize the main point of this email in a short phrase (max 15 words) in Portuguese. EMAIL: '{email_body_text}'"
        summary_response = call_gemini(summary_prompt, temperature=0.2)
        original_email_summary = summary_response.get("text", "Could not summarize.").strip()

        # --- STEP 2: PERSONA SELECTION (Identical to app.py) ---
        sender_name, sender_email = parse_sender_info(str(headers))
        interlocutor_profile = None
        persona_id = 'rodrigo_novelo_formal'
        
        if sender_email:
            profiles = ONTOLOGY_DATA.get("interlocutor_profiles", {})
            for key, profile in profiles.items():
                if profile.get("email_match", "").lower() == sender_email.lower():
                    interlocutor_profile = profile
                    relationship = profile.get('relationship', '').lower()
                    if any(term in relationship for term in ['amigo', 'irmão', 'colega']):
                        persona_id = 'rodrigo_novelo_informal'
                    break
        
        if not interlocutor_profile:
            tone_analysis_prompt = f"Analyze the tone of the following email and classify it as 'formal' or 'informal'. Respond with ONLY one word.\n\nE-MAIL:\n\"{email_body_text}\""
            tone_response = call_gemini(tone_analysis_prompt, temperature=0.0)
            if "informal" in tone_response.get("text", "formal").strip().lower():
                persona_id = 'rodrigo_novelo_informal'
        
        persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
        if not persona:
            logging.error(f"Persona '{persona_id}' not found.")
            return
        logging.info(f"Using persona: {persona.get('label')}")

        # --- STEP 3: CONTEXT CONSTRUCTION (WITH THE MEMORY FIX) ---
        base_knowledge = ONTOLOGY_DATA.get("base_knowledge", [])
        persona_specific_knowledge = persona.get("personal_knowledge_base", [])
        combined_knowledge = base_knowledge + persona_specific_knowledge
        
        learned_corrections = persona.get("learned_knowledge_base", [])
        
        relevant_memories, relevant_corrections = find_relevant_knowledge(
            email_body_text, combined_knowledge, learned_corrections
        )

        prompt_context_parts = []
        
        if key_principles := persona.get("style_profile", {}).get('key_principles', []):
            prompt_context_parts.append("--- Persona Key Principles (Base Rules) ---\n- " + "\n- ".join(key_principles))

        if interlocutor_profile:
            context_parts = [f"Name: {interlocutor_profile.get('full_name')}", f"Relationship: {interlocutor_profile.get('relationship')}"]
            prompt_context_parts.append("--- Context About the Interlocutor ---\n" + " | ".join(filter(None, context_parts)))

            if personalization_rules := interlocutor_profile.get("personalization_rules", []):
                prompt_context_parts.append(f"--- Specific Rules For This Contact (Highest Priority) ---\n- " + "\n- ".join(personalization_rules))
    
        if relevant_memories:
            # --- THIS IS THE MISSING LINE THAT IS NOW FIXED ---
            formatted_memories = "\n- ".join(relevant_memories)
            prompt_context_parts.append(f"--- Relevant Information from Memory (Use in content) ---\n- {formatted_memories}")

        if relevant_corrections:
            prompt_context_parts.append(f"--- Learned Rules (Overrides Key Principles) ---\n- {formatted_corrections}")

        final_context_block = "\n\n".join(prompt_context_parts)

        # --- STEP 4: FINAL PROMPT AND AI CALL (Logic is clean from app.py) ---
        guidance_summary = "Nenhuma instrução específica. Gerar uma resposta com base no contexto do email e na persona."

        final_prompt = f"""
You are a writing assistant embodying the persona '{persona.get('label', persona_id)}'.
Your task is to write a complete and natural email draft, following ALL rules in the context.

{final_context_block}

--- Original Email to Reply To ---
{email_body_text}

--- User Instructions (Follow strictly) ---
{guidance_summary}

--- Final Draft (Start here) ---
"""
        
        llm_response = call_gemini(final_prompt, temperature=0.5)
        if "error" in llm_response:
            logging.error(f"Gemini API Error: {llm_response['error']}")
            return

        # --- STEP 5: CLEANING THE RESPONSE ---
        raw_draft = llm_response.get("text", "").strip()
        if "--- Final Draft (Start here) ---" in raw_draft:
            raw_draft = raw_draft.split("--- Final Draft (Start here) ---")[-1].strip()
        
        final_draft_body = re.sub(r'\n{3,}', '\n\n', raw_draft)
        
        # --- STEP 6: SAVING AND NOTIFYING ---
        new_draft_id = add_pending_draft(
            thread_id=thread_id,
            recipient=sender_email,
            subject=f"Re: {original_subject}",
            body=final_draft_body,
            original_message_id=original_message_id
        )
        logging.info(f"Draft {new_draft_id} generated and successfully saved for thread {thread_id}.")
        
        draft_details = {
            "recipient": sender_email,
            "subject": f"Re: {original_subject}",
            "body": final_draft_body,
            "original_summary": original_email_summary
        }
        send_approval_notification(new_draft_id, draft_details)

    except Exception as e:
        logging.error(f"An unexpected error occurred while processing thread {thread_id}: {e}", exc_info=True)