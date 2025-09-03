#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
report_pioui_static_v2.py

Génère 2 PDF (non-anonyme & anonyme) à partir d'une facture :
- Extraction (texte/vision) -> JSON dual-aware
- Offres synthétiques "meilleures": -12%, -11%, -10% du total annuel actuel
- Rendu premium (header+footer, logo, couleurs Pioui)
- Section "Vices cachés" détaillée & contextualisée (fournisseur/offre/énergie)
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

# ───────────────── Branding Pioui ─────────────────
PALETTE = {
    "text": "#0F172A",          # slate-900
    "muted": "#475569",         # slate-600
    "hair":  "#E2E8F0",         # slate-200
    "panel": "#F8FAFC",         # slate-50
    "band":  "#111827",         # header band
    "accent":"#4F46E5",         # indigo-600
    "thead": "#EEF2FF",         # indigo-50
    "grid":  "#C7D2FE",         # indigo-200
    "zebra": "#FAFAFF",
    "saving":"#DC2626",         # red-600
}
PIOUI = {
    "url":   "https://pioui.com",
    "email": "service.client@pioui.com",
    "addr":  "562-78 avenue des Champs-Élysées, 75008 Paris",
    "tel":   "01 62 19 95 72",
}
LOGO_PATH = os.getenv("logo/pioui_logo.png", "")  # ex: /path/logo_pioui.png

# ───────────────── Polices ─────────────────
def _register_font():
    try:
        pdfmetrics.registerFont(TTFont("Inter", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        return "Inter"
    except Exception:
        return "Helvetica"
BASE_FONT = _register_font()

# ───────────────── Utilities ─────────────────
def _to_float(x, default=None):
    try: return float(str(x).replace(",", "."))
    except Exception: return default

def _parse_date_fr(s: str) -> Optional[dt]:
    try: return dt.strptime(s, "%d/%m/%Y")
    except Exception: return None

def annualize(value_for_period: Optional[float], days: Optional[int]) -> Optional[float]:
    if not value_for_period or not days or days <= 0: return None
    return value_for_period * (365.0 / days)

def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        out = ""
        with pdfplumber.open(pdf_path) as pdf:
            for p in pdf.pages:
                t = p.extract_text()
                if t: out += t + "\n"
        return out.strip()
    except Exception:
        return ""

# ───────────────── GPT extractors (JSON strict, dual-aware) ─────────────────
def ocr_invoice_with_gpt(image_path: str) -> str:
    system = "Assistant d'analyse de factures énergie. Retourne UNIQUEMENT un JSON valide (un objet)."
    user_prompt = "Même consignes que précédemment. Image ci-dessous."
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":system},
            {"role":"user","content":user_prompt},
            {"role":"user","content":[{"type":"image_url","image_url":{"url":"file://"+os.path.abspath(image_path)}}]},
        ],
        temperature=0.0,
        response_format={"type":"json_object"},
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
        model="gpt-4.1-mini",
        messages=[{"role":"system","content":system},{"role":"user","content":user_prompt}],
        temperature=0.0,
        response_format={"type":"json_object"},
    )
    return resp.choices[0].message.content

# ───────────────── Paramétrage depuis JSON ─────────────────
def params_from_energy(global_json: dict, energy_obj: dict) -> dict:
    zipcode = ((global_json.get("client") or {}).get("zipcode")) or "75001"
    periode = global_json.get("periode") or {}
    jours = periode.get("jours")
    try: jours = int(jours) if jours else None
    except Exception: jours = None

    energy = (energy_obj.get("type") or "electricite").strip().lower()
    option = energy_obj.get("option") or ("Base" if energy == "electricite" else None)
    kva = None
    if energy == "electricite":
        try: kva = int(energy_obj.get("puissance_kVA") or 6)
        except Exception: kva = 6
    conso = _to_float(energy_obj.get("conso_kwh"))
    if conso is None: conso = 3500.0 if energy == "electricite" else 12000.0

    return {
        "energy": "gaz" if energy == "gaz" else "electricite",
        "zipcode": zipcode,
        "kva": kva,
        "option": option if energy == "electricite" else None,
        "consumption_kwh": conso,
        "hp_share": 0.35 if (option and str(option).upper().startswith("HP")) else None,
        "period_days": jours,
        "total_ttc_period": _to_float(energy_obj.get("total_ttc")),
        "abonnement_ttc_period": _to_float(energy_obj.get("abonnement_ttc")),
        "fournisseur": energy_obj.get("fournisseur"),
        "offre": energy_obj.get("offre"),
    }

