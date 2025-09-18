import os, re, json, time, csv
from typing import List, Dict, Any, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
from rapidfuzz import process, fuzz
import yaml

# -------- Config --------
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))

app = FastAPI(title="ContractorOS API", version="0.4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- Catalog (baseline for fallback pricing) --------
VENDOR_CATALOG: Dict[str, Dict[str, Any]] = {
    "2x4_stud_92": {"name": '2x4 Stud 92-5/8"', "unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":3.69},
            {"store":"Home Depot","zipPrefix":"784","price":3.79},
            {"store":"Lowe's","zipPrefix":"784","price":3.75},
            {"store":"Generic","zipPrefix":"*","price":4.10},
        ]},
    "2x4_plate_lf": {"name":"2x4 Plate (linear ft)","unit":"lf",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":0.85},
            {"store":"Home Depot","zipPrefix":"784","price":0.92},
            {"store":"Lowe's","zipPrefix":"784","price":0.90},
            {"store":"Generic","zipPrefix":"*","price":1.05},
        ]},
    "2x1012_joist": {"name":"2x10x12 Joist","unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":19.80},
            {"store":"Home Depot","zipPrefix":"784","price":20.50},
            {"store":"Lowe's","zipPrefix":"784","price":20.10},
            {"store":"Generic","zipPrefix":"*","price":22.00},
        ]},
    "osb_716_4x8": {"name":'OSB Sheathing 7/16" 4x8',"unit":"sheet",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":12.95},
            {"store":"Home Depot","zipPrefix":"784","price":13.20},
            {"store":"Lowe's","zipPrefix":"784","price":13.10},
            {"store":"Generic","zipPrefix":"*","price":14.00},
        ]},
    "hurricane_tie": {"name":"Hurricane Tie","unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":0.89},
            {"store":"Home Depot","zipPrefix":"784","price":0.98},
            {"store":"Lowe's","zipPrefix":"784","price":0.95},
            {"store":"Generic","zipPrefix":"*","price":1.10},
        ]},
    "nails_lb": {"name":"Nails (per lb)","unit":"lb",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":2.10},
            {"store":"Home Depot","zipPrefix":"784","price":2.30},
            {"store":"Lowe's","zipPrefix":"784","price":2.25},
            {"store":"Generic","zipPrefix":"*","price":2.60},
        ]},
    "screws_lb": {"name":"Exterior Screws (per lb)","unit":"lb",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":4.90},
            {"store":"Home Depot","zipPrefix":"784","price":5.30},
            {"store":"Lowe's","zipPrefix":"784","price":5.10},
            {"store":"Generic","zipPrefix":"*","price":5.70},
        ]},
    "4x4_post_8": {"name":"4x4x8 Treated Post","unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":12.98},
            {"store":"Home Depot","zipPrefix":"784","price":13.77},
            {"store":"Lowe's","zipPrefix":"784","price":13.42},
            {"store":"Generic","zipPrefix":"*","price":14.99},
        ]},
    "4x4_post_10": {"name":"4x4x10 Treated Post","unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":18.90},
            {"store":"Home Depot","zipPrefix":"784","price":19.45},
            {"store":"Lowe's","zipPrefix":"784","price":19.20},
            {"store":"Generic","zipPrefix":"*","price":20.90},
        ]},
    "2x4x16": {"name":"2x4x16 Treated","unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":10.20},
            {"store":"Home Depot","zipPrefix":"784","price":10.68},
            {"store":"Lowe's","zipPrefix":"784","price":10.49},
            {"store":"Generic","zipPrefix":"*","price":11.30},
        ]},
    "picket_treated":{"name":"Fence picket (treated)","unit":"each",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":2.35},
            {"store":"Home Depot","zipPrefix":"784","price":2.48},
            {"store":"Lowe's","zipPrefix":"784","price":2.44},
            {"store":"Generic","zipPrefix":"*","price":2.69},
        ]},
    "quikrete_50lb":{"name":"Quikrete 50 lb","unit":"bag",
        "vendors":[
            {"store":"McCoy's","zipPrefix":"784","price":4.95},
            {"store":"Home Depot","zipPrefix":"784","price":5.25},
            {"store":"Lowe's","zipPrefix":"784","price":5.10},
            {"store":"Generic","zipPrefix":"*","price":5.60},
        ]},
}

# -------- Load YAML config (synonyms/providers) --------
def load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

MATS = load_yaml("materials.yaml")
PROVIDERS = load_yaml("providers.yaml")

# -------- Fuzzy mapping --------
CANON_MAP = {
    "4x4 post 8": "4x4_post_8",
    "4x4x8": "4x4_post_8",
    "4x4 post 10": "4x4_post_10",
    "4x4x10": "4x4_post_10",
    "2x4x16": "2x4x16",
    "2x4 16": "2x4x16",
    "2x4 plate": "2x4_plate_lf",
    "stud 92": "2x4_stud_92",
    "osb 7/16": "osb_716_4x8",
    "hurricane tie": "hurricane_tie",
    "nails": "nails_lb",
    "screws": "screws_lb",
    "pickets": "picket_treated",
    "quikrete 50 lb": "quikrete_50lb",
    "quikrete 50lb": "quikrete_50lb",
}
# also inject synonyms from materials.yaml
for k, vals in (MATS.get("synonyms") or {}).items():
    for v in vals:
        CANON_MAP[v.lower()] = CANON_MAP.get(v.lower(), None) or k.lower()

