import openai
import json
import logging
from typing import Dict, Any, Optional

from config import settings

# Configure logging
logger = logging.getLogger(__name__)

# Initialize the OpenAI client
# It's recommended to handle the case where the API key is not set.
if not settings.OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable not set.")

# THE FIX: Use the AsyncOpenAI client for async functions
client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def get_analysis_prompt(invoice_text: str) -> str:
    """
    Generates the full prompt for the OpenAI API, instructing it to return JSON.
    """
    # This JSON structure is what we want the AI to return.
    # It's much more reliable than parsing text.
    json_schema = {
        "client_info": {
            "name": "string",
            "address": "string",
            "contract_number": "string",
            "client_reference": "string"
        },
        "contract_details": {
            "type": "Électricité, Gaz, Mobile, Internet, etc.",
            "supplier": "string",
            "offer_name": "string",
            "price_ht": "float",
            "price_ttc": "float",
            "consumption": "string (e.g., 3583 kWh)",
            "commitment_period": "string"
        },
        "analysis": {
            "summary": "A paragraph analyzing the current offer, its pros and cons.",
            "detected_issues": ["List of detected traps or disadvantages, e.g., 'Prix moyen élevé'"]
        },
        "recommendation": {
            "summary": "A paragraph recommending the best course of action.",
            "estimated_savings": "string (e.g., 'Jusqu'à 95 € TTC/an')",
        },
        "alternative_offers": [
            {
                "supplier": "string",
                "offer_name": "string",
                "price_kwh": "float",
                "subscription_fee": "float",
                "annual_total_ttc": "float"
            }
        ],
        "popup_summary": "A very short, punchy summary for the frontend popup (max 4-5 lines, no competitor names)."
    }

    prompt = f"""
    You are a world-class expert in analyzing French utility bills (energy, mobile, internet).
    Your task is to analyze the following invoice text, extract key information, and provide a structured analysis.
    Your response MUST be a single, valid JSON object that conforms to the schema described below. Do not include any text or formatting outside of the JSON object.

    JSON Schema to follow:
    {json.dumps(json_schema, indent=2)}

    Here is the raw text extracted from the invoice:
    --- INVOICE TEXT START ---
    {invoice_text}
    --- INVOICE TEXT END ---

    Please analyze the text and return the populated JSON object. If a value is not found, use "Non disponible" for strings and null for numbers.
    """
    return prompt


async def analyze_invoice_text(invoice_text: str) -> Optional[Dict[str, Any]]:
    """
    Sends the invoice text to OpenAI for analysis and requests a structured JSON response.

    Args:
        invoice_text: The raw text extracted from the invoice.

    Returns:
        A dictionary containing the structured analysis, or None if it fails.
    """
    if not invoice_text or not invoice_text.strip():
        logger.error("Invoice text is empty. Cannot perform analysis.")
        return None

    system_prompt = "You are an expert financial analyst specializing in French utility bills. Your output must be a valid JSON object as requested by the user."
    user_prompt = get_analysis_prompt(invoice_text)

    try:
        logger.info("Sending request to OpenAI API for invoice analysis...")
        # This await now works correctly because we are using the Async client
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2048,
        )

        response_content = response.choices[0].message.content
        logger.info("Successfully received response from OpenAI.")

        # The response should be a JSON string, so we parse it.
        analysis_data = json.loads(response_content)
        return analysis_data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from OpenAI response: {e}")
        logger.error(f"Raw response content: {response_content}")
        return None
    except Exception as e:
        logger.error(f"An error occurred while calling the OpenAI API: {e}")
        return None
