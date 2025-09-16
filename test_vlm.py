#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
simple_pixtral_invoice_json.py
Very small CLI: send image(s) of a French energy invoice to Mistral Pixtral
and save a structured JSON file similar to your PDF logic.

Usage:
  MISTRAL_API_KEY=sk-... python simple_pixtral_invoice_json.py \
      -e electricite img1.png [img2.png ...] \
      --model pixtral-large-latest \
      --out out.json
"""

import os, sys, argparse, json, base64, mimetypes, re, pathlib, datetime
from typing import List, Optional

# Optional config module; falls back to env if missing
try:
    from config import Config  # must define MISTRAL_API_KEY
except Exception:
    Config = None  # type: ignore

from mistralai import Mistral

# ── helpers ──────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    if Config and getattr(Config, "MISTRAL_API_KEY", None):
        return Config.MISTRAL_API_KEY  # type: ignore[attr-defined]
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise RuntimeError("Set MISTRAL_API_KEY in your environment or config.Config.")
    return key

def _b64_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def _extract_json_loose(s: str) -> dict:
    """If model adds extra text, grab the biggest {...} block."""
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))

def _default_output_path(first_image: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = pathlib.Path(first_image).stem
    return os.path.join(os.path.dirname(os.path.abspath(first_image)),
                        f"{stem}_{ts}_pixtral.json")

# number normalization (FR → float)
def _fr_num(s):
    if not isinstance(s, str):
        return None
    x = re.sub(r"[^\d,.\-]", "", s)
    if "," in x and "." in x:
        x = x.replace(".", "").replace(",", ".")
    elif "," in x:
        x = x.replace(",", ".")
    try:
        return float(x)
    except:
        return None


def normalize_pixtral_json(data: dict) -> dict:
    import re

    # Ensure minimal shape
    data.setdefault("client", {})
    data.setdefault("periode", {})
    data.setdefault("energies", [])

    # 1) periode.jours -> int
    j = data.get("periode", {}).get("jours")
    if isinstance(j, str):
        m = re.search(r"\d+", j)
        data["periode"]["jours"] = int(m.group(0)) if m else None

    # 2) fill zipcode from address if missing
    if data["client"].get("zipcode", "") == "" and data["client"].get("address"):
        m = re.search(r"\b\d{5}\b", data["client"]["address"])
        if m:
            data["client"]["zipcode"] = m.group(0)

    # 2b) NEW: split zipcode if it contains the city (e.g., "30190 LA CALMETTE")
    z = data["client"].get("zipcode", "")
    m = re.match(r"^\s*(\d{5})\s*(.*)$", z)
    if m:
        data["client"]["zipcode"] = m.group(1)                # keep only the 5-digit ZIP
        city = m.group(2).strip()
        if city:
            data["client"]["city"] = city                     # optional: store city separately

    # 3) per-energy normalization
    for e in data["energies"]:
        # 3a) parse numeric-like strings first (FR -> float)
        for k in (
            "conso_kwh_total", "conso_hc_kwh", "conso_hp_kwh",
            "prix_hc_eur_kwh", "prix_hp_eur_kwh",
            "abonnement_ttc", "total_ttc",
        ):
            v = e.get(k)
            if isinstance(v, str):
                e[k] = _fr_num(v)

        # 3b) puissance_kVA -> int if possible
        pk = e.get("puissance_kVA")
        if isinstance(pk, str):
            m = re.search(r"\d+", pk)
            e["puissance_kVA"] = int(m.group(0)) if m else None
        elif isinstance(pk, float):  # tolerate float-to-int
            e["puissance_kVA"] = int(pk)

        # 3c) normalize option labels
        opt = (e.get("option") or "").strip().lower()
        if opt in {
            "heures creuses", "hp/hc", "heures pleines/creuses",
            "heures pleines et creuses", "hc/hp", "hp hc"
        }:
            e["option"] = "HP/HC"
        elif opt in {"base", "option base"}:
            e["option"] = "Base"

        # 3d) fix total kWh if inconsistent with HP/HC sum
        hp = e.get("conso_hp_kwh") or 0
        hc = e.get("conso_hc_kwh") or 0
        if isinstance(hp, (int, float)) and isinstance(hc, (int, float)):
            s = hp + hc
            tot = e.get("conso_kwh_total")
            if (tot is None or not isinstance(tot, (int, float))
                or (s and abs(s - tot) / max(s, 1) > 0.2)  # >20% off
                or (tot is not None and tot > 2000)):      # obvious OCR spike
                e["conso_kwh_total"] = s

    return data



def _ensure_shape(d: dict) -> dict:
    """Ensure minimal top-level shape for downstream compatibility."""
    d.setdefault("type_facture", "")
    d.setdefault("client", {}).setdefault("name", "")
    d["client"].setdefault("address", "")
    d["client"].setdefault("zipcode", "")
    d.setdefault("periode", {}).setdefault("de", "")
    d["periode"].setdefault("a", "")
    d["periode"].setdefault("jours", "")
    d.setdefault("energies", [])
    # ensure at least one energy block exists
    if not d["energies"]:
        d["energies"] = [{
            "type":"", "fournisseur":"", "offre":"", "option":"",
            "puissance_kVA":"", "conso_kwh_total":"", "conso_hc_kwh":"",
            "conso_hp_kwh":"", "prix_hc_eur_kwh":"", "prix_hp_eur_kwh":"",
            "abonnement_ttc":"", "total_ttc":""
        }]
    return d

# ── minimal prompt (docs-style) ──────────────────────────────────────────

SYSTEM = (
    "You extract structured data from French electricity/gas invoices. "
    "Return ONLY a JSON object (no prose, no markdown). "
    "If something is not visible, return an empty string for that field."
)

USER_INSTRUCTIONS = """\
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
- Use empty string \"\" for any unknown field.
- Use French field names exactly as shown.
"""

# ── core call ─────────────────────────────────────────────────────────────

def run_pixtral(images: List[str], model: str, energy_hint: Optional[str]) -> dict:
    api_key = _get_api_key()
    if len(images) > 8:
        raise ValueError("Pixtral accepts up to 8 images per request. Pass <= 8.")

    client = Mistral(api_key=api_key)

    content = [{"type": "text", "text": USER_INSTRUCTIONS}]
    if energy_hint and energy_hint != "auto":
        content.insert(0, {"type":"text","text": f"Type attendu: {energy_hint}."})

    for p in images:
        content.append({"type":"image_url","image_url": _b64_data_url(p)})

    resp = client.chat.complete(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": content},
        ],
        response_format={"type": "json_object"},  # simple & reliable
        temperature=0,
        max_tokens=2200,
    )
    text = resp.choices[0].message.content
    data = _extract_json_loose(text)
    return _ensure_shape(data)

# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Extract JSON from invoice images via Mistral Pixtral.")
    ap.add_argument("images", nargs="+", help="Paths to 1..8 images (one invoice).")
    ap.add_argument("-e", "--energy", default="auto",
                    help="Energy type hint: auto|electricite|gaz|dual (default: auto)")
    ap.add_argument("--model", default="pixtral-large-latest",
                    help="Mistral vision model (pixtral-large-latest or pixtral-12b-latest).")
    ap.add_argument("--out", default=None, help="Output JSON path. Default: <first>_<ts>_pixtral.json")
    args = ap.parse_args()

    imgs = [os.path.abspath(p) for p in args.images]
    for p in imgs:
        if not os.path.exists(p):
            print(f"[ERROR] File not found: {p}", file=sys.stderr)
            sys.exit(1)

    out_path = args.out or _default_output_path(imgs[0])

    try:
        data = run_pixtral(imgs, args.model, args.energy)
        # inject hint if user forced it and model left blank
        if args.energy != "auto":
            data["type_facture"] = data.get("type_facture") or args.energy
        data = normalize_pixtral_json(data)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved JSON -> {out_path}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(99)

if __name__ == "__main__":
    main()
