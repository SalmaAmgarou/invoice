"""
Système de prompts spécialisés pour l'analyse de factures françaises
Intègre toutes les instructions spécifiques données par l'utilisateur
"""

from typing import Dict, List
from datetime import datetime


class FrenchInvoicePromptSystem:
    """Système de prompts adapté aux spécificités françaises et instructions utilisateur"""

    def __init__(self):
        self.base_instructions = self._get_base_french_instructions()

    def _get_base_french_instructions(self) -> str:
        """Instructions de base communes à tous les types de factures"""
        return """
INSTRUCTIONS IMPÉRATIVES POUR FACTURES FRANÇAISES:

1. ✅ PÉRIODE: Bien prendre en compte la période de la facture (mensuelle, trimestrielle, annuelle)
2. ✅ VERSIONS: Générer version anonyme ET non anonyme selon demande
3. ✅ CALCUL: Utiliser consommation kWh/an OU montant annuel selon disponibilité
4. ✅ SOURCES: Se référer aux prix RÉELS des sites fournisseurs (données fournies)
5. ✅ DONNÉES PARTIELLES: Calculer sur infos disponibles même si incomplètes
6. ✅ VICES CACHÉS: Minimum 3 pièges concrets et chiffrés
7. ✅ MÉTHODOLOGIE: Citer sources et méthodes utilisées
8. ✅ ÉCONOMIES: Mettre en rouge/évidence les économies réalisables
9. ✅ TABLEAUX ÉLECTRICITÉ: 2 tableaux (Base ET HP-HC) si applicable
10. ✅ CLASSEMENT: Top 5 fournisseurs du plus intéressant au moins intéressant
11. ✅ DIFFÉRENTIELS: Ligne par ligne (prix kWh actuel - nouveau) + (abonnement actuel - nouveau)

FORMAT DE CALCUL OBLIGATOIRE:
- Offre actuelle - Offre nouvelle (la meilleure)
- Une ligne différence prix kWh
- Une ligne différence prix abonnement
"""

    def get_energy_analysis_prompt(self, invoice_data: Dict, competitive_offers: List[Dict],
                                   anonymize: bool = False) -> str:
        """Prompt spécialisé pour l'analyse d'énergie selon vos instructions"""

        offers_context = self._format_competitive_offers(competitive_offers, 'energie')
        anonymization_instruction = "IMPORTANT: Anonymiser tous les noms de fournisseurs (utiliser 'Fournisseur A', 'Fournisseur B', etc.)" if anonymize else "Utiliser les vrais noms des fournisseurs."

        return f"""
{self.base_instructions}

Tu es un expert en factures d'énergie françaises. Analyse cette facture selon les INSTRUCTIONS IMPÉRATIVES ci-dessus.

{anonymization_instruction}

DONNÉES CONCURRENTIELLES RÉELLES (à utiliser obligatoirement):
{offers_context}

RÉPONSE JSON STRICTEMENT REQUISE:

{{
  "periode_facture": "mensuel|trimestriel|annuel - DÉTECTÉ AUTOMATIQUEMENT",
  "client_info": {{
    "nom": "{'' if anonymize else 'Nom réel du client'}",
    "adresse": "{'' if anonymize else 'Adresse complète'}",
    "reference_contrat": "Numéro contrat"
  }},

  "offre_actuelle_electricite": {{
    "fournisseur": "{'Fournisseur Actuel' if anonymize else 'Nom réel'}",
    "offre_nom": "Nom exact de l'offre",
    "puissance_souscrite": "X kVA",
    "consommation_annuelle_kwh": "Consommation/an (calculée si nécessaire selon période)",
    "montant_total_annuel": "Montant annuel TTC calculé",
    "prix_moyen_kwh": "Prix kWh moyen TTC",
    "option_tarifaire": "Base|HP-HC",
    "abonnement_annuel": "Abonnement annuel TTC"
  }},

  "comparatif_offres_base": [
    {{
      "fournisseur": "Nom fournisseur{'(anonymisé)' if anonymize else ''}",
      "nom_offre": "Nom exact offre",
      "prix_kwh": "X,XXXX €",
      "abonnement": "XXX,XX €/an",
      "total_annuel_client": "Total TTC calculé pour CONSOMMATION CLIENT",
      "differentiel_kwh": "Différence vs actuel: +/- X,XXXX €",
      "differentiel_abonnement": "Différence vs actuel: +/- XX,XX €",
      "avantages": "Avantages principaux"
    }}
  ],

  "comparatif_offres_hphc": [
    // OBLIGATOIRE si client en HP-HC ou si recommandé
    {{
      "fournisseur": "Nom fournisseur",
      "prix_kwh_hp": "X,XXXX €",
      "prix_kwh_hc": "X,XXXX €", 
      "abonnement": "XXX,XX €/an",
      "total_annuel_client": "Calculé avec répartition HP/HC client",
      "differentiel_total": "vs offre Base actuelle"
    }}
  ],

  "pieges_detectes_offre_actuelle": [
    "Piège 1: [CONCRET et CHIFFRÉ] Ex: Tarif HP-HC inadapté, surcoût de X€/an",
    "Piège 2: [CONCRET] Ex: Puissance souscrite excessive, économie possible Y€/an", 
    "Piège 3: [CONCRET] Ex: Option tarifaire non optimale",
    "Piège 4: [SI APPLICABLE]"
  ],

  "notre_recommandation": {{
    "fournisseur_recommande": "Meilleur fournisseur identifié",
    "economie_kwh": "Économie annuelle sur prix kWh: XX € (consommation × différentiel)",
    "economie_abonnement": "Économie annuelle abonnement: XX €",
    "economie_totale_annuelle": "TOTAL: XXX € TTC/an",
    "pourcentage_economie": "XX% d'économies",
    "calcul_detaille": "Offre actuelle (XXX €) - Offre recommandée (XXX €) = XXX € d'économie"
  }},

  "methodologie_fiabilite": {{
    "sources_donnees": "Facture client, tarifs officiels CRE, sites fournisseurs consultés le [date]",
    "methode_comparaison": "Calculs basés sur consommation annuelle réelle/estimée",
    "references_officielles": "TRV CRE, barèmes publics 2025",
    "independance": "Rapport indépendant, sans publicité ni affiliation"
  }}
}}

RÈGLES DE CALCUL OBLIGATOIRES:
1. Si période mensuelle → multiplier par 12 pour annuel
2. Si trimestrielle → multiplier par 4 pour annuel  
3. Si données partielles → extrapoler intelligemment avec mention
4. Différentiels ligne par ligne: (Actuel - Nouveau) pour chaque composant
5. Classement du PLUS économique au MOINS économique
6. Maximum 5 offres dans chaque tableau
7. Économies en VALEUR ABSOLUE et POURCENTAGE

ATTENTION SPÉCIALE:
- Si facture souscription/mise en service: mentionner "Analyse à compléter après première facture de consommation"
- Si consommation estimée: le préciser clairement
- Calculs HP-HC: utiliser répartition 60% HP / 40% HC si non spécifiée
"""

    def get_telecom_analysis_prompt(self, invoice_data: Dict, competitive_offers: List[Dict],
                                    anonymize: bool = False) -> str:
        """Prompt spécialisé pour les factures télécom/internet"""

        offers_context = self._format_competitive_offers(competitive_offers, 'telecom')
        anonymization_instruction = "ANONYMISER les opérateurs (Opérateur A, B, C...)" if anonymize else "Utiliser vrais noms opérateurs"

        return f"""
{self.base_instructions}

Tu es un expert en offres télécoms françaises. {anonymization_instruction}

OFFRES CONCURRENTIELLES ACTUELLES:
{offers_context}

RÉPONSE JSON REQUISE:

{{
  "type_facture": "internet|mobile|fixe",
  "periode_facture": "mensuel (standard télécom)",

  "offre_actuelle": {{
    "operateur": "{'Opérateur Actuel' if anonymize else 'Nom réel'}",
    "offre_nom": "Nom exact offre actuelle",
    "prix_mensuel": "XX,XX € TTC",
    "prix_annuel": "XXX,XX € TTC (×12)",
    "services_inclus": "Internet, TV, mobile, débit...",
    "engagement": "Durée engagement restante",
    "date_fin_promo": "Si prix promotionnel"
  }},

  "comparatif_offres": [
    {{
      "operateur": "Nom opérateur{'(anonymisé)' if anonymize else ''}",
      "offre": "Nom offre",
      "prix_mensuel": "XX,XX €",
      "prix_annuel": "XXX,XX €", 
      "engagement": "0|12|24 mois",
      "services_inclus": "Détail services",
      "economie_annuelle": "Économie vs actuel: XXX €/an",
      "avantages": "Points forts"
    }}
  ],

  "pieges_detectes": [
    "Engagement contractuel long (XX mois restants)",
    "Prix promotionnel temporaire (passage à XX€/mois après)",
    "Services payants non utilisés (estimation XX€/mois)",
    "Frais résiliation anticipée: XX€"
  ],

  "recommendation": {{
    "operateur_recommande": "Meilleur choix identifié", 
    "economie_annuelle": "XXX € TTC/an",
    "pourcentage_economie": "XX%",
    "action_immediate": "Négociation|Changement|Attente fin engagement",
    "timing_optimal": "Quand changer (fin engagement, etc.)"
  }},

  "calcul_economies": {{
    "actuel_annuel": "XXX €",
    "nouveau_annuel": "XXX €", 
    "difference": "XXX € d'économie",
    "sur_engagement": "Économie sur durée engagement: XXX €"
  }}
}}

SPÉCIFICITÉS TÉLÉCOM:
- Prix promotionnels: mentionner prix après promotion
- Engagement: calculer coût résiliation vs économies
- Services inclus: identifier non-utilisés
- Négociation: possibilités avec opérateur actuel
"""

    def get_insurance_analysis_prompt(self, invoice_data: Dict, competitive_offers: List[Dict],
                                      anonymize: bool = False) -> str:
        """Prompt pour les factures d'assurance"""

        return f"""
{self.base_instructions}

Tu es un expert en assurances françaises.

RÉPONSE JSON REQUISE:

{{
  "type_assurance": "auto|habitation|sante",
  "periode_facture": "annuel|mensuel",

  "contrat_actuel": {{
    "assureur": "{'Assureur Actuel' if anonymize else 'Nom réel'}",
    "type_contrat": "Type exact",
    "prime_annuelle": "XXX € TTC",
    "franchise": "XXX €",
    "garanties_principales": ["Garantie 1", "Garantie 2"],
    "date_echeance": "Date renouvellement"
  }},

  "alternatives": [
    {{
      "assureur": "Nom assureur",
      "prime_annuelle": "XXX €",
      "garanties": "Équivalentes/Supérieures/Inférieures",
      "franchise": "XXX €",
      "economie_annuelle": "XXX € vs actuel"
    }}
  ],

  "pieges_detectes": [
    "Surprimes injustifiées",
    "Garanties inutiles/redondantes", 
    "Franchise élevée",
    "Reconduction tacite défavorable"
  ],

  "recommendation": {{
    "assureur_recommande": "Meilleur choix",
    "economie_annuelle": "XXX €",
    "garanties": "Maintenues/Améliorées",
    "timing": "Date optimale pour changement"
  }}
}}
"""

    def get_subscription_prompt(self, invoice_data: Dict) -> str:
        """Prompt spécial pour factures de souscription/mise en service"""

        return f"""
{self.base_instructions}

FACTURE DE SOUSCRIPTION/MISE EN SERVICE DÉTECTÉE.

IMPORTANT: 
- Pas de calcul d'économies précis (pas d'historique consommation)
- Focus sur l'optimisation future
- Recommandations prospectives

RÉPONSE JSON REQUISE:

{{
  "type_facture": "souscription_energie|souscription_telecom",
  "statut": "nouveau_contrat",

  "contrat_souscrit": {{
    "fournisseur": "Fournisseur choisi",
    "offre_souscrite": "Nom offre",
    "caracteristiques": "Puissance, options, services",
    "montant_facture": "Montant de cette facture mise en service",
    "date_mise_en_service": "Date activation"
  }},

  "analyse_choix": {{
    "pertinence_offre": "Analyse du choix effectué",
    "alternatives_meilleures": [
      {{
        "fournisseur": "Alternative 1",
        "offre": "Nom offre", 
        "avantages": "Pourquoi meilleure",
        "economie_estimee": "XX-XXX €/an selon profil"
      }}
    ]
  }},

  "recommandations_immediates": [
    "Vérifier adéquation puissance/besoins réels",
    "Programmer réévaluation après 2-3 premières factures",
    "Surveiller consommation réelle vs estimations"
  ],

  "planification_optimisation": {{
    "delai_reevaluation": "2-3 mois après mise en service",
    "donnees_a_collecter": "Consommation réelle, habitudes usage",
    "economies_potentielles": "Fourchette XX-XXX €/an selon profil",
    "prochaine_action": "RDV analyse complète avec données réelles"
  }},

  "methode_future": "Analyse précise possible uniquement avec données de consommation réelles sur quelques mois"
}}

FOCUS: Préparation de l'analyse future plutôt que calculs imprécis immédiats.
"""

    def get_multi_service_prompt(self, invoice_data: Dict, competitive_offers: Dict) -> str:
        """Prompt pour factures multi-services (énergie + gaz, internet + mobile, etc.)"""

        return f"""
{self.base_instructions}

FACTURE MULTI-SERVICES DÉTECTÉE.

Analyser CHAQUE SERVICE SÉPARÉMENT puis synthèse globale.

RÉPONSE JSON REQUISE:

{{
  "type_facture": "multi_services",
  "services_detectes": ["service1", "service2"],

  "analyse_service_1": {{
    // Structure complète selon type de service
  }},

  "analyse_service_2": {{  
    // Structure complète selon type de service
  }},

  "synthese_globale": {{
    "economie_totale_possible": "Somme économies tous services",
    "fournisseur_unique_optimal": "Si regroupement avantageux",
    "vs_fournisseurs_separes": "Comparaison regroupé vs séparé",
    "strategie_recommandee": "Regrouper|Séparer services"
  }},

  "plan_action_integre": [
    "Action 1: Service prioritaire à changer",
    "Action 2: Timing optimal",
    "Action 3: Négociation groupée possible"
  ]
}}

ATTENTION: Calculer économies par service ET économies globales.
"""

    def _format_competitive_offers(self, offers: List[Dict], service_type: str) -> str:
        """Formate les offres concurrentielles pour inclusion dans le prompt"""

        if not offers:
            return "Aucune offre concurrentielle récupérée - utiliser données de référence."

        formatted = f"\n=== OFFRES CONCURRENTIELLES {service_type.upper()} (données réelles) ===\n"

        for i, offer in enumerate(offers[:5], 1):  # Top 5
            formatted += f"\n{i}. {offer.get('fournisseur', 'Inconnu')}:\n"

            if service_type == 'energie':
                formatted += f"   - Offre: {offer.get('offre_nom', 'N/A')}\n"
                formatted += f"   - Prix kWh: {offer.get('prix_kwh', 'N/A')} €\n"
                formatted += f"   - Abonnement: {offer.get('abonnement_annuel', 'N/A')} €/an\n"

                if offer.get('prix_kwh_hp'):  # Tarif HP-HC disponible
                    formatted += f"   - Prix kWh HP: {offer.get('prix_kwh_hp')} €\n"
                    formatted += f"   - Prix kWh HC: {offer.get('prix_kwh_hc')} €\n"
                    formatted += f"   - Abonnement HP-HC: {offer.get('abonnement_annuel_hphc')} €/an\n"

            elif service_type == 'telecom':
                formatted += f"   - Offre: {offer.get('offre_nom', 'N/A')}\n"
                formatted += f"   - Prix mensuel: {offer.get('prix_mensuel', 'N/A')} €\n"
                formatted += f"   - Prix annuel: {offer.get('prix_annuel', 'N/A')} €\n"
                formatted += f"   - Engagement: {offer.get('engagement', 'N/A')}\n"

            formatted += f"   - Avantages: {offer.get('avantages', 'N/A')}\n"
            formatted += f"   - Source: {offer.get('source', 'N/A')}\n"

            if offer.get('derniere_maj'):
                formatted += f"   - Dernière MAJ: {offer.get('derniere_maj')}\n"

        formatted += "\n=== FIN OFFRES CONCURRENTIELLES ===\n"
        formatted += "UTILISER OBLIGATOIREMENT ces données dans les calculs et recommandations.\n"

        return formatted

    def get_prompt_for_invoice_type(self, invoice_classification: Dict, invoice_data: Dict,
                                    competitive_offers: List[Dict], anonymize: bool = False) -> str:
        """Sélecteur de prompt selon le type de facture détecté"""

        invoice_type = invoice_classification.get('type', 'inconnu')
        special_case = invoice_classification.get('special_case')

        if special_case == 'souscription':
            return self.get_subscription_prompt(invoice_data)

        elif invoice_type == 'energie':
            return self.get_energy_analysis_prompt(invoice_data, competitive_offers, anonymize)

        elif invoice_type == 'telecom':
            return self.get_telecom_analysis_prompt(invoice_data, competitive_offers, anonymize)

        elif invoice_type == 'assurance':
            return self.get_insurance_analysis_prompt(invoice_data, competitive_offers, anonymize)

        else:
            # Fallback pour types non supportés
            return self._get_generic_fallback_prompt(invoice_data, anonymize)

    def _get_generic_fallback_prompt(self, invoice_data: Dict, anonymize: bool) -> str:
        """Prompt générique pour types de factures non supportés"""

        return f"""
{self.base_instructions}

TYPE DE FACTURE NON STANDARD DÉTECTÉ.

Analyser selon les principes généraux:

RÉPONSE JSON REQUISE:

{{
  "type_facture": "autre|non_identifie",
  "analyse_possible": "limitee|impossible",

  "informations_extraites": {{
    "fournisseur": "{'Fournisseur' if anonymize else 'Nom réel'}",
    "service": "Type de service détecté",
    "montant": "Montant identifié",
    "periode": "Période identifiée"
  }},

  "recommandations_generales": [
    "Analyse manuelle recommandée",
    "Vérification avec service client fournisseur",
    "Recherche comparative spécialisée nécessaire"
  ],

  "action_suggered": "Analyse personnalisée requise pour ce type de facture"
}}

LIMITATION: Analyse automatique non optimale pour ce type de document.
"""


