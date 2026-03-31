#!/usr/bin/env bash
set -euo pipefail

# obsidian-nlm-cli one-click setup
# Usage: curl -sSL https://raw.githubusercontent.com/.../setup.sh | bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---- Check prerequisites ----
info "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || error "Python 3 is required. Install it first."
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" || error "Python 3.10+ required, got $PYTHON_VERSION"

command -v ffmpeg >/dev/null 2>&1 || warn "ffmpeg not found. Install via: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"

command -v git >/dev/null 2>&1 || error "git is required."

# ---- Determine install location ----
INSTALL_DIR="${1:-$HOME/.obsidian-nlm-cli}"
info "Installing to: $INSTALL_DIR"

# ---- Clone or update ----
if [ -d "$INSTALL_DIR" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --ff-only || error "Git pull failed. Check for local changes."
else
    info "Cloning obsidian-nlm-cli..."
    git clone https://github.com/yanxuwang/obsidian-nlm-cli.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ---- Create virtual environment ----
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# ---- Install dependencies ----
info "Installing obsidian-nlm-cli and dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -e ".[dev]" --quiet 2>/dev/null || "$VENV_DIR/bin/pip" install -e . --quiet
"$VENV_DIR/bin/pip" install notebooklm-mcp-cli --quiet

# ---- Verify ----
info "Verifying installation..."
"$VENV_DIR/bin/obsidian-nlm" --help >/dev/null 2>&1 || error "Installation verification failed."
"$VENV_DIR/bin/nlm" --version >/dev/null 2>&1 || warn "nlm CLI not found in venv, checking system..."

echo ""
info "Installation complete!"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Authenticate with Google NotebookLM:"
echo "     $VENV_DIR/bin/nlm login"
echo ""
echo "  2. Bootstrap your vault from existing NotebookLM data:"
echo "     $VENV_DIR/bin/obsidian-nlm bootstrap --vault /path/to/your/vault"
echo ""
echo "  3. Or start syncing:"
echo "     $VENV_DIR/bin/obsidian-nlm scan --vault /path/to/your/vault"
echo ""
echo "  Add to PATH (optional):"
echo "     echo 'export PATH=\"$VENV_DIR/bin:\$PATH\"' >> ~/.bashrc"
echo "     source ~/.bashrc"
echo ""
