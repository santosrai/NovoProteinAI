"""Tests for MCP tools."""

import pytest
from unittest.mock import patch, Mock
from pymol_mcp import tools


class TestTools:
    """Test MCP tool functions."""
    
    @pytest.fixture
    def mock_client(self):
        """Create mock client."""
        with patch('pymol_mcp.tools.get_client') as mock:
            client = Mock()
            mock.return_value = client
            yield client
    
    def test_load_structure_success(self, mock_client):
        """Test load_structure with successful response."""
        mock_client.call.return_value = {
            "result": {
                "message": "Loaded structure: 1ABC",
                "object_name": "1ABC"
            }
        }
        
        result = tools.load_structure("1ABC")
        
        assert "✓" in result
        assert "Loaded structure" in result
        mock_client.call.assert_called_once_with(
            "load_structure",
            {"source": "1ABC", "object_name": ""}
        )
    
    def test_load_structure_with_name(self, mock_client):
        """Test load_structure with custom object name."""
        mock_client.call.return_value = {
            "result": {
                "message": "Loaded structure: my_protein",
                "object_name": "my_protein"
            }
        }
        
        result = tools.load_structure("1ABC", "my_protein")
        
        assert "✓" in result
        mock_client.call.assert_called_once_with(
            "load_structure",
            {"source": "1ABC", "object_name": "my_protein"}
        )
    
    def test_load_structure_error(self, mock_client):
        """Test load_structure with error response."""
        mock_client.call.return_value = {
            "error": {
                "code": -32000,
                "message": "File not found"
            }
        }
        
        with pytest.raises(Exception) as exc_info:
            tools.load_structure("invalid.pdb")
        
        assert "File not found" in str(exc_info.value)
    
    def test_select_atoms_success(self, mock_client):
        """Test select_atoms with successful response."""
        mock_client.call.return_value = {
            "result": {
                "message": "Selected 150 atoms",
                "count": 150,
                "selection_name": "active_site"
            }
        }
        
        result = tools.select_atoms("active_site", "resi 100-150")
        
        assert "✓" in result
        assert "150 atoms" in result
        assert "active_site" in result
        mock_client.call.assert_called_once_with(
            "select_atoms",
            {"selection_name": "active_site", "selection_expr": "resi 100-150"}
        )
    
    def test_select_atoms_error(self, mock_client):
        """Test select_atoms with error response."""
        mock_client.call.return_value = {
            "error": {
                "code": -32602,
                "message": "Invalid selection expression"
            }
        }
        
        with pytest.raises(Exception) as exc_info:
            tools.select_atoms("test", "invalid syntax")
        
        assert "Invalid selection expression" in str(exc_info.value)
    
    def test_color_selection_success(self, mock_client):
        """Test color_selection with successful response."""
        mock_client.call.return_value = {
            "result": {
                "message": "Colored chain A with red"
            }
        }
        
        result = tools.color_selection("red", "chain A")
        
        assert "✓" in result
        assert "Color applied" in result or "Colored" in result
        mock_client.call.assert_called_once_with(
            "color_selection",
            {"color": "red", "selection": "chain A"}
        )
    
    def test_color_selection_default(self, mock_client):
        """Test color_selection with default selection."""
        mock_client.call.return_value = {
            "result": {
                "message": "Colored all with blue"
            }
        }
        
        result = tools.color_selection("blue")
        
        assert "✓" in result
        mock_client.call.assert_called_once_with(
            "color_selection",
            {"color": "blue", "selection": "all"}
        )
    
    def test_render_image_success(self, mock_client):
        """Test render_image with successful response."""
        mock_client.call.return_value = {
            "result": {
                "message": "Rendered image to /tmp/test.png",
                "path": "/tmp/test.png",
                "width": 800,
                "height": 600,
                "ray_traced": False
            }
        }
        
        result = tools.render_image("/tmp/test.png")
        
        assert "✓" in result
        assert "/tmp/test.png" in result
        assert "800x600" in result
        mock_client.call.assert_called_once_with(
            "render_image",
            {
                "output_path": "/tmp/test.png",
                "width": 800,
                "height": 600,
                "ray_trace": False
            }
        )
    
    def test_render_image_ray_traced(self, mock_client):
        """Test render_image with ray tracing."""
        mock_client.call.return_value = {
            "result": {
                "message": "Rendered image to /tmp/hq.png",
                "path": "/tmp/hq.png",
                "width": 1920,
                "height": 1080,
                "ray_traced": True
            }
        }
        
        result = tools.render_image("/tmp/hq.png", 1920, 1080, ray_trace=True)
        
        assert "✓" in result
        assert "ray-traced" in result
        assert "1920x1080" in result
        mock_client.call.assert_called_once_with(
            "render_image",
            {
                "output_path": "/tmp/hq.png",
                "width": 1920,
                "height": 1080,
                "ray_trace": True
            }
        )
    
    def test_ping_pymol_success(self, mock_client):
        """Test ping_pymol with successful response."""
        mock_client.call.return_value = {
            "result": {
                "status": "ok",
                "version": "2.5.0"
            }
        }
        
        result = tools.ping_pymol()
        
        assert "✓" in result
        assert "Connected" in result
        assert "2.5.0" in result
        mock_client.call.assert_called_once_with("ping")
    
    def test_ping_pymol_error(self, mock_client):
        """Test ping_pymol with error response."""
        mock_client.call.return_value = {
            "error": {
                "code": -32300,
                "message": "Connection refused"
            }
        }
        
        with pytest.raises(Exception) as exc_info:
            tools.ping_pymol()
        
        assert "Connection refused" in str(exc_info.value)
