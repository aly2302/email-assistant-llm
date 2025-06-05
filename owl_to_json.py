import json
import os
from rdflib import Graph, Namespace, URIRef # URIRef é importante
from rdflib.namespace import RDF, RDFS, OWL, XSD

# --- Configuração de Namespaces ---
ACADEMIC_NS_STR = "http://www.semanticweb.org/ontologies/2025/5/academicEmailPersona#"
ACADEMIC_NS = Namespace(ACADEMIC_NS_STR)

# --- Funções Auxiliares Melhoradas ---
def get_literal_value(graph, subject, predicate, lang="pt", default=None):
    if not subject or not predicate:
        return default
    val_lang = None
    val_no_lang = None
    val_other_lang = None

    for obj in graph.objects(subject, predicate):
        if hasattr(obj, 'language') and obj.language == lang:
            val_lang = str(obj)
            break 
        elif hasattr(obj, 'value') and (not hasattr(obj, 'language') or obj.language is None): # Literal sem idioma
            if val_no_lang is None: val_no_lang = str(obj) # Captura o primeiro sem idioma
        elif hasattr(obj, 'value'): # Outro idioma
            if val_other_lang is None: val_other_lang = str(obj) # Captura o primeiro de outro idioma
        elif not hasattr(obj, 'value') and not hasattr(obj, 'language') and val_no_lang is None: # Literal simples (raro, mas por segurança)
             val_no_lang = str(obj)

    if val_lang is not None: return val_lang
    if val_no_lang is not None: return val_no_lang
    if val_other_lang is not None: return val_other_lang # Fallback para outro idioma
    
    # Se ainda nada foi encontrado, tenta um graph.value (menos específico sobre literais)
    value_from_graph = graph.value(subject, predicate)
    if value_from_graph is not None:
        return str(value_from_graph)
        
    return default

def get_literal_list(graph, subject, predicate, lang="pt"):
    if not subject or not predicate:
        return []
    values_lang = []
    values_no_lang = []
    values_other_lang = []
    for obj in graph.objects(subject, predicate):
        if hasattr(obj, 'language') and obj.language == lang:
            values_lang.append(str(obj))
        elif hasattr(obj, 'value') and (not hasattr(obj, 'language') or obj.language is None):
            values_no_lang.append(str(obj))
        elif hasattr(obj, 'value'):
            values_other_lang.append(str(obj))
        elif not hasattr(obj, 'language'): 
             values_no_lang.append(str(obj))
    
    final_list = []
    # Prioriza pela ordem: idioma específico, sem idioma, outros idiomas
    if values_lang: final_list.extend(values_lang)
    elif values_no_lang: final_list.extend(values_no_lang) # Usa SEM idioma se PT não encontrado
    else: final_list.extend(values_other_lang) # Por último, outros idiomas
    
    return list(set(final_list))

def get_iri_value(graph, subject, predicate, default=None):
    if not subject or not predicate: return default
    value = graph.value(subject, predicate)
    return str(value) if value else default

def get_iri_list(graph, subject, predicate):
    if not subject or not predicate: return []
    return [str(obj) for obj in graph.objects(subject, predicate) if isinstance(obj, URIRef)]

def get_entity_key(iri_str):
    if not iri_str: return None
    return iri_str.split('#')[-1]

