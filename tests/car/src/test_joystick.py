"""Exercise selection persistence and discovery with simulated Linux devices."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from car.src.config import load_config
from car.src.configuration.schema import JoystickIdentity
from car.src.joystick.discovery import Controller, discover, resolve_controller
from car.system.management.joystick import select_joystick


@pytest.fixture
def controller():
    return Controller(
        JoystickIdentity(
            name="Gamepad",
            vendor=1,
            product=2,
            unique_id="serial",
        ),
        "/dev/input/event1",
        "Axes: ABS_X, ABS_Y",
    )


def test_save_and_cancel(tmp_path, controller):
    path = tmp_path / "config.toml"
    path.write_text(Path("car/config.toml").read_text())
    original = path.read_bytes()
    pages = []
    for selection in (None, 0):
        select_joystick(
            tmp_path,
            select=lambda *args, selection=selection: selection,
            display=lambda *args: pages.append(args),
            scan=lambda: ([controller], []),
        )
        if selection is None:
            assert path.read_bytes() == original
    assert load_config(path).joystick.name == controller.identity.name
    assert pages == []


@pytest.mark.parametrize("current", [[], [1, 1]])
def test_disconnect_or_ambiguity_never_saves(tmp_path, controller, current):
    (tmp_path / "config.toml").write_text(Path("car/config.toml").read_text())
    original = (tmp_path / "config.toml").read_bytes()
    scans = iter([([controller], []), ([controller for _ in current], [])])
    with pytest.raises(RuntimeError):
        select_joystick(
            tmp_path,
            select=lambda *args: 0,
            display=lambda *args: None,
            scan=lambda: next(scans),
        )
    assert (tmp_path / "config.toml").read_bytes() == original


def test_no_devices_does_not_ask(tmp_path):
    def unexpected(*args):
        pytest.fail("No selection should be offered")

    select_joystick(
        tmp_path,
        select=unexpected,
        display=lambda *args: None,
        scan=lambda: ([], ["Permission denied"]),
    )


def test_discovery_filters_closes_and_reports_permissions(tmp_path):
    for name in ("event0", "event1", "event2"):
        (tmp_path / name).touch()
    closed = []
    codes = SimpleNamespace(
        EV_KEY=1,
        EV_ABS=3,
        BTN_JOYSTICK=288,
        BTN_DIGI=320,
        BTN_TRIGGER_HAPPY=704,
        BTN_TRIGGER_HAPPY40=743,
        bytype={1: {304: "BTN_SOUTH"}},
        ABS={0: "ABS_X"},
    )
    axis = SimpleNamespace(min=-32768, max=32767, flat=128, fuzz=4, resolution=0)

    def open_device(path, readonly):
        assert readonly
        if path.endswith("2"):
            raise PermissionError("Permission denied")
        return SimpleNamespace(
            name="Gamepad",
            path=path,
            uniq="serial",
            phys="usb-port",
            info=SimpleNamespace(bustype=3, vendor=1, product=2, version=1),
            capabilities=lambda **kwargs: {
                1: [304 if path.endswith("0") else 30],
                3: [(0, axis)],
            },
            close=lambda: closed.append(path),
        )

    devices, errors = discover(
        backend=SimpleNamespace(ecodes=codes, InputDevice=open_device),
        input_directory=tmp_path,
    )
    assert len(devices) == 1
    assert len(closed) == 2
    assert "Permission denied" in errors[0]
    assert "min=-32768" in devices[0].specifications
    moved = Controller(devices[0].identity, "/dev/input/event9", "")
    assert resolve_controller([moved], devices[0].identity) == moved


def test_unique_identity_survives_port_change_and_rejects_other_device(controller):
    moved = Controller(controller.identity, "event9", "")
    assert resolve_controller([moved], controller.identity) == moved
    other = Controller(
        controller.identity.with_overrides(unique_id="different"), "event1", ""
    )
    with pytest.raises(RuntimeError):
        resolve_controller([other], controller.identity)


def test_without_unique_id_survives_path_change_but_rejects_duplicates(controller):
    identity = controller.identity.with_overrides(unique_id="")
    moved = Controller(identity, "event9", "")
    assert resolve_controller([moved], identity) == moved
    with pytest.raises(RuntimeError):
        resolve_controller([moved, Controller(identity, "event1", "")], identity)


def test_saved_name_is_visible_in_menu(tmp_path, controller):
    from car.src.config import update_config

    path = tmp_path / "config.toml"
    path.write_text(Path("car/config.toml").read_text())
    update_config(
        "joystick",
        load_config(path)
        .joystick.with_overrides(**controller.identity.model_dump())
        .model_dump(exclude_none=True),
        path,
    )
    titles = []
    select_joystick(
        tmp_path,
        select=lambda title, labels: titles.append(title),
        scan=lambda: ([controller], []),
    )
    assert "saved: Gamepad" in titles[0]


def test_joystick_submenu_dispatch_and_back(tmp_path, monkeypatch):
    from car.system.management import joystick
    from car.system.ui.theme import menu_descriptions

    calls = []
    monkeypatch.setattr(joystick, "select_joystick", calls.append)
    choices = iter([0, None])

    def select(title, labels):
        assert title == "Joystick"
        assert labels == [
            "Identify and select device",
            "Configure controls",
            "Check controls",
        ]
        return next(choices)

    joystick.joystick_menu(tmp_path, select=select)
    assert calls == [tmp_path]
    assert menu_descriptions("Drivion system management", ["Joystick"])[0]
    assert menu_descriptions("Joystick", ["Identify and select device"])[0]
