import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain.agents import create_agent
import asyncio

load_dotenv()

app = FastAPI()

# ─── LLM ───
llm = ChatGroq(
    model_name="openai/gpt-oss-120b",
    temperature=0,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

# ─── État partagé par session WebSocket ───
SESSION_STATE = {
    "mapping": {},
    "questions": [],
    "responses": {},
    "config_finale": {},
    "pending_question": None,   # la question en attente de réponse du user
    "user_answer": None,        # la réponse du user (mise par le WebSocket)
}

# ─── Outils ───
@tool
def load_module_mapping(module_name: str) -> str:
    """Charge le fichier mapping JSON d'un module Odoo.

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

    SESSION_STATE["mapping"] = data
    SESSION_STATE["questions"] = data.get("questions_mapping", [])
    SESSION_STATE["responses"] = {}

    summary = [
        f"Q{i+1} : {q['question']} (champ: {q['odoo_field']}, type: {q.get('data_type','text')})"
        for i, q in enumerate(SESSION_STATE["questions"])
    ]
    return f"Mapping chargé. {len(summary)} question(s) :\n" + "\n".join(summary)


@tool
def ask_user_question(question_index: int) -> str:
    """Pose la question à l'index donné à l'utilisateur via l'interface.
    Cette fonction BLOQUE jusqu'à ce que l'utilisateur réponde via le WebSocket.

    Args:
        question_index: L'index de la question (commence à 0)
    """
    questions = SESSION_STATE["questions"]
    if question_index < 0 or question_index >= len(questions):
        return f"Index invalide. Questions : 0 à {len(questions)-1}"

    item = questions[question_index]

    # On met la question en attente — le WebSocket la poussera au frontend
    SESSION_STATE["pending_question"] = {
        "index": question_index,
        "total": len(questions),
        "question": item["question"],
        "odoo_field": item["odoo_field"],
        "options": item.get("options", []),
        "data_type": item.get("data_type", "text"),
    }
    SESSION_STATE["user_answer"] = None

    # On attend que le frontend envoie la réponse (polling rapide)
    import time
    timeout = 300  # 5 minutes max
    start = time.time()
    while SESSION_STATE["user_answer"] is None:
        time.sleep(0.3)
        if time.time() - start > timeout:
            return "Timeout : pas de réponse en 5 minutes."

    # Récupérer et stocker la réponse
    raw = SESSION_STATE["user_answer"]
    SESSION_STATE["pending_question"] = None

    # Conversion selon le type
    if item.get("data_type") == "boolean":
        raw = raw.lower() in ("oui", "o", "true", "1")
    elif item.get("data_type") == "integer":
        try:
            raw = int(raw)
        except ValueError:
            return "Erreur : réponse non valide pour un nombre."

    SESSION_STATE["responses"][item["odoo_field"]] = raw
    return f"Réponse enregistrée : {item['odoo_field']} = {raw}"


@tool
def generate_config_json() -> str:
    """Génère le JSON de configuration Odoo final depuis les réponses collectées.
    Appeler APRÈS que toutes les questions sont posées.
    """
    if not SESSION_STATE["responses"]:
        return "Erreur : aucune réponse collectée."
    if not SESSION_STATE["mapping"]:
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
        "sondage": json.dumps(SESSION_STATE["responses"], ensure_ascii=False),
        "mapping": json.dumps(SESSION_STATE["mapping"], ensure_ascii=False),
    })

    SESSION_STATE["config_finale"] = config
    return f"JSON généré :\n{json.dumps(config, indent=4, ensure_ascii=False)}"


@tool
def save_config_to_file(filename: str = "config_odoo.json") -> str:
    """Sauvegarde le JSON de configuration dans un fichier.

    Args:
        filename: Nom du fichier (par défaut: config_odoo.json)
    """
    config = SESSION_STATE.get("config_finale")
    if not config:
        return "Erreur : pas de config générée."

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    return f"Sauvegardé dans '{filename}' ✅"


# ─── Agent ───
tools = [load_module_mapping, ask_user_question, generate_config_json, save_config_to_file]
agent = create_agent(llm, tools)

# ─── WebSocket : communication temps réel avec le frontend ───
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()

            # ── Le user choisit un module → on lance l'agent dans un thread ──
            if data.get("action") == "start_module":
                module = data["module"]

                # Reset état
                SESSION_STATE.update({
                    "mapping": {},
                    "questions": [],
                    "responses": {},
                    "config_finale": {},
                    "pending_question": None,
                    "user_answer": None,
                })

                await websocket.send_json({"type": "status", "message": f"🚀 Lancement du module {module}..."})

                # Lance l'agent dans un thread séparé (sinon il bloque le WebSocket)
                loop = asyncio.get_event_loop()
                def run_agent():
                    return agent.invoke({
                        "messages": [
                            ("human",
                             f"Fais ces étapes dans l'ordre :\n"
                             f"1. Appelle load_module_mapping('{module}')\n"
                             f"2. Lis le résultat pour savoir combien de questions\n"
                             f"3. Appelle ask_user_question pour chaque question, index 0, 1, 2...\n"
                             f"4. Après la dernière question, appelle generate_config_json\n"
                             f"5. Appelle save_config_to_file('config_{module}.json')\n")
                        ]
                    })

                await loop.run_in_executor(None, run_agent)

                # Après que l'agent fini, envoyer le résultat final
                await websocket.send_json({
                    "type": "done",
                    "config": SESSION_STATE.get("config_finale", {}),
                })

            # ── Le user répond à une question ──
            elif data.get("action") == "answer_question":
                SESSION_STATE["user_answer"] = data["answer"]

            # ── Polling du frontend pour savoir s'il y a une question en attente ──
            elif data.get("action") == "poll":
                q = SESSION_STATE.get("pending_question")
                if q:
                    await websocket.send_json({"type": "question", **q})

    except WebSocketDisconnect:
        pass


# ─── Health check ───
@app.get("/health")
def health():
    return {"status": "ok"}
