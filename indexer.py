import json
from sentence_transformers import SentenceTransformer
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Garante que o GEMINI_API_KEY não é necessário para este script
os.environ.pop('GEMINI_API_KEY', None)

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
ontology_file = 'personas2.0.json'

try:
    with open(ontology_file, 'r+', encoding='utf-8') as f:
        data = json.load(f)

        all_memories = data.get('base_knowledge', [])
        for persona in data.get('personas', {}).values():
            all_memories.extend(persona.get('personal_knowledge_base', []))

        logging.info(f"A processar {len(all_memories)} memórias para indexação semântica.")
        
        updated_count = 0
        for memory in all_memories:
            # A GRANDE MUDANÇA: Combinamos o label e o value para dar mais contexto
            label = memory.get('label', '')
            value = memory.get('value', '')
            text_to_embed = f"{label}: {value}"
            
            if text_to_embed:
                embedding = model.encode(text_to_embed).tolist()
                memory['embedding'] = embedding
                updated_count += 1

        f.seek(0)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.truncate()

    logging.info(f"Indexação concluída. {updated_count} memórias foram atualizadas com embeddings em '{ontology_file}'.")

except Exception as e:
    logging.error(f"Ocorreu um erro inesperado: {e}")