def fuzzy_to_sku(text: str) -> Optional[str]:
    text = (text or "").lower().replace('"','').replace("in","").strip()
    if text in CANON_MAP:
        key = CANON_MAP[text]
        for sku, data in VENDOR_CATALOG.items():
            if data["name"].lower().startswith(key) or sku == key:
                return sku
        if text in VENDOR_CATALOG:
            return text
    candidates = list(CANON_MAP.keys()) + [VENDOR_CATALOG[k]["name"].lower() for k in VENDOR_CATALOG]
    got = process.extractOne(text, candidates, scorer=fuzz.WRatio)
    if got and got[1] >= 80:
        match = got[0]
        if match in CANON_MAP:
            target = CANON_MAP[match]
            for sku, data in VENDOR_CATALOG.items():
                if data["name"].lower().startswith(target) or sku == target:
                    return sku
        else:
            for sku, data in VENDOR_CATALOG.items():
                if data["name"].lower() == match:
                    return sku
    return None

# -------- Models --------
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

class SearchReq(BaseModel):
    query: str
    zip: str
    limit: Optional[int] = 10

# -------- Utilities --------
def parse_line(line: str):
    l = line.lower()
    m = re.search(r"(^|\s)(\d+(?:\.\d+)?)", l)
    qty = float(m.group(2)) if m else 1.0
    if "2x4" in l and ("stud" in l or "92" in l): return ("2x4_stud_92", qty)
    if "2x4" in l and ("plate" in l or "lf" in l or "linear" in l): return ("2x4_plate_lf", qty)
    if "2x10" in l and ("12" in l or "joist" in l): return ("2x1012_joist", qty)
    if ("osb" in l or "sheath" in l) and ("7/16" in l or "716" in l): return ("osb_716_4x8", qty)
    if "hurricane" in l: return ("hurricane_tie", qty)
    if "nail" in l: return ("nails_lb", qty)
    if "screw" in l: return ("screws_lb", qty)
    if "4x4" in l and ("8" in l): return ("4x4_post_8", qty)
    if "4x4" in l and ("10" in l): return ("4x4_post_10", qty)
    return (None, None)

def usd(text: str) -> Optional[float]:
    m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None

# -------- Routes --------
@app.get("/")
def root():
    return {"service":"ContractorOS API","status":"running",
            "endpoints":["/health","/normalize","/normalize_gpt","/search_materials","/prices","/prices_live","/quote"]}

@app.get("/health")
def health():
    return {"ok": True, "service": "ContractorOS API"}

# Basic rules parser (fallback)
@app.post("/normalize")
def normalize(req: NormalizeReq):
    items: Dict[str, float] = {}
    for raw in req.text.splitlines():
        raw = raw.strip("-• ").strip()
        if not raw: continue
        sku, qty = parse_line(raw)
        if not sku:
            sku = fuzzy_to_sku(raw)
        if not sku:
            continue
        items[sku] = items.get(sku, 0) + float(qty)
    out: List[Item] = []
    for sku, qty in items.items():
        cat = VENDOR_CATALOG.get(sku, {})
        out.append(Item(name=cat.get("name", sku), qty=qty, unit=cat.get("unit", ""), canonical_hint=sku))
    return {"items": [i.dict() for i in out]}

# GPT normalization (structured)
@app.post("/normalize_gpt")
def normalize_gpt(req: NormalizeReq):
    if not OPENAI_API_KEY:
        return normalize(req)
    prompt = f"""
You are a materials estimator. Parse the list into JSON array of items with fields:
name, qty, unit, canonical_hint (pick closest from keys: {list(VENDOR_CATALOG.keys())}).
Text:
{req.text}
"""
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "messages":[{"role":"user","content": prompt}], "temperature":0.1}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            s = content.strip()
            s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
            arr = json.loads(s)
            out = []
            for it in arr:
                sku = it.get("canonical_hint") or ""
                if sku not in VENDOR_CATALOG:
                    sku_guess, _ = parse_line((it.get("name") or ""))
                    sku_fuzzy = fuzzy_to_sku((it.get("name") or ""))
                    sku = sku if sku in VENDOR_CATALOG else (sku_fuzzy or sku_guess or "2x4_stud_92")
                out.append(Item(name=it.get("name","item"), qty=float(it.get("qty",1)), unit=it.get("unit",""), canonical_hint=sku))
            return {"items":[i.dict() for i in out]}
    except Exception:
        return normalize(req)

