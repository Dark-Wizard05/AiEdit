import os
from pathlib import Path
import cv2
import logging
import ffmpeg

# Import centralized logging
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def _ffmpeg_cmd() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"



def extract_frames(video_path: str, output_folder: str, fps: int = 30) -> bool:
    """
    Extract frames from a video file using FFmpeg.
    
    Args:
        video_path (str): Path to the input video file
        output_folder (str): Path to the folder where frames will be saved
        fps (int): Frames per second to extract (default: 30)
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        extract_frames('video.mp4', 'frames/', fps=30)
    """
    try:
        # Create output folder if it doesn't exist
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        
        # Define output pattern for frames (e.g., frame_001.png, frame_002.png)
        output_pattern = os.path.join(output_folder, 'frame_%04d.png')
        
        logger.info(f"Extracting frames from {video_path} at {fps} FPS to {output_folder}")
        
        try:
            # Try FFmpeg first (faster, requires FFmpeg installed)
            import ffmpeg
            (
                ffmpeg
                .input(video_path)
                .filter('fps', fps=fps)
                .output(output_pattern)
                .run(
                    cmd=_ffmpeg_cmd(),
                    capture_stdout=True,
                    capture_stderr=True,
                    quiet=True,
                    overwrite_output=True,
                )
            )
            logger.info("[OK] FFmpeg extraction successful")
        except Exception as ffmpeg_error:
            # Fallback to OpenCV if FFmpeg fails
            logger.warning(f"FFmpeg not available, falling back to OpenCV: {str(ffmpeg_error)}")
            
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error(f"Cannot open video file {video_path}")
                return False
            
            frame_count = 0
            frame_idx = 0
            video_fps = cap.get(cv2.CAP_PROP_FPS)
            frame_interval = max(1, int(video_fps / fps))
            logger.info(f"Video FPS: {video_fps}, Frame interval: {frame_interval}")
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if frame_count % frame_interval == 0:
                    output_path = os.path.join(output_folder, f'frame_{frame_idx:04d}.png')
                    cv2.imwrite(output_path, frame)
                    frame_idx += 1
                
                frame_count += 1
            
            cap.release()
            logger.info(f"[OK] OpenCV extraction successful: {frame_idx} frames extracted")
        
        frame_count = len([f for f in os.listdir(output_folder) if f.endswith('.png')])
        logger.info(f"[OK] Total {frame_count} frames extracted to {output_folder}")
        return True
        
    except ffmpeg.Error as e:
        logger.error(f"FFmpeg error: {e.stderr.decode()}")
        return False
    except Exception as e:
        logger.error(f"Error extracting frames: {str(e)}", exc_info=True)
        return False


def _sorted_frame_files(frames_folder: str):
    return sorted(Path(frames_folder).glob("frame_*.png"))


def reassemble_frames(
    frames_folder: str,
    output_video: str,
    fps: int = 30,
    codec: str = "libx264",
    audio_source: str = None,
) -> bool:
    """
    Reassemble frames back into a video file using FFmpeg.
    
    Args:
        frames_folder (str): Path to the folder containing frames
        output_video (str): Path to the output video file
        fps (int): Frames per second for output video (default: 30)
        codec (str): Video codec to use (default: 'libx264' for H.264)
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        reassemble_frames('frames/', 'output.mp4', fps=30, codec='libx264')
    """
    try:
        frame_files = _sorted_frame_files(frames_folder)
        
        logger.info(f"Reassembling frames from {frames_folder} to {output_video}")
        logger.info(f"Output FPS: {fps}, Codec: {codec}")
        
        if not frame_files:
            logger.error(f"No frames found in {frames_folder}")
            return False

        first_frame = frame_files[0]
        input_pattern = os.path.join(frames_folder, "frame_%04d.png")
        try:
            start_number = int(first_frame.stem.split("_")[-1])
        except ValueError:
            start_number = 0

        try:
            video_stream = ffmpeg.input(
                input_pattern,
                framerate=fps,
                start_number=start_number,
            ).video

            if audio_source and Path(audio_source).exists():
                audio_stream = ffmpeg.input(audio_source).audio
                (
                    ffmpeg
                    .output(
                        video_stream,
                        audio_stream,
                        output_video,
                        vcodec=codec,
                        acodec="aac",
                        pix_fmt="yuv420p",
                        shortest=None,
                    )
                    .run(
                        cmd=_ffmpeg_cmd(),
                        overwrite_output=True,
                        capture_stdout=True,
                        capture_stderr=True,
                        quiet=True,
                    )
                )
            else:
                (
                    ffmpeg
                    .output(video_stream, output_video, vcodec=codec, pix_fmt="yuv420p")
                    .run(
                        cmd=_ffmpeg_cmd(),
                        overwrite_output=True,
                        capture_stdout=True,
                        capture_stderr=True,
                        quiet=True,
                    )
                )
        except Exception as e:
            stderr = e.stderr.decode() if isinstance(e, ffmpeg.Error) and e.stderr else str(e)
            logger.warning(f"FFmpeg reassembly failed, falling back to OpenCV: {stderr}")

            sample = cv2.imread(str(first_frame))
            if sample is None:
                logger.error("Could not read first frame for fallback reassembly")
                return False

            height, width = sample.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(output_video, fourcc, fps, (width, height))

            for frame_file in frame_files:
                frame = cv2.imread(str(frame_file))
                if frame is None:
                    logger.warning(f"Skipping unreadable frame during reassembly: {frame_file}")
                    continue
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)

            writer.release()
        
        if os.path.exists(output_video):
            file_size = os.path.getsize(output_video) / (1024 * 1024)  # Size in MB
            logger.info(f"[OK] Video created: {output_video} ({file_size:.2f} MB)")
            return True
        else:
            logger.error("Video creation failed")
            return False
            
    except Exception as e:
        logger.error(f"Error reassembling frames: {str(e)}", exc_info=True)
        return False


if __name__ == "__main__":
    # Example usage
    video_file = "input_video.mp4"
    frames_dir = "extracted_frames/"
    output_file = "output_video.mp4"
    
    # Extract frames
    if extract_frames(video_file, frames_dir, fps=30):
        # Reassemble frames
        reassemble_frames(frames_dir, output_file, fps=30)
