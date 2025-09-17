import os
import tempfile
import logging
from typing import Optional
from pathlib import Path

import PyPDF2
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

from config import Config

logger = logging.getLogger(__name__)


class OCRProcessor:
    def __init__(self):
        # Set tesseract command path if specified
        if Config.TESSERACT_CMD != "tesseract":
            pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_CMD

    def extract_text_from_file(self, file_path: str) -> str:
        """
        Extract text from PDF or image file

        Args:
            file_path: Path to the file

        Returns:
            Extracted text string

        Raises:
            ValueError: If file type is not supported
            Exception: If text extraction fails
        """
        file_extension = Path(file_path).suffix.lower()

        try:
            if file_extension == '.pdf':
                return self._extract_text_from_pdf(file_path)
            elif file_extension in ['.png', '.jpg', '.jpeg', '.gif']:
                return self._extract_text_from_image(file_path)
            else:
                raise ValueError(f"Type de fichier non supporté: {file_extension}")
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction du texte de {file_path}: {str(e)}")
            raise Exception(f"Impossible d'extraire le texte du fichier: {str(e)}")

    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF file, with OCR fallback if no text found"""
        text = ""

        try:
            # First, try to extract text directly from PDF
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"

            # If no text extracted, use OCR on PDF pages
            if not text.strip():
                logger.info(f"Pas de texte extrait directement du PDF {pdf_path}, utilisation de l'OCR")
                text = self._ocr_pdf_pages(pdf_path)

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction directe du PDF: {str(e)}")
            # Fallback to OCR
            text = self._ocr_pdf_pages(pdf_path)

        return text.strip()

    def _ocr_pdf_pages(self, pdf_path: str) -> str:
        """Convert PDF pages to images and run OCR"""
        text = ""

        try:
            # Convert PDF pages to images
            pages = convert_from_path(pdf_path, dpi=300)

            for i, page in enumerate(pages):
                logger.info(f"Traitement OCR de la page {i + 1}/{len(pages)}")

                # Save page as temporary image
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_img:
                    page.save(temp_img.name, 'JPEG')

                    # Run OCR on the image
                    page_text = pytesseract.image_to_string(
                        temp_img.name,
                        lang='fra',  # French language
                        config='--oem 3 --psm 6'  # OCR Engine Mode 3, Page Segmentation Mode 6
                    )
                    text += page_text + "\n"

                    # Clean up temporary file
                    os.unlink(temp_img.name)

        except Exception as e:
            logger.error(f"Erreur lors de l'OCR des pages PDF: {str(e)}")
            raise Exception(f"Échec de l'OCR sur le PDF: {str(e)}")

        return text.strip()

    def _extract_text_from_image(self, image_path: str) -> str:
        """Extract text from image using OCR"""
        try:
            # Open and process image
            image = Image.open(image_path)

            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Run OCR
            text = pytesseract.image_to_string(
                image,
                lang='fra',  # French language
                config='--oem 3 --psm 6'  # OCR Engine Mode 3, Page Segmentation Mode 6
            )

            return text.strip()

        except Exception as e:
            logger.error(f"Erreur lors de l'OCR de l'image: {str(e)}")
            raise Exception(f"Échec de l'OCR sur l'image: {str(e)}")

    def is_text_extracted(self, text: str) -> bool:
        """Check if meaningful text was extracted"""
        if not text or not text.strip():
            return False

        # Check if we have at least some reasonable amount of text
        words = text.split()
        return len(words) >= 5  # At least 5 words

    def preprocess_text(self, text: str) -> str:
        """Clean and preprocess extracted text"""
        if not text:
            return ""

        # Remove excessive whitespace and normalize line breaks
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if line:  # Only keep non-empty lines
                lines.append(line)

        # Join lines with single newlines
        cleaned_text = '\n'.join(lines)

        # Remove multiple consecutive spaces
        import re
        cleaned_text = re.sub(r' +', ' ', cleaned_text)

        return cleaned_text