import { useState, useEffect } from "react";

// ─────────────────────────────────────────────
// DONNÉES RÉELLES — viennent de tes KD/*.json
// ─────────────────────────────────────────────
const CRM_DATA = {
  module: "crm",
  questions_mapping: [
    {
      section: "CRM",
      odoo_field: "group_use_recurring_revenues",
      question: "Souhaitez-vous configurer des plans et des revenus récurrents sur les opportunités dans le CRM ?",
      data_type: "boolean",
      description: "Définir des plans et des revenus récurrents sur les opportunités."
    },
    {
      section: "CRM",
      odoo_field: "group_use_lead",
      question: "Préférez-vous ajouter une étape de qualification avant de créer une opportunité pour mieux gérer les pistes ?",
      data_type: "boolean",
      description: "Ajouter une étape de qualification (Leads) avant de créer une opportunité."
    },
    {
      section: "CRM",
      odoo_field: "is_membership_multi",
      question: "Avez-vous besoin de la possibilité d'affecter des vendeurs à plusieurs équipes commerciales dans le CRM ?",
      data_type: "boolean",
      description: "Affecter des vendeurs à plusieurs équipes commerciales."
    },
    {
      section: "CRM",
      odoo_field: "crm_use_auto_assignment",
      question: "Souhaitez-vous configurer une assignation périodique des pistes en fonction de règles spécifiques dans le CRM ?",
      data_type: "boolean",
      description: "Attribuez périodiquement des pistes en fonction des priorités et des filtres."
    },
    {
      section: "Génération de pistes",
      odoo_field: "module_crm_iap_enrich",
      question: "Souhaitez-vous enrichir les pistes sur demande seulement ou préférez-vous enrichir automatiquement toutes les pistes ?",
      data_type: "boolean",
      description: "Enrichir vos pistes avec des données sur l'entreprise en fonction de leur adresse e-mail."
    },
    {
      section: "Génération de pistes",
      odoo_field: "module_crm_iap_mine",
      question: "Aimeriez-vous générer de nouvelles pistes en fonction de critères tels que le pays, le secteur d'activité, la taille de l'entreprise, etc. ?",
      data_type: "boolean",
      description: "Prospection de pistes : Générer de nouvelles pistes via les services IAP d'Odoo."
    },
    {
      section: "Génération de pistes",
      odoo_field: "module_website_crm_iap_reveal",
      question: "Souhaitez-vous convertir les visiteurs de votre site internet en piste dans le CRM et enrichir leurs données en se basant sur leur adresse IP ?",
      data_type: "boolean",
      description: "Visites en pistes : Conversion des visiteurs du site web en opportunités CRM."
    }
  ]
};

