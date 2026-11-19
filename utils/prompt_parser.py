from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional

import requests
from pydantic import BaseModel, Field, ValidationError

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


KNOWN_COLORS = {
    "red": (0, 0, 255),
    "orange": (0, 165, 255),
    "yellow": (0, 255, 255),
    "gold": (0, 215, 255),
    "golden": (0, 215, 255),
    "green": (0, 255, 0),
    "cyan": (255, 255, 0),
    "blue": (255, 0, 0),
    "purple": (255, 0, 255),
    "magenta": (255, 0, 255),
    "pink": (203, 192, 255),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "brown": (42, 42, 165),
    "blonde": (102, 204, 255),
    "blond": (102, 204, 255),
    "silver": (192, 192, 192),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    # Extended CSS-ish palette — keeps the parser useful when prompts don't
    # use one of the original 19 names. resolve_color() also accepts hex /
    # rgb() so totally arbitrary colors still work.
    "teal": (128, 128, 0),
    "turquoise": (208, 224, 64),
    "navy": (128, 0, 0),
    "indigo": (130, 0, 75),
    "violet": (238, 130, 238),
    "lavender": (250, 230, 230),
    "lime": (0, 255, 0),
    "olive": (0, 128, 128),
    "maroon": (0, 0, 128),
    "crimson": (60, 20, 220),
    "scarlet": (35, 17, 255),
    "salmon": (114, 128, 250),
    "coral": (80, 127, 255),
    "peach": (180, 229, 255),
    "beige": (220, 245, 245),
    "tan": (140, 180, 210),
    "ivory": (240, 255, 255),
    "burgundy": (32, 0, 128),
    "charcoal": (54, 54, 54),
    "rose": (164, 173, 255),
    "mint": (152, 255, 152),
    "aqua": (255, 255, 0),
    "amber": (10, 180, 255),
}


def resolve_color(value: Any) -> Optional[tuple]:
    """Return a (B, G, R) tuple for any reasonable color spec.

    Accepts:
      - None / empty -> None
      - existing palette name (case-insensitive)
      - hex strings: "#rgb", "#rrggbb", "rrggbb", "0xRRGGBB"
      - rgb()/rgba(): "rgb(255, 120, 30)"
      - already-resolved 3-tuple/list of ints

    Used everywhere a color value crosses prompt -> render boundary so the
    user is not constrained to the closed palette. KNOWN_COLORS is preserved
    as a back-compat synonym table.
    """

    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) == 3:
        try:
            b, g, r = (int(value[0]), int(value[1]), int(value[2]))
            return (max(0, min(255, b)), max(0, min(255, g)), max(0, min(255, r)))
        except (TypeError, ValueError):
            return None

    text = str(value).strip().lower()
    if not text:
        return None

    if text in KNOWN_COLORS:
        return tuple(int(c) for c in KNOWN_COLORS[text])

    rgb_match = re.match(
        r"^rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)$",
        text,
    )
    if rgb_match:
        r, g, b = (int(rgb_match.group(i)) for i in (1, 2, 3))
        return (max(0, min(255, b)), max(0, min(255, g)), max(0, min(255, r)))

    hex_text = text
    if hex_text.startswith("0x"):
        hex_text = hex_text[2:]
    if hex_text.startswith("#"):
        hex_text = hex_text[1:]
    if re.fullmatch(r"[0-9a-f]{3}", hex_text):
        hex_text = "".join(ch * 2 for ch in hex_text)
    if re.fullmatch(r"[0-9a-f]{6}", hex_text):
        r = int(hex_text[0:2], 16)
        g = int(hex_text[2:4], 16)
        b = int(hex_text[4:6], 16)
        return (b, g, r)

    return None


