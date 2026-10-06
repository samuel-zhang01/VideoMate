#!/bin/sh
# Used only when start.sh cannot find Python. All extracted bytes are pinned.
set -eu
umask 077
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
tag=$1
shift
offline=no
approved=no
archive=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cli) break ;;
        --offline) offline=yes ;;
        --yes|--setup-online) approved=yes ;;
        --runtime-archive)
            shift
            [ "$#" -gt 0 ] || { printf '%s\n' 'Missing runtime archive argument.' >&2; exit 2; }
            archive=$1 ;;
    esac
    shift
done
case "$tag" in macos-arm64|linux-x86_64|linux-arm64) ;; *) printf '%s\n' 'Unsupported platform.' >&2; exit 2 ;; esac
record=$(awk -F '\t' -v tag="$tag" '$1 == tag {print $2 " " $3 " " $4}' "$ROOT/dependencies/runtime-bootstrap.tsv")
IFS=' ' read -r sha filename url <<EOF
$record
EOF
[ "${#sha}" -eq 64 ] && [ -n "$filename" ] || exit 2
cache="$ROOT/dependencies/cache"
runtime_root="$ROOT/dependencies/python"
case "$tag:$ROOT" in linux-*:/mnt/[a-z]/*) runtime_root="${XDG_CACHE_HOME:-$HOME/.cache}/videomate-software/python" ;; esac
runtime_root="${VIDEOMATE_RUNTIME_ROOT:-$runtime_root}"
export VIDEOMATE_RUNTIME_ROOT="$runtime_root"
mkdir -p "$cache" "$runtime_root"
# mktemp creates our exclusive staging area; cleanup touches only this directory.
stage=$(mktemp -d "$runtime_root/.bootstrap-XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 130' INT TERM HUP
if [ -z "$archive" ]; then
    archive="$cache/$filename"
    if [ ! -f "$archive" ]; then
        [ "$offline" = no ] || { printf '%s\n' 'Offline setup needs the pinned Python/Tk archive in dependencies/cache or --runtime-archive.' >&2; exit 2; }
        if [ "$approved" != yes ]; then
            printf '%s\n' 'A compatible Python was not found. VideoMate can install its pinned Python/Tk runtime locally.' 'No administrator access, PATH changes, venv or Conda installation is needed.' 'Alternatively install Python 3.11+ from https://www.python.org/downloads/ or set VIDEOMATE_PYTHON to an existing interpreter.'
            [ -t 0 ] || { printf '%s\n' 'No interactive terminal is available. Run sh start.sh --yes to approve setup, or use a complete runtime kit.' >&2; exit 2; }
            printf '%s' 'Download and install the local Python/Tk runtime? [y/N] '
            read -r answer || answer=no
            case "$answer" in y|Y|yes|YES|Yes) ;; *) printf '%s\n' 'Setup cancelled. No software was downloaded.'; exit 2 ;; esac
        fi
        printf '%s\n' 'Downloading pinned Python/Tk. No system packages will change.'
        curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 30 --max-time 600 --max-filesize 268435456 --retry 2 --output "$stage/runtime.tar.gz" "$url"
        archive="$stage/runtime.tar.gz"
    fi
fi
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum < "$archive" | awk '{print $1}')
else
    actual=$(shasum -a 256 < "$archive" | awk '{print $1}')
fi
[ "$actual" = "$sha" ] || { printf '%s\n' 'Python archive checksum mismatch; nothing was installed.' >&2; exit 2; }
# Extraction is permitted only after an exact match to the checked-in pin.
mkdir "$stage/unpack"
tar -xzf "$archive" -C "$stage/unpack"
"$stage/unpack/python/bin/python3" -I -X utf8 "$ROOT/tools/install_python.py" --platform "$tag" --archive "$archive"
