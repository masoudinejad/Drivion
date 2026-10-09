#!/usr/bin/env bash
# Reusable selection UI. Terminal interaction stays on /dev/tty; stdout is data.

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/theme.sh"

drivion_menu() (
    local title="Select an option" option key sequence saved_state=""
    local selected=0 first=0 count rows columns visible index last label
    local owns_screen=0
    local cyan amber red green gray bold dim reset
    local -a options=()
    drivion_load_theme || return 2

    while (( $# )); do
        case "$1" in
            --title)
                if (( $# < 2 )); then
                    printf '%s\n' 'menu.sh: --title requires a value' >&2
                    return 2
                fi
                title=$2
                shift 2
                ;;
            --)
                shift
                options+=("$@")
                break
                ;;
            --help|-h)
                printf '%s\n' 'Usage: menu.sh [--title TITLE] [--] OPTION...' \
                    'Returns an option number (1-based), or 0 for Back.' \
                    'Keys: Up/Down, Enter, Escape for Back; Ctrl-C cancels.'
                return 0
                ;;
            *)
                options+=("$1")
                shift
                ;;
        esac
    done

    for option in "$title" "${options[@]}"; do
        if [[ $option == *[[:cntrl:]]* ]]; then
            printf '%s\n' 'menu.sh: labels must not contain control characters' >&2
            return 2
        fi
    done
    if [[ ${TERM:-dumb} == dumb ]]; then
        printf '%s\n' 'menu.sh: an interactive ANSI terminal is required' >&2
        return 2
    fi
    if ! { exec 3<>/dev/tty; } 2>/dev/null; then
        printf '%s\n' 'menu.sh: no controlling terminal available' >&2
        return 2
    fi
    if ! saved_state=$(stty -g <&3); then
        return 2
    fi
    # The subshell keeps traps, terminal descriptors, and variables out of callers.
    # Only the screen owner switches back to the shell on exit.
    trap 'stty "'"$saved_state"'" <&3; printf "\033[?25h" >&3; if (( owns_screen )); then printf "\033[?1049l" >&3; fi; exec 3>&-' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    if ! stty -echo -icanon -isig min 1 time 0 <&3; then
        return 2
    fi
    if [[ ${DRIVION_UI_SCREEN_ACTIVE:-0} != 1 ]]; then
        owns_screen=1
        printf '\033[?1049h' >&3
    fi
    printf '\033[?25l' >&3
    count=${#options[@]}

    while :; do
        read -r rows columns < <(stty size <&3)
        rows=${rows:-24}
        columns=${columns:-80}
        (( columns < 10 )) && columns=10
        visible=$(( rows - 8 ))
        (( visible < 1 )) && visible=1
        if (( selected < count )); then
            (( selected < first )) && first=$selected
            (( selected >= first + visible )) && first=$(( selected - visible + 1 ))
        fi
        last=$(( first + visible ))
        (( last > count )) && last=$count
        printf '\033[H\033[2J\n  %s%s%s\n\n' "$bold" "${title:0:columns-4}" "$reset" >&3
        for (( index=first; index<last; index++ )); do
            label=${options[index]:0:columns-6}
            if (( selected == index )); then
                printf '  %s▸ %s%s\n' "$cyan" "$label" "$reset" >&3
            else
                printf '    %s\n' "$label" >&3
            fi
        done
        if (( selected == count )); then
            printf '\n  %s▸ Back%s\n' "$cyan" "$reset" >&3
        else
            printf '\n    Back\n' >&3
        fi
        printf '\n  %s[↑/↓] Move    [Enter] Select%s\n' "$dim" "$reset" >&3

        if ! IFS= read -r -n 1 -u 3 key; then
            return 1
        fi
        case "$key" in
            $'\003') return 130 ;;
            $'\033')
                # Distinguish a lone Escape from an arrow-key escape sequence.
                if ! IFS= read -r -n 1 -t 1 -u 3 sequence; then
                    printf '0\n'
                    return 0
                fi
                if [[ $sequence == '[' || $sequence == 'O' ]]; then
                    if IFS= read -r -n 1 -t 1 -u 3 key; then
                        case "$key" in
                            A) selected=$(( (selected + count) % (count + 1) )) ;;
                            B) selected=$(( (selected + 1) % (count + 1) )) ;;
                        esac
                    fi
                fi
                ;;
            ''|$'\r')
                if (( selected == count )); then
                    printf '0\n'
                else
                    printf '%s\n' "$(( selected + 1 ))"
                fi
                return 0
                ;;
        esac
    done
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    drivion_menu "$@"
fi
