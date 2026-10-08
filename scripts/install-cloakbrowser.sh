#!/usr/bin/env bash
#
# install-cloakbrowser.sh — install CloakBrowser (the stealth Chromium
# that powers scripts/extract-everything.py).
#
# Usage: ./scripts/install-cloakbrowser.sh
#
# What it does:
#   1. Installs the cloakbrowser pip package
#   2. Downloads the patched Chromium binary (~200 MB)
#   3. Installs Playwright (which CloakBrowser drives)
#   4. Installs xvfb if you're on a headless Linux box (optional)
#
# Tested on: macOS 13+, Ubuntu 22.04+, Debian 12+

set -euo pipefail

echo "▶ Installing cloakbrowser pip package…"
pip install -U --break-system-packages cloakbrowser || \
    pip install -U cloakbrowser

echo "▶ Downloading patched Chromium binary (one-time, ~200 MB)…"
python3 -m cloakbrowser install

echo "▶ Installing Playwright…"
pip install -U --break-system-packages playwright || \
    pip install -U playwright
playwright install-deps chromium 2>/dev/null || true

# xvfb is only needed on headless Linux for the login UI
if [[ "$(uname -s)" == "Linux" ]] && [[ -z "${DISPLAY:-}" ]] && \
   ! command -v xvfb-run >/dev/null 2>&1; then
    echo "▶ Installing xvfb (for headless Linux login UI)…"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y xvfb
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y xorg-x11-server-Xvfb
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y xorg-x11-server-Xvfb
    fi
fi

echo
echo "✓ All set. Now run:"
echo "  python3 scripts/extract-everything.py"
echo
echo "If you're on a headless server without a display:"
echo "  xvfb-run -a python3 scripts/extract-everything.py"
