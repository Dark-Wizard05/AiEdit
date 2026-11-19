"""
Centralized logging configuration for AiEdit
Logs to both console and rotating file handlers with timestamp and level info
"""

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
import json


# Create logs directory
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Log file paths
MAIN_LOG_FILE = LOG_DIR / f"aiedit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"
SESSION_LOG_FILE = LOG_DIR / "sessions.json"


def get_logger(name: str, level=logging.INFO) -> logging.Logger:
    """
    Get or create a logger with file and console handlers.
    
    Args:
        name (str): Logger name (usually __name__)
        level: Logging level
    
    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Skip if handlers already added
    if logger.handlers:
        return logger
    
    # Format
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler (main log) - UTF-8 encoding
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            MAIN_LOG_FILE,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not create file logger: {e}")
    
    # Error file handler - UTF-8 encoding
    try:
        error_handler = logging.handlers.RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        logger.addHandler(error_handler)
    except Exception as e:
        print(f"Warning: Could not create error logger: {e}")
    
    # Console handler - UTF-8 encoding for Windows compatibility
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    # Set encoding for Windows console
    if hasattr(console_handler.stream, 'reconfigure'):
        console_handler.stream.reconfigure(encoding='utf-8')
    logger.addHandler(console_handler)
    
    return logger


def log_session(video_path: str, command: str, status: str, 
                details: dict = None) -> None:
    """
    Log a processing session to JSON for audit trail.
    
    Args:
        video_path (str): Input video path
        command (str): Processing command
        status (str): "started", "completed", "failed"
        details (dict): Additional details
    """
    try:
        session_data = {
            "timestamp": datetime.now().isoformat(),
            "video": str(video_path),
            "command": command,
            "status": status,
            "details": details or {}
        }
        
        # Append to session log
        sessions = []
        if SESSION_LOG_FILE.exists():
            with open(SESSION_LOG_FILE, 'r') as f:
                sessions = json.load(f)
        
        sessions.append(session_data)
        
        with open(SESSION_LOG_FILE, 'w') as f:
            json.dump(sessions, f, indent=2)
    
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Failed to log session: {str(e)}")


EVENT_LOG_FILE = LOG_DIR / "events.jsonl"


def log_event(stage: str, **fields) -> None:
    """Append one structured event line to ``logs/events.jsonl``.

    Phase 5 helper for operations metrics: stage names like ``parse``,
    ``mask``, ``export``, plus arbitrary fields (``session_id``, ``duration_ms``,
    ``error``...). Best-effort: never raises.
    """

    try:
        record = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "stage": stage,
        }
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value
            else:
                record[key] = str(value)
        EVENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(EVENT_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


def get_recent_logs(num_lines: int = 100) -> str:
    """Get last N lines from main log file."""
    try:
        if MAIN_LOG_FILE.exists():
            with open(MAIN_LOG_FILE, 'r') as f:
                lines = f.readlines()
                return ''.join(lines[-num_lines:])
    except Exception as e:
        return f"Error reading logs: {str(e)}"
    
    return "No logs available yet"


def get_error_logs(num_lines: int = 50) -> str:
    """Get last N lines from error log file."""
    try:
        if ERROR_LOG_FILE.exists():
            with open(ERROR_LOG_FILE, 'r') as f:
                lines = f.readlines()
                return ''.join(lines[-num_lines:])
    except Exception as e:
        return f"Error reading logs: {str(e)}"
    
    return "No errors logged yet"


def get_session_history() -> list:
    """Get all session history."""
    try:
        if SESSION_LOG_FILE.exists():
            with open(SESSION_LOG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Failed to read session history: {str(e)}")
    
    return []


def clear_old_logs(days: int = 7) -> None:
    """Delete log files older than N days."""
    from datetime import timedelta
    import os
    
    try:
        cutoff = datetime.now() - timedelta(days=days)
        
        for log_file in LOG_DIR.glob("aiedit_*.log"):
            if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff:
                os.remove(log_file)
                logger = get_logger(__name__)
                logger.info(f"Deleted old log: {log_file}")
    
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error clearing old logs: {str(e)}")


# Create default logger
logger = get_logger("aiedit")

if __name__ == "__main__":
    # Test logging
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    
    log_session("test_video.mp4", "test command", "completed", 
                {"frames": 100, "time": 5.2})
    
    print(f"\n✓ Logs stored in: {LOG_DIR}")
    print(f"  Main log: {MAIN_LOG_FILE}")
    print(f"  Error log: {ERROR_LOG_FILE}")
    print(f"  Sessions: {SESSION_LOG_FILE}")
