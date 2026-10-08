"""Format or check all tracked and non-ignored project source files."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPP_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".ino"}


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
    python = [name for name in files if Path(name).suffix in {".py", ".pyi"}]
    markdown = [name for name in files if Path(name).suffix.lower() == ".md"]
    cpp = [name for name in files if Path(name).suffix in CPP_EXTENSIONS]
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
