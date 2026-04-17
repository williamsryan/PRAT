#!/usr/bin/env bash
# fetch-targets.sh — Download target projects for PRAT analysis
#
# Usage:
#   ./scripts/fetch-targets.sh              # Fetch all targets
#   ./scripts/fetch-targets.sh mosquitto    # Fetch only Mosquitto
#   ./scripts/fetch-targets.sh ffmpeg       # Fetch only FFmpeg
#
# Target projects are stored in App/ and are .gitignored.
# Run this after cloning the repo to set up demo targets.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/App"

# Pinned versions for reproducibility
MOSQUITTO_VERSION="v2.0.15"
MOSQUITTO_REPO="https://github.com/eclipse/mosquitto.git"

FFMPEG_VERSION="n5.1.4"
FFMPEG_REPO="https://github.com/FFmpeg/FFmpeg.git"

fetch_mosquitto() {
    echo "[+] Fetching Mosquitto ${MOSQUITTO_VERSION}..."
    if [ -d "$APP_DIR/mosquitto" ]; then
        echo "    Already exists. Skipping. (Delete App/mosquitto to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$MOSQUITTO_VERSION" "$MOSQUITTO_REPO" "$APP_DIR/mosquitto"
    echo "[+] Mosquitto ready at App/mosquitto"
}

fetch_ffmpeg() {
    echo "[+] Fetching FFmpeg ${FFMPEG_VERSION}..."
    if [ -d "$APP_DIR/FFmpeg" ]; then
        echo "    Already exists. Skipping. (Delete App/FFmpeg to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$FFMPEG_VERSION" "$FFMPEG_REPO" "$APP_DIR/FFmpeg"
    echo "[+] FFmpeg ready at App/FFmpeg"
}

mkdir -p "$APP_DIR"

TARGET="${1:-all}"

case "$TARGET" in
    mosquitto)
        fetch_mosquitto
        ;;
    ffmpeg)
        fetch_ffmpeg
        ;;
    all)
        fetch_mosquitto
        fetch_ffmpeg
        ;;
    *)
        echo "Unknown target: $TARGET"
        echo "Usage: $0 [mosquitto|ffmpeg|all]"
        exit 1
        ;;
esac

echo ""
echo "[+] Done. Target projects are in App/"
echo "    These are .gitignored and won't be committed."
