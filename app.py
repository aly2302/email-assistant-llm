# -*- coding: utf-8 -*-
import os
import json
import re
import requests
from flask import Flask, render_template, request, jsonify
import logging
from dotenv import load_dotenv
import traceback # Para logging de exceções mais detalhado

# Load environment variables from .env file
load_dotenv()

# Configurar logging básico
# Adiciona o nome da função ao formato do log para melhor rastreamento
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

# --- Configuração ---
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GENERATION_TEMPERATURE = float(os.environ.get('GENERATION_TEMPERATURE', 0.8)) # Temperatura padrão para geração criativa
DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# --- Gemini Configuration ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')

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


# --- Carregar Personas do Ficheiro JSON ---
PERSONAS = {} # Inicializa vazio
try:
    # Abre e lê o ficheiro JSON com as definições das personas
    with open(PERSONAS_FILE, 'r', encoding='utf-8') as f:
        PERSONAS = json.load(f)
    logging.info(f"Personas carregadas com sucesso de {PERSONAS_FILE}")
except FileNotFoundError:
    # Loga um erro crítico se o ficheiro não for encontrado
    logging.error(f"ERRO CRÍTICO: Ficheiro de personas '{PERSONAS_FILE}' não encontrado.")
    # A aplicação pode continuar, mas as funcionalidades de persona não funcionarão
except json.JSONDecodeError as e:
    # Loga um erro crítico se o JSON estiver mal formado
    logging.error(f"ERRO CRÍTICO: Falha ao fazer parse do JSON em '{PERSONAS_FILE}': {e}")
except Exception as e:
    # Loga qualquer outro erro inesperado durante o carregamento
    logging.error(f"ERRO CRÍTICO: Ocorreu um erro inesperado ao carregar personas: {e}\n{traceback.format_exc()}")


# --- Funções Auxiliares ---

def call_gemini(prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE):
    """
    Envia um prompt para a Google Gemini API e retorna a resposta.

    Args:
        prompt (str): O texto do prompt a ser enviado.
        model (str): O identificador do modelo Gemini a ser usado.
        temperature (float): A temperatura para a geração (controla a criatividade/aleatoriedade).

    Returns:
        dict: Um dicionário contendo 'text' com a resposta do LLM em caso de sucesso,
              ou 'error' com uma mensagem de erro em caso de falha.
    """
    # Verifica se a API Key está configurada
    if not GEMINI_API_KEY:
        logging.error("Variável de ambiente GEMINI_API_KEY não definida!")
        return {"error": "ERROR_CONFIG: Gemini API Key não configurada."}

    # Endpoint da API Gemini v1beta
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    # Payload da requisição para a API
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "text/plain", # Solicita resposta em texto plano
            # Outros parâmetros de geração podem ser adicionados aqui (topP, topK, maxOutputTokens)
        },
         "safetySettings": [ # Configurações de segurança para bloquear conteúdo prejudicial
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
         ]
    }
    headers = {'Content-Type': 'application/json'}

    logging.info(f"Enviando para Gemini API | Modelo: {model} | Temp: {temperature}")
    # Loga apenas o início do payload para não expor dados sensíveis ou sobrecarregar logs
    app.logger.debug(f"Payload (primeiros 500): {str(payload)[:500]}...")
    response = None
    try:
        # Faz a requisição POST para a API
        response = requests.post(api_url, json=payload, headers=headers, timeout=180) # Timeout de 3 minutos
        response.raise_for_status() # Levanta um erro HTTP para respostas 4xx/5xx

        # Processa a resposta JSON
        data = response.json()
        app.logger.debug(f"Resposta API (parcial): {str(data)[:500]}...")

        # --- Extração cuidadosa da resposta ---
        try:
            # Verifica se o prompt foi bloqueado por segurança
            if 'promptFeedback' in data and 'blockReason' in data['promptFeedback']:
                block_reason = data['promptFeedback']['blockReason']
                safety_ratings_str = f" Safety Ratings: {data['promptFeedback'].get('safetyRatings', 'N/A')}"
                error_msg = f"ERROR_GEMINI_BLOCKED_PROMPT: Prompt bloqueado. Reason: {block_reason}.{safety_ratings_str}"
                logging.error(f"{error_msg}. Feedback: {data['promptFeedback']}")
                return {"error": error_msg}

            # Verifica se há candidatos (respostas geradas)
            if 'candidates' in data and data['candidates']:
                candidate = data['candidates'][0] # Pega o primeiro candidato
                finish_reason = candidate.get('finishReason', 'UNKNOWN')
                safety_ratings_str = f" Safety Ratings: {candidate.get('safetyRatings', 'N/A')}"

                # Loga um aviso se a geração não terminou normalmente (STOP ou MAX_TOKENS)
                if finish_reason not in ['STOP', 'MAX_TOKENS']:
                    logging.warning(f"Gemini finishReason foi '{finish_reason}'. Resposta pode estar incompleta ou bloqueada.{safety_ratings_str}")
                    # Se foi bloqueado por segurança durante a geração
                    if finish_reason in ['SAFETY', 'RECITATION', 'OTHER']:
                        error_msg = f"ERROR_GEMINI_BLOCKED_FINISH: Geração interrompida. Reason: {finish_reason}.{safety_ratings_str}"
                        logging.error(error_msg)
                        return {"error": error_msg}

                # Extrai o texto gerado da estrutura da resposta
                generated_text = None
                if 'content' in candidate and 'parts' in candidate['content'] and candidate['content']['parts']:
                    text_part = candidate['content']['parts'][0]
                    if 'text' in text_part:
                         generated_text = text_part['text']

                # Retorna o texto se encontrado
                if generated_text is not None:
                     return {"text": generated_text.strip()}
                else:
                    # Se não houve texto, mas também não foi bloqueado explicitamente, logar e retornar erro
                    error_msg = f"ERROR_GEMINI_PARSE: Resposta válida mas sem texto gerado (finishReason: {finish_reason}). Candidate: {str(candidate)[:500]}"
                    logging.error(error_msg)
                    return {"error": error_msg}

            # Caso de resposta válida mas estrutura inesperada
            error_msg = f"ERROR_GEMINI_PARSE: Estrutura de resposta inesperada. Data: {str(data)[:500]}"
            logging.error(error_msg)
            return {"error": error_msg}

        except (KeyError, IndexError, TypeError) as e:
            # Erro ao tentar aceder a chaves/índices na resposta JSON
            error_msg = f"ERROR_GEMINI_PARSE: Exception parsing response data. Error: {e}. Data: {str(data)[:500]}"
            logging.exception("Error parsing Gemini response structure:") # Loga o stack trace completo
            return {"error": error_msg}

    # --- Tratamento de erros de rede e HTTP ---
    except requests.exceptions.Timeout:
        error_msg = "ERROR_GEMINI_TIMEOUT: Timeout (180s) ao contactar Gemini API."
        logging.error(error_msg)
        return {"error": error_msg}
    except requests.exceptions.ConnectionError:
        error_msg = "ERROR_GEMINI_CONNECTION: Falha na conexão com Gemini API."
        logging.error(error_msg)
        return {"error": error_msg}
    except requests.exceptions.RequestException as e:
        # Erro genérico da biblioteca requests (inclui HTTPError)
        error_details = ""
        status_code = "N/A"
        if response is not None:
            status_code = response.status_code
            try:
                # Tenta obter detalhes do erro do JSON da resposta
                error_content = response.json()
                error_details = error_content.get('error', {}).get('message', response.text)
            except (json.JSONDecodeError, AttributeError):
                 # Se não for JSON, pega o início do texto da resposta
                 if hasattr(response, 'text'):
                      error_details = response.text[:200] + "..."
        error_msg = f"ERROR_GEMINI_REQUEST: {e} (Status: {status_code}) - Detalhes: {error_details}"
        logging.error(f"Erro na chamada API Gemini: {e}. Status: {status_code}. Detalhes: {error_details}")
        app.logger.debug(f"Payload que causou erro (parcial): {str(payload)[:500]}...")
        return {"error": error_msg}
    except json.JSONDecodeError as e:
        # Erro se a resposta da API não for um JSON válido
        error_msg = f"ERROR_JSON_DECODE: Falha ao descodificar JSON da resposta da API. Error: {e}. Resposta (início): {response.text[:200] if response is not None else 'N/A'}..."
        logging.error(error_msg)
        if response is not None:
             logging.error(f"Resposta completa recebida (status {response.status_code}): {response.text}")
        return {"error": error_msg}
    except Exception as e:
        # Captura qualquer outro erro inesperado
        error_msg = f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"
        logging.exception("Erro inesperado na função call_gemini:") # Loga o stack trace completo
        return {"error": error_msg}


