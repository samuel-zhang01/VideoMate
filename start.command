#!/bin/sh
# Finder launcher for the source/Python edition on Apple Silicon.
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P) || exit 2
exec /bin/sh "$SCRIPT_DIR/start.sh" "$@"