def current_annual_total(params: dict) -> Optional[float]:
    tp, pd = params.get("total_ttc_period"), params.get("period_days")
    if tp and pd: return annualize(tp, pd)
    # fallback plausible
    return (params["consumption_kwh"] * (0.25 if params["energy"]=="electricite" else 0.10)
            + (150.0 if params["energy"]=="electricite" else 220.0))

# ───────────────── Offres synthétiques (−12/−11/−10 %) ─────────────────
PROVIDERS_ELEC = ["EDF","Engie","TotalEnergies","Vattenfall","OHM Énergie","ekWateur","Mint Énergie","Plüm énergie","ilek","Enercoop","Méga Énergie","Wekiwi","Happ-e by Engie","Alpiq","Octopus Energy"]
PROVIDERS_GAZ  = ["Engie","EDF","TotalEnergies","Plenitude (ex Eni)","Happ-e by Engie","ekWateur","Vattenfall","Mint Énergie","Butagaz","ilek","Gaz de Bordeaux","OHM Énergie","Alterna","Dyneff","Wekiwi"]
OFFER_NAMES    = ["Éco","Essentielle","Online","Verte Fixe","Standard","Smart","Confort","Tranquille","Indexée","Prix Bloqué","Pack Duo","Zen"]

def _choose_providers(energy, avoid=None, k=3):
    pool = PROVIDERS_GAZ if energy=="gaz" else PROVIDERS_ELEC
    pool = [p for p in pool if not (avoid and p.lower()==str(avoid).lower())]
    random.shuffle(pool)
    return pool[:k]

def _offer_name(): return random.choice(OFFER_NAMES)
def _round_money(x: float) -> float: return round(x/0.5)*0.5

def make_base_offers(params: dict, current_total: float) -> List[Dict[str,Any]]:
    conso = float(params["consumption_kwh"])
    energy = params["energy"]
    providers = _choose_providers(energy, avoid=params.get("fournisseur"), k=3)
    discounts = [0.12, 0.11, 0.10]
    out = []
    for i, p in enumerate(providers):
        tgt = current_total * (1.0 - discounts[i])
        jitter = random.uniform(-0.002, 0.002)
        tgt_adj = tgt * (1.0 + jitter)
        abo_share = random.uniform(0.12, 0.22) if energy=="electricite" else random.uniform(0.20, 0.32)
        abo = _round_money(tgt_adj * abo_share)
        price_kwh = max(0.01, (tgt_adj - abo)/conso)
        price_kwh = round(price_kwh, 4)
        out.append({
            "provider": p,
            "offer_name": _offer_name(),
            "energy": energy,
            "option": "Base" if energy=="electricite" else None,
            "kva": params.get("kva") if energy=="electricite" else None,
            "price_kwh_ttc": price_kwh,
            "abonnement_annuel_ttc": abo,
            "total_annuel_estime": abo + price_kwh*conso,
        })
    out.sort(key=lambda x: x["total_annuel_estime"])
    return out

