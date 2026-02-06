import json
import os
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor
from langchain.agents import create_openai_functions_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════
# LLM — GPT-4o
# ═══════════════════════════════════════════════════════
llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0.2,
    openai_api_key=os.getenv("OPENAI_API_KEY"),
)

# ═══════════════════════════════════════════════════════
# ÉTAT DES SESSIONS
# ═══════════════════════════════════════════════════════
SESSIONS: Dict[str, Dict[str, Any]] = {}
CURRENT_SESSION_ID: Optional[str] = None

MODULE_FILES = {
    "crm": "KD/crm_mapping.json",
    "sales": "KD/sales_mapping.json",
    "facturation": "KD/facturation_mapping.json",
}

# ═══════════════════════════════════════════════════════
# OUTILS DE L'AGENT
# ═══════════════════════════════════════════════════════

@tool
def load_module_mapping(module_name: str) -> str:
    """Charge le mapping JSON du module Odoo sélectionné (crm, sales, facturation).
    
    UTILISE CE TOOL IMMÉDIATEMENT quand le client dit "CRM", "Sales" ou "Facturation".
    
    Args:
        module_name: nom du module (crm, sales, facturation)
    """
    global CURRENT_SESSION_ID
    session_id = CURRENT_SESSION_ID
    
    if not session_id:
        return json.dumps({"error": "Session ID non défini"})
    path = MODULE_FILES.get(module_name.lower())
    if not path or not os.path.exists(path):
        return json.dumps({"error": "Module introuvable. Modules valides: crm, sales, facturation"})
    
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    
    SESSIONS[session_id]["module"] = module_name
    SESSIONS[session_id]["mapping"] = mapping
    SESSIONS[session_id]["fields_covered"] = {}
    SESSIONS[session_id]["questions_asked"] = []
    SESSIONS[session_id]["last_question"] = None
    
    questions = mapping.get("questions_mapping", [])
    config_fields = [q for q in questions if q.get("is_config", True)]
    info_fields = [q for q in questions if not q.get("is_config", True)]
    
    return json.dumps({
        "status": "success",
        "message": f"✅ Module {module_name} chargé avec succès",
        "total_fields": len(questions),
        "config_fields_count": len(config_fields),
        "info_fields_count": len(info_fields),
        "note": f"Les {len(info_fields)} champs informatifs (is_config=false) ne seront pas requis pour la génération du JSON",
        "first_config_fields": [q["odoo_field"] for q in config_fields[:5]]
    }, ensure_ascii=False, indent=2)


