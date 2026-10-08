"""Benchmark capture and optionally save frames using central TOML settings.

Run from the repository root in the car environment:
    python -m car.src.camera.fast_cam_test --seconds 10
    python -m car.src.camera.fast_cam_test --channels y --save-frames captures
    python -m car.src.camera.fast_cam_test --format jpeg --save test_frame

Saving runs synchronously and is included in measured throughput. This benchmark
counts completed captures, not necessarily distinct sensor exposures; verify
actual hardware FPS using reported frame durations and sensor timestamps.
"""

import argparse
import math
import time
from pathlib import Path

from car.src.camera.camera import Camera, save_frame
from car.src.config import load_config


def parse_size(text: str) -> tuple[int, int]:
    """Parse width x height; CameraConfig validates dimensions."""
    try:
        width, height = (int(value) for value in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 640x480") from None
    return width, height


def positive_seconds(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("seconds must be positive and finite")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="TOML path; defaults to car/config.toml"
    )
    parser.add_argument("--size", type=parse_size, help="override output WxH")
    parser.add_argument("--fps", type=float, help="override configured frame rate")
    parser.add_argument(
        "--channels", choices=["rgb", "y"], help="override configured channels"
    )
    parser.add_argument(
        "--format", choices=["numpy", "jpeg"], help="override file format"
    )
    parser.add_argument("--seconds", type=positive_seconds, default=10.0)
    parser.add_argument("--save", type=Path, help="save one frame to this path")
    parser.add_argument(
        "--save-frames", type=Path, help="save every benchmark frame here"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    overrides = {}
    if args.size is not None:
        overrides.update(width=args.size[0], height=args.size[1])
    for option, field in (
        ("fps", "frame_rate"),
        ("channels", "channels"),
        ("format", "file_format"),
    ):
        value = getattr(args, option)
        if value is not None:
            overrides[field] = value
    try:
        config = load_config(args.config).camera.with_overrides(**overrides)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)
    with Camera(config) as camera:
        time.sleep(1.0)  # Let automatic exposure and white balance settle.
        metadata = camera.camera.capture_metadata()
        print("Config:", config)
        print("Applied sensor:", camera.camera.camera_configuration()["sensor"])
        print("Frame duration (us):", metadata.get("FrameDuration"))
        if args.save:
            print("Saved:", camera.save_capture(args.save))
        count = 0
        start = time.perf_counter()
        while time.perf_counter() - start < args.seconds:
            frame = camera.single_capture()
            count += 1
            if args.save_frames:
                save_frame(frame, args.save_frames / f"frame_{count:06d}", config)
        elapsed = time.perf_counter() - start
        print(
            f"Frames: {count}; elapsed: {elapsed:.2f}s; throughput: {count / elapsed:.2f} FPS"
        )


if __name__ == "__main__":
    main()
