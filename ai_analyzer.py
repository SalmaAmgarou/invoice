import re
import json
import logging
from typing import Dict, Optional, Tuple, List, Any
from openai import OpenAI
from config import Config
from web_search_service import CompetitiveOffersSearchService
from integration_donnees_reelles import RealDataProvider

logger = logging.getLogger(__name__)


class EnhancedInvoiceAnalyzer:
    def __init__(self):
        if not Config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY n'est pas configuré")

        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.web_search = CompetitiveOffersSearchService()
        self.data_provider = RealDataProvider()

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

    def analyze_invoice(self, extracted_text: str) -> Dict[str, Any]:
        """Analyse complète avec détection intelligente et recherche web"""
        try:
            # 1. DÉTECTION AVANCÉE DU TYPE
            invoice_type, confidence = self._advanced_type_detection(extracted_text)
            logger.info(f"🎯 Type détecté: {invoice_type} (confiance: {confidence}%)")

            # 2. EXTRACTION STRUCTURÉE PAR TYPE
            structured_data = self._extract_structured_data(extracted_text, invoice_type)

            # 3. RECHERCHE WEB DES OFFRES CONCURRENTES
            competitive_offers = self._search_competitive_offers(invoice_type, structured_data)

            # 4. ANALYSE DES PIÈGES ET OPTIMISATIONS
            issues = self._detect_issues(structured_data, invoice_type)

            # 5. CALCUL DES ÉCONOMIES
            best_savings = self._calculate_best_savings(structured_data, competitive_offers)

            # 6. COMPILATION DU RÉSULTAT FINAL
            result = {
                'type_facture': invoice_type,
                'confidence': confidence,
                'client_info': structured_data.get('client_info', {}),
                'current_offer': structured_data.get('current_offer', {}),
                'alternatives': competitive_offers[:5],  # Top 5
                'detected_issues': issues,
                'best_savings': best_savings,
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

    def _extract_structured_data(self, text: str, invoice_type: str) -> Dict:
        """Extraction structurée adaptée au type de facture"""

        # Prompt spécialisé selon le type
        prompt = self._get_specialized_extraction_prompt(invoice_type)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Texte de la facture:\n{text}"}
                ],
                max_tokens=1500,
                temperature=0.1
            )

            result = response.choices[0].message.content

            # Parser le JSON
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())

        except Exception as e:
            logger.error(f"Erreur extraction: {e}")

        return self._get_fallback_structure(invoice_type)

    def _get_specialized_extraction_prompt(self, invoice_type: str) -> str:
        """Retourne le prompt spécialisé selon le type"""

        if invoice_type == 'internet_mobile':
            return """Tu es expert en factures télécoms françaises. Extrais PRÉCISÉMENT:

{
  "client_info": {
    "nom": "Nom complet",
    "adresse": "Adresse complète",
    "numero_client": "N° client",
    "reference_pto": "Référence fibre si présente"
  },
  "current_offer": {
    "fournisseur": "Orange|SFR|Free|Bouygues",
    "offre_nom": "Nom exact de l'offre (ex: Open Max 200 Go)",
    "prix_mensuel": "Prix mensuel TTC en euros",
    "montant_total_annuel": "Montant annuel calculé",
    "services_inclus": {
      "internet": "Type et débit",
      "mobile": "Forfait data",
      "tv": "Oui/Non et détails",
      "telephone_fixe": "Oui/Non"
    },
    "engagement": "Date fin engagement"
  },
  "consommation": {
    "data_mobile": "Go consommés",
    "appels": "Durée/nombre",
    "sms": "Nombre"
  },
  "facturation": {
    "periode": "Période facturée",
    "montant_ttc": "Montant de cette facture"
  }
}"""

        elif invoice_type == 'electricite':
            return """Tu es expert en factures d'électricité françaises. Extrais PRÉCISÉMENT:

{
  "client_info": {
    "nom": "Nom complet",
    "adresse": "Adresse",
    "numero_pdl": "Point de livraison",
    "numero_contrat": "N° contrat"
  },
  "current_offer": {
    "fournisseur": "Nom du fournisseur",
    "offre_nom": "Nom de l'offre",
    "puissance_souscrite": "kVA",
    "option_tarifaire": "Base/HP-HC",
    "consommation_annuelle": "kWh/an",
    "montant_total_annuel": "€ TTC/an",
    "prix_kwh": "€/kWh TTC",
    "abonnement_annuel": "€ TTC/an"
  },
  "consommation": {
    "periode": "Dates",
    "kwh_consommes": "Total kWh",
    "index_releve": "Index compteur"
  }
}"""

        elif invoice_type == 'gaz':
            return """Tu es expert en factures de gaz françaises. Extrais:

{
  "client_info": {
    "nom": "Nom",
    "adresse": "Adresse",
    "numero_pce": "Point comptage",
    "numero_contrat": "Contrat"
  },
  "current_offer": {
    "fournisseur": "Fournisseur",
    "offre_nom": "Offre",
    "classe_consommation": "B0/B1/B2I",
    "consommation_annuelle": "kWh/an",
    "montant_total_annuel": "€ TTC/an",
    "prix_kwh": "€/kWh TTC",
    "abonnement_annuel": "€ TTC/an"
  }
}"""

        # Autres types...
        return self._get_generic_extraction_prompt()

    def _search_competitive_offers(self, invoice_type: str, structured_data: Dict) -> List[Dict]:
        """Recherche les offres concurrentes via web search et données réelles"""

        competitive_offers = []

        # 1. Données réelles du provider
        if invoice_type == 'electricite':
            consumption = self._extract_consumption_value(
                structured_data.get('current_offer', {}).get('consommation_annuelle', '5000')
            )
            real_offers = self.data_provider.get_real_electricity_offers(consumption)
            competitive_offers.extend(real_offers)

        elif invoice_type == 'gaz':
            consumption = self._extract_consumption_value(
                structured_data.get('current_offer', {}).get('consommation_annuelle', '10000')
            )
            real_offers = self.data_provider.get_real_gas_offers(consumption)
            competitive_offers.extend(real_offers)

        elif invoice_type in ['internet', 'mobile', 'internet_mobile']:
            current_price = self._extract_price_value(
                structured_data.get('current_offer', {}).get('prix_mensuel', '50')
            )
            real_offers = self.data_provider.get_real_internet_offers(current_price)
            competitive_offers.extend(real_offers)

        # 2. Web search pour offres supplémentaires
        if invoice_type in ['electricite', 'gaz']:
            search_type = 'energie'
        elif invoice_type in ['internet', 'mobile', 'internet_mobile']:
            search_type = 'telecom'
        else:
            search_type = invoice_type

        web_offers = self.web_search.search_competitive_offers(
            search_type,
            structured_data.get('current_offer', {}),
            structured_data.get('consommation', {})
        )

        # 3. Fusion et déduplication
        all_offers = self._merge_and_deduplicate_offers(competitive_offers + web_offers)

        # 4. Classement par économies potentielles
        return self._rank_offers_by_savings(all_offers, structured_data)

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
                    kva = float(re.search(r'(\d+)', puissance).group(1))
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
            if engagement and '2026' in engagement:
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

    def _calculate_best_savings(self, structured_data: Dict, competitive_offers: List[Dict]) -> Dict:
        """Calcule les économies selon les instructions utilisateur"""

        current_offer = structured_data.get('current_offer', {})
        best_saving = {
            'fournisseur_recommande': '',
            'economie_annuelle': 0,
            'pourcentage_economie': 0,
            'action_recommandee': ''
        }

        # Extraire le coût actuel
        current_cost = self._extract_annual_cost(current_offer)

        if not current_cost or not competitive_offers:
            return {
                'fournisseur_recommande': 'Analyse approfondie recommandée',
                'economie_annuelle': 'À déterminer',
                'pourcentage_economie': 'Variable',
                'action_recommandee': 'Comparer les offres détaillées'
            }

        # Calculer économies pour chaque offre
        max_saving = 0
        best_offer = None

        for offer in competitive_offers:
            offer_cost = self._extract_annual_cost(offer)
            if offer_cost and offer_cost < current_cost:
                saving = current_cost - offer_cost
                if saving > max_saving:
                    max_saving = saving
                    best_offer = offer

        if best_offer:
            percentage = (max_saving / current_cost) * 100
            best_saving = {
                'fournisseur_recommande': best_offer.get('fournisseur', ''),
                'economie_annuelle': f"{max_saving:.2f}€",
                'pourcentage_economie': f"{percentage:.1f}%",
                'action_recommandee': f"Changer pour {best_offer.get('fournisseur', '')} - {best_offer.get('offre', '')}"
            }

        return best_saving

    def _extract_consumption_value(self, text: str) -> int:
        """Extrait une valeur de consommation"""
        try:
            match = re.search(r'(\d+)', str(text).replace(' ', ''))
            return int(match.group(1)) if match else 5000
        except:
            return 5000

    def _extract_price_value(self, text: str) -> float:
        """Extrait une valeur de prix"""
        try:
            cleaned = re.sub(r'[^\d,.]', '', str(text))
            cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except:
            return 0.0

    def _extract_annual_cost(self, offer: Dict) -> float:
        """Extrait ou calcule le coût annuel"""
        # Essayer le total annuel direct
        total = offer.get('montant_total_annuel') or offer.get('total_annuel', '')
        if total:
            cost = self._extract_price_value(total)
            if cost > 0:
                return cost

        # Calculer depuis mensuel
        monthly = offer.get('prix_mensuel', '')
        if monthly:
            monthly_cost = self._extract_price_value(monthly)
            if monthly_cost > 0:
                return monthly_cost * 12

        # Calculer depuis kWh + abonnement
        prix_kwh = self._extract_price_value(offer.get('prix_kwh', '0'))
        abonnement = self._extract_price_value(offer.get('abonnement_annuel', '0'))
        consommation = self._extract_consumption_value(offer.get('consommation_annuelle', '0'))

        if prix_kwh > 0 and consommation > 0:
            return (prix_kwh * consommation) + abonnement

        return 0

    def _merge_and_deduplicate_offers(self, offers: List[Dict]) -> List[Dict]:
        """Fusionne et déduplique les offres"""
        unique_offers = {}

        for offer in offers:
            key = f"{offer.get('fournisseur', '')}-{offer.get('offre', '')}"
            if key not in unique_offers:
                unique_offers[key] = offer

        return list(unique_offers.values())

    def _rank_offers_by_savings(self, offers: List[Dict], structured_data: Dict) -> List[Dict]:
        """Classe les offres par économies potentielles"""
        current_cost = self._extract_annual_cost(structured_data.get('current_offer', {}))

        for offer in offers:
            offer_cost = self._extract_annual_cost(offer)
            if current_cost and offer_cost:
                offer['savings_potential'] = current_cost - offer_cost
            else:
                offer['savings_potential'] = 0

        # Trier par économies décroissantes
        offers.sort(key=lambda x: x.get('savings_potential', 0), reverse=True)

        return offers

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