@tool
def extract_and_store_fields_automatically(user_message: str) -> str:
    """OUTIL OBLIGATOIRE : Analyse CHAQUE réponse du client et stocke automatiquement les configurations.
    
    ⚠️ TU DOIS APPELER CET OUTIL APRÈS CHAQUE MESSAGE DU CLIENT, SANS EXCEPTION.
    
    Args:
        user_message: le message libre du user
    """
    global CURRENT_SESSION_ID
    session_id = CURRENT_SESSION_ID
    
    if not session_id:
        return json.dumps({"error": "Session ID non défini"})
    if session_id not in SESSIONS or "mapping" not in SESSIONS[session_id]:
        return json.dumps({"error": "Aucun module chargé. Utilise d'abord load_module_mapping."})
    
    mapping = SESSIONS[session_id]["mapping"]
    fields_structure = mapping.get("questions_mapping", [])
    questions_asked = SESSIONS[session_id].get("questions_asked", [])
    last_question = SESSIONS[session_id].get("last_question")
    
    config_fields_structure = [f for f in fields_structure if f.get("is_config", True)]
    
    recent_questions_context = []
    if last_question:
        recent_questions_context.append(last_question)
    for field_id in questions_asked[-2:]:
        field_info = next((f for f in config_fields_structure if f["odoo_field"] == field_id), None)
        if field_info:
            recent_questions_context.append({
                "odoo_field": field_info["odoo_field"],
                "question": field_info["question"]
            })
    
    extraction_prompt = f"""
Tu es un expert en extraction de données pour Odoo. Analyse cette réponse du client et extrait TOUTES les informations pertinentes pour la configuration Odoo.

RÉPONSE CLIENT:
{user_message}

⚠️ CONTEXTE IMPORTANT (dernières questions posées) :
{json.dumps(recent_questions_context, ensure_ascii=False, indent=2) if recent_questions_context else "Aucune question posée récemment"}

CHAMPS DE CONFIGURATION DISPONIBLES (is_config=true uniquement):
{json.dumps(config_fields_structure, ensure_ascii=False, indent=2)}

INSTRUCTIONS CRITIQUES:
1. IMPORTANT : Concentre-toi UNIQUEMENT sur les champs avec is_config=true
2. Ignore complètement les champs informatifs (is_config=false ou info_*)
3. Pour chaque information identifiée, trouve le odoo_field correspondant
4. Si le champ a un "options_mapping", convertis vers la VALEUR TECHNIQUE
5. Si c'est un boolean, retourne true ou false (pas "oui"/"non")
6. Si c'est un integer, retourne un nombre
7. Si c'est une selection, retourne EXACTEMENT une des options listées
8. Ne stocke JAMAIS le texte brut du client — uniquement les valeurs techniques Odoo

9. ⚠️ Gestion des réponses courtes et contextuelles :
   
   A) "Non" ou "Aucune" ou "Rien" :
      - Si une question a été posée juste avant (vérifie CONTEXTE), interpréte comme false/standard pour ce champ
   
   B) "Oui" ou "D'accord" :
      - Si une question a été posée juste avant, interpréte comme true
   
   C) "Standard" ou "Par défaut" :
      - Cherche la valeur par défaut ou retourne false si boolean
   
   D) Réponses multiples :
      Exemple : "Non pour les limites, oui pour les rappels"
      → Extrais TOUS les champs mentionnés

10. Si le client dit "tout le reste en standard" ou "valeurs par défaut" :
    → Mets dans unrelated_info : "CLIENT_WANTS_DEFAULTS"

11. ⚠️ DÉTECTION D'INFORMATIONS HORS-SUJET :
    Si le client parle de sujets NON LIÉS à la configuration Odoo (café, météo, anecdotes personnelles, etc.) :
    → Mets le texte dans unrelated_info avec le préfixe "OFF_TOPIC: "
    → Exemple : unrelated_info: "OFF_TOPIC: Le client parle du café de la machine"

RÉPONDS EN JSON STRICT:
{{
    "extracted_fields": {{
        "odoo_field_name": {{
            "value": <valeur technique>,
            "confidence": "high" | "medium" | "low",
            "user_text": "ce que le user a dit textuellement"
        }}
    }},
    "needs_clarification": ["odoo_field1"],
    "unrelated_info": "OFF_TOPIC: ... OU CLIENT_WANTS_DEFAULTS OU texte si autre"
}}
"""
    
    response = llm.invoke([HumanMessage(content=extraction_prompt)])
    
    try:
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        extracted = json.loads(content)
    except Exception as e:
        return json.dumps({"error": "Échec de l'extraction", "details": str(e), "raw": response.content[:500]})
    
    # Détection des cas spéciaux
    unrelated_info = extracted.get("unrelated_info", "")
    wants_defaults = "CLIENT_WANTS_DEFAULTS" in unrelated_info
    is_off_topic = "OFF_TOPIC:" in unrelated_info
    
    stored_fields = []
    failed_fields = []
    updated_fields = []
    
    for odoo_field, field_data in extracted.get("extracted_fields", {}).items():
        confidence = field_data.get("confidence", "low")
        
        if confidence in ["high", "medium"]:
            field_def = next(
                (f for f in config_fields_structure if f["odoo_field"] == odoo_field),
                None
            )
            
            if not field_def:
                failed_fields.append(f"{odoo_field} (champ introuvable ou is_config=false)")
                continue
            
            value = field_data["value"]
            data_type = field_def.get("data_type", "string")
            
            if data_type == "boolean":
                if isinstance(value, bool):
                    pass
                elif isinstance(value, str):
                    value = value.lower() in ["true", "yes", "oui", "1"]
                else:
                    failed_fields.append(f"{odoo_field} (doit être boolean)")
                    continue
            
            if data_type == "integer":
                try:
                    value = int(value)
                except:
                    failed_fields.append(f"{odoo_field} (doit être integer)")
                    continue
            
            if data_type == "selection":
                options_mapping = field_def.get("options_mapping", {})
                valid_values = list(options_mapping.values()) if options_mapping else field_def.get("options", [])
                
                if valid_values and value not in valid_values:
                    failed_fields.append(f"{odoo_field} (valeur '{value}' invalide, attendu: {valid_values})")
                    continue
            
            is_update = odoo_field in SESSIONS[session_id]["fields_covered"]
            old_value = SESSIONS[session_id]["fields_covered"].get(odoo_field) if is_update else None
            
            SESSIONS[session_id]["fields_covered"][odoo_field] = value
            
            if odoo_field not in SESSIONS[session_id]["questions_asked"]:
                SESSIONS[session_id]["questions_asked"].append(odoo_field)
            
            field_info = {
                "field": odoo_field,
                "value": value,
                "user_said": field_data.get("user_text", ""),
                "description": field_def.get("description", ""),
                "question": field_def.get("question", "")
            }
            
            if is_update:
                field_info["old_value"] = old_value
                field_info["is_correction"] = True
                updated_fields.append(field_info)
            else:
                stored_fields.append(field_info)
    
    result = {
        "status": "success",
        "stored_count": len(stored_fields),
        "updated_count": len(updated_fields),
        "stored_fields": stored_fields,
        "updated_fields": updated_fields,
        "failed_fields": failed_fields,
        "needs_clarification": extracted.get("needs_clarification", []),
        "total_filled": len(SESSIONS[session_id]["fields_covered"]),
        "questions_asked_count": len(SESSIONS[session_id]["questions_asked"]),
        "wants_defaults": wants_defaults,
        "is_off_topic": is_off_topic,
        "off_topic_message": unrelated_info.replace("OFF_TOPIC:", "").strip() if is_off_topic else ""
    }
    
    print(f"✅ Stockage : {len(stored_fields)} nouveaux, {len(updated_fields)} mis à jour - Total: {len(SESSIONS[session_id]['fields_covered'])}")
    if wants_defaults:
        print(f"⚠️ Client demande des valeurs par défaut !")
    if is_off_topic:
        print(f"💬 Message hors-sujet détecté : {result['off_topic_message']}")
    
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_configuration_progress() -> str:
    """Retourne l'état d'avancement ET la liste des champs manquants NON ENCORE ABORDÉS.
    
    🔒 FILTRAGE AUTOMATIQUE STRICT
    """
    global CURRENT_SESSION_ID
    session_id = CURRENT_SESSION_ID
    
    if not session_id:
        return json.dumps({"error": "Session ID non défini"})
    if session_id not in SESSIONS or "mapping" not in SESSIONS[session_id]:
        return json.dumps({"error": "Aucun module chargé"})
    
    mapping = SESSIONS[session_id]["mapping"]
    all_fields = mapping["questions_mapping"]
    filled = SESSIONS[session_id].get("fields_covered", {})
    questions_asked = SESSIONS[session_id].get("questions_asked", [])
    
    config_fields = [f for f in all_fields if f.get("is_config", True)]
    info_fields = [f for f in all_fields if not f.get("is_config", True)]
    
    missing_fields = []
    
    for f in config_fields:
        odoo_field = f["odoo_field"]
        
        if odoo_field in filled:
            continue
        
        already_asked = odoo_field in questions_asked
        
        missing_fields.append({
            "odoo_field": odoo_field,
            "question": f["question"],
            "section": f.get("section", "Général"),
            "description": f.get("description", ""),
            "already_asked": already_asked
        })
    
    never_asked = [f for f in missing_fields if not f["already_asked"]]
    asked_but_not_filled = [f for f in missing_fields if f["already_asked"]]
    
    if never_asked:
        next_suggestion = never_asked[0]
    elif asked_but_not_filled:
        next_suggestion = asked_but_not_filled[0]
    else:
        next_suggestion = None
    
    if next_suggestion:
        SESSIONS[session_id]["last_question"] = next_suggestion
    
    completion = (len(filled) / len(config_fields) * 100) if config_fields else 0
    
    result = {
        "module": SESSIONS[session_id].get("module"),
        "completion_percentage": round(completion, 1),
        "total_config_fields": len(config_fields),
        "info_fields_ignored": len(info_fields),
        "filled_fields": len(filled),
        "missing_count": len(missing_fields),
        "never_asked_count": len(never_asked),
        "never_asked_fields": never_asked[:3],
        "asked_but_not_filled_count": len(asked_but_not_filled),
        "asked_but_not_filled": asked_but_not_filled[:2],
        "next_question": next_suggestion,
        "can_generate_config": len(missing_fields) == 0,
        "warning": "⚠️ Il manque encore des champs de configuration" if missing_fields else "✅ Configuration complète !",
        "agent_instruction": (
            f"Pose une question sur : {next_suggestion['question']}" if next_suggestion 
            else "Tous les champs de configuration sont remplis ! Affiche le récapitulatif et propose de générer."
        )
    }
    
    print(f"📊 Progression : {completion:.1f}% - Remplis: {len(filled)}/{len(config_fields)} - Manquants: {len(missing_fields)}")
    print(f"   → Champs informatifs ignorés: {len(info_fields)}")
    print(f"   → Jamais posés: {len(never_asked)}")
    print(f"   → Posés mais pas clairs: {len(asked_but_not_filled)}")
    if next_suggestion:
        print(f"   → Prochain: {next_suggestion['odoo_field']}")
    
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def set_default_values_for_remaining_fields() -> str:
    """OUTIL DE FALLBACK : Rempli automatiquement les champs manquants avec des valeurs par défaut."""
    global CURRENT_SESSION_ID
    session_id = CURRENT_SESSION_ID
    
    if not session_id or session_id not in SESSIONS or "mapping" not in SESSIONS[session_id]:
        return json.dumps({"error": "Aucun module chargé"})
    
    mapping = SESSIONS[session_id]["mapping"]
    all_fields = mapping["questions_mapping"]
    filled = SESSIONS[session_id].get("fields_covered", {})
    
    config_fields = [f for f in all_fields if f.get("is_config", True)]
    missing_fields = [f for f in config_fields if f["odoo_field"] not in filled]
    
    if not missing_fields:
        return json.dumps({
            "status": "info",
            "message": "Tous les champs de configuration sont déjà remplis !"
        })
    
    defaults_applied = []
    for field in missing_fields:
        odoo_field = field["odoo_field"]
        data_type = field.get("data_type", "string")
        
        if data_type == "boolean":
            default_value = False
        elif data_type == "integer":
            default_value = 0
        elif data_type == "selection":
            options_mapping = field.get("options_mapping", {})
            if options_mapping:
                default_value = list(options_mapping.values())[0]
            else:
                options = field.get("options", [])
                default_value = options[0] if options else ""
        else:
            default_value = ""
        
        SESSIONS[session_id]["fields_covered"][odoo_field] = default_value
        if odoo_field not in SESSIONS[session_id]["questions_asked"]:
            SESSIONS[session_id]["questions_asked"].append(odoo_field)
        
        defaults_applied.append({
            "field": odoo_field,
            "value": default_value,
            "question": field["question"]
        })
    
    print(f"⚙️ Valeurs par défaut appliquées : {len(defaults_applied)} champs de configuration")
    
    return json.dumps({
        "status": "success",
        "message": f"✅ {len(defaults_applied)} champs de configuration remplis avec des valeurs par défaut",
        "defaults_applied": defaults_applied,
        "total_filled": len(SESSIONS[session_id]["fields_covered"])
    }, ensure_ascii=False, indent=2)


