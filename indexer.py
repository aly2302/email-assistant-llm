import json
from sentence_transformers import SentenceTransformer
import logging
import os

# Configuração do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Garante que as variáveis de ambiente do Flask/Gemini não interferem
os.environ.pop('GEMINI_API_KEY', None)

# Carrega o modelo de embedding
try:
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
except Exception as e:
    logging.error(f"Falha ao carregar o modelo SentenceTransformer. Verifique a sua conexão à internet ou a instalação. Erro: {e}")
    exit()

ontology_file = 'personas2.0.json'

try:
    with open(ontology_file, 'r+', encoding='utf-8') as f:
        data = json.load(f)

        # --- INÍCIO DA CORREÇÃO ---
        # Cria uma lista temporária e independente para processar, em vez de modificar a original.
        # O .copy() é a chave para evitar o bug de duplicação.
        memories_to_process = data.get('base_knowledge', []).copy()
        for persona in data.get('personas', {}).values():
            memories_to_process.extend(persona.get('personal_knowledge_base', []))
        # --- FIM DA CORREÇÃO ---

        logging.info(f"A processar {len(memories_to_process)} memórias para indexação semântica.")
        
        updated_count = 0
        # O loop agora itera sobre a cópia segura
        for memory in memories_to_process:
            label = memory.get('label', '')
            value = memory.get('value', '')
            text_to_embed = f"{label}: {value}"
            
            if text_to_embed.strip() != ":":
                embedding = model.encode(text_to_embed).tolist()
                # A alteração do embedding continua a ser feita no objeto original dentro de 'data', o que está correto.
                memory['embedding'] = embedding
                updated_count += 1

        # Volta ao início do ficheiro para o reescrever com os dados corretos e não modificados
        f.seek(0)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.truncate()

    logging.info(f"Indexação concluída. {updated_count} memórias foram atualizadas com embeddings em '{ontology_file}'.")

except FileNotFoundError:
    logging.error(f"ERRO: O ficheiro '{ontology_file}' não foi encontrado. Execute este script na mesma diretoria que o seu ficheiro de personas.")
except Exception as e:
    logging.error(f"Ocorreu um erro inesperado durante a indexação: {e}")
