import streamlit as st
import os
import json
import xmlrpc.client
import ssl
from dotenv import load_dotenv
from groq import Groq

# --- CONFIGURATION & ENV ---
load_dotenv()
st.set_page_config(page_title="AI Agent CFO - Odoo", layout="wide")
client = Groq(api_key=os.getenv("api_key"))

# --- FONCTIONS OUTILS (BACKEND ODOO) ---
def get_odoo_models():
    url, db, user, pwd = os.getenv("ODOO_URL"), os.getenv("ODOO_DB"), os.getenv("ODOO_USER"), os.getenv("ODOO_PASS")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", context=ssl._create_unverified_context())
    uid = common.authenticate(db, user, pwd, {})
    return xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", context=ssl._create_unverified_context()), uid, pwd, db

def odoo_fetch_sales(client_name=None):
    models, uid, pwd, db = get_odoo_models()
    domain = [('state', 'in', ['sale', 'done'])]
    if client_name: domain.append(('partner_id', 'ilike', client_name))
    sales = models.execute_kw(db, uid, pwd, 'sale.order', 'search_read', [domain], {'fields': ['name', 'date_order', 'partner_id', 'amount_total'], 'limit': 10})
    return json.dumps(sales)

def odoo_fetch_stock():
    models, uid, pwd, db = get_odoo_models()
    stock = models.execute_kw(db, uid, pwd, 'product.product', 'search_read', [[('type', '=', 'product')]], {'fields': ['display_name', 'qty_available', 'list_price'], 'limit': 15})
    return json.dumps(stock)

def odoo_fetch_accounting_risk(client_name=None):
    models, uid, pwd, db = get_odoo_models()
    domain = [('state', '=', 'posted'), ('payment_state', 'not in', ['paid', 'reversed'])]
    if client_name: domain.append(('partner_id', 'ilike', client_name))
    invoices = models.execute_kw(db, uid, pwd, 'account.move', 'search_read', [domain], {'fields': ['name', 'amount_residual', 'invoice_date_due'], 'limit': 10})
    return json.dumps(invoices)

# --- CONFIGURATION DE L'AGENT ---
tools = [
    {"type": "function", "function": {"name": "odoo_fetch_sales", "description": "Récupère les ventes.", "parameters": {"type": "object", "properties": {"client_name": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "odoo_fetch_stock", "description": "Vérifie les stocks.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "odoo_fetch_accounting_risk", "description": "Vérifie les impayés.", "parameters": {"type": "object", "properties": {"client_name": {"type": "string"}}, "required": []}}}
]

# --- INTERFACE STREAMLIT ---
st.title("🕵️‍♂️ Agent Expert Pilotage Odoo")
st.markdown("Cet agent croise vos **Ventes**, vos **Stocks** et votre **Compta** en temps réel.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ex: Gemini est-il un bon client ?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        messages = [{"role": "system", "content": "Tu es un CFO Expert. Utilise tes outils pour analyser Ventes, Stocks et Risques avant de répondre."}] + st.session_state.messages
        
        # 1er Appel IA
        response = client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, tools=tools)
        response_msg = response.choices[0].message
        
        if response_msg.tool_calls:
            messages.append(response_msg)
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                with st.status(f"📡 Interrogation Odoo : {func_name}...", expanded=False):
                    if func_name == "odoo_fetch_sales": res = odoo_fetch_sales(**args)
                    elif func_name == "odoo_fetch_stock": res = odoo_fetch_stock()
                    else: res = odoo_fetch_accounting_risk(**args)
                    st.write(res)
                
                messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": func_name, "content": res})
            
            # Réponse finale
            final_res = client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages)
            full_response = final_res.choices[0].message.content
            st.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        else:
            st.markdown(response_msg.content)
            st.session_state.messages.append({"role": "assistant", "content": response_msg.content})