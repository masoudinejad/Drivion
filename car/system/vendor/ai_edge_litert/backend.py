"""Correct LiteRT's backport dependency in the verified upstream ARM64 wheel."""

import base64
import csv
import hashlib
import io
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import tomllib


def upstream_wheel():
    """Read and validate the pinned upstream artifact from project TOML."""
    with Path(__file__).with_name("pyproject.toml").open("rb") as source:
        values = tomllib.load(source)["tool"]["drivion"]["upstream-wheel"]
    if set(values) != {
        "filename",
        "url",
        "sha256",
        "download_timeout_seconds",
    }:
        raise ValueError("Configure exactly the supported upstream wheel settings")
    if not values["filename"].endswith(".whl") or "/" in values["filename"]:
        raise ValueError("Configure a valid upstream wheel filename")
    if not values["url"].startswith("https://"):
        raise ValueError("Configure a secure upstream wheel URL")
    if len(values["sha256"]) != 64 or any(
        character not in "0123456789abcdef" for character in values["sha256"]
    ):
        raise ValueError("Configure a valid upstream wheel checksum")
    timeout = values["download_timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise ValueError("Configure a valid upstream wheel download timeout")
    return values


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
    settings = upstream_wheel()
    with urlopen(
        settings["url"], timeout=settings["download_timeout_seconds"]
    ) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != settings["sha256"]:
        raise ValueError("Upstream LiteRT wheel checksum does not match")
    repair_wheel(io.BytesIO(data), Path(wheel_directory) / settings["filename"])
    return settings["filename"]


def get_requires_for_build_wheel(config_settings=None):
    return []
