import os
import chump
from dotenv import load_dotenv

load_dotenv()

# Load keys from .env file
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN")
FLASK_BASE_URL = os.environ.get("FLASK_BASE_URL")

def send_approval_notification(draft_id, draft_details):
    """Sends a push notification with context and approve/reject links."""
    if not all([PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN]):
        print("Pushover keys not configured. Skipping notification.")
        return

    try:
        app = chump.Application(PUSHOVER_API_TOKEN)
        user = app.get_user(PUSHOVER_USER_KEY)
        
        # --- LÓGICA DE MENSAGEM MELHORADA ---
        # Extrai os detalhes para uma formatação mais clara
        recipient = draft_details.get('recipient', 'N/A')
        subject = draft_details.get('subject', 'N/A')
        original_summary = draft_details.get('original_summary', 'Sem resumo.')
        proposed_reply = draft_details.get('body', 'Erro ao gerar rascunho.')

        # Constrói o título e o corpo da mensagem com contexto
        title = f"Rascunho para: {recipient}"
        
        message_body = (
            f"📥 RESUMO DO ORIGINAL:\n{original_summary}\n"
            f"-------------------------------------\n"
            f"🤖 RESPOSTA PROPOSTA:\n{proposed_reply}"
        )

        approve_url = f"{FLASK_BASE_URL}/approve/{draft_id}"
        reject_url = f"{FLASK_BASE_URL}/reject/{draft_id}"
        
        message = user.create_message(
            message=f"{message_body}\n\nRejeitar aqui: {reject_url}",
            title=title,
            url=approve_url,
            url_title="✅ Aprovar e Enviar"
        )
        
        if message.send():
            print(f"Sent contextual approval notification for draft {draft_id}")
        else:
            print(f"Failed to send notification for draft {draft_id}. Errors: {message.errors}")
            
    except Exception as e:
        print(f"An error occurred in the notification function: {e}")