import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# 1. Chargement du .env (situé un dossier au-dessus de 'configuration_odoo')
load_dotenv(os.path.join('..', '.env'))

# 2. Configuration Client Groq
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("api_key"),
)

# Modèle performant sur Groq (Llama 3 70b est excellent pour l'extraction de données)
MODEL = "llama-3.3-70b-versatile" 

def agent_interprete(question, reponse_user, data_type, options=None):
    """L'IA convertit la réponse libre en valeur technique Odoo."""
    prompt = f"""
    En tant qu'expert Odoo, convertis la réponse utilisateur en valeur technique.
    Question Odoo : {question}
    Réponse client : {reponse_user}
    Type attendu : {data_type}
    {f'Options possibles : {options}' if options else ''}
    
    Réponds UNIQUEMENT par la valeur finale : 
    - Si boolean : true ou false
    - Si selection : le nom de l'option technique
    - Si integer : le nombre
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0 # Pour plus de précision technique
        )
        
        res = response.choices[0].message.content.strip().lower()
        
        # Nettoyage et conversion
        if data_type == "boolean":
            return "true" in res or "oui" in res or "yes" in res
        if data_type == "integer":
            import re
            nums = re.findall(r'\d+', res)
            return int(nums[0]) if nums else 0
        return res
    except Exception as e:
        print(f"Erreur lors de l'appel Groq : {e}")
        return None

def run_configuration():
    # Liste des fichiers dans ton dossier 'KD'
    catalogues = ["sale_mapping.json", "crm_mapping.json", "account_mapping.json"]
    config_finale = {}

    print("--- DÉBUT DE LA MISSION DE CONFIGURATION ODOO (GROQ) ---")

    for cat_file in catalogues:
        path = os.path.join("KD", cat_file)
        if not os.path.exists(path):
            print(f"Fichier manquant : {path}")
            continue
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"\n🚀 MODULE : {data['module'].upper()}")

        for item in data['questions_mapping']:
            print(f"\n[?] {item['question']}")
            user_input = input("Réponse (ou 's' pour passer) : ")
            
            if user_input.lower() == 's':
                continue

            valeur = agent_interprete(
                item['question'], 
                user_input,     
                item['data_type'], 
                item.get('options')
            )
            
            if valeur is not None:
                config_finale[item['odoo_field']] = valeur
                print(f"   -> Mapping : {item['odoo_field']} = {valeur}")

    # Sauvegarde du JSON final
    output_name = "configuration_finale_odoo.json"  
    with open(output_name, 'w', encoding='utf-8') as f:
        json.dump(config_finale, f, indent=4)
    
    print(f"\n--- MISSION TERMINÉE ---")
    print(f"Fichier généré : {os.path.abspath(output_name)}")

if __name__ == "__main__":
    run_configuration()