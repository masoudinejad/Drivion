"""Verify management dispatch and generated-information presentation."""

from unittest.mock import patch

import pytest

from car.system.information.view import load_info, render_info, system_info_page
from car.system.management.application import MenuItem, run_management


def test_dispatch_and_back(tmp_path):
    calls = []
    choices = iter([0, 1, None])
    items = [MenuItem("Info", calls.append), MenuItem("Setup", calls.append)]

    def select(title, labels):
        assert labels == ["Info", "Setup"]
        return next(choices)

    run_management(tmp_path, items=items, select=select)
    assert calls == [tmp_path.resolve(), tmp_path.resolve()]


def test_failed_action_returns_to_menu(tmp_path):
    choices = iter([0, None])
    pages = []

    def fail(root):
        raise ValueError("Invalid TOML")

    run_management(
        tmp_path,
        items=[MenuItem("Info", fail)],
        select=lambda *args: next(choices),
        display=lambda *args: pages.append(args),
    )
    assert pages == [("Info unavailable", "Invalid TOML")]


def test_cancellation_propagates(tmp_path):
    def cancel(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_management(tmp_path, select=cancel)


def test_info_reloads_and_does_not_modify_file(tmp_path):
    path = tmp_path / "system/info.toml"
    path.parent.mkdir()
    with patch("car.system.information.view.show_page") as display:
        for hostname in ["First", "Second"]:
            content = f'[system]\nhostname = "{hostname}"\n'
            path.write_text(content)
            system_info_page(tmp_path)
            assert hostname in display.call_args.args[1]
            assert path.read_text() == content


@pytest.mark.parametrize("content", [None, "[broken"])
def test_unavailable_info(tmp_path, content):
    if content is not None:
        path = tmp_path / "system/info.toml"
        path.parent.mkdir()
        path.write_text(content)
    with pytest.raises((OSError, ValueError)):
        load_info(tmp_path)


def test_render_all_fields_and_sanitize():
    info = {
        "software": {"version": "abc123", "dirty": True},
        "hardware": {"model": "Raspberry Pi", "serial_number": "123456"},
        "system": {"hostname": "Drivion", "architecture": "aarch64"},
        "network": {"fallback_ssid": "Drivion-123456"},
    }
    rendered = render_info(info)
    for section, fields in info.items():
        assert section.title() in rendered
        for value in fields.values():
            assert (
                ("Yes" if value else "No") in rendered
                if isinstance(value, bool)
                else str(value) in rendered
            )
    assert "\x1b" not in render_info({"future": {"value": "\x1b[2J"}})
    assert "Future / Nested" in render_info({"future": {"nested": {"value": 1}}})
    assert "No system information" in render_info({})
