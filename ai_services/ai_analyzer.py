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
                'keywords': ['kwh', 'électricité', 'edf', 'engie', 'totalenergies',
                             'tarif bleu', 'heures creuses', 'heures pleines'],
                'providers': ['EDF', 'Engie', 'TotalEnergies', 'OHM', 'ekWateur',
                              'Vattenfall', 'Planète OUI', 'Mint Énergie', 'Alpiq']
            },
            'gaz': {
                'keywords': ['gaz naturel', 'm3', 'mètres cubes', 'thermes'],
                'providers': ['Engie', 'TotalEnergies', 'ENI', 'ekWateur', 'Vattenfall']
            },
            'dual': {  # Nouvelle catégorie
                'keywords': ['offre duale', 'bi-énergie', 'électricité et gaz'],
                'providers': ['EDF', 'Engie', 'TotalEnergies', 'Eni', 'OHM']
            },
            'internet': {
                'keywords': ['internet', 'fibre', 'adsl', 'livebox', 'freebox'],
                'providers': ['Orange', 'Free', 'SFR', 'Bouygues', 'RED', 'Sosh']
            },
            'mobile': {
                'keywords': ['mobile', 'forfait', 'go', '4g', '5g'],
                'providers': ['Orange', 'Free', 'SFR', 'Bouygues', 'RED', 'Sosh']
            },
            'internet_mobile': {
                'keywords': ['open', 'pack', 'offre groupée', 'convergente'],
                'providers': ['Orange', 'Free', 'SFR', 'Bouygues']
            },
            'eau': {  # Nouveau type
                'keywords': ['eau potable', 'm3', 'assainissement', 'consommation eau'],
                'providers': ['Veolia', 'Suez', 'SAUR', 'Régie municipale']
            },
            'assurance_auto': {
                'keywords': ['assurance auto', 'véhicule', 'sinistre', 'franchise'],
                'providers': ['AXA', 'Allianz', 'MAIF', 'MACIF', 'Matmut', 'MMA']
            },
            'assurance_habitation': {
                'keywords': ['assurance habitation', 'multirisque', 'logement'],
                'providers': ['AXA', 'Allianz', 'MAIF', 'MACIF', 'Matmut', 'MMA']
            }
        }

    def analyze_invoice_with_type(self, extracted_text: str, invoice_type: str, db_offers: List[Dict] = None) -> \
    Dict[str, Any]:
        """
        Analyse avec type prédéfini par l'utilisateur (pas de détection automatique)
        """
        try:
            logger.info(f"🎯 Analyse pour type défini: {invoice_type}")

            # Extraction structurée directe avec le type fourni
            structured_data = self._extract_structured_data_with_offers(
                extracted_text,
                invoice_type,
                db_offers
            )

            # Analyse des problèmes selon le type
            issues = self._detect_issues(structured_data, invoice_type)

            # Compilation du résultat
            result = {
                'type_facture': invoice_type,
                'confidence': 100,  # 100% car défini par l'utilisateur
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
            logger.error(f"Erreur analyse avec type: {str(e)}")
            raise

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
                    logger.info(
                        f"LLM n'a généré que {len(result.get('alternatives', []))} alternatives, utilisation de toutes les {len(db_offers)} offres DB")
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
        "m3_consommes": "Total m³ consommés si présent",
        "coefficient_conversion": "Coefficient de conversion m³ vers kWh si présent"
      }},
      "alternatives": [
        {{
          "fournisseur": "Nom du fournisseur",
          "offre": "Nom de l'offre",
          "prix_kwh": "Prix kWh TTC",
          "abonnement": "Abonnement annuel TTC",
          "total_annuel": "Total annuel calculé TTC",
          "type_gaz": "gaz naturel ou biogaz %"
        }}
      ],
      "best_savings": {{
        "fournisseur_recommande": "Nom du fournisseur recommandé",
        "economie_annuelle": "Économie annuelle en euros",
        "pourcentage_economie": "Pourcentage d'économie"
      }}
    }}

    Utilise les offres disponibles pour remplir 'alternatives' et calculer 'best_savings'.{offers_context}"""

        elif invoice_type == 'dual' or invoice_type == 'electricite_gaz':
            return f"""Tu es expert en factures duales électricité/gaz françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "adresse": "Adresse complète",
        "numero_pdl": "Point de livraison électricité",
        "numero_pce": "Point comptage gaz",
        "numero_contrat": "N° contrat unique ou séparés"
      }},
      "current_offer": {{
        "fournisseur": "Nom du fournisseur unique",
        "offre_nom": "Nom de l'offre duale",
        "electricite": {{
          "consommation_annuelle_kwh": "Consommation électricité en kWh",
          "montant_annuel": "Montant annuel électricité €",
          "prix_kwh": "Prix kWh électricité",
          "abonnement_annuel": "Abonnement électricité €",
          "puissance_souscrite": "Puissance kVA",
          "option_tarifaire": "Base ou HP/HC"
        }},
        "gaz": {{
          "consommation_annuelle_kwh": "Consommation gaz en kWh",
          "montant_annuel": "Montant annuel gaz €",
          "prix_kwh": "Prix kWh gaz",
          "abonnement_annuel": "Abonnement gaz €",
          "classe_consommation": "B0/B1/B2I"
        }},
        "montant_total_annuel": "Total annuel combiné €",
        "reduction_duale": "Réduction pour offre groupée si applicable"
      }},
      "alternatives": [
        {{
          "fournisseur": "Nom du fournisseur",
          "offre": "Nom de l'offre duale",
          "electricite_prix_kwh": "Prix kWh électricité",
          "gaz_prix_kwh": "Prix kWh gaz",
          "total_annuel": "Total annuel calculé TTC",
          "avantages": "Avantages offre duale"
        }}
      ],
      "best_savings": {{
        "fournisseur_recommande": "Nom du fournisseur recommandé",
        "economie_annuelle": "Économie annuelle totale en euros",
        "economie_electricite": "Économie sur l'électricité €",
        "economie_gaz": "Économie sur le gaz €"
      }}
    }}

    Utilise les offres électricité ET gaz disponibles. Privilégie les offres duales combinées.{offers_context}"""

        elif invoice_type == 'internet':
            return f"""Tu es expert en factures internet/fibre françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "adresse": "Adresse de service",
        "numero_client": "N° client",
        "numero_ligne": "N° ligne fixe associée",
        "reference_pto": "Référence PTO fibre si présente"
      }},
      "current_offer": {{
        "fournisseur": "Orange|Free|SFR|Bouygues|RED|Sosh",
        "offre_nom": "Nom exact de l'offre box",
        "type_connexion": "Fibre|ADSL|VDSL",
        "debit": "Débit en Mbps ou Gbps",
        "prix_mensuel": "Prix mensuel TTC €",
        "prix_promo": "Prix promotionnel si applicable",
        "duree_promo": "Durée de la promotion",
        "montant_total_annuel": "Montant annuel calculé",
        "services_inclus": {{
          "tv": "Oui/Non et nombre de chaînes",
          "telephone_fixe": "Illimité vers fixes/mobiles",
          "options": "Netflix, Canal+, etc."
        }},
        "engagement": "Date fin engagement ou sans engagement",
        "frais_resiliation": "Montant si applicable"
      }},
      "consommation": {{
        "data_consommee": "Volume données si plafonné",
        "appels_fixes": "Minutes consommées si non illimité"
      }},
      "alternatives": [
        {{
          "fournisseur": "Nom du fournisseur",
          "offre": "Nom de l'offre",
          "type": "Fibre/ADSL",
          "prix_mensuel": "Prix mensuel TTC",
          "prix_promo": "Prix promo 1ère année",
          "total_annuel": "Total annuel calculé",
          "avantages": "Points forts de l'offre"
        }}
      ],
      "best_savings": {{
        "fournisseur_recommande": "Nom du fournisseur recommandé",
        "economie_annuelle": "Économie annuelle en euros",
        "services_supplementaires": "Services en plus par rapport à l'offre actuelle"
      }}
    }}

    Compare avec les offres internet disponibles sur le marché.{offers_context}"""

        elif invoice_type == 'mobile':
            return f"""Tu es expert en factures mobile françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "numero_telephone": "06/07 XX XX XX XX",
        "numero_client": "N° client",
        "numero_contrat": "N° contrat ou compte"
      }},
      "current_offer": {{
        "fournisseur": "Orange|Free|SFR|Bouygues|RED|Sosh|B&You",
        "offre_nom": "Nom exact du forfait",
        "prix_mensuel": "Prix mensuel TTC €",
        "data_incluse": "Go de data inclus",
        "data_europe": "Go en Europe/DOM",
        "appels": "Illimités ou X heures",
        "sms_mms": "Illimités ou nombre",
        "5g": "Oui/Non",
        "montant_total_annuel": "Montant annuel calculé",
        "engagement": "Avec ou sans engagement",
        "options": {{
          "multi_sim": "Oui/Non",
          "international": "Pays inclus",
          "autres": "Autres options souscrites"
        }}
      }},
      "consommation": {{
        "data_consommee": "Go consommés sur la période",
        "appels": "Minutes consommées",
        "sms": "Nombre de SMS envoyés",
        "hors_forfait": "Montant hors forfait si applicable"
      }},
      "alternatives": [
        {{
          "fournisseur": "Nom du fournisseur",
          "offre": "Nom du forfait",
          "prix_mensuel": "Prix mensuel TTC",
          "data": "Go inclus",
          "5g": "Inclus ou non",
          "total_annuel": "Total annuel",
          "avantages": "Points forts"
        }}
      ],
      "best_savings": {{
        "fournisseur_recommande": "Nom du fournisseur recommandé",
        "economie_annuelle": "Économie annuelle en euros",
        "data_supplementaire": "Go en plus par rapport au forfait actuel"
      }}
    }}

    Compare avec les forfaits mobile actuels du marché.{offers_context}"""

        elif invoice_type == 'internet_mobile':
            return f"""Tu es expert en factures convergentes internet+mobile françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "adresse": "Adresse de service",
        "numero_client": "N° client unique",
        "reference_pto": "Référence fibre si présente"
      }},
      "current_offer": {{
        "fournisseur": "Orange|SFR|Free|Bouygues",
        "offre_nom": "Nom de l'offre convergente",
        "prix_mensuel_total": "Prix mensuel pack TTC €",
        "montant_total_annuel": "Montant annuel calculé",
        "internet": {{
          "type": "Fibre/ADSL",
          "debit": "Débit Mbps/Gbps",
          "tv_incluse": "Oui/Non + chaînes",
          "telephone_fixe": "Illimité vers"
        }},
        "mobile": {{
          "nombre_lignes": "Nombre de forfaits mobiles",
          "forfait_principal": "Go et prix forfait principal",
          "forfaits_additionnels": "Détails lignes supplémentaires",
          "data_partagee": "Enveloppe data partagée si applicable"
        }},
        "avantages_convergence": "Réductions ou avantages du pack",
        "engagement": "Date fin engagement si applicable"
      }},
      "consommation": {{
        "data_mobile_totale": "Go consommés toutes lignes",
        "streaming_inclus": "Netflix, Disney+, etc."
      }},
      "alternatives": [
        {{
          "fournisseur": "Nom du fournisseur",
          "offre": "Nom offre convergente",
          "prix_mensuel": "Prix mensuel TTC",
          "composition": "Box + X forfaits",
          "total_annuel": "Total annuel calculé",
          "avantages": "Avantages du pack"
        }}
      ],
      "best_savings": {{
        "fournisseur_recommande": "Nom du fournisseur recommandé",
        "economie_annuelle": "Économie annuelle en euros",
        "services_supplementaires": "Ce qui est gagné en plus"
      }}
    }}

    Compare avec les offres convergentes (Open, Freebox Pop + mobile, etc.).{offers_context}"""

        elif invoice_type == 'eau':
            return f"""Tu es expert en factures d'eau françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "adresse": "Adresse de desserte",
        "numero_contrat": "N° contrat ou abonné",
        "numero_compteur": "N° compteur d'eau"
      }},
      "current_offer": {{
        "distributeur": "Veolia|Suez|SAUR|Régie municipale|Autre",
        "gestionnaire": "Nom de la collectivité ou syndicat",
        "consommation_periode": "m³ sur la période",
        "consommation_annuelle_m3": "Consommation annuelle estimée en m³",
        "montant_total_annuel": "Montant total annuel TTC €",
        "detail_tarification": {{
          "part_fixe_abonnement": "Abonnement annuel €",
          "prix_m3_eau_potable": "Prix du m³ eau potable",
          "prix_m3_assainissement": "Prix du m³ assainissement",
          "taxes_agence_eau": "Redevances agence de l'eau €",
          "tva": "Montant TVA"
        }},
        "type_tarification": "Binomiale|Volumétrique|Forfaitaire"
      }},
      "consommation": {{
        "periode": "Période de facturation",
        "index_ancien": "Index précédent",
        "index_nouveau": "Nouvel index",
        "m3_consommes": "m³ consommés",
        "moyenne_journaliere": "Litres/jour si indiqué"
      }},
      "alternatives": [
        {{
          "type": "Information",
          "message": "Le service d'eau est un monopole local - pas de changement de fournisseur possible",
          "conseil": "Économies possibles uniquement par réduction de consommation"
        }}
      ],
      "best_savings": {{
        "recommandations": [
          "Vérifier les fuites (compteur qui tourne robinets fermés)",
          "Installer des mousseurs sur les robinets",
          "Privilégier les douches aux bains",
          "Récupération eau de pluie pour jardin"
        ],
        "economie_potentielle": "20-30% par les éco-gestes",
        "aide_fuite": "Écrêtement possible de la facture en cas de fuite après compteur"
      }}
    }}

    Note: L'eau est un service public local sans concurrence. Focus sur les conseils d'économie.{offers_context}"""

        elif invoice_type == 'assurance_auto':
            return f"""Tu es expert en factures d'assurance automobile françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "adresse": "Adresse du souscripteur",
        "numero_contrat": "N° contrat ou police",
        "numero_societaire": "N° sociétaire si mutuelle"
      }},
      "current_offer": {{
        "assureur": "Nom de la compagnie d'assurance",
        "type_contrat": "Tous risques|Tiers étendu|Tiers|Au kilomètre",
        "vehicule": {{
          "marque_modele": "Marque et modèle",
          "immatriculation": "Plaque d'immatriculation",
          "annee": "Année du véhicule",
          "valeur_argus": "Valeur à dire d'expert si indiquée"
        }},
        "prime_annuelle": "Prime annuelle TTC €",
        "mensualite": "Si paiement mensuel €/mois",
        "bonus_malus": "Coefficient bonus-malus",
        "franchises": {{
          "bris_glace": "Franchise bris de glace €",
          "vol": "Franchise vol €",
          "accident": "Franchise accident responsable €"
        }},
        "garanties": {{
          "responsabilite_civile": "Obligatoire - montants",
          "dommages_collision": "Oui/Non",
          "vol_incendie": "Oui/Non",
          "bris_glace": "Oui/Non",
          "assistance": "0 km ou X km",
          "protection_juridique": "Oui/Non",
          "garantie_conducteur": "Capital si accident"
        }},
        "date_echeance": "Date échéance annuelle"
      }},
      "conducteurs": {{
        "principal": "Nom et date permis",
        "secondaires": "Autres conducteurs déclarés"
      }},
      "alternatives": [
        {{
          "assureur": "Nom assureur",
          "formule": "Type de formule",
          "prime_annuelle": "Prime annuelle TTC",
          "franchises": "Niveau franchises",
          "avantages": "Points forts"
        }}
      ],
      "best_savings": {{
        "assureur_recommande": "Nom de l'assureur recommandé",
        "economie_annuelle": "Économie annuelle en euros",
        "garanties_supplementaires": "Garanties en plus",
        "conseil_franchise": "Augmenter franchise pour réduire prime"
      }}
    }}

    Compare avec les tarifs d'assurance auto actuels. Attention au niveau de garanties équivalent.{offers_context}"""

        elif invoice_type == 'assurance_habitation':
            return f"""Tu es expert en factures d'assurance habitation françaises. Extrais selon ce schéma JSON strict:

    {{
      "client_info": {{
        "nom": "Nom complet du client",
        "adresse_assuree": "Adresse du logement assuré",
        "numero_contrat": "N° contrat ou police",
        "statut": "Propriétaire|Locataire|PNO"
      }},
      "current_offer": {{
        "assureur": "Nom de la compagnie d'assurance",
        "type_contrat": "MRH|Locataire|PNO|Étudiant",
        "logement": {{
          "type": "Appartement|Maison",
          "surface": "Surface en m²",
          "nombre_pieces": "Nombre de pièces principales",
          "annee_construction": "Si indiquée",
          "residence": "Principale|Secondaire"
        }},
        "prime_annuelle": "Prime annuelle TTC €",
        "mensualite": "Si paiement mensuel €/mois",
        "capital_mobilier": "Capital mobilier assuré €",
        "franchises": {{
          "generale": "Franchise générale €",
          "catastrophe_naturelle": "Franchise cat nat €",
          "degat_eaux": "Franchise dégât des eaux €"
        }},
        "garanties": {{
          "responsabilite_civile": "Montants couverts",
          "incendie_explosion": "Oui - plafonds",
          "degat_eaux": "Oui - conditions",
          "vol_vandalisme": "Oui/Non - conditions",
          "bris_glace": "Oui/Non",
          "catastrophes_naturelles": "Oui",
          "tempete": "Oui",
          "assistance": "Type assistance incluse",
          "protection_juridique": "Oui/Non - plafond"
        }},
        "options": "Piscine, dépendances, objets de valeur",
        "date_echeance": "Date échéance annuelle"
      }},
      "sinistralite": {{
        "nombre_sinistres": "Sur les 3 dernières années",
        "nature_sinistres": "Types de sinistres déclarés"
      }},
      "alternatives": [
        {{
          "assureur": "Nom assureur",
          "formule": "Type de formule",
          "prime_annuelle": "Prime annuelle TTC",
          "capital_mobilier": "Capital mobilier",
          "avantages": "Points forts"
        }}
      ],
      "best_savings": {{
        "assureur_recommande": "Nom de l'assureur recommandé",
        "economie_annuelle": "Économie annuelle en euros",
        "garanties_supplementaires": "Garanties améliorées",
        "conseil": "Ajuster capital mobilier et franchises"
      }}
    }}

    Compare avec les tarifs MRH actuels. Vérifie l'équivalence des garanties et capitaux.{offers_context}"""

        else:
            # Fallback pour type inconnu
            return f"""Analyse ce document de type {invoice_type}. Extrais le maximum d'informations structurées:

    {{
      "client_info": {{
        "nom": "Nom du client",
        "adresse": "Adresse si présente",
        "numero_client": "Identifiant client"
      }},
      "current_offer": {{
        "fournisseur": "Nom du fournisseur/prestataire",
        "service": "Description du service",
        "montant_periode": "Montant pour la période",
        "montant_annuel": "Montant annuel estimé",
        "details": "Autres informations pertinentes"
      }},
      "alternatives": [
        "Pas d'alternatives identifiées pour ce type de service"
      ],
      "best_savings": {{
        "message": "Analyse manuelle recommandée pour ce type de document"
      }}
    }}

    Extrais toutes les informations disponibles du document.{offers_context}"""

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