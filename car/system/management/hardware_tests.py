"""Manual hardware diagnostics with independent logs and terminal transcripts."""

import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import tomllib

from ..ui.navigation import select_item, show_page
from ..ui.progress import show_progress, show_success


def latency_summary(label, samples, log):
    """Report host-observed durations in milliseconds, including every sample."""
    values = [value * 1000 for value in samples]
    log.info(
        "%s latency ms: min=%.3f mean=%.3f median=%.3f max=%.3f",
        label,
        min(values),
        statistics.mean(values),
        statistics.median(values),
        max(values),
    )


def check_camera(root, config, settings, log):
    """Measure blocking capture duration, not sensor-to-display latency."""
    from car.src.camera.camera import Camera

    started = time.monotonic()
    with Camera(config) as camera:
        log.info(
            "Camera initialization latency: %.3f ms",
            (time.monotonic() - started) * 1000,
        )
        log.info("Camera settings: %s", config.model_dump())
        time.sleep(config.warmup_seconds)
        samples = []
        started = time.monotonic()
        for index in range(settings.camera_frames):
            before = time.monotonic()
            frame = camera.single_capture()
            elapsed = time.monotonic() - before
            samples.append(elapsed)
            expected = (config.height, config.width)
            if config.channels == "rgb":
                expected += (3,)
            if frame.shape != expected or str(frame.dtype) != "uint8":
                raise ValueError(
                    f"Unexpected camera frame: {frame.shape}/{frame.dtype}"
                )
            log.info(
                "Frame %d: shape=%s dtype=%s capture latency=%.3f ms",
                index + 1,
                frame.shape,
                frame.dtype,
                elapsed * 1000,
            )
        duration = time.monotonic() - started
        latency_summary("Capture", samples, log)
        log.info(
            "Captured %d frames in %.3f s; observed throughput %.2f FPS",
            len(samples),
            duration,
            len(samples) / duration,
        )


def check_arduino(root, config, settings, log):
    """Verify negotiated communication and correlated snapshots without targets."""
    from car.src.communication import Communication, ReportedValues

    started = time.monotonic()
    with Communication.open(
        config["address"], config["communication"], progress=show_progress
    ) as client:
        log.info(
            "Connection latency (includes board boot wait): %.3f ms",
            (time.monotonic() - started) * 1000,
        )
        log.info("Port: %s", getattr(client.transport, "port", config["address"]))
        log.info(
            "Baud rate: %d; capabilities: %s",
            config["communication"].baud_rate,
            client.capabilities,
        )
        handshake_samples, telemetry_samples = [], []
        for index in range(settings.arduino_samples):
            before = time.monotonic()
            client.synchronize()
            handshake = time.monotonic() - before
            handshake_samples.append(handshake)
            before = time.monotonic()
            sequence = client.request_values()
            while True:
                events = client.poll()
                elapsed = time.monotonic() - before
                if elapsed > settings.response_timeout_seconds:
                    raise TimeoutError(f"Telemetry request {sequence} timed out")
                response = next(
                    (
                        event
                        for event in events
                        if isinstance(event, ReportedValues)
                        and event.request_sequence == sequence
                    ),
                    None,
                )
                if response is not None:
                    telemetry_samples.append(elapsed)
                    log.info(
                        "Sample %d: handshake RTT=%.3f ms telemetry RTT=%.3f ms values=%s",
                        index + 1,
                        handshake * 1000,
                        elapsed * 1000,
                        response,
                    )
                    break
        deadline = time.monotonic() + settings.response_timeout_seconds
        while client.status_stale:
            client.poll()
            if time.monotonic() > deadline:
                raise TimeoutError("No fresh Arduino status received")
        log.info("Arduino status: %s", client.latest_status)
        latency_summary("Handshake round-trip", handshake_samples, log)
        latency_summary("Telemetry round-trip", telemetry_samples, log)


