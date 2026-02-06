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

# CORS pour le frontend
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
    temperature=0.2,  # Réduit pour plus de cohérence
    openai_api_key=os.getenv("OPENAI_API_KEY"),
)

# ═══════════════════════════════════════════════════════
# ÉTAT DES SESSIONS
# ═══════════════════════════════════════════════════════
SESSIONS: Dict[str, Dict[str, Any]] = {}
CURRENT_SESSION_ID: Optional[str] = None  # Session active pour les tools

MODULE_FILES = {
    "crm": "KD/crm_mapping.json",
    "sales": "KD/sales_mapping.json",
    "facturation": "KD/facturation_mapping.json",
}

# ═══════════════════════════════════════════════════════
# OUTILS DE L'AGENT
# ���══════════════════════════════════════════════════════

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
    
    # Stocke dans la session
    SESSIONS[session_id]["module"] = module_name
    SESSIONS[session_id]["mapping"] = mapping
    SESSIONS[session_id]["fields_covered"] = {}  # champs déjà remplis
    
    # Retourne un résumé structuré pour l'agent
    questions = mapping.get("questions_mapping", [])
    
    return json.dumps({
        "status": "success",
        "message": f"Module {module_name} chargé avec succès",
        "total_fields": len(questions),
        "first_5_fields": [q["odoo_field"] for q in questions[:5]]
    }, ensure_ascii=False, indent=2)


@tool
def extract_and_store_fields_automatically(user_message: str) -> str:
    """OUTIL OBLIGATOIRE : Analyse CHAQUE réponse du client et stocke automatiquement les configurations.
    
    TU DOIS APPELER CET OUTIL APRÈS CHAQUE RÉPONSE DU CLIENT (sauf s'il dit juste "oui" ou "non" de confirmation).
    
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
    
    # Prompt spécialisé pour extraction + conversion technique
    extraction_prompt = f"""
Tu es un expert en extraction de données pour Odoo. Analyse cette réponse du client et extrait TOUTES les informations pertinentes pour la configuration Odoo.

RÉPONSE CLIENT:
{user_message}

CHAMPS DISPONIBLES (avec leurs valeurs techniques autorisées):
{json.dumps(fields_structure, ensure_ascii=False, indent=2)}

INSTRUCTIONS CRITIQUES:
1. Pour chaque information identifiée, trouve le odoo_field correspondant
2. Si le champ a un "options_mapping", tu DOIS convertir la réponse vers la VALEUR TECHNIQUE (la valeur du mapping, pas la clé)
   Exemple: si options_mapping = {{"Facturer les produits livrés": "delivery"}}, retourne "delivery"
