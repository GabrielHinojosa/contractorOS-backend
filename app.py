
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any

# ---------- Config ----------
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")  # set to your Netlify URL for production
PORT = int(os.getenv("PORT", "10000"))

app = FastAPI(title="ContractorOS API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Data (Mock vendors for demo; replace with real feeds later) ----------
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

# ---------- Utils ----------
def parse_line(line: str):
    l = line.lower()
    import re
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

# ---------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True, "service": "ContractorOS API"}

@app.post("/normalize")
def normalize(req: NormalizeReq):
    # For MVP, use simple rules. Later: swap with GPT for better parsing.
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
        out.append(Item(
            name=cat.get("name", sku),
            qty=qty,
            unit=cat.get("unit", ""),
            canonical_hint=sku
        ))
    return {"items": [i.dict() for i in out]}

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
        results.append({
            "item": it.dict(),
            "offers": offers
        })
    return {"results": results, "zip": zip5}

@app.post("/quote")
def quote(req: QuoteReq):
    subtotal = 0.0
    for it in req.items:
        # For demo, choose lowest vendor price for each item
        cat = VENDOR_CATALOG.get(it.canonical_hint)
        if not cat: continue
        offers = sorted(cat["vendors"], key=lambda v: v["price"])
        price = offers[0]["price"]
        subtotal += float(it.qty) * float(price)
    markup = subtotal * (req.markup_pct/100.0)
    tax = (subtotal + markup) * (req.tax_pct/100.0)
    total = subtotal + markup + tax
    return {"subtotal": subtotal, "markup": markup, "tax": tax, "total": total}