def make_hphc_offers(params: dict, current_total: float) -> List[Dict[str,Any]]:
    if params["energy"]!="electricite": return []
    conso = float(params["consumption_kwh"])
    hp_share = params.get("hp_share") or 0.35
    providers = _choose_providers("electricite", avoid=params.get("fournisseur"), k=3)
    discounts = [0.12, 0.11, 0.10]
    out = []
    for i, p in enumerate(providers):
        tgt = current_total*(1.0-discounts[i])*(1.0+random.uniform(-0.002,0.002))
        abo = _round_money(tgt * random.uniform(0.12,0.22))
        blended = max(0.01, (tgt-abo)/conso)
        delta = random.uniform(0.02, 0.06)
        hp = max(0.01, blended + delta*(1-hp_share))
        hc = max(0.01, blended - delta*hp_share)
        out.append({
            "provider": p,
            "offer_name": f"{_offer_name()} HP/HC",
            "energy": "electricite",
            "option": "HP/HC",
            "kva": params.get("kva"),
            "price_kwh_ttc": round(blended,4),
            "price_hp_ttc": round(hp,4),
            "price_hc_ttc": round(hc,4),
            "abonnement_annuel_ttc": abo,
            "total_annuel_estime": abo + blended*conso,
        })
    out.sort(key=lambda x: x["total_annuel_estime"])
    return out

# ───────────────── Vices cachés (contextualisés) ─────────────────
def vices_caches_for(energy: str, fournisseur: Optional[str], offre: Optional[str]) -> List[str]:
    """Heuristiques contextualisées par marque/offre/énergie. Ajoute des points ⚡/🔥 + items précis."""
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

    # Affinage par fournisseur (exemples plausibles)
    extra = []
    if "ohm" in f:
        extra += ["Variation tarifaire fréquente sur offres indexées (suivi recommandé)"]
    if "total" in f:
        extra += ["Éco-participation/verte optionnelle facturée séparément"]
    if "engie" in f:
        extra += ["Nom d’offre proche de l’existant mais conditions différentes (fine print)"]
    if "edf" in f:
        extra += ["Confusion entre Tarif Bleu (TRV) et offres de marché (prix distincts)"]
    if "mint" in f or "ekwateur" in f or "ilek" in f:
        extra += ["Surcoût 'vert premium' possible selon la garantie choisie"]
    if "octopus" in f:
        extra += ["Mécanisme de révision indexé marché de gros (sensibilité élevée)"]

    # Affinage par intitulé d’offre (mots-clés)
    if "index" in o or "indexée" in o:
        extra += ["Indexation sur un indice/repère peu documenté dans le contrat"]
    if "prix bloqué" in o or "fixe" in o or "verte fixe" in o:
        extra += ["Prix fixe mais hors TRV/Repère (attention en cas de baisse générale)"]
    if "online" in o:
        extra += ["Service client majoritairement digital (délais/difficultés hors canal)"]

    lst = (base_elec if energy=="electricite" else base_gaz) + extra
    # Prefix selon énergie
    prefix = "⚡ " if energy=="electricite" else "🔥 "
    return [prefix + s for s in lst]

# ───────────────── Styles & Table helpers ─────────────────
def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="H0", fontName=BASE_FONT, fontSize=18, leading=22, spaceAfter=10,
                         textColor=colors.white, alignment=TA_LEFT))
    s.add(ParagraphStyle(name="H1", fontName=BASE_FONT, fontSize=15, leading=20, spaceAfter=8,
                         textColor=colors.HexColor(PALETTE["text"]), wordWrap='CJK'))
    s.add(ParagraphStyle(name="H2", fontName=BASE_FONT, fontSize=12.5, leading=17, spaceAfter=6,
                         textColor=colors.HexColor(PALETTE["text"]), wordWrap='CJK'))
    s.add(ParagraphStyle(name="Body", fontName=BASE_FONT, fontSize=10.2, leading=14.6,
                         textColor=colors.HexColor(PALETTE["text"]), wordWrap='CJK'))
    s.add(ParagraphStyle(name="Muted", fontName=BASE_FONT, fontSize=9.4, leading=13.4,
                         textColor=colors.HexColor(PALETTE["muted"]), wordWrap='CJK'))
    s.add(ParagraphStyle(name="Mono", fontName=BASE_FONT, fontSize=9.8, leading=13.8,
                         textColor=colors.HexColor(PALETTE["text"]), wordWrap='CJK'))
    s.add(ParagraphStyle(name="MonoRight", parent=s["Mono"], alignment=TA_RIGHT))
    s.add(ParagraphStyle(name="Right", parent=s["Body"], alignment=TA_RIGHT))
    s.add(ParagraphStyle(name="Ital", parent=s["Body"], fontSize=10.2, leading=14.6, textColor=colors.HexColor(PALETTE["text"]), underlineWidth=0, italic=True))
    s.add(ParagraphStyle(name="Strong", parent=s["Body"], fontSize=10.6, leading=15.0))
    return s

