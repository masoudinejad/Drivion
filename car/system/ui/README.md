# Terminal interactions

Reusable Bash UI helpers for car system operations.

## Drive startup

`startup.py` provides the Python startup display used by `car/drive.py`. It shows
a bold cyan Drivion banner using the `art` package's `small` font after the
configured Python environment has been entered, followed by configuration and
environment status. Driving remains a
placeholder, so it does not report camera or model readiness.

The display clears the visible interactive terminal before showing the banner,
and matches the menu's cyan, bold, and dim styling without additional
dependencies beyond the existing `art` package or an artificial startup delay.
Redirected output and `TERM=dumb` use plain text without ANSI escape sequences.
`NO_COLOR` disables color and
styling while keeping the interactive screen clear.
Narrow terminals and redirected output use a single-line DRIVION title.
Gray horizontal lines frame the banner and its subtitle. The ASCII letters use
two extra spaces between characters.

## Interactive menu

`menu.sh` is a reusable Bash selection menu with arrow-key navigation and an
always-visible Back option. It requires an interactive ANSI terminal, including
an SSH terminal. It uses Bash and stty for interaction and Python 3.11 or newer
to load the shared TOML theme.

From the car directory:

```bash
selection=$(./system/ui/menu.sh \
    --title "Car system" "Setup" "Update" "Flash Arduino")
```

Or source it from another Bash script:

```bash
source ./system/ui/menu.sh
if selection=$(drivion_menu --title "Car system" "Setup" "Update"); then
    case "$selection" in
        1) printf 'Setup selected\n' ;;
        2) printf 'Update selected\n' ;;
        0) printf 'Back selected\n' ;;
    esac
fi
```

Pass a Bash array with `drivion_menu --title "Menu" -- "${options[@]}"`.
The `--` separator allows labels such as `--help` to be treated as options.
The result is a 1-based option number, or `0` for Back. Up/Down wraps around,
Enter confirms, Escape selects Back, and Ctrl-C cancels with exit status 130.
Other errors use a nonzero status. Empty option lists display Back alone.

The interface uses the controlling terminal; only the result goes to stdout.
It restores terminal settings and the previous screen when it exits. Long lists
scroll while Back stays visible. Set `NO_COLOR=1` to disable styling. The menu
does not perform the selected action; its caller decides what to do next.

## Typed questions

`prompt.sh` uses the same terminal style to ask for a typed answer. Invalid input
shows an error and asks again. Ignore is always displayed in amber; press Escape
to skip the question. From the car directory:

```bash
if answer=$(./system/ui/prompt.sh \
    --question "Camera frame rate?" --type integer); then
    printf 'Frame rate: %s\n' "$answer"
else
    status=$?
    case "$status" in
        3) printf 'Question ignored\n' ;;
        130) printf 'Cancelled\n' ;;
        *) printf 'Prompt failed: %s\n' "$status" >&2 ;;
    esac
fi
```

Or source `system/ui/prompt.sh` and call `drivion_prompt` with the same arguments.
Supported types are `text` (default, non-blank), `integer` (optional sign),
`number` (decimal or scientific notation), and `boolean`. Boolean input accepts
yes/no, y/n, and true/false without case sensitivity, returning `true` or `false`.
Other answers are returned unchanged; numeric validation checks syntax, not
hardware limits or ranges. Numeric input must not contain surrounding spaces.

Only valid answers go to stdout. Ignore returns no answer and status 3;
Ctrl-C returns 130; errors return another nonzero status. Enter submits,
Backspace edits, and Ctrl-U clears input. Arrow keys are ignored. Terminal state
and the previous screen are restored on exit. `NO_COLOR=1` disables styling.

## Confirmation

`confirm.sh` provides `drivion_confirm --question "Continue?"` when sourced,
or can be run with Bash. It reuses the prompt's cyan input, amber Ignore,
and dim keyboard hints. Type yes/no or y/n in any letter case and press Enter.
Long questions wrap to the terminal width so the complete question and answer
hints remain visible. Invalid or empty input asks again. Yes returns status 0;
No or Escape/Ignore returns 1; Ctrl-C returns
130, and terminal or argument errors return 2. No answer is written to stdout.

```bash
source ./system/ui/confirm.sh
if drivion_confirm --question "Apply the update?"; then
    printf 'Confirmed\n'
fi
```

## Work in progress

`progress.sh` provides `drivion_progress` when sourced. It runs a command with
a cyan spinner and dim message until the command finishes, preserving its
exit status and output. Use it for non-interactive work; interactive commands
should use the menu or prompt directly. Feedback goes to stderr. Redirected
output and `TERM=dumb` get one plain line; `NO_COLOR` removes styling.

```bash
bash ./system/ui/progress.sh --message "Checking environment" -- \
    python3 ./system/verify_environment.py
```

Python callers can use `show_progress` from `system.ui.progress` as a context
manager around work, including waiting for a background future:

```python
with show_progress("Loading configuration"):
    configuration = load_configuration()
```

The spinner stops and clears its line on success or failure, and exceptions
propagate to the caller.

`run_background(message, operation, *args, **kwargs)` runs a callable in a
worker thread, displays progress, and returns its result or propagates its
exception. Operations must avoid writing to the progress stream. The initial
startup banner uses this helper to prepare its ASCII title in the background;
its rendering function contains no animation logic or forced delay.

## Shared theme

`theme.toml` is the single source of ANSI colors and text styles. Python uses
`theme.py`; Bash uses `theme.sh` to load the same validated palette with Python
3.11 or newer. Edit the TOML file to change the appearance of menus, prompts,
confirmations, progress indicators, and the startup banner together.
`NO_COLOR` continues to disable styling across all elements.

## Raspberry Pi UI walkthrough

Run the single interactive test file from the deployed car directory using the
provisioned Python environment (which includes `art`):

```bash
./system/env/drivion/bin/python ./system/ui/test_ui.py
```

The walkthrough shows the startup banner, background and command progress,
menu, confirmation, and each typed prompt. It reports answers and exit statuses
and performs no hardware or configuration changes. Try arrows, Enter, Escape,
invalid input, and editing keys; Ctrl-C cancels the walkthrough. The two progress
demonstrations each wait two seconds so the spinner can be inspected.
Run again with `NO_COLOR=1` to check the unstyled appearance. If the environment
path in `config.toml` was customized, use that environment's Python instead.
