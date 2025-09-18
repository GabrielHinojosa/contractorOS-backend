# app.py
import os, re, json
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup

# ---------- Config ----------
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # small + fast
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))

app = FastAPI(title="ContractorOS API", version="0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Mock catalog (kept from your MVP) ----------
VENDOR_CATALOG: Dict[str, Dict[str, Any]] = {
    "2x4_stud_92": {
        "name": '2x4 Stud 92-5/8"',
        "unit": "each",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 3.69},
            {"store": "Home Depot", "zipPrefix": "784", "price": 3.79},
            {"store": "Lowe's", "zipPrefix": "784", "price": 3.75},
            {"store": "Generic", "zipPrefix": "*", "price": 4.10},
        ],
    },
    "2x4_plate_lf": {
        "name": "2x4 Plate (linear ft)",
        "unit": "lf",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 0.85},
            {"store": "Home Depot", "zipPrefix": "784", "price": 0.92},
            {"store": "Lowe's", "zipPrefix": "784", "price": 0.90},
            {"store": "Generic", "zipPrefix": "*", "price": 1.05},
        ],
    },
    "2x1012_joist": {
        "name": "2x10x12 Joist",
        "unit": "each",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 19.80},
            {"store": "Home Depot", "zipPrefix": "784", "price": 20.50},
            {"store": "Lowe's", "zipPrefix": "784", "price": 20.10},
            {"store": "Generic", "zipPrefix": "*", "price": 22.00},
        ],
    },
    "osb_716_4x8": {
        "name": 'OSB Sheathing 7/16" 4x8',
        "unit": "sheet",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 12.95},
            {"store": "Home Depot", "zipPrefix": "784", "price": 13.20},
            {"store": "Lowe's", "zipPrefix": "784", "price": 13.10},
            {"store": "Generic", "zipPrefix": "*", "price": 14.00},
        ],
    },
    "hurricane_tie": {
        "name": "Hurricane Tie",
        "unit": "each",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 0.89},
            {"store": "Home Depot", "zipPrefix": "784", "price": 0.98},
            {"store": "Lowe's", "zipPrefix": "784", "price": 0.95},
            {"store": "Generic", "zipPrefix": "*", "price": 1.10},
        ],
    },
    "nails_lb": {
        "name": "Nails (per lb)",
        "unit": "lb",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 2.10},
            {"store": "Home Depot", "zipPrefix": "784", "price": 2.30},
            {"store": "Lowe's", "zipPrefix": "784", "price": 2.25},
            {"store": "Generic", "zipPrefix": "*", "price": 2.60},
        ],
    },
    "screws_lb": {
        "name": "Exterior Screws (per lb)",
        "unit": "lb",
        "vendors": [
            {"store": "McCoy's", "zipPrefix": "784", "price": 4.90},
            {"store": "Home Depot", "zipPrefix": "784", "price": 5.30},
            {"store": "Lowe's", "zipPrefix": "784", "price": 5.10},
            {"store": "Generic", "zipPrefix": "*", "price": 5.70},
        ],
    },
}

# ---------- Models ----------
class NormalizeReq(BaseModel):
    text: str
    zip: str

class Item(BaseModel):
    name: str
    qty: float
    unit: str
    canonical_hint: str

class QuoteReq(BaseModel):
    items: List[Item]
    markup_pct: float
    tax_pct: float

class PricesReq(BaseModel):
    items: List[Item]
    zip: str

# ---------- Simple parser (kept for fallback) ----------
def parse_line(line: str):
    l = line.lower()
    qty_match = re.search(r"(^|\\s)(\\d+(?:\\.\\d+)?)", l)
    qty = float(qty_match.group(2)) if qty_match else 1.0
    if "2x4" in l and ("stud" in l or "92" in l): return ("2x4_stud_92", qty)
    if "2x4" in l and ("plate" in l or "lf" in l or "linear" in l): return ("2x4_plate_lf", qty)
    if "2x10" in l and ("12" in l or "joist" in l): return ("2x1012_joist", qty)
    if ("osb" in l or "sheath" in l) and ("7/16" in l or "716" in l): return ("osb_716_4x8", qty)
    if "hurricane" in l: return ("hurricane_tie", qty)
    if "nail" in l: return ("nails_lb", qty)
    if "screw" in l: return ("screws_lb", qty)
    if "stud" in l: return ("2x4_stud_92", qty)
    if "joist" in l: return ("2x1012_joist", qty)
    return (None, None)

# ---------- Routes you already had ----------
@app.get("/health")
def health():
    return {"ok": True, "service": "ContractorOS API"}

@app.post("/normalize")
def normalize(req: NormalizeReq):
    items: Dict[str, float] = {}
    for raw in req.text.splitlines():
        raw = raw.strip("-• ").strip()
        if not raw: continue
        sku, qty = parse_line(raw)
        if not sku: continue
        items[sku] = items.get(sku, 0) + float(qty)
    out: List[Item] = []
    for sku, qty in items.items():
        cat = VENDOR_CATALOG.get(sku, {})
        out.append(Item(name=cat.get("name", sku), qty=qty, unit=cat.get("unit", ""), canonical_hint=sku))
    return {"items": [i.dict() for i in out]}

