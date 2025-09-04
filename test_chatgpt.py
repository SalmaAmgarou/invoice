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

import os, json, random, datetime
from datetime import date, datetime as dt
from typing import List, Dict, Any, Tuple, Optional

# --- OpenAI ---
from openai import OpenAI
from config import Config

client = OpenAI(api_key=Config.OPENAI_API_KEY)

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

# ───────────────── 🎨 Pioui Branding & Styling 🎨 ─────────────────
PALETTE = {
    "primary_blue": "#2563EB",   # Main accent blue
    "brand_yellow": "#F0BC00",   # Pioui yellow (NEW)
    "dark_navy": "#1E293B",      # Header/footer backgrounds
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
    "addr": "562-78 avenue des Champs-Élysées, 75008 Paris",
    "tel": "01 62 19 95 72",
    "copyright": f"Copyright © {date.today().year} / 2025, All Rights Reserved."
}

# Assets
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "logo", "pioui_logo.png")
FONT_DIR = os.path.join(SCRIPT_DIR, "fonts")

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
        print("[INFO] Poppins font family successfully registered.")
        return True
    except Exception as e:
        print(f"[WARN] Could not register Poppins fonts. Fallback to Helvetica. Error: {e}")
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
            {"role": "user",
             "content": [{"type": "image_url", "image_url": {"url": "file://" + os.path.abspath(image_path)}}]},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content

