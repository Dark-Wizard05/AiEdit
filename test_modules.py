"""
Manual smoke tests for AiEdit utility modules and optional FastAPI checks.

This is the single maintained script for ad-hoc verification (text detection,
removal/overlay, frame extract/reassemble, and ``backend.api`` when a server is up).
Run from the project root::

    py test_modules.py

Older duplicates ``simple_test.py`` and ``quick_test.py`` were removed to avoid
three overlapping suites generating different stray PNG names.
"""

import cv2
import numpy as np
from pathlib import Path
import sys

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent))

def test_video_processor():
    """Test video processing functions"""
    print("\n" + "="*60)
    print("Testing Video Processor Module")
    print("="*60)
    
    try:
        from utils.video_processor import extract_frames, reassemble_frames
        
        # Test with a sample video (if available)
        test_video = "test_video.mp4"
        
        if not Path(test_video).exists():
            print(f"⚠ No test video found at {test_video}")
            print("To test, provide a video file named 'test_video.mp4'")
            return
        
        frames_dir = "extracted_frames/"
        output_video = "output_video.mp4"
        
        # Extract frames
        print("\n✓ Testing extract_frames()...")
        success = extract_frames(test_video, frames_dir, fps=30)
        print(f"  Result: {'SUCCESS' if success else 'FAILED'}")
        
        # Reassemble frames
        if success:
            print("\n✓ Testing reassemble_frames()...")
            success = reassemble_frames(frames_dir, output_video, fps=30)
            print(f"  Result: {'SUCCESS' if success else 'FAILED'}")
    
    except Exception as e:
        print(f"✗ Error testing video processor: {str(e)}")


def test_text_detection():
    """Test text detection with OCR"""
    print("\n" + "="*60)
    print("Testing Text Detection Module")
    print("="*60)
    
    try:
        from utils.text_detection_sam import TextDetectionSAM
        
        # Create a test image with text
        test_image_path = "test_frame.png"
        
        if not Path(test_image_path).exists():
            print(f"⚠ No test image found at {test_image_path}")
            print("Creating sample test image...")
            
            # Create a simple test image
            img = np.ones((480, 640, 3), dtype=np.uint8) * 255
            cv2.putText(img, "Hello World", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 
                       2, (0, 0, 0), 3)
            cv2.putText(img, "Test Text", (100, 250), cv2.FONT_HERSHEY_SIMPLEX, 
                       1.5, (0, 0, 0), 2)
            cv2.imwrite(test_image_path, img)
            print(f"✓ Created sample test image: {test_image_path}")
        
        # Initialize detector
        print("\n✓ Initializing TextDetectionSAM (CPU mode)...")
        detector = TextDetectionSAM(device='cpu')
        
        # Load image
        image = cv2.imread(test_image_path)
        
        # Detect text
        print("\n✓ Testing text detection...")
        detections = detector.detect_text_regions(image)
        print(f"  Found {len(detections)} text regions")
        
        for i, det in enumerate(detections):
            print(f"  [{i}] Text: '{det['text']}' | Confidence: {det['confidence']:.2f}")
        
        # Generate masks (without SAM, will use bbox masks)
        print("\n✓ Testing mask generation...")
        masks = detector.generate_text_masks(image, detections)
        print(f"  Generated {len(masks)} masks")
        
        # Visualize
        print("\n✓ Creating visualization...")
        vis_image = detector.visualize_detections(
            image, detections, masks,
            output_path="text_detection_result.png"
        )
        print(f"  Visualization saved to: text_detection_result.png")
        
        print("\n✓ Text Detection Tests: PASSED")
    
    except Exception as e:
        print(f"✗ Error testing text detection: {str(e)}")


