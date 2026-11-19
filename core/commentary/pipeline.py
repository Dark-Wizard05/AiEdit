"""Commentary v2 pipeline orchestrator."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.commentary.analyze import analyze_video
from core.commentary.config import CommentaryJobConfig, CommentaryJobState
from core.commentary.job_store import load_job_state, save_job_state, update_job
from core.commentary.music import music_credit_string, resolve_music_track
from core.commentary.mux import mux_export
from core.commentary.schedule import fit_schedule
from core.commentary.script_service import CommentaryScriptService, validate_script
from core.commentary.subtitles import build_ass_subtitles
from core.commentary.timeline import prepare_timeline_for_script
from core.commentary.tts import render_tts
from core.storage import StorageBackend, get_storage

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

ProgressFn = Optional[Callable[[str, float, str], None]]


class CommentaryPipeline:
    def __init__(self, storage: Optional[StorageBackend] = None) -> None:
        self.storage = storage or get_storage()
        self.script_service = CommentaryScriptService()

    def _progress(
        self,
        state: CommentaryJobState,
        stage: str,
        progress: float,
        message: str,
    ) -> None:
        state.stage = stage  # type: ignore[assignment]
        state.progress = progress
        state.message = message
        save_job_state(state, self.storage)

    def run(
        self,
        config: CommentaryJobConfig,
        *,
        progress_cb: ProgressFn = None,
    ) -> CommentaryJobState:
        state = load_job_state(config.job_id, self.storage) or CommentaryJobState(job_id=config.job_id)
        work_dir = Path(tempfile.mkdtemp(prefix=f"aiedit_commentary_{config.job_id}_"))

        def emit(stage: str, pct: float, msg: str) -> None:
            self._progress(state, stage, pct, msg)
            if progress_cb:
                progress_cb(stage, pct, msg)

        try:
            emit("analyzing", 0.05, "Analyzing clip frames")
            analysis = analyze_video(config, self.storage, work_dir, progress=emit)
            state.timeline_key = analysis["timeline_key"]
            timeline = analysis["timeline"]
            script_timeline = prepare_timeline_for_script(timeline)
            duration = float(analysis["duration_sec"])
            video_path = analysis["video_path"]

            emit("writing_script", 0.35, "Writing play-by-play script")
            lines = self.script_service.generate(
                script_timeline,
                duration_sec=duration,
                player_name=config.player_name,
                video_context=config.video_context or config.game_title or None,
                tone=config.tone,
                must_include_joke=config.must_include_joke,
                must_sync_timestamp=config.must_sync_timestamp,
                seed=config.seed,
            )

            emit("validating_script", 0.42, "Validating script against timeline")
            ok, errs = validate_script(
                lines,
                script_timeline,
                duration_sec=duration,
                extra_entities=[config.player_name] if config.player_name else None,
                tone=config.tone,
            )
            if not ok:
                logger.warning("Script validation notes: %s", errs)

            script_payload = {"lines": lines, "validation_errors": errs if not ok else []}
            script_key = self.storage.job_key(config.job_id, "script.json")
            self.storage.write_json(script_key, script_payload)
            state.script_key = script_key

            emit("rendering_tts", 0.50, "Rendering voice-over")
            audio_dir = work_dir / "audio"
            rendered = render_tts(
                lines,
                audio_dir,
                voice=config.voice,
                tone=config.tone,
                progress=emit,
            )

            emit("scheduling", 0.68, "Scheduling audio to gameplay")
            scheduled = fit_schedule(rendered, duration_sec=duration)

            emit("building_subtitles", 0.78, "Building karaoke subtitles")
            ass_content = build_ass_subtitles(scheduled)
            subs_key = self.storage.job_key(config.job_id, "subtitles.ass")
            self.storage.write_text(subs_key, ass_content)
            state.subtitles_key = subs_key

            music_path: Optional[str] = None
            music_credit: Optional[str] = None
            if config.music_enabled and config.music_track_id:
                track = resolve_music_track(config.music_track_id, self.storage)
                if track:
                    key = str(track.get("storage_key") or "")
                    local = self.storage.local_path(key)
                    if local.is_file():
                        music_path = str(local)
                        music_credit = music_credit_string(track)
                    else:
                        logger.info("Music track key missing on disk: %s", key)

            emit("muxing", 0.88, "Muxing export")
            out_key = self.storage.job_key(config.job_id, "output.mp4")
            out_path = self.storage.local_path(out_key)
            ok_mux = mux_export(
                video_path,
                scheduled,
                str(out_path),
                ass_path=str(self.storage.local_path(subs_key)),
                music_path=music_path,
                music_volume=config.music_volume,
                mute_game_audio=config.mute_game_audio,
            )
            if not ok_mux:
                raise RuntimeError("mux export failed")

            state.output_video_key = out_key
            state.music_credit = music_credit
            state.artifacts["outputVideoUrl"] = self.storage.public_url(out_key)
            state.artifacts["subtitlesUrl"] = self.storage.public_url(subs_key)
            state.artifacts["scriptJson"] = script_payload
            state.stage = "done"
            state.progress = 1.0
            state.message = "Commentary export ready"
            save_job_state(state, self.storage)
            logger.info("Commentary pipeline complete job=%s lines=%s", config.job_id, len(lines))
            return state
        except Exception as exc:  # noqa: BLE001
            state.stage = "error"
            state.error = str(exc)
            state.message = "Commentary pipeline failed"
            save_job_state(state, self.storage)
            logger.exception("Commentary pipeline failed job=%s", config.job_id)
            raise
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


def run_commentary_job(
    config: CommentaryJobConfig,
    *,
    storage: Optional[StorageBackend] = None,
    progress_cb: ProgressFn = None,
) -> CommentaryJobState:
    return CommentaryPipeline(storage=storage).run(config, progress_cb=progress_cb)
