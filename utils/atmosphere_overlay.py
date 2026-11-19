"""
Atmospheric styling without regenerating geometry.

The renderer is **knob-based, not preset-based**. A user prompt like
"sunny but snowing" or "thick fog at dusk" or "cyclone winds with dust" is
parsed into a generic params dict; this module just executes whatever knobs
are set. Motion, layout, and silhouettes always stay aligned with the source
pixels (we never resynthesize geometry).

Knobs (all optional; sensible defaults applied):
    tint_bgr            : (B, G, R) float push direction         e.g. (180, 90, 30) cool blue
    tint_strength       : 0..1                                    how strong the tint push is
    saturation_mul      : 0.0..2.0                                <1 desaturate, >1 punch
    exposure_add        : -0.4..+0.4                              add to luminance (in [0,1] space)
    shadow_lift         : 0..0.5                                  raise dark areas
    contrast_mul        : 0.7..1.6                                contrast multiplier
    particle_kind       : "rain"|"snow"|"hail"|"dust"|"ash"|"none"
    particle_intensity  : 0..1
    particle_wind       : -1..1                                    lateral drift bias
    particle_speed      : 0.3..3.0                                 vertical scroll factor
    haze_strength       : 0..1                                     fog/sand veil strength
    haze_color_bgr      : (B, G, R)                                veil color
    flash_kind          : "lightning"|"none"
    flash_rate_per_min  : 0..40
    flash_strength      : 0..1
    heat_haze           : 0..1                                     bottom-band rolling warp
    vignette            : 0..0.7
    mix_rain_audio      : bool                                     post-pass audio bed
    audio_bed           : "rain"|"wind"|"none"                     selects bed type
    mix_thunder_audio   : bool                                     rumble bursts under rain/wind when lightning flashes

Optional post-pass: ``mix_rain_under_original_audio`` adds a synthesized
rain/wind bed under the existing audio via FFmpeg lavfi. When lightning is
enabled and ``mix_thunder_audio`` is true, low-frequency rumble bursts are
mixed at timestamps aligned to the same flash cadence as the video.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# FFmpeg / FFprobe helpers
# --------------------------------------------------------------------------- #

def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _ffprobe_exe() -> str:
    ff = Path(_ffmpeg_exe())
    candidate = ff.parent / ("ffprobe.exe" if ff.suffix.lower() == ".exe" else "ffprobe")
    if candidate.exists():
        return str(candidate)
    return "ffprobe"


def video_has_audio_stream(video_path: str) -> bool:
    import subprocess

    try:
        r = subprocess.run(
            [
                _ffprobe_exe(),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Color grading primitives
# --------------------------------------------------------------------------- #

def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        return float(np.clip(float(value), lo, hi))
    except (TypeError, ValueError):
        return default


def _as_bgr(value: Any, default: Tuple[float, float, float]) -> Tuple[float, float, float]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            b, g, r = float(value[0]), float(value[1]), float(value[2])
            return (
                float(np.clip(b, 0.0, 255.0)),
                float(np.clip(g, 0.0, 255.0)),
                float(np.clip(r, 0.0, 255.0)),
            )
        except (TypeError, ValueError):
            return default
    return default


def apply_generic_grade(
    img: np.ndarray,
    *,
    tint_bgr: Tuple[float, float, float],
    tint_strength: float,
    saturation_mul: float,
    exposure_add: float,
    shadow_lift: float,
    contrast_mul: float,
) -> np.ndarray:
    """One color-grading pass driven entirely by knobs (no presets)."""

    f = img.astype(np.float32) / 255.0

    if abs(saturation_mul - 1.0) > 1e-3:
        hsv = cv2.cvtColor((f * 255.0).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * float(saturation_mul), 0.0, 255.0)
        f = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32) / 255.0

    if abs(exposure_add) > 1e-3:
        f = np.clip(f + float(exposure_add), 0.0, 1.0)

    if shadow_lift > 1e-3:
        gray = cv2.cvtColor((f * 255.0).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        shadow = np.clip(1.15 - gray * 1.35, 0.0, 1.0)[..., None]
        f = np.clip(f + shadow * float(shadow_lift), 0.0, 1.0)

    if tint_strength > 1e-3:
        tint = np.array([[list(tint_bgr)]], dtype=np.float32) / 255.0
        gray = cv2.cvtColor((f * 255.0).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        weight = (1.0 - gray)[..., None] * 0.6 + 0.4  # tint shadows + midtones more than highlights
        f = np.clip(f * (1.0 - tint_strength * weight) + tint * tint_strength * weight, 0.0, 1.0)

    if abs(contrast_mul - 1.0) > 1e-3:
        f = np.clip((f - 0.5) * float(contrast_mul) + 0.5, 0.0, 1.0)

    return (f * 255.0).astype(np.uint8)


# Back-compat shims (older code paths still call these names) ----------------

def apply_battlefield_grade(img: np.ndarray, strength: float = 1.0) -> np.ndarray:
    s = _clamp(strength, 0.0, 1.5, 1.0)
    return apply_generic_grade(
        img,
        tint_bgr=(70.0, 35.0, 18.0),
        tint_strength=0.30 * s,
        saturation_mul=1.0 - 0.22 * s,
        exposure_add=-0.04 * s,
        shadow_lift=0.05 * s,
        contrast_mul=1.0 + 0.09 * s,
    )


def apply_neutral_cool_grade(img: np.ndarray, strength: float = 1.0) -> np.ndarray:
    s = _clamp(strength, 0.0, 1.5, 1.0)
    return apply_generic_grade(
        img,
        tint_bgr=(40.0, 30.0, 20.0),
        tint_strength=0.12 * s,
        saturation_mul=1.0 - 0.12 * s,
        exposure_add=0.0,
        shadow_lift=0.0,
        contrast_mul=1.0,
    )


# --------------------------------------------------------------------------- #
# Vignette + haze + heat haze
# --------------------------------------------------------------------------- #

def _vignette(img: np.ndarray, strength: float) -> np.ndarray:
    strength = _clamp(strength, 0.0, 0.85, 0.0)
    if strength <= 0.001:
        return img
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    nx = (xx - cx) / max(cx, 1e-3)
    ny = (yy - cy) / max(cy, 1e-3)
    r = np.sqrt(nx * nx + ny * ny)
    mask = np.clip(1.0 - strength * np.power(r, 1.35), 0.0, 1.0)[..., None]
    return np.clip(img.astype(np.float32) * mask, 0, 255).astype(np.uint8)


def _haze(img: np.ndarray, strength: float, color_bgr: Tuple[float, float, float]) -> np.ndarray:
    strength = _clamp(strength, 0.0, 1.0, 0.0)
    if strength <= 0.005:
        return img
    h, w = img.shape[:2]
    veil = np.full((h, w, 3), list(color_bgr), dtype=np.float32)
    f = img.astype(np.float32)
    out = f * (1.0 - strength) + veil * strength
    if strength > 0.25:
        k = max(1, int(2 * round(strength * 4) + 1))
        out = cv2.GaussianBlur(out, (k, k), sigmaX=0.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def _heat_haze(img: np.ndarray, strength: float, frame_index: int) -> np.ndarray:
    strength = _clamp(strength, 0.0, 1.0, 0.0)
    if strength <= 0.005:
        return img
    h, w = img.shape[:2]
    band_top = int(h * 0.55)
    if band_top >= h - 2:
        return img
    band = img[band_top:h].copy()
    bh = band.shape[0]
    yy = np.arange(bh, dtype=np.float32)
    phase = frame_index * 0.18
    amp = 1.5 + 4.5 * strength
    shifts = (np.sin(yy * 0.07 + phase) * amp).astype(np.int32)
    rolled = np.empty_like(band)
    for i in range(bh):
        rolled[i] = np.roll(band[i], int(shifts[i]), axis=0)
    out = img.copy()
    out[band_top:h] = rolled
    return out


# --------------------------------------------------------------------------- #
# Particles (rain, snow, hail, dust, ash) + flashes
# --------------------------------------------------------------------------- #

_PARTICLE_PROFILES: Dict[str, Dict[str, Any]] = {
    "rain": {
        "n_per_megapixel": 420,
        "len": (12, 48),
        "thickness": 1,
        "shade": (160, 255),
        "angle_rad": (0.35, 0.65),  # downward right (radians from +x axis)
        "blur": (0.8, 1.6),
        "blend": "screen",
        "alpha": 0.55,
    },
    "snow": {
        "n_per_megapixel": 320,
        "len": (1, 2),
        "thickness": 2,
        "shade": (215, 255),
        "angle_rad": (0.50, 0.50),
        "blur": (1.4, 1.4),
        "blend": "screen",
        "alpha": 0.85,
        "is_dot": True,
    },
    "hail": {
        "n_per_megapixel": 180,
        "len": (3, 7),
        "thickness": 2,
        "shade": (220, 255),
        "angle_rad": (0.45, 0.55),
        "blur": (0.6, 0.6),
        "blend": "screen",
        "alpha": 0.95,
    },
    "dust": {
        "n_per_megapixel": 600,
        "len": (1, 2),
        "thickness": 1,
        "shade": (110, 165),  # warm-tan dots when combined with haze
        "angle_rad": (0.10, 0.30),
        "blur": (1.0, 1.0),
        "blend": "screen",
        "alpha": 0.55,
        "is_dot": True,
    },
    "ash": {
        "n_per_megapixel": 250,
        "len": (1, 2),
        "thickness": 2,
        "shade": (170, 210),
        "angle_rad": (0.55, 0.55),
        "blur": (1.6, 1.6),
        "blend": "screen",
        "alpha": 0.7,
        "is_dot": True,
    },
}


def _particle_layer(
    h: int,
    w: int,
    *,
    kind: str,
    intensity: float,
    wind: float,
    rng: np.random.Generator,
    frame_shift: int,
) -> Optional[np.ndarray]:
    """Return a BGR particle layer (0..255) or None when no particles."""

    profile = _PARTICLE_PROFILES.get(kind)
    if profile is None:
        return None
    intensity = _clamp(intensity, 0.0, 1.0, 0.0)
    if intensity <= 0.02:
        return None

    layer = np.zeros((h, w), dtype=np.uint8)
    scale = (h * w) / float(1920 * 1080)
    n = int(profile["n_per_megapixel"] * intensity * scale)
    n = max(40, min(n, 8000))

    lo_len, hi_len = profile["len"]
    lo_a, hi_a = profile["angle_rad"]
    lo_s, hi_s = profile["shade"]
    is_dot = bool(profile.get("is_dot", False))

    wind = float(np.clip(wind, -1.0, 1.0))
    angle_bias = wind * 0.4

    xs = rng.integers(0, w, size=n)
    ys = rng.integers(0, h, size=n)
    lengths = rng.integers(int(lo_len), int(hi_len) + 1, size=n)
    angles = rng.uniform(lo_a, hi_a, size=n) + angle_bias
    shades = rng.integers(int(lo_s), int(hi_s) + 1, size=n)

    if is_dot:
        for i in range(n):
            cv2.circle(
                layer,
                (int(xs[i]), int(ys[i])),
                int(profile["thickness"]),
                int(shades[i]),
                -1,
                cv2.LINE_AA,
            )
    else:
        for i in range(n):
            x1 = int(xs[i])
            y1 = int(ys[i])
            length = int(lengths[i])
            ang = float(angles[i])
            x2 = int(np.clip(x1 + length * np.cos(ang), 0, w - 1))
            y2 = int(np.clip(y1 + length * np.sin(ang), 0, h - 1))
            cv2.line(layer, (x1, y1), (x2, y2), int(shades[i]), int(profile["thickness"]), cv2.LINE_AA)

    bx, by = profile["blur"]
    layer = cv2.GaussianBlur(layer, (0, 0), sigmaX=float(bx), sigmaY=float(by))
    layer = np.roll(layer, int(frame_shift) % max(h, 1), axis=0)
    if abs(wind) > 0.05:
        layer = np.roll(layer, int(frame_shift * wind * 0.8) % max(w, 1), axis=1)
    return cv2.merge([layer, layer, layer])


def _build_lightning_curve(
    n_frames: int,
    fps: float,
    rng: np.random.Generator,
    rate_per_min: float,
) -> np.ndarray:
    curve = np.zeros(max(n_frames, 1), dtype=np.float32)
    if n_frames <= 0 or fps <= 0 or rate_per_min <= 0.05:
        return curve
    secs_per_strike = 60.0 / float(rate_per_min)
    avg_gap = max(0.5, secs_per_strike) * fps
    idx = int(rng.uniform(0, max(1.0, fps)))
    strengths = (0.22, 0.14, 0.07)
    while idx < n_frames:
        idx += int(rng.uniform(avg_gap * 0.7, avg_gap * 1.6))
        if idx >= n_frames:
            break
        for j, s in enumerate(strengths):
            k = idx + j
            if k < n_frames:
                curve[k] = max(curve[k], s)
        idx += len(strengths)
    return curve


def _lightning_burst_start_frames(curve: np.ndarray) -> List[int]:
    """First frame index of each triple-strike group (matches visual lightning)."""

    if curve is None or curve.size == 0:
        return []
    c = curve.astype(np.float32)
    out: List[int] = []
    for i in range(int(c.shape[0])):
        v = float(c[i])
        prev = float(c[i - 1]) if i > 0 else 0.0
        if v >= 0.18 and prev < 0.06:
            out.append(i)
    return out


def _flash(img: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0.0:
        return img
    flash_color = np.array([[[235.0, 245.0, 255.0]]], dtype=np.float32)
    f = img.astype(np.float32)
    return np.clip(f * (1.0 - strength) + flash_color * strength, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Resolve params (back-compat layer between old keys and new knobs)
# --------------------------------------------------------------------------- #

_GRADE_PRESET_KNOBS: Dict[str, Dict[str, Any]] = {
    "battlefield": {
        "tint_bgr": (70.0, 35.0, 18.0),
        "tint_strength": 0.30,
        "saturation_mul": 0.78,
        "exposure_add": -0.04,
        "shadow_lift": 0.05,
        "contrast_mul": 1.09,
    },
    "neutral": {
        "tint_bgr": (40.0, 30.0, 20.0),
        "tint_strength": 0.12,
        "saturation_mul": 0.88,
        "exposure_add": 0.0,
        "shadow_lift": 0.0,
        "contrast_mul": 1.0,
    },
}


def _resolve_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize old + new param keys into the renderer's internal knob dict."""

    p = dict(params or {})

    preset = str(p.get("grade_preset") or "").strip().lower()
    base = dict(_GRADE_PRESET_KNOBS.get(preset, {}))
    if not base and "tint_bgr" not in p:
        base = dict(_GRADE_PRESET_KNOBS["neutral"])
    base.update({k: v for k, v in p.items() if v is not None})

    grade_strength = _clamp(p.get("grade_strength", 1.0), 0.0, 1.5, 1.0)

    knobs: Dict[str, Any] = {
        "tint_bgr": _as_bgr(base.get("tint_bgr"), (40.0, 30.0, 20.0)),
        "tint_strength": _clamp(base.get("tint_strength", 0.12), 0.0, 1.0, 0.12) * grade_strength,
        "saturation_mul": _clamp(base.get("saturation_mul", 1.0), 0.0, 2.0, 1.0),
        "exposure_add": _clamp(base.get("exposure_add", 0.0), -0.5, 0.5, 0.0),
        "shadow_lift": _clamp(base.get("shadow_lift", 0.0), 0.0, 0.5, 0.0),
        "contrast_mul": _clamp(base.get("contrast_mul", 1.0), 0.5, 1.6, 1.0),
    }

    particle_kind = str(p.get("particle_kind") or "").strip().lower()
    if not particle_kind:
        if bool(p.get("rain", False)):
            particle_kind = "rain"
        else:
            particle_kind = "none"
    particle_intensity = _clamp(
        p.get("particle_intensity", p.get("rain_intensity", 0.55)), 0.0, 1.0, 0.55
    )
    knobs["particle_kind"] = particle_kind if particle_kind in _PARTICLE_PROFILES else "none"
    knobs["particle_intensity"] = particle_intensity if knobs["particle_kind"] != "none" else 0.0
    knobs["particle_wind"] = _clamp(p.get("particle_wind", 0.0), -1.0, 1.0, 0.0)
    knobs["particle_speed"] = _clamp(p.get("particle_speed", 1.0), 0.1, 4.0, 1.0)

    flash_kind = str(p.get("flash_kind") or "").strip().lower()
    if not flash_kind:
        flash_kind = "lightning" if bool(p.get("lightning", False)) else "none"
    knobs["flash_kind"] = flash_kind if flash_kind == "lightning" else "none"
    knobs["flash_rate_per_min"] = _clamp(p.get("flash_rate_per_min", 18.0), 0.0, 60.0, 18.0)
    knobs["flash_strength"] = _clamp(p.get("flash_strength", 1.0), 0.0, 1.0, 1.0)

    knobs["haze_strength"] = _clamp(p.get("haze_strength", 0.0), 0.0, 1.0, 0.0)
    knobs["haze_color_bgr"] = _as_bgr(p.get("haze_color_bgr"), (180.0, 180.0, 180.0))

    knobs["heat_haze"] = _clamp(p.get("heat_haze", 0.0), 0.0, 1.0, 0.0)
    knobs["vignette"] = _clamp(p.get("vignette", 0.35), 0.0, 0.85, 0.35)

    knobs["mix_rain_audio"] = bool(p.get("mix_rain_audio", knobs["particle_kind"] == "rain"))
    audio_bed = str(p.get("audio_bed") or "").strip().lower()
    if not audio_bed:
        if knobs["particle_kind"] == "rain":
            audio_bed = "rain"
        elif knobs["particle_kind"] in {"snow", "dust", "ash", "hail"} or knobs["haze_strength"] > 0.2:
            audio_bed = "wind"
        else:
            audio_bed = "none"
    knobs["audio_bed"] = audio_bed if audio_bed in {"rain", "wind", "none"} else "none"

    default_mix_thunder = (
        knobs["flash_kind"] == "lightning"
        and knobs["audio_bed"] in {"rain", "wind"}
        and knobs["mix_rain_audio"]
    )
    knobs["mix_thunder_audio"] = bool(p.get("mix_thunder_audio", default_mix_thunder))

    return knobs


