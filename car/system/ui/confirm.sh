#!/usr/bin/env bash
# Confirmation UI shares the typed prompt's validation and visual style.

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/prompt.sh"

drivion_confirm() (
    local answer status
    if [[ $# != 2 || $1 != --question || -z $2 ]]; then
        printf '%s\n' 'Usage: confirm.sh --question QUESTION' >&2
        return 2
    fi
    if answer=$(drivion_prompt --question "$2 (yes/no or y/n)" --type boolean); then
        case "$answer" in
            true) return 0 ;;
            *) return 1 ;;
        esac
    else
        status=$?
        [[ $status == 3 ]] && return 1
        return "$status"
    fi
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    drivion_confirm "$@"
fi
