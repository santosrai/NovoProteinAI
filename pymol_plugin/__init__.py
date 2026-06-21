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
                object_name = params.get("object_name", "")
                
                if not source:
                    return {
                        "error": {
                            "code": -32602,
                            "message": "Missing required parameter: source"
                        }
                    }
                
                if source.endswith(('.pdb', '.cif', '.mol2', '.sdf')):
                    cmd.load(source, object_name or None)
                    obj_name = object_name or source.split('/')[-1].split('.')[0]
                else:
                    cmd.fetch(source, object_name or source)
                    obj_name = object_name or source
                
                return {
                    "result": {
                        "message": f"Loaded structure: {obj_name}",
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
        self._drain_log()

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


_server_instance: Optional[PyMOLTCPServer] = None
_dialog_instance: Optional["PyMOLMCPDialog"] = None


def __init_plugin__(app=None):
    """PyMOL plugin initialization."""
    from pymol.plugins import addmenuitemqt

    addmenuitemqt('Control Panel', show_dialog)
    addmenuitemqt('Start Server', start_server)
    addmenuitemqt('Stop Server', stop_server)
    addmenuitemqt('Server Status', show_status)


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
