"""CS2 double-kill edit: full video, variable speed, Gobble Glitch synced to the Short."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import imageio_ffmpeg

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOWNLOADS = _REPO_ROOT / "downloads"

INPUT: Path
MUSIC: Path
OUTPUT: Path

# (source_start_sec, source_end_sec, playback_speed)
# speed 0.25 => 4x slower (1s source lasts 4s)
# speed 4.0 => 4x fast forward
SEGMENTS: list[tuple[float, float, float]] = [
    (0.0, 2.0, 1.0),
    (2.0, 3.0, 0.25),  # first kill (fadeyg)
    (3.0, 4.0, 1.0),
    (4.0, 5.0, 0.25),  # second kill in apartments
    (5.0, 9.0, 1.0),
    (9.0, 20.0, 4.0),  # fast-forward mid-round traversal
    (20.0, 22.0, 1.0),
    (22.0, 23.0, 0.25),  # last kill
    (23.0, 23.701045, 1.0),
]

# Short seconds 3-5 map to ~gobble 15.3s; align that drop with output t=2 (slow-mo start).
MUSIC_OFFSET_SEC = 13.3
MUSIC_VOLUME = 0.92


def ff() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_duration(path: Path) -> float:
    import cv2

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return frames / fps


def output_duration(segments: list[tuple[float, float, float]]) -> float:
    return sum((end - start) / speed for start, end, speed in segments)


def build_video_filter(segments: list[tuple[float, float, float]]) -> str:
    parts: list[str] = []
    labels: list[str] = []
    for i, (start, end, speed) in enumerate(segments):
        pts_expr = "PTS-STARTPTS" if speed == 1.0 else f"(PTS-STARTPTS)/{speed}"
        parts.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts={pts_expr}[v{i}]"
        )
        labels.append(f"[v{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[vout]")
    return ";".join(parts)


def main() -> None:
    global INPUT, MUSIC, OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Source gameplay clip (local path)",
    )
    parser.add_argument(
        "--music",
        type=Path,
        default=_DOWNLOADS / "gobble_glitch.mp3",
        help="Background track under downloads/ by default",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DOWNLOADS / "cs2_double_kill_edit.mp4",
        help="Rendered file under downloads/ by default",
    )
    args = parser.parse_args()
    INPUT, MUSIC, OUTPUT = args.input, args.music, args.output
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(INPUT)
    segments = list(SEGMENTS)
    segments[-1] = (segments[-1][0], duration, segments[-1][2])

    out_dur = output_duration(segments)
    vfilter = build_video_filter(segments)

    cmd = [
        ff(),
        "-y",
        "-i",
        str(INPUT),
        "-ss",
        str(MUSIC_OFFSET_SEC),
        "-i",
        str(MUSIC),
        "-filter_complex",
        vfilter,
        "-map",
        "[vout]",
        "-map",
        "1:a",
        "-t",
        f"{out_dur:.3f}",
        "-af",
        f"volume={MUSIC_VOLUME},afade=t=in:st=0:d=0.12,afade=t=out:st={max(0.0, out_dur - 0.5):.3f}:d=0.5",
        "-c:v",
        "libx264",
        "-crf",
        "17",
        "-preset",
        "medium",
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
    print(f"Source duration: {duration:.3f}s")
    print(f"Output duration: {out_dur:.3f}s")
    print(f"Music offset: {MUSIC_OFFSET_SEC}s (Short ~3s drop lands on first slow-mo)")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
