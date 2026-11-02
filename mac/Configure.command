#!/bin/bash
set -eu
umask 077
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  echo "Run Setup.command first."
  read -r -p "Press Return to close this window. " _
  exit 1
fi
"$APP_DIR/.venv/bin/python" "$APP_DIR/mac/launcher.py" configure
read -r -p "Press Return to close this window. " _
