import os
import pytesseract
from PIL import Image
import pdfplumber
from pdfplumber.display import PageImage
import logging
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_text_from_image(file_path: str) -> str:
    """
    Extracts text from an image file using Tesseract OCR.

    Args:
        file_path: The path to the image file.

    Returns:
        The extracted text as a string.
    """
    try:
        text = pytesseract.image_to_string(Image.open(file_path), lang='fra')
        logger.info(f"Successfully extracted text from image: {file_path}")
        return text
    except Exception as e:
        logger.error(f"Error during OCR for image {file_path}: {e}")
        return ""


def extract_text_from_pdf(file_path: str, use_ocr_fallback: bool = True) -> Optional[str]:
    """
    Extracts text from a PDF file.

    It first tries direct text extraction. If that fails or returns minimal text,
    it uses a fallback mechanism to convert each page to an image and perform OCR.

    Args:
        file_path: The path to the PDF file.
        use_ocr_fallback: Whether to use OCR if direct extraction fails.

    Returns:
        The extracted text, or None if extraction fails completely.
    """
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        # If the extracted text is very short, it might be a scanned PDF.
        if len(text.strip()) > 50:
            logger.info(f"Successfully extracted text directly from PDF: {file_path}")
            return text

        logger.warning(f"Direct text extraction from {file_path} yielded little to no text.")
        if not use_ocr_fallback:
            return text if text.strip() else None

        # --- OCR Fallback ---
        logger.info(f"Attempting OCR fallback for {file_path}")
        ocr_text = ""
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # Convert page to image
                img: PageImage = page.to_image(resolution=300)
                # Perform OCR on the image
                page_ocr_text = pytesseract.image_to_string(img.original, lang='fra')
                ocr_text += page_ocr_text + "\n"

        if ocr_text.strip():
            logger.info(f"Successfully extracted text via OCR from PDF: {file_path}")
            return ocr_text
        else:
            logger.error(f"OCR fallback also failed to extract text from {file_path}")
            return None

    except Exception as e:
        logger.error(f"Failed to process PDF {file_path}: {e}")
        return None


def extract_text(file_path: str, mime_type: str) -> Optional[str]:
    """
    A wrapper function that extracts text from a file based on its MIME type.
    """
    logger.info(f"Extracting text from {file_path} with MIME type {mime_type}")
    if "pdf" in mime_type:
        return extract_text_from_pdf(file_path)
    elif "image" in mime_type:
        return extract_text_from_image(file_path)
    else:
        logger.error(f"Unsupported file type: {mime_type}")
        return None
