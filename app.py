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

# Load environment variables from .env file
load_dotenv()

# Configurar logging básico
# Adiciona o nome da função ao formato do log para melhor rastreamento
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

# --- Configuração ---
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GENERATION_TEMPERATURE = float(os.environ.get('GENERATION_TEMPERATURE', 0.8)) # Temp padrão para geração
REFINEMENT_TEMPERATURE = float(os.environ.get('REFINEMENT_TEMPERATURE', 0.6)) # Temp para refinamento

DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# --- Gemini Configuration ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash-latest') # Modelo Gemini recomendado

# Diretoria base da aplicação e ficheiro de personas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONAS_FILE = os.path.join(BASE_DIR, 'personas.json')

# Inicializa a aplicação Flask
app = Flask(__name__)
# Configura o nível de log da aplicação Flask
if DEBUG_MODE:
    app.logger.setLevel(logging.DEBUG)
else:
    app.logger.setLevel(logging.INFO)

# Cria um Lock para proteger o acesso ao ficheiro personas.json
# Isto ajuda a prevenir race conditions se a app for executada com múltiplos threads/workers
personas_file_lock = threading.Lock()

# --- Carregar Personas do Ficheiro JSON (Função para poder recarregar) ---
def load_personas():
    """Carrega ou recarrega as personas do ficheiro JSON."""
    personas_data = {}
    try:
        # Usa o lock para garantir leitura segura se houver escritas concorrentes
        with personas_file_lock:
            # Garante que o ficheiro existe antes de tentar abrir
            if not os.path.exists(PERSONAS_FILE):
                 logging.error(f"ERRO CRÍTICO: Ficheiro de personas '{PERSONAS_FILE}' não encontrado ao tentar carregar.")
                 return {} # Retorna vazio se não existe

            with open(PERSONAS_FILE, 'r', encoding='utf-8') as f:
                # Verifica se o ficheiro está vazio antes de tentar fazer parse
                content = f.read()
                if not content:
                    logging.warning(f"Ficheiro de personas '{PERSONAS_FILE}' está vazio.")
                    return {}
                personas_data = json.loads(content) # Faz parse do conteúdo lido

        logging.info(f"Personas carregadas/recarregadas com sucesso de {PERSONAS_FILE}")
        return personas_data
    except FileNotFoundError: # Embora verificado acima, mantém por robustez
        logging.error(f"ERRO CRÍTICO: Ficheiro de personas '{PERSONAS_FILE}' não encontrado.")
        return {} # Retorna vazio em caso de erro
    except json.JSONDecodeError as e:
        logging.error(f"ERRO CRÍTICO: Falha ao fazer parse do JSON em '{PERSONAS_FILE}': {e}")
        return {} # Retorna vazio
    except Exception as e:
        logging.error(f"ERRO CRÍTICO: Ocorreu um erro inesperado ao carregar personas: {e}\n{traceback.format_exc()}")
        return {} # Retorna vazio

# Carregamento inicial das personas
PERSONAS = load_personas()

# --- Funções Auxiliares (call_gemini, parse_analysis_output, etc.) ---

def call_gemini(prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE):
    """
    Sends a prompt to the Google Gemini API and returns the response.

    Args:
        prompt (str): The text prompt to send.
        model (str): The Gemini model identifier to use.
        temperature (float): The generation temperature (controls creativity/randomness).

    Returns:
        dict: A dictionary containing 'text' with the LLM response on success,
              or 'error' with an error message on failure.
    """
    # Check if the API Key is configured
    if not GEMINI_API_KEY:
        logging.error("Environment variable GEMINI_API_KEY not set!")
        return {"error": "ERROR_CONFIG: Gemini API Key not configured."}

    # Gemini API v1beta endpoint
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    # API request payload
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "text/plain", # Request plain text response
            # Other generation parameters can be added here (topP, topK, maxOutputTokens)
        },
         "safetySettings": [ # Safety settings to block harmful content
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
         ]
    }
    headers = {'Content-Type': 'application/json'}

    logging.info(f"Sending to Gemini API | Model: {model} | Temp: {temperature}")
    # Log only the beginning of the payload to avoid exposing sensitive data or overloading logs
    app.logger.debug(f"Payload (first 500): {str(payload)[:500]}...")
    response = None
    try:
        # Make the POST request to the API
        response = requests.post(api_url, json=payload, headers=headers, timeout=180) # 3-minute timeout
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)

        # Process the JSON response
        data = response.json()
        app.logger.debug(f"API Response (partial): {str(data)[:500]}...")

        # --- Careful extraction of the response ---
        try:
            # Check if the prompt was blocked for safety
            if 'promptFeedback' in data and 'blockReason' in data['promptFeedback']:
                block_reason = data['promptFeedback']['blockReason']
                safety_ratings_str = f" Safety Ratings: {data['promptFeedback'].get('safetyRatings', 'N/A')}"
                error_msg = f"ERROR_GEMINI_BLOCKED_PROMPT: Prompt blocked. Reason: {block_reason}.{safety_ratings_str}"
                logging.error(f"{error_msg}. Feedback: {data['promptFeedback']}")
                return {"error": error_msg}

            # Check if there are candidates (generated responses)
            if 'candidates' in data and data['candidates']:
                candidate = data['candidates'][0] # Get the first candidate
                finish_reason = candidate.get('finishReason', 'UNKNOWN')
                safety_ratings_str = f" Safety Ratings: {candidate.get('safetyRatings', 'N/A')}"

                # Log a warning if generation didn't finish normally (STOP or MAX_TOKENS)
                if finish_reason not in ['STOP', 'MAX_TOKENS']:
                    logging.warning(f"Gemini finishReason was '{finish_reason}'. Response might be incomplete or blocked.{safety_ratings_str}")
                    # If blocked for safety during generation
                    if finish_reason in ['SAFETY', 'RECITATION', 'OTHER']:
                        error_msg = f"ERROR_GEMINI_BLOCKED_FINISH: Generation stopped. Reason: {finish_reason}.{safety_ratings_str}"
                        logging.error(error_msg)
                        return {"error": error_msg}

                # Extract the generated text from the response structure
                generated_text = None
                if 'content' in candidate and 'parts' in candidate['content'] and candidate['content']['parts']:
                    text_part = candidate['content']['parts'][0]
                    if 'text' in text_part:
                        generated_text = text_part['text']

                # Return the text if found
                if generated_text is not None:
                    return {"text": generated_text.strip()}
                else:
                    # If no text, but not explicitly blocked, log and return error
                    error_msg = f"ERROR_GEMINI_PARSE: Valid response but no generated text (finishReason: {finish_reason}). Candidate: {str(candidate)[:500]}"
                    logging.error(error_msg)
                    return {"error": error_msg}

            # Case of valid response but unexpected structure
            error_msg = f"ERROR_GEMINI_PARSE: Unexpected response structure. Data: {str(data)[:500]}"
            logging.error(error_msg)
            return {"error": error_msg}

        except (KeyError, IndexError, TypeError) as e:
            # Error accessing keys/indices in the JSON response
            error_msg = f"ERROR_GEMINI_PARSE: Exception parsing response data. Error: {e}. Data: {str(data)[:500]}"
            logging.exception("Error parsing Gemini response structure:") # Log full stack trace
            return {"error": error_msg}

    # --- Network and HTTP error handling ---
    except requests.exceptions.Timeout:
        error_msg = "ERROR_GEMINI_TIMEOUT: Timeout (180s) contacting Gemini API."
        logging.error(error_msg)
        return {"error": error_msg}
    except requests.exceptions.ConnectionError:
        error_msg = "ERROR_GEMINI_CONNECTION: Connection failed with Gemini API."
        logging.error(error_msg)
        return {"error": error_msg}
    except requests.exceptions.RequestException as e:
        # Generic requests library error (includes HTTPError)
        error_details = ""
        status_code = "N/A"
        if response is not None:
            status_code = response.status_code
            try:
                # Try to get error details from the response JSON
                error_content = response.json()
                error_details = error_content.get('error', {}).get('message', response.text)
            except (json.JSONDecodeError, AttributeError):
                 # If not JSON, get the beginning of the response text
                 if hasattr(response, 'text'):
                     error_details = response.text[:200] + "..."
        error_msg = f"ERROR_GEMINI_REQUEST: {e} (Status: {status_code}) - Details: {error_details}"
        logging.error(f"Error in Gemini API call: {e}. Status: {status_code}. Details: {error_details}")
        app.logger.debug(f"Payload that caused error (partial): {str(payload)[:500]}...")
        return {"error": error_msg}
    except json.JSONDecodeError as e:
        # Error if the API response is not valid JSON
        error_msg = f"ERROR_JSON_DECODE: Failed to decode JSON from API response. Error: {e}. Response (start): {response.text[:200] if response is not None else 'N/A'}..."
        logging.error(error_msg)
        if response is not None:
            logging.error(f"Full response received (status {response.status_code}): {response.text}")
        return {"error": error_msg}
    except Exception as e:
        # Catch any other unexpected error
        error_msg = f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"
        logging.exception("Unexpected error in call_gemini function:") # Log full stack trace
        return {"error": error_msg}

