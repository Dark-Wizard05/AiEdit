"""React Bits–inspired dark glass theme for Streamlit (CSS-only)."""

from __future__ import annotations

import streamlit as st


def inject_aiedit_theme() -> None:
    """Inject global CSS: dark mesh background, glass cards, gradient accents."""

    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --ae-bg-0: #050508;
  --ae-bg-1: #0c0c14;
  --ae-bg-2: #12121c;
  --ae-surface: rgba(18, 18, 28, 0.72);
  --ae-surface-hover: rgba(26, 26, 40, 0.85);
  --ae-border: rgba(255, 255, 255, 0.08);
  --ae-border-glow: rgba(168, 85, 247, 0.35);
  --ae-text: #f4f4f5;
  --ae-muted: #a1a1aa;
  --ae-accent-a: #a855f7;
  --ae-accent-b: #22d3ee;
  --ae-accent-c: #f472b6;
  --ae-success: #34d399;
  --ae-radius: 16px;
  --ae-radius-sm: 10px;
}

html, body, [class*="css"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

.stApp {
  background:
    radial-gradient(ellipse 80% 50% at 20% -10%, rgba(168, 85, 247, 0.18), transparent 55%),
    radial-gradient(ellipse 60% 40% at 90% 10%, rgba(34, 211, 238, 0.12), transparent 50%),
    radial-gradient(ellipse 50% 30% at 50% 100%, rgba(244, 114, 182, 0.08), transparent 45%),
    linear-gradient(180deg, var(--ae-bg-0) 0%, var(--ae-bg-1) 40%, var(--ae-bg-2) 100%) !important;
  color: var(--ae-text);
}

.stApp::before {
  content: "";
  position: fixed;
  inset: 0;
  background-image: radial-gradient(rgba(255,255,255,0.04) 1px, transparent 1px);
  background-size: 28px 28px;
  pointer-events: none;
  z-index: 0;
  opacity: 0.35;
}

.block-container {
  padding-top: 1.5rem !important;
  padding-bottom: 3rem !important;
  max-width: 1180px !important;
}

/* Hide default Streamlit header clutter */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] {
  background: transparent !important;
  border-bottom: none !important;
}

/* Sidebar glass panel */
section[data-testid="stSidebar"] {
  background: rgba(8, 8, 14, 0.88) !important;
  border-right: 1px solid var(--ae-border) !important;
  backdrop-filter: blur(18px);
}
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {
  color: var(--ae-text) !important;
}

/* Hero */
.aiedit-hero {
  position: relative;
  padding: 2rem 2.25rem 1.75rem;
  margin-bottom: 1.25rem;
  border-radius: calc(var(--ae-radius) + 4px);
  border: 1px solid var(--ae-border);
  background: linear-gradient(135deg, rgba(168,85,247,0.12) 0%, rgba(34,211,238,0.06) 50%, rgba(244,114,182,0.08) 100%);
  backdrop-filter: blur(12px);
  overflow: hidden;
}
.aiedit-hero::after {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(135deg, rgba(168,85,247,0.5), rgba(34,211,238,0.25), rgba(244,114,182,0.35));
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  opacity: 0.55;
}
.aiedit-hero h1 {
  margin: 0 0 0.35rem 0;
  font-size: 2.15rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  background: linear-gradient(120deg, #fff 0%, #c4b5fd 35%, #67e8f9 70%, #f9a8d4 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: aiedit-shimmer 8s ease-in-out infinite;
  background-size: 200% auto;
}
.aiedit-hero p {
  margin: 0;
  color: var(--ae-muted);
  font-size: 1.02rem;
  max-width: 52ch;
}
.aiedit-pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1rem;
}
.aiedit-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  border: 1px solid var(--ae-border);
  background: rgba(255,255,255,0.04);
  color: #d4d4d8;
}

@keyframes aiedit-shimmer {
  0%, 100% { background-position: 0% center; }
  50% { background-position: 100% center; }
}

/* Glass cards */
.aiedit-card {
  padding: 1.25rem 1.35rem;
  border-radius: var(--ae-radius);
  border: 1px solid var(--ae-border);
  background: var(--ae-surface);
  backdrop-filter: blur(14px);
  margin-bottom: 1rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.aiedit-card:hover {
  border-color: rgba(168, 85, 247, 0.22);
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
}
.aiedit-card-title {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ae-muted);
  margin-bottom: 0.65rem;
}
.aiedit-card h2, .aiedit-card h3 {
  color: var(--ae-text) !important;
  margin-top: 0 !important;
}

/* Tabs — React Bits–style segmented control */
.stTabs [data-baseweb="tab-list"] {
  gap: 0.35rem !important;
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid var(--ae-border) !important;
  border-radius: 14px !important;
  padding: 0.35rem !important;
  margin-bottom: 1.25rem !important;
}
.stTabs [data-baseweb="tab"] {
  height: 2.65rem !important;
  border-radius: 10px !important;
  background: transparent !important;
  color: var(--ae-muted) !important;
  font-weight: 600 !important;
  padding: 0 1.1rem !important;
  border: 1px solid transparent !important;
  transition: all 0.2s ease !important;
}
.stTabs [aria-selected="true"] {
  background: linear-gradient(135deg, rgba(168,85,247,0.35), rgba(34,211,238,0.2)) !important;
  color: #fff !important;
  border-color: rgba(168,85,247,0.35) !important;
  box-shadow: 0 0 20px rgba(168,85,247,0.15) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
  font-size: 0.92rem !important;
}

