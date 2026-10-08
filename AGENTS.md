# Project instructions

Consult the user before implementing changes unless the change has already been
agreed in the conversation.

Before every commit, run the whole-project formatting checks:

```sh
uv run --project dev python dev/quality/format_all.py
uv run --project dev python dev/quality/format_all.py --check
```

Use default tool settings: Ruff checks with automatic fixes and Ruff formatting
for Python, markdownlint with automatic fixes for Markdown, and clang-format for
C/C++ and Arduino `.ino` files. Fix remaining lint errors before committing.
Review and stage formatter changes. Keep the pre-commit hook installed.