@tool
def search_odoo_documentation(query: str) -> str:
    """Recherche dans la documentation Odoo pour expliquer un concept."""
    mock_results = {
        "invoice policy": "La politique de facturation détermine quand une facture peut être créée. 'order' = facturer à la commande, 'delivery' = facturer à la livraison.",
        "payment terms": "Les conditions de paiement définissent les délais et échéances. Exemple: Net 30 jours, paiement immédiat, etc.",
        "product variants": "Les variantes permettent de gérer différentes versions d'un produit (tailles, couleurs).",
        "pricelist": "Les listes de prix permettent de définir des tarifs différents selon les clients, les quantités ou les périodes.",
        "delivery": "La gestion des livraisons permet de calculer automatiquement les frais de port et de suivre les expéditions.",
        "signature": "La signature électronique permet au client de valider sa commande en ligne de manière sécurisée.",
        "lead": "Les leads (pistes) sont des contacts potentiels avant qualification en opportunité commerciale.",
        "recurring revenue": "Les revenus récurrents permettent de suivre les abonnements et contrats à facturation répétée.",
        "auto assignment": "L'assignation automatique distribue les pistes/opportunités aux vendeurs selon des règles définies.",
        "credit limit": "La limite de crédit permet de bloquer les commandes si un client dépasse son crédit autorisé.",
        "batch payment": "Les paiements par lots permettent de regrouper plusieurs paiements fournisseurs en une seule opération.",
        "currency": "La gestion multi-devises permet de facturer en différentes monnaies avec synchronisation des taux de change."
    }
    
    result = mock_results.get(query.lower(), f"Documentation Odoo sur '{query}' : voir https://docs.odoo.com/search?q={query}")
    
    return json.dumps({
        "query": query,
        "source": "docs.odoo.com",
        "content": result
    }, ensure_ascii=False)


