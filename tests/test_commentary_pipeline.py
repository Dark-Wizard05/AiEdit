"""Unit tests for Commentary validator, subtitles, scheduler, and timeline."""

from __future__ import annotations

import unittest

from core.commentary.schedule import fit_schedule
from core.commentary.script_service import is_score_or_timer_only, validate_script
from core.commentary.subtitles import build_ass_subtitles, count_dialogue_lines, split_sentences
from core.commentary.timeline import fill_scene_beats, prepare_timeline_for_script
from core.commentary.tts import style_commentary_text


SAMPLE_TIMELINE = [
    {
        "timestamp_sec": 5.0,
        "events": ["On-screen: Alex crosses the finish line", "Score 2-1"],
        "confidence": "high",
        "notes": "on-screen detail visible",
    },
    {
        "timestamp_sec": 12.0,
        "events": ["Win banner visible", "Scene beat at 0:12"],
        "confidence": "medium",
        "notes": "scene beat",
    },
]


class TestCommentaryValidator(unittest.TestCase):
    def test_rejects_score_heavy_script(self) -> None:
        lines = [
            {"text": "Score is 4-5", "target_start_sec": 1.0, "emotion": "neutral", "references": []},
            {"text": "Still 4-5 on the board", "target_start_sec": 3.0, "emotion": "neutral", "references": []},
            {"text": "Score reads 4-5 again", "target_start_sec": 5.0, "emotion": "neutral", "references": []},
        ]
        ok, errs = validate_script(lines, SAMPLE_TIMELINE, duration_sec=30.0, tone="hype")
        self.assertFalse(ok)

    def test_is_score_or_timer_only(self) -> None:
        self.assertTrue(is_score_or_timer_only("Score is 4-5"))
        self.assertTrue(is_score_or_timer_only("30 seconds left"))
        self.assertFalse(is_score_or_timer_only("Alex crosses the finish line — what a run!"))

    def test_accepts_humor_driven_script(self) -> None:
        lines = [
            {
                "text": "STOP THE BROADCAST — Alex crosses the finish line! The booth is SCREAMING!",
                "target_start_sec": 1.0,
                "emotion": "hype",
                "references": ["Alex", "finish line"],
            },
            {
                "text": "Win banner visible — someone in the production truck just spilled their coffee.",
                "target_start_sec": 8.0,
                "emotion": "dry",
                "references": ["Win banner visible"],
            },
            {
                "text": "Scene beat at 0:12 — pure chaos, and we're here for all of it!",
                "target_start_sec": 16.0,
                "emotion": "hype",
                "references": ["Scene beat at 0:12"],
            },
            {
                "text": "We sign off with Alex still owning the highlight reel — what a clip!",
                "target_start_sec": 24.0,
                "emotion": "hype",
                "references": ["Alex"],
            },
        ]
        ok, errs = validate_script(lines, SAMPLE_TIMELINE, duration_sec=30.0, tone="hype")
        self.assertTrue(ok, msg=str(errs))


class TestTimelineCoverage(unittest.TestCase):
    def test_fill_scene_beats_for_sparse_video(self) -> None:
        beats = fill_scene_beats([], duration_sec=24.0, target_entries=5)
        self.assertGreaterEqual(len(beats), 3)

    def test_prepare_timeline_caps_score_mentions(self) -> None:
        raw = [
            {"timestamp_sec": 1.0, "events": ["Score 1-0"], "confidence": "high", "notes": ""},
            {"timestamp_sec": 2.0, "events": ["Score 1-0"], "confidence": "high", "notes": ""},
            {"timestamp_sec": 3.0, "events": ["On-screen: big play", "Score 1-0"], "confidence": "high", "notes": ""},
        ]
        prepared = prepare_timeline_for_script(raw)
        score_labels = [
            ev for entry in prepared for ev in entry.get("events", []) if ev.lower().startswith("score")
        ]
        self.assertLessEqual(len(score_labels), 1)


class TestExpressiveTts(unittest.TestCase):
    def test_hype_styling_adds_energy(self) -> None:
        styled = style_commentary_text("Alex scores the goal.", "hype", tone="hype")
        self.assertTrue(styled.endswith("!"))


class TestSubtitleBuilder(unittest.TestCase):
    def test_one_dialogue_per_sentence_with_k_tags(self) -> None:
        scheduled = [
            {
                "text": "Alex strikes! Win banner visible.",
                "start_sec": 5.0,
                "word_boundaries": [
                    {"text": "Alex", "offset_ms": 0, "duration_ms": 400},
                    {"text": "strikes", "offset_ms": 400, "duration_ms": 300},
                    {"text": "Win", "offset_ms": 800, "duration_ms": 250},
                    {"text": "banner", "offset_ms": 1050, "duration_ms": 300},
                    {"text": "visible", "offset_ms": 1350, "duration_ms": 350},
                ],
            }
        ]
        ass = build_ass_subtitles(scheduled)
        sentences = split_sentences(scheduled[0]["text"])
        self.assertEqual(count_dialogue_lines(ass), len(sentences))

    def test_k_tag_pattern_present(self) -> None:
        ass = build_ass_subtitles(
            [
                {
                    "text": "Hello world.",
                    "start_sec": 0.0,
                    "word_boundaries": [
                        {"text": "Hello", "offset_ms": 0, "duration_ms": 200},
                        {"text": "world", "offset_ms": 200, "duration_ms": 300},
                    ],
                }
            ]
        )
        self.assertRegex(ass, r"\\k\d+")


class TestScheduler(unittest.TestCase):
    def test_no_overlaps(self) -> None:
        lines = [
            {"text": "Line one.", "target_start_sec": 0.0, "audio_duration": 2.0},
            {"text": "Line two.", "target_start_sec": 1.0, "audio_duration": 2.5},
            {"text": "Line three.", "target_start_sec": 2.0, "audio_duration": 1.8},
        ]
        scheduled = fit_schedule(lines, duration_sec=20.0)
        for a, b in zip(scheduled, scheduled[1:]):
            self.assertGreaterEqual(b["start_sec"], a["end_sec"] - 0.001)


if __name__ == "__main__":
    unittest.main()
