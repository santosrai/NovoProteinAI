import os
import socket
import struct
import json
import queue
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any

try:
    from pymol import cmd
    PYMOL_AVAILABLE = True
except ImportError:
    PYMOL_AVAILABLE = False
    cmd = None

try:
    from pymol.Qt import QtWidgets, QtCore, QtGui
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False
    QtWidgets = None
    QtCore = None
    QtGui = None

try:
    import websocket  # from the `websocket-client` package
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    websocket = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_log_queue: "queue.Queue[str]" = queue.Queue()


def _log(message: str):
    """Push a timestamped message to the activity log queue and console."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}"
    try:
        _log_queue.put_nowait(entry)
    except queue.Full:
        pass
    logger.info(message)


# Structure file extensions PyMOL can load from disk (lower-case, without an
# optional trailing ".gz"). Used to decide whether a source string is a local
# file path versus a PDB ID to fetch from the network.
STRUCTURE_EXTENSIONS = (
    ".pdb", ".ent", ".cif", ".mmcif", ".mcif",
    ".mol2", ".mol", ".sdf", ".xyz", ".pdbqt", ".mae",
)


def _sanitize_object_name(name: str) -> str:
    """Make a string safe to use as a PyMOL object name.

    PyMOL object names should avoid whitespace and characters that have
    meaning in selection expressions, so we replace anything that is not
    alphanumeric or an underscore with an underscore.
    """
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in name).strip("_")
    return safe or "structure"


def _looks_like_structure_file(source: str) -> bool:
    """Heuristic: does this source string refer to a local file path?

    True if it has a known structure extension (optionally gzipped) or it
    otherwise looks like a path (contains a separator or starts with ~).
    """
    lowered = source.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    if lowered.endswith(STRUCTURE_EXTENSIONS):
        return True
    return "/" in source or "\\" in source or source.startswith("~")


def resolve_structure_source(source: str, object_name: str = "") -> Dict[str, Any]:
    """Decide how to load ``source`` and validate it (no PyMOL needed).

    Returns a dict describing the action:
      - {"error": "..."} when the input is invalid or the file is missing.
      - {"mode": "load", "path": <abs path>, "object_name": <name>} for a
        local file (PDB/CIF/etc.), including non-PDB CIF files.
      - {"mode": "fetch", "source": <id>, "object_name": <name>} for a PDB ID.

    Kept free of any PyMOL imports so it can be unit-tested directly.
    """
    if not source or not source.strip():
        return {"error": "Missing required parameter: source"}

    source = source.strip()

    if _looks_like_structure_file(source):
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(source)))
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        if not os.path.isfile(path):
            return {"error": f"Not a file: {path}"}

        if object_name:
            obj = object_name
        else:
            base = os.path.basename(path)
            if base.lower().endswith(".gz"):
                base = base[:-3]
            obj = os.path.splitext(base)[0]

        return {
            "mode": "load",
            "path": path,
            "object_name": _sanitize_object_name(obj),
        }

    # Otherwise treat it as a PDB ID to fetch from the network.
    return {
        "mode": "fetch",
        "source": source,
        "object_name": object_name or source,
    }


class JSONRPCProtocol:
    """Length-prefixed JSON-RPC 2.0 protocol handler."""
    
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


class PyMOLCommandHandler:
    """Handles PyMOL command execution."""
    
    @staticmethod
    def execute(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a PyMOL command and return result."""
        if not PYMOL_AVAILABLE:
            return {
                "error": {
                    "code": -32000,
                    "message": "PyMOL not available"
                }
            }
        
        try:
            if method == "ping":
                return {
                    "result": {
                        "status": "ok",
                        "version": cmd.get_version()[0] if hasattr(cmd, 'get_version') else "unknown"
                    }
                }
            
            elif method == "load_structure":
                source = params.get("source")
                object_name = params.get("object_name", "") or ""

                resolved = resolve_structure_source(source or "", object_name)

                if "error" in resolved:
                    return {
                        "error": {
                            "code": -32602,
                            "message": resolved["error"]
                        }
                    }

                obj_name = resolved["object_name"]
                if resolved["mode"] == "load":
                    cmd.load(resolved["path"], obj_name)
                    message = f"Loaded structure from file: {obj_name}"
                else:
                    cmd.fetch(resolved["source"], obj_name)
                    message = f"Fetched structure: {obj_name}"

                return {
                    "result": {
                        "message": message,
                        "object_name": obj_name
                    }
                }
            
            elif method == "select_atoms":
                selection_name = params.get("selection_name")
                selection_expr = params.get("selection_expr")
                
                if not selection_name or not selection_expr:
                    return {
                        "error": {
                            "code": -32602,
                            "message": "Missing required parameters: selection_name, selection_expr"
                        }
                    }
                
                count = cmd.select(selection_name, selection_expr)
                return {
                    "result": {
                        "message": f"Selected {count} atoms",
                        "count": count,
                        "selection_name": selection_name
                    }
                }
            
            elif method == "color_selection":
                color = params.get("color")
                selection = params.get("selection", "all")
                
                if not color:
                    return {
                        "error": {
                            "code": -32602,
                            "message": "Missing required parameter: color"
                        }
                    }
                
                cmd.color(color, selection)
                return {
                    "result": {
                        "message": f"Colored {selection} with {color}"
                    }
                }
            
            elif method == "rotate":
                axis = params.get("axis", "y")
                angle = params.get("angle", 90)
                selection = params.get("selection", "")

                if axis not in ("x", "y", "z"):
                    return {
                        "error": {
                            "code": -32602,
                            "message": "Invalid axis: must be one of 'x', 'y', 'z'"
                        }
                    }

                try:
                    angle = float(angle)
                except (TypeError, ValueError):
                    return {
                        "error": {
                            "code": -32602,
                            "message": "Invalid angle: must be a number"
                        }
                    }

                if selection:
                    cmd.rotate(axis, angle, selection)
                    target = selection
                else:
                    cmd.turn(axis, angle)
                    target = "camera"

                return {
                    "result": {
                        "message": f"Rotated {target} by {angle} degrees about {axis}-axis",
                        "axis": axis,
                        "angle": angle,
                        "selection": selection or None
                    }
                }

            elif method == "render_image":
                output_path = params.get("output_path")
                width = params.get("width", 800)
                height = params.get("height", 600)
                ray_trace = params.get("ray_trace", False)
                
                if not output_path:
                    return {
                        "error": {
                            "code": -32602,
                            "message": "Missing required parameter: output_path"
                        }
                    }
                
                cmd.viewport(width, height)
                
                if ray_trace:
                    cmd.ray(width, height)
                
                cmd.png(output_path)
                
                return {
                    "result": {
                        "message": f"Rendered image to {output_path}",
                        "path": output_path,
                        "width": width,
                        "height": height,
                        "ray_traced": ray_trace
                    }
                }
            
            else:
                return {
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
        
        except Exception as e:
            logger.error(f"Error executing {method}: {e}")
            return {
                "error": {
                    "code": -32000,
                    "message": f"PyMOL execution error: {str(e)}"
                }
            }


class PyMOLTCPServer:
    """TCP server for PyMOL plugin."""
    
    def __init__(self, host: str = "localhost", port: int = 9877):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.client_count = 0
        
    def start(self):
        """Start the TCP server."""
        if self.running:
            logger.warning("Server already running")
            return
        
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            
            self.thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.thread.start()
            
            _log(f"Server started on {self.host}:{self.port}")
            if PYMOL_AVAILABLE:
                print(f"PyMOL MCP Plugin: Server started on {self.host}:{self.port}")
        
        except Exception as e:
            _log(f"Failed to start server: {e}")
            self.running = False
            raise
    
    def stop(self):
        """Stop the TCP server."""
        if not self.running:
            return
        
        self.running = False
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        _log("Server stopped")
        if PYMOL_AVAILABLE:
            print("PyMOL MCP Plugin: Server stopped")
    
    def _accept_loop(self):
        """Accept incoming connections."""
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                try:
                    client_socket, address = self.server_socket.accept()
                    _log(f"Client connected from {address[0]}:{address[1]}")
                    
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket,),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
            
            except Exception as e:
                if self.running:
                    logger.error(f"Error in accept loop: {e}")
                break
    
    def _handle_client(self, client_socket: socket.socket):
        """Handle a client connection."""
        self.client_count += 1
        try:
            while self.running:
                request = JSONRPCProtocol.read_message(client_socket)
                
                if not request:
                    break
                
                if not isinstance(request, dict) or "jsonrpc" not in request:
                    response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32600,
                            "message": "Invalid Request"
                        },
                        "id": request.get("id") if isinstance(request, dict) else None
                    }
                else:
                    method = request.get("method")
                    params = request.get("params", {})
                    request_id = request.get("id")
                    
                    result = PyMOLCommandHandler.execute(method, params)
                    
                    if "error" in result:
                        _log(f"\u2717 {method} \u2192 error: {result['error'].get('message')}")
                    else:
                        _log(f"\u2713 {method} \u2192 ok")
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id
                    }
                    response.update(result)
                
                response_data = JSONRPCProtocol.encode_message(response)
                client_socket.sendall(response_data)
        
        except Exception as e:
            _log(f"Error handling client: {e}")
        
        finally:
            self.client_count -= 1
            try:
                client_socket.close()
            except:
                pass
            _log("Client disconnected")
    
    def get_status(self) -> str:
        """Get server status."""
        if self.running:
            return f"Running on {self.host}:{self.port} ({self.client_count} clients)"
        return "Stopped"


