# Car system management

Setup and update tools live here. The car Python environment uses Raspberry Pi
OS Python with system package access for Picamera2. See the root README for
setup commands. Arduino firmware and Pi-side build and flash scripts live in
`arduino/`.

## Interactive menu

`menu.sh` is a reusable Bash selection menu with arrow-key navigation and an
always-visible Back option. It requires an interactive ANSI terminal, including
an SSH terminal. It uses standard Bash and stty, with no Python dependencies.

From the car directory:

```bash
selection=$(./system/menu.sh --title "Car system" "Setup" "Update" "Flash Arduino")
```

Or source it from another Bash script:

```bash
source ./system/menu.sh
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
