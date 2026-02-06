from playwright.sync_api import sync_playwright
import json
import sys

# Forcer l'encodage pour Windows
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def extraire_config():
    with sync_playwright() as p:
        print("Lancement du navigateur...")
        browser = p.chromium.launch(headless=False) 
        context = browser.new_context()
        page = context.new_page()

        # 1. Connexion
        print("Tentative de connexion...")
        page.goto("https://econostic1.odoo.com/web/login", wait_until="domcontentloaded") 
        
        page.fill("#login", "consultant.econostic@gmail.com")
        page.fill("#password", "wpV5*jZP$f#n8tj")
        page.click("button[type='submit']")

        # On attend de voir la barre de menu Odoo au lieu d'attendre le réseau
        print("Attente du chargement du tableau de bord...")
        try:
            page.wait_for_selector(".o_main_navbar", timeout=15000)
        except:
            print("Note: Chargement lent, on continue quand meme...")

        # 2. Aller aux parametres de facturation via clics UI
        print("Navigation vers Facturation...")
        page.click("text=Facturation")
        page.wait_for_timeout(3000)

        print("Ouverture du menu Configuration...")
        page.click("text=Configuration")
        page.wait_for_timeout(3000)

        print("Ouverture des Parametres...")
        page.click("text=Paramètres")
        page.wait_for_timeout(3000)

        # 3. Extraction
        print("Extraction en cours...")
        # On s'assure que les boites de reglages sont visibles
        try:
            page.wait_for_selector(".o_setting_box", timeout=60000)
        except Exception as e:
            page.screenshot(path="timeout_o_setting_box.png", full_page=True)
            print("Capture d'ecran enregistree : timeout_o_setting_box.png")
            raise
        
        settings = page.query_selector_all(".o_setting_box")
        resultats = []

        for s in settings:
            # On cherche les noms techniques dans les attributs 'name'
            # Odoo stocke souvent le champ technique dans un div name="..."
            nom_tech_el = s.query_selector("div[name], input[name]")
            label_el = s.query_selector(".o_form_label")
            
            if nom_tech_el and label_el:
                t_name = nom_tech_el.get_attribute("name")
                label_text = label_el.inner_text().strip()
                
                if t_name and label_text:
                    # Description (aide)
                    desc_el = s.query_selector(".text-muted")
                    description = desc_el.inner_text().strip() if desc_el else ""

                    # Section (titre parent)
                    section = s.evaluate("""
                        (el) => {
                            let cur = el;
                            while (cur) {
                                let prev = cur.previousElementSibling;
                                while (prev) {
                                    if (prev.matches('h2, .o_horizontal_separator')) {
                                        return prev.innerText.trim();
                                    }
                                    prev = prev.previousElementSibling;
                                }
                                cur = cur.parentElement;
                            }
                            return '';
                        }
                    """)

                    # Type de champ et options
                    data_type = "integer/char"
                    options = []
                    checkbox_el = s.query_selector("input[type='checkbox']")
                    select_el = s.query_selector("select")
                    radio_els = s.query_selector_all("input[type='radio']")

                    if checkbox_el:
                        data_type = "boolean"
                    elif select_el or radio_els:
                        data_type = "selection"
                        if select_el:
                            for opt in select_el.query_selector_all("option"):
                                opt_text = opt.inner_text().strip()
                                if opt_text:
                                    options.append(opt_text)
                        elif radio_els:
                            for r in radio_els:
                                label = r.evaluate("""
                                    (el) => {
                                        const id = el.getAttribute('id');
                                        if (id) {
                                            const lbl = document.querySelector(`label[for="${id}"]`);
                                            if (lbl) return lbl.innerText.trim();
                                        }
                                        const parentLabel = el.closest('label');
                                        return parentLabel ? parentLabel.innerText.trim() : '';
                                    }
                                """)
                                if label:
                                    options.append(label)

                    question = label_text if label_text.endswith("?") else f"Voulez-vous activer {label_text} ?"

                    resultats.append({
                        "section": section,
                        "odoo_field": t_name,
                        "question": question,
                        "data_type": data_type,
                        "options": options,
                        "description": description
                    })

        # Sauvegarde
        with open("mapping_facturation_auto.json", "w", encoding="utf-8") as f:
            json.dump(resultats, f, indent=4, ensure_ascii=False)
        
        print(f"SUCCES ! {len(resultats)} champs extraits dans 'mapping_facturation_auto.json'")
        browser.close()

if __name__ == "__main__":
    extraire_config()