class PromptValidator:
    """Validateur pour s'assurer que les prompts respectent les instructions"""

    @staticmethod
    def validate_prompt_compliance(prompt: str) -> Dict[str, bool]:
        """Vérifie que le prompt respecte toutes les instructions obligatoires"""

        validations = {
            'periode_mentioned': 'période' in prompt.lower(),
            'anonymization_handled': 'anonyme' in prompt.lower() or 'anonymiser' in prompt.lower(),
            'calculation_method': 'consommation' in prompt.lower() and 'montant' in prompt.lower(),
            'sources_required': 'source' in prompt.lower() and 'site' in prompt.lower(),
            'vices_caches': 'piège' in prompt.lower() or 'vice' in prompt.lower(),
            'methodology': 'méthodologie' in prompt.lower(),
            'economies_highlight': 'économie' in prompt.lower(),
            'differentiel_calculation': 'différence' in prompt.lower() or 'différentiel' in prompt.lower(),
            'ranking_required': 'classe' in prompt.lower() or 'top' in prompt.lower()
        }

        return validations

    @staticmethod
    def get_missing_instructions(validations: Dict[str, bool]) -> List[str]:
        """Retourne la liste des instructions manquantes"""

        missing = []
        instruction_names = {
            'periode_mentioned': 'Prise en compte période facture',
            'anonymization_handled': 'Gestion anonymisation',
            'calculation_method': 'Méthode de calcul (kWh/montant)',
            'sources_required': 'Référence aux sources réelles',
            'vices_caches': 'Détection vices cachés',
            'methodology': 'Méthodologie et sources',
            'economies_highlight': 'Mise en évidence économies',
            'differentiel_calculation': 'Calcul différentiel ligne par ligne',
            'ranking_required': 'Classement des offres'
        }

        for key, passed in validations.items():
            if not passed:
                missing.append(instruction_names[key])

        return missing