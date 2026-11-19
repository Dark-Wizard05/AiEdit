from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Tuple
import torch
from transformers import pipeline
import logging
import time

from backend import auth_db
from backend.commentary_routes import router as commentary_router
from backend.studio import router as studio_router
from backend.auth_routes import router as auth_router

# Import centralized logging
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    auth_db.init_db()
    logger.info("Auth database ready")
    yield


# Initialize FastAPI app
app = FastAPI(
    title="AiEdit API",
    description="Video and image editing with AI-powered intent detection",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(commentary_router)
app.include_router(auth_router)
app.include_router(studio_router)

# ==================== Pydantic Models ====================

class CommandRequest(BaseModel):
    """Request model for text command processing"""
    command: str
    confidence_threshold: Optional[float] = 0.5


class CommandResponse(BaseModel):
    """Response model for command processing"""
    command: str
    detected_intent: str
    confidence: float
    intent_type: str
    parameters: Dict[str, Any]
    suggestions: List[str]


class EditOperation(BaseModel):
    """Edit operation details"""
    operation_type: str  # "text_replacement", "trimming", "background_removal"
    description: str
    parameters: Dict[str, Any]


class BatchCommandRequest(BaseModel):
    """Request model for batch command processing"""
    commands: List[str]


class BatchCommandResponse(BaseModel):
    """Response model for batch command processing"""
    results: List[CommandResponse]
    processing_time: float


# ==================== Intent Detection Pipeline ====================

class IntentDetector:
    """Intent detection using zero-shot classification"""
    
    # Define intent labels and their aliases
    INTENT_LABELS = {
        "text_replacement": {
            "label": "text replacement",
            "aliases": ["change text", "replace text", "edit text", "modify text", "swap text"],
            "description": "Replace or change existing text"
        },
        "text_removal": {
            "label": "remove text",
            "aliases": ["delete text", "erase text", "remove all text", "clean text"],
            "description": "Remove text from image/video"
        },
        "trimming": {
            "label": "trim video",
            "aliases": ["cut video", "crop video", "trim clip", "cut clip", "remove frames"],
            "description": "Trim or crop video/image"
        },
        "background_removal": {
            "label": "background removal",
            "aliases": ["remove background", "change background", "transparent background", "extract subject"],
            "description": "Remove or change background"
        },
        "motion_blur": {
            "label": "motion blur effect",
            "aliases": ["add blur", "blur motion", "smooth motion", "stabilize video"],
            "description": "Add motion blur or stabilization effects"
        },
        "color_correction": {
            "label": "color correction",
            "aliases": ["adjust color", "fix colors", "change colors", "enhance colors"],
            "description": "Adjust colors and brightness"
        },
        "frame_extraction": {
            "label": "extract frames",
            "aliases": ["save frames", "get frames", "export frames", "extract video to images"],
            "description": "Extract frames from video"
        },
        "video_assembly": {
            "label": "create video from frames",
            "aliases": ["make video", "combine frames", "assemble video", "create video"],
            "description": "Assemble frames into video"
        }
    }
    
    def __init__(self, device: str = None):
        """Initialize intent detector"""
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"Loading zero-shot classification model (device: {self.device})")
        
        try:
            self.classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
                device=0 if self.device == 'cuda' else -1
            )
            logger.info("Intent detector loaded successfully")
        except Exception as e:
            logger.error(f"Error loading classifier: {str(e)}")
            self.classifier = None
    
    def detect_intent(self, command: str, threshold: float = 0.5) -> Dict[str, Any]:
        """
        Detect intent from user command.
        
        Args:
            command (str): User command text
            threshold (float): Confidence threshold for intent detection
        
        Returns:
            Dict with detected intent and confidence
        """
        if not command or not self.classifier:
            return {
                "success": False,
                "error": "Intent detector not available",
                "command": command
            }
        
        try:
            # Prepare intent labels
            intent_labels = [info["label"] for info in self.INTENT_LABELS.values()]
            
            # Run classification
            result = self.classifier(command, intent_labels, multi_class=True)
            
            # Extract top result
            top_label = result['labels'][0]
            confidence = result['scores'][0]
            
            # Find matching intent key
            intent_key = None
            for key, info in self.INTENT_LABELS.items():
                if info["label"] == top_label:
                    intent_key = key
                    break
            
            if not intent_key:
                intent_key = "text_replacement"  # Default fallback
            
            return {
                "success": True,
                "command": command,
                "detected_intent": top_label,
                "intent_key": intent_key,
                "confidence": float(confidence),
                "all_scores": {
                    label: float(score) 
                    for label, score in zip(result['labels'], result['scores'])
                },
                "threshold_met": confidence >= threshold
            }
        
        except Exception as e:
            logger.error(f"Error detecting intent: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "command": command
            }
    
    def extract_parameters(self, command: str, intent_key: str) -> Dict[str, Any]:
        """
        Extract parameters from command based on intent.
        
        Args:
            command (str): User command
            intent_key (str): Detected intent type
        
        Returns:
            Dict with extracted parameters
        """
        parameters = {}
        command_lower = command.lower()
        
        # Extract common parameters
        if "to" in command_lower:
            parts = command_lower.split("to")
            if len(parts) > 1:
                parameters["new_value"] = parts[-1].strip()
        
        # Intent-specific extraction
        if intent_key == "text_replacement":
            # Extract "from X to Y" or "change X to Y"
            if "from" in command_lower and "to" in command_lower:
                from_idx = command_lower.find("from") + 4
                to_idx = command_lower.find("to")
                parameters["old_text"] = command[from_idx:to_idx].strip()
                parameters["new_text"] = command[to_idx + 2:].strip()
        
        elif intent_key == "trimming":
            # Extract start/end times or frames
            import re
            numbers = re.findall(r'\d+', command)
            if len(numbers) >= 2:
                parameters["start_second"] = int(numbers[0])
                parameters["end_second"] = int(numbers[1])
            elif len(numbers) == 1:
                parameters["duration_seconds"] = int(numbers[0])
        
        elif intent_key == "frame_extraction":
            # Extract FPS parameter
            import re
            if "fps" in command_lower or "frame" in command_lower:
                numbers = re.findall(r'\d+', command)
                if numbers:
                    parameters["fps"] = int(numbers[0])
        
        return parameters
    
    def get_suggestions(self, intent_key: str, command: str) -> List[str]:
        """
        Get suggestions for the detected intent.
        
        Args:
            intent_key (str): Detected intent type
            command (str): Original command
        
        Returns:
            List of helpful suggestions
        """
        suggestions = []
        
        intent_info = self.INTENT_LABELS.get(intent_key, {})
        suggestions.append(f"✓ Detected: {intent_info.get('description', intent_key)}")
        
        # Add examples
        if intent_key == "text_replacement":
            suggestions.append('Example: "Replace \'Old\' with \'New\'"')
        elif intent_key == "trimming":
            suggestions.append('Example: "Trim from 10 to 30 seconds"')
        elif intent_key == "background_removal":
            suggestions.append('Example: "Remove the background"')
        elif intent_key == "frame_extraction":
            suggestions.append('Example: "Extract frames at 30 fps"')
        
        return suggestions


