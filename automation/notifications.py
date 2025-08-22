# automation/notifications.py

import os
import requests
import json
import logging
from dotenv import load_dotenv

load_dotenv()

PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
FLASK_BASE_URL = os.environ.get("FLASK_BASE_URL")

def send_approval_notification(draft_id, draft_details):
    """Envia uma notificação PUSH com links HTML para as ações."""
    if not all([PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN, FLASK_BASE_URL]):
        logging.warning("Pushover ou FLASK_BASE_URL não configurados. A saltar notificação.")
        return

    try:
        subject = draft_details.get('subject', 'N/A')
        original_summary = draft_details.get('original_summary', 'Contexto indisponível.')
        full_draft_body = draft_details.get('full_draft_body', 'Rascunho indisponível.')
        
        title = "Novo Rascunho para Aprovação"
        dashboard_url = f"{FLASK_BASE_URL}"
        approve_url = f"{FLASK_BASE_URL}/approve/{draft_id}"
        reject_url = f"{FLASK_BASE_URL}/reject/{draft_id}"

        # --- NOVA LÓGICA COM HTML ---
        # Construímos a mensagem com tags <a> para criar os links clicáveis.
        # A tag <b> torna os links mais visíveis.
        formatted_message = (
            f"<b>Assunto:</b> {subject}\n\n"
            f"<b>Resumo do Email Recebido:</b>\n"
            f'<i>"{original_summary}"</i>\n\n'
            f"<b>--- Rascunho Proposto ---</b>\n"
            f"{full_draft_body}\n\n"
            f"-------------------------------------\n"
            f'<b>Ações Rápidas:</b> <a href="{approve_url}">Aprovar</a> | <a href="{reject_url}">Rejeitar</a>'
        )

        payload = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "url": dashboard_url,
            "url_title": "✍️ Rever e Editar no Dashboard",
            "title": title,
            "message": formatted_message,
            "html": 1  # Informamos a API do Pushover que a mensagem contém HTML
        }

        response = requests.post("https://api.pushover.net/1/messages.json", data=payload)
        response.raise_for_status()
        
        response_data = response.json()
        if response_data.get("status") == 1:
            logging.info(f"Notificação de revisão enviada com sucesso para o rascunho {draft_id}")
        else:
            logging.error(f"Falha ao enviar notificação para {draft_id}. Erros: {response_data.get('errors')}")

    except Exception as e:
        logging.error(f"Ocorreu um erro na função de notificação: {e}", exc_info=True)