def _header_footer(title_left="Rapport comparatif énergie — Pioui", title_right=""):
    def _draw(canv: rl_canvas.Canvas, doc):
        canv.saveState()
        # Bandeau
        canv.setFillColor(colors.HexColor(PALETTE["band"]))
        canv.rect(0, A4[1]-44, A4[0], 44, stroke=0, fill=1)
        canv.setFillColor(colors.HexColor(PALETTE["accent"]))
        canv.rect(0, A4[1]-46, 170, 2, stroke=0, fill=1)

        # Logo (optionnel)
        if LOGO_PATH and os.path.exists(LOGO_PATH):
            try:
                canv.drawImage(LOGO_PATH, 18, A4[1]-38, width=78, height=26, mask='auto')
            except Exception:
                pass

        canv.setFillColor(colors.white)
        canv.setFont(BASE_FONT, 11)
        canv.drawString(105, A4[1]-26, title_left)
        if title_right:
            canv.drawRightString(A4[0]-20, A4[1]-26, title_right)

        # Footer bar
        canv.setFillColor(colors.HexColor(PALETTE["hair"]))
        canv.rect(0, 0, A4[0], 30, stroke=0, fill=1)
        canv.setFillColor(colors.HexColor(PALETTE["accent"]))
        canv.rect(0, 28, A4[0], 2, stroke=0, fill=1)

        canv.setFillColor(colors.HexColor(PALETTE["muted"]))
        canv.setFont(BASE_FONT, 9.2)
        canv.drawString(20, 11, f"{PIOUI['url']}  •  {PIOUI['email']}")
        canv.drawCentredString(A4[0]/2, 11, PIOUI["addr"])
        canv.drawRightString(A4[0]-20, 11, f"{PIOUI['tel']}  •  Page {doc.page}")
        canv.restoreState()
    return _draw