@tool
def generate_final_config_json() -> str:
    """Génère le fichier JSON final de configuration Odoo."""
    global CURRENT_SESSION_ID
    session_id = CURRENT_SESSION_ID
    
    if not session_id:
        return json.dumps({"error": "Session ID non défini"})
    if session_id not in SESSIONS:
        return json.dumps({"error": "Session introuvable"})
    
    module = SESSIONS[session_id].get("module")
    mapping = SESSIONS[session_id].get("mapping", {})
    fields_covered = SESSIONS[session_id].get("fields_covered", {})
    
    all_fields = mapping.get("questions_mapping", [])
    config_fields_ids = [f["odoo_field"] for f in all_fields if f.get("is_config", True)]
    
    final_config = {k: v for k, v in fields_covered.items() if k in config_fields_ids}
    
    output = {
        "module": module,
        "configuration": final_config
    }
    
    filename = f"config_{module}_final.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Configuration générée : {len(final_config)} champs dans {filename}")
    
    return json.dumps({
        "status": "success",
        "filename": filename,
        "fields_count": len(final_config),
        "config_preview": final_config
    }, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════
# PROMPT SYSTÈME
# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════
# PROMPT SYSTÈME
# ═══════════════════════════════════════════════════════
CONSULTANT_SYSTEM_PROMPT = """Tu es un consultant Odoo expert. Ton rôle est de collecter TOUTES les informations nécessaires pour générer une configuration technique complète.

🚨 RÈGLE CRITIQUE N°0 : ACCUSER RÉCEPTION SYSTÉMATIQUEMENT (PRIORITÉ ABSOLUE)

APRÈS avoir appelé extract_and_store_fields_automatically, tu DOIS TOUJOURS réagir au message du client.

┌─────────────────────────────────────────────────────────────────┐
│ CAS 1 : Informations UTILES extraites (stored_count > 0)       │
└─────────────────────────────────────────────────────────────────┘

Affiche :

"
Parfait ! Voici ce que j'ai noté :

✅ [Fonction 1 en langage clair]
   → [Bénéfice concret]

✅ [Fonction 2 en langage clair]
   → [Bénéfice concret]

Est-ce que tout est correct ?
"

┌─────────────────────────────────────────────────────────────────┐
│ CAS 2 : Informations HORS-SUJET (is_off_topic = true)          │
└─────────────────────────────────────────────────────────────────┘

Le tool retourne is_off_topic = true :

Tu DOIS reconnaître le message avec EMPATHIE mais REDIRIGER vers la configuration :

⚠️ FORMULES OBLIGATOIRES (choisis selon le contexte) :

A) Si c'est complètement hors-sujet (café, météo, anecdotes personnelles) :

"
Je comprends votre remarque ! 😊 Cependant, je ne vois pas l'utilité de cette information à ce stade de la configuration.

Concentrons-nous sur votre module [module] : [Prochaine question]
"

B) Si c'est un besoin réel mais pour un autre module Odoo :

"
Intéressant ! Cette fonctionnalité pourra être configurée dans un autre module (comme Inventaire ou Achats).

Pour l'instant, revenons à votre module [module] : [Prochaine question]
"

C) Si c'est une suggestion d'amélioration du processus métier :

"
C'est une bonne remarque ! Nous pourrons explorer cette piste après avoir finalisé la configuration de base.

Revenons à votre module [module] : [Prochaine question]
"

EXEMPLES CONCRETS OBLIGATOIRES À SUIVRE :

User: "Le café du troisième est imbuvable"
Agent: "Je comprends votre remarque ! 😊 Cependant, je ne vois pas l'utilité de cette information à ce stade de la configuration. Concentrons-nous sur votre module Sales : souhaitez-vous..."

User: "On devrait gérer les stocks de café dans l'ERP"
Agent: "Intéressant ! La gestion des stocks consommables pourra être configurée dans le module Inventaire. Pour l'instant, revenons à votre module Sales : souhaitez-vous..."

User: "Mon chat a mangé mes clés USB ce matin"
Agent: "😅 J'espère que tout va bien ! Cependant, je ne vois pas l'utilité de cette information pour votre configuration Odoo. Concentrons-nous sur votre module Sales : souhaitez-vous..."

User: "Les commandes arrivent par WhatsApp"
Agent: "Je note que vous recevez les commandes par WhatsApp ! Cette information sera utile pour l'intégration future. Pour l'instant, concentrons-nous sur la configuration Sales : souhaitez-vous activer la signature électronique pour vos devis ?"

⚠️ RÈGLE CRITIQUE : 
- Utilise TOUJOURS la formule A) "je ne vois pas l'utilité à ce stade" pour les sujets TOTALEMENT hors contexte (café, météo, vie personnelle, etc.)
- Utilise la formule B) pour les besoins réels mais d'un autre module
- Utilise la formule C) pour les suggestions d'amélioration

┌─────────────────────────────────────────────────────────────────┐
│ CAS 3 : Aucune information extraite (stored_count = 0)         │
│         ET PAS hors-sujet                                       │
└─────────────────────────────────────────────────────────────────┘

Cela signifie que la réponse est ambiguë ou incomplète.

Affiche :

"
Je ne suis pas sûr d'avoir bien compris votre réponse.

Pourriez-vous préciser : [reformule la question] ?
"

┌─────────────────────────────────────────────────────────────────┐
│ CAS 4 : Correction (updated_fields existe)                     │
└─────────────────────────────────────────────────────────────────┘

Affiche :

"
🔄 Correction prise en compte :

❌ [Fonction corrigée]
   → Ancienne valeur : [old_value]
   → Nouvelle valeur : [value]

Merci pour la précision !
"

⚠️ RÈGLE D'OR : JAMAIS passer directement à la question suivante sans avoir reconnu le message du client.

🎯 OBJECTIF
Générer un fichier JSON de configuration Odoo avec 100% des champs de configuration (is_config=true) remplis, SANS JAMAIS répéter une question.

⚠️ IMPORTANT : CHAMPS INFORMATIFS vs CHAMPS DE CONFIGURATION
- Champs avec is_config=true : CE SONT LES SEULS À REMPLIR pour le JSON final
- Champs avec is_config=false : Informatifs uniquement, NE VONT PAS dans le JSON

📋 WORKFLOW OBLIGATOIRE (STRICT)

1. CHARGEMENT DU MODULE
   Dès que le client dit "CRM", "Sales" ou "Facturation" :
   → APPELLE load_module_mapping(module_name) IMMÉDIATEMENT

2. QUESTION OUVERTE INITIALE
   → Pose UNE question ouverte : "Parlez-moi de votre activité et de vos processus"

3. EXTRACTION APRÈS CHAQUE RÉPONSE (OBLIGATOIRE)
   
   ⚠️ RÈGLE ABSOLUE : Après CHAQUE message du client :
   
   a) APPELLE extract_and_store_fields_automatically(user_message)
   
   b) Lis attentivement le résultat :
      • stored_count : nombre de champs stockés
      • stored_fields : nouveaux champs
      • updated_fields : corrections
      • is_off_topic : true si hors-sujet
      • wants_defaults : true si valeurs par défaut demandées
   
   c) 🚨 ACCUSE RÉCEPTION selon le CAS (voir RÈGLE N°0 ci-dessus)
   
   d) Appelle get_configuration_progress() pour connaître la suite

4. VÉRIFICATION DE PROGRESSION
   
   → APPELLE get_configuration_progress()
   
   → Si can_generate_config = false :
     • Pose la question suggérée dans next_question
   
   → Si can_generate_config = true :
     • Passe à l'étape 5

5. GÉNÉRATION (UNIQUEMENT SI 100% COMPLET)
   
   → Affiche un RÉCAPITULATIF COMPLET
   → Si confirmation : APPELLE generate_final_config_json()

🚨 RÈGLES CRITIQUES

RÈGLE 1 : Extraction systématique
→ Appelle extract_and_store_fields_automatically après CHAQUE message

RÈGLE 2 : Accusé de réception obligatoire
→ Utilise les formats du CAS correspondant (voir RÈGLE N°0)
→ JAMAIS ignorer le message du client
→ Pour hors-sujet total : TOUJOURS dire "je ne vois pas l'utilité à ce stade"

RÈGLE 3 : Fais confiance au filtrage automatique
→ get_configuration_progress filtre automatiquement
→ Pose la question suggérée dans next_question

RÈGLE 4 : Gestion des corrections
→ Affiche avec 🔄

RÈGLE 5 : Outil de fallback
Si wants_defaults = true :
→ APPELLE set_default_values_for_remaining_fields()

📊 FORMAT DE CONFIRMATION

"
Parfait ! Voici ce que j'ai noté :

✅ [Fonction 1 en langage clair]
   → [Bénéfice concret]

✅ [Fonction 2 en langage clair]
   → [Bénéfice concret]

Est-ce que tout est correct ?
"

💬 TON ET STYLE

- Professionnel mais accessible
- Patient et à l'écoute
- Ferme mais poli pour rediriger les hors-sujets
- Jamais de jargon technique
- Emoji ✅ ❌ 📋 🔄 🎉 😊 pour structurer

🔧 EXEMPLES DE REFORMULATION

- group_use_credit_limit → "Limite de crédit par client"
- module_account_batch_payment → "Paiements par lots"
- tax_exigibility → "Régime de TVA"

RAPPEL FINAL : 
• Appelle extract_and_store_fields_automatically APRÈS CHAQUE MESSAGE
• ACCUSE RÉCEPTION systématiquement
• Pour hors-sujet total : DIS "je ne vois pas l'utilité à ce stade"
• Seuls les champs is_config=true comptent
"""
# ═══════════════════════════════════════════════════════
# CRÉATION DE L'AGENT
# ═══════════════════════════════════════════════════════
tools = [
    load_module_mapping,
    extract_and_store_fields_automatically,
    get_configuration_progress,
    search_odoo_documentation,
    set_default_values_for_remaining_fields,
    generate_final_config_json,
]

prompt = ChatPromptTemplate.from_messages([
    ("system", CONSULTANT_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

agent = create_openai_functions_agent(llm, tools, prompt)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=30,
    max_execution_time=90,
    return_intermediate_steps=False,
)

# ═══════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════
@app.get("/")
async def serve_frontend():
    return FileResponse("chat_interface.html")


@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "history": [],
            "module": None,
            "mapping": {},
            "fields_covered": {},
            "questions_asked": [],
            "last_question": None,
        }
        
        welcome_msg = "Bonjour ! Je suis votre consultant Odoo. Quel module souhaitez-vous configurer aujourd'hui : CRM, Sales ou Facturation ?"
        SESSIONS[session_id]["history"].append({"role": "assistant", "content": welcome_msg})
    
    try:
        await websocket.send_json({
            "type": "ai_message",
            "content": "Bonjour ! Je suis votre consultant Odoo. Quel module souhaitez-vous configurer aujourd'hui : CRM, Sales ou Facturation ?"
        })
        
        while True:
            data = await websocket.receive_json()
            user_msg = data.get("message", "").strip()
            
            if not user_msg:
                continue
            
            SESSIONS[session_id]["history"].append({"role": "user", "content": user_msg})
            
            global CURRENT_SESSION_ID
            CURRENT_SESSION_ID = session_id
            
            chat_history = []
            for msg in SESSIONS[session_id]["history"][:-1]:
                if msg["role"] == "user":
                    chat_history.append(HumanMessage(content=msg["content"]))
                else:
                    chat_history.append(AIMessage(content=msg["content"]))
            
            try:
                print(f"\n{'='*60}")
                print(f"USER ({session_id}): {user_msg}")
                print(f"{'='*60}")
                
                response = await agent_executor.ainvoke(
                    {
                        "input": user_msg,
                        "chat_history": chat_history,
                    }
                )
                
                ai_response = response["output"]
                
                print(f"\n{'='*60}")
                print(f"AGENT: {ai_response}")
                print(f"CHAMPS STOCKÉS: {len(SESSIONS[session_id]['fields_covered'])}")
                print(f"QUESTIONS POSÉES: {len(SESSIONS[session_id]['questions_asked'])}")
                print(f"{'='*60}\n")
                
                SESSIONS[session_id]["history"].append({"role": "assistant", "content": ai_response})
                
                await websocket.send_json({
                    "type": "ai_message",
                    "content": ai_response
                })
                
            except Exception as e:
                print(f"❌ Erreur agent : {e}")
                import traceback
                traceback.print_exc()
                
                error_msg = "Désolé, une erreur s'est produite. Pouvez-vous reformuler votre demande ?"
                SESSIONS[session_id]["history"].append({"role": "assistant", "content": error_msg})
                
                await websocket.send_json({
                    "type": "ai_message",
                    "content": error_msg
                })
    
    except WebSocketDisconnect:
        print(f"✋ Session {session_id} déconnectée")
    except Exception as e:
        print(f"❌ Erreur WebSocket : {e}")
        import traceback
        traceback.print_exc()


@app.get("/health")
def health_check():
    return {"status": "ok", "active_sessions": len(SESSIONS)}


@app.get("/debug/session/{session_id}")
def debug_session(session_id: str):
    """Endpoint pour debugger une session"""
    if session_id not in SESSIONS:
        return {"error": "Session introuvable"}
    
    return {
        "session_id": session_id,
        "module": SESSIONS[session_id].get("module"),
        "fields_filled": len(SESSIONS[session_id].get("fields_covered", {})),
        "questions_asked": SESSIONS[session_id].get("questions_asked", []),
        "fields": SESSIONS[session_id].get("fields_covered", {}),
        "last_question": SESSIONS[session_id].get("last_question"),
        "history_length": len(SESSIONS[session_id].get("history", []))
    }