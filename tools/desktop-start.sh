#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
if [ -x "$SCRIPT_DIR/VideoMate.app/Contents/MacOS/VideoMate" ]; then
    executable="$SCRIPT_DIR/VideoMate.app/Contents/MacOS/VideoMate"
else
    executable="$SCRIPT_DIR/VideoMate/VideoMate"
fi
case "${1:-}" in
    '') exec "$executable" ;;
    --check)
        [ "$#" -eq 1 ] || exit 2
        "$executable" --check
        printf '%s\n' 'VideoMate desktop dependencies ready. Offline; no separate Python required.' ;;
    --self-test|--config)
        [ "$#" -eq 2 ] || exit 2
        exec "$executable" "$@" ;;
    *) printf '%s\n' 'Usage: ./start.sh [--check | --self-test NEW-REPORT.json | --config SETTINGS.json]' 'Use the Python test kit for CLI commands.' >&2; exit 2 ;;
esac
