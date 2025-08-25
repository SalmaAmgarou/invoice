import re
import json
import logging
from typing import Dict, Optional, Tuple, List, Any
from openai import OpenAI
from config import Config

logger = logging.getLogger(__name__)


class EnhancedInvoiceAnalyzer:
    def __init__(self):
        if not Config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY n'est pas configuré")

        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)

        # Mapping détaillé des types de factures
        self.invoice_patterns = {
            'electricite': {
                'keywords': ['kwh', 'électricité', 'edf', 'engie', 'totalenergies', 'ohm',
                             'ekwateur', 'vattenfall', 'tarif bleu', 'heures creuses',
                             'heures pleines', 'consommation électrique', 'compteur électrique'],
                'negative': ['gaz naturel', 'mobile', 'internet', 'fibre'],
                'providers': ['EDF', 'Engie', 'TotalEnergies', 'OHM', 'ekWateur', 'Vattenfall',
                              'Planète OUI', 'Mint Énergie', 'Alpiq', 'Iberdrola']
            },
            'gaz': {
                'keywords': ['gaz naturel', 'm3', 'mètres cubes', 'thermes', 'pcs',
                             'consommation gaz', 'chaudière', 'chauffage gaz'],
                'negative': ['électricité', 'kwh électrique'],
                'providers': ['Engie', 'TotalEnergies', 'ENI', 'ekWateur', 'Vattenfall']
            },
            'internet': {
                'keywords': ['internet', 'fibre', 'adsl', 'livebox', 'freebox', 'bbox',
                             'sfr box', 'débit', 'mbps', 'wifi', 'routeur', 'modem',
                             'ligne fixe', 'téléphone illimité'],
                'negative': ['consommation kwh', 'compteur'],
                'providers': ['Orange', 'Free', 'SFR', 'Bouygues', 'RED', 'Sosh']
            },
            'mobile': {
                'keywords': ['mobile', 'forfait', 'go', 'données mobiles', '4g', '5g',
                             'sms', 'mms', 'roaming', 'carte sim', 'smartphone'],
                'negative': ['fibre', 'box internet'],
                'providers': ['Orange', 'Free', 'SFR', 'Bouygues', 'RED', 'Sosh', 'B&You']
            },
            'internet_mobile': {
                'keywords': ['open', 'pack', 'offre groupée', 'convergente', 'quadruple play',
                             'internet + mobile', 'fibre + mobile', 'box + mobile'],
                'negative': [],
                'providers': ['Orange', 'Free', 'SFR', 'Bouygues']
            },
            'assurance_auto': {
                'keywords': ['assurance auto', 'véhicule', 'sinistre', 'franchise',
                             'responsabilité civile', 'tous risques', 'tiers', 'bonus malus',
                             'immatriculation', 'carte verte'],
                'negative': ['habitation', 'santé'],
                'providers': ['AXA', 'Allianz', 'MAIF', 'MACIF', 'Matmut', 'MMA', 'Direct Assurance']
            },
            'assurance_habitation': {
                'keywords': ['assurance habitation', 'multirisque habitation', 'mrh',
                             'logement', 'incendie', 'dégât des eaux', 'vol', 'responsabilité locative'],
                'negative': ['véhicule', 'auto'],
                'providers': ['AXA', 'Allianz', 'MAIF', 'MACIF', 'Matmut', 'MMA']
            }
        }

    def _get_generic_extraction_prompt(self) -> str:
        """
        Retourne un prompt générique pour l'extraction de données de base
        quand le type de facture est inconnu.
        """
        logger.info("Utilisation du prompt d'extraction générique pour un type de facture inconnu.")
        return """
        Tu es un assistant intelligent d'extraction de données. Le type de document suivant est inconnu.
        Analyse le texte et extrais les informations les plus pertinentes que tu peux trouver, comme :
        - Le nom du fournisseur
        - Le montant total
        - La date du document
        - Un numéro de client ou de contrat

        Retourne ces informations dans un format JSON simple. Si une information n'est pas trouvée, indique "non trouvé".
        """

    def analyze_invoice(self, extracted_text: str, db_offers: List[Dict] = None) -> Dict[str, Any]:
        """Analyse complète avec détection intelligente et comparaison via offres DB"""
        try:
            # 1. DÉTECTION AVANCÉE DU TYPE
            invoice_type, confidence = self._advanced_type_detection(extracted_text)
            logger.info(f"🎯 Type détecté: {invoice_type} (confiance: {confidence}%)")

            # 2. EXTRACTION STRUCTURÉE PAR TYPE avec offres DB (RAG-style)
            structured_data = self._extract_structured_data_with_offers(extracted_text, invoice_type, db_offers)

            # 3. ANALYSE DES PIÈGES ET OPTIMISATIONS
            issues = self._detect_issues(structured_data, invoice_type)

            # 4. COMPILATION DU RÉSULTAT FINAL
            result = {
                'type_facture': invoice_type,
                'confidence': confidence,
                'client_info': structured_data.get('client_info', {}),
                'current_offer': structured_data.get('current_offer', {}),
                'alternatives': structured_data.get('alternatives', []),
                'detected_issues': issues,
                'best_savings': structured_data.get('best_savings', {}),
                'methodology': self._get_methodology(invoice_type),
                'structured_data': structured_data
            }

            return {
                'structured_data': result,
                'raw_response': json.dumps(result, ensure_ascii=False, indent=2)
            }

        except Exception as e:
            logger.error(f"Erreur analyse: {str(e)}")
            raise

    def _advanced_type_detection(self, text: str) -> Tuple[str, int]:
        """Détection avancée du type de facture avec score de confiance"""
        text_lower = text.lower()
        scores = {}

        for invoice_type, patterns in self.invoice_patterns.items():
            score = 0

            # Points positifs pour mots-clés trouvés
            for keyword in patterns['keywords']:
                if keyword in text_lower:
                    score += 10

            # Points bonus pour fournisseurs identifiés
            for provider in patterns['providers']:
                if provider.lower() in text_lower:
                    score += 20

            # Points négatifs pour exclusions
            for negative in patterns['negative']:
                if negative in text_lower:
                    score -= 15

            scores[invoice_type] = max(0, score)

        # Détection spéciale pour factures combinées
        if scores.get('internet', 0) > 30 and scores.get('mobile', 0) > 30:
            return 'internet_mobile', 95

        # Retourner le type avec le score le plus élevé
        if scores:
            best_type = max(scores, key=scores.get)
            confidence = min(100, scores[best_type])

            # Si confiance trop faible, utiliser l'analyse GPT
            if confidence < 40:
                return self._gpt_type_detection(text)

            return best_type, confidence

        return 'inconnu', 0

    def _gpt_type_detection(self, text: str) -> Tuple[str, int]:
        """Détection par GPT en cas d'incertitude"""
        prompt = """Analyse ce texte de facture et détermine son type EXACT.

Types possibles (CHOISIR UN SEUL):
- electricite
- gaz
- internet
- mobile
- internet_mobile
- assurance_auto
- assurance_habitation
- autre

Réponds UNIQUEMENT avec le type, rien d'autre."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text[:1000]}
                ],
                max_tokens=10,
                temperature=0
            )

            detected_type = response.choices[0].message.content.strip().lower()

            if detected_type in self.invoice_patterns:
                return detected_type, 80

        except Exception as e:
            logger.error(f"Erreur GPT detection: {e}")

        return 'inconnu', 0

    def _extract_structured_data_with_offers(self, text: str, invoice_type: str, db_offers: List[Dict] = None) -> Dict:
        """Extraction structurée avec offres DB pour comparaison (RAG-style)"""
        
        # Construire le prompt avec les offres DB si disponibles
        offers_context = ""
        if db_offers:
            offers_context = f"\n\nOffres disponibles pour comparaison:\n{json.dumps(db_offers, ensure_ascii=False, indent=2)}"
        
        # Prompt spécialisé selon le type avec schéma JSON strict
        prompt = self._get_specialized_extraction_prompt_with_schema(invoice_type, offers_context)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Texte de la facture:\n{text}"}
                ],
                max_tokens=2000,
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            try:
                result = json.loads(content)
                
                # Fallback: si pas assez d'alternatives, utiliser toutes les offres DB
                if db_offers and len(result.get('alternatives', [])) < len(db_offers):
                    logger.info(f"LLM n'a généré que {len(result.get('alternatives', []))} alternatives, utilisation de toutes les {len(db_offers)} offres DB")
                    result['alternatives'] = db_offers
                
                return result
            except Exception as e:
                logger.error(f"Erreur parsing JSON: {e}")
                # Dernier recours: tenter d'extraire un objet JSON si présent
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    # Fallback: utiliser toutes les offres DB
                    if db_offers:
                        result['alternatives'] = db_offers
                    return result
        except Exception as e:
            logger.error(f"Erreur extraction: {e}")

        # Fallback final: utiliser toutes les offres DB
        if db_offers:
            logger.info("Utilisation du fallback avec toutes les offres DB")
            return {
                'type_facture': invoice_type,
                'client_info': {'nom': 'À extraire'},
                'current_offer': {'fournisseur': 'À identifier'},
                'alternatives': db_offers,
                'best_savings': {'economie_annuelle': 'À calculer'}
            }

        return self._get_fallback_structure(invoice_type)

    def _get_specialized_extraction_prompt_with_schema(self, invoice_type: str, offers_context: str) -> str:
        """Retourne le prompt spécialisé avec schéma JSON strict selon le type"""

        if invoice_type == 'electricite':
            return f"""Tu es expert en factures d'électricité françaises. Extrais PRÉCISÉMENT selon ce schéma JSON strict:

