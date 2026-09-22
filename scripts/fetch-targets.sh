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
# The paper does not publish source commits. This compatibility corpus pins
# named releases to immutable commits so repeated runs analyze identical code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/App"

# ── Pinned versions for reproducibility ──────────────────────────────────────

MOSQUITTO_VERSION="v2.0.15"
MOSQUITTO_COMMIT="b0277869d9806f6fab8e1bc11c4a4987c9a79ded"
MOSQUITTO_REPO="https://github.com/eclipse/mosquitto.git"

FFMPEG_VERSION="n5.1.4"
FFMPEG_COMMIT="4729204c17f756e186d622060088371d10b34f7e"
FFMPEG_REPO="https://github.com/FFmpeg/FFmpeg.git"

UAMQP_VERSION="v1.2.0"
UAMQP_COMMIT="9701f09a4db40afb53f5086662be64e8fac78bbf"
UAMQP_REPO="https://github.com/Azure/azure-uamqp-c.git"

OPENDDS_VERSION="DDS-3.25"
OPENDDS_COMMIT="2038b660f2037fb0758dbf106005d77f3b2d52f8"
OPENDDS_REPO="https://github.com/OpenDDS/OpenDDS.git"

QUICHE_VERSION="0.20.1"
QUICHE_COMMIT="dae27b7d5a0dcf8304a56ffd295399fc00ec03e9"
QUICHE_REPO="https://github.com/cloudflare/quiche.git"

RAV1E_VERSION="v0.7.1"
RAV1E_COMMIT="a8d05d0c43826a465b60dbadd0ab7f1327d75371"
RAV1E_REPO="https://github.com/xiph/rav1e.git"

AOM_VERSION="v3.7.1"
AOM_COMMIT="aca387522ccc0a1775716923d5489dd2d4b1e628"
AOM_REPO="https://aomedia.googlesource.com/aom"

# ── Fetch functions ──────────────────────────────────────────────────────────

verify_commit() {
    local directory="$1"
    local expected="$2"
    local actual
    actual="$(git -C "$directory" rev-parse HEAD)"
    if [ "$actual" != "$expected" ]; then
        echo "[!] Source revision mismatch in $directory" >&2
        echo "    expected: $expected" >&2
        echo "    actual:   $actual" >&2
        return 1
    fi
}

verify_existing_checkout() {
    local directory="$1"
    local expected="$2"
    verify_commit "$directory" "$expected"
    git -C "$directory" diff --quiet
    git -C "$directory" diff --cached --quiet
    if git -C "$directory" submodule status --recursive | grep -Eq '^[-+U]'; then
        echo "[!] Submodule revision mismatch in $directory" >&2
        return 1
    fi
}

fetch_mosquitto() {
    echo "[+] Fetching Mosquitto ${MOSQUITTO_VERSION}..."
    if [ -d "$APP_DIR/mosquitto" ]; then
        verify_existing_checkout "$APP_DIR/mosquitto" "$MOSQUITTO_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$MOSQUITTO_VERSION" "$MOSQUITTO_REPO" "$APP_DIR/mosquitto"
    verify_commit "$APP_DIR/mosquitto" "$MOSQUITTO_COMMIT"
    echo "[+] Mosquitto ready at App/mosquitto"
}

fetch_ffmpeg() {
    echo "[+] Fetching FFmpeg ${FFMPEG_VERSION}..."
    if [ -d "$APP_DIR/FFmpeg" ]; then
        verify_existing_checkout "$APP_DIR/FFmpeg" "$FFMPEG_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$FFMPEG_VERSION" "$FFMPEG_REPO" "$APP_DIR/FFmpeg"
    verify_commit "$APP_DIR/FFmpeg" "$FFMPEG_COMMIT"
    echo "[+] FFmpeg ready at App/FFmpeg"
}

fetch_uamqp() {
    echo "[+] Fetching azure-uamqp-c ${UAMQP_VERSION}..."
    if [ -d "$APP_DIR/azure-uamqp-c" ]; then
        verify_existing_checkout "$APP_DIR/azure-uamqp-c" "$UAMQP_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$UAMQP_VERSION" "$UAMQP_REPO" "$APP_DIR/azure-uamqp-c"
    verify_commit "$APP_DIR/azure-uamqp-c" "$UAMQP_COMMIT"
    # azure-uamqp-c uses git submodules for dependencies
    (cd "$APP_DIR/azure-uamqp-c" && git submodule update --init --recursive --depth 1)
    echo "[+] azure-uamqp-c ready at App/azure-uamqp-c"
}

fetch_opendds() {
    echo "[+] Fetching OpenDDS ${OPENDDS_VERSION}..."
    if [ -d "$APP_DIR/OpenDDS" ]; then
        verify_existing_checkout "$APP_DIR/OpenDDS" "$OPENDDS_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$OPENDDS_VERSION" "$OPENDDS_REPO" "$APP_DIR/OpenDDS"
    verify_commit "$APP_DIR/OpenDDS" "$OPENDDS_COMMIT"
    echo "[+] OpenDDS ready at App/OpenDDS"
}

fetch_quiche() {
    echo "[+] Fetching Quiche ${QUICHE_VERSION}..."
    if [ -d "$APP_DIR/quiche" ]; then
        verify_existing_checkout "$APP_DIR/quiche" "$QUICHE_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$QUICHE_VERSION" "$QUICHE_REPO" "$APP_DIR/quiche"
    verify_commit "$APP_DIR/quiche" "$QUICHE_COMMIT"
    (cd "$APP_DIR/quiche" && git submodule update --init --recursive --depth 1)
    echo "[+] Quiche ready at App/quiche"
}

fetch_rav1e() {
    echo "[+] Fetching rav1e ${RAV1E_VERSION}..."
    if [ -d "$APP_DIR/rav1e" ]; then
        verify_existing_checkout "$APP_DIR/rav1e" "$RAV1E_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$RAV1E_VERSION" "$RAV1E_REPO" "$APP_DIR/rav1e"
    verify_commit "$APP_DIR/rav1e" "$RAV1E_COMMIT"
    echo "[+] rav1e ready at App/rav1e"
}

fetch_aom() {
    echo "[+] Fetching AOM (libaom) ${AOM_VERSION}..."
    if [ -d "$APP_DIR/aom" ]; then
        verify_existing_checkout "$APP_DIR/aom" "$AOM_COMMIT"
        echo "    Existing checkout matches the pinned revision."
        return 0
    fi
    git clone --depth 1 --branch "$AOM_VERSION" "$AOM_REPO" "$APP_DIR/aom"
    verify_commit "$APP_DIR/aom" "$AOM_COMMIT"
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
