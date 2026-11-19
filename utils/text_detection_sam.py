import cv2
import numpy as np
import easyocr
import torch
from pathlib import Path
from typing import List, Tuple, Dict
import warnings
import logging

warnings.filterwarnings('ignore')

# Import centralized logging
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)



class TextDetectionSAM:
    """
    Text detection and segmentation using EasyOCR and Segment Anything Model (SAM).
    """
    
    def __init__(self, device: str = None):
        """
        Initialize TextDetectionSAM with EasyOCR and SAM models.
        
        Args:
            device (str): Device to use ('cuda' or 'cpu'). Auto-detects if None.
        """
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"TextDetectionSAM initializing with device: {self.device}")
        
        # Initialize EasyOCR reader
        logger.info("Loading EasyOCR model...")
        self.ocr_reader = easyocr.Reader(['en'], gpu=(self.device == 'cuda'))
        logger.info("[OK] EasyOCR model loaded")
        
        # Import SAM
        try:
            from segment_anything import sam_model_registry, SamPredictor
            self.sam_model_registry = sam_model_registry
            self.SamPredictor = SamPredictor
            self.sam_available = True
            logger.info("[OK] SAM models available")
        except ImportError:
            logger.warning("Segment Anything not fully installed. Install with: pip install segment-anything")
            self.sam_available = False
        
        self.sam = None
        self.predictor = None
    
    def load_sam_model(self, model_type: str = "vit_b", checkpoint_path: str = None):
        """
        Load SAM model with automatic checkpoint download.
        
        Args:
            model_type (str): SAM model type - 'vit_b', 'vit_l', or 'vit_h'
            checkpoint_path (str): Path to SAM checkpoint. If None, downloads automatically.
        """
        if not self.sam_available:
            print("SAM not available. Skipping SAM model loading.")
            return False
        
        try:
            # Download model checkpoint if not provided
            if checkpoint_path is None:
                home_dir = Path.home()
                checkpoint_dir = home_dir / '.cache' / 'sam_checkpoints'
                checkpoint_dir.mkdir(parents=True, exist_ok=True)
                
                checkpoint_mapping = {
                    'vit_b': 'sam_vit_b_01ec64.pth',
                    'vit_l': 'sam_vit_l_0b3195.pth',
                    'vit_h': 'sam_vit_h_4b8939.pth'
                }
                
                checkpoint_file = checkpoint_dir / checkpoint_mapping.get(model_type, checkpoint_mapping['vit_b'])
                
                if not checkpoint_file.exists():
                    import urllib.request
                    url_base = 'https://dl.fbaipublicfiles.com/segment_anything/'
                    url = url_base + checkpoint_file.name
                    logger.info(f"Downloading SAM model ({model_type})...")
                    urllib.request.urlretrieve(url, checkpoint_file)
                
                checkpoint_path = str(checkpoint_file)
            
            logger.info(f"Loading SAM model ({model_type})...")
            self.sam = self.sam_model_registry[model_type](checkpoint=checkpoint_path)
            self.sam.to(device=self.device)
            self.predictor = self.SamPredictor(self.sam)
            logger.info("[OK] SAM model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error loading SAM model: {str(e)}", exc_info=True)
            return False
    
    def detect_text_regions(self, image: np.ndarray) -> List[Dict]:
        """
        Detect text regions using EasyOCR.
        
        Args:
            image (np.ndarray): Input image (BGR format from OpenCV)
        
        Returns:
            List[Dict]: List of detected text regions with bounding boxes and confidence
        """
        try:
            # Convert BGR to RGB for OCR
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # Run OCR
            logger.debug("Detecting text regions with EasyOCR...")
            results = self.ocr_reader.readtext(image_rgb, detail=1)
            
            detections = []
            for (bbox, text, confidence) in results:
                # bbox is a list of 4 points (top-left, top-right, bottom-right, bottom-left)
                bbox = np.array(bbox, dtype=np.int32)
                x_min = int(bbox[:, 0].min())
                y_min = int(bbox[:, 1].min())
                x_max = int(bbox[:, 0].max())
                y_max = int(bbox[:, 1].max())
                
                detections.append({
                    'text': text,
                    'confidence': confidence,
                    'bbox': (x_min, y_min, x_max, y_max),
                    'polygon': bbox,
                    'width': x_max - x_min,
                    'height': y_max - y_min
                })
            
            logger.debug(f"Detected {len(detections)} text regions")
            return detections
        
        except Exception as e:
            logger.error(f"Error detecting text regions: {str(e)}", exc_info=True)
            return []
    
    def generate_text_masks(self, image: np.ndarray, detections: List[Dict]) -> List[np.ndarray]:
        """
        Generate precise masks for detected text regions using SAM.
        
        Args:
            image (np.ndarray): Input image (BGR format)
            detections (List[Dict]): Text detections from detect_text_regions()
        
        Returns:
            List[np.ndarray]: List of binary masks for each detected text region
        """
        if not self.sam_available or self.predictor is None:
            print("SAM not available. Returning bounding box masks instead.")
            return self._create_bbox_masks(image, detections)
        
        masks = []
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        print(f"Generating SAM masks for {len(detections)} text regions...")
        self.predictor.set_image(image_rgb)
        
        for i, detection in enumerate(detections):
            try:
                bbox = detection['bbox']
                # SAM expects input prompts as (x, y) points or bounding boxes
                input_box = np.array([bbox[0], bbox[1], bbox[2], bbox[3]])
                
                # Generate mask
                masks_output, scores, logits = self.predictor.predict(
                    box=input_box,
                    multimask_output=False
                )
                
                mask = masks_output[0].astype(np.uint8) * 255
                masks.append(mask)
                
            except Exception as e:
                print(f"Error generating mask for region {i}: {str(e)}")
                # Fallback to bounding box mask
                masks.append(self._create_bbox_mask(image, detection))
        
        return masks
    
    def _create_bbox_masks(self, image: np.ndarray, detections: List[Dict]) -> List[np.ndarray]:
        """Create binary masks from bounding boxes."""
        height, width = image.shape[:2]
        masks = []
        
        for detection in detections:
            mask = np.zeros((height, width), dtype=np.uint8)
            x1, y1, x2, y2 = detection['bbox']
            mask[y1:y2, x1:x2] = 255
            masks.append(mask)
        
        return masks
    
    def _create_bbox_mask(self, image: np.ndarray, detection: Dict) -> np.ndarray:
        """Create a single binary mask from bounding box."""
        height, width = image.shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)
        x1, y1, x2, y2 = detection['bbox']
        mask[y1:y2, x1:x2] = 255
        return mask
    
    def visualize_detections(self, image: np.ndarray, detections: List[Dict], 
                            masks: List[np.ndarray] = None, output_path: str = None) -> np.ndarray:
        """
        Visualize detected text regions with bounding boxes and optional masks.
        
        Args:
            image (np.ndarray): Input image
            detections (List[Dict]): Detected text regions
            masks (List[np.ndarray]): SAM masks (optional)
            output_path (str): Path to save visualization (optional)
        
        Returns:
            np.ndarray: Visualized image
        """
        vis_image = image.copy()
        
        # Draw masks if available
        if masks:
            for i, mask in enumerate(masks):
                # Create colored overlay for mask
                colored_mask = np.zeros_like(vis_image)
                colored_mask[mask > 0] = [0, 255, 0]  # Green for masks
                vis_image = cv2.addWeighted(vis_image, 1, colored_mask, 0.3, 0)
        
        # Draw bounding boxes
        for detection in detections:
            x1, y1, x2, y2 = detection['bbox']
            text = detection['text']
            confidence = detection['confidence']
            
            # Draw rectangle
            cv2.rectangle(vis_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Draw text label with confidence
            label = f"{text} ({confidence:.2f})"
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(vis_image, (x1, y1 - label_size[1] - 4), 
                         (x1 + label_size[0], y1), (0, 255, 0), -1)
            cv2.putText(vis_image, label, (x1, y1 - 2), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        # Save if output path provided
        if output_path:
            cv2.imwrite(output_path, vis_image)
            print(f"Visualization saved to {output_path}")
        
        return vis_image
    
    def process_frame(self, frame_path: str, use_sam: bool = True, 
                     output_dir: str = None) -> Dict:
        """
        Complete pipeline: load frame, detect text, generate masks, and visualize.
        
        Args:
            frame_path (str): Path to input frame/image
            use_sam (bool): Whether to use SAM for mask generation
            output_dir (str): Directory to save results (optional)
        
        Returns:
            Dict: Results with detections, masks, and visualization
        """
        # Load image
        image = cv2.imread(frame_path)
        if image is None:
            print(f"Error: Could not load image from {frame_path}")
            return None
        
        # Create output directory if needed
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Detect text regions
        detections = self.detect_text_regions(image)
        
        # Generate masks
        masks = None
        if use_sam and self.predictor is not None:
            masks = self.generate_text_masks(image, detections)
        elif use_sam:
            print("SAM not loaded. Load it with load_sam_model() before processing.")
        
        # Visualize
        vis_image = self.visualize_detections(
            image, detections, masks,
            output_path=f"{output_dir}/visualization.png" if output_dir else None
        )
        
        # Save masks individually if output directory provided
        if output_dir and masks:
            for i, mask in enumerate(masks):
                cv2.imwrite(f"{output_dir}/mask_{i:04d}.png", mask)
        
        return {
            'image': image,
            'detections': detections,
            'masks': masks,
            'visualization': vis_image
        }


# Example usage
if __name__ == "__main__":
    # Initialize detector
    detector = TextDetectionSAM(device='cpu')
    
    # Load SAM model (optional but recommended for better results)
    # detector.load_sam_model(model_type='vit_b')
    
    # Process a frame
    # frame_path = "frame_0001.png"
    # results = detector.process_frame(frame_path, use_sam=True, output_dir="ocr_results/")
    
    # To use with a specific frame:
    # image = cv2.imread("frame_0001.png")
    # detections = detector.detect_text_regions(image)
    # masks = detector.generate_text_masks(image, detections)
    # vis_image = detector.visualize_detections(image, detections, masks)
    # cv2.imshow("Text Detection with SAM", vis_image)
    # cv2.waitKey(0)