{{
  "client_info": {{
    "nom": "Nom complet du client",
    "adresse": "Adresse complète",
    "numero_pdl": "Point de livraison si présent",
    "numero_contrat": "N° contrat si présent"
  }},
  "current_offer": {{
    "fournisseur": "Nom exact du fournisseur",
    "offre_nom": "Nom exact de l'offre",
    "puissance_souscrite": "Puissance en kVA (ex: 6)",
    "option_tarifaire": "Base ou HP/HC",
    "consommation_annuelle": "Consommation annuelle en kWh",
    "montant_total_annuel": "Montant total annuel TTC en euros",
    "prix_kwh": "Prix du kWh TTC en euros",
    "abonnement_annuel": "Abonnement annuel TTC en euros",
    "details": {{
      "prix_hp": "Prix kWh heures pleines si HP/HC",
      "prix_hc": "Prix kWh heures creuses si HP/HC",
      "repartition_hp_hc": "Répartition HP/HC si applicable"
    }}
  }},
  "consommation": {{
    "periode": "Période de facturation",
    "kwh_consommes": "Total kWh consommés",
    "index_releve": "Index compteur si présent"
  }},
  "alternatives": [
    {{
      "fournisseur": "Nom du fournisseur",
      "offre": "Nom de l'offre",
      "prix_kwh": "Prix kWh TTC",
      "abonnement_annuel": "Abonnement annuel TTC",
      "total_annuel": "Total annuel calculé TTC",
      "type_offre": "base ou hphc"
    }}
  ],
  "best_savings": {{
    "fournisseur_recommande": "Nom du fournisseur recommandé",
    "economie_annuelle": "Économie annuelle en euros",
    "pourcentage_economie": "Pourcentage d'économie"
  }}
}}