const VENTES_DATA = {
  module: "ventes",
  questions_mapping: [
    {
      section: "Catalogue des produits",
      odoo_field: "group_product_variant",
      question: "Souhaitez-vous gérer différentes variantes pour vos produits (tailles, couleurs, etc.) ?",
      data_type: "boolean",
      description: "Active les attributs et variantes de produits."
    },
    {
      section: "Catalogue des produits",
      odoo_field: "group_uom",
      question: "Vendez-vous des produits dans des unités de mesure différentes (ex: kilo, carton, unité) ?",
      data_type: "boolean",
      description: "Active la gestion des unités de mesure."
    },
    {
      section: "Catalogue des produits",
      odoo_field: "module_product_email_template",
      question: "Souhaitez-vous envoyer un email de confirmation automatique dès la validation d'une commande ?",
      data_type: "boolean",
      description: "Envoi d'un email automatique à la confirmation."
    },
    {
      section: "Tarifs",
      odoo_field: "group_discount_per_so_line",
      question: "Devez-vous appliquer des remises manuelles directement sur les lignes de vos devis ?",
      data_type: "boolean",
      description: "Autorise les remises par ligne de commande."
    },
    {
      section: "Tarifs",
      odoo_field: "group_product_pricelist",
      question: "Avez-vous besoin de gérer plusieurs listes de prix ou des tarifs spécifiques par client ?",
      data_type: "boolean",
      description: "Active les listes de prix avancées."
    },
    {
      section: "Tarifs",
      odoo_field: "module_loyalty",
      question: "Souhaitez-vous mettre en place des programmes de fidélité, des coupons ou des cartes cadeaux ?",
      data_type: "boolean",
      description: "Installe le module de fidélité et promotions."
    },
    {
      section: "Tarifs",
      odoo_field: "module_sale_margin",
      question: "Souhaitez-vous visualiser votre marge brute en temps réel sur vos devis ?",
      data_type: "boolean",
      description: "Affiche les marges sur les commandes."
    },
    {
      section: "Devis et commandes",
      odoo_field: "portal_confirmation_sign",
      question: "Voulez-vous autoriser vos clients à signer leurs devis en ligne ?",
      data_type: "boolean",
      description: "Active la signature électronique sur le portail."
    },
    {
      section: "Devis et commandes",
      odoo_field: "portal_confirmation_pay",
      question: "Souhaitez-vous que vos clients puissent payer directement en ligne pour confirmer leur commande ?",
      data_type: "boolean",
      description: "Active le paiement en ligne à la confirmation."
    },
    {
      section: "Devis et commandes",
      odoo_field: "quotation_validity_days",
      question: "Combien de jours vos devis restent-ils valables par défaut ?",
      data_type: "integer",
      description: "Délai de validité par défaut des offres."
    },
    {
      section: "Devis et commandes",
      odoo_field: "group_warning_sale",
      question: "Avez-vous besoin d'alertes visuelles sur les fiches clients ou produits lors de la vente ?",
      data_type: "boolean",
      description: "Active les messages d'avertissement."
    },
    {
      section: "Devis et commandes",
      odoo_field: "group_proforma_sales",
      question: "Avez-vous l'habitude d'émettre des factures Pro-forma avant la vente finale ?",
      data_type: "boolean",
      description: "Active l'option facture pro-forma."
    },
    {
      section: "Expéditions",
      odoo_field: "module_delivery",
      question: "Souhaitez-vous calculer automatiquement les frais de port sur vos commandes ?",
      data_type: "boolean",
      description: "Active les connecteurs de transporteurs et frais d'expédition."
    },
    {
      section: "Facturation",
      odoo_field: "default_invoice_policy",
      question: "Quelle est votre politique de facturation par défaut ?",
      data_type: "selection",
      options: ["Facturer les produits commandés", "Facturer les produits livrés"],
      options_mapping: {
        "Facturer les produits commandés": "order",
        "Facturer les produits livrés": "delivery"
      },
      description: "Détermine le moment où une commande peut être facturée."
    }
  ]
};