def parse_analysis_output(llm_output):
    """
    Faz o parsing da saída textual do LLM (Prompt 1 - Análise de Pontos/Ações)
    para extrair listas de pontos a responder e ações a tomar.

    Args:
        llm_output (str | dict): A saída do LLM. Pode ser uma string ou um
                                 dicionário de erro vindo de `call_gemini`.

    Returns:
        dict: Um dicionário com as chaves 'points' (list) e 'actions' (list).
              Em caso de erro no input ou parsing, retorna um dicionário
              com a chave 'error'.
    """
    points = []
    actions = []

    # Verifica se a entrada já é um erro
    if isinstance(llm_output, dict) and "error" in llm_output:
        return llm_output
    if not llm_output:
        return {"error": "Empty response from LLM analysis"}
    if not isinstance(llm_output, str):
        llm_output = str(llm_output) # Garante que é string para regex
    if llm_output.startswith("ERROR_"):
        return {"error": llm_output} # Propaga erros prefixados

    # Regex para encontrar a secção "Pontos a Responder" e capturar o seu conteúdo
    # Procura por "pontos a responder" ou "points to address" (case-insensitive),
    # seguido por dois pontos, opcionalmente nova linha, e captura tudo (*)
    # até encontrar a próxima secção "ações" ou "actions" (com ** ou __) ou o fim ($).
    points_match = re.search(
        r"(?:points\s+to\s+address|pontos\s+a\s+responder)\s*:\s*\n*(.*?)(?:\n*\s*(?:\*\*|\_\_)(?:actions|ações)|$)",
        llm_output, re.IGNORECASE | re.DOTALL
    )
    if points_match:
        points_text = points_match.group(1).strip()
        # Verifica se o texto não é apenas "nenhum" ou "none"
        if points_text and not re.search(r"^\s*(nenhum|none)\.?\s*$", points_text, re.IGNORECASE | re.MULTILINE):
            # Tenta extrair itens de lista (numerados ou com marcadores)
            raw_points = re.findall(r"^\s*(?:\d+[\.\)]?|\*|\-)\s+(.*?)(?=\n\s*(?:\d+[\.\)]?|\*|\-)|\Z)", points_text, re.MULTILINE | re.DOTALL)
            # Limpa espaços extra e adiciona à lista se não estiver vazio
            points = [re.sub(r'\s+', ' ', p).strip() for p in raw_points if p.strip()]
    elif "pontos a responder" in llm_output.lower() or "points to address" in llm_output.lower():
        # Loga aviso se o cabeçalho foi encontrado mas vazio ou não parseável
        logging.warning("Analysis parsing: Section 'Pontos a Responder' found but was empty or unparseable.")

    # Regex similar para encontrar a secção "Ações para Rodrigo"
    actions_match = re.search(
        r"(?:actions\s+for\s+rodrigo|ações\s+para\s+rodrigo)\s*(?:\(optional|opcional\))?\s*:\s*\n*(.*?)(?:\n*\s*(?:\*\*|\_\_)|$)",
        llm_output, re.IGNORECASE | re.DOTALL
    )
    if actions_match:
        actions_text = actions_match.group(1).strip()
        # Verifica se não é apenas "nenhum", "none", "nenhuma"
        if actions_text and not re.search(r"^\s*(nenhum|none|nenhuma)\.?\s*$", actions_text, re.IGNORECASE | re.MULTILINE):
            # Tenta extrair itens com marcadores (* ou -)
            raw_actions = re.findall(r"^\s*[\*\-]\s+(.*?)(?=\n\s*[\*\-]|\Z)", actions_text, re.MULTILINE | re.DOTALL)
            actions = [re.sub(r'\s+', ' ', a).strip() for a in raw_actions if a.strip()]

    # Loga aviso se a estrutura esperada não foi encontrada ou parseada
    if not points and not actions and not llm_output.startswith("ERROR_") and llm_output.strip():
        if not points_match and not actions_match:
             logging.warning(f"Analysis parsing: Could not find 'Pontos a Responder' or 'Ações' structure. LLM output (start): {llm_output[:200]}...")
        else:
             logging.warning(f"Analysis parsing: Found headers but failed to extract list items. LLM output (start): {llm_output[:200]}...")

    # Se o LLM explicitamente disse "nenhum ponto", retorna lista vazia
    if not points and re.search(r"nenhum ponto a responder", llm_output, re.IGNORECASE):
        points = [] # Retorna lista vazia para consistência

    return {"points": points or [], "actions": actions or []}