IMPORTANT: Utilise TOUTES les offres disponibles pour remplir 'alternatives'. Ne limite pas le nombre d'alternatives. Chaque offre doit avoir un 'type_offre' correct ('base' ou 'hphc').{offers_context}"""

        elif invoice_type == 'gaz':
            return f"""Tu es expert en factures de gaz françaises. Extrais selon ce schéma JSON strict:

{{
  "client_info": {{
    "nom": "Nom complet du client",
    "adresse": "Adresse complète",
    "numero_pce": "Point comptage et émission si présent",
    "numero_contrat": "N° contrat si présent"
  }},
  "current_offer": {{
    "fournisseur": "Nom exact du fournisseur",
    "offre_nom": "Nom exact de l'offre",
    "classe_consommation": "Classe B0/B1/B2I si présente",
    "consommation_annuelle": "Consommation annuelle en kWh",
    "montant_total_annuel": "Montant total annuel TTC en euros",
    "prix_kwh": "Prix du kWh TTC en euros",
    "abonnement_annuel": "Abonnement annuel TTC en euros"
  }},
  "consommation": {{
    "periode": "Période de facturation",
    "kwh_consommes": "Total kWh consommés",
    "m3_consommes": "Total m³ consommés si présent"
  }},
  "alternatives": [
    {{
      "fournisseur": "Nom du fournisseur",
      "offre": "Nom de l'offre",
      "prix_kwh": "Prix kWh TTC",
      "abonnement": "Abonnement annuel TTC",
      "total_annuel": "Total annuel calculé TTC"
    }}
  ],
  "best_savings": {{
    "fournisseur_recommande": "Nom du fournisseur recommandé",
    "economie_annuelle": "Économie annuelle en euros",
    "pourcentage_economie": "Pourcentage d'économie"
  }}
}}

Utilise les offres disponibles pour remplir 'alternatives' et calculer 'best_savings'.{offers_context}"""

        elif invoice_type == 'internet_mobile':
            return f"""Tu es expert en factures télécoms françaises. Extrais selon ce schéma JSON strict:

{{
  "client_info": {{
    "nom": "Nom complet du client",
    "adresse": "Adresse complète",
    "numero_client": "N° client si présent",
    "reference_pto": "Référence fibre si présente"
  }},
  "current_offer": {{
    "fournisseur": "Orange|SFR|Free|Bouygues",
    "offre_nom": "Nom exact de l'offre",
    "prix_mensuel": "Prix mensuel TTC en euros",
    "montant_total_annuel": "Montant annuel calculé",
    "services_inclus": {{
      "internet": "Type et débit",
      "mobile": "Forfait data",
      "tv": "Oui/Non et détails",
      "telephone_fixe": "Oui/Non"
    }},
    "engagement": "Date fin engagement si présente"
  }},
  "consommation": {{
    "data_mobile": "Go consommés si applicable",
    "appels": "Durée/nombre si applicable",
    "sms": "Nombre si applicable"
  }},
  "alternatives": [
    {{
      "fournisseur": "Nom du fournisseur",
      "offre": "Nom de l'offre",
      "prix_mensuel": "Prix mensuel TTC",
      "total_annuel": "Total annuel calculé TTC",
      "avantages": "Avantages de l'offre"
    }}
  ],
  "best_savings": {{
    "fournisseur_recommande": "Nom du fournisseur recommandé",
    "economie_annuelle": "Économie annuelle en euros"
  }}
}}

Utilise les offres disponibles pour remplir 'alternatives' et calculer 'best_savings'.{offers_context}"""

        # Autres types...
        return self._get_generic_extraction_prompt()

    def _detect_issues(self, structured_data: Dict, invoice_type: str) -> List[str]:
        """Détecte les pièges et problèmes selon les instructions utilisateur"""

        issues = []
        current_offer = structured_data.get('current_offer', {})

        # Instructions de l'utilisateur pour détecter les pièges
        if invoice_type == 'electricite':
            # Vérifier la puissance souscrite
            puissance = current_offer.get('puissance_souscrite', '')
            if puissance:
                try:
                    kva = float(re.search(r'(\d+)', str(puissance)).group(1))
                    if kva > 6:
                        issues.append(f"Puissance souscrite élevée ({kva} kVA) - vérifier si nécessaire")
                except:
                    pass

            # Vérifier option tarifaire
            if 'HP-HC' in str(current_offer.get('option_tarifaire', '')):
                issues.append("Option Heures Pleines/Creuses - rentable seulement si >30% consommation en HC")

            # Prix élevé
            prix_kwh = self._extract_price_value(current_offer.get('prix_kwh', '0'))
            if prix_kwh > 0.25:
                issues.append(f"Prix du kWh élevé ({prix_kwh}€) - potentiel d'économies important")

        elif invoice_type in ['internet', 'internet_mobile']:
            # Engagement
            engagement = current_offer.get('engagement', '')
            if engagement and '2026' in str(engagement):
                issues.append("Engagement longue durée limitant la flexibilité")

            # Services non utilisés
            services = current_offer.get('services_inclus', {})
            if services.get('tv') and 'premium' in str(services.get('tv', '')).lower():
                issues.append("Services TV premium inclus - vérifier l'utilisation réelle")

            # Prix après promotion
            prix = current_offer.get('prix_mensuel', '')
            if 'promo' in str(prix).lower() or 'première année' in str(prix).lower():
                issues.append("Tarif promotionnel temporaire - prévoir augmentation")

        # Limite à 4 issues comme demandé
        return issues[:4]

    def _extract_price_value(self, text: str) -> float:
        """Extrait une valeur de prix"""
        try:
            cleaned = re.sub(r'[^\d,.]', '', str(text))
            cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except:
            return 0.0

    def _get_methodology(self, invoice_type: str) -> str:
        """Retourne la méthodologie adaptée"""
        methodologies = {
            'electricite': "Comparaison basée sur les tarifs réglementés CRE et offres de marché janvier 2025",
            'gaz': "Analyse selon les tarifs de référence gaz et offres concurrentes 2025",
            'internet_mobile': "Comparaison des offres convergentes triple/quadruple play du marché français",
            'assurance_auto': "Analyse basée sur les tarifs moyens du marché assurance auto 2025"
        }
        return methodologies.get(invoice_type, "Analyse comparative du marché français actuel")

    def _get_fallback_structure(self, invoice_type: str) -> Dict:
        """Structure de fallback en cas d'erreur"""
        return {
            'type_facture': invoice_type,
            'client_info': {'nom': 'À extraire'},
            'current_offer': {'fournisseur': 'À identifier'},
            'alternatives': [],
            'detected_issues': ['Analyse manuelle requise'],
            'best_savings': {'economie_annuelle': 'À calculer'}
        }

    def calculate_savings(self, structured_data: Dict) -> Optional[float]:
        """Calcul des économies pour compatibilité"""
        best_savings = structured_data.get('best_savings', {})
        economie = best_savings.get('economie_annuelle', '')

        if economie and isinstance(economie, str):
            try:
                return float(re.search(r'(\d+[.]?\d*)', economie).group(1))
            except:
                pass

        return None