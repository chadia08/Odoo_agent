import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# =========================
# INIT
# =========================

load_dotenv()
app = FastAPI()

llm = ChatGroq(
    model_name="openai/gpt-oss-120b",
    temperature=0,
    max_tokens=500,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

USER_PROGRESS = {}
FINAL_ANSWERS = {}

# =========================
# NORMALISATION DES RÉPONSES
# =========================

def normalize_user_input(text: str) -> str:
    if not text:
        return text

    t = text.lower().strip()

    OUI = [
        "oui", "ok", "d'accord", "pourquoi pas",
        "oui je veux", "ça marche", "yes"
    ]

    NON = [
        "non", "pas besoin", "inutile",
        "non merci", "no"
    ]

    if t in OUI:
        return "oui"

    if t in NON:
        return "non"

    return text

# =========================
# TOOLS
# =========================

@tool
def get_current_question(module_name: str, session_id: str) -> str:
    """Retourne la question courante"""
    file_map = {
        "sales": "KD/sales_mapping.json",
        "crm": "KD/crm_mapping.json",
        "facturation": "KD/facturation_mapping.json"
    }

    path = file_map.get(module_name.lower())
    if not path or not os.path.exists(path):
        return "MODULE_INCONNU"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        questions = data.get("questions_mapping", [])

    idx = USER_PROGRESS.get(session_id, 0)
    if idx >= len(questions):
        return "FIN_QUESTIONS"

    q = questions[idx]
    question = q.get("question", "").strip()
    field = q.get("odoo_field", "").strip()

    # Sécurité anti-question cassée
    if not question or not field:
        USER_PROGRESS[session_id] = idx + 1
        return get_current_question(module_name, session_id)

    return json.dumps(
        {"question": question, "field": field},
        ensure_ascii=False
    )

@tool
def save_response(field: str, value: bool, session_id: str) -> str:
    """Sauvegarde la réponse"""
    if session_id not in FINAL_ANSWERS:
        FINAL_ANSWERS[session_id] = {}

    FINAL_ANSWERS[session_id][field] = value
    USER_PROGRESS[session_id] = USER_PROGRESS.get(session_id, 0) + 1
    return "OK"

@tool
def generate_config_file(module_name: str, session_id: str) -> str:
    """Génère le fichier JSON final"""
    answers = FINAL_ANSWERS.get(session_id, {})
    filename = f"config_{module_name.lower()}_final.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=4, ensure_ascii=False)

    return f"FICHIER_CREE: {filename}"

tools = [get_current_question, save_response, generate_config_file]
memory = MemorySaver()

# =========================
# SYSTEM PROMPT FINAL (STABLE)
# =========================

SYSTEM_PROMPT = """Tu es un expert Odoo qui anime un atelier de configuration client.

MISSION :
1. Poser les questions UNE PAR UNE.
2. Chaque question attend une décision booléenne.
3. Interpréter la réponse du client selon les règles ci-dessous.
4. Dès que la décision est claire, appeler 'save_response'.
5. Après chaque sauvegarde, appeler 'get_current_question'.
6. Quand 'get_current_question' renvoie 'FIN_QUESTIONS', appeler 'generate_config_file'.

INTERPRÉTATION DES RÉPONSES :
- OUI = "oui", "ok", "d'accord", "pourquoi pas", "oui je veux", "ça marche", "yes"
- NON = "non", "pas besoin", "inutile", "non merci", "no"
- "Pourquoi pas" = OUI par défaut
- Si le client pose une question ("c quoi", "à quoi ça sert"), expliquer brièvement puis redemander OUI/NON.

RÈGLE ABSOLUE :
- Si la réponse est interprétée comme OUI ou NON,
  tu DOIS immédiatement appeler 'save_response'
  et tu N’AS PAS LE DROIT d’expliquer, de reformuler,
  ou de reposer la question.

RÈGLES STRICTES :
- Ne JAMAIS inventer une question.
- Ne JAMAIS poser plusieurs questions.
- Ne JAMAIS rester bloqué sans appeler un outil.
- Ne JAMAIS afficher ton raisonnement interne.
"""

agent_executor = create_react_agent(
    llm,
    tools,
    checkpointer=memory
)

# =========================
# ROUTES
# =========================

@app.get("/")
async def get_interface():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    await websocket.accept()

    USER_PROGRESS[session_id] = 0
    FINAL_ANSWERS[session_id] = {}

    config = {"configurable": {"thread_id": session_id}}

    try:
        while True:
            data = await websocket.receive_json()
            user_text = normalize_user_input(data.get("text"))

            result = await agent_executor.ainvoke(
                {
                    "messages": [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=user_text)
                    ]
                },
                config
            )

            await websocket.send_json({
                "type": "ai_answer",
                "text": result["messages"][-1].content
            })

    except WebSocketDisconnect:
        pass
