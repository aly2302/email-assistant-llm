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
        
        # --- BLOCO ANTI-LOOP DEFINITIVO ---
        # Verifica as labels da última mensagem na thread.
        last_message = thread['messages'][-1]
        last_message_labels = last_message.get('labelIds', [])

        # Se a label 'SENT' estiver presente, foi enviada pelo utilizador. Ignoramos.
        if 'SENT' in last_message_labels:
            logging.info(f"Webhook for thread {thread_id} ignored. The last message was sent by the user (loop prevention).")
            return
        # --- FIM DO BLOCO ANTI-LOOP ---

        payload = last_message.get('payload', {})
        headers = payload.get('headers', [])
        
        # --- CAPTURAR O MESSAGE-ID PARA THREADING CORRETO ---
        original_message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
        if not original_message_id:
            logging.warning(f"Could not find Message-ID for thread {thread_id}. Threading may fail.")
        
        original_subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        
        email_body_text = get_email_body(payload)
        
        if not email_body_text:
            logging.warning(f"Could not extract a usable text or HTML body from email thread {thread_id}. Skipping.")
            return

        summary_prompt = f"Resume o ponto principal deste email numa frase curta (máximo 15 palavras) em português. EMAIL: '{email_body_text}'"
        summary_response = call_gemini(summary_prompt, temperature=0.2)
        original_email_summary = "Não foi possível resumir."
        if "error" not in summary_response:
            original_email_summary = summary_response.get("text", original_email_summary).strip()

        persona_id = 'rodrigo_novelo_formal'
        persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
        if not persona:
            logging.error(f"Default persona '{persona_id}' not found. Cannot process email.")
            return

        sender_name, sender_email = parse_sender_info(str(headers))

        # ... (O resto da sua lógica de IA para gerar o rascunho continua aqui)
        # (A parte de gerar o monólogo, encontrar conhecimento, etc., não precisa de alterações)

        interlocutor_context = ""
        if sender_email:
            profiles = ONTOLOGY_DATA.get("interlocutor_profiles", {})
            for key, profile in profiles.items():
                if profile.get("email_match", "").lower() == sender_email.lower():
                    logging.info(f"Automation: Interlocutor '{sender_email}' identified as '{key}'.")
                    context_parts = [f"Nome: {profile.get('full_name')}", f"Relação: {profile.get('relationship')}", f"Notas: {profile.get('notes')}"]
                    interlocutor_context = f"<contexto_interlocutor>{' | '.join(filter(None, context_parts))}</contexto_interlocutor>"
                    break
        
        relevant_memories, relevant_corrections = find_relevant_knowledge(
            email_body_text,
            persona.get("personal_knowledge_base", []),
            persona.get("learned_knowledge_base", [])
        )
        
        monologue = ["<monologo>"]
        monologue.append("  <fase_0_analise_perfil_e_conhecimento>")
        style_profile = persona.get("style_profile", {})
        monologue.append(f"    <principios_chave>{' '.join(style_profile.get('key_principles', ['N/A']))}</principios_chave>")
        
        if relevant_memories:
            formatted_memories = "\n- ".join(relevant_memories)
            monologue.append(f"    <informacao_relevante_da_minha_memoria>\n- {formatted_memories}\n    </informacao_relevante_da_minha_memoria>")
        if relevant_corrections:
            formatted_corrections = "\n- ".join(relevant_corrections)
            monologue.append(f"    <principios_aprendidos_relevantes>\n- {formatted_corrections}\n    </principios_aprendidos_relevantes>")
            
        monologue.append("  </fase_0_analise_perfil_e_conhecimento>")
        
        default_ids = persona.get("default_components", {})
        greeting_text = resolve_component(get_component("greetings", default_ids.get("greeting_id")), sender_name.split()[0])
        closing_text = resolve_component(get_component("closings", default_ids.get("closing_id")))
        signature_text = resolve_component(get_component("signatures", default_ids.get("signature_id")))

        final_prompt = f"""Atue como um assistente de escrita de emails que personifica '{persona.get('label', persona_id)}'.
A sua tarefa é gerar uma resposta de email COMPLETA e natural.
--- MONÓLOGO DE RACIOCÍNIO (O seu contexto interno. NÃO inclua no rascunho final) ---
{''.join(monologue)}
{interlocutor_context}
--- DIRETRIZES ABSOLUTAS DO UTILIZADOR (OBRIGATÓRIO CUMPRIR) ---
Nenhuma diretriz específica. Siga a lógica do seu raciocínio.
--- EMAIL ORIGINAL A RESPONDER ---
{email_body_text}
--- TAREFA ---
1.  **PRIORIDADE ALTA:** Use a 'Informação Relevante da Minha Memória' e os 'Princípios Aprendidos Relevantes' para guiar o conteúdo e o tom.
2.  Use os componentes (saudação, etc.) para a estrutura.
3.  Escreva o CORPO do email. Seja breve e eficiente.
---RASCUNHO-FINAL---
{greeting_text}

[CORPO DO EMAIL AQUI]

{closing_text}
{signature_text}
"""
        
        llm_response = call_gemini(final_prompt, temperature=0.5)
        if "error" in llm_response:
            logging.error(f"Gemini API error for thread {thread_id}: {llm_response['error']}")
            return

        raw_draft = llm_response.get("text", "").strip()
        draft_section = raw_draft.split("---RASCUNHO-FINAL---")[-1].strip()
        final_draft_body = draft_section.replace('[CORPO DO EMAIL AQUI]', '').strip()
        
        # Passar o original_message_id para a base de dados
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