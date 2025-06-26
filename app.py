# -*- coding: utf-8 -*-
import os
# --- FIX FOR LOCAL DEVELOPMENT ---
# This line tells the OAuth library to allow HTTP for local testing.
# It MUST be set before other imports that might use oauthlib.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# ---------------------------------

import json
import re
import requests
import logging
import traceback # For detailed exception logging
import datetime # For feedback timestamps
import threading # For simple file locking
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
import base64 # To decode email body
from email.mime.text import MIMEText # NEW: Import MIMEText for composing emails

# Load environment variables from the .env file
load_dotenv()

# Configure basic logging for better tracking
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

# --- Application Configuration ---
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GENERATION_TEMPERATURE = float(os.environ.get('GENERATION_TEMPERATURE', 0.75))
REFINEMENT_TEMPERATURE = float(os.environ.get('REFINEMENT_TEMPERATURE', 0.4))
ANALYSIS_TEMPERATURE = 0.2

DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# --- Gemini Configuration ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash-latest')

# --- File Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONAS_FILE = os.path.join(BASE_DIR, 'personas2.0.json')
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, 'client_secret.json') # Path for Gmail OAuth

# Flask App Initialization
app = Flask(__name__)
# A secret key is required for Flask session management
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a-very-secret-key-for-sessions')

if DEBUG_MODE:
    app.logger.setLevel(logging.DEBUG)
else:
    app.logger.setLevel(logging.INFO)

# --- Gmail API Configuration ---
SCOPES = [
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose', # REQUIRED for sending emails
    'openid'
]


# Lock to protect concurrent access to the personas.json file
personas_file_lock = threading.Lock()

# --- Persona Data Loading ---
def load_persona_file():
    """Safely loads or reloads the content of the personas file."""
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

# Initial data load
PERSONA_DATA = load_persona_file()

# --- Gemini API Communication ---
def call_gemini(prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE):
    """Sends a prompt to the Gemini API and returns the response, with robust error handling."""
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
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
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


