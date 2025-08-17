
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
import unidecode # Necessita 'pip install unidecode'
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
import google.auth.transport.requests # Necessário para refresh de tokens

# --- CONFIGURAÇÃO INICIAL E CONSTANTES ---
# Esta linha indica à biblioteca OAuth para permitir HTTP para testes locais.
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

# --- MELHORIA: Adicionado 'openid' para compatibilidade com OpenID Connect ---
SCOPES = [
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'openid' # Adicionado
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
    """Obtém um componente de comunicação da ontologia."""
    if not component_id: return None
    return ONTOLOGY_DATA.get("communication_components", {}).get(component_type, {}).get(component_id)

def get_current_time_of_day():
    """Determina se é manhã, tarde ou noite."""
    current_hour = datetime.datetime.now().hour
    if 5 <= current_hour < 13: return "morning"
    if 13 <= current_hour < 20: return "afternoon"
    return "evening"

def resolve_component(component, recipient_name=""):
    """Processa as condições de um componente e retorna o texto final, escolhendo aleatoriamente se houver múltiplas opções."""
    if not component or not component.get('content'): return ""
    
    time_of_day = get_current_time_of_day()
    
    valid_options = []
    for item in component['content']:
        condition = item.get('condition')
        if not condition:
            valid_options.append(item)
        elif "time_of_day" in condition and condition.endswith(time_of_day):
            valid_options.append(item)

    if not valid_options:
        return ""

    chosen_item = random.choice(valid_options)
    text_template = chosen_item.get('text', "")
    return text_template.replace("{{recipient_name}}", recipient_name).strip()

def parse_sender_info(original_email_text):
    """Extrai de forma robusta o nome e o email do remetente."""
    match = re.search(r"(?:From|De):\s*['\"]?(.*?)['\"]?\s*<(.*?)>", original_email_text, re.IGNORECASE)
    if match:
        name, email = match.group(1).strip(), match.group(2).strip()
        if '@' in name:
            name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
        name = name.replace('"', '')
        return name, email
    
    match = re.search(r"(?:From|De):\s*(.*?)\s*<(.*?)>", original_email_text, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
        
    return "Equipa", ""

# --- COMUNICAÇÃO COM A API GEMINI ---
def call_gemini(prompt, model=GEMINI_MODEL, temperature=0.6):
    """Envia um prompt à API do Gemini e retorna a resposta."""
    if not GEMINI_API_KEY:
        return {"error": "ERROR_CONFIG: Chave da API do Gemini não configurada."}

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "text/plain"},
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        data = response.json()

        if data.get('promptFeedback', {}).get('blockReason'):
            reason = data['promptFeedback']['blockReason']
            return {"error": f"ERROR_GEMINI_BLOCKED_PROMPT: Prompt bloqueado. Motivo: {reason}"}
        
        if candidates := data.get('candidates'):
            if text_parts := candidates[0].get('content', {}).get('parts', []):
                return {"text": text_parts[0]['text'].strip()}

        return {"error": "ERROR_GEMINI_PARSE: Resposta válida, mas nenhum texto gerado encontrado."}
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response else "N/A"
        return {"error": f"ERROR_GEMINI_REQUEST: O pedido à API falhou com o estado {status}."}
    except Exception as e:
        return {"error": f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"}

# --- ROTAS DE AUTENTICAÇÃO E GMAIL API ---

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
        session['credentials'] = {
            'token': credentials.token, 'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri, 'client_id': credentials.client_id,
            'client_secret': credentials.client_secret, 'scopes': credentials.scopes
        }
        return redirect(url_for('index_route'))
    except Exception as e:
        logging.error(f"Erro durante a autorização OAuth: {e}")
        return "Erro na autorização.", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index_route'))

# --- MELHORIA: Função de serviço do Gmail robusta com refresh de token ---
def get_gmail_service():
    """Cria um objeto de serviço do Gmail autorizado a partir das credenciais da sessão, com refresh automático."""
    if 'credentials' not in session:
        return None
    try:
        # Recria o objeto de credenciais a partir dos dados da sessão
        creds = google.oauth2.credentials.Credentials(**session['credentials'])
        
        # Verifica se o token de acesso expirou e se existe um refresh token
        if creds.expired and creds.refresh_token:
            logging.info("Credenciais do Gmail expiradas. A tentar atualizar o token...")
            # Atualiza as credenciais
            creds.refresh(google.auth.transport.requests.Request())
            # Guarda as novas credenciais (com o novo token de acesso) na sessão
            session['credentials'] = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }
            logging.info("Token do Gmail atualizado com sucesso.")

        # Constrói e retorna o objeto de serviço da API
        return googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
        
    except Exception as e:
        logging.error(f"Falha ao criar o serviço do Gmail (credenciais inválidas?): {e}\n{traceback.format_exc()}")
        # Limpa a sessão para forçar um novo login em caso de erro grave
        session.clear()
        return None

@app.route('/api/emails')
def fetch_emails_route():
    service = get_gmail_service()
    if not service: return jsonify({"error": "Utilizador não autenticado ou sessão expirada."}), 401
    try:
        results = service.users().messages().list(userId='me', maxResults=15, q="category:primary in:inbox").execute()
        messages = results.get('messages', [])
        email_list = []
        for msg in messages:
            message_meta = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From', 'Date']).execute()
            headers = message_meta.get('payload', {}).get('headers', [])
            email_list.append({
                'id': message_meta['id'], 'threadId': message_meta['threadId'],
                'subject': next((h['value'] for h in headers if h['name'] == 'Subject'), '(Sem Assunto)'),
                'sender': next((h['value'] for h in headers if h['name'] == 'From'), 'Desconhecido'),
                'snippet': message_meta.get('snippet', '')
            })
        return jsonify(email_list)
    except Exception as e:
        return jsonify({"error": f"Falha ao obter emails: {e}"}), 500

@app.route('/api/thread/<thread_id>')
def get_thread_route(thread_id):
    service = get_gmail_service()
    if not service: return jsonify({"error": "Utilizador não autenticado ou sessão expirada."}), 401
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
        
        first_message_headers = thread['messages'][0].get('payload', {}).get('headers', [])
        original_sender = next((h['value'] for h in first_message_headers if h['name'].lower() == 'from'), '')
        original_subject = next((h['value'] for h in first_message_headers if h['name'].lower() == 'subject'), '')

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
    if not service: return jsonify({"error": "Utilizador não autenticado ou sessão expirada."}), 401
    data = request.json
    try:
        message = MIMEText(data['body'], _charset='utf-8')
        message['to'] = data['recipient']
        message['subject'] = data['subject']
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_options = {'raw': raw_message}
        if data.get('thread_id'):
            send_options['threadId'] = data['thread_id']
        sent_message = service.users().messages().send(userId='me', body=send_options).execute()
        return jsonify({"message": "Email enviado com sucesso!", "id": sent_message['id']})
    except Exception as e:
        return jsonify({"error": f"Falha ao enviar email: {e}"}), 500

# --- ROTAS PRINCIPAIS DA APLICAÇÃO ---

@app.route('/')
def index_route():
    """Serve a página principal."""
    if DEBUG_MODE:
        global ONTOLOGY_DATA
        ONTOLOGY_DATA = load_ontology_file()
    
    personas_dict = {key: {"name": data.get("label", key)} for key, data in ONTOLOGY_DATA.get("personas", {}).items()}
    return render_template('index.html', personas_dict=personas_dict, is_logged_in='credentials' in session)

@app.route('/analyze', methods=['POST'])
def analyze_email_route():
    """Analisa o email para extrair a INTENÇÃO e os pontos de ação."""
    email_text = request.json.get('email_text', '')
    if not email_text.strip():
        return jsonify({"error": "O texto do email não pode estar vazio."}), 400

    prompt = f"""Analise o email e classifique a sua intenção principal. Extraia também os pontos que necessitam de uma resposta do utilizador.
Intenções Válidas: 'confirmation' (confirma algo já sabido), 'call_to_action' (pede para fazer algo), 'direct_question' (faz uma pergunta específica), 'generic_notification' (apenas informa, não requer resposta).
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
        if "email_intent" not in analysis_data or "points" not in analysis_data:
            raise ValueError("O JSON da análise não contém as chaves 'email_intent' ou 'points'.")
        return jsonify(analysis_data)
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Falha ao analisar JSON da análise: {e}. Resposta bruta: {llm_response.get('text', '')}")
        return jsonify({"error": "Falha ao processar a análise da IA."}), 500

@app.route('/draft', methods=['POST'])
def draft_response_route():
    """Orquestra a criação do rascunho com base na INTENÇÃO e nas DIRETRIZES ABSOLUTAS."""
    data = request.json
    original_email = data.get('original_email', '')
    persona_id = data.get('persona_name')
    user_inputs = data.get('user_inputs', [])
    email_intent = data.get('email_intent')

    sender_name, sender_email = parse_sender_info(original_email)
    
    monologue = ["<monologo>"]
    persona = ONTOLOGY_DATA.get("personas", {}).get(persona_id)
    if not persona: return jsonify({"error": f"Persona '{persona_id}' não encontrada."}), 404

    monologue.append("  <fase_0_analise_perfil_estilo>")
    style_profile = persona.get("style_profile", {})
    monologue.append(f"    <principios_chave>{' '.join(style_profile.get('key_principles', ['N/A']))}</principios_chave>")
    monologue.append("  </fase_0_analise_perfil_estilo>")

    monologue.append("  <fase_1_analise_intencao_e_diretrizes>")
    monologue.append(f"    <intencao_detetada>{email_intent or 'Não fornecida'}</intencao_detetada>")
    
    guidance_summary = ""
    if user_inputs:
        guidance_points = [item.get('guidance', '').strip() for item in user_inputs if item.get('guidance', '').strip()]
        if guidance_points:
            guidance_summary = "\n- " + "\n- ".join(guidance_points)
    
    if not guidance_summary and email_intent == 'confirmation':
        guidance_summary = "\n- Agradecer brevemente pela confirmação."
        monologue.append("    <acao_proativa>Intenção de confirmação detetada. A gerar resposta breve e automática.</acao_proativa>")

    monologue.append(f"    <diretrizes_utilizador>{guidance_summary or 'Nenhuma.'}</diretrizes_utilizador>")
    monologue.append("  </fase_1_analise_intencao_e_diretrizes>")

    monologue.append("  <fase_2_selecao_componentes_e_adaptacao>")
    default_ids = persona.get("default_components", {})
    greeting_id = default_ids.get("greeting_id")
    
    if sender_name.lower() in ["equipa", "departamento", "suporte"]:
         greeting_text = resolve_component(get_component("greetings", greeting_id), "").rstrip(',')
    else:
         greeting_text = resolve_component(get_component("greetings", greeting_id), sender_name.split()[0])

    closing_text = resolve_component(get_component("closings", default_ids.get("closing_id")))
    signature_text = resolve_component(get_component("signatures", default_ids.get("signature_id")))
    monologue.append(f"    <saudacao_resolvida>{greeting_text}</saudacao_resolvida>")
    monologue.append(f"    <despedida_resolvida>{closing_text}</despedida_resolvida>")
    monologue.append("  </fase_2_selecao_componentes_e_adaptacao>")
    monologue.append("</monologo>")

    prompt = f"""Atue como um assistente de escrita de emails que personifica '{persona['label']}'.
A sua tarefa é gerar uma resposta de email COMPLETA, natural e profissional, seguindo regras estritas.

--- MONÓLOGO DE RACIOCÍNIO (Contexto Interno) ---
{''.join(monologue)}

--- DIRETRIZES ABSOLUTAS DO UTILIZADOR (OBRIGATÓRIO CUMPRIR SEM DESVIOS) ---
{guidance_summary or "Nenhuma diretriz específica. Siga a lógica da intenção detetada e os princípios da persona."}

--- EMAIL ORIGINAL A RESPONDER ---
{original_email}

--- TAREFA ---
1.  **PRIORIDADE MÁXIMA:** Cumpra as 'Diretrizes Absolutas do Utilizador'. Elas sobrepõem-se a qualquer outra interpretação.
2.  Incorpore os 'Princípios Chave' da persona (Fase 0 do monólogo) em todo o texto.
3.  Use os componentes resolvidos (saudação, despedida) como a estrutura final.
4.  Escreva o CORPO do email, respondendo ao email original de acordo com a intenção e as diretrizes.
5.  **NÃO REPITA** informação. Seja breve e eficiente.

---RASCUNHO-FINAL---
"""
    llm_response = call_gemini(prompt, temperature=0.5)
    if "error" in llm_response: return jsonify({"error": llm_response["error"], "monologue": "\n".join(monologue)}), 500

    raw_draft = llm_response.get("text", "").strip()
    
    final_draft = raw_draft.split("---RASCUNHO-FINAL---")[-1].strip()
    
    if not final_draft or "MONÓLOGO DE RACIOCÍNIO" in final_draft:
        match = re.search(r"(Bom dia|Boa tarde|Boa noite|Olá)[\s\S]*", raw_draft, re.IGNORECASE)
        if match:
            final_draft = match.group(0).strip()
        else:
            final_draft = raw_draft

    return jsonify({"draft": final_draft, "monologue": "\n".join(monologue)})

# --- ROTAS ADICIONAIS ---
@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route():
    """Gera sugestões de diretrizes de forma mais inteligente."""
    data = request.json
    point_to_address = data.get('point_to_address')
    direction = data.get('direction', 'outro')

    if not ONTOLOGY_DATA.get("personas", {}).get(data['persona_name']):
        return jsonify({"error": "Persona não encontrada."}), 404
    
    direction_map = {'sim': 'AFIRMATIVO', 'nao': 'NEGATIVO', 'outro': 'NEUTRO/DETALHADO'}
    direction_text = direction_map.get(direction)

    if direction == 'outro':
        prompt = f"""Atue como um especialista e responda diretamente à seguinte pergunta de forma clara, profissional e completa, como se estivesse a redigir a resposta para um email.
Pergunta: "{point_to_address}"
Saída: APENAS o texto da resposta.
"""
    else:
        prompt = f"""Formule uma resposta curta e {direction_text} ao seguinte ponto, mantendo um tom profissional.
Ponto: "{point_to_address}"
Saída: APENAS o texto da resposta curta.
"""
    
    llm_response = call_gemini(prompt, temperature=0.2)
    
    if "error" in llm_response: return jsonify(llm_response), 500
    return jsonify({"suggestion": llm_response.get("text", "").strip()})

@app.route('/refine_text', methods=['POST'])
def refine_text_route():
    data = request.json
    if not ONTOLOGY_DATA.get("personas", {}).get(data['persona_name']):
        return jsonify({"error": "Persona não encontrada."}), 404

    action_instructions = {
        "make_formal": "Reescreva o 'Texto Selecionado' para ser mais formal.",
        "make_casual": "Reescreva o 'Texto Selecionado' para ser mais casual.",
        "shorten": "Condense o 'Texto Selecionado' ao máximo.",
        "expand": "Elabore sobre o 'Texto Selecionado'.",
        "simplify": "Reescreva o 'Texto Selecionado' com linguagem mais simples.",
        "improve_flow": "Melhore o fluxo e a coesão do 'Texto Selecionado'.",
        "rephrase": "Refraseie o 'Texto Selecionado'.",
        "translate_en": "Traduza o 'Texto Selecionado' para inglês profissional."
    }
    instruction = action_instructions.get(data['action'], f"Modifique o 'Texto Selecionado'.")
    prompt = f"Ação: {instruction}\nContexto do Rascunho Completo:\n{data['full_context']}\n---\nTexto Selecionado para Modificar:\n{data['selected_text']}\n---\nSaída: APENAS o texto modificado."
    llm_response = call_gemini(prompt, temperature=0.4)

    if "error" in llm_response: return jsonify(llm_response), 500
    return jsonify({"refined_text": llm_response.get("text", "")})

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback_route():
    logging.info("A rota /submit_feedback foi chamada.")
    data = request.json
    persona_name = data.get('persona_name')
    if not persona_name:
        logging.error("Pedido de feedback recebido sem 'persona_name'.")
        return jsonify({"error": "Nome da persona é obrigatório."}), 400

    ai_original_response = data.get('ai_original_response', '')
    user_corrected_output = data.get('user_corrected_output', '')
    interaction_context = data.get('interaction_context', {})
    original_email = interaction_context.get('original_email_text', 'N/A')

    logging.info("A iniciar a inferência de regra a partir do feedback.")
    inference_prompt = f"""
    Analise a seguinte interação de email para extrair um princípio de aprendizagem.
    Um assistente de IA, agindo como a persona '{persona_name}', produziu uma "Resposta Original".
    O utilizador corrigiu-a com uma "Versão Melhorada".
    A sua tarefa é identificar a principal diferença e formular uma regra concisa e acionável em português (pt-PT) que a IA deve seguir no futuro para se alinhar melhor com a preferência do utilizador.

    --- CONTEXTO DO EMAIL ORIGINAL QUE O UTILIZADOR RECEBEU ---
    {original_email}

    --- RESPOSTA ORIGINAL DA IA (INCORRETA/MELHORÁVEL) ---
    {ai_original_response}

    --- VERSÃO MELHORADA FORNECIDA PELO UTILIZADOR (CORRETA) ---
    {user_corrected_output}

    --- ANÁLISE E TAREFA ---
    1. Compare a "Resposta Original da IA" com a "Versão Melhorada do Utilizador".
    2. Identifique a mudança mais significativa: foi no tom, na formalidade, na estrutura, na adição/remoção de informação, ou na eficiência?
    3. Com base nesta diferença, formule uma única regra imperativa e geral. A regra deve ser curta, clara e começar com um verbo.
    
    Exemplos de boas regras:
    - "Evitar usar a palavra 'ansiosamente' e manter um tom mais neutro."
    - "Confirmar sempre a receção do pedido antes de dar a resposta."
    - "Manter as respostas a notificações simples extremamente curtas, como 'Recebido, obrigado.'."
    - "Usar sempre a saudação 'Bom dia,' sem o nome do destinatário para emails de equipas."

    --- SAÍDA ---
    Produza APENAS um objeto JSON com uma única chave "inferred_rule".
    {{
      "inferred_rule": "Sua regra inferida aqui."
    }}
    """

    inferred_rule = "Não foi possível inferir uma regra específica."
    llm_response = call_gemini(inference_prompt, temperature=0.3)
    
    if "error" in llm_response:
        logging.warning(f"Falha na inferência da regra para o feedback: {llm_response['error']}")
    else:
        try:
            json_str_match = re.search(r'\{.*\}', llm_response.get("text", ""), re.DOTALL)
            if json_str_match:
                rule_data = json.loads(json_str_match.group(0))
                inferred_rule = rule_data.get("inferred_rule", inferred_rule)
                logging.info(f"Regra inferida com sucesso: '{inferred_rule}'")
            else:
                 logging.warning(f"A resposta da inferência de regra não continha JSON válido. Resposta: {llm_response.get('text', '')}")
        except Exception as e:
            logging.error(f"Erro ao analisar o JSON da regra inferida: {e}")

    try:
        with ontology_file_lock:
            logging.info("A adquirir lock para modificar o ficheiro de ontologia.")
            current_data = load_ontology_file()
            persona_obj = current_data.get("personas", {}).get(persona_name)
            
            if not persona_obj:
                logging.error(f"Persona '{persona_name}' não encontrada no ficheiro ao tentar salvar.")
                return jsonify({"error": f"Persona '{persona_name}' não encontrada no ficheiro."}), 404
            
            persona_obj.setdefault('learned_knowledge_base', [])
            
            feedback_entry = {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "inferred_rule_pt": inferred_rule,
                "ai_original_response_text": ai_original_response,
                "user_corrected_output_text": user_corrected_output,
                "interaction_context_snapshot": interaction_context
            }
            persona_obj['learned_knowledge_base'].append(feedback_entry)
            
            logging.info("A tentar salvar os dados no ficheiro JSON...")
            if not save_ontology_file(current_data):
                raise IOError("A função save_ontology_file retornou 'False'. Verifique os logs para o erro de escrita.")
            
            global ONTOLOGY_DATA
            ONTOLOGY_DATA = current_data
            logging.info("Ficheiro salvo e ontologia em memória atualizada. A enviar resposta de sucesso.")

        return jsonify({
            "message": "Feedback submetido e nova regra aprendida com sucesso!",
            "inferred_rule": inferred_rule
        }), 200

    except Exception as e:
        logging.error(f"ERRO CRÍTICO na rota /submit_feedback ao tentar salvar: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Ocorreu um erro no servidor ao salvar o feedback: {e}"}), 500


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
            if new_key in current_data.get("personas", {}): return jsonify({"error": "Chave de persona já existe."}), 409
            
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
            current_data["personas"][persona_key] = updated_data
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao salvar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify({"message": "Persona atualizada."})

        if request.method == 'DELETE':
            del current_data["personas"][persona_key]
            if not save_ontology_file(current_data): return jsonify({"error": "Falha ao salvar."}), 500
            ONTOLOGY_DATA = current_data
            return jsonify({"message": "Persona removida."})

# --- PONTO DE ENTRADA DA APLICAÇÃO ---
if __name__ == '__main__':
    logging.info("--- A Iniciar Aplicação Flask com Nova Arquitetura de Ontologia e Lógica de Intenção ---")
    if not os.path.exists(CLIENT_SECRETS_FILE):
        logging.critical(f"ERRO FATAL: `client_secret.json` não encontrado.")
    elif not GEMINI_API_KEY:
        logging.warning("A variável de ambiente GEMINI_API_KEY não está definida!")
    elif not ONTOLOGY_DATA:
        logging.critical("A ONTOLOGIA está vazia! A aplicação não funcionará corretamente.")
    else:
        logging.info(f"{len(ONTOLOGY_DATA.get('personas', {}))} personas carregadas.")

    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)