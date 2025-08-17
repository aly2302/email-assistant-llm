# -*- coding: utf-8 -*-
import os
import json
import re
import requests
import logging
import traceback
import datetime
import threading
import base64
import random
import uuid
import unidecode # Necessita 'pip install unidecode'
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
import google.auth.transport.requests # Necessário para refresh de tokens
# NEW IMPORTS FOR AUTOMATION
from database import get_pending_draft, update_draft_status, save_user_credentials, get_user_credentials


# --- CONFIGURAÇÃO INICIAL E CONSTANTES ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-lite')
DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY_FILE = os.path.join(BASE_DIR, 'personas2.0.json')
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, 'client_secret.json')

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'uma-chave-secreta-para-sessoes')

if DEBUG_MODE:
    app.logger.setLevel(logging.DEBUG)

SCOPES = [
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'openid'
]

ontology_file_lock = threading.Lock()

# --- CARREGAMENTO E GESTÃO DA ONTOLOGIA ---

def load_ontology_file():
    """Carrega de forma segura o conteúdo do ficheiro da ontologia."""
    try:
        with open(ONTOLOGY_FILE, 'r', encoding='utf-8') as f:
            ontology_data = json.load(f)
        logging.info(f"Ontologia carregada com sucesso do ficheiro: {ONTOLOGY_FILE}")
        return ontology_data
    except Exception as e:
        logging.error(f"ERRO CRÍTICO ao carregar a ontologia: {e}\n{traceback.format_exc()}")
        return {}
    
