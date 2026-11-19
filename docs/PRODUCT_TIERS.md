# Product Tiers — Normal vs Premium

## Auth & access

- Users **sign up / log in** at `/login` (SQLite auth DB at `data/aiedit_auth.db`).
- **Active weekly plan required** to upload, parse, or run edits.
- Tier is determined at subscribe time and shown on **Profile** (`/profile`).

| Plan | Price (INR/week) | Edits/day | Features |
|------|------------------|-----------|----------|
| **Normal** | 79 | 5 | All built-in structured edits (see below) |
| **Premium** | 199 | 12 | Normal + **AI code-gen** for unsupported / open-ended prompts |

### Limit upgrades

| Situation | Action |
|-----------|--------|
| Normal user hits daily limit | **Upgrade to Premium** for remainder of week (₹199) |
| Premium user hits daily limit | **+50% boost**: pay 50% of current weekly price now; limit ×1.5; weekly price increases (e.g. ₹199 → pay ₹99 → ₹298/week, 12 → 18 edits/day) |
| Premium boost stacking | Can repeat +50% offer; each time pay 50% of **current** price |
| Week end | Choose **keep boosted** pricing/limit or **revert** to base plan (₹79/5 or ₹199/12) |

Payments are **stubbed locally** (recorded in DB). Razorpay hooks go in `backend/auth_db.py` when ready.

---

## Strategy

| Tier | Audience | Execution |
|------|----------|-----------|
| **Normal (default)** | All subscribers | Parsed prompt → validated operation → `core.engine` runner (deterministic) |
| **Premium** | Paying upgrade | When prompt maps to `unsupported`, user opts in → `codegen_edit` → sandboxed script → MP4 |

**Normal:** maximize structured operations (CV + FFmpeg).  
**Premium:** when no structured operation fits, generate and run a custom script (in progress).

---

## Normal plan — included operations

Everything in `core.edit_plan.SUPPORTED_OPERATIONS` except `codegen_edit`:

### Text & detection

- Text detect / remove / replace (OCR + inpaint)
- Frame extraction

### Visual / semantic (mask-based)

- Object recolor / remove / reference-guided replace
- Character hair recolor
- Global color change (with tolerance)

### Timeline (FFmpeg — Normal plan)

| Operation | What it does |
|-----------|----------------|
| `timeline_trim` | Cut/trim by start/end time |
| `speed_change` | Slow-mo, timelapse, segment speed |
| `crop_resize` | 9:16, 16:9, 1:1, 4:5, center crop |
| `volume_adjust` | Mute, volume, audio fade |
| `fade_in_out` | Video fade in/out |
| `rotate_flip` | Rotate 90/180/270, flip H/V |
| `brightness_contrast` | EQ + presets (cinematic, vivid, …) |
| `timeline_edit` | Chained trim + zoom + speed montages |

Example prompts: *Trim from 0:05 to 0:30*, *Slow motion 0.5x from 3s to 6s*, *Crop to 9:16 for TikTok*, *Mute audio*, *Fade in over 1 second*.

### Atmosphere & commentary

- Weather / mood / lighting overlays (`atmosphere_overlay`)
- Auto play-by-play commentary (`auto_commentary`)

### Planned Normal expansions (not premium)

- Auto captions (Whisper + burn-in)
- Background blur on subject

---

## Premium plan

Triggered when parser returns `unsupported` or `unsupported_generative_edit`.

1. User sees **Premium upsell** in Studio (not a cryptic validator error).
2. Default job is **blocked** with `error_code: premium_required`.
3. With Premium (or dev unlock), user can submit with `use_premium: true` → `codegen_edit`.

Premium is for:

- Open-ended prompts with no structured operation
- Custom compositing / filters not covered by built-in ops
- Complex edits that fail to map to the fixed schema

**Note:** Common timeline edits (trim, speed, crop, zoom montages) are **Normal** — not Premium.

Premium **code-gen runner** is currently a **scaffold** (`core/codegen/`); execution sandbox not shipped yet.

---

## API fields

Parse and job responses include:

| Field | Meaning |
|-------|---------|
| `tier` | `default` \| `premium` |
| `premium_required` | Normal plan cannot run this as-is |
| `executable_default` | Validator OK for a built-in operation |
| `user_message` | Human-readable status |
| `premium_message` | Upsell copy when premium required |
| `error_code` | `premium_required` \| `clarification` on failed jobs |

Job submit: `use_premium: true` (requires Premium entitlement).

All Studio routes require `Authorization: Bearer <token>` except auth register/login.

---

## Local development

Premium checkout is stubbed. To test premium routing:

```powershell
$env:AIEDIT_DEV_PREMIUM = "1"
py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000
```

In Studio, use **Try Premium (dev)** on unsupported prompts.

Auth DB path override:

```powershell
$env:AIEDIT_AUTH_DB = "data/aiedit_auth.db"
```

---

## Hosting (Phase 6)

- **Normal jobs:** GPU workers + `core.engine` runners
- **Premium jobs:** isolated sandbox worker (Docker), timeouts, no network
- **Auth / billing:** payment webhooks set entitlements server-side — never trust client alone

---

## Code map

| Module | Role |
|--------|------|
| `core/tiers.py` | Tier detection, upsell messages, feature lists |
| `core/billing/plans.py` | Pricing, limits, +50% math |
| `core/billing/service.py` | Entitlements, renew, boost |
| `core/edit_plan.py` | Supported operations + validation |
| `core/runners/timeline_edits.py` | FFmpeg timeline runners |
| `utils/ffmpeg_edits.py` | FFmpeg filter implementations |
| `utils/timeline_parser_rules.py` | Rule-based timeline prompt parsing |
| `core/codegen/` | Premium runner (scaffold) |
| `backend/auth_routes.py` | Login, profile, subscribe, boost |
| `backend/auth_db.py` | SQLite persistence |
| `backend/studio.py` | Studio API + auth/quota gates |
| `frontend/src/routes/login/` | Login UI |
| `frontend/src/routes/profile/` | Plan selection & usage |
| `frontend/src/routes/studio/` | Editor |
| `frontend/src/lib/components/PremiumUpsell.svelte` | Upsell UI |