def parse_analysis_output(llm_output):
    """
    Parses the textual output from the LLM (Prompt 1 - Analysis)
    to extract lists of points to address and actions to take.

    Args:
        llm_output (str | dict): The LLM output. Can be a string or an
                                  error dictionary from `call_gemini`.

    Returns:
        dict: A dictionary with keys 'points' (list) and 'actions' (list).
              In case of input or parsing error, returns a dictionary
              with the key 'error'.
    """
    points = []
    actions = []

    # Check if input is already an error
    if isinstance(llm_output, dict) and "error" in llm_output:
        return llm_output
    if not llm_output:
        return {"error": "Empty response from LLM analysis"}
    if not isinstance(llm_output, str):
        llm_output = str(llm_output) # Ensure it's a string for regex
    if llm_output.startswith("ERROR_"):
        return {"error": llm_output} # Propagate prefixed errors

    # Regex to find the "Pontos a Responder" section and capture its content
    # Looks for "pontos a responder" or "points to address" (case-insensitive),
    # followed by a colon, optional newline, and captures everything (*)
    # until the next section "ações" or "actions" (with ** or __) or the end ($).
    points_match = re.search(
        r"(?:points\s+to\s+address|pontos\s+a\s+responder)\s*:\s*\n*(.*?)(?:\n*\s*(?:\*\*|\_\_)(?:actions|ações)|$)",
        llm_output, re.IGNORECASE | re.DOTALL
    )
    if points_match:
        points_text = points_match.group(1).strip()
        # Check if the text is not just "nenhum" or "none"
        if points_text and not re.search(r"^\s*(nenhum|none)\.?\s*$", points_text, re.IGNORECASE | re.MULTILINE):
            # Try to extract list items (numbered or with markers)
            raw_points = re.findall(r"^\s*(?:\d+[\.\)]?|\*|\-)\s+(.*?)(?=\n\s*(?:\d+[\.\)]?|\*|\-)|\Z)", points_text, re.MULTILINE | re.DOTALL)
            # Clean extra spaces and add to list if not empty
            points = [re.sub(r'\s+', ' ', p).strip() for p in raw_points if p.strip()]
    elif "pontos a responder" in llm_output.lower() or "points to address" in llm_output.lower():
        # Log warning if header found but empty or unparseable
        logging.warning("Analysis parsing: Section 'Pontos a Responder' found but was empty or unparseable.")

    # Similar regex to find the "Ações para Rodrigo" section
    actions_match = re.search(
        r"(?:actions\s+for\s+rodrigo|ações\s+para\s+rodrigo)\s*(?:\(optional|opcional\))?\s*:\s*\n*(.*?)(?:\n*\s*(?:\*\*|\_\_)|$)",
        llm_output, re.IGNORECASE | re.DOTALL
    )
    if actions_match:
        actions_text = actions_match.group(1).strip()
        # Check if not just "nenhum", "none", "nenhuma"
        if actions_text and not re.search(r"^\s*(nenhum|none|nenhuma)\.?\s*$", actions_text, re.IGNORECASE | re.MULTILINE):
            # Try to extract items with markers (* or -)
            raw_actions = re.findall(r"^\s*[\*\-]\s+(.*?)(?=\n\s*[\*\-]|\Z)", actions_text, re.MULTILINE | re.DOTALL)
            actions = [re.sub(r'\s+', ' ', a).strip() for a in raw_actions if a.strip()]

    # Log warning if expected structure not found or parsed
    if not points and not actions and not llm_output.startswith("ERROR_") and llm_output.strip():
        if not points_match and not actions_match:
             logging.warning(f"Analysis parsing: Could not find 'Pontos a Responder' or 'Ações' structure. LLM output (start): {llm_output[:200]}...")
        else:
             logging.warning(f"Analysis parsing: Found headers but failed to extract list items. LLM output (start): {llm_output[:200]}...")

    # If LLM explicitly said "nenhum ponto", return empty list
    if not points and re.search(r"nenhum ponto a responder", llm_output, re.IGNORECASE):
        points = [] # Return empty list for consistency

    return {"points": points or [], "actions": actions or []}


def build_prompt_1_analysis(email_text):
    """
    Builds the prompt to request the initial email analysis from the LLM (Prompt 1),
    focused on extracting points needing response and actions to take, with a slight emphasis on direct requests.

    Args:
        email_text (str): The full content of the received email.

    Returns:
        str: The formatted prompt for the LLM.
    """
    prompt = f"""System: You are a highly efficient and precise email analysis assistant. Your function is to read the provided email and clearly identify elements requiring a **direct response or action** from the recipient. Focus solely on the email content. **ALWAYS respond in Portuguese from Portugal (pt-PT).**

Task: Analyze the email provided below and produce your analysis strictly in the following format, with two distinct sections:

1.  **Pontos a Responder:** (Points to Address)
    * Create a **numbered list** (`1.`, `2.`, `3.`, ...) containing the **key questions (explicit or strongly implied)** and **direct requests** mentioned in the email that **need a direct response, answer, or clarification** by Rodrigo.
    * **Prioritize actual questions and clear calls to action.**
    * Include information requests if they are directly asking for something specific.
    * Formulate each point clearly and concisely, ideally as a question or statement needing a response/confirmation.
    * If the email is purely informational, a thank you, or contains absolutely nothing that needs a direct response or action, write only: `Nenhum ponto a responder.` (No points to address.)

2.  **Ações para Rodrigo (Opcional):** (Actions for Rodrigo (Optional))
    * If, and only if, the email mentions or implies concrete tasks or actions that Rodrigo needs to **perform** (beyond simply replying to the email - e.g., "envia ficheiro X", "marcar reuniao Y", "pesquisa Z"), list them here using markers (`* `).
    * If no clear actions are identified for Rodrigo, completely omit this "Ações para Rodrigo" section or write `Nenhuma ação específica para Rodrigo.` (No specific actions for Rodrigo.).

    
Analyze and extract the points that are meant to be answered and not all text that is giving information or context about something.
Keep the analysis focused and objective on the email content, prioritizing elements that require a direct response or action. Avoid listing general topics or informational statements that don't solicit a specific reply. Make sure to follow the requested format (numbered list for points, bullets for actions).

Email Recebido: (Received Email)
---
{email_text}
---
**Análise:** (Analysis)
"""
    return prompt

    
