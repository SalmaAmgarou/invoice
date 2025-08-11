import re
import json
import logging
from typing import Dict, Optional, Tuple, List
from openai import OpenAI
from config import Config

logger = logging.getLogger(__name__)


def _extract_annual_total(alternative: Dict) -> float:
    """Safely extracts the annual total from an alternative offer."""
    # Ensure we are working with a string
    total_str = str(alternative.get('total_annuel', 'inf'))

    match = re.search(r'(\d+[,.]?\d*)', total_str)
    if match:
        return float(match.group(1).replace(',', '.'))

    # If no number is found, return infinity so it's never chosen as the minimum
    return float('inf')


class EnhancedInvoiceAnalyzer:
    def __init__(self):
        if not Config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY n'est pas configuré")

        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.system_prompt = self._get_enhanced_system_prompt()

    def analyze_invoice(self, extracted_text: str) -> Dict[str, str]:
        """
        Analyse améliorée avec contenu enrichi et données précises
        """
        try:
            user_message = f"TEXTE EXTRAIT DE LA FACTURE:\n{extracted_text}\n\nANALYSE DEMANDÉE:"

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=2000,  # Augmenté pour plus de détails
                temperature=0.05,  # Plus précis
                timeout=120.0
            )

            ai_result = response.choices[0].message.content

            if not ai_result:
                raise Exception("Aucune réponse générée par OpenAI")

            # Parse et enrichir la réponse
            parsed_data = self._parse_enhanced_response(ai_result)
            enriched_data = self._enrich_analysis_content(parsed_data)

            return {
                'structured_data': enriched_data,
                'raw_response': ai_result
            }

        except Exception as e:
            logger.error(f"Erreur lors de l'analyse OpenAI: {str(e)}")
            raise Exception(f"Erreur lors de l'analyse IA: {str(e)}")

    def _parse_enhanced_response(self, ai_result: str) -> Dict:
        """Parse amélioré avec validation et enrichissement"""

        # Essayer d'extraire le JSON
        json_match = re.search(r'\{.*\}', ai_result, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return self._validate_and_enhance_data(data)
            except json.JSONDecodeError:
                pass

        # Fallback vers parsing texte
        return self._parse_text_format_enhanced(ai_result)

    def _validate_and_enhance_data(self, data: Dict) -> Dict:
        """Valide et enrichit les données parsées"""

        # Structure garantie
        enhanced_data = {
            "type_facture": data.get('type_facture', 'énergie'),
            "client_info": data.get('client_info', {}),
            "current_offer": data.get('current_offer', {}),
            "alternatives": data.get('alternatives', []),
            "detected_issues": data.get('detected_issues', []),
            "market_analysis": data.get('market_analysis', {}),
            "best_savings": data.get('best_savings', {}),
            "recommendations": data.get('recommendations', []),
            "methodology": data.get('methodology', ''),
            "analysis_quality": "high"
        }

        # Enrichir les issues détectées avec des détails
        enhanced_data['detected_issues'] = self._enhance_detected_issues(
            enhanced_data['detected_issues'],
            enhanced_data['current_offer']
        )

        # Ajouter analyse de marché si manquante
        if not enhanced_data['market_analysis']:
            enhanced_data['market_analysis'] = self._generate_market_analysis(
                enhanced_data['type_facture'],
                enhanced_data['current_offer']
            )

        return enhanced_data

    def _enhance_detected_issues(self, issues: List[str], current_offer: Dict) -> List[str]:
        """Enrichit les problèmes détectés avec des détails spécifiques"""

        enhanced_issues = []

        for issue in issues:
            # Rendre les issues plus spécifiques
            if 'prix élevé' in issue.lower() or 'prix moyen élevé' in issue.lower():
                # Ajouter contexte du prix
                montant = current_offer.get('montant_total_annuel', '')
                if montant:
                    price_match = re.search(r'(\d+[,.]?\d*)', montant)
                    if price_match:
                        annual_cost = float(price_match.group(1).replace(',', '.'))
                        monthly_cost = annual_cost / 12
                        enhanced_issues.append(
                            f"Prix élevé par rapport au marché ({monthly_cost:.2f}€/mois soit {annual_cost:.0f}€/an)")
                    else:
                        enhanced_issues.append(issue)
                else:
                    enhanced_issues.append(issue)

            elif 'abonnement' in issue.lower():
                # Détailler le problème d'abonnement
                puissance = current_offer.get('puissance_souscrite', '')
                if puissance:
                    enhanced_issues.append(f"Abonnement potentiellement surdimensionné pour le profil ({puissance})")
                else:
                    enhanced_issues.append("Abonnement potentiellement inadapté au profil de consommation")

            elif 'fidélité' in issue.lower():
                enhanced_issues.append("Absence d'avantages fidélité ou de remises long terme")

            else:
                enhanced_issues.append(issue)

        # Ajouter des analyses supplémentaires si peu d'issues détectées
        if len(enhanced_issues) < 2:
            enhanced_issues.extend(self._detect_additional_issues(current_offer))

        return enhanced_issues[:4]  # Max 4 issues pour lisibilité

    def _detect_additional_issues(self, current_offer: Dict) -> List[str]:
        """Détecte des problèmes supplémentaires basés sur l'offre actuelle"""
        additional_issues = []

        # Analyse du type d'offre
        offre_nom = current_offer.get('offre_nom', '').lower()

        if 'fixe' in offre_nom:
            additional_issues.append("Offre à prix fixe sans avantage de marché en baisse")

        if 'variable' in offre_nom:
            additional_issues.append("Offre à prix variable exposée aux fluctuations du marché")

        # Analyse de la puissance (électricité)
        puissance = current_offer.get('puissance_souscrite', '')
        if puissance:
            kva_match = re.search(r'(\d+)', puissance)
            if kva_match:
                kva = int(kva_match.group(1))
                if kva >= 9:
                    additional_issues.append("Puissance souscrite élevée - vérifier si nécessaire")

        return additional_issues

    def _generate_market_analysis(self, facture_type: str, current_offer: Dict) -> Dict:
        """Génère une analyse de marché contextuelle"""

        analysis = {
            "market_trend": "",
            "competition_level": "",
            "price_evolution": "",
            "regulatory_context": ""
        }

        if 'electricite' in facture_type.lower() or 'électricité' in facture_type.lower():
            analysis.update({
                "market_trend": "Marché très concurrentiel avec de nombreuses offres alternatives",
                "competition_level": "Élevée - plus de 40 fournisseurs actifs en France",
                "price_evolution": "Stabilisation après les hausses de 2022-2023",
                "regulatory_context": "Tarifs réglementés EDF comme référence du marché"
            })

        elif 'gaz' in facture_type.lower():
            analysis.update({
                "market_trend": "Marché ouvert avec alternatives compétitives",
                "competition_level": "Modérée à élevée - environ 20 fournisseurs majeurs",
                "price_evolution": "Volatilité liée aux prix européens du gaz",
                "regulatory_context": "Suppression progressive des tarifs réglementés"
            })

        elif 'internet' in facture_type.lower():
            analysis.update({
                "market_trend": "Guerre des prix sur la fibre, consolidation du marché",
                "competition_level": "Très élevée - 4 opérateurs majeurs + MVNO",
                "price_evolution": "Baisse tendancielle des prix fibre",
                "regulatory_context": "Régulation ARCEP pour la concurrence"
            })

        return analysis

    def _enrich_analysis_content(self, data: Dict) -> Dict:
        """Enrichit le contenu de l'analyse avec des insights supplémentaires"""

        # Ajouter des recommandations détaillées
        data['detailed_recommendations'] = self._generate_detailed_recommendations(data)

        # Ajouter score de performance actuelle
        data['performance_score'] = self._calculate_performance_score(data)

        # Ajouter timeline d'action recommandée
        data['action_timeline'] = self._generate_action_timeline(data)

        return data

    def _generate_detailed_recommendations(self, data: Dict) -> List[Dict]:
        """Génère des recommandations détaillées avec priorités"""

        recommendations = []
        facture_type = data.get('type_facture', '').lower()
        alternatives = data.get('alternatives', [])

        # Recommandation principale de changement
        if alternatives:
            best_alt = min(alternatives, key=_extract_annual_total)

            best_total = _extract_annual_total(best_alt)
            if best_total != float('inf'):
                recommendations.append({
                    "priority": "Haute",
                    "action": "Changement de fournisseur",
                    "details": f"Passer à {best_alt.get('fournisseur', 'Alternative recommandée')}",
                    "expected_benefit": best_alt.get('total_annuel', ''),
                    "effort": "Faible",
                    "timeline": "1-2 mois"
                })

                # Recommandations spécifiques par type
        if 'electricite' in facture_type or 'électricité' in facture_type:
            recommendations.extend([
            {
            "priority": "Moyenne",
            "action": "Optimisation de la puissance",
            "details": "Vérifier si la puissance souscrite correspond aux besoins réels",
            "expected_benefit": "10-20% d'économie sur l'abonnement",
            "effort": "Moyen",
            "timeline": "Immédiat"
            },
            {
            "priority": "Moyenne",
            "action": "Option tarifaire",
            "details": "Évaluer l'intérêt des heures creuses selon votre profil",
            "expected_benefit": "5-15% selon usage",
            "effort": "Faible",
            "timeline": "Lors du changement"
            }
            ])

        elif 'internet' in facture_type:
            recommendations.extend([
            {
            "priority": "Moyenne",
            "action": "Négociation avec l'opérateur actuel",
            "details": "Contacter le service client pour obtenir une offre de rétention",
            "expected_benefit": "10-30% de remise possible",
            "effort": "Faible",
            "timeline": "Immédiat"
            },
            {
            "priority": "Faible",
            "action": "Services inclus",
            "details": "Vérifier l'utilisation réelle des services TV/téléphonie inclus",
            "expected_benefit": "Possibilité de forfait plus simple",
            "effort": "Faible",
            "timeline": "Évaluation continue"
            }
            ])

        return recommendations

    def _calculate_performance_score(self, data: Dict) -> Dict:
        """Calcule un score de performance de l'offre actuelle"""

        score_data = {
            "overall_score": 0,
            "price_competitiveness": 0,
            "contract_flexibility": 0,
            "service_quality": 0,
            "market_position": ""
        }

        # Score basé sur les alternatives disponibles
        alternatives = data.get('alternatives', [])
        current_offer = data.get('current_offer', {})

        if alternatives and current_offer.get('montant_total_annuel'):
            try:
                current_total = float(
                    re.search(r'(\d+[,.]?\d*)', current_offer['montant_total_annuel']).group(1).replace(',', '.'))

                alt_totals = []
                for alt in alternatives:
                    total_str = alt.get('total_annuel', '0')
                    total_match = re.search(r'(\d+[,.]?\d*)', total_str)
                    if total_match:
                        alt_totals.append(float(total_match.group(1).replace(',', '.')))

                if alt_totals:
                    min_market = min(alt_totals)
                    max_market = max(alt_totals)

                    # Score de compétitivité prix (0-100)
                    if current_total <= min_market:
                        score_data["price_competitiveness"] = 100
                        score_data["market_position"] = "Excellente"
                    elif current_total <= (min_market + max_market) / 2:
                        score_data["price_competitiveness"] = 70
                        score_data["market_position"] = "Correcte"
                    else:
                        score_data["price_competitiveness"] = 30
                        score_data["market_position"] = "À améliorer"

            except Exception as e:
                logger.warning(f"Erreur calcul score: {e}")

        # Score global
        score_data["overall_score"] = score_data["price_competitiveness"]

        return score_data

    def _generate_action_timeline(self, data: Dict) -> Dict:
        """Génère un planning d'actions recommandées"""

        return {
            "immediate": [
                "Comparer les offres alternatives",
                "Calculer les économies potentielles exactes"
            ],
            "within_1_month": [
                "Contacter les fournisseurs pour devis personnalisés",
                "Vérifier les conditions de résiliation actuelle"
            ],
            "within_3_months": [
                "Effectuer le changement de fournisseur",
                "Optimiser la puissance souscrite si nécessaire"
            ],
            "ongoing": [
                "Surveiller l'évolution des prix du marché",
                "Réévaluer annuellement les options disponibles"
            ]
        }

    def calculate_savings(self, structured_data: Dict) -> Optional[float]:
        """Calcul amélioré des économies avec validation"""
        try:
            current_offer = structured_data.get('current_offer', {})
            alternatives = structured_data.get('alternatives', [])

            # Extraire le coût actuel
            current_total = None
            montant_str = current_offer.get('montant_total_annuel', '')
            if montant_str:
                amount_match = re.search(r'(\d+[,.]?\d*)', montant_str)
                if amount_match:
                    current_total = float(amount_match.group(1).replace(',', '.'))

            # Trouver la meilleure alternative
            if current_total and alternatives:
                best_saving = 0
                for alt in alternatives:
                    total_str = alt.get('total_annuel', '')
                    if total_str:
                        alt_match = re.search(r'(\d+[,.]?\d*)', total_str)
                        if alt_match:
                            alt_total = float(alt_match.group(1).replace(',', '.'))
                            saving = current_total - alt_total
                            if saving > best_saving:
                                best_saving = saving

                return round(best_saving, 2) if best_saving > 0 else None

            # Fallback: estimation 12%
            if current_total:
                return round(current_total * 0.12, 2)

            return None

        except Exception as e:
            logger.error(f"Erreur calcul économies: {str(e)}")
            return None

    def _get_enhanced_system_prompt(self) -> str:
        """Prompt système amélioré pour une analyse plus riche"""
        return """Tu es un expert senior en analyse de contrats énergie, télécoms et assurances en France avec 15 ans d'expérience.

MISSION: Analyser la facture et produire un rapport comparatif détaillé et précis avec des données réelles du marché français 2025.

RÉPONSE REQUISE: JSON structuré avec analyse approfondie:

{
  "type_facture": "électricité|gaz|mobile|internet|assurance",
  "client_info": {
    "nom": "Nom complet si trouvé",
    "adresse": "Adresse complète",
    "contrat_numero": "Numéro de contrat",
    "reference_client": "Référence client",
    "zone_tarifaire": "Zone si applicable (B0, B1, etc.)"
  },
  "current_offer": {
    "fournisseur": "Nom exact du fournisseur",
    "offre_nom": "Nom exact de l'offre",
    "consommation_annuelle": "Consommation avec unité (kWh, Go, etc.)",
    "montant_total_annuel": "Montant TTC sur 12 mois",
    "prix_moyen_kwh": "Prix unitaire TTC",
    "abonnement_annuel": "Partie fixe annuelle",
    "puissance_souscrite": "Puissance en kVA si applicable",
    "option_tarifaire": "Base/HP-HC/Tempo si applicable",
    "engagement": "Durée engagement restant",
    "date_souscription": "Date si trouvée"
  },
  "alternatives": [
    {
      "fournisseur": "EDF|Engie|TotalEnergies|OHM|Vattenfall|ekWateur|etc.",
      "offre": "Nom précis de l'offre 2025",
      "prix_kwh": "Prix kWh TTC réel",
      "abonnement": "Abonnement annuel réel",
      "total_annuel": "Total calculé TTC",
      "avantages": "Points forts spécifiques",
      "inconvenients": "Limitations éventuelles"
    }
  ],
  "detected_issues": [
    "Prix X% au-dessus de la moyenne marché (chiffrer précisément)",
    "Abonnement surdimensionné de X kVA par rapport aux besoins estimés",
    "Absence d'offre verte disponible chez d'autres fournisseurs",
    "Frais cachés détectés: service client payant / frais de résiliation"
  ],
  "market_analysis": {
    "market_trend": "Tendance actuelle du marché",
    "competition_level": "Niveau de concurrence",
    "price_evolution": "Évolution récente des prix",
    "regulatory_context": "Contexte réglementaire"
  },
  "best_savings": {
    "fournisseur_recommande": "Meilleur fournisseur identifié",
    "economie_annuelle": "Montant précis en euros",
    "pourcentage_economie": "Pourcentage d'économie",
    "delai_retour": "Temps pour récupérer les frais de changement"
  },
  "methodology": "Sources: facture client + données temps réel des fournisseurs (TRV, sites officiels, CRE, ARCEP) + comparateurs certifiés."
}

TARIFS RÉELS 2025 À UTILISER:

ÉLECTRICITÉ (Base TTC):
- EDF Bleu: 0,2516€/kWh + 151,20€/an
- Engie Référence: 0,2489€/kWh + 154,44€/an  
- TotalEnergies Essentielle: 0,2340€/kWh + 151,20€/an
- OHM Essentielle: 0,2229€/kWh + 136,14€/an
- ekWateur Vert: 0,2480€/kWh + 158,00€/an
- Vattenfall Eco: 0,2452€/kWh + 150,00€/an

GAZ (B1 TTC):
- Engie Référence: 0,1121€/kWh + 257,16€/an
- TotalEnergies Verte: 0,1023€/kWh + 265,00€/an
- OHM Essentielle: 0,0948€/kWh + 249,60€/an
- ekWateur: 0,1036€/kWh + 270,00€/an
- Vattenfall: 0,1005€/kWh + 255,00€/an

INTERNET FIBRE (TTC):
- Orange Livebox: 42,99€/mois (promo 22,99€ 12 mois)
- Free Freebox Pop: 29,99€/mois vie
- SFR Fiber Power: 43,00€/mois (promo 23,00€ 12 mois)
- Bouygues Bbox Must: 41,99€/mois (promo 22,99€ 12 mois)
- RED Box: 24,00€/mois vie

INSTRUCTIONS CRITIQUES:
1. Utilise UNIQUEMENT ces tarifs réels 2025 - pas d'invention
2. Calcule précisément les totaux selon la consommation donnée
3. Identifie 3-4 problèmes concrets et chiffrés
4. Donne une recommandation avec économie exacte en euros
5. Mentionne les vraies sources (TRV, CRE, sites fournisseurs)
6. Analyse la facture ligne par ligne pour extraire toutes les données
7. Si données manquantes, l'indiquer clairement

Analyse maintenant la facture avec cette expertise et ces données réelles."""