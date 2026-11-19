# AiEdit Frontend (SvelteKit)

Modern UI for the prompt-based video editor. Talks to the FastAPI backend at `http://127.0.0.1:8000`.

## Quick start (from project root)

**Windows:**
```powershell
.\scripts\dev.ps1
```

**Manual (two terminals):**

Terminal 1 — API:
```bash
py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — UI:
```bash
cd frontend
npm install
npm run dev
```

## Routes

| Path | Purpose |
|------|---------|
| `/login` | Sign up / log in |
| `/profile` | Plan, usage, upgrades, logout |
| `/studio` | Upload, prompt, preview, export (requires active plan) |

## Auth & plans

1. Open **http://localhost:5173/login** — sign up or log in (meet **Reel the Clapper** 🎬)
2. Pick **Normal (₹79/week)** or **Premium (₹199/week)** on Profile
3. Go to **Studio** to edit (requires active plan)

Payments are simulated locally until Razorpay is wired.

## Environment

Copy `.env.example` to `.env` if you need a custom API URL:

```
VITE_API_URL=http://127.0.0.1:8000
```

## Stack

- SvelteKit 2 + Svelte 5
- TypeScript
- Tailwind CSS (dark theme, violet accent)

The legacy Streamlit UI (`app.py`) remains available but is no longer the primary interface.