def extract_style_guidance_profile_details(g, sgp_iri_ref): # Aceita URIRef
    if not sgp_iri_ref: return {}
    
    profile_data = {
        "profile_iri": str(sgp_iri_ref),
        "profile_label_pt": get_literal_value(g, sgp_iri_ref, RDFS.label, lang="pt"),
        "tone_elements": [],
        "formality_element": {},
        "primary_communication_goal": {}
    }

    # Tone Elements
    for te_iri_obj in g.objects(sgp_iri_ref, ACADEMIC_NS.includesToneElement):
        if isinstance(te_iri_obj, URIRef): # Verifica se é um IRI antes de usar como sujeito
            tone_el = {
                "iri": str(te_iri_obj),
                "label_pt": get_literal_value(g, te_iri_obj, ACADEMIC_NS.label, lang="pt"),
                "intensity": float(get_literal_value(g, te_iri_obj, ACADEMIC_NS.toneIntensity, default="0.0")),
                "keywords_pt": get_literal_list(g, te_iri_obj, ACADEMIC_NS.toneKeyword, lang="pt"),
                "avoid_keywords_pt": get_literal_list(g, te_iri_obj, ACADEMIC_NS.avoidToneKeyword, lang="pt")
            }
            profile_data["tone_elements"].append(tone_el)

    # Formality Element
    fe_iri = g.value(sgp_iri_ref, ACADEMIC_NS.specifiesFormalityElement)
    if fe_iri and isinstance(fe_iri, URIRef):
        profile_data["formality_element"] = {
            "iri": str(fe_iri),
            "label_pt": get_literal_value(g, fe_iri, ACADEMIC_NS.label, lang="pt"),
            "level_numeric": int(get_literal_value(g, fe_iri, ACADEMIC_NS.formalityLevelNumeric, default="0")),
            "guidance_notes_pt": get_literal_value(g, fe_iri, ACADEMIC_NS.formalityGuidanceNotes, lang="pt")
        }

    # Communication Goal
    cg_iri = g.value(sgp_iri_ref, ACADEMIC_NS.hasPrimaryCommunicationGoal)
    if cg_iri and isinstance(cg_iri, URIRef):
        profile_data["primary_communication_goal"] = {
            "iri": str(cg_iri),
            "label_pt": get_literal_value(g, cg_iri, RDFS.label, lang="pt"),
            "goal_key": get_literal_value(g, cg_iri, ACADEMIC_NS.label, lang="pt", default=get_entity_key(str(cg_iri))),
            "description_pt": get_literal_value(g, cg_iri, ACADEMIC_NS.goalDescription, lang="pt")
        }
    return profile_data

