"""Connect firmware selection to the existing compile and verified-flash steps."""

import subprocess

from ...ui.navigation import select_item, show_page
from ..device.flash import flash_firmware
from ..firmware.compile import compile_firmware
from ..firmware.definitions import load_firmware
from ..settings import load_context


def change_firmware(car_root, *, select=select_item, display=show_page):
    """Select a registered firmware, compile it, then flash that exact build.

    Each procedure retains its own confirmation and progress UI. Cancellation
    never advances to the next step; hardware is touched only by flash_firmware.
    Recoverable failures show diagnostics and return to the Arduino submenu.
    """
    try:
        context = load_context(car_root)
        root = context.root
        firmwares, errors = {}, {}
        for name, values in context.firmware_defaults.items():
            try:
                firmwares[name] = load_firmware(name, root, values, context=context)
            except (OSError, ValueError, TypeError, KeyError) as error:
                errors[name] = str(error)
        if errors:
            display(
                "Unavailable firmware",
                "\n".join(f"{name}: {error}" for name, error in errors.items()),
            )
        if not firmwares:
            display(
                "Change firmware",
                "No valid firmware is available. Check the reported entries, or "
                "add firmware entries to config.toml and their sketches to the "
                "configured Arduino sketchbook."
                if errors
                else "No firmwares are registered. Add firmware entries to config.toml "
                "and their sketches to the configured Arduino sketchbook.",
            )
            return
        names = list(firmwares)
        labels = [
            f"{name} — {firmwares[name]['version']} ({firmwares[name]['fqbn']})"
            for name in names
        ]
        selected = select("Select firmware to compile and flash", labels)
        if selected is None:
            return
        if not 0 <= selected < len(names):
            raise ValueError("Invalid firmware selection")
        name = names[selected]
        artifacts = compile_firmware(name, root, context=context)
        if artifacts is None:
            return
        log_path = flash_firmware(artifacts, root, context=context)
        if log_path is None:
            return
        display(
            "Firmware changed",
            f"{name} was uploaded and its running identity verified.\n\n"
            f"Compiled artifacts: {artifacts}\nFlash log: {log_path}",
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        diagnostics = [str(error)]
        if isinstance(error, subprocess.SubprocessError):
            for field in ("stdout", "stderr"):
                output = getattr(error, field, None)
                if output:
                    diagnostics.append(
                        output.decode(errors="replace")
                        if isinstance(output, bytes)
                        else output
                    )
        display("Firmware change failed", "\n\n".join(diagnostics))
