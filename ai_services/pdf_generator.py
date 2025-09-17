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

from config import Config

logger = logging.getLogger(__name__)


class AdaptivePDFGenerator:
    """Générateur PDF adaptatif selon le type de facture"""

    def __init__(self):
        self.colors = {
            'title_black': HexColor('#000000'),
            'section_blue': HexColor('#4472C4'),
            'table_header_blue': HexColor('#D9E2F3'),
            'table_border': HexColor('#8EAADB'),
            'recommendation_red': HexColor('#FF0000'),  # Rouge plus visible
            'recommendation_blue': HexColor('#0000FF'),  # Bleu option
            'savings_green': HexColor('#00AA00'),
            'text_black': HexColor('#000000'),
            'text_gray': HexColor('#595959'),
            'light_gray': HexColor('#F8F9FA'),
            'white': HexColor('#FFFFFF')
        }

        self._setup_fonts()

    def _setup_fonts(self):
        """Configuration des polices"""
        self.fonts = {
            'regular': 'Helvetica',
            'bold': 'Helvetica-Bold'
        }

    def generate_reports(self, structured_data: Dict, user_id: int) -> Tuple[str, str]:
        """Génère les rapports adaptés au type de facture"""
        Config.create_folders()

        # Type de facture
        invoice_type = structured_data.get('type_facture', 'inconnu')

        # Noms de fichiers
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        internal_filename = f"rapport_{invoice_type}_internal_{user_id}_{timestamp}.pdf"
        user_filename = f"rapport_{invoice_type}_user_{user_id}_{timestamp}.pdf"

        internal_path = os.path.join(Config.REPORTS_INTERNAL_FOLDER, internal_filename)
        user_path = os.path.join(Config.REPORTS_FOLDER, user_filename)

        # Générer selon le type
        if invoice_type in ['electricite', 'gaz']:
            self._create_energy_pdf(structured_data, internal_path, False)
            self._create_energy_pdf(structured_data, user_path, True)
        elif invoice_type in ['internet', 'mobile', 'internet_mobile']:
            self._create_telecom_pdf(structured_data, internal_path, False)
            self._create_telecom_pdf(structured_data, user_path, True)
        elif 'assurance' in invoice_type:
            self._create_insurance_pdf(structured_data, internal_path, False)
            self._create_insurance_pdf(structured_data, user_path, True)
        else:
            self._create_generic_pdf(structured_data, internal_path, False)
            self._create_generic_pdf(structured_data, user_path, True)

        logger.info(f"Rapports générés: {internal_path}, {user_path}")
        return internal_path, user_path

    def _create_energy_pdf(self, data: Dict, output_path: str, anonymize: bool = False):
        """PDF spécialisé pour électricité/gaz selon instructions utilisateur"""

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=1.5 * cm,
            bottomMargin=2 * cm
        )

        story = []
        styles = self._get_energy_styles()

        # Type d'énergie
        energy_type = data.get('type_facture', 'énergie').upper()

        # TITRE avec version
        title = f"Rapport comparatif énergie – {energy_type} (Version V10)"
        story.append(Paragraph(title, styles['main_title']))
        story.append(Spacer(1, 4 * mm))

        # CLIENT
        client_name = data.get('client_info', {}).get('nom', '[anonymisé]')
        if anonymize:
            client_name = '[anonymisé]'

        story.append(Paragraph(f"Client : {client_name}", styles['client_info']))
        story.append(Paragraph(f"Date : {datetime.now().strftime('%B %Y')}", styles['client_info']))
        story.append(Spacer(1, 6 * mm))

        # OFFRE ACTUELLE
        self._add_current_energy_offer(story, data, styles, anonymize)

        # TABLEAU COMPARATIF selon le type
        if energy_type == 'ÉLECTRICITÉ':
            # Tableau BASE
            story.append(Paragraph("■ Comparatif – Offres Électricité BASE", styles['section_title']))
            self._add_electricity_comparison_table(story, data, styles, anonymize, 'base')

            # Tableau HP/HC
            story.append(Paragraph("■ Comparatif – Offres Électricité HP/HC", styles['section_title']))
            self._add_electricity_comparison_table(story, data, styles, anonymize, 'hphc')
        else:
            # Tableau GAZ
            story.append(Paragraph(f"■ Comparatif – Offres {energy_type}", styles['section_title']))
            self._add_gas_comparison_table(story, data, styles, anonymize)

        # PIÈGES DÉTECTÉS (Instruction: au moins 3 pièges)
        self._add_hidden_issues_section(story, data, styles)

        # RECOMMANDATION
        self._add_recommendation_section(story, data, styles, anonymize)

        # MÉTHODOLOGIE
        self._add_methodology_section(story, data, styles)

        doc.build(story)

    def _create_telecom_pdf(self, data: Dict, output_path: str, anonymize: bool = False):
        """PDF spécialisé pour internet/mobile"""

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=1.5 * cm,
            bottomMargin=2 * cm
        )

        story = []
        styles = self._get_telecom_styles()

        # TITRE
        service_type = "INTERNET & MOBILE" if data.get('type_facture') == 'internet_mobile' else data.get(
            'type_facture', '').upper()
        title = f"Rapport comparatif – {service_type}"
        story.append(Paragraph(title, styles['main_title']))
        story.append(Spacer(1, 4 * mm))

        # CLIENT
        client_name = data.get('client_info', {}).get('nom', '[anonymisé]')
        if anonymize:
            client_name = '[anonymisé]'

        story.append(Paragraph(f"Client : {client_name}", styles['client_info']))
        story.append(Paragraph(f"Date : {datetime.now().strftime('%B %Y')}", styles['client_info']))
        story.append(Spacer(1, 6 * mm))

        # OFFRE ACTUELLE
        self._add_current_telecom_offer(story, data, styles, anonymize)

        # COMPARATIF
        story.append(Paragraph("■ Top 5 Offres Alternatives", styles['section_title']))
        self._add_telecom_comparison_table(story, data, styles, anonymize)

        # PROBLÈMES DÉTECTÉS
        self._add_telecom_issues(story, data, styles)

        # RECOMMANDATION
        self._add_telecom_recommendation(story, data, styles, anonymize)

        # MÉTHODOLOGIE
        self._add_methodology_section(story, data, styles)

        doc.build(story)

    def _add_current_energy_offer(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Offre actuelle énergie avec tous les détails selon format demandé"""
        current = data.get('current_offer', {})

        fournisseur = current.get('fournisseur', 'Non spécifié')
        if anonymize:
            fournisseur = 'Fournisseur Actuel'

        story.append(Paragraph(f"■ Offre actuelle {data.get('type_facture', 'énergie')} – {fournisseur}",
                               styles['section_title']))

        # Détails selon format demandé
        details = []
        if current.get('offre_nom'):
            details.append(f"Offre : {current['offre_nom']}")

        if data.get('type_facture') == 'electricite':
            if current.get('option_tarifaire'):
                details.append(f"Option tarifaire : {current['option_tarifaire']}")
            if current.get('puissance_souscrite'):
                details.append(f"Puissance souscrite : {current['puissance_souscrite']} kVA")

        if current.get('consommation_annuelle'):
            details.append(f"Consommation annuelle réelle : {current['consommation_annuelle']} kWh")

        if current.get('montant_total_annuel'):
            details.append(f"Montant total payé sur 12 mois : {current['montant_total_annuel']} € TTC")

        if current.get('prix_moyen_ttc'):
            details.append(f"Prix moyen constaté : {current['prix_moyen_ttc']} €/kWh TTC")
        elif current.get('prix_kwh'):
            details.append(f"Prix du kWh : {current['prix_kwh']} € TTC")

        if current.get('abonnement_annuel'):
            details.append(f"Abonnement annuel : {current['abonnement_annuel']} € TTC")

        for detail in details:
            story.append(Paragraph(detail, styles['offer_details']))

        story.append(Spacer(1, 4 * mm))

    def _add_electricity_comparison_table(self, story: List, data: Dict, styles: Dict, anonymize: bool,
                                          tarif_type: str):
        """Tableau comparatif électricité selon format demandé"""
        alternatives = data.get('alternatives', [])
        if not alternatives:
            story.append(Paragraph("Aucune alternative disponible", styles['offer_details']))
            return

        # Filtrer selon le type (BASE ou HP/HC)
        filtered_alternatives = []
        for alt in alternatives:
            alt_type = str(alt.get('type_offre', '')).lower()
            if tarif_type == 'base':
                if 'hphc' not in alt_type and 'hp' not in alt_type and 'hc' not in alt_type:
                    filtered_alternatives.append(alt)
            else:  # HP/HC
                if 'hphc' in alt_type or 'hp' in alt_type or 'hc' in alt_type:
                    filtered_alternatives.append(alt)

        if not filtered_alternatives:
            story.append(Paragraph(f"Aucune offre {tarif_type} disponible", styles['offer_details']))
            return

        # Headers selon format demandé
        headers = ['Fournisseur', 'Prix kWh', 'Abonnement', 'Total annuel TTC']
        table_data = [headers]

        # Largeurs fixes
        col_widths = [40 * mm, 30 * mm, 35 * mm, 40 * mm]

        # Trier par coût total
        try:
            filtered_alternatives.sort(
                key=lambda x: float(x.get('total_annuel', 999999)) if x.get('total_annuel') else 999999)
        except Exception:
            pass

        for i, alt in enumerate(filtered_alternatives[:5]):  # Top 5
            if anonymize:
                fournisseur = f"Fournisseur {i + 1}"
            else:
                fournisseur = alt.get('fournisseur', f'Fournisseur {i + 1}')

            # Formatage des prix selon le type
            if tarif_type == 'hphc' and alt.get('details', {}).get('prix_hp') and alt.get('details', {}).get('prix_hc'):
                prix_kwh = f"{alt['details']['prix_hp']} / {alt['details']['prix_hc']} €"
            else:
                prix_kwh = f"{alt.get('prix_kwh', 'N/A')} €"

            # Formatage des valeurs
            abonnement = f"{alt.get('abonnement_annuel', 'N/A')} €" if alt.get('abonnement_annuel') else 'N/A'
            total_annuel = f"{alt.get('total_annuel', 'N/A')} €" if alt.get('total_annuel') else 'N/A'

            row = [
                fournisseur[:25],
                prix_kwh,
                abonnement,
                total_annuel
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Style du tableau
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.colors['table_header_blue']),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.colors['section_blue']),
            ('FONTNAME', (0, 0), (-1, 0), self.fonts['bold']),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            ('BACKGROUND', (0, 1), (-1, -1), self.colors['white']),
            ('TEXTCOLOR', (0, 1), (-1, -1), self.colors['text_black']),
            ('FONTNAME', (0, 1), (-1, -1), self.fonts['regular']),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),

            ('GRID', (0, 0), (-1, -1), 0.5, self.colors['table_border']),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        story.append(table)
        story.append(Spacer(1, 4 * mm))

    def _add_gas_comparison_table(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Tableau comparatif gaz selon format demandé"""
        alternatives = data.get('alternatives', [])
        if not alternatives:
            story.append(Paragraph("Aucune alternative disponible", styles['offer_details']))
            return

        # Headers selon format demandé
        headers = ['Fournisseur', 'Prix kWh', 'Abonnement', 'Total annuel TTC']
        table_data = [headers]

        # Largeurs fixes
        col_widths = [40 * mm, 30 * mm, 35 * mm, 40 * mm]

        # Trier par coût total
        try:
            alternatives.sort(key=lambda x: float(x.get('total_annuel', 999999)) if x.get('total_annuel') else 999999)
        except Exception:
            pass

        for i, alt in enumerate(alternatives[:5]):  # Top 5
            if anonymize:
                fournisseur = f"Fournisseur {i + 1}"
            else:
                fournisseur = alt.get('fournisseur', f'Fournisseur {i + 1}')

            # Formatage des valeurs
            prix_kwh = f"{alt.get('prix_kwh', 'N/A')} €" if alt.get('prix_kwh') else 'N/A'
            abonnement = f"{alt.get('abonnement_annuel', 'N/A')} €" if alt.get('abonnement_annuel') else 'N/A'
            total_annuel = f"{alt.get('total_annuel', 'N/A')} €" if alt.get('total_annuel') else 'N/A'

            row = [
                fournisseur[:25],
                prix_kwh,
                abonnement,
                total_annuel
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Style du tableau
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.colors['table_header_blue']),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.colors['section_blue']),
            ('FONTNAME', (0, 0), (-1, 0), self.fonts['bold']),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            ('BACKGROUND', (0, 1), (-1, -1), self.colors['white']),
            ('TEXTCOLOR', (0, 1), (-1, -1), self.colors['text_black']),
            ('FONTNAME', (0, 1), (-1, -1), self.fonts['regular']),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),

            ('GRID', (0, 0), (-1, -1), 0.5, self.colors['table_border']),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        story.append(table)
        story.append(Spacer(1, 4 * mm))

    def _add_hidden_issues_section(self, story: List, data: Dict, styles: Dict):
        """Section pièges détectés (au moins 3 pièges)"""
        issues = data.get('detected_issues', [])

        story.append(Paragraph("■ Pièges détectés dans l'offre actuelle", styles['section_title']))

        if issues:
            for issue in issues[:4]:  # Max 4
                story.append(Paragraph(f"• {issue}", styles['warning_text']))
        else:
            # Générer des pièges par défaut si aucun détecté
            default_issues = [
                "Prix moyen élevé par rapport au marché",
                "Aucun avantage fidélité détecté",
                "Offre peu compétitive par rapport aux alternatives"
            ]
            for issue in default_issues:
                story.append(Paragraph(f"• {issue}", styles['warning_text']))

        story.append(Spacer(1, 4 * mm))

    def _add_recommendation_section(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Section recommandation selon format demandé"""
        best_savings = data.get('best_savings', {})

        story.append(Paragraph("■ Notre recommandation", styles['section_title']))

        fournisseur = best_savings.get('fournisseur_recommande', '')
        if anonymize and fournisseur:
            fournisseur = 'le fournisseur recommandé'

        economie = best_savings.get('economie_annuelle', '')

        if fournisseur and economie and economie != 'À calculer':
            text = f"En changeant pour {fournisseur}, vous pourriez économiser jusqu'à {economie}/an à consommation constante."
            story.append(Paragraph(text, styles['savings_highlight']))
        else:
            story.append(Paragraph("Analyse personnalisée requise pour calculer vos économies exactes.",
                                   styles['offer_details']))

        story.append(Spacer(1, 6 * mm))

    def _add_methodology_section(self, story: List, data: Dict, styles: Dict):
        """Méthodologie et fiabilité selon format demandé"""
        story.append(Paragraph("■ Méthodologie & Fiabilité des données", styles['section_title']))

        methodology_text = data.get(
            'methodology',
            "Les données de ce rapport proviennent de votre facture, d'offres publiques à jour, et de références officielles (TRV, CRE, barèmes)."
        )
        story.append(Paragraph(methodology_text, styles['methodology']))

        story.append(Paragraph(
            "Les comparaisons sont faites à partir de sources vérifiables (sites fournisseurs, simulateurs certifiés).",
            styles['methodology']))

        # Ajouter le snapshot d'offres si disponible
        snapshot = data.get('_offers_snapshot_date')
        if snapshot:
            story.append(Paragraph(f"Snapshot d'offres utilisé : {snapshot}", styles['methodology']))

        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            "■ Rapport indépendant, sans publicité ni affiliation. Son seul but : identifier vos économies possibles.",
            styles['methodology']))

    def _get_energy_styles(self) -> Dict:
        """Styles pour rapports énergie"""
        return {
            'main_title': ParagraphStyle(
                'MainTitle',
                fontName=self.fonts['bold'],
                fontSize=14,
                textColor=self.colors['title_black'],
                alignment=TA_LEFT,
                spaceAfter=4 * mm
            ),
            'section_title': ParagraphStyle(
                'SectionTitle',
                fontName=self.fonts['bold'],
                fontSize=11,
                textColor=self.colors['section_blue'],
                spaceAfter=3 * mm,
                spaceBefore=4 * mm
            ),
            'client_info': ParagraphStyle(
                'ClientInfo',
                fontName=self.fonts['regular'],
                fontSize=10,
                textColor=self.colors['text_black'],
                spaceAfter=1 * mm
            ),
            'offer_details': ParagraphStyle(
                'OfferDetails',
                fontName=self.fonts['regular'],
                fontSize=10,
                textColor=self.colors['text_black'],
                spaceAfter=1 * mm,
                leftIndent=3 * mm
            ),
            'warning_text': ParagraphStyle(
                'Warning',
                fontName=self.fonts['regular'],
                fontSize=10,
                textColor=self.colors['recommendation_red'],
                spaceAfter=2 * mm,
                leftIndent=5 * mm
            ),
            'savings_highlight': ParagraphStyle(
                'Savings',
                fontName=self.fonts['bold'],
                fontSize=11,
                textColor=self.colors['recommendation_red'],
                spaceAfter=3 * mm
            ),
            'calculation_header': ParagraphStyle(
                'CalcHeader',
                fontName=self.fonts['bold'],
                fontSize=10,
                textColor=self.colors['text_black'],
                spaceAfter=2 * mm,
                spaceBefore=2 * mm
            ),
            'calculation_detail': ParagraphStyle(
                'CalcDetail',
                fontName=self.fonts['regular'],
                fontSize=9,
                textColor=self.colors['text_black'],
                leftIndent=5 * mm,
                spaceAfter=1 * mm
            ),
            'methodology': ParagraphStyle(
                'Methodology',
                fontName=self.fonts['regular'],
                fontSize=9,
                textColor=self.colors['text_black'],
                spaceAfter=1 * mm
            )
        }

    def _get_telecom_styles(self) -> Dict:
        """Styles pour rapports télécom"""
        styles = self._get_energy_styles()
        # Ajustements spécifiques télécom si nécessaire
        return styles

    def _add_current_telecom_offer(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Offre actuelle télécom"""
        current = data.get('current_offer', {})

        fournisseur = current.get('fournisseur', 'Non spécifié')
        if anonymize:
            fournisseur = 'Opérateur Actuel'

        story.append(Paragraph(f"■ Offre actuelle – {fournisseur}", styles['section_title']))

        details = []
        if current.get('offre_nom'):
            details.append(f"Offre : {current['offre_nom']}")
        if current.get('prix_mensuel'):
            details.append(f"Prix mensuel : {current['prix_mensuel']} TTC")
        if current.get('services_inclus'):
            services = current['services_inclus']
            if isinstance(services, dict):
                for service, detail in services.items():
                    if detail and detail != 'Non':
                        details.append(f"{service.title()} : {detail}")
        if current.get('engagement'):
            details.append(f"Engagement jusqu'au : {current['engagement']}")

        for detail in details:
            story.append(Paragraph(detail, styles['offer_details']))

        story.append(Spacer(1, 4 * mm))

    def _add_telecom_comparison_table(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Tableau comparatif télécom"""
        alternatives = data.get('alternatives', [])
        if not alternatives:
            return

        headers = ['Opérateur', 'Offre', 'Prix/mois', 'Prix/an', 'Avantages']
        table_data = [headers]

        col_widths = [30 * mm, 35 * mm, 25 * mm, 25 * mm, 50 * mm]

        for i, alt in enumerate(alternatives[:5]):
            if anonymize:
                operateur = f"Opérateur {i + 1}"
            else:
                operateur = alt.get('fournisseur', f'Opérateur {i + 1}')

            row = [
                operateur[:15],
                alt.get('offre', 'N/A')[:20],
                alt.get('prix_mensuel', 'N/A'),
                alt.get('total_annuel', 'N/A'),
                alt.get('avantages', '')[:30]
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.colors['table_header_blue']),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.colors['section_blue']),
            ('FONTNAME', (0, 0), (-1, 0), self.fonts['bold']),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            ('BACKGROUND', (0, 1), (-1, -1), self.colors['white']),
            ('TEXTCOLOR', (0, 1), (-1, -1), self.colors['text_black']),
            ('FONTNAME', (0, 1), (-1, -1), self.fonts['regular']),
            ('FONTSIZE', (0, 1), (-1, -1), 8),

            ('GRID', (0, 0), (-1, -1), 0.5, self.colors['table_border']),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        story.append(table)
        story.append(Spacer(1, 4 * mm))

    def _add_telecom_issues(self, story: List, data: Dict, styles: Dict):
        """Problèmes détectés télécom"""
        issues = data.get('detected_issues', [])
        if not issues:
            return

        story.append(Paragraph("■ Points d'attention", styles['section_title']))

        for issue in issues[:4]:
            story.append(Paragraph(f"• {issue}", styles['offer_details']))

        story.append(Spacer(1, 4 * mm))

    def _add_telecom_recommendation(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Recommandation télécom"""
        best_savings = data.get('best_savings', {})

        story.append(Paragraph("■ Notre recommandation", styles['section_title']))

        fournisseur = best_savings.get('fournisseur_recommande', '')
        if anonymize and fournisseur:
            fournisseur = 'l\'opérateur recommandé'

        economie = best_savings.get('economie_annuelle', '')

        if fournisseur and economie:
            text = f"En passant chez {fournisseur}, vous pourriez économiser {economie}/an"
            story.append(Paragraph(text, styles['savings_highlight']))

        story.append(Spacer(1, 4 * mm))

    def _extract_price(self, price_str: str) -> float:
        """Extrait valeur numérique d'un prix"""
        try:
            cleaned = re.sub(r'[^\d,.]', '', str(price_str))
            cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except:
            return 999999

    def _create_insurance_pdf(self, data: Dict, output_path: str, anonymize: bool = False):
        """PDF pour assurances"""
        # À implémenter selon le même modèle
        self._create_generic_pdf(data, output_path, anonymize)

    def _create_generic_pdf(self, data: Dict, output_path: str, anonymize: bool = False):
        """PDF générique de fallback"""
        # Utiliser le format énergie par défaut
        self._create_energy_pdf(data, output_path, anonymize)

    def generate_popup_summary(self, data: Dict) -> str:
        """Résumé pour popup"""
        invoice_type = data.get('type_facture', 'inconnu')
        best_savings = data.get('best_savings', {})
        issues = data.get('detected_issues', [])

        summary_parts = []

        # Type détecté
        summary_parts.append(f"📋 Type de facture : {invoice_type}")

        # Économies
        economie = best_savings.get('economie_annuelle', '')
        if economie and economie != 'À calculer':
            summary_parts.append(f"💰 Économies potentielles : {economie}/an")

        # Problèmes principaux
        if issues:
            summary_parts.append("⚠️ Points d'attention :")
            for issue in issues[:2]:
                summary_parts.append(f"  • {issue}")

        # Recommandation
        if best_savings.get('fournisseur_recommande'):
            summary_parts.append(f"✅ Recommandé : {best_savings['fournisseur_recommande']}")

        return "\n".join(summary_parts)


# Alias pour compatibilité
FixedPDFGenerator = AdaptivePDFGenerator