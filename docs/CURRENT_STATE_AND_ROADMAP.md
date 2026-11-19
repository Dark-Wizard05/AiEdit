# Current State And Roadmap

## Project Goal

AiEdit lets a user **sign up**, pick a plan, **upload a video**, describe the edit in natural language, preview the result, and export MP4.

## Strategy: Power Before Hosting

Development prioritizes **local capability** first: masks, temporal consistency, prompt understanding, and export quality on the developer’s machine. **No production hosting spend** (managed GPUs, CDN, payment rails) is assumed until the tool clears the **power checkpoints** below.

Architecture choices **separate parsing from execution** and keep a **strict edit schema** so a future hosted deployment does not require a rewrite.

## Power Checkpoints (Go / No-Go Before Investing In Hosting)

Use a small **golden set** of clips and prompts; revisit after each major phase.

| Checkpoint | What “good” looks like |
|------------|------------------------|
| **Objects** | Stable masks on moving or partially occluded targets; fewer failures when Segment Anything is configured versus GrabCut-only paths |
| **Time** | Noticeably less flicker or mask drift across frames on a difficult 5–15 second clip |
| **Text** | Reliable replace/remove on typical UI or overlay text; sensible behavior when OCR is uncertain |
| **Timeline** | Trim, speed, crop, and montage edits export correctly with audio in sync |
| **Prompts** | Natural language maps to a validated edit plan; clarification when ambiguous; no silent wrong edits |
| **Trust** | Preview aligns with export; failures indicate stage (parser vs mask vs OCR vs export) |

---

## Current Implementation (June 2026)

### Primary UI

| Layer | Location | Notes |
|-------|----------|--------|
| **Frontend** | `frontend/` (SvelteKit 5 + Tailwind) | `/login`, `/profile`, `/studio` |
| **Studio API** | `backend/studio.py` | Upload, parse, jobs, system status — **auth + quota gated** |
| **Auth / billing** | `backend/auth_routes.py`, `backend/auth_db.py`, `core/billing/` | SQLite; payments **stubbed** locally |
| **Legacy UI** | `app.py` (Streamlit) | Still works; not the primary interface |

**Local run:** `.\scripts\dev.ps1` or API on `:8000` + `cd frontend && npm run dev` on `:5173`.

See also: `docs/PRODUCT_TIERS.md`, `frontend/README.md`, root `README.md`.

### Auth & plans (local stub)

- Sign up / log in at `/login`
- **Active weekly plan required** to upload, parse, or run edits
- **Normal** — ₹79/week, 5 edits/day, built-in operations only
- **Premium** — ₹199/week, 12 edits/day, built-in + **AI code-gen** (scaffold) for unsupported prompts
- Limit upgrades, +50% Premium boost — see `docs/PRODUCT_TIERS.md`
- DB: `data/aiedit_auth.db` (override with `AIEDIT_AUTH_DB`)

### Supported operations (via `core.engine`)

All paths go through `core.engine.execute(instruction, context)` — invalid plans never touch pixels.

**Text & frames** (`pipeline.VideoPipeline`):

- `text_replacement`, `text_removal`, `text_detection`, `frame_extraction`

**Visual / mask-based** (`core/runners/visual_edits.py`):

- `object_recolor`, `object_remove`, `object_replace_guided`
- `character_hair_recolor`, `global_color_change`

**Timeline / FFmpeg** (`core/runners/timeline_edits.py`, `utils/ffmpeg_edits.py`):

- `timeline_trim` — cut/trim by start/end time
- `speed_change` — whole clip or segment slow-mo / timelapse
- `crop_resize` — 9:16, 16:9, 1:1, 4:5, etc.
- `volume_adjust` — mute, volume factor, audio fade
- `fade_in_out` — video fade in/out
- `rotate_flip` — 90°/180°/270°, horizontal/vertical flip
- `brightness_contrast` — eq + presets (cinematic, vivid, muted, bright)
- `timeline_edit` — chained trim / zoom / speed montages

**Atmosphere & commentary**:

- `atmosphere_overlay` — weather/mood grading + particles (no geometry regen)
- `auto_commentary` — play-by-play TTS pipeline

**Premium only** (scaffold):

- `codegen_edit` — sandboxed AI script generation (`core/codegen/`)

Parser: `utils/prompt_parser.py` (Ollama LLM + rule fallback); timeline rules in `utils/timeline_parser_rules.py`.

### Other functional areas

- Free-form colors via `resolve_color()` (palette, hex, rgb)
- Prompt-driven text styling (color, font, alignment)
- Color tolerance for global/object recolor
- Hardware presets: `fast` / `balanced` / `quality` (`core/presets.py`)

### Backend modules (key files)