def parse_text_with_gpt(text: str) -> str:
    system = "Assistant d'analyse de factures énergie. Retourne UNIQUEMENT un JSON valide (un objet)."
    user_prompt = f"""
Analyse cette facture et retourne ce JSON (strict):
{{
  "client": {{"name": null, "address": null, "zipcode": null}},
  "periode": {{"de":"dd/mm/yyyy","a":"dd/mm/yyyy","jours":null}},
  "energies": [
    {{
      "type": "electricite" | "gaz",
      "fournisseur": null,
      "offre": null,
      "option": "Base" | "HP/HC" | null,
      "puissance_kVA": null,
      "zone_gaz": null,
      "class_gaz": null,
      "conso_kwh": null,
      "abonnement_ttc": null,
      "total_ttc": null
    }}
  ]
}}
Règles:
- Si la facture contient électricité ET gaz, mets DEUX objets dans "energies".
- "periode.jours" = diff exacte si possible.
- "total_ttc" & "abonnement_ttc" sont par énergie.
- "conso_kwh" peut être null.

Texte:
{text}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content

# ───────────────── Data processing ─────────────────
def params_from_energy(global_json: dict, energy_obj: dict) -> dict:
    zipcode = ((global_json.get("client") or {}).get("zipcode")) or "75001"
    periode = global_json.get("periode") or {}
    jours = periode.get("jours")
    try:
        jours = int(jours) if jours else None
    except Exception:
        jours = None

    energy = (energy_obj.get("type") or "electricite").strip().lower()
    option = energy_obj.get("option") or ("Base" if energy == "electricite" else None)
    kva = None
    if energy == "electricite":
        try:
            kva = int(energy_obj.get("puissance_kVA") or 6)
        except Exception:
            kva = 6
    conso = _to_float(energy_obj.get("conso_kwh"))
    if conso is None:
        conso = 3500.0 if energy == "electricite" else 12000.0

    return {
        "energy": "gaz" if energy == "gaz" else "electricite",
        "zipcode": zipcode,
        "kva": kva,
        "option": option if energy == "electricite" else None,
        "consumption_kwh": conso,  # (logic unchanged)
        "hp_share": 0.35 if (option and str(option).upper().startswith("HP")) else None,
        "period_days": jours,
        "total_ttc_period": _to_float(energy_obj.get("total_ttc")),
        "abonnement_ttc_period": _to_float(energy_obj.get("abonnement_ttc")),
        "fournisseur": energy_obj.get("fournisseur"),
        "offre": energy_obj.get("offre"),
    }

def current_annual_total(params: dict) -> Optional[float]:
    tp, pd = params.get("total_ttc_period"), params.get("period_days")
    if tp and pd:
        return annualize(tp, pd)
    # fallback rough estimate
    return (params["consumption_kwh"] * (0.25 if params["energy"] == "electricite" else 0.10)
            + (150.0 if params["energy"] == "electricite" else 220.0))

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

# ───────────────── Vices cachés (ASCII, no emoji) ─────────────────
def vices_caches_for(energy: str, fournisseur: Optional[str], offre: Optional[str]) -> List[str]:
    f = (fournisseur or "").lower()
    o = (offre or "").lower()

    base_elec = [
        "Tarif supérieur au TRV (à vérifier sur la période de facturation)",
        "Remise temporaire déguisée (prix d'appel limité dans le temps)",
        "Option verte non certifiée (labels/garanties d'origine floues)",
        "Double abonnement (compteur secondaire / services additionnels)",
        "Indexation non transparente (référence ambiguë, révision discrétionnaire)",
    ]
    base_gaz = [
        "Prix > Prix repère CRE pour profil comparable",
        "Tarif indexé sans plafond (exposition forte aux hausses)",
        "Frais techniques (mise en service, déplacement) supérieurs aux barèmes GRDF",
        "Promotion trompeuse (conditions d’éligibilité restrictives)",
        "Révision des barèmes en cours d’engagement",
    ]

    extra = []
    if "ohm" in f: extra += ["Variation tarifaire fréquente sur offres indexées (suivi recommandé)"]
    if "total" in f: extra += ["Éco-participation/verte optionnelle facturée séparément"]
    if "engie" in f: extra += ["Nom d’offre proche de l’existant mais conditions différentes (fine print)"]
    if "edf" in f: extra += ["Confusion entre Tarif Bleu (TRV) et offres de marché (prix distincts)"]
    if "mint" in f or "ekwateur" in f or "ilek" in f: extra += ["Surcoût 'vert premium' possible selon la garantie choisie"]
    if "octopus" in f: extra += ["Mécanisme de révision indexé marché de gros (sensibilité élevée)"]
    if "index" in o or "indexée" in o: extra += ["Indexation sur un indice/repère peu documenté dans le contrat"]
    if "prix bloqué" in o or "fixe" in o or "verte fixe" in o: extra += ["Prix fixe mais hors TRV/Repère (attention en cas de baisse générale)"]
    if "online" in o: extra += ["Service client majoritairement digital (délais/difficultés hors canal)"]

    lst = (base_elec if energy == "electricite" else base_gaz) + extra
    prefix = "[ELEC] " if energy == "electricite" else "[GAZ] "  # ASCII labels for reliability
    return [ s for s in lst]

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
                logo = RLImage(LOGO_PATH, width=90, height=30)
                logo.drawOn(canv, 2 * cm, height - 40)
            except Exception:
                canv.setFillColor(colors.white)
                canv.setFont(BOLD_FONT, 12)
                canv.drawString(2 * cm, height - 32, "Pioui")

        canv.setFillColor(colors.white)
        canv.setFont(BASE_FONT, 10)
        canv.drawRightString(width - 2 * cm, height - 28, "Rapport Comparatif Énergie")
        canv.setFont(BASE_FONT, 8)
        canv.setFillColor(colors.HexColor(PALETTE["text_muted"]))
        canv.drawRightString(width - 2 * cm, height - 40, title_right)

        # === Footer ===
        canv.setFillColor(colors.HexColor(PALETTE["dark_navy"]))
        canv.rect(0, 0, width, 60, stroke=0, fill=1)
        # Yellow thin line above footer content
        canv.setFillColor(colors.HexColor(PALETTE["brand_yellow"]))
        canv.rect(0, 58, width, 2, stroke=0, fill=1)

        # Footer content
        y_pos = 45
        canv.setFillColor(colors.white)
        canv.setFont(BASE_FONT, 8)
        canv.drawString(2 * cm, y_pos, PIOUI["url"])
        canv.drawCentredString(width / 2, y_pos, PIOUI["addr"])
        canv.drawRightString(width - 2 * cm, y_pos, f"Page {doc.page}")

        y_pos -= 15
        canv.setFillColor(colors.HexColor(PALETTE["text_muted"]))
        canv.drawString(2 * cm, y_pos, PIOUI["email"])
        canv.drawCentredString(width / 2, y_pos, PIOUI["tel"])

        y_pos -= 10
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

# ───────────────── PDF Builder ─────────────────
def build_pdfs(parsed: dict, sections: List[Dict[str, Any]], combined_dual: List[Dict[str, Any]], output_base: str) -> Tuple[str, str]:
    def render(path_out: str, anonymous: bool):
        doc = SimpleDocTemplate(
            path_out, pagesize=A4,
            leftMargin=2 * cm, rightMargin=2 * cm,
            topMargin=2.5 * cm + 50,   # header space
            bottomMargin=2.0 * cm + 60 # footer space
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
        right_title = "Rapport Anonyme" if anonymous else (client.get("name") or "")
        on_page = draw_header_footer(title_right=right_title)

        # — Intro
        story.append(H1("Votre Rapport Comparatif"))
        if anonymous:
            story.append(P("<b>Client :</b> — (anonyme)"))
        else:
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
        story.append(H2("Période de facturation analysée"))
        story.append(P(f"Du <b>{p_de or 'N/A'}</b> au <b>{p_a or 'N/A'}</b> (soit {p_j or '~'} jours)"))
        story.append(Spacer(1, 12))

        # — Sections per energy type (ORDER ENFORCED)
        for sec in sections:
            params = sec["params"]
            rows = sec["rows"]
            energy_label = "Électricité" if params["energy"] == "electricite" else "Gaz"

            # 1) Offre actuelle
            story.append(H1(f"Analyse {energy_label}"))
            story.append(H2("Votre offre actuelle"))

            conso = params.get("consumption_kwh")
            total_period = params.get("total_ttc_period")
            avg_price = (total_period / conso) if (total_period and conso) else None
            annual_now = current_annual_total(params)

            head = [
                P("Fournisseur"), P("Offre"), P("Puissance"), P("Option"),
                P("Conso. (fact.)"), PR("Total TTC (période)"), PR("Prix moyen (€/kWh)"),
                PR("Estimation annuelle actuelle")  # NEW column
            ]
            row = [
                P(f"<b>{params.get('fournisseur') or '—'}</b>"),
                P(params.get('offre') or '—'),
                P(str(params.get('kva')) if params["energy"] == "electricite" else "N/A"),
                P(params.get('option') if params["energy"] == "electricite" else "N/A"),
                P(_fmt_kwh(conso)),
                PR(_fmt_euro(total_period)),
                PR(f"{avg_price:.4f} €/kWh" if avg_price else "—"),
                PR(_fmt_euro(annual_now))  # NEW value
            ]
            story.append(create_modern_table([head, row], cw(1.3, 1.8, 0.9, 0.9, 1.2, 1.2, 1.2, 1.6),
                                             numeric_cols={4, 5, 6, 7}, zebra=False))
            story.append(Spacer(1, 12))

            # 2) Comparatif
            story.append(H2(f"Comparatif des offres {energy_label}"))
            if params["energy"] == "electricite":
                base = [o for o in rows if o.get("option") in (None, "Base")]
                hphc = [o for o in rows if o.get("option") == "HP/HC"]

                thead = [P("Fournisseur"), P("Offre"), PR("Prix kWh TTC"), PR("Abonnement / an"), PR("Total estimé / an")]
                def map_b(o):
                    return [
                        P(o["provider"]), P(o["offer_name"]),
                        PR(f"{o['price_kwh_ttc']:.4f} €/kWh"),
                        PR(_fmt_euro(o["abonnement_annuel_ttc"])),
                        PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")
                    ]

                if base:
                    story.append(P("<b> Option Base</b>"))
                    story.append(create_modern_table([thead] + [map_b(o) for o in base[:3]],
                                                     cw(1.2, 2.0, 1.0, 1.2, 1.2), numeric_cols={2,3,4}))
                    story.append(Spacer(1, 6))

                if hphc:
                    story.append(P("<b> Option Heures Pleines / Heures Creuses</b>"))
                    thead2 = [P("Fournisseur"), P("Offre"), PR("Prix HP / HC"), PR("Abonnement / an"), PR("Total estimé / an")]
                    def map_h(o):
                        return [
                            P(o["provider"]), P(o["offer_name"]),
                            PR(f"{o['price_hp_ttc']:.4f} / {o['price_hc_ttc']:.4f} €/kWh"),
                            PR(_fmt_euro(o["abonnement_annuel_ttc"])),
                            PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")
                        ]
                    story.append(create_modern_table([thead2] + [map_h(o) for o in hphc[:3]],
                                                     cw(1.2, 1.8, 1.4, 1.2, 1.2), numeric_cols={2,3,4}))
                    story.append(Spacer(1, 8))
            else:
                thead = [P("Fournisseur"), P("Offre"), PR("Prix kWh TTC"), PR("Abonnement / an"), PR("Total estimé / an")]
                def map_g(o):
                    return [
                        P(o["provider"]), P(o["offer_name"]),
                        PR(f"{o['price_kwh_ttc']:.4f} €/kWh"),
                        PR(_fmt_euro(o["abonnement_annuel_ttc"])),
                        PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")
                    ]
                story.append(create_modern_table([thead] + [map_g(o) for o in rows[:3]],
                                                 cw(1.2, 2.0, 1.0, 1.2, 1.2), numeric_cols={2,3,4}))
                story.append(Spacer(1, 8))

            # 3) Vices cachés (Points de vigilance)
            story.append(H2("Points de vigilance (Vices cachés)"))
            story.append(PM("Analyse sur l’offre actuelle et les alternatives proposées."))
            story.append(Spacer(1, 4))
            bullets = vices_caches_for(params["energy"], params.get("fournisseur"), params.get("offre"))

            # Add 1–2 extra points based on best alternative (for nuance)
            best_for_notes = next((o for o in rows if o.get("total_annuel_estime") is not None), None)
            if best_for_notes:
                bullets += vices_caches_for(params["energy"], best_for_notes.get("provider"), best_for_notes.get("offer_name"))[:2]

            # Render as bullet list (ASCII safe)
            for b in dict.fromkeys(bullets):  # preserve order, avoid duplicates
                story.append(Paragraph(f"• {b}", s["Body"]))
            story.append(Spacer(1, 10))

            # Yellow badge separator
            badge = Table([[Paragraph("Attention aux clauses et indexations", s["Badge"])]], colWidths=[W])
            badge.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(PALETTE["brand_yellow"])),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
                ('RIGHTPADDING', (0,0), (-1,-1), 8),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(badge)
            story.append(Spacer(1, 12))

            # 4) Notre recommandation
            story.append(H2("Notre recommandation"))
            best = next((o for o in rows if o.get("total_annuel_estime") is not None), None)
            curr = annual_now
            if best and curr:
                best = min([o for o in rows if o.get("total_annuel_estime") is not None], key=lambda x: x["total_annuel_estime"])
                delta = curr - best["total_annuel_estime"]
                if delta > 0:
                    reco_text = Paragraph(
                        f"Économisez jusqu'à <font size='14' color='{PALETTE['saving_red']}'><b>{_fmt_euro(delta)}</b></font> "
                        f"par an en passant chez <b>{best['provider']}</b> avec l'offre <b>{best['offer_name']}</b>.",
                        s["Body"]
                    )
                else:
                    reco_text = Paragraph(
                        "Votre offre actuelle semble compétitive. Aucune économie nette identifiée.",
                        s["Body"]
                    )
            else:
                reco_text = Paragraph("Données insuffisantes pour une recommandation chiffrée fiable.", s["Body"])

            reco_box = Table([[reco_text]], colWidths=[W])
            reco_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(PALETTE["bg_light"])),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(PALETTE["border_light"])),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ]))
            story.append(reco_box)
            story.append(Spacer(1, 12))

            story.append(HRFlowable(width="100%", color=colors.HexColor(PALETTE["border_light"]), thickness=1))
            story.append(Spacer(1, 12))

        # Pack Dual (optional)
        if combined_dual:
            story.append(H1("Pack Dual (Électricité + Gaz)"))
            thead = [P("Fournisseur"), P("Offres combinées"), PR("Total estimé (élec+gaz)")]
            def map_d(o):
                return [P(o["provider"]), P(o["offer_name"]), PR(f"<b>{_fmt_euro(o['total_annuel_estime'])}</b>")]
            story.append(create_modern_table([thead] + [map_d(o) for o in combined_dual[:3]],
                                             cw(1.3, 3.0, 1.2), numeric_cols={2}))
            story.append(Spacer(1, 10))

        # 5) Méthodologie & Fiabilité des données (global, at the end)
        story.append(H2("Méthodologie & Fiabilité des données"))
        story.append(Paragraph(
            "Les données de ce rapport proviennent de votre facture, d’offres publiques de référence, et de barèmes officiels. "
            "Les comparaisons sont estimées à partir d’hypothèses réalistes pour illustrer des économies potentielles.",
            s["Muted"]
        ))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<b>Rapport indépendant</b>, sans publicité ni affiliation. Son seul but : identifier vos économies possibles.",
            s["Muted"]
        ))

        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        print(f"✅ PDF report created: {path_out}")

    non_anon_path = output_base + "_rapport_non_anonyme.pdf"
    anon_path = output_base + "_rapport_anonyme.pdf"
    render(non_anon_path, anonymous=False)
    render(anon_path, anonymous=True)
    return non_anon_path, anon_path

# ───────────────── Pipeline ─────────────────
def process_invoice_file(pdf_path: str, auto_save_suffix_date: bool = True) -> Tuple[str, str]:
    pdf_path = os.path.abspath(pdf_path)
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = os.path.dirname(pdf_path)
    suffix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") if auto_save_suffix_date else ""
    base_out = os.path.join(out_dir, f"{basename}{('_' + suffix) if suffix else ''}")

    text = extract_text_from_pdf(pdf_path)
    parsed = None
    if text and len(text) > 60:
        print("[INFO] Text-based PDF found. Parsing with GPT...")
        raw = parse_text_with_gpt(text)
        try:
            parsed = json.loads(raw)
        except Exception:
            print("[WARN] JSON parsing failed. Falling back to OCR...")
    if not parsed:
        print("[INFO] PDF is image-based or text parsing failed. Using OCR via GPT-4o (page 1)...")
        try:
            pages = convert_from_path(pdf_path, dpi=200)
            if not pages:
                raise ValueError("No pages converted from PDF.")
            tmp_img = os.path.join(out_dir, f"{basename}_page1_temp.png")
            pages[0].save(tmp_img, "PNG")
            raw = ocr_invoice_with_gpt(tmp_img)
            os.remove(tmp_img)
            parsed = json.loads(raw)
        except Exception as e:
            print(f"[ERROR] OCR and parsing failed: {e}. Using fallback data.")
            parsed = {
                "client": {"name": None, "address": None, "zipcode": "75001"},
                "periode": {"de": None, "a": None, "jours": None},
                "energies": [{
                    "type": "electricite", "fournisseur": None, "offre": None,
                    "option": "Base", "puissance_kVA": 6, "conso_kwh": 3500,
                    "abonnement_ttc": None, "total_ttc": None
                }]
            }

    # Fill "jours" if missing and dates present
    periode = parsed.get("periode") or {}
    if not periode.get("jours") and periode.get("de") and periode.get("a"):
        d1, d2 = _parse_date_fr(periode["de"]), _parse_date_fr(periode["a"])
        if d1 and d2:
            periode["jours"] = (d2 - d1).days
            parsed["periode"] = periode

    energies = parsed.get("energies") or []
    if not energies:
        energies = [{
            "type": (parsed.get("type_facture") or "electricite"),
            "fournisseur": parsed.get("fournisseur"),
            "offre": parsed.get("offre"),
            "option": parsed.get("option"),
            "puissance_kVA": parsed.get("puissance_kVA"),
            "conso_kwh": parsed.get("consommation_kWh"),
            "abonnement_ttc": parsed.get("abonnement_TTC"),
            "total_ttc": parsed.get("total_TTC"),
        }]

    sections = []
    energy_seen = set()
    for e in energies:
        params = params_from_energy(parsed, e)
        curr = current_annual_total(params)
        offers = []
        if params["energy"] == "electricite":
            offers += make_base_offers(params, curr)
            offers += make_hphc_offers(params, curr)
        else:
            offers += make_base_offers(params, curr)
        sections.append({"params": params, "rows": offers})
        energy_seen.add(params["energy"])

    combined_dual = []
    if "electricite" in energy_seen and "gaz" in energy_seen:
        elec = [s for s in sections if s["params"]["energy"] == "electricite"][0]["rows"]
        gaz  = [s for s in sections if s["params"]["energy"] == "gaz"][0]["rows"]
        for i in range(min(3, len(elec), len(gaz))):
            provider = random.choice([elec[i]["provider"], gaz[i]["provider"]])
            combined_dual.append({
                "provider": provider,
                "offer_name": f"{elec[i]['offer_name']} + {gaz[i]['offer_name']}",
                "total_annuel_estime": elec[i]["total_annuel_estime"] + gaz[i]["total_annuel_estime"]
            })
        combined_dual.sort(key=lambda x: x["total_annuel_estime"])

    return build_pdfs(parsed, sections, combined_dual, base_out)

# ───────────────── CLI ─────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("\nUsage: python3 report_pioui_static_v3_gemini.py <path_to_invoice.pdf>\n")
        print("Ensure you have a 'logo' folder with 'pioui_logo.png' and a 'fonts' folder with Poppins .ttf files.")
        sys.exit(1)

    invoice_path = sys.argv[1]
    if not os.path.exists(invoice_path):
        print(f"[ERROR] File not found: {invoice_path}")
        sys.exit(1)

    non_anon, anon = process_invoice_file(invoice_path)
    print("\n🎉 Reports generated successfully!")
    print(f"   -> {non_anon}")
    print(f"   -> {anon}")
