#!/bin/sh
# POSIX shell entry point; accepts Python executable paths containing spaces.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
MODE=${1:-offline}
if [ "$#" -gt 0 ]; then shift; fi
case "$MODE" in
    menu|offline|rpc|test) ;;
    help|-h|--help)
        printf '%s\n' 'Usage: sh scripts/demo.sh [offline|menu|rpc|test] [CLI arguments]' \
            'Default: build and run the offline teaching example.' \
            'RPC requires an explicit DELTA_RPC_URL or hidden prompt input; blank cancels.' \
            'Set DELTA_PYTHON to an existing Python 3.12+ executable if necessary.'
        exit 0 ;;
    *) printf '%s\n' "Unknown demo mode: $MODE" >&2; exit 2 ;;
esac

PYTHON=${DELTA_PYTHON:-}
DIR=$ROOT
while [ -z "$PYTHON" ]; do
    if [ -x "$DIR/.venv/bin/python" ]; then
        PYTHON=$DIR/.venv/bin/python
    elif [ -x "$DIR/.venv/Scripts/python.exe" ]; then
        PYTHON=$DIR/.venv/Scripts/python.exe
    elif [ "$DIR" = / ]; then
        PYTHON=$(command -v python3 || command -v python || true)
        break
    else
        DIR=$(dirname -- "$DIR")
    fi
done
if [ -z "$PYTHON" ]; then
    printf '%s\n' 'Python not found. Create a local .venv or set DELTA_PYTHON.' >&2
    exit 2
fi
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ is required")'
export PYTHONIOENCODING=utf-8
"$PYTHON" -m delta_terminal build
case "$MODE" in
    menu) exec "$PYTHON" -m delta_terminal "$@" ;;
    test) exec "$PYTHON" -m unittest delta_terminal.tests.test_terminal token_graph_dataset.tests.test_dataset token_graph_dataset.tests.test_collect -v "$@" ;;
    *) exec "$PYTHON" -m delta_terminal "$MODE" "$@" ;;
esac
