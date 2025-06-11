# -*- coding: utf-8 -*-
import os
import json
import re
import requests
import logging
import traceback # Para logging de exceções mais detalhado
import datetime # Para timestamps no feedback
import threading # Para file locking simples
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()

# Configura o logging básico para um melhor rastreamento
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

# --- Configuração da Aplicação ---
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GENERATION_TEMPERATURE = float(os.environ.get('GENERATION_TEMPERATURE', 0.75))
REFINEMENT_TEMPERATURE = float(os.environ.get('REFINEMENT_TEMPERATURE', 0.4))
ANALYSIS_TEMPERATURE = 0.2

DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# --- Configuração do Gemini ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash-latest')

# --- Caminhos de Ficheiros ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONAS_FILE = os.path.join(BASE_DIR, 'personas2.0.json')

# Inicialização da aplicação Flask
app = Flask(__name__)
if DEBUG_MODE:
    app.logger.setLevel(logging.DEBUG)
else:
    app.logger.setLevel(logging.INFO)

# Lock para proteger o acesso concorrente ao ficheiro personas.json
personas_file_lock = threading.Lock()

# --- Carregamento de Dados das Personas ---
def load_persona_file():
    """Carrega ou recarrega de forma segura o conteúdo do ficheiro de personas."""
    try:
        with personas_file_lock:
            if not os.path.exists(PERSONAS_FILE):
                logging.error(f"CRITICAL ERROR: Personas file '{PERSONAS_FILE}' not found.")
                return {}
            with open(PERSONAS_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    logging.warning(f"Personas file '{PERSONAS_FILE}' is empty.")
                    return {}
                full_data = json.loads(content)
        logging.info(f"Personas data loaded successfully from {PERSONAS_FILE}")
        return full_data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"CRITICAL ERROR loading personas file: {e}\n{traceback.format_exc()}")
        return {}
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading personas: {e}\n{traceback.format_exc()}")
        return {}

# Carregamento inicial dos dados
PERSONA_DATA = load_persona_file()

