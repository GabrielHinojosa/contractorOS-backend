import os, re, json, base64
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx, yaml
from rapidfuzz import process, fuzz

# --------- Environment ----------
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TIMEOUT         = float(os.getenv("HTTP_TIMEOUT", "20"))

# --------- App/CORS ----------
app = FastAPI(title="ContractorOS API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN != "*" else ["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

def load_yaml(path: str) -> dict:
    if not os.path.exists(path): return {}
    with open(path, "r", encoding="utf-8") as f: return yaml.safe_load(f) or {}

CONF      = load_yaml("materials.yaml")
CATALOG   = CONF.get("catalog") or {}
SYN       = CONF.get("synonyms") or {}
PROVIDERS = load_yaml("providers.yaml").get("providers") or []  # kept empty for compliant MVP

# --------- Fuzzy mapping ----------
CANON: Dict[str, str] = {}
for sku, data in CATALOG.items():
    CANON[data["name"].lower()] = sku
for human, variants in SYN.items():
    # try to map variants to a known sku by name start
    sku_guess = None
    for sku, d in CATALOG.items():
        if d["name"].lower().startswith(human.lower()):
            sku_guess = sku
            break
    for v in variants:
        if sku_guess:
            CANON[v.lower()] = sku_guess

def to_sku(text: str) -> Optional[str]:
    t = (text or "").lower().strip()
    if t in CANON: return CANON[t]
    got = process.extractOne(t, list(CANON.keys()), scorer=fuzz.WRatio)
    if got and got[1] >= 80:
        return CANON.get(got[0])

    # also try catalog item names
    names = [CATALOG[k]["name"].lower() for k in CATALOG]
    got2 = process.extractOne(t, names, scorer=fuzz.WRatio)
    if got2 and got2[1] >= 85:
        name = got2[0]
        for sku, d in CATALOG.items():
            if d["name"].lower() == name:
                return sku
    return None

def parse_qty(line: str) -> float:
    m = re.search(r"(^|\\b)(\\d+(?:\\.\\d+)?)", line)
    return float(m.group(2)) if m else 1.0

# --------- Models ----------
class Item(BaseModel):
    name: str
    qty: float
    unit: str = ""
    canonical_hint: str = ""

class AnalyzeTextReq(BaseModel):
    query: str
    zip: str = "78413"

class PriceReq(BaseModel):
    items: List[Item]
    zip: str = "78413"

class QuoteReq(BaseModel):
    items: List[Item]
    markup_pct: float = 15.0
    tax_pct: float = 8.25

# --------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/analyze_text")
def analyze_text(req: AnalyzeTextReq):
    items = []

    # If an API key exists, try OpenAI for smarter parsing
    if OPENAI_API_KEY:
        prompt = f"""
Extract a bill of materials from this text as a JSON array.
Fields per item: name (string), qty (number), unit (string), canonical_hint (closest SKU key if known).
Your SKU key options are: {list(CATALOG.keys())}
Text:
{req.query}
"""
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        body = {"model": OPENAI_MODEL, "messages":[{"role":"user","content": prompt}], "temperature":0.1}
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
                items = json.loads(cleaned)
        except Exception:
            items = []

    # Fallback: rules + fuzzy
    if not items:
        for raw in [l.strip("-• ").strip() for l in req.query.splitlines() if l.strip()]:
            qty = parse_qty(raw)
            sku = to_sku(raw)
            if sku:
                d = CATALOG.get(sku, {})
                items.append({"name": d.get("name", sku), "qty": qty, "unit": d.get("unit",""), "canonical_hint": sku})

    return {"items": items, "zip": req.zip}

@app.post("/analyze_image")
async def analyze_image(file: UploadFile = File(...), zip: str = Form("78413")):
    if not OPENAI_API_KEY:
        raise HTTPException(400, "OPENAI_API_KEY not set; image parsing requires a vision-capable model.")
    content = await file.read()
    mime = file.content_type or "image/jpeg"
    b64 = base64.b64encode(content).decode("utf-8")
    prompt = f"""Extract a bill of materials as JSON array with fields: name, qty (number), unit (string), canonical_hint (closest SKU).
Your SKU key options are: {list(CATALOG.keys())}"""
    body = {
        "model": OPENAI_MODEL,
        "messages":[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url": f"data:{mime};base64,{b64}"}}]}],
        "temperature":0.1
    }
    headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json"}
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
    try:
        s = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        items = json.loads(s)
    except Exception:
        items = []
    return {"items": items, "zip": zip}

@app.post("/price")
def price(req: PriceReq):
    zip5 = (req.zip or "")[:5]
    results = []
    for it in req.items:
        sku = it.canonical_hint or to_sku(it.name) or ""
        offers = []
        if sku and sku in CATALOG:
            for v in CATALOG[sku].get("vendors", []):
                zp = v.get("zipPrefix", "*")
                if zp == "*" or zip5.startswith(zp):
                    offers.append({"store": v["store"], "price": float(v["price"]), "source": "catalog"})
        results.append({"item": it.dict(), "offers": sorted(offers, key=lambda x: x["price"])})
    return {"zip": zip5, "results": results}

@app.post("/quote")
def quote(req: QuoteReq):
    subtotal = 0.0
    for it in req.items:
        price = None
        sku = it.canonical_hint or to_sku(it.name) or ""
        if sku and sku in CATALOG and CATALOG[sku].get("vendors"):
            price = CATALOG[sku]["vendors"][0]["price"]
        subtotal += (float(it.qty) * float(price or 0.0))
    markup = subtotal * (req.markup_pct/100.0)
    tax    = (subtotal + markup) * (req.tax_pct/100.0)
    total  = subtotal + markup + tax
    return {"subtotal": subtotal, "markup": markup, "tax": tax, "total": total}