# --------------------------------------------------------------------------- #
# Frame processing
# --------------------------------------------------------------------------- #

def process_frame(
    bgr: np.ndarray,
    *,
    frame_index: int,
    total_frames: int,
    fps: float,
    params: Dict[str, Any],
    rng: np.random.Generator,
    lightning_curve: Optional[np.ndarray] = None,
    knobs: Optional[Dict[str, Any]] = None,
) -> np.ndarray:
    k = knobs if knobs is not None else _resolve_params(params)

    out = apply_generic_grade(
        bgr,
        tint_bgr=k["tint_bgr"],
        tint_strength=k["tint_strength"],
        saturation_mul=k["saturation_mul"],
        exposure_add=k["exposure_add"],
        shadow_lift=k["shadow_lift"],
        contrast_mul=k["contrast_mul"],
    )

    if k["haze_strength"] > 0.005:
        out = _haze(out, k["haze_strength"], k["haze_color_bgr"])

    if k["particle_kind"] != "none" and k["particle_intensity"] > 0.02:
        h, w = out.shape[:2]
        layer = _particle_layer(
            h,
            w,
            kind=k["particle_kind"],
            intensity=k["particle_intensity"],
            wind=k["particle_wind"],
            rng=rng,
            frame_shift=int(frame_index * 3 * k["particle_speed"]) + 17,
        )
        if layer is not None:
            layer_f = layer.astype(np.float32) / 255.0
            base_f = out.astype(np.float32) / 255.0
            alpha = float(_PARTICLE_PROFILES[k["particle_kind"]].get("alpha", 0.55))
            screened = 1.0 - (1.0 - base_f) * (1.0 - layer_f * alpha * k["particle_intensity"])
            out = np.clip(screened * 255.0, 0, 255).astype(np.uint8)

    if k["flash_kind"] == "lightning" and lightning_curve is not None:
        ls = float(lightning_curve[frame_index]) if 0 <= frame_index < len(lightning_curve) else 0.0
        if ls > 0.0:
            out = _flash(out, ls * k["flash_strength"])

    if k["heat_haze"] > 0.005:
        out = _heat_haze(out, k["heat_haze"], frame_index)

    out = _vignette(out, k["vignette"])
    return out


