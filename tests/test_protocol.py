"""Tests for JSON-RPC protocol encoding/decoding."""

import struct
import json
import pytest
from pymol_mcp.client import JSONRPCProtocol


class TestJSONRPCProtocol:
    """Test JSON-RPC protocol utilities."""
    
    def test_encode_message(self):
        """Test message encoding with length prefix."""
        message = {"jsonrpc": "2.0", "method": "ping", "id": 1}
        encoded = JSONRPCProtocol.encode_message(message)
        
        length = struct.unpack('>I', encoded[:4])[0]
        json_data = encoded[4:]
        
        assert len(json_data) == length
        assert json.loads(json_data) == message
    
    def test_decode_message(self):
        """Test message decoding."""
        message = {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": 1}
        json_data = json.dumps(message).encode('utf-8')
        
        decoded = JSONRPCProtocol.decode_message(json_data)
        assert decoded == message
    
    def test_round_trip(self):
        """Test encode/decode round trip."""
        original = {
            "jsonrpc": "2.0",
            "method": "load_structure",
            "params": {"source": "1ABC", "object_name": "test"},
            "id": 42
        }
        
        encoded = JSONRPCProtocol.encode_message(original)
        json_data = encoded[4:]
        decoded = JSONRPCProtocol.decode_message(json_data)
        
        assert decoded == original
    
    def test_encode_empty_params(self):
        """Test encoding message with empty params."""
        message = {"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1}
        encoded = JSONRPCProtocol.encode_message(message)
        
        assert len(encoded) > 4
        json_data = encoded[4:]
        decoded = json.loads(json_data)
        assert decoded["params"] == {}
    
    def test_encode_unicode(self):
        """Test encoding message with unicode characters."""
        message = {
            "jsonrpc": "2.0",
            "method": "test",
            "params": {"text": "Hello 世界 🧬"},
            "id": 1
        }
        encoded = JSONRPCProtocol.encode_message(message)
        json_data = encoded[4:]
        decoded = json.loads(json_data.decode('utf-8'))
        
        assert decoded["params"]["text"] == "Hello 世界 🧬"
