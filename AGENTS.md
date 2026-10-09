# Project instructions

Consult the user before implementing changes unless the change has already been
agreed in the conversation.

Act as a responsible quality steward for the project. When reviewing or changing
the project:

- Keep code clean, simple, maintainable, and appropriately optimized. Prefer
  clear implementations over unnecessary complexity, and identify duplicated,
  dead, or inefficient code.
- Keep configuration centralized in TOML configuration files. Do not hard-code
  configurable values in application code or scatter configuration across the
  repository.
- Keep code and configuration well documented. Update relevant documentation,
  docstrings, comments, and examples when behavior or configuration changes.
- Validate changes with the relevant tests, linters, formatters, and other
  project-wide quality checks. Report unresolved risks or quality issues clearly.

Before every commit, run the whole-project formatting checks:

```sh
uv run --project dev python dev/quality/format_all.py
uv run --project dev python dev/quality/format_all.py --check
```

Use default tool settings: Ruff checks with automatic fixes and Ruff formatting
for Python, markdownlint with automatic fixes for Markdown, and clang-format for
C/C++ and Arduino `.ino` files. Fix remaining lint errors before committing.
Review and stage formatter changes. Keep the pre-commit hook installed.
