"""Tests for local-file vs PDB-ID resolution in load_structure.

These exercise ``resolve_structure_source`` from the PyMOL plugin, which is
deliberately free of any PyMOL imports so it can run without PyMOL installed.
"""

import os
import pytest
from pymol_plugin import resolve_structure_source


class TestResolveStructureSource:
    """Test how source strings are classified and validated."""

    def test_local_cif_file(self, tmp_path):
        """A real local .cif path resolves to a load with an absolute path."""
        cif = tmp_path / "my_design.cif"
        cif.write_text("data_test\n")

        resolved = resolve_structure_source(str(cif))

        assert resolved["mode"] == "load"
        assert resolved["path"] == os.path.abspath(str(cif))
        assert resolved["object_name"] == "my_design"

    def test_object_name_override(self, tmp_path):
        """An explicit object_name is preserved (sanitized)."""
        cif = tmp_path / "structure.cif"
        cif.write_text("data_test\n")

        resolved = resolve_structure_source(str(cif), "my obj")

        assert resolved["mode"] == "load"
        assert resolved["object_name"] == "my_obj"

    def test_gzipped_cif_extension_stripped(self, tmp_path):
        """A .cif.gz file is recognized and the name drops both extensions."""
        cif = tmp_path / "model.cif.gz"
        cif.write_text("ignored\n")

        resolved = resolve_structure_source(str(cif))

        assert resolved["mode"] == "load"
        assert resolved["object_name"] == "model"

    def test_uppercase_extension(self, tmp_path):
        """Extension matching is case-insensitive."""
        cif = tmp_path / "DESIGN.CIF"
        cif.write_text("data_test\n")

        resolved = resolve_structure_source(str(cif))

        assert resolved["mode"] == "load"

    def test_missing_file_is_error(self, tmp_path):
        """A path-like source that does not exist returns an error."""
        resolved = resolve_structure_source(str(tmp_path / "nope.cif"))

        assert "error" in resolved
        assert "File not found" in resolved["error"]

    def test_directory_is_error(self, tmp_path):
        """A path that exists but is a directory is rejected."""
        resolved = resolve_structure_source(str(tmp_path))

        assert "error" in resolved

    def test_empty_source_is_error(self):
        """Empty/whitespace source is rejected."""
        assert "error" in resolve_structure_source("")
        assert "error" in resolve_structure_source("   ")

    def test_pdb_id_is_fetch(self):
        """A bare 4-char code with no path markers resolves to a fetch."""
        resolved = resolve_structure_source("1ABC")

        assert resolved["mode"] == "fetch"
        assert resolved["source"] == "1ABC"
        assert resolved["object_name"] == "1ABC"

    def test_pdb_id_with_object_name(self):
        """Fetch keeps the explicit object name."""
        resolved = resolve_structure_source("1abc", "my_protein")

        assert resolved["mode"] == "fetch"
        assert resolved["object_name"] == "my_protein"
