"""Verify named compilation, generated literals and mandatory UI approval."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import tomllib

from car.system.arduino.compile import (
    c_literal,
    compile_firmware,
    render_header,
    validate_compile_configuration,
)
from car.system.ui.navigation import confirm

ROOT = Path(__file__).resolve().parents[3] / "car"
MODULE = "car.system.arduino.compile"


@pytest.fixture
def car_root(tmp_path):
    root = tmp_path / "car"
    root.mkdir()
    shutil.copy(ROOT / "config.toml", root)
    (root / "system").mkdir()
    shutil.copy(ROOT / "system/pyproject.toml", root / "system")
    with (root / "config.toml").open("a") as stream:
        stream.write(
            '\n[firmware.demo]\nversion = "1.2.0"\nprotocol_version = 1\nfqbn = "arduino:avr:nano:cpu=atmega328"\nrequired_parameters = ["PIN", "LABEL", "ENABLED"]\n[firmware.demo.parameters]\nPIN = 5\nLABEL = \'a"b\'\nENABLED = true\n'
        )
    sketch = root / "system/arduino/code/demo"
    sketch.mkdir(parents=True)
    (sketch / "demo.ino").write_text(
        '#include "drivion_generated.h"\nvoid setup() {}\nvoid loop() {}\n'
    )
    return root


def test_compile_generated_header_and_cli(car_root):
    (car_root / "system/info.toml").write_text(
        '[software]\ncommit = "abc123"\ndirty = true\n'
    )

    def compile_output(command, **kwargs):
        output = Path(command[command.index("--output-dir") + 1])
        output.mkdir()
        (output / "demo.ino.hex").write_text(":00000001FF\n")
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    with (
        patch(f"{MODULE}.confirm", return_value=True) as approval,
        patch(
            f"{MODULE}.subprocess.run",
            side_effect=compile_output,
        ) as run,
        patch(f"{MODULE}.show_progress") as waiting,
    ):
        artifacts = compile_firmware("demo", car_root)
    approval.assert_called_once()
    waiting.assert_called_once()
    header = (artifacts.parent / "demo/drivion_generated.h").read_text()
    assert '#define DRIVION_FIRMWARE_VERSION "1.2.0"' in header
    assert '#define DRIVION_GIT_COMMIT "abc123"' in header
    assert "#define DRIVION_SOURCE_DIRTY true" in header
    assert '#define LABEL "a\\042b"' in header
    assert "#define PIN 5UL" in header
    assert not (car_root / "system/arduino/code/demo/drivion_generated.h").exists()
    command = run.call_args.args[0]
    assert command[3:6] == ["compile", "--fqbn", "arduino:avr:nano:cpu=atmega328"]
    assert "upload" not in command
    assert run.call_args.kwargs["timeout"] == 300
    manifest = tomllib.loads((artifacts.parent / "firmware.toml").read_text())
    assert manifest["firmware"]["firmware_version"] == "1.2.0"
    assert manifest["serial"]["baud_rate"] == 115200
    assert "demo.ino.hex" in manifest["artifacts"]
    assert "drivionHandleInfo" in header


def test_refusal_has_no_side_effects(car_root):
    with (
        patch(f"{MODULE}.confirm", return_value=False),
        patch(f"{MODULE}.subprocess.run") as run,
    ):
        assert compile_firmware("demo", car_root) is None
    run.assert_not_called()
    assert not (car_root / "system/arduino/build").exists()


def test_unknown_name_does_not_prompt(car_root):
    with (
        patch(f"{MODULE}.confirm") as approval,
        pytest.raises(ValueError, match="Unknown firmware"),
    ):
        compile_firmware("missing", car_root)
    approval.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, ["compile"], "output", "failure"),
        subprocess.TimeoutExpired(["compile"], 300),
        FileNotFoundError("CLI missing"),
    ],
)
def test_compile_failure_propagates(car_root, failure):
    with (
        patch(f"{MODULE}.confirm", return_value=True),
        patch(f"{MODULE}.subprocess.run", side_effect=failure),
        pytest.raises(type(failure)),
    ):
        compile_firmware("demo", car_root)


@pytest.mark.parametrize(
    "values",
    [{}, {"PIN": 1, "EXTRA": 2}, {"PIN": [1]}, {"PIN": float("inf")}, {"PIN": 2**40}],
)
def test_invalid_parameters(values):
    settings = {
        "build_directory": "system/arduino/build",
        "header_filename": "generated.h",
        "manifest_filename": "firmware.toml",
        "command_timeout_seconds": 300,
    }
    firmware = {
        "version": "1.0.0",
        "protocol_version": 1,
        "fqbn": "arduino:avr:uno",
        "required_parameters": ["PIN"],
        "parameters": values,
    }
    with pytest.raises(ValueError):
        validate_compile_configuration(settings, {"demo": firmware})


def test_unknown_deployment_identity():
    with (ROOT / "config.toml").open("rb") as stream:
        settings = tomllib.load(stream)["firmware_flash"]
    header = render_header(
        "demo", {"version": "1", "protocol_version": 1, "parameters": {}}, {}, settings
    )
    assert '#define DRIVION_GIT_COMMIT "unknown"' in header


def test_control_characters_are_valid_c_escapes():
    assert c_literal("\x01?\n") == '"\\001\\077\\012"'


@pytest.mark.parametrize("status, expected", [(0, True), (1, False)])
def test_shared_confirmation(status, expected):
    with patch(
        "car.system.ui.navigation.subprocess.run",
        return_value=subprocess.CompletedProcess([], status, "", ""),
    ):
        assert confirm("Compile firmware?") is expected


@pytest.mark.parametrize(
    "status, exception", [(2, RuntimeError), (130, KeyboardInterrupt)]
)
def test_confirmation_errors_are_not_approval(status, exception):
    with (
        patch(
            "car.system.ui.navigation.subprocess.run",
            return_value=subprocess.CompletedProcess([], status, "", "error"),
        ),
        pytest.raises(exception),
    ):
        confirm("Compile firmware?")


def test_generated_identity_handler_compiles_with_available_avr_core(tmp_path):
    """Optional real compiler smoke test; never connects to or uploads a board."""
    executable = shutil.which("arduino-cli")
    if executable is None:
        pytest.skip("Arduino CLI is not installed on this development machine")
    listing = subprocess.run(
        [executable, "core", "list", "--json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    platforms = json.loads(listing.stdout).get("platforms", [])
    if not any(
        item.get("id") == "arduino:avr" and item.get("installed_version")
        for item in platforms
    ):
        pytest.skip("Arduino AVR core is not installed on this development machine")
    with (ROOT / "config.toml").open("rb") as stream:
        settings = tomllib.load(stream)
    sketch = tmp_path / "compile_smoke"
    sketch.mkdir()
    (sketch / "compile_smoke.ino").write_text(
        f'#include "{settings["firmware_compile"]["header_filename"]}"\n'
        "void setup() { Serial.begin(DRIVION_SERIAL_BAUD_RATE); }\nvoid loop() { drivionHandleInfo(DRIVION_INFO_COMMAND); }\n"
    )
    (sketch / settings["firmware_compile"]["header_filename"]).write_text(
        render_header(
            "compile_smoke",
            {"version": '1.0"quoted', "protocol_version": 1, "parameters": {}},
            {},
            settings["firmware_flash"],
        )
    )
    subprocess.run(
        [
            executable,
            "compile",
            "--fqbn",
            "arduino:avr:nano:cpu=atmega328",
            "--build-path",
            str(tmp_path / "build"),
            "--output-dir",
            str(tmp_path / "artifacts"),
            str(sketch),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=settings["firmware_compile"]["command_timeout_seconds"],
    )
    assert (tmp_path / "artifacts/compile_smoke.ino.hex").is_file()
