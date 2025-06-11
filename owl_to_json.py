# final_complete_converter.py

import json
from functools import lru_cache
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD

# --- Define Namespaces ---
AEP = Namespace("http://www.semanticweb.org/ontologies/2025/5/academicEmailPersona#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")


def get_short_name(iri):
    if isinstance(iri, URIRef):
        return str(iri).split('#')[-1]
    return str(iri)

def get_object(g, subject, predicate):
    return g.value(subject=subject, predicate=predicate)

def get_objects_list(g, subject, predicate):
    return list(g.objects(subject=subject, predicate=predicate))

def literal_to_native(lit):
    if isinstance(lit, Literal):
        if lit.datatype:
            if lit.datatype in [XSD.integer, XSD.int]:
                return int(lit)
            if lit.datatype in [XSD.float, XSD.double, XSD.decimal]:
                return float(lit)
            if lit.datatype == XSD.boolean:
                return bool(lit)
        return str(lit)
    elif isinstance(lit, URIRef):
        return str(lit)
    return lit

@lru_cache(maxsize=None)
def process_tone_element(g, tone_iri):
    if not tone_iri: return None
    return {
        "iri": str(tone_iri),
        "label_pt": literal_to_native(get_object(g, tone_iri, AEP.label)),
        "intensity": literal_to_native(get_object(g, tone_iri, AEP.toneIntensity)),
        "keywords_pt": [literal_to_native(kw) for kw in get_objects_list(g, tone_iri, AEP.toneKeyword)],
        "avoid_keywords_pt": [literal_to_native(kw) for kw in get_objects_list(g, tone_iri, AEP.avoidToneKeyword)]
    }

@lru_cache(maxsize=None)
def process_formality_element(g, formality_iri):
    if not formality_iri: return None
    return {
        "iri": str(formality_iri),
        "label_pt": literal_to_native(get_object(g, formality_iri, AEP.label)),
        "level_numeric": literal_to_native(get_object(g, formality_iri, AEP.formalityLevelNumeric)),
        "guidance_notes_pt": literal_to_native(get_object(g, formality_iri, AEP.formalityGuidanceNotes))
    }

@lru_cache(maxsize=None)
def process_style_profile(g, profile_iri):
    if not profile_iri: return None
    profile_data = {
        "profile_iri": str(profile_iri),
        "profile_label_pt": literal_to_native(get_object(g, profile_iri, RDFS.label))
    }
    
    tone_elements = [process_tone_element(g, tone_iri) for tone_iri in get_objects_list(g, profile_iri, AEP.includesToneElement)]
    if tone_elements:
        profile_data["tone_elements"] = tone_elements

    formality_iri = get_object(g, profile_iri, AEP.specifiesFormalityElement)
    if formality_iri:
        profile_data["formality_element"] = process_formality_element(g, formality_iri)
        
    return profile_data

@lru_cache(maxsize=None)
def process_communication_attributes(g, attrib_iri):
    if not attrib_iri: return None
    return {
        "iri": str(attrib_iri),
        "language": literal_to_native(get_object(g, attrib_iri, AEP.language)),
        "base_verbosity_pt": literal_to_native(get_object(g, attrib_iri, AEP.baseVerbosity)),
        "base_sentence_structure_pt": literal_to_native(get_object(g, attrib_iri, AEP.baseSentenceStructure)),
        "base_vocabulary_preference_pt": literal_to_native(get_object(g, attrib_iri, AEP.baseVocabularyPreference)),
        "emoji_usage_pt": literal_to_native(get_object(g, attrib_iri, AEP.emojiUsage)),
    }

@lru_cache(maxsize=None)
def process_interaction_context(g, context_iri):
    if not context_iri: return None
    return {
        "snapshot_iri": str(context_iri),
        "snapshot_for_persona_iri": str(get_object(g, context_iri, AEP.snapshotForPersona)),
        "snapshot_recipient_category_key": literal_to_native(get_object(g, context_iri, AEP.snapshotRecipientCategoryKey)),
        "snapshot_sender_name_guess": literal_to_native(get_object(g, context_iri, AEP.snapshotSenderNameGuess)),
        "snapshot_incoming_tone_pt": literal_to_native(get_object(g, context_iri, AEP.snapshotIncomingTone)),
    }

