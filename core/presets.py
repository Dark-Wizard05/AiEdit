"""
Phase 4: hardware presets.

Pick sensible defaults for "fast / balanced / quality" based on what the
machine can actually do. Used by the unified engine, the API, and (later)
the Streamlit UI to avoid one fragile max-everything setting.

Three named presets:

- ``fast``:     CPU-friendly, no SAM, no diffusion, fewer frames per second
- ``balanced``: SAM if available, OpenCV inpaint, full FPS
- ``quality``:  SAM, optional diffusion, full FPS

``recommend()`` chooses one based on detected GPU/VRAM. We do not import torch
at module load to keep the import cheap; detection happens on demand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Preset:
    name: str
    device: str
    use_sam: bool
    use_diffusion: bool
    fps: int
    grounding_model: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


PRESETS: Dict[str, Preset] = {
    "fast": Preset(
        name="fast",
        device="cpu",
        use_sam=False,
        use_diffusion=False,
        fps=15,
        grounding_model="IDEA-Research/grounding-dino-tiny",
    ),
    "balanced": Preset(
        name="balanced",
        device="cuda",
        use_sam=True,
        use_diffusion=False,
        fps=30,
        grounding_model="IDEA-Research/grounding-dino-tiny",
    ),
    "quality": Preset(
        name="quality",
        device="cuda",
        use_sam=True,
        use_diffusion=True,
        fps=30,
        grounding_model="IDEA-Research/grounding-dino-base",
    ),
}


def get_preset(name: str) -> Preset:
    if name not in PRESETS:
        raise KeyError(f"unknown preset '{name}'. Choose from: {sorted(PRESETS)}")
    return PRESETS[name]


def detect_hardware() -> Dict[str, object]:
    """Return a small dict describing the local environment.

    Never raises; if torch isn't installed, returns CPU-only info.
    """

    info: Dict[str, object] = {
        "device": "cpu",
        "cuda": False,
        "vram_gb": 0.0,
        "gpu_name": "",
    }
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            info["device"] = "cuda"
            info["cuda"] = True
            try:
                props = torch.cuda.get_device_properties(0)
                info["gpu_name"] = props.name
                info["vram_gb"] = round(props.total_memory / (1024**3), 1)
            except Exception:
                pass
    except Exception:
        pass
    return info


def recommend(hardware: Optional[Dict[str, object]] = None) -> Preset:
    """Pick a preset for current hardware.

    - No CUDA -> fast
    - <12 GB VRAM -> balanced
    - >=12 GB VRAM -> quality
    """

    info = hardware or detect_hardware()
    if not info.get("cuda"):
        return PRESETS["fast"]
    vram = float(info.get("vram_gb") or 0.0)
    if vram >= 12.0:
        return PRESETS["quality"]
    return PRESETS["balanced"]