def save_ontology_file(data):
    """Salva os dados da ontologia de forma segura."""
    try:
        with open(ONTOLOGY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Ontologia salva com sucesso em {ONTOLOGY_FILE}")
        return True
    except Exception as e:
        logging.error(f"ERRO AO SALVAR O FICHEIRO DE ONTOLOGIA: {e}\n{traceback.format_exc()}")
        return False

ONTOLOGY_DATA = load_ontology_file()

# --- FUNÇÕES HELPER PARA A ARQUITETURA ---

def get_component(component_type, component_id):
    if not component_id: return None
    return ONTOLOGY_DATA.get("communication_components", {}).get(component_type, {}).get(component_id)

def get_current_time_of_day():
    current_hour = datetime.datetime.now().hour
    if 5 <= current_hour < 13: return "morning"
    if 13 <= current_hour < 20: return "afternoon"
    return "evening"

def resolve_component(component, recipient_name=""):
    if not component or not component.get('content'): return ""
    time_of_day = get_current_time_of_day()
    valid_options = [item for item in component['content'] if not item.get('condition') or ("time_of_day" in item.get('condition') and item.get('condition').endswith(time_of_day))]
    if not valid_options: return ""
    chosen_item = random.choice(valid_options)
    return chosen_item.get('text', "").replace("{{recipient_name}}", recipient_name).strip()

def parse_sender_info(original_email_text):
    match = re.search(r"(?:From|De):\s*['\"]?(.*?)['\"]?\s*<(.*?)>", original_email_text, re.IGNORECASE)
    if match:
        name, email = match.group(1).strip().replace('"', ''), match.group(2).strip()
        if '@' in name: name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
        return name, email
    return "Equipa", ""

# --- COMUNICAÇÃO COM A API GEMINI ---
def call_gemini(prompt, model=GEMINI_MODEL, temperature=0.6):
    if not GEMINI_API_KEY: return {"error": "ERROR_CONFIG: Chave da API do Gemini não configurada."}
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "text/plain"},
        "safetySettings": [{"category": c, "threshold": "BLOCK_MEDIUM_AND_ABOVE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
    }
    try:
        response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=180)
        response.raise_for_status()
        data = response.json()
        if data.get('promptFeedback', {}).get('blockReason'): return {"error": f"ERROR_GEMINI_BLOCKED_PROMPT: {data['promptFeedback']['blockReason']}"}
        if candidates := data.get('candidates'):
            if text_parts := candidates[0].get('content', {}).get('parts', []):
                return {"text": text_parts[0]['text'].strip()}
        return {"error": "ERROR_GEMINI_PARSE: Resposta válida, mas nenhum texto gerado encontrado."}
    except requests.exceptions.RequestException as e:
        return {"error": f"ERROR_GEMINI_REQUEST: O pedido à API falhou com o estado {e.response.status_code if e.response else 'N/A'}."}
    except Exception as e:
        return {"error": f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"}

# --- NOVAS FUNÇÕES DE BUSCA POR RELEVÂNCIA ---

def calculate_relevance_for_corrections(new_email_words, learned_corrections, top_n=2):
    """Função auxiliar para calcular a relevância apenas para as correções aprendidas."""
    scored_rules = []
    for item in learned_corrections:
        context_snapshot = item.get("interaction_context_snapshot", {})
        original_email_context = context_snapshot.get("original_email_text", "")
        if original_email_context:
            context_words = set(re.sub(r'[^\w\s]', '', unidecode.unidecode(original_email_context.lower())).split())
            intersection = len(new_email_words.intersection(context_words))
            union = len(new_email_words.union(context_words))
            score = intersection / union if union > 0 else 0
            if score > 0.05: # Limiar mínimo de relevância
                scored_rules.append((score, item.get("inferred_rule_pt")))
    
    scored_rules.sort(key=lambda x: x[0], reverse=True)
    return [rule_text for score, rule_text in scored_rules[:top_n] if rule_text]

def find_relevant_knowledge(new_email_text, personal_knowledge, learned_corrections, top_n=3):
    """Encontra o conhecimento mais relevante usando pré-filtragem por keywords para eficiência."""
    if not new_email_text: return [], []

    stopwords = set(['a', 'o', 'e', 'de', 'do', 'da', 'em', 'um', 'uma', 'com', 'por', 'para'])
    new_email_words = set(re.sub(r'[^\w\s]', '', unidecode.unidecode(new_email_text.lower())).split()) - stopwords

    # 1. Busca na Memória Explícita (personal_knowledge_base) com pré-filtragem
    candidate_memories = [
        mem for mem in personal_knowledge 
        if not set(mem.get("trigger_keywords", [])).isdisjoint(new_email_words)
    ]
    
    scored_memories = []
    for memory in candidate_memories:
        content_words = set(re.sub(r'[^\w\s]', '', unidecode.unidecode(memory.get("content", "").lower())).split())
        intersection = len(new_email_words.intersection(content_words))
        union = len(new_email_words.union(content_words))
        score = intersection / union if union > 0 else 0
        if score > 0.05:
            scored_memories.append((score, memory))

    scored_memories.sort(key=lambda x: x[0], reverse=True)
    top_memories = [mem.get("content") for score, mem in scored_memories[:top_n] if mem.get("content")]
    #top_memories = [mem for score, mem in scored_memories[:top_n]] # Devolve a memória completa

    # 2. Busca nas Correções Implícitas (learned_knowledge_base)
    top_corrections = calculate_relevance_for_corrections(new_email_words, learned_corrections, top_n=2)
    
    if top_memories or top_corrections:
        logging.info(f"Conhecimento relevante encontrado: {len(top_memories)} memórias, {len(top_corrections)} correções.")

    return top_memories, top_corrections

# --- ROTAS DE AUTENTICAÇÃO E GMAIL API ---
# (As rotas /login, /authorize, /logout, get_gmail_service, /api/emails, /api/thread, /api/send_email permanecem as mesmas)
@app.route('/login')
def login():
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=url_for('authorize', _external=True))
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/authorize')
def authorize():
    state = session.get('state')
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=url_for('authorize', _external=True))
    try:
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        
        # Get user's email to use as a primary key
        service = googleapiclient.discovery.build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        user_email = user_info['email']
        
        creds_data = {
            'token': credentials.token, 'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri, 'client_id': credentials.client_id,
            'client_secret': credentials.client_secret, 'scopes': credentials.scopes
        }
        
        # Save the credentials to the database, linked to the email
        save_user_credentials(user_email, creds_data)
        logging.info(f"Credentials saved to database for {user_email}")

        # Keep the credentials in the session for the web UI to work
        session['credentials'] = creds_data 
        return redirect(url_for('index_route'))
        
    except Exception as e:
        logging.error(f"Erro durante a autorização OAuth: {e}")
        return "Erro na autorização.", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index_route'))

