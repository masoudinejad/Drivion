"""Check the LiteRT wheel repair preserves code and valid integrity records."""

import base64
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
from zipfile import ZipFile

import pytest

BACKEND = (
    Path(__file__).resolve().parents[3] / "car/system/vendor/ai_edge_litert/backend.py"
)
spec = importlib.util.spec_from_file_location("litert_backend", BACKEND)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def wheel(metadata):
    source = io.BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("ai_edge_litert/runtime.so", b"unchanged binary")
        archive.writestr("ai_edge_litert-2.3.0.dist-info/METADATA", metadata)
        archive.writestr("ai_edge_litert-2.3.0.dist-info/RECORD", "old record")
    source.seek(0)
    return source


def test_repair_preserves_binary_and_updates_integrity(tmp_path):
    destination = tmp_path / "patched.whl"
    backend.repair_wheel(wheel(b"Requires-Dist: backports.strenum\n"), destination)
    with ZipFile(destination) as archive:
        assert archive.read("ai_edge_litert/runtime.so") == b"unchanged binary"
        metadata = archive.read("ai_edge_litert-2.3.0.dist-info/METADATA")
        assert b'python_version < "3.11"' in metadata
        records = csv.reader(
            io.StringIO(archive.read("ai_edge_litert-2.3.0.dist-info/RECORD").decode())
        )
        for name, digest, size in records:
            if name.endswith("/RECORD"):
                assert digest == size == ""
                continue
            data = archive.read(name)
            expected = (
                base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                .rstrip(b"=")
                .decode()
            )
            assert digest == "sha256=" + expected
            assert int(size) == len(data)


def test_unexpected_metadata_fails(tmp_path):
    with pytest.raises(ValueError, match="metadata"):
        backend.repair_wheel(
            wheel(b"Requires-Dist: unexpected\n"), tmp_path / "bad.whl"
        )


def test_download_checksum_must_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        backend, "urlopen", lambda *args, **kwargs: io.BytesIO(b"tampered")
    )
    with pytest.raises(ValueError, match="checksum"):
        backend.build_wheel(tmp_path)
