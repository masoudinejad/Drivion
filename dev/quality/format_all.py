"""Format or check all tracked and non-ignored project source files."""

import argparse
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]


def configured_extensions():
    """Read the file classes handled by the project quality tools."""
    with (ROOT / "dev/pyproject.toml").open("rb") as stream:
        values = tomllib.load(stream)["tool"]["drivion"]["quality"]
    expected = {"python_extensions", "markdown_extensions", "cpp_extensions"}
    if set(values) != expected or any(
        not isinstance(items, list)
        or not items
        or any(not isinstance(item, str) or not item.startswith(".") for item in items)
        for items in values.values()
    ):
        raise ValueError("Configure valid tool.drivion.quality extension lists")
    return tuple(
        set(values[name])
        for name in ("python_extensions", "markdown_extensions", "cpp_extensions")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check without modifying files"
    )
    args = parser.parse_args()
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    files = sorted(
        {
            name.decode()
            for name in result.stdout.split(b"\0")
            if name and (ROOT / name.decode()).is_file()
        }
    )
    python_extensions, markdown_extensions, cpp_extensions = configured_extensions()
    python = [name for name in files if Path(name).suffix in python_extensions]
    markdown = [
        name for name in files if Path(name).suffix.lower() in markdown_extensions
    ]
    cpp = [name for name in files if Path(name).suffix in cpp_extensions]
    commands = []
    if python:
        commands.append(["ruff", "check", *([] if args.check else ["--fix"]), *python])
        commands.append(
            ["ruff", "format", *(["--check"] if args.check else []), *python]
        )
    if markdown:
        executable = ROOT / "dev/node_modules/.bin/markdownlint-cli2"
        if not executable.exists():
            print(
                "Run npm ci --prefix dev to install markdownlint.",
                file=sys.stderr,
            )
            return 1
        commands.append(
            [str(executable), *([] if args.check else ["--fix"]), *markdown]
        )
    for name in cpp:
        commands.append(
            [
                "clang-format",
                *(["--dry-run", "--Werror"] if args.check else ["-i"]),
                *(["--assume-filename=source.cpp"] if name.endswith(".ino") else []),
                name,
            ]
        )
    failed = False
    for command in commands:
        print(f"Running {Path(command[0]).name}...", flush=True)
        try:
            failed |= subprocess.run(command, cwd=ROOT, check=False).returncode != 0
        except FileNotFoundError:
            print("Run this tool through uv run --project dev.", file=sys.stderr)
            return 1
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