/* Inputs */
.stTextArea textarea, .stTextInput input {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid var(--ae-border) !important;
  border-radius: var(--ae-radius-sm) !important;
  color: var(--ae-text) !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: rgba(168,85,247,0.45) !important;
  box-shadow: 0 0 0 1px rgba(168,85,247,0.25) !important;
}

[data-testid="stFileUploader"] section {
  border: 1px dashed rgba(168,85,247,0.35) !important;
  border-radius: var(--ae-radius-sm) !important;
  background: rgba(255,255,255,0.03) !important;
}
[data-testid="stFileUploader"] section:hover {
  border-color: rgba(34,211,238,0.45) !important;
  background: rgba(34,211,238,0.04) !important;
}

[data-baseweb="slider"] div[role="slider"] {
  background: linear-gradient(90deg, var(--ae-accent-a), var(--ae-accent-b)) !important;
}

section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
  color: var(--ae-muted);
}

.stExpander {
  border: 1px solid var(--ae-border) !important;
  border-radius: var(--ae-radius-sm) !important;
  background: rgba(255,255,255,0.02) !important;
}

/* Primary buttons */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
  background: linear-gradient(135deg, #9333ea 0%, #7c3aed 45%, #0891b2 100%) !important;
  border: none !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
  letter-spacing: 0.02em !important;
  box-shadow: 0 4px 24px rgba(147, 51, 234, 0.35) !important;
  transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}
.stButton > button[kind="primary"]:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 8px 32px rgba(147, 51, 234, 0.45) !important;
}

.stButton > button {
  border-radius: 10px !important;
  border: 1px solid var(--ae-border) !important;
  background: rgba(255,255,255,0.05) !important;
  color: var(--ae-text) !important;
  font-weight: 600 !important;
  transition: all 0.15s ease !important;
}
.stButton > button:hover {
  border-color: rgba(34,211,238,0.35) !important;
  background: rgba(34,211,238,0.08) !important;
}

/* Metrics / info boxes */
.stAlert {
  border-radius: var(--ae-radius-sm) !important;
  border: 1px solid var(--ae-border) !important;
  backdrop-filter: blur(8px);
}

/* Preview strip */
.aiedit-preview-strip img {
  max-width: 380px !important;
  width: 100% !important;
  height: auto !important;
  cursor: default !important;
  user-select: none !important;
  -webkit-user-drag: none !important;
  pointer-events: none !important;
  border-radius: 12px !important;
  border: 1px solid var(--ae-border) !important;
  box-shadow: 0 12px 40px rgba(0,0,0,0.35) !important;
}
.aiedit-preview-strip figcaption {
  color: var(--ae-muted) !important;
}

/* Status badge */
.aiedit-status-ok {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 600;
  background: rgba(52, 211, 153, 0.12);
  border: 1px solid rgba(52, 211, 153, 0.35);
  color: #6ee7b7;
}
.aiedit-status-warn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 600;
  background: rgba(251, 191, 36, 0.1);
  border: 1px solid rgba(251, 191, 36, 0.3);
  color: #fcd34d;
}

/* Footer */
.aiedit-footer {
  text-align: center;
  padding: 2rem 1rem;
  color: var(--ae-muted);
  font-size: 0.88rem;
}
.aiedit-footer strong {
  background: linear-gradient(90deg, var(--ae-accent-a), var(--ae-accent-b));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.success-msg { color: var(--ae-success); font-weight: 600; }
.error-msg { color: #f87171; font-weight: 600; }
</style>
""",
        unsafe_allow_html=True,
    )


def render_hero(
    subtitle: str | None = None,
    *,
    show_atmosphere_tab: bool = False,
    show_commentary_tab: bool = False,
) -> None:
    sub = subtitle or (
        "Describe your edit in plain language — text, objects, colors, weather, or "
        "auto-commentary. Specialised tabs unlock after their first export."
    )
    atm_pill = (
        '<span class="aiedit-pill">🌦️ Atmosphere tab</span>'
        if show_atmosphere_tab
        else ""
    )
    commentary_pill = (
        '<span class="aiedit-pill">🎙️ Commentary tab</span>'
        if show_commentary_tab
        else ""
    )
    st.markdown(
        f"""
<div class="aiedit-hero">
  <h1>AiEdit</h1>
  <p>{sub}</p>
  <div class="aiedit-pill-row">
    <span class="aiedit-pill">✨ Prompt-first</span>
    {atm_pill}
    {commentary_pill}
    <span class="aiedit-pill">🎬 Local edits</span>
    <span class="aiedit-pill">⚡ FFmpeg audio beds</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_card_open(title: str) -> None:
    st.markdown(
        f'<div class="aiedit-card"><div class="aiedit-card-title">{title}</div>',
        unsafe_allow_html=True,
    )


def render_card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)
