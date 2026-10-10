# Contributing to Drivion

Drivion is an experimental robotics project. For substantial behavior or
architecture changes, discuss the proposal in a
[GitHub issue](https://github.com/masoudinejad/Drivion/issues) before implementing
it. Include the motivation, affected component, and how you plan to validate it.

## Development setup

Use Python 3.11+, uv, and Node.js with npm. From the repository root:

```sh
uv sync --project dev
npm ci --prefix dev
uv run --project dev pre-commit install
```

Keep the hook installed. See the [development guide](dev/README.md) for SSH,
sync, and provisioning prerequisites. Local development does not require
installing the Raspberry Pi runtime environment.

## Code and configuration

- Keep implementations simple, modular, and well named. Reuse shared behavior
  instead of duplicating it.
- Keep configurable, non-secret behavior in the existing central TOML files:
  `car/config.toml`, `car/system/pyproject.toml`, and `dev/pyproject.toml`.
  Do not hard-code configurable values in application code.
- Keep credentials and machine-specific connection values in the ignored local
  `dev/sync/.env` file, as documented in the development guide. Never commit
  secrets or generated environments, firmware build artifacts, or runtime logs.
- Add regression tests and update relevant documentation when behavior changes.
  Document hardware requirements and distinguish mocked tests from device tests.

## Validation

Before every commit, run the whole-project formatting tools followed by the
non-mutating check:

```sh
uv run --project dev python dev/quality/format_all.py
uv run --project dev python dev/quality/format_all.py --check
uv run --project dev pytest
```

The formatting tool uses Ruff for Python, markdownlint for Markdown, and
clang-format for C/C++ and Arduino sketches. Fix remaining lint failures,
review formatter edits, and stage the changes intentionally. See the
[test guide](tests/README.md) for platform requirements and optional toolchains.
Report checks that could not run; do not claim hardware validation unless it
was actually performed.

## Commits and pull requests

Keep each commit small and focused on one coherent concept. Related changes
may span multiple files; unrelated concepts belong in separate commits. Use
clear, specific commit messages that explain the change.

Commit only changes belonging to your task. Do not stage pre-existing or
unrelated changes without explicit authorization from their owner. For agents,
a request to commit does not authorize including other people's changes unless
the user explicitly says so. Follow [AGENTS.md](AGENTS.md) when working as an
agent.

In pull requests, describe the change, link relevant issues, and list validation
results and remaining limitations. For bug reports, include reproduction steps,
expected and actual behavior, and relevant platform or tool versions. Redact
credentials and private device details from logs.
