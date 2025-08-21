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
import sqlite3
from automation.database import get_pending_draft, update_draft_status, save_user_credentials, get_user_credentials, is_thread_processed, mark_thread_as_processed, get_dashboard_stats

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
DATABASE_FILE = os.path.join(BASE_DIR, 'automation.db')

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
        
        # Lista de palavras-chave que indicam um remetente genérico
        generic_keywords = ['secretariado', 'organização', 'equipa', 'serviços', 'departamento', 'noreply', 'info@']
        
        # Se o nome contiver uma keyword genérica ou se o nome for parte do email (ex: "info"), considera-se genérico
        if any(keyword in name.lower() for keyword in generic_keywords) or '@' in name:
            return None, email # Retorna None para o nome para que seja omitido
            
        return name, email
        
    return None, "" # Fallback principal também retorna None

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

def find_relevant_knowledge(new_email_text, personal_knowledge, learned_corrections, top_n=10): # Aumentamos o top_n por segurança
    """
    Encontra o conhecimento relevante de forma mais robusta, confiando na pré-filtragem por keywords.
    """
    if not new_email_text: 
        return [], []

    stopwords = set(['a', 'o', 'e', 'de', 'do', 'da', 'em', 'um', 'uma', 'com', 'por', 'para'])
    new_email_words = set(re.sub(r'[^\w\s]', '', unidecode.unidecode(new_email_text.lower())).split()) - stopwords

    # 1. Busca na Memória Explícita (personal_knowledge_base)
    # A lógica foi simplificada: se uma keyword corresponde, a memória é relevante.
    # O cálculo complexo de Jaccard foi removido por ser ineficaz para factos curtos.
    relevant_memories = [
        mem.get("content") for mem in personal_knowledge
        if mem.get("content") and not set(mem.get("trigger_keywords", [])).isdisjoint(new_email_words)
    ]
    
    # Limita o número de memórias para evitar sobrecarregar o prompt, mas com um limite mais generoso.
    top_memories = relevant_memories[:top_n]

    # 2. Busca nas Correções Implícitas (learned_knowledge_base) - Lógica inalterada
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
    """Envia um e-mail a partir do fluxo MANUAL."""
    service = get_gmail_service()
    if not service: return jsonify({"error": "Não autenticado."}), 401
    
    data = request.json
    try:
        message = MIMEText(data['body'], _charset='utf-8')
        message['to'] = data['recipient']
        message['subject'] = data['subject']
        
        # Nota: Não adicionamos cabeçalhos de threading aqui porque este é o fluxo
        # manual. Se o utilizador colar uma thread inteira, podemos adicionar
        # os cabeçalhos se o threadId for fornecido.
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_options = {'raw': raw_message}
        
        # Se for uma resposta manual a um e-mail carregado, ele terá um threadId.
        if data.get('thread_id'):
            send_options['threadId'] = data['thread_id']
            # Numa versão futura, poderíamos também extrair o Message-ID para adicionar aqui.
            # Por agora, confiar no threadId é suficiente para o fluxo manual.

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
    
    # --- PROMPT ATUALIZADO COM FOCO NO CONTEXTO ---
    prompt = f"""
Analise o seguinte email. A sua tarefa é identificar as perguntas diretas ou pedidos de ação que exigem uma resposta do destinatário.
Para cada ponto, reescreva-o de forma a incluir o contexto essencial para que seja compreensível isoladamente.
Ignore informações gerais e notificações. A sua saída deve ser APENAS um objeto JSON.

Exemplo:
- Email Original: "Podes, por favor, clarificar este ponto? Refiro-me à duração da apresentação."
- Ponto Extraído Correto: "Clarificar se os 15 minutos da apresentação incluem o tempo para perguntas e respostas."

Intenções Válidas: 'confirmation', 'call_to_action', 'direct_question', 'generic_notification'.
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

    persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
    if not persona:
        return jsonify({"error": f"Persona '{persona_id}' não encontrada."}), 404

    sender_name, sender_email = parse_sender_info(original_email)

    # --- LÓGICA DO PROMPT RECONSTRUÍDA PARA MÁXIMA QUALIDADE ---

    # 1. Obter todo o conhecimento disponível
    personal_knowledge = persona.get("personal_knowledge_base", [])
    learned_corrections = persona.get("learned_knowledge_base", [])
    relevant_memories, relevant_corrections = find_relevant_knowledge(
        original_email, personal_knowledge, learned_corrections
    )

    # 2. Construir um bloco de contexto limpo e dinâmico
    prompt_context_parts = []
    
    # Adiciona sempre os princípios chave, que são a base da persona
    style_profile = persona.get("style_profile", {})
    key_principles = style_profile.get('key_principles', [])
    if key_principles:
        prompt_context_parts.append("--- Princípios Chave da Persona (Regras Base) ---\n- " + "\n- ".join(key_principles))

    # Adiciona contexto do interlocutor, se existir
    if sender_email:
        profiles = ONTOLOGY_DATA.get("interlocutor_profiles", {})
        for key, profile in profiles.items():
            if profile.get("email_match", "").lower() == sender_email.lower():
                # Adiciona o contexto geral como antes
                context_parts = [f"Nome: {profile.get('full_name')}", f"Relação: {profile.get('relationship')}"]
                interlocutor_context = "--- Contexto Sobre o Interlocutor ---\n" + " | ".join(filter(None, context_parts))
                prompt_context_parts.append(interlocutor_context)

                # NOVA PARTE: Adiciona as regras de personalização com prioridade máxima
                personalization_rules = profile.get("personalization_rules", [])
                if personalization_rules:
                    formatted_rules = "\n- ".join(personalization_rules)
                    override_rules_context = f"--- Regras Específicas Para Este Contacto (Prioridade Máxima) ---\n- {formatted_rules}"
                    prompt_context_parts.append(override_rules_context)
                break # Sai do loop assim que encontra o perfil
    
    # Adiciona memórias relevantes, APENAS se existirem
    if relevant_memories:
        formatted_memories = "\n- ".join(relevant_memories)
        prompt_context_parts.append(f"--- Informação Relevante da Memória (Usar no conteúdo) ---\n- {formatted_memories}")

    # Adiciona correções aprendidas, APENAS se existirem
    if relevant_corrections:
        formatted_corrections = "\n- ".join(relevant_corrections)
        prompt_context_parts.append(f"--- Regras Aprendidas (Sobrepõem-se aos Princípios Chave) ---\n- {formatted_corrections}")

    # Junta todas as partes do contexto numa única variável
    final_context_block = "\n\n".join(prompt_context_parts)

    # 3. Obter as diretrizes do utilizador
    guidance_parts = []
    for item in user_inputs:
        point = item.get('point', '').strip()      # O ponto original extraído pela análise
        guidance = item.get('guidance', '').strip()  # A resposta que inseriu

        if guidance: # Apenas processa se deu uma resposta
            # Criamos uma instrução explícita que liga a sua resposta ao ponto de ação
            instruction = f"Relativamente à questão '{point}', a informação a transmitir é: '{guidance}'."
            guidance_parts.append(instruction)

    if not guidance_parts:
        guidance_summary = "Nenhuma instrução específica. Gerar uma resposta com base no contexto do email e na persona."
    else:
        guidance_summary = "\n- ".join(guidance_parts)


    # 4. Construir o prompt final, agora muito mais limpo e direto
    default_ids = persona.get("default_components", {})

    recipient_first_name = ""
    if sender_name:  # This checks if sender_name is not None
        recipient_first_name = sender_name.split()[0]

    greeting_text = resolve_component(get_component("greetings", default_ids.get("greeting_id")), recipient_first_name)


            
    closing_text = resolve_component(get_component("closings", default_ids.get("closing_id")))
    signature_text = resolve_component(get_component("signatures", default_ids.get("signature_id")))

    prompt = f"""
