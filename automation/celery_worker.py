# celery_worker.py

import os
from dotenv import load_dotenv
import logging
import base64
import google.oauth2.credentials
import googleapiclient.discovery
from bs4 import BeautifulSoup
import re

# Ensure environment variables are loaded when the worker starts
load_dotenv()

from celery import Celery

# Import from our other project files
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
    """Recursively search for the best text body in an email payload."""
    if "parts" in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
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
    Fetches an email, generates a high-quality draft using advanced prompting,
    saves it, and sends a notification.
    """
    logging.info(f"Starting to process new email thread: {thread_id}")
    
    try:
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        last_message = thread['messages'][-1]
        if 'SENT' in last_message.get('labelIds', []):
            logging.info(f"Thread {thread_id} ignored. Last message was sent by the user (loop prevention).")
            return

        payload = last_message.get('payload', {})
        headers = payload.get('headers', [])
        
        original_message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
        original_subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        
        email_body_text = get_email_body(payload)
        
        if not email_body_text:
            logging.warning(f"Could not extract a usable body from email thread {thread_id}. Skipping.")
            return

        # --- STEP 1: SUMMARIZE THE ORIGINAL EMAIL FOR THE NOTIFICATION ---
        summary_prompt = f"Resume o ponto principal deste email numa frase curta (máximo 15 palavras) em português. EMAIL: '{email_body_text}'"
        summary_response = call_gemini(summary_prompt, temperature=0.2)
        original_email_summary = summary_response.get("text", "Não foi possível resumir.").strip() if "error" not in summary_response else "Não foi possível resumir."

        # --- STEP 2: IDENTIFY SENDER AND SELECT PERSONA DYNAMICALLY ---
        sender_name, sender_email = parse_sender_info(str(headers))
        interlocutor_profile = None
        
        # Default to formal persona initially
        persona_id = 'rodrigo_novelo_formal' 
        
        known_interlocutor = False
        if sender_email:
            profiles = ONTOLOGY_DATA.get("interlocutor_profiles", {})
            for key, profile in profiles.items():
                if profile.get("email_match", "").lower() == sender_email.lower():
                    logging.info(f"Automation: Interlocutor '{sender_email}' identified as '{key}'.")
                    interlocutor_profile = profile
                    known_interlocutor = True
                    # Dynamically select persona based on relationship
                    relationship = profile.get('relationship', '').lower()
                    if any(term in relationship for term in ['amigo', 'irmão', 'colega']):
                        persona_id = 'rodrigo_novelo_informal'
                        logging.info(f"Switching to informal persona based on relationship: '{relationship}'")
                    break
        
        # --- NEW: TONE ANALYSIS FOR UNKNOWN SENDERS ---
        if not known_interlocutor:
            logging.info(f"Sender '{sender_email}' not in profiles. Analyzing email tone...")
            tone_analysis_prompt = f"""
            Analise o tom do seguinte e-mail e classifique-o como 'formal' ou 'informal'.
            Responda APENAS com uma palavra: 'formal' ou 'informal'.

            E-MAIL:
            "{email_body_text}"
            """
            tone_response = call_gemini(tone_analysis_prompt, temperature=0.0)
            detected_tone = tone_response.get("text", "formal").strip().lower()

            if "informal" in detected_tone:
                persona_id = 'rodrigo_novelo_informal'
                logging.info(f"Email tone classified as informal. Switched to persona: {persona_id}")
            else:
                logging.info(f"Email tone classified as formal. Using default persona: {persona_id}")
        
        persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
        if not persona:
            logging.error(f"Selected persona '{persona_id}' not found. Cannot process email.")
            return
        logging.info(f"Using persona: {persona.get('label')}")

        # --- STEP 3: REBUILD PROMPT LOGIC FOR MAXIMUM QUALITY (from /draft route) ---
        
        # 3.1. Gather all available knowledge
        personal_knowledge = persona.get("personal_knowledge_base", [])
        learned_corrections = persona.get("learned_knowledge_base", [])
        relevant_memories, relevant_corrections = find_relevant_knowledge(
            email_body_text, personal_knowledge, learned_corrections
        )

        # 3.2. Build a clean and dynamic context block
        prompt_context_parts = []
        
        style_profile = persona.get("style_profile", {})
        key_principles = style_profile.get('key_principles', [])
        if key_principles:
            prompt_context_parts.append("--- Princípios Chave da Persona (Regras Base) ---\n- " + "\n- ".join(key_principles))

        if interlocutor_profile:
            context_parts = [f"Nome: {interlocutor_profile.get('full_name')}", f"Relação: {interlocutor_profile.get('relationship')}"]
            prompt_context_parts.append("--- Contexto Sobre o Interlocutor ---\n" + " | ".join(filter(None, context_parts)))

            personalization_rules = interlocutor_profile.get("personalization_rules", [])
            if personalization_rules:
                prompt_context_parts.append(f"--- Regras Específicas Para Este Contacto (Prioridade Máxima) ---\n- " + "\n- ".join(personalization_rules))
    
        if relevant_memories:
            prompt_context_parts.append(f"--- Informação Relevante da Memória (Usar no conteúdo) ---\n- " + "\n- ".join(relevant_memories))

        if relevant_corrections:
            prompt_context_parts.append(f"--- Regras Aprendidas (Sobrepõem-se aos Princípios Chave) ---\n- " + "\n- ".join(relevant_corrections))

        final_context_block = "\n\n".join(prompt_context_parts)

        # --- STEP 4: CONSTRUCT AND EXECUTE THE FINAL, HIGH-QUALITY PROMPT ---

        default_ids = persona.get("default_components", {})
        
        # **ERROR FIX**: Check if sender_name exists before trying to split it.
        recipient_first_name = ""
        if sender_name:
            recipient_first_name = sender_name.split()[0]
            
        greeting_text = resolve_component(get_component("greetings", default_ids.get("greeting_id")), recipient_first_name)
        closing_text = resolve_component(get_component("closings", default_ids.get("closing_id")))
        signature_text = resolve_component(get_component("signatures", default_ids.get("signature_id")))

        final_prompt = f"""
