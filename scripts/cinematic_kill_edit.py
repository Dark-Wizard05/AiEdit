"""One-off cinematic CS2 kill edit: push-in zoom + slow-mo + Gobble Glitch sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

INPUT = Path(r"c:\Users\adity\Videos\Counter-Strike 2 - 2026-07-04 8-36-55 PM - Double kill.mp4")
MUSIC = Path(r"c:\Users\adity\Downloads\AiEdit\downloads\gobble_glitch.mp3")
OUTPUT = Path(r"c:\Users\adity\Downloads\AiEdit\downloads\cs2_cinematic_kill.mp4")

# Kill sequence in source footage (seconds)
SRC_START = 2.15
SRC_RAMP_END = 3.35  # slow-mo begins here (enemy hit / falling)
SRC_END = 5.05

# Focal point on enemy (normalized 0-1)
FOCUS_X = 0.50
FOCUS_Y = 0.42

OUT_W, OUT_H = 1080, 1920
OUT_FPS = 30
SLOW_FACTOR = 0.18  # heavy slow-mo, still feels alive

# Music: align ~3s glitch hit with slow-mo start in the edit
MUSIC_OFFSET = 2.05


def lerp(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


def ease_in_out(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def crop_zoom(frame: np.ndarray, zoom: float, fx: float, fy: float) -> np.ndarray:
    h, w = frame.shape[:2]
    zoom = max(1.0, zoom)
    cw, ch = int(w / zoom), int(h / zoom)
    cx = int(fx * w - cw / 2)
    cy = int(fy * h - ch / 2)
    cx = max(0, min(w - cw, cx))
    cy = max(0, min(h - ch, cy))
    cropped = frame[cy : cy + ch, cx : cx + cw]
    return cv2.resize(cropped, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)


def letterbox_crop(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    target_ratio = OUT_W / OUT_H
    src_ratio = w / h
    if src_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        frame = frame[:, x0 : x0 + new_w]
    else:
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        frame = frame[y0 : y0 + new_h, :]
    return cv2.resize(frame, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)


def build_video() -> tuple[Path, float]:
    cap = cv2.VideoCapture(str(INPUT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 60.0

    ramp_dur = SRC_RAMP_END - SRC_START
    slow_src_dur = SRC_END - SRC_RAMP_END
    out_dur = ramp_dur + slow_src_dur / SLOW_FACTOR

    tmp_video = OUTPUT.with_suffix(".silent.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(tmp_video), fourcc, OUT_FPS, (OUT_W, OUT_H))

    t_out = 0.0
    while t_out < out_dur:
        if t_out < ramp_dur:
            src_t = SRC_START + t_out
            prog = ease_in_out(t_out / max(ramp_dur, 1e-6))
            zoom = lerp(1.0, 1.35, prog)
        else:
            slow_t = t_out - ramp_dur
            src_t = SRC_RAMP_END + slow_t * SLOW_FACTOR
            prog = ease_in_out(min(1.0, slow_t / (slow_src_dur / SLOW_FACTOR)))
            zoom = lerp(1.35, 2.75, prog)

        cap.set(cv2.CAP_PROP_POS_MSEC, src_t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            break
        frame = letterbox_crop(frame)
        frame = crop_zoom(frame, zoom, FOCUS_X, FOCUS_Y)
        writer.write(frame)
        t_out += 1.0 / OUT_FPS

    writer.release()
    cap.release()
    return tmp_video, out_dur


def mux_audio(silent_video: Path, duration: float) -> None:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff,
        "-y",
        "-i",
        str(silent_video),
        "-ss",
        str(MUSIC_OFFSET),
        "-i",
        str(MUSIC),
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        "[1:a]volume=0.95,afade=t=in:st=0:d=0.15,afade=t=out:st="
        f"{max(0.0, duration - 0.6):.3f}:d=0.6[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(OUTPUT),
    ]
    subprocess.run(cmd, check=True)
    silent_video.unlink(missing_ok=True)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    silent, duration = build_video()
    mux_audio(silent, duration)
    print(f"Wrote {OUTPUT} ({duration:.1f}s)")


if __name__ == "__main__":
    main()
