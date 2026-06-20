import os
import yaml
from typing import Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PyMOLConfig:
    """Configuration for PyMOL MCP server."""
    host: str = "localhost"
    port: int = 9877
    timeout: float = 30.0
    reconnect_attempts: int = 3
    reconnect_delay: float = 1.0
    log_level: str = "INFO"
    
    @classmethod
    def from_env(cls) -> "PyMOLConfig":
        """Load configuration from environment variables."""
        return cls(
            host=os.getenv("PYMOL_HOST", "localhost"),
            port=int(os.getenv("PYMOL_PORT", "9877")),
            timeout=float(os.getenv("PYMOL_TIMEOUT", "30.0")),
            reconnect_attempts=int(os.getenv("PYMOL_RECONNECT_ATTEMPTS", "3")),
            reconnect_delay=float(os.getenv("PYMOL_RECONNECT_DELAY", "1.0")),
            log_level=os.getenv("PYMOL_LOG_LEVEL", "INFO")
        )
    
    @classmethod
    def from_file(cls, config_path: str) -> "PyMOLConfig":
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
            
            return cls(
                host=data.get("host", "localhost"),
                port=data.get("port", 9877),
                timeout=data.get("timeout", 30.0),
                reconnect_attempts=data.get("reconnect_attempts", 3),
                reconnect_delay=data.get("reconnect_delay", 1.0),
                log_level=data.get("log_level", "INFO")
            )
        except FileNotFoundError:
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return cls()
        except Exception as e:
            logger.error(f"Error loading config file: {e}, using defaults")
            return cls()
    
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "PyMOLConfig":
        """Load configuration with priority: file > env > defaults."""
        if config_path and os.path.exists(config_path):
            config = cls.from_file(config_path)
        else:
            config = cls.from_env()
        
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper(), logging.INFO),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        return config