def get_gmail_service():
    if 'credentials' not in session: return None
    try:
        creds = google.oauth2.credentials.Credentials(**session['credentials'])
        if creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
            session['credentials'] = {
                'token': creds.token, 'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri, 'client_id': creds.client_id,
                'client_secret': creds.client_secret, 'scopes': creds.scopes
            }
        return googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
    except Exception as e:
        logging.error(f"Falha ao criar o serviço do Gmail: {e}")
        session.clear()
        return None

@app.route('/api/emails')
def fetch_emails_route():
    service = get_gmail_service()
    if not service: return jsonify({"error": "Não autenticado."}), 401
    try:
        results = service.users().messages().list(userId='me', maxResults=15, q="category:primary in:inbox").execute()
        messages = results.get('messages', [])
        email_list = []
        for msg in messages:
            msg_meta = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From', 'Date']).execute()
            headers = msg_meta.get('payload', {}).get('headers', [])
            email_list.append({
                'id': msg_meta['id'], 'threadId': msg_meta['threadId'],
                'subject': next((h['value'] for h in headers if h['name'] == 'Subject'), '(Sem Assunto)'),
                'sender': next((h['value'] for h in headers if h['name'] == 'From'), 'Desconhecido'),
                'snippet': msg_meta.get('snippet', '')
            })
        return jsonify(email_list)
    except Exception as e:
        return jsonify({"error": f"Falha ao obter emails: {e}"}), 500

@app.route('/api/thread/<thread_id>')
def get_thread_route(thread_id):
    service = get_gmail_service()
    if not service: return jsonify({"error": "Não autenticado."}), 401
    try:
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        full_conversation = []
        for message in thread.get('messages', []):
            payload = message.get('payload', {})
            headers = payload.get('headers', [])
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Desconhecido')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')
            body = ''
            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data')
                        if data: body = base64.urlsafe_b64decode(data).decode('utf-8'); break
            elif 'data' in payload.get('body', {}):
                body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
            full_conversation.append(f"--- De: {sender} ({date}) ---\n{body.strip()}\n")
        
        first_msg_headers = thread['messages'][0].get('payload', {}).get('headers', [])
        original_sender = next((h['value'] for h in first_msg_headers if h['name'].lower() == 'from'), '')
        original_subject = next((h['value'] for h in first_msg_headers if h['name'].lower() == 'subject'), '')

        return jsonify({
            "thread_text": "\n".join(full_conversation),
            "original_sender_email": original_sender,
            "original_subject": original_subject
        })
    except Exception as e:
        return jsonify({"error": f"Falha ao recuperar o tópico: {e}"}), 500

@app.route('/api/send_email', methods=['POST'])
def send_email_route():
    service = get_gmail_service()
    if not service: return jsonify({"error": "Não autenticado."}), 401
    data = request.json
    try:
        message = MIMEText(data['body'], _charset='utf-8')
        message['to'] = data['recipient']
        message['subject'] = data['subject']
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_options = {'raw': raw_message}
        if data.get('thread_id'): send_options['threadId'] = data['thread_id']
        sent_message = service.users().messages().send(userId='me', body=send_options).execute()
        return jsonify({"message": "Email enviado com sucesso!", "id": sent_message['id']})
    except Exception as e:
        return jsonify({"error": f"Falha ao enviar email: {e}"}), 500

# --- ROTAS PRINCIPAIS DA APLICAÇÃO ---

@app.route('/')
def index_route():
    if DEBUG_MODE:
        global ONTOLOGY_DATA
        ONTOLOGY_DATA = load_ontology_file()
    return render_template('index.html', is_logged_in='credentials' in session)

