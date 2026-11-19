import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Tuple, Optional, List
import warnings
import logging

warnings.filterwarnings('ignore')

# Import centralized logging
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)



class TextRemovalAndOverlay:
    """
    Text removal using Stable Diffusion inpainting and text overlay with style preservation.
    """
    
    def __init__(self, device: str = None, use_fp16: bool = True):
        """
        Initialize text removal and overlay pipeline.
        
        Args:
            device (str): Device to use ('cuda' or 'cpu'). Auto-detects if None.
            use_fp16 (bool): Use half precision for faster inference (requires GPU)
        """
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.use_fp16 = use_fp16 and (self.device == 'cuda')
        
        logger.info(f"TextRemovalAndOverlay initializing with device: {self.device}")
        if self.use_fp16:
            logger.info("Using FP16 precision")
        
        self.inpainting_pipe = None
        self.text_generator_pipe = None

    def _load_overlay_font(self, font_path: Optional[str], font_size: int):
        candidate_paths = []
        if font_path:
            candidate_paths.append(font_path)
        candidate_paths.extend([
            str(Path(r"C:\Windows\Fonts\timesbd.ttf")),
            str(Path(r"C:\Windows\Fonts\times.ttf")),
            str(Path(r"C:\Windows\Fonts\georgia.ttf")),
            str(Path(r"C:\Windows\Fonts\arial.ttf")),
        ])

        for candidate in candidate_paths:
            if candidate and Path(candidate).exists():
                try:
                    return ImageFont.truetype(candidate, max(12, font_size))
                except Exception:
                    continue
        return ImageFont.load_default()
    
    def load_inpainting_model(self, model_id: str = "stabilityai/stable-diffusion-2-inpainting"):
        """
        Load Stable Diffusion inpainting model.
        
        Args:
            model_id (str): HuggingFace model ID for inpainting
        """
        try:
            from diffusers import StableDiffusionInpaintPipeline
            
            logger.info(f"Loading inpainting model: {model_id}...")
            
            pipe = StableDiffusionInpaintPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.float16 if self.use_fp16 else torch.float32
            )
            pipe.enable_attention_slicing()
            pipe.to(self.device)
            
            self.inpainting_pipe = pipe
            logger.info("[OK] Inpainting model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error loading inpainting model: {str(e)}", exc_info=True)
            return False
    
    def load_text_generation_model(self, model_id: str = "runwayml/stable-diffusion-v1-5"):
        """
        Load Stable Diffusion text-to-image model for text generation.
        
        Args:
            model_id (str): HuggingFace model ID for text generation
        """
        try:
            from diffusers import StableDiffusionPipeline
            
            logger.info(f"Loading text generation model: {model_id}...")
            
            pipe = StableDiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.float16 if self.use_fp16 else torch.float32
            )
            pipe.enable_attention_slicing()
            pipe.to(self.device)
            
            self.text_generator_pipe = pipe
            logger.info("[OK] Text generation model loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error loading text generation model: {str(e)}", exc_info=True)
            return False
    
    def expand_mask(self, mask: np.ndarray, expansion_pixels: int = 5) -> np.ndarray:
        """
        Expand mask boundaries to ensure complete text removal.
        
        Args:
            mask (np.ndarray): Binary mask
            expansion_pixels (int): Number of pixels to expand
        
        Returns:
            np.ndarray: Expanded mask
        """
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (2 * expansion_pixels + 1, 2 * expansion_pixels + 1)
        )
        expanded_mask = cv2.dilate(mask, kernel, iterations=1)
        return expanded_mask
    
    def remove_text_inpainting(self, image: np.ndarray, mask: np.ndarray, 
                               prompt: str = "clean background", 
                               negative_prompt: str = "text, watermark, logo",
                               strength: float = 0.95,
                               num_inference_steps: int = 50) -> np.ndarray:
        """
        Remove text from image using Stable Diffusion inpainting.
        
        Args:
            image (np.ndarray): Input image (BGR format)
            mask (np.ndarray): Binary mask of text regions
            prompt (str): Positive prompt for inpainting
            negative_prompt (str): Negative prompt for inpainting
            strength (float): How much to transform the masked area (0-1)
            num_inference_steps (int): Number of denoising steps
        
        Returns:
            np.ndarray: Image with text removed
        """
        if self.inpainting_pipe is None:
            print("Inpainting model not loaded. Call load_inpainting_model() first.")
            return image
        
        try:
            # Convert BGR to RGB
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # Expand mask to ensure complete coverage
            mask_expanded = self.expand_mask(mask, expansion_pixels=5)
            
            # Normalize mask to 0-255
            if mask_expanded.max() <= 1:
                mask_expanded = (mask_expanded * 255).astype(np.uint8)
            
            # Convert to PIL
            image_pil = Image.fromarray(image_rgb)
            mask_pil = Image.fromarray(mask_expanded)
            
            # Ensure same size
            image_pil = image_pil.resize((512, 512))
            mask_pil = mask_pil.resize((512, 512))
            
            print("Running inpainting pipeline...")
            
            with torch.no_grad():
                inpainted = self.inpainting_pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    image=image_pil,
                    mask_image=mask_pil,
                    strength=strength,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=7.5
                ).images[0]
            
            # Resize back to original
            inpainted = inpainted.resize((image.shape[1], image.shape[0]))
            
            # Convert back to BGR
            inpainted_cv = cv2.cvtColor(np.array(inpainted), cv2.COLOR_RGB2BGR)
            
            print("Text removal completed")
            return inpainted_cv
            
        except Exception as e:
            print(f"Error during inpainting: {str(e)}")
            return image
    
    def remove_text_opencv(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Remove text using OpenCV's inpainting (faster alternative to diffusion).
        
        Args:
            image (np.ndarray): Input image (BGR format)
            mask (np.ndarray): Binary mask of text regions
        
        Returns:
            np.ndarray: Image with text removed
        """
        try:
            # Expand mask
            mask_expanded = self.expand_mask(mask, expansion_pixels=3)
            
            # Normalize mask to 0-255
            if mask_expanded.max() <= 1:
                mask_expanded = (mask_expanded * 255).astype(np.uint8)
            
            print("Running OpenCV inpainting...")
            
            # Use Telea's algorithm for fast inpainting
            result = cv2.inpaint(image, mask_expanded, 3, cv2.INPAINT_TELEA)
            
            print("Text removal completed (OpenCV)")
            return result
            
        except Exception as e:
            print(f"Error during OpenCV inpainting: {str(e)}")
            return image
    
    def overlay_text(self, image: np.ndarray, new_text: str, 
                     bbox: Tuple[int, int, int, int],
                     font_path: Optional[str] = None,
                     font_size: int = 30,
                     color: Tuple[int, int, int] = (0, 0, 0),
                     alpha: float = 1.0,
                     stroke_width: int = 0,
                     stroke_color: Optional[Tuple[int, int, int]] = None,
                     shadow_offset: Tuple[int, int] = (0, 0),
                     shadow_color: Optional[Tuple[int, int, int]] = None,
                     align: str = "center",
                     width_scale: float = 0.88,
                     height_scale: float = 0.82) -> np.ndarray:
        """
        Overlay new text on image with transparency support.
        
        Args:
            image (np.ndarray): Input image (BGR format)
            new_text (str): Text to overlay
            bbox (Tuple): Bounding box (x1, y1, x2, y2)
            font_path (str): Path to custom font file (optional)
            font_size (int): Font size in pixels
            color (Tuple): Text color in BGR format
            alpha (float): Text transparency (0-1)
        
        Returns:
            np.ndarray: Image with overlaid text
        """
        result = image.copy()
        
        try:
            x1, y1, x2, y2 = bbox
            text_width = x2 - x1
            text_height = y2 - y1
            
            # Create transparent text layer
            overlay = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            
            fitted_size = max(12, font_size)
            while fitted_size > 10:
                font = self._load_overlay_font(font_path, fitted_size)
                trial_bbox = draw.textbbox((0, 0), new_text, font=font, stroke_width=stroke_width)
                rendered_width = max(1, trial_bbox[2] - trial_bbox[0])
                rendered_height = max(1, trial_bbox[3] - trial_bbox[1])
                if rendered_width <= int(text_width * width_scale) and rendered_height <= int(text_height * height_scale):
                    break
                fitted_size -= 1
            font = self._load_overlay_font(font_path, fitted_size)
            
            # Convert BGR to RGB for PIL
            color_rgb = (color[2], color[1], color[0])
            stroke_rgb = (stroke_color[2], stroke_color[1], stroke_color[0]) if stroke_color else None
            shadow_rgb = (shadow_color[2], shadow_color[1], shadow_color[0]) if shadow_color else None

            text_bbox = draw.textbbox((0, 0), new_text, font=font, stroke_width=stroke_width)
            rendered_width = max(1, text_bbox[2] - text_bbox[0])
            rendered_height = max(1, text_bbox[3] - text_bbox[1])

            if align == "center":
                text_x = max(0, (text_width - rendered_width) // 2 - text_bbox[0])
                text_y = max(0, (text_height - rendered_height) // 2 - text_bbox[1])
            else:
                text_x = max(0, -text_bbox[0])
                text_y = max(0, -text_bbox[1])
            
            if shadow_rgb and shadow_offset != (0, 0):
                draw.text(
                    (text_x + shadow_offset[0], text_y + shadow_offset[1]),
                    new_text,
                    font=font,
                    fill=shadow_rgb + (180,),
                    stroke_width=stroke_width,
                    stroke_fill=stroke_rgb,
                )

            draw.text(
                (text_x, text_y),
                new_text,
                font=font,
                fill=color_rgb + (255,),
                stroke_width=stroke_width,
                stroke_fill=stroke_rgb,
            )
            
            # Convert overlay to numpy and blend with original
            overlay_np = np.array(overlay)
            
            # Create mask for blending
            mask = overlay_np[:, :, 3] / 255.0
            mask = cv2.resize(mask, (text_width, text_height))
            
            # Blend text
            for c in range(3):
                result[y1:y2, x1:x2, c] = (
                    result[y1:y2, x1:x2, c] * (1 - alpha * mask) +
                    overlay_np[:text_height, :text_width, c] * alpha * mask
                )
            
            return result
            
        except Exception as e:
            print(f"Error overlaying text with PIL: {str(e)}")
            return self._overlay_text_opencv(result, new_text, bbox, color, font_size)
    
    def _overlay_text_opencv(self, image: np.ndarray, text: str,
                            bbox: Tuple[int, int, int, int],
                            color: Tuple[int, int, int],
                            font_size: int) -> np.ndarray:
        """
        Fallback text overlay using OpenCV.
        """
        x1, y1, x2, y2 = bbox
        
        # Calculate font scale based on bbox
        font_scale = min((x2 - x1) / (len(text) * 10), (y2 - y1) / 30)
        font_scale = max(font_scale, 0.3)
        
        # Put text at center of bbox
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)[0]
        text_x = x1 + (x2 - x1 - text_size[0]) // 2
        text_y = y1 + (y2 - y1 + text_size[1]) // 2
        
        cv2.putText(image, text, (text_x, text_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 2)
        
        return image
    
    def generate_stylized_text(self, context_image: np.ndarray, 
                              new_text: str,
                              bbox: Tuple[int, int, int, int],
                              style_prompt: str = "clean, professional, seamless") -> np.ndarray:
        """
        Generate stylized text using Stable Diffusion conditioned on context.
        
        Args:
            context_image (np.ndarray): Image to condition generation on
            new_text (str): Text to generate
            bbox (Tuple): Bounding box for text region
            style_prompt (str): Style description for generation
        
        Returns:
            np.ndarray: Generated text overlay
        """
        if self.text_generator_pipe is None:
            print("Text generation model not loaded. Using simple overlay instead.")
            return None
        
        try:
            x1, y1, x2, y2 = bbox
            text_width = x2 - x1
            text_height = y2 - y1
            
            # Create prompt for generation
            prompt = f"Text reading '{new_text}' in {style_prompt} style, {text_width}x{text_height}px"
            
            print(f"Generating stylized text: '{new_text}'...")
            
            # Generate at smaller size for efficiency
            with torch.no_grad():
                generated = self.text_generator_pipe(
                    prompt=prompt,
                    height=min(text_height, 256),
                    width=min(text_width, 512),
                    num_inference_steps=30,
                    guidance_scale=7.5
                ).images[0]
            
            # Resize to match bbox
            generated = generated.resize((text_width, text_height), Image.Resampling.LANCZOS)
            
            print("Text generation completed")
            return np.array(generated)
            
        except Exception as e:
            print(f"Error generating stylized text: {str(e)}")
            return None
    
    def process_frame(self, frame: np.ndarray, 
                     mask: np.ndarray,
                     new_text: str,
                     bbox: Tuple[int, int, int, int],
                     removal_method: str = "opencv",
                     inpainting_prompt: str = "clean background") -> dict:
        """
        Complete pipeline: remove text and overlay new text.
        
        Args:
            frame (np.ndarray): Input frame
            mask (np.ndarray): Text mask
            new_text (str): Text to overlay
            bbox (Tuple): Bounding box of text region
            removal_method (str): "opencv" or "diffusion" for text removal
            inpainting_prompt (str): Prompt for diffusion inpainting
        
        Returns:
            dict: Results with cleaned and final frames
        """
        print(f"Processing frame with new text: '{new_text}'")
        
        # Step 1: Remove text
        if removal_method.lower() == "diffusion":
            cleaned_frame = self.remove_text_inpainting(
                frame, mask, 
                prompt=inpainting_prompt
            )
        else:
            cleaned_frame = self.remove_text_opencv(frame, mask)
        
        # Step 2: Overlay new text
        final_frame = self.overlay_text(
            cleaned_frame, new_text, bbox,
            color=(0, 0, 0), font_size=20
        )
        
        return {
            'original': frame,
            'cleaned': cleaned_frame,
            'final': final_frame,
            'mask': mask
        }


# Example usage
if __name__ == "__main__":
    # Initialize processor
    processor = TextRemovalAndOverlay(device='cpu')
    
    # For diffusion-based removal (requires GPU):
    # processor.load_inpainting_model()
    # processor.load_text_generation_model()
    
    # Example usage:
    # frame = cv2.imread("frame.png")
    # mask = cv2.imread("mask.png", 0)
    # bbox = (100, 50, 300, 100)
    # 
    # results = processor.process_frame(
    #     frame, mask, "Both", bbox,
    #     removal_method="opencv"
    # )
    # 
    # cv2.imwrite("cleaned.png", results['cleaned'])
    # cv2.imwrite("final.png", results['final'])
