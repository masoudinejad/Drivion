#!/usr/bin/env bash
# Typed input UI. Only a validated answer is written to stdout.

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/theme.sh"

drivion_prompt() (
    local question="" type=text answer="" key sequence error="" valid normalized
    local saved_state rows columns width display
    local cyan amber red green gray bold dim reset
    drivion_load_theme || return 2

    while (( $# )); do
        case "$1" in
            --question|--type)
                if (( $# < 2 )); then
                    printf 'prompt.sh: %s requires a value\n' "$1" >&2
                    return 2
                fi
                if [[ $1 == --question ]]; then question=$2; else type=$2; fi
                shift 2
                ;;
            --help|-h)
                printf '%s\n' 'Usage: prompt.sh --question QUESTION [--type TYPE]' \
                    'Types: text, integer, number, boolean (default: text).' \
                    'Enter submits; Escape ignores (status 3); Ctrl-C cancels (130).'
                return 0
                ;;
            *) printf 'prompt.sh: unknown argument: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    if [[ -z $question || $question == *[[:cntrl:]]* ]]; then
        printf '%s\n' 'prompt.sh: provide a question without control characters' >&2
        return 2
    fi
    case "$type" in
        text|integer|number|boolean) ;;
        *) printf 'prompt.sh: unsupported type: %s\n' "$type" >&2; return 2 ;;
    esac
    if [[ ${TERM:-dumb} == dumb ]]; then
        printf '%s\n' 'prompt.sh: an interactive ANSI terminal is required' >&2
        return 2
    fi
    if ! { exec 3<>/dev/tty; } 2>/dev/null; then
        printf '%s\n' 'prompt.sh: no controlling terminal available' >&2
        return 2
    fi
    if ! saved_state=$(stty -g <&3); then return 2; fi
    trap 'stty "'"$saved_state"'" <&3; printf "\033[?25h\033[?1049l" >&3; exec 3>&-' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    if ! stty -echo -icanon -isig min 1 time 0 <&3; then return 2; fi
    printf '\033[?1049h' >&3

    while :; do
        read -r rows columns < <(stty size <&3)
        columns=${columns:-80}
        (( columns < 12 )) && columns=12
        width=$(( columns - 6 ))
        display=$answer
        if (( ${#display} > width )); then display=${display: -width}; fi
        printf '\033[?25l\033[H\033[2J\n  %s%s%s\n\n' "$bold" "${question:0:columns-4}" "$reset" >&3
        printf '  %sType: %s%s\n\n' "$dim" "$type" "$reset" >&3
        printf '  %sIgnore%s\n\n' "$amber" "$reset" >&3
        if [[ -n $error ]]; then printf '  %s%s%s\n\n' "$red" "$error" "$reset" >&3; fi
        printf '  %s[Enter] Submit  [Backspace] Edit  [Ctrl+U] Clear  [Esc] Ignore%s\n\n' \
            "$dim" "$reset" >&3
        printf '  %s▸ %s%s\033[?25h' "$cyan" "$display" "$reset" >&3
        if ! IFS= read -r -n 1 -u 3 key; then return 1; fi
        case "$key" in
            $'\003') return 130 ;;
            $'\004') return 1 ;;
            $'\033')
                if ! IFS= read -r -n 1 -t 1 -u 3 sequence; then return 3; fi
                # Discard navigation sequences; they must not become answer text.
                if [[ $sequence == '[' || $sequence == 'O' ]]; then
                    while IFS= read -r -n 1 -t 1 -u 3 key; do
                        [[ $key == [@-~] ]] && break
                    done
                fi
                ;;
            $'\177'|$'\010')
                if [[ -n $answer ]]; then answer=${answer:0:${#answer}-1}; fi
                ;;
            $'\025') answer="" ;;
            ''|$'\r')
                valid=0
                normalized=$answer
                case "$type" in
                    text)
                        [[ $answer =~ [^[:space:]] ]] && valid=1
                        error='Please enter non-empty text.'
                        ;;
                    integer)
                        [[ $answer =~ ^[+-]?[0-9]+$ ]] && valid=1
                        error='Please enter an integer, e.g. 30.'
                        ;;
                    number)
                        [[ $answer =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]] && valid=1
                        error='Please enter a number, e.g. 0.5.'
                        ;;
                    boolean)
                        normalized=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')
                        case "$normalized" in
                            y|yes|true) normalized=true; valid=1 ;;
                            n|no|false) normalized=false; valid=1 ;;
                        esac
                        error='Please enter yes/no, y/n, or true/false.'
                        ;;
                esac
                if (( valid )); then printf '%s\n' "$normalized"; return 0; fi
                answer=""
                ;;
            *)
                if [[ $key != *[[:cntrl:]]* ]]; then answer+=$key; fi
                ;;
        esac
    done
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    drivion_prompt "$@"
fi