@app.route('/analyze', methods=['POST'])
def analyze_email_route():
    email_text = request.json.get('email_text', '')
    if not email_text.strip(): return jsonify({"error": "O texto do email não pode estar vazio."}), 400
    prompt = f"""Analise o email e classifique a sua intenção principal. Extraia também os pontos que necessitam de uma resposta.
Intenções Válidas: 'confirmation', 'call_to_action', 'direct_question', 'generic_notification'.
Formato: APENAS um objeto JSON.
---
Email:
{email_text}
---
JSON Result:
{{
  "email_intent": "...",
  "points": ["..."]
}}
"""
    llm_response = call_gemini(prompt, temperature=0.1)
    if "error" in llm_response: return jsonify({"error": llm_response['error']}), 500
    try:
        json_str_match = re.search(r'\{.*\}', llm_response.get("text", ""), re.DOTALL)
        if not json_str_match: raise json.JSONDecodeError("Nenhum JSON encontrado.", "", 0)
        analysis_data = json.loads(json_str_match.group(0))
        return jsonify(analysis_data)
    except Exception as e:
        return jsonify({"error": f"Falha ao processar a análise da IA: {e}"}), 500
        
# --- ROTA /DRAFT ATUALIZADA ---
@app.route('/draft', methods=['POST'])
def draft_response_route():
    data = request.json
    original_email = data.get('original_email', '')
    persona_id = data.get('persona_name')
    user_inputs = data.get('user_inputs', [])
    
    sender_name, sender_email = parse_sender_info(original_email)
    
    # --- NOVO BLOCO DE CÓDIGO PARA CONTEXTO DO INTERLOCUTOR ---
    interlocutor_context = ""
    if sender_email:
        profiles = ONTOLOGY_DATA.get("interlocutor_profiles", {})
        for key, profile in profiles.items():
            if profile.get("email_match", "").lower() == sender_email.lower():
                logging.info(f"Interlocutor '{sender_email}' identificado como '{key}'.")
                context_parts = []
                if name := profile.get("full_name"):
                    context_parts.append(f"Nome: {name}")
                if nickname := profile.get("nickname"):
                    context_parts.append(f"Alcunha/Como tratar: {nickname}")
                if rel := profile.get("relationship"):
                    context_parts.append(f"Relação: {rel}")
                if notes := profile.get("notes"):
                    context_parts.append(f"Notas: {notes}")
                
                if context_parts:
                    interlocutor_context = f"<contexto_interlocutor>{' | '.join(context_parts)}</contexto_interlocutor>"
                break
    # --- FIM DO NOVO BLOCO ---

    monologue = ["<monologo>"]
    persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
    if not persona: return jsonify({"error": f"Persona '{persona_id}' não encontrada."}), 404

    # --- LÓGICA DE CONHECIMENTO ATUALIZADA ---
    personal_knowledge = persona.get("personal_knowledge_base", [])
    learned_corrections = persona.get("learned_knowledge_base", [])
    
    relevant_memories, relevant_corrections = find_relevant_knowledge(
        original_email, personal_knowledge, learned_corrections
    )
    # --- FIM DA LÓGICA DE CONHECIMENTO ---

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

    guidance_summary = "\n- ".join([item.get('guidance', '').strip() for item in user_inputs if item.get('guidance', '').strip()])
    if guidance_summary: guidance_summary = "\n- " + guidance_summary

    monologue.append(f"  <fase_1_diretrizes_utilizador>\n    <diretrizes>{guidance_summary or 'Nenhuma.'}</diretrizes>\n  </fase_1_diretrizes_utilizador>")

    default_ids = persona.get("default_components", {})
    greeting_text = resolve_component(get_component("greetings", default_ids.get("greeting_id")), sender_name.split()[0])
    closing_text = resolve_component(get_component("closings", default_ids.get("closing_id")))
    signature_text = resolve_component(get_component("signatures", default_ids.get("signature_id")))
    
    prompt = f"""Atue como um assistente de escrita de emails que personifica '{persona.get('label', persona_id)}'.
A sua tarefa é gerar uma resposta de email COMPLETA e natural.

--- MONÓLOGO DE RACIOCÍNIO (O seu contexto interno. NÃO inclua no rascunho final) ---
{''.join(monologue)}
{interlocutor_context}

--- DIRETRIZES ABSOLUTAS DO UTILIZADOR (OBRIGATÓRIO CUMPRIR) ---
{guidance_summary or "Nenhuma diretriz específica. Siga a lógica do seu raciocínio."}

--- EMAIL ORIGINAL A RESPONDER ---
{original_email}

--- TAREFA ---
1.  **PRIORIDADE MÁXIMA:** Cumpra as 'Diretrizes Absolutas do Utilizador'.
2.  **PRIORIDADE ALTA:** Use a 'Informação Relevante da Minha Memória' e os 'Princípios Aprendidos Relevantes' para guiar o conteúdo e o tom. Eles sobrepõem-se aos 'Princípios Chave' genéricos.
3.  Use os componentes (saudação, etc.) para a estrutura.
4.  Escreva o CORPO do email. Seja breve e eficiente.

---RASCUNHO-FINAL---
{greeting_text}

[CORPO DO EMAIL AQUI]

{closing_text}
{signature_text}
"""
    llm_response = call_gemini(prompt, temperature=0.5)
    if "error" in llm_response: return jsonify({"error": llm_response["error"], "monologue": "\n".join(monologue)}), 500

    raw_draft = llm_response.get("text", "").strip()
    
    draft_section = raw_draft.split("---RASCUNHO-FINAL---")[-1].strip()
    if '</monologo>' in draft_section:
        final_draft = draft_section.split('</monologo>')[-1].strip()
    else:
        final_draft = draft_section
    final_draft = final_draft.replace('[CORPO DO EMAIL AQUI]', '').strip()
    final_draft = re.sub(r'\n{3,}', '\n\n', final_draft)

    # --- ALTERAÇÃO AQUI: Loop de substituição agora usa enumerate para MEMORY_1, MEMORY_2, etc. ---
    if relevant_memories:
        for i, memory in enumerate(relevant_memories):
            placeholder = f"{{{{MEMORY_{i+1}}}}}"
            content_to_inject = memory.get('content', '')
            final_draft = final_draft.replace(placeholder, content_to_inject)

    return jsonify({"draft": final_draft, "monologue": "\n".join(monologue)})