def build_prompt_1_analysis(email_text):
    """
    Constrói o prompt para solicitar a análise inicial do email ao LLM (Prompt 1),
    focado em extrair pontos que necessitam de resposta e ações a tomar.

    Args:
        email_text (str): O conteúdo completo do email recebido.

    Returns:
        str: O prompt formatado para o LLM.
    """
    prompt = f"""System: És um assistente de análise de emails altamente eficiente e preciso. A tua função é ler o email fornecido e identificar claramente os elementos que requerem atenção por parte do destinatário (vamos assumir que se chama Rodrigo). Foca-te apenas no conteúdo do email. **Responde SEMPRE em Português de Portugal (pt-PT).**

Tarefa: Analisa o email fornecido abaixo e produz a tua análise estritamente no seguinte formato, com duas secções distintas:

1.  **Pontos a Responder:**
    * Cria uma lista **numerada** (`1.`, `2.`, `3.`, ...) contendo **todos** os pontos chave, **perguntas (explícitas ou implícitas)**, ou tópicos específicos mencionados no email que **precisam ser abordados, respondidos ou clarificados** por Rodrigo na sua resposta por email.
    * **Inclui todas as perguntas e pedidos de informação, mesmo que técnicos.**
    * Formula cada ponto de forma clara e concisa, idealmente como uma pergunta ou afirmação que necessita de resposta/confirmação.
    * Se o email for puramente informativo, de agradecimento, ou não contiver absolutamente nada que precise ser abordado/respondido, escreve apenas: `Nenhum ponto a responder.`

2.  **Ações para Rodrigo (Opcional):**
    * Se, e apenas se, o email mencionar ou implicar tarefas ou ações concretas que Rodrigo precisa de **realizar** (para além de simplesmente responder ao email - ex: "enviar o ficheiro X", "marcar reunião Y", "investigar Z"), lista-as aqui usando marcadores (`* `).
    * Se não houver ações claras identificadas para Rodrigo, omite completamente esta secção "Ações para Rodrigo" ou escreve `Nenhuma ação específica para Rodrigo.`.

Mantém a análise focada e objetiva no conteúdo do email. Evita interpretações subjetivas ou adicionar informação externa. Certifica-te de seguir o formato pedido (lista numerada para pontos, bullets para ações).

Email Recebido:
---
{email_text}
---
**Análise:**
"""
    return prompt

# --- NOVA FUNÇÃO e PROMPT para Análise de Contexto (Pré-Análise) ---
def build_prompt_0_context_analysis(original_email, persona):
    """
    Constrói o prompt para a Pré-Análise (Prompt 0): identificar tipo de destinatário,
    tom do email recebido e nome do remetente, usando o LLM.

    Args:
        original_email (str): O conteúdo do email recebido.
        persona (dict): O dicionário da persona que irá responder.

    Returns:
        str: O prompt formatado para o LLM solicitar a análise de contexto em JSON.
    """
    # Limitar o tamanho do email para evitar prompts excessivamente longos e custos
    max_email_length = 3000 # Ajustar conforme necessário (considerar tokens)
    truncated_email = original_email[:max_email_length]
    if len(original_email) > max_email_length:
        truncated_email += "\n... (email truncado)"

    # Extrair apenas as informações da persona relevantes para esta análise
    # Evita incluir exemplos de escrita longos ou descrições detalhadas aqui.
    persona_context = {
        "name": persona.get("name", "N/A"),
        "role": persona.get("role", "N/A"),
        "language": persona.get("attributes", {}).get("language", "pt-PT"),
        # Inclui apenas os nomes das relações e os seus tipos
        "relationships": {k: v.get('type', 'N/A') for k, v in persona.get("relationships", {}).items()},
        # Inclui as chaves das regras de adaptação (tipos de destinatários conhecidos)
        "recipient_types": list(persona.get("recipient_adaptation_rules", {}).keys())
    }

    # O prompt instrui o LLM a analisar o email e a persona, e retornar um JSON específico.
    prompt = f"""System: És um especialista em análise de contexto de emails. Dada a Persona que vai responder e o Email Recebido, analisa cuidadosamente o remetente (From:), destinatários (To:/Cc:), saudação, corpo e assinatura para determinar a relação mais provável, o tom do email e o nome do remetente principal. Responde **APENAS** em formato JSON válido.

Persona Que Vai Responder (Contexto Relevante):
```json
{json.dumps(persona_context, indent=2, ensure_ascii=False)}
```

Email Recebido (Analisa o conteúdo e metadados como From/To/Cc se disponíveis):
---
{truncated_email}
---

Tarefa: Analisa o email recebido e o contexto da persona. Determina a categoria mais provável do remetente PRINCIPAL (a quem a resposta será dirigida) e o tom do email recebido. Devolve **APENAS** um objeto JSON com as seguintes chaves **OBRIGATÓRIAS**:

1.  `recipient_category`: (string) A chave **exata** que melhor descreve o remetente principal. Deve ser UMA das seguintes opções, pela ordem de prioridade:
    * A chave de uma das `relationships` da persona (ex: "Professor Jorge") se houver uma correspondência clara e direta entre o remetente do email e essa relação específica.
    * A chave de um dos `recipient_types` da persona (ex: "professor", "colleague_student", "admin_services") se não for uma relação específica mas se encaixar numa categoria geral definida nas regras.
    * "unknown" se nenhuma das opções acima se aplicar claramente ou se a informação for insuficiente.
2.  `incoming_tone`: (string) O tom/formalidade percebido do **email recebido**. Escolhe UMA das seguintes opções que melhor descreva o email: "Muito Formal", "Formal", "Semi-Formal", "Casual", "Urgente", "InformativoNeutro", "Outro".
3.  `sender_name_guess`: (string) A melhor estimativa do nome do remetente principal (ex: "Marta Silva", "João", "Dr. Carlos", "Equipa de Suporte"). Tenta extrair o nome do campo 'From:', da assinatura ou da saudação. Se impossível determinar com razoável certeza, retorna uma string vazia "".

**IMPORTANTE:** A tua saída deve ser **APENAS** o objeto JSON, sem qualquer texto adicional antes ou depois (sem ```json ... ```, apenas o JSON puro). Exemplo de saída válida:
{{
  "recipient_category": "colleague_student",
  "incoming_tone": "Casual",
  "sender_name_guess": "Marta"
}}

JSON Result:
"""
    return prompt