# --- Função Principal de Extração ---
def extract_ontology_data(owl_file_path):
    g = Graph()
    g.parse(owl_file_path, format="turtle")
    g.bind("academic", ACADEMIC_NS)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("owl", OWL)
    g.bind("xsd", XSD)

    ontology_export_data = {
        "personas": {},
        "generic_recipient_adaptation_rules": {},
        "global_ia_settings": {"options": {}},
        "academic_email_categories": {}
    }
    personas_dict = ontology_export_data["personas"]

    query_persona_archetypes = """
        SELECT ?archetype ?archetypeLabel ?roleTemplate ?description ?commAttrIRI ?baseStyleProfileIRI
        WHERE {
            { ?archetype rdf:type academic:StudentArchetype . }
            UNION
            { ?archetype rdf:type academic:ProfessorArchetype . }
            OPTIONAL { ?archetype rdfs:label ?archetypeLabel . FILTER(langMatches(lang(?archetypeLabel), "pt") || lang(?archetypeLabel) = "") }
            OPTIONAL { ?archetype academic:roleTemplate ?roleTemplate . }
            OPTIONAL { ?archetype academic:description ?description . FILTER(langMatches(lang(?description), "pt") || lang(?description) = "") }
            OPTIONAL { ?archetype academic:hasCommunicationAttributes ?commAttrIRI . }
            OPTIONAL { ?archetype academic:hasBaseStyleProfile ?baseStyleProfileIRI . }
        }
    """
    print("--- Executando Query para Arquétipos de Persona ---")
    results_archetypes = g.query(query_persona_archetypes)
    print(f"Encontrados {len(results_archetypes)} resultados para arquétipos.")

    for row_arch in results_archetypes:
        archetype_iri_ref = URIRef(row_arch.archetype) # Use URIRef
        archetype_key = get_entity_key(str(archetype_iri_ref))

        if archetype_key not in personas_dict:
            personas_dict[archetype_key] = {
                "iri": str(archetype_iri_ref),
                "label_pt": str(row_arch.archetypeLabel) if row_arch.archetypeLabel else archetype_key,
                "role_template": str(row_arch.roleTemplate) if row_arch.roleTemplate else None,
                "description_pt": get_literal_value(g, archetype_iri_ref, ACADEMIC_NS.description, lang="pt"),
                "communication_attributes": {}, "base_style_profile": {},
                "general_dos_pt": [], "general_donts_pt": [],
                "relevant_generic_rule_keys": [],
                "recipient_adaptation_rules": {}, "learned_knowledge_base": []
            }
        persona_entry = personas_dict[archetype_key]

        comm_attr_iri = row_arch.commAttrIRI
        if comm_attr_iri:
            comm_attr_iri_ref = URIRef(comm_attr_iri)
            persona_entry["communication_attributes"] = {
                "iri": str(comm_attr_iri_ref),
                "language": get_literal_value(g, comm_attr_iri_ref, ACADEMIC_NS.language),
                "base_verbosity_pt": get_literal_value(g, comm_attr_iri_ref, ACADEMIC_NS.baseVerbosity, lang="pt"),
                "base_sentence_structure_pt": get_literal_value(g, comm_attr_iri_ref, ACADEMIC_NS.baseSentenceStructure, lang="pt"),
                "base_vocabulary_preference_pt": get_literal_value(g, comm_attr_iri_ref, ACADEMIC_NS.baseVocabularyPreference, lang="pt"),
                "emoji_usage_pt": get_literal_value(g, comm_attr_iri_ref, ACADEMIC_NS.emojiUsage, lang="pt")
            }

        base_style_profile_iri = row_arch.baseStyleProfileIRI
        if base_style_profile_iri:
            persona_entry["base_style_profile"] = extract_style_guidance_profile_details(g, URIRef(base_style_profile_iri))
        
        # *** CORREÇÃO PARA GENERAL DOS/DON'TS ***
        dos_texts = []
        for do_guideline_iri_obj in g.objects(archetype_iri_ref, ACADEMIC_NS.hasGeneralDo):
            if isinstance(do_guideline_iri_obj, URIRef): # Verifica se é um IRI
                text = get_literal_value(g, do_guideline_iri_obj, ACADEMIC_NS.guidelineText, lang="pt")
                if text: dos_texts.append(text)
        persona_entry["general_dos_pt"] = list(set(dos_texts)) # Garante unicidade

        donts_texts = []
        for dont_guideline_iri_obj in g.objects(archetype_iri_ref, ACADEMIC_NS.hasGeneralDont):
            if isinstance(dont_guideline_iri_obj, URIRef): # Verifica se é um IRI
                text = get_literal_value(g, dont_guideline_iri_obj, ACADEMIC_NS.guidelineText, lang="pt")
                if text: donts_texts.append(text)
        persona_entry["general_donts_pt"] = list(set(donts_texts)) # Garante unicidade
        # *** FIM DA CORREÇÃO PARA GENERAL DOS/DON'TS ***

        persona_entry["relevant_generic_rule_keys"] = [get_entity_key(str(rule_iri)) for rule_iri in g.objects(archetype_iri_ref, ACADEMIC_NS.hasRelevantGenericRule)]

    print(f"Processados {len(personas_dict)} arquétipos de persona únicos.")

    # --- PASSO 2: Extrair GenericRecipientAdaptationRules ---
    print("--- Executando Query para Regras de Adaptação Genéricas ---")
    query_rules = """
        SELECT ?rule ?ruleKey ?ruleLabel ?description ?greetingTemplate ?farewellTemplate ?adaptedStyleProfileIRI
        WHERE {
            ?rule rdf:type academic:GenericRecipientAdaptationRule .
            OPTIONAL { ?rule academic:ruleKey ?ruleKey . }
            OPTIONAL { ?rule rdfs:label ?ruleLabel . FILTER(langMatches(lang(?ruleLabel), "pt") || lang(?ruleLabel) = "") }
            OPTIONAL { ?rule academic:description ?description . FILTER(langMatches(lang(?description), "pt") || lang(?description) = "") }
            OPTIONAL { ?rule academic:greetingTemplate ?greetingTemplate . }
            OPTIONAL { ?rule academic:farewellTemplate ?farewellTemplate . }
            OPTIONAL { ?rule academic:hasAdaptedStyleProfile ?adaptedStyleProfileIRI . }
        }
    """
    results_rules = g.query(query_rules)
    print(f"Encontradas {len(results_rules)} regras de adaptação genéricas.")
    adaptation_rules_dict = ontology_export_data["generic_recipient_adaptation_rules"]

    for row_rule in results_rules:
        rule_iri_ref = URIRef(row_rule.rule)
        rule_key = str(row_rule.ruleKey) if row_rule.ruleKey else get_entity_key(str(rule_iri_ref))

        rule_entry = {
            "iri": str(rule_iri_ref),
            "rule_key": rule_key,
            "label_pt": str(row_rule.ruleLabel) if row_rule.ruleLabel else rule_key,
            "description_pt": get_literal_value(g, rule_iri_ref, ACADEMIC_NS.description, lang="pt"),
            "greeting_template": str(row_rule.greetingTemplate) if row_rule.greetingTemplate else None,
            "farewell_template": str(row_rule.farewellTemplate) if row_rule.farewellTemplate else None,
            "adapted_style_profile": {},
            "specific_dos_pt": [],
            "specific_donts_pt": []
        }
        
        adapted_style_profile_iri = row_rule.adaptedStyleProfileIRI
        if adapted_style_profile_iri:
            rule_entry["adapted_style_profile"] = extract_style_guidance_profile_details(g, URIRef(adapted_style_profile_iri))

        specific_dos_texts = []
        for do_guideline_iri_obj in g.objects(rule_iri_ref, ACADEMIC_NS.hasSpecificDo):
            if isinstance(do_guideline_iri_obj, URIRef):
                text = get_literal_value(g, do_guideline_iri_obj, ACADEMIC_NS.guidelineText, lang="pt")
                if text: specific_dos_texts.append(text)
        rule_entry["specific_dos_pt"] = list(set(specific_dos_texts))
        
        specific_donts_texts = []
        for dont_guideline_iri_obj in g.objects(rule_iri_ref, ACADEMIC_NS.hasSpecificDont):
            if isinstance(dont_guideline_iri_obj, URIRef):
                text = get_literal_value(g, dont_guideline_iri_obj, ACADEMIC_NS.guidelineText, lang="pt")
                if text: specific_donts_texts.append(text)
        rule_entry["specific_donts_pt"] = list(set(specific_donts_texts))
            
        adaptation_rules_dict[rule_key] = rule_entry

    # --- PASSO 3: Extrair LearnedKnowledgeItems ---
    print("--- Extraindo Itens de Conhecimento Aprendido ---")
    for archetype_key, persona_entry_ref in personas_dict.items(): # Renomeado para evitar conflito de nome
        archetype_iri_ref_for_learn = URIRef(persona_entry_ref["iri"]) # Usa o IRI da persona do dicionário
        
        query_learned_items = """
            SELECT ?item ?itemLabel ?timestamp ?feedbackCat ?aiOriginal ?userCorrected ?userExplanation ?modelUsed ?contextIRI
            WHERE {
                ?archetype_param academic:hasLearnedItem ?item . # Usa um nome de variável diferente para o parâmetro
                ?item academic:hasInteractionContext ?contextIRI .
                OPTIONAL { ?item rdfs:label ?itemLabel . FILTER(langMatches(lang(?itemLabel), "pt") || lang(?itemLabel) = "") }
                OPTIONAL { ?item academic:hasTimestampUTC ?timestamp . }
                OPTIONAL { ?item academic:hasFeedbackCategory ?feedbackCat . }
                OPTIONAL { ?item academic:aiOriginalResponseText ?aiOriginal . }
                OPTIONAL { ?item academic:userCorrectedOutputText ?userCorrected . }
                OPTIONAL { ?item academic:userExplanationText ?userExplanation . FILTER(langMatches(lang(?userExplanation), "pt") || lang(?userExplanation) = "") }
                OPTIONAL { ?item academic:modelUsedForOriginal ?modelUsed . }
            }
        """
        results_learned = g.query(query_learned_items, initBindings={'archetype_param': archetype_iri_ref_for_learn}) # Passa o IRI correto
        
        current_learned_items = [] # Lista para esta persona
        for row_learn in results_learned:
            item_iri_ref = URIRef(row_learn.item)
            context_iri_ref = URIRef(row_learn.contextIRI)
            
            learned_item_entry = {
                "iri": str(item_iri_ref),
                "item_label_pt": str(row_learn.itemLabel) if row_learn.itemLabel else get_entity_key(str(item_iri_ref)),
                "timestamp_utc": str(row_learn.timestamp) if row_learn.timestamp else None,
                "feedback_category_pt": get_literal_value(g, item_iri_ref, ACADEMIC_NS.hasFeedbackCategory, lang="pt"), # Usar get_literal_value
                "ai_original_response_text": str(row_learn.aiOriginal) if row_learn.aiOriginal else None,
                "user_corrected_output_text": str(row_learn.userCorrected) if row_learn.userCorrected else None,
                "user_explanation_text_pt": str(row_learn.userExplanation) if row_learn.userExplanation else get_literal_value(g, item_iri_ref, ACADEMIC_NS.userExplanationText, lang="pt"),
                "model_used_for_original": str(row_learn.modelUsed) if row_learn.modelUsed else None,
                "interaction_context_snapshot": {}
            }

            snapshot_persona_iri = g.value(context_iri_ref, ACADEMIC_NS.snapshotForPersona)
            snapshot_email_cat_iri = g.value(context_iri_ref, ACADEMIC_NS.snapshotIdentifiedEmailCategory)

            learned_item_entry["interaction_context_snapshot"] = {
                "snapshot_iri": str(context_iri_ref),
                "snapshot_for_persona_iri": str(snapshot_persona_iri) if snapshot_persona_iri else None,
                "snapshot_for_persona_key": get_entity_key(str(snapshot_persona_iri)) if snapshot_persona_iri else None,
                "snapshot_recipient_category_key": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotRecipientCategoryKey),
                "snapshot_sender_name_guess": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotSenderNameGuess),
                "snapshot_incoming_tone_pt": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotIncomingTone, lang="pt"),
                "snapshot_original_email_text_snippet_pt": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotOriginalEmailTextSnippet, lang="pt"),
                "snapshot_user_guidance_inputs": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotUserGuidanceInputs),
                "snapshot_ia_action_type": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotIAActionType),
                "snapshot_llm_pre_analysis_rationale_pt": get_literal_value(g, context_iri_ref, ACADEMIC_NS.snapshotLLMPreAnalysisRationale, lang="pt"),
                "snapshot_identified_email_category_iri": str(snapshot_email_cat_iri) if snapshot_email_cat_iri else None,
                "snapshot_identified_email_category_key": get_entity_key(str(snapshot_email_cat_iri)) if snapshot_email_cat_iri else None
            }
            current_learned_items.append(learned_item_entry)
        persona_entry_ref["learned_knowledge_base"] = current_learned_items # Atribui a lista à persona correta
        print(f"  Extraídos {len(current_learned_items)} itens aprendidos para {archetype_key}.")

    # --- PASSO 4: Extrair IAProcessDefaultSet e AcademicEmailCategories ---
    print("--- Extraindo Configurações Globais de IA e Categorias de Email ---")
    ia_settings_dict = ontology_export_data["global_ia_settings"]
    ia_options_dict = ia_settings_dict["options"]

    query_ia_defaults = """
        SELECT ?defaultSet ?optionIRI ?optionProp ?optionValue ?optionDesc ?optionChoicesLabel # Mudado de optionChoices para optionChoicesLabel
        WHERE {
            ?defaultSet rdf:type academic:IAProcessDefaultSet .
            { ?defaultSet academic:definesHandlingOfMissingInfo ?optionIRI . BIND(academic:definesHandlingOfMissingInfo AS ?optionProp) }
            UNION { ?defaultSet academic:definesPriorityOfUserInput ?optionIRI . BIND(academic:definesPriorityOfUserInput AS ?optionProp) }
            UNION { ?defaultSet academic:definesExpectedIAAutonomyLevel ?optionIRI . BIND(academic:definesExpectedIAAutonomyLevel AS ?optionProp) }
            UNION { ?defaultSet academic:definesBehaviorForUnclearRequests ?optionIRI . BIND(academic:definesBehaviorForUnclearRequests AS ?optionProp) }

            ?optionIRI academic:value ?optionValue .
            OPTIONAL { ?optionIRI academic:description ?optionDesc . FILTER(langMatches(lang(?optionDesc), "pt") || lang(?optionDesc) = "") }
            # Usar a propriedade de anotação :options_description que tem rdfs:label
            OPTIONAL { ?optionIRI academic:options_description ?optionChoicesLabel . FILTER(langMatches(lang(?optionChoicesLabel), "pt") || lang(?optionChoicesLabel) = "") }
        }
    """
    results_ia_defaults = g.query(query_ia_defaults)
    for row_ia in results_ia_defaults:
        default_set_iri_ref = URIRef(row_ia.defaultSet)
        if "default_set_iri" not in ia_settings_dict: # Preenche uma vez
            ia_settings_dict["default_set_iri"] = str(default_set_iri_ref)
            ia_settings_dict["default_set_label_pt"] = get_literal_value(g, default_set_iri_ref, RDFS.label, lang="pt")

        option_prop_key_cleaned = get_entity_key(str(row_ia.optionProp)).replace("defines", "").lower() # Cria chave mais limpa
        
        option_iri_ref = URIRef(row_ia.optionIRI)
        ia_options_dict[option_prop_key_cleaned] = {
            "option_iri": str(option_iri_ref),
            "option_label_pt": get_literal_value(g, option_iri_ref, RDFS.label, lang="pt"),
            "value": str(row_ia.optionValue),
            "description_pt": str(row_ia.optionDesc) if row_ia.optionDesc else None,
            "options_list_description_pt": str(row_ia.optionChoicesLabel) if row_ia.optionChoicesLabel else get_literal_value(g, option_iri_ref, ACADEMIC_NS.options_description, lang="pt") # Fallback para a propriedade de anotação
        }
    
    email_categories_dict = ontology_export_data["academic_email_categories"]
    query_email_categories = """
        SELECT ?cat ?catID ?displayName ?catDescription # Renomeado ?description para ?catDescription
        WHERE {
            ?cat rdf:type academic:AcademicEmailCategory .
            OPTIONAL { ?cat academic:categoryID ?catID . }
            OPTIONAL { ?cat academic:displayName ?displayName . FILTER(langMatches(lang(?displayName), "pt") || lang(?displayName) = "") }
            OPTIONAL { ?cat academic:description ?catDescription . FILTER(langMatches(lang(?catDescription), "pt") || lang(?catDescription) = "") }
        }
    """
    results_email_cat = g.query(query_email_categories)
    for row_cat in results_email_cat:
        cat_iri_ref = URIRef(row_cat.cat)
        cat_key = str(row_cat.catID) if row_cat.catID else get_entity_key(str(cat_iri_ref))
        
        email_categories_dict[cat_key] = {
            "iri": str(cat_iri_ref),
            "category_id": str(row_cat.catID) if row_cat.catID else None,
            "display_name_pt": str(row_cat.displayName) if row_cat.displayName else None,
            "description_pt": str(row_cat.catDescription) if row_cat.catDescription else get_literal_value(g, cat_iri_ref, ACADEMIC_NS.description, lang="pt")
        }
    print(f"Extraídas {len(ia_options_dict)} opções de IA e {len(email_categories_dict)} categorias de email.")

    return ontology_export_data