| Module | Role |
|--------|------|
| `core/edit_plan.py` | Validator for all supported operations |
| `core/engine.py` | Runner registry + execute funnel |
| `core/tiers.py` | Default vs premium routing, upsell copy |
| `core/billing/` | Plans, entitlements, boost math |
| `backend/studio.py` | Studio REST API (`/api/*`) |
| `backend/auth_routes.py` | Auth, profile, subscribe, boost |
| `backend/api.py` | FastAPI app, CORS, legacy `/jobs` + intent endpoints |
| `utils/prompt_parser.py` | LLM + rule parser |
| `utils/ffmpeg_edits.py` | FFmpeg timeline implementations |
| `core/prompt_memory.py` | JSONL parse log at `logs/prompt_history.jsonl` |
| `core/clarification.py` | Clarification helpers for UI |
| `logging_config.py` | Rotating logs + `logs/events.jsonl` |

### Supporting docs

- `README.md` — install, run, Ollama, prompt examples
- `docs/PRODUCT_TIERS.md` — Normal vs Premium, billing rules
- `docs/LLM_PROMPT_PARSER_PLAN.md` — parser architecture (parser-only scope)

---

## Current Known Issues

### Prompt understanding

- Ollama optional; cold model loads can hit the 45s read timeout — rule fallback still works
- LLM schema does not yet list all timeline operations; **rule-based parser** handles most trim/speed/crop prompts
- Clarification helpers exist; interactive follow-up in Studio UI is still light

### Editing quality

- OCR depends on frame quality and contrast
- GrabCut masks weaker than SAM
- Object replacement is compositing, not full generative swap
- Timeline segment speed/zoom on long clips can be slow (FFmpeg filter chains)
- Premium **code-gen execution** is not implemented — upsell routes correctly but runner returns stub error

### Product readiness

- **Local-first** — SvelteKit + FastAPI, not deployed
- Payments simulated in SQLite (Razorpay not wired)
- Auth sessions in SQLite — not production hardened
- Streamlit (`app.py`) not fully aligned with auth-gated Studio API

---

## Why Prompt Understanding Still Matters

Rule-based parsing bootstraps predictable edits but does not scale to ambiguous phrasing. Semantic parsing (Ollama today; optional cloud later) outputs a **strict JSON edit plan** validated before execution. The LLM interprets intent; it does not directly edit media.

---

## Roadmap (Phased Master Plan)

**Phase 6 hosting** remains after local quality targets are met. **Auth/billing stub** is implemented locally ahead of hosting.

### Phase 0: Baseline And Reproducibility

- Golden test set: clips, prompts, expected outcomes
- Document hardware profile for comparisons
- Reproducible setup: `requirements.txt`, Ollama env vars
- Parser golden tests in `test_modules.py`; timeline tests in `tests/test_timeline_edits.py`

**Status:** 8/8 parser golden cases passing; timeline parser tests passing; clip-level golden set still pending.

### Phase 1: Unified Execution Core

- Single validate-then-execute funnel for all editors

**Status: largely done.**

- `core.engine.execute` + runner registry
- Text, visual, atmosphere, commentary, and **timeline** runners registered
- `backend/studio.py` jobs route through `core.engine`
- Streamlit `app.py` still has parallel paths for some flows — incremental migration only if needed

### Phase 2: Prompt Understanding, Validation, And Local Memory

**Status: core done; UI wiring partial.**

- `validate_edit_instruction` on every parse
- `core.prompt_memory` JSONL logging
- `core.clarification` helpers — Studio shows messages but limited interactive clarify flow
- Timeline ops need LLM schema expansion in `ParsedEditPlan` (rules work today)

### Phase 3: Editing Quality (Masks, Time, OCR)

**Status: helpers ready; production wiring selective.**

- `core.temporal`, `core.ocr_consensus` implemented and unit-tested
- Mask tracker / OCR default paths not yet calling all helpers — A/B on real clips pending

### Phase 4: Optional Heavy Quality Tier (Local)

**Status: presets shipped; diffusion gating pending real-GPU validation.**

- `core.presets` + `/api/system/status` recommended preset
- Diffusion inpainting exists; quality-preset gating held until GPU clip testing

### Phase 5: Local Job API And Operations

**Status: done for Studio MVP.**

- `POST /api/videos/upload`, `POST /api/parse`, `POST /api/jobs`, polling, MP4 export
- Auth + daily quota on studio routes
- Structured logging via `log_event`
- In-memory job store (process-local)

### Phase 5b: Auth, Plans, And Billing (local stub) — **NEW**

**Status: MVP done.**

- Login, profile, Normal/Premium subscribe, upgrade, +50% boost, renew/revert
- Simulated payments in SQLite
- **Pending:** Razorpay/Stripe, email verification, production session security

### Phase 6: Hosted Product And Advanced Generative Backends

**After power checkpoints + payment integration.**

- Deploy API + workers + object storage
- Real payment webhooks; server-side entitlement only
- Premium code-gen in isolated Docker sandbox
- Optional cloud LLM / generative video backends
- Deterministic grounded editing remains the default

---

## Design Principles

- Let the LLM understand the prompt, not directly edit the media
- Keep execution deterministic and schema-driven
- Prefer graceful clarification over guessing
- **Normal plan** = maximum structured FFmpeg + CV coverage; **Premium** = code-gen fallback
- Offer **modes/presets** (fast / balanced / quality) rather than one fragile max-everything path
- Same `core.engine` core should run unchanged when hosted later