# --- Advanced Prompt Building Functions ---
def build_holistic_draft_prompt(original_email, user_guidance, active_persona_key, persona_data, context_analysis_result, summarized_knowledge=""):
    """(IMPROVED) Builds the holistic prompt with Chain of Thought, enriched by pre-analysis AND context memory."""
    knowledge_section = ""
    if summarized_knowledge:
        knowledge_section = f"""
### CONTEXT MEMORY (ACTIVE LEARNING) - HIGH PRIORITY ###
Analysis of past interactions with this sender generated the following guidelines. YOU MUST FOLLOW THESE SPECIFIC RULES for this person, overriding general rules if there is a conflict:
---
{summarized_knowledge}
---
"""
    system_prompt_text = f"""
# SYSTEM PROMPT: EXPERT ACADEMIC EMAIL ASSISTANT
## 1. YOUR IDENTITY AND CORE OBJECTIVE
You are an expert communication assistant, acting as an intelligent writing co-pilot to draft exceptional emails. Your goal is to generate a final email that is natural, coherent, and human, perfectly achieving the user's intent.
{knowledge_section}
## 2. NON-NEGOTIABLE RULES
Regardless of the persona guidelines or context memory, the following rules have MAXIMUM priority:
* **Professional Etiquette:** All emails MUST begin with an appropriate greeting to the recipient and end with a suitable closing and signature, unless the CONTEXT MEMORY specifies an EXACT closing.
* **Factual Accuracy:** The response must be factually correct. If the user asks to confirm a FUTURE ACTION (e.g., "I will sign the minutes"), your response must reflect that. NEVER state that an action has already been completed if that was not the instruction.
## 3. YOUR ADVANCED REASONING PROCESS
For each request, you must follow a rigorous process of **Chain of Thought and a final Quality Cycle**.
### PART 1: CHAIN OF THOUGHT (INTERNAL ANALYSIS)
1.  **Request and Context Analysis:**
    * **Pre-Processed Context Analysis:** READ the analysis already done on the sender and tone. Use this information as absolute truth to guide your response.
    * **User Intent:** What is the true goal behind the `USER REQUEST`?
    * **Received Email Analysis:** What is the tone, hierarchy, and central request?
2.  **Persona Synthesis:**
    * **Apply Context Memory:** The first and most important source of guidance is the `CONTEXT MEMORY`. Apply these rules rigorously.
    * **Identify Active Persona:** `ACTIVE PERSONA`.
    * **Load Archetype and Adaptation Rules:** Use the archetype as a base and the `generic_recipient_adaptation_rules` to refine, guided by the `Sender Category` from the context analysis. The `CONTEXT MEMORY` rules take precedence over these.
    * **Prioritize Acquired Knowledge (Raw):** Use the full `learned_knowledge_base` as a secondary source to extract nuances that the summarized memory might have missed.
3.  **Email Structure Planning:**
    * Greeting, Opening, Main Body, Closing, and Farewell.
### PART 2: GENERATION AND QUALITY CYCLE
1.  **Write the First Draft (Draft 1).**
2.  **Quality Check & Refinement:** Critically evaluate your Draft 1 against this mandatory checklist:
    * **✅ Context Memory:** Were the high-priority rules from the `CONTEXT MEMORY` 100% followed? (THE MOST IMPORTANT)
    * **✅ Non-Negotiable Rules:** Were the rules of etiquette and factual accuracy followed?
    * **✅ Intent Fulfillment:** Does it 100% achieve the user's goal?
    * **✅ Persona and Context Alignment:** Does the response genuinely sound like the persona and is it adapted to the `Received Email Tone`?
    * **✅ Clarity and Professionalism:** Is the language clear, professional, and human?
3.  **Write the Final Improved Version (Final Version):** Based on your check, rewrite the email to produce the final, polished version.
## 4. EXPECTED OUTPUT
Your final output must be **ONLY the full text of the "Final Version" email**. Do not show your chain of thought or intermediate drafts.
"""
    persona_data_json_string = json.dumps(persona_data, indent=2, ensure_ascii=False)
    final_prompt = f"""{system_prompt_text}
--- START OF DATA FOR THE TASK ---
### CONTEXT ANALYSIS (PRE-PROCESSED) ###
- Sender Category: {context_analysis_result.get('recipient_category', 'unknown')}
- Received Email Tone: {context_analysis_result.get('incoming_tone', 'unknown')}
- Sender's Name (guess): {context_analysis_result.get('sender_name_guess', 'not identified')}
- Analysis Rationale: {context_analysis_result.get('rationale', 'N/A')}
### USER REQUEST ###
{user_guidance}
### RECEIVED EMAIL ###
---
{original_email if original_email.strip() else "No received email provided. The response should be a new email."}
---
### ACTIVE PERSONA ###
{active_persona_key}
### PERSONA CONTEXT DATA (JSON) ###
```json
{persona_data_json_string}
```
--- END OF DATA FOR THE TASK ---
Now, execute your advanced reasoning process and generate the final email.
**Final Email:**
"""
    return final_prompt

def build_prompt_1_analysis(email_text):
    """(NEW) Builds the prompt for an Intent Analysis and User Decision Points."""
    return f"""System: You are an expert email analyst. Your task is to perform an **Intent Analysis** on the received email. Your goal is to identify the core request and, most importantly, determine the **key decision points** that require input ONLY from the user to proceed. Do not ask for information that could be inferred or is secondary. Focus on what the user MUST decide.
Task: Analyze the email below and respond ONLY with a valid JSON object. Do not add any text before or after the JSON. Use Portuguese (pt-PT) for the content.
The JSON object must have two keys:
1.  `core_request`: A string summarizing the sender's core request in one objective sentence.
2.  `points`: An array of strings. Each string is a concise, summarized question representing a crucial decision or piece of context that only the user can provide. If there are no specific decision points (e.g., a simple thank you email), provide a generic point about how to reply.
Example for a code review email:
{{
  "core_request": "O remetente pede uma revisão de um snippet de código Python que está a dar um erro.",
  "points": [
    "Confirmar a análise do snippet e definir uma expectativa de resposta (ex: 'Vou ver hoje', 'Estou ocupado agora')."
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
    """Builds the prompt for Pre-Analysis (Prompt 0): identify recipient type, tone, sender name, and rationale."""
    max_email_length = 3000
    truncated_email = original_email[:max_email_length]
    if len(original_email) > max_email_length:
        truncated_email += "\n... (email truncated)"
    persona_context = {
        "name": persona.get("label_pt", "N/A"),
        "role": persona.get("role_template", "N/A"),
        "language": persona.get("communication_attributes", {}).get("language", "pt-PT"),
        "recipient_types": list(generic_rules.keys())
    }
    prompt = f"""System: You are an expert in email context analysis. Given the Persona who will respond and the Received Email, carefully analyze the sender (From:), recipients (To:/Cc:), greeting, body, and signature to determine the most likely relationship, the email's tone, and the main sender's name. Respond **ONLY** in valid JSON format.
