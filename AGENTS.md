# Project instructions

Consult the user before implementing changes unless the change has already been
agreed in the conversation.

When the user asks for a commit, that request authorizes committing only the
changes made by the agent for the current task. Do not stage or commit
pre-existing or unrelated changes unless the user explicitly includes them.
Follow commit best practices: keep each commit small and focused on one coherent
concept, include all related changes needed for that concept even when they span
multiple files, and do not combine unrelated concepts. Use a clear, specific
commit message so the change is easy to understand and track.

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
