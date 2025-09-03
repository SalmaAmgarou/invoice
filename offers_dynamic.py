# offers_dynamic.py
import os, re, json, math, time
from datetime import date
from typing import Dict, Any, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# --- A) Selectra API (if key present) --------------------------------
# Docs/landing: https://api.selectra.com/  (pricing: https://selectra.info/energie/electricite/prix/api)
# The exact endpoint/params may vary with your contract.
SELECTRA_BASE = os.getenv("SELECTRA_BASE", "https://api.selectra.com")
SELECTRA_API_KEY = os.getenv("SELECTRA_API_KEY")  # set this to enable API path

def _map_selectra_offer(o: Dict[str, Any], energy: str, option: Optional[str], kva: Optional[int]) -> Dict[str, Any]:
    return {
        "provider": o.get("supplier_name") or o.get("provider") or "—",
        "offer_name": o.get("offer_name") or o.get("name") or "—",
        "energy": energy,
        "option": option,
        "kva": kva,
        "zone_gaz": o.get("gas_zone"),
        "class_gaz": o.get("gas_class"),
        "price_kwh_ttc": float(o.get("price_kwh_ttc")) if o.get("price_kwh_ttc") is not None else None,
        "abonnement_annuel_ttc": float(o.get("abo_year_ttc")) if o.get("abo_year_ttc") is not None else None,
        "source_url": SELECTRA_BASE,
        "fetched_at": str(date.today()),
    }

def _fetch_selectra_offers(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not SELECTRA_API_KEY:
        return []
    energy = params["energy"]  # "electricite" | "gaz"
    # Example generic comparator endpoint; adapt to your Selectra contract
    url = f"{SELECTRA_BASE}/comparator"
    payload = {
        "api_key": SELECTRA_API_KEY,
        "energy": energy,
        "zipcode": params.get("zipcode", "75001"),
        "consumption_kwh": params.get("consumption_kwh", 3500),
        "kva": params.get("kva", 6),
        "option": params.get("option", "Base"),
        "hp_share": params.get("hp_share"),  # fraction, e.g. 0.35 (optional)
        "gas_zone": params.get("zone_gaz"),
        "gas_class": params.get("class_gaz"),
    }
    r = requests.get(url, params=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    offers = []
    for o in data.get("offers", []):
        offers.append(_map_selectra_offer(o, energy, payload["option"], payload["kva"]))
    return offers

# --- B) Official comparator (free, neutral) via Playwright ------------
# https://comparateur.energie-info.fr/
# We’ll keep this minimal: fill form, submit, read table rows.

def _playwright_offers(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # To keep it zero-config, import on demand.
    from playwright.sync_api import sync_playwright

    energy = params["energy"]
    zipcode = params.get("zipcode", "75001")
    conso = params.get("consumption_kwh", 3500)
    kva = params.get("kva", 6)
    option = (params.get("option") or "Base").strip()

    url = "https://comparateur.energie-info.fr/"

    results: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)

        # Choose Particulier
        page.get_by_text("Particulier").click()

        # Fill energy type & basic profile
        if energy == "electricite":
            page.get_by_label("Électricité").check()
            # puissance (kVA)
            page.select_option("select[name='power']", str(kva))
            # option
            if option.lower().startswith("hp"):
                page.get_by_label("Heures pleines / Heures creuses").check()
                # If you store user HP share, the comparator may have a slider/field:
                # page.fill("input[name='hp_share']", str(int((params.get('hp_share') or 0.35)*100)))
            else:
                page.get_by_label("Option Base").check()

            page.fill("input[name='postalCode']", zipcode)
            page.fill("input[name='annualConsumption']", str(int(conso)))

        elif energy == "gaz":
            page.get_by_label("Gaz naturel").check()
            page.fill("input[name='postalCode']", zipcode)
            page.fill("input[name='annualConsumption']", str(int(conso)))
            # If you have zone/classe, some fields appear or are inferred after postal code.

        # Submit (button label can change; look for “Comparer”)
        page.get_by_role("button", name=re.compile("Comparer|Lancer", re.I)).click()
        page.wait_for_selector("table", timeout=60000)

        # Parse first result table
        html = page.content()
        browser.close()

    # very light HTML parse
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return results

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    # We expect columns like: Fournisseur, Offre, Prix kWh TTC, Abonnement TTC, etc.
    for tr in table.find_all("tr")[1:]:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 3:
            continue
        provider = tds[0]
        offer_name = tds[1]
        # find numbers in the rest
        price_kwh = _to_float_euro_per_kwh(" ".join(tds))
        abo = _to_float_euro(" ".join(tds))
        results.append({
            "provider": provider,
            "offer_name": offer_name,
            "energy": energy,
            "option": option if energy=="electricite" else None,
            "kva": kva if energy=="electricite" else None,
            "zone_gaz": params.get("zone_gaz"),
            "class_gaz": params.get("class_gaz"),
            "price_kwh_ttc": price_kwh,
            "abonnement_annuel_ttc": abo,
            "source_url": url,
            "fetched_at": str(date.today()),
        })
    # NOTE: selectors can change; if so, adjust the parsing block above.
    return [o for o in results if o["price_kwh_ttc"] and o["abonnement_annuel_ttc"]]

def _to_float_euro(s: str) -> Optional[float]:
    # looks for e.g. 185,64 € or 185.64 €
    m = re.search(r"(\d{1,4}[.,]\d{2})\s*€", s)
    return float(m.group(1).replace(",", ".")) if m else None

def _to_float_euro_per_kwh(s: str) -> Optional[float]:
    # looks for e.g. 0,1952 €/kWh
    m = re.search(r"(\d{1}[.,]\d{3,4})\s*€\s*/?\s*kWh", s, flags=re.I)
    return float(m.group(1).replace(",", ".")) if m else None

# --- C) Minimal EDF adapter (Tarif Bleu) as safety net ---------------
EDF_JECHANGE = "https://www.jechange.fr/energie/edf/tarifs/tarif-bleu"  # monthly summary values
def _edf_tarif_bleu(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    if params.get("energy") != "electricite":
        return []
    # Fetch page and extract a couple of numbers (quick-start)
    r = requests.get(EDF_JECHANGE, timeout=15)
    r.raise_for_status()
    text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    m_base = re.search(r"(0[.,]\d{3,4})\s*€/?kWh\s*\(base\)", text, flags=re.I)
    m_hp = re.search(r"(0[.,]\d{3,4})\s*€/?kWh\s*\(heures pleines\)", text, flags=re.I)
    m_hc = re.search(r"(0[.,]\d{3,4})\s*€/?kWh\s*\(heures creuses\)", text, flags=re.I)
    # Abonnement baseline for 6 kVA (approx)
    m_abo6 = re.search(r"(\d{2,3}[.,]\d{2})\s*€\s*(par an|pour l'abonnement annuel).{0,80}6\s*kVA", text, flags=re.I)
    abo6 = float(m_abo6.group(1).replace(",", ".")) if m_abo6 else None

    kva = int(params.get("kva") or 6)
    # scale abo roughly for demo (replace by official PDF parse if you need exact per kVA)
    scale = {3:0.9, 6:1.0, 9:1.22, 12:1.43, 15:1.65, 18:1.87, 24:2.45, 30:3.0, 36:3.55}
    abo = round((abo6 or 186.0) * scale.get(kva, 1.0), 2)

    offers = []
    if m_base:
        offers.append({
            "provider": "EDF",
            "offer_name": "Tarif Bleu (Base)",
            "energy": "electricite",
            "option": "Base",
            "kva": kva,
            "zone_gaz": None, "class_gaz": None,
            "price_kwh_ttc": float(m_base.group(1).replace(",", ".")),
            "abonnement_annuel_ttc": abo,
            "source_url": EDF_JECHANGE,
            "fetched_at": str(date.today()),
        })
    if m_hp and m_hc:
        hp = float(m_hp.group(1).replace(",", "."))
        hc = float(m_hc.group(1).replace(",", "."))
        hp_share = float(params.get("hp_share") or 0.35)
        blended = round(hp*hp_share + hc*(1-hp_share), 4)
        offers.append({
            "provider": "EDF",
            "offer_name": "Tarif Bleu (HP/HC)",
            "energy": "electricite",
            "option": "HP/HC",
            "kva": kva,
            "zone_gaz": None, "class_gaz": None,
            "price_kwh_ttc": blended,
            "abonnement_annuel_ttc": abo,
            "source_url": EDF_JECHANGE,
            "fetched_at": str(date.today()),
        })
    return offers

# --- Public entrypoint ------------------------------------------------
def get_offers_dynamic(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Returns a normalized list of offers for *this month* that fits your pipeline.

    Strategy:
      1) Selectra API (if SELECTRA_API_KEY is set)
      2) Official comparator via Playwright
      3) EDF fallback
    """
    # Try API first (all providers)
    try:
        api_offers = _fetch_selectra_offers(params)
        if api_offers:
            return _dedupe(api_offers)
    except Exception as e:
        print(f"[WARN] Selectra API failed: {e}")

    # Then official comparator (free)
    try:
        plw = _playwright_offers(params)
        if plw:
            return _dedupe(plw)
    except Exception as e:
        print(f"[WARN] Comparator scrape failed: {e}")

    # Fallback: EDF recent values (never returns empty for electricity)
    try:
        return _dedupe(_edf_tarif_bleu(params))
    except Exception as e:
        print(f"[WARN] EDF fallback failed: {e}")
        return []

def _dedupe(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for o in offers:
        key = (o.get("provider"), o.get("offer_name"), o.get("option"), o.get("kva"), o.get("energy"))
        if key not in seen and o.get("price_kwh_ttc") and o.get("abonnement_annuel_ttc"):
            seen.add(key)
            out.append(o)
    return out
