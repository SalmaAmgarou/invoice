import requests
import json
import re
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
import time

logger = logging.getLogger(__name__)


class CompetitiveOffersSearchService:
    """Service de recherche d'offres concurrentes via web search"""

    def __init__(self, search_api_key: Optional[str] = None):
        self.search_api_key = search_api_key

        # URLs des principaux comparateurs français
        self.comparator_urls = {
            'energie': [
                'https://www.energie-info.fr',
                'https://www.selectra.info/energie',
                'https://www.comparateur-energie.fr',
                'https://www.papernest.com/energie/',
                'https://www.hellowatt.fr'
            ],
            'telecom': [
                'https://www.ariase.com',
                'https://www.degrouptest.com',
                'https://www.boutique-box-internet.fr',
                'https://www.comparateur-box.com'
            ],
            'assurance': [
                'https://www.lesfurets.com',
                'https://www.lelynx.fr',
                'https://www.assurland.com'
            ]
        }

        # Patterns d'extraction pour chaque type
        self.extraction_patterns = {
            'energie_electricite': {
                'fournisseur': r'(EDF|Engie|TotalEnergies|OHM[\s\w]*|ekWateur|Vattenfall|Planète OUI|Mint Énergie)',
                'prix_kwh': r'(\d+[,.]?\d*)\s*[c€]?/?\s*kwh',
                'abonnement': r'(\d+[,.]?\d*)\s*€[/\s]*an',
                'offre_nom': r'(Tarif\s+\w+|Offre\s+\w+|\w+\s+Électricité)'
            },
            'telecom_internet': {
                'fournisseur': r'(Orange|SFR|Free|Bouygues|RED|Sosh)',
                'prix_mensuel': r'(\d+[,.]?\d*)\s*€[/\s]*mois',
                'debit': r'(\d+)\s*Mb?/s',
                'offre_nom': r'(Livebox|Freebox|Bbox|RED Box)[\s\w]*'
            }
        }

    def search_competitive_offers(self, invoice_type: str, current_offer: Dict, consumption_data: Dict = None) -> List[
        Dict]:
        """Point d'entrée principal pour rechercher des offres concurrentes"""

        try:
            if invoice_type == 'energie':
                return self._search_energy_offers(current_offer, consumption_data)
            elif invoice_type == 'telecom':
                return self._search_telecom_offers(current_offer)
            elif invoice_type == 'assurance':
                return self._search_insurance_offers(current_offer)
            else:
                logger.warning(f"Type d'offre non supporté: {invoice_type}")
                return []

        except Exception as e:
            logger.error(f"Erreur recherche offres {invoice_type}: {e}")
            return self._get_cached_offers(invoice_type)

    def _search_energy_offers(self, current_offer: Dict, consumption_data: Dict = None) -> List[Dict]:
        """Recherche spécialisée pour les offres énergie"""

        competitive_offers = []

        # 1. Recherche via API de recherche si disponible
        if self.search_api_key:
            api_offers = self._api_search_energy_offers(current_offer)
            competitive_offers.extend(api_offers)

        # 2. Scraping ciblé des comparateurs
        scraping_offers = self._scrape_energy_comparators(current_offer)
        competitive_offers.extend(scraping_offers)

        # 3. Fusion avec données statiques actualisées
        static_offers = self._get_updated_static_energy_offers()
        competitive_offers.extend(static_offers)

        # 4. Déduplication et classement
        unique_offers = self._deduplicate_and_rank_offers(competitive_offers, current_offer)

        return unique_offers[:5]  # Top 5 selon vos instructions

    def _api_search_energy_offers(self, current_offer: Dict) -> List[Dict]:
        """Recherche via APIs publiques (Brave Search, Bing, etc.)"""

        if not self.search_api_key:
            return []

        search_queries = [
            "meilleurs tarifs électricité 2025 comparaison prix kWh",
            "comparateur électricité OHM Energie TotalEnergies EDF 2025",
            "tarifs électricité moins cher que EDF janvier 2025",
            f"alternative fournisseur électricité {current_offer.get('fournisseur', '')} 2025"
        ]

        offers = []

        for query in search_queries:
            try:
                search_results = self._execute_search_query(query)
                parsed_offers = self._parse_search_results_for_energy(search_results)
                offers.extend(parsed_offers)

                # Pause pour éviter rate limiting
                time.sleep(1)

            except Exception as e:
                logger.warning(f"Erreur recherche API '{query}': {e}")
                continue

        return offers

    def _execute_search_query(self, query: str) -> str:
        """Exécute une recherche web via API"""

        # Exemple avec Brave Search API (remplacez par votre service)
        try:
            headers = {
                'Accept': 'application/json',
                'X-Subscription-Token': self.search_api_key
            }

            url = f"https://api.search.brave.com/res/v1/web/search"
            params = {
                'q': query,
                'count': 10,
                'search_lang': 'fr',
                'country': 'FR',
                'freshness': 'pm'  # Past month pour infos récentes
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                results = response.json()

                # Extraire contenu des résultats
                content = ""
                for result in results.get('web', {}).get('results', []):
                    content += f"{result.get('title', '')} {result.get('description', '')} "

                return content
            else:
                logger.warning(f"Search API error: {response.status_code}")
                return ""

        except Exception as e:
            logger.error(f"Search API failed: {e}")
            return ""

    def _parse_search_results_for_energy(self, search_content: str) -> List[Dict]:
        """Parse les résultats de recherche pour extraire les offres énergie"""

        offers = []

        # Patterns améliorés pour extraire les informations des résultats
        patterns = self.extraction_patterns['energie_electricite']

        # Recherche des fournisseurs mentionnés
        fournisseurs_matches = re.findall(patterns['fournisseur'], search_content, re.IGNORECASE)

        for fournisseur in set(fournisseurs_matches):
            # Pour chaque fournisseur, essayer d'extraire prix et abonnement
            fournisseur_text = self._extract_text_around_keyword(search_content, fournisseur, 200)

            prix_kwh_match = re.search(patterns['prix_kwh'], fournisseur_text)
            abonnement_match = re.search(patterns['abonnement'], fournisseur_text)

            if prix_kwh_match or abonnement_match:
                offer = {
                    'fournisseur': fournisseur.strip(),
                    'source': 'web_search',
                    'date_extraction': datetime.now().isoformat(),
                    'prix_kwh': prix_kwh_match.group(1) if prix_kwh_match else 'N/A',
                    'abonnement_annuel': abonnement_match.group(1) if abonnement_match else 'N/A'
                }

                # Enrichir avec nom d'offre si trouvé
                offre_match = re.search(patterns['offre_nom'], fournisseur_text, re.IGNORECASE)
                if offre_match:
                    offer['offre_nom'] = offre_match.group(1).strip()

                offers.append(offer)

        return offers

    def _scrape_energy_comparators(self, current_offer: Dict) -> List[Dict]:
        """Scrape les principaux comparateurs énergie français"""

        offers = []

        for comparator_url in self.comparator_urls['energie']:
            try:
                offers_from_site = self._scrape_single_energy_site(comparator_url)
                offers.extend(offers_from_site)

                # Pause respectueuse
                time.sleep(2)

            except Exception as e:
                logger.warning(f"Erreur scraping {comparator_url}: {e}")
                continue

        return offers

    def _scrape_single_energy_site(self, url: str) -> List[Dict]:
        """Scrape un site de comparaison spécifique"""

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br'
            }

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Patterns spécifiques selon le site
            if 'selectra' in url:
                return self._parse_selectra_energy_offers(soup)
            elif 'energie-info' in url:
                return self._parse_energie_info_offers(soup)
            elif 'hellowatt' in url:
                return self._parse_hellowatt_offers(soup)
            else:
                return self._parse_generic_energy_offers(soup)

        except Exception as e:
            logger.warning(f"Erreur scraping {url}: {e}")
            return []

    def _parse_selectra_energy_offers(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse spécifique pour Selectra"""
        offers = []

        # Sélecteurs CSS spécifiques à Selectra (à adapter selon structure réelle)
        offer_elements = soup.select('.offer-card, .tariff-comparison, .provider-offer')

        for element in offer_elements:
            try:
                # Extraire fournisseur
                fournisseur_elem = element.select_one('.provider-name, .supplier-name, h3, h4')
                fournisseur = fournisseur_elem.get_text(strip=True) if fournisseur_elem else 'Inconnu'

                # Extraire prix kWh
                prix_elem = element.select_one('.price-kwh, .unit-price')
                prix_text = prix_elem.get_text(strip=True) if prix_elem else ''
                prix_kwh_match = re.search(r'(\d+[,.]?\d*)', prix_text)
                prix_kwh = prix_kwh_match.group(1) if prix_kwh_match else 'N/A'

                # Extraire abonnement
                abonnement_elem = element.select_one('.subscription-fee, .standing-charge')
                abonnement_text = abonnement_elem.get_text(strip=True) if abonnement_elem else ''
                abonnement_match = re.search(r'(\d+[,.]?\d*)', abonnement_text)
                abonnement = abonnement_match.group(1) if abonnement_match else 'N/A'

                if fournisseur and fournisseur != 'Inconnu':
                    offers.append({
                        'fournisseur': fournisseur,
                        'prix_kwh': prix_kwh,
                        'abonnement_annuel': abonnement,
                        'source': 'selectra.info',
                        'date_extraction': datetime.now().isoformat()
                    })

            except Exception as e:
                logger.warning(f"Erreur parsing offre Selectra: {e}")
                continue

        return offers

    def _get_updated_static_energy_offers(self) -> List[Dict]:
        """Offres énergie statiques mises à jour (solution de secours fiable)"""

        # Ces données doivent être mises à jour régulièrement (mensuellement)
        # via un processus automatisé ou manuel

        return [
            {
                'fournisseur': 'OHM Énergie',
                'offre_nom': 'Essentielle Électricité',
                'prix_kwh': '0.2229',
                'abonnement_annuel': '136.14',
                'type_contrat': 'Marché',
                'avantages': 'Prix très compétitif, -11% vs TRV',
                'source': 'Site officiel OHM Énergie',
                'derniere_maj': '2025-01-15',
                'url_officielle': 'https://ohm-energie.com/offres/electricite'
            },
            {
                'fournisseur': 'TotalEnergies',
                'offre_nom': 'Essentielle Électricité',
                'prix_kwh': '0.2340',
                'abonnement_annuel': '151.20',
                'type_contrat': 'Marché',
                'avantages': 'Prix stable, -7% vs TRV',
                'source': 'Site officiel TotalEnergies',
                'derniere_maj': '2025-01-15'
            },
            {
                'fournisseur': 'EDF',
                'offre_nom': 'Tarif Bleu',
                'prix_kwh': '0.2516',
                'prix_kwh_hp': '0.2700',
                'prix_kwh_hc': '0.2068',
                'abonnement_annuel': '151.20',
                'abonnement_annuel_hphc': '196.56',
                'type_contrat': 'Tarif Réglementé',
                'avantages': 'Tarif réglementé, référence',
                'source': 'CRE - Tarif réglementé',
                'derniere_maj': '2025-01-15'
            },
            {
                'fournisseur': 'Vattenfall',
                'offre_nom': 'Eco Green',
                'prix_kwh': '0.2452',
                'abonnement_annuel': '150.00',
                'type_contrat': 'Marché',
                'avantages': 'Électricité 100% renouvelable',
                'source': 'Site officiel Vattenfall',
                'derniere_maj': '2025-01-15'
            },
            {
                'fournisseur': 'ekWateur',
                'offre_nom': 'Électricité Verte',
                'prix_kwh': '0.2480',
                'abonnement_annuel': '158.00',
                'type_contrat': 'Marché',
                'avantages': 'Énergie verte française',
                'source': 'Site officiel ekWateur',
                'derniere_maj': '2025-01-15'
            }
        ]

    def _deduplicate_and_rank_offers(self, offers: List[Dict], current_offer: Dict) -> List[Dict]:
        """Déduplique les offres et les classe selon vos critères"""

        # 1. Déduplication par fournisseur
        unique_offers = {}
        for offer in offers:
            fournisseur = offer.get('fournisseur', '').strip().lower()
            if fournisseur and fournisseur not in unique_offers:
                unique_offers[fournisseur] = offer

        # 2. Conversion en liste et nettoyage
        cleaned_offers = []
        for offer in unique_offers.values():
            try:
                # Nettoyer et standardiser les prix
                prix_kwh = self._clean_price_value(offer.get('prix_kwh', '0'))
                abonnement = self._clean_price_value(offer.get('abonnement_annuel', '0'))

                if prix_kwh > 0:  # Ne garder que les offres avec prix valides
                    offer['prix_kwh_numeric'] = prix_kwh
                    offer['abonnement_numeric'] = abonnement
                    cleaned_offers.append(offer)

            except Exception as e:
                logger.warning(f"Erreur nettoyage offre: {e}")
                continue

        # 3. Classement selon économies potentielles
        # Estimer consommation moyenne si pas disponible
        estimated_consumption = 5000  # kWh/an moyenne française

        for offer in cleaned_offers:
            annual_cost = (offer['prix_kwh_numeric'] * estimated_consumption) + offer['abonnement_numeric']
            offer['estimated_annual_cost'] = annual_cost

        # Trier du moins cher au plus cher
        cleaned_offers.sort(key=lambda x: x.get('estimated_annual_cost', float('inf')))

        return cleaned_offers

    def _clean_price_value(self, price_str: str) -> float:
        """Nettoie et convertit une valeur de prix en float"""
        if not price_str or price_str == 'N/A':
            return 0.0

        # Nettoyer la chaîne
        cleaned = re.sub(r'[^\d,.]', '', str(price_str))
        cleaned = cleaned.replace(',', '.')

        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _extract_text_around_keyword(self, text: str, keyword: str, context_length: int = 100) -> str:
        """Extrait le contexte autour d'un mot-clé"""

        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        match = pattern.search(text)

        if match:
            start = max(0, match.start() - context_length)
            end = min(len(text), match.end() + context_length)
            return text[start:end]

        return ""

    def _get_cached_offers(self, invoice_type: str) -> List[Dict]:
        """Retourne des offres en cache en cas d'échec de recherche"""

        if invoice_type == 'energie':
            return self._get_updated_static_energy_offers()[:3]  # Top 3 en backup
        else:
            return []

    # Méthodes pour télécom et assurance (structure similaire)
    def _search_telecom_offers(self, current_offer: Dict) -> List[Dict]:
        """Recherche offres télécom - structure similaire à énergie"""
        # Implementation similaire adaptée aux offres internet/mobile
        return self._get_static_telecom_offers()

    def _search_insurance_offers(self, current_offer: Dict) -> List[Dict]:
        """Recherche offres assurance"""
        # Implementation pour assurances
        return []

    def _get_static_telecom_offers(self) -> List[Dict]:
        """Offres télécom statiques fiables"""
        return [
            {
                'fournisseur': 'Free',
                'offre_nom': 'Freebox Pop',
                'prix_mensuel': 29.99,
                'prix_annuel': 359.88,
                'avantages': 'Sans engagement, TV incluse',
                'source': 'Site officiel Free'
            },
            {
                'fournisseur': 'RED by SFR',
                'offre_nom': 'RED Box Fiber',
                'prix_mensuel': 24.00,
                'prix_annuel': 288.00,
                'avantages': 'Prix vie, sans engagement',
                'source': 'Site officiel RED'
            }
        ]


class OfferDataCache:
    """Cache local pour les données d'offres avec expiration"""

    def __init__(self, cache_duration_hours: int = 24):
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.cache = {}

    def get_cached_offers(self, cache_key: str) -> Optional[List[Dict]]:
        """Récupère les offres du cache si valides"""

        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_duration:
                return cached_data['offers']

        return None

    def cache_offers(self, cache_key: str, offers: List[Dict]):
        """Met en cache les offres"""

        self.cache[cache_key] = {
            'offers': offers,
            'timestamp': datetime.now()
        }