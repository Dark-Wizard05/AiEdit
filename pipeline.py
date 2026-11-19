"""
Standalone text-focused video pipeline for scripting or CLI-style runs.

Orchestrates frame extraction, EasyOCR detection, text removal/replacement, and
reassemble-to-MP4 using ``utils/video_processor.py``, ``utils/text_detection_sam.py``,
and ``utils/text_removal_overlay.py``.

The Streamlit editor (``app.py``) does **not** import this module; it drives the same
utilities plus object masking, prompt parsing, and export paths directly. Keep this
file for batch text workflows without the UI, or retire it once a unified execution
core exists (see ``docs/CURRENT_STATE_AND_ROADMAP.md`` Phase 1).
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging
from dataclasses import dataclass
import time

# Import centralized logging
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    # Fallback to basic logging if logging_config not available
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)



@dataclass
class PipelineConfig:
    """Configuration for video processing pipeline"""
    device: str = "cpu"  # "cpu" or "cuda"
    fps: int = 30
    max_frames: Optional[int] = None  # Process only first N frames (None = all)
    confidence_threshold: float = 0.5
    use_sam: bool = False  # Use Segment Anything for masks
    inpainting_method: str = "opencv"  # "opencv" or "diffusion"
    output_format: str = "mp4"
    save_intermediate: bool = True  # Save extracted frames and masks
    verbose: bool = True


@dataclass
class PipelineResult:
    """Result of pipeline execution"""
    success: bool
    video_path: str
    frames_dir: str
    detections: List[Dict]
    processing_time: float
    frames_processed: int
    text_replacements: Dict[str, str]
    output_video_path: Optional[str] = None
    error_message: Optional[str] = None


class VideoPipeline:
    """Text-focused extract → OCR → inpaint/overlay → export."""

    def __init__(self, config: PipelineConfig = None):
        self.config = config or PipelineConfig()
        self.detector = None
        self.processor = None
        self.start_time = None
        
        logger.info(f"Pipeline initialized with device: {self.config.device}")
    
    def _load_models(self):
        """Load required ML models"""
        try:
            if self.detector is None:
                from utils.text_detection_sam import TextDetectionSAM
                logger.info("Loading text detection model...")
                self.detector = TextDetectionSAM(device=self.config.device)
                
                if self.config.use_sam:
                    logger.info("Loading SAM model...")
                    self.detector.load_sam_model(model_type='vit_b')
            
            if self.processor is None:
                from utils.text_removal_overlay import TextRemovalAndOverlay
                logger.info("Loading text removal/overlay model...")
                self.processor = TextRemovalAndOverlay(device=self.config.device)
                
                if self.config.inpainting_method == "diffusion":
                    logger.info("Loading inpainting model...")
                    self.processor.load_inpainting_model()
            
            return True
        
        except Exception as e:
            logger.error(f"Error loading models: {str(e)}")
            return False
    
    def extract_frames(self, video_path: str, output_dir: str) -> Tuple[bool, List[Path]]:
        """Return success flag and sorted frame paths under ``output_dir``."""
        try:
            from utils.video_processor import extract_frames
            
            logger.info(f"Extracting frames from {video_path}...")
            success = extract_frames(video_path, output_dir, fps=self.config.fps)
            
            if success:
                frame_files = sorted(Path(output_dir).glob("frame_*.png"))
                
                # Limit frames if specified
                if self.config.max_frames:
                    frame_files = frame_files[:self.config.max_frames]
                
                logger.info(f"[OK] Extracted {len(frame_files)} frames")
                return True, frame_files
            else:
                logger.error("Frame extraction failed")
                return False, []
        
        except Exception as e:
            logger.error(f"Error extracting frames: {str(e)}")
            return False, []
    
    def detect_text_in_frames(self, frame_files: List[Path]) -> Dict[str, Any]:
        """Per-frame OCR; returns ``success``, ``detections``, ``masks``."""
        if not self._load_models():
            return {"success": False, "error": "Failed to load models"}
        
        try:
            detections_all = {}
            masks_all = {}
            
            logger.info(f"Detecting text in {len(frame_files)} frames...")
            
            for idx, frame_path in enumerate(frame_files):
                try:
                    image = cv2.imread(str(frame_path))
                    
                    # Detect text
                    detections = self.detector.detect_text_regions(image)
                    detections_all[str(frame_path)] = detections
                    
                    # Generate masks
                    if detections:
                        masks = self.detector.generate_text_masks(image, detections)
                        masks_all[str(frame_path)] = masks
                    
                    if self.config.verbose and (idx + 1) % max(1, len(frame_files) // 10) == 0:
                        logger.info(f"  Processed {idx + 1}/{len(frame_files)} frames")
                except Exception as e:
                    logger.warning(f"Error processing frame {frame_path}: {str(e)}")
                    continue
            
            total_texts = sum(len(dets) for dets in detections_all.values())
            logger.info(f"[OK] Detected {total_texts} text regions across all frames")
            
            return {
                "success": True,
                "detections": detections_all,
                "masks": masks_all
            }
        
        except Exception as e:
            logger.error(f"Error detecting text: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def replace_text(
        self,
        frame_files: List[Path],
        detections: Dict,
        replacement_text: str,
        output_dir: str,
        style_overrides: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[Path]]:
        """Inpaint each text bbox and overlay ``replacement_text``.

        ``style_overrides`` may set: color, stroke_color, font_size,
        font_weight, align, font_path/font_family. Anything missing falls
        back to a sensible default.
        """
        if not self._load_models():
            return False, []
        
        try:
            logger.info(f"Replacing text with '{replacement_text}'...")
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            processed_frames = []
            ov = dict(style_overrides or {})
            color = tuple(int(c) for c in ov.get("color", (0, 0, 0)))
            stroke_color = tuple(int(c) for c in ov["stroke_color"]) if "stroke_color" in ov else None
            stroke_width = 2 if str(ov.get("font_weight", "")).lower() == "bold" else 1
            try:
                base_font_size = max(6, int(ov.get("font_size", 20)))
            except (TypeError, ValueError):
                base_font_size = 20
            align = str(ov.get("align") or "center").lower()
            if align not in ("left", "center", "right"):
                align = "center"
            font_path = ov.get("font_path") or ov.get("font_family")
            if not isinstance(font_path, str):
                font_path = None

            for idx, frame_path in enumerate(frame_files):
                frame_dets = detections.get(str(frame_path), [])
                
                # Read frame
                image = cv2.imread(str(frame_path))
                result = image.copy()
                
                # Process each detected text region
                for det_idx, detection in enumerate(frame_dets):
                    bbox = detection['bbox']
                    
                    # Create mask for this text
                    mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
                    x1, y1, x2, y2 = bbox
                    mask[y1:y2, x1:x2] = 255
                    
                    # Remove text
                    if self.config.inpainting_method == "diffusion":
                        result = self.processor.remove_text_inpainting(
                            result, mask,
                            prompt="clean background"
                        )
                    else:
                        result = self.processor.remove_text_opencv(result, mask)
                    
                    # Overlay new text
                    result = self.processor.overlay_text(
                        result, replacement_text, bbox,
                        color=color,
                        font_size=base_font_size,
                        stroke_width=stroke_width,
                        stroke_color=stroke_color,
                        align=align,
                        font_path=font_path,
                    )
                
                # Save processed frame
                output_path = output_dir / frame_path.name
                cv2.imwrite(str(output_path), result)
                processed_frames.append(output_path)
                
                if self.config.verbose and (idx + 1) % max(1, len(frame_files) // 10) == 0:
                    logger.info(f"  Processed {idx + 1}/{len(frame_files)} frames")
            
            logger.info(f"[OK] Text replacement complete")
            return True, processed_frames
        
        except Exception as e:
            logger.error(f"Error replacing text: {str(e)}")
            return False, []
    
    def remove_text(
        self, frame_files: List[Path], detections: Dict, output_dir: str
    ) -> Tuple[bool, List[Path]]:
        """Combine text bboxes per frame and inpaint once."""
        if not self._load_models():
            return False, []
        
        try:
            logger.info("Removing text from frames...")
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            processed_frames = []
            
            for idx, frame_path in enumerate(frame_files):
                frame_dets = detections.get(str(frame_path), [])
                
                image = cv2.imread(str(frame_path))
                result = image.copy()
                
                # Create combined mask for all text regions
                mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
                
                for detection in frame_dets:
                    x1, y1, x2, y2 = detection['bbox']
                    mask[y1:y2, x1:x2] = 255
                
                # Remove text if any detected
                if mask.sum() > 0:
                    if self.config.inpainting_method == "diffusion":
                        result = self.processor.remove_text_inpainting(
                            result, mask,
                            prompt="clean, seamless background"
                        )
                    else:
                        result = self.processor.remove_text_opencv(result, mask)
                
                # Save processed frame
                output_path = output_dir / frame_path.name
                cv2.imwrite(str(output_path), result)
                processed_frames.append(output_path)
                
                if self.config.verbose and (idx + 1) % max(1, len(frame_files) // 10) == 0:
                    logger.info(f"  Processed {idx + 1}/{len(frame_files)} frames")
            
            logger.info(f"[OK] Text removal complete")
            return True, processed_frames
        
        except Exception as e:
            logger.error(f"Error removing text: {str(e)}")
            return False, []
    
    def reassemble_video(self, frames_dir: str, output_path: str) -> bool:
        """Write MP4 from numbered frames."""
        try:
            from utils.video_processor import reassemble_frames
            
            logger.info(f"Reassembling video to {output_path}...")
            success = reassemble_frames(frames_dir, output_path, fps=self.config.fps)
            
            if success:
                file_size = Path(output_path).stat().st_size / (1024 * 1024)
                logger.info(f"[OK] Video created: {output_path} ({file_size:.1f} MB)")
            
            return success
        
        except Exception as e:
            logger.error(f"Error reassembling video: {str(e)}")
            return False
    
    def run_text_extraction(self, video_path: str, output_dir: str) -> PipelineResult:
        """Extract frames and detect text."""
        self.start_time = time.time()
        logger.info(f"Starting text extraction pipeline: {video_path}")
        
        try:
            # Create output directories
            output_dir = Path(output_dir)
            frames_dir = output_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract frames
            logger.info("Step 1/2: Extracting frames...")
            success, frame_files = self.extract_frames(video_path, str(frames_dir))
            if not success:
                raise Exception("Frame extraction failed")
            
            # Detect text
            logger.info("Step 2/2: Detecting text...")
            detection_result = self.detect_text_in_frames(frame_files)
            if not detection_result["success"]:
                raise Exception(detection_result.get("error", "Text detection failed"))
            
            detections = detection_result["detections"]
            all_detections = []
            for frame_path, frame_dets in detections.items():
                all_detections.extend(frame_dets)
            
            logger.info(f"Detected {len(all_detections)} text regions in {len(frame_files)} frames")
            
            processing_time = time.time() - self.start_time
            logger.info(f"[OK] Text extraction complete in {processing_time:.1f}s")
            
            return PipelineResult(
                success=True,
                video_path=video_path,
                frames_dir=str(frames_dir),
                detections=all_detections,
                processing_time=processing_time,
                frames_processed=len(frame_files),
                text_replacements={}
            )
        
        except Exception as e:
            processing_time = time.time() - self.start_time
            logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
            
            return PipelineResult(
                success=False,
                video_path=video_path,
                frames_dir=str(output_dir / "frames"),
                detections=[],
                processing_time=processing_time,
                frames_processed=0,
                text_replacements={},
                error_message=str(e)
            )
    
    def _run_full_text_edit_pipeline(
        self,
        video_path: str,
        output_dir: str,
        *,
        replacement_text: Optional[str],
        style_overrides: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """Shared extract → detect → replace or remove → reassemble."""
        self.start_time = time.time()
        mode = "replacement" if replacement_text is not None else "removal"
        logger.info(f"Starting text {mode} pipeline: {video_path}")
        if replacement_text is not None:
            logger.info(f"Replacement text: '{replacement_text}'")

        out = Path(output_dir)
        frames_dir = out / "extracted_frames"
        processed_dir = out / "processed_frames"

        try:
            frames_dir.mkdir(parents=True, exist_ok=True)
            processed_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Step 1/4: Extracting frames...")
            ok, frame_files = self.extract_frames(video_path, str(frames_dir))
            if not ok:
                raise RuntimeError("Frame extraction failed")

            logger.info("Step 2/4: Detecting text...")
            detection_result = self.detect_text_in_frames(frame_files)
            if not detection_result["success"]:
                raise RuntimeError(detection_result.get("error", "Text detection failed"))

            detections = detection_result["detections"]
            all_detections = [d for fds in detections.values() for d in fds]
            logger.info(f"Detected {len(all_detections)} text regions")

            logger.info(f"Step 3/4: {'Replacing' if replacement_text else 'Removing'} text...")
            if replacement_text is not None:
                ok, _ = self.replace_text(
                    frame_files,
                    detections,
                    replacement_text,
                    str(processed_dir),
                    style_overrides=style_overrides,
                )
            else:
                ok, _ = self.remove_text(frame_files, detections, str(processed_dir))
            if not ok:
                raise RuntimeError("Text edit failed")

            logger.info("Step 4/4: Reassembling video...")
            output_video = out / "output.mp4"
            if not self.reassemble_video(str(processed_dir), str(output_video)):
                raise RuntimeError("Video reassembly failed")

            processing_time = time.time() - self.start_time
            logger.info(f"[OK] Text {mode} complete in {processing_time:.1f}s")
            text_replacements = (
                {"old": "original", "new": replacement_text} if replacement_text else {}
            )
            return PipelineResult(
                success=True,
                video_path=video_path,
                frames_dir=str(frames_dir),
                detections=all_detections,
                processing_time=processing_time,
                frames_processed=len(frame_files),
                text_replacements=text_replacements,
                output_video_path=str(output_video),
            )
        except Exception as e:
            processing_time = time.time() - self.start_time
            logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
            return PipelineResult(
                success=False,
                video_path=video_path,
                frames_dir=str(out / "extracted_frames"),
                detections=[],
                processing_time=processing_time,
                frames_processed=0,
                text_replacements={},
                error_message=str(e),
            )

    def run_text_replacement(
        self,
        video_path: str,
        replacement_text: str,
        output_dir: str,
        style_overrides: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        return self._run_full_text_edit_pipeline(
            video_path,
            output_dir,
            replacement_text=replacement_text,
            style_overrides=style_overrides,
        )

    def run_text_removal(self, video_path: str, output_dir: str) -> PipelineResult:
        return self._run_full_text_edit_pipeline(video_path, output_dir, replacement_text=None)

    def run(
        self,
        video_path: str,
        command: str,
        output_dir: str,
        replacement_text: str = None,
    ) -> PipelineResult:
        """Dispatch by keywords in ``command`` (extract | remove | replace)."""
        self.start_time = time.time()
        logger.info(f"Starting pipeline: {command}")
        logger.info(f"Input: {video_path}")
        logger.info(f"Output: {output_dir}")

        command_lower = command.lower()

        try:
            if "extract" in command_lower or "frame" in command_lower:
                return self.run_text_extraction(video_path, output_dir)

            if "remove" in command_lower or "delete" in command_lower:
                return self.run_text_removal(video_path, output_dir)

            if "replace" in command_lower or "change" in command_lower:
                repl = replacement_text or "MODIFIED"
                return self.run_text_replacement(video_path, repl, output_dir)

            return self.run_text_extraction(video_path, output_dir)

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            elapsed = time.time() - self.start_time
            return PipelineResult(
                success=False,
                video_path=video_path,
                frames_dir=str(Path(output_dir) / "frames"),
                detections=[],
                processing_time=elapsed,
                frames_processed=0,
                text_replacements={},
                error_message=str(e),
            )


def create_pipeline(device: str = "cpu", fps: int = 30, max_frames: int = None) -> VideoPipeline:
    return VideoPipeline(PipelineConfig(device=device, fps=fps, max_frames=max_frames))


def process_video(
    video_path: str, command: str, output_dir: str, replacement_text: str = None
) -> PipelineResult:
    return create_pipeline().run(video_path, command, output_dir, replacement_text)


if __name__ == "__main__":
    print("Import VideoPipeline / process_video from this module, or call methods from Python.")
