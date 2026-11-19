# AiEdit

AiEdit is a prompt-based AI video editor. Describe your edit in natural language, preview the result, and export MP4.

**Primary UI:** SvelteKit frontend + FastAPI backend (local). Legacy Streamlit UI (`app.py`) remains available.

## Documentation

| Doc | Contents |
|-----|----------|
| [`docs/CURRENT_STATE_AND_ROADMAP.md`](docs/CURRENT_STATE_AND_ROADMAP.md) | Implementation status, gaps, phased roadmap |
| [`docs/PRODUCT_TIERS.md`](docs/PRODUCT_TIERS.md) | Normal vs Premium plans, billing, operations |
| [`docs/LLM_PROMPT_PARSER_PLAN.md`](docs/LLM_PROMPT_PARSER_PLAN.md) | LLM parser architecture and schema |
| [`frontend/README.md`](frontend/README.md) | SvelteKit UI setup and auth flow |

## What It Can Do

### Timeline (Normal plan — FFmpeg)

- Trim / cut clips by time range
- Speed change — slow-mo, timelapse, segment speed
- Crop / resize — 9:16 (TikTok/Reels), 16:9, square, etc.
- Volume, mute, audio fade
- Video fade in / fade out
- Rotate and flip
- Brightness, contrast, saturation presets
- Combined zoom + speed montages

### Visual & text (Normal plan)

- Extract frames from a video
- Detect, remove, and replace on-screen text (OCR)
- Recolor character hair
- Recolor, remove, or reference-replace grounded objects
- Global color change with tolerance
- Atmosphere / weather / mood overlays
- Auto play-by-play commentary

### Premium (stub)

- AI code-gen path for prompts that do not map to a built-in operation (sandbox in progress)

## Accounts & plans

1. Open **http://localhost:5173/login** — sign up or log in
2. Choose **Normal (₹79/week)** or **Premium (₹199/week)** on Profile
3. Edit in **Studio** (active plan required; daily edit quota applies)

Payments are simulated locally until Razorpay is connected. See `docs/PRODUCT_TIERS.md`.

## Current Limits

- Broad scene redesign still out of scope for the mask-based workflow
- Premium code-gen execution is not implemented yet (routing + upsell work)
- Object replacement works best with a reference image
- Text quality depends on OCR and frame clarity
- LLM parsing is best with Ollama running locally (rule fallback always available)

## Recommended Hardware

- Best experience: NVIDIA GPU with CUDA
- Good starting point: 8 GB VRAM
- Better for longer clips: 12–16 GB VRAM
- CPU works for timeline-only edits; object/text paths are slower

## Install

```bash
py -m pip install -r requirements.txt
```

## Run (recommended)

**One command (Windows):**

```powershell
.\scripts\dev.ps1
```

**Or two terminals:**

Terminal 1 — API:

```bash
py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173/login**.

## Run (legacy Streamlit UI)

```bash
py -m streamlit run app.py
```

Note: Streamlit is not integrated with the auth-gated Studio API.

## Prompt Understanding

Two modes:

- **Ollama LLM** — semantic JSON edit plan (when Ollama is running)
- **Rule-based fallback** — `utils/prompt_parser.py` + `utils/timeline_parser_rules.py`

### Enable Local LLM Parsing

1. Install [Ollama](https://ollama.com/download)
2. Start Ollama (API on port `11434`)
3. Pull a model:

```bash
ollama pull qwen2.5:7b
```

Optional env vars:

- `AIEDIT_OLLAMA_URL` (default `http://127.0.0.1:11434`)
- `AIEDIT_OLLAMA_MODEL` (default `qwen2.5:7b`)

### Dev flags

- `AIEDIT_DEV_PREMIUM=1` — unlock Premium routing without subscribing
- `AIEDIT_AUTH_DB` — path to auth SQLite file

## Supported Prompt Examples

```text
Trim from 0:05 to 0:30
Slow motion 0.5x from 3s to 6s
Crop to 9:16 for TikTok
Mute audio
Fade in over 1 second
Replace "GAME OVER" with "BOTH"
Change the character's hair to pink
Remove the fireworks behind the character
Add a rain and storm atmosphere
```

## Reference Images

For object replacement, upload reference images in Studio before applying. Without a reference, quality is limited.

## Future Direction

Dependable prompt-to-edit first; optional heavier generative backends later as Premium tier. Full phased plan: **`docs/CURRENT_STATE_AND_ROADMAP.md`**.
