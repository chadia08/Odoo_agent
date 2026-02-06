import streamlit as st
import pandas as pd
import plotly.express as px
from groq import Groq
import xmlrpc.client
import ssl

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Odoo AI Pilotage", layout="wide")
st.title("🚀 Assistant de Pilotage Stratégique (AI)")

# --- CONNEXION ODOO ---
@st.cache_data
def get_odoo_data():
    url = 'https://econostic1.odoo.com'
    db = 'econostic1'
    username = 'consultant.econostic@gmail.com'
    password = 'wpV5*jZP$f#n8tj'
    context = ssl._create_unverified_context()
    
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", context=context)
    uid = common.authenticate(db, username, password, {})
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", context=context)
    
    fields = ['name', 'date_order', 'partner_id', 'amount_total', 'state']
    sales_raw = models.execute_kw(db, uid, password, 'sale.order', 'search_read', [[]], {'fields': fields})
    
    df = pd.DataFrame(sales_raw)
    # Nettoyage du nom du client
    df['client'] = df['partner_id'].apply(lambda x: x[1] if isinstance(x, list) else x)
    return df

# --- INITIALISATION DE LA MÉMOIRE DU CHAT ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CHARGEMENT DES DONNÉES ---
try:
    df = get_odoo_data()

    # --- BARRE LATÉRALE : INDICATEURS ---
    st.sidebar.header("📊 Indicateurs Clés")
    total_ca = df['amount_total'].sum()
    nb_ventes = len(df)
    # Calcul de la dépendance max
    ca_par_client = df.groupby('client')['amount_total'].sum()
    dep_client = (ca_par_client.max() / total_ca) * 100 if total_ca > 0 else 0

    st.sidebar.metric("Chiffre d'Affaires", f"{total_ca:,.2f} €")
    st.sidebar.metric("Nombre de Ventes", nb_ventes)
    st.sidebar.metric("Dépendance Client Max", f"{dep_client:.1f}%")
    
    if st.sidebar.button("Effacer la conversation"):
        st.session_state.messages = []
        st.rerun()

    # --- LAYOUT : VISUALISATION ---
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Répartition du CA par Client")
        fig = px.pie(df, values='amount_total', names='client', hole=0.4)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("Historique des Commandes")
        fig2 = px.bar(df, x='name', y='amount_total', color='state')
        st.plotly_chart(fig2, use_container_width=True)

    # --- AGENT IA : CHAT INTERACTIF ---
    st.divider()
    st.subheader("🤖 Votre Expert en Pilotage")

    # Affichage de l'historique des messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Zone de saisie
    if prompt := st.chat_input("Posez une question sur votre performance..."):
        
        # 1. Ajouter le message utilisateur à l'historique
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 2. Réponse de l'IA
        with st.chat_message("assistant"):
            # Filtre pour les salutations simples
            if prompt.lower().strip() in ['salut', 'bonjour', 'hello', 'hi']:
                response = "Bonjour ! Je suis votre assistant de pilotage. Comment puis-je vous aider à analyser vos données Odoo aujourd'hui ?"
                st.markdown(response)
            else:
                with st.spinner("Analyse stratégique en cours..."):
                    client = Groq(api_key="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")
                    context_text = df.to_markdown()
                    
                    # Préparation des messages avec historique et contexte
                    # Modifie cette partie dans ton bloc de code
                    messages_history = [
                        {
                            "role": "system", 
                            "content": f"""Tu es un Directeur Financier (CFO) virtuel. 
                            Tes données proviennent de ce tableau Odoo :
                            {context_text}
                            
                            RÈGLES CRITIQUES :
                            1. Ne donne JAMAIS de code Python ou d'instructions techniques Odoo sauf si on te le demande.
                            2. Fais les calculs toi-même immédiatement à partir du tableau fourni.
                            3. Si on demande 'la semaine dernière', nous sommes le jeudi 29 janvier 2026. La semaine dernière est la période du 19 au 25 janvier 2026.
                            4. Réponds toujours avec des chiffres précis et une analyse de performance."""
                        }
                    ]
                    # Ajout de l'historique récent (limité aux 5 derniers échanges pour la performance)
                    for m in st.session_state.messages[-10:]:
                        messages_history.append({"role": m["role"], "content": m["content"]})

                    completion = client.chat.completions.create(
                        model="openai/gpt-oss-120b",
                        messages=messages_history,
                        temperature=0.7,
                        stream=False
                    )
                    response = completion.choices[0].message.content
                    st.markdown(response)
            
            # 3. Ajouter la réponse à l'historique
            st.session_state.messages.append({"role": "assistant", "content": response})

except Exception as e:
    st.error(f"❌ Erreur : {e}")