def build_prompt_0_context_analysis(original_email, persona):
    """
    Builds the prompt for Pre-Analysis (Prompt 0): identify recipient type,
    tone of the received email, sender's name (WITHOUT TITLES), and rationale, using the LLM.

    Args:
        original_email (str): The content of the received email.
        persona (dict): The dictionary of the persona who will respond.

    Returns:
        str: The formatted prompt for the LLM to request context analysis in JSON.
    """
    # Limit email size to avoid excessively long prompts and costs
    max_email_length = 3000 # Adjust as needed (consider tokens)
    truncated_email = original_email[:max_email_length]
    if len(original_email) > max_email_length:
        truncated_email += "\n... (email truncado)" # email truncated

    # Extract only relevant persona information for this analysis
    # Adjusted to use the correct keys from the provided personas.json
    persona_context = {
        "name": persona.get("name", "N/A"),
        "role": persona.get("role", "N/A"),
        "language": persona.get("attributes", {}).get("language", "pt-PT"),
        # Use 'relationships_specifics' and get 'known_name'
        "relationships": {k: v.get('known_name', 'N/A') for k, v in persona.get("relationships_specifics", {}).items()},
        # Include keys from adaptation rules AND specific relationships
        # to help the LLM map correctly
        "recipient_types": list(persona.get("recipient_adaptation_rules", {}).keys()) + list(persona.get("relationships_specifics", {}).keys())
    }


    # The prompt instructs the LLM to analyze the email and persona, and return specific JSON.
    prompt = f"""System: You are an expert in email context analysis. Given the Persona who will respond and the Received Email, carefully analyze the sender (From:), recipients (To:/Cc:), greeting, body, and signature to determine the most likely relationship, the email's tone, and the main sender's name. Respond **ONLY** in valid JSON format.

Persona Que Vai Responder (Contexto Relevante): (Responding Persona (Relevant Context))
```json
{json.dumps(persona_context, indent=2, ensure_ascii=False)}
```

Email Recebido (Analisa o conteúdo e metadados como From/To/Cc se disponíveis): (Received Email (Analyze content and metadata like From/To/Cc if available))
---
{truncated_email}
---

Tarefa: Analisa o email recebido e o contexto da persona. Determina a categoria mais provável do remetente PRINCIPAL (a quem a resposta será dirigida) e o tom do email recebido. Devolve **APENAS** um objeto JSON com as seguintes chaves **OBRIGATÓRIAS**: (Task: Analyze the received email and persona context. Determine the most likely category of the MAIN sender (to whom the reply will be addressed) and the tone of the received email. Return **ONLY** a JSON object with the following **MANDATORY** keys:)

1.  `recipient_category`: (string) The **exact** key that best describes the main sender. Must be ONE of the following options, in order of priority:
    * The key of one of the persona's `relationships` (e.g., "prof.jorge.bernardino@exemplo.com") if there is a clear and direct match between the email sender and that specific relationship (by email, name, etc.).
    * The key of one of the persona's `recipient_types` (e.g., "professor_orientador", "colega_projeto_academico", "servicos_academicos_isec", "empresa_recrutamento_estagio", "unknown_formal_default") if it's not a specific relationship but fits a general category defined in the rules.
    * "unknown" if none of the above options clearly apply or if information is insufficient.
2.  `incoming_tone`: (string) The perceived tone/formality of the **received email**. Choose ONE of the following options that best describes the email: "Muito Formal" (Very Formal), "Formal", "Semi-Formal", "Casual", "Urgente" (Urgent), "InformativoNeutro" (InformativeNeutral), "Outro" (Other).
3.  `sender_name_guess`: (string) The best guess of the main sender's name (e.g., "Marta Silva", "João Carlos", "Ana", "Equipa de Suporte"). **IMPORTANT: Extract ONLY the first name and/or last name, OMITTING titles like 'Prof.', 'Professor', 'Dr.', 'Eng.', 'Exmo.', etc.** If the name is an entity (e.g., 'Serviços Académicos', 'Suporte Técnico'), return that name. If impossible to determine with reasonable certainty, return an empty string "".
4.  `rationale`: (string) A **short and objective** sentence justifying the choice of `recipient_category` (e.g., "Sender identified as 'Professor Jorge' in the relationship list", "Signature indicates 'Serviços Académicos'", "Tone and content suggest fellow student", "Insufficient information to categorize").

**IMPORTANTE:** A tua saída deve ser **APENAS** o objeto JSON, sem qualquer texto adicional antes ou depois (sem ```json ... ```, apenas o JSON puro). Exemplo de saída válida: (IMPORTANT: Your output must be **ONLY** the JSON object, without any additional text before or after (no ```json ... ```, just the raw JSON). Valid output example:)
{{
  "recipient_category": "colega_projeto_academico",
  "incoming_tone": "Semi-Formal",
  "sender_name_guess": "Ana Silva",
  "rationale": "Conteúdo do email refere 'dúvidas sobre o projeto' e assinatura inclui número de aluno."
}}ss

JSON Result:
"""
    return prompt