COLOR_HEX_PATTERN = re.compile(r"#?[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
COLOR_RGB_PATTERN = re.compile(
    r"rgba?\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)",
    re.IGNORECASE,
)


def extract_color_from_text(text: str) -> Optional[str]:
    """Find a color spec inside free text.

    Returns the original token (palette name, "#rrggbb", or "rgb(...)").
    Leaves resolution to ``resolve_color``.
    """

    if not text:
        return None
    rgb_match = COLOR_RGB_PATTERN.search(text)
    if rgb_match:
        return rgb_match.group(0)
    hex_match = COLOR_HEX_PATTERN.search(text)
    if hex_match:
        token = hex_match.group(0)
        if not token.startswith("#"):
            token = "#" + token
        if resolve_color(token) is not None:
            return token
    text_lower = text.lower()
    for color_name in sorted(KNOWN_COLORS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(color_name)}s?\b", text_lower):
            return color_name
    return None

TEXT_FILLER_WORDS = {
    "the",
    "a",
    "an",
    "text",
    "word",
    "words",
    "caption",
    "subtitle",
    "title",
    "logo",
    "sign",
    "saying",
    "that",
}

SUPPORTED_OPERATIONS = {
    "text_replacement",
    "text_removal",
    "text_detection",
    "frame_extraction",
    "character_hair_recolor",
    "object_recolor",
    "object_remove",
    "object_replace_guided",
    "global_color_change",
    "atmosphere_overlay",
    "auto_commentary",
    "timeline_trim",
    "speed_change",
    "crop_resize",
    "volume_adjust",
    "fade_in_out",
    "rotate_flip",
    "brightness_contrast",
    "timeline_edit",
    "unsupported",
    "unsupported_generative_edit",
}


@dataclass
class EditInstruction:
    operation: str
    summary: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    supported: bool = True
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ParsedEntity(BaseModel):
    type: Literal["text", "object", "color", "none"] = "none"
    value: Optional[str] = None


class ParsedEditPlan(BaseModel):
    operation: Literal[
        "text_replacement",
        "text_removal",
        "text_detection",
        "frame_extraction",
        "character_hair_recolor",
        "object_recolor",
        "object_remove",
        "object_replace_guided",
        "global_color_change",
        "atmosphere_overlay",
        "auto_commentary",
        "unsupported",
    ]
    target: ParsedEntity = Field(default_factory=ParsedEntity)
    replacement: ParsedEntity = Field(default_factory=ParsedEntity)
    target_color: Optional[str] = None
    source_color: Optional[str] = None
    scope: Literal["whole_clip", "segment", "single_frame", "unknown"] = "whole_clip"
    needs_reference: bool = False
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    confidence: float = 0.0
    notes: List[str] = Field(default_factory=list)
    atmosphere_rain: Optional[bool] = None
    atmosphere_lightning: Optional[bool] = None
    atmosphere_preset: Optional[str] = None
    # Generic atmosphere knobs (preferred for any freeform weather request).
    atmosphere_particles: Optional[
        Literal["none", "rain", "snow", "hail", "dust", "ash"]
    ] = None
    atmosphere_particle_intensity: Optional[float] = None
    atmosphere_wind: Optional[float] = None
    atmosphere_haze: Optional[
        Literal["none", "mist", "fog", "heavy_fog", "sand"]
    ] = None
    atmosphere_flashes: Optional[Literal["none", "lightning"]] = None
    atmosphere_tint: Optional[
        Literal[
            "warm",
            "cool",
            "neutral",
            "blue",
            "orange",
            "teal",
            "green",
            "purple",
            "amber",
            "magenta",
            "red",
            "yellow",
        ]
    ] = None
    atmosphere_tint_strength: Optional[float] = None
    atmosphere_brightness: Optional[Literal["darker", "normal", "brighter"]] = None
    atmosphere_saturation: Optional[Literal["low", "normal", "high"]] = None
    atmosphere_heat_haze: Optional[float] = None
    atmosphere_vignette: Optional[float] = None
    atmosphere_audio_bed: Optional[Literal["rain", "wind", "none"]] = None
    atmosphere_summary: Optional[str] = None
    atmosphere_tint_color: Optional[str] = None  # hex / rgb() / arbitrary name override

    # Optional text-replacement style overrides driven by the prompt itself.
    # When set, they override estimate_text_style() / preserve_original_style.
    text_color: Optional[str] = None       # palette name / hex / rgb()
    text_stroke_color: Optional[str] = None
    text_font_family: Optional[str] = None
    text_font_size: Optional[int] = None
    text_font_weight: Optional[Literal["normal", "bold"]] = None
    text_alignment: Optional[Literal["left", "center", "right"]] = None
    text_preserve_style: Optional[bool] = None  # explicit prompt override of UI checkbox

    # Color-change tolerance / strictness for hue-distance based ops.
    color_tolerance: Optional[
        Literal["narrow", "normal", "wide", "very_wide"]
    ] = None

    # Auto-commentary knobs (only meaningful when operation == "auto_commentary").
    commentary_tone: Optional[Literal["hype", "dry", "roast"]] = None
    commentary_player_name: Optional[str] = None
    commentary_keep_source_audio: Optional[bool] = None
    commentary_voice: Optional[str] = None
    commentary_rate: Optional[str] = None


def _extract_color(command_lower: str) -> Optional[str]:
    return extract_color_from_text(command_lower)


def normalize_text_for_matching(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    tokens = [token for token in value.split() if token not in TEXT_FILLER_WORDS]
    return " ".join(tokens)


def _clean_target_phrase(value: str) -> str:
    value = re.sub(
        r"\b(?:the|a|an|this|that|all|whole|entire)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:in the whole clip|in this clip|throughout the clip|across the clip)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,'\"")


def _normalize_text_target(value: str) -> str:
    value = _clean_target_phrase(value)
    value = re.sub(
        r"\b(?:text|words|word|caption|subtitle|logo|sign)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,'\"")


def _mentions_reference(command_lower: str) -> bool:
    return any(
        marker in command_lower
        for marker in [
            "reference image",
            "reference photo",
            "using this image",
            "using this reference",
            "use this image",
            "use this reference",
        ]
    )


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def _build_llm_prompt(command: str) -> str:
    return f"""
You are a prompt interpreter for an AI video editor.

Convert the user's request into a JSON object with this exact schema:
{{
  "operation": "text_replacement | text_removal | text_detection | frame_extraction | character_hair_recolor | object_recolor | object_remove | object_replace_guided | global_color_change | atmosphere_overlay | auto_commentary | unsupported",
  "target": {{"type": "text | object | color | none", "value": "string or null"}},
  "replacement": {{"type": "text | object | color | none", "value": "string or null"}},
  "target_color": "string or null",
  "source_color": "string or null",
  "scope": "whole_clip | segment | single_frame | unknown",
  "needs_reference": true,
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.95,
  "notes": ["short note"],

  "atmosphere_particles": "none | rain | snow | hail | dust | ash",
  "atmosphere_particle_intensity": 0.6,
  "atmosphere_wind": 0.0,
  "atmosphere_haze": "none | mist | fog | heavy_fog | sand",
  "atmosphere_flashes": "none | lightning",
  "atmosphere_tint": "warm | cool | neutral | blue | orange | teal | green | purple | amber | magenta | red | yellow",
  "atmosphere_tint_strength": 0.3,
  "atmosphere_brightness": "darker | normal | brighter",
  "atmosphere_saturation": "low | normal | high",
  "atmosphere_heat_haze": 0.0,
  "atmosphere_vignette": 0.35,
  "atmosphere_audio_bed": "rain | wind | none",
  "atmosphere_tint_color": "optional hex like #1a3b2e or rgb(...) for non-standard tints",
  "atmosphere_summary": "one short sentence describing the look",

  "text_color": "optional, palette name or #rrggbb / rgb(...) for text replacement",
  "text_stroke_color": "optional",
  "text_font_family": "optional font family hint, e.g. 'Arial', 'serif'",
  "text_font_size": null,
  "text_font_weight": "normal | bold",
  "text_alignment": "left | center | right",
  "text_preserve_style": null,

  "color_tolerance": "narrow | normal | wide | very_wide",

  "commentary_tone": "hype | dry | roast",
  "commentary_player_name": "optional player name to address",
  "commentary_keep_source_audio": true,
  "commentary_voice": "edge-tts voice id (default en-US-AndrewNeural)",
  "commentary_rate": "edge-tts rate string like +0% / -10% / +20%"
}}

Rules:
- Return JSON only.
- If the user wants text changed, use operation "text_replacement".
- Strip filler words from target text. For example, "the GAME OVER text" should become target.value = "GAME OVER".
- If the request is ambiguous, set needs_clarification = true.
- If the request is beyond current capabilities, return operation "unsupported".
- Hair color changes must use operation "character_hair_recolor".
- Object replacement should use operation "object_replace_guided".
- Use operation "atmosphere_overlay" for ANY weather, lighting, mood, time-of-day or "make it feel/look like X" request that does NOT require regenerating the geometry, characters, or layout. This includes: rain, snow, hail, fog, mist, overcast, cloudy, sunny, harsh sun, golden hour, sunset, sunrise, night, dusk, dawn, dust storms, sandstorms, cyclones / hurricanes / typhoons, blizzards, ash / volcanic, smoky, cinematic, battlefield mood, etc.
- Multiple weathers can stack. "Sunny but snowing" -> particles="snow", tint="warm", brightness="brighter".
- If the user explicitly asks to regenerate the entire scene, swap costumes, or paint new geometry / new sky, return "unsupported" — do NOT use atmosphere_overlay.
- For atmosphere_overlay, fill the atmosphere_* knobs sensibly. For non-atmosphere operations leave the atmosphere_* knobs at their defaults / null.
- If the user mentions a SPECIFIC color for an overlay or text (e.g. "moss green tint", "#1a3b2e", "rgb(220, 30, 30) text"), put that color literal in atmosphere_tint_color or text_color rather than rounding to a palette name.
- For text_replacement, fill text_color / text_font_size / text_font_weight / text_alignment / text_preserve_style **only** when the prompt asks for them. Otherwise leave them null.
- For object_recolor / character_hair_recolor / global_color_change, set color_tolerance to "wide" if the user says "all reds / all warm tones / loosely", "narrow" if they say "only the exact color / only the pure red / strictly". Default null.
- Use operation "auto_commentary" when the user asks for play-by-play / sports-style commentary / shoutcast / narration / voiceover over ANY video clip (sports, vlogs, gameplay, tutorials, etc.). Set commentary_tone (hype | dry | roast) from the prompt vibe; default "hype". Pull commentary_player_name from phrases like "for X" / "as X" / "named X" when they name a person or team. Set commentary_keep_source_audio = true ONLY when the user explicitly wants original audio kept/ducked under the voice; default false (mute original).
- For auto_commentary, do NOT also produce text_replacement just because the prompt mentions a player name; the name belongs in commentary_player_name.

Examples:
User: Change the GAME OVER text to BOTH
JSON:
{{
  "operation": "text_replacement",
  "target": {{"type": "text", "value": "GAME OVER"}},
  "replacement": {{"type": "text", "value": "BOTH"}},
  "target_color": null,
  "source_color": null,
  "scope": "whole_clip",
  "needs_reference": false,
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.96,
  "notes": ["text replacement request"]
}}

User: Change the female character's hair color to pink
JSON:
{{
  "operation": "character_hair_recolor",
  "target": {{"type": "object", "value": "female character hair"}},
  "replacement": {{"type": "none", "value": null}},
  "target_color": "pink",
  "source_color": null,
  "scope": "whole_clip",
  "needs_reference": false,
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.95,
  "notes": ["hair recolor request"]
}}

User: Add a heavy thunderstorm and gritty battlefield mood without changing gameplay
JSON:
{{
  "operation": "atmosphere_overlay",
  "target": {{"type": "none", "value": null}},
  "replacement": {{"type": "none", "value": null}},
  "target_color": null,
  "source_color": null,
  "scope": "whole_clip",
  "needs_reference": false,
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.93,
  "notes": ["atmospheric overlays only; geometry preserved"],
  "atmosphere_particles": "rain",
  "atmosphere_particle_intensity": 0.85,
  "atmosphere_wind": 0.2,
  "atmosphere_haze": "mist",
  "atmosphere_flashes": "lightning",
  "atmosphere_tint": "cool",
  "atmosphere_tint_strength": 0.45,
  "atmosphere_brightness": "darker",
  "atmosphere_saturation": "low",
  "atmosphere_heat_haze": 0.0,
  "atmosphere_vignette": 0.45,
  "atmosphere_audio_bed": "rain",
  "atmosphere_summary": "Heavy thunderstorm, cool gritty grade, lightning flashes"
}}

User: Make it look sunny but with light snowing, keep gameplay
JSON:
{{
  "operation": "atmosphere_overlay",
  "target": {{"type": "none", "value": null}},
  "replacement": {{"type": "none", "value": null}},
  "target_color": null,
  "source_color": null,
  "scope": "whole_clip",
  "needs_reference": false,
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.9,
  "notes": ["mixed weather: sunny + light snow"],
  "atmosphere_particles": "snow",
  "atmosphere_particle_intensity": 0.35,
  "atmosphere_wind": 0.1,
  "atmosphere_haze": "none",
  "atmosphere_flashes": "none",
  "atmosphere_tint": "warm",
  "atmosphere_tint_strength": 0.25,
  "atmosphere_brightness": "brighter",
  "atmosphere_saturation": "high",
  "atmosphere_heat_haze": 0.0,
  "atmosphere_vignette": 0.2,
  "atmosphere_audio_bed": "wind",
  "atmosphere_summary": "Bright sunny look with gentle snow falling"
}}

User: Cyclone with heavy wind and dust, no rain
JSON:
{{
  "operation": "atmosphere_overlay",
  "target": {{"type": "none", "value": null}},
  "replacement": {{"type": "none", "value": null}},
  "target_color": null,
  "source_color": null,
  "scope": "whole_clip",
  "needs_reference": false,
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.9,
  "notes": ["wind-driven dust, no rain"],
  "atmosphere_particles": "dust",
  "atmosphere_particle_intensity": 0.8,
  "atmosphere_wind": 0.8,
  "atmosphere_haze": "sand",
  "atmosphere_flashes": "none",
  "atmosphere_tint": "amber",
  "atmosphere_tint_strength": 0.4,
  "atmosphere_brightness": "darker",
  "atmosphere_saturation": "low",
  "atmosphere_heat_haze": 0.2,
  "atmosphere_vignette": 0.4,
  "atmosphere_audio_bed": "wind",
  "atmosphere_summary": "Cyclone-driven dust storm, no rain"
}}

User request:
{command}
""".strip()


def get_prompt_parser_status() -> Dict[str, Any]:
    base_url = os.getenv("AIEDIT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("AIEDIT_OLLAMA_MODEL", "qwen2.5:7b")
    status = {
        "preferred_backend": "ollama_llm",
        "fallback_backend": "rule_based",
        "ollama_url": base_url,
        "ollama_model": model,
        "ollama_available": False,
        "warnings": [],
    }
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        if response.ok:
            status["ollama_available"] = True
            models = [item.get("name", "") for item in response.json().get("models", [])]
            if model not in models:
                status["warnings"].append(
                    f"Ollama is running but model '{model}' is not pulled yet."
                )
    except requests.RequestException:
        status["warnings"].append("Ollama is not running locally, so the parser will fall back to rule-based mode.")
    return status


# --------------------------------------------------------------------------- #
# Atmosphere knob mapping (LLM/rule fields -> renderer params).
# Designed to be generic so the user can describe any weather/look freely.
# --------------------------------------------------------------------------- #


_TINT_BGR: Dict[str, tuple] = {
    "warm": (40, 90, 195),
    "amber": (40, 110, 210),
    "orange": (35, 120, 220),
    "red": (40, 50, 215),
    "yellow": (50, 200, 230),
    "magenta": (170, 50, 200),
    "purple": (200, 60, 110),
    "cool": (200, 80, 30),
    "blue": (220, 80, 20),
    "teal": (180, 160, 30),
    "green": (50, 180, 60),
    "neutral": (40, 30, 20),
}

_HAZE_PROFILES: Dict[str, tuple] = {
    "none": (0.0, (180.0, 180.0, 180.0)),
    "mist": (0.18, (190.0, 190.0, 195.0)),
    "fog": (0.4, (185.0, 185.0, 185.0)),
    "heavy_fog": (0.65, (180.0, 180.0, 180.0)),
    "sand": (0.45, (140.0, 175.0, 205.0)),
}

_BRIGHTNESS_EXPOSURE: Dict[str, float] = {
    "darker": -0.10,
    "normal": 0.0,
    "brighter": 0.08,
}

_SATURATION_MUL: Dict[str, float] = {"low": 0.65, "normal": 1.0, "high": 1.25}


def _atmosphere_fields_from_plan(plan: ParsedEditPlan) -> Dict[str, Any]:
    """Pull the high-level atmosphere fields off a ParsedEditPlan.

    Honors the new generic knobs first; falls back to the legacy
    rain/lightning/preset trio for older LLM responses.
    """

    fields: Dict[str, Any] = {}
    if plan.atmosphere_particles is not None:
        fields["particles"] = plan.atmosphere_particles
    elif plan.atmosphere_rain is True:
        fields["particles"] = "rain"
    elif plan.atmosphere_rain is False:
        fields["particles"] = "none"

    if plan.atmosphere_particle_intensity is not None:
        fields["particle_intensity"] = plan.atmosphere_particle_intensity
    if plan.atmosphere_wind is not None:
        fields["wind"] = plan.atmosphere_wind
    if plan.atmosphere_haze is not None:
        fields["haze"] = plan.atmosphere_haze
    if plan.atmosphere_flashes is not None:
        fields["flashes"] = plan.atmosphere_flashes
    elif plan.atmosphere_lightning is True:
        fields["flashes"] = "lightning"
    elif plan.atmosphere_lightning is False:
        fields["flashes"] = "none"
    if plan.atmosphere_tint is not None:
        fields["tint"] = plan.atmosphere_tint
    if plan.atmosphere_tint_strength is not None:
        fields["tint_strength"] = plan.atmosphere_tint_strength
    if plan.atmosphere_brightness is not None:
        fields["brightness"] = plan.atmosphere_brightness
    if plan.atmosphere_saturation is not None:
        fields["saturation"] = plan.atmosphere_saturation
    if plan.atmosphere_heat_haze is not None:
        fields["heat_haze"] = plan.atmosphere_heat_haze
    if plan.atmosphere_vignette is not None:
        fields["vignette"] = plan.atmosphere_vignette
    if plan.atmosphere_audio_bed is not None:
        fields["audio_bed"] = plan.atmosphere_audio_bed
    if plan.atmosphere_summary:
        fields["summary"] = plan.atmosphere_summary
    if plan.atmosphere_tint_color:
        fields["tint_color"] = plan.atmosphere_tint_color

    if plan.atmosphere_preset and "tint" not in fields:
        if plan.atmosphere_preset.lower() == "battlefield":
            fields.setdefault("tint", "cool")
            fields.setdefault("saturation", "low")
            fields.setdefault("tint_strength", 0.3)
            fields.setdefault("brightness", "darker")
        elif plan.atmosphere_preset.lower() == "neutral":
            fields.setdefault("tint", "neutral")
    return fields


def _atmosphere_fields_to_renderer_params(
    fields: Dict[str, Any],
) -> tuple:
    """Return (renderer_params, human_summary) for ``utils.atmosphere_overlay``."""

    f = dict(fields or {})
    particles = str(f.get("particles") or "none").lower()
    if particles not in {"none", "rain", "snow", "hail", "dust", "ash"}:
        particles = "none"

    try:
        particle_intensity = float(f.get("particle_intensity"))
    except (TypeError, ValueError):
        particle_intensity = 0.0 if particles == "none" else 0.55

    try:
        wind = float(f.get("wind", 0.0))
    except (TypeError, ValueError):
        wind = 0.0

    haze_kind = str(f.get("haze") or "none").lower()
    if haze_kind not in _HAZE_PROFILES:
        haze_kind = "none"
    haze_strength, haze_color = _HAZE_PROFILES[haze_kind]

    flashes = str(f.get("flashes") or "none").lower()
    if flashes not in {"none", "lightning"}:
        flashes = "none"

    tint = str(f.get("tint") or "neutral").lower()
    explicit_tint = f.get("tint_color")
    explicit_bgr = resolve_color(explicit_tint) if explicit_tint else None
    if explicit_bgr is not None:
        tint_bgr = explicit_bgr
    else:
        tint_bgr = _TINT_BGR.get(tint, _TINT_BGR["neutral"])
    try:
        tint_strength = float(f.get("tint_strength"))
    except (TypeError, ValueError):
        tint_strength = 0.25 if (tint != "neutral" or explicit_bgr is not None) else 0.10

    brightness = str(f.get("brightness") or "normal").lower()
    exposure_add = _BRIGHTNESS_EXPOSURE.get(brightness, 0.0)

    saturation = str(f.get("saturation") or "normal").lower()
    saturation_mul = _SATURATION_MUL.get(saturation, 1.0)

    try:
        heat_haze = float(f.get("heat_haze", 0.0))
    except (TypeError, ValueError):
        heat_haze = 0.0

    try:
        vignette = float(f.get("vignette", 0.35))
    except (TypeError, ValueError):
        vignette = 0.35

    audio_bed = str(f.get("audio_bed") or "").lower()
    if audio_bed not in {"rain", "wind", "none"}:
        if particles == "rain":
            audio_bed = "rain"
        elif particles in {"snow", "hail", "dust", "ash"} or haze_strength > 0.2:
            audio_bed = "wind"
        else:
            audio_bed = "none"

    params: Dict[str, Any] = {
        "particle_kind": particles,
        "particle_intensity": max(0.0, min(1.0, particle_intensity)),
        "particle_wind": max(-1.0, min(1.0, wind)),
        "flash_kind": flashes,
        "haze_strength": haze_strength,
        "haze_color_bgr": haze_color,
        "tint_bgr": tint_bgr,
        "tint_strength": max(0.0, min(1.0, tint_strength)),
        "exposure_add": exposure_add,
        "saturation_mul": saturation_mul,
        "heat_haze": max(0.0, min(1.0, heat_haze)),
        "vignette": max(0.0, min(0.85, vignette)),
        "audio_bed": audio_bed,
        "mix_rain_audio": audio_bed != "none",
    }

    summary_text = str(f.get("summary") or "").strip()
    if not summary_text:
        bits = []
        if particles != "none":
            bits.append(f"{particles}")
        if flashes == "lightning":
            bits.append("lightning")
        if haze_kind != "none":
            bits.append(haze_kind.replace("_", " "))
        if tint != "neutral":
            bits.append(f"{tint} grade")
        if brightness != "normal":
            bits.append(brightness)
        if heat_haze > 0.1:
            bits.append("heat haze")
        summary_text = (
            "Atmosphere overlay: " + ", ".join(bits)
            if bits
            else "Atmosphere overlay (subtle grade)"
        )
    return params, summary_text


def _text_style_overrides_from_plan(plan: ParsedEditPlan) -> Dict[str, Any]:
    """Collect prompt-driven text-replacement style overrides.

    Empty dict means "let the existing estimate_text_style + UI checkbox decide".
    Anything set here flows into the renderer as a partial override.
    """

    overrides: Dict[str, Any] = {}
    if plan.text_color:
        bgr = resolve_color(plan.text_color)
        if bgr is not None:
            overrides["color"] = list(bgr)
            overrides["color_label"] = plan.text_color
    if plan.text_stroke_color:
        bgr = resolve_color(plan.text_stroke_color)
        if bgr is not None:
            overrides["stroke_color"] = list(bgr)
    if plan.text_font_family:
        overrides["font_family"] = str(plan.text_font_family)
    if plan.text_font_size:
        try:
            overrides["font_size"] = max(6, int(plan.text_font_size))
        except (TypeError, ValueError):
            pass
    if plan.text_font_weight:
        overrides["font_weight"] = str(plan.text_font_weight).lower()
    if plan.text_alignment:
        overrides["align"] = str(plan.text_alignment).lower()
    if plan.text_preserve_style is not None:
        overrides["preserve_style"] = bool(plan.text_preserve_style)
    return overrides


def _convert_plan_to_instruction(plan: ParsedEditPlan, parser_backend: str) -> EditInstruction:
    notes = [note for note in plan.notes if note]
    metadata = {
        "parser_backend": parser_backend,
        "confidence": float(plan.confidence),
        "needs_clarification": bool(plan.needs_clarification),
        "clarification_question": plan.clarification_question,
    }

    if plan.needs_clarification:
        warnings = list(notes)
        if plan.clarification_question:
            warnings.append(plan.clarification_question)
        return EditInstruction(
            operation="unsupported",
            summary="The prompt needs clarification before editing can start.",
            supported=False,
            warnings=warnings or ["Please clarify the requested edit."],
            metadata=metadata,
        )

    operation = plan.operation
    if operation == "text_replacement":
        old_text = _normalize_text_target(plan.target.value or "")
        new_text = (plan.replacement.value or "").strip(" '\"")
        if old_text and new_text:
            params: Dict[str, Any] = {"old_text": old_text, "new_text": new_text}
            style = _text_style_overrides_from_plan(plan)
            if style:
                params["style_overrides"] = style
            return EditInstruction(
                operation=operation,
                summary=f"Replace text '{old_text}' with '{new_text}'.",
                parameters=params,
                warnings=notes,
                metadata=metadata,
            )
    elif operation == "text_removal":
        return EditInstruction(
            operation=operation,
            summary="Remove text from the video.",
            warnings=notes,
            metadata=metadata,
        )
    elif operation == "text_detection":
        return EditInstruction(
            operation=operation,
            summary="Detect text in the video.",
            warnings=notes,
            metadata=metadata,
        )
    elif operation == "frame_extraction":
        return EditInstruction(
            operation=operation,
            summary="Extract frames from the video.",
            warnings=notes,
            metadata=metadata,
        )
    elif operation == "character_hair_recolor":
        target_color = (plan.target_color or plan.replacement.value or "").strip()
        if resolve_color(target_color) is not None:
            return EditInstruction(
                operation=operation,
                summary=f"Change detected hair regions to {target_color}.",
                parameters={"target_color": target_color},
                warnings=notes,
                metadata=metadata,
            )
    elif operation == "object_recolor":
        target_object = _clean_target_phrase(plan.target.value or "")
        target_color = (plan.target_color or plan.replacement.value or "").strip()
        if target_object and resolve_color(target_color) is not None:
            params: Dict[str, Any] = {
                "target_object": target_object,
                "target_color": target_color,
            }
            if plan.color_tolerance:
                params["tolerance"] = plan.color_tolerance
            return EditInstruction(
                operation=operation,
                summary=f"Change {target_object} to {target_color}.",
                parameters=params,
                warnings=notes,
                metadata=metadata,
            )
    elif operation == "object_remove":
        target_object = _clean_target_phrase(plan.target.value or "")
        if target_object:
            return EditInstruction(
                operation=operation,
                summary=f"Remove {target_object} from the clip.",
                parameters={"target_object": target_object},
                warnings=notes,
                metadata=metadata,
            )
    elif operation == "object_replace_guided":
        target_object = _clean_target_phrase(plan.target.value or "")
        replacement_object = _clean_target_phrase(plan.replacement.value or "")
        if target_object and replacement_object:
            warnings = list(notes)
            if plan.needs_reference:
                warnings.append("Best results need a reference image for the replacement object.")
            return EditInstruction(
                operation=operation,
                summary=f"Replace {target_object} with {replacement_object}.",
                parameters={
                    "target_object": target_object,
                    "replacement_object": replacement_object,
                    "needs_reference": bool(plan.needs_reference),
                },
                warnings=list(dict.fromkeys(warnings)),
                metadata=metadata,
            )
    elif operation == "global_color_change":
        source_color = (plan.source_color or plan.target.value or "").strip()
        target_color = (plan.target_color or plan.replacement.value or "").strip()
        if resolve_color(source_color) is not None and resolve_color(target_color) is not None:
            params = {"source_color": source_color, "target_color": target_color}
            if plan.color_tolerance:
                params["tolerance"] = plan.color_tolerance
            return EditInstruction(
                operation=operation,
                summary=f"Change {source_color} regions to {target_color}.",
                parameters=params,
                warnings=notes,
                metadata=metadata,
            )
    elif operation == "atmosphere_overlay":
        fields = _atmosphere_fields_from_plan(plan)
        params, summary = _atmosphere_fields_to_renderer_params(fields)
        warn = list(notes)
        warn.append(
            "Atmosphere mode only adds grading and overlays — it does not regenerate geometry, characters, or layout."
        )
        return EditInstruction(
            operation=operation,
            summary=summary,
            parameters=params,
            warnings=warn,
            metadata=metadata,
        )
    elif operation == "auto_commentary":
        tone = (plan.commentary_tone or "hype").lower()
        if tone not in {"hype", "dry", "roast"}:
            tone = "hype"
        keep_audio = plan.commentary_keep_source_audio
        if keep_audio is None:
            keep_audio = False
        params: Dict[str, Any] = {
            "tone": tone,
            "player_name": (plan.commentary_player_name or "").strip() or None,
            "keep_source_audio": bool(keep_audio),
            "voice": (plan.commentary_voice or "en-US-GuyNeural").strip(),
            "rate": (plan.commentary_rate or "+0%").strip(),
        }
        bits = ["Add play-by-play voiceover", f"({tone} tone)"]
        if params["player_name"]:
            bits.append(f"for {params['player_name']}")
        if not keep_audio:
            bits.append("muting original audio")
        return EditInstruction(
            operation=operation,
            summary=" ".join(bits) + ".",
            parameters=params,
            warnings=list(notes) + [
                "Commentary references on-screen details from sampled frames; off-screen audio alone won't be narrated.",
            ],
            metadata=metadata,
        )

    return EditInstruction(
        operation="unsupported",
        summary="The LLM parser could not map this prompt to a supported edit plan.",
        supported=False,
        warnings=notes or ["Please rephrase the prompt or use a more specific edit request."],
        metadata=metadata,
    )


def _parse_with_ollama(command: str) -> Optional[EditInstruction]:
    status = get_prompt_parser_status()
    if not status["ollama_available"]:
        return None

    base_url = status["ollama_url"]
    model = status["ollama_model"]
    prompt = _build_llm_prompt(command)
    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": 350,
                },
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        json_payload = _extract_json_object(payload.get("response", ""))
        if not json_payload:
            raise ValueError("No valid JSON returned by Ollama.")
        plan = ParsedEditPlan.model_validate(json_payload)
        return _convert_plan_to_instruction(plan, parser_backend=f"ollama:{model}")
    except (requests.RequestException, ValidationError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("LLM prompt parsing failed, falling back to rule-based parser: %s", exc)
        return None


_ATMOSPHERE_TRIGGERS = (
    "atmosphere", "atmospheric", "weather", "color grade", "colour grade",
    "grading", "cinematic", "film look", "movie look", "vibe",
    "look like", "feel like", "make it feel", "make it look",
    "without regenerating", "without regeneration", "do not regenerate",
    "don't regenerate", "same gameplay", "keep gameplay", "keep movement",
    "rain", "raining", "downpour", "drizzle", "wet weather",
    "thunder", "thunderstorm", "lightning", "storm", "stormy",
    "cyclone", "hurricane", "typhoon", "tropical storm",
    "snow", "snowing", "snowfall", "blizzard", "snowstorm",
    "hail", "hailing",
    "fog", "foggy", "mist", "misty", "haze",
    "overcast", "cloudy", "gloomy", "gray sky", "grey sky",
    "sand", "sandstorm", "haboob", "dust", "dusty", "dust storm",
    "sunny", "bright", "clear sky", "midday", "noon",
    "scorching", "harsh sun", "desert", "summer day",
    "golden hour", "sunset", "sunrise", "dusk", "dawn", "twilight",
    "night", "moonlit", "evening", "dark sky",
    "ash", "volcanic", "eruption", "smoky", "smoke",
    "battlefield", "war zone", "warzone", "combat",
    "neon", "cyberpunk",
)


def _detect_atmosphere_fields(text: str) -> Optional[Dict[str, Any]]:
    """Map any freeform weather / mood description to high-level fields.

    Multiple weathers stack ("sunny but snowing" -> warm tint + snow).
    Returns None if the prompt does not look atmospheric at all.
    """

    cl = text.lower()
    if not any(t in cl for t in _ATMOSPHERE_TRIGGERS):
        return None

    fields: Dict[str, Any] = {}

    no_rain = any(x in cl for x in ("no rain", "without rain", "dry look"))
    if not no_rain and any(
        x in cl for x in ("rain", "raining", "downpour", "drizzle", "storm", "thunderstorm", "wet weather")
    ):
        fields["particles"] = "rain"
        fields["particle_intensity"] = 0.55
        if any(x in cl for x in ("downpour", "heavy rain", "torrential", "monsoon")):
            fields["particle_intensity"] = 0.85
        elif "drizzle" in cl:
            fields["particle_intensity"] = 0.30

    if any(x in cl for x in ("snow", "snowing", "snowfall", "blizzard", "snowstorm")):
        fields["particles"] = "snow"
        fields["particle_intensity"] = fields.get("particle_intensity", 0.55)
        if "blizzard" in cl or "snowstorm" in cl:
            fields["particle_intensity"] = 0.85
            fields["wind"] = 0.6

    if "hail" in cl:
        fields["particles"] = "hail"
        fields["particle_intensity"] = 0.7

    if any(x in cl for x in ("sandstorm", "haboob", "dust storm", "sand storm")):
        fields["particles"] = "dust"
        fields["particle_intensity"] = 0.8
        fields["wind"] = 0.7
        fields["haze"] = "sand"
    elif any(x in cl for x in ("dust", "dusty")):
        fields["particles"] = fields.get("particles", "dust")
        fields["particle_intensity"] = fields.get("particle_intensity", 0.4)

    if any(x in cl for x in ("ash", "volcanic", "eruption", "smoky", "smoke")):
        fields["particles"] = "ash"
        fields["particle_intensity"] = 0.6
        fields["tint"] = fields.get("tint", "amber")
        fields["saturation"] = "low"

    if any(x in cl for x in ("cyclone", "hurricane", "typhoon", "tropical storm")):
        fields["wind"] = max(float(fields.get("wind", 0.0)), 0.7)
        fields["particles"] = fields.get("particles", "rain")
        fields["particle_intensity"] = max(float(fields.get("particle_intensity", 0.0)), 0.85)
        fields["haze"] = fields.get("haze", "mist")

    no_flash = any(x in cl for x in ("no lightning", "no flash", "no thunder"))
    if no_flash:
        fields["flashes"] = "none"
    elif any(x in cl for x in ("lightning", "thunder", "thunderstorm", "flash of lightning")):
        fields["flashes"] = "lightning"

    if any(x in cl for x in ("heavy fog", "thick fog", "dense fog")):
        fields["haze"] = "heavy_fog"
    elif any(x in cl for x in ("fog", "foggy")):
        fields["haze"] = fields.get("haze", "fog")
    elif any(x in cl for x in ("mist", "misty")):
        fields["haze"] = fields.get("haze", "mist")

    if any(x in cl for x in ("overcast", "cloudy", "gloomy", "gray sky", "grey sky")):
        fields["tint"] = fields.get("tint", "cool")
        fields["saturation"] = fields.get("saturation", "low")
        fields["brightness"] = fields.get("brightness", "darker")

    if any(x in cl for x in ("golden hour", "sunset", "sunrise", "dusk", "dawn", "twilight")):
        fields["tint"] = "amber"
        fields["tint_strength"] = 0.45
        fields["saturation"] = fields.get("saturation", "high")

    if any(x in cl for x in ("sunny", "scorching", "harsh sun", "midday", "noon", "desert", "summer day", "bright day")):
        fields["tint"] = fields.get("tint", "warm")
        fields["brightness"] = fields.get("brightness", "brighter")
        fields["saturation"] = fields.get("saturation", "high")
        if any(x in cl for x in ("scorching", "desert", "heat haze", "shimmering heat", "very hot")):
            fields["heat_haze"] = max(float(fields.get("heat_haze", 0.0)), 0.6)

    if any(x in cl for x in ("night", "moonlit", "evening", "dark sky", "after dark")):
        fields["tint"] = fields.get("tint", "blue")
        fields["brightness"] = fields.get("brightness", "darker")
        fields["saturation"] = fields.get("saturation", "low")
        fields["vignette"] = max(float(fields.get("vignette", 0.0)), 0.5)

    if any(x in cl for x in ("battlefield", "war zone", "warzone", "combat", "military", "soldier")):
        fields["tint"] = fields.get("tint", "cool")
        fields["saturation"] = fields.get("saturation", "low")
        fields["tint_strength"] = max(float(fields.get("tint_strength", 0.0)), 0.35)
        fields["brightness"] = fields.get("brightness", "darker")

    if any(x in cl for x in ("neon", "cyberpunk")):
        fields["tint"] = "magenta"
        fields["tint_strength"] = max(float(fields.get("tint_strength", 0.0)), 0.45)
        fields["saturation"] = "high"

    if any(x in cl for x in ("cinematic", "film look", "movie look")):
        fields["vignette"] = max(float(fields.get("vignette", 0.0)), 0.4)
        fields["tint_strength"] = max(float(fields.get("tint_strength", 0.0)), 0.2)

    # Pick up an explicit color literal when the prompt mentions the words
    # "tint", "grade", "look", "wash", "filter" near a color spec.
    if any(w in cl for w in ("tint", "grade", "look", "wash", "filter", "hue")):
        explicit = extract_color_from_text(text)
        if explicit and resolve_color(explicit) is not None:
            fields["tint_color"] = explicit
            fields["tint_strength"] = max(float(fields.get("tint_strength", 0.0)), 0.35)

    fields.setdefault("particles", "none")
    fields.setdefault("flashes", "none")

    summary_bits = []
    if fields.get("particles") not in (None, "none"):
        summary_bits.append(str(fields["particles"]))
    if fields.get("haze") not in (None, "none"):
        summary_bits.append(str(fields["haze"]).replace("_", " "))
    if fields.get("flashes") == "lightning":
        summary_bits.append("lightning")
    if fields.get("tint"):
        summary_bits.append(f"{fields['tint']} grade")
    if fields.get("brightness") and fields["brightness"] != "normal":
        summary_bits.append(fields["brightness"])
    if fields.get("heat_haze", 0) > 0.1:
        summary_bits.append("heat haze")
    fields["summary"] = (
        "Atmosphere overlay: " + ", ".join(summary_bits)
        if summary_bits
        else "Atmosphere overlay (subtle grade)"
    )
    return fields


def _parse_atmosphere_overlay_command(command: str) -> Optional[EditInstruction]:
    """Freeform atmosphere parser. Detects ANY weather/mood description."""

    fields = _detect_atmosphere_fields(command or "")
    if fields is None:
        return None

    params, summary = _atmosphere_fields_to_renderer_params(fields)
    return EditInstruction(
        operation="atmosphere_overlay",
        summary=summary,
        parameters=params,
        warnings=[
            "Gameplay layout and motion stay the same; only grading and layered effects are applied.",
        ],
        metadata={"parser_backend": "rule_based", "confidence": 0.78},
    )


_COMMENTARY_TRIGGERS = (
    "commentary",
    "commentate",
    "play by play",
    "play-by-play",
    "voice over",
    "voice-over",
    "voiceover",
    "vo over the clip",
    "caster",
    "shoutcast",
    "narrate the gameplay",
    "narrate this clip",
    "narrate this gameplay",
    "narration over gameplay",
)

_TONE_KEYWORDS = {
    "hype": ("hype", "excited", "energetic", "loud", "esports"),
    "dry": ("dry", "deadpan", "calm", "monotone", "sarcastic"),
    "roast": ("roast", "trash talk", "trash-talk", "savage", "burn"),
}


def _detect_commentary_tone(text_lc: str) -> str:
    for tone, words in _TONE_KEYWORDS.items():
        if any(w in text_lc for w in words):
            return tone
    return "hype"


_NAME_STOP_WORDS = {
    "and", "but", "with", "without", "keep", "drop", "mute", "in", "on",
    "for", "as", "the", "a", "an", "this", "that", "clip", "video",
    "gameplay", "audio", "voice", "low", "high", "under", "over",
}


def _detect_commentary_player_name(command: str) -> Optional[str]:
    if not command:
        return None

    quoted = re.search(
        r"(?:for|as|named|player(?:\s+name)?(?:\s+is)?|i\s+am|i'?m)\s+['\"]([^'\"]{2,40})['\"]",
        command,
    )
    if quoted:
        return quoted.group(1).strip()

    m = re.search(
        r"(?:for|as|named|player(?:\s+name)?(?:\s+is)?|i\s+am|i'?m)\s+([A-Za-z][A-Za-z0-9_\-\.]+(?:\s+[A-Za-z][A-Za-z0-9_\-\.]+)?)",
        command,
    )
    if not m:
        return None

    candidate = m.group(1).strip(" '\"")
    parts = [p for p in candidate.split() if p]
    while parts and parts[-1].lower().rstrip(",.;:") in _NAME_STOP_WORDS:
        parts.pop()
    if not parts:
        return None
    cleaned = " ".join(parts).strip(" .,;:'\"")
    if cleaned.lower() in _NAME_STOP_WORDS:
        return None
    return cleaned or None


def _parse_auto_commentary_command(command: str) -> Optional[EditInstruction]:
    """Detect auto-commentary requests like 'add hype commentary to this clip'."""

    if not command:
        return None
    cl = command.lower()
    if not any(trigger in cl for trigger in _COMMENTARY_TRIGGERS):
        return None

    tone = _detect_commentary_tone(cl)
    player_name = _detect_commentary_player_name(command)

    keep_audio = False
    if any(p in cl for p in ("keep original audio", "keep source audio", "keep game audio", "with game audio", "duck original", "lower original audio")):
        keep_audio = True
    elif any(p in cl for p in ("mute original", "mute source", "mute audio", "no game audio", "drop game audio", "remove game audio", "mute the original")):
        keep_audio = False

    summary_bits = ["Add play-by-play voiceover"]
    summary_bits.append(f"({tone} tone)")
    if player_name:
        summary_bits.append(f"for {player_name}")
    if not keep_audio:
        summary_bits.append("muting original audio")

    return EditInstruction(
        operation="auto_commentary",
        summary=" ".join(summary_bits) + ".",
        parameters={
            "tone": tone,
            "player_name": player_name,
            "keep_source_audio": keep_audio,
            "voice": "en-US-GuyNeural",
            "rate": "+0%",
        },
        warnings=[
            "Commentary is driven by sampled on-screen details; off-screen cues won't be referenced.",
        ],
        metadata={"parser_backend": "rule_based", "confidence": 0.82},
    )


def _detect_text_style_from_command(command: str) -> Dict[str, Any]:
    """Pull text-style hints out of a freeform replacement prompt."""

    out: Dict[str, Any] = {}
    if not command:
        return out
    cl = command.lower()

    color_phrase = re.search(
        r"\bin\s+([#0-9a-fA-F]{3,7}|rgba?\([^)]+\)|[a-z][a-z\s]{0,20}?)\s+(?:text|font|letters?|color|colour)?",
        command,
        re.IGNORECASE,
    )
    if color_phrase:
        token = color_phrase.group(1).strip()
        if resolve_color(token) is not None:
            out["color"] = list(resolve_color(token))
            out["color_label"] = token
    if "color" not in out:
        token = extract_color_from_text(command)
        if token and resolve_color(token) is not None:
            out["color"] = list(resolve_color(token))
            out["color_label"] = token

    size_match = re.search(r"\b(?:size|font\s*size)\s*(\d{1,3})\b", cl)
    if size_match:
        try:
            out["font_size"] = max(6, int(size_match.group(1)))
        except ValueError:
            pass

    if re.search(r"\bbold\b|\bheavy\b|\bthick\s+text\b", cl):
        out["font_weight"] = "bold"
    if re.search(r"\bcenter(ed)?\b", cl):
        out["align"] = "center"
    elif re.search(r"\bleft[-\s]?align(ed)?\b", cl):
        out["align"] = "left"
    elif re.search(r"\bright[-\s]?align(ed)?\b", cl):
        out["align"] = "right"

    family_match = re.search(
        r"\b(?:in|using)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+font\b",
        command,
    )
    if family_match:
        out["font_family"] = family_match.group(1).strip()

    if re.search(r"\bkeep\s+(?:the\s+)?(?:original|same)\s+(?:style|font|look)\b", cl):
        out["preserve_style"] = True
    if re.search(r"\bdo\s+not\s+keep\s+(?:the\s+)?(?:style|font)\b|\bignore\s+(?:the\s+)?original\s+style\b", cl):
        out["preserve_style"] = False
    return out


def _detect_color_tolerance(command_lower: str) -> Optional[str]:
    """Map natural-language strictness phrases to a tolerance bucket."""

    if not command_lower:
        return None
    if re.search(r"\b(only the|just the|exact(ly)?|strictly|pure)\s+(this|that|the)?\s*colou?r\b", command_lower):
        return "narrow"
    if re.search(r"\bonly the (pure|exact) [a-z]+\b|\bonly the [a-z]+ pixels\b", command_lower):
        return "narrow"
    if re.search(r"\ball\s+(reds|blues|greens|yellows|oranges|purples|pinks|warm|cool)\b", command_lower):
        return "wide"
    if re.search(r"\bloosely|broad(ly)?|every\s+shade\s+of\b", command_lower):
        return "wide"
    if re.search(r"\bevery\s+(reddish|bluish|greenish|warm|cool)\s+pixel\b", command_lower):
        return "very_wide"
    return None


def _parse_rule_based(command: str) -> EditInstruction:
    command = (command or "").strip()
    command_lower = command.lower()

    if not command:
        return EditInstruction(
            operation="unknown",
            summary="No command provided.",
            supported=False,
            warnings=["Enter a command before processing."],
            metadata={"parser_backend": "rule_based", "confidence": 0.0},
        )

    quoted_replace_match = re.search(
        r"(?:replace|change|make)\s+['\"](.+?)['\"]\s+(?:with|to|say)\s+['\"](.+?)['\"]",
        command,
        re.IGNORECASE,
    )
    if quoted_replace_match:
        old_text = _normalize_text_target(quoted_replace_match.group(1))
        new_text = quoted_replace_match.group(2).strip()
        params = {"old_text": old_text, "new_text": new_text}
        style = _detect_text_style_from_command(command)
        if style:
            params["style_overrides"] = style
        return EditInstruction(
            operation="text_replacement",
            summary=f"Replace text '{old_text}' with '{new_text}'.",
            parameters=params,
            metadata={"parser_backend": "rule_based", "confidence": 0.86},
        )

    commentary_inst = _parse_auto_commentary_command(command)
    if commentary_inst is not None:
        return commentary_inst

    atm_inst = _parse_atmosphere_overlay_command(command)
    if atm_inst is not None:
        return atm_inst

    from utils.timeline_parser_rules import parse_timeline_command

    timeline_inst = parse_timeline_command(command)
    if timeline_inst is not None:
        return timeline_inst

    if "firework" in command_lower or "pattern" in command_lower:
        if any(keyword in command_lower for keyword in ["remove", "delete", "erase"]):
            return EditInstruction(
                operation="object_remove",
                summary="Remove the fireworks/object from the clip.",
                parameters={"target_object": "fireworks"},
                warnings=["Small or fast-moving particles may need a short clip for best results."],
                metadata={"parser_backend": "rule_based", "confidence": 0.74},
            )
        return EditInstruction(
            operation="unsupported_generative_edit",
            summary="This request needs stronger generative video editing than the local mask-based workflow.",
            supported=False,
            warnings=[
                "Changing object shapes or animation patterns still needs a larger generative video model.",
                "This build supports object recolor, object removal, and reference-guided replacement first.",
            ],
            metadata={"parser_backend": "rule_based", "confidence": 0.65},
        )

    if ("hair" in command_lower and "color" in command_lower) or "hair" in command_lower:
        target_match = re.search(
            r"\b(?:to|into)\s+(#?[0-9a-fA-F]{3,6}|rgba?\([^)]+\)|[A-Za-z]+)\b",
            command,
            re.IGNORECASE,
        )
        target_color = (
            target_match.group(1).strip() if target_match else _extract_color(command_lower)
        )
        if target_color and resolve_color(target_color) is not None:
            return EditInstruction(
                operation="character_hair_recolor",
                summary=f"Change detected hair regions to {target_color}.",
                parameters={"target_color": target_color},
                metadata={"parser_backend": "rule_based", "confidence": 0.85},
            )

    if any(term in command_lower for term in ["text", "subtitle", "caption", "word", "logo", "sign", "say"]):
        replace_match = re.search(
            r"(?:replace|change|make)\s+['\"]?(.*?)['\"]?\s+(?:with|to|say)\s+['\"]?(.*?)['\"]?$",
            command,
            re.IGNORECASE,
        )
        if replace_match:
            old_text = _normalize_text_target(replace_match.group(1))
            new_text = replace_match.group(2).strip(" '\"")
            if old_text and new_text:
                params = {"old_text": old_text, "new_text": new_text}
                style = _detect_text_style_from_command(command)
                if style:
                    params["style_overrides"] = style
                return EditInstruction(
                    operation="text_replacement",
                    summary=f"Replace text '{old_text}' with '{new_text}'.",
                    parameters=params,
                    metadata={"parser_backend": "rule_based", "confidence": 0.8},
                )

    if "remove" in command_lower and "text" in command_lower:
        return EditInstruction(
            operation="text_removal",
            summary="Remove text from the video.",
            metadata={"parser_backend": "rule_based", "confidence": 0.82},
        )

    if "detect" in command_lower and "text" in command_lower:
        return EditInstruction(
            operation="text_detection",
            summary="Detect text in the video.",
            metadata={"parser_backend": "rule_based", "confidence": 0.82},
        )

    if "extract" in command_lower and "frame" in command_lower:
        return EditInstruction(
            operation="frame_extraction",
            summary="Extract frames from the video.",
            metadata={"parser_backend": "rule_based", "confidence": 0.85},
        )

    target_phrase: Optional[str] = None
    target_color: Optional[str] = None
    intro_verbs = re.compile(
        r"^\s*(?:change|make|turn|paint|render)\s+",
        re.IGNORECASE,
    )
    if intro_verbs.match(command):
        # Strategy: find the LAST token in the command that resolves to a color,
        # call that the target color, and treat everything between the verb and
        # that token as the phrase. Survives "make the crown teal", "all reds to
        # blue loosely", "color to rgb(20,180,90)" without per-pattern tweaks.
        candidates = list(
            re.finditer(
                r"(#?[0-9a-fA-F]{3,6}|rgba?\([^)]+\)|[A-Za-z]+)",
                command,
            )
        )
        for m in reversed(candidates):
            token = m.group(0).strip()
            if resolve_color(token) is None:
                continue
            head = command[: m.start()].rstrip()
            head = intro_verbs.sub("", head, count=1)
            head = re.sub(r"\b(?:color|colour)\b\s*$", "", head, flags=re.IGNORECASE).strip()
            head = re.sub(r"\b(?:to|into)\s*$", "", head, flags=re.IGNORECASE).strip(" .,'\"")
            if not head:
                continue
            target_phrase = _clean_target_phrase(head.lower())
            target_color = token
            break

    if target_color and target_phrase is not None:
        tolerance = _detect_color_tolerance(command_lower)
        if resolve_color(target_color) is not None:
            embedded_color = _extract_color(target_phrase)
            phrase_resolves = resolve_color(target_phrase) is not None
            if phrase_resolves:
                params = {"source_color": target_phrase, "target_color": target_color}
                if tolerance:
                    params["tolerance"] = tolerance
                return EditInstruction(
                    operation="global_color_change",
                    summary=f"Change {target_phrase} regions to {target_color}.",
                    parameters=params,
                    metadata={"parser_backend": "rule_based", "confidence": 0.79},
                )
            if embedded_color and re.search(
                r"\b(all|every|only|just|pure)\b|reds?$|blues?$|greens?$|yellows?$|purples?$|pinks?$|oranges?$",
                target_phrase,
            ):
                params = {"source_color": embedded_color, "target_color": target_color}
                if tolerance:
                    params["tolerance"] = tolerance
                elif re.search(r"\ball\b|\bevery\b|loosely|broad", target_phrase + " " + command_lower):
                    params["tolerance"] = "wide"
                elif re.search(r"\bonly\b|\bjust\b|\bpure\b|\bexact(ly)?\b", target_phrase + " " + command_lower):
                    params["tolerance"] = "narrow"
                return EditInstruction(
                    operation="global_color_change",
                    summary=f"Change {embedded_color} regions to {target_color}.",
                    parameters=params,
                    metadata={"parser_backend": "rule_based", "confidence": 0.78},
                )
            if target_phrase:
                params = {"target_object": target_phrase, "target_color": target_color}
                if tolerance:
                    params["tolerance"] = tolerance
                return EditInstruction(
                    operation="object_recolor",
                    summary=f"Change {target_phrase} to {target_color}.",
                    parameters=params,
                    metadata={"parser_backend": "rule_based", "confidence": 0.77},
                )

    _color_token_local = r"#?[0-9a-fA-F]{3,6}|rgba?\([^)]+\)|[A-Za-z]+"
    source_target_match = re.search(
        rf"\bchange\s+({_color_token_local})\s+to\s+({_color_token_local})(?=$|[\s.,;!?])",
        command,
        re.IGNORECASE,
    )
    if source_target_match:
        source_color = source_target_match.group(1).strip()
        target_color = source_target_match.group(2).strip()
        if (
            resolve_color(source_color) is not None
            and resolve_color(target_color) is not None
        ):
            params = {"source_color": source_color, "target_color": target_color}
            tolerance = _detect_color_tolerance(command_lower)
            if tolerance:
                params["tolerance"] = tolerance
            return EditInstruction(
                operation="global_color_change",
                summary=f"Change {source_color} regions to {target_color}.",
                parameters=params,
                metadata={"parser_backend": "rule_based", "confidence": 0.77},
            )

    remove_match = re.search(
        r"(?:remove|delete|erase)\s+(.+?)(?:\s+(?:from|in|on|throughout|across|behind)\b.*)?$",
        command_lower,
    )
    if remove_match and "text" not in command_lower:
        target_object = _clean_target_phrase(remove_match.group(1))
        if target_object:
            return EditInstruction(
                operation="object_remove",
                summary=f"Remove {target_object} from the clip.",
                parameters={"target_object": target_object},
                metadata={"parser_backend": "rule_based", "confidence": 0.76},
            )

    replace_object_match = re.search(
        r"(?:replace|swap|turn)\s+(.+?)\s+(?:with|into)\s+(.+?)(?:\s+using\b.*)?$",
        command_lower,
    )
    if replace_object_match:
        source_object = _clean_target_phrase(replace_object_match.group(1))
        replacement_object = _clean_target_phrase(replace_object_match.group(2))
        if source_object and replacement_object:
            warnings = []
            if not _mentions_reference(command_lower):
                warnings.append("Best results need a reference image for the replacement object.")
            return EditInstruction(
                operation="object_replace_guided",
                summary=f"Replace {source_object} with {replacement_object}.",
                parameters={
                    "target_object": source_object,
                    "replacement_object": replacement_object,
                    "needs_reference": True,
                },
                warnings=warnings,
                metadata={"parser_backend": "rule_based", "confidence": 0.73},
            )

    # Broad fallback: only after specific recolor/remove/object-replace patterns
    # have had a chance. Otherwise prompts like "change the crown to pink" got
    # mis-classified as text replacement.
    broad_replace_match = re.search(
        r"(?:replace|change|make)\s+(.+?)\s+(?:with|to|say)\s+(.+)$",
        command,
        re.IGNORECASE,
    )
    if broad_replace_match:
        source_value = _normalize_text_target(broad_replace_match.group(1))
        replacement_value = broad_replace_match.group(2).strip(" '\"")
        if source_value and replacement_value and len(source_value.split()) <= 4:
            return EditInstruction(
                operation="text_replacement",
                summary=f"Replace text '{source_value}' with '{replacement_value}'.",
                parameters={"old_text": source_value, "new_text": replacement_value},
                metadata={"parser_backend": "rule_based", "confidence": 0.72},
            )

    return EditInstruction(
        operation="unsupported",
        summary="This prompt is outside the current local prompt-to-mask editor capabilities.",
        supported=False,
        warnings=[
            "Supported prompts include trim/cut, speed change, crop, fades, text editing, object removal, object recolor, and reference-guided replacement.",
            "Broader scene redesign still needs a heavier generative video model.",
        ],
        metadata={"parser_backend": "rule_based", "confidence": 0.3},
    )


def _decide_instruction(command: str) -> EditInstruction:
    rule_instruction = _parse_rule_based(command)
    llm_instruction = _parse_with_ollama(command)
    if llm_instruction is not None:
        if llm_instruction.supported:
            return llm_instruction
        if rule_instruction.supported:
            rule_instruction.warnings.append(
                "The local LLM parser was uncertain, so AiEdit used the rule-based fallback for this prompt."
            )
            rule_instruction.metadata["llm_fallback"] = True
            return rule_instruction
        return llm_instruction

    instruction = rule_instruction
    status = get_prompt_parser_status()
    if status["warnings"]:
        instruction.metadata.setdefault("parser_status", status)
    return instruction


def parse_edit_command(command: str) -> EditInstruction:
    command = (command or "").strip()
    if not command:
        return _parse_rule_based(command)

    instruction = _decide_instruction(command)

    # Validate + log via the shared core package. Both are best-effort: a
    # validator import error or a disk error must never break parsing.
    try:
        from core.edit_plan import validate_edit_instruction
        from core.prompt_memory import log_parse

        validation = validate_edit_instruction(instruction)
        instruction.metadata["validation"] = validation.to_dict()
        if not validation.ok and instruction.supported:
            instruction.metadata["validation_blocked"] = True
        try:
            log_parse(prompt=command, instruction=instruction, validation=validation)
        except Exception:
            pass
    except Exception as exc:
        logger.debug("core validation/memory unavailable: %s", exc)

    return instruction
