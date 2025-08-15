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
import unidecode # Necessita 'pip install unidecode' para normalizar nomes sem acentos
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
import google.auth.transport.requests # Necessário para refresh de tokens

# --- FIX FOR LOCAL DEVELOPMENT ---
# Esta linha indica à biblioteca OAuth para permitir HTTP para testes locais.
# DEVE ser definida antes de outras importações que possam usar oauthlib.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# ---------------------------------

# Carrega variáveis de ambiente do ficheiro .env
load_dotenv()

# Configura o registo básico para melhor acompanhamento
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

# --- Configuração da Aplicação ---
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GENERATION_TEMPERATURE = float(os.environ.get('GENERATION_TEMPERATURE', 0.75)) # Temperatura para geração de rascunhos
REFINEMENT_TEMPERATURE = float(os.environ.get('REFINEMENT_TEMPERATURE', 0.4))  # Temperatura para refinamento de texto
ANALYSIS_TEMPERATURE = 0.2                                                # Temperatura para análises (mais determinística)

DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# --- Configuração do Gemini ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-lite')

# --- Caminhos de Ficheiros ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONAS_FILE = os.path.join(BASE_DIR, 'personas2.0.json')
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, 'client_secret.json') # Caminho para o OAuth do Gmail

# Inicialização da Aplicação Flask
app = Flask(__name__)
# É necessária uma chave secreta para a gestão de sessões do Flask
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'uma-chave-secreta-para-sessoes')

if DEBUG_MODE:
    app.logger.setLevel(logging.DEBUG)
else:
    app.logger.setLevel(logging.INFO)

# --- Configuração da API do Gmail ---
SCOPES = [
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose', # OBRIGATÓRIO para enviar emails
    'openid'
]

# Bloqueio para proteger o acesso concorrente ao ficheiro personas.json
personas_file_lock = threading.Lock()

# --- Funções de Carregamento e Gestão de Personas ---
def load_persona_file():
    """Carrega ou recarrega de forma segura o conteúdo do ficheiro de personas."""
    try:
        with personas_file_lock:
            if not os.path.exists(PERSONAS_FILE):
                logging.error(f"ERRO CRÍTICO: Ficheiro de personas '{PERSONAS_FILE}' não encontrado.")
                return {}
            with open(PERSONAS_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    logging.warning(f"Ficheiro de personas '{PERSONAS_FILE}' está vazio.")
                    return {}
                full_data = json.loads(content)
        logging.info(f"Dados das personas carregados com sucesso de {PERSONAS_FILE}")
        return full_data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"ERRO CRÍTICO ao carregar o ficheiro de personas: {e}\n{traceback.format_exc()}")
        return {}
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao carregar as personas: {e}\n{traceback.format_exc()}")
        return {}