# --- Comunicação com a API Gemini ---
def call_gemini(prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE):
    """Envia um prompt para a API Gemini e retorna a resposta, com tratamento de erros robusto."""
    if not GEMINI_API_KEY:
        logging.error("Environment variable GEMINI_API_KEY not set!")
        return {"error": "ERROR_CONFIG: Gemini API Key not configured."}

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

    logging.info(f"Sending to Gemini API | Model: {model} | Temp: {temperature}")
    app.logger.debug(f"Payload (first 500 chars): {str(payload)[:500]}...")

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        data = response.json()
        app.logger.debug(f"API Response (partial): {str(data)[:500]}...")

        if data.get('promptFeedback', {}).get('blockReason'):
            reason = data['promptFeedback']['blockReason']
            logging.error(f"Prompt blocked by Gemini. Reason: {reason}. Details: {data['promptFeedback']}")
            return {"error": f"ERROR_GEMINI_BLOCKED_PROMPT: Prompt blocked. Reason: {reason}"}

        if candidates := data.get('candidates'):
            candidate = candidates[0]
            finish_reason = candidate.get('finishReason', 'UNKNOWN')

            if finish_reason not in ['STOP', 'MAX_TOKENS']:
                logging.warning(f"Gemini finishReason was '{finish_reason}'.")
                if finish_reason in ['SAFETY', 'RECITATION', 'OTHER']:
                    return {"error": f"ERROR_GEMINI_BLOCKED_FINISH: Generation stopped. Reason: {finish_reason}."}

            if text_parts := candidate.get('content', {}).get('parts', []):
                if 'text' in text_parts[0]:
                    return {"text": text_parts[0]['text'].strip()}

            logging.error(f"No text found in Gemini response. Finish reason: {finish_reason}. Candidate: {candidate}")
            return {"error": "ERROR_GEMINI_PARSE: Valid response but no generated text found."}

        logging.error(f"Unexpected API response structure. Data: {str(data)[:500]}")
        return {"error": "ERROR_GEMINI_PARSE: Unexpected response structure."}

    except requests.exceptions.Timeout as e:
        logging.error("Timeout contacting Gemini API: %s", e)
        return {"error": "ERROR_GEMINI_TIMEOUT: The request to the Gemini API timed out."}
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response else "N/A"
        details = e.response.text if e.response else str(e)
        logging.error(f"Gemini API request failed. Status: {status}. Details: {details[:200]}...")
        return {"error": f"ERROR_GEMINI_REQUEST: API request failed with status {status}."}
    except Exception as e:
        logging.exception("An unexpected error occurred in call_gemini:")
        return {"error": f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"}


# --- Funções de Construção de Prompts (Avançadas) ---

def build_holistic_draft_prompt(original_email, user_guidance, active_persona_key, persona_data, context_analysis_result, summarized_knowledge=""):
    """
    (IMPROVED) Constrói o prompt holístico com Cadeia de Pensamento, enriquecido pela pré-análise E pela memória de contexto.
    """
    
    knowledge_section = ""
    if summarized_knowledge:
        knowledge_section = f"""
### MEMÓRIA DE CONTEXTO (APRENDIZAGEM ATIVA) - ALTA PRIORIDADE ###
A análise de interações passadas com este remetente gerou as seguintes diretrizes. VOCÊ DEVE SEGUIR ESTAS REGRAS ESPECÍFICAS para esta pessoa, sobrepondo-se a regras gerais se houver conflito:
---
{summarized_knowledge}
---
"""

    system_prompt_text = f"""
# SYSTEM PROMPT: ASSISTENTE ESPECIALISTA EM E-MAIL ACADÉMICO

## 1. A SUA IDENTIDADE E OBJETIVO PRINCIPAL
Você é um assistente especialista em comunicação, agindo como um co-piloto de escrita inteligente para redigir e-mails excecionais. O seu objetivo é gerar um e-mail final natural, coerente e humano, que atinja perfeitamente a intenção do utilizador.

{knowledge_section}

## 2. REGRAS NÃO NEGOCIÁVEIS
Independente das diretrizes da persona ou da memória de contexto, as seguintes regras têm prioridade MÁXIMA:
* **Etiqueta Profissional:** Todos os e-mails DEVEM começar com uma saudação apropriada ao destinatário e terminar com uma despedida e assinatura adequadas, a menos que a MEMÓRIA DE CONTEXTO especifique uma despedida EXATA.
* **Precisão Factual:** A resposta deve ser factualmente correta. Se o utilizador pede para confirmar uma AÇÃO FUTURA (ex: "vou assinar a ata"), a sua resposta deve refletir isso. NUNCA afirme que uma ação já foi concluída se não foi essa a instrução.

## 3. O SEU PROCESSO DE RACIOCÍNIO AVANÇADO

Para cada pedido, você deve seguir um rigoroso processo de **Cadeia de Pensamento e um Ciclo de Qualidade final**.

### PARTE 1: CADEIA DE PENSAMENTO (ANÁLISE INTERNA)

1.  **Análise do Pedido e do Contexto:**
    * **Análise de Contexto Pré-Processada:** LEIA a análise já feita sobre o remetente e tom. Use esta informação como verdade absoluta para guiar a sua resposta.
    * **Intenção do Utilizador:** Qual é o verdadeiro objetivo por detrás do `PEDIDO DO UTILIZADOR`?
    * **Análise do E-mail Recebido:** Qual é o tom, hierarquia e pedido central?

2.  **Síntese da Persona:**
    * **Aplicar Memória de Contexto:** A primeira e mais importante fonte de orientação é a `MEMÓRIA DE CONTEXTO`. Aplique essas regras de forma rigorosa.
    * **Identificar Persona Ativa:** `PERSONA ATIVA`.
    * **Carregar Arquétipo e Regras de Adaptação:** Use o arquétipo como base e as `generic_recipient_adaptation_rules` para refinar, guiado pela `Categoria do Remetente` da análise de contexto. As regras da `MEMÓRIA DE CONTEXTO` têm prioridade sobre estas.
    * **Priorizar Conhecimento Adquirido (Raw):** Use o `learned_knowledge_base` completo como fonte secundária para extrair nuances que a memória resumida possa ter perdido.

3.  **Planeamento da Estrutura do E-mail:**
    * Saudação, Abertura, Corpo Principal, Fecho e Despedida.

### PARTE 2: GERAÇÃO E CICLO DE QUALIDADE

1.  **Escrever o Primeiro Rascunho (Draft 1).**

2.  **Verificação de Qualidade e Refinamento (Quality Check & Refinement):** Avalie o seu Draft 1 de forma crítica contra esta checklist obrigatória:
    * **✅ Memória de Contexto:** As regras de alta prioridade da `MEMÓRIA DE CONTEXTO` foram 100% cumpridas? (A MAIS IMPORTANTE)
    * **✅ Regras Não Negociáveis:** As regras de etiqueta e precisão factual foram cumpridas?
    * **✅ Cumprimento da Intenção:** Atinge 100% o objetivo do utilizador?
    * **✅ Alinhamento com a Persona e Contexto:** A resposta soa genuinamente como a persona e está adaptada ao `Tom do E-mail Recebido`?
    * **✅ Clareza e Profissionalismo:** A linguagem é clara, profissional e humana?

3.  **Escrever a Versão Final Melhorada (Final Version):** Com base na sua verificação, reescreva o e-mail para produzir a versão final e polida.

## 4. OUTPUT ESPERADO
O seu output final deve ser **APENAS o texto completo do e-mail da "Final Version"**. Não mostre a sua cadeia de pensamento ou rascunhos intermédios.
"""

    persona_data_json_string = json.dumps(persona_data, indent=2, ensure_ascii=False)

    final_prompt = f"""{system_prompt_text}

--- INÍCIO DOS DADOS PARA A TAREFA ---

### ANÁLISE DE CONTEXTO (PRÉ-PROCESSADA) ###
- Categoria do Remetente: {context_analysis_result.get('recipient_category', 'desconhecida')}
- Tom do E-mail Recebido: {context_analysis_result.get('incoming_tone', 'desconhecido')}
- Nome do Remetente (suposição): {context_analysis_result.get('sender_name_guess', 'não identificado')}
- Justificação da Análise: {context_analysis_result.get('rationale', 'N/A')}

### PEDIDO DO UTILIZADOR ###
{user_guidance}

### E-MAIL RECEBIDO ###
---
{original_email if original_email.strip() else "Nenhum e-mail recebido fornecido. A resposta deve ser um novo e-mail."}
---

### PERSONA ATIVA ###
{active_persona_key}

### DADOS DE CONTEXTO DA PERSONA (JSON) ###
```json
{persona_data_json_string}
```
--- FIM DOS DADOS PARA A TAREFA ---

Agora, execute o seu processo de raciocínio avançado e gere o e-mail final.

**E-mail Final:**
"""
    return final_prompt

def build_prompt_1_analysis(email_text):
    """
    (NOVO) Constrói o prompt para uma Análise de Intenção e Pontos de Decisão do Utilizador.
    """
    return f"""System: You are an expert email analyst. Your task is to perform an **Intent Analysis** on the received email. Your goal is to identify the core request and, most importantly, determine the **key decision points** that require input ONLY from the user to proceed. Do not ask for information that could be inferred or is secondary. Focus on what the user MUST decide.

Task: Analyze the email below and respond ONLY with a valid JSON object. Do not add any text before or after the JSON. Use Portuguese (pt-PT) for the content.

The JSON object must have two keys:
1.  `core_request`: A string summarizing the sender's core request in one objective sentence.
2.  `decision_points`: An array of strings. Each string is a concise, summarized question representing a crucial decision or piece of context that only the user can provide. If there are no specific decision points (e.g., a simple thank you email), provide a generic point about how to reply.

Example for a code review email:
{{
  "core_request": "O remetente pede uma revisão de um snippet de código Python que está a dar um erro.",
  "decision_points": [
    "Confirmar a análise do snippet e definir uma expectativa de resposta (ex: 'Vou ver hoje', 'Estou ocupado agora')."
  ]
}}

Example for a meeting request:
{{
  "core_request": "O remetente propõe uma reunião para a próxima semana para discutir o projeto.",
  "decision_points": [
    "Aceitar, recusar ou sugerir uma nova data/hora para a reunião.",
    "Confirmar os tópicos de discussão ou propor novos."
  ]
}}

Example for a simple notification:
{{
  "core_request": "O remetente informa que a ata foi assinada.",
  "decision_points": [
    "Decidir se é necessário responder e, em caso afirmativo, como (ex: 'Agradecer a confirmação')."
  ]
}}

---
Email Recebido para Análise:
---
{email_text}
---

JSON Result:
"""

def build_prompt_0_context_analysis(original_email, persona, generic_rules):
    """
    Constrói o prompt para Pré-Análise (Prompt 0): identificar tipo de destinatário,
    tom, nome do remetente e justificação.
    """
    max_email_length = 3000
    truncated_email = original_email[:max_email_length]
    if len(original_email) > max_email_length:
        truncated_email += "\n... (email truncado)"

    persona_context = {
        "name": persona.get("label_pt", "N/A"),
        "role": persona.get("role_template", "N/A"),
        "language": persona.get("communication_attributes", {}).get("language", "pt-PT"),
        "recipient_types": list(generic_rules.keys())
    }

    prompt = f"""System: You are an expert in email context analysis. Given the Persona who will respond and the Received Email, carefully analyze the sender (From:), recipients (To:/Cc:), greeting, body, and signature to determine the most likely relationship, the email's tone, and the main sender's name. Respond **ONLY** in valid JSON format.

Persona Que Vai Responder (Contexto Relevante):
```json
{json.dumps(persona_context, indent=2, ensure_ascii=False)}
```

Email Recebido:
---
{truncated_email}
---

Tarefa: Analisa o email recebido e o contexto da persona. Determina a categoria mais provável do remetente PRINCIPAL e o tom do email recebido. Devolve **APENAS** um objeto JSON com as seguintes chaves **OBRIGATÓRIAS**:

1.  `recipient_category`: (string) A chave **exata** que melhor descreve o remetente. Deve ser UMA das chaves `recipient_types` fornecidas (ex: "student_to_professor_academic_inquiry"). Se nenhuma opção se aplicar, retorna "unknown".
2.  `incoming_tone`: (string) O tom percebido do **email recebido**. Escolha UMA das opções: "Muito Formal", "Formal", "Semi-Formal", "Casual", "Urgente", "InformativoNeutro", "Outro".
3.  `sender_name_guess`: (string) A melhor suposição do nome do remetente principal (ex: "Marta Silva", "João Carlos"). **IMPORTANTE: Omita títulos como 'Prof.', 'Dr.', 'Eng.', etc.** Se impossível determinar, retorna uma string vazia "".
4.  `rationale`: (string) Uma frase **curta e objetiva** a justificar a escolha da `recipient_category`.

**IMPORTANTE:** A tua saída deve ser **APENAS** o objeto JSON, sem qualquer texto adicional antes ou depois. Exemplo de saída válida:
{{
  "recipient_category": "student_to_colleague_project_collaboration",
  "incoming_tone": "Semi-Formal",
  "sender_name_guess": "Ana Silva",
  "rationale": "Conteúdo do email refere 'dúvidas sobre o projeto' e assinatura inclui número de aluno."
}}

JSON Result:
"""
    return prompt

def build_prompt_3_suggestion(point_to_address, persona, direction):
    """
    (FIXED) Constrói o prompt para sugerir uma "diretriz" exemplar para um Ponto de Decisão.
    Esta função gera uma INSTRUÇÃO para a IA, não um trecho do e-mail.
    """
    persona_name = persona.get('label_pt', 'Assistente')
    
    direction_map = {
        'sim': 'AFIRMATIVA / POSITIVA',
        'nao': 'NEGATIVA',
        'outro': 'NEUTRA / DETALHADA'
    }
    direction_text = direction_map.get(direction, 'NEUTRA / DETALHADA')
    
    comm_attrs = persona.get('communication_attributes', {})
    persona_lang = comm_attrs.get('language', 'pt-PT')
    
    return f"""System: Your task is to act as a helpful assistant and generate a single, concise **guidance instruction** for a user. This instruction tells the user what to write to an AI to get a good email response.
The instruction you generate should be:
- Actionable and clear.
- In Portuguese (pt-PT).
- Reflect a **{direction_text}** intention.
- Brief (one sentence).

---
**Context:**
* **Persona who will write the final email:** '{persona_name}'
* **Decision Point from original email:** "{point_to_address}"
* **Intended slant for the response:** {direction_text}

**Task:**
Write the exemplary guidance text a user could give to the AI.

**Exemplary Guidance Text (Your output must be ONLY this text, nothing else):**
"""

def build_prompt_4_refinement(persona, selected_text, full_context, action):
    """Constrói o prompt para refinar uma parte do texto."""
    persona_name = persona.get('label_pt', 'Assistant')
    persona_info = f"System: Act as a '{persona_name}'. Maintain the persona's style and language."
    action_instructions = {
        "make_formal": "Rewrite the 'Selected Text' to be significantly more formal.",
        "make_casual": "Rewrite the 'Selected Text' to be more casual and direct.",
        "shorten": "Significantly shorten the 'Selected Text', preserving its core meaning.",
        "expand": "Elaborate on the 'Selected Text', adding relevant details or explanations.",
        "rephrase": "Rewrite the 'Selected Text', expressing the same core idea differently.",
    }
    instruction = action_instructions.get(action, f"Modify the 'Selected Text' as requested ({action}).")

    return f"""{persona_info}
Task: Refine a part of an email draft.
Action: {instruction}
Full Draft:
---
{full_context}
---
Selected Text to Modify:
---
{selected_text}
---
MANDATORY: RETURN ONLY THE MODIFIED TEXT.

Modified Text:
"""

def build_prompt_5_summarize_knowledge(relevant_feedback_entries, sender_name):
    """
    (NEW) Constrói um prompt para o LLM sintetizar conhecimento relevante sobre um contacto.
    """
    formatted_entries = ""
    for i, entry in enumerate(relevant_feedback_entries):
        original = entry.get('ai_original_response_text', 'N/A')
        corrected = entry.get('user_corrected_output_text', 'N/A')
        explanation = entry.get('user_explanation_text_pt', 'N/A')
        formatted_entries += f"""
### Exemplo de Feedback Passado {i+1} ###
- **Explicação do Utilizador:** "{explanation}"
- **O que a IA escreveu:** "{original}"
- **O que o utilizador corrigiu para:** "{corrected}"
"""

    prompt = f"""System: You are a Knowledge Synthesizer. Your goal is to analyze past user feedback related to a specific person and extract a concise, actionable set of rules for an AI assistant to follow in the future.

**Task:**
Analyze the following feedback provided for communications with **{sender_name}**.
Based ONLY on the user's explanations and corrections, create a short, bulleted list of style rules or preferences.
Focus on the core lesson. For example, if the user always changes the closing to "beijinhos", the rule should be "Use 'beijinhos' as the closing."

**DO NOT** invent rules. If the feedback is unclear, state that. Your output must be ONLY the bulleted list of rules.

---
**Dados de Feedback para {sender_name}:**
{formatted_entries}
---

**Regras de Estilo Sintetizadas para {sender_name} (apenas a lista com bullets):**
"""
    return prompt

# --- Funções de Análise, Parsing e Conhecimento ---

def _normalize_name(name):
    """(NEW HELPER) Normaliza um nome para uma correspondência mais robusta."""
    if not name:
        return ""
    # Converte para minúsculas
    name = name.lower()
    # Remove títulos comuns
    titles = ['prof.', 'prof', 'dr.', 'dr', 'eng.', 'eng', 'dra.', 'dra']
    for title in titles:
        name = name.replace(title, '')
    # Remove pontuação e excesso de espaços
    name = re.sub(r'[^\w\s]', '', name)
    return name.strip()

def find_and_summarize_relevant_knowledge(persona_obj, current_context_analysis):
    """
    (REBUILT FOR 100% RELIABILITY) Encontra feedback relevante usando lógica de correspondência multicamada e o sintetiza.
    """
    knowledge_base = persona_obj.get("learned_knowledge_base", [])
    current_sender_name_raw = current_context_analysis.get("sender_name_guess", "")
    
    if not knowledge_base or not current_sender_name_raw:
        logging.info("Knowledge base search skipped: no knowledge base or no current sender name.")
        return ""

    normalized_current_name = _normalize_name(current_sender_name_raw)
    if not normalized_current_name:
        logging.info("Knowledge base search skipped: current sender name is empty after normalization.")
        return ""

    relevant_feedback = []
    
    logging.info(f"Starting knowledge search for normalized name: '{normalized_current_name}'")

    for entry in knowledge_base:
        try:
            snapshot_sender_name_raw = entry.get("interaction_context_snapshot", {}).get("llm_pre_analysis_snapshot", {}).get("sender_name_guess", "")
            explanation_text = entry.get("user_explanation_text_pt", "").lower()
            
            normalized_snapshot_name = _normalize_name(snapshot_sender_name_raw)

            is_match = False
            
            # Nível 1: Correspondência direta dos nomes normalizados (mais fiável)
            if normalized_snapshot_name and normalized_current_name == normalized_snapshot_name:
                is_match = True
                logging.info(f"MATCH (Level 1 - Exact Normalized): '{normalized_current_name}' vs '{normalized_snapshot_name}'")
            
            # Nível 2: Correspondência de substring (para "Prof. Nome" vs "Nome")
            elif not is_match and normalized_snapshot_name and (normalized_snapshot_name in normalized_current_name or normalized_current_name in normalized_snapshot_name):
                is_match = True
                logging.info(f"MATCH (Level 2 - Substring): '{normalized_current_name}' vs '{normalized_snapshot_name}'")

            # Nível 3: O nome atual está na explicação do feedback? (para regras explícitas como "Sempre que falar com Inês Teixeira...")
            elif not is_match and normalized_current_name in explanation_text:
                is_match = True
                logging.info(f"MATCH (Level 3 - Explanation Text): Found '{normalized_current_name}' in explanation: '{explanation_text[:50]}...'")

            if is_match:
                if entry not in relevant_feedback:
                    relevant_feedback.append(entry)

        except Exception as e:
            logging.warning(f"Skipping a malformed feedback entry during knowledge search: {e}")
            continue
    
    if not relevant_feedback:
        logging.info(f"NO MATCHES FOUND for sender: '{current_sender_name_raw}' (Normalized: '{normalized_current_name}')")
        return ""

    logging.info(f"Found {len(relevant_feedback)} relevant feedback entries for '{current_sender_name_raw}'. Synthesizing knowledge...")

    synthesis_prompt = build_prompt_5_summarize_knowledge(relevant_feedback, current_sender_name_raw)
    llm_response = call_gemini(synthesis_prompt, temperature=0.1)

    if "error" in llm_response or not llm_response.get("text"):
        logging.error(f"Failed to synthesize knowledge for {current_sender_name_raw}. Error: {llm_response.get('error', 'Empty response')}")
        return ""

    summarized_knowledge = llm_response.get("text", "").strip()
    logging.info(f"Summarized knowledge for '{current_sender_name_raw}': {summarized_knowledge}")
    return summarized_knowledge


def analyze_sender_and_context(original_email, persona, generic_rules):
    """
    Chama o LLM para realizar a Pré-Análise de Contexto (Prompt 0)
    e retorna os resultados JSON analisados.
    """
    logging.info(f"Starting Context Pre-Analysis for email and persona {persona.get('label_pt', 'N/A')}")
    if not persona:
        return {"error": "Invalid persona provided for context analysis."}

    analysis_prompt = build_prompt_0_context_analysis(original_email, persona, generic_rules)
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.2)

    if "error" in llm_response_data:
        logging.error(f"Error in Gemini call for Pre-Analysis: {llm_response_data['error']}")
        return {
            "recipient_category": "unknown", "incoming_tone": "Neutro",
            "sender_name_guess": "", "rationale": "",
            "error": f"Failed communication with LLM for pre-analysis: {llm_response_data['error']}"
        }

    llm_response_text = llm_response_data.get("text", "")
    logging.info("Pre-Analysis received from Gemini, parsing JSON.")

    try:
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```|({[\s\S]+})", llm_response_text)
        json_str = json_match.group(1) or json_match.group(2) if json_match else llm_response_text
        parsed_json = json.loads(json_str)

        required_keys = ["recipient_category", "incoming_tone", "sender_name_guess", "rationale"]
        if any(key not in parsed_json for key in required_keys):
            raise ValueError(f"Invalid Pre-Analysis JSON. Missing keys.")

        parsed_json["error"] = None
        logging.info("Pre-Analysis JSON parsed successfully.")
        return parsed_json

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        error_msg = f"Failed to parse or validate Pre-Analysis JSON: {e}. Raw: {llm_response_text[:200]}..."
        logging.error(error_msg)
        return {
            "recipient_category": "unknown", "incoming_tone": "Neutro",
            "sender_name_guess": "", "rationale": "",
            "error": f"ERROR_PARSE_CONTEXT: {error_msg}"
        }

def parse_analysis_output(llm_output_text):
    """
    (ATUALIZADO) Faz o parsing da resposta JSON da nova Análise de Intenção.
    """
    if not isinstance(llm_output_text, str) or not llm_output_text.strip():
        return {"error": "Empty or invalid response from LLM analysis"}

    try:
        json_match = re.search(r"```json\s*({[\s\S]*?})\s*```|({[\s\S]*})", llm_output_text)
        if not json_match:
            parsed_json = json.loads(llm_output_text)
        else:
            json_str = json_match.group(1) or json_match.group(2)
            parsed_json = json.loads(json_str)

        core_request = parsed_json.get("core_request")
        decision_points = parsed_json.get("decision_points")

        if not isinstance(core_request, str) or not isinstance(decision_points, list):
            raise ValueError("JSON structure is invalid.")

        return {
            "core_request": [core_request],
            "points": decision_points,
            "actions": []
        }
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Failed to parse analysis JSON: {e}. Raw output: {llm_output_text[:300]}")
        return {"error": f"Failed to parse the analysis from the AI. Details: {e}"}


# --- Rotas da Aplicação Flask ---

@app.route('/')
def index_route():
    """Serve a página inicial."""
    global PERSONA_DATA
    if DEBUG_MODE:
        PERSONA_DATA = load_persona_file()
    personas_dict = PERSONA_DATA.get("personas", {})
    personas_display = {key: {"name": data.get("label_pt", key)} for key, data in personas_dict.items()}
    return render_template('index.html', personas_dict=personas_display, error_loading_personas=not bool(personas_dict))

@app.route('/analyze', methods=['POST'])
def analyze_email_route():
    """(ATUALIZADO) Endpoint para a nova Análise de Intenção."""
    if not request.json or not request.json.get('email_text', '').strip():
        return jsonify({"error": "Email text cannot be empty."}), 400
    email_text = request.json['email_text']
    logging.info("Starting Intent Analysis")
    analysis_prompt = build_prompt_1_analysis(email_text)
    llm_response = call_gemini(analysis_prompt, temperature=ANALYSIS_TEMPERATURE)

    if "error" in llm_response:
        logging.error(f"Error in Gemini call for /analyze: {llm_response['error']}")
        return jsonify({"error": f"LLM analysis failed: {llm_response['error']}", "raw_analysis": llm_response.get("text")}), 500

    analysis_result = parse_analysis_output(llm_response.get("text", ""))
    analysis_result["raw_analysis_response"] = llm_response.get("text", "")

    logging.info("Intent analysis processed successfully.")
    return jsonify(analysis_result)


@app.route('/draft', methods=['POST'])
def draft_response_route():
    """(IMPROVED) Endpoint principal para gerar a minuta, com recuperação de conhecimento ativo."""
    global PERSONA_DATA
    if not request.json:
        return jsonify({"error": "Invalid request (JSON expected)."}), 400

    required = ['original_email', 'persona_name', 'user_inputs']
    if not all(field in request.json for field in required):
        return jsonify({"error": f"Missing data: {', '.join(f for f in required if f not in request.json)}."}), 400

    original_email = request.json['original_email']
    active_persona_key = request.json['persona_name']
    if not PERSONA_DATA or active_persona_key not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{active_persona_key}' not found or personas not loaded."}), 400

    selected_persona = PERSONA_DATA["personas"][active_persona_key]
    generic_rules = PERSONA_DATA.get("generic_recipient_adaptation_rules", {})

    # --- PASSO 1: Pré-Análise de Contexto ---
    context_analysis_result = analyze_sender_and_context(original_email, selected_persona, generic_rules)
    if context_analysis_result.get("error") and "PARSE_CONTEXT" not in context_analysis_result["error"]:
        logging.error(f"Critical error during Context Pre-Analysis: {context_analysis_result['error']}")
        return jsonify({"error": f"Context pre-analysis failed: {context_analysis_result['error']}"}), 500
    elif context_analysis_result.get("error"):
         logging.warning(f"Non-critical error during Pre-Analysis: {context_analysis_result['error']}. Continuing with defaults.")

    # --- PASSO 2 (NEW): Recuperação e Síntese de Conhecimento Ativo ---
    summarized_knowledge = find_and_summarize_relevant_knowledge(selected_persona, context_analysis_result)

    # --- PASSO 3: Construção da Orientação do Utilizador ---
    user_inputs = request.json['user_inputs']
    if not user_inputs or not any(item.get('guidance', '').strip() for item in user_inputs):
        user_guidance = "Escrever uma resposta apropriada ao e-mail, considerando o contexto e a persona."
    else:
        guidance_points = [f'- Para o ponto de decisão "{item.get("point", "geral")}", a minha intenção é: "{item.get("guidance")}"'
                           for item in user_inputs if item.get('guidance', '').strip()]
        user_guidance = "A intenção da resposta é a seguinte:\n" + "\n".join(guidance_points)

    logging.info(f"Starting HYBRID Draft Generation for Persona: {active_persona_key}")

    # --- PASSO 4: Geração da Minuta com Conhecimento Injetado ---
    draft_prompt = build_holistic_draft_prompt(
        original_email, user_guidance, active_persona_key, PERSONA_DATA, context_analysis_result, summarized_knowledge
    )

    llm_response = call_gemini(draft_prompt, temperature=GENERATION_TEMPERATURE)

    if "error" in llm_response:
        logging.error(f"Error in Gemini call for /draft: {llm_response['error']}")
        return jsonify({
            "error": f"Failed to generate draft with LLM: {llm_response['error']}",
            "context_analysis": context_analysis_result
        }), 500

    final_draft = llm_response.get("text", "").strip()
    logging.info(f"Final Draft Generated successfully for persona {active_persona_key}.")
    app.logger.debug(f"Final Draft:\n{final_draft}")

    return jsonify({
        "draft": final_draft,
        "context_analysis": context_analysis_result
    })

@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route():
    """(FIXED) Endpoint para gerar uma sugestão de DIRETRIZ para um Ponto de Decisão."""
    global PERSONA_DATA
    if not request.json or not all(k in request.json for k in ['point_to_address', 'persona_name']):
        return jsonify({"error": "Missing data in request (point_to_address, persona_name required)."}), 400
    
    persona_name = request.json['persona_name']
    point_to_address = request.json['point_to_address']
    original_email = request.json.get('original_email', '')
    direction = request.json.get('direction', 'outro') 

    if not point_to_address or not persona_name:
         return jsonify({"error": "Point to address and persona name cannot be empty."}), 400

    if persona_name not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400

    selected_persona = PERSONA_DATA["personas"][persona_name]
    prompt = build_prompt_3_suggestion(point_to_address, selected_persona, direction)
    
    logging.info(f"Requesting GUIDANCE suggestion for direction: {direction}")
    
    llm_response = call_gemini(prompt, temperature=ANALYSIS_TEMPERATURE)

    if "error" in llm_response:
         logging.error(f"Error suggesting guidance: {llm_response['error']}")
         return jsonify(llm_response), 500

    suggestion_text = llm_response.get("text", "").strip()
    logging.info(f"Guidance suggestion generated for '{direction}': {suggestion_text}")
    return jsonify({"suggestion": suggestion_text})


@app.route('/refine_text', methods=['POST'])
def refine_text_route():
    """Endpoint para refinar uma parte do texto gerado."""
    global PERSONA_DATA
    if not request.json or not all(k in request.json for k in ['selected_text', 'full_context', 'action', 'persona_name']):
        return jsonify({"error": "Missing data in request."}), 400
    persona_name = request.json['persona_name']
    if persona_name not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400

    selected_persona = PERSONA_DATA["personas"][persona_name]
    prompt = build_prompt_4_refinement(selected_persona, request.json['selected_text'], request.json['full_context'], request.json['action'])
    llm_response = call_gemini(prompt, temperature=REFINEMENT_TEMPERATURE)

    return jsonify(llm_response) if "error" in llm_response else jsonify({"refined_text": llm_response.get("text", "")})

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback_route():
    """
    Endpoint para receber user feedback e guardá-lo no personas.json.
    """
    if not request.json:
        logging.warning("Invalid /submit_feedback request: No JSON.")
        return jsonify({"error": "Invalid request (JSON expected)."}), 400

    required_fields = ['persona_name', 'ai_original_response', 'user_corrected_output', 'feedback_category', 'interaction_context']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Invalid /submit_feedback request: Missing data: {missing}")
        return jsonify({"error": f"Missing data in request: {', '.join(missing)}."}), 400

    persona_name = request.json['persona_name']
    user_corrected_output = request.json['user_corrected_output']
    feedback_category = request.json['feedback_category']
    interaction_context = request.json['interaction_context']

    if not persona_name.strip() or not user_corrected_output.strip() or not feedback_category.strip():
        return jsonify({"error": "Persona name, corrected output, and feedback category are mandatory."}), 400
    if not isinstance(interaction_context, dict):
        return jsonify({"error": "Interaction context is invalid or missing."}), 400

    logging.info(f"Received feedback for persona: {persona_name}. Category: {feedback_category}")

    try:
        with personas_file_lock:
            try:
                with open(PERSONAS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content:
                        logging.error(f"Error saving feedback: File '{PERSONAS_FILE}' is empty.")
                        return jsonify({"error": "Internal error: Personas configuration file is empty."}), 500
                    current_persona_data = json.loads(content)
            except FileNotFoundError:
                logging.error(f"Error saving feedback: File '{PERSONAS_FILE}' not found.")
                return jsonify({"error": "Internal error: Personas configuration file not found."}), 500
            except json.JSONDecodeError as e:
                logging.error(f"Error saving feedback: Invalid JSON in '{PERSONAS_FILE}': {e}")
                return jsonify({"error": f"Internal error: Personas configuration file corrupted. ({e})"}), 500

            if persona_name not in current_persona_data.get("personas", {}):
                logging.error(f"Error saving feedback: Persona '{persona_name}' does not exist in the file.")
                return jsonify({"error": f"Persona '{persona_name}' not found in configuration."}), 404

            persona_obj = current_persona_data["personas"][persona_name]

            persona_obj.setdefault('learned_knowledge_base', [])

            feedback_entry = {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "feedback_category_pt": feedback_category,
                "ai_original_response_text": request.json['ai_original_response'],
                "user_corrected_output_text": user_corrected_output,
                "user_explanation_text_pt": request.json.get('user_explanation', ''),
                "interaction_context_snapshot": interaction_context,
                "model_used_for_original": interaction_context.get('model_used', GEMINI_MODEL)
            }

            persona_obj['learned_knowledge_base'].append(feedback_entry)
            logging.info(f"Feedback added to 'learned_knowledge_base' for persona '{persona_name}'.")

            try:
                with open(PERSONAS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(current_persona_data, f, ensure_ascii=False, indent=2)
                logging.info(f"File '{PERSONAS_FILE}' updated successfully with new feedback.")
            except IOError as e:
                logging.error(f"I/O error trying to write to '{PERSONAS_FILE}': {e}")
                return jsonify({"error": f"Internal error: Failed to save updates. ({e})"}), 500

        return jsonify({"message": "Feedback submitted and saved successfully!"})

    except Exception as e:
        logging.exception("Unexpected error in /submit_feedback route:")
        return jsonify({"error": f"Unexpected server error processing feedback: {e}"}), 500

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    logging.info("--- Starting Flask App ---")
    logging.info(f"Host: {APP_HOST}, Port: {APP_PORT}, Debug Mode: {DEBUG_MODE}")
    logging.info(f"Gemini Model: {GEMINI_MODEL}")
    if not GEMINI_API_KEY:
        logging.warning("Environment variable GEMINI_API_KEY is not set!")
    else:
        logging.info(f"Gemini API Key found (masked): ...{GEMINI_API_KEY[-4:]}")

    if not PERSONA_DATA:
        logging.critical("PERSONA_DATA is empty! The application will not function correctly.")
    else:
        logging.info(f"{len(PERSONA_DATA.get('personas', {}))} persona(s) loaded.")

    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)
