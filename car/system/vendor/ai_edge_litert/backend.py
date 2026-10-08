"""Correct LiteRT's backport dependency in the verified upstream ARM64 wheel."""

import base64
import csv
import hashlib
import io
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

WHEEL = "ai_edge_litert-2.3.0-cp313-cp313-manylinux_2_27_aarch64.whl"
URL = (
    "https://files.pythonhosted.org/packages/"
    "b2/ad/234674ab4781ff1822c26794488b5640512bc61011a6b3490bfecdc46aa1/" + WHEEL
)
SHA256 = "2ab71e4f5dfa65b3882634b42755f455f3e7415630d720200bd792733e15e257"


def repair_wheel(source, destination):
    """Change only dependency metadata and regenerate wheel RECORD hashes."""
    with ZipFile(source) as original, ZipFile(destination, "w") as patched:
        records = []
        record_name = None
        corrections = 0
        for entry in original.infolist():
            if entry.filename.endswith(".dist-info/RECORD"):
                record_name = entry.filename
                continue
            data = original.read(entry.filename)
            if entry.filename.endswith(".dist-info/METADATA"):
                old = b"Requires-Dist: backports.strenum\n"
                if data.count(old) != 1:
                    raise ValueError("Unexpected upstream LiteRT dependency metadata")
                data = data.replace(
                    old,
                    b'Requires-Dist: backports.strenum; python_version < "3.11"\n',
                )
                corrections += 1
            patched.writestr(entry, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            records.append(
                (entry.filename, "sha256=" + digest.rstrip(b"=").decode(), len(data))
            )
        if corrections != 1 or record_name is None:
            raise ValueError("Unexpected upstream LiteRT wheel layout")
        records.append((record_name, "", ""))
        output = io.StringIO(newline="")
        csv.writer(output).writerows(records)
        patched.writestr(record_name, output.getvalue())


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    with urlopen(URL, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Upstream LiteRT wheel checksum does not match")
    repair_wheel(io.BytesIO(data), Path(wheel_directory) / WHEEL)
    return WHEEL


def get_requires_for_build_wheel(config_settings=None):
    return []
