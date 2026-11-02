#!/bin/bash
set -eu
umask 077
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  echo "No local installation in this folder yet."
  exit 0
fi
"$APP_DIR/.venv/bin/python" "$APP_DIR/mac/launcher.py" stop