Você é um assistente de escrita que encarna a persona '{persona.get('label', persona_id)}'.
A sua tarefa é escrever um rascunho de e-mail completo e natural para aprovação.

{final_context_block}

--- E-mail Original a Responder ---
{email_body_text}

--- Instruções do Utilizador (Gerar resposta automática) ---
Gerar uma resposta apropriada com base no contexto do email e na persona. Seja breve e eficiente.

--- Rascunho Final (Comece aqui) ---
{greeting_text}

[ESCREVA O CORPO DO E-MAIL AQUI]

{closing_text}
{signature_text}
"""
        
        llm_response = call_gemini(final_prompt, temperature=0.5)
        if "error" in llm_response:
            logging.error(f"Gemini API error for thread {thread_id}: {llm_response['error']}")
            return

        raw_draft = llm_response.get("text", "").strip()
        
        if "--- Rascunho Final (Comece aqui) ---" in raw_draft:
            raw_draft = raw_draft.split("--- Rascunho Final (Comece aqui) ---")[-1]

        final_draft_body = raw_draft.replace('[ESCREVA O CORPO DO E-MAIL AQUI]', '').strip()
        final_draft_body = re.sub(r'\n{3,}', '\n\n', final_draft_body).strip()
        
        # --- STEP 5: SAVE DRAFT AND SEND NOTIFICATION ---
        new_draft_id = add_pending_draft(
            thread_id=thread_id,
            recipient=sender_email,
            subject=f"Re: {original_subject}",
            body=final_draft_body,
            original_message_id=original_message_id
        )
        logging.info(f"Successfully generated and saved draft {new_draft_id} for thread {thread_id}.")
        
        draft_details = {
            "recipient": sender_email,
            "subject": f"Re: {original_subject}",
            "body": final_draft_body,
            "original_summary": original_email_summary
        }
        send_approval_notification(new_draft_id, draft_details)

    except Exception as e:
        logging.error(f"An unexpected error occurred while processing thread {thread_id}: {e}", exc_info=True)