def apply_atmosphere_to_frames(
    frame_files: List[Path],
    output_dir: Path,
    params: Dict[str, Any],
    fps: float,
    update_display: Optional[Callable[[str, float, str], None]] = None,
    seed: int = 42,
) -> Tuple[List[Path], Dict[str, Any]]:
    """Write processed frames to ``output_dir`` preserving filenames."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    knobs = _resolve_params(params)
    n = len(frame_files)
    lightning_curve = None
    if knobs["flash_kind"] == "lightning":
        lightning_curve = _build_lightning_curve(n, fps, rng, knobs["flash_rate_per_min"])

    burst_frames: List[int] = []
    if lightning_curve is not None:
        burst_frames = _lightning_burst_start_frames(lightning_curve)

    notes: Dict[str, Any] = {
        "particle_kind": knobs["particle_kind"],
        "particle_intensity": round(knobs["particle_intensity"], 3),
        "flash_kind": knobs["flash_kind"],
        "haze_strength": round(knobs["haze_strength"], 3),
        "tint_strength": round(knobs["tint_strength"], 3),
        "saturation_mul": round(knobs["saturation_mul"], 3),
        "audio_bed": knobs["audio_bed"],
        "mix_rain_audio": knobs["mix_rain_audio"],
        "mix_thunder_audio": knobs["mix_thunder_audio"],
        "lightning_burst_frames": burst_frames,
        "atmosphere_fps": float(fps),
        "atmosphere_seed": int(seed),
    }

    out_paths: List[Path] = []
    for idx, fp in enumerate(frame_files):
        img = cv2.imread(str(fp))
        if img is None:
            logger.warning("Skipping unreadable frame: %s", fp)
            continue
        processed = process_frame(
            img,
            frame_index=idx,
            total_frames=n,
            fps=fps,
            params=params,
            rng=rng,
            lightning_curve=lightning_curve,
            knobs=knobs,
        )
        outp = output_dir / fp.name
        cv2.imwrite(str(outp), processed)
        out_paths.append(outp)

        if update_display and (idx + 1) % max(1, n // 20) == 0:
            update_display(
                "Atmosphere overlay",
                0.25 + 0.55 * (idx + 1) / max(n, 1),
                f"Frame {idx + 1}/{n}",
            )

    return out_paths, notes


# --------------------------------------------------------------------------- #
# Audio bed (rain hiss / wind low-end) under original audio
# --------------------------------------------------------------------------- #


def _probe_duration_sec(video_path: str) -> float:
    import subprocess

    try:
        r = subprocess.run(
            [
                _ffprobe_exe(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        return max(0.12, float(r.stdout.strip()))
    except Exception:
        return 30.0


def _one_thunder_burst(num_samples: int, sample_rate: int, rng: np.random.Generator) -> np.ndarray:
    buf = max(num_samples + 4096, 2048)
    white = rng.standard_normal(buf).astype(np.float32)
    brown = np.cumsum(white)[:num_samples]
    brown /= np.max(np.abs(brown)) + 1e-8
    k = max(16, sample_rate // 320)
    kernel = np.ones(k, dtype=np.float32) / float(k)
    smooth = np.convolve(brown, kernel, mode="same")
    t = np.arange(num_samples, dtype=np.float32) / float(sample_rate)
    decay = np.exp(-t * float(rng.uniform(1.8, 3.2)))
    crack = np.exp(-t * float(rng.uniform(55.0, 110.0))) * float(rng.uniform(0.35, 0.95))
    sig = smooth * (decay + crack)
    sig *= float(rng.uniform(0.14, 0.32))
    return sig.astype(np.float32)


def _synthesize_thunder_mono(
    duration_sec: float,
    sample_rate: int,
    burst_start_times_sec: Sequence[float],
    rng: np.random.Generator,
) -> np.ndarray:
    n = max(int(duration_sec * sample_rate), 1)
    out = np.zeros(n, dtype=np.float32)
    for t0 in burst_start_times_sec:
        try:
            t_sec = float(t0)
        except (TypeError, ValueError):
            continue
        si = int(t_sec * sample_rate)
        if si >= n:
            continue
        rumble_samples = int(sample_rate * float(rng.uniform(0.42, 1.05)))
        rumble_samples = max(rumble_samples, int(sample_rate * 0.08))
        sig = _one_thunder_burst(rumble_samples, sample_rate, rng)
        end = min(si + sig.shape[0], n)
        take = end - si
        out[si:end] += sig[:take]
    peak = float(np.max(np.abs(out)) + 1e-9)
    if peak > 0.95:
        out *= 0.92 / peak
    return out


def _write_wav_mono(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm_i16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm_i16.tobytes())


def _audio_filter_complex(bed_kind: str, *, mix_thunder_track: bool) -> Optional[str]:
    if bed_kind == "rain":
        middle = (
            "[0:a]volume=0.88[a0];"
            "anoisesrc=color=white:sample_rate=48000:amplitude=0.035[rn];"
            "[rn]highpass=f=400,lowpass=f=7800,volume=0.085[rain];"
            "[a0][rain]amix=inputs=2:duration=first:dropout_transition=2[bedmix]"
        )
    elif bed_kind == "wind":
        middle = (
            "[0:a]volume=0.92[a0];"
            "anoisesrc=color=brown:sample_rate=48000:amplitude=0.045[wn];"
            "[wn]highpass=f=80,lowpass=f=900,volume=0.075[wind];"
            "[a0][wind]amix=inputs=2:duration=first:dropout_transition=2[bedmix]"
        )
    else:
        return None

    if mix_thunder_track:
        return (
            middle + ";"
            "[1:a]aresample=48000,volume=0.72[tn];"
            "[bedmix][tn]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    return middle + ";[bedmix]volume=1[aout]"


def mix_rain_under_original_audio(
    video_in: str,
    video_out: str,
    bed_kind: str = "rain",
    *,
    mix_thunder: bool = False,
    lightning_burst_frames: Optional[Sequence[int]] = None,
    fps: float = 30.0,
    thunder_rng_seed: Optional[int] = None,
) -> bool:
    """Mix a synthesized rain or wind bed under existing audio. Best-effort."""

    import subprocess

    inp = Path(video_in)
    if not inp.exists():
        return False

    bed_kind = str(bed_kind or "rain").strip().lower()
    fps_ok = max(float(fps), 1e-3)
    bursts = [int(f) for f in (lightning_burst_frames or []) if int(f) >= 0]
    burst_times_sec = [fi / fps_ok for fi in bursts]
    use_thunder = bool(mix_thunder and burst_times_sec)

    filter_complex = _audio_filter_complex(bed_kind, mix_thunder_track=use_thunder)
    if filter_complex is None:
        return False

    exe = _ffmpeg_exe()
    thunder_path: Optional[Path] = None
    try:
        cmd: List[str]
        if use_thunder:
            fd, tpath = tempfile.mkstemp(suffix=".wav", prefix="thunder_")
            os.close(fd)
            thunder_path = Path(tpath)
            dur = _probe_duration_sec(str(inp)) + 0.25
            sr = 48000
            rng = np.random.default_rng(int(thunder_rng_seed if thunder_rng_seed is not None else 42))
            samples = _synthesize_thunder_mono(dur, sr, burst_times_sec, rng)
            _write_wav_mono(thunder_path, samples, sr)
            cmd = [
                exe,
                "-y",
                "-i",
                str(inp),
                "-i",
                str(thunder_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(video_out),
            ]
        else:
            cmd = [
                exe,
                "-y",
                "-i",
                str(inp),
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(video_out),
            ]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=max(120, int(inp.stat().st_size / (1024 * 1024)) * 30),
        )
        return Path(video_out).exists()
    except Exception as exc:
        logger.warning("Audio bed mix (%s, thunder=%s) failed: %s", bed_kind, use_thunder, exc)
        return False
    finally:
        if thunder_path is not None:
            try:
                thunder_path.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "apply_atmosphere_to_frames",
    "mix_rain_under_original_audio",
    "video_has_audio_stream",
    "process_frame",
    "apply_generic_grade",
    "apply_battlefield_grade",
    "apply_neutral_cool_grade",
]
