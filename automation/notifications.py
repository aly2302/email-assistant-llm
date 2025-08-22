# automation/notifications.py

import os
import requests
import json
import logging
from dotenv import load_dotenv

load_dotenv()

# As suas chaves continuam a ser carregadas do ficheiro .env
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
FLASK_BASE_URL = os.environ.get("FLASK_BASE_URL") # O seu link do ngrok

def send_approval_notification(draft_id, draft_details):
    """Envia uma notificação push diretamente para a API do Pushover."""
    if not all([PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN, FLASK_BASE_URL]):
        logging.warning("Pushover ou FLASK_BASE_URL não configurados. A saltar notificação.")
        return

    try:
        subject = draft_details.get('subject', 'N/A')
        body_preview = draft_details.get('body_preview', 'Sem pré-visualização.')
        title = "Novo Rascunho para Aprovação"
        
        dashboard_url = f"{FLASK_BASE_URL}"
        approve_url = f"{FLASK_BASE_URL}/approve/{draft_id}"
        reject_url = f"{FLASK_BASE_URL}/reject/{draft_id}"

        # A lista de ações (dicionários) continua igual
        actions_list = [
            {"action": "view", "label": "✓ Aprovar Direto", "url": approve_url},
            {"action": "view", "label": "✗ Rejeitar", "url": reject_url}
        ]

        # --- NOVA LÓGICA DE ENVIO DIRETO ---
        # Construímos o payload exatamente como a API do Pushover documenta
        payload = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "url": dashboard_url,
            "url_title": "✍️ Rever e Editar no Dashboard",
            "title": title,
            "message": f"Assunto: {subject}\n\nPreview: {body_preview}",
            "actions": json.dumps(actions_list) # As ações têm de ser uma string JSON
        }

        # Fazemos o pedido POST para a API do Pushover
        response = requests.post("https://api.pushover.net/1/messages.json", data=payload)
        response.raise_for_status() # Isto irá gerar um erro para respostas 4xx ou 5xx
        
        response_data = response.json()
        if response_data.get("status") == 1:
            logging.info(f"Notificação de revisão enviada com sucesso para o rascunho {draft_id}")
        else:
            logging.error(f"Falha ao enviar notificação para {draft_id}. Erros: {response_data.get('errors')}")

    except requests.exceptions.RequestException as http_error:
        logging.error(f"Erro de HTTP ao enviar notificação: {http_error}")
    except Exception as e:
        logging.error(f"Ocorreu um erro na função de notificação: {e}", exc_info=True)