def check_joystick(root, config, log):
    """Exercise calibrated controls interactively and measure host read duration.

    Both controls must change before Enter can complete the check. Escape cancels;
    disconnects fail. Read duration measures kernel queries and normalization,
    not the physical controller's input-to-host latency. No drive targets are sent.
    """
    from car.src.configuration.schema import JoystickSetupConfig
    from car.src.joystick import Joystick

    from .joystick_preview import preview_controls

    with (root / "system/pyproject.toml").open("rb") as source:
        settings = JoystickSetupConfig.model_validate(
            tomllib.load(source)["tool"]["drivion"]["joystick_setup"]
        )
    started = time.monotonic()
    with Joystick(config, progress=show_progress, success=show_success) as joystick:
        log.info(
            "Joystick initialization latency: %.3f ms",
            (time.monotonic() - started) * 1000,
        )
        log.info("Joystick settings: %s", config.model_dump())
        log.info("Axis metadata: %s", joystick.axis_snapshot())
        log.info(
            "Move both controls; Enter completes after both change; Escape cancels."
        )
        count, total, minimum, maximum = 0, 0.0, float("inf"), 0.0
        previous = None

        def read():
            nonlocal count, total, minimum, maximum, previous
            before = time.monotonic()
            current = joystick.read()
            elapsed = time.monotonic() - before
            count += 1
            total += elapsed
            minimum, maximum = min(minimum, elapsed), max(maximum, elapsed)
            if current != previous:
                log.info(
                    "Input demands: speed=%.3f steering=%.3f",
                    current.speed,
                    current.steering,
                    extra={"file_only": True},
                )
                previous = current
            return current

        try:
            return preview_controls(joystick, config.controls, settings, read=read)
        finally:
            if count:
                log.info(
                    "Joystick read latency ms: samples=%d min=%.3f mean=%.3f max=%.3f",
                    count,
                    minimum * 1000,
                    total / count * 1000,
                    maximum * 1000,
                )


def run_check(root, name, *, stream=None):
    """Log failures and interruptions, close handlers, and return the transcript."""
    from car.src.configuration.schema import (
        CameraConfig,
        CommunicationConfig,
        HardwareTestsConfig,
        JoystickConfig,
    )

    root = Path(root)
    with (root / "config.toml").open("rb") as source:
        values = tomllib.load(source)
    if "hardware_tests" not in values:
        raise ValueError(
            "Configure [hardware_tests] in car/config.toml before running diagnostics"
        )
    settings = HardwareTestsConfig.model_validate(values["hardware_tests"])
    directory = root / settings.log_directory
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = directory / f"{name}-{stamp}-{uuid4().hex}.log"
    log = logging.getLogger(f"hardware.{name}")
    log.setLevel(logging.INFO)
    log.propagate = False
    file_handler = logging.FileHandler(path, encoding="utf-8")
    terminal_handler = logging.StreamHandler(stream)
    # Per-read details belong in the saved report, not over the live monitor.
    terminal_handler.addFilter(lambda record: not getattr(record, "file_only", False))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (file_handler, terminal_handler):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    started = time.monotonic()
    try:
        log.info("Starting %s check; log: %s", name, path)
        completed = True
        if name == "camera":
            check_camera(
                root, CameraConfig.model_validate(values["camera"]), settings, log
            )
        elif name == "arduino":
            check_arduino(
                root,
                {
                    "address": values["arduino"]["address"],
                    "communication": CommunicationConfig.model_validate(
                        values["communication"]
                    ),
                },
                settings,
                log,
            )
        elif name == "joystick":
            completed = check_joystick(
                root, JoystickConfig.model_validate(values["joystick"]), log
            )
        else:
            raise ValueError(f"Unknown hardware check: {name}")
        log.info("PASS" if completed else "CANCELLED")
    except KeyboardInterrupt:
        log.warning("INTERRUPTED")
        raise
    except Exception:
        log.exception("FAIL")
    finally:
        log.info("Total duration: %.3f s", time.monotonic() - started)
        for handler in (file_handler, terminal_handler):
            log.removeHandler(handler)
            handler.close()
    return path.read_text(encoding="utf-8")


def hardware_tests_menu(root):
    """Keep diagnostics together and leave room for future hardware checks."""
    labels = ["Camera check", "Arduino communication check", "Joystick check"]
    while True:
        selected = select_item("Hardware tests", labels)
        if selected is None:
            return
        # Opening USB serial can reset the board; explain before the check runs.
        if selected == 1:
            from ..ui.navigation import confirm

            if not confirm(
                "Stop driving and close other serial users. Opening serial may reset the Arduino. Run communication check?"
            ):
                continue
        name = ("camera", "arduino", "joystick")[selected]
        with open("/dev/tty", "w", encoding="utf-8", buffering=1) as terminal:
            transcript = run_check(root, name, stream=terminal)
        show_page(labels[selected], transcript)