const FACTURATION_DATA = {
  module: "account",
  questions_mapping: [
    { section: "1. Contexte général", odoo_field: "info_objectifs", question: "Quels sont vos principaux objectifs en utilisant le module facturation d'Odoo ?", data_type: "selection", options: ["Suivi des paiements clients", "Émission rapide des factures", "Gestion des factures fournisseurs", "Conformité fiscale"], is_config: false },
    { section: "1. Contexte général", odoo_field: "info_erp_actuel", question: "Utilisez-vous déjà un ERP/logiciel pour la gestion comptable ?", data_type: "selection", options: ["Oui", "Non / Excel"], is_config: false },
    { section: "1. Contexte général", odoo_field: "info_gestion_compta", question: "Comment gérez-vous votre comptabilité ?", data_type: "selection", options: ["En interne", "Partiellement externalisé", "Totalement externalisé"], is_config: false },
    { section: "1. Contexte général", odoo_field: "info_integration_valeur", question: "Votre process comptable actuel est-il intégré avec la chaîne de valeur (Ventes/Achats/Inventaire) ?", data_type: "selection", options: ["Oui, totalement", "Partiellement", "Aucune intégration"], is_config: false },
    { section: "1. Contexte général", odoo_field: "info_journaux_specifiques", question: "Souhaitez-vous utiliser des journaux spécifiques pour différencier les types d'opérations ?", data_type: "selection", options: ["Oui, pour chaque type d'opération", "Oui, seulement opérations principales", "Non"], is_config: false },
    { section: "2. Facturation clients", odoo_field: "info_validation_ventes", question: "Avez-vous une politique de validation pour les factures de ventes ?", data_type: "selection", options: ["Oui", "Pour les paiements uniquement", "Pour les paiements de montants élevés", "Non"], is_config: false },
    { section: "2. Facturation clients", odoo_field: "info_modes_paiement_clients", question: "Quels modes de paiement utilisez-vous pour vos clients ?", data_type: "selection", options: ["Virement bancaire", "Carte de crédit", "Chèque", "Espèces", "Autre"], is_config: false },
    { section: "2. Facturation clients", odoo_field: "group_use_credit_limit", question: "Appliquez-vous une limite de crédit pour vos clients ?", data_type: "boolean", is_config: true },
    { section: "2. Facturation clients", odoo_field: "module_account_reports_followup", question: "Avez-vous besoin d'un système de suivi des paiements clients en retard ?", data_type: "selection", options: ["Oui, avec des rappels automatiques", "Oui, uniquement notifications manuelles", "Non"], is_config: true },
    { section: "3. Facturation fournisseurs", odoo_field: "info_validation_fournisseurs", question: "Avez-vous des politiques de validation spécifiques pour les factures fournisseurs ?", data_type: "selection", options: ["Oui, toutes les factures", "Oui, les paiements uniquement", "Oui, les paiements de montants élevés", "Non"], is_config: false },
    { section: "3. Facturation fournisseurs", odoo_field: "info_modes_paiement_achats", question: "Quels sont les moyens de paiements que vous utilisez pour les factures d'achats ?", data_type: "selection", options: ["Chèques", "Virement", "Effets", "Versements", "Autre"], is_config: false },
    { section: "3. Facturation fournisseurs", odoo_field: "module_account_batch_payment", question: "Souhaitez-vous utiliser les paiements par lots pour vos factures d'achat ?", data_type: "boolean", is_config: true },
    { section: "4. Gestion de trésorerie", odoo_field: "info_nb_comptes_bancaires", question: "Combien de comptes bancaires souhaitez-vous intégrer dans Odoo ?", data_type: "selection", options: ["1 seul compte", "2 à 5 comptes", "Plus de 5 comptes"], is_config: false },
    { section: "4. Gestion de trésorerie", odoo_field: "module_currency_rate_live", question: "Utilisez-vous des devises étrangères dans vos transactions ?", data_type: "boolean", is_config: true },
    { section: "4. Gestion de trésorerie", odoo_field: "info_conditions_paiement_particulieres", question: "Avez-vous des conditions de paiement particulières (ex : paiement partiel, échéance prolongée) ?", data_type: "selection", options: ["Oui, pour certains clients", "Oui, pour tous les clients", "Non"], is_config: false },
    { section: "4. Gestion de trésorerie", odoo_field: "module_account_reports", question: "Souhaitez-vous envoyer automatiquement des rappels pour les factures impayées ?", data_type: "selection", options: ["Oui, pour toutes les factures", "Oui, seulement certaines catégories", "Non"], is_config: true },
    { section: "5. Fiscalité", odoo_field: "tax_exigibility", question: "Quel est le régime de TVA que vous adoptez ?", data_type: "selection", options: ["TVA sur encaissement", "TVA sur engagement"], is_config: true },
    { section: "5. Fiscalité", odoo_field: "info_taux_tva_ventes", question: "Quels taux de TVA s'appliquent sur vos ventes ?", data_type: "selection", options: ["20 %", "10 %", "Autres"], is_config: false },
    { section: "5. Fiscalité", odoo_field: "info_taux_tva_achats", question: "Quels taux de TVA s'appliquent à vos achats ?", data_type: "selection", options: ["20%", "10%", "Autres"], is_config: false },
    { section: "5. Fiscalité", odoo_field: "info_declaration_tva_odoo", question: "Souhaitez-vous générer la déclaration de TVA sur Odoo ?", data_type: "boolean", is_config: false }
  ]
};

