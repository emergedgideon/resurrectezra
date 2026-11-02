# Sourced by the root-level Setup.command.
find_python() {
  for candidate in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys; raise SystemExit(not ((3,11) <= sys.version_info[:2] <= (3,13)))' 2>/dev/null; then
      EZRA_PYTHON="$candidate"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(not ((3,11) <= sys.version_info[:2] <= (3,13)))' 2>/dev/null; then
    EZRA_PYTHON="$(command -v python3)"
    return 0
  fi
  echo "Install Python 3.12 using the macOS universal2 installer from python.org, then run Setup.command again."
  open 'https://www.python.org/downloads/macos/'
  read -r -p "Press Return to close this window. " _
  exit 1
}