# --- ROTAS ADICIONAIS (Feedback, Refine, etc.) ---
# (As rotas /suggest_guidance, /refine_text, /submit_feedback permanecem as mesmas)
@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route():
    data = request.json
    point_to_address = data.get('point_to_address')
    direction = data.get('direction', 'outro')
    direction_map = {'sim': 'AFIRMATIVO', 'nao': 'NEGATIVO', 'outro': 'NEUTRO/DETALHADO'}
    direction_text = direction_map.get(direction)
    prompt = f"""Formule uma resposta curta e {direction_text} ao seguinte ponto: "{point_to_address}". Saída: APENAS o texto da resposta."""
    llm_response = call_gemini(prompt, temperature=0.2)
    if "error" in llm_response: return jsonify(llm_response), 500
    return jsonify({"suggestion": llm_response.get("text", "").strip()})

@app.route('/refine_text', methods=['POST'])
def refine_text_route():
    data = request.json
    action_instructions = {
        "make_formal": "Reescreva para ser mais formal.", "make_casual": "Reescreva para ser mais casual.",
        "shorten": "Condense ao máximo.", "expand": "Elabore sobre o texto.",
        "simplify": "Reescreva com linguagem mais simples.", "improve_flow": "Melhore o fluxo e a coesão.",
        "rephrase": "Refraseie o texto.", "translate_en": "Traduza para inglês profissional."
    }
    instruction = action_instructions.get(data['action'], "Modifique o texto.")
    prompt = f"Ação: {instruction}\nContexto: {data['full_context']}\n---\nTexto a Modificar: {data['selected_text']}\n---\nSaída: APENAS o texto modificado."
    llm_response = call_gemini(prompt, temperature=0.4)
    if "error" in llm_response: return jsonify(llm_response), 500
    return jsonify({"refined_text": llm_response.get("text", "")})

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback_route():
    data = request.json
    persona_name = data.get('persona_name')
    ai_original_response = data.get('ai_original_response', '')
    user_corrected_output = data.get('user_corrected_output', '')
    interaction_context = data.get('interaction_context', {})
    original_email = interaction_context.get('original_email_text', 'N/A')

    inference_prompt = f"""Analise a diferença entre a 'Resposta Original da IA' e a 'Versão Melhorada do Utilizador'. Formule uma regra curta, imperativa e acionável em português (pt-PT) que a IA deve seguir no futuro.
--- CONTEXTO DO EMAIL ORIGINAL ---
{original_email}
--- RESPOSTA ORIGINAL DA IA ---
{ai_original_response}
--- VERSÃO MELHORADA DO UTILIZADOR ---
{user_corrected_output}
--- TAREFA ---
Identifique a mudança principal (tom, formalidade, informação) e crie uma regra geral.
Exemplos: "Confirmar sempre a receção do pedido.", "Manter as respostas a notificações curtas."
--- SAÍDA ---
Produza APENAS um objeto JSON com uma única chave "inferred_rule".
{{ "inferred_rule": "Sua regra inferida aqui." }}
"""
    inferred_rule = "Não foi possível inferir uma regra."
    llm_response = call_gemini(inference_prompt, temperature=0.3)
    if "error" not in llm_response:
        try:
            json_str_match = re.search(r'\{.*\}', llm_response.get("text", ""), re.DOTALL)
            if json_str_match:
                rule_data = json.loads(json_str_match.group(0))
                inferred_rule = rule_data.get("inferred_rule", inferred_rule)
        except Exception as e:
            logging.error(f"Erro ao analisar JSON da regra inferida: {e}")

    try:
        with ontology_file_lock:
            current_data = load_ontology_file()
            persona_obj = current_data.get("personas", {}).get(persona_name)
            if not persona_obj: return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 404
            
            persona_obj.setdefault('learned_knowledge_base', [])
            feedback_entry = {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "inferred_rule_pt": inferred_rule,
                "ai_original_response_text": ai_original_response,
                "user_corrected_output_text": user_corrected_output,
                "interaction_context_snapshot": interaction_context
            }
            persona_obj['learned_knowledge_base'].append(feedback_entry)
            
            if not save_ontology_file(current_data): raise IOError("Falha ao salvar no ficheiro.")
            
            global ONTOLOGY_DATA
            ONTOLOGY_DATA = current_data
        return jsonify({"message": "Feedback submetido!", "inferred_rule": inferred_rule}), 200
    except Exception as e:
        logging.error(f"ERRO CRÍTICO ao salvar feedback: {e}")
        return jsonify({"error": f"Erro no servidor ao salvar: {e}"}), 500

