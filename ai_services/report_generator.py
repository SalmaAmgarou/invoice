from fpdf import FPDF
from typing import Dict, Any
import datetime
import logging
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

# Define the path to the fonts directory relative to this file
# This makes the path robust, no matter where the script is run from.
FONTS_DIR = Path(__file__).parent / "fonts"


class PDF(FPDF):
    def header(self):
        # Logo - you can add a logo image here if you have one
        # self.image('logo.png', 10, 8, 33)
        self.set_font('DejaVu', 'B', 20)  # Use DejaVu font
        self.cell(0, 10, 'Rapport d\'Analyse de Facture', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', 'I', 8)  # Use DejaVu font
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('DejaVu', 'B', 14)  # Use DejaVu font
        self.set_fill_color(230, 240, 255)
        self.cell(0, 10, title, 0, 1, 'L', fill=True)
        self.ln(4)

    def chapter_body(self, content):
        self.set_font('DejaVu', '', 12)  # Use DejaVu font
        self.multi_cell(0, 8, content)
        self.ln()

    def key_value_pair(self, key: str, value: Any):
        self.set_font('DejaVu', 'B', 11)  # Use DejaVu font
        self.cell(60, 8, f"{key}:", 0, 0)
        self.set_font('DejaVu', '', 11)  # Use DejaVu font
        self.multi_cell(0, 8, str(value) if value else 'Non disponible')
        self.ln(2)


def create_report_pdf(analysis_data: Dict[str, Any], output_path: str, anonymize: bool = False):
    """
    Generates a PDF report from the structured analysis data.

    Args:
        analysis_data: The dictionary returned from the AI analyzer.
        output_path: The file path to save the generated PDF.
        anonymize: If True, anonymizes competitor supplier names.
    """
    try:
        pdf = PDF()

        # Pointing to the correct nested path from your screenshot
        font_base_path = FONTS_DIR / "dejavu-fonts-ttf-2.37" / "ttf"

        pdf.add_font("DejaVu", "", font_base_path / "DejaVuSans.ttf", uni=True)
        pdf.add_font("DejaVu", "B", font_base_path / "DejaVuSans-Bold.ttf", uni=True)
        pdf.add_font("DejaVu", "I", font_base_path / "DejaVuSans-Oblique.ttf", uni=True)

        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        # --- Client and Offer Details ---
        pdf.chapter_title("1. Résumé de votre situation actuelle")

        client_info = analysis_data.get('client_info', {})
        contract = analysis_data.get('contract_details', {})

        pdf.key_value_pair("Client", client_info.get('name'))
        pdf.key_value_pair("Adresse", client_info.get("address"))
        pdf.key_value_pair("N° de Contrat", client_info.get("contract_number"))
        pdf.key_value_pair("Fournisseur Actuel", contract.get("supplier"))
        pdf.key_value_pair("Offre Actuelle", contract.get("offer_name"))
        pdf.key_value_pair("Montant Annuel TTC", f"{contract.get('price_ttc')} €")
        pdf.key_value_pair("Consommation", contract.get("consumption"))

        # --- Analysis ---
        pdf.chapter_title("2. Analyse de votre contrat")
        analysis = analysis_data.get('analysis', {})
        pdf.chapter_body(analysis.get('summary', ''))

        if analysis.get('detected_issues'):
            pdf.set_font('DejaVu', 'B', 12)
            pdf.cell(0, 10, "Pièges détectés :", 0, 1)
            pdf.set_font('DejaVu', '', 11)
            for issue in analysis['detected_issues']:
                # THE FIX: Use write() instead of multi_cell() for better text wrapping.
                pdf.write(8, f"- {issue}\n")
            pdf.ln()

        # --- Alternative Offers ---
        pdf.chapter_title("3. Comparatif des offres alternatives")
        alternatives = analysis_data.get('alternative_offers', [])
        if alternatives:
            # Table Header
            pdf.set_font('DejaVu', 'B', 10)
            pdf.cell(60, 8, 'Fournisseur', 1)
            pdf.cell(50, 8, 'Offre', 1)
            pdf.cell(40, 8, 'Total Annuel TTC', 1)
            pdf.cell(30, 8, 'Économie', 1)
            pdf.ln()

            # Table Rows
            pdf.set_font('DejaVu', '', 10)
            current_price = contract.get('price_ttc') or 0

            for i, offer in enumerate(alternatives):
                supplier_name = offer.get('supplier')
                if anonymize:
                    supplier_name = f"Fournisseur {i + 1}"

                pdf.cell(60, 8, supplier_name, 1)
                pdf.cell(50, 8, offer.get('offer_name'), 1)

                annual_total = offer.get('annual_total_ttc')
                pdf.cell(40, 8, f"{annual_total} €" if annual_total else "N/A", 1)

                savings = (current_price - annual_total) if current_price and annual_total else 0
                savings_text = f"{savings:.2f} €" if savings > 0 else "-"
                pdf.cell(30, 8, savings_text, 1)
                pdf.ln()
        else:
            pdf.chapter_body("Aucune offre alternative n'a pu être identifiée pour le moment.")

        pdf.ln(5)

        # --- Recommendation ---
        pdf.chapter_title("4. Notre Recommandation")
        recommendation = analysis_data.get('recommendation', {})
        pdf.set_font('DejaVu', 'B', 12)
        pdf.chapter_body(recommendation.get('summary', ''))

        pdf.set_font('DejaVu', 'B', 14)
        pdf.set_text_color(220, 50, 50)
        pdf.cell(0, 10, f"Économie potentielle : {recommendation.get('estimated_savings', 'N/A')}", 0, 1, 'C')

        pdf.output(output_path)
        logger.info(f"Successfully created PDF report: {output_path}")

    except Exception as e:
        logger.error(f"Failed to generate PDF report at {output_path}: {e}")
        raise
