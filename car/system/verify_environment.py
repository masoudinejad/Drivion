"""Verify configured dependencies with isolated imports in the active Python."""

import argparse
import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if __package__:
    from .provisioning import system_settings, verification_timeout
else:
    from provisioning import system_settings, verification_timeout


def verification_plan(car_root):
    root = Path(car_root)
    _, system_modules = system_settings(root)
    with (root / "system/pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    mappings = (
        project.get("tool", {})
        .get("drivion", {})
        .get("verification", {})
        .get("imports", {})
    )
    dependencies = [Requirement(value) for value in project["project"]["dependencies"]]
    names = {canonicalize_name(value.name) for value in dependencies}
    mappings = {canonicalize_name(name): module for name, module in mappings.items()}
    if mappings.keys() - names:
        raise ValueError("Import mappings must refer to declared project dependencies")
    checks = []
    for requirement in dependencies:
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        module = mappings.get(
            canonicalize_name(requirement.name), requirement.name.replace("-", "_")
        )
        checks.append((requirement, module))
    checks.extend((None, module) for module in system_modules)
    for _, module in checks:
        if not isinstance(module, str) or not re.fullmatch(
            r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module
        ):
            raise ValueError(f"Invalid import module: {module!r}")
    return checks


def verify(car_root):
    failures = []
    timeout = verification_timeout(car_root)
    for requirement, module in verification_plan(car_root):
        label = str(requirement) if requirement else f"system:{module}"
        try:
            if requirement:
                installed = importlib.metadata.version(requirement.name)
                if not requirement.specifier.contains(installed, prereleases=True):
                    raise ValueError(
                        f"Installed {installed} does not satisfy {requirement}"
                    )
            print(f"Checking {label} -> {module}", flush=True)
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"import importlib; importlib.import_module({module!r})",
                ],
                check=True,
                timeout=timeout,
            )
            print(f"OK: {label}", flush=True)
        except (
            importlib.metadata.PackageNotFoundError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            failures.append(label)
            print(f"FAILED: {label}: {error}", file=sys.stderr, flush=True)
    if failures:
        print(
            "Environment verification failed: " + ", ".join(failures), file=sys.stderr
        )
        return 1
    print("All configured dependencies and system imports verified.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("car_root", type=Path)
    args = parser.parse_args(argv)
    try:
        return verify(args.car_root)
    except (KeyError, OSError, ValueError) as error:
        print(f"Verification configuration error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