def analyze_sender_and_context(original_email, persona):
    """
    Chama o LLM para realizar a Pré-Análise de Contexto (Prompt 0)
    e retorna os resultados parseados do JSON.

    Args:
        original_email (str): O conteúdo do email recebido.
        persona (dict): O dicionário da persona que irá responder.

    Returns:
        dict: Um dicionário contendo 'recipient_category', 'incoming_tone',
              'sender_name_guess', e 'error' (None em caso de sucesso,
              ou mensagem de erro se a análise falhar).
              Em caso de erro de parsing, retorna valores default e a msg de erro.
    """
    logging.info(f"Iniciando Pré-Análise de Contexto para email e persona {persona.get('name', 'N/A')}")
    if not persona: # Validação básica
        logging.error("Pré-Análise falhou: Persona inválida.")
        return {"error": "Persona inválida fornecida para análise de contexto."}

    # Constrói o prompt específico para esta análise
    analysis_prompt = build_prompt_0_context_analysis(original_email, persona)
    # Loga o prompt se estiver em modo debug
    app.logger.debug(f"Prompt Pré-Análise (Contexto):\n{analysis_prompt}")

    # Chama o LLM com temperatura baixa para uma análise mais determinística e focada
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.2)

    # Verifica se houve erro na chamada à API
    if "error" in llm_response_data:
        logging.error(f"Erro na chamada Gemini para Pré-Análise: {llm_response_data['error']}")
        # Retorna o erro da API
        return {"error": f"Falha na comunicação com LLM para pré-análise: {llm_response_data['error']}"}

    llm_response_text = llm_response_data.get("text", "")
    logging.info("Pré-Análise recebida do Gemini, a fazer parsing do JSON.")
    app.logger.debug(f"Resposta Bruta Pré-Análise LLM: {llm_response_text}")

    # Tenta fazer o parse do JSON da resposta
    try:
        # O LLM pode retornar o JSON dentro de ```json ... ``` ou diretamente.
        # Esta regex tenta encontrar o JSON em ambos os casos.
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```|({[\s\S]+})", llm_response_text)
        if not json_match:
            # Se não encontrar um padrão JSON claro, tenta fazer parse da string inteira
            logging.warning("JSON da pré-análise não encontrado com regex, tentando parse direto.")
            json_str = llm_response_text
            # Levanta erro se não conseguir fazer parse direto
            if not json_str.strip().startswith("{") or not json_str.strip().endswith("}"):
                 raise json.JSONDecodeError("Resposta não parece ser JSON válido.", llm_response_text, 0)

        else:
             # Pega o conteúdo do JSON encontrado pela regex
             json_str = json_match.group(1) or json_match.group(2)

        # Faz o parse da string JSON
        parsed_json = json.loads(json_str)

        # Validação da estrutura esperada do JSON
        required_keys = ["recipient_category", "incoming_tone", "sender_name_guess"]
        if not all(key in parsed_json for key in required_keys):
            missing = [key for key in required_keys if key not in parsed_json]
            raise ValueError(f"JSON da Pré-Análise inválido. Faltam chaves: {missing}")

        # Validação dos tipos de dados (opcional mas recomendado)
        if not isinstance(parsed_json["recipient_category"], str):
            raise ValueError("Tipo inválido para 'recipient_category'. Esperado: string.")
        if not isinstance(parsed_json["incoming_tone"], str):
             raise ValueError("Tipo inválido para 'incoming_tone'. Esperado: string.")
        if not isinstance(parsed_json["sender_name_guess"], str):
             raise ValueError("Tipo inválido para 'sender_name_guess'. Esperado: string.")


        logging.info("Pré-Análise JSON parseada com sucesso.")
        app.logger.debug(f"Resultado Pré-Análise: {parsed_json}")
        # Retorna o JSON parseado com 'error: None' para indicar sucesso
        return {**parsed_json, "error": None}

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        # Erro durante o parsing ou validação do JSON
        error_msg = f"Falha ao fazer parse ou validar JSON da Pré-Análise: {e}. Resposta LLM: {llm_response_text}"
        logging.error(error_msg)
        logging.exception("Detalhes do erro de parsing da Pré-Análise:") # Loga stack trace
        # Fallback: Se falhar, retorna 'unknown' e 'Neutro' para não bloquear o fluxo principal,
        # mas inclui a mensagem de erro para debugging.
        return {
            "recipient_category": "unknown",
            "incoming_tone": "Neutro",
            "sender_name_guess": "",
            "error": f"ERROR_PARSE_CONTEXT: {error_msg}"
        }
    except Exception as e:
        # Captura qualquer outro erro inesperado
        error_msg = f"Erro inesperado no processamento da Pré-Análise: {e}"
        logging.exception("Erro inesperado em analyze_sender_and_context:")
        return {
            "recipient_category": "unknown",
            "incoming_tone": "Neutro",
            "sender_name_guess": "",
            "error": f"ERROR_UNEXPECTED_CONTEXT: {error_msg}"
        }


# --- PROMPT 2 (Rascunho) REFACTORADO COM FOCO NA COESÃO ---
def build_prompt_2_drafting(persona, original_email, user_inputs, context_analysis):
    """
    Constrói o prompt complexo para solicitar a geração do rascunho da resposta (Prompt 2),
    UTILIZANDO os resultados da pré-análise de contexto e com instruções REFORÇADAS
    para COESÃO e FLUXO NATURAL.

    Args:
        persona (dict): O dicionário da persona selecionada.
        original_email (str): O conteúdo do email recebido.
        user_inputs (list): Lista de dicionários com 'point' e 'guidance' do utilizador.
        context_analysis (dict): O resultado da função `analyze_sender_and_context`.

    Returns:
        str: O prompt formatado para o LLM gerar o rascunho da resposta.
    """
    # Determina a instrução de linguagem (pt-PT vs pt-BR)
    persona_lang = persona.get("attributes", {}).get("language", "pt-PT")
    if persona_lang == "pt-BR":
        lang_instruction = "Escreve **exclusivamente** em **Português do Brasil (pt-BR)** de forma **natural e fluída**. Evita construções de Portugal."
        lang_instruction_short = "LINGUAGEM pt-BR natural"
    else:
        lang_instruction = "Escreve **exclusivamente** em **Português de Portugal (pt-PT)** de forma **natural e fluída**. Evita construções do Brasil (ex: gerúndio excessivo)."
        lang_instruction_short = "LINGUAGEM pt-PT natural"

    # --- Obter resultados da Pré-Análise ---
    recipient_category = context_analysis.get("recipient_category", "unknown")
    incoming_tone = context_analysis.get("incoming_tone", "Neutro")
    sender_name_guess = context_analysis.get("sender_name_guess") if context_analysis.get("sender_name_guess") else "Destinatário"

    # --- Determinar Saudação/Despedida/Tom com base na Pré-Análise ---
    # (Lógica de determinação de saudação/despedida/tom base - sem alterações)
    final_greeting = f"Bom dia/tarde {sender_name_guess},"
    final_farewell = f"Com os melhores cumprimentos,\n{persona.get('name', '')}"
    base_tone = persona.get("attributes", {}).get("tone", "Neutro")
    rules = persona.get("recipient_adaptation_rules", {})
    relationships = persona.get("relationships", {})

    if recipient_category in relationships:
        relationship_data = relationships[recipient_category]
        final_greeting = relationship_data.get("greeting_individual", rules.get(recipient_category, {}).get("greeting", final_greeting))
        # Tenta obter despedida da regra associada à categoria da relação, senão usa 'unknown', senão fallback.
        # Assume que a chave da relação pode ser usada como chave da regra, ou usa 'unknown'
        final_farewell = rules.get(recipient_category, rules.get("unknown", {})).get("farewell", final_farewell)
        base_tone = relationship_data.get("tone", rules.get(recipient_category, {}).get("tone", base_tone))
    elif recipient_category in rules:
        adapt_rules = rules[recipient_category]
        final_greeting = adapt_rules.get("greeting", final_greeting)
        final_farewell = adapt_rules.get("farewell", final_farewell)
        base_tone = adapt_rules.get("tone", base_tone)
    else: # Categoria 'unknown' ou não encontrada
        adapt_rules = rules.get("unknown", {})
        final_greeting = adapt_rules.get("greeting", final_greeting)
        final_farewell = adapt_rules.get("farewell", final_farewell)
        base_tone = adapt_rules.get("tone", base_tone)

    # Substitui placeholders na saudação
    final_greeting = final_greeting.replace("[Apelido]", sender_name_guess).replace("[Nome]", sender_name_guess)

    # Ajusta a assinatura na despedida se necessário (ex: nome curto vs completo)
    persona_signature_name = persona.get("name", "")
    # Exemplo: Se a regra diz "Abraço,\nRodrigo" mas a persona é "Rodrigo Novelo",
    # e a categoria NÃO é 'colleague_student', ajusta para o nome completo.
    if persona_signature_name and persona_signature_name != "Rodrigo" and "\nRodrigo" in final_farewell and recipient_category != "colleague_student":
         final_farewell = final_farewell.replace("\nRodrigo", f"\n{persona_signature_name}")
    # Considerar outros casos de ajuste se necessário


    # --- Estrutura do Prompt Refatorada em Blocos ---

    # --- Bloco 1: Definição da Persona e Regras Gerais ---
    system_prompt = f"""### INSTRUÇÕES DE SISTEMA E PERSONA ###
System: **TU ÉS {persona['name']}**. A tua tarefa é gerar um email de resposta de ALTA QUALIDADE, escrito por ti ({persona['name']}) para '{sender_name_guess}'. Assume integralmente o teu papel ({persona.get('role', 'Assistente')}) e adota rigorosamente a seguinte Persona:
* **Nome da Persona:** {persona['name']}
* **Papel:** {persona.get('role', 'N/A')}
* **Descrição Geral:** {persona.get('description', 'Estilo padrão')}
* **Atributos Gerais:** (Tom Base: {persona.get('attributes', {}).get('tone', 'Neutro')}, Formalidade Base: {persona.get('attributes', {}).get('formality', 'Média')}, Verbosidade: {persona.get('attributes', {}).get('verbosity', 'Média')}, Uso de Emojis: {persona.get('attributes', {}).get('emoji_usage', 'Nenhum')})
* **Linguagem OBRIGATÓRIA:** {lang_instruction}

**Regras Essenciais de Escrita:**
* **Qualidade:** Produz uma resposta bem escrita, humana, natural e profissional (ou adaptada à formalidade). O texto deve fluir bem.
* **Clareza e Concisão:** Vai direto ao ponto, mas mantém a cordialidade. Evita repetições.
* **Contexto:** Responde diretamente ao email original e às orientações dadas.

**Regras OBRIGATÓRIAS "Faz" (Do's de {persona['name']}):**
{chr(10).join([f'* {rule}' for rule in persona.get('dos', ['Ser claro.'])])}

**Regras OBRIGATÓRIAS "Não Faças" (Don'ts de {persona['name']}):**
{chr(10).join([f'* {rule}' for rule in persona.get('donts', ['Ser vago.'])])}
--- FIM PERSONA E REGRAS GERAIS ---

"""

    # --- Bloco 2: Exemplos de Estilo ---
    examples_prompt = ""
    writing_examples = persona.get("writing_examples")
    if writing_examples:
        examples_prompt += f"\n### EXEMPLOS DE ESTILO DE ESCRITA (APENAS COMO GUIA DE ESTILO) ###\n"
        examples_prompt += "**NÃO uses o conteúdo destes exemplos na resposta final. Usa-os APENAS para aprender o tom, vocabulário, estrutura e formalidade da persona.**\n"
        limited_examples = writing_examples[:3] # Limita para poupar tokens
        for i, example in enumerate(limited_examples):
            context_desc = example.get("context", f"Exemplo {i+1}")
            output_example = example.get("output_style_example", "")
            if output_example:
                examples_prompt += f"\n---\nContexto Exemplo {i+1}: {context_desc}\nTexto Exemplo:\n{output_example}\n"
        examples_prompt += f"---\n--- FIM DOS EXEMPLOS DE ESTILO ---\n"

    # --- Bloco 3: Contexto da Tarefa Atual ---
    context_prompt = f"""\n### CONTEXTO DA TAREFA ATUAL ###
**Email Original Recebido de '{sender_name_guess}'**
*Tom do Email Recebido (detetado pela pré-análise):* '{incoming_tone}'
---
{original_email}
---

**Análise do Destinatário (feita pela pré-análise):**
* Categoria do Destinatário: '{recipient_category}'
* Tom Base Definido para este Destinatário: '{base_tone}'
* Saudação Determinada: `{final_greeting}`
* Despedida Determinada: (ver abaixo na Tarefa Final)

**Itens a Abordar & Informação Chave/Pontos Essenciais Fornecidos por Ti ({persona['name']}) para Construir a Resposta:**
"""
    # Processamento dos user_inputs (igual à versão anterior)
    if user_inputs:
        has_real_points = False
        guidance_provided = False
        for i, item in enumerate(user_inputs):
            point = item.get('point', 'N/A')
            guidance = item.get('guidance', '')
            if guidance: guidance_provided = True
            is_placeholder_point = point == 'N/A' or point == "null" or (isinstance(point, str) and point.lower().startswith("nenhum ponto"))

            if not is_placeholder_point:
                context_prompt += f"* Ponto Original {i+1} a Abordar: \"{point}\"\n"
                context_prompt += f"    * Informação/Ideias Chave para a Tua Resposta: \"{guidance if guidance else '(Nenhuma orientação específica dada - responde apropriadamente)'}\"\n"
                has_real_points = True
            elif guidance: # Orientação geral
                context_prompt += f"* Tua Orientação Geral (a incorporar na resposta): \"{guidance}\"\n"

        # Adiciona instruções se não houver pontos ou orientações específicas
        if not has_real_points and not guidance_provided:
             context_prompt += "* Tarefa Adicional: Escrever uma resposta curta e apropriada (ex: agradecimento, confirmação simples) baseada apenas no email original e na tua persona.\n"
        elif not has_real_points and guidance_provided:
             context_prompt += "* Tarefa Adicional: Incorpora a(s) orientação(ões) geral(is) acima numa resposta apropriada ao email original, seguindo a tua persona.\n"
    else: # Nenhum user_input fornecido
        context_prompt += "* Tarefa Adicional: Escrever uma resposta curta e apropriada baseada apenas no email original e na tua persona.\n"
    context_prompt += "--- FIM CONTEXTO ---\n"


    # --- Bloco 4: Tarefa Final (COM INSTRUÇÕES DE COESÃO REFORÇADAS) ---
    task_prompt = f"""\n### TAREFA FINAL ###
Com base em TUDO o que foi dito acima (Instruções, Persona, Exemplos, Contexto, Informação Chave), redige agora o corpo COMPLETO e de ALTA QUALIDADE do email de resposta.

**Instruções Específicas:**
1.  **Coesão e Fluxo:** Integra TODA a 'Informação/Ideias Chave' tua de forma **natural, humana e coesa** no texto. **Agrupa tópicos relacionados em parágrafos lógicos** e utiliza **frases de transição** apropriadas para ligar as diferentes ideias. **EVITA responder a cada ponto isoladamente como uma lista; constrói uma resposta unificada e fluida**, como um humano faria.
2.  **Adaptação Dinâmica ao Tom:** Considera o 'Tom do Email Recebido' ('{incoming_tone}'). O teu 'Tom Base Definido' para '{recipient_category}' é '{base_tone}'. **AJUSTA subtilmente** o teu tom na resposta para criar harmonia. Se o tom recebido for muito diferente do teu base (ex: recebeste email casual mas o teu base é formal), aproxima-te ligeiramente do tom recebido, mas sem quebrar completamente a tua persona. Se os tons já forem semelhantes, mantém o teu tom base.
3.  **Integração do Conteúdo:** Relembrando: NÃO copies literalmente a 'Informação/Ideias Chave', **Usa-as como BASE** para construir as tuas próprias frases, mantendo o fluxo da conversa e o teu estilo. Responde a todos os pontos que foram identificados como necessitando de resposta.
4.  **Fidelidade à Persona:** Mantém-te ESTRITAMENTE FIEL à Persona {persona['name']} ({lang_instruction_short}, regras Do/Don't, estilo geral aprendido dos exemplos).
5.  **Formato OBRIGATÓRIO:**
    * Começa **DIRETAMENTE** com a saudação: `{final_greeting}`
    * Gera o corpo da resposta em **formato de parágrafo(s)**.
    * Termina **EXATAMENTE** com a despedida:
{final_farewell}
    * **NÃO** adiciones cabeçalhos (Assunto:, De:, Para:), comentários extra, ou qualquer texto fora do corpo do email (saudação > conteúdo > despedida).

Resposta Gerada:
"""

    # --- Combinar todos os blocos e retornar ---
    full_prompt = system_prompt + examples_prompt + context_prompt + task_prompt
    # Logar o prompt completo em modo debug para análise
    if DEBUG_MODE:
        prompt_hash = hash(full_prompt) # Hash para identificar prompts únicos nos logs
        logging.debug(f"--- DEBUG: PROMPT 2 (Drafting) Persona: {persona['name']} / Hash: {prompt_hash} ---")
        logging.debug(f"Prompt 2 Length: {len(full_prompt)} chars")
        log_limit = 4000 # Limite para não sobrecarregar logs
        logging.debug(full_prompt[:log_limit] + "..." if len(full_prompt) > log_limit else full_prompt)
        logging.debug("--- FIM DEBUG PROMPT 2 ---")
    return full_prompt



def build_prompt_3_suggestion(original_email, point_to_address, persona, direction=None):
    """
    Constrói o prompt para solicitar uma SUGESTÃO DE TEXTO DE RESPOSTA (Prompt 3)
    para um ponto específico, seguindo a persona e opcionalmente uma direção (Sim/Não).

    Args:
        original_email (str): O conteúdo do email original (para contexto).
        point_to_address (str): O ponto específico extraído da análise (Prompt 1).
        persona (dict): O dicionário da persona selecionada.
        direction (str, optional): A direção indicada pelo utilizador ("sim", "nao", ou None).

    Returns:
        str: O prompt formatado para o LLM gerar a sugestão.
    """
    # Determina a instrução de linguagem
    persona_lang = persona.get("attributes", {}).get("language", "pt-PT")
    if persona_lang == "pt-BR":
        lang_instruction = "Escreve **exclusivamente** em **Português do Brasil (pt-BR)** e soa natural."
    else:
        lang_instruction = "Escreve **exclusivamente** em **Português de Portugal (pt-PT)** e soa natural."

    # Constrói a instrução adicional com base na direção fornecida
    direction_instruction = ""
    if direction == "sim":
        direction_instruction = "\n**Instrução Adicional Importante:** O utilizador indicou que a resposta a este ponto deve ser **AFIRMATIVA / POSITIVA ('Sim')**. Baseia a tua sugestão nesta direção, mantendo a persona."
    elif direction == "nao":
        direction_instruction = "\n**Instrução Adicional Importante:** O utilizador indicou que a resposta a este ponto deve ser **NEGATIVA ('Não')**. Baseia a tua sugestão nesta direção, mantendo a persona."
    # Se direction for "outro" ou None/vazio, nenhuma instrução específica é adicionada.

    # Constrói o prompt completo
    system_prompt = f"""System: A tua tarefa é gerar uma sugestão CURTA (idealmente 1-2 frases concisas) de texto de resposta para um ponto específico de um email. Deves agir EXATAMENTE como {persona['name']}, adotando a seguinte Persona:
* **Nome:** {persona['name']} ({persona.get('role', '')})
* **Tom Geral:** {persona.get('attributes', {}).get('tone', 'Neutro')} (Adapta ao contexto se necessário)
* **Formalidade:** {persona.get('attributes', {}).get('formality', 'Média')} (Adapta ao contexto se necessário)
* **Verbosidade:** {persona.get('attributes', {}).get('verbosity', 'Média')} (Aplica à sugestão - ser concisa!)
* **Uso de Emojis:** {persona.get('attributes', {}).get('emoji_usage', 'Nenhum')}

**Regra de Linguagem OBRIGATÓRIA: {lang_instruction}**

**Regras "Faz" (aplicáveis à sugestão):**
{chr(10).join([f'* {rule}' for rule in persona.get('dos', ['Ser claro.'])])}

**Regras "Não Faças" (aplicáveis à sugestão):**
{chr(10).join([f'* {rule}' for rule in persona.get('donts', ['Ser vago.'])])}

**Formato OBRIGATÓRIO da Saída:**
* Gera APENAS o texto da resposta sugerida para o ponto específico.
* NÃO incluas saudações, despedidas, ou explicações como "Para responder a isso, poderias dizer:".
* Foca-te em criar uma frase ou duas que {persona['name']} poderia usar diretamente ou adaptar para responder/abordar o ponto fornecido.{direction_instruction} # <<< INSTRUÇÃO DE DIREÇÃO INJETADA AQUI

--- FIM DAS INSTRUÇÕES DE SISTEMA ---

Contexto: Email Original Recebido (apenas para referência de contexto)
---
{original_email[:1000]} ... (email truncado para contexto)
---

Ponto Específico do Email Original a Abordar: "{point_to_address}"

Tarefa: Escreve agora a sugestão de texto que {persona['name']} poderia usar na sua resposta para abordar APENAS este ponto específico, seguindo TODAS as regras e a instrução adicional (se existir) acima. Sê conciso e direto ao ponto.

Sugestão de Texto de Resposta para este Ponto:
"""
    return system_prompt

# --- Rotas da Aplicação Flask ---

@app.route('/')
def index_route():
    """Renderiza a página HTML inicial."""
    logging.info("A servir a página inicial (index.html)")
    # Verifica se as personas foram carregadas corretamente
    if not PERSONAS:
         logging.warning("Renderizando index.html mas PERSONAS não foram carregadas.")
         # Passa um indicador de erro para o template
         return render_template('index.html', personas_dict={}, error_loading_personas=True)

    # Passa um dicionário simplificado das personas para o template
    # (ex: apenas nome e descrição para um seletor)
    personas_display = {key: {"name": data.get("name", key), "description": data.get("description", "")}
                        for key, data in PERSONAS.items()}
    return render_template('index.html', personas_dict=personas_display, error_loading_personas=False)


@app.route('/analyze', methods=['POST'])
def analyze_email_route(): # Renomeado para evitar conflito com a função analyze_email
    """Endpoint para analisar o email recebido usando Gemini (Prompt 1)."""
    # Validação básica do pedido
    if not request.json or 'email_text' not in request.json:
        logging.warning("Pedido /analyze inválido: Falta 'email_text'.")
        return jsonify({"error": "Pedido inválido. Falta 'email_text'."}), 400

    email_text = request.json['email_text']
    if not email_text.strip():
        logging.warning("Pedido /analyze inválido: 'email_text' vazio.")
        return jsonify({"error": "O texto do email não pode estar vazio."}), 400

    logging.info("Iniciando Análise do Email (Prompt 1 via Gemini)")
    # Constrói o prompt de análise
    analysis_prompt = build_prompt_1_analysis(email_text)

    # Chama o LLM com temperatura mais baixa para análise focada
    llm_response_data = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.5)

    # Log da resposta bruta para depuração
    logging.info(f"DEBUG - Resposta Bruta Análise LLM: --------\n{llm_response_data}\n--------")

    # Verifica se houve erro na chamada à API
    if "error" in llm_response_data:
        # Determina o código de status HTTP apropriado
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Erro na chamada Gemini para /analyze: {llm_response_data['error']}")
        return jsonify({"error": f"Falha ao comunicar com o LLM para análise: {llm_response_data['error']}"}), status_code

    # Faz o parsing da resposta textual do LLM
    llm_response_text = llm_response_data.get("text", "")
    logging.info("Análise recebida do Gemini, a fazer parsing.")
    analysis_result = parse_analysis_output(llm_response_text)
    app.logger.debug(f"Resultado Parseado (Análise): {analysis_result}")

    # Verifica se o parsing retornou um erro
    if "error" in analysis_result:
        logging.error(f"Erro no parsing da análise: {analysis_result['error']}")
        # Retorna o erro de parsing e a resposta bruta para debug
        return jsonify({"error": f"Falha ao processar resposta da análise: {analysis_result['error']}", "raw_analysis": llm_response_text}), 500

    # Verificação adicional de consistência (opcional)
    if not analysis_result.get("points") and "nenhum ponto a responder" not in llm_response_text.lower():
        logging.warning("Parsing pode ter falhado. Resposta LLM não continha 'nenhum ponto', mas a lista de pontos está vazia.")

    logging.info("Análise processada com sucesso.")
    # Retorna os pontos e ações extraídos
    return jsonify(analysis_result)


@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance_route(): # Renomeado
    """Endpoint para gerar sugestão de texto para um ponto específico (Prompt 3)."""
    # Validação dos campos obrigatórios no JSON do pedido
    required_fields = ['original_email', 'point_to_address', 'persona_name']
    if not request.json:
        logging.warning("Pedido /suggest_guidance inválido: Sem JSON.")
        return jsonify({"error": "Pedido inválido (JSON esperado)."}), 400
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Pedido /suggest_guidance inválido: Faltam dados: {missing}")
        return jsonify({"error": f"Faltam dados no pedido: {', '.join(missing)}."}), 400

    original_email = request.json['original_email']
    point_to_address = request.json['point_to_address']
    persona_name = request.json['persona_name']
    # Obtém a direção (pode ser None se não for enviada)
    direction = request.json.get('direction')

    # Validações dos dados recebidos
    if not original_email.strip() or not point_to_address or point_to_address == 'N/A' or not persona_name.strip():
        logging.warning("Pedido /suggest_guidance inválido: Campos obrigatórios vazios ou inválidos.")
        return jsonify({"error": "Email original, ponto a abordar válido e nome da persona são obrigatórios."}), 400

    # Verifica se as personas foram carregadas
    if not PERSONAS:
        logging.error("Erro crítico: PERSONAS não carregadas, impossível processar /suggest_guidance.")
        return jsonify({"error": "Erro interno do servidor: Definições de persona não disponíveis."}), 500
    # Verifica se a persona selecionada existe
    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' não encontrada em /suggest_guidance.")
        return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 400

    selected_persona = PERSONAS[persona_name]
    logging.info(f"Solicitando sugestão de TEXTO via Gemini para ponto='{point_to_address[:50]}...' com Persona: {persona_name}, Direção: {direction}")

    # Constrói o prompt de sugestão
    suggestion_prompt = build_prompt_3_suggestion(original_email, point_to_address, selected_persona, direction)

    # Chama o LLM (usando temperatura padrão para sugestões mais criativas)
    llm_response_data = call_gemini(suggestion_prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE)

    # Verifica erros da API
    if "error" in llm_response_data:
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Erro na chamada Gemini para /suggest_guidance: {llm_response_data['error']}")
        return jsonify({"error": f"Falha ao obter sugestão do LLM: {llm_response_data['error']}"}), status_code

    # Extrai e limpa o texto da sugestão
    llm_response_text = llm_response_data.get("text", "").strip()
    logging.info("Sugestão de texto gerada com sucesso.")
    app.logger.debug(f"Sugestão gerada: {llm_response_text}")
    # Retorna a sugestão
    return jsonify({"suggestion": llm_response_text})


# --- ROTA /draft REFACTORADA para incluir Pré-Análise ---
@app.route('/draft', methods=['POST'])
def draft_response_route(): # Renomeado
    """
    Endpoint para gerar o rascunho da resposta final (Prompt 2),
    incluindo a pré-análise de contexto (Prompt 0).
    """
    # Validação do pedido JSON
    if not request.json:
        logging.warning("Pedido /draft inválido: Sem JSON.")
        return jsonify({"error": "Pedido inválido (JSON esperado)."}), 400

    required_fields = ['original_email', 'persona_name', 'user_inputs']
    if not all(field in request.json for field in required_fields):
        missing = [field for field in required_fields if field not in request.json]
        logging.warning(f"Pedido /draft inválido: Faltam dados: {missing}")
        return jsonify({"error": f"Faltam dados no pedido: {', '.join(missing)}."}), 400

    original_email = request.json['original_email']
    persona_name = request.json['persona_name']
    # user_inputs é a lista de {point: ..., guidance: ...}
    user_inputs = request.json['user_inputs']

    # Validações adicionais
    if not PERSONAS:
         logging.error("Erro crítico: PERSONAS não carregadas, impossível processar /draft.")
         return jsonify({"error": "Erro interno do servidor: Definições de persona não disponíveis."}), 500
    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' não encontrada em /draft.")
        return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 400
    if not isinstance(user_inputs, list):
        logging.error(f"Formato inválido para 'user_inputs' em /draft. Esperada lista, recebido: {type(user_inputs)}")
        return jsonify({"error": "Formato inválido para 'user_inputs'. Esperada uma lista de objetos."}), 400

    selected_persona = PERSONAS[persona_name]

    # --- PASSO 1: Pré-Análise de Contexto ---
    logging.info(f"Iniciando Pré-Análise de Contexto para /draft (Persona: {persona_name})")
    # Chama a função que executa o Prompt 0
    context_analysis_result = analyze_sender_and_context(original_email, selected_persona)

    # Verifica se a pré-análise retornou um erro crítico (ex: erro de API)
    # Erros de parsing retornam defaults e uma msg de erro, mas não bloqueiam.
    if context_analysis_result.get("error") and \
       "ERROR_PARSE_CONTEXT" not in context_analysis_result["error"] and \
       "ERROR_UNEXPECTED_CONTEXT" not in context_analysis_result["error"]:
         logging.error(f"Erro crítico durante a Pré-Análise de Contexto: {context_analysis_result['error']}")
         # Determina o status code apropriado para o erro da API
         status_code = 500
         error_msg_prefix = "Falha na pré-análise de contexto:"
         if "ERROR_GEMINI" in context_analysis_result["error"] or "ERROR_CONFIG" in context_analysis_result["error"]:
              status_code = 503 # Default para erros Gemini (pode ser ajustado)
              if "BLOCKED" in context_analysis_result["error"]: status_code = 400
              error_msg_prefix = "Erro na comunicação com LLM durante pré-análise:"
         # Retorna o erro que impediu a continuação
         return jsonify({"error": f"{error_msg_prefix} {context_analysis_result['error']}"}), status_code
    elif context_analysis_result.get("error"):
         # Loga o erro não crítico (parsing/inesperado), mas continua com os defaults
         logging.warning(f"Erro não crítico durante a Pré-Análise: {context_analysis_result['error']}. Continuando com defaults.")


    # --- PASSO 2: Geração do Rascunho (Prompt 2) ---
    logging.info(f"Iniciando Geração de Rascunho (Prompt 2 via Gemini) para Persona: {persona_name}")
    # Constrói o Prompt 2, passando o resultado da pré-análise
    draft_prompt = build_prompt_2_drafting(selected_persona, original_email, user_inputs, context_analysis_result)

    # Chama o LLM para gerar o rascunho
    llm_response_data = call_gemini(draft_prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE)

    # Verifica erros na geração do rascunho
    if "error" in llm_response_data:
        status_code = 503 if "TIMEOUT" in llm_response_data["error"] or "CONNECTION" in llm_response_data["error"] else 500
        if "CONFIG" in llm_response_data["error"] or "BLOCKED" in llm_response_data["error"]: status_code = 400
        logging.error(f"Erro na chamada Gemini para /draft (Geração): {llm_response_data['error']}")
        # Retorna o erro da geração e a análise de contexto usada (para debug)
        return jsonify({
            "error": f"Falha ao gerar rascunho com o LLM: {llm_response_data['error']}",
            "context_analysis": context_analysis_result # Inclui a análise para debug
            }), status_code

    # Extrai o rascunho final
    final_draft = llm_response_data.get("text", "").strip()
    logging.info(f"Rascunho Final Gerado com sucesso via Gemini para persona {persona_name}.")
    # Loga a análise de contexto usada e o rascunho final em modo debug
    app.logger.debug(f"Context Analysis Used: {context_analysis_result}")
    app.logger.debug(f"Rascunho Final:\n{final_draft}")

    # Retorna o rascunho e também a análise de contexto usada (pode ser útil no frontend)
    return jsonify({
        "draft": final_draft,
        "context_analysis": context_analysis_result
        })


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    # Logs iniciais ao arrancar a aplicação
    logging.info("--- Iniciando Flask App ---")
    logging.info(f"Host: {APP_HOST}")
    logging.info(f"Port: {APP_PORT}")
    logging.info(f"Debug Mode: {DEBUG_MODE}")
    logging.info(f"Gemini Model: {GEMINI_MODEL}")

    # Verifica e loga o estado da API Key (mascarada)
    if not GEMINI_API_KEY:
        logging.warning("Variável de ambiente GEMINI_API_KEY não definida!")
    else:
        # Mostra apenas os últimos 4 caracteres da chave
        logging.info(f"Gemini API Key: {'*' * (len(GEMINI_API_KEY) - 4)}{GEMINI_API_KEY[-4:]}")

    # Verifica e loga o estado do carregamento das personas
    if not PERSONAS:
         logging.warning("PERSONAS não foram carregadas! Funcionalidades de persona podem não operar corretamente.")
    else:
         logging.info(f"{len(PERSONAS)} personas carregadas.")
         # Lembra o utilizador de completar as definições no JSON
         logging.warning("Certifique-se de completar as Personas dos Professores (dos, donts, writing_examples) em 'personas.json' para melhores resultados.")

    logging.info(f"Default Generation Temperature: {GENERATION_TEMPERATURE}")

    # Inicia o servidor Flask
    # use_reloader=False é útil em debug para evitar que o código execute duas vezes ao iniciar
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)
