import json
import os
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain.agents import create_agent

load_dotenv()

# ─── Modèle ───
llm = ChatGroq(
    model_name="openai/gpt-oss-120b",
    temperature=0,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

# ─── État partagé entre les outils ───
# L'agent ne peut pas "se souvenir" entre deux appels d'outils,
# donc on stocke les réponses ici pour qu'ils se lisent.
STATE = {
    "mapping": {},          # le mapping chargé
    "questions": [],        # la liste des questions extraites du mapping
    "responses": {},        # les réponses du user, clé = odoo_field
}

# ──────────────────────────────────────
# TOOL 1 : Charger le mapping d'un module
# ──────────────────────────────────────
@tool
def load_module_mapping(module_name: str) -> str:
    """Charge le fichier mapping JSON d'un module Odoo disponible.
    
    Args:
        module_name: Le nom du module parmi : 'sales', 'crm', 'facturation'
    """
    file_map = {
        "sales": "KD/sales_mapping.json",
        "crm": "KD/crm_mapping.json",
        "facturation": "KD/facturation_mapping.json",
    }

    path = file_map.get(module_name.lower())
    if not path or not os.path.exists(path):
        return f"Module '{module_name}' introuvable. Choix : sales, crm, facturation"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    STATE["mapping"] = data
    STATE["questions"] = data.get("questions_mapping", [])
    STATE["responses"] = {}

    # On retourne un résumé des questions à poser
    summary = [
        f"Q{i+1} : {q['question']} (champ: {q['odoo_field']}, type: {q.get('data_type','text')})"
        for i, q in enumerate(STATE["questions"])
    ]
    return f"Mapping chargé. {len(summary)} question(s) à poser :\n" + "\n".join(summary)


# ──────────────────────────────────────
# TOOL 2 : Poser UNE question à l'user
# ──────────────────────────────────────
@tool
def ask_user_question(question_index: int) -> str:
    """Pose la question numéro X à l'utilisateur dans le terminal et récupère sa réponse.
    
    Args:
        question_index: L'index de la question à poser (commence à 0)
    """
    questions = STATE["questions"]

    if question_index < 0 or question_index >= len(questions):
        return f"Index invalide. Questions disponibles : 0 à {len(questions)-1}"

    item = questions[question_index]
    question_text = item["question"]
    odoo_field = item["odoo_field"]
    options = item.get("options", [])
    data_type = item.get("data_type", "text")

    # ── Affichage dans le terminal ──
    print(f"\n{'─'*50}")
    print(f"  Question {question_index + 1}/{len(questions)}")
    print(f"  {question_text}")

    if options:
        print(f"  Options : {options}")
        print(f"  Tapez le numéro ou le texte de votre choix.")
    elif data_type == "boolean":
        print(f"  Répondez : Oui ou Non")
    elif data_type == "integer":
        print(f"  Répondez avec un nombre entier.")
    print(f"{'─'*50}")

    # ── Lecture de la réponse ──
    raw = input("  Votre réponse : ").strip()

    # ── Conversion selon le type ──
    if options and raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            raw = options[idx]

    if data_type == "boolean":
        raw = raw.lower() in ("oui", "o", "true", "1")
    elif data_type == "integer":
        try:
            raw = int(raw)
        except ValueError:
            return "Erreur : réponse non valide pour un nombre entier."

    # ── Sauvegarde dans l'état ──
    STATE["responses"][odoo_field] = raw
    return f"Réponse enregistrée : {odoo_field} = {raw}"


# ──────────────────────────────────────
# TOOL 3 : Générer le JSON de config
# ──────────────────────────────────────
@tool
def generate_config_json() -> str:
    """Génère le JSON de configuration Odoo final à partir des réponses collectées
    et du mapping chargé. Utilise le LLM pour produire un JSON technique propre.
    Appeler cette fonction APRÈS que toutes les questions ont été posées.
    """
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser

    if not STATE["responses"]:
        return "Erreur : aucune réponse collectée. Posez d'abord les questions."
    if not STATE["mapping"]:
        return "Erreur : aucun mapping chargé."

    parser = JsonOutputParser()
    prompt = ChatPromptTemplate.from_template(
        "Tu es un expert Odoo. Voici les réponses du client : {sondage}. "
        "Voici le mapping technique : {mapping}. "
        "CONSIGNE : Génère le JSON UNIQUEMENT pour les champs avec 'is_config': true. "
        "Réponds uniquement avec le JSON brut, sans explication."
    )
    chain = prompt | llm | parser
    config = chain.invoke({
        "sondage": json.dumps(STATE["responses"], ensure_ascii=False),
        "mapping": json.dumps(STATE["mapping"], ensure_ascii=False),
    })

    STATE["config_finale"] = config
    return f"JSON généré avec succès :\n{json.dumps(config, indent=4, ensure_ascii=False)}"


# ──────────────────────────────────────
# TOOL 4 : Sauvegarder le JSON
# ──────────────────────────────────────
@tool
def save_config_to_file(filename: str = "config_odoo.json") -> str:
    """Sauvegarde le JSON de configuration final dans un fichier sur disque.
    
    Args:
        filename: Le nom du fichier de sortie (par défaut: config_odoo.json)
    """
    config = STATE.get("config_finale")
    if not config:
        return "Erreur : pas de configuration générée. Lancez d'abord generate_config_json."

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    return f"Configuration sauvegardée dans '{filename}' ✅"


# ──────────────────────────────────────
# AGENT
# ──────────────────────────────────────
tools = [load_module_mapping, ask_user_question, generate_config_json, save_config_to_file]

agent = create_agent(llm, tools)

# ──────────────────────────────────────
# MAIN
# ──────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  AGENT DE CONFIGURATION ODOO 🤖")
    print("=" * 50)
    print("  Modules disponibles : sales, crm, facturation\n")

    module = input("  Quel module configurer ? ").strip()

    result = agent.invoke({
        "messages": [
            ("human",
             f"Charge le mapping du module '{module}', "
             f"pose chaque question à l'utilisateur une par une, "
             f"puis génère le JSON de configuration et sauvegarde-le.")
        ]
    })

    print("\n" + "=" * 50)
    print("  DONE — Vérifie le fichier config_odoo.json")
    print("=" * 50)