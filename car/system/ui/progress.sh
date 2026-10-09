#!/usr/bin/env bash
# Sourceable command progress helper; Python uses only its standard library.

drivion_progress() (
    local script
    script="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/progress.py"
    python3 "$script" "$@"
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    drivion_progress "$@"
fi
