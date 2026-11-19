"""Auto-commentary tuning panel (hidden until first commentary export)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from ui.prompt_queue import queue_command_prompt
from ui.theme import render_card_close, render_card_open

_TONE_CHOICES = ("hype", "dry", "roast")
_VOICE_CHOICES = (
    "en-US-GuyNeural",
    "en-US-AndrewNeural",
    "en-US-AriaNeural",
    "en-US-JennyNeural",
    "en-GB-RyanNeural",
    "en-AU-WilliamNeural",
)
_RATE_CHOICES = ("-20%", "-10%", "+0%", "+10%", "+20%")


def render_commentary_tab(
    *,
    inferred: Optional[Dict[str, Any]],
    instruction_summary: str = "",
    active: bool = False,
    last_artifacts: Optional[Dict[str, Any]] = None,
) -> None:
    """Render commentary tuning controls; persists to ``commentary_overrides``."""

    render_card_open("Auto-commentary")
    st.markdown(
        "Generate humorous sports-style play-by-play with hype delivery. "
        "Commentary focuses on what's happening — not background score bugs. "
        "Use **Guy Neural** for the most energetic commentator feel."
    )

    if not active or not inferred:
        st.info(
            "Re-run a commentary prompt on the **Edit** tab "
            "(e.g. *“add hype sports commentary for this clip”*) to refresh detected settings."
        )
        if st.button("Load commentary example prompt", key="commentary_load_example", use_container_width=True):
            queue_command_prompt(
                "Add hype sports-style play-by-play commentary over this clip. "
                "Mute the original audio and keep the voice clear."
            )
        render_card_close()
        return

    if instruction_summary:
        st.markdown(f"**Detected:** {instruction_summary}")

    overrides = dict(st.session_state.get("commentary_overrides") or {})

    def _val(key: str, default: Any) -> Any:
        return overrides.get(key, inferred.get(key, default))

    def _idx(opts, value):
        try:
            return opts.index(value)
        except ValueError:
            return 0

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("↺ Reset to detected", key="commentary_reset_btn", use_container_width=True):
            st.session_state.commentary_overrides = {}
            st.rerun()
    with c2:
        st.caption("Tweaks merge with parsed params on next run.")

    st.markdown("#### Voice & delivery")
    col_a, col_b = st.columns(2)
    with col_a:
        voice = st.selectbox(
            "Voice", _VOICE_CHOICES, index=_idx(_VOICE_CHOICES, _val("voice", "en-US-GuyNeural"))
        )
        tone = st.selectbox(
            "Tone", _TONE_CHOICES, index=_idx(_TONE_CHOICES, _val("tone", "hype"))
        )
    with col_b:
        rate = st.selectbox(
            "Speech rate", _RATE_CHOICES, index=_idx(_RATE_CHOICES, _val("rate", "+0%"))
        )
        player_name = st.text_input(
            "Player name (optional)", value=str(_val("player_name", "") or "")
        )

    st.markdown("#### Audio mix")
    col_c, col_d = st.columns(2)
    with col_c:
        keep_audio = st.checkbox(
            "Keep original game audio (ducked)",
            value=bool(_val("keep_source_audio", True)),
        )
    with col_d:
        duck = st.slider(
            "Original audio level under VO",
            0.0, 1.0,
            float(_val("source_audio_volume", 0.25)),
            0.05,
            disabled=not keep_audio,
        )

    voice_vol = st.slider(
        "Voice volume",
        0.5, 1.5,
        float(_val("voice_volume", 1.0)),
        0.05,
    )

    new_overrides: Dict[str, Any] = {
        "voice": voice,
        "tone": tone,
        "rate": rate,
        "keep_source_audio": keep_audio,
        "source_audio_volume": duck,
        "voice_volume": voice_vol,
    }
    pname = (player_name or "").strip()
    if pname:
        new_overrides["player_name"] = pname

    st.session_state.commentary_overrides = new_overrides

    if last_artifacts:
        events = last_artifacts.get("timeline") or last_artifacts.get("events") or []
        lines = last_artifacts.get("lines") or []
        with st.expander(f"Detected events ({len(events)})", expanded=False):
            if events:
                st.dataframe(
                    [
                        {
                            "t": ev.get("t"),
                            "kind": ev.get("kind"),
                            "label": ev.get("text"),
                            "killer": ev.get("killer") or "",
                            "victim": ev.get("victim") or "",
                            "weapon": ev.get("weapon") or "",
                        }
                        for ev in events
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No on-screen details detected — scene beats will still drive commentary.")
        with st.expander(f"Generated commentary script ({len(lines)} lines)", expanded=True):
            for ln in lines:
                start = ln.get("start") or 0.0
                st.markdown(f"`{start:>5.1f}s` · {ln.get('text')}")

    render_card_close()
