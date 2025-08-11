import os
import re
import json
import logging
from typing import List, Dict, Tuple, Any
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm, mm
from reportlab.lib.colors import HexColor, Color, black, white
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate
from reportlab.platypus.frames import Frame

from config import Config
from integration_donnees_reelles import RealDataProvider

logger = logging.getLogger(__name__)


class EnhancedPDFGenerator:
    """Générateur PDF professionnel avec formatage avancé"""

    def __init__(self):
        # Palette de couleurs professionnelle (exacte des exemples)
        self.colors = {
            'title_black': HexColor('#000000'),
            'section_blue': HexColor('#4472C4'),
            'table_header_blue': HexColor('#D9E2F3'),
            'table_border': HexColor('#8EAADB'),
            'recommendation_red': HexColor('#C5504B'),
            'text_black': HexColor('#000000'),
            'text_gray': HexColor('#595959'),
            'light_gray': HexColor('#F2F2F2'),
            'bullet_blue': HexColor('#4472C4'),
            'methodology_black': HexColor('#000000')
        }

        # Configuration des polices
        self._setup_enhanced_fonts()

        # Intégration des données réelles
        self.data_provider = RealDataProvider()

    def _setup_enhanced_fonts(self):
        """Configuration des polices optimisées"""
        try:
            # Essayer plusieurs polices système de qualité
            font_candidates = [
                # Windows
                ('Arial', 'C:/Windows/Fonts/arial.ttf'),
                ('ArialBold', 'C:/Windows/Fonts/arialbd.ttf'),
                ('ArialItalic', 'C:/Windows/Fonts/ariali.ttf'),
                ('Calibri', 'C:/Windows/Fonts/calibri.ttf'),
                ('CalibriBold', 'C:/Windows/Fonts/calibrib.ttf'),

                # macOS
                ('Arial', '/System/Library/Fonts/Arial.ttf'),
                ('ArialBold', '/System/Library/Fonts/Arial Bold.ttf'),
                ('Helvetica', '/System/Library/Fonts/Helvetica.ttc'),

                # Linux
                ('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                ('DejaVuBold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
                ('Liberation', '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'),

                # Fonts locales du projet
                ('CustomRegular', os.path.join(os.path.dirname(__file__), 'fonts', 'Arial.ttf')),
                ('CustomBold', os.path.join(os.path.dirname(__file__), 'fonts', 'Arial-Bold.ttf')),
            ]

            self.fonts = {
                'regular': 'Helvetica',
                'bold': 'Helvetica-Bold',
                'italic': 'Helvetica-Oblique'
            }

            # Enregistrer les polices disponibles
            for font_name, font_path in font_candidates:
                if os.path.exists(font_path):
                    try:
                        pdfmetrics.registerFont(TTFont(font_name, font_path))
                        if 'Bold' in font_name or 'bold' in font_name.lower():
                            self.fonts['bold'] = font_name
                        elif 'Italic' in font_name or 'italic' in font_name.lower():
                            self.fonts['italic'] = font_name
                        else:
                            self.fonts['regular'] = font_name
                        logger.info(f"Police chargée: {font_name}")
                    except Exception as e:
                        logger.warning(f"Impossible de charger {font_name}: {e}")

        except Exception as e:
            logger.warning(f"Erreur configuration polices: {e}")
            # Fallback vers polices par défaut
            self.fonts = {
                'regular': 'Helvetica',
                'bold': 'Helvetica-Bold',
                'italic': 'Helvetica-Oblique'
            }

    def generate_reports(self, structured_data: Dict, user_id: int) -> Tuple[str, str]:
        """Génère les rapports avec données réelles"""
        Config.create_folders()

        # Enrichir les données avec des vraies offres du marché
        enhanced_data = self._enrich_with_real_data(structured_data)

        # Générer les noms de fichiers
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        internal_filename = f"rapport_internal_{user_id}_{timestamp}.pdf"
        user_filename = f"rapport_user_{user_id}_{timestamp}.pdf"

        internal_path = os.path.join(Config.REPORTS_INTERNAL_FOLDER, internal_filename)
        user_path = os.path.join(Config.REPORTS_FOLDER, user_filename)

        # Créer les rapports
        self._create_enhanced_pdf(enhanced_data, internal_path, anonymize_suppliers=False)
        self._create_enhanced_pdf(enhanced_data, user_path, anonymize_suppliers=True)

        logger.info(f"Rapports professionnels générés: {internal_path}, {user_path}")
        return internal_path, user_path

    def _enrich_with_real_data(self, structured_data: Dict) -> Dict:
        """Enrichit les données avec des vraies offres du marché"""
        enhanced_data = structured_data.copy()

        facture_type = enhanced_data.get('type_facture', '').lower()
        current_offer = enhanced_data.get('current_offer', {})

        try:
            if 'electricite' in facture_type or 'électricité' in facture_type:
                consumption = self._extract_consumption(current_offer.get('consommation_annuelle', ''))
                if consumption:
                    real_offers = self.data_provider.get_real_electricity_offers(consumption)
                    enhanced_data['alternatives'] = real_offers

            elif 'gaz' in facture_type:
                consumption = self._extract_consumption(current_offer.get('consommation_annuelle', ''))
                if consumption:
                    real_offers = self.data_provider.get_real_gas_offers(consumption)
                    enhanced_data['alternatives'] = real_offers

            elif 'internet' in facture_type:
                current_monthly = self._extract_monthly_price(current_offer.get('montant_total_annuel', ''))
                real_offers = self.data_provider.get_real_internet_offers(current_monthly)
                enhanced_data['alternatives'] = real_offers

        except Exception as e:
            logger.warning(f"Impossible d'enrichir avec données réelles: {e}")
            # Garder les données générées par l'IA en fallback

        return enhanced_data

    def _extract_consumption(self, consumption_str: str) -> int:
        """Extrait la consommation numérique d'une chaîne"""
        if not consumption_str:
            return 0
        match = re.search(r'(\d+)', str(consumption_str))
        return int(match.group(1)) if match else 0

    def _extract_monthly_price(self, annual_str: str) -> float:
        """Extrait le prix mensuel d'un montant annuel"""
        if not annual_str:
            return 0
        match = re.search(r'(\d+[.,]?\d*)', str(annual_str))
        if match:
            annual = float(match.group(1).replace(',', '.'))
            return annual / 12
        return 0

    def _create_enhanced_pdf(self, data: Dict, output_path: str, anonymize_suppliers: bool = False):
        """Crée un PDF avec formatage professionnel amélioré"""
        try:
            # Configuration du document avec marges optimisées
            doc = SimpleDocTemplate(
                output_path,
                pagesize=A4,
                rightMargin=25 * mm,
                leftMargin=25 * mm,
                topMargin=20 * mm,
                bottomMargin=25 * mm
            )

            # Construire le contenu
            story = []
            styles = self._get_enhanced_styles()

            # Type de document
            doc_type = data.get('type_facture', 'énergie').upper()

            # TITRE PRINCIPAL - Taille et formatage optimisés
            title = f"Rapport comparatif énergie – {doc_type}"
            story.append(Paragraph(title, styles['main_title']))
            story.append(Spacer(1, 8 * mm))

            # INFORMATIONS CLIENT ET DATE
            client_name = data.get('client_info', {}).get('nom', '[anonymisé]')
            if anonymize_suppliers:
                client_name = '[anonymisé]'

            story.append(Paragraph(f"Client : {client_name}", styles['client_info']))
            story.append(Paragraph(f"Date : {datetime.now().strftime('%B %Y')}", styles['client_info']))
            story.append(Spacer(1, 12 * mm))

            # SECTION OFFRE ACTUELLE
            self._add_enhanced_current_offer(story, data, styles, anonymize_suppliers)

            # TABLEAU COMPARATIF
            self._add_enhanced_comparison_table(story, data, styles, anonymize_suppliers)

            # SECTION PIÈGES DÉTECTÉS
            self._add_enhanced_issues_section(story, data, styles)

            # SECTION RECOMMANDATION
            self._add_enhanced_recommendation(story, data, styles, anonymize_suppliers)

            # SECTION MÉTHODOLOGIE
            self._add_enhanced_methodology(story, styles)

            # Générer le PDF
            doc.build(story)
            logger.info(f"PDF professionnel créé: {output_path}")

        except Exception as e:
            logger.error(f"Erreur création PDF {output_path}: {str(e)}")
            raise Exception(f"Erreur génération PDF professionnel: {str(e)}")

    def _get_enhanced_styles(self) -> Dict:
        """Styles optimisés pour un rendu professionnel"""

        return {
            'main_title': ParagraphStyle(
                'MainTitle',
                fontName=self.fonts['bold'],
                fontSize=16,
                textColor=self.colors['title_black'],
                alignment=TA_LEFT,
                spaceAfter=8 * mm,
                spaceBefore=0,
                leading=20  # Espacement des lignes
            ),
            'section_title': ParagraphStyle(
                'SectionTitle',
                fontName=self.fonts['regular'],
                fontSize=12,
                textColor=self.colors['section_blue'],
                spaceAfter=6 * mm,
                spaceBefore=10 * mm,
                leftIndent=0,
                leading=16,
                bulletText='■',
                bulletIndent=0,
                # leftIndent=15 * mm,
                bulletFontName=self.fonts['regular'],
                bulletFontSize=12,
                bulletColor=self.colors['bullet_blue']
            ),
            'client_info': ParagraphStyle(
                'ClientInfo',
                fontName=self.fonts['regular'],
                fontSize=11,
                textColor=self.colors['text_black'],
                spaceAfter=3 * mm,
                leading=14
            ),
            'offer_details': ParagraphStyle(
                'OfferDetails',
                fontName=self.fonts['regular'],
                fontSize=11,
                textColor=self.colors['text_black'],
                spaceAfter=2 * mm,
                leftIndent=5 * mm,
                leading=14
            ),
            'issues_list': ParagraphStyle(
                'IssuesList',
                fontName=self.fonts['regular'],
                fontSize=11,
                textColor=self.colors['text_black'],
                spaceAfter=3 * mm,
                leftIndent=8 * mm,
                leading=14,
                bulletText='-',
                bulletIndent=3 * mm,
                bulletFontName=self.fonts['regular']
            ),
            'recommendation': ParagraphStyle(
                'Recommendation',
                fontName=self.fonts['bold'],
                fontSize=12,
                textColor=self.colors['recommendation_red'],
                spaceAfter=6 * mm,
                spaceBefore=4 * mm,
                leading=16
            ),
            'methodology': ParagraphStyle(
                'Methodology',
                fontName=self.fonts['regular'],
                fontSize=10,
                textColor=self.colors['methodology_black'],
                spaceAfter=3 * mm,
                alignment=TA_JUSTIFY,
                leading=13
            ),
            'methodology_highlight': ParagraphStyle(
                'MethodologyHighlight',
                fontName=self.fonts['bold'],
                fontSize=10,
                textColor=self.colors['methodology_black'],
                spaceAfter=3 * mm,
                leading=13
            )
        }

    def _add_enhanced_current_offer(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Section offre actuelle avec formatage amélioré"""
        current_offer = data.get('current_offer', {})
        doc_type = data.get('type_facture', 'énergie')

        # Titre de section avec puce bleue
        fournisseur = current_offer.get('fournisseur', 'Non spécifié')
        if anonymize:
            fournisseur = 'Fournisseur Actuel'

        title = f"■ Offre actuelle {doc_type} – {fournisseur}"
        story.append(Paragraph(title, styles['section_title']))

        # Détails organisés
        details = []
        if current_offer.get('offre_nom'):
            details.append(f"Offre : {current_offer['offre_nom']}")
        if current_offer.get('puissance_souscrite'):
            details.append(f"Puissance souscrite : {current_offer['puissance_souscrite']}")
        if current_offer.get('consommation_annuelle'):
            details.append(f"Consommation annuelle estimée : {current_offer['consommation_annuelle']}")
        if current_offer.get('montant_total_annuel'):
            details.append(f"Montant total payé sur l'année : {current_offer['montant_total_annuel']} TTC")
        if current_offer.get('prix_moyen_kwh'):
            details.append(f"Prix moyen observé : {current_offer['prix_moyen_kwh']} TTC")

        for detail in details:
            story.append(Paragraph(detail, styles['offer_details']))

        story.append(Spacer(1, 10 * mm))

    def _add_enhanced_comparison_table(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Tableau comparatif avec style professionnel amélioré"""
        alternatives = data.get('alternatives', [])
        if not alternatives:
            return

        doc_type = data.get('type_facture', 'énergie')

        # Titre de section
        consumption = data.get('current_offer', {}).get('consommation_annuelle', '')
        title = f"■ Comparatif – Offres {doc_type.title()}"
        if consumption and consumption != 'Non applicable':
            title += f" ({consumption})"
        story.append(Paragraph(title, styles['section_title']))

        # Préparer les données du tableau
        if doc_type.lower() == 'internet':
            headers = ['Fournisseur', 'Prix kWh', 'Abonnement', 'Total annuel TTC']
        else:
            headers = ['Fournisseur', 'Prix kWh', 'Abonnement', 'Total annuel TTC']

        table_data = [headers]

        # Ajouter les données avec anonymisation si nécessaire
        for i, alt in enumerate(alternatives):
            if anonymize:
                fournisseur = f"Fournisseur {i + 1}"
            else:
                fournisseur = alt.get('fournisseur', f'Fournisseur {i + 1}')

            if doc_type.lower() == 'internet':
                row = [
                    fournisseur,
                    'Non applicable',  # Pas de kWh pour internet
                    alt.get('abonnement', alt.get('prix_mensuel', '')),
                    alt.get('total_annuel', '')
                ]
            else:
                row = [
                    fournisseur,
                    alt.get('prix_kwh', ''),
                    alt.get('abonnement', ''),
                    alt.get('total_annuel', '')
                ]
            table_data.append(row)

        # Créer le tableau avec dimensions optimales
        col_widths = [50 * mm, 30 * mm, 35 * mm, 35 * mm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Style du tableau amélioré
        table.setStyle(TableStyle([
            # En-tête - Style professionnel
            ('BACKGROUND', (0, 0), (-1, 0), self.colors['table_header_blue']),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.colors['section_blue']),
            ('FONTNAME', (0, 0), (-1, 0), self.fonts['bold']),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            # Données - Style clean
            ('BACKGROUND', (0, 1), (-1, -1), white),
            ('TEXTCOLOR', (0, 1), (-1, -1), self.colors['text_black']),
            ('FONTNAME', (0, 1), (-1, -1), self.fonts['regular']),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),  # Centrer les chiffres
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),  # Aligner les noms à gauche

            # Bordures et grilles
            ('GRID', (0, 0), (-1, -1), 0.75, self.colors['table_border']),
            ('LINEBELOW', (0, 0), (-1, 0), 2, self.colors['section_blue']),

            # Padding optimal
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),

            # Alternance de couleurs pour lisibilité
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, self.colors['light_gray']]),
        ]))

        story.append(table)
        story.append(Spacer(1, 12 * mm))

    def _add_enhanced_issues_section(self, story: List, data: Dict, styles: Dict):
        """Section pièges détectés avec mise en forme améliorée"""
        issues = data.get('detected_issues', [])
        if not issues:
            return

        # Titre de section
        story.append(Paragraph("■ Pièges détectés dans l'offre actuelle", styles['section_title']))

        # Liste des problèmes avec puces
        for issue in issues:
            story.append(Paragraph(f"- {issue}", styles['issues_list']))

        story.append(Spacer(1, 10 * mm))

    def _add_enhanced_recommendation(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Recommandation mise en évidence"""
        best_savings = data.get('best_savings', {})
        if not best_savings:
            return

        # Titre de section
        story.append(Paragraph("■ Notre recommandation", styles['section_title']))

        # Texte de recommandation en rouge et gras
        fournisseur = best_savings.get('fournisseur_recommande', '')
        if anonymize and fournisseur:
            fournisseur = 'le fournisseur recommandé'

        economie = best_savings.get('economie_annuelle', '')
        consumption = data.get('current_offer', {}).get('consommation_annuelle', '')

        if fournisseur and economie:
            text = f"En changeant pour {fournisseur}, vous pourriez économiser jusqu'à {economie} TTC/an"

            if consumption and consumption != 'Non applicable':
                text += f" à consommation constante ({consumption})."
            else:
                text += "."

            story.append(Paragraph(text, styles['recommendation']))

        story.append(Spacer(1, 10 * mm))

    def _add_enhanced_methodology(self, story: List, styles: Dict):
        """Section méthodologie avec formatage professionnel"""
        # Titre de section
        story.append(Paragraph("■ Méthodologie & Fiabilité des données", styles['section_title']))

        # Textes méthodologie
        methodology_texts = [
            "Les données de ce rapport proviennent de votre facture, d'offres publiques à jour, et de références officielles (TRV, CRE, barèmes).",
            "Les comparaisons sont faites à partir de sources vérifiables (sites fournisseurs, simulateurs certifiés).",
        ]

        for text in methodology_texts:
            story.append(Paragraph(text, styles['methodology']))

        # Mention finale en gras
        final_text = "■ Rapport indépendant, sans publicité ni affiliation. Son seul but : identifier vos économies possibles."
        story.append(Paragraph(final_text, styles['methodology_highlight']))

        story.append(Spacer(1, 6 * mm))

    def generate_popup_summary(self, data: Dict) -> str:
        """Génère le résumé pour la popup avec données enrichies"""
        issues = data.get('detected_issues', [])
        best_savings = data.get('best_savings', {})

        summary_parts = []

        # Économies
        economie = best_savings.get('economie_annuelle', '')
        if economie:
            summary_parts.append(f"💸 Vous pourriez optimiser jusqu'à {economie}/an sur votre facture !")

        # Problèmes clés (max 3)
        if issues:
            summary_parts.append("🔍 Problèmes détectés :")
            for issue in issues[:3]:
                summary_parts.append(f"• {issue}")

        # Recommandation
        if best_savings:
            summary_parts.append("💡 Changement recommandé pour réaliser ces économies.")

        # Source des données
        summary_parts.append("📊 Basé sur des données réelles du marché français 2025.")

        return "\n\n".join(summary_parts)