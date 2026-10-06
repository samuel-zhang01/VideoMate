#!/bin/sh
# POSIX launcher; pinned local dependencies, no package manager or sudo.
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
if [ "$#" -eq 0 ] && [ ! -f "$SCRIPT_DIR/src/videomate/gui.py" ]; then
    if [ -x "$SCRIPT_DIR/VideoMate.app/Contents/MacOS/VideoMate" ]; then
        exec "$SCRIPT_DIR/VideoMate.app/Contents/MacOS/VideoMate"
    fi
    if [ -x "$SCRIPT_DIR/VideoMate/VideoMate" ]; then
        exec "$SCRIPT_DIR/VideoMate/VideoMate"
    fi
fi
if [ -z "${VIDEOMATE_PYTHON:-}" ]; then
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        VIDEOMATE_PYTHON="$VIRTUAL_ENV/bin/python"
        export VIDEOMATE_PYTHON
    elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
        VIDEOMATE_PYTHON="$CONDA_PREFIX/bin/python"
        export VIDEOMATE_PYTHON
    fi
fi
if [ -n "${VIDEOMATE_PYTHON:-}" ]; then
    exec "$VIDEOMATE_PYTHON" -I -X utf8 "$SCRIPT_DIR/tools/bootstrap.py" "$@"
fi
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) platform=macos-arm64 ;;
    Linux-x86_64) platform=linux-x86_64 ;;
    Linux-aarch64|Linux-arm64) platform=linux-arm64 ;;
    *) platform=unsupported ;;
esac
runtime_root="$SCRIPT_DIR/dependencies/python"
case "$platform:$SCRIPT_DIR" in
    linux-*:/mnt/[a-z]/*) runtime_root="${XDG_CACHE_HOME:-$HOME/.cache}/videomate-software/python" ;;
esac
runtime_root="${VIDEOMATE_RUNTIME_ROOT:-$runtime_root}"
if [ -x "$runtime_root/$platform/python/bin/python3" ]; then
    exec "$runtime_root/$platform/python/bin/python3" -I -X utf8 "$SCRIPT_DIR/tools/bootstrap.py" "$@"
fi
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -c 'import sys,struct;sys.exit(not(sys.version_info >= (3,11) and struct.calcsize("P") == 8))' 2>/dev/null; then
        exec "$candidate" -I -X utf8 "$SCRIPT_DIR/tools/bootstrap.py" "$@"
    fi
done
sh "$SCRIPT_DIR/tools/bootstrap_runtime.sh" "$platform" "$@"
exec "$runtime_root/$platform/python/bin/python3" -I -X utf8 "$SCRIPT_DIR/tools/bootstrap.py" "$@"