Persona Who Will Respond (Relevant Context):
```json
{json.dumps(persona_context, indent=2, ensure_ascii=False)}
```
Received Email:
---
{truncated_email}
---
Task: Analyze the received email and the persona context. Determine the most likely category of the MAIN sender and the tone of the received email. Return **ONLY** a JSON object with the following **MANDATORY** keys:
1.  `recipient_category`: (string) The **exact** key that best describes the sender. It must be ONE of the `recipient_types` provided (e.g., "student_to_professor_academic_inquiry"). If no option applies, return "unknown".
2.  `incoming_tone`: (string) The perceived tone of the **received email**. Choose ONE of the options: "Muito Formal", "Formal", "Semi-Formal", "Casual", "Urgente", "InformativoNeutro", "Outro".
3.  `sender_name_guess`: (string) The best guess of the main sender's name (e.g., "Marta Silva", "João Carlos"). **IMPORTANT: Omit titles like 'Prof.', 'Dr.', 'Eng.', etc.** If impossible to determine, return an empty string "".
4.  `rationale`: (string) A **short and objective** sentence justifying the choice of `recipient_category`.
**IMPORTANT:** Your output must be **ONLY** the JSON object, without any additional text before or after.
JSON Result:
"""
    return prompt

def build_prompt_3_suggestion(point_to_address, persona, direction):
    """(FIXED) Builds the prompt to suggest an exemplary "guideline" for a Decision Point."""
    persona_name = persona.get('label_pt', 'Assistant')
    direction_map = {
        'sim': 'AFFIRMATIVE / POSITIVE',
        'nao': 'NEGATIVE',
        'outro': 'NEUTRAL / DETAILED'
    }
    direction_text = direction_map.get(direction, 'NEUTRAL / DETAILED')
    return f"""System: Your task is to act as a helpful assistant and generate a single, concise **guidance instruction** for a user.
This instruction should be: Actionable, clear, in Portuguese (pt-PT), reflect a **{direction_text}** intention, and be brief (one sentence).
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
    """(COMPLETED) Builds the prompt to refine a part of the text."""
    persona_name = persona.get('label_pt', 'Assistant')
    persona_info = f"System: Act as a '{persona_name}' assistant. Maintain the persona's style, tone ({persona.get('base_style_profile', {}).get('tone_elements', [{}])[0].get('keywords_pt', [])}), and language (pt-PT)."
    action_instructions = {
        "make_formal": "Rewrite the 'Selected Text' to be significantly more formal and professional.",
        "make_casual": "Rewrite the 'Selected Text' to be more casual and direct.",
        "shorten": "Condense the 'Selected Text' to be as brief as possible, preserving its core meaning.",
        "expand": "Elaborate on the 'Selected Text', adding more detail or context.",
        "simplify": "Rewrite the 'Selected Text' using simpler language and shorter sentences.",
        "improve_flow": "Improve the flow and cohesion of the 'Selected Text' within the 'Full Draft'.",
        "rephrase": "Rephrase the 'Selected Text', expressing the same idea differently.",
        "translate_en": "Translate the 'Selected Text' accurately to professional English."
    }
    instruction = action_instructions.get(action, f"Modify the 'Selected Text' as requested ({action}).")
    return f"""{persona_info}
Task: You are an expert editor. Refine a portion of an email draft according to the specified action.
Action: {instruction}
Full Draft Context (for reference):
---
{full_context}
---
Selected Text to Modify:
---
{selected_text}
---
MANDATORY: Your response must be ONLY the modified text. Do not include explanations or any surrounding text.
Modified Text:
"""