# --- ROTAS DE GESTÃO DE PERSONAS E MEMÓRIA ---
# (As rotas /api/personas, /api/personas/<key>, e as novas rotas de memória permanecem as mesmas)
@app.route('/api/personas', methods=['GET', 'POST'])
def personas_api_route():
    global ONTOLOGY_DATA
    if request.method == 'GET':
        return jsonify(ONTOLOGY_DATA.get("personas", {}))
    if request.method == 'POST':
        data = request.json
        new_key = data.get('persona_key')
        new_data = data.get('persona_data')
        if not new_key or not new_data: return jsonify({"error": "Dados inválidos."}), 400
        with ontology_file_lock:
            current_data = load_ontology_file()
            if new_key in current_data.get("personas", {}): return jsonify({"error": "Chave já existe."}), 409
            current_data.setdefault("personas", {})[new_key] = new_data
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao salvar."}), 500
            ONTOLOGY_DATA = current_data
        return jsonify({"message": "Persona criada."}), 201

@app.route('/api/personas/<persona_key>', methods=['GET', 'PUT', 'DELETE'])
def persona_detail_api_route(persona_key):
    global ONTOLOGY_DATA
    with ontology_file_lock:
        current_data = load_ontology_file()
        if persona_key not in current_data.get("personas", {}): return jsonify({"error": "Não encontrado."}), 404
        if request.method == 'GET':
            return jsonify(current_data["personas"][persona_key])
        if request.method == 'PUT':
            updated_data = request.json
            # Preserva as bases de conhecimento ao atualizar
            updated_data["learned_knowledge_base"] = current_data["personas"][persona_key].get("learned_knowledge_base", [])
            updated_data["personal_knowledge_base"] = current_data["personas"][persona_key].get("personal_knowledge_base", [])
            current_data["personas"][persona_key].update(updated_data)
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao salvar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify({"message": "Persona atualizada."})
        if request.method == 'DELETE':
            del current_data["personas"][persona_key]
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao salvar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify({"message": "Persona removida."})

