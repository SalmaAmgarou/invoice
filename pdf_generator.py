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


class ProfessionalPDFGenerator:
    def __init__(self):
        # Colors matching the sample reports
        self.colors = {
            'primary_blue': HexColor('#1f4788'),
            'section_blue': HexColor('#4472C4'),
            'light_blue': HexColor('#E7EFFD'),
            'table_header': HexColor('#D9E2F3'),
            'recommendation_red': HexColor('#C5504B'),
            'text_dark': HexColor('#2F2F2F'),
            'text_medium': HexColor('#595959')
        }

        # Try to register Unicode fonts
        self._setup_fonts()

    def _setup_fonts(self):
        """Setup fonts for better text rendering"""
        try:
            # Try to use system fonts or custom fonts
            font_paths = [
                '/System/Library/Fonts/Arial.ttf',  # macOS
                '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',  # Linux
                'C:/Windows/Fonts/arial.ttf',  # Windows
                os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans.ttf')  # Custom
            ]

            for font_path in font_paths:
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path))
                    self.font_name = 'CustomFont'
                    break
            else:
                self.font_name = 'Helvetica'

        except Exception as e:
            logger.warning(f"Could not load custom fonts: {e}")
            self.font_name = 'Helvetica'

    def generate_reports(self, structured_data: Dict, user_id: int) -> Tuple[str, str]:
        """Generate both internal and user reports"""
        Config.create_folders()

        # Generate unique filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        internal_filename = f"rapport_internal_{user_id}_{timestamp}.pdf"
        user_filename = f"rapport_user_{user_id}_{timestamp}.pdf"

        internal_path = os.path.join(Config.REPORTS_INTERNAL_FOLDER, internal_filename)
        user_path = os.path.join(Config.REPORTS_FOLDER, user_filename)

        # Create internal report (with real supplier names)
        self._create_professional_pdf(structured_data, internal_path, anonymize_suppliers=False)

        # Create user report (anonymized suppliers)
        self._create_professional_pdf(structured_data, user_path, anonymize_suppliers=True)

        logger.info(f"Professional reports generated: {internal_path}, {user_path}")
        return internal_path, user_path

    def _create_professional_pdf(self, data: Dict, output_path: str, anonymize_suppliers: bool = False):
        """Create professional PDF matching the sample format"""
        try:
            doc = SimpleDocTemplate(
                output_path,
                pagesize=A4,
                rightMargin=2 * cm,
                leftMargin=2 * cm,
                topMargin=2 * cm,
                bottomMargin=2 * cm
            )

            # Build story elements
            story = []
            styles = self._get_professional_styles()

            # Determine document type
            doc_type = data.get('type_facture', 'énergie').upper()

            # Add title
            title = f"Rapport comparatif énergie – {doc_type}"
            story.append(Paragraph(title, styles['main_title']))
            story.append(Spacer(1, 8 * mm))

            # Add client info and date
            client_name = data.get('client_info', {}).get('nom', '[anonymisé]')
            if anonymize_suppliers:
                client_name = '[anonymisé]'

            story.append(Paragraph(f"Client : {client_name}", styles['client_info']))
            story.append(Paragraph(f"Date : {datetime.now().strftime('%B %Y')}", styles['client_info']))
            story.append(Spacer(1, 10 * mm))

            # Add current offer section
            self._add_current_offer_section(story, data, styles, anonymize_suppliers)

            # Add comparison table
            self._add_comparison_table(story, data, styles, anonymize_suppliers)

            # Add detected issues section
            self._add_issues_section(story, data, styles)

            # Add recommendation section
            self._add_recommendation_section(story, data, styles, anonymize_suppliers)

            # Add methodology section
            self._add_methodology_section(story, styles)

            # Build PDF
            doc.build(story)
            logger.info(f"Professional PDF created: {output_path}")

        except Exception as e:
            logger.error(f"Error creating professional PDF {output_path}: {str(e)}")
            raise Exception(f"Error generating professional PDF: {str(e)}")

    def _get_professional_styles(self) -> Dict:
        """Get professional paragraph styles"""
        styles = getSampleStyleSheet()

        custom_styles = {
            'main_title': ParagraphStyle(
                'MainTitle',
                parent=styles['Heading1'],
                fontName=self.font_name,
                fontSize=16,
                textColor=black,
                alignment=TA_LEFT,
                spaceAfter=6 * mm,
                spaceBefore=0,
                fontWeight='bold'
            ),
            'section_title': ParagraphStyle(
                'SectionTitle',
                parent=styles['Heading2'],
                fontName=self.font_name,
                fontSize=12,
                textColor=self.colors['section_blue'],
                spaceAfter=4 * mm,
                spaceBefore=8 * mm,
                leftIndent=0,
                bulletIndent=6 * mm,
                bulletFontName=self.font_name,
                bulletFontSize=12,
                bulletColor=self.colors['section_blue']
            ),
            'client_info': ParagraphStyle(
                'ClientInfo',
                parent=styles['Normal'],
                fontName=self.font_name,
                fontSize=10,
                textColor=self.colors['text_dark'],
                spaceAfter=2 * mm
            ),
            'body_text': ParagraphStyle(
                'BodyText',
                parent=styles['Normal'],
                fontName=self.font_name,
                fontSize=10,
                textColor=self.colors['text_dark'],
                spaceAfter=3 * mm,
                leftIndent=3 * mm
            ),
            'recommendation': ParagraphStyle(
                'Recommendation',
                parent=styles['Normal'],
                fontName=self.font_name,
                fontSize=11,
                textColor=self.colors['recommendation_red'],
                spaceAfter=4 * mm,
                spaceBefore=2 * mm,
                fontWeight='bold'
            ),
            'methodology': ParagraphStyle(
                'Methodology',
                parent=styles['Normal'],
                fontName=self.font_name,
                fontSize=9,
                textColor=self.colors['text_medium'],
                spaceAfter=2 * mm,
                alignment=TA_JUSTIFY
            )
        }

        return custom_styles

    def _add_current_offer_section(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Add current offer section with blue header"""
        current_offer = data.get('current_offer', {})
        doc_type = data.get('type_facture', 'énergie')

        # Section title with bullet
        fournisseur = current_offer.get('fournisseur', 'Non spécifié')
        if anonymize:
            fournisseur = 'Fournisseur Actuel'

        title = f"■ Offre actuelle {doc_type} – {fournisseur}"
        story.append(Paragraph(title, styles['section_title']))

        # Details
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
            story.append(Paragraph(detail, styles['body_text']))

        story.append(Spacer(1, 6 * mm))

    def _add_comparison_table(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Add professional comparison table"""
        alternatives = data.get('alternatives', [])
        if not alternatives:
            return

        doc_type = data.get('type_facture', 'énergie')

        # Section title
        consumption = data.get('current_offer', {}).get('consommation_annuelle', '')
        title = f"■ Comparatif – Offres {doc_type.title()}"
        if consumption:
            title += f" ({consumption})"
        story.append(Paragraph(title, styles['section_title']))

        # Prepare table data
        headers = ['Fournisseur', 'Prix kWh', 'Abonnement', 'Total annuel TTC']
        table_data = [headers]

        for i, alt in enumerate(alternatives):
            if anonymize:
                fournisseur = f"Fournisseur {i + 1}"
            else:
                fournisseur = alt.get('fournisseur', f'Fournisseur {i + 1}')

            row = [
                fournisseur,
                alt.get('prix_kwh', ''),
                alt.get('abonnement', ''),
                alt.get('total_annuel', '')
            ]
            table_data.append(row)

        # Create table
        table = Table(table_data, colWidths=[45 * mm, 30 * mm, 35 * mm, 40 * mm])

        # Style table
        table.setStyle(TableStyle([
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), self.colors['table_header']),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.colors['primary_blue']),
            ('FONTNAME', (0, 0), (-1, 0), self.font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTWEIGHT', (0, 0), (-1, 0), 'bold'),

            # Data styling
            ('BACKGROUND', (0, 1), (-1, -1), white),
            ('TEXTCOLOR', (0, 1), (-1, -1), self.colors['text_dark']),
            ('FONTNAME', (0, 1), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),  # Center numbers
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),  # Left align supplier names

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, self.colors['text_medium']),
            ('LINEBELOW', (0, 0), (-1, 0), 1, self.colors['primary_blue']),

            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(table)
        story.append(Spacer(1, 8 * mm))

    def _add_issues_section(self, story: List, data: Dict, styles: Dict):
        """Add detected issues section"""
        issues = data.get('detected_issues', [])
        if not issues:
            return

        # Section title
        story.append(Paragraph("■ Pièges détectés dans l'offre actuelle", styles['section_title']))

        # Issues list
        for issue in issues:
            story.append(Paragraph(f"- {issue}", styles['body_text']))

        story.append(Spacer(1, 6 * mm))

    def _add_recommendation_section(self, story: List, data: Dict, styles: Dict, anonymize: bool):
        """Add recommendation section with highlighting"""
        best_savings = data.get('best_savings', {})
        if not best_savings:
            return

        # Section title
        story.append(Paragraph("■ Notre recommandation", styles['section_title']))

        # Recommendation text
        fournisseur = best_savings.get('fournisseur_recommande', '')
        if anonymize and fournisseur:
            fournisseur = 'le fournisseur recommandé'

        economie = best_savings.get('economie_annuelle', '')
        consumption = data.get('current_offer', {}).get('consommation_annuelle', '')

        if fournisseur and economie:
            if anonymize:
                text = f"En changeant pour {fournisseur}, vous pourriez économiser jusqu'à {economie} TTC/an"
            else:
                text = f"En changeant pour {fournisseur}, vous pourriez économiser jusqu'à {economie} TTC/an"

            if consumption:
                text += f" à consommation constante ({consumption})."
            else:
                text += "."

            story.append(Paragraph(text, styles['recommendation']))

        story.append(Spacer(1, 6 * mm))

    def _add_methodology_section(self, story: List, styles: Dict):
        """Add methodology and reliability section"""
        # Section title
        story.append(Paragraph("■ Méthodologie & Fiabilité des données", styles['section_title']))

        # Methodology text
        methodology_text = [
            "Les données de ce rapport proviennent de votre facture, d'offres publiques à jour, et de références officielles (TRV, CRE, barèmes).",
            "Les comparaisons sont faites à partir de sources vérifiables (sites fournisseurs, simulateurs certifiés).",
            "■ Rapport indépendant, sans publicité ni affiliation. Son seul but : identifier vos économies possibles."
        ]

        for text in methodology_text:
            story.append(Paragraph(text, styles['methodology']))

        story.append(Spacer(1, 4 * mm))

    def generate_popup_summary(self, data: Dict) -> str:
        """Generate summary for popup display"""
        issues = data.get('detected_issues', [])
        best_savings = data.get('best_savings', {})

        summary_parts = []

        # Add savings info
        economie = best_savings.get('economie_annuelle', '')
        if economie:
            summary_parts.append(f"💸 Vous pourriez optimiser jusqu'à {economie}/an sur votre facture !")

        # Add key issues (max 3)
        if issues:
            summary_parts.append("🔍 Problèmes détectés :")
            for issue in issues[:3]:
                summary_parts.append(f"• {issue}")

        # Add recommendation
        if best_savings:
            summary_parts.append("💡 Changement de fournisseur recommandé pour réaliser ces économies.")

        return "\n\n".join(summary_parts)