3. Si c'est un boolean, retourne true ou false (pas "oui"/"non")
4. Si c'est un integer, retourne un nombre
5. Si c'est une selection sans mapping, retourne EXACTEMENT une des options listées
6. Ne stocke JAMAIS le texte brut du client — uniquement les valeurs techniques Odoo

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
    "unrelated_info": "texte si hors sujet"
}}
"""
    
    response = llm.invoke([HumanMessage(content=extraction_prompt)])
    
    try:
        # Parse la réponse JSON
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        extracted = json.loads(content)
    except Exception as e:
        return json.dumps({"error": "Échec de l'extraction", "details": str(e), "raw": response.content[:500]})
    
    # Étape 2 : Stockage automatique des champs avec high/medium confidence
    stored_fields = []
    failed_fields = []
    
    for odoo_field, field_data in extracted.get("extracted_fields", {}).items():
        confidence = field_data.get("confidence", "low")
        
        if confidence in ["high", "medium"]:
            # Validation du champ
            field_def = next(
                (f for f in fields_structure if f["odoo_field"] == odoo_field),
                None
            )
            
            if not field_def:
                failed_fields.append(f"{odoo_field} (champ introuvable)")
                continue
            
            value = field_data["value"]
            data_type = field_def.get("data_type", "string")
            
            # Validation type
            if data_type == "boolean":
                if isinstance(value, bool):
                    pass  # OK
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
            
            # Stockage
            SESSIONS[session_id]["fields_covered"][odoo_field] = value
            stored_fields.append({
                "field": odoo_field,
                "value": value,
                "user_said": field_data.get("user_text", ""),
                "description": field_def.get("description", "")
            })
    
    result = {
        "status": "success",
        "stored_count": len(stored_fields),
        "stored_fields": stored_fields,
        "failed_fields": failed_fields,
        "needs_clarification": extracted.get("needs_clarification", []),
        "total_filled": len(SESSIONS[session_id]["fields_covered"])
    }
    
    print(f"✅ Stockage : {len(stored_fields)} champs enregistrés - Total: {len(SESSIONS[session_id]['fields_covered'])}")
    
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_configuration_progress() -> str:
    """Retourne l'état d'avancement ET la liste COMPLÈTE des champs manquants.
    
    UTILISE CE TOOL avant de proposer la génération pour être SÛR que tout est rempli.
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
    
    # TOUS les champs (pas de filtre is_config)
    missing_fields = [
        {
            "odoo_field": f["odoo_field"],
            "question": f["question"],
            "section": f.get("section", "Général"),
            "description": f.get("description", "")
        }
        for f in all_fields if f["odoo_field"] not in filled
    ]
    
    completion = (len(filled) / len(all_fields) * 100) if all_fields else 0
    
    return json.dumps({
        "module": SESSIONS[session_id].get("module"),
        "completion_percentage": round(completion, 1),
        "total_fields": len(all_fields),
        "filled_fields": len(filled),
        "missing_count": len(missing_fields),
        "missing_fields": missing_fields,  # Retourne TOUS les champs manquants
        "can_generate_config": len(missing_fields) == 0,  # ← STRICT : 100% requis
        "warning": "⚠️ ATTENTION : Il manque encore des champs critiques !" if missing_fields else "✅ Tout est complet !"
    }, ensure_ascii=False, indent=2)

@tool
def search_odoo_documentation(query: str) -> str:
    """Recherche dans la documentation Odoo pour expliquer un concept.
    
    Args:
        query: terme à chercher
    """
    mock_results = {
        "invoice policy": "La politique de facturation détermine quand une facture peut être créée. 'order' = facturer à la commande, 'delivery' = facturer à la livraison.",
        "payment terms": "Les conditions de paiement définissent les délais et échéances. Exemple: Net 30 jours, paiement immédiat, etc.",
        "product variants": "Les variantes permettent de gérer différentes versions d'un produit (tailles, couleurs).",
        "pricelist": "Les listes de prix permettent de définir des tarifs différents selon les clients, les quantités ou les périodes.",
        "delivery": "La gestion des livraisons permet de calculer automatiquement les frais de port et de suivre les expéditions.",
        "signature": "La signature électronique permet au client de valider sa commande en ligne de manière sécurisée."
    }
    
    result = mock_results.get(query.lower(), f"Documentation Odoo sur '{query}' : voir https://docs.odoo.com/search?q={query}")
    
    return json.dumps({
        "query": query,
        "source": "docs.odoo.com",
        "content": result
    }, ensure_ascii=False)


