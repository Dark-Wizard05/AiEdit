"""Atmosphere / weather tuning panel (dedicated tab)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from ui.prompt_queue import queue_command_prompt
from ui.theme import render_card_close, render_card_open


def render_atmosphere_tab(
    *,
    inferred: Optional[Dict[str, Any]],
    instruction_summary: str = "",
    active: bool = False,
) -> None:
    """Render atmosphere controls; writes ``st.session_state.atmosphere_overrides``."""

    render_card_open("Atmosphere & weather")
    st.markdown(
        "Overlay grading, particles, lightning, haze, and optional rain/wind/thunder audio — "
        "**without** regenerating your video geometry."
    )

    if not active or not inferred:
        st.info(
            "Re-run an atmosphere prompt on the **Edit** tab to refresh detected settings, "
            "or load an example below."
        )
        if st.button("Load atmosphere example prompt", key="atm_load_example", use_container_width=True):
            queue_command_prompt(
                "Make it look like a heavy thunderstorm with lightning and rain audio. "
                "Keep gameplay and map exactly the same — atmosphere overlay only."
            )
        render_card_close()
        return

    st.markdown(f"**Detected look:** {instruction_summary or 'Atmosphere overlay'}")

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("↺ Reset to detected", key="atmosphere_reset_btn", use_container_width=True):
            st.session_state.atmosphere_overrides = {}
            st.rerun()
    with c2:
        st.caption("Tweaks merge with parsed params when you process.")

    ov = dict(st.session_state.atmosphere_overrides)

    def _val(key: str, default):
        return ov.get(key, inferred.get(key, default))

    particle_kinds = ("none", "rain", "snow", "hail", "dust", "ash")
    tints = (
        "neutral", "warm", "amber", "orange", "yellow", "red",
        "cool", "blue", "teal", "green", "purple", "magenta",
    )
    hazes = ("none", "mist", "fog", "heavy_fog", "sand")
    flashes = ("none", "lightning")
    beds = ("none", "rain", "wind")
    bright_opts = ("darker", "normal", "brighter")
    sat_opts = ("low", "normal", "high")

    def _idx(opts, value):
        try:
            return opts.index(value)
        except ValueError:
            return 0

    st.markdown("#### Particles & motion")
    col_a, col_b = st.columns(2)
    with col_a:
        pk = _val("particle_kind", "none")
        pk_new = st.selectbox("Particles", particle_kinds, index=_idx(particle_kinds, pk), key="atm_pk")
        pi = float(_val("particle_intensity", 0.0))
        pi_new = st.slider("Particle intensity", 0.0, 1.0, pi, 0.05, key="atm_pi")
        wind = float(_val("particle_wind", 0.0))
        wind_new = st.slider("Wind (lateral)", -1.0, 1.0, wind, 0.05, key="atm_wind")

    with col_b:
        fk = _val("flash_kind", "none")
        fk_new = st.selectbox("Flashes", flashes, index=_idx(flashes, fk), key="atm_fk")
        flash_rate = float(_val("flash_rate_per_min", 18.0))
        flash_rate_new = st.slider(
            "Lightning rate (/min)", 0.0, 40.0, flash_rate, 1.0, key="atm_flash_rate"
        )
        flash_str = float(_val("flash_strength", 1.0))
        flash_str_new = st.slider("Flash strength", 0.0, 1.0, flash_str, 0.05, key="atm_flash_str")

    st.markdown("#### Color & mood")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        tint_choice = ov.get("_tint_choice", "neutral")
        tint_new = st.selectbox("Tint", tints, index=_idx(tints, tint_choice), key="atm_tint")
        ts = float(_val("tint_strength", 0.0))
        ts_new = st.slider("Tint strength", 0.0, 1.0, ts, 0.05, key="atm_ts")
    with col_b2:
        bright_choice = ov.get("_brightness_choice", "normal")
        bright_new = st.radio(
            "Brightness", bright_opts, index=_idx(bright_opts, bright_choice), horizontal=True, key="atm_bright"
        )
        sat_choice = ov.get("_saturation_choice", "normal")
        sat_new = st.radio(
            "Saturation", sat_opts, index=_idx(sat_opts, sat_choice), horizontal=True, key="atm_sat"
        )

    st.markdown("#### Environment & audio")
    col_c, col_d = st.columns(2)
    with col_c:
        haze_choice = ov.get("_haze_choice", "none")
        haze_new = st.selectbox("Haze / fog", hazes, index=_idx(hazes, haze_choice), key="atm_haze")
        heat = float(_val("heat_haze", 0.0))
        heat_new = st.slider("Heat haze", 0.0, 1.0, heat, 0.05, key="atm_heat")
        vig = float(_val("vignette", 0.35))
        vig_new = st.slider("Vignette", 0.0, 0.85, vig, 0.05, key="atm_vig")
    with col_d:
        bed_choice = _val("audio_bed", "none")
        bed_new = st.selectbox(
            "Audio bed under original audio", beds, index=_idx(beds, bed_choice), key="atm_bed"
        )
        mix_thunder_default = bool(
            _val(
                "mix_thunder_audio",
                fk_new == "lightning" and bed_new != "none",
            )
        )
        mix_thunder_new = st.checkbox(
            "Mix thunder rumble with lightning flashes",
            value=mix_thunder_default,
            key="atm_mix_thunder",
            help="Low-frequency bursts aligned to visual lightning when rain/wind bed is on.",
        )

    from utils.prompt_parser import (
        _BRIGHTNESS_EXPOSURE,
        _HAZE_PROFILES,
        _SATURATION_MUL,
        _TINT_BGR,
    )

    new_overrides: Dict[str, Any] = {}
    if pk_new != inferred.get("particle_kind", "none") or pk_new != "none":
        new_overrides["particle_kind"] = pk_new
    if abs(pi_new - float(inferred.get("particle_intensity", 0.0))) > 1e-3:
        new_overrides["particle_intensity"] = pi_new
    if abs(wind_new - float(inferred.get("particle_wind", 0.0))) > 1e-3:
        new_overrides["particle_wind"] = wind_new
    if fk_new != inferred.get("flash_kind", "none"):
        new_overrides["flash_kind"] = fk_new
    if abs(flash_rate_new - float(inferred.get("flash_rate_per_min", 18.0))) > 1e-3:
        new_overrides["flash_rate_per_min"] = flash_rate_new
    if abs(flash_str_new - float(inferred.get("flash_strength", 1.0))) > 1e-3:
        new_overrides["flash_strength"] = flash_str_new

    new_overrides["_tint_choice"] = tint_new
    new_overrides["tint_bgr"] = list(_TINT_BGR.get(tint_new, _TINT_BGR["neutral"]))
    if abs(ts_new - float(inferred.get("tint_strength", 0.0))) > 1e-3:
        new_overrides["tint_strength"] = ts_new

    new_overrides["_brightness_choice"] = bright_new
    new_overrides["exposure_add"] = _BRIGHTNESS_EXPOSURE.get(bright_new, 0.0)
    new_overrides["_saturation_choice"] = sat_new
    new_overrides["saturation_mul"] = _SATURATION_MUL.get(sat_new, 1.0)

    haze_strength, haze_color = _HAZE_PROFILES.get(haze_new, _HAZE_PROFILES["none"])
    new_overrides["_haze_choice"] = haze_new
    new_overrides["haze_strength"] = haze_strength
    new_overrides["haze_color_bgr"] = list(haze_color)
    if abs(heat_new - float(inferred.get("heat_haze", 0.0))) > 1e-3:
        new_overrides["heat_haze"] = heat_new
    if abs(vig_new - float(inferred.get("vignette", 0.35))) > 1e-3:
        new_overrides["vignette"] = vig_new
    new_overrides["audio_bed"] = bed_new
    new_overrides["mix_rain_audio"] = bed_new != "none"
    new_overrides["mix_thunder_audio"] = mix_thunder_new

    st.session_state.atmosphere_overrides = new_overrides
    render_card_close()