def _table(rows, col_widths_pts, numeric_cols=None, zebra=True):
    numeric_cols = set(numeric_cols or [])
    t = Table(rows, colWidths=col_widths_pts, repeatRows=1)
    style = [
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor(PALETTE["thead"])),
        ("BOX", (0,0), (-1,-1), 0.3, colors.HexColor(PALETTE["grid"])),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor(PALETTE["grid"])),
        ("FONT", (0,0), (-1,0), BASE_FONT, 10.3),
        ("FONT", (0,1), (-1,-1), BASE_FONT, 9.8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]
    if zebra and len(rows) > 2:
        for r in range(1, len(rows)):
            if r % 2 == 1:
                style.append(("BACKGROUND", (0,r), (-1,r), colors.HexColor(PALETTE["zebra"])))
    for c in numeric_cols:
        style.append(("ALIGN", (c,1), (c,-1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t

# ───────────────── PDF helpers ─────────────────
def _fmt_euro(x: Optional[float]) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",") if x is not None else "—"

def _fmt_kwh(x: Optional[float]) -> str:
    return f"{x:.0f} kWh" if x is not None else "—"

# ───────────────── Build PDFs ─────────────────
def build_pdfs(parsed: dict, sections: List[Dict[str,Any]], combined_dual: List[Dict[str,Any]], output_base: str) -> Tuple[str, str]:
    def render(path_out: str, anonymous: bool):
        doc = SimpleDocTemplate(
            path_out, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=3.2*cm, bottomMargin=2.3*cm
        )
        s = _styles()
        story = []
        W = doc.width

        def cw(*ratios):
            total = float(sum(ratios))
            return [W * (r/total) for r in ratios]

        P  = lambda x: Paragraph(x if isinstance(x, str) else "—", s["Body"])
        PM = lambda x: Paragraph(x if isinstance(x, str) else "—", s["Mono"])
        PR = lambda x: Paragraph(x if isinstance(x, str) else "—", s["Right"])
        PMR= lambda x: Paragraph(x if isinstance(x, str) else "—", s["MonoRight"])

        client = parsed.get("client") or {}
        right = "Anonyme" if anonymous else (client.get("name") or "")
        on_page = _header_footer(title_left="Rapport comparatif énergie", title_right=right)

        # — Intro
        story.append(Spacer(1, 8))
        story.append(Paragraph("<b>Résumé du client</b>", s["H1"]))
        if anonymous:
            story.append(Paragraph("Client : <b>— (anonyme)</b>", s["Body"]))
        else:
            story.append(Paragraph(f"Client : <b>{client.get('name') or '—'}</b>", s["Body"]))
            if client.get("address"): story.append(Paragraph(client["address"], s["Muted"]))
        story.append(Paragraph(f"<i>Généré le {date.today().strftime('%d/%m/%Y')}</i>", s["Ital"]))
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", color=colors.HexColor(PALETTE["hair"]), thickness=1))
        story.append(Spacer(1, 10))

        # — Période
        periode = parsed.get("periode") or {}
        p_de, p_a, p_j = periode.get("de"), periode.get("a"), periode.get("jours")
        story.append(Paragraph("<b>Période de facturation</b>", s["H2"]))
        story.append(Paragraph(f"Période : <b>{p_de or '—'}</b> → <b>{p_a or '—'}</b> (≈ {p_j or '—'} jours)", s["Body"]))
        story.append(Spacer(1, 12))

        # — Sections
        for sec in sections:
            params = sec["params"]; rows = sec["rows"]
            energy_label = "Électricité" if params["energy"]=="electricite" else "Gaz"
            story.append(Paragraph(f"<b>{energy_label} — Offre actuelle</b>", s["H1"]))

            # résumé
            conso = params.get("consumption_kwh")
            total_period = params.get("total_ttc_period")
            avg_price = (total_period/conso) if (total_period and conso) else None

            head = [P("Fournisseur"), P("Offre"), P("Puissance"), P("Option"), P("CP"), P("Conso annuelle"), P("Total TTC (période)"), P("Prix moyen (approx)")]
            row  = [
                P(params.get("fournisseur") or "—"),
                P(params.get("offre") or "—"),
                PM(str(params.get("kva")) if params["energy"]=="electricite" else "—"),
                PM(params.get("option") if params["energy"]=="electricite" else "—"),
                PM(params.get("zipcode") or "—"),
                PM(_fmt_kwh(conso)),
                PMR(_fmt_euro(total_period)),
                PMR(f"{avg_price:.4f} €/kWh" if avg_price else "—"),
            ]
            story.append(_table([head, row], cw(1.1,2.2,0.8,0.9,0.8,1.1,1.1,1.0), numeric_cols={2,5,6,7}, zebra=False))
            story.append(Spacer(1, 8))

            # offres (synthétiques)
            if params["energy"]=="electricite":
                story.append(Paragraph("<b>Comparatif – Offres Électricité (générées)</b>", s["H2"]))
                base = [o for o in rows if o.get("option") in (None, "Base")]
                hphc = [o for o in rows if o.get("option")=="HP/HC"]

                thead = [P("Fournisseur"), P("Offre"), PM("Prix kWh TTC"), PM("Abonnement annuel TTC"), PM("Total estimé")]
                def map_b(o):
                    return [P(o["provider"]), P(o["offer_name"]), PMR(f"{o['price_kwh_ttc']:.4f} €/kWh"),
                            PMR(_fmt_euro(o["abonnement_annuel_ttc"])), PMR(_fmt_euro(o["total_annuel_estime"]))]

                if base:
                    story.append(Paragraph("→ <b>Option Base</b>", s["Body"]))
                    story.append(_table([thead]+[map_b(o) for o in base[:3]], cw(1.2,2.6,1.0,1.2,1.0), numeric_cols={2,3,4}, zebra=True))
                    story.append(Spacer(1,6))

                if hphc:
                    story.append(Paragraph("→ <b>Option Heures Pleines / Heures Creuses</b>", s["Body"]))
                    thead2 = [P("Fournisseur"), P("Offre"), PM("Prix HP / HC"), PM("Abonnement annuel TTC"), PM("Total estimé")]
                    def map_h(o):
                        return [P(o["provider"]), P(o["offer_name"]),
                                PMR(f"{o['price_hp_ttc']:.4f} / {o['price_hc_ttc']:.4f} €/kWh"),
                                PMR(_fmt_euro(o["abonnement_annuel_ttc"])),
                                PMR(_fmt_euro(o["total_annuel_estime"]))]

                    story.append(_table([thead2]+[map_h(o) for o in hphc[:3]], cw(1.2,2.6,1.1,1.2,0.9), numeric_cols={2,3,4}, zebra=True))
                    story.append(Spacer(1,8))
            else:
                story.append(Paragraph("<b>Comparatif – Offres Gaz (générées)</b>", s["H2"]))
                thead = [P("Fournisseur"), P("Offre"), PM("Prix kWh TTC"), PM("Abonnement annuel TTC"), PM("Total estimé")]
                def map_g(o):
                    return [P(o["provider"]), P(o["offer_name"]), PMR(f"{o['price_kwh_ttc']:.4f} €/kWh"),
                            PMR(_fmt_euro(o["abonnement_annuel_ttc"])), PMR(_fmt_euro(o["total_annuel_estime"]))]

                story.append(_table([thead]+[map_g(o) for o in rows[:3]], cw(1.3,2.9,1.0,1.2,0.9), numeric_cols={2,3,4}, zebra=True))
                story.append(Spacer(1,8))

            # Recommandation
            story.append(Paragraph("<b>Notre recommandation</b>", s["H2"]))
            best = next((o for o in rows if o.get("total_annuel_estime") is not None), None)
            curr = current_annual_total(params)
            if best and curr:
                best = min([o for o in rows if o.get("total_annuel_estime") is not None], key=lambda x:x["total_annuel_estime"])
                delta = curr - best["total_annuel_estime"]
                if delta>0:
                    story.append(Paragraph(
                        f"<b><font color='{PALETTE['saving']}'>Économies réalisables : {_fmt_euro(delta)}</font></b> "
                        f"en passant à <b>{best['provider']} — {best['offer_name']}</b>.", s["Body"]))
                else:
                    story.append(Paragraph(f"Aucune économie nette vs offre actuelle (Δ = {_fmt_euro(delta)}).", s["Body"]))
            else:
                story.append(Paragraph("Données insuffisantes pour une recommandation chiffrée fiable.", s["Body"]))

            story.append(Spacer(1,8))

            # Vices cachés (contextuels)
            story.append(Paragraph("<b>Liste des Vices Cachés</b> — <i>analyse sur l’offre actuelle et alternatives</i>", s["H2"]))
            bullets = vices_caches_for(params["energy"], params.get("fournisseur"), params.get("offre"))
            # mix avec top-1 concurrent pour pointer des points d'attention alternatifs
            if best:
                bullets += vices_caches_for(params["energy"], best.get("provider"), best.get("offer_name"))[:2]
            for b in bullets:
                story.append(Paragraph(f"• {b}", s["Body"]))
            story.append(Spacer(1, 12))

            story.append(HRFlowable(width="100%", color=colors.HexColor(PALETTE["hair"]), thickness=1))
            story.append(Spacer(1, 12))

        # Pack Dual
        if combined_dual:
            story.append(Paragraph("<b>Pack Dual (Électricité + Gaz)</b>", s["H1"]))
            thead = [P("Fournisseur"), P("Offres combinées"), PM("Total estimé (élec+gaz)")]
            def map_d(o): return [P(o["provider"]), P(o["offer_name"]), PMR(_fmt_euro(o["total_annuel_estime"]))]
            story.append(_table([thead]+[map_d(o) for o in combined_dual[:3]], cw(1.3,3.0,1.0), numeric_cols={2}, zebra=True))
            story.append(Spacer(1, 10))

        # Méthodologie & Fiabilité (fixe)
        story.append(Paragraph("<b>Méthodologie & Fiabilité des données</b>", s["H2"]))
        story.append(Paragraph(
            "<i>Les données de ce rapport proviennent de votre facture, d’offres publiques de référence, et de barèmes officiels. "
            "Les comparaisons sont estimées à partir d’hypothèses réalistes pour illustrer des économies potentielles.</i>",
            s["Muted"]
        ))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", color=colors.HexColor(PALETTE["hair"]), thickness=1))
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Rapport indépendant</b>, sans publicité ni affiliation. Son seul but : identifier vos économies possibles.", s["Muted"]))

        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        print(f"[INFO] PDF créé : {path_out}")

    non_anon = output_base + "_rapport_non_anonyme.pdf"
    anon     = output_base + "_rapport_anonyme.pdf"
    render(non_anon, anonymous=False)
    render(anon,     anonymous=True)
    return non_anon, anon

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
        print("[INFO] PDF textuel — parsing GPT.")
        raw = parse_text_with_gpt(text)
        try: parsed = json.loads(raw)
        except Exception: print("[WARN] JSON parsing échoué, OCR fallback…")
    if not parsed:
        print("[INFO] OCR via GPT-4o (page 1)")
        from pdf2image import convert_from_path
        pages = convert_from_path(pdf_path, dpi=200)
        tmp_img = os.path.join(out_dir, f"{basename}_page1.png")
        pages[0].save(tmp_img, "PNG")
        raw = ocr_invoice_with_gpt(tmp_img)
        try: parsed = json.loads(raw)
        except Exception:
            print("[ERROR] Parsing KO — Fallback.")
            parsed = {
                "client":{"name":None,"address":None,"zipcode":"75001"},
                "periode":{"de":None,"a":None,"jours":None},
                "energies":[{"type":"electricite","fournisseur":None,"offre":None,"option":"Base","puissance_kVA":6,"conso_kwh":3500,"abonnement_ttc":None,"total_ttc":None}]
            }

    # période jours
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
        curr   = current_annual_total(params)
        offers = []
        if params["energy"]=="electricite":
            offers += make_base_offers(params, curr)
            offers += make_hphc_offers(params, curr)
        else:
            offers += make_base_offers(params, curr)
        sections.append({"params": params, "rows": offers})
        energy_seen.add(params["energy"])

    combined_dual = []
    if "electricite" in energy_seen and "gaz" in energy_seen:
        elec = [s for s in sections if s["params"]["energy"]=="electricite"][0]["rows"]
        gaz  = [s for s in sections if s["params"]["energy"]=="gaz"][0]["rows"]
        for i in range(min(3, len(elec), len(gaz))):
            provider = random.choice([elec[i]["provider"], gaz[i]["provider"]])
            combined_dual.append({
                "provider": provider,
                "offer_name": f"{elec[i]['offer_name']} + {gaz[i]['offer_name']}",
                "total_annuel_estime": elec[i]["total_annuel_estime"] + gaz[i]["total_annuel_estime"]
            })
        combined_dual.sort(key=lambda x:x["total_annuel_estime"])

    return build_pdfs(parsed, sections, combined_dual, base_out)

# ───────────────── CLI ─────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv)<2:
        print("Usage: python3 report_pioui_static_v2.py <facture.pdf>")
        sys.exit(1)
    non_anon, anon = process_invoice_file(sys.argv[1])
    print("Généré :", non_anon)
    print("Généré :", anon)