# Live prices (HTML adapters + CSV + fallback to catalog)
async def fetch_price_by_provider(session: httpx.AsyncClient, provider: dict, query: str) -> Optional[Dict[str, Any]]:
    typ = provider.get("type")
    if typ == "html":
        url = provider["search"].format(q=httpx.utils.quote(query))
        r = await session.get(url, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        title_sel = provider["selectors"].get("title","")
        price_sel = provider["selectors"].get("price","")
        title_el = soup.select_one(title_sel) if title_sel else None
        price_el = soup.select_one(price_sel) if price_sel else None
        title = title_el.get_text(" ", strip=True) if title_el else query
        price = usd(price_el.get_text(" ", strip=True)) if price_el else usd(soup.get_text(" ", strip=True))
        if price:
            return {"store": provider["name"].replace("_"," ").title()+" (live)", "price": price, "url": url, "title": title}
        return None
    elif typ == "csv":
        path = provider.get("path","")
        zf = provider.get("zip_filter","")
        try:
            rows = []
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if zf and not row.get("zipPrefix","").startswith(zf): 
                        continue
                    rows.append(row)
            if rows:
                titles = [r["title"] for r in rows]
                got = process.extractOne(query, titles, scorer=fuzz.WRatio)
                if got and got[1] >= 70:
                    row = rows[got[2]]
                    price = float(row.get("price",0) or 0)
                    return {"store":"Local CSV", "price": price, "title": row.get("title",""), "sku": row.get("sku","")}
        except Exception:
            return None
    return None

@app.post("/prices_live")
async def prices_live(req: PricesReq):
    zip5 = (req.zip or "")[:5]
    out = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as session:
        for it in req.items:
            q = (it.name or it.canonical_hint).replace('"','').strip()
            offers = []
            for provider in (PROVIDERS.get("providers") or []):
                got = await fetch_price_by_provider(session, provider, q)
                if got:
                    offers.append(got)
            if not offers:
                cat = VENDOR_CATALOG.get(it.canonical_hint)
                if cat:
                    offers = sorted(cat["vendors"], key=lambda v: v["price"])
            out.append({"item": it.dict(), "offers": offers})
    return {"zip": zip5, "results": out, "mode":"universal-live"}

# Universal smart search: free text -> intents -> offers
class Intent(BaseModel):
    name: str
    qty: float
    unit: str
    canonical_hint: str

def simple_intents_from_text(text: str) -> List[Intent]:
    intents: Dict[str,float] = {}
    for raw in text.splitlines():
        raw = raw.strip("-• ").strip()
        if not raw: continue
        sku, qty = parse_line(raw)
        if not sku:
            sku = fuzzy_to_sku(raw)
        if not sku:
            continue
        intents[sku] = intents.get(sku, 0.0) + (qty or 1.0)
    out: List[Intent] = []
    for sku, qty in intents.items():
        cat = VENDOR_CATALOG.get(sku, {})
        out.append(Intent(name=cat.get("name", sku), qty=qty, unit=cat.get("unit",""), canonical_hint=sku))
    return out

@app.post("/search_materials")
async def search_materials(req: SearchReq):
    intents: List[Intent] = []
    if OPENAI_API_KEY:
        try:
            prompt = f"""Turn this request into a JSON array of items with fields:
name, qty, unit, canonical_hint (closest of: {list(VENDOR_CATALOG.keys())}).
Text:
{req.query}
"""
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json"}
            body = {"model": OPENAI_MODEL, "messages":[{"role":"user","content":prompt}], "temperature":0.1}
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
                r.raise_for_status()
                s = r.json()["choices"][0]["message"]["content"].strip()
                s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
                arr = json.loads(s)
                for it in arr:
                    sku = it.get("canonical_hint") or ""
                    if sku not in VENDOR_CATALOG:
                        sku_guess, _ = parse_line((it.get("name") or ""))
                        sku_fuzzy = fuzzy_to_sku((it.get("name") or ""))
                        sku = sku if sku in VENDOR_CATALOG else (sku_fuzzy or sku_guess or "2x4_stud_92")
                    intents.append(Intent(name=it.get("name","item"), qty=float(it.get("qty",1)), unit=it.get("unit",""), canonical_hint=sku))
        except Exception:
            intents = simple_intents_from_text(req.query)
    else:
        intents = simple_intents_from_text(req.query)

    prices_req = PricesReq(items=[Item(**i.dict()) for i in intents], zip=req.zip)
    live = await prices_live(prices_req)
    for i, row in enumerate(live["results"]):
        row["intent"] = intents[i].dict()
        row["offers"] = (row.get("offers") or [])[: req.limit or 10]
    return {"items": live["results"], "zip": req.zip}

# Simple catalog quote (uses cheapest catalog vendor as unit price)
@app.post("/quote")
def quote(req: QuoteReq):
    subtotal = 0.0
    for it in req.items:
        cat = VENDOR_CATALOG.get(it.canonical_hint)
        if not cat: 
            continue
        offers = sorted(cat["vendors"], key=lambda v: v["price"])
        price = offers[0]["price"]
        subtotal += float(it.qty) * float(price)
    markup = subtotal * (req.markup_pct/100.0)
    tax = (subtotal + markup) * (req.tax_pct/100.0)
    total = subtotal + markup + tax
    return {"subtotal": subtotal, "markup": markup, "tax": tax, "total": total}
