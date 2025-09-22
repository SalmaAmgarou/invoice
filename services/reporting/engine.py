#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
report_pioui_static_v3_gemini.py

Generates 2 stylish PDF reports (non-anonymous & anonymous) from an energy bill.
- Extraction (text/vision) -> JSON dual-aware
- Synthetic "best" offers: -12%, -11%, -10% of current annual total
- Premium rendering with Pioui branding (Poppins font, modern layout, logo, new color palette)
- Detailed and contextualized "Vices cachés" section
- ORDER per energy: Offre actuelle -> Comparatif -> Vices cachés -> Recommandation -> (global) Méthodologie & Fiabilité
- Uses Pioui yellow #F0BC00 and replaces emojis with ASCII labels for reliability
"""
import base64, mimetypes, pathlib
import os, json, random, datetime
from datetime import date, datetime as dt
from typing import List, Dict, Any, Tuple, Optional
import instructor
from mistralai import Mistral
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
# --- OpenAI ---
from openai import OpenAI
from core.config import Config
import re
client = OpenAI(api_key=Config.OPENAI_API_KEY)
import io
# --- PDF / OCR ---
import pdfplumber
from pdf2image import convert_from_path

# --- ReportLab ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas as rl_canvas
from openai import OpenAI
import instructor
from core.config import Config
from pathlib import Path


# ───────────────── 🎨 Pioui Branding & Styling 🎨 ─────────────────
PALETTE = {
    "primary_blue": "#2563EB",   # Main accent blue
    "brand_yellow": "#F0BC00",   # Pioui yellow (NEW)
    "dark_navy": "#e6efff",      # Header/footer backgrounds
    "text_dark": "#0F172A",      # Main text
    "text_muted": "#64748B",     # Subtitles
    "bg_light": "#F8FAFC",       # Zebra rows
    "bg_white": "#FFFFFF",
    "border_light": "#E2E8F0",   # Hairlines
    "table_header": "#F1F5F9",   # Table header
    "saving_red": "#DC2626",     # Savings emphasis
}

PIOUI = {
    "url": "https://pioui.com",
    "email": "service.client@pioui.com",
    "name":"ND CONSULTING, société à responsabilité limitée",
    "addr": "Bureau 562-78 avenue des Champs-Élysées, 75008 Paris",
    "tel": "01 62 19 95 72",
    "copyright": f"Copyright © {date.today().year} / 2025, All Rights Reserved."
}

# Assets

PKG_ROOT = Path(__file__).resolve().parents[2]  # .../pioui
ASSETS_DIR = PKG_ROOT / "assets"
FONT_DIR   = ASSETS_DIR / "fonts"
LOGO_PATH  = ASSETS_DIR / "logo" / "pioui.png"

# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# LOGO_PATH = os.path.join(SCRIPT_DIR, "logo", "pioui.png")
# FONT_DIR = os.path.join(SCRIPT_DIR, "fonts")



def _image_to_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:%s;base64,%s" % (mime, b64)

# DÃ©finir la structure de sortie avec Pydantic
class ClientInfo(BaseModel):
    name: Optional[str] = Field(..., description="Nom complet du client titulaire du contrat.")
    address: Optional[str] = Field(..., description="Adresse de facturation complète.")
    zipcode: Optional[str] = Field(..., description="Code postal de l'adresse de facturation.")

class Periode(BaseModel):
    de: Optional[str] = Field(..., description="Date de début au format JJ/MM/AAAA.")
    a: Optional[str] = Field(..., description="Date de fin au format JJ/MM/AAAA.")
    jours: Optional[int] = Field(..., description="Nombre total de jours dans la période.")

class EnergyDetails(BaseModel):
    type: str = Field(..., description="Le type d'énergie : 'electricite' ou 'gaz'.")
    periode: Optional[Periode] = Field(..., description="La période de facturation pour la CONSOMMATION réelle de cette énergie, et non la période de l'abonnement.")
    fournisseur: Optional[str] = Field(..., description="Le nom du fournisseur d'énergie.")
    offre: Optional[str] = Field(..., description="Le nom commercial de l'offre.")
    option: Optional[str] = Field(None, description="Pour l'électricité : 'Base' ou 'HP/HC'.")
    puissance_kVA: Optional[int] = Field(None, description="La puissance souscrite en kVA pour l'électricité.")
    conso_kwh: Optional[float] = Field(None, description="La consommation totale en kWh pour la période. Peut être null si non trouvée.")
    total_ttc: Optional[float] = Field(..., description="Le montant total TTC pour cette énergie pour la période.")

    @field_validator("conso_kwh", "total_ttc")
    def required_field(cls, v):
        if v is None:
            # Ce message sera envoyé au LLM en cas d'échec !
            raise ValueError("Ce champ est manquant. Retrouvez sa valeur dans le document.")
        return v


class Facture(BaseModel):
    client: ClientInfo
    periode_globale: Optional[Periode] = Field(..., description="La période de bilan annuel si présente, sinon la période principale.")
    energies: List[EnergyDetails]

client = instructor.patch(OpenAI(api_key=Config.OPENAI_API_KEY))
# ───────────────── ✍️ Font Registration (Poppins) ✍️ ─────────────────
def register_poppins_fonts():
    try:
        fonts_to_register = {
            'Poppins': 'Poppins-Regular.ttf',
            'Poppins-Bold': 'Poppins-Bold.ttf',
            'Poppins-Italic': 'Poppins-Italic.ttf',
            'Poppins-BoldItalic': 'Poppins-BoldItalic.ttf',
        }
        for name, filename in fonts_to_register.items():
            pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, filename)))
        pdfmetrics.registerFontFamily(
            'Poppins', normal='Poppins', bold='Poppins-Bold',
            italic='Poppins-Italic', boldItalic='Poppins-BoldItalic'
        )
        print("[INFO] Famille de polices Poppins enregistrée avec succès.")
        return True
    except Exception as e:
        print(f"[AVERTISSEMENT] Impossible d'enregistrer les polices Poppins. Retour à Helvetica. Erreur : {e}")
        return False

IS_POPPINS_AVAILABLE = register_poppins_fonts()
BASE_FONT = "Poppins" if IS_POPPINS_AVAILABLE else "Helvetica"
BOLD_FONT = "Poppins-Bold" if IS_POPPINS_AVAILABLE else "Helvetica-Bold"

# ───────────────── Utilities ─────────────────
def _to_float(x, default=None):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return default

def _to_int(x, default=None):
    try:
        return int(str(x).strip())
    except Exception:
        return default

def _find_first_int(pattern: str, text: str, flags=re.I|re.S):
    m = re.search(pattern, text, flags)
    return _to_int(m.group(1)) if m else None

def try_parse_car_annual_kwh(text: str) -> Optional[float]:
    # Ex: "Consommation Annuelle de Référence : 631 kWh"
    n = _find_first_int(r"Consommation\s+Annuelle\s+de\s+Référence.*?:\s*([\d\s]{1,7})\s*kWh", text)
    return float(n) if n is not None else None

def try_parse_monthly_kwh_sum(text: str) -> Optional[float]:
    # Ex bloc "ma consommation (kWh) ... 112 90 45 44 ..."
    m = re.search(r"ma\s+consommation\s*\(kWh\)(.*)", text, re.I|re.S)
    if not m:
        return None
    block = m.group(1)
    nums = [int(x) for x in re.findall(r"\b(\d{1,5})\b", block)]
    if len(nums) >= 6:
        # somme les 12 premiers entiers plausibles si dispo
        return float(sum(nums[:12])) if len(nums) >= 12 else float(sum(nums))
    return None

def try_parse_period_kwh_from_detail(text: str) -> Optional[float]:
    """
    Cherche dans "Détail de ma facture" des lignes avec 'Conso (kWh) <n>'.
    On somme toutes les occurrences sur la période.
    """
    # restreindre au bloc "Détail" si possible
    detail = re.search(r"D[ée]tail\s+de\s+ma\s+facture(.*?)(?:TOTAL|TVA|$)", text, re.I|re.S)
    scope = detail.group(1) if detail else text
    vals = [int(x) for x in re.findall(r"Conso\s*\(kWh\)\s*([0-9]{1,6})", scope, re.I)]
    if vals:
        return float(sum(vals))
    return None

def try_parse_m3_and_coef_to_kwh(text: str) -> Optional[float]:
    """
    Si on ne trouve pas kWh directement, tenter 'Conso (m3)' et 'Coefficient ... : <coef>'
    """
    m3s = re.findall(r"Conso\s*\(m3\)\s*([\d\.,]+)", text, re.I)
    coef = re.search(r"Coefficient\s+de\s+conversion.*?:\s*([\d\.,]+)", text, re.I)
    if not m3s or not coef:
        return None
    def f(x): return _to_float(x.replace(" ", ""))
    coef_v = f(coef.group(1))
    if not coef_v:
        return None
    total_m3 = sum([f(x) or 0.0 for x in m3s])
    kwh = total_m3 * coef_v
    return float(kwh) if kwh > 0 else None

def derive_consumptions_from_text(raw_text: str,
                                  energy: str,
                                  period_days: Optional[int]) -> Tuple[Optional[float], Optional[float]]:
    """
    Retourne (period_kwh, annual_kwh) en combinant plusieurs indices du PDF.
    Priorités:
      - Annuel: CAR > somme 'ma consommation (kWh)' > extrapolation (si période dispo)
      - Période: somme des 'Conso (kWh)' dans le détail > m3*coef
    """
    period_kwh = try_parse_period_kwh_from_detail(raw_text)
    if period_kwh in (None, 0.0):
        alt = try_parse_m3_and_coef_to_kwh(raw_text)
        period_kwh = alt if alt not in (None, 0.0) else period_kwh

    annual_kwh = try_parse_car_annual_kwh(raw_text)
    if annual_kwh in (None, 0.0):
        annual_kwh = try_parse_monthly_kwh_sum(raw_text)

    if (annual_kwh in (None, 0.0)) and period_kwh and period_days and period_days > 0:
        annual_kwh = period_kwh * (365.0 / float(period_days))

    # Nettoyage final
    if period_kwh is not None and period_kwh < 0:
        period_kwh = None
    if annual_kwh is not None and annual_kwh <= 0:
        annual_kwh = None

    return (period_kwh, annual_kwh)

def _parse_date_fr(s: str) -> Optional[dt]:
    try:
        return dt.strptime(s, "%d/%m/%Y")
    except Exception:
        return None

def annualize(value_for_period: Optional[float], days: Optional[int]) -> Optional[float]:
    if not value_for_period or not days or days <= 0:
        return None
    return value_for_period * (365.0 / days)

def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        out = ""
        with pdfplumber.open(pdf_path) as pdf:
            for p in pdf.pages:
                t = p.extract_text()
                if t:
                    out += t + "\n"
        return out.strip()
    except Exception:
        return ""

# ───────────────── GPT extractors ─────────────────
def ocr_invoice_with_gpt(image_path: str) -> str:
    system = "Assistant d'analyse de factures énergie. Retourne UNIQUEMENT un JSON valide (un objet)."
    user_prompt = "Même consignes que précédemment. Image ci-dessous."
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_to_data_url(image_path)}
                    }
                ],
            },
        ],
        temperature=0.0,
        seed=42,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content

def parse_text_with_gpt(text: str) -> str: # La fonction retournera toujours un str JSON pour la compatibilité
    """
    Analyse le texte de la facture en utilisant Instructor et Pydantic pour garantir
    une sortie JSON structurée et correcte.
    """
    try:
        facture_model = client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=Facture, # C'est ici que la magie opère
            max_retries=1,
            messages=[
                {"role": "system", "content": "Tu es un expert en extraction de données sur les factures d'énergie. Extrais les informations demandées en te basant sur le schéma Pydantic fourni.  Si un champ est marqué comme obligatoire et que tu ne le trouves pas, cherche plus attentivement."},
                {"role": "user", "content": f"Voici le texte de la facture à analyser:\n\n---\n{text}\n---"}
            ],
            temperature=0.0,
            seed=42,
        )
        # Convertit le modèle Pydantic en dictionnaire puis en string JSON
        # On renomme 'periode_globale' en 'periode' pour garder la compatibilité avec le reste du code
        parsed_dict = facture_model.model_dump()
        parsed_dict['periode'] = parsed_dict.pop('periode_globale', None)
        return json.dumps(parsed_dict, indent=2)

    except Exception as e:
        print(f"[ERREUR] Échec de l'analyse Instructor/Pydantic après les tentatives : {e}")
        # Retourne un JSON vide ou une structure de secours
        return json.dumps({"client": {}, "periode": {}, "energies": []})

# ───────────────── Data processing ─────────────────
def params_from_energy(global_json: dict, energy_obj: dict, raw_text: str) -> dict:
    zipcode = ((global_json.get("client") or {}).get("zipcode")) or "75001"
    periode = energy_obj.get("periode") or global_json.get("periode") or {}
    jours = periode.get("jours")
    try:
        jours = int(jours) if jours else None
    except Exception:
        jours = None
    if not jours and periode.get("de") and periode.get("a"):
        d1, d2 = _parse_date_fr(periode["de"]), _parse_date_fr(periode["a"])
        if d1 and d2 and d1 < d2:
            jours = (d2 - d1).days

    energy = (energy_obj.get("type") or "electricite").strip().lower()
    option = energy_obj.get("option") or ("Base" if energy == "electricite" else None)
    kva = None
    if energy == "electricite":
        try:
            kva = int(energy_obj.get("puissance_kVA") or 6)
        except Exception:
            kva = 6

    # 1) Dérive conso depuis le PDF (robuste)
    period_kwh_txt, annual_kwh_txt = derive_consumptions_from_text(raw_text, energy, jours)

    # 2) Lis la valeur GPT si dispo (peut être période ou annuel… on l’utilise en secours uniquement si > 0)
    conso_gpt = _to_float(energy_obj.get("conso_kwh"))

    # 3) Choix finaux
    #    - conso période = priorité au texte; sinon, si GPT paraît raisonnable ET jours connus (=> sans doute une période), on prend GPT
    period_kwh = period_kwh_txt
    if (period_kwh in (None, 0.0)) and conso_gpt and conso_gpt > 0 and jours:
        period_kwh = conso_gpt

    #    - conso annuelle = priorité CAR/“ma consommation”; sinon extrapolation période; sinon, si GPT est grand et jours inconnus, on suppose que GPT est annuel
    annual_kwh = annual_kwh_txt
    if annual_kwh in (None, 0.0):
        if period_kwh and jours:
            annual_kwh = period_kwh * (365.0 / float(jours))
        elif conso_gpt and conso_gpt > 0 and not jours:
            annual_kwh = conso_gpt  # suppose annuel (faute d'indice meilleur)

    return {
        "energy": "gaz" if energy.startswith("gaz") else "electricite",
        "zipcode": zipcode,
        "kva": kva if energy == "electricite" else None,
        "option": option if energy == "electricite" else None,

        "period_kwh": period_kwh,
        "annual_kwh": annual_kwh,
        "consumption_kwh": annual_kwh,  # Keep for backward compatibility in offer generation

        # Add start and end dates for the report
        "period_start_date": periode.get("de"),
        "period_end_date": periode.get("a"),
        "period_days": jours,

        "hp_share": 0.35 if (option and str(option).upper().startswith("HP")) else None,
        "total_ttc_period": _to_float(energy_obj.get("total_ttc")),
        "abonnement_ttc_period": _to_float(energy_obj.get("abonnement_ttc")),
        "fournisseur": energy_obj.get("fournisseur"),
        "offre": energy_obj.get("offre"),
    }


# Corrected function
def current_annual_total(params: dict) -> Optional[float]:
    tp, pd = params.get("total_ttc_period"), params.get("period_days")
    if tp and pd:
        return annualize(tp, pd)

    # fallback rough estimate
    conso_kwh = params.get("consumption_kwh")  # Use .get() for safety
    if conso_kwh is not None:
        return (conso_kwh * (0.25 if params["energy"] == "electricite" else 0.10)
                + (150.0 if params["energy"] == "electricite" else 220.0))

    return None  # Return None if no consumption data is available to calculate
# ───────────────── Synthetic offers (logic unchanged) ─────────────────
PROVIDERS_ELEC = ["EDF", "Engie", "TotalEnergies", "Vattenfall", "OHM Énergie", "ekWateur", "Mint Énergie",
                  "Plüm énergie", "ilek", "Enercoop", "Méga Énergie", "Wekiwi", "Happ-e by Engie", "Alpiq",
                  "Octopus Energy"]
PROVIDERS_GAZ = ["Engie", "EDF", "TotalEnergies", "Plenitude (ex Eni)", "Happ-e by Engie", "ekWateur", "Vattenfall",
                 "Mint Énergie", "Butagaz", "ilek", "Gaz de Bordeaux", "OHM Énergie", "Alterna", "Dyneff", "Wekiwi"]
OFFER_NAMES = ["Éco", "Essentielle", "Online", "Verte Fixe", "Standard", "Smart", "Confort", "Tranquille", "Indexée",
               "Prix Bloqué", "Pack Duo", "Zen"]

def _choose_providers(energy, avoid=None, k=3):
    pool = PROVIDERS_GAZ if energy == "gaz" else PROVIDERS_ELEC
    pool = [p for p in pool if not (avoid and p.lower() == str(avoid).lower())]
    random.shuffle(pool)
    return pool[:k]

def _offer_name():
    return random.choice(OFFER_NAMES)

def _round_money(x: float) -> float:
    return round(x / 0.5) * 0.5

def make_base_offers(params: dict, current_total: float) -> List[Dict[str, Any]]:
    conso = float(params["consumption_kwh"])
    energy = params["energy"]
    providers = _choose_providers(energy, avoid=params.get("fournisseur"), k=3)
    discounts = [0.12, 0.11, 0.10]
    out = []
    for i, p in enumerate(providers):
        tgt = current_total * (1.0 - discounts[i])
        jitter = random.uniform(-0.002, 0.002)
        tgt_adj = tgt * (1.0 + jitter)
        abo_share = random.uniform(0.12, 0.22) if energy == "electricite" else random.uniform(0.20, 0.32)
        abo = _round_money(tgt_adj * abo_share)
        price_kwh = max(0.01, (tgt_adj - abo) / conso)
        price_kwh = round(price_kwh, 4)
        out.append({
            "provider": p, "offer_name": _offer_name(), "energy": energy,
            "option": "Base" if energy == "electricite" else None,
            "kva": params.get("kva") if energy == "electricite" else None,
            "price_kwh_ttc": price_kwh, "abonnement_annuel_ttc": abo,
            "total_annuel_estime": abo + price_kwh * conso,
        })
    out.sort(key=lambda x: x["total_annuel_estime"])
    return out

def make_hphc_offers(params: dict, current_total: float) -> List[Dict[str, Any]]:
    if params["energy"] != "electricite":
        return []
    conso = float(params["consumption_kwh"])

    hp_share = params.get("hp_share") or 0.35
    providers = _choose_providers("electricite", avoid=params.get("fournisseur"), k=3)
    discounts = [0.12, 0.11, 0.10]
    out = []
    for i, p in enumerate(providers):
        tgt = current_total * (1.0 - discounts[i]) * (1.0 + random.uniform(-0.002, 0.002))
        abo = _round_money(tgt * random.uniform(0.12, 0.22))
        blended = max(0.01, (tgt - abo) / conso)
        delta = random.uniform(0.02, 0.06)
        hp = max(0.01, blended + delta * (1 - hp_share))
        hc = max(0.01, blended - delta * hp_share)
        out.append({
            "provider": p, "offer_name": f"{_offer_name()} HP/HC", "energy": "electricite",
            "option": "HP/HC", "kva": params.get("kva"),
            "price_kwh_ttc": round(blended, 4), "price_hp_ttc": round(hp, 4), "price_hc_ttc": round(hc, 4),
            "abonnement_annuel_ttc": abo, "total_annuel_estime": abo + blended * conso,
        })
    out.sort(key=lambda x: x["total_annuel_estime"])
    return out
# ───────────────── Vices cachés — Base de règles par fournisseur/offre ─────────────────
# Catégories (ajout de 2 génériques pour atteindre 6 par type)
VC = {
    "ELEC_TRV_SUP": "Tarif supérieur au TRV (à vérifier sur la période de facturation)",
    "ELEC_REMISE_TEMP": "Remise temporaire déguisée (prix d'appel limité dans le temps)",
    "ELEC_VERT_NON_CERT": "Option verte non certifiée (labels/garanties d'origine floues)",
    "ELEC_DOUBLE_ABO": "Double abonnement (compteur secondaire / services additionnels)",
    "ELEC_INDEX_OPAQUE": "Indexation non transparente (référence ambiguë, révision discrétionnaire)",
    "GEN_FRAIS_GESTION": "Frais de service/gestion additionnels peu transparents",

    "GAZ_SUP_REPERE": "Prix > Prix repère CRE pour profil comparable",
    "GAZ_INDEX_SANS_PLAFO": "Tarif indexé sans plafond (exposition forte aux hausses)",
    "GAZ_FRAIS_ABUSIFS": "Frais techniques (mise en service, déplacement) supérieurs aux barèmes GRDF",
    "GAZ_PROMO_TROMPEUSE": "Promotion trompeuse (conditions d’éligibilité restrictives)",
    "GAZ_REVISION_ENGT": "Révision tarifaire possible en cours d’engagement",
    "GEN_PAIEMENT_IMPOSE": "Mode de paiement imposé / pénalités annexes",
}

# Socle générique (peut servir ailleurs)
_BASE_VICES = {
    "electricite": [
        VC["ELEC_TRV_SUP"], VC["ELEC_REMISE_TEMP"], VC["ELEC_VERT_NON_CERT"],
        VC["ELEC_DOUBLE_ABO"], VC["ELEC_INDEX_OPAQUE"], VC["GEN_FRAIS_GESTION"],
    ],
    "gaz": [
        VC["GAZ_SUP_REPERE"], VC["GAZ_INDEX_SANS_PLAFO"], VC["GAZ_FRAIS_ABUSIFS"],
        VC["GAZ_PROMO_TROMPEUSE"], VC["GAZ_REVISION_ENGT"], VC["GEN_PAIEMENT_IMPOSE"],
    ],
}

# Pool garanti à 6 (ordre de remplissage)
_GENERIC_6 = {
    "electricite": _BASE_VICES["electricite"][:],  # déjà 6
    "gaz": _BASE_VICES["gaz"][:],                  # déjà 6
}

def _norm(s: str) -> str:
    import re, unicodedata
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9+ ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

# ───────────────── Exceptions & helpers ─────────────────
class EnergyTypeError(ValueError):
    pass

class EnergyTypeMismatchError(EnergyTypeError):
    pass

def normalize_energy_mode(x: str | None) -> str:
    if not x:
        return "auto"
    m = x.strip().lower()
    mapping = {
        "auto": "auto",
        "gaz": "gaz", "gas": "gaz", "g": "gaz",
        "electricite": "electricite", "électricité": "electricite", "elec": "electricite", "e": "electricite",
        "dual": "dual", "duale": "dual", "duo": "dual", "pack": "dual",
    }
    return mapping.get(m, "invalid")

# ───────────────── Robust signals + scoring + confidence ─────────────────
def detect_energy_signals(raw_text: str) -> dict:
    """
    Retourne un dict:
      {
        "scores": {"gaz": s_g, "electricite": s_e},
        "conf":   {"gaz": c_g, "electricite": c_e},  # [0..1], absolu
        "decision": set(["gaz", "electricite"]),     # décision heuristique
      }
    """
    import math
    if not raw_text:
        return {"scores": {"gaz": 0, "electricite": 0},
                "conf": {"gaz": 0.0, "electricite": 0.0},
                "decision": set()}

    t = _norm(raw_text)  # ascii/lower/espaces

    gas_weights = {
        "pce": 6, "grdf": 5, "gazpar": 5, "ticgn": 5, "coefficient de conversion": 4,
        "pcs": 3, "gaz naturel": 2, "zone gaz": 2, "classe de consommation": 2,
        "m3": 1, "gaz": 1
    }
    elec_weights = {
        "pdl": 6, "enedis": 5, "linky": 4, "kva": 4,
        "heures pleines": 3, "heures creuses": 3, "hp hc": 3,
        "turpe": 3, "electricite": 1, "elec": 1
    }
    marketing_noise = ["electricite et gaz", "électricité et gaz", "elec et gaz",
                       "pack duo", "duale", "dual", "offre duo", "pack dual"]

    def score(weights: dict) -> int:
        s = 0
        for k, w in weights.items():
            s += t.count(k) * w
        return s

    s_g = score(gas_weights)
    s_e = score(elec_weights)

    # Pénalise le bruit marketing (ne doit pas créer une fausse dualité)
    noise_hits = sum(t.count(n) for n in marketing_noise)
    if noise_hits:
        s_g = max(0, s_g - 2 * noise_hits)
        s_e = max(0, s_e - 2 * noise_hits)

    # Confiances absolues (croissent vite avec le score; bornées à 1)
    conf_g = 1.0 - math.exp(-s_g / 8.0)
    conf_e = 1.0 - math.exp(-s_e / 8.0)

    # Décision heuristique (claire et déterministe)
    decision = set()
    # marqueurs durs PCE/PDL: s'ils sont exclusifs, ça tranche
    if "pce" in t and "pdl" not in t:
        decision = {"gaz"}
    elif "pdl" in t and "pce" not in t:
        decision = {"electricite"}
    else:
        if s_g == 0 and s_e == 0:
            decision = set()
        elif abs(s_g - s_e) >= 3:
            decision = {"gaz"} if s_g > s_e else {"electricite"}
        elif max(s_g, s_e) >= 6 and min(s_g, s_e) >= 3:
            decision = {"gaz", "electricite"}
        else:
            decision = {"gaz"} if s_g >= s_e else {"electricite"}

    return {"scores": {"gaz": s_g, "electricite": s_e},
            "conf": {"gaz": float(conf_g), "electricite": float(conf_e)},
            "decision": decision}

def filter_energies(parsed: dict, keep: set[str]) -> dict:
    energies = parsed.get("energies") or []
    def want(t: str) -> bool:
        t = (t or "").strip().lower()
        return any(t.startswith(k) for k in keep)
    kept = [e for e in energies if want(e.get("type"))]
    parsed["energies"] = kept
    return parsed

def ensure_stub(parsed: dict, energy: str) -> dict:
    energies = parsed.get("energies") or []
    if not any(((e.get("type") or "").startswith(energy)) for e in energies):
        stub = {"type": energy}
        if energy == "electricite":
            stub["option"] = "Base"
        energies.append(stub)
        parsed["energies"] = energies
    return parsed

def apply_energy_mode(parsed: dict, raw_text: str,
                      mode: str = "auto",
                      conf_min: float = 0.5,
                      strict: bool = True) -> tuple[dict, dict]:
    """
    Applique le mode d'énergie demandé:
      - mode "auto": détecte et filtre en fonction du PDF
      - mode "gaz"/"electricite": force ce type, mais recheck; si contradiction avec forte confiance, lève une erreur
      - mode "dual": exige forte confiance sur les deux; sinon lève une erreur
    Retourne (parsed_modifie, diagnostics)
    """
    mode = normalize_energy_mode(mode)
    if mode == "invalid":
        raise EnergyTypeError("Paramètre --energy invalide. Utilise: auto | gaz | electricite | dual")

    diag = detect_energy_signals(raw_text)
    dec = set(diag["decision"])
    cg, ce = diag["conf"]["gaz"], diag["conf"]["electricite"]

    if mode == "auto":
        if not dec:
            # Retombe sur l’heuristique existante si aucune décision
            parsed = enforce_single_energy_if_clear(parsed, raw_text)
            return parsed, diag
        parsed = filter_energies(parsed, dec)
        if not parsed.get("energies"):
            # Si GPT n’a rien de valide, crée des stubs pour les types détectés
            for k in dec:
                parsed = ensure_stub(parsed, k)
        return parsed, diag

    if mode in {"gaz", "electricite"}:
        other = "electricite" if mode == "gaz" else "gaz"
        # Si l'autre type est fortement probable, bloque (en strict)
        if strict and diag["conf"][other] >= conf_min and (other in dec) and (mode not in dec):
            raise EnergyTypeMismatchError(
                f"Type demandé: {mode}. Mais la facture ressemble plutôt à {other} "
                f"(confiance {diag['conf'][other]:.2f})."
            )
        # Sinon on force le type demandé
        parsed = filter_energies(parsed, {mode})
        if not parsed.get("energies"):
            parsed = ensure_stub(parsed, mode)
        return parsed, diag

    # mode == "dual"
    if cg >= conf_min and ce >= conf_min:
        parsed = filter_energies(parsed, {"gaz", "electricite"})
        if not parsed.get("energies"):
            parsed = ensure_stub(parsed, "electricite")
            parsed = ensure_stub(parsed, "gaz")
        else:
            # si un seul présent, complète l’autre en stub
            parsed = ensure_stub(parsed, "electricite")
            parsed = ensure_stub(parsed, "gaz")
        return parsed, diag
    raise EnergyTypeMismatchError(
        f"Type demandé: dual. Indices insuffisants dans le PDF "
        f"(confiance gaz={cg:.2f}, élec={ce:.2f} ; besoin ≥ {conf_min:.2f})."
    )


def _match_any(name: str, patterns) -> bool:
    nm = _norm(name or "")
    for p in patterns or []:
        if _norm(p) and _norm(p) in nm:
            return True
    return False

# ───────────────── Catalogue des vices par fournisseur/offre (extraits) ─────────────────
VICES_DB = {
    "electricite": {
        "edf": {
            "provider_vices": [VC["ELEC_INDEX_OPAQUE"]],
            "offers": [
                {"name_patterns": ["Tarif Bleu", "TRV"], "offer_vices": []},
                {"name_patterns": ["Vert", "Vert Electrique", "Vert Électrique", "Vert Fixe"], "offer_vices": [VC["ELEC_VERT_NON_CERT"]]},
            ],
        },
        "engie": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Elec Reference", "Référence", "Reference 3 ans", "Tranquillite", "Tranquillité"], "offer_vices": [VC["ELEC_TRV_SUP"]]},
                {"name_patterns": ["Online", "Happ e"], "offer_vices": [VC["ELEC_REMISE_TEMP"]]},
            ],
        },
        "totalenergies": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Online", "Standard Online", "Heures Creuses Online"], "offer_vices": [VC["ELEC_REMISE_TEMP"], VC["ELEC_INDEX_OPAQUE"]]},
                {"name_patterns": ["Verte", "Verte Fixe"], "offer_vices": [VC["ELEC_VERT_NON_CERT"], VC["ELEC_TRV_SUP"]]},
            ],
        },
        "ohm energie": {
            "provider_vices": [VC["ELEC_REMISE_TEMP"], VC["ELEC_INDEX_OPAQUE"]],
            "offers": [
                {"name_patterns": ["Eco", "Classique", "Petite Conso", "Beaux Jours"], "offer_vices": [VC["ELEC_REMISE_TEMP"], VC["ELEC_INDEX_OPAQUE"]]},
            ],
        },
        "mint": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Online", "Smart"], "offer_vices": [VC["ELEC_REMISE_TEMP"], VC["ELEC_INDEX_OPAQUE"]]},
                {"name_patterns": ["Vert", "Verte", "100% vert"], "offer_vices": [VC["ELEC_VERT_NON_CERT"], VC["ELEC_TRV_SUP"]]},
            ],
        },
        "ekwateur": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Verte", "Bois", "Hydro", "Eolien", "Éolien"], "offer_vices": [VC["ELEC_VERT_NON_CERT"], VC["ELEC_TRV_SUP"]]},
                {"name_patterns": ["Indexee", "Indexée"], "offer_vices": [VC["ELEC_INDEX_OPAQUE"]]},
            ],
        },
        "enercoop": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Cooperative", "Coopérative"], "offer_vices": [VC["ELEC_TRV_SUP"]]},
            ],
        },
        "vattenfall": {"provider_vices": [], "offers": [{"name_patterns": ["Eco", "Fixe"], "offer_vices": [VC["ELEC_TRV_SUP"]]}]},
        "mega": {"provider_vices": [], "offers": [{"name_patterns": ["Super", "Online", "Variable"], "offer_vices": [VC["ELEC_REMISE_TEMP"], VC["ELEC_INDEX_OPAQUE"]]}]},
        "wekiwi": {"provider_vices": [], "offers": [{"name_patterns": ["Kiwhi", "Online", "Spot"], "offer_vices": [VC["ELEC_INDEX_OPAQUE"]]}]},
        "octopus": {"provider_vices": [], "offers": [{"name_patterns": ["Agile", "Spot", "Heures Creuses dynamiques"], "offer_vices": [VC["ELEC_INDEX_OPAQUE"]]}]},
        "plum": {"provider_vices": [], "offers": [{"name_patterns": ["Plum", "Plüm"], "offer_vices": [VC["ELEC_VERT_NON_CERT"]]}]},
        "ilek": {"provider_vices": [], "offers": [{"name_patterns": ["local", "producteur", "eolien", "hydro", "Éolien"], "offer_vices": [VC["ELEC_VERT_NON_CERT"], VC["ELEC_TRV_SUP"]]}]},
        "alpiq": {"provider_vices": [], "offers": [{"name_patterns": ["Eco", "Online"], "offer_vices": [VC["ELEC_TRV_SUP"]]}]},
        "happ e": {"provider_vices": [], "offers": [{"name_patterns": ["Happ e"], "offer_vices": [VC["ELEC_REMISE_TEMP"]]}]},
    },

    "gaz": {
        "engie": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Reference", "Référence", "Tranquillite", "Tranquillité", "Fixe"], "offer_vices": [VC["GAZ_SUP_REPERE"]]},
                {"name_patterns": ["Online", "Happ e"], "offer_vices": [VC["GAZ_PROMO_TROMPEUSE"]]},
            ],
        },
        "edf": {"provider_vices": [], "offers": [{"name_patterns": ["Avantage Gaz", "Fixe"], "offer_vices": [VC["GAZ_SUP_REPERE"]]}]},
        "totalenergies": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Online", "Standard"], "offer_vices": [VC["GAZ_PROMO_TROMPEUSE"]]},
                {"name_patterns": ["Verte", "Biogaz"], "offer_vices": [VC["GAZ_SUP_REPERE"]]},
            ],
        },
        "mint": {"provider_vices": [], "offers": [{"name_patterns": ["Biogaz", "Online"], "offer_vices": [VC["GAZ_SUP_REPERE"], VC["GAZ_PROMO_TROMPEUSE"]]}]},
        "ekwateur": {
            "provider_vices": [],
            "offers": [
                {"name_patterns": ["Biogaz", "Vert"], "offer_vices": [VC["GAZ_SUP_REPERE"]]},
                {"name_patterns": ["Indexee", "Indexée", "Spot"], "offer_vices": [VC["GAZ_INDEX_SANS_PLAFO"]]},
            ],
        },
        "gaz de bordeaux": {"provider_vices": [], "offers": [{"name_patterns": ["Variable", "Indexee", "Indexée", "Spot"], "offer_vices": [VC["GAZ_INDEX_SANS_PLAFO"]]}]},
        "wekiwi": {"provider_vices": [], "offers": [{"name_patterns": ["Spot", "Variable", "Kiwhi"], "offer_vices": [VC["GAZ_INDEX_SANS_PLAFO"]]}]},
        "dyneff": {"provider_vices": [], "offers": [{"name_patterns": ["Fixe", "Confort"], "offer_vices": [VC["GAZ_SUP_REPERE"]]}]},
        "butagaz": {"provider_vices": [], "offers": [{"name_patterns": ["Online", "Confort"], "offer_vices": [VC["GAZ_PROMO_TROMPEUSE"]]}]},
        "ohm energie": {"provider_vices": [VC["GAZ_PROMO_TROMPEUSE"], VC["GAZ_INDEX_SANS_PLAFO"]], "offers": [{"name_patterns": ["Eco", "Classique"], "offer_vices": [VC["GAZ_PROMO_TROMPEUSE"], VC["GAZ_INDEX_SANS_PLAFO"]]}]},
        "ilek": {"provider_vices": [], "offers": [{"name_patterns": ["Biogaz", "Local"], "offer_vices": [VC["GAZ_SUP_REPERE"]]}]},
        "mega": {"provider_vices": [], "offers": [{"name_patterns": ["Online", "Variable"], "offer_vices": [VC["GAZ_INDEX_SANS_PLAFO"]]}]},
        "alterna": {"provider_vices": [], "offers": [{"name_patterns": ["Fixe", "Tranquille"], "offer_vices": [VC["GAZ_SUP_REPERE"]]}]},
        "plenitude": {"provider_vices": [], "offers": [{"name_patterns": ["Fixe", "Indexee", "Indexée"], "offer_vices": [VC["GAZ_SUP_REPERE"], VC["GAZ_INDEX_SANS_PLAFO"]]}]},
    },
}
# ───────────────── Vices cachés (ASCII, no emoji) ─────────────────
def vices_caches_for(energy: str, fournisseur: Optional[str], offre: Optional[str], n_items: int = 6) -> list[str]:
    """
    Retourne exactement `n_items` vices cachés.
    - 1) on collecte les vices spécifiques (fournisseur/offre) s'ils existent,
    - 2) on complète avec le pool générique (6 par type),
    - 3) on dédoublonne et on tronque/complète à `n_items`.
    """
    energy_key = "gaz" if (energy or "").lower().startswith("gaz") else "electricite"
    prefix = "[ELEC] " if energy_key == "electricite" else "[GAZ] "

    # 1) spécifiques (fournisseur/offre)
    specifics: list[str] = []
    f_norm, o_norm = _norm(fournisseur or ""), _norm(offre or "")
    provider_db = None
    db = VICES_DB.get(energy_key, {})

    if f_norm:
        for prov_key, prov_rules in db.items():
            if _norm(prov_key) in f_norm or f_norm in _norm(prov_key):
                provider_db = prov_rules
                break

    if provider_db:
        # vices généraux du fournisseur
        specifics.extend(provider_db.get("provider_vices", []))
        # vices spécifiques si l'offre matche
        for rule in provider_db.get("offers", []):
            if _match_any(offre, rule.get("name_patterns", [])):
                specifics.extend(rule.get("offer_vices", []))

    # 2) pool générique garanti à 6
    generic_pool = list(_GENERIC_6.get(energy_key, []))

    # 3) merge: spécifiques d'abord, puis génériques, avec dédoublonnage
    merged = []
    seen = set()
    for src in (specifics + generic_pool):
        if src not in seen and src:
            merged.append(prefix + src)
            seen.add(src)

    # 4) si on a moins que n_items (ça ne devrait pas arriver), on recycle le generic_pool
    i = 0
    while len(merged) < n_items and generic_pool:
        candidate = prefix + generic_pool[i % len(generic_pool)]
        if candidate not in merged:
            merged.append(candidate)
        i += 1

    # 5) tronque à n_items
    return merged[:n_items]

# ───────────────── Styles & PDF Helpers ─────────────────
def get_pioui_styles() -> Dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    styles["BodyText"].fontName = BASE_FONT
    styles["Italic"].fontName = "Poppins-Italic" if IS_POPPINS_AVAILABLE else "Helvetica-Oblique"

    common_props = {"wordWrap": 'CJK', "splitLongWords": True}

    styles.add(ParagraphStyle(
        name="H1", fontName=BOLD_FONT, fontSize=22, leading=28,
        textColor=colors.HexColor(PALETTE["primary_blue"]), spaceAfter=16, **common_props
    ))
    styles.add(ParagraphStyle(
        name="H2", fontName=BOLD_FONT, fontSize=14, leading=18,
        textColor=colors.HexColor(PALETTE["text_dark"]), spaceAfter=8, **common_props
    ))
    styles.add(ParagraphStyle(
        name="Body", fontName=BASE_FONT, fontSize=10, leading=14,
        textColor=colors.HexColor(PALETTE["text_dark"]), **common_props
    ))
    styles.add(ParagraphStyle(
        name="Muted", fontName=BASE_FONT, fontSize=9, leading=12,
        textColor=colors.HexColor(PALETTE["text_muted"]), **common_props
    ))
    styles.add(ParagraphStyle(
        name="ItalicMuted", parent=styles["Muted"],
        fontName="Poppins-Italic" if IS_POPPINS_AVAILABLE else "Helvetica-Oblique"
    ))
    styles.add(ParagraphStyle(
        name="BodyRight", parent=styles["Body"], alignment=TA_RIGHT
    ))
    styles.add(ParagraphStyle(
        name="FooterText", fontName=BASE_FONT, fontSize=8, leading=11,
        textColor=colors.white, **common_props
    ))
    styles.add(ParagraphStyle(  # Small yellow badge text
        name="Badge", fontName=BOLD_FONT, fontSize=9.2, leading=12,
        textColor=colors.HexColor(PALETTE["dark_navy"])
    ))
    return styles

def draw_header_footer(title_right=""):
    def _draw(canv: rl_canvas.Canvas, doc):
        canv.saveState()
        width, height = A4

        # === Header ===
        canv.setFillColor(colors.HexColor(PALETTE["dark_navy"]))
        canv.rect(0, height - 50, width, 50, stroke=0, fill=1)
        # Yellow accent bar
        canv.setFillColor(colors.HexColor(PALETTE["brand_yellow"]))
        canv.rect(0, height - 52, 160, 2, stroke=0, fill=1)

        if LOGO_PATH and os.path.exists(LOGO_PATH):
            try:
                logo = RLImage(LOGO_PATH, width=95, height=35)
                logo.drawOn(canv, 2 * cm, height - 40)
            except Exception:
                canv.setFillColor(colors.white)
                canv.setFont(BOLD_FONT, 12)
                canv.drawString(2 * cm, height - 32, "Pioui")

        canv.setFillColor(colors.black)
        canv.setFont(BASE_FONT, 10)
        canv.drawRightString(width - 2 * cm, height - 28, "Rapport Comparatif Énergie")
        canv.setFont(BASE_FONT, 8)
        canv.setFillColor(colors.HexColor(PALETTE["text_muted"]))
        canv.drawRightString(width - 2 * cm, height - 40, title_right)

        # === Footer ===
        canv.setFillColor(colors.HexColor(PALETTE["dark_navy"]))
        canv.rect(0, 0, width, 70, stroke=0, fill=1)
        # Yellow thin line above footer content
        canv.setFillColor(colors.HexColor(PALETTE["brand_yellow"]))
        canv.rect(0, 68, width, 2, stroke=0, fill=1)

        # Footer content
        y_pos = 55
        canv.setFillColor(colors.HexColor("#1E293B"))
        canv.setFont(BASE_FONT, 8)
        canv.drawString(2 * cm, y_pos, PIOUI["url"])
        canv.drawCentredString(width / 2, y_pos, PIOUI["name"])
        canv.drawRightString(width - 2 * cm, y_pos, f"Page {doc.page}")

        y_pos -= 15
        canv.setFillColor(colors.HexColor(PALETTE["text_muted"]))
        canv.drawString(2 * cm, y_pos, PIOUI["email"])
        canv.drawCentredString(width / 2, y_pos, PIOUI["addr"])

        y_pos -= 15
        canv.setFillColor(colors.HexColor(PALETTE["text_muted"]))
        canv.drawCentredString(width / 2, y_pos, PIOUI["tel"])

        y_pos -= 8
        canv.setStrokeColor(colors.HexColor(PALETTE["border_light"]))
        canv.line(2 * cm, y_pos, width - 2 * cm, y_pos)
        y_pos -= 12
        canv.setFont(BASE_FONT, 7)
        canv.drawCentredString(width / 2, y_pos, PIOUI["copyright"])
        canv.restoreState()
    return _draw

def create_modern_table(rows, col_widths_pts, numeric_cols=None, zebra=True):
    numeric_cols = set(numeric_cols or [])
    table = Table(rows, colWidths=col_widths_pts, repeatRows=1)

    style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(PALETTE["table_header"])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(PALETTE["text_dark"])),
        ('FONTNAME', (0, 0), (-1, 0), BOLD_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 9.5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        # Yellow underline under header
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor(PALETTE["brand_yellow"])),

        ('FONTNAME', (0, 1), (-1, -1), BASE_FONT),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(PALETTE["text_dark"])),
        ('VALIGN', (0, 0), (-1, -1), "MIDDLE"),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0,0), (-1,-1), 0.25, colors.HexColor(PALETTE["border_light"])),
    ]

    if zebra and len(rows) > 2:
        for r in range(1, len(rows)):
            if r % 2 == 1:
                style.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor(PALETTE["bg_light"])))

    for c in numeric_cols:
        style.append(("ALIGN", (c, 1), (c, -1), "RIGHT"))

    table.setStyle(TableStyle(style))
    return table

# Formatting helpers
def _fmt_euro(x: Optional[float]) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",") if x is not None else "—"

def _fmt_kwh(x: Optional[float]) -> str:
    return f"{x:,.0f} kWh".replace(",", " ") if x is not None else "—"

def enforce_single_energy_if_clear(parsed: dict, raw_text: str) -> dict:
    """
    If the parser returned both energies but the PDF clearly points to one,
    drop the other. Rules precedence:
      1) Strong tokens: PDL => electricité ; PCE => gaz
      2) If only one token appears, keep that energy.
      3) If neither/ both appear, use robust keyword scoring.
    """
    try:
        energies = parsed.get("energies") or []
        if len(energies) <= 1:
            return parsed
        if not raw_text:
            return parsed

        txt = raw_text.lower()

        # Strong tokens
        has_pdl = "pdl" in txt
        has_pce = "pce" in txt

        # If exactly one appears, force it
        if has_pdl and not has_pce:
            parsed["energies"] = [e for e in energies if (e.get("type") or "").strip().lower().startswith("elect")]
            return parsed
        if has_pce and not has_pdl:
            parsed["energies"] = [e for e in energies if (e.get("type") or "").strip().lower().startswith("gaz")]
            return parsed

        # Robust scoring if strong tokens are inconclusive
        score_e = (
            txt.count("électricité") + txt.count("electricite") +
            txt.count("elec") + txt.count("compteur") + txt.count("enedis") +
            3 * txt.count("pdl")
        )
        score_g = (
            txt.count("gaz") + txt.count("grdf") + txt.count("gaz naturel") +
            3 * txt.count("pce")
        )

        # Clear margin? keep the dominant one
        if abs(score_e - score_g) >= 2:
            keep = "electricite" if score_e > score_g else "gaz"
            parsed["energies"] = [
                e for e in energies if (e.get("type") or "").strip().lower().startswith(keep)
            ]
        return parsed
    except Exception:
        return parsed

# ───────────────── PDF Builder ─────────────────
def build_pdfs(parsed: dict, sections: List[Dict[str, Any]], combined_dual: List[Dict[str, Any]]) -> Tuple[bytes, bytes]:
    """
        Generates two PDF reports in memory and returns them as byte strings.

        Returns:
            A tuple containing (non_anonymous_pdf_bytes, anonymous_pdf_bytes).
        """

    def render(anonymous: bool):
        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,  # Write directly to the buffer
            pagesize=A4,
            leftMargin=2 * cm, rightMargin=2 * cm,
            topMargin=2.5 * cm + 50,
            bottomMargin=2.0 * cm + 60
        )
        s = get_pioui_styles()
        story = []
        W = doc.width

        def cw(*ratios):
            total = float(sum(ratios))
            return [W * (r / total) for r in ratios]

        H1 = lambda x: Paragraph(x, s["H1"])
        H2 = lambda x: Paragraph(x, s["H2"])
        P  = lambda x: Paragraph(x if isinstance(x, str) else "—", s["Body"])
        PR = lambda x: Paragraph(x if isinstance(x, str) else "—", s["BodyRight"])
        PM = lambda x: Paragraph(x if isinstance(x, str) else "—", s["Muted"])

        client = parsed.get("client") or {}
        right_title = client.get("name") or ""
        on_page = draw_header_footer(title_right=right_title)

        story.append(H1("Votre Rapport Comparatif"))

        story.append(P(f"<b>Client :</b> {client.get('name') or '—'}"))
        if client.get("address"):
            story.append(PM(client["address"]))
        story.append(Paragraph(f"<i>Généré le {date.today().strftime('%d/%m/%Y')}</i>", s["ItalicMuted"]))
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", color=colors.HexColor(PALETTE["border_light"]), thickness=1))
        story.append(Spacer(1, 10))

        # — Période
        periode = parsed.get("periode") or {}
        p_de, p_a, p_j = periode.get("de"), periode.get("a"), periode.get("jours")
        if p_de and p_a:
            story.append(H2("Période de facturation analysée"))
            story.append(P(f"Du <b>{p_de}</b> au <b>{p_a}</b> (soit {p_j or '~'} jours)"))
            story.append(Spacer(1, 12))

        # — Sections per energy type
        for sec in sections:
            params = sec["params"]
            rows = sec["rows"]
            if not sec["rows"]:
                continue
            energy_label = "Électricité" if params["energy"] == "electricite" else "Gaz"

            # 1) Offre actuelle
            story.append(H1(f"Analyse {energy_label}"))
            story.append(H2("Votre offre actuelle"))

            p_de_sec = params.get("period_start_date")
            p_a_sec = params.get("period_end_date")
            p_j_sec = params.get("period_days")
            if p_de_sec and p_a_sec and p_j_sec:
                story.append(
                    P(f"<i>Période analysée : Du <b>{p_de_sec}</b> au <b>{p_a_sec}</b> (soit {p_j_sec} jours)</i>"))
                story.append(Spacer(1, 6))

            conso_period = params.get("period_kwh")
            total_period = params.get("total_ttc_period")
            avg_price = (total_period / conso_period) if (total_period and conso_period) else None
            annual_now = current_annual_total(params)

            head = [P("Fournisseur"), P("Offre"), P("Puissance"), P("Option"), P("Conso. (période)"),
                    PR("Total TTC (période)"), PR("Prix moyen (€/kWh)"), PR("Estimation annuelle actuelle")]
            row = [P(f"<b>{params.get('fournisseur') or '—'}</b>"), P(params.get('offre') or '—'),
                   P(str(params.get('kva')) if params["energy"] == "electricite" else "—"),
                   P(params.get('option') if params["energy"] == "electricite" else "—"), P(_fmt_kwh(conso_period)),
                   PR(_fmt_euro(total_period)), PR(f"{avg_price:.4f} €/kWh" if avg_price else "—"),
                   PR(_fmt_euro(annual_now))]
            story.append(
                create_modern_table([head, row], cw(1.3, 1.8, 0.9, 0.9, 1.2, 1.2, 1.2, 1.6), numeric_cols={4, 5, 6, 7},
                                    zebra=False))
            story.append(Spacer(1, 12))

            # 2) Comparatif
            story.append(H2(f"Comparatif des offres {energy_label}"))
            if anonymous:
                # Créer des maps locales pour chaque type d'offre, basées sur leur ordre d'apparition
                base_offers = [o for o in rows if o.get("option") in (None, "Base")]
                hphc_offers = [o for o in rows if o.get("option") == "HP/HC"]
                base_map = {o['provider']: f"Fournisseur Alternatif {chr(65 + i)}" for i, o in
                            enumerate(base_offers[:3])}
                hphc_map = {o['provider']: f"Fournisseur Alternatif {chr(65 + i)}" for i, o in
                            enumerate(hphc_offers[:3])}

            def get_anon_name(provider_name, offer_option):
                if not anonymous: return provider_name or "—"
                # Choisit la bonne map (base ou hphc) en fonction de l'option de l'offre
                current_map = hphc_map if offer_option == "HP/HC" else base_map
                return current_map.get(provider_name, provider_name or "—")

            if params["energy"] == "electricite":
                base = [o for o in rows if o.get("option") in (None, "Base")]
                hphc = [o for o in rows if o.get("option") == "HP/HC"]

                def map_b(o):
                    return [P(get_anon_name(o["provider"], "Base")), P(o["offer_name"]),
                            PR(f"{o['price_kwh_ttc']:.4f} €/kWh"), PR(_fmt_euro(o["abonnement_annuel_ttc"])),
                            PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")]

                if base:
                    story.append(P("<b> Option Base</b>"))
                    thead = [P("Fournisseur"), P("Offre"), PR("Prix kWh TTC"), PR("Abonnement / an"),
                             PR("Total estimé / an")]
                    story.append(
                        create_modern_table([thead] + [map_b(o) for o in base[:3]], cw(1.2, 2.0, 1.0, 1.2, 1.2),
                                            numeric_cols={2, 3, 4}))
                    story.append(Spacer(1, 6))

                def map_h(o):
                    return [P(get_anon_name(o["provider"], "HP/HC")), P(o["offer_name"]),
                            PR(f"{o['price_hp_ttc']:.4f} / {o['price_hc_ttc']:.4f} €/kWh"),
                            PR(_fmt_euro(o["abonnement_annuel_ttc"])),
                            PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")]

                if hphc:
                    story.append(P("<b> Option Heures Pleines / Heures Creuses</b>"))
                    thead2 = [P("Fournisseur"), P("Offre"), PR("Prix HP / HC"), PR("Abonnement / an"),
                              PR("Total estimé / an")]
                    story.append(
                        create_modern_table([thead2] + [map_h(o) for o in hphc[:3]], cw(1.2, 1.8, 1.4, 1.2, 1.2),
                                            numeric_cols={2, 3, 4}))
                    story.append(Spacer(1, 8))
            else:  # Gaz
                def map_g(o):
                    return [P(get_anon_name(o["provider"], "Base")), P(o["offer_name"]),
                            PR(f"{o['price_kwh_ttc']:.4f} €/kWh"), PR(_fmt_euro(o["abonnement_annuel_ttc"])),
                            PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")]

                thead = [P("Fournisseur"), P("Offre"), PR("Prix kWh TTC"), PR("Abonnement / an"),
                         PR("Total estimé / an")]
                story.append(create_modern_table([thead] + [map_g(o) for o in rows[:3]], cw(1.2, 2.0, 1.0, 1.2, 1.2),
                                                 numeric_cols={2, 3, 4}))
                story.append(Spacer(1, 8))

            # 3) Vices cachés ...
            story.append(H2("Points de vigilance (Vices cachés)"))
            story.append(PM("Analyse sur l’offre actuelle et les alternatives proposées."))
            story.append(Spacer(1, 4))
            bullets = vices_caches_for(params["energy"], params.get("fournisseur"), params.get("offre"))
            for b in bullets:
                story.append(Paragraph(f"• {b}", s["Body"]))
            story.append(Spacer(1, 10))

            badge = Table([[Paragraph("Attention aux clauses et indexations", s["Badge"])]], colWidths=[W])
            badge.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PALETTE["brand_yellow"])),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                                       ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
            story.append(badge)
            story.append(Spacer(1, 12))

            # 4) Notre recommandation
            story.append(H2("Notre recommandation"))
            best = min(rows, key=lambda x: x["total_annuel_estime"]) if rows else None
            curr = annual_now
            if best and curr and best.get("total_annuel_estime"):
                delta = curr - best["total_annuel_estime"]
                if delta > 0:
                    # ✅ MODIFIÉ : La recommandation utilise la même logique pour trouver le nom anonymisé correct
                    reco_provider_name = get_anon_name(best['provider'], best.get('option'))
                    reco_text = Paragraph(
                        f"Économisez jusqu'à <font size='14' color='{PALETTE['saving_red']}'><b>{_fmt_euro(delta)}</b></font> "
                        f"par an en passant chez <b>{reco_provider_name}</b> avec l'offre <b>{best['offer_name']}</b>."
                        f" Pour approfondir cette recommandation et obtenir un conseil personnalisé, "
                        f"nos experts sont joignables au <b>{PIOUI['tel']}</b>.", s["Body"]
                    )
                else:
                    reco_text = Paragraph("Votre offre actuelle semble compétitive. Aucune économie nette identifiée.",
                                          s["Body"])
            else:
                reco_text = Paragraph("Données insuffisantes pour une recommandation chiffrée fiable.", s["Body"])

            reco_box = Table([[reco_text]], colWidths=[W])
            reco_box.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PALETTE["bg_light"])),
                                          ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(PALETTE["border_light"])),
                                          ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                                          ('TOPPADDING', (0, 0), (-1, -1), 12),
                                          ('BOTTOMPADDING', (0, 0), (-1, -1), 12)]))
            story.append(reco_box)
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width="100%", color=colors.HexColor(PALETTE["border_light"]), thickness=1))
            story.append(Spacer(1, 12))

        # Pack Dual (optional)
        if combined_dual:
            # ✅ MODIFIÉ : Création d'une map locale pour le pack dual
            dual_map = {}
            if anonymous:
                dual_map = {o['provider']: f"Fournisseur Alternatif {chr(65 + i)}" for i, o in
                            enumerate(combined_dual[:3])}

            story.append(H1("Pack Dual (Électricité + Gaz)"))

            def map_d(o):
                provider_name = dual_map.get(o["provider"], o["provider"]) if anonymous else o["provider"]
                return [P(provider_name), P(o["offer_name"]), PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")]

            thead = [P("Fournisseur"), P("Offres combinées"), PR("Total estimé (élec+gaz)")]
            story.append(create_modern_table([thead] + [map_d(o) for o in combined_dual[:3]], cw(1.3, 3.0, 1.2),
                                             numeric_cols={2}))
            story.append(Spacer(1, 10))
        # 5) Méthodologie
        story.append(H2("Méthodologie & Fiabilité des données"))
        story.append(Paragraph(
            "Les données de ce rapport proviennent de votre facture, d’offres publiques de référence, et de barèmes officiels. Les comparaisons sont estimées à partir d’hypothèses réalistes pour illustrer des économies potentielles.",
            s["Muted"]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<b>Rapport indépendant</b>, sans publicité ni affiliation. Son seul but : identifier vos économies possibles.",
            s["Muted"]))

        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        # Get the byte value from the buffer
        pdf_bytes = buffer.getvalue()
        buffer.close()

        print(f"✅ In-memory PDF report generated (anonymous={anonymous}, size={len(pdf_bytes) / 1024:.1f} KB).")
        return pdf_bytes

    # Generate both PDF versions in memory
    non_anon_bytes = render(anonymous=False)
    anon_bytes = render(anonymous=True)

    # Return the raw bytes
    return non_anon_bytes, anon_bytes


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def process_invoice_file(pdf_path: str,
                         energy_mode: str = "auto",
                         confidence_min: float = 0.5,
                         strict: bool = True) -> Tuple[bytes, bytes]:
    """
    Processes a PDF invoice file and returns the generated reports as raw bytes.
    This version is modified for stateless API usage and does not write report files to disk.
    """
    pdf_path = os.path.abspath(pdf_path)

    # --- All processing logic remains the same ---
    text = extract_text_from_pdf(pdf_path)
    parsed = None
    if text and len(text) > 60:
        print("[INFO] PDF basé sur le texte trouvé. Analyse avec GPT...")
        raw = parse_text_with_gpt(text)
        try:
            parsed = json.loads(raw)
        except Exception:
            print("[AVERTISSEMENT] Échec de l'analyse JSON. Retour à l'OCR...")
    if not parsed:
        print("[INFO] Le PDF est basé sur des images ou l'analyse de texte a échoué. Utilisation de l'OCR via GPT-4o (toutes les pages)...")
        try:
            # Note: This part still creates temporary image files from the PDF for OCR, which is necessary.
            out_dir = os.path.dirname(pdf_path)
            basename = os.path.splitext(os.path.basename(pdf_path))[0]
            pages = convert_from_path(pdf_path, dpi=200)
            if not pages:
                raise ValueError("No pages converted from PDF.")

            all_ocr_text = []
            for i, page in enumerate(pages):
                tmp_img = os.path.join(out_dir, f"{basename}_page{i + 1}_temp.png")
                page.save(tmp_img, "PNG")
                page_text = ocr_invoice_with_gpt(tmp_img)
                all_ocr_text.append(f"=== PAGE {i + 1} ===\n{page_text}")
                os.remove(tmp_img)

            combined_ocr = "\n\n".join(all_ocr_text)
            raw = parse_text_with_gpt(combined_ocr)
            parsed = json.loads(raw)

        except Exception as e:
            print(f"[ERREUR] Échec de l'OCR et de l'analyse : {e}. Utilisation de données de secours.")
            parsed = {
                "client": {"name": None, "address": None, "zipcode": "75001"},
                "periode": {"de": None, "a": None, "jours": None},
                "energies": [{"type": "electricite", "fournisseur": None, "offre": None, "option": "Base", "puissance_kVA": 6, "conso_kwh": 3500, "total_ttc": None}]
            }

    periode = parsed.get("periode") or {}
    if not periode.get("jours") and periode.get("de") and periode.get("a"):
        d1, d2 = _parse_date_fr(periode["de"]), _parse_date_fr(periode["a"])
        if d1 and d2:
            periode["jours"] = (d2 - d1).days
            parsed["periode"] = periode

    parsed, _diag = apply_energy_mode(parsed, text, mode=energy_mode, conf_min=confidence_min, strict=strict)

    energies = parsed.get("energies") or []
    if not energies:
        energies = [{"type": (parsed.get("type_facture") or "electricite"), "fournisseur": parsed.get("fournisseur"), "offre": parsed.get("offre"), "option": parsed.get("option"), "puissance_kVA": parsed.get("puissance_kVA"), "conso_kwh": parsed.get("consommation_kWh"), "total_ttc": parsed.get("total_TTC")}]

    sections = []
    for e in energies:
        params = params_from_energy(parsed, e, text)
        curr = current_annual_total(params)
        offers = []
        if params["energy"] == "electricite":
            offers += make_base_offers(params, curr)
            offers += make_hphc_offers(params, curr)
        else:
            offers += make_base_offers(params, curr)
        sections.append({"params": params, "rows": offers})

    combined_dual = []
    has_elec = any(s["params"]["energy"] == "electricite" for s in sections)
    has_gaz = any(s["params"]["energy"] == "gaz" for s in sections)
    if has_elec and has_gaz:
        elec_rows = next((s["rows"] for s in sections if s["params"]["energy"] == "electricite"), [])
        gaz_rows = next((s["rows"] for s in sections if s["params"]["energy"] == "gaz"), [])
        if elec_rows and gaz_rows:
            for i in range(min(3, len(elec_rows), len(gaz_rows))):
                provider = random.choice([elec_rows[i]["provider"], gaz_rows[i]["provider"]])
                combined_dual.append({
                    "provider": provider,
                    "offer_name": f"{elec_rows[i]['offer_name']} + {gaz_rows[i]['offer_name']}",
                    "total_annuel_estime": elec_rows[i]["total_annuel_estime"] + gaz_rows[i]["total_annuel_estime"],
                })
            combined_dual.sort(key=lambda x: x["total_annuel_estime"])

    # The function now returns the bytes directly from the modified build_pdfs function
    return build_pdfs(parsed, sections, combined_dual)

_PIXTRAL_SYSTEM = (
    "You extract structured data from French electricity/gas invoices. "
    "Return ONLY a JSON object (no prose, no markdown). "
    "If something is not visible, return an empty string for that field."
)

_PIXTRAL_USER_INSTRUCTIONS = """\
From these image(s) of a French utility invoice, return this JSON:

