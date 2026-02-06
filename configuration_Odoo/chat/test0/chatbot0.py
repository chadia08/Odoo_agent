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

# =========================================================
# INIT
# =========================================================

load_dotenv()
app = FastAPI()

llm = ChatGroq(
    model_name="openai/gpt-oss-120b",
    temperature=0,
    max_tokens=300,
    groq_api_key=os.getenv("GROQ_API_KEY"),
)

memory = MemorySaver()

USER_INDEX = {}
USER_ANSWERS = {}

MODULE_FILES = {
    "sales": "KD/sales_mapping.json",
    "crm": "KD/crm_mapping.json",
    "facturation": "KD/facturation_mapping.json",
}

# =========================================================
# LOGIQUE MÉTIER
# =========================================================

POSITIVE_HINTS = {
    "oui", "yes", "ok", "bien sûr", "bien sur",
    "pourquoi pas", "évidemment", "clairement", "bien sur"
}
NEGATIVE_HINTS = {"non", "no", "pas du tout", "jamais"}


def normalize_boolean(text: str):
    t = text.lower().strip()

    if t in POSITIVE_HINTS:
        return True
    if t in NEGATIVE_HINTS:
        return False

    if any(w in t for w in ["peut", "probablement", "ça dépend", "ca depend", "why not"]):
        return None

    return None


def parse_answer(answer: str, data_type: str):
    if data_type == "boolean":
        return normalize_boolean(answer)

    if data_type == "integer":
        return int(answer) if answer.isdigit() else "INVALID"

    if data_type == "string":
        return answer.strip() if answer.strip() else "INVALID"

    return "INVALID"


def format_question(q: dict):
    if q["data_type"] == "boolean":
        return f'{q["question"]} (Oui / Non)'
    return q["question"]

# =========================================================
# TOOLS
# =========================================================

@tool
def get_current_question(module_name: str, session_id: str) -> str:
    """Retourne la question courante ou FIN_QUESTIONS."""
    path = MODULE_FILES.get(module_name)
    if not path or not os.path.exists(path):
        return "MODULE_NOT_FOUND"

    with open(path, "r", encoding="utf-8") as f:
        questions = json.load(f).get("questions_mapping", [])

    idx = USER_INDEX.get(session_id, 0)

    if idx >= len(questions):
        return "FIN_QUESTIONS"

    return json.dumps(questions[idx], ensure_ascii=False)


@tool
def save_response(field: str, value, session_id: str) -> str:
    """Sauvegarde la réponse validée."""
    USER_ANSWERS.setdefault(session_id, {})
    USER_ANSWERS[session_id][field] = value
    USER_INDEX[session_id] += 1
    return "OK"


@tool
def generate_config_file(module_name: str, session_id: str) -> str:
    """Génère le fichier JSON final."""
    filename = f"config_{module_name}_final.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(USER_ANSWERS.get(session_id, {}), f, indent=4, ensure_ascii=False)
    return f"FICHIER_CREE:{filename}"

# =========================================================
# AGENT
# =========================================================

SYSTEM_PROMPT = """
Tu es un assistant de configuration Odoo.
Règles strictes :
- Une seule question à la fois
- Respecte data_type
- Si ambigu pour booléen → demande confirmation
- N'invente jamais de question
- À FIN_QUESTIONS → generate_config_file
"""

agent = create_react_agent(
    llm,
    tools=[get_current_question, save_response, generate_config_file],
    checkpointer=memory,
)

# =========================================================
# ROUTES
# =========================================================

@app.get("/")
async def get_interface():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "index.html")
    )


@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    await ws.accept()

    USER_INDEX[session_id] = 0
    USER_ANSWERS[session_id] = {}
    module_name = None

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("text", "").strip()

            # 1️⃣ Choix du module
            if module_name is None:
                module_name = user_text.lower()

                if module_name not in MODULE_FILES:
                    await ws.send_json({
                        "type": "ai_answer",
                        "text": "Module invalide. Choisissez : Sales, CRM ou Facturation."
                    })
                    module_name = None
                    continue

                await agent.ainvoke(
                    {
                        "messages": [
                            SystemMessage(content=SYSTEM_PROMPT),
                            HumanMessage(content=f"MODULE:{module_name}")
                        ]
                    },
                    {"configurable": {"thread_id": session_id}},
                )

                q = get_current_question.invoke({
                    "module_name": module_name,
                    "session_id": session_id
                })

                question = json.loads(q)
                await ws.send_json({
                    "type": "ai_answer",
                    "text": format_question(question)
                })
                continue

            # 2️⃣ Traitement réponse
            path = MODULE_FILES[module_name]
            with open(path, "r", encoding="utf-8") as f:
                questions = json.load(f)["questions_mapping"]

            if USER_INDEX[session_id] >= len(questions):
                break

            current_q = questions[USER_INDEX[session_id]]
            parsed = parse_answer(user_text, current_q["data_type"])

            if parsed is None:
                await ws.send_json({
                    "type": "ai_answer",
                    "text": "Merci de confirmer clairement par **Oui** ou **Non**."
                })
                continue

            if parsed == "INVALID":
                await ws.send_json({
                    "type": "ai_answer",
                    "text": "Réponse invalide. Merci de respecter le format attendu."
                })
                continue

            save_response.invoke({
                "field": current_q["odoo_field"],
                "value": parsed,
                "session_id": session_id
            })

            if USER_INDEX[session_id] >= len(questions):
                generate_config_file.invoke({
                    "module_name": module_name,
                    "session_id": session_id
                })
                await ws.send_json({
                    "type": "ai_answer",
                    "text": "✅ Configuration terminée. Fichier JSON généré."
                })
                break

            next_q = questions[USER_INDEX[session_id]]
            await ws.send_json({
                "type": "ai_answer",
                "text": format_question(next_q)
            })

    except WebSocketDisconnect:
        pass
