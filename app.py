# -*- coding: utf-8 -*-
import os
import json
import re
import requests
from flask import Flask, render_template, request, jsonify
import logging # Usar logging para melhor controlo das mensagens
from dotenv import load_dotenv # Import dotenv

# Load environment variables from .env file (optional but recommended)
load_dotenv()

# Configurar logging básico
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuração ---
APP_HOST = os.environ.get('APP_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('APP_PORT', 5001))
GENERATION_TEMPERATURE = float(os.environ.get('GENERATION_TEMPERATURE', 0.7))
DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# --- Gemini Configuration ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
# *** User confirmed this model version works for them ***
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash') # Using 1.5 Flash as per last successful run

# Diretoria base da aplicação
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Inicializa a aplicação Flask
app = Flask(__name__)
if DEBUG_MODE:
    app.logger.setLevel(logging.DEBUG)

# --- Definições Detalhadas das Personas ---
# (Persona definitions remain the same as provided by the user)
PERSONAS = {
    "rodrigo_novelo": {
        "name": "Rodrigo Novelo", # <<< REMOVIDO (Eu) DAQUI
        "role": "Aluno de Licenciatura em Engenharia Informática, ISEC/DEIS",
        "area": "Inteligência Artificial",
        "current_context": [
            "Projeto: Desenvolvimento de assistente LLM para emails (IA Generativa)",
            "Orientadores: Professor Rodrigo, Professor Jorge",
            "Disciplinas: Sistemas Operativos II, Encaminhamento de Dados"
        ],
        "description": "Estilo q.b. formal mas adaptável. Prefere emails diretos e informativos, estruturando bem os de atualização para orientadores (tópicos/listas). Mantém profissionalismo 'leve' com orientadores. Casual e direto com colegas.",
        "attributes": {
            "tone": "Adaptável (definido pelas regras)",
            "formality": "Variável (definido pelas regras)",
            "verbosity": "DiretoInformativo",
            "emoji_usage": "Nenhum",
            "language": "pt-PT"
        },
        "recipient_adaptation_rules": {
            # *** NOTA: Assinaturas aqui usam o nome da persona (agora sem "(Eu)") ***
            "professor": {"tone": "Formal", "greeting": "Caro(a) Professor(a) [Apelido],", "farewell": "Com os melhores cumprimentos,\nRodrigo Novelo"},
            "colleague_student": {"tone": "Casual", "greeting": "Olá [Nome],", "farewell": "Abraço,\nRodrigo"},
            "admin_services": {"tone": "FormalFuncional", "greeting": "Exmos(as). Senhores(as),", "farewell": "Com os melhores cumprimentos,\nRodrigo Novelo"},
            "external_formal": {"tone": "Formal", "greeting": "Boa tarde/noite,", "farewell": "Com os melhores cumprimentos,\nRodrigo Novelo"},
            "research_collaborator_external": {"tone": "FormalColaborativo", "greeting": "Estimado(a) Professor(a)/Doutor(a) [Apelido],", "farewell": "Com os melhores cumprimentos,\nRodrigo Novelo"},
            "conference_contact": {"tone": "SemiFormalProfissional", "greeting": "Caro(a) [Nome], (Referir conferência)", "farewell": "Atenciosamente,\nRodrigo Novelo"},
            "support_technical": {"tone": "Funcional", "greeting": "Bom dia/tarde,", "farewell": "Obrigado(a),\nRodrigo Novelo"},
            "group_mixed_formal": {"tone": "Formal", "greeting": "Bom dia a todos,", "farewell": "Com os melhores cumprimentos,\nRodrigo Novelo"},
            "unknown": {"tone": "Formal", "greeting": "Bom dia/tarde/noite,", "farewell": "Com os melhores cumprimentos,\nRodrigo Novelo"}
        },
        "relationships": {
            "Professor Rodrigo": {"type": "Orientador de Projeto", "tone": "ProfissionalLeveDescontraido", "greeting_individual": "Caro Professor Rodrigo,"},
            "Professor Jorge": {"type": "Orientador de Projeto", "tone": "ProfissionalLeveDescontraido", "greeting_individual": "Caro Professor Jorge,"}
        },
        "dos": [
            "Ser direto mas informativo.",
            "Estruturar emails de atualização para orientadores com tópicos/listas.",
            "Manter profissionalismo educado e 'leve' com orientadores.",
            "Adaptar formalidade e saudação/despedida ao tipo de destinatário.",
            "Ser formal com serviços administrativos e contactos externos formais.",
            "Ser casual e direto com colegas próximos."
        ],
        "donts": [
            "Ser vago.",
            "Usar linguagem demasiado informal com professores ou contactos formais/desconhecidos.",
            "Usar emojis."
        ],
        "writing_examples": [
            # Exemplos mantêm-se iguais...
             {"context": "Update formal para orientadores após reunião", "output_style_example": "Caros Professores,\n\nDurante a última reunião:\nDiscutimos a vertente prática do trabalho que desenvolvi ao longo da última semana, focada em técnicas de prompt engineering. Recebi recomendações muito úteis que irão orientar o desenvolvimento das próximas etapas.\n\nAo longo desta semana pretendo:\nEntregar a versão revista do survey ao Professor Jorge;\nInvestigar a possibilidade de utilização de um modelo LLM mais avançado e gratuito...\nCaso não seja viável..., irei focar-me em melhorar o código actual...\n\nAtenciosamente,\nRodrigo Novelo"},
             {"context": "Update formal para orientadores sobre progresso semanal", "output_style_example": "Boa tarde professores,\n\nSegue um pequeno resumo da última reunião e o que ficou proposto fazer durante esta semana.\n\nResumo da Reunião Anterior: apresentei uma pequena amostra de outputs criados por diversos modelos LLM... Contudo, como discutido, houve dificuldade em identificar padrões claros...\n\nProgresso Atual:\nConclusões mais objetivas sobre os modelos LLM:\nEstou a tentar usar 1 ou 2 benchmarks...\nAnalisar pros e contras...\nSurvey:\nDesenvolvimento da versão inicial...\nPretendo apresentar esta versão inicial na próxima quarta-feira...\n\nAtenciosamente,\nRodrigo Novelo."},
             {"context": "Pedido formal de estágio (Deloitte)", "output_style_example": "Boa noite,\n\nEstou a contactar para perguntar sobre a possibilidade de realizar um estágio Curricular na Deloitte, na área de Redes e Administração de Sistemas.\n\nAtualmente, estou na reta final da licenciatura em Engenharia Informática no ISEC, em Coimbra, e estou à procura de uma oportunidade para desenvolver as competências aprendidas...\n\nSe eventualmente houver abertura para receber estagiários..., estou disponível para enviar o meu CV...\n\nAgradeço desde já a sua atenção.\n\nCom os melhores cumprimentos,\nRodrigo Novelo"},
             {"context": "Pedido formal de estágio (AIRC)", "output_style_example": "Boa noite,\n\nEstou a contactar para perguntar sobre a possibilidade de realizar um estágio Curricular na AIRC, na área de Redes e Administração de Sistemas.\n\nAtualmente, estou na reta final da licenciatura em Engenharia Informática no ISEC, em Coimbra, e estou à procura de uma oportunidade para desenvolver as competências aprendidas...\n\nSe eventualmente houver abertura para receber estagiários..., estou disponível para enviar o meu CV...\n\nAgradeço desde já a sua atenção.\n\nCom os melhores cumprimentos,\nRodrigo Novelo"},
             {"context": "Casual - Partilhar descoberta tech com colega (João)", "output_style_example": "Boas João,\nJá experimentaste o novo modelo do GPT? Estive a testar umas automações com ele e está a dar resultados brutais, muito mais coerente que o anterior.\nDepois mostro-te o que fiz com integração no Notion — está mesmo incrivel.\nAbraço,\nRodrigo."},
             {"context": "Casual - Pedir ajuda técnica a colega (Miguel)", "output_style_example": "Boas Miguel,\n\nEstou preso naquela parte do módulo “Web Requests” no HackTheBox — acho que estou a fazer bem o encoding mas não passo do check. Tu conseguiste à primeira?\n\nSe tiveres uma dica, agradecia bastante.\nAbraço,\nRodrigo."},
             {"context": "Casual - Pedir sugestão técnica a colega (Rúben)", "output_style_example": "Boas Rúben,\n\nTiveste a experimentar o LLaMA 3 8B localmente? Consegui meter a correr com o Ollama, mas agora queria fazer uma ligação simples a uma página web que estou a montar (tipo fetch para mandar prompts e receber resposta).\n\nTens alguma sugestão rápida ou setup base que possa seguir? Não precisa de ser nada muito complexo, só quero começar a testar.\nAbraço,\nRodrigo."}
        ]
    },
    "prof_rodrigo": {
        "name": "Professor Rodrigo Rocha Silva",
        "role": "Pesquisador Associado (CISUC/DEIS/UC), Professor (Fatec Mogi das Cruzes)",
        "area": "Ciência da Computação (Arquitetura de Sistemas, Big Data, Data Mining, IA)",
        "current_context": [ "Orientador de Projeto (Assistente LLM)", "Interesses: Big Data, Data Mining, DW, NoSQL, Sentiment Analysis, IA Aplicada, Arquitetura de Sistemas" ],
        "description": "Professor e Investigador (UC & Fatec) com experiência em indústria e academia. Foco em Arquitetura de Sistemas, Big Data e IA. Estilo adaptável, usa Português do Brasil (pt-BR). ***(NECESSITA MAIS DETALHES E EXEMPLOS)***",
        "attributes": { "tone": "Adaptável (a definir)", "formality": "Variável (a definir)", "verbosity": "InformativoProfissional", "emoji_usage": "Nenhum", "language": "pt-BR" },
        "recipient_adaptation_rules": {
             "orientando_uc": {"tone": "OrientadorDireto", "greeting": "Prezado Rodrigo,", "farewell": "Atenciosamente,\nProf. Rodrigo Rocha Silva"},
             "professor_colega_uc": {"tone": "ProfissionalRespeitoso", "greeting": "Prezado Prof. [Apelido],", "farewell": "Atenciosamente,\nProf. Rodrigo Rocha Silva"},
             "unknown": {"tone": "Formal", "greeting": "Prezados(as),", "farewell": "Atenciosamente,\nProf. Rodrigo Rocha Silva"}
        },
        "relationships": {
             "Rodrigo Novelo": {"type": "Orientando (Licenciatura ISEC)", "tone": "OrientadorDireto"},
             "Professor Jorge": {"type": "Colega Investigador / Co-orientador", "tone": "ProfissionalRespeitoso"}
        },
        "dos": [ "*** (A DEFINIR - Adicionar Do's específicos do Prof. Rodrigo) ***" ],
        "donts": [ "*** (A DEFINIR - Adicionar Don'ts específicos do Prof. Rodrigo) ***" ],
        "writing_examples": [
            # <<< ADICIONAR EXEMPLOS DE ESCRITA REAIS DO PROF. RODRIGO AQUI >>>
        ]
    },
    "prof_jorge": {
        "name": "Professor Jorge Bernardino",
        "role": "Professor Coordenador (ISEC/DEIS)",
        "area": "Ciência da Computação (Big Data, Data Warehousing, BI, IoT, Eng. Software)",
        "current_context": [ "Orientador de Projeto (Assistente LLM)", "Experiência anterior: Presidente ISEC, Presidente Conselho Científico ISEC, Diretor i2A, Visiting Prof CMU", "Membro ACM e IEEE", "Interesses de investigação: Big Data, DW, BI, IoT, Eng. Software" ],
        "description": "Professor Coordenador no ISEC/DEIS com vasta experiência académica e de gestão. Investigação em Big Data, BI, IoT, Eng. Software. Utiliza Português de Portugal (pt-PT). ***(NECESSITA DETALHES DE ESTILO E EXEMPLOS)***",
        "attributes": { "tone": "ProfissionalAcadémico", "formality": "Alta", "verbosity": "Estruturado", "emoji_usage": "Nenhum", "language": "pt-PT" },
        "recipient_adaptation_rules": {
             "orientando_licenciatura": {"tone": "OrientadorFormal", "greeting": "Caro Rodrigo,", "farewell": "Com os melhores cumprimentos,\nJorge Bernardino"},
             "professor_colega_uc": {"tone": "ProfissionalRespeitoso", "greeting": "Caro Prof. [Apelido],", "farewell": "Com os melhores cumprimentos,\nJorge Bernardino"},
             "unknown": {"tone": "Formal", "greeting": "Exmo(a). Sr(a). [Apelido],", "farewell": "Com os melhores cumprimentos,\nJorge Bernardino"}
        },
        "relationships": {
             "Rodrigo Novelo": {"type": "Orientando (Licenciatura UC)", "tone": "OrientadorFormal"},
             "Professor Rodrigo": {"type": "Colega Investigador / Co-orientador", "tone": "ProfissionalRespeitoso"}
        },
        "dos": [ "*** (A DEFINIR - Adicionar Do's específicos do Prof. Jorge) ***" ],
        "donts": [ "*** (A DEFINIR - Adicionar Don'ts específicos do Prof. Jorge) ***" ],
        "writing_examples": [
            # <<< ADICIONAR EXEMPLOS DE ESCRITA REAIS DO PROF. JORGE AQUI >>>
        ]
    }
}


# --- Funções Auxiliares ---

def call_gemini(prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE):
    """
    Envia um prompt para a Google Gemini API e retorna a resposta.
    (Função call_gemini completa - sem alterações, reutilizada)
    """
    if not GEMINI_API_KEY:
        logging.error("Variável de ambiente GEMINI_API_KEY não definida!")
        return "ERROR_CONFIG: Gemini API Key não configurada."

    # Updated API endpoint for v1beta
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature
            # "maxOutputTokens": 8192,
            # "topP": 0.95,
        },
         "safetySettings": [ # Example safety settings
             {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
             {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
         ]
    }
    headers = {'Content-Type': 'application/json'}

    logging.info(f"Enviando para Gemini API | Modelo: {model} | Temp: {temperature}")
    app.logger.debug(f"Payload (primeiros 500): {str(payload)[:500]}...")
    response = None
    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=180)
        response.raise_for_status() # Raise HTTPError for bad responses

        data = response.json()
        app.logger.debug(f"Resposta API (parcial): {str(data)[:500]}...")

        # --- Careful response extraction ---
        try:
            if 'promptFeedback' in data and 'blockReason' in data['promptFeedback']:
                block_reason = data['promptFeedback']['blockReason']
                safety_ratings_str = f" Safety Ratings: {data['promptFeedback'].get('safetyRatings', 'N/A')}"
                error_msg = f"ERROR_GEMINI_BLOCKED_PROMPT: Prompt bloqueado. Reason: {block_reason}.{safety_ratings_str}"
                logging.error(f"{error_msg}. Feedback: {data['promptFeedback']}")
                return error_msg

            if 'candidates' in data and data['candidates']:
                candidate = data['candidates'][0]
                finish_reason = candidate.get('finishReason', 'UNKNOWN')
                safety_ratings_str = f" Safety Ratings: {candidate.get('safetyRatings', 'N/A')}"

                if finish_reason not in ['STOP', 'MAX_TOKENS']:
                    logging.warning(f"Gemini finishReason foi '{finish_reason}'. Resposta pode estar incompleta ou bloqueada.{safety_ratings_str}")
                    if finish_reason in ['SAFETY', 'RECITATION', 'OTHER']:
                        error_msg = f"ERROR_GEMINI_BLOCKED_FINISH: Geração interrompida. Reason: {finish_reason}.{safety_ratings_str}"
                        logging.error(error_msg)
                        return error_msg

                if 'content' in candidate and 'parts' in candidate['content'] and candidate['content']['parts']:
                    text_part = candidate['content']['parts'][0]
                    if 'text' in text_part:
                        generated_text = text_part['text']
                        return generated_text.strip()
                    else:
                        error_msg = f"ERROR_GEMINI_PARSE: 'text' key missing in response part. Part: {text_part}"
                        logging.error(error_msg)
                        return error_msg
                else:
                     error_msg = f"ERROR_GEMINI_PARSE: Missing 'content' or 'parts' in candidate. Candidate: {candidate}"
                     logging.error(error_msg)
                     return error_msg

            error_msg = f"ERROR_GEMINI_PARSE: Resposta inesperada - sem 'candidates' ou 'promptFeedback' com bloqueio. Data: {str(data)[:500]}"
            logging.error(error_msg)
            return error_msg

        except (KeyError, IndexError, TypeError) as e:
            error_msg = f"ERROR_GEMINI_PARSE: Exception accessing response data. Error: {e}. Data: {str(data)[:500]}"
            logging.exception("Error parsing Gemini response:")
            return error_msg

    except requests.exceptions.Timeout:
        error_msg = f"ERROR_GEMINI_TIMEOUT: Timeout (180s) ao contactar Gemini API."
        logging.error(error_msg)
        return error_msg
    except requests.exceptions.ConnectionError:
        error_msg = f"ERROR_GEMINI_CONNECTION: Falha na conexão com Gemini API."
        logging.error(error_msg)
        return error_msg
    except requests.exceptions.RequestException as e:
        error_details = ""
        status_code = "N/A"
        if response is not None:
            status_code = response.status_code
            try:
                error_content = response.json()
                error_details = error_content.get('error', {}).get('message', response.text)
            except (json.JSONDecodeError, AttributeError):
                 if hasattr(response, 'text'):
                     error_details = response.text[:200]
        error_msg = f"ERROR_GEMINI_REQUEST: {e} (Status: {status_code}) - Detalhes: {error_details}"
        logging.error(f"Erro ao chamar a API Gemini: {e}. Status: {status_code}. Detalhes: {error_details}")
        app.logger.debug(f"Payload que causou erro (parcial): {str(payload)[:500]}...")
        return error_msg
    except json.JSONDecodeError as e:
        error_msg = f"ERROR_JSON_DECODE: {e} - Resposta (início): {response.text[:200] if response is not None else 'N/A'}..."
        logging.error(f"Erro ao descodificar JSON da resposta Gemini: {e}")
        if response is not None:
             logging.error(f"Resposta completa recebida (status {response.status_code}): {response.text}")
        return error_msg
    except Exception as e:
        error_msg = f"ERROR_UNEXPECTED: {e.__class__.__name__} - {e}"
        logging.exception("Erro inesperado na função call_gemini:")
        return error_msg