@tool
def generate_final_config_json() -> str:
    """Génère le fichier JSON final de configuration Odoo.
    
    APPELLE CE TOOL UNIQUEMENT quand le client confirme ou que la configuration est >= 70% complète.
    """
    global CURRENT_SESSION_ID
    session_id = CURRENT_SESSION_ID
    
    if not session_id:
        return json.dumps({"error": "Session ID non défini"})
    if session_id not in SESSIONS:
        return json.dumps({"error": "Session introuvable"})
    
    module = SESSIONS[session_id].get("module")
    mapping = SESSIONS[session_id].get("mapping", {})
    fields_covered = SESSIONS[session_id].get("fields_covered", {})
    
    # Pour facturation, on filtre is_config: true
    if module == "facturation":
        config_fields = [
            f["odoo_field"] 
            for f in mapping.get("questions_mapping", []) 
            if f.get("is_config", False)
        ]
        final_config = {k: v for k, v in fields_covered.items() if k in config_fields}
    else:
        final_config = fields_covered
    
    # Structure finale (SANS metadata)
    output = {
        "module": module,
        "configuration": final_config
    }
    
    # Sauvegarde
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
# PROMPT SYSTÈME SIMPLIFIÉ ET STRICT
# ═══════════════════════════════════════════════════════
CONSULTANT_SYSTEM_PROMPT = """Tu es un consultant Odoo expert. Ton rôle est de collecter TOUTES les informations nécessaires pour générer une configuration technique complète.

🎯 OBJECTIF
Générer un fichier JSON de configuration Odoo avec 100% des champs du mapping remplis.

📋 WORKFLOW OBLIGATOIRE (STRICT)

1. CHARGEMENT DU MODULE
   Dès que le client dit "CRM", "Sales" ou "Facturation" :
   → APPELLE load_module_mapping(module_name) IMMÉDIATEMENT
   → Note le nombre total de champs à remplir

2. QUESTION OUVERTE
   → Pose UNE question ouverte : "Parlez-moi de votre activité et de vos processus..."
   → Encourage le client à donner beaucoup de détails

3. EXTRACTION APRÈS CHAQUE RÉPONSE
   Après CHAQUE réponse du client (sauf "oui"/"non" de confirmation) :
   → APPELLE extract_and_store_fields_automatically(user_message)
   → Lis attentivement le résultat (stored_fields)
   → Affiche un résumé conversationnel avec ✅ (format ci-dessous)

4. VÉRIFICATION DE PROGRESSION
   Après chaque extraction :
   → APPELLE get_configuration_progress()
   → Lis le résultat :
     - Si can_generate_config = false : Il manque des champs !
     - Lis missing_fields et pose une question sur le PREMIER champ manquant
   → Continue jusqu'à can_generate_config = true

5. GÉNÉRATION (UNIQUEMENT SI 100% COMPLET)
   Quand can_generate_config = true :
   → Affiche un RÉCAPITULATIF COMPLET de TOUS les champs
   → Demande : "Tout est bon ? Je génère votre fichier ?"
   → Si le client confirme : APPELLE generate_final_config_json()

🚨 RÈGLES CRITIQUES

RÈGLE 1 : Gestion des doutes
Si l'utilisateur dit "je ne sais pas", "peut-être", "c'est utile ?" :
→ NE STOCKE PAS de valeur
→ Explique le bénéfice en 1 phrase simple
→ Demande : "Voulez-vous activer cette option ?"
→ Attends "oui" (→ true) ou "non" (→ false)

RÈGLE 2 : Validation stricte
AVANT de proposer la génération :
→ APPELLE get_configuration_progress()
→ Si missing_fields n'est pas vide : TU NE PEUX PAS générer
→ Pose une question sur le premier champ manquant

RÈGLE 3 : Questions ciblées pour les champs manquants
Utilise la "question" du mapping pour formuler ta question :
→ Si missing_fields[0].question = "Souhaitez-vous configurer des revenus récurrents ?"
→ Reformule : "Concernant les revenus récurrents, souhaitez-vous les activer pour suivre vos abonnements par exemple ?"

RÈGLE 4 : Pas de génération partielle
Si le client dit "génère" ou "ok" mais que missing_fields existe :
→ Réponds : "Il nous manque encore quelques informations importantes. Laissez-moi vous poser une dernière question : [question sur le premier champ manquant]"

📊 FORMAT DE CONFIRMATION

Après extract_and_store_fields_automatically :

""
Parfait ! Voici ce que j'ai noté :

✅ [Fonction 1 en langage clair]
   → [Bénéfice concret]

✅ [Fonction 2]
   → [Ce que ça permet]

... (liste TOUS les champs de stored_fields)

[Si des champs ont été refusés, mentionne-les aussi :]
❌ [Fonction refusée]
   → Vous avez choisi de ne pas l'activer

Est-ce que tout est correct ?
""

📋 FORMAT DE RÉCAPITULATIF FINAL

Avant génération (quand can_generate_config = true) :

""
Parfait ! Voici le récapitulatif complet de votre configuration :

📋 **MODULE : [Nom]**

✅ [Liste TOUTES les fonctionnalités activées (true)]
❌ [Liste toutes les fonctionnalités désactivées (false)]

Tout est bon ? Je génère votre fichier de configuration ?
""

💬 TON ET STYLE

- Professionnel mais accessible
- Patient si le client hésite
- Jamais de jargon technique visible
- Une question à la fois
- Emoji ✅ ❌ 📋 pour structurer

🔧 EXEMPLES DE REFORMULATION

Jargon technique → Langage métier :
- group_use_recurring_revenues → "Suivi des revenus récurrents (abonnements)"
- crm_use_auto_assignment → "Assignation automatique des pistes aux vendeurs"
- module_crm_iap_mine → "Génération automatique de nouvelles pistes"
- module_crm_iap_enrich → "Enrichissement des données clients"

🎯 CHECKLIST AVANT GÉNÉRATION

Avant d'appeler generate_final_config_json() :
☑️ As-tu appelé get_configuration_progress() ?
☑️ Est-ce que can_generate_config = true ?
☑️ Est-ce que missing_fields est vide [] ?
☑️ As-tu affiché le récapitulatif complet au client ?
☑️ Le client a-t-il confirmé ?

Si UNE SEULE réponse est "non" : TU NE PEUX PAS GÉNÉRER.

RAPPEL FINAL : 100% des champs doivent être remplis. Pas d'exception.
"""
# ═══════════════════════════════════════════════════════
# CRÉATION DE L'AGENT
# ═══════════════════════════════════════════════════════
tools = [
    load_module_mapping,
    extract_and_store_fields_automatically,
    get_configuration_progress,
    search_odoo_documentation,
    generate_final_config_json,
]

