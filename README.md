
# ContractorOS Backend (FastAPI)

Endpoints:
- `GET /health` → {"ok": true}
- `POST /normalize` → turns free text into items [{name, qty, unit, canonical_hint}]
- `POST /prices` → returns vendor offers per item for a ZIP
- `POST /quote` → computes totals (uses lowest vendor price per item)

## Deploy on Render
1. Push these files to a new GitHub repo.
2. Render → New → Web Service → connect the repo.
3. Environment:
   - `FRONTEND_ORIGIN` = your Netlify URL (e.g., https://webappmats.netlify.app)
4. Build command:
   `pip install -r requirements.txt`
5. Start command:
   `uvicorn app:app --host 0.0.0.0 --port $PORT`

## Test
- `GET https://YOUR-RENDER-URL/health`
- `POST /normalize` with JSON: {"text":"1000 2x4 studs\n200 sheets 7/16 OSB","zip":"78413"}
- `POST /prices` with the items from /normalize
- `POST /quote` with items + markup_pct + tax_pct
