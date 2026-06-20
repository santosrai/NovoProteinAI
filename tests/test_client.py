"""Tests for PyMOL TCP client."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pymol_mcp.client import PyMOLClient
from pymol_mcp.config import PyMOLConfig


class TestPyMOLClient:
    """Test PyMOL client functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PyMOLConfig(
            host="localhost",
            port=9877,
            timeout=5.0,
            reconnect_attempts=2,
            reconnect_delay=0.1
        )
    
    @pytest.fixture
    def client(self, config):
        """Create test client."""
        return PyMOLClient(config)
    
    def test_client_initialization(self, client, config):
        """Test client initializes with config."""
        assert client.config == config
        assert client.socket is None
        assert client.connected is False
        assert client.request_id == 0
    
    @patch('socket.socket')
    def test_connect_success(self, mock_socket_class, client):
        """Test successful connection."""
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        
        result = client.connect()
        
        assert result is True
        assert client.connected is True
        mock_socket.connect.assert_called_once_with(("localhost", 9877))
    
    @patch('socket.socket')
    def test_connect_failure(self, mock_socket_class, client):
        """Test connection failure with retries."""
        mock_socket = Mock()
        mock_socket.connect.side_effect = ConnectionRefusedError()
        mock_socket_class.return_value = mock_socket
        
        result = client.connect()
        
        assert result is False
        assert client.connected is False
        assert mock_socket.connect.call_count == client.config.reconnect_attempts
    
    def test_disconnect(self, client):
        """Test disconnection."""
        client.socket = Mock()
        client.connected = True
        
        client.disconnect()
        
        assert client.connected is False
        client.socket.close.assert_called_once()
    
    @patch('socket.socket')
    def test_call_not_connected(self, mock_socket_class, client):
        """Test call when not connected."""
        mock_socket = Mock()
        mock_socket.connect.side_effect = ConnectionRefusedError()
        mock_socket_class.return_value = mock_socket
        
        response = client.call("ping")
        
        assert "error" in response
        assert response["error"]["code"] == -32300
    
    @patch('socket.socket')
    @patch('pymol_mcp.client.JSONRPCProtocol')
    def test_call_success(self, mock_protocol, mock_socket_class, client):
        """Test successful RPC call."""
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        
        mock_protocol.encode_message.return_value = b'test_request'
        mock_protocol.read_message.return_value = {
            "jsonrpc": "2.0",
            "result": {"status": "ok"},
            "id": 1
        }
        
        client.connected = True
        client.socket = mock_socket
        
        response = client.call("ping")
        
        assert "result" in response
        assert response["result"]["status"] == "ok"
        mock_socket.sendall.assert_called_once()
    
    @patch('socket.socket')
    @patch('pymol_mcp.client.JSONRPCProtocol')
    def test_call_error_response(self, mock_protocol, mock_socket_class, client):
        """Test call with error response from server."""
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        
        mock_protocol.encode_message.return_value = b'test_request'
        mock_protocol.read_message.return_value = {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": "Method not found"},
            "id": 1
        }
        
        client.connected = True
        client.socket = mock_socket
        
        response = client.call("invalid_method")
        
        assert "error" in response
        assert response["error"]["code"] == -32601
    
    @patch('socket.socket')
    def test_ping_success(self, mock_socket_class, client):
        """Test ping method."""
        with patch.object(client, 'call') as mock_call:
            mock_call.return_value = {
                "result": {"status": "ok", "version": "2.5.0"}
            }
            
            result = client.ping()
            
            assert result is True
            mock_call.assert_called_once_with("ping")
    
    @patch('socket.socket')
    def test_ping_failure(self, mock_socket_class, client):
        """Test ping method with failure."""
        with patch.object(client, 'call') as mock_call:
            mock_call.return_value = {
                "error": {"code": -32300, "message": "Not connected"}
            }
            
            result = client.ping()
            
            assert result is False
    
    def test_context_manager(self, client):
        """Test client as context manager."""
        with patch.object(client, 'connect') as mock_connect:
            with patch.object(client, 'disconnect') as mock_disconnect:
                with client:
                    pass
                
                mock_connect.assert_called_once()
                mock_disconnect.assert_called_once()