# --- Ponto de Entrada Principal ---
if __name__ == "__main__":
    owl_file = "ontologia-updatedPT.ttl" 
    
    if not os.path.exists(owl_file):
        print(f"ERRO: Ficheiro OWL '{owl_file}' não encontrado. Verifique o caminho.")
    else:
        print(f"A carregar ontologia de: {os.path.abspath(owl_file)}")
        ontology_export = extract_ontology_data(owl_file)
        
        output_json_file = "personas2.0.json"
        with open(output_json_file, 'w', encoding='utf-8') as f:
            json.dump(ontology_export, f, ensure_ascii=False, indent=2)
        
        print(f"Dados extraídos e guardados em: {os.path.abspath(output_json_file)}")
        
        if not ontology_export.get("personas"):
            print("AVISO: Nenhuma persona foi extraída.")
        else:
            print(f"\n--- Resumo da Extração ({len(ontology_export.get('personas', {}))} Personas) ---")
            for persona_key, data in ontology_export["personas"].items():
                print(f"\nPersona: {persona_key} ({data.get('label_pt')})")
                print(f"  Regras Relevantes (chaves): {data.get('relevant_generic_rule_keys')}")
                print(f"  Itens Aprendidos: {len(data.get('learned_knowledge_base', []))}")
                if data.get('general_dos_pt'): print(f"  General Dos: {data['general_dos_pt']}")
                if data.get('general_donts_pt'): print(f"  General Don'ts: {data['general_donts_pt']}")


        print(f"\nRegras de Adaptação Genéricas Extraídas: {len(ontology_export.get('generic_recipient_adaptation_rules', {}))}")
        if ontology_export.get('generic_recipient_adaptation_rules'):
            for rule_key, rule_data in ontology_export['generic_recipient_adaptation_rules'].items():
                print(f"  Regra: {rule_key} - Dos: {len(rule_data.get('specific_dos_pt',[]))}, Don'ts: {len(rule_data.get('specific_donts_pt',[]))}")

        print(f"Opções de IA Globais Extraídas: {len(ontology_export.get('global_ia_settings', {}).get('options', {}))}")
        print(f"Categorias de Email Académico Extraídas: {len(ontology_export.get('academic_email_categories', {}))}")