# celery_worker.py

import os
from dotenv import load_dotenv
import logging
import base64
import google.oauth2.credentials
import googleapiclient.discovery
from bs4 import BeautifulSoup
import re

# Garante que as variáveis de ambiente são carregadas quando o worker inicia
load_dotenv()

from celery import Celery

# Importa de outros ficheiros do nosso projeto
from app import (
    app, parse_sender_info, find_relevant_knowledge, call_gemini,
    ONTOLOGY_DATA, resolve_component, get_component
)
from .database import add_pending_draft
from .notifications import send_approval_notification

# --- Configuração do Celery ---
celery = Celery(
    app.import_name,
    backend='redis://localhost:6379/1',
    broker='redis://localhost:6379/0'
)
celery.conf.update(app.config)


# --- Função Auxiliar para Extrair o Corpo do Email ---
def get_email_body(payload):
    """Procura recursivamente pelo melhor corpo de texto num payload de email."""
    if "parts" in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
        # Fallback para HTML se não houver texto simples
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


# --- A Tarefa Principal em Background ---
@celery.task
def process_new_email(thread_id, user_credentials):
    """
    Busca um email, gera um rascunho de alta qualidade e salva-o para aprovação.
    Esta lógica agora espelha a da rota /draft do app.py para consistência total.
    """
    logging.info(f"A iniciar o processamento do novo email da thread: {thread_id}")
    
    try:
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        last_message = thread['messages'][-1]
        if 'SENT' in last_message.get('labelIds', []):
            logging.info(f"Thread {thread_id} ignorada (prevenção de loop).")
            return

        payload = last_message.get('payload', {})
        headers = payload.get('headers', [])
        
        original_message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
        original_subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        email_body_text = get_email_body(payload)
        
        if not email_body_text:
            logging.warning(f"Não foi possível extrair um corpo de texto da thread {thread_id}. A ignorar.")
            return

        # --- PASSO 1: RESUMO PARA NOTIFICAÇÃO (Rápido e Simples) ---
        summary_prompt = f"Resume o ponto principal deste email numa frase curta (máximo 15 palavras) em português. EMAIL: '{email_body_text}'"
        summary_response = call_gemini(summary_prompt, temperature=0.2)
        original_email_summary = summary_response.get("text", "Não foi possível resumir.").strip()

        # --- PASSO 2: SELEÇÃO DE PERSONA (Idêntico ao app.py) ---
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
            tone_analysis_prompt = f"Analise o tom do seguinte e-mail e classifique-o como 'formal' ou 'informal'. Responda APENAS com uma palavra.\n\nE-MAIL:\n\"{email_body_text}\""
            tone_response = call_gemini(tone_analysis_prompt, temperature=0.0)
            if "informal" in tone_response.get("text", "formal").strip().lower():
                persona_id = 'rodrigo_novelo_informal'
        
        persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
        if not persona:
            logging.error(f"Persona '{persona_id}' não encontrada.")
            return
        logging.info(f"A usar a persona: {persona.get('label')}")

        # --- PASSO 3: CONSTRUÇÃO DO CONTEXTO (LÓGICA 100% IGUAL AO APP.PY) ---
        personal_knowledge = persona.get("personal_knowledge_base", [])
        learned_corrections = persona.get("learned_knowledge_base", [])
        relevant_memories, relevant_corrections = find_relevant_knowledge(
            email_body_text, personal_knowledge, learned_corrections
        )

        prompt_context_parts = []
        
        if key_principles := persona.get("style_profile", {}).get('key_principles', []):
            prompt_context_parts.append("--- Princípios Chave da Persona (Regras Base) ---\n- " + "\n- ".join(key_principles))

        if interlocutor_profile:
            context_parts = [f"Nome: {interlocutor_profile.get('full_name')}", f"Relação: {interlocutor_profile.get('relationship')}"]
            prompt_context_parts.append("--- Contexto Sobre o Interlocutor ---\n" + " | ".join(filter(None, context_parts)))

            # Passa TODAS as regras diretamente para a IA
            if personalization_rules := interlocutor_profile.get("personalization_rules", []):
                prompt_context_parts.append(f"--- Regras Específicas Para Este Contacto (Prioridade Máxima) ---\n- " + "\n- ".join(personalization_rules))
    
        if relevant_memories:
            formatted_memories = "\n- ".join(relevant_memories)
            prompt_context_parts.append(f"--- Informação Relevante da Memória (Usar no conteúdo) ---\n- {formatted_memories}")

        if relevant_corrections:
            formatted_corrections = "\n- ".join(relevant_corrections)
            prompt_context_parts.append(f"--- Regras Aprendidas (Sobrepõem-se aos Princípios Chave) ---\n- {formatted_corrections}")

        final_context_block = "\n\n".join(prompt_context_parts)

        # --- PASSO 4: PROMPT FINAL E CHAMADA À IA (LÓGICA LIMPA DO APP.PY) ---
        # A instrução é genérica para permitir que a IA use as regras de contexto
        guidance_summary = "Nenhuma instrução específica. Gerar uma resposta com base no contexto do email e na persona."

        # O prompt agora é construído de forma idêntica ao do /draft
        final_prompt = f"""
Você é um assistente de escrita que encarna a persona '{persona.get('label', persona_id)}'.
A sua tarefa é escrever um rascunho de e-mail completo e natural, seguindo TODAS as regras do contexto.

{final_context_block}

--- E-mail Original a Responder ---
{email_body_text}

--- Instruções do Utilizador (Seguir à risca) ---
{guidance_summary}

--- Rascunho Final (Comece aqui) ---
"""
        
        llm_response = call_gemini(final_prompt, temperature=0.5)
        if "error" in llm_response:
            logging.error(f"Erro da API Gemini: {llm_response['error']}")
            return

        # --- PASSO 5: LIMPEZA DA RESPOSTA (SEM MONTAGEM, A IA GERA TUDO) ---
        raw_draft = llm_response.get("text", "").strip()
        if "--- Rascunho Final (Comece aqui) ---" in raw_draft:
            raw_draft = raw_draft.split("--- Rascunho Final (Comece aqui) ---")[-1].strip()
        
        final_draft_body = re.sub(r'\n{3,}', '\n\n', raw_draft)
        
        # --- PASSO 6: SALVAR E NOTIFICAR ---
        new_draft_id = add_pending_draft(
            thread_id=thread_id,
            recipient=sender_email,
            subject=f"Re: {original_subject}",
            body=final_draft_body,
            original_message_id=original_message_id
        )
        logging.info(f"Rascunho {new_draft_id} gerado e salvo com sucesso para a thread {thread_id}.")
        
        draft_details = {
            "recipient": sender_email,
            "subject": f"Re: {original_subject}",
            "body": final_draft_body,
            "original_summary": original_email_summary
        }
        send_approval_notification(new_draft_id, draft_details)

    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao processar a thread {thread_id}: {e}", exc_info=True)