def parse_analysis_output(llm_output):
    """
    Faz o parsing da saída textual do LLM (Prompt 1) para extrair pontos e ações.
    (Função parse_analysis_output completa - sem alterações aqui)
    """
    points = []
    actions = []
    if not llm_output or llm_output.startswith("ERROR_"):
        # Retorna o erro se existir, ou uma mensagem genérica se a saída for vazia
        return {"error": llm_output or "Empty or error response from LLM analysis"}

    # Regex mais flexível para o cabeçalho "Pontos a Responder"
    points_match = re.search(r"(?:points\s+to\s+address|pontos\s+a\s+responder)\s*:\s*\n*(.*?)(?:\n*\s*(?:\*\*|\_\_)(?:actions|ações)|$)", llm_output, re.IGNORECASE | re.DOTALL)
    if points_match:
        points_text = points_match.group(1).strip()
        # Verifica se o texto contém algo para além de "nenhum/none" (case-insensitive, opcional ponto final)
        if points_text and not re.search(r"^\s*(nenhum|none)\.?\s*$", points_text, re.IGNORECASE | re.MULTILINE):
            # Tenta encontrar itens numerados ou com bullets
            raw_points = re.findall(r"^\s*(?:\d+[\.\)]?|\*|\-)\s+(.*?)(?=\n\s*(?:\d+[\.\)]?|\*|\-)|\Z)", points_text, re.MULTILINE | re.DOTALL)
            points = [re.sub(r'\s+', ' ', p).strip() for p in raw_points if p.strip()]
            # Fallback: Se não encontrou itens estruturados mas havia texto, considera tudo como um ponto? (Opcional, pode ser confuso)
            # if not points and points_text:
            #    points = [points_text]
    elif "pontos a responder" in llm_output.lower() or "points to address" in llm_output.lower():
        logging.warning("Analysis parsing: Section 'Pontos a Responder' found but was empty or unparseable.")
    # Se não encontrou o cabeçalho de pontos, `points` permanecerá vazio.

    # Regex mais flexível para o cabeçalho "Ações para Rodrigo"
    actions_match = re.search(r"(?:actions\s+for\s+rodrigo|ações\s+para\s+rodrigo)\s*(?:\(optional|opcional\))?\s*:\s*\n*(.*?)(?:\n*\s*(?:\*\*|\_\_)|$)", llm_output, re.IGNORECASE | re.DOTALL)
    if actions_match:
        actions_text = actions_match.group(1).strip()
        if actions_text and not re.search(r"^\s*(nenhum|none|nenhuma)\.?\s*$", actions_text, re.IGNORECASE | re.MULTILINE):
            # Tenta encontrar itens com bullets
            raw_actions = re.findall(r"^\s*[\*\-]\s+(.*?)(?=\n\s*[\*\-]|\Z)", actions_text, re.MULTILINE | re.DOTALL)
            actions = [re.sub(r'\s+', ' ', a).strip() for a in raw_actions if a.strip()]
            # Fallback? (Opcional)
            # if not actions and actions_text:
            #    actions = [actions_text]

    # Se o parsing não encontrou nada estruturado, mas havia texto, loga aviso
    if not points and not actions and not llm_output.startswith("ERROR_") and llm_output.strip():
        if not points_match and not actions_match:
             logging.warning(f"Analysis parsing: Could not find 'Pontos a Responder' or 'Ações' structure. LLM output (start): {llm_output[:200]}...")
        else:
             logging.warning(f"Analysis parsing: Found headers but failed to extract list items. LLM output (start): {llm_output[:200]}...")

    # Normaliza o caso de "nenhum ponto" explicitamente retornado pelo LLM
    if not points and re.search(r"nenhum ponto a responder", llm_output, re.IGNORECASE):
        points = ["Nenhum ponto a responder."] # Garante consistência

    return {"points": points or [], "actions": actions or []}