@app.route('/api/personas/<persona_key>/memories', methods=['GET', 'POST'])
def memories_api_route(persona_key):
    global ONTOLOGY_DATA
    with ontology_file_lock:
        current_data = load_ontology_file()
        persona = current_data.get("personas", {}).get(persona_key)
        if not persona: return jsonify({"error": "Persona não encontrada."}), 404
        if request.method == 'GET':
            return jsonify(persona.get("personal_knowledge_base", []))
        if request.method == 'POST':
            new_memory = request.json
            if not new_memory or 'content' not in new_memory: return jsonify({"error": "Conteúdo obrigatório."}), 400
            persona.setdefault("personal_knowledge_base", [])
            new_memory['id'] = f"mem_{uuid.uuid4().hex[:8]}"
            persona["personal_knowledge_base"].append(new_memory)
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao salvar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify(new_memory), 201

@app.route('/api/personas/<persona_key>/memories/<memory_id>', methods=['PUT', 'DELETE'])
def memory_detail_api_route(persona_key, memory_id):
    global ONTOLOGY_DATA
    with ontology_file_lock:
        current_data = load_ontology_file()
        persona = current_data.get("personas", {}).get(persona_key)
        if not persona: return jsonify({"error": "Persona não encontrada."}), 404
        knowledge_base = persona.get("personal_knowledge_base", [])
        memory_to_modify = next((mem for mem in knowledge_base if mem.get("id") == memory_id), None)
        if not memory_to_modify: return jsonify({"error": "Memória não encontrada."}), 404
        if request.method == 'PUT':
            updated_data = request.json
            if not updated_data or 'content' not in updated_data: return jsonify({"error": "Conteúdo obrigatório."}), 400
            memory_to_modify.update(updated_data)
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao atualizar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify(memory_to_modify)
        if request.method == 'DELETE':
            persona["personal_knowledge_base"] = [mem for mem in knowledge_base if mem.get("id") != memory_id]
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao apagar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify({"message": "Memória apagada."})
        

# --- AUTOMATION APPROVAL ROUTES ---

@app.route('/approve/<draft_id>')
def approve_draft_route(draft_id):
    # This route is triggered when you tap the "Approve" link
    
    # 1. Get the draft details from our database
    draft = get_pending_draft(draft_id)
    if not draft:
        return "<h1>Draft Not Found</h1><p>This draft may have already been processed or does not exist.</p>", 404
    
    # 2. Get the Gmail service to send the email
    service = get_gmail_service()
    if not service:
        # If not logged in, we can't send. Redirect to login.
        return redirect(url_for('login'))

    try:
        # 3. Create and send the email (similar to your existing send_email_route)
        message = MIMEText(draft['body'], _charset='utf-8')
        message['to'] = draft['recipient']
        message['subject'] = draft['subject']
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        send_options = {'raw': raw_message, 'threadId': draft['thread_id']}
        service.users().messages().send(userId='me', body=send_options).execute()
        
        # 4. Update the draft's status in the database to 'approved'
        update_draft_status(draft_id, 'approved')
        
        logging.info(f"Draft {draft_id} approved and sent successfully.")
        return "<h1>Email Approved & Sent!</h1><p>The response has been sent successfully. You can close this window.</p>"

    except Exception as e:
        logging.error(f"Failed to send approved email for draft {draft_id}: {e}")
        return f"<h1>Error</h1><p>An error occurred while trying to send the email: {e}</p>", 500


