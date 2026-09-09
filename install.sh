#!/bin/bash
# hyprtk-bar installer for Hyprtk
# Creates a venv, installs the app, and drops a launcher on PATH.
# Usage: ./install.sh            — install
#        ./install.sh --uninstall — remove everything

set -euo pipefail

APP_NAME="hyprtk-bar"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.config/$APP_NAME"
CONFIG_FILE="$CONFIG_DIR/config.json"

if [[ "${1:-}" == "--uninstall" || "${1:-}" == "-u" ]]; then
    echo ":: Uninstalling $APP_NAME..."
    rm -rf "$INSTALL_DIR"
    rm -f "$BIN_DIR/$APP_NAME"
    rm -f "$APPS_DIR/$APP_NAME.desktop"
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
    echo ":: Done. $APP_NAME has been uninstalled."
    exit 0
fi

echo ":: Installing $APP_NAME..."

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR" "$CONFIG_DIR"

# ── Preserve the user's live config across install/update ────────────────
# An update must never reset the user's customisations. Back the live config
# up first; if it is ever missing afterwards (interrupted update, cleanup),
# restore the last-good backup so the bar comes back with the saved settings.
if [ -f "$CONFIG_FILE" ]; then
    cp -f "$CONFIG_FILE" "$CONFIG_DIR/config.json.bak" 2>/dev/null || true
    echo ":: Backed up existing config to $CONFIG_DIR/config.json.bak"
fi

cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/assets" "$INSTALL_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR" --quiet 2>/dev/null || \
"$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR" --quiet

# Main launcher
cat > "$BIN_DIR/$APP_NAME" << LAUNCHER
#!/bin/bash
exec "$INSTALL_DIR/venv/bin/python3" -m hyprtk_bar "\$@"
LAUNCHER
chmod +x "$BIN_DIR/$APP_NAME"

cp "$SCRIPT_DIR/$APP_NAME.desktop" "$APPS_DIR/"
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# Restore the config if the live file is missing but a backup exists (the app
# itself also auto-restores on load; this is belt-and-braces for installs).
if [ ! -f "$CONFIG_FILE" ] && [ -f "$CONFIG_DIR/config.json.bak" ]; then
    cp -f "$CONFIG_DIR/config.json.bak" "$CONFIG_FILE" 2>/dev/null || true
    echo ":: Restored config from backup"
fi

echo ":: Installed to $BIN_DIR/$APP_NAME"
echo ":: Config: ~/.config/hyprtk-bar/config.json"
echo ":: Run './install.sh --uninstall' to remove"
