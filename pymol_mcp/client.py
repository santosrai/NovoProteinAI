import socket
import struct
import json
import time
import logging
import threading
from typing import Optional, Dict, Any
from .config import PyMOLConfig

logger = logging.getLogger(__name__)


class JSONRPCProtocol:
    """Length-prefixed JSON-RPC 2.0 protocol handler (client side)."""
    
    @staticmethod
    def encode_message(message: Dict[str, Any]) -> bytes:
        """Encode a JSON-RPC message with 4-byte length prefix."""
        json_data = json.dumps(message).encode('utf-8')
        length = struct.pack('>I', len(json_data))
        return length + json_data
    
    @staticmethod
    def decode_message(data: bytes) -> Dict[str, Any]:
        """Decode a length-prefixed JSON-RPC message."""
        return json.loads(data.decode('utf-8'))
    
    @staticmethod
    def read_message(sock: socket.socket, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Read a complete length-prefixed message from socket."""
        sock.settimeout(timeout)
        try:
            length_data = sock.recv(4)
            if not length_data or len(length_data) < 4:
                return None
            
            length = struct.unpack('>I', length_data)[0]
            
            chunks = []
            bytes_received = 0
            while bytes_received < length:
                chunk = sock.recv(min(length - bytes_received, 4096))
                if not chunk:
                    return None
                chunks.append(chunk)
                bytes_received += len(chunk)
            
            data = b''.join(chunks)
            return JSONRPCProtocol.decode_message(data)
        except socket.timeout:
            logger.warning("Socket read timeout")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None


class PyMOLClient:
    """TCP client for communicating with PyMOL plugin."""
    
    def __init__(self, config: PyMOLConfig):
        self.config = config
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.request_id = 0
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        """Connect to PyMOL plugin with retry logic."""
        for attempt in range(self.config.reconnect_attempts):
            try:
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.config.host, self.config.port))
                self.connected = True
                logger.info(f"Connected to PyMOL at {self.config.host}:{self.config.port}")
                return True
            
            except (socket.error, ConnectionRefusedError) as e:
                logger.warning(f"Connection attempt {attempt + 1}/{self.config.reconnect_attempts} failed: {e}")
                if attempt < self.config.reconnect_attempts - 1:
                    time.sleep(self.config.reconnect_delay * (2 ** attempt))
        
        self.connected = False
        logger.error(f"Failed to connect to PyMOL after {self.config.reconnect_attempts} attempts")
        return False
    
    def disconnect(self):
        """Disconnect from PyMOL plugin."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False
        logger.info("Disconnected from PyMOL")
    
    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call a JSON-RPC method on PyMOL plugin."""
        with self._lock:
            return self._call_locked(method, params)

    def _call_locked(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.connected:
            if not self.connect():
                return {
                    "error": {
                        "code": -32300,
                        "message": "Not connected to PyMOL. Is the plugin running?"
                    }
                }
        
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self.request_id
        }
        
        try:
            request_data = JSONRPCProtocol.encode_message(request)
            self.socket.sendall(request_data)
            
            response = JSONRPCProtocol.read_message(self.socket, self.config.timeout)
            
            if not response:
                self.connected = False
                return {
                    "error": {
                        "code": -32300,
                        "message": "No response from PyMOL"
                    }
                }
            
            if "error" in response:
                logger.error(f"PyMOL error: {response['error']}")
            
            return response
        
        except socket.error as e:
            logger.error(f"Socket error during call: {e}")
            self.connected = False
            return {
                "error": {
                    "code": -32300,
                    "message": f"Connection error: {str(e)}"
                }
            }
        except Exception as e:
            logger.error(f"Error during call: {e}")
            return {
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }
    
    def ping(self) -> bool:
        """Check if PyMOL is responding."""
        response = self.call("ping")
        return "result" in response and response["result"].get("status") == "ok"
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


_client_instance: Optional[PyMOLClient] = None


def get_client(config: Optional[PyMOLConfig] = None) -> PyMOLClient:
    """Get or create singleton PyMOL client."""
    global _client_instance
    
    if _client_instance is None:
        if config is None:
            config = PyMOLConfig.load()
        _client_instance = PyMOLClient(config)
    
    return _client_instance