def build_prompt_5_summarize_knowledge(relevant_feedback_entries, sender_name):
    """(NEW) Builds a prompt for the LLM to synthesize relevant knowledge about a contact."""
    formatted_entries = ""
    for i, entry in enumerate(relevant_feedback_entries):
        original = entry.get('ai_original_response_text', 'N/A')
        corrected = entry.get('user_corrected_output_text', 'N/A')
        explanation = entry.get('user_explanation_text_pt', 'N/A')
        formatted_entries += f"""
### Past Feedback Example {i+1} ###
- **User Explanation:** "{explanation}"
- **What the AI wrote:** "{original}"
- **What the user corrected to:** "{corrected}"
"""
    prompt = f"""System: You are a Knowledge Synthesizer. Your goal is to analyze past user feedback related to a specific person and extract a concise, actionable set of rules for an AI assistant to follow in the future.
**Task:**
Analyze the following feedback provided for communications with **{sender_name}**.
Based ONLY on the user's explanations and corrections, create a short, bulleted list of style rules or preferences.
Focus on the core lesson. **DO NOT** invent rules. Your output must be ONLY the bulleted list of rules.
---
**Feedback Data for {sender_name}:**
{formatted_entries}
---
**Synthesized Style Rules for {sender_name} (only the bulleted list):**
"""
    return prompt

# --- Analysis, Parsing, and Knowledge Functions ---
def _normalize_name(name):
    """(NEW HELPER) Normalizes a name for more robust matching."""
    if not name: return ""
    name = name.lower()
    titles = ['prof.', 'prof', 'dr.', 'dr', 'eng.', 'eng', 'dra.', 'dra']
    for title in titles: name = name.replace(title, '')
    name = re.sub(r'[^\w\s]', '', name)
    return name.strip()

def find_and_summarize_relevant_knowledge(persona_obj, current_context_analysis):
    """(REBUILT) Finds relevant feedback using multi-layered matching logic and synthesizes it."""
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
            context_snapshot = entry.get("interaction_context_snapshot", {})
            if not context_snapshot: continue
            snapshot_sender_name_raw = context_snapshot.get("llm_pre_analysis_snapshot", {}).get("sender_name_guess", "")
            explanation_text = entry.get("user_explanation_text_pt", "").lower()
            normalized_snapshot_name = _normalize_name(snapshot_sender_name_raw)
            is_match = False
            if normalized_snapshot_name and normalized_current_name == normalized_snapshot_name: is_match = True
            elif not is_match and normalized_snapshot_name and (normalized_snapshot_name in normalized_current_name or normalized_current_name in normalized_snapshot_name): is_match = True
            elif not is_match and normalized_current_name in explanation_text: is_match = True
            if is_match and entry not in relevant_feedback:
                relevant_feedback.append(entry)
        except Exception as e:
            logging.warning(f"Skipping a malformed feedback entry during knowledge search: {e}")
            continue
    if not relevant_feedback:
        logging.info(f"NO MATCHES FOUND for sender: '{current_sender_name_raw}'")
        return ""
    logging.info(f"Found {len(relevant_feedback)} relevant feedback entries. Synthesizing knowledge...")
    synthesis_prompt = build_prompt_5_summarize_knowledge(relevant_feedback, current_sender_name_raw)
    llm_response = call_gemini(synthesis_prompt, temperature=0.1)
    if "error" in llm_response or not llm_response.get("text"):
        logging.error(f"Failed to synthesize knowledge. Error: {llm_response.get('error', 'Empty response')}")
        return ""
    summarized_knowledge = llm_response.get("text", "").strip()
    logging.info(f"Summarized knowledge for '{current_sender_name_raw}': {summarized_knowledge}")
    return summarized_knowledge