def test_text_removal():
    """Test text removal and overlay"""
    print("\n" + "="*60)
    print("Testing Text Removal & Overlay Module")
    print("="*60)
    
    try:
        from utils.text_removal_overlay import TextRemovalAndOverlay
        
        test_image_path = "test_frame.png"
        
        if not Path(test_image_path).exists():
            print(f"⚠ No test image found at {test_image_path}")
            print("Run text detection test first to create test_frame.png")
            return
        
        # Initialize processor
        print("\n✓ Initializing TextRemovalAndOverlay (CPU mode)...")
        processor = TextRemovalAndOverlay(device='cpu')
        
        # Load image
        image = cv2.imread(test_image_path)
        
        # Create a simple mask (rectangle)
        mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
        mask[80:120, 40:350] = 255  # Mark text area
        
        # Test OpenCV inpainting (fast)
        print("\n✓ Testing text removal (OpenCV method)...")
        cleaned = processor.remove_text_opencv(image, mask)
        cv2.imwrite("text_removed.png", cleaned)
        print("  Result saved to: text_removed.png")
        
        # Test overlay
        print("\n✓ Testing text overlay...")
        bbox = (40, 80, 350, 120)
        result = processor.overlay_text(
            cleaned, "Both", bbox,
            color=(0, 0, 0), font_size=20
        )
        cv2.imwrite("text_overlay_result.png", result)
        print("  Result saved to: text_overlay_result.png")
        
        print("\n✓ Text Removal & Overlay Tests: PASSED")
    
    except Exception as e:
        print(f"✗ Error testing text removal: {str(e)}")


def test_api_endpoints():
    """Test FastAPI endpoints"""
    print("\n" + "="*60)
    print("Testing FastAPI Endpoints")
    print("="*60)
    
    try:
        import requests
        import json
        
        base_url = "http://localhost:8000"
        
        # Test 1: Health check
        print("\n✓ Testing GET /health...")
        response = requests.get(f"{base_url}/health")
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.json()}")
        
        # Test 2: Process single command
        print("\n✓ Testing POST /process-command...")
        payload = {
            "command": "Replace hello with goodbye",
            "confidence_threshold": 0.5
        }
        response = requests.post(f"{base_url}/process-command", json=payload)
        print(f"  Status: {response.status_code}")
        result = response.json()
        print(f"  Intent: {result['intent_type']}")
        print(f"  Confidence: {result['confidence']:.3f}")
        
        # Test 3: Batch processing
        print("\n✓ Testing POST /batch-process...")
        payload = {
            "commands": [
                "Change old text to new text",
                "Trim video from 10 to 30 seconds",
                "Remove the background",
                "Extract frames at 30 fps"
            ]
        }
        response = requests.post(f"{base_url}/batch-process", json=payload)
        print(f"  Status: {response.status_code}")
        result = response.json()
        print(f"  Processed: {len(result['results'])} commands")
        print(f"  Processing time: {result['processing_time']:.3f}s")
        
        for i, cmd_result in enumerate(result['results'], 1):
            print(f"    [{i}] {cmd_result['command']}")
            print(f"        Intent: {cmd_result['intent_type']} (confidence: {cmd_result['confidence']:.3f})")
        
        # Test 4: List intents
        print("\n✓ Testing GET /intents...")
        response = requests.get(f"{base_url}/intents")
        print(f"  Status: {response.status_code}")
        intents = response.json()['intents']
        print(f"  Available intents: {len(intents)}")
        for intent_key in list(intents.keys())[:3]:
            print(f"    - {intent_key}: {intents[intent_key]['description']}")
        
        print("\n✓ API Endpoint Tests: PASSED")
    
    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to API server at http://localhost:8000")
        print("  Make sure the server is running: py -m uvicorn backend.api:app --reload")
    except Exception as e:
        print(f"✗ Error testing API: {str(e)}")