@lru_cache(maxsize=None)
def process_learned_item(g, item_iri):
    if not item_iri: return None
    context_iri = get_object(g, item_iri, AEP.hasInteractionContext)
    return {
        "iri": str(item_iri),
        "item_label_pt": literal_to_native(get_object(g, item_iri, RDFS.label)),
        "timestamp_utc": literal_to_native(get_object(g, item_iri, AEP.hasTimestampUTC)),
        "feedback_category_pt": literal_to_native(get_object(g, item_iri, AEP.hasFeedbackCategory)),
        "ai_original_response_text": literal_to_native(get_object(g, item_iri, AEP.aiOriginalResponseText)),
        "user_corrected_output_text": literal_to_native(get_object(g, item_iri, AEP.userCorrectedOutputText)),
        "user_explanation_text_pt": literal_to_native(get_object(g, item_iri, AEP.userExplanationText)),
        "model_used_for_original": literal_to_native(get_object(g, item_iri, AEP.modelUsedForOriginal)),
        "interaction_context_snapshot": process_interaction_context(g, context_iri) if context_iri else None,
    }

def process_persona(g, persona_iri):
    persona_data = {
        "iri": str(persona_iri),
        "label_pt": literal_to_native(get_object(g, persona_iri, RDFS.label)),
        "type": get_short_name(get_object(g, persona_iri, RDF.type)),
        "role_template": literal_to_native(get_object(g, persona_iri, AEP.roleTemplate)),
        "description_pt": literal_to_native(get_object(g, persona_iri, AEP.description)),
    }

    config_iri = get_object(g, persona_iri, AEP.hasConfiguration)
    if config_iri:
        attrib_iri = get_object(g, config_iri, AEP.hasCommunicationAttributes)
        persona_data["communication_attributes"] = process_communication_attributes(g, attrib_iri)

        profile_iri = get_object(g, config_iri, AEP.hasBaseStyleProfile)
        persona_data["base_style_profile"] = process_style_profile(g, profile_iri)

        dos = [literal_to_native(get_object(g, do_iri, AEP.guidelineText)) for do_iri in get_objects_list(g, config_iri, AEP.hasGeneralDo)]
        donts = [literal_to_native(get_object(g, dnt_iri, AEP.guidelineText)) for dnt_iri in get_objects_list(g, config_iri, AEP.hasGeneralDont)]
        persona_data["general_dos_pt"] = dos
        persona_data["general_donts_pt"] = donts
        
        rule_iris = get_objects_list(g, config_iri, AEP.hasRelevantGenericRule)
        persona_data["relevant_generic_rule_keys"] = [literal_to_native(get_object(g, r, AEP.ruleKey)) for r in rule_iris]
        
    learned_items = [process_learned_item(g, item_iri) for item_iri in get_objects_list(g, persona_iri, AEP.hasLearnedItem)]
    persona_data["learned_knowledge_base"] = learned_items
    
    return {k: v for k, v in persona_data.items() if v is not None and v != []}

def process_rule(g, rule_iri):
    rule_data = {
        "iri": str(rule_iri),
        "rule_key": literal_to_native(get_object(g, rule_iri, AEP.ruleKey)),
        "label_pt": literal_to_native(get_object(g, rule_iri, RDFS.label)),
        "description_pt": literal_to_native(get_object(g, rule_iri, AEP.description)),
        "greeting_template": literal_to_native(get_object(g, rule_iri, AEP.greetingTemplate)),
        "farewell_template": literal_to_native(get_object(g, rule_iri, AEP.farewellTemplate)),
    }
    
    adapted_profile_iri = get_object(g, rule_iri, AEP.hasAdaptedStyleProfile)
    rule_data["adapted_style_profile"] = process_style_profile(g, adapted_profile_iri)
    
    dos = [literal_to_native(get_object(g, do_iri, AEP.guidelineText)) for do_iri in get_objects_list(g, rule_iri, AEP.hasSpecificDo)]
    donts = [literal_to_native(get_object(g, dnt_iri, AEP.guidelineText)) for dnt_iri in get_objects_list(g, rule_iri, AEP.hasSpecificDont)]
    rule_data["specific_dos_pt"] = dos
    rule_data["specific_donts_pt"] = donts
    
    return rule_data
    