// ─────────────────────────────────────────────
// MODULES DISPONIBLES
// ─────────────────────────────────────────────
const MODULES = {
  crm:         { icon: "🎯", label: "CRM",         data: CRM_DATA },
  ventes:      { icon: "💰", label: "Ventes",      data: VENTES_DATA },
  facturation: { icon: "🧾", label: "Facturation", data: FACTURATION_DATA },
};

// ─────────────────────────────────────────────
// THEME
// ─────────────────────────────────────────────
const T = {
  bg: "#0f1117",
  card: "#1a1d27",
  accent: "#4ecca3",
  accentDim: "rgba(78,204,163,0.12)",
  blue: "#5b8dee",
  text: "#e2e4e9",
  textDim: "#7a7f8e",
  border: "#2a2d3a",
  red: "#e74c6f",
};

// ─────────────────────────────────────────────
// COMPOSANT PRINCIPAL
// ─────────────────────────────────────────────
export default function OdooAgent() {
  // screens: "home" | "survey" | "generating" | "result"
  const [screen, setScreen]             = useState("home");
  const [selectedModule, setSelectedModule] = useState(null);
  const [currentQ, setCurrentQ]         = useState(0);
  const [answers, setAnswers]           = useState({});
  const [answer, setAnswer]             = useState(null);
  const [configResult, setConfigResult] = useState(null);
  const [dots, setDots]                 = useState("");
  // section visuelle courante (pour la barre de section)
  const [currentSection, setCurrentSection] = useState("");

  // animation dots pendant génération
  useEffect(() => {
    if (screen !== "generating") return;
    const iv = setInterval(() => setDots(d => d.length >= 3 ? "" : d + "."), 500);
    return () => clearInterval(iv);
  }, [screen]);

  // met à jour la section courante quand la question change
  useEffect(() => {
    if (!selectedModule) return;
    const qs = MODULES[selectedModule].data.questions_mapping;
    if (qs[currentQ]) setCurrentSection(qs[currentQ].section);
  }, [currentQ, selectedModule]);

  // ── helpers ──
  const questions   = selectedModule ? MODULES[selectedModule].data.questions_mapping : [];
  const totalQ      = questions.length;
  const progress    = totalQ > 0 ? (currentQ / totalQ) * 100 : 0;
  const currentItem = questions[currentQ] || null;

  // sections uniques pour la barre latérale
  const sections = [...new Set(questions.map(q => q.section))];

  // ── actions ──
  const startModule = (key) => {
    setSelectedModule(key);
    setCurrentQ(0);
    setAnswers({});
    setAnswer(null);
    setScreen("survey");
  };

  const submitAnswer = () => {
    if (answer === null || answer === "") return;

    // si options_mapping existe (cas ventes/facturation), on mappe la valeur
    let finalValue = answer;
    if (currentItem.options_mapping && currentItem.options_mapping[answer] !== undefined) {
      finalValue = currentItem.options_mapping[answer];
    }

    const newAnswers = { ...answers, [currentItem.odoo_field]: finalValue };
    setAnswers(newAnswers);
    setAnswer(null);

    if (currentQ + 1 >= totalQ) {
      // dernière question → génération
      setScreen("generating");
      // simule un appel à l'agent (2s)
      setTimeout(() => {
        // Pour facturation : on filtre uniquement is_config: true dans le JSON final
        // Pour crm / ventes : on garde tout
        let config = { ...newAnswers };
        if (selectedModule === "facturation") {
          const configFields = questions
            .filter(q => q.is_config === true)
            .map(q => q.odoo_field);
          const filtered = {};
          configFields.forEach(f => { if (config[f] !== undefined) filtered[f] = config[f]; });
          config = filtered;
        }
        setConfigResult({
          module: MODULES[selectedModule].data.module,
          config,
          _generated_by: "groq/gpt-oss-120b",
          _timestamp: new Date().toISOString(),
        });
        setScreen("result");
      }, 2200);
    } else {
      setCurrentQ(currentQ + 1);
    }
  };

  const goHome = () => {
    setScreen("home");
    setSelectedModule(null);
    setCurrentQ(0);
    setAnswers({});
    setAnswer(null);
    setConfigResult(null);
  };

  // ─────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────
  return (
    <div style={{ minHeight: "100vh", background: T.bg, color: T.text, fontFamily: "'Segoe UI', sans-serif", display: "flex", flexDirection: "column", alignItems: "center", padding: "48px 20px" }}>

      {/* ── Header ── */}
      <div style={{ textAlign: "center", marginBottom: 40 }}>
        <div style={{ fontSize: 28, fontWeight: 700, background: `linear-gradient(135deg, ${T.accent}, ${T.blue})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          ⚙️ Odoo Config Agent
        </div>
        <div style={{ color: T.textDim, fontSize: 14, marginTop: 4 }}>Configuration intelligente via ReAct Agent</div>
      </div>

      {/* ════════════ HOME ════════════ */}
      {screen === "home" && (
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 16, padding: 32, width: "100%", maxWidth: 520 }}>
          <div style={{ color: T.textDim, fontSize: 12, textTransform: "uppercase", letterSpacing: 1, marginBottom: 16 }}>Sélectionnez un module</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {Object.entries(MODULES).map(([key, mod]) => (
              <button key={key} onClick={() => startModule(key)}
                style={{ background: "transparent", border: `1px solid ${T.border}`, borderRadius: 14, padding: "24px 10px", cursor: "pointer", color: T.text, fontFamily: "inherit", fontSize: 14, textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 10, transition: "all 0.2s" }}
                onMouseEnter={e => { e.currentTarget.style.background = T.accentDim; e.currentTarget.style.borderColor = T.accent; }}
                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = T.border; }}
              >
                <span style={{ fontSize: 30 }}>{mod.icon}</span>
                <span style={{ fontWeight: 600 }}>{mod.label}</span>
                <span style={{ color: T.textDim, fontSize: 11 }}>{mod.data.questions_mapping.length} questions</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ════════════ SURVEY ════════════ */}
      {screen === "survey" && currentItem && (
        <div style={{ width: "100%", maxWidth: 620, display: "flex", gap: 20 }}>

          {/* Barre sections (gauche) */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 140 }}>
            {sections.map((s, i) => {
              const sectionQs = questions.filter(q => q.section === s);
              const firstIdx  = questions.findIndex(q => q.section === s);
              const done      = currentQ > firstIdx + sectionQs.length - 1;
              const active    = s === currentSection;
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 3, height: 28, borderRadius: 2, background: done ? T.accent : active ? T.blue : T.border, transition: "background 0.3s" }} />
                  <span style={{ fontSize: 11, color: done ? T.accent : active ? T.text : T.textDim, fontWeight: active ? 600 : 400, transition: "color 0.3s" }}>{s}</span>
                </div>
              );
            })}
          </div>

          {/* Card question (droite) */}
          <div style={{ flex: 1, background: T.card, border: `1px solid ${T.border}`, borderRadius: 16, padding: 28 }}>

            {/* back */}
            <button onClick={goHome} style={{ background: "none", border: "none", color: T.textDim, fontFamily: "inherit", fontSize: 13, cursor: "pointer", marginBottom: 18, padding: 0 }}>← Retour</button>

            {/* progress bar */}
            <div style={{ width: "100%", height: 4, background: T.border, borderRadius: 2, marginBottom: 6, overflow: "hidden" }}>
              <div style={{ width: `${progress}%`, height: "100%", background: `linear-gradient(90deg, ${T.accent}, ${T.blue})`, borderRadius: 2, transition: "width 0.4s" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: T.textDim, marginBottom: 22 }}>
              <span>Question {currentQ + 1} / {totalQ}</span>
              <span style={{ color: T.accent }}>{Math.round(progress)}%</span>
            </div>

            {/* question texte */}
            <div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.5, marginBottom: 6 }}>{currentItem.question}</div>
            {currentItem.description && (
              <div style={{ fontSize: 12, color: T.textDim, marginBottom: 20, fontStyle: "italic" }}>{currentItem.description}</div>
            )}

            {/* ── INPUTS selon data_type ── */}

            {/* BOOLEAN → Oui / Non */}
            {currentItem.data_type === "boolean" && (
              <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                {["Oui", "Non"].map(opt => (
                  <button key={opt} onClick={() => setAnswer(opt === "Oui")}
                    style={{ flex: 1, padding: "14px 0", borderRadius: 10, border: `1px solid ${answer === (opt === "Oui") ? T.accent : T.border}`, background: answer === (opt === "Oui") ? T.accentDim : "transparent", color: T.text, fontFamily: "inherit", fontSize: 15, fontWeight: 600, cursor: "pointer", transition: "all 0.2s" }}
                  >
                    {answer === (opt === "Oui") && <span style={{ color: T.accent }}>✓ </span>}
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {/* SELECTION → options multiples */}
            {currentItem.data_type === "selection" && currentItem.options && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                {currentItem.options.map(opt => (
                  <button key={opt} onClick={() => setAnswer(opt)}
                    style={{ textAlign: "left", padding: "12px 16px", borderRadius: 10, border: `1px solid ${answer === opt ? T.accent : T.border}`, background: answer === opt ? T.accentDim : "transparent", color: T.text, fontFamily: "inherit", fontSize: 14, cursor: "pointer", transition: "all 0.15s" }}
                    onMouseEnter={e => { if (answer !== opt) e.currentTarget.style.borderColor = T.blue; }}
                    onMouseLeave={e => { if (answer !== opt) e.currentTarget.style.borderColor = T.border; }}
                  >
                    {answer === opt && <span style={{ color: T.accent }}>✓ </span>}
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {/* INTEGER → input nombre */}
            {currentItem.data_type === "integer" && (
              <input
                type="number"
                min="0"
                placeholder="Tapez un nombre..."
                value={answer ?? ""}
                onChange={e => setAnswer(e.target.value === "" ? null : Number(e.target.value))}
                onKeyDown={e => e.key === "Enter" && submitAnswer()}
                style={{ width: "100%", marginTop: 8, padding: "12px 16px", borderRadius: 10, border: `1px solid ${T.border}`, background: T.bg, color: T.text, fontFamily: "inherit", fontSize: 15, outline: "none", boxSizing: "border-box" }}
              />
            )}

            {/* Bouton Suivant / Générer */}
            <button
              onClick={submitAnswer}
              disabled={answer === null || answer === ""}
              style={{
                marginTop: 24, width: "100%", padding: "14px 0", borderRadius: 10, border: "none",
                background: `linear-gradient(135deg, ${T.accent}, ${T.blue})`,
                color: "#0f1117", fontFamily: "inherit", fontSize: 15, fontWeight: 700, cursor: answer === null || answer === "" ? "not-allowed" : "pointer",
                opacity: answer === null || answer === "" ? 0.35 : 1, transition: "opacity 0.2s"
              }}
            >
              {currentQ + 1 >= totalQ ? "Générer la configuration →" : "Suivant →"}
            </button>
          </div>
        </div>
      )}

      {/* ════════════ GÉNÉRATION ════════════ */}
      {screen === "generating" && (
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 16, padding: "60px 32px", width: "100%", maxWidth: 520, textAlign: "center" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🤖</div>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 6, background: `${T.accent}20`, border: `1px solid ${T.accent}50`, borderRadius: 20, padding: "4px 14px", fontSize: 13, color: T.accent, marginBottom: 20 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: T.accent, animation: "pulse 1.2s infinite" }} />
            Agent en cours
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>Génération du JSON{dots}</div>
          <div style={{ color: T.textDim, fontSize: 14 }}>L'agent appelle <code style={{ color: T.accent }}>generate_config_json()</code></div>

          {/* Logs */}
          <div style={{ background: T.bg, border: `1px solid ${T.border}`, borderRadius: 10, padding: 16, marginTop: 24, textAlign: "left", fontSize: 12, color: T.textDim, fontFamily: "'Consolas', monospace", lineHeight: 1.9 }}>
            <div><span style={{ color: T.accent }}>✓</span> load_module_mapping('<span style={{ color: T.blue }}>{selectedModule}</span>')</div>
            {questions.slice(0, currentQ + 1).map((_, i) => (
              <div key={i}><span style={{ color: T.accent }}>✓</span> ask_user_question(<span style={{ color: T.blue }}>{i}</span>)</div>
            ))}
            <div><span style={{ color: T.blue }}>⟳</span> generate_config_json(){dots}</div>
          </div>

          <style>{`@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.3; } }`}</style>
        </div>
      )}

      {/* ════════════ RÉSULTAT ════════════ */}
      {screen === "result" && configResult && (
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 16, padding: 32, width: "100%", maxWidth: 620 }}>
          {/* badge */}
          <div style={{ display: "inline-flex", alignItems: "center", gap: 6, background: `${T.accent}20`, border: `1px solid ${T.accent}50`, borderRadius: 20, padding: "4px 14px", fontSize: 13, color: T.accent, marginBottom: 18 }}>
            <span>✓</span> Configuration générée
          </div>

          <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>{MODULES[selectedModule].icon} Config {MODULES[selectedModule].label}</div>
          <div style={{ color: T.textDim, fontSize: 13, marginBottom: 16 }}>
            Fichier de sortie : <code style={{ color: T.accent }}>config_{MODULES[selectedModule].data.module}.json</code>
          </div>

          {/* JSON */}
          <div style={{ background: T.bg, border: `1px solid ${T.border}`, borderRadius: 10, padding: 18, overflowX: "auto", fontFamily: "'Consolas', monospace", fontSize: 13, lineHeight: 1.8, color: T.accent, whiteSpace: "pre" }}>
            {JSON.stringify(configResult, null, 2)}
          </div>

          {/* Boutons */}
          <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
            <button onClick={goHome}
              style={{ flex: 1, padding: "13px 0", borderRadius: 10, border: "none", background: `linear-gradient(135deg, ${T.accent}, ${T.blue})`, color: "#0f1117", fontFamily: "inherit", fontSize: 15, fontWeight: 700, cursor: "pointer" }}>
              ← Nouveau module
            </button>
            <button onClick={() => {
              // télécharge le JSON
              const blob = new Blob([JSON.stringify(configResult, null, 4)], { type: "application/json" });
              const url  = URL.createObjectURL(blob);
              const a    = document.createElement("a");
              a.href     = url;
              a.download = `config_${MODULES[selectedModule].data.module}.json`;
              a.click();
              URL.revokeObjectURL(url);
            }}
              style={{ padding: "13px 20px", borderRadius: 10, border: `1px solid ${T.border}`, background: "transparent", color: T.text, fontFamily: "inherit", fontSize: 14, cursor: "pointer" }}>
              ⬇ Télécharger
            </button>
          </div>
        </div>
      )}
    </div>
  );
}