class PyMOLRelayClient:
    """Outbound WebSocket client to a public NovoProteinAI relay.

    Used when the agent is deployed publicly (e.g. Railway). PyMOL runs locally
    and dials *out* to wss://<app>/plugin?token=<token>, then waits for JSON-RPC
    commands and replies using the same PyMOLCommandHandler as the TCP server.
    Outbound connections work from behind NAT, so no port-forwarding is needed.
    """

    def __init__(self, url: str, token: str):
        self.base_url = url.rstrip("/")
        self.token = token
        self.ws_app: Optional["websocket.WebSocketApp"] = None
        self.thread: Optional[threading.Thread] = None
        self.connected = False
        self._should_run = False

    @property
    def full_url(self) -> str:
        return f"{self.base_url}?token={self.token}"

    def _on_open(self, ws):
        self.connected = True
        _log(f"Relay connected: {self.base_url} (token={self.token})")

    def _on_close(self, ws, status_code, msg):
        self.connected = False
        _log(f"Relay disconnected (code={status_code})")

    def _on_error(self, ws, error):
        self.connected = False
        _log(f"Relay error: {error}")

    def _on_message(self, ws, raw):
        """Execute an incoming JSON-RPC command and send the reply back."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            _log("Relay: dropped non-JSON frame")
            return

        method = msg.get("method")
        params = msg.get("params", {})
        request_id = msg.get("id")

        result = PyMOLCommandHandler.execute(method, params)

        if "error" in result:
            _log(f"\u2717 {method} \u2192 error: {result['error'].get('message')}")
        else:
            _log(f"\u2713 {method} \u2192 ok")

        response = {"jsonrpc": "2.0", "id": request_id}
        response.update(result)
        try:
            ws.send(json.dumps(response))
        except Exception as exc:
            _log(f"Relay: failed to send reply: {exc}")

    def _run_forever(self):
        """Reconnecting run loop (websocket-client handles the socket)."""
        while self._should_run:
            self.ws_app = websocket.WebSocketApp(
                self.full_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_close=self._on_close,
                on_error=self._on_error,
            )
            self.ws_app.run_forever(ping_interval=30, ping_timeout=10)
            if self._should_run:
                _log("Relay: reconnecting in 3s...")
                threading.Event().wait(3)

    def start(self):
        """Open the outbound WebSocket connection (non-blocking)."""
        if not WEBSOCKET_AVAILABLE:
            raise RuntimeError(
                "websocket-client is not installed in PyMOL's Python. "
                "Install it with: pip install websocket-client"
            )
        if self._should_run:
            _log("Relay client already running")
            return
        self._should_run = True
        self.thread = threading.Thread(target=self._run_forever, daemon=True)
        self.thread.start()
        _log(f"Relay client starting -> {self.base_url}")

    def stop(self):
        """Close the WebSocket connection."""
        self._should_run = False
        if self.ws_app:
            try:
                self.ws_app.close()
            except Exception:
                pass
        self.connected = False
        _log("Relay client stopped")

    def get_status(self) -> str:
        if self.connected:
            return f"Connected to {self.base_url} (token={self.token})"
        if self._should_run:
            return f"Connecting to {self.base_url}..."
        return "Disconnected"


class PyMOLMCPDialog(QtWidgets.QDialog if QT_AVAILABLE else object):
    """Control panel dialog for the PyMOL MCP Bridge."""

    MAX_LOG_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PyMOL MCP Bridge")
        self.setMinimumWidth(440)
        self.setMinimumHeight(420)

        self._init_ui()

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        self._update_status()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout()

        title = QtWidgets.QLabel("<h2>PyMOL MCP Bridge</h2>")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Exposes PyMOL as MCP tools to LLM agents"
        )
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(subtitle)

        status_group = QtWidgets.QGroupBox("Server Status")
        status_layout = QtWidgets.QVBoxLayout()
        self.status_label = QtWidgets.QLabel("Status: -")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.port_label = QtWidgets.QLabel("Port: -")
        self.clients_label = QtWidgets.QLabel("Connected clients: 0")
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.port_label)
        status_layout.addWidget(self.clients_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        button_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start Server")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;"
        )
        self.stop_btn = QtWidgets.QPushButton("Stop Server")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setStyleSheet(
            "background-color: #f44336; color: white; padding: 8px; font-weight: bold;"
        )
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        layout.addLayout(button_layout)

        # --- Cloud relay (connect to a public NovoProteinAI agent) ---
        relay_group = QtWidgets.QGroupBox("Cloud Relay (public agent)")
        relay_layout = QtWidgets.QVBoxLayout()

        self.relay_status_label = QtWidgets.QLabel("Relay: Disconnected")
        self.relay_status_label.setStyleSheet("font-weight: bold;")
        relay_layout.addWidget(self.relay_status_label)

        url_row = QtWidgets.QHBoxLayout()
        url_row.addWidget(QtWidgets.QLabel("Relay URL:"))
        self.relay_url_edit = QtWidgets.QLineEdit()
        self.relay_url_edit.setPlaceholderText("wss://yourapp.up.railway.app/plugin")
        url_row.addWidget(self.relay_url_edit)
        relay_layout.addLayout(url_row)

        token_row = QtWidgets.QHBoxLayout()
        token_row.addWidget(QtWidgets.QLabel("Token:"))
        self.relay_token_edit = QtWidgets.QLineEdit()
        self.relay_token_edit.setPlaceholderText("your-pairing-token")
        token_row.addWidget(self.relay_token_edit)
        relay_layout.addLayout(token_row)

        relay_btn_row = QtWidgets.QHBoxLayout()
        self.relay_connect_btn = QtWidgets.QPushButton("Connect")
        self.relay_connect_btn.clicked.connect(self._on_relay_connect)
        self.relay_connect_btn.setStyleSheet(
            "background-color: #2196F3; color: white; padding: 8px; font-weight: bold;"
        )
        self.relay_disconnect_btn = QtWidgets.QPushButton("Disconnect")
        self.relay_disconnect_btn.clicked.connect(self._on_relay_disconnect)
        self.relay_disconnect_btn.setStyleSheet(
            "background-color: #9E9E9E; color: white; padding: 8px; font-weight: bold;"
        )
        relay_btn_row.addWidget(self.relay_connect_btn)
        relay_btn_row.addWidget(self.relay_disconnect_btn)
        relay_layout.addLayout(relay_btn_row)

        relay_group.setLayout(relay_layout)
        layout.addWidget(relay_group)

        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        log_layout.addWidget(self.log_view)
        clear_btn = QtWidgets.QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_view.clear)
        log_layout.addWidget(clear_btn)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.setLayout(layout)

    def _tick(self):
        self._update_status()
        self._update_relay_status()
        self._drain_log()

    def _update_relay_status(self):
        relay = _relay_instance
        if not relay:
            self.relay_status_label.setText("Relay: Disconnected")
            self.relay_status_label.setStyleSheet("color: gray; font-weight: bold;")
            self.relay_connect_btn.setEnabled(True)
            self.relay_disconnect_btn.setEnabled(False)
            return

        if relay.connected:
            self.relay_status_label.setText(f"Relay: Connected (token={relay.token})")
            self.relay_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.relay_connect_btn.setEnabled(False)
            self.relay_disconnect_btn.setEnabled(True)
        elif relay._should_run:
            self.relay_status_label.setText("Relay: Connecting...")
            self.relay_status_label.setStyleSheet("color: orange; font-weight: bold;")
            self.relay_connect_btn.setEnabled(False)
            self.relay_disconnect_btn.setEnabled(True)
        else:
            self.relay_status_label.setText("Relay: Disconnected")
            self.relay_status_label.setStyleSheet("color: gray; font-weight: bold;")
            self.relay_connect_btn.setEnabled(True)
            self.relay_disconnect_btn.setEnabled(False)

    def _update_status(self):
        server = _server_instance
        if not server:
            self.status_label.setText("Status: Not initialized")
            self.status_label.setStyleSheet(
                "color: red; font-weight: bold; font-size: 14px;"
            )
            self.port_label.setText("Port: -")
            self.clients_label.setText("Connected clients: 0")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        if server.running:
            self.status_label.setText("Status: Running")
            self.status_label.setStyleSheet(
                "color: green; font-weight: bold; font-size: 14px;"
            )
            self.port_label.setText(f"Port: {server.port}")
            self.clients_label.setText(f"Connected clients: {server.client_count}")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_label.setText("Status: Stopped")
            self.status_label.setStyleSheet(
                "color: orange; font-weight: bold; font-size: 14px;"
            )
            self.port_label.setText(f"Port: {server.port} (not listening)")
            self.clients_label.setText("Connected clients: 0")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _drain_log(self):
        appended = False
        while True:
            try:
                entry = _log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_view.appendPlainText(entry)
            appended = True

        if appended:
            doc = self.log_view.document()
            if doc.blockCount() > self.MAX_LOG_LINES:
                cursor = self.log_view.textCursor()
                cursor.movePosition(QtGui.QTextCursor.Start)
                excess = doc.blockCount() - self.MAX_LOG_LINES
                for _ in range(excess):
                    cursor.select(QtGui.QTextCursor.BlockUnderCursor)
                    cursor.removeSelectedText()
                    cursor.deleteChar()
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_start(self):
        try:
            start_server()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to start server:\n{e}\n\n"
                "Make sure the port is not already in use.",
            )
        self._update_status()

    def _on_stop(self):
        stop_server()
        self._update_status()

    def _on_relay_connect(self):
        url = self.relay_url_edit.text().strip()
        token = self.relay_token_edit.text().strip()
        if not url or not token:
            QtWidgets.QMessageBox.warning(
                self, "Missing info", "Enter both a Relay URL and a Token."
            )
            return
        try:
            start_relay(url, token)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to connect to relay:\n{e}"
            )
        self._update_relay_status()

    def _on_relay_disconnect(self):
        stop_relay()
        self._update_relay_status()


_server_instance: Optional[PyMOLTCPServer] = None
_relay_instance: Optional[PyMOLRelayClient] = None
_dialog_instance: Optional["PyMOLMCPDialog"] = None


def start_relay(url: str, token: str):
    """Connect the plugin out to a public relay (cloud agent)."""
    global _relay_instance

    if _relay_instance and _relay_instance._should_run:
        print("Relay client already running; stopping the previous one.")
        _relay_instance.stop()

    _relay_instance = PyMOLRelayClient(url, token)
    _relay_instance.start()


def stop_relay():
    """Disconnect the plugin from the relay."""
    global _relay_instance

    if not _relay_instance:
        print("Relay client is not running")
        return

    _relay_instance.stop()


def __init_plugin__(app=None):
    """PyMOL plugin initialization."""
    from pymol.plugins import addmenuitemqt

    addmenuitemqt('Control Panel', show_dialog)
    addmenuitemqt('Start Server (local)', start_server)
    addmenuitemqt('Stop Server (local)', stop_server)
    addmenuitemqt('Server Status', show_status)

    # Auto-start TCP server on plugin load
    start_server()


def show_dialog():
    """Open the control panel dialog."""
    global _server_instance, _dialog_instance

    if not QT_AVAILABLE:
        print("Qt not available; falling back to console status.")
        show_status()
        return

    if not _server_instance:
        _server_instance = PyMOLTCPServer()

    if _dialog_instance is None:
        _dialog_instance = PyMOLMCPDialog()

    _dialog_instance.show()
    _dialog_instance.raise_()
    _dialog_instance.activateWindow()


def start_server():
    """Start the TCP server."""
    global _server_instance

    if _server_instance and _server_instance.running:
        print("Server is already running")
        return

    if not _server_instance:
        _server_instance = PyMOLTCPServer()
    _server_instance.start()


def stop_server():
    """Stop the TCP server."""
    global _server_instance

    if not _server_instance or not _server_instance.running:
        print("Server is not running")
        return

    _server_instance.stop()


def show_status():
    """Print server status to the PyMOL console."""
    global _server_instance

    print("=" * 50)
    print("PyMOL MCP Bridge - Server Status")
    print("=" * 50)
    if not _server_instance:
        print("Status: Not initialized")
    else:
        print(f"Status: {_server_instance.get_status()}")
        print(f"Host: {_server_instance.host}")
        print(f"Port: {_server_instance.port}")
        print(f"Connected clients: {_server_instance.client_count}")

    if not _server_instance or not _server_instance.running:
        print("\nTo start the server:")
        print("  Plugin -> agentic-pymol plugin -> Control Panel")
        print("  or Plugin -> agentic-pymol plugin -> Start Server")
    else:
        print("\nServer is ready for MCP client connections on "
              f"localhost:{_server_instance.port}")
    print("=" * 50)
