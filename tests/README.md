# Tests

Tests mirror the project structure: development-tool tests live under `dev/`,
and car system tests live under `car/system/`.

Install the development environment and run the suite from the repository root:

```sh
uv sync --project dev
uv run --project dev pytest
```

Run a subset with `uv run --project dev pytest tests/car/system` or
`uv run --project dev pytest tests/dev`.

The suite uses local temporary files and pseudo-terminals. It does not connect
to the Pi or read local credentials. Menu tests require a Unix-like environment
with Bash and access to a controlling terminal. Python is used only by the test
harness; the menu itself runs entirely in Bash on the Raspberry Pi.
