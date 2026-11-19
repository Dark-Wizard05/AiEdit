"""ASS karaoke subtitles — one Dialogue per sentence with \\k tags."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple


def _ass_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _centiseconds(ms: float) -> int:
    return max(1, int(round(float(ms) / 10.0)))


def build_sentence_karaoke_text(
    sentence: str,
    word_boundaries: Sequence[Dict[str, Any]],
    *,
    word_cursor: int,
) -> Tuple[str, int]:
    """Build ASS text with \\k tags for one sentence; return (ass_text, new_cursor)."""

    words = sentence.split()
    if not words:
        return sentence, word_cursor

    chunks: List[str] = []
    cursor = word_cursor
    for word in words:
        clean = re.sub(r"[^\w$\-']+", "", word)
        matched = None
        for j in range(cursor, min(cursor + 3, len(word_boundaries))):
            btext = str(word_boundaries[j].get("text") or "").strip()
            if not btext:
                continue
            if clean.lower().startswith(btext.lower()) or btext.lower() in clean.lower():
                matched = word_boundaries[j]
                cursor = j + 1
                break
        if matched:
            k = _centiseconds(matched.get("duration_ms") or 100)
            chunks.append(f"{{\\k{k}}}{word}")
        else:
            chunks.append(f"{{\\k25}}{word}")
    return " ".join(chunks), cursor


def build_ass_subtitles(
    scheduled_lines: Sequence[Dict[str, Any]],
    *,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """Return full ASS document with top-center karaoke (one Dialogue per sentence)."""

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Commentary,Arial,52,&H0000FFFF&,&H00FFFFFF&,&H00000000&,&H80000000&,-1,0,0,0,100,100,0,0,3,3,0,8,40,40,72,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogues: List[str] = []

    for ln in scheduled_lines:
        text = str(ln.get("text") or "").strip()
        if not text:
            continue
        start_sec = float(ln.get("start_sec") or ln.get("start") or 0.0)
        boundaries = list(ln.get("word_boundaries") or [])
        sentences = split_sentences(text)
        if not sentences:
            continue

        cursor = 0
        cursor_ms = 0.0
        for sent in sentences:
            karaoke, cursor = build_sentence_karaoke_text(sent, boundaries, word_cursor=cursor)
            sent_words = sent.split()
            sent_duration_ms = 0.0
            for w in sent_words:
                if cursor <= len(boundaries):
                    idx = min(cursor - 1, len(boundaries) - 1)
                    if idx >= 0 and boundaries[idx].get("text", "").lower() in w.lower():
                        sent_duration_ms += float(boundaries[idx].get("duration_ms") or 250)
                    else:
                        sent_duration_ms += 250.0
                else:
                    sent_duration_ms += 250.0
            if sent_duration_ms <= 0:
                sent_duration_ms = max(800.0, len(sent_words) * 280.0)

            sent_start = start_sec + cursor_ms / 1000.0
            sent_end = sent_start + sent_duration_ms / 1000.0
            cursor_ms += sent_duration_ms

            line_text = f"{{\\an8\\q2}}{karaoke}"
            dialogues.append(
                f"Dialogue: 0,{_ass_time(sent_start)},{_ass_time(sent_end)},Commentary,,0,0,0,,{line_text}"
            )

    return header + "\n".join(dialogues) + "\n"


def count_dialogue_lines(ass_content: str) -> int:
    return sum(1 for ln in ass_content.splitlines() if ln.startswith("Dialogue:"))