@app.route('/reject/<draft_id>')
def reject_draft_route(draft_id):
    # This route is triggered when you tap the "Reject" link
    
    # We just need to update the status in the database. We don't send anything.
    if update_draft_status(draft_id, 'rejected'):
        logging.info(f"Draft {draft_id} was rejected by the user.")
        return "<h1>Draft Rejected</h1><p>The draft has been cancelled and will not be sent. You can close this window.</p>"
    else:
        return "<h1>Draft Not Found</h1><p>This draft may have already been processed or does not exist.</p>", 404
    
# --- AUTOMATION TRIGGER & SETUP ---

@app.route('/gmail-webhook', methods=['POST'])
def gmail_webhook_route():
    """Receives push notifications from Google Cloud Pub/Sub."""
    if 'message' not in request.json:
        return "Bad Request: No message data", 400

    try:
        # Decode the incoming message from Google
        message_data = base64.b64decode(request.json['message']['data']).decode('utf-8')
        message_json = json.loads(message_data)
        
        user_email = message_json['emailAddress']
        history_id = message_json['historyId']
        
        # Look up credentials in the database using the email from the notification
        user_credentials = get_user_credentials(user_email)
        
        if not user_credentials:
            logging.warning(f"Received webhook for {user_email}, but no credentials found in database. Skipping.")
            return "OK", 200

        # Build a temporary service instance to look up the thread ID
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
        history = service.users().history().list(userId='me', startHistoryId=history_id).execute()
        
        if 'history' in history:
            for item in history['history']:
                if 'messagesAdded' in item:
                    # We'll process the first new message we find.
                    thread_id = item['messagesAdded'][0]['message']['threadId']
                    
                    # Hand off the job to our Celery worker, passing the credentials
                    process_new_email.delay(thread_id, user_credentials)
                    
                    logging.info(f"Webhook received. Queued processing for thread {thread_id}.")
                    break # Stop after queuing the first new message

    except Exception as e:
        logging.error(f"Error processing webhook: {e}", exc_info=True)

    # Always return a success status code to Google to prevent retries.
    return "OK", 200


@app.route('/start-watch')
def start_watch_route():
    """Tells Gmail to start sending notifications for the logged-in user."""
    service = get_gmail_service()
    if not service:
        return redirect(url_for('login'))

    try:
        # Get the full topic name from your Google Cloud Project ID
        PROJECT_ID = "emailllm-463115" 
        topic_name = f"projects/{PROJECT_ID}/topics/gmail-inbox-updates"
        
        request_body = {
            'labelIds': ['INBOX'],
            'topicName': topic_name
        }
        
        response = service.users().watch(userId='me', body=request_body).execute()
        logging.info(f"Successfully started watching inbox. Response: {response}")
        return f"<h1>Success!</h1><p>Your inbox is now being watched. Expiration: {response.get('expiration')}</p>"

    except Exception as e:
        logging.error(f"Failed to start watch: {e}")
        return f"<h1>Error</h1><p>Could not start watch: {e}</p>", 500

# --- PONTO DE ENTRADA DA APLICAÇÃO ---
if __name__ == '__main__':
    logging.info("--- A Iniciar Aplicação Flask ---")
    if not os.path.exists(CLIENT_SECRETS_FILE): logging.critical("ERRO FATAL: `client_secret.json` não encontrado.")
    elif not GEMINI_API_KEY: logging.warning("A variável de ambiente GEMINI_API_KEY não está definida!")
    elif not ONTOLOGY_DATA: logging.critical("A ONTOLOGIA está vazia!")
    else: logging.info(f"{len(ONTOLOGY_DATA.get('personas', {}))} personas carregadas.")
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)