def analyze_sender_and_context(original_email, persona):
    """
    Calls the LLM to perform Context Pre-Analysis (Prompt 0)
    and returns the parsed JSON results, including 'rationale'.

    Args:
        original_email (str): The content of the received email.
        persona (dict): The dictionary of the persona who will respond.

    Returns:
        dict: A dictionary containing 'recipient_category', 'incoming_tone',
              'sender_name_guess', 'rationale', and 'error' (None on success,
              or error message if analysis fails).
              In case of parsing error, returns default values and the error message.
    """
    logging.info(f"Starting Context Pre-Analysis for email and persona {persona.get('name', 'N/A')}")
    if not persona: # Basic validation
        logging.error("Pre-Analysis failed: Invalid Persona.")
        return {
            "recipient_category": "unknown",
            "incoming_tone": "Neutro",
            "sender_name_guess": "",
            "rationale": "",
            "error": "Invalid persona provided for context analysis."
        }

    # Build the specific prompt for this analysis
    analysis_prompt = build_prompt_0_context_analysis(original_email, persona)
    # Log prompt in debug mode
    app.logger.debug(f"Prompt Pre-Analysis (Context):\n{analysis_prompt}")

    # Call LLM with low temperature for more deterministic analysis
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.2)

    # Check for API call errors
    if "error" in llm_response_data:
        logging.error(f"Error in Gemini call for Pre-Analysis: {llm_response_data['error']}")
        # Return API error, keeping defaults for other keys
        return {
            "recipient_category": "unknown",
            "incoming_tone": "Neutro",
            "sender_name_guess": "",
            "rationale": "", # Return empty rationale on API error
            "error": f"Failed communication with LLM for pre-analysis: {llm_response_data['error']}"
        }

    llm_response_text = llm_response_data.get("text", "")
    logging.info("Pre-Analysis received from Gemini, parsing JSON.")
    app.logger.debug(f"Raw Pre-Analysis LLM Response: {llm_response_text}")

    # Try to parse the JSON response
    try:
        # Regex to find JSON (robust to ```json ... ``` or direct JSON)
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```|({[\s\S]+})", llm_response_text)
        if not json_match:
            logging.warning("Pre-analysis JSON not found with regex, trying direct parse.")
            json_str = llm_response_text
            # Basic validation if it looks like JSON before direct parse
            if not json_str.strip().startswith("{") or not json_str.strip().endswith("}"):
                 raise json.JSONDecodeError("Response does not appear to be valid JSON.", llm_response_text, 0)
        else:
            # Get the matched group (either the first or second)
            json_str = json_match.group(1) or json_match.group(2)

        # Parse the JSON string
        parsed_json = json.loads(json_str)

        # Validate expected JSON structure (including 'rationale')
        required_keys = ["recipient_category", "incoming_tone", "sender_name_guess", "rationale"]
        missing_keys = [key for key in required_keys if key not in parsed_json]

        if missing_keys:
            # If only rationale is missing, log warning but continue
            if missing_keys == ["rationale"]:
                 logging.warning("Pre-Analysis JSON received without 'rationale' key. Continuing with empty rationale.")
                 parsed_json["rationale"] = "" # Add empty rationale for consistency
            else:
                 # If other mandatory keys are missing, raise error
                 raise ValueError(f"Invalid Pre-Analysis JSON. Missing mandatory keys: {missing_keys}")

        # Validate data types (more robust with .get())
        if not isinstance(parsed_json.get("recipient_category"), str):
            logging.warning(f"Unexpected type for 'recipient_category' (received: {type(parsed_json.get('recipient_category'))}). Using 'unknown'.")
            parsed_json["recipient_category"] = "unknown"
        if not isinstance(parsed_json.get("incoming_tone"), str):
             logging.warning(f"Unexpected type for 'incoming_tone' (received: {type(parsed_json.get('incoming_tone'))}). Using 'Neutro'.")
             parsed_json["incoming_tone"] = "Neutro"
        if not isinstance(parsed_json.get("sender_name_guess"), str):
             logging.warning(f"Unexpected type for 'sender_name_guess' (received: {type(parsed_json.get('sender_name_guess'))}). Using empty string.")
             parsed_json["sender_name_guess"] = ""
        if not isinstance(parsed_json.get("rationale"), str):
             # Tolerate if rationale is not string (e.g., null), but log warning and convert
             logging.warning(f"Unexpected type for 'rationale' (received: {type(parsed_json.get('rationale'))}). Converting to string.")
             parsed_json["rationale"] = str(parsed_json.get("rationale", ""))


        logging.info("Pre-Analysis JSON parsed successfully.")
        app.logger.debug(f"Pre-Analysis Result: {parsed_json}")

        # Return parsed JSON with 'error: None' to indicate success
        # Ensure all expected keys exist in the return, using .get() with defaults
        return {
            "recipient_category": parsed_json.get("recipient_category", "unknown"),
            "incoming_tone": parsed_json.get("incoming_tone", "Neutro"),
            "sender_name_guess": parsed_json.get("sender_name_guess", ""),
            "rationale": parsed_json.get("rationale", ""), # Return rationale
            "error": None
        }

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        # Error during JSON parsing or validation
        error_msg = f"Failed to parse or validate Pre-Analysis JSON: {e}. LLM Response (start): {llm_response_text[:200]}..."
        logging.error(error_msg)
        logging.exception("Details of Pre-Analysis parsing error:") # Log stack trace
        # Fallback: Return defaults but include the error message.
        return {
            "recipient_category": "unknown",
            "incoming_tone": "Neutro",
            "sender_name_guess": "",
            "rationale": "", # Empty rationale in fallback
            "error": f"ERROR_PARSE_CONTEXT: {error_msg}"
        }
    except Exception as e:
        # Catch any other unexpected error
        error_msg = f"Unexpected error processing Pre-Analysis: {e}"
        logging.exception("Unexpected error in analyze_sender_and_context:")
        return {
            "recipient_category": "unknown",
            "incoming_tone": "Neutro",
            "sender_name_guess": "",
            "rationale": "", # Empty rationale in fallback
            "error": f"ERROR_UNEXPECTED_CONTEXT: {error_msg}"
        }

def build_prompt_2_drafting(persona, original_email, user_inputs, context_analysis):
    """
    Generates a highly enhanced prompt for drafting the email response (Prompt 2),
    prioritizing direct instructions, dynamic adaptation, and comprehensive rule application.

    Args:
        persona (dict): The selected persona dictionary.
        original_email (str): The content of the received email.
        user_inputs (list): List of dictionaries with 'point' and 'guidance' from the user.
        context_analysis (dict): The result of the analyze_sender_and_context function.

    Returns:
        str: The formatted prompt for the LLM to generate the draft response.
    """
    persona_name = persona['name']
    persona_role = persona.get('role', 'Assistant')
    persona_desc = persona.get('description', 'Standard style')
    base_tone = persona.get('attributes', {}).get('base_tone', 'Neutro')
    base_formality = persona.get('attributes', {}).get('base_formality', 'Media')
    lang_instruction = f"Respond EXCLUSIVELY in {persona.get('attributes', {}).get('language', 'pt-PT')} naturally."
    general_dos = persona.get('dos_generais', [])
    general_donts = persona.get('donts_generais', [])
    sender_name = context_analysis.get('sender_name_guess', 'Recipient')
    recipient_category = context_analysis.get('recipient_category', 'unknown')
    rule_key_to_use = context_analysis.get('rule_key_to_use', 'unknown_formal_default')
    incoming_tone = context_analysis.get('incoming_tone', 'Neutro')
    rationale = context_analysis.get('rationale', 'N/A')  # Include rationale
    greeting_rule = "Caro(a) [Nome],"  # Fallback
    final_farewell = f"Com os melhores cumprimentos,\n{persona.get('name', '')}"  # Fallback

    # --- Determine Greeting / Farewell and Specific Rules ---
    rules = persona.get("recipient_adaptation_rules", {})
    relationships = persona.get("relationships_specifics", {})

    if recipient_category in relationships:
        relationship_data = relationships[recipient_category]
        rule_key_from_relationship = relationship_data.get("default_recipient_category_key")
        if rule_key_from_relationship and rule_key_from_relationship in rules:
            rule_key_to_use = rule_key_from_relationship
            specific_rules_data = rules[rule_key_to_use]
            greeting_rule = relationship_data.get("override_greeting", specific_rules_data.get("greeting", greeting_rule))
            final_farewell = relationship_data.get("override_farewell", specific_rules_data.get("farewell", final_farewell))
            base_tone = relationship_data.get("override_tone", specific_rules_data.get("adapted_tone", base_tone))
            specific_dos = specific_rules_data.get("dos_especificos", []) + relationship_data.get("specific_notes_for_ia",
                                                                                                [])
            specific_donts = specific_rules_data.get("donts_especificos", [])
        else:
            logging.warning(
                f"Relationship '{recipient_category}' points to invalid rule key '{rule_key_from_relationship}'. Using fallback '{rule_key_to_use}'.")
            specific_rules_data = rules.get(rule_key_to_use, {})
            greeting_rule = relationship_data.get("override_greeting", specific_rules_data.get("greeting", greeting_rule))
            final_farewell = relationship_data.get("override_farewell", specific_rules_data.get("farewell", final_farewell))
            base_tone = relationship_data.get("override_tone", specific_rules_data.get("adapted_tone", base_tone))
            specific_dos = specific_rules_data.get("dos_especificos", []) + relationship_data.get("specific_notes_for_ia",
                                                                                                [])
            specific_donts = specific_rules_data.get("donts_especificos", [])

    elif recipient_category in rules:
        rule_key_to_use = recipient_category
        specific_rules_data = rules[rule_key_to_use]
        greeting_rule = specific_rules_data.get("greeting", greeting_rule)
        final_farewell = specific_rules_data.get("farewell", final_farewell)
        base_tone = specific_rules_data.get("adapted_tone", base_tone)
        specific_dos = specific_rules_data.get("dos_especificos", [])
        specific_donts = specific_rules_data.get("donts_especificos", [])
    else:
        specific_rules_data = rules.get("unknown_formal_default", {})
        greeting_rule = specific_rules_data.get("greeting", greeting_rule)
        final_farewell = specific_rules_data.get("farewell", final_farewell)
        base_tone = specific_rules_data.get("adapted_tone", base_tone)
        specific_dos = specific_rules_data.get("dos_especificos", [])
        specific_donts = specific_rules_data.get("donts_especificos", [])
        if recipient_category != "unknown":
            logging.warning(
                f"Category '{recipient_category}' not found in relationships or rules, using fallback 'unknown_formal_default'.")

    # --- Build Greeting Instruction for LLM ---
    greeting_instruction_base = greeting_rule
    name_placeholders = {
        "[NomeColega]": sender_name,
        "[NomeAluno]": sender_name,
        "[ApelidoContactoSeConhecido]": sender_name,
        "[Apelido]": sender_name,
        "[Nome]": sender_name,
    }
    for placeholder, value in name_placeholders.items():
        greeting_instruction_base = greeting_instruction_base.replace(placeholder, value)

    gender_patterns = ["(a)", "(as)", "(os)", "(o/a)"]
    needs_gender_resolution = any(pattern in greeting_instruction_base for pattern in gender_patterns)

    if needs_gender_resolution:
        cleaned_greeting_base = greeting_instruction_base
        for pattern in gender_patterns:
            cleaned_greeting_base = cleaned_greeting_base.replace(pattern, "")
        cleaned_greeting_base = re.sub(r'\s+', ' ', cleaned_greeting_base).strip()
        greeting_instruction_for_llm = f"Start with the greeting: '{cleaned_greeting_base}'. Use '{sender_name}' and choose the correct gender form (e.g., Caro/Cara) based on the name. If the gender is ambiguous, use the masculine form or a neutral greeting."
    else:
        greeting_instruction_for_llm = f"Start with the greeting: '{greeting_instruction_base}'."

    # --- Placeholder substitution in FAREWELL ---
    persona_student_id = persona.get("student_id", "SEU_NUMERO_ALUNO")
    persona_contact = persona.get("contact_info", "SEU_EMAIL | SEU_TELEFONE")
    final_farewell = final_farewell.replace("SEU_NUMERO_ALUNO", persona_student_id)
    final_farewell = final_farewell.replace("SEU_EMAIL | SEU_TELEFONE", persona_contact)
    persona_signature_name = persona.get("name", "")
    if persona_signature_name and "\n" in final_farewell:
        current_sig_name = final_farewell.split("\n")[-1]
        is_informal_farewell = any(kw in rule_key_to_use.lower() for kw in ["colega", "casual"])
        if persona_signature_name != current_sig_name and len(
                persona_signature_name) > len(current_sig_name) and not is_informal_farewell:
            final_farewell = final_farewell.replace(f"\n{current_sig_name}", f"\n{persona_signature_name}")

    # --- Construct the final prompt ---
    prompt = f"""
### SYSTEM ###
You are {persona_name}, a {persona_role}. Your style is {persona_desc}. {lang_instruction}

### CONTEXT ###
Sender: {sender_name}. Recipient Category: {recipient_category} (Rule: {rule_key_to_use}). Rationale: {rationale}. Incoming Tone: {incoming_tone}.
Adapt tone/formality: Blend '{base_tone}' (your style) and '{incoming_tone}'.

### GREETING ###
{greeting_instruction_for_llm}

### RESPONSE ###
Write a cohesive response, integrating these points:
{chr(10).join([f'  - {i+1}: "{item.get('point', 'N/A')}" -> {item.get('guidance', '(Respond appropriately)')}' for i, item in enumerate(user_inputs) if item.get('point') != 'N/A' and item.get('point') is not None and not item.get('point').lower().strip().startswith("nenhum ponto")]) if any(item.get('point') != 'N/A' and item.get('point') is not None and not item.get('point').lower().strip().startswith("nenhum ponto") for item in user_inputs) else "Write a short, appropriate response to the original email."}

### RULES ###
Apply these rules (specific override general):
General Do's: {', '.join(general_dos) or 'None'}.
General Don'ts: {', '.join(general_donts) or 'None'}.
Specific Do's: {', '.join(specific_dos) or 'None'}.
Specific Don'ts: {', '.join(specific_donts) or 'None'}.

### SELF-CORRECTION ###
Review your draft for clarity, tone, persona adherence, and completeness.

### FAREWELL ###
End with:
{final_farewell}
"""
    return prompt


def build_prompt_3_suggestion(original_email, point_to_address, persona, direction=None):
    """
    Builds the prompt to request a RESPONSE TEXT SUGGESTION (Prompt 3)
    for a specific point, following the persona and optionally a direction (Yes/No).
    (Adapted to use the correct keys from personas.json)

    Args:
        original_email (str): The original email content (for context).
        point_to_address (str): The specific point extracted from analysis (Prompt 1).
        persona (dict): The selected persona dictionary.
        direction (str, optional): The direction indicated by the user ("sim", "nao", or None).

    Returns:
        str: The formatted prompt for the LLM to generate the suggestion.
    """
    # Determine language instruction
    persona_lang = persona.get("attributes", {}).get("language", "pt-PT")
    lang_instruction = f"Write **exclusively** in **{persona_lang}** and sound natural."

    # Build additional instruction based on provided direction
    direction_instruction = ""
    if direction == "sim":
        direction_instruction = "\n**Important Additional Instruction:** The user indicated the response to this point should be **AFFIRMATIVE / POSITIVE ('Yes')**. Base your suggestion on this direction, maintaining the persona."
    elif direction == "nao":
        direction_instruction = "\n**Important Additional Instruction:** The user indicated the response to this point should be **NEGATIVE ('No')**. Base your suggestion on this direction, maintaining the persona."
    # If direction is "outro" or None/empty, no specific instruction is added.

    # Build the full prompt
    # Use 'base_tone', 'base_formality', etc., and 'dos_generais'/'donts_generais'
    system_prompt = f"""System: Your task is to generate a SHORT suggestion (ideally 1-2 concise sentences) of response text for a specific point in an email. You must act EXACTLY like {persona['name']}, adopting the following Persona:
* **Name:** {persona['name']} ({persona.get('role', '')})
* **General Tone:** {persona.get('attributes', {}).get('base_tone', 'Neutro')} (Adapt to context if needed)
* **Formality:** {persona.get('attributes', {}).get('base_formality', 'Média')} (Adapt to context if needed)
* **Verbosity:** {persona.get('attributes', {}).get('base_verbosity', 'Média')} (Apply to suggestion - be concise!)
* **Emoji Usage:** {persona.get('attributes', {}).get('emoji_usage', 'Nenhum')}

**MANDATORY Language Rule: {lang_instruction}**

**"Do's" (applicable to suggestion):**
{chr(10).join([f'* {rule}' for rule in persona.get('dos_generais', ['Be clear.'])])}

**"Don'ts" (applicable to suggestion):**
{chr(10).join([f'* {rule}' for rule in persona.get('donts_generais', ['Be vague.'])])}

**MANDATORY Output Format:**
* Generate ONLY the suggested response text for the specific point.
* DO NOT include greetings, farewells, or explanations like "To answer that, you could say:".
* Focus on creating a sentence or two that {persona['name']} could use directly or adapt to address/respond to the provided point.{direction_instruction} # <<< DIRECTION INSTRUCTION INJECTED HERE

--- END SYSTEM INSTRUCTIONS ---

Context: Original Received Email (for context reference only)
---
{original_email[:1000]} ... (email truncated for context)
---

Specific Point from Original Email to Address: "{point_to_address}"

Task: Now write the text suggestion that {persona['name']} could use in their response to address ONLY this specific point, following ALL rules and the additional instruction (if any) above. Be concise and to the point.

Sugestão de Texto de Resposta para este Ponto: (Suggested Response Text for this Point)
"""
    return system_prompt

def build_prompt_4_refinement(persona, selected_text, full_context, action):
    """
    Builds the prompt to request a specific REFINEMENT (Prompt 4)
    on a selected part of the draft text, maintaining the persona.
    (Adapted to use the correct keys from personas.json)

    Args:
        persona (dict): The selected persona dictionary.
        selected_text (str): The text snippet selected by the user.
        full_context (str): The complete text of the current draft (for context).
        action (str): The key of the refinement action to perform (e.g., "make_formal").

    Returns:
        str: The formatted prompt for the LLM to perform the refinement.
    """
    # Basic Persona info for consistency
    persona_lang = persona.get("attributes", {}).get("language", "pt-PT")
    lang_instruction = f"Use exclusively {persona_lang}."
    persona_info = f"System: Act as {persona['name']} ({persona.get('role', 'Assistant')}). Maintain the persona's general style and tone (Base Tone: {persona.get('attributes', {}).get('base_tone', 'Neutro')}, Language: {lang_instruction})."

    # Descriptions of actions for the LLM to understand the task (kept the same)
    action_instructions = {
        "make_formal": "Rewrite the 'Selected Text' below to be significantly more formal, suitable for the 'Full Context'. Use formal language and address.",
        "make_casual": "Rewrite the 'Selected Text' below to be more casual and direct, suitable for the 'Full Context'. Use informal language appropriate for the persona, if applicable.",
        "shorten": "Significantly shorten the 'Selected Text' below, preserving its core meaning. Make it concise and to the point, fitting the 'Full Context'. Remove redundancies.",
        "expand": "Elaborate on the 'Selected Text' below, adding relevant details or explanations, maintaining the topic and fitting the 'Full Context'. Maintain the persona's style.",
        "simplify": "Simplify the language and sentence structure of the 'Selected Text' below, making it easier to understand, but maintaining the meaning and fitting the 'Full Context'.",
        "improve_flow": "Rewrite the 'Selected Text' below to improve its flow and connection with the 'Full Context'. Adjust wording and add transitions if necessary.",
        "rephrase": "Rewrite the 'Selected Text' below, expressing the same core idea differently, fitting the 'Full Context'.",
        "translate_en": "Accurately translate the 'Selected Text' below into natural-sounding English, considering the 'Full Context'."
    }

    # Get the specific instruction or a generic one if action not recognized
    instruction = action_instructions.get(action, f"Modify the 'Selected Text' as requested ({action}), ensuring it fits the 'Full Context'.")

    # Build the final prompt (kept the same)
    prompt = f"""{persona_info}

Your task is to refine a specific part of an email draft, as instructed.

**Action Required:** {instruction}

**Full Context (Current Draft):**
---
{full_context}
---

**Selected Text (The part to modify):**
---
{selected_text}
---

**MANDATORY Output Rules:**
1.  Modify ONLY the 'Selected Text' according to the 'Action Required'.
2.  MAINTAIN the style and voice of the persona {persona['name']} in your response.
3.  ENSURE the modified text fits naturally into the 'Full Context'.
4.  **RETURN ONLY THE MODIFIED TEXT.** Do not include the full context, explanations, markers like "Modified Text:", or ```. Just the resulting text segment from the modification.

