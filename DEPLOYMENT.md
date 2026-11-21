# Deploying Es Magico AI Quality Studio (Vercel + Render + Groq)

> **Confidentiality reminder (per assignment brief):** Keep your GitHub repository **Private**, and always set `APP_ACCESS_TOKEN` on Render so neither the assignment data nor your Groq API key is publicly accessible.

## Architecture

```
Vercel (frontend/)            ──HTTPS──▶  Render Web Service (backend/app.py)
React + Vite + TypeScript                  FastAPI wrapping es_eval
                                              ├── SQLite (default, zero setup) or optional Postgres (DATABASE_URL)
                                              └── Groq / OpenAI-compatible LLMs
```

---

## Step 1: Run Locally First

### Backend (FastAPI + SQLite)
```bash
cd es-magico-quality-evaluation
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cp backend/.env.example .env
# Edit .env with your Groq API key (LLM_API_KEY / JUDGE_API_KEY)

uvicorn backend.app:app --reload --port 8000
```

### Frontend (Vite + React)
```bash
cd es-magico-quality-evaluation/frontend
npm install
npm run dev
```
Open `http://localhost:5173`. Vite proxies `/api/*` to `http://127.0.0.1:8000` automatically.

---

## Step 2: Deploy Backend on Render (No Database Required)

1. Push `es-magico-quality-evaluation` to a **private** GitHub repository.
2. In the Render Dashboard, click **New + → Blueprint** and select your repo. Render detects [`render.yaml`](render.yaml) and provisions:
   - `es-magico-eval-api` (Python 3.11 FastAPI Web Service, Free plan, using built-in SQLite by default)
   - *(Optional)* Add a `DATABASE_URL` env var later (e.g., Neon, Supabase, or Render Postgres) only if you want saved runs to survive Render free-tier restarts.
3. Fill in the prompted secrets in Render → **Environment**:
   - `LLM_BASE_URL` = `https://api.groq.com/openai/v1`
   - `LLM_MODEL` = `openai/gpt-oss-20b` (check your Groq Console for active IDs)
   - `LLM_API_KEY` = `gsk_...`
   - `JUDGE_BASE_URL` = `https://api.groq.com/openai/v1` *(or a second provider such as Gemini OpenAI-compat to avoid single-family bias)*
   - `JUDGE_MODEL` = `openai/gpt-oss-120b`
   - `JUDGE_API_KEY` = `gsk_...`
   - `APP_ACCESS_TOKEN` = auto-generated strong secret (copy this to unlock the Vercel UI!)
   - `CORS_ORIGINS` = `https://<your-vercel-app>.vercel.app` (update right after Step 3)
   - `RATE_LIMIT_MIN_DELAY_SECONDS` = `2.5` if using Groq Free Tier (8,000 TPM), or `0.0` on Groq Developer Tier.
4. Verify health at `https://<your-render-service>.onrender.com/api/health`.

---

## Step 3: Deploy Frontend on Vercel

1. In Vercel Dashboard, click **Add New → Project** and import the same private GitHub repo.
2. Set **Root Directory** to `frontend`.
3. Vercel auto-detects Vite via [`frontend/vercel.json`](frontend/vercel.json).
4. Add Environment Variable:
   - `VITE_API_URL` = `https://<your-render-service>.onrender.com` (no trailing slash)
5. Click **Deploy**, then copy your live `https://*.vercel.app` URL into Render's `CORS_ORIGINS` env var and redeploy Render if needed.

---

## Step 4: Complete the Assignment Deliverables

1. Unlock the Studio using your `APP_ACCESS_TOKEN`.
2. In **Eval Runs & Report**, launch a **Smoke Run** (`v1` vs `v2`) first to confirm Groq connectivity & token rates.
3. Launch the **Full 30-Case Run** (`v1` vs `v2`). If Render sleeps or a rate limit pauses it, click **Resume** — all completed events are persisted in Postgres.
4. Open **Blinded Human Review**, personally label the **10 Calibration** outputs first, review agreement, then label the **20 Held-Out Validation** outputs.
5. Click **Download REPORT.md** and **Export JSON** to save the empirical evidence bundle into your submission repo (`runs/main/` and top-level `REPORT.md`).
6. *(Optional bonus)* Run a second evaluation comparing **`v1` vs `v3`** to demonstrate your fixed, spec-compliant prompt!
