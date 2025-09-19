# ContractorOS Backend (Compliant MVP)

**Endpoints**
- `GET /health` – quick status
- `POST /analyze_text` – NL → items (uses OpenAI if `OPENAI_API_KEY` is set, else fuzzy rules)
- `POST /analyze_image` – image → items (requires OpenAI vision)
- `POST /price` – returns offers from `materials.yaml` catalog (safe fallback)
- `POST /quote` – totals with markup & tax

**Environment (Render → Environment Variables)**