def analyze_sender_and_context(original_email, persona, generic_rules):
    """Calls the LLM to perform Context Pre-Analysis and returns the parsed JSON results."""
    logging.info(f"Starting Context Pre-Analysis for persona {persona.get('label_pt', 'N/A')}")
    if not persona: return {"error": "Invalid persona for context analysis."}
    analysis_prompt = build_prompt_0_context_analysis(original_email, persona, generic_rules)
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.2)
    if "error" in llm_response_data:
        return {"error": f"LLM communication failed: {llm_response_data['error']}"}
    llm_response_text = llm_response_data.get("text", "")
    try:
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```|({[\s\S]+})", llm_response_text)
        json_str = json_match.group(1) or json_match.group(2) if json_match else llm_response_text
        parsed_json = json.loads(json_str)
        if any(key not in parsed_json for key in ["recipient_category", "incoming_tone", "sender_name_guess", "rationale"]):
            raise ValueError("Invalid JSON from Pre-Analysis. Missing keys.")
        return parsed_json
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        error_msg = f"Failed to parse Pre-Analysis JSON: {e}. Raw: {llm_response_text[:200]}..."
        logging.error(error_msg)
        return {"error": f"ERROR_PARSE_CONTEXT: {error_msg}"}

def parse_analysis_output(llm_output_text):
    """(UPDATED) Parses the JSON response from the new Intent Analysis."""
    if not isinstance(llm_output_text, str) or not llm_output_text.strip():
        return {"error": "Empty or invalid response from LLM analysis"}
    try:
        json_match = re.search(r"```json\s*({[\s\S]*?})\s*```|({[\s\S]*})", llm_output_text)
        json_str = json_match.group(1) or json_match.group(2) if json_match else llm_output_text
        parsed_json = json.loads(json_str)
        core_request = parsed_json.get("core_request")
        decision_points = parsed_json.get("points")
        if not isinstance(core_request, str) or not isinstance(decision_points, list):
            raise ValueError("JSON structure is invalid. Missing 'core_request' or 'points'.")
        return {"actions": [core_request], "points": decision_points}
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Failed to parse analysis JSON: {e}. Raw output: {llm_output_text[:300]}")
        return {"error": f"Failed to parse the analysis from the AI. Details: {e}"}


# --- Gmail Authentication Routes ---
@app.route('/login')
def login():
    """Initiates the OAuth 2.0 login flow."""
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
    """Callback route that Google redirects to after user consent."""
    state = session.get('state')
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for('authorize', _external=True)
    )
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

@app.route('/logout')
def logout():
    """Clears the session to log the user out."""
    session.clear()
    return redirect(url_for('index_route'))


# --- NEW: Gmail Data Fetching Helper Functions and Routes ---
def get_gmail_service():
    """Creates an authorized Gmail service object from session credentials."""
    if 'credentials' not in session:
        return None
    try:
        # Create credentials object from the session data
        creds = google.oauth2.credentials.Credentials(**session['credentials'])
        # Build the service object
        service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        logging.error(f"Failed to create Gmail service: {e}")
        # Potentially invalid credentials, clear the session
        session.clear()
        return None

def get_full_thread_text(service, thread_id):
    """Fetches a full email thread and formats it into a single text block for analysis."""
    try:
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        full_conversation = []
        # The messages in a thread are returned oldest to newest by the API.
        for message in thread.get('messages', []):
            payload = message.get('payload', {})
            headers = payload.get('headers', [])
            
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Unknown Date')
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
            
            body = ''
            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data')
                        if data:
                            body = base64.urlsafe_b64decode(data).decode('utf-8')
                            break # Found the plain text part, no need to look further
            elif 'data' in payload.get('body', {}):
                data = payload['body']['data']
                body = base64.urlsafe_b64decode(data).decode('utf-8')

            # Format each message clearly for the LLM to understand the conversation flow
            message_text = f"--- Previous Message ---\nFrom: {sender}\nDate: {date}\nSubject: {subject}\n\n{body.strip()}\n"
            full_conversation.append(message_text)
            
        # Join all messages to form a coherent thread for the LLM prompt
        return "\n".join(full_conversation)
        
    except Exception as e:
        logging.error(f"Error fetching thread details for ID {thread_id}: {e}")
        return None

@app.route('/api/emails')
def fetch_emails_route():
    """API endpoint to fetch the last 15 emails from the user's inbox."""
    service = get_gmail_service()
    if not service:
        return jsonify({"error": "User not authenticated or session expired."}), 401
    
    try:
        # Get the list of message IDs from the INBOX
        results = service.users().messages().list(userId='me', maxResults=15, q="category:primary in:inbox").execute()
        messages = results.get('messages', [])
        
        email_list = []
        for msg in messages:
            # For the list view, we only need metadata (headers and snippet) which is faster
            message_meta = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From', 'Date']).execute()
            headers = message_meta.get('payload', {}).get('headers', [])
            
            email_summary = {
                'id': message_meta['id'],
                'threadId': message_meta['threadId'],
                'subject': next((h['value'] for h in headers if h['name'] == 'Subject'), '(No Subject)'),
                'sender': next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender'),
                'date': next((h['value'] for h in headers if h['name'] == 'Date'), ''),
                'snippet': message_meta.get('snippet', '')
            }
            email_list.append(email_summary)
            
        return jsonify(email_list)
    except Exception as e:
        logging.error(f"Failed to fetch emails: {e}")
        return jsonify({"error": "Failed to fetch emails from Gmail."}), 500

@app.route('/api/thread/<thread_id>')
def get_thread_route(thread_id):
    """
    (REESCRITO) API endpoint to fetch the LAST message of a thread 
    and format it for simple display.
    """
    service = get_gmail_service()
    if not service:
        return jsonify({"error": "User not authenticated or session expired."}), 401
    
    try:
        # Pede a thread completa para garantir que temos todos os dados
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        
        # Pega apenas na última mensagem da lista de mensagens
        if not thread.get('messages'):
            return jsonify({"error": "Thread contains no messages."}), 404
            
        # Get the first message in the thread for original sender and subject (for reply context)
        first_message = thread['messages'][0]
        first_payload = first_message.get('payload', {})
        first_headers = first_payload.get('headers', [])
        
        # Extract original sender email (e.g., "John Doe <john.doe@example.com>")
        original_sender_email = next((h['value'] for h in first_headers if h['name'].lower() == 'from'), 'Remetente Desconhecido')
        # Extract original subject
        original_subject = next((h['value'] for h in first_headers if h['name'].lower() == 'subject'), '(Sem Assunto)')

        # Get the last message in the thread for the `originalEmailEl` content (what the user sees)
        last_message = thread['messages'][-1]
        payload = last_message.get('payload', {})
        headers = payload.get('headers', [])
        
        body = ''
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8')
                        break
        elif 'data' in payload.get('body', {}):
            data = payload['body']['data']
            body = base64.urlsafe_b64decode(data).decode('utf-8')

        # Create the final formatted text for display in the textarea
        # This format helps the analysis function extract sender/subject from the displayed text
        display_text = f"From: {original_sender_email}\nSubject: {original_subject}\n\n{body.strip()}"
        
        # Return the simplified text PLUS the original sender and subject for sending replies
        return jsonify({
            "thread_text": display_text,
            "original_sender_email": original_sender_email,
            "original_subject": original_subject
        })

    except Exception as e:
        logging.error(f"Error fetching simplified thread for ID {thread_id}: {e}")
        return jsonify({"error": f"Failed to retrieve thread content: {e}"}), 500

@app.route('/api/send_email', methods=['POST'])
def send_email_route():
    """API endpoint to send an email using Gmail API."""
    service = get_gmail_service()
    if not service:
        return jsonify({"error": "User not authenticated or session expired."}), 401

    data = request.get_json()
    recipient = data.get('recipient')
    subject = data.get('subject')
    body = data.get('body')
    thread_id = data.get('thread_id') # Get thread_id from request

    if not all([recipient, subject, body]):
        return jsonify({"error": "Recipient, subject, and body are required."}), 400

    try:
        # Create the email message
        message = MIMEText(body)
        message['to'] = recipient
        message['subject'] = subject
        # Add 'In-Reply-To' header to link to the specific message being replied to
        # This helps Gmail correctly group replies in the same thread.
        # Note: Gmail API's `threadId` parameter typically handles this, but including headers can be good practice.
        # If replying to a specific message, you would need the original message's Message-ID header.
        # For simplicity, relying on threadId parameter for now.

        # Encode message for Gmail API
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        send_options = {'raw': raw_message}
        
        # If thread_id is provided, reply in the same thread
        if thread_id:
            send_options['threadId'] = thread_id

        # Use the send method to send the email
        sent_message = service.users().messages().send(userId='me', body=send_options).execute()
        
        logging.info(f"Email sent successfully to {recipient} with message ID: {sent_message['id']}")
        return jsonify({"message": "Email sent successfully!", "id": sent_message['id']})

    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        return jsonify({"error": f"Failed to send email: {e}"}), 500


# --- Main Application Routes ---
@app.route('/')
def index_route():
    """Serves the main page."""
    global PERSONA_DATA
    # Reload personas data in debug mode to pick up changes without restarting Flask
    if DEBUG_MODE:
        PERSONA_DATA = load_persona_file()
    personas_dict = PERSONA_DATA.get("personas", {})
    personas_display = {key: {"name": data.get("label_pt", key)} for key, data in personas_dict.items()}
    is_logged_in = 'credentials' in session
    return render_template('index.html', personas_dict=personas_display, error_loading_personas=not bool(personas_dict), is_logged_in=is_logged_in)

@app.route('/analyze', methods=['POST'])
def analyze_email_route():
    """(UPDATED) Endpoint for the new Intent Analysis."""
    if not request.json or not request.json.get('email_text', '').strip():
        return jsonify({"error": "Email text cannot be empty."}), 400
    email_text = request.json['email_text']
    logging.info("Starting Intent Analysis")
    analysis_prompt = build_prompt_1_analysis(email_text)
    llm_response = call_gemini(analysis_prompt, temperature=ANALYSIS_TEMPERATURE)
    if "error" in llm_response:
        return jsonify({"error": f"LLM analysis failed: {llm_response['error']}", "raw_analysis": llm_response.get("text")}), 500
    analysis_result = parse_analysis_output(llm_response.get("text", ""))
    if analysis_result.get("error"):
         return jsonify(analysis_result), 500
    logging.info("Intent analysis processed successfully.")
    return jsonify(analysis_result)


@app.route('/draft', methods=['POST'])
def draft_response_route():
    """(IMPROVED) Main endpoint to generate the draft, with active knowledge retrieval."""
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
    
    # Perform context analysis
    context_analysis_result = analyze_sender_and_context(original_email, selected_persona, generic_rules)
    if context_analysis_result.get("error"):
        logging.warning(f"Context pre-analysis failed: {context_analysis_result['error']}. Continuing with defaults.")
    
    # Find and summarize relevant knowledge based on context analysis
    summarized_knowledge = find_and_summarize_relevant_knowledge(selected_persona, context_analysis_result)
    
    user_inputs = request.json['user_inputs']
    if not user_inputs or not any(item.get('guidance', '').strip() for item in user_inputs):
        user_guidance = "Write an appropriate response to the email, considering the context and persona."
    else:
        guidance_points = [f'- For the decision point "{item.get("point", "geral")}", my intention is: "{item.get("guidance")}"'
                           for item in user_inputs if item.get('guidance', '').strip()]
        user_guidance = "The intention for the response is as follows:\n" + "\n".join(guidance_points)
    
    logging.info(f"Starting HYBRID Draft Generation for Persona: {active_persona_key}")
    draft_prompt = build_holistic_draft_prompt(
        original_email, user_guidance, active_persona_key, PERSONA_DATA, context_analysis_result, summarized_knowledge
    )
    llm_response = call_gemini(draft_prompt, temperature=GENERATION_TEMPERATURE)
    if "error" in llm_response:
        return jsonify({"error": f"Failed to generate draft: {llm_response['error']}", "context_analysis": context_analysis_result}), 500
    final_draft = llm_response.get("text", "").strip()
    return jsonify({"draft": final_draft, "context_analysis": context_analysis_result})

@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route():
    """(FIXED) Endpoint to generate a GUIDELINE suggestion for a Decision Point."""
    global PERSONA_DATA
    if not request.json or not all(k in request.json for k in ['point_to_address', 'persona_name']):
        return jsonify({"error": "Missing data in request."}), 400
    persona_name = request.json['persona_name']
    if persona_name not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400
    selected_persona = PERSONA_DATA["personas"][persona_name]
    prompt = build_prompt_3_suggestion(request.json['point_to_address'], selected_persona, request.json.get('direction', 'outro'))
    llm_response = call_gemini(prompt, temperature=ANALYSIS_TEMPERATURE)
    if "error" in llm_response:
         return jsonify(llm_response), 500
    return jsonify({"suggestion": llm_response.get("text", "").strip()})


@app.route('/refine_text', methods=['POST'])
def refine_text_route():
    """(COMPLETED) Endpoint to refine a portion of the generated text."""
    global PERSONA_DATA
    if not request.json or not all(k in request.json for k in ['selected_text', 'full_context', 'action', 'persona_name']):
        return jsonify({"error": "Missing data in request."}), 400
    persona_name = request.json['persona_name']
    if persona_name not in PERSONA_DATA.get("personas", {}):
        return jsonify({"error": f"Persona '{persona_name}' not found."}), 400
    selected_persona = PERSONA_DATA["personas"][persona_name]
    prompt = build_prompt_4_refinement(selected_persona, request.json['selected_text'], request.json['full_context'], request.json['action'])
    llm_response = call_gemini(prompt, temperature=REFINEMENT_TEMPERATURE)
    if "error" in llm_response:
        return jsonify(llm_response), 500
    return jsonify({"refined_text": llm_response.get("text", "")})


@app.route('/submit_feedback', methods=['POST'])
def submit_feedback_route():
    """Endpoint to receive user feedback and save it to personas.json."""
    if not request.json:
        return jsonify({"error": "Invalid request (JSON expected)."}), 400
    required_fields = ['persona_name', 'ai_original_response', 'user_corrected_output', 'feedback_category', 'interaction_context']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        return jsonify({"error": f"Missing data in request: {', '.join(missing)}."}), 400
    persona_name = request.json['persona_name']
    with personas_file_lock:
        try:
            with open(PERSONAS_FILE, 'r+', encoding='utf-8') as f:
                current_persona_data = json.load(f)
                if persona_name not in current_persona_data.get("personas", {}):
                    return jsonify({"error": f"Persona '{persona_name}' not found."}), 404
                persona_obj = current_persona_data["personas"][persona_name]
                persona_obj.setdefault('learned_knowledge_base', [])
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
                f.seek(0) # Rewind to the beginning of the file
                json.dump(current_persona_data, f, ensure_ascii=False, indent=2)
                f.truncate() # Truncate the file to the new size
        except Exception as e:
            logging.exception("Error saving feedback:")
            return jsonify({"error": f"Unexpected server error: {e}"}), 500
    # Update the global persona data in memory after saving to disk
    global PERSONA_DATA
    PERSONA_DATA = current_persona_data
    return jsonify({"message": "Feedback submitted successfully!"})


# --- Application Entry Point ---
if __name__ == '__main__':
    if not os.path.exists(CLIENT_SECRETS_FILE):
        logging.critical(f"FATAL ERROR: `client_secret.json` not found.")
        logging.critical("Please download it from your Google Cloud Console.")
    else:
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