def test_prompt_parser_golden():
    """Run lightweight golden prompts through the rule-based parser + validator.

    No ML model loads, no Ollama, no network. This is the Phase 0 baseline:
    fast, deterministic, catches regressions when prompt rules or the
    validator change.
    """
    print("\n" + "=" * 60)
    print("Testing Prompt Parser (golden prompts)")
    print("=" * 60)

    try:
        from utils.prompt_parser import _parse_rule_based
        from core.edit_plan import validate_edit_instruction
    except Exception as exc:
        print(f"✗ Import failed: {exc}")
        return

    cases = [
        ("Replace 'GAME OVER' with 'BOTH'", "text_replacement", True),
        ("Remove text from the video", "text_removal", True),
        ("Extract frames from the video", "frame_extraction", True),
        ("Change Rapunzel's hair color to pink", "character_hair_recolor", True),
        ("Change the crown to pink", "object_recolor", True),
        ("Remove the fireworks behind the character", "object_remove", True),
        ("Replace the crown with a flower", "object_replace_guided", True),
        ("Change Rapunzel's hair color to #ff66cc", "character_hair_recolor", True),
        ("Make the crown teal", "object_recolor", True),
        ("Change the crown color to rgb(20, 180, 90)", "object_recolor", True),
        ("Replace 'Hello' with 'Goodbye' in red bold size 32", "text_replacement", True),
        ("Change all reds to blue loosely", "global_color_change", True),
        ("Change only the pure red to navy", "global_color_change", True),
        (
            "Heavy thunderstorm with a moss-green #1a3b2e tint",
            "atmosphere_overlay",
            True,
        ),
        (
            "Add rain and thunder mood without regenerating the scene",
            "atmosphere_overlay",
            True,
        ),
        ("Make it look sunny but with light snowing", "atmosphere_overlay", True),
        ("Thick fog at dusk, very moody", "atmosphere_overlay", True),
        ("Cyclone with heavy wind and dust, no rain", "atmosphere_overlay", True),
        ("Golden hour, warm cinematic look", "atmosphere_overlay", True),
        ("Night scene with neon cyberpunk glow", "atmosphere_overlay", True),
        ("Make the entire video sing opera in French", "unsupported", False),
    ]

    passed = 0
    for prompt, expected_op, should_be_executable in cases:
        instruction = _parse_rule_based(prompt)
        validation = validate_edit_instruction(instruction)
        op_ok = instruction.operation == expected_op or (
            not should_be_executable and not instruction.supported
        )
        exec_ok = validation.ok if should_be_executable else not validation.ok
        ok = op_ok and exec_ok
        marker = "PASS" if ok else "FAIL"
        print(
            f"  [{marker}] '{prompt[:48]}' -> op={instruction.operation} "
            f"valid={validation.ok}"
        )
        if not ok:
            print(
                f"      expected op={expected_op} executable={should_be_executable}; "
                f"errors={validation.errors}"
            )
        if ok:
            passed += 1
    print(f"\n  {passed}/{len(cases)} golden prompts passed")