{
  "type_facture": "electricite|gaz|dual",
  "client": {"name":"", "address":"", "zipcode":""},
  "periode": {"de":"JJ/MM/AAAA", "a":"JJ/MM/AAAA", "jours":""},
  "energies": [
    {
      "type":"electricite|gaz",
      "fournisseur":"",
      "offre":"",
      "option":"Base|Heures Creuses|HP/HC",
      "puissance_kVA":"",
      "conso_kwh_total":"",
      "conso_hc_kwh":"",
      "conso_hp_kwh":"",
      "prix_hc_eur_kwh":"",
      "prix_hp_eur_kwh":"",
      "abonnement_ttc":"",
      "total_ttc":""
    }
  ]
}

Rules:
- Copy numbers as printed (e.g., '98,68 €', '0,1894'); do not invent values.
- Use empty string "" for any unknown field.
- Use French field names exactly as shown.
"""

def _fr_num(s):
    import re
    if not isinstance(s, str): return None
    x = re.sub(r"[^\d,.\-]", "", s)
    if "," in x and "." in x: x = x.replace(".", "").replace(",", ".")
    elif "," in x: x = x.replace(",", ".")
    try: return float(x)
    except: return None

def _extract_json_loose(s: str) -> dict:
    import json, re
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))

def normalize_pixtral_json(data: dict) -> dict:
    """Coerce fields to what the pipeline expects."""
    import re

    # periode.jours -> int if str
    j = (data.get("periode") or {}).get("jours")
    if isinstance(j, str):
        m = re.search(r"\d+", j)
        data["periode"]["jours"] = int(m.group(0)) if m else None

    # fill zipcode if missing (extract from address)
    cli = data.get("client") or {}
    if (cli.get("zipcode") in (None, "")) and cli.get("address"):
        m = re.search(r"\b\d{5}\b", cli["address"])
        if m:
            cli["zipcode"] = m.group(0)
            data["client"] = cli

    energies = data.get("energies") or []
    for e in energies:
        # Normalize option
        opt = (e.get("option") or "").strip().lower()
        if opt in {"heures creuses", "hp/hc", "heures pleines/creuses", "heures pleines et creuses", "hc/hp", "hp hc"}:
            e["option"] = "HP/HC"
        elif opt in {"base", "option base"}:
            e["option"] = "Base"

        # Numbers => floats
        for k in ("conso_kwh_total","conso_hc_kwh","conso_hp_kwh",
                  "prix_hc_eur_kwh","prix_hp_eur_kwh",
                  "abonnement_ttc","total_ttc"):
            if k in e and isinstance(e[k], str):
                e[k] = _fr_num(e[k])

        # puissance -> int
        if isinstance(e.get("puissance_kVA"), str):
            m = re.search(r"\d+", e["puissance_kVA"])
            e["puissance_kVA"] = int(m.group(0)) if m else None

        # Add legacy key  pipeline expects
        if e.get("conso_kwh") is None and e.get("conso_kwh_total") is not None:
            e["conso_kwh"] = e["conso_kwh_total"]

        # Fix total kWh if inconsistent with HP/HC
        hp = e.get("conso_hp_kwh") or 0
        hc = e.get("conso_hc_kwh") or 0
        if (hp or hc):
            s = (hp or 0) + (hc or 0)
            tot = e.get("conso_kwh_total")
            if tot is None or (s and abs(s - tot) / max(s, 1) > 0.2) or (tot and tot > 20000):
                e["conso_kwh_total"] = s
                e["conso_kwh"] = s

    data["energies"] = energies
    return data

def pixtral_extract_invoice(image_paths: List[str],
                            model: str = "pixtral-large-latest",
                            energy_hint: str | None = None) -> dict:
    """Call Mistral Pixtral on 1..8 images and return normalized JSON."""
    if not Config.MISTRAL_API_KEY:
        raise RuntimeError("Set MISTRAL_API_KEY in your environment or Config.")
    if len(image_paths) > 8:
        raise ValueError("Pixtral accepts up to 8 images per request.")

    client = Mistral(api_key=Config.MISTRAL_API_KEY)

    content = [{"type": "text", "text": _PIXTRAL_USER_INSTRUCTIONS}]
    if energy_hint and energy_hint != "auto":
        content.insert(0, {"type": "text", "text": f"Type attendu: {energy_hint}."})

    # Reuse  existing helper to embed as data URLs
    for p in image_paths:
        content.append({"type": "image_url", "image_url": _image_to_data_url(p)})

    resp = client.chat.complete(
        model=model,
        messages=[
            {"role": "system", "content": _PIXTRAL_SYSTEM},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=2200,
    )
    print("[Mistral] usage:", getattr(resp, "usage", None))
    raw = resp.choices[0].message.content
    parsed = _extract_json_loose(raw)
    return normalize_pixtral_json(parsed)


def process_image_files(image_paths: List[str],
                        energy_mode: str = "auto",
                        confidence_min: float = 0.5,
                        strict: bool = True) -> Tuple[bytes, bytes]:
    """
    Processes invoice images and returns the generated reports as raw bytes.
    This version is modified for stateless API usage and does not write report files to disk.
    """
    if not image_paths:
        raise ValueError("No image paths provided")

    # --- All processing logic remains the same ---
    print(f"[INFO] Extraction de la structure avec Pixtral ({len(image_paths)} image(s))...")
    model = os.getenv("PIOUI_PIXTRAL_MODEL", "pixtral-large-latest")
    parsed = pixtral_extract_invoice(image_paths, model=model, energy_hint=(energy_mode if energy_mode != "auto" else None))

    periode = parsed.get("periode") or {}
    if not periode.get("jours") and periode.get("de") and periode.get("a"):
        d1, d2 = _parse_date_fr(periode["de"]), _parse_date_fr(periode["a"])
        if d1 and d2:
            periode["jours"] = (d2 - d1).days
            parsed["periode"] = periode

    parsed, _diag = apply_energy_mode(parsed, "", mode=energy_mode, conf_min=confidence_min, strict=strict)

    energies = parsed.get("energies") or []
    if not energies:
        energies = [{"type": (parsed.get("type_facture") or "electricite"), "fournisseur": parsed.get("fournisseur"), "offre": parsed.get("offre"), "option": parsed.get("option"), "puissance_kVA": parsed.get("puissance_kVA"), "conso_kwh": parsed.get("consommation_kWh"), "total_ttc": parsed.get("total_TTC")}]

    sections = []
    for e in energies:
        params = params_from_energy(parsed, e, "")
        curr = current_annual_total(params)
        offers = []
        if params["energy"] == "electricite":
            offers += make_base_offers(params, curr)
            offers += make_hphc_offers(params, curr)
        else:
            offers += make_base_offers(params, curr)
        sections.append({"params": params, "rows": offers})

    combined_dual = []
    has_elec = any(s["params"]["energy"] == "electricite" for s in sections)
    has_gaz = any(s["params"]["energy"] == "gaz" for s in sections)
    if has_elec and has_gaz:
        elec_rows = next((s["rows"] for s in sections if s["params"]["energy"] == "electricite"), [])
        gaz_rows = next((s["rows"] for s in sections if s["params"]["energy"] == "gaz"), [])
        if elec_rows and gaz_rows:
            for i in range(min(3, len(elec_rows), len(gaz_rows))):
                provider = random.choice([elec_rows[i]["provider"], gaz_rows[i]["provider"]])
                combined_dual.append({
                    "provider": provider,
                    "offer_name": f"{elec_rows[i]['offer_name']} + {gaz_rows[i]['offer_name']}",
                    "total_annuel_estime": elec_rows[i]["total_annuel_estime"] + gaz_rows[i]["total_annuel_estime"],
                })
            combined_dual.sort(key=lambda x: x["total_annuel_estime"])

    # The function now returns the bytes directly from the modified build_pdfs function
    return build_pdfs(parsed, sections, combined_dual)

# CLI - Updated to handle both PDFs and images
if __name__ == "__main__":
    import argparse, sys, os

    parser = argparse.ArgumentParser(
        prog="report_pioui_static_v3_gemini.py",
        description="Génère deux rapports (anonyme / non-anonyme) à partir d'une facture d'énergie (PDF ou images)."
    )
    parser.add_argument("input_paths", nargs='+', help="Chemin(s) vers le PDF ou les images de la facture")
    parser.add_argument("-e", "--energy", default="auto",
                        help="Type attendu: auto | gaz | electricite | dual (par défaut: auto)")
    parser.add_argument("-c", "--conf", type=float, default=0.5,
                        help="Seuil de confiance pour bloquer si contradiction (par défaut: 0.5)")
    parser.add_argument("--no-strict", action="store_true",
                        help="Ne pas bloquer en cas de contradiction forte; avertir seulement")
    parser.add_argument("--vlm", choices=["pixtral", "gpt"], default="pixtral",
                        help="Vision backend for images (default: pixtral).")

    args = parser.parse_args()

    # Validate input paths
    input_paths = [os.path.abspath(p) for p in args.input_paths]

    # Check that all files exist
    for path in input_paths:
        if not os.path.exists(path):
            print(f"[ERREUR] Fichier introuvable : {path}")
            sys.exit(1)

    # Determine if we're processing PDF or images
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}
    pdf_extensions = {'.pdf'}

    # Check file types
    file_types = []
    for path in input_paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in pdf_extensions:
            file_types.append('pdf')
        elif ext in image_extensions:
            file_types.append('image')
        else:
            print(f"[ERREUR] Type de fichier non supporté : {ext}")
            sys.exit(1)

    # Validate that we don't have mixed types
    unique_types = set(file_types)
    if len(unique_types) > 1:
        print("[ERREUR] Impossible de mélanger PDFs et images. Veuillez fournir soit des PDF(s) soit des image(s), pas les deux.")
        sys.exit(1)

    # Validate that we have only one PDF if PDF type
    if 'pdf' in unique_types and len(input_paths) > 1:
        print("[ERREUR] Plusieurs PDFs non supportés. Veuillez fournir un seul fichier PDF.")
        sys.exit(1)

    try:
        if 'pdf' in unique_types:
            # Single PDF processing
            print(f"[INFO] Traitement du PDF : {input_paths[0]}")
            non_anon, anon = process_invoice_file(
                input_paths[0],
                energy_mode=args.energy,
                confidence_min=max(0.0, min(1.0, args.conf)),
                strict=(not args.no_strict)
            )
        else:
            # Image processing (single or multiple)
            if len(input_paths) == 1:
                print(f"[INFO] Traitement d'une seule image : {input_paths[0]}")
            else:
                print(f"[INFO] Traitement de {len(input_paths)} images comme facture multi-pages")

            non_anon, anon = process_image_files(
                input_paths,
                energy_mode=args.energy,
                confidence_min=max(0.0, min(1.0, args.conf)),
                strict=(not args.no_strict)
            )

        print("\n🎉 Rapports générés avec succès !")
        print(f"   -> Non-anonyme : {non_anon}")
        print(f"   -> Anonyme : {anon}")

    except EnergyTypeMismatchError as e:
        print(f"[ERREUR] Type d'énergie incorrect : {e}")
        print("[CONSEIL] Essayez d'utiliser --no-strict pour ignorer la détection du type d'énergie")
        sys.exit(2)
    except EnergyTypeError as e:
        print(f"[ERREUR] Paramètre : {e}")
        sys.exit(3)
    except FileNotFoundError as e:
        print(f"[ERREUR] Fichier introuvable : {e}")
        sys.exit(4)
    except ValueError as e:
        print(f"[ERREUR] Entrée invalide : {e}")
        sys.exit(5)
    except Exception as e:
        print(f"[ERREUR] Erreur inattendue : {e}")
        import traceback

        traceback.print_exc()
        sys.exit(99)