def process_ia_option(g, option_iri):
    if not option_iri: return None
    return {
        "option_iri": str(option_iri),
        "option_label_pt": literal_to_native(get_object(g, option_iri, RDFS.label)),
        "value": literal_to_native(get_object(g, option_iri, AEP.value)),
        "description_pt": literal_to_native(get_object(g, option_iri, AEP.description)),
        "options_list_description_pt": literal_to_native(get_object(g, option_iri, AEP.options_description))
    }

def process_ia_settings(g, settings_iri):
    return {
        "default_set_iri": str(settings_iri),
        "default_set_label_pt": literal_to_native(get_object(g, settings_iri, RDFS.label)),
        "options": {
            "handlingofmissinginfo": process_ia_option(g, get_object(g, settings_iri, AEP.definesHandlingOfMissingInfo)),
            "priorityofuserinput": process_ia_option(g, get_object(g, settings_iri, AEP.definesPriorityOfUserInput)),
            "expectediaautonomylevel": process_ia_option(g, get_object(g, settings_iri, AEP.definesExpectedIAAutonomyLevel)),
            "behaviorforunclearrequests": process_ia_option(g, get_object(g, settings_iri, AEP.definesBehaviorForUnclearRequests)),
        }
    }
    
def process_email_category(g, category_iri):
    return {
        "iri": str(category_iri),
        "category_id": literal_to_native(get_object(g, category_iri, AEP.categoryID)),
        "display_name_pt": literal_to_native(get_object(g, category_iri, AEP.displayName)),
        "description_pt": literal_to_native(get_object(g, category_iri, AEP.description)),
    }

def convert_ttl_to_structured_json(ttl_file_path, json_file_path):
    g = Graph()
    try:
        # --- A CORREÇÃO ESTÁ AQUI ---
        # 1. Definir o endereço base oficial da ontologia
        base_uri = "http://www.semanticweb.org/ontologies/2025/5/academicEmailPersona#"
        
        # 2. Usar o parâmetro 'base' para forçar o endereço correto durante a leitura
        g.parse(source=ttl_file_path, format='turtle', publicID=base_uri)
        
        print(f"Successfully parsed {len(g)} triples from '{ttl_file_path}' using the correct base URI.")
    except Exception as e:
        print(f"Error parsing TTL file: {e}")
        return

    final_json = {
        "personas": {},
        "generic_recipient_adaptation_rules": {},
        "global_ia_settings": {},
        "academic_email_categories": {}
    }

    persona_types = [AEP.StudentArchetype, AEP.ProfessorArchetype]
    all_persona_iris = set()
    for persona_type in persona_types:
        for persona_iri in g.subjects(predicate=RDF.type, object=persona_type):
            if (persona_iri, RDF.type, OWL.Class) not in g:
                 all_persona_iris.add(persona_iri)

    for persona_iri in sorted(all_persona_iris):
        persona_key = get_short_name(persona_iri)
        final_json["personas"][persona_key] = process_persona(g, persona_iri)

    for rule_iri in g.subjects(predicate=RDF.type, object=AEP.GenericRecipientAdaptationRule):
        rule_obj = process_rule(g, rule_iri)
        rule_key = rule_obj.get("rule_key")
        if rule_key:
            final_json["generic_recipient_adaptation_rules"][rule_key] = rule_obj
        
    for settings_iri in g.subjects(predicate=RDF.type, object=AEP.IAProcessDefaultSet):
        final_json["global_ia_settings"] = process_ia_settings(g, settings_iri)
        
    for category_iri in g.subjects(predicate=RDF.type, object=AEP.AcademicEmailCategory):
        category_obj = process_email_category(g, category_iri)
        category_key = category_obj.get("category_id")
        if category_key:
            final_json["academic_email_categories"][category_key] = category_obj

    try:
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(final_json, f, indent=2, ensure_ascii=False)
        print(f"Successfully converted complete ontology to structured JSON at '{json_file_path}'.")
    except Exception as e:
        print(f"Error writing JSON file: {e}")

if __name__ == "__main__":
    input_ttl_file = "ontologia.ttl"
    output_json_file = "new_personas.json"

    convert_ttl_to_structured_json(input_ttl_file, output_json_file)