def save_persona_file(data):
    """Salva os dados da persona de forma segura no arquivo."""
    try:
        with personas_file_lock:
            with open(PERSONAS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Erro ao salvar o arquivo de personas: {e}")
        return False

def get_personas_for_frontend():
    """Lê os dados e remove a base de conhecimento aprendida para o frontend."""
    # Garante que os dados em memória estão atualizados antes de criar a cópia
    global PERSONA_DATA
    PERSONA_DATA = load_persona_file() 

    if not PERSONA_DATA:
        return {}
    
    # Cria uma cópia profunda para não modificar os dados em memória e evitar recursão
    personas_clean = json.loads(json.dumps(PERSONA_DATA.get("personas", {})))
    
    for key in personas_clean:
        if 'learned_knowledge_base' in personas_clean[key]:
            del personas_clean[key]['learned_knowledge_base']
    return personas_clean

# Carregamento inicial de dados
PERSONA_DATA = load_persona_file()

# --- Comunicação com a API do Gemini ---
def call_gemini(prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE):
    """Envia um prompt à API do Gemini e retorna a resposta, com tratamento robusto de erros."""
    if not GEMINI_API_KEY:
        logging.error("Variável de ambiente GEMINI_API_KEY não definida!")
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

    logging.info(f"A enviar para a API do Gemini | Modelo: {model} | Temp: {temperature}")
    app.logger.debug(f"Payload (primeiros 500 carateres): {str(payload)[:500]}...")

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=180)
        response.raise_for_status() # Lança uma exceção para erros HTTP (4xx ou 5xx)
        data = response.json()
        app.logger.debug(f"Resposta da API (parcial): {str(data)[:500]}...")

        if data.get('promptFeedback', {}).get('blockReason'):
            reason = data['promptFeedback']['blockReason']
            logging.error(f"Prompt bloqueado pelo Gemini. Motivo: {reason}. Detalhes: {data['promptFeedback']}")
            return {"error": f"ERROR_GEMINI_BLOCKED_PROMPT: Prompt bloqueado. Motivo: {reason}"}

        if candidates := data.get('candidates'):
            candidate = candidates[0]
            finish_reason = candidate.get('finishReason', 'UNKNOWN')

            if finish_reason not in ['STOP', 'MAX_TOKENS']:
                logging.warning(f"O finishReason do Gemini foi '{finish_reason}'.")
                if finish_reason in ['SAFETY', 'RECITATION', 'OTHER']:
                    return {"error": f"ERROR_GEMINI_BLOCKED_FINISH: Geração interrompida. Motivo: {finish_reason}."}

            if text_parts := candidate.get('content', {}).get('parts', []):
                if 'text' in text_parts[0]:
                    return {"text": text_parts[0]['text'].strip()}

            logging.error(f"Nenhum texto encontrado na resposta do Gemini. Motivo de conclusão: {finish_reason}. Candidato: {candidate}")
            return {"error": "ERROR_GEMINI_PARSE: Resposta válida, mas nenhum texto gerado encontrado."}

        logging.error(f"Estrutura de resposta da API inesperada. Dados: {str(data)[:500]}")
        return {"error": "ERROR_GEMINI_PARSE: Estrutura de resposta inesperada."}

    except requests.exceptions.Timeout as e:
        logging.error("Tempo limite excedido ao contactar a API do Gemini: %s", e)
        return {"error": "ERROR_GEMINI_TIMEOUT: O pedido à API do Gemini excedeu o tempo limite."}
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response else "N/A"
        details = e.response.text if e.response else str(e)
        logging.error(f"O pedido à API do Gemini falhou. Estado: {status}. Detalhes: {details[:200]}...")
        return {"error": f"ERROR_GEMINI_REQUEST: O pedido à API falhou com o estado {status}."}
    except Exception as e:
        logging.exception("An unexpected error occurred in call_gemini:")
        return {"error": f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"}


# --- Funções Avançadas de Construção de Prompt (Otimizadas) ---
# Removida a função get_relevant_few_shot_examples, pois não será mais utilizada.

def build_holistic_draft_prompt(original_email, user_guidance, active_persona_key, persona_data, context_analysis_result, summarized_knowledge=""):
    """
    Constrói um prompt holístico mais conciso e dinâmico, priorizando a naturalidade e a performance.
    Injeta apenas o contexto mais relevante para o LLM.
    """
    persona_info = persona_data['personas'][active_persona_key]
    persona_name = persona_info['label_pt']
    
    # Extrai o primeiro elemento de 'tone_elements' para uso genérico no prompt
    persona_base_style = persona_info['base_style_profile'].get('tone_elements', [{}])[0]
    persona_formality = persona_info['base_style_profile'].get('formality_element', {})
    
    context_category = context_analysis_result.get('recipient_category', 'unknown')
    incoming_tone = context_analysis_result.get('incoming_tone', 'unknown')

    # Busca as regras de adaptação de sentimento específicas para a categoria e tom
    sentiment_rules = persona_data.get('generic_recipient_adaptation_rules', {}).get(context_category, {}).get('sentiment_adaptation', {})
    
    current_sentiment_guidance = ""
    current_sentiment_keywords = []

    # Se houver uma regra de sentimento que corresponda ao tom de entrada, use-a
    if incoming_tone in sentiment_rules:
        sentiment_adaptation = sentiment_rules[incoming_tone]
        current_sentiment_guidance = sentiment_adaptation.get('guidance_notes_pt', '')
        current_sentiment_keywords = sentiment_adaptation.get('keywords', [])
    
    # Se houver um nome de remetente específico da análise de contexto, adicione
    sender_name_display = context_analysis_result.get('sender_name_guess', 'o remetente')

    # NOVO: Sintetiza as diretrizes da persona para serem mais explícitas no prompt
    persona_core_guidelines = ""
    if persona_info.get('description_pt'):
        persona_core_guidelines += f"- Estilo geral: {persona_info['description_pt']}\n"
    if persona_info.get('general_dos_pt'):
        persona_core_guidelines += "- Regras a seguir: " + ", ".join(persona_info['general_dos_pt']) + "\n"
    if persona_info.get('general_donts_pt'):
        persona_core_guidelines += "- Regras a evitar: " + ", ".join(persona_info['general_donts_pt']) + "\n"
    if persona_core_guidelines:
        persona_core_guidelines = "### Diretrizes Essenciais da Persona ###\n" + persona_core_guidelines


    system_instruction = f"""
        Você é um assistente de email em Português. Sua função é responder a emails de forma natural e humana, usando a persona **'{persona_name}'**.
        Siga estas instruções estritamente para gerar a resposta final.
    """

    context_block = f"""
        ### Contexto do Pedido ###
        - **Email Original:** ```{original_email}```
        - **Diretrizes do Utilizador:** ```{user_guidance}```
    """

    persona_and_rules_block = f"""
        ### Perfil e Regras de Escrita ###
        - **Persona Ativa:** {persona_name}
        {persona_core_guidelines}
        - **Tom Preferencial:** {persona_base_style.get('label_pt', 'Não definido')} ({', '.join(persona_base_style.get('keywords_pt', []))}).
        - **Nível de Formalidade:** {persona_formality.get('label_pt', 'Não definido')} ({persona_formality.get('guidance_notes_pt', '')}).
        - **Adaptação ao Contexto do Remetente ('{sender_name_display}'):**
            - Categoria: {context_category}
            - Tom Recebido: {incoming_tone}
            - Regras de Sentimento: {current_sentiment_guidance} ({', '.join(current_sentiment_keywords)})
        
        {summarized_knowledge if summarized_knowledge else "Nenhum conhecimento prévio específico para este remetente."}
    """

    output_instruction = f"""
        Com base nas informações acima (email original, diretrizes do utilizador, perfil da persona, e regras de adaptação), elabore a resposta.
        
        A sua resposta deve ser **exclusivamente** o texto do email final. Não inclua raciocínio, notas, nem a sua identificação como IA.
        
        **Resposta Final:**
    """

    return f"{system_instruction}\n{context_block}\n{persona_and_rules_block}\n{output_instruction}"

def build_prompt_1_analysis(email_text):
    """Constrói o prompt para Análise de Intenção e Pontos de Decisão do Utilizador."""
    return f"""Sistema: Analista expert de email.
Tarefa: Analisar o email recebido para identificar o **pedido principal** e os **pontos de decisão chave** que SÓ o utilizador pode fornecer. Não peça informação inferível.
Formato: APENAS um objeto JSON (sem texto extra).
Chaves JSON:
1.  `core_request`: Resumo objetivo do pedido principal (uma frase).
2.  `points`: Array de perguntas concisas para o utilizador. Se não houver pontos específicos, inclua um ponto genérico sobre como como responder.
---
Email Recebido para Análise:
---
{email_text}
---
Resultado JSON:
"""

def build_prompt_0_context_analysis(original_email, persona, generic_rules):
    """Constrói o prompt para Pré-Análise: identifica tipo de destinatário, tom, nome do remetente e justificativa."""
    max_email_length = 3000
    truncated_email = original_email[:max_email_length]
    if len(original_email) > max_email_length:
        truncated_email += "\n... (email truncado)"
    
    # Cria uma lista de categorias de destinatário para o LLM escolher
    recipient_types_list = list(generic_rules.keys())
    
    persona_context = {
        "name": persona.get("label_pt", "N/A"),
        "role": persona.get("role_template", "N/A"),
        "language": persona.get("communication_attributes", {}).get("language", "pt-PT"),
        "supported_recipient_types": recipient_types_list # Passa as categorias suportadas
    }
    
    prompt = f"""Sistema: Expert em análise de contexto de emails.
Tarefa: Analisar o email recebido e o contexto da Persona para determinar a **relação mais provável**, o **tom do email** e o **nome do remetente principal**.
Formato: APENAS um objeto JSON válido (sem texto extra).
Chaves OBRIGATÓRIAS:
1.  `recipient_category`: (string) Categoria **exata** do remetente (UMA das `supported_recipient_types` fornecidas, ou "unknown" se nenhuma corresponder).
2.  `incoming_tone`: (string) Tom do email recebido ("Muito Formal", "Formal", "Semi-Formal", "Casual", "Urgente", "InformativoNeutro", "Outro").
3.  `sender_name_guess`: (string) Melhor suposição do nome do remetente (ex: "Marta Silva"). Omitir títulos (Prof., Dr.). Se impossível, "".
4.  `rationale`: (string) Frase **curta e objetiva** justificando a `recipient_category`.
---
Persona Que Irá Responder (Contexto Relevante):
```json
{json.dumps(persona_context, indent=2, ensure_ascii=False)}
```
Email Recebido:
---
{truncated_email}
---
Resultado JSON:
"""
    return prompt

def build_prompt_3_suggestion(point_to_address, persona, direction):
    """Constrói o prompt para sugerir uma "diretriz" exemplar para um Ponto de Decisão."""
    persona_name = persona.get('label_pt', 'Assistente')
    direction_map = {
        'sim': 'AFIRMATIVO / POSITIVO',
        'nao': 'NEGATIVO',
        'outro': 'NEUTRO / DETALHADO'
    }
    direction_text = direction_map.get(direction, 'NEUTRO / DETALHADO')
    return f"""Sistema: Assistente útil.
Tarefa: Gerar uma única, concisa e acionável **instrução de orientação** para o utilizador, em português (pt-PT), refletindo uma intenção **{direction_text}**.
---
Contexto:
* Persona que irá escrever o email: '{persona_name}'
* Ponto de Decisão: "{point_to_address}"
* Intenção: {direction_text}
---
Saída: APENAS o texto de orientação exemplar (nada mais).
"""

def build_prompt_4_refinement(persona, selected_text, full_context, action):
    """Constrói o prompt para refinar uma parte do texto."""
    persona_name = persona.get('label_pt', 'Assistente')
    persona_info = f"Sistema: Atue como um assistente '{persona_name}'. Mantenha o estilo, tom e idioma da persona."
    action_instructions = {
        "make_formal": "Reescreva o 'Texto Selecionado' para ser mais formal e profissional.",
        "make_casual": "Reescreva o 'Texto Selecionado' para ser mais casual e direto.",
        "shorten": "Condense o 'Texto Selecionado' ao máximo, preservando o significado.",
        "expand": "Elabore sobre o 'Texto Selecionado', adicionando detalhes/contexto.",
        "simplify": "Reescreva o 'Texto Selecionado' com linguagem mais simples.",
        "improve_flow": "Melhore o fluxo e a coesão do 'Texto Selecionado' no 'Rascunho Completo'.",
        "rephrase": "Refraseie o 'Texto Selecionado' de forma diferente.",
        "translate_en": "Traduza o 'Texto Selecionado' para inglês profissional."
    }
    instruction = action_instructions.get(action, f"Modifique o 'Texto Selecionado' conforme solicitado ({action}).")
    return f"""{persona_info}
Tarefa: Refinar uma parte do rascunho de email.
Ação: {instruction}
---
Rascunho Completo (referência):
---
{full_context}
---
Texto Selecionado para Modificar:
---
{selected_text}
---
Saída: APENAS o texto modificado (nada mais).
"""

def build_prompt_5_summarize_knowledge(relevant_feedback_entries, sender_name):
    """
    Constrói um prompt para o LLM sintetizar regras acionáveis
    e concisas sobre um contacto com base em feedback passado.
    """
    formatted_entries = ""
    for i, entry in enumerate(relevant_feedback_entries):
        original = entry.get('ai_original_response_text', 'N/A')
        corrected = entry.get('user_corrected_output_text', 'N/A')
        explanation = entry.get('user_explanation_text_pt', 'N/A')
        formatted_entries += f"""
### Feedback {i+1} ###
- **Explicação do Utilizador:** "{explanation}"
- **O que a IA escreveu:** "{original}"
- **O que o utilizador corrigiu para:** "{corrected}"
"""
    prompt = f"""
Sistema: Sintetizador de Regras de Estilo.
Tarefa: Analise o feedback do utilizador sobre interações passadas com **{sender_name}**. Crie uma lista de bullet points com **regras de escrita concisas e acionáveis** para a IA seguir em futuras interações com este remetente.
**As regras devem ser diretas e focar em como a IA deve adaptar o estilo ou conteúdo. Não inclua justificativas.**

---
**Dados de Feedback para {sender_name}:**
{formatted_entries}
---
**Regras de Estilo Sintetizadas:**
"""
    return prompt

# --- Funções de Análise, Parsing e Conhecimento (Aprimoradas) ---
def _normalize_name_robust(name):
    """
    Normaliza um nome para uma correspondência mais robusta,
    removendo acentos, títulos e outros caracteres.
    """
    if not name:
        return ""
    
    name = str(name).strip().lower()
    
    # Remove títulos e abreviações comuns
    titles = ['prof.', 'prof', 'dr.', 'dr', 'dra.', 'dra', 'eng.', 'eng', 'sr.', 'sra.']
    name = ' '.join([word for word in name.split() if word not in titles])
    
    # Remove acentos
    name = unidecode.unidecode(name)
    
    # Remove caracteres não alfanuméricos (exceto espaços) e excesso de espaços
    name = re.sub(r'[^\w\s]', '', name).strip()
    name = re.sub(r'\s+', ' ', name)
    
    return name

def find_relevant_feedback_entries(persona_obj, current_context_analysis):
    """
    Encontra todas as entradas de feedback relevantes para o remetente atual
    usando uma lógica de correspondência mais flexível, comparando nomes normalizados.
    """
    knowledge_base = persona_obj.get("learned_knowledge_base", [])
    current_sender_name_raw = current_context_analysis.get("sender_name_guess", "")
    
    if not knowledge_base or not current_sender_name_raw:
        logging.info("Pesquisa na base de conhecimento ignorada: sem dados ou nome de remetente.")
        return []

    normalized_current_name = _normalize_name_robust(current_sender_name_raw)
    
    if not normalized_current_name:
        logging.info("Nome do remetente vazio após normalização. Sem pesquisa.")
        return []
        
    relevant_feedback = []
    
    for entry in knowledge_base:
        try:
            snapshot = entry.get("interaction_context_snapshot", {})
            # Pega o nome do remetente da análise prévia do LLM no snapshot
            snapshot_sender_raw = snapshot.get("llm_pre_analysis_snapshot", {}).get("sender_name_guess", "")
            
            if not snapshot_sender_raw:
                continue

            normalized_snapshot_name = _normalize_name_robust(snapshot_sender_raw)

            # Lógica de correspondência flexível: nomes exatos ou um contido no outro
            if (normalized_current_name == normalized_snapshot_name or
                normalized_current_name in normalized_snapshot_name or
                normalized_snapshot_name in normalized_current_name):
                relevant_feedback.append(entry)
                
        except Exception as e:
            logging.warning(f"A ignorar uma entrada de feedback malformada durante a pesquisa de conhecimento: {e}")
            continue

    logging.info(f"Encontradas {len(relevant_feedback)} entradas de feedback para o remetente '{current_sender_name_raw}'.")
    return relevant_feedback


def analyze_sender_and_context(original_email, persona, generic_rules):
    """
    Chama o LLM para realizar a Pré-Análise de Contexto (tipo de destinatário, tom, nome do remetente)
    e retorna os resultados JSON analisados.
    """
    logging.info(f"A iniciar Pré-Análise de Contexto para a persona {persona.get('label_pt', 'N/A')}")
    if not persona:
        return {"error": "Persona inválida para análise de contexto."}
    
    analysis_prompt = build_prompt_0_context_analysis(original_email, persona, generic_rules)
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.2)
    
    if "error" in llm_response_data:
        return {"error": f"A comunicação com o LLM falhou durante a pré-análise: {llm_response_data['error']}"}
    
    llm_response_text = llm_response_data.get("text", "")
    try:
        # Regex mais robusta para encontrar o JSON, seja dentro de um bloco de código ou solto
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```|({[\s\S]+})", llm_response_text)
        json_str = json_match.group(1) or json_match.group(2) if json_match else llm_response_text
        
        parsed_json = json.loads(json_str)
        
        # Validação para garantir que as chaves esperadas estão presentes
        if any(key not in parsed_json for key in ["recipient_category", "incoming_tone", "sender_name_guess", "rationale"]):
            raise ValueError("JSON inválido da Pré-Análise. Faltam chaves obrigatórias.")
        
        return parsed_json
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        error_msg = f"Falha ao analisar o JSON da Pré-Análise: {e}. Resposta bruta: {llm_response_text[:500]}..."
        logging.error(error_msg)
        return {"error": f"ERROR_PARSE_CONTEXT: {error_msg}"}

def parse_analysis_output(llm_output_text):
    """Analisa a resposta JSON da nova Análise de Intenção."""
    if not isinstance(llm_output_text, str) or not llm_output_text.strip():
        return {"error": "Resposta vazia ou inválida da análise do LLM"}
    try:
        # Regex mais robusta para encontrar o JSON
        json_match = re.search(r"```json\s*({[\s\S]*?})\s*```|({[\s\S]*})", llm_output_text)
        json_str = json_match.group(1) or json_match.group(2) if json_match else llm_output_text
        
        parsed_json = json.loads(json_str)
        
        core_request = parsed_json.get("core_request")
        decision_points = parsed_json.get("points")
        
        if not isinstance(core_request, str) or not isinstance(decision_points, list):
            raise ValueError("A estrutura JSON é inválida. Faltam 'core_request' ou 'points'.")
        
        return {"actions": [core_request], "points": decision_points}
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Falha ao analisar o JSON de análise: {e}. Saída bruta: {llm_output_text[:500]}")
        return {"error": f"Falha ao analisar a análise da IA. Detalhes: {e}"}


# --- Rotas de Autenticação do Gmail ---
@app.route('/login')
def login():
    """Inicia o fluxo de login OAuth 2.0."""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for('authorize', _external=True)
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/authorize')
def authorize():
    """Rota de callback para onde o Google redireciona após o consentimento do utilizador."""
    state = session.get('state')
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for('authorize', _external=True)
    )
    try:
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        return redirect(url_for('index_route'))
    except Exception as e:
        logging.error(f"Erro durante a autorização OAuth: {e}\n{traceback.format_exc()}")
        return "Erro na autorização. Por favor, tente novamente.", 500

@app.route('/logout')
def logout():
    """Limpa a sessão para fazer logout do utilizador."""
    session.clear()
    return redirect(url_for('index_route'))


# --- Funções Auxiliares e Rotas para Obtenção de Dados do Gmail ---
def get_gmail_service():
    """Cria um objeto de serviço do Gmail autorizado a partir das credenciais da sessão."""
    if 'credentials' not in session:
        return None
    try:
        # Rehidrata as credenciais
        creds = google.oauth2.credentials.Credentials(**session['credentials'])
        
        # Se o token de acesso estiver expirado, ele tentará usar o refresh_token automaticamente
        if not creds.valid:
            if creds.refresh_token:
                creds.refresh(google.auth.transport.requests.Request())
                # Atualiza as credenciais na sessão
                session['credentials'] = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes
                }
            else:
                logging.warning("Credenciais inválidas e sem refresh token. Sessão expirada.")
                session.clear()
                return None
        
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        logging.error(f"Falha ao criar o serviço do Gmail (credenciais inválidas?): {e}\n{traceback.format_exc()}")
        # Credenciais potencialmente inválidas, limpa a sessão para forçar novo login
        session.clear()
        return None

def get_full_thread_text(service, thread_id):
    """
    Obtém um tópico de email completo e formata-o num único bloco de texto
    para análise do LLM, mantendo a ordem cronológica.
    """
    try:
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        full_conversation = []
        # As mensagens num tópico são retornadas do mais antigo para o mais recente pela API.
        for message in thread.get('messages', []):
            payload = message.get('payload', {})
            headers = payload.get('headers', [])
            
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Remetente Desconhecido')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Data Desconhecida')
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(Sem Assunto)')
            
            body = ''
            if 'parts' in payload:
                # Prioriza text/plain sobre text/html
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data')
                        if data:
                            body = base64.urlsafe_b64decode(data).decode('utf-8')
                            break # Encontrou a parte de texto simples, não precisa procurar mais
            elif 'data' in payload.get('body', {}): # Caso de corpo simples (sem partes)
                data = payload['body']['data']
                body = base64.urlsafe_b64decode(data).decode('utf-8')

            # Formata cada mensagem claramente para o LLM entender o fluxo da conversa
            message_text = f"--- Mensagem de '{sender}' ({date}) ---\nAssunto: {subject}\n\n{body.strip()}\n"
            full_conversation.append(message_text)
            
        # Junta todas as mensagens para formar um tópico coerente para o prompt do LLM
        return "\n".join(full_conversation)
        
    except Exception as e:
        logging.error(f"Erro ao obter detalhes do tópico para o ID {thread_id}: {e}\n{traceback.format_exc()}")
        return None

@app.route('/api/emails')
def fetch_emails_route():
    """Endpoint da API para obter os últimos 15 emails da caixa de entrada do utilizador."""
    service = get_gmail_service()
    if not service:
        # Retorna 401 para que o frontend possa redirecionar para o login
        return jsonify({"error": "Utilizador não autenticado ou sessão expirada."}), 401
    
    try:
        # Obtém a lista de IDs de mensagens da CAIXA DE ENTRADA
        results = service.users().messages().list(userId='me', maxResults=15, q="category:primary in:inbox").execute()
        messages = results.get('messages', [])
        
        email_list = []
        for msg in messages:
            # Para a vista de lista, só precisamos de metadados (cabeçalhos e snippet), o que é mais rápido
            message_meta = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From', 'Date']).execute()
            headers = message_meta.get('payload', {}).get('headers', [])
            
            email_summary = {
                'id': message_meta['id'],
                'threadId': message_meta['threadId'],
                'subject': next((h['value'] for h in headers if h['name'] == 'Subject'), '(Sem Assunto)'),
                'sender': next((h['value'] for h in headers if h['name'] == 'From'), 'Remetente Desconhecido'),
                'date': next((h['value'] for h in headers if h['name'] == 'Date'), ''),
                'snippet': message_meta.get('snippet', '')
            }
            email_list.append(email_summary)
            
        return jsonify(email_list)
    except Exception as e:
        logging.error(f"Falha ao obter emails: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Falha ao obter emails do Gmail."}), 500

@app.route('/api/thread/<thread_id>')
def get_thread_route(thread_id):
    """
    Endpoint da API para obter o texto completo de um tópico e informações do remetente original.
    """
    service = get_gmail_service()
    if not service:
        return jsonify({"error": "Utilizador não autenticado ou sessão expirada."}), 401
    
    try:
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        if not thread.get('messages'):
            return jsonify({"error": "O tópico não contém mensagens."}), 404
            
        # Para responder, precisamos do remetente e assunto da PRIMEIRA mensagem do tópico.
        # A API do Gmail já agrupa as respostas numa thread se o threadId for fornecido no envio.
        first_message = thread['messages'][0]
        first_payload = first_message.get('payload', {})
        first_headers = first_payload.get('headers', [])
        
        original_sender_email = next((h['value'] for h in first_headers if h['name'].lower() == 'from'), 'Remetente Desconhecido')
        original_subject = next((h['value'] for h in first_headers if h['name'].lower() == 'subject'), '(Sem Assunto)')

        # Obtém o texto completo do tópico formatado para exibição/análise pelo LLM
        full_thread_text = get_full_thread_text(service, thread_id)
        if full_thread_text is None:
            raise Exception(f"Falha ao formatar texto do tópico {thread_id}")

        return jsonify({
            "thread_text": full_thread_text, # Agora é o texto de todo o tópico
            "original_sender_email": original_sender_email,
            "original_subject": original_subject
        })

    except Exception as e:
        logging.error(f"Erro ao obter tópico completo para o ID {thread_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Falha ao recuperar o conteúdo do tópico: {e}"}), 500

@app.route('/api/send_email', methods=['POST'])
def send_email_route():
    """Endpoint da API para enviar um email usando a API do Gmail."""
    service = get_gmail_service()
    if not service:
        return jsonify({"error": "Utilizador não autenticado ou sessão expirada."}), 401

    data = request.get_json()
    recipient = data.get('recipient')
    subject = data.get('subject')
    body = data.get('body')
    thread_id = data.get('thread_id') # Obtém thread_id do pedido para responder no mesmo tópico

    if not all([recipient, subject, body]):
        return jsonify({"error": "Recipiente, assunto e corpo são obrigatórios."}), 400

    try:
        message = MIMEText(body, _charset='utf-8') # Garante que o charset é utf-8
        message['to'] = recipient
        message['subject'] = subject
        
        # O cabeçalho 'In-Reply-To' e 'References' são automaticamente geridos pelo Gmail
        # quando se usa o `threadId` no `send()`
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        send_options = {'raw': raw_message}
        
        # Se thread_id for fornecido, responde no mesmo tópico
        if thread_id:
            send_options['threadId'] = thread_id

        # Usa o método de envio para enviar o email
        sent_message = service.users().messages().send(userId='me', body=send_options).execute()
        
        logging.info(f"Email enviado com sucesso para {recipient} com ID da mensagem: {sent_message['id']} no tópico {sent_message.get('threadId', 'N/A')}")
        return jsonify({"message": "Email enviado com sucesso!", "id": sent_message['id']})

    except Exception as e:
        logging.error(f"Falha ao enviar email: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Falha ao enviar email: {e}"}), 500

# --- Rotas de Gestão de Personas (API CRUD) ---
@app.route('/api/personas', methods=['GET'])
def get_all_personas_route():
    """Retorna uma lista de todas as personas (sem a base de conhecimento aprendida)."""
    return jsonify(get_personas_for_frontend())

@app.route('/api/personas', methods=['POST'])
def create_persona_route():
    """Cria uma nova persona no arquivo JSON."""
    global PERSONA_DATA
    if not request.json or 'persona_key' not in request.json or 'persona_data' not in request.json:
        return jsonify({"error": "Dados inválidos: 'persona_key' e 'persona_data' são obrigatórios."}), 400

    new_key = request.json['persona_key']
    new_data = request.json['persona_data']

    # Validação mínima dos dados da nova persona
    if not new_key or not isinstance(new_key, str) or not new_key.strip():
        return jsonify({"error": "A 'persona_key' deve ser uma string não vazia."}), 400
    if not new_data or not isinstance(new_data, dict):
        return jsonify({"error": "'persona_data' deve ser um objeto JSON válido."}), 400
    if not new_data.get('label_pt') or not isinstance(new_data.get('label_pt'), str):
        return jsonify({"error": "O campo 'label_pt' na 'persona_data' é obrigatório e deve ser uma string."}), 400

    with personas_file_lock:
        current_data = load_persona_file() # Garante que estamos a trabalhar com a versão mais recente
        if "personas" not in current_data:
            current_data["personas"] = {} # Inicializa se não existir
        
        if new_key in current_data["personas"]:
            return jsonify({"error": f"A chave de persona '{new_key}' já existe."}), 409
        
        # Adiciona a nova persona, garantindo que 'learned_knowledge_base' existe
        new_data.setdefault('learned_knowledge_base', [])
        current_data["personas"][new_key] = new_data

        if not save_persona_file(current_data):
            return jsonify({"error": "Falha ao salvar a nova persona."}), 500
        
        PERSONA_DATA = current_data # Atualiza a variável global em memória
    
    return jsonify({"message": f"Persona '{new_key}' criada com sucesso."}), 201

@app.route('/api/personas/<persona_key>', methods=['GET', 'PUT', 'DELETE'])
def manage_persona_route(persona_key):
    """Gerencia uma persona específica (leitura, atualização, remoção)."""
    global PERSONA_DATA
    
    # Sempre recarrega para garantir que estamos a trabalhar com os dados mais recentes do ficheiro
    current_data = load_persona_file()

    if "personas" not in current_data or persona_key not in current_data["personas"]:
        return jsonify({"error": f"Persona '{persona_key}' não encontrada."}), 404

    if request.method == 'GET':
        # Retorna a persona completa (incluindo base de conhecimento) para fins de administração/edição
        return jsonify(current_data['personas'][persona_key])

    if request.method == 'PUT':
        updated_data = request.get_json()
        if not updated_data or not isinstance(updated_data, dict):
            return jsonify({"error": "Dados de atualização não fornecidos ou inválidos."}), 400
        
        with personas_file_lock:
            # Atualiza apenas os campos fornecidos, sem apagar a base de conhecimento
            # Se updated_data contiver 'learned_knowledge_base', ele será sobrescrito.
            # No entanto, a UI não deve permitir a edição direta desta secção para evitar corrupção.
            current_data['personas'][persona_key].update(updated_data)
            
            if not save_persona_file(current_data):
                return jsonify({"error": "Falha ao atualizar a persona."}), 500
                
            PERSONA_DATA = current_data # Atualiza a variável global em memória
        return jsonify({"message": f"Persona '{persona_key}' atualizada com sucesso."}), 200

    if request.method == 'DELETE':
        with personas_file_lock:
            del current_data['personas'][persona_key]
            
            if not save_persona_file(current_data):
                return jsonify({"error": "Falha ao remover a persona."}), 500
                
            PERSONA_DATA = current_data # Atualiza a variável global em memória
        return jsonify({"message": f"Persona '{persona_key}' removida com sucesso."}), 200


# --- Rotas Principais da Aplicação ---
@app.route('/')
def index_route():
    """Serve a página principal."""
    global PERSONA_DATA
    # Recarrega os dados das personas em modo de depuração para captar alterações sem reiniciar o Flask
    # e também para garantir que as alterações da API CRUD são refletidas no carregamento inicial.
    if DEBUG_MODE:
        PERSONA_DATA = load_persona_file()
    
    personas_dict = PERSONA_DATA.get("personas", {})
    personas_display = {key: {"name": data.get("label_pt", key)} for key, data in personas_dict.items()}
    
    is_logged_in = 'credentials' in session
    
    return render_template('index.html', personas_dict=personas_display, error_loading_personas=not bool(personas_dict), is_logged_in=is_logged_in)

@app.route('/analyze', methods=['POST'])
def analyze_email_route():
    """Endpoint para a Análise de Intenção do email."""
    if not request.json or not request.json.get('email_text', '').strip():
        return jsonify({"error": "O texto do email não pode estar vazio."}), 400
    
    email_text = request.json['email_text']
    logging.info("A iniciar Análise de Intenção")
    
    analysis_prompt = build_prompt_1_analysis(email_text)
    llm_response = call_gemini(analysis_prompt, temperature=ANALYSIS_TEMPERATURE)
    
    if "error" in llm_response:
        return jsonify({"error": f"A análise do LLM falhou: {llm_response['error']}", "raw_analysis": llm_response.get("text")}), 500
    
    analysis_result = parse_analysis_output(llm_response.get("text", ""))
    
    if analysis_result.get("error"):
        return jsonify(analysis_result), 500
    
    logging.info("Análise de intenção processada com sucesso.")
    return jsonify(analysis_result)


@app.route('/draft', methods=['POST'])
def draft_response_route():
    """Endpoint principal para gerar o rascunho, com recuperação de conhecimento ativo."""
    global PERSONA_DATA
    if not request.json:
        return jsonify({"error": "Pedido inválido (JSON esperado)."}), 400
    
    required = ['original_email', 'persona_name', 'user_inputs']
    if not all(field in request.json for field in required):
        missing = [field for field in required if field not in request.json]
        return jsonify({"error": f"Dados em falta: {', '.join(missing)}."}), 400
    
    original_email = request.json['original_email']
    active_persona_key = request.json['persona_name']
    
    if not PERSONA_DATA or active_persona_key not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{active_persona_key}' não encontrada ou personas não carregadas."}), 400
    
    selected_persona = PERSONA_DATA["personas"][active_persona_key]
    generic_rules = PERSONA_DATA.get("generic_recipient_adaptation_rules", {})
    
    # 1. Realiza a análise de contexto (remetente, tom, categoria)
    context_analysis_result = analyze_sender_and_context(original_email, selected_persona, generic_rules)
    if context_analysis_result.get("error"):
        logging.warning(f"A pré-análise de contexto falhou: {context_analysis_result['error']}. A continuar sem dados contextuais detalhados.")
        # Define um contexto padrão para evitar erros no prompt
        context_analysis_result = {
            "recipient_category": "unknown",
            "incoming_tone": "unknown",
            "sender_name_guess": "não identificado",
            "rationale": "Análise falhou."
        }
    
    # 2. Encontra e sintetiza conhecimento relevante da base de dados (se houver)
    relevant_feedback = find_relevant_feedback_entries(selected_persona, context_analysis_result)
    summarized_knowledge = ""
    if relevant_feedback:
        # A síntese é feita apenas se houver feedback relevante
        synthesis_prompt = build_prompt_5_summarize_knowledge(relevant_feedback, context_analysis_result.get("sender_name_guess", ""))
        llm_response_knowledge = call_gemini(synthesis_prompt, temperature=0.1) # Baixa temperatura para precisão
        
        if "error" not in llm_response_knowledge and llm_response_knowledge.get("text"):
            summarized_knowledge = llm_response_knowledge.get("text", "").strip()
            logging.info(f"Conhecimento sintetizado para '{context_analysis_result.get('sender_name_guess', '')}': {summarized_knowledge}")
        else:
            logging.warning(f"Falha ao sintetizar conhecimento para '{context_analysis_result.get('sender_name_guess', '')}': {llm_response_knowledge.get('error', 'Resposta vazia')}")

    # Removido: 3. Obtém os exemplos de few-shot relevantes para o email original
    # few_shot_examples_formatted = get_relevant_few_shot_examples(selected_persona, original_email)
    
    # 4. Formata as diretrizes do utilizador
    user_inputs = request.json['user_inputs']
    if not user_inputs or not any(item.get('guidance', '').strip() for item in user_inputs):
        user_guidance = "Escreva uma resposta apropriada ao email, considerando o contexto e a persona."
    else:
        guidance_points = []
        for item in user_inputs:
            guidance_text = item.get('guidance', '').strip()
            point_text = item.get('point', 'geral')
            if guidance_text:
                guidance_points.append(f'- Para o ponto de decisão "{point_text}", a minha intenção é: "{guidance_text}"')
        user_guidance = "A intenção para a resposta é a seguinte:\n" + "\n".join(guidance_points)
    
    logging.info(f"A iniciar Geração de Rascunho HÍBRIDO para a Persona: {active_persona_key}")
    
    # 5. Constrói o prompt holístico final com todos os elementos (few_shot_examples_formatted removido)
    draft_prompt = build_holistic_draft_prompt(
        original_email, user_guidance, active_persona_key, PERSONA_DATA, context_analysis_result,
        summarized_knowledge # few_shot_examples_formatted removido
    )

    # 6. Chama o LLM para gerar o rascunho
    llm_response_draft = call_gemini(draft_prompt, temperature=GENERATION_TEMPERATURE)
    
    if "error" in llm_response_draft:
        return jsonify({"error": f"Falha ao gerar rascunho: {llm_response_draft['error']}", "context_analysis": context_analysis_result}), 500
    
    final_draft_full_output = llm_response_draft.get("text", "").strip()

    # 7. Pós-processamento para extrair apenas a "Versão Final"
    final_draft_match = re.search(
        r"versão final:\s*\n*(.*?)(?=\n*#+\s*PARTE|\n*---|$)", # Busca "versão final:" e captura até um novo título ou separador
        final_draft_full_output,
        re.DOTALL | re.IGNORECASE
    )
    
    if final_draft_match:
        final_draft = final_draft_match.group(1).strip()
    else:
        # Fallback se a regex falhar: tenta uma regex mais simples (apenas o que vem antes de um separador)
        simpler_match = re.search(r"^\s*(.*?)(?=\n*#+\s*PART|\n*---|$)", final_draft_full_output, re.DOTALL | re.IGNORECASE)
        if simpler_match:
            final_draft = simpler_match.group(1).strip()
        else:
            logging.warning("Não foi possível extrair a 'Versão Final' com a regex. Usando o texto completo.")
            final_draft = final_draft_full_output

    return jsonify({"draft": final_draft, "context_analysis": context_analysis_result})

@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route():
    """Endpoint para gerar uma sugestão de ORIENTAÇÃO para um Ponto de Decisão."""
    global PERSONA_DATA
    if not request.json or not all(k in request.json for k in ['point_to_address', 'persona_name']):
        return jsonify({"error": "Dados em falta no pedido."}), 400
    
    persona_name = request.json['persona_name']
    if persona_name not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 400
    
    selected_persona = PERSONA_DATA["personas"][persona_name]
    
    prompt = build_prompt_3_suggestion(request.json['point_to_address'], selected_persona, request.json.get('direction', 'outro'))
    llm_response = call_gemini(prompt, temperature=ANALYSIS_TEMPERATURE) # Baixa temperatura para sugestões diretas
    
    if "error" in llm_response:
        return jsonify(llm_response), 500
    
    return jsonify({"suggestion": llm_response.get("text", "").strip()})


@app.route('/refine_text', methods=['POST'])
def refine_text_route():
    """Endpoint para refinar uma parte do texto gerado."""
    global PERSONA_DATA
    if not request.json or not all(k in request.json for k in ['selected_text', 'full_context', 'action', 'persona_name']):
        return jsonify({"error": "Dados em falta no pedido."}), 400
    
    persona_name = request.json['persona_name']
    if persona_name not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 400
    
    selected_persona = PERSONA_DATA["personas"][persona_name]
    
    prompt = build_prompt_4_refinement(selected_persona, request.json['selected_text'], request.json['full_context'], request.json['action'])
    llm_response = call_gemini(prompt, temperature=REFINEMENT_TEMPERATURE)
    
    if "error" in llm_response:
        return jsonify(llm_response), 500
    
    return jsonify({"refined_text": llm_response.get("text", "")})


@app.route('/submit_feedback', methods=['POST'])
def submit_feedback_route():
    """Endpoint para receber feedback do utilizador e guardá-lo em personas.json."""
    if not request.json:
        return jsonify({"error": "Pedido inválido (JSON esperado)."}), 400
    
    required_fields = ['persona_name', 'ai_original_response', 'user_corrected_output', 'feedback_category', 'interaction_context']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        return jsonify({"error": f"Dados em falta no pedido: {', '.join(missing)}."}), 400
    
    persona_name = request.json['persona_name']
    
    with personas_file_lock:
        try:
            current_persona_data = load_persona_file() # Garante que estamos a trabalhar com a versão mais recente
            
            if "personas" not in current_persona_data or persona_name not in current_persona_data["personas"]:
                return jsonify({"error": f"Persona '{persona_name}' não encontrada para submeter feedback."}), 404
            
            persona_obj = current_persona_data["personas"][persona_name]
            persona_obj.setdefault('learned_knowledge_base', []) # Garante que a lista existe
            
            feedback_entry = {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "feedback_category_pt": request.json['feedback_category'],
                "ai_original_response_text": request.json['ai_original_response'],
                "user_corrected_output_text": request.json['user_corrected_output'],
                "user_explanation_text_pt": request.json.get('user_explanation', ''),
                "interaction_context_snapshot": request.json['interaction_context'],
                "model_used_for_original": request.json['interaction_context'].get('model_used', GEMINI_MODEL)
            }
            persona_obj['learned_knowledge_base'].append(feedback_entry)
            
            if not save_persona_file(current_persona_data):
                return jsonify({"error": "Falha ao salvar feedback."}), 500
            
        except Exception as e:
            logging.exception("Erro ao guardar feedback:")
            return jsonify({"error": f"Erro inesperado do servidor ao processar feedback: {e}"}), 500
    
    # Atualiza os dados globais da persona em memória após guardar no disco
    global PERSONA_DATA
    PERSONA_DATA = current_persona_data
    return jsonify({"message": "Feedback submetido com sucesso!"})


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    if not os.path.exists(CLIENT_SECRETS_FILE):
        logging.critical(f"ERRO FATAL: `client_secret.json` não encontrado. Por favor, descarregue-o da sua Google Cloud Console.")
    else:
        logging.info("--- A Iniciar Aplicação Flask ---")
        logging.info(f"Host: {APP_HOST}, Porta: {APP_PORT}, Modo de Depuração: {DEBUG_MODE}")
        logging.info(f"Modelo Gemini: {GEMINI_MODEL}")
        if not GEMINI_API_KEY:
            logging.warning("A variável de ambiente GEMINI_API_KEY não está definida!")
        else:
            logging.info(f"Chave da API do Gemini encontrada (mascarada): ...{GEMINI_API_KEY[-4:]}")

        if not PERSONA_DATA:
            logging.critical("PERSONA_DATA está vazio! A aplicação pode não funcionar corretamente.")
        else:
            logging.info(f"{len(PERSONA_DATA.get('personas', {}))} persona(s) carregada(s).")

        app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)