def build_prompt_1_analysis(email_text):
    """
    Constrói o prompt para solicitar a análise do email ao LLM (Prompt 1).
    *** VERSÃO REFINADA PARA SER MAIS CLARA ***
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


def build_prompt_2_drafting(persona, original_email, user_inputs):
    """
    Constrói o prompt complexo para solicitar a geração do rascunho da resposta (Prompt 2).
    (Função build_prompt_2_drafting completa - sem alterações aqui)
    """
    persona_lang = persona.get("attributes", {}).get("language", "pt-PT")
    if persona_lang == "pt-BR":
        lang_instruction = "Escreve **exclusivamente** em **Português do Brasil (pt-BR)** de forma **natural e fluída**. Evita construções de Portugal."
        lang_instruction_short = "LINGUAGEM pt-BR natural"
    else:
        lang_instruction = "Escreve **exclusivamente** em **Português de Portugal (pt-PT)** de forma **natural e fluída**. Evita construções do Brasil (ex: gerúndio excessivo)."
        lang_instruction_short = "LINGUAGEM pt-PT natural"

    # --- Extrair Nome do Remetente (Tentativa Simples) ---
    sender_name_guess = "Destinatário" # Default
    match_from = re.search(r"^(?:De|From):\s*\"?([^\<\"(]+?)[\"\s]*[<(].*", original_email, re.MULTILINE | re.IGNORECASE)
    match_plain = re.search(r"^\s*Ol[áa]\s+([^\s,;!]+)", original_email, re.MULTILINE | re.IGNORECASE) # Tenta saudações
    match_farewell = re.search(r"\n(?:Abra[çc]o|Cumprimentos|Atenciosamente|Obrigad[oa])(?:,|:)?\s*([^\n]+)$", original_email, re.MULTILINE | re.IGNORECASE) # Tenta assinatura

    if match_from:
        sender_name_guess = match_from.group(1).strip().title()
    elif match_farewell:
         sender_name_guess = match_farewell.group(1).strip().title()
         # Avoid picking up titles like 'Prof.' if possible from farewell
         sender_name_guess = re.sub(r'^(Prof\.?|Dr\.?|Eng\.?)\s+', '', sender_name_guess).strip()
    elif match_plain:
        sender_name_guess = match_plain.group(1).strip().title()

    # --- Determinar tipo de destinatário e regras (Simplificado) ---
    recipient_type = "unknown" # Default
    # Basic keyword check in email or sender name (could be improved)
    if "professor" in original_email.lower() or "prof." in sender_name_guess.lower():
        recipient_type = "professor"
    elif "joão" in sender_name_guess.lower() or "miguel" in sender_name_guess.lower() or "rúben" in sender_name_guess.lower():
         # Assuming these are colleagues based on examples
         recipient_type = "colleague_student"

    rules = persona.get("recipient_adaptation_rules", {})
    adapt_rules = rules.get(recipient_type, rules.get("unknown", {})) # Fallback to unknown

    # --- Obter Saudação/Despedida ---
    # Use specific relationship greeting/farewell if available
    if sender_name_guess in persona.get("relationships", {}):
         relationship_data = persona["relationships"][sender_name_guess]
         final_greeting = relationship_data.get("greeting_individual", adapt_rules.get("greeting", "Olá,"))
         final_farewell = adapt_rules.get("farewell", persona.get('attributes', {}).get('farewell', f"Cumprimentos,\n{persona['name']}")) # Relationship specific farewell? Add if needed.
    else:
        # Use generic rule greeting/farewell, replacing placeholders
         final_greeting = adapt_rules.get("greeting", "Olá [Nome],")
         final_greeting = final_greeting.replace("[Apelido]", sender_name_guess).replace("[Nome]", sender_name_guess)
         final_farewell = adapt_rules.get("farewell", persona.get('attributes', {}).get('farewell', f"Cumprimentos,\n{persona['name']}"))

    # --- System Prompt ---
    system_prompt = f"""System: **TU ÉS {persona['name']}**. A tua tarefa é gerar um email de resposta de ALTA QUALIDADE, escrito por ti ({persona['name']}) PARA {sender_name_guess}. Assume integralmente o teu papel ({persona.get('role', 'Assistente')}) e adota rigorosamente a seguinte Persona:
* **Nome da Persona:** {persona['name']}
* **Descrição Geral:** {persona.get('description', 'Estilo padrão')}
* **Tom & Formalidade:** (Adaptados para '{recipient_type}' conforme regras: Tom '{adapt_rules.get('tone', 'N/A')}', Formalidade '{adapt_rules.get('formality', persona.get('attributes', {}).get('formality', 'Média'))}')
* **Verbosidade:** {persona.get('attributes', {}).get('verbosity', 'Média')}
* **Uso de Emojis:** {persona.get('attributes', {}).get('emoji_usage', 'Nenhum')}

**Regras Essenciais de Escrita:**
* **Qualidade:** Produz uma resposta bem escrita, humana, natural e profissional (ou adaptada à formalidade). O texto deve fluir bem.
* **Linguagem:** {lang_instruction} Presta atenção ao vocabulário e tratamento específicos da variante e formalidade.
* **Clareza e Concisão:** Vai direto ao ponto, mas mantém a cordialidade. **Evita repetições desnecessárias**. Garante leitura fácil.
* **Contexto:** Responde diretamente ao email original e às orientações dadas.

**Regras OBRIGATÓRIAS "Faz" (Do's de {persona['name']}):**
{chr(10).join([f'* {rule}' for rule in persona.get('dos', ['Ser claro.'])])}

**Regras OBRIGATÓRIAS "Não Faças" (Don'ts de {persona['name']}):**
{chr(10).join([f'* {rule}' for rule in persona.get('donts', ['Ser vago.'])])}

**Formato OBRIGATÓRIO da Resposta:**
* **Saudação:** Começa **DIRETAMENTE** com: `{final_greeting}`
* **Despedida:** Termina **EXATAMENTE** com:
{final_farewell}
* **Corpo Apenas:** Gera **APENAS** o corpo do email (saudação, conteúdo, despedida/assinatura). Sem cabeçalhos nem texto extra.

--- FIM DAS INSTRUÇÕES DE SISTEMA ---
"""
    # --- Few-Shot Examples ---
    examples_prompt = ""
    writing_examples = persona.get("writing_examples")
    if writing_examples:
        examples_prompt += f"\n**Exemplos de Estilo de Escrita para {persona['name']} (Usa apenas como Guia de Estilo):**\n"
        limited_examples = writing_examples[:3] # Limit to save tokens
        for i, example in enumerate(limited_examples):
            context_desc = example.get("context", f"Exemplo {i+1}")
            output_example = example.get("output_style_example", "")
            if output_example:
                examples_prompt += f"\n---\nContexto Exemplo {i+1}: {context_desc}\nTexto Exemplo:\n{output_example}\n"
        examples_prompt += f"---\n\n--- FIM DOS EXEMPLOS DE ESTILO ---\n"

    # --- Contexto e Orientações ---
    context_prompt = f"""\nContexto: Email Original Recebido de '{sender_name_guess}' (Estás a responder a este email/pessoa)
---
{original_email}
---

"""
    items_prompt = f"Itens a Abordar & Informação Chave/Pontos Essenciais Fornecidos por Ti ({persona['name']}) para Construir a Resposta:\n"
    if user_inputs:
        has_real_points = False
        guidance_provided = False
        for i, item in enumerate(user_inputs):
            point = item.get('point', 'N/A')
            guidance = item.get('guidance', '')
            if guidance: guidance_provided = True

            is_placeholder_point = point == 'N/A' or point == "null" or point.lower().startswith("nenhum ponto")

            if not is_placeholder_point:
                items_prompt += f"* Ponto Original {i+1} a Abordar: \"{point}\"\n"
                items_prompt += f"    * Informação/Ideias Chave para a Tua Resposta: \"{guidance if guidance else '(Nenhuma orientação específica dada - responde apropriadamente)'}\"\n"
                has_real_points = True
            elif guidance: # Guidance for general response
                items_prompt += f"* Tua Orientação Geral (a incorporar na resposta): \"{guidance}\"\n"

        if not has_real_points and not guidance_provided:
             items_prompt += "* Tarefa Adicional: Escrever uma resposta curta e apropriada (ex: agradecimento, confirmação simples) baseada apenas no email original e na tua persona.\n"
        elif not has_real_points and guidance_provided:
             items_prompt += "* Tarefa Adicional: Incorpora a(s) orientação(ões) geral(is) acima numa resposta apropriada ao email original, seguindo a tua persona.\n"

    else: # No user_inputs array provided
        items_prompt += "* Tarefa Adicional: Escrever uma resposta curta e apropriada baseada apenas no email original e na tua persona.\n"
    items_prompt += "\n"

    # --- Task Prompt ---
    task_prompt = f"""Tarefa Final: Com base em TUDO o que foi dito acima (Instruções, Exemplos, Contexto, Informação Chave), redige agora o corpo COMPLETO e de ALTA QUALIDADE do email de resposta.
* Integra TODA a 'Informação/Ideias Chave' tua de forma **natural, humana e coesa** no texto. **Adapta** o texto para fluir bem dentro do email.
* **IMPORTANTE:** NÃO copies a 'Informação/Ideias Chave' literalmente. **Usa essa informação como BASE** para construir as tuas próprias frases, mantendo o fluxo da conversa e o teu estilo.
* Garante que a resposta final é bem escrita, clara, relevante para o email original e aborda o necessário.
* Mantém-te ESTRITAMENTE FIEL à Persona {persona['name']} ({lang_instruction_short}, tom, estilo, regras Do/Don't, saudação, despedida).
* Lembra-te: Gera APENAS o corpo do email. Não adiciones comentários nem cabeçalhos.

Resposta Gerada:
"""

    # --- Combinar e Retornar ---
    full_prompt = system_prompt + examples_prompt + context_prompt + items_prompt + task_prompt
    if DEBUG_MODE:
        prompt_hash = hash(full_prompt)
        logging.debug(f"--- DEBUG: PROMPT 2 (Drafting) Persona: {persona['name']} / Hash: {prompt_hash} ---")
        logging.debug(f"Prompt 2 Length: {len(full_prompt)} chars")
        log_limit = 4000
        logging.debug(full_prompt[:log_limit] + "..." if len(full_prompt) > log_limit else full_prompt)
        logging.debug("--- FIM DEBUG PROMPT 2 ---")
    return full_prompt


# <<< MODIFICAÇÃO AQUI >>>
def build_prompt_3_suggestion(original_email, point_to_address, persona, direction=None):
    """
    Constrói o prompt para solicitar uma SUGESTÃO DE TEXTO DE RESPOSTA
    para um ponto específico, seguindo a persona (Prompt 3),
    INCLUINDO A DIREÇÃO (Sim/Não/Outro) fornecida pelo utilizador.
    """
    persona_lang = persona.get("attributes", {}).get("language", "pt-PT")
    if persona_lang == "pt-BR":
        lang_instruction = "Escreve **exclusivamente** em **Português do Brasil (pt-BR)** e soa natural."
    else:
        lang_instruction = "Escreve **exclusivamente** em **Português de Portugal (pt-PT)** e soa natural."

    # --- Construir a instrução de direção ---
    direction_instruction = ""
    if direction == "sim":
        direction_instruction = "\n**Instrução Adicional Importante:** O utilizador indicou que a resposta a este ponto deve ser **AFIRMATIVA / POSITIVA ('Sim')**. Baseia a tua sugestão nesta direção, mantendo a persona."
    elif direction == "nao":
        direction_instruction = "\n**Instrução Adicional Importante:** O utilizador indicou que a resposta a este ponto deve ser **NEGATIVA ('Não')**. Baseia a tua sugestão nesta direção, mantendo a persona."
    # Se direction for "outro" ou None/vazio, nenhuma instrução é adicionada.

    # --- Construir o prompt completo ---
    system_prompt = f"""System: A tua tarefa é gerar uma sugestão CURTA (idealmente 1-2 frases concisas) de texto de resposta para um ponto específico de um email. Deves agir EXATAMENTE como {persona['name']}, adotando a seguinte Persona:
* **Nome:** {persona['name']} ({persona.get('role', '')})
* **Tom Geral:** {persona.get('attributes', {}).get('tone', 'Neutro')}
* **Formalidade:** {persona.get('attributes', {}).get('formality', 'Média')}
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

Contexto: Email Original Recebido
---
{original_email}
---

Ponto Específico do Email Original a Abordar: "{point_to_address}"

Tarefa: Escreve agora a sugestão de texto que {persona['name']} poderia usar na sua resposta para abordar APENAS este ponto específico, seguindo TODAS as regras e a instrução adicional (se existir) acima. Sê conciso e direto ao ponto.

Sugestão de Texto de Resposta para este Ponto:
"""
    return system_prompt


# --- Rotas da Aplicação Flask ---

@app.route('/')
def index_route(): # Renamed function to avoid conflict with imported index
    """Renderiza a página HTML inicial."""
    logging.info("A servir a página inicial (index.html)")
    personas_display = {}
    for key, data in PERSONAS.items():
        personas_display[key] = data.copy()
    return render_template('index.html', personas_dict=personas_display)


@app.route('/analyze', methods=['POST'])
def analyze_email():
    """Endpoint para analisar o email recebido usando Gemini."""
    if not request.json or 'email_text' not in request.json:
        logging.warning("Pedido /analyze inválido: Falta 'email_text'.")
        return jsonify({"error": "Pedido inválido. Falta 'email_text'."}), 400

    email_text = request.json['email_text']
    if not email_text.strip():
        logging.warning("Pedido /analyze inválido: 'email_text' vazio.")
        return jsonify({"error": "O texto do email não pode estar vazio."}), 400

    logging.info("Iniciando Análise do Email (Prompt 1 via Gemini)")
    # *** USANDO PROMPT REFINADO ***
    analysis_prompt = build_prompt_1_analysis(email_text)

    # *** USANDO TEMPERATURA LIGEIRAMENTE MAIS ALTA PARA ANÁLISE ***
    llm_response = call_gemini(analysis_prompt, model=GEMINI_MODEL, temperature=0.5) # Increased temp slightly

    # Log da resposta bruta para depuração
    logging.info(f"DEBUG - Resposta Bruta Análise LLM: --------\n{llm_response}\n--------")

    if not llm_response or llm_response.startswith("ERROR_"):
        status_code = 503 if "TIMEOUT" in llm_response or "CONNECTION" in llm_response else 500
        if "CONFIG" in llm_response or "BLOCKED" in llm_response: status_code = 400
        logging.error(f"Erro na chamada Gemini para /analyze: {llm_response}")
        # Tenta retornar o erro específico se existir, caso contrário uma mensagem genérica
        error_msg = llm_response if llm_response else "Resposta vazia ou erro desconhecido do LLM."
        return jsonify({"error": f"Falha ao comunicar com o LLM para análise: {error_msg}"}), status_code

    logging.info("Análise recebida do Gemini, a fazer parsing.")
    analysis_result = parse_analysis_output(llm_response)
    app.logger.debug(f"Resultado Parseado (Análise): {analysis_result}")

    # Verifica se o parsing em si retornou um erro ou se não encontrou pontos/ações mas deveria
    if "error" in analysis_result:
        logging.error(f"Erro no parsing da análise: {analysis_result['error']}")
        return jsonify({"error": f"Falha ao processar resposta da análise: {analysis_result['error']}", "raw_analysis": llm_response}), 500
    # Adiciona uma verificação extra: se a resposta bruta não for "nenhum ponto..." mas o parsing não encontrou nada, indica problema
    if not analysis_result.get("points") and "nenhum ponto a responder" not in llm_response.lower():
         logging.warning("Parsing pode ter falhado. Resposta LLM não continha 'nenhum ponto', mas a lista de pontos está vazia.")
         # Opcional: retornar um aviso ao frontend?
         # return jsonify({**analysis_result, "warning": "LLM response structure might not match expected format."})


    logging.info("Análise processada com sucesso.")
    return jsonify(analysis_result)


# <<< MODIFICAÇÃO AQUI >>>
@app.route('/suggest_guidance', methods=['POST'])
def suggest_guidance():
    """Endpoint para gerar sugestão de texto para um ponto, usando Gemini, incluindo a direção."""
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
    # Extrai a direção (pode ser None/null se não for enviado ou nenhum rádio selecionado)
    direction = request.json.get('direction') # <<< OBTÉM A DIREÇÃO

    # Validações básicas
    if not original_email.strip() or not point_to_address or point_to_address == 'N/A' or not persona_name.strip():
        logging.warning("Pedido /suggest_guidance inválido: Campos obrigatórios vazios ou inválidos (point_to_address='N/A').")
        return jsonify({"error": "Email original, ponto a abordar válido e nome da persona são obrigatórios."}), 400
    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' não encontrada em /suggest_guidance.")
        return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 400

    selected_persona = PERSONAS[persona_name]
    logging.info(f"Solicitando sugestão de TEXTO via Gemini para ponto='{point_to_address[:50]}...' com Persona: {persona_name}, Direção: {direction}") # Log da direção

    # Passa a 'direction' para a função que constrói o prompt
    suggestion_prompt = build_prompt_3_suggestion(original_email, point_to_address, selected_persona, direction) # <<< PASSA A DIREÇÃO

    # Usa a temperatura geral para sugestões (pode ser ajustada se necessário)
    llm_response = call_gemini(suggestion_prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE)

    if not llm_response or llm_response.startswith("ERROR_"):
        status_code = 503 if "TIMEOUT" in llm_response or "CONNECTION" in llm_response else 500
        if "CONFIG" in llm_response or "BLOCKED" in llm_response: status_code = 400
        logging.error(f"Erro na chamada Gemini para /suggest_guidance: {llm_response}")
        error_msg = llm_response if llm_response else "Resposta vazia ou erro desconhecido do LLM."
        return jsonify({"error": f"Falha ao obter sugestão do LLM: {error_msg}"}), status_code

    logging.info("Sugestão de texto gerada com sucesso.")
    app.logger.debug(f"Sugestão gerada: {llm_response}")
    return jsonify({"suggestion": llm_response.strip()})


@app.route('/draft', methods=['POST'])
def draft_response():
    """Endpoint para gerar o rascunho da resposta final usando Gemini."""
    # (Código da rota /draft permanece igual ao fornecido pelo utilizador)
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
    user_inputs = request.json['user_inputs'] # Lista de {"point": "...", "guidance": "..."}

    if persona_name not in PERSONAS:
        logging.error(f"Persona '{persona_name}' não encontrada em /draft.")
        return jsonify({"error": f"Persona '{persona_name}' não encontrada."}), 400
    if not isinstance(user_inputs, list):
        logging.error(f"Formato inválido para 'user_inputs' em /draft. Esperada lista, recebido: {type(user_inputs)}")
        return jsonify({"error": "Formato inválido para 'user_inputs'. Esperada uma lista de objetos."}), 400

    selected_persona = PERSONAS[persona_name]
    logging.info(f"Iniciando Geração de Rascunho (Prompt 2 via Gemini) para Persona: {persona_name}")
    draft_prompt = build_prompt_2_drafting(selected_persona, original_email, user_inputs)

    llm_response = call_gemini(draft_prompt, model=GEMINI_MODEL, temperature=GENERATION_TEMPERATURE)

    if not llm_response or llm_response.startswith("ERROR_"):
        status_code = 503 if "TIMEOUT" in llm_response or "CONNECTION" in llm_response else 500
        if "CONFIG" in llm_response or "BLOCKED" in llm_response: status_code = 400
        logging.error(f"Erro na chamada Gemini para /draft: {llm_response}")
        error_msg = llm_response if llm_response else "Resposta vazia ou erro desconhecido do LLM."
        return jsonify({"error": f"Falha ao gerar rascunho com o LLM: {error_msg}"}), status_code

    final_draft = llm_response
    logging.info(f"Rascunho Final Gerado com sucesso via Gemini para persona {persona_name}.")
    app.logger.debug(f"Rascunho Final:\n{final_draft}")

    return jsonify({"draft": final_draft})


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    logging.info("--- Iniciando Flask App ---")
    logging.info(f"Host: {APP_HOST}")
    logging.info(f"Port: {APP_PORT}")
    logging.info(f"Debug Mode: {DEBUG_MODE}")
    logging.info(f"Gemini Model: {GEMINI_MODEL}")
    if not GEMINI_API_KEY:
        logging.warning("Variável de ambiente GEMINI_API_KEY não definida!")
    else:
        logging.info(f"Gemini API Key: {'*' * (len(GEMINI_API_KEY) - 4)}{GEMINI_API_KEY[-4:]}") # Mask key
    logging.info(f"Default Generation Temperature: {GENERATION_TEMPERATURE}")
    logging.warning("Certifique-se de completar as Personas dos Professores (dos, donts, writing_examples) para melhores resultados.")

    # Renomeei a função da rota '/' para index_route para evitar conflito com 'import index' se existisse
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG_MODE)