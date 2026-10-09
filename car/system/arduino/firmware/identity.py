"""Validated firmware identity shared by builds and serial replies."""


def firmware_identity(name, firmware, software):
    """Construct the compile-time identity that the running firmware must report."""
    identity = {
        "firmware_name": name,
        "firmware_version": firmware["version"],
        "protocol_version": firmware["protocol_version"],
        "git_commit": software.get("commit", "unknown"),
        "source_dirty": software.get("dirty", False),
    }
    return validate_identity(identity)


def validate_identity(identity):
    """Accept only the exact, bounded firmware identity JSON contract."""
    if not isinstance(identity, dict) or set(identity) != {
        "firmware_name",
        "firmware_version",
        "protocol_version",
        "git_commit",
        "source_dirty",
    }:
        raise ValueError("Firmware identity response has missing or unexpected fields")
    for key in ("firmware_name", "firmware_version", "git_commit"):
        value = identity[key]
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isprintable()
            or not 1 <= len(value) <= 255
        ):
            raise ValueError(f"Invalid firmware identity {key}")
    if (
        type(identity["protocol_version"]) is not int
        or not 1 <= identity["protocol_version"] < 2**32
    ):
        raise ValueError("Invalid firmware protocol version")
    if type(identity["source_dirty"]) is not bool:
        raise ValueError("Firmware source_dirty must be boolean")
    return identity


def identity_info(identity):
    """Map validated wire identity to the shared flat system-information fields."""
    return {
        key if key.startswith("firmware_") else f"firmware_{key}": value
        for key, value in validate_identity(identity).items()
    }
