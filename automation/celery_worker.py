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
from automation.database import add_pending_draft
from automation.notifications import send_approval_notification

# --- Configuração do Celery ---
celery = Celery(
    app.import_name,
    backend='redis://localhost:6379/1',
    broker='redis://localhost:6379/0'
)
celery.conf.update(app.config)


# --- Função Auxiliar para Extrair Corpo do Email ---
def get_email_body(payload):
    """
    Procura recursivamente pelo melhor corpo de texto num payload de email.
    Prioritiza texto simples e recorre a uma versão limpa do HTML como fallback.
    """
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


# --- Tarefa Principal em Background (ATUALIZADA) ---
@celery.task
def process_new_email(thread_id, user_credentials):
    """
    Busca um email, gera um rascunho de alta qualidade e guarda-o para aprovação.
    Esta lógica agora espelha a rota /draft do app.py para consistência total.
    """
    logging.info(f"A iniciar processamento de novo email da thread: {thread_id}")

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
            logging.warning(f"Não foi possível extrair o corpo do texto da thread {thread_id}. A ignorar.")
            return

        # --- PASSO 1: RESUMO PARA NOTIFICAÇÃO ---
        summary_prompt = f"Resume o ponto principal deste email numa frase curta (máx 15 palavras) em Português. EMAIL: '{email_body_text}'"
        summary_response = call_gemini(summary_prompt, temperature=0.2)
        original_email_summary = summary_response.get("text", "Não foi possível resumir.").strip()

        # --- PASSO 2: SELEÇÃO DE PERSONA ---
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
            tone_analysis_prompt = f"Analisa o tom do seguinte email e classifica-o como 'formal' ou 'informal'. Responde APENAS com uma palavra.\n\nE-MAIL:\n\"{email_body_text}\""
            tone_response = call_gemini(tone_analysis_prompt, temperature=0.0)
            if "informal" in tone_response.get("text", "formal").strip().lower():
                persona_id = 'rodrigo_novelo_informal'

        persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
        if not persona:
            logging.error(f"Persona '{persona_id}' não encontrada.")
            return
        logging.info(f"A utilizar a persona: {persona.get('label')}")

        # --- PASSO 3: CONSTRUÇÃO DE CONTEXTO (LÓGICA ATUALIZADA) ---
        base_knowledge = ONTOLOGY_DATA.get("base_knowledge", [])
        persona_specific_knowledge = persona.get("personal_knowledge_base", [])
        combined_knowledge = base_knowledge + persona_specific_knowledge

        learned_corrections = persona.get("learned_knowledge_base", [])
        relevant_memories, relevant_corrections = find_relevant_knowledge(
            email_body_text, combined_knowledge, learned_corrections
        )

                # --- INÍCIO DA LÓGICA DE ESTADO E DESCONFLITUALIZAÇÃO (AUTOMAÇÃO - VERSÃO FINAL) ---
        final_task_instruction = "A sua tarefa é escrever um rascunho de e-mail completo e natural, seguindo as instruções."
        is_scheduling_request = 'reunião' in email_body_text.lower() or 'marcar' in email_body_text.lower()

        # Na automação, um pedido de agendamento ATIVA SEMPRE o protocolo de segurança
        if is_scheduling_request:
            relevant_corrections = [rule for rule in relevant_corrections if "agendamento" not in rule.lower()]
            logging.info("Regra de agendamento suprimida para automação para forçar o uso da regra de segurança.")
            # A tarefa da IA é refinada para ser mais natural e proativa, mas segura.
            final_task_instruction = "A sua tarefa é acusar a receção do pedido de agendamento e indicar que as datas/horas precisam de ser confirmadas internamente. Para isso, construa uma frase natural que utilize os placeholders '[Confirmar data aqui]' e '[Confirmar hora aqui]' para propor as datas. NÃO INVENTE NENHUMA DATA OU HORA."
        # --- FIM DA LÓGICA ---

        prompt_context_parts = []
        style_profile = persona.get("style_profile", {})
        
        tone_keywords = style_profile.get('tone_keywords', [])
        verbosity = style_profile.get('verbosity')
        
        style_instructions = []
        if tone_keywords:
            style_instructions.append(f"Tom geral a adotar: {', '.join(tone_keywords)}.")
        if verbosity:
            style_instructions.append(f"Nível de detalhe do texto: {verbosity}.")
        
        if style_instructions:
            prompt_context_parts.append("--- Estilo e Tom (Seguir estritamente) ---\n" + "\n".join(style_instructions))

        if key_principles := style_profile.get('key_principles', []):
            prompt_context_parts.append("--- Princípios Chave da Persona (Regras Gerais) ---\n- " + "\n- ".join(key_principles))

        if interlocutor_profile:
            context_parts = [f"Nome: {interlocutor_profile.get('full_name')}", f"Relação: {interlocutor_profile.get('relationship')}"]
            prompt_context_parts.append("--- Contexto Sobre o Interlocutor ---\n" + " | ".join(filter(None, context_parts)))
            if personalization_rules := interlocutor_profile.get("personalization_rules", []):
                prompt_context_parts.append(f"--- Regras Específicas Para Este Contacto (Prioridade Máxima) ---\n- " + "\n- ".join(personalization_rules))

        if relevant_memories:
            formatted_memories = [f"{mem.get('label', 'Facto')} = {mem.get('value')}" for mem in relevant_memories if mem.get('value')]
            if formatted_memories:
                prompt_context_parts.append(f"--- Factos Relevantes da Memória (Usar apenas se solicitado) ---\n- " + "\n- ".join(formatted_memories))

        if relevant_corrections:
            critical_rules, standard_rules = [], []
            for rule in relevant_corrections:
                if re.search(r'\b(Nunca|Jamais|Regra Crítica)\b', rule, re.IGNORECASE):
                    critical_rules.append(rule)
                else:
                    standard_rules.append(rule)
            if standard_rules:
                prompt_context_parts.append(f"--- Regras Aprendidas (Sobrepõem-se aos Princípios Chave) ---\n- " + "\n- ".join(standard_rules))
            if critical_rules:
                prompt_context_parts.insert(0, f"--- REGRAS CRÍTICAS E INVIOLÁVEIS (OBRIGATÓRIO CUMPRIR) ---\n- " + "\n- ".join(critical_rules))

        final_context_block = "\n\n".join(prompt_context_parts)

        # --- PASSO 4: PROMPT FINAL E CHAMADA À IA ---
        guidance_summary = "Nenhuma instrução específica. Gerar uma resposta com base no contexto do email e na persona."
        
        default_ids = persona.get("default_components", {})
        recipient_first_name = sender_name.split()[0] if sender_name else ""
        greeting_text = resolve_component(get_component("greetings", default_ids.get("greeting_id")), recipient_first_name)
        closing_text = resolve_component(get_component("closings", default_ids.get("closing_id")))
        signature_text = resolve_component(get_component("signatures", default_ids.get("signature_id")))

        final_prompt = f"""
Você é um assistente de escrita que encarna a persona '{persona.get('label', persona_id)}'.
{final_task_instruction}

{final_context_block}

--- E-mail Original a Responder ---
{email_body_text}

--- Instruções do Utilizador (Seguir à risca) ---
{guidance_summary}

--- Rascunho Final (Comece aqui) ---
{greeting_text}

[ESCREVA O CORPO DO E-MAIL AQUI]

{closing_text}
{signature_text}
"""
        llm_response = call_gemini(final_prompt, temperature=0.5)
        if "error" in llm_response:
            logging.error(f"Erro da API Gemini: {llm_response['error']}")
            return

        # --- PASSO 5: LIMPEZA DA RESPOSTA ---
        raw_draft = llm_response.get("text", "").strip()
        if "--- Rascunho Final (Comece aqui) ---" in raw_draft:
            raw_draft = raw_draft.split("--- Rascunho Final (Comece aqui) ---")[-1]
        
        final_draft_body = raw_draft.replace('[ESCREVA O CORPO DO E-MAIL AQUI]', '').strip()
        final_draft_body = re.sub(r'\n{3,}', '\n\n', final_draft_body).strip()

        # --- PASSO 6: GUARDAR E NOTIFICAR ---
        new_draft_id = add_pending_draft(
            thread_id=thread_id,
            recipient=sender_email,
            subject=f"Re: {original_subject}",
            body=final_draft_body,
            original_message_id=original_message_id
        )
        logging.info(f"Rascunho {new_draft_id} gerado e guardado com sucesso para a thread {thread_id}.")

        draft_details_for_notification = {
            "subject": f"Re: {original_subject}",
            "full_draft_body": final_draft_body,
            "original_summary": original_email_summary
        }
        send_approval_notification(new_draft_id, draft_details_for_notification)

    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao processar a thread {thread_id}: {e}", exc_info=True)
