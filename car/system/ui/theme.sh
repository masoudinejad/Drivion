#!/usr/bin/env bash
# Load the same TOML palette used by the Python UI without evaluating shell code.

drivion_load_theme() {
    local theme_codes theme_name
    theme_codes=$(python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/theme.py") || return
    read -r cyan amber red green gray bold dim reset <<< "$theme_codes"
    for theme_name in cyan amber red green gray bold dim reset; do
        if [[ -n ${NO_COLOR+x} ]]; then
            printf -v "$theme_name" '%s' ''
        else
            printf -v "$theme_name" '\033[%sm' "${!theme_name}"
        fi
    done
}
