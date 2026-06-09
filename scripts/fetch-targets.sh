#!/usr/bin/env bash
# fetch-targets.sh — Download target projects for PRAT analysis
#
# Usage:
#   ./scripts/fetch-targets.sh              # Fetch all targets
#   ./scripts/fetch-targets.sh mosquitto    # Fetch only Mosquitto
#   ./scripts/fetch-targets.sh ffmpeg       # Fetch only FFmpeg
#   ./scripts/fetch-targets.sh uamqp        # Fetch only azure-uamqp-c
#   ./scripts/fetch-targets.sh opendds      # Fetch only OpenDDS
#   ./scripts/fetch-targets.sh quiche       # Fetch only Quiche
#   ./scripts/fetch-targets.sh rav1e        # Fetch only rav1e
#   ./scripts/fetch-targets.sh aom          # Fetch only AOM (libaom)
#
# Target projects are stored in App/ and are .gitignored.
# Run this after cloning the repo to set up demo targets.
#
# All versions are pinned to match the TOSEM 2021 paper evaluation period.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/App"

# ── Pinned versions for reproducibility ──────────────────────────────────────

MOSQUITTO_VERSION="v2.0.15"
MOSQUITTO_REPO="https://github.com/eclipse/mosquitto.git"

FFMPEG_VERSION="n5.1.4"
FFMPEG_REPO="https://github.com/FFmpeg/FFmpeg.git"

UAMQP_VERSION="2024-01-22"
UAMQP_REPO="https://github.com/Azure/azure-uamqp-c.git"

OPENDDS_VERSION="DDS-3.25"
OPENDDS_REPO="https://github.com/OpenDDS/OpenDDS.git"

QUICHE_VERSION="0.20.1"
QUICHE_REPO="https://github.com/cloudflare/quiche.git"

RAV1E_VERSION="v0.7.1"
RAV1E_REPO="https://github.com/xiph/rav1e.git"

AOM_VERSION="v3.7.1"
AOM_REPO="https://aomedia.googlesource.com/aom"

# ── Fetch functions ──────────────────────────────────────────────────────────

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

fetch_uamqp() {
    echo "[+] Fetching azure-uamqp-c ${UAMQP_VERSION}..."
    if [ -d "$APP_DIR/azure-uamqp-c" ]; then
        echo "    Already exists. Skipping. (Delete App/azure-uamqp-c to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$UAMQP_VERSION" "$UAMQP_REPO" "$APP_DIR/azure-uamqp-c"
    # azure-uamqp-c uses git submodules for dependencies
    (cd "$APP_DIR/azure-uamqp-c" && git submodule update --init --recursive --depth 1)
    echo "[+] azure-uamqp-c ready at App/azure-uamqp-c"
}

fetch_opendds() {
    echo "[+] Fetching OpenDDS ${OPENDDS_VERSION}..."
    if [ -d "$APP_DIR/OpenDDS" ]; then
        echo "    Already exists. Skipping. (Delete App/OpenDDS to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$OPENDDS_VERSION" "$OPENDDS_REPO" "$APP_DIR/OpenDDS"
    echo "[+] OpenDDS ready at App/OpenDDS"
}

fetch_quiche() {
    echo "[+] Fetching Quiche ${QUICHE_VERSION}..."
    if [ -d "$APP_DIR/quiche" ]; then
        echo "    Already exists. Skipping. (Delete App/quiche to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$QUICHE_VERSION" "$QUICHE_REPO" "$APP_DIR/quiche"
    echo "[+] Quiche ready at App/quiche"
}

fetch_rav1e() {
    echo "[+] Fetching rav1e ${RAV1E_VERSION}..."
    if [ -d "$APP_DIR/rav1e" ]; then
        echo "    Already exists. Skipping. (Delete App/rav1e to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$RAV1E_VERSION" "$RAV1E_REPO" "$APP_DIR/rav1e"
    echo "[+] rav1e ready at App/rav1e"
}

fetch_aom() {
    echo "[+] Fetching AOM (libaom) ${AOM_VERSION}..."
    if [ -d "$APP_DIR/aom" ]; then
        echo "    Already exists. Skipping. (Delete App/aom to re-fetch)"
        return 0
    fi
    git clone --depth 1 --branch "$AOM_VERSION" "$AOM_REPO" "$APP_DIR/aom"
    echo "[+] AOM ready at App/aom"
}

# ── Main ─────────────────────────────────────────────────────────────────────

mkdir -p "$APP_DIR"

TARGET="${1:-all}"

case "$TARGET" in
    mosquitto)
        fetch_mosquitto
        ;;
    ffmpeg)
        fetch_ffmpeg
        ;;
    uamqp|azure-uamqp-c)
        fetch_uamqp
        ;;
    opendds)
        fetch_opendds
        ;;
    quiche)
        fetch_quiche
        ;;
    rav1e)
        fetch_rav1e
        ;;
    aom|libaom)
        fetch_aom
        ;;
    all)
        fetch_mosquitto
        fetch_ffmpeg
        fetch_uamqp
        fetch_opendds
        fetch_quiche
        fetch_rav1e
        fetch_aom
        ;;
    *)
        echo "Unknown target: $TARGET"
        echo "Usage: $0 [mosquitto|ffmpeg|uamqp|opendds|quiche|rav1e|aom|all]"
        exit 1
        ;;
esac

echo ""
echo "[+] Done. Target projects are in App/"
echo "    These are .gitignored and won't be committed."