# Prompt avec chat_history
prompt = ChatPromptTemplate.from_messages([
    ("system", CONSULTANT_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# Création de l'agent
agent = create_openai_functions_agent(llm, tools, prompt)

# AgentExecutor avec paramètres optimisés
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,  # Pour voir les appels de tools dans la console
    handle_parsing_errors=True,
    max_iterations=25,  # Augmenté pour éviter "iteration limit"
    max_execution_time=60,  # 60 secondes max par échange
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
    
    # Init session AVANT tout
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "history": [],
            "module": None,
            "mapping": {},
            "fields_covered": {},
        }
        
        # Message de bienvenue dans l'historique
        welcome_msg = "Bonjour ! Je suis votre consultant Odoo. Quel module souhaitez-vous configurer aujourd'hui : CRM, Sales ou Facturation ?"
        SESSIONS[session_id]["history"].append({"role": "assistant", "content": welcome_msg})
    
    try:
        # Message de bienvenue
        await websocket.send_json({
            "type": "ai_message",
            "content": "Bonjour ! Je suis votre consultant Odoo. Quel module souhaitez-vous configurer aujourd'hui : CRM, Sales ou Facturation ?"
        })
        
        while True:
            data = await websocket.receive_json()
            user_msg = data.get("message", "").strip()
            
            if not user_msg:
                continue
            
            # Stocke dans l'historique de session
            SESSIONS[session_id]["history"].append({"role": "user", "content": user_msg})
            
            # Set global session ID pour les tools
            global CURRENT_SESSION_ID
            CURRENT_SESSION_ID = session_id
            
            # Construit l'historique pour l'agent
            chat_history = []
            for msg in SESSIONS[session_id]["history"][:-1]:  # Exclut le dernier message user
                if msg["role"] == "user":
                    chat_history.append(HumanMessage(content=msg["content"]))
                else:
                    chat_history.append(AIMessage(content=msg["content"]))
            
            # Exécute l'agent avec AgentExecutor
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
                
                # Récupère la réponse finale
                ai_response = response["output"]
                
                print(f"\n{'='*60}")
                print(f"AGENT: {ai_response}")
                print(f"CHAMPS STOCKÉS: {len(SESSIONS[session_id]['fields_covered'])}")
                print(f"{'='*60}\n")
                
                SESSIONS[session_id]["history"].append({"role": "assistant", "content": ai_response})
                
                # Envoie au frontend
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
        "fields": SESSIONS[session_id].get("fields_covered", {}),
        "history_length": len(SESSIONS[session_id].get("history", []))
    }