# ==================== Initialize Intent Detector ====================

intent_detector = IntentDetector()


def _parse_command(
    command: str, confidence_threshold: float = 0.5
) -> Tuple[Optional[CommandResponse], Optional[str]]:
    """Return (response, error_message)."""
    intent_result = intent_detector.detect_intent(command, confidence_threshold)
    if not intent_result.get("success"):
        return None, intent_result.get("error", "Intent detection failed")
    intent_key = intent_result["intent_key"]
    return CommandResponse(
        command=command,
        detected_intent=intent_result["detected_intent"],
        confidence=intent_result["confidence"],
        intent_type=intent_key,
        parameters=intent_detector.extract_parameters(command, intent_key),
        suggestions=intent_detector.get_suggestions(intent_key, command),
    ), None


# ==================== API Endpoints ====================

@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API status"""
    return {
        "status": "ok",
        "message": "AiEdit API is running",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {
        "status": "healthy",
        "model_loaded": intent_detector.classifier is not None,
        "device": intent_detector.device
    }


@app.post("/process-command", response_model=CommandResponse, tags=["Commands"])
async def process_command(request: CommandRequest):
    logger.info(f"Processing command: {request.command}")
    try:
        threshold = request.confidence_threshold if request.confidence_threshold is not None else 0.5
        resp, err = _parse_command(request.command, threshold)
        if err:
            logger.warning(f"Intent detection failed: {err}")
            raise HTTPException(status_code=400, detail=err)
        logger.info(
            f"Detected intent: {resp.detected_intent} (confidence: {resp.confidence:.2%})"
        )
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing command: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch-process", response_model=BatchCommandResponse, tags=["Commands"])
async def batch_process_commands(request: BatchCommandRequest):
    logger.info(f"Batch processing {len(request.commands)} commands")
    try:
        start_time = time.time()
        results = []
        for idx, command in enumerate(request.commands):
            try:
                resp, _ = _parse_command(command, 0.5)
                if resp:
                    results.append(resp)
            except Exception as e:
                logger.warning(f"Error processing command {idx}: {str(e)}")
                continue
        processing_time = time.time() - start_time
        logger.info(
            f"Batch processing complete: {len(results)}/{len(request.commands)} "
            f"processed in {processing_time:.2f}s"
        )
        return BatchCommandResponse(results=results, processing_time=processing_time)
    except Exception as e:
        logger.error(f"Error in batch processing: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/intents", tags=["Reference"])
async def list_intents():
    """Get list of supported intents and their details"""
    return {
        "intents": {
            key: {
                "label": info["label"],
                "aliases": info["aliases"],
                "description": info["description"]
            }
            for key, info in intent_detector.INTENT_LABELS.items()
        }
    }


@app.get("/intents/{intent_key}", tags=["Reference"])
async def get_intent_details(intent_key: str):
    """Get detailed information about a specific intent"""
    intent_info = intent_detector.INTENT_LABELS.get(intent_key)
    
    if not intent_info:
        raise HTTPException(
            status_code=404,
            detail=f"Intent '{intent_key}' not found"
        )
    
    return {
        "intent_key": intent_key,
        "label": intent_info["label"],
        "aliases": intent_info["aliases"],
        "description": intent_info["description"]
    }


@app.post("/edit-operation", response_model=EditOperation, tags=["Operations"])
async def create_edit_operation(request: CommandRequest):
    try:
        resp, err = _parse_command(request.command)
        if err:
            raise HTTPException(status_code=400, detail=err)
        intent_info = intent_detector.INTENT_LABELS.get(resp.intent_type, {})
        return EditOperation(
            operation_type=resp.intent_type,
            description=intent_info.get("description", "Edit operation"),
            parameters=resp.parameters,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating edit operation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Error Handlers ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc)
        }
    )


# ==================== Phase 5: Local Jobs API ====================
#
# Localhost-only job runner: parse -> validate -> execute through core.engine.
# Jobs live in process memory; no auth, no quotas, not for hosting yet.
# When Phase 6 starts, swap _JOBS for a real queue + storage.

import threading
import uuid
from typing import Literal


class JobSubmit(BaseModel):
    prompt: str
    video_path: str
    output_dir: Optional[str] = "output/job"
    preset: Optional[Literal["fast", "balanced", "quality"]] = None


class JobStatus(BaseModel):
    job_id: str
    state: Literal["queued", "running", "done", "error"]
    operation: Optional[str] = None
    summary: Optional[str] = None
    output_video_path: Optional[str] = None
    error: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None


_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _run_job(job_id: str, body: JobSubmit) -> None:
    from utils.prompt_parser import parse_edit_command
    from core.engine import ExecutionContext, execute
    from core.presets import get_preset, recommend
    try:
        from logging_config import log_event
    except Exception:
        def log_event(*_args, **_kwargs):
            return None

    log_event("job_start", job_id=job_id, prompt=body.prompt)
    with _JOBS_LOCK:
        _JOBS[job_id]["state"] = "running"

    try:
        instruction = parse_edit_command(body.prompt)
        preset = get_preset(body.preset) if body.preset else recommend()
        ctx = ExecutionContext(
            video_path=body.video_path,
            output_dir=body.output_dir or "output/job",
            device=preset.device,
            fps=preset.fps,
        )
        result = execute(instruction, ctx)
        with _JOBS_LOCK:
            _JOBS[job_id].update(
                {
                    "state": "done" if result.ok else "error",
                    "operation": result.operation,
                    "summary": result.summary,
                    "output_video_path": result.output_video_path,
                    "error": result.error,
                    "validation": result.validation.to_dict() if result.validation else None,
                }
            )
        log_event(
            "job_finish",
            job_id=job_id,
            ok=result.ok,
            operation=result.operation,
            error=result.error,
        )
    except Exception as exc:
        with _JOBS_LOCK:
            _JOBS[job_id].update({"state": "error", "error": str(exc)})
        log_event("job_finish", job_id=job_id, ok=False, error=str(exc))


@app.post("/jobs", response_model=JobStatus, tags=["Jobs"])
async def submit_job(body: JobSubmit):
    """Submit a parse-validate-execute job. Localhost only."""
    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "state": "queued",
        }
    threading.Thread(target=_run_job, args=(job_id, body), daemon=True).start()
    return JobStatus(job_id=job_id, state="queued")


@app.get("/jobs/{job_id}", response_model=JobStatus, tags=["Jobs"])
async def get_job(job_id: str):
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    return JobStatus(**record)


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn
    
    # NOTE: localhost-only by default; Phase 6 (hosting) is intentionally deferred.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