Texto Modificado: (Modified Text)
"""
    # Log refinement prompt in debug mode
    if DEBUG_MODE:
        logging.debug(f"--- DEBUG: PROMPT 4 (Refinement) Action: {action} Persona: {persona['name']} ---")
        log_limit = 1500 # Limit to avoid overwhelming logs
        logging.debug(f"Selected Text (len {len(selected_text)}): {selected_text[:log_limit//3]}...")
        logging.debug(f"Full Context (len {len(full_context)}): {full_context[:log_limit//2]}...")
        logging.debug(f"Generated Prompt (len {len(prompt)}): {prompt[:log_limit]}...")
        logging.debug("--- END DEBUG PROMPT 4 ---")

    return prompt


# --- Flask Application Routes ---

@app.route('/')
def index_route():
    """Renders the initial HTML page."""
    global PERSONAS # Use the global variable
    logging.info("Serving the initial page (index.html)")

    # Reload personas if the file might have been modified (useful in debug/dev)
    # In production, reloading on every request might be unnecessary.
    # However, it's crucial to see saved feedback reflected on the next page load.
    # Consider a more efficient strategy (e.g., cache with TTL) if loading is heavy.
    if DEBUG_MODE: # Reload only in debug mode to test feedback more easily
         PERSONAS = load_personas()

    if not PERSONAS:
         logging.warning("Rendering index.html but PERSONAS were not loaded or are empty.")
         # Pass an error indicator to the template
         return render_template('index.html', personas_dict={}, error_loading_personas=True)

    # Pass a simplified dictionary (only persona keys and their names) to the template
    # Filter out metadata_schema if it exists
    personas_display = {key: {"name": data.get("name", key)}
                        for key, data in PERSONAS.items() if key != "metadata_schema"}

    # Added: Logic to extract error_loading_personas
    # load_personas now returns {} on error, so check if PERSONAS is empty.
    error_loading = not bool(PERSONAS) # True if PERSONAS is empty {}

    return render_template('index.html', personas_dict=personas_display, error_loading_personas=error_loading)


@app.route('/analyze', methods=['POST'])
def analyze_email_route():
    """Endpoint to analyze the received email using Gemini (Prompt 1)."""
    # (Kept same as original version)
    if not request.json or 'email_text' not in request.json:
        logging.warning("Invalid /analyze request: Missing 'email_text'.")
        return jsonify({"error": "Invalid request. Missing 'email_text'."}), 400

    email_text = request.json['email_text']
    if not email_text.strip():
        logging.warning("Invalid /analyze request: 'email_text' is empty.")
        return jsonify({"error": "Email text cannot be empty."}), 400

    logging.info("Starting Email Analysis (Prompt 1 via Gemini)")
    # Build analysis prompt
    analysis_prompt = build_prompt_1_analysis(email_text)

    # Call LLM with lower temperature for focused analysis
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.5)

    # Log raw response for debugging
    logging.debug(f"DEBUG - Raw Analysis LLM Response: --------\n{llm_response_data}\n--------")

    # Check for API call errors
    if "error" in llm_response_data:
        # Determine appropriate HTTP status code
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Error in Gemini call for /analyze: {llm_response_data['error']}")
        return jsonify({"error": f"Failed to communicate with LLM for analysis: {llm_response_data['error']}"}), status_code

    # Parse the LLM's textual response
    llm_response_text = llm_response_data.get("text", "")
    logging.info("Analysis received from Gemini, parsing.")
    analysis_result = parse_analysis_output(llm_response_text)
    app.logger.debug(f"Parsed Result (Analysis): {analysis_result}")

    # Check if parsing returned an error
    if "error" in analysis_result:
        logging.error(f"Error parsing analysis: {analysis_result['error']}")
        # Return parsing error and raw response for debug
        return jsonify({"error": f"Failed to process analysis response: {analysis_result['error']}", "raw_analysis": llm_response_text}), 500

    # Additional consistency check (optional)
    if not analysis_result.get("points") and "nenhum ponto a responder" not in llm_response_text.lower():
        logging.warning("Parsing might have failed. LLM response did not contain 'nenhum ponto', but points list is empty.")

    logging.info("Analysis processed successfully.")
    # Return extracted points and actions
    return jsonify(analysis_result)


@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route():
    """Endpoint to generate text suggestion for a specific point (Prompt 3)."""
    # (Adapted to use the global PERSONAS variable)
    global PERSONAS
    required_fields = ['original_email', 'point_to_address', 'persona_name']
    if not request.json:
        logging.warning("Invalid /suggest_guidance request: No JSON.")
        return jsonify({"error": "Invalid request (JSON expected)."}), 400
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Invalid /suggest_guidance request: Missing data: {missing}")
        return jsonify({"error": f"Missing data in request: {', '.join(missing)}."}), 400

    original_email = request.json['original_email']
    point_to_address = request.json['point_to_address']
    persona_name = request.json['persona_name']
    direction = request.json.get('direction')

    if not original_email.strip() or not point_to_address or point_to_address == 'N/A' or not persona_name.strip():
        logging.warning("Invalid /suggest_guidance request: Required fields empty or invalid.")
        return jsonify({"error": "Original email, a valid point to address, and persona name are required."}), 400

    # Use the global PERSONAS variable
    if not PERSONAS:
        logging.error("Critical error: PERSONAS not loaded, cannot process /suggest_guidance.")
        return jsonify({"error": "Server internal error: Persona definitions unavailable."}), 500
    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' not found in /suggest_guidance.")
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400

    selected_persona = PERSONAS[persona_name]
    logging.info(f"Requesting TEXT suggestion via Gemini for point='{point_to_address[:50]}...' with Persona: {persona_name}, Direction: {direction}")

    # Build suggestion prompt
    suggestion_prompt = build_prompt_3_suggestion(original_email, point_to_address, selected_persona, direction)

    # Call LLM
    llm_response_data = call_gemini(suggestion_prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE)

    # Check for API errors
    if "error" in llm_response_data:
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Error in Gemini call for /suggest_guidance: {llm_response_data['error']}")
        return jsonify({"error": f"Failed to get suggestion from LLM: {llm_response_data['error']}"}), status_code

    # Extract and clean suggestion text
    llm_response_text = llm_response_data.get("text", "").strip()
    logging.info("Text suggestion generated successfully.")
    app.logger.debug(f"Suggestion generated: {llm_response_text}")
    # Return suggestion
    return jsonify({"suggestion": llm_response_text})


@app.route('/draft', methods=['POST'])
def draft_response_route():
    """
    Endpoint to generate the final draft response (Prompt 2),
    including context pre-analysis (Prompt 0).
    (Adapted to use the global PERSONAS variable)
    """
    global PERSONAS
    if not request.json:
        logging.warning("Invalid /draft request: No JSON.")
        return jsonify({"error": "Invalid request (JSON expected)."}), 400

    required_fields = ['original_email', 'persona_name', 'user_inputs']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Invalid /draft request: Missing data: {missing}")
        return jsonify({"error": f"Missing data in request: {', '.join(missing)}."}), 400

    original_email = request.json['original_email']
    persona_name = request.json['persona_name']
    user_inputs = request.json['user_inputs']

    # Use the global PERSONAS variable
    if not PERSONAS:
         logging.error("Critical error: PERSONAS not loaded, cannot process /draft.")
         return jsonify({"error": "Server internal error: Persona definitions unavailable."}), 500
    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' not found in /draft.")
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400
    if not isinstance(user_inputs, list):
        logging.error(f"Invalid format for 'user_inputs' in /draft. Expected list, received: {type(user_inputs)}")
        return jsonify({"error": "Invalid format for 'user_inputs'. Expected a list of objects."}), 400

    selected_persona = PERSONAS[persona_name]

    # --- STEP 1: Context Pre-Analysis ---
    logging.info(f"Starting Context Pre-Analysis for /draft (Persona: {persona_name})")
    context_analysis_result = analyze_sender_and_context(original_email, selected_persona)

    # Check for critical errors from pre-analysis (e.g., API error)
    # Parsing errors return defaults and an error msg, but don't block.
    if context_analysis_result.get("error") and \
       "ERROR_PARSE_CONTEXT" not in context_analysis_result["error"] and \
       "ERROR_UNEXPECTED_CONTEXT" not in context_analysis_result["error"]:
        logging.error(f"Critical error during Context Pre-Analysis: {context_analysis_result['error']}")
        status_code = 500
        error_msg_prefix = "Failed context pre-analysis:"
        if "ERROR_GEMINI" in context_analysis_result["error"] or "ERROR_CONFIG" in context_analysis_result["error"]:
            status_code = 503 # Default for Gemini errors (can be adjusted)
            if "BLOCKED" in context_analysis_result["error"]: status_code = 400
            error_msg_prefix = "LLM communication error during pre-analysis:"
        # Return the error that prevented continuation
        return jsonify({"error": f"{error_msg_prefix} {context_analysis_result['error']}"}), status_code
    elif context_analysis_result.get("error"):
        # Log non-critical error (parsing/unexpected), but continue with defaults
        logging.warning(f"Non-critical error during Pre-Analysis: {context_analysis_result['error']}. Continuing with defaults.")

    # --- STEP 2: Draft Generation (Prompt 2) ---
    logging.info(f"Starting Draft Generation (Prompt 2 via Gemini) for Persona: {persona_name}")
    # Build Prompt 2, passing the pre-analysis result
    draft_prompt = build_prompt_2_drafting(selected_persona, original_email, user_inputs, context_analysis_result)

    # Call LLM to generate draft
    llm_response_data = call_gemini(draft_prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE)

    # Check for errors in draft generation
    if "error" in llm_response_data:
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Error in Gemini call for /draft (Generation): {llm_response_data['error']}")
        # Return generation error and the context analysis used (for debug)
        return jsonify({
            "error": f"Failed to generate draft with LLM: {llm_response_data['error']}",
            "context_analysis": context_analysis_result # Include analysis for debug
            }), status_code

    # Extract final draft
    final_draft = llm_response_data.get("text", "").strip()
    logging.info(f"Final Draft Generated successfully via Gemini for persona {persona_name}.")
    # Log context analysis used and final draft in debug mode
    app.logger.debug(f"Context Analysis Used: {context_analysis_result}")
    app.logger.debug(f"Final Draft:\n{final_draft}")

    # Return draft and also the context analysis used (might be useful on frontend)
    return jsonify({
        "draft": final_draft,
        "context_analysis": context_analysis_result
        })


@app.route('/refine_text', methods=['POST'])
def refine_text_route():
    """Endpoint to refine a selected snippet of the draft (Prompt 4)."""
    # (Adapted to use the global PERSONAS variable)
    global PERSONAS
    if not request.json:
        logging.warning("Invalid /refine_text request: No JSON.")
        return jsonify({"error": "Invalid request (JSON expected)."}), 400

    required_fields = ['selected_text', 'full_context', 'action', 'persona_name']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Invalid /refine_text request: Missing data: {missing}")
        return jsonify({"error": f"Missing data in request: {', '.join(missing)}."}), 400

    selected_text = request.json['selected_text']
    full_context = request.json['full_context']
    action = request.json['action']
    persona_name = request.json['persona_name']

    if not selected_text: # Don't refine empty text
        return jsonify({"error": "No text selected to refine."}), 400
    # Use the global PERSONAS variable
    if not PERSONAS:
        logging.error("Critical error: PERSONAS not loaded, cannot process /refine_text.")
        return jsonify({"error": "Server internal error: Persona definitions unavailable."}), 500
    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' not found in /refine_text.")
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400

    selected_persona = PERSONAS[persona_name]
    logging.info(f"Requesting Refinement via Gemini. Action: '{action}', Persona: {persona_name}, Text (start): '{selected_text[:50]}...'")

    # Build refinement prompt (Prompt 4)
    refinement_prompt = build_prompt_4_refinement(selected_persona, selected_text, full_context, action)

    # Call LLM with lower temperature for focused edits
    llm_response_data = call_gemini(refinement_prompt, model=GEMINI_MODEL, temperature=REFINEMENT_TEMPERATURE)

    # Check for Gemini API errors
    if "error" in llm_response_data:
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Error in Gemini call for /refine_text: {llm_response_data['error']}")
        return jsonify({"error": f"Failed to refine text with LLM: {llm_response_data['error']}"}), status_code

    # Extract refined text
    refined_text = llm_response_data.get("text", "").strip() # .strip() is important here

    # Extra check: If LLM returns empty (can happen with extreme 'shorten' requests)
    if not refined_text and action == 'shorten':
        logging.warning(f"Refinement 'shorten' resulted in empty text for selection: '{selected_text[:100]}...'")
        # We could return an empty string or maybe the original? For now, returns empty.
        # To prevent text disappearing, uncomment the line below
        # refined_text = selected_text

    logging.info(f"Refinement '{action}' completed successfully. Refined text (start): '{refined_text[:100]}...'")
    app.logger.debug(f"Full Refined Text:\n{refined_text}")

    # Return refined text
    return jsonify({"refined_text": refined_text})


# --- NEW ROUTE: /submit_feedback ---
@app.route('/submit_feedback', methods=['POST'])
def submit_feedback_route():
    """
    Endpoint to receive user feedback and save it to personas.json.
    """
    global PERSONAS # To potentially reload or verify

    # 1. Validate Input
    if not request.json:
        logging.warning("Invalid /submit_feedback request: No JSON.")
        return jsonify({"error": "Invalid request (JSON expected)."}), 400

    required_fields = ['persona_name', 'ai_original_response', 'user_corrected_output', 'feedback_category', 'interaction_context']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Invalid /submit_feedback request: Missing data: {missing}")
        return jsonify({"error": f"Missing data in request: {', '.join(missing)}."}), 400

    persona_name = request.json['persona_name']
    ai_original_response = request.json['ai_original_response']
    user_corrected_output = request.json['user_corrected_output']
    feedback_category = request.json['feedback_category']
    user_explanation = request.json.get('user_explanation', '') # Optional
    interaction_context = request.json['interaction_context'] # Essential

    # Additional validation
    if not persona_name.strip():
         return jsonify({"error": "Persona name cannot be empty."}), 400
    if not user_corrected_output.strip(): # Correction is mandatory
         return jsonify({"error": "User's corrected version is mandatory."}), 400
    if not feedback_category.strip():
         return jsonify({"error": "Feedback category is mandatory."}), 400
    if not isinstance(interaction_context, dict): # Must be an object
        return jsonify({"error": "Interaction context is invalid or missing."}), 400

    logging.info(f"Received feedback for persona: {persona_name}. Category: {feedback_category}")

    # 2. Read, Modify, and Write the personas.json File
    try:
        # Use the lock to ensure read and write are atomic in multi-threaded environments
        with personas_file_lock:
            # Read the current JSON file
            try:
                # Re-load the data from file inside the lock to get the absolute latest state
                with open(PERSONAS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content:
                        logging.error(f"Error saving feedback: File '{PERSONAS_FILE}' is empty.")
                        return jsonify({"error": "Internal error: Personas configuration file is empty."}), 500
                    current_personas_data = json.loads(content)

            except FileNotFoundError:
                logging.error(f"Error saving feedback: File '{PERSONAS_FILE}' not found.")
                return jsonify({"error": "Internal error: Personas configuration file not found."}), 500
            except json.JSONDecodeError as e:
                logging.error(f"Error saving feedback: Invalid JSON in '{PERSONAS_FILE}': {e}")
                return jsonify({"error": f"Internal error: Personas configuration file corrupted. ({e})"}), 500

            # Check if the persona exists
            if persona_name not in current_personas_data:
                logging.error(f"Error saving feedback: Persona '{persona_name}' does not exist in the file.")
                return jsonify({"error": f"Persona '{persona_name}' not found in configuration."}), 404 # 404 Not Found

            persona_obj = current_personas_data[persona_name]

            # Ensure 'learned_knowledge_base' list exists
            if 'learned_knowledge_base' not in persona_obj:
                persona_obj['learned_knowledge_base'] = []
            # Check if it's a list (in case the file was manually edited incorrectly)
            elif not isinstance(persona_obj.get('learned_knowledge_base'), list):
                 logging.warning(f"'learned_knowledge_base' structure for '{persona_name}' was not a list. Replacing with empty list.")
                 persona_obj['learned_knowledge_base'] = []

            # Create the new feedback entry
            feedback_entry = {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "feedback_category": feedback_category,
                "ai_original_response": ai_original_response,
                "user_corrected_output": user_corrected_output,
                "user_explanation": user_explanation,
                "interaction_context": interaction_context, # Save the entire interaction context
                 # Could add more metadata here if needed (e.g., AI model version)
                "model_used" : interaction_context.get('llm_pre_analysis_snapshot', {}).get('model_used', GEMINI_MODEL) # Example
            }

            # Add the entry to the list
            # Ensure it's definitely a list before appending
            if isinstance(persona_obj['learned_knowledge_base'], list):
                persona_obj['learned_knowledge_base'].append(feedback_entry)
                logging.info(f"Feedback added to 'learned_knowledge_base' for persona '{persona_name}'.")
            else:
                # This case should be handled by the check above, but as a safeguard:
                logging.error(f"Could not append feedback, 'learned_knowledge_base' for '{persona_name}' is not a list.")
                return jsonify({"error": "Internal error: Invalid configuration structure for persona."}), 500


            # Write the ENTIRE modified dictionary back to the JSON file
            try:
                with open(PERSONAS_FILE, 'w', encoding='utf-8') as f:
                    # Use indent=2 for readable formatting, ensure_ascii=False for PT characters
                    json.dump(current_personas_data, f, ensure_ascii=False, indent=2)
                logging.info(f"File '{PERSONAS_FILE}' updated successfully with new feedback.")

                # Optional: Update the global PERSONAS variable in memory after successful write
                # This ensures subsequent requests WITHIN THE SAME PROCESS use the updated data
                # without needing a restart (useful if not using reloader)
                # global PERSONAS
                # PERSONAS = current_personas_data # Uncomment if needed

            except IOError as e:
                logging.error(f"I/O error trying to write to '{PERSONAS_FILE}': {e}")
                return jsonify({"error": f"Internal error: Failed to save updates to configuration file. ({e})"}), 500
            except Exception as e:
                logging.error(f"Unexpected error writing JSON to '{PERSONAS_FILE}': {e}\n{traceback.format_exc()}")
                return jsonify({"error": f"Unexpected internal error saving feedback. ({e})"}), 500

        # If everything went well inside the lock
        return jsonify({"message": "Feedback submitted and saved successfully!"})

    except Exception as e:
        # Catch errors that might occur outside the main read/write block
        logging.exception("Unexpected error in /submit_feedback route:")
        return jsonify({"error": f"Unexpected server error processing feedback: {e}"}), 500


# --- Application Entry Point ---
if __name__ == '__main__':
    # Initial logs when starting the application
    logging.info("--- Starting Flask App ---")
    logging.info(f"Host: {APP_HOST}")
    logging.info(f"Port: {APP_PORT}")
    logging.info(f"Debug Mode: {DEBUG_MODE}")
    logging.info(f"Gemini Model: {GEMINI_MODEL}")

    # Check and log API Key status (masked)
    if not GEMINI_API_KEY:
        logging.warning("Environment variable GEMINI_API_KEY not set!")
    else:
        # Show only the last 4 characters of the key
        logging.info(f"Gemini API Key: {'*' * (len(GEMINI_API_KEY) - 4)}{GEMINI_API_KEY[-4:]}")

    # Check and log initial persona loading status
    if not PERSONAS:
         logging.warning("PERSONAS were not loaded initially or the file is empty! Persona features might not work correctly.")
    else:
         # Exclude metadata_schema from count
         persona_count = len([k for k in PERSONAS if k != "metadata_schema"])
         logging.info(f"{persona_count} persona(s) loaded.")

    logging.info(f"Default Generation Temperature: {GENERATION_TEMPERATURE}")
    logging.info(f"Refinement Temperature: {REFINEMENT_TEMPERATURE}")
    logging.info(f"Personas file lock initialized.")


    # Start the Flask server
    # use_reloader=False is useful in debug to prevent code executing twice on startup
    # In real production, using a WSGI server like Gunicorn or uWSGI is recommended.
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)