Você é um assistente de escrita que encarna a persona '{persona.get('label', persona_id)}'.
A sua tarefa é escrever um rascunho de e-mail completo e natural.

{final_context_block}

--- E-mail Original a Responder ---
{original_email}

--- Instruções do Utilizador (Seguir à risca) ---
{guidance_summary}

--- Rascunho Final (Comece aqui) ---
{greeting_text}

[ESCREVA O CORPO DO E-MAIL AQUI]

{closing_text}
{signature_text}
"""

    llm_response = call_gemini(prompt, temperature=0.5)
    if "error" in llm_response:
        # Para debugging, podemos devolver o prompt que foi gerado
        return jsonify({"error": llm_response["error"], "prompt_sent": prompt}), 500

    raw_draft = llm_response.get("text", "").strip()
    
    # Limpeza da resposta da IA para garantir que não inclui texto extra
    if "--- Rascunho Final (Comece aqui) ---" in raw_draft:
        raw_draft = raw_draft.split("--- Rascunho Final (Comece aqui) ---")[-1]

    final_draft = raw_draft.replace('[ESCREVA O CORPO DO E-MAIL AQUI]', '').strip()
    final_draft = re.sub(r'\n{3,}', '\n\n', final_draft).strip()

    # Devolvemos também o prompt para fins de depuração, se necessário
    return jsonify({"draft": final_draft, "prompt_sent_for_debug": prompt})

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
        "make_formal": "Reescreva o texto para ser mais formal, usando vocabulário profissional. Usa PT-PT.",
        "make_casual": "Reescreva o texto com um tom mais casual e descontraído. Usa PT-PT.",
        "shorten": "Condense o texto ao máximo, mantendo apenas a informação essencial. Usa PT-PT.",
        "expand": "Elabore sobre o texto, adicionando mais detalhes e contexto para o enriquecer. Usa PT-PT.",
        "simplify": "Reescreva o texto com linguagem mais simples e frases mais curtas para ser fácil de entender. Usa PT-PT.",
        "rephrase": "Refraseie o texto com palavras diferentes, mantendo o significado e o tom originais. Usa PT-PT.",
        "translate_en": "Traduza o seguinte texto para inglês profissional e natural.",
        "find_synonym": "Sugira um sinónimo para a palavra ou frase selecionada. Devolva apenas a palavra ou frase sinónima em PT-PT.",
        "correct_grammar": "Corrija a gramática e a ortografia do texto, mantendo o significado original. Usa português europeu.",
        "make_persuasive": "Altera o texto para um tom mais persuasivo e convincente, ideal para propostas ou marketing. Usa PT-PT"
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
    """Esta rota é acionada pelo link do Pushover."""
    draft = get_pending_draft(draft_id)
    if not draft:
        return "<h1>Rascunho Não Encontrado</h1><p>Este rascunho pode já ter sido processado ou não existe.</p>", 404

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM user_credentials LIMIT 1")
    user_row = cursor.fetchone()
    conn.close()

    if not user_row:
        return "<h1>Erro</h1><p>Nenhuma credencial de utilizador encontrada na base de dados.</p>", 500

    user_email = user_row[0]
    user_credentials = get_user_credentials(user_email)

    if not user_credentials:
        return "<h1>Erro</h1><p>Não foi possível carregar as credenciais para o utilizador.</p>", 500

    try:
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

        message = MIMEText(draft['body'], _charset='utf-8')
        message['to'] = draft['recipient']
        message['subject'] = draft['subject']
        
        # --- ADICIONAR CABEÇALHOS DE THREADING ---
        if draft.get('original_message_id'):
            message['In-Reply-To'] = draft['original_message_id']
            message['References'] = draft['original_message_id']
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_options = {'raw': raw_message, 'threadId': draft['thread_id']}
        service.users().messages().send(userId='me', body=send_options).execute()

        update_draft_status(draft_id, 'approved')
        logging.info(f"Pushover: Rascunho {draft_id} aprovado e enviado com sucesso.")
        return "<h1>E-mail Aprovado & Enviado!</h1><p>A resposta foi enviada com sucesso. Pode fechar esta janela.</p>"

    except Exception as e:
        logging.error(f"Falha ao enviar e-mail aprovado para o rascunho {draft_id}: {e}")
        return f"<h1>Erro</h1><p>Ocorreu um erro ao tentar enviar o e-mail: {e}</p>", 500

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
    from automation.celery_worker import process_new_email
    """Receives push notifications from Google Cloud Pub/Sub."""
    if 'message' not in request.json:
        return "Bad Request: No message data", 400

    try:
        message_data = base64.b64decode(request.json['message']['data']).decode('utf-8')
        message_json = json.loads(message_data)
        user_email = message_json['emailAddress']
        
        user_credentials = get_user_credentials(user_email)
        if not user_credentials:
            logging.warning(f"Received webhook for {user_email}, but no credentials found in database. Skipping.")
            return "OK", 200

        # --- FINAL, MOST ROBUST LOGIC ---
        creds = google.oauth2.credentials.Credentials(**user_credentials)
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
        
        # Directly ask for the most recent thread in the inbox
        response = service.users().threads().list(userId='me', labelIds=['INBOX'], maxResults=1).execute()
        
        if 'threads' in response and response['threads']:
            latest_thread_id = response['threads'][0]['id']
            
            # Check if we've already processed this thread
            if is_thread_processed(latest_thread_id):
                logging.info(f"Webhook: Thread {latest_thread_id} has already been processed. Skipping.")
            else:
                # Mark it as processed now to prevent duplicates, then start the job
                mark_thread_as_processed(latest_thread_id)
                process_new_email.delay(latest_thread_id, user_credentials)
                logging.info(f"Webhook: Found new thread {latest_thread_id}. Queued for processing.")
        else:
            logging.info("Webhook received, but no threads found in inbox. Skipping.")
            
    except Exception as e:
        logging.error(f"Error processing webhook: {e}", exc_info=True)

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

# --- NOVAS ROTAS PARA O DASHBOARD ---

@app.route('/api/dashboard_stats')
def dashboard_stats_route():
    """Fornece todas as estatísticas necessárias para o dashboard."""
    if 'credentials' not in session:
        return jsonify({"error": "Não autenticado."}), 401
    try:
        stats = get_dashboard_stats()
        return jsonify(stats)
    except Exception as e:
        logging.error(f"Erro ao obter estatísticas do dashboard: {e}")
        return jsonify({"error": "Erro interno ao buscar dados."}), 500

@app.route('/api/draft/<draft_id>/status', methods=['POST'])
def update_draft_status_route(draft_id):
    """Atualiza o status de um rascunho (aprovado/rejeitado) a partir do dashboard."""
    if 'credentials' not in session:
        return jsonify({"error": "Não autenticado."}), 401
    
    data = request.json
    new_status = data.get('status')

    if new_status not in ['approved', 'rejected']:
        return jsonify({"error": "Status inválido."}), 400

    try:
        if new_status == 'approved':
            # A lógica de aprovação real (envio de email) é tratada pela rota /approve/<id>
            # Aqui, apenas simulamos a atualização para o frontend, ou poderíamos chamar essa lógica.
            # Por simplicidade, vamos apenas atualizar a base de dados.
            # A notificação Pushover já envia para a rota /approve que faz o trabalho.
            # Esta rota é para o clique direto no dashboard.
            if update_draft_status(draft_id, 'approved'):
                 # AQUI você poderia adicionar a lógica para enviar o e-mail se necessário
                return jsonify({"message": f"Rascunho {draft_id} marcado como aprovado."})
            else:
                return jsonify({"error": "Rascunho não encontrado."}), 404

        elif new_status == 'rejected':
            if update_draft_status(draft_id, 'rejected'):
                return jsonify({"message": f"Rascunho {draft_id} rejeitado."})
            else:
                return jsonify({"error": "Rascunho não encontrado."}), 404
                
    except Exception as e:
        logging.error(f"Erro ao atualizar o status do rascunho {draft_id}: {e}")
        return jsonify({"error": "Erro interno do servidor."}), 500
    
@app.route('/api/draft/<draft_id>/send', methods=['POST'])
def send_draft_from_dashboard_route(draft_id):
    """Envia um e-mail aprovado diretamente a partir de um pedido da API do dashboard."""
    if 'credentials' not in session:
        return jsonify({"error": "Não autenticado."}), 401

    draft = get_pending_draft(draft_id)
    if not draft:
        return jsonify({"error": "Rascunho não encontrado ou já processado."}), 404

    try:
        creds = google.oauth2.credentials.Credentials(**session['credentials'])
        if creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
            session['credentials'] = {
                'token': creds.token, 'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri, 'client_id': creds.client_id,
                'client_secret': creds.client_secret, 'scopes': creds.scopes
            }

        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

        message = MIMEText(draft['body'], _charset='utf-8')
        message['to'] = draft['recipient']
        message['subject'] = draft['subject']

        # --- ADICIONAR CABEÇALHOS DE THREADING ---
        if draft.get('original_message_id'):
            message['In-Reply-To'] = draft['original_message_id']
            message['References'] = draft['original_message_id']

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_options = {'raw': raw_message, 'threadId': draft['thread_id']}
        service.users().messages().send(userId='me', body=send_options).execute()

        update_draft_status(draft_id, 'approved')
        logging.info(f"Dashboard: Rascunho {draft_id} aprovado e enviado com sucesso.")
        return jsonify({"message": "Email enviado com sucesso!"})

    except Exception as e:
        logging.error(f"Dashboard: Falha ao enviar e-mail para o rascunho {draft_id}: {e}")
        return jsonify({"error": f"Ocorreu um erro ao tentar enviar o e-mail: {e}"}), 500
    

# --- PONTO DE ENTRADA DA APLICAÇÃO ---
if __name__ == '__main__':
    logging.info("--- A Iniciar Aplicação Flask ---")
    if not os.path.exists(CLIENT_SECRETS_FILE): logging.critical("ERRO FATAL: `client_secret.json` não encontrado.")
    elif not GEMINI_API_KEY: logging.warning("A variável de ambiente GEMINI_API_KEY não está definida!")
    elif not ONTOLOGY_DATA: logging.critical("A ONTOLOGIA está vazia!")
    else: logging.info(f"{len(ONTOLOGY_DATA.get('personas', {}))} personas carregadas.")
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)