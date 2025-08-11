import re
import json
import logging
from typing import Dict, Optional, Tuple, List
from openai import OpenAI
from config import Config

logger = logging.getLogger(__name__)


class InvoiceAnalyzer:
    def __init__(self):
        if not Config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY n'est pas configuré")

        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.system_prompt = self._get_enhanced_system_prompt()

    def analyze_invoice(self, extracted_text: str) -> Dict[str, str]:
        """
        Analyze invoice text using OpenAI and return structured analysis
        """
        try:
            user_message = f"TEXTE EXTRAIT DE LA FACTURE:\n{extracted_text}\n\nANALYSE DEMANDÉE:"

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=1500,  # Augmenté pour plus de détails
                temperature=0.1,  # Plus précis
                timeout=90.0
            )

            ai_result = response.choices[0].message.content

            if not ai_result:
                raise Exception("Aucune réponse générée par OpenAI")

            # Parse the response
            parsed_data = self._parse_enhanced_response(ai_result)

            return {
                'structured_data': parsed_data,
                'raw_response': ai_result
            }

        except Exception as e:
            logger.error(f"Erreur lors de l'analyse OpenAI: {str(e)}")
            raise Exception(f"Erreur lors de l'analyse IA: {str(e)}")

    def _parse_enhanced_response(self, ai_result: str) -> Dict:
        """Parse AI response into structured data for professional report"""

        # Try to extract JSON if provided
        json_match = re.search(r'\{.*\}', ai_result, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Fallback: parse text format
        return self._parse_text_format(ai_result)

    def _parse_text_format(self, text: str) -> Dict:
        """Parse text format response into structured data"""
        data = {
            "client_info": {},
            "contract_info": {},
            "current_offer": {},
            "alternatives": [],
            "detected_issues": [],
            "recommendation": "",
            "savings_estimation": "",
            "methodology": ""
        }

        lines = text.split('\n')
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect sections
            if 'CLIENT:' in line.upper() or 'INFORMATIONS CLIENT' in line.upper():
                current_section = 'client_info'
            elif 'CONTRAT' in line.upper() or 'TYPE DE CONTRAT' in line.upper():
                current_section = 'contract_info'
            elif 'OFFRE ACTUELLE' in line.upper() or 'FOURNISSEUR ACTUEL' in line.upper():
                current_section = 'current_offer'
            elif 'ALTERNATIVES' in line.upper() or 'COMPARATIF' in line.upper():
                current_section = 'alternatives'
            elif 'PIÈGES' in line.upper() or 'PROBLÈMES' in line.upper():
                current_section = 'detected_issues'
            elif 'RECOMMANDATION' in line.upper():
                current_section = 'recommendation'
            elif 'ÉCONOMIE' in line.upper():
                current_section = 'savings_estimation'
            else:
                # Add content to current section
                if current_section == 'client_info':
                    if ':' in line:
                        key, value = line.split(':', 1)
                        data['client_info'][key.strip()] = value.strip()
                elif current_section and line:
                    if current_section not in data:
                        data[current_section] = []
                    if isinstance(data[current_section], list):
                        data[current_section].append(line)
                    else:
                        data[current_section] = line

        return data

    def calculate_savings(self, structured_data: Dict) -> Optional[float]:
        """Calculate savings from structured data"""
        try:
            current_offer = structured_data.get('current_offer', {})
            alternatives = structured_data.get('alternatives', [])

            # Extract current total cost
            current_total = None
            if isinstance(current_offer, dict):
                for key, value in current_offer.items():
                    if 'total' in key.lower() or 'montant' in key.lower():
                        amount_match = re.search(r'(\d+[,.]?\d*)', str(value))
                        if amount_match:
                            current_total = float(amount_match.group(1).replace(',', '.'))
                            break

            # Find best alternative
            if current_total and alternatives:
                best_saving = 0
                for alt in alternatives:
                    if isinstance(alt, dict):
                        for key, value in alt.items():
                            if 'total' in key.lower():
                                amount_match = re.search(r'(\d+[,.]?\d*)', str(value))
                                if amount_match:
                                    alt_total = float(amount_match.group(1).replace(',', '.'))
                                    saving = current_total - alt_total
                                    if saving > best_saving:
                                        best_saving = saving

                return round(best_saving, 2) if best_saving > 0 else None

            # Fallback: 12% calculation
            if current_total:
                return round(current_total * 0.12, 2)

            return None

        except Exception as e:
            logger.error(f"Erreur lors du calcul des économies: {str(e)}")
            return None

    def _get_enhanced_system_prompt(self) -> str:
        """Get enhanced system prompt for better analysis"""
        return """Tu es un expert en analyse de factures d'énergie (électricité, gaz), mobile, internet et assurances en France.

MISSION: Analyser la facture et produire un rapport comparatif professionnel structuré.

RÉPONSE ATTENDUE: Retourne tes données au format JSON structuré suivant:

{
  "type_facture": "électricité|gaz|mobile|internet|assurance",
  "client_info": {
    "nom": "Nom du client si trouvé",
    "adresse": "Adresse si trouvée", 
    "contrat_numero": "Numéro de contrat",
    "reference_client": "Référence client"
  },
  "current_offer": {
    "fournisseur": "Nom du fournisseur actuel",
    "offre_nom": "Nom de l'offre actuelle",
    "consommation_annuelle": "Consommation en kWh ou unité appropriée",
    "montant_total_annuel": "Montant total TTC sur 12 mois",
    "prix_moyen_kwh": "Prix moyen par kWh TTC",
    "abonnement_annuel": "Montant abonnement annuel",
    "puissance_souscrite": "Puissance en kVA si applicable",
    "option_tarifaire": "Base, HP/HC, etc si applicable"
  },
  "alternatives": [
    {
      "fournisseur": "Nom fournisseur 1",
      "offre": "Nom de l'offre",
      "prix_kwh": "Prix kWh",
      "abonnement": "Prix abonnement annuel",
      "total_annuel": "Total annuel TTC",
      "avantages": "Avantages spécifiques"
    },
    {
      "fournisseur": "Nom fournisseur 2", 
      "offre": "Nom de l'offre",
      "prix_kwh": "Prix kWh", 
      "abonnement": "Prix abonnement annuel",
      "total_annuel": "Total annuel TTC",
      "avantages": "Avantages spécifiques"
    }
  ],
  "detected_issues": [
    "Prix moyen élevé par rapport au marché (précise le prix)",
    "Absence d'avantages fidélité",
    "Abonnement surdimensionné pour le profil"
  ],
  "best_savings": {
    "fournisseur_recommande": "Meilleur fournisseur",
    "economie_annuelle": "Montant économie en euros",
    "pourcentage_economie": "Pourcentage d'économie"
  },
  "methodology": "Les données proviennent de votre facture et d'offres publiques vérifiables (TRV, CRE, sites fournisseurs officiels)."
}

INSTRUCTIONS IMPORTANTES:
1. Pour ALTERNATIVES, propose au moins 4-5 fournisseurs français majeurs avec des offres réelles du marché 2025
2. Pour ÉLECTRICITÉ: inclus EDF, Engie, TotalEnergies, ekWateur, Vattenfall, OHM Énergie
3. Pour GAZ: inclus Engie, EDF, TotalEnergies, ekWateur, Vattenfall, OHM Énergie  
4. Pour MOBILE: inclus Orange, SFR, Bouygues, Free, Sosh, RED, B&You
5. Pour INTERNET: inclus Orange, SFR, Bouygues, Free, RED
6. Calcule des prix réalistes basés sur les tarifs 2025
7. Identifie 2-3 pièges concrets et mesurables
8. Donne une recommandation chiffrée précise

EXEMPLE pour facture électricité:
Si la facture montre 2202 kWh/an pour 805€, compare avec:
- EDF Tarif Réglementé: ~705€
- OHM Énergie Base: ~627€ 
- TotalEnergies Essentielle: ~666€
Et identifie l'économie potentielle.

Analyse maintenant la facture fournie et retourne le JSON structuré."""