@app.post("/quote")
def quote(req: QuoteReq):
    subtotal = 0.0
    for it in req.items:
        cat = VENDOR_CATALOG.get(it.canonical_hint)
        if not cat: continue
        offers = sorted(cat["vendors"], key=lambda v: v["price"])
        price = offers[0]["price"]
        subtotal += float(it.qty) * float(price)
    markup = subtotal * (req.markup_pct/100.0)
    tax = (subtotal + markup) * (req.tax_pct/100.0)
    total = subtotal + markup + tax
    return {"subtotal": subtotal, "markup": markup, "tax": tax, "total": total}

@app.post("/prices")
def prices(req: PricesReq):
    zip5 = (req.zip or "").strip()[:5]
    results = []
    for it in req.items:
        cat = VENDOR_CATALOG.get(it.canonical_hint)
        if not cat:
            results.append({"item": it.dict(), "offers": []})
            continue
        offers = sorted(
            [v for v in cat["vendors"] if v["zipPrefix"] == "*" or zip5.startswith(v["zipPrefix"])],
            key=lambda v: v["price"]
        )
        results.append({"item": it.dict(), "offers": offers})
    return {"results": results, "zip": zip5}

# ---------- NEW: GPT normalization ----------
@app.post("/normalize_gpt")
def normalize_gpt(req: NormalizeReq):
    if not OPENAI_API_KEY:
        # If no key, fall back to rules
        return normalize(req)

    prompt = f"""
You are a materials estimator. Parse the following free-text list into a JSON array of items.
Schema for each item: {{
  "name": string,              // human-readable normalized name
  "qty": number,               // numeric quantity
  "unit": string,              // e.g., each, sheet, lf, lb
  "canonical_hint": string     // pick closest of: {list(VENDOR_CATALOG.keys())}
}}
Be strict about JSON. If unsure, best-guess and map to the closest canonical_hint.
Text:
{req.text}
"""

    # Minimal OpenAI call through raw HTTP to keep requirements simple
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            # Ensure we extract JSON even if the model wraps it
            json_str = content.strip()
            json_str = re.sub(r"^```(?:json)?|```$", "", json_str, flags=re.MULTILINE).strip()
            items_raw = json.loads(json_str)
            out = []
            for it in items_raw:
                sku = it.get("canonical_hint") or ""
                if sku not in VENDOR_CATALOG:
                    # try a naive map: keywords
                    nm = (it.get("name") or "").lower()
                    sku_guess, _ = parse_line(nm)
                    sku = sku if sku in VENDOR_CATALOG else (sku_guess or "2x4_stud_92")
                out.append(Item(
                    name=it.get("name","item"),
                    qty=float(it.get("qty",1)),
                    unit=it.get("unit",""),
                    canonical_hint=sku
                ))
            return {"items": [i.dict() for i in out]}
    except Exception as e:
        # Fallback to rules on any error
        return normalize(req)

# ---------- NEW: live price fetch (beta) ----------
# IMPORTANT: this uses public HTML and may break if sites change. Use respectfully and cache results.
SEARCH_TEMPLATES = {
    # naive search URLs; location-specific pricing may require cookies/sign-in on real sites
    "Home Depot": "https://www.homedepot.com/s/{query}",
    "Lowe's":      "https://www.lowes.com/search?searchTerm={query}"
}

def extract_usd(text: str) -> float | None:
    m = re.search(r"\$\\s*([0-9]+(?:\\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None

async def fetch_price(session: httpx.AsyncClient, url: str) -> float | None:
    try:
        r = await session.get(url, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # very loose extraction: pick first $price-like pattern on the page
        # (For production, use site-specific selectors.)
        txt = soup.get_text(" ", strip=True)
        return extract_usd(txt)
    except Exception:
        return None

@app.post("/prices_live")
async def prices_live(req: PricesReq):
    # Build naive search queries per item name
    results = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as session:
        for it in req.items:
            offers = []
            q = (it.name or it.canonical_hint).replace('"','').replace("  "," ").strip()
            for store, tmpl in SEARCH_TEMPLATES.items():
                url = tmpl.format(query=httpx.utils.quote(q))
                price = await fetch_price(session, url)
                if price:
                    offers.append({"store": store+" (live beta)", "price": price, "url": url})
            # backstop: if no live price, fall back to catalog vendors
            if not offers:
                cat = VENDOR_CATALOG.get(it.canonical_hint)
                if cat:
                    offers = sorted(cat["vendors"], key=lambda v: v["price"])
            results.append({"item": it.dict(), "offers": offers})
    return {"results": results, "zip": (req.zip or "")[:5], "mode": "live-beta"}