def test_core_modules():
    """Fast checks for the new core/ helpers (no ML, no network)."""
    print("\n" + "=" * 60)
    print("Testing core/ modules")
    print("=" * 60)

    import numpy as np
    failures = []

    try:
        from core.edit_plan import validate_edit_instruction

        class _Fake:
            def __init__(self, op, params):
                self.operation = op
                self.parameters = params
                self.supported = True
                self.metadata = {}

        good = validate_edit_instruction(_Fake("text_replacement", {"old_text": "A", "new_text": "B"}))
        bad = validate_edit_instruction(_Fake("text_replacement", {"old_text": "", "new_text": ""}))
        bad_color = validate_edit_instruction(_Fake("character_hair_recolor", {"target_color": "octarine"}))
        unknown = validate_edit_instruction(_Fake("unsupported", {}))
        assert good.ok, "valid plan should pass"
        assert not bad.ok and bad.missing, "missing params must be flagged"
        assert not bad_color.ok and bad_color.invalid, "unknown color must be flagged"
        assert not unknown.ok, "unsupported op must fail"
        print("  [PASS] edit_plan.validate_edit_instruction")
    except AssertionError as exc:
        failures.append(f"edit_plan: {exc}")
        print(f"  [FAIL] edit_plan: {exc}")

    try:
        from core.clarification import clarification_question, needs_clarification

        class _Fake:
            def __init__(self, op, params, supported=True, metadata=None):
                self.operation = op
                self.parameters = params
                self.supported = supported
                self.metadata = metadata or {}

        a = _Fake("text_replacement", {"old_text": "", "new_text": ""})
        assert needs_clarification(a), "should ask when text params are empty"
        assert clarification_question(a), "should produce a question"
        b = _Fake("text_replacement", {"old_text": "A", "new_text": "B"})
        assert not needs_clarification(b), "valid plan should not ask"
        print("  [PASS] clarification.needs_clarification / clarification_question")
    except AssertionError as exc:
        failures.append(f"clarification: {exc}")
        print(f"  [FAIL] clarification: {exc}")

    try:
        from core.temporal import smooth_mask_sequence, stabilize_bboxes

        m = np.zeros((5, 8, 8), dtype=np.uint8)
        m[:, 2:6, 2:6] = 255
        m[2] = 0  # one-frame dropout that smoothing should fill
        out = smooth_mask_sequence(list(m), window=2, threshold=0.4, morph_kernel=0)
        assert out[2][3, 3] > 0, "temporal smoothing should fill the 1-frame hole"
        boxes = [(0, 0, 10, 10), (2, 2, 12, 12), (4, 4, 14, 14)]
        smoothed = stabilize_bboxes(boxes, window=1)
        assert len(smoothed) == 3
        print("  [PASS] temporal.smooth_mask_sequence / stabilize_bboxes")
    except AssertionError as exc:
        failures.append(f"temporal: {exc}")
        print(f"  [FAIL] temporal: {exc}")

    try:
        from core.ocr_consensus import consensus_text_regions

        per_frame = [
            [{"bbox": (10, 10, 100, 30), "text": "GAME OVER", "confidence": 0.9}],
            [{"bbox": (12, 11, 102, 31), "text": "GAME OVER", "confidence": 0.85}],
            [{"bbox": (11, 10, 99, 30), "text": "GANE OVER", "confidence": 0.4}],
        ]
        out = consensus_text_regions(per_frame, grid=8, min_votes=2)
        assert out and out[0]["text"] == "GAME OVER", out
        print("  [PASS] ocr_consensus.consensus_text_regions")
    except AssertionError as exc:
        failures.append(f"ocr_consensus: {exc}")
        print(f"  [FAIL] ocr_consensus: {exc}")

    try:
        from core.presets import PRESETS, detect_hardware, recommend

        info = detect_hardware()
        chosen = recommend(info)
        assert chosen.name in PRESETS
        print(f"  [PASS] presets.recommend -> {chosen.name} (hw={info})")
    except AssertionError as exc:
        failures.append(f"presets: {exc}")
        print(f"  [FAIL] presets: {exc}")

    try:
        from core.engine import ExecutionContext, execute

        class _Fake:
            operation = "unsupported"
            parameters = {}
            supported = False
            metadata = {}

        result = execute(_Fake(), ExecutionContext())
        assert not result.ok and result.validation is not None
        print("  [PASS] engine.execute blocks invalid plans before any runner runs")
    except AssertionError as exc:
        failures.append(f"engine: {exc}")
        print(f"  [FAIL] engine: {exc}")

    print(f"\n  {6 - len(failures)}/6 core checks passed")


def main():
    """Run all tests"""
    print("\n╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "   AiEdit Testing Suite".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    
    # Fast, dependency-free checks first.
    test_prompt_parser_golden()
    test_core_modules()

    # Heavier checks (load OCR/torch, hit FastAPI). Comment any out if unwanted.
    test_api_endpoints()
    test_text_detection()
    test_text_removal()
    test_video_processor()
    
    print("\n" + "="*60)
    print("Testing Complete!")
    print("="*60)
    print("\nGenerated files:")
    for file in Path(".").glob("*.png"):
        print(f"  - {file}")
    print("\nFor more detailed testing, see individual module docstrings.")


if __name__ == "__main__":
    main()
