#!/bin/bash
set -eu
umask 077
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
source "$APP_DIR/mac/common.sh"
find_python
"$EZRA_PYTHON" "$APP_DIR/mac/launcher.py" setup
read -r -p "Press Return to close this window. " _
