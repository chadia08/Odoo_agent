import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
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
    max_tokens=400,
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
# RESPONSE INTERPRETER (LE CŒUR)
# =========================================================

INTERPRETER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """
Tu es un interpréteur de réponses utilisateur pour un assistant de configuration Odoo.

On te donne :
- question
- data_type (boolean, string, integer)
- user_answer

Tu dois répondre STRICTEMENT en JSON avec :
- action : SAVE | ASK_CONFIRMATION | EXPLAIN | INVALID
- value : true / false / string / integer / null
- message : string ou null

Règles :
- Si l'utilisateur pose une question → EXPLAIN
- Si la réponse est ambiguë → ASK_CONFIRMATION
- Si la réponse est valide → SAVE
- Si hors sujet → INVALID
- N'invente jamais de valeur
"""
    ),
    (
        "human",
        """
question: {question}
data_type: {data_type}
user_answer: {user_answer}
"""
    )
])

interpreter_chain = INTERPRETER_PROMPT | llm | JsonOutputParser()

# =========================================================
# TOOLS LANGGRAPH
# =========================================================

@tool
def get_current_question(module_name: str, session_id: str) -> str:
    """
    Retourne la question courante du module pour une session donnée.
    Renvoie FIN_QUESTIONS si toutes les questions ont été posées.
    """
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
    """
    Sauvegarde une réponse validée pour un champ Odoo donné
    et incrémente l’index de la session.
    """
    USER_ANSWERS.setdefault(session_id, {})
    USER_ANSWERS[session_id][field] = value
    USER_INDEX[session_id] += 1
    return "OK"


@tool
def generate_config_file(module_name: str, session_id: str) -> str:
    """
    Génère le fichier JSON final de configuration Odoo
    à partir des réponses collectées.
    """
    filename = f"config_{module_name}_final.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(USER_ANSWERS.get(session_id, {}), f, indent=4, ensure_ascii=False)
    return f"FICHIER_CREE:{filename}"


# =========================================================
# AGENT (ORCHESTRATION)
# =========================================================

SYSTEM_PROMPT = """
Tu es un assistant de configuration Odoo.
- Pose une seule question à la fois
- Ne réponds jamais à la place de l'utilisateur
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

            # =================================================
            # 1️⃣ CHOIX MODULE
            # =================================================
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
                    "text": question["question"]
                })
                continue

            # =================================================
            # 2️⃣ INTERPRÉTATION RÉPONSE
            # =================================================
            path = MODULE_FILES[module_name]
            with open(path, "r", encoding="utf-8") as f:
                questions = json.load(f)["questions_mapping"]

            if USER_INDEX[session_id] >= len(questions):
                break

            current_q = questions[USER_INDEX[session_id]]

            interpretation = interpreter_chain.invoke({
                "question": current_q["question"],
                "data_type": current_q["data_type"],
                "user_answer": user_text
            })

            action = interpretation["action"]

            if action == "SAVE":
                save_response.invoke({
                    "field": current_q["odoo_field"],
                    "value": interpretation["value"],
                    "session_id": session_id
                })

            elif action in {"ASK_CONFIRMATION", "EXPLAIN", "INVALID"}:
                await ws.send_json({
                    "type": "ai_answer",
                    "text": interpretation["message"]
                })
                continue

            # =================================================
            # 3️⃣ QUESTION SUIVANTE / FIN
            # =================================================
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
                "text": next_q["question"]
            })

    except WebSocketDisconnect:
        pass
