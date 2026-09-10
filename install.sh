#!/bin/bash
# hyprtk-bar installer for Hyprtk
# Creates a venv, installs the app, and drops a launcher on PATH.
# Usage: ./install.sh             — install (system deps + venv)
#        ./install.sh --no-deps   — install without touching system packages
#        ./install.sh --uninstall — remove everything
#        ./install.sh --help      — show this message

set -euo pipefail

APP_NAME="hyprtk-bar"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.config/$APP_NAME"
CONFIG_FILE="$CONFIG_DIR/config.json"

usage() {
    echo "Usage: $0 [--no-deps|--no-extras|--uninstall|--help]"
    echo "  (no args)     Install the bar with system deps + feature dependencies."
    echo "  --no-deps     Skip system package installation (assume typelibs present)."
    echo "  --no-extras   Skip the optional feature binaries (quick settings, monitor,"
    echo "                clipboard, theming, etc. — those features then degrade)."
    echo "  --uninstall   Remove the bar, its launcher and desktop entry."
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ "${1:-}" == "--uninstall" || "${1:-}" == "-u" ]]; then
    echo ":: Uninstalling $APP_NAME..."
    rm -rf "$INSTALL_DIR"
    rm -f "$BIN_DIR/$APP_NAME"
    rm -f "$BIN_DIR/hyprtk-bar-menu-toggle.sh"
    rm -f "$BIN_DIR/hyprtk-bar-arc-toggle.sh"
    rm -f "$BIN_DIR/hyprtk-bar-clipboard-toggle.sh"
    rm -f "$APPS_DIR/$APP_NAME.desktop"
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
    echo ":: Done. $APP_NAME has been uninstalled."
    exit 0
fi

SKIP_DEPS=0
if [[ "${1:-}" == "--no-deps" ]]; then
    SKIP_DEPS=1
fi

SKIP_EXTRAS=0
if [[ "${1:-}" == "--no-extras" ]]; then
    SKIP_EXTRAS=1
fi

# ── Package-manager detection ──────────────────────────────────────────────
# Returns the identifier of the system package manager, or "none".
detect_pkg_manager() {
    if command -v pacman >/dev/null 2>&1; then echo pacman; return; fi
    if command -v apt-get >/dev/null 2>&1; then echo apt; return; fi
    if command -v dnf >/dev/null 2>&1; then echo dnf; return; fi
    if command -v zypper >/dev/null 2>&1; then echo zypper; return; fi
    if command -v xbps-install >/dev/null 2>&1; then echo xbps; return; fi
    if command -v apk >/dev/null 2>&1; then echo apk; return; fi
    if command -v emerge >/dev/null 2>&1; then echo emerge; return; fi
    if command -v nix >/dev/null 2>&1; then echo nix; return; fi
    echo none
}

# True when the system libc is musl (Alpine, Void-musl, ...). musl has no
# manylinux wheels for PyGObject/pycairo, so the venv pip step must build.
is_musl() {
    ldd --version 2>&1 | grep -qi musl
}

# System runtime deps per package manager (GI typelibs + python tooling).
# PyGObject/pycairo/dbus-next themselves are installed into the venv.
declare -A DEPS
DEPS[pacman]="gtk3 gtk-layer-shell gdk-pixbuf2 pango cairo python python-pip"
DEPS[apt]="gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 gir1.2-gdkpixbuf-2.0 gir1.2-pango-1.0 gir1.2-cairo-1.0 python3-gi python3-gi-cairo python3-venv python3-pip"
DEPS[dnf]="gtk3 gtk-layer-shell gdk-pixbuf2 pango cairo python3-gobject python3-pip"
DEPS[zypper]="typelib-1_0-Gtk-3_0 gtk-layer-shell typelib-1_0-GdkPixbuf-2_0 typelib-1_0-Pango-1_0 python3-gobject python3-gobject-Gdk python3-gobject-cairo python3-pip"
DEPS[xbps]="gtk+3 gtk-layer-shell gdk-pixbuf pango cairo python3-gobject python3-pip"
DEPS[apk]="gtk+3.0 gtk-layer-shell gdk-pixbuf pango cairo py3-gobject3 py3-pip py3-virtualenv"
DEPS[emerge]="x11-libs/gtk+:3 gui-libs/gtk-layer-shell x11-libs/gdk-pixbuf x11-libs/pango x11-libs/cairo dev-python/pygobject"
DEPS[nix]="gtk3 gtk-layer-shell gdk-pixbuf pango cairo gobject-introspection python3"

# Build deps for building PyGObject/pycairo from source (musl / no wheel).
declare -A BUILD_DEPS
BUILD_DEPS[pacman]="base-devel gobject-introspection cairo"
BUILD_DEPS[apt]="gcc pkg-config libgirepository1.0-dev libcairo2-dev python3-dev"
BUILD_DEPS[dnf]="gcc pkg-config gobject-introspection-devel cairo-devel python3-devel"
BUILD_DEPS[zypper]="gcc pkg-config gobject-introspection-devel cairo-devel python3-devel"
BUILD_DEPS[xbps]="gcc pkg-config gobject-introspection cairo-devel python3-devel"
BUILD_DEPS[apk]="gcc musl-dev pkgconfig gobject-introspection-dev cairo-dev python3-dev"
BUILD_DEPS[emerge]="dev-python/pycairo"
BUILD_DEPS[nix]=""

# Optional feature dependencies — the external binaries the bar shells out to
# for quick settings, system monitor, clipboard, theming, etc. Installed by
# default (skip with --no-extras); each feature degrades gracefully when its
# tool is missing, so a partial install is still a working bar.
declare -A EXTRAS
EXTRAS[pacman]="networkmanager bluez bluez-utils pipewire pipewire-pulse wireplumber brightnessctl hyprsunset dmidecode pciutils cliphist wl-clipboard rofi libnotify wob papirus-icon-theme polkit awww matugen"
EXTRAS[apt]="network-manager bluez pipewire pipewire-pulse wireplumber brightnessctl dmidecode pciutils wl-clipboard rofi libnotify papirus-icon-theme policykit-1"
EXTRAS[dnf]="NetworkManager bluez pipewire pipewire-pulse wireplumber brightnessctl dmidecode pciutils wl-clipboard rofi libnotify papirus-icon-theme polkit"
EXTRAS[zypper]="NetworkManager bluez pipewire pipewire-pulse wireplumber brightnessctl dmidecode pciutils wl-clipboard rofi libnotify papirus-icon-theme polkit"
EXTRAS[xbps]="NetworkManager bluez pipewire wireplumber brightnessctl dmidecode pciutils wl-clipboard rofi libnotify papirus-icon-theme polkit"
EXTRAS[apk]="networkmanager bluez pipewire wireplumber brightnessctl dmidecode pciutils wl-clipboard rofi libnotify papirus-icon-theme polkit"
EXTRAS[emerge]="net-misc/networkmanager net-wireless/bluez media-video/pipewire media-video/wireplumber x11-misc/rofi gui-apps/wl-clipboard x11-libs/libnotify"
EXTRAS[nix]="networkmanager bluez pipewire wireplumber rofi wl-clipboard libnotify"

# AUR-only extras (Arch) — installed via yay/paru when an AUR helper is present.
EXTRAS_AUR="python-pywal16-git papirus-folders"

# True when the two typelibs the bar cannot run without are present.
typelib_present() {
    local name="$1" d
    for d in /usr/lib/girepository-1.0 /usr/lib64/girepository-1.0 \
             /usr/lib/x86_64-linux-gnu/girepository-1.0 \
             /usr/lib/aarch64-linux-gnu/girepository-1.0 \
             /usr/local/lib/girepository-1.0; do
        [ -f "$d/${name}.typelib" ] && return 0
    done
    return 1
}

deps_ok() {
    typelib_present "Gtk-3.0" && typelib_present "GtkLayerShell-0.1"
}

# Run a package-manager command with root (directly if already root, else sudo).
run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo ":: ERROR: need root to install system packages; no sudo found." >&2
        echo ":: Run as root:  $*" >&2
        return 1
    fi
}

install_pkgs() {
    local pm="$1"; shift
    case "$pm" in
        pacman) run_root pacman -S --noconfirm --needed "$@" ;;
        apt)    run_root apt-get install -y "$@" ;;
        dnf)    run_root dnf install -y "$@" ;;
        zypper) run_root zypper --non-interactive install "$@" ;;
        xbps)   run_root xbps-install -Sy "$@" ;;
        apk)    run_root apk add --no-cache "$@" ;;
        emerge)
            echo ":: Gentoo detected — install manually, then rerun with --no-deps:" >&2
            echo "     emerge -av $*" >&2
            return 1 ;;
        nix)
            echo ":: Nix detected — prefer a flake/derivation with these inputs:" >&2
            echo "     $*" >&2
            echo ":: Or install via nix-env, then rerun with --no-deps." >&2
            return 1 ;;
        *) return 1 ;;
    esac
}

install_extras() {
    local pm="$1"
    if [ -n "${EXTRAS[$pm]:-}" ]; then
        echo ":: Installing optional feature dependencies via $pm ..."
        install_pkgs "$pm" ${EXTRAS[$pm]:-} || \
            echo ":: WARN: some optional packages failed to install — those features degrade gracefully."
    fi
    if [ "$pm" = "pacman" ] && [ -n "${EXTRAS_AUR:-}" ]; then
        local aur=""
        command -v yay >/dev/null 2>&1 && aur=yay
        [ -z "$aur" ] && command -v paru >/dev/null 2>&1 && aur=paru
        if [ -n "$aur" ]; then
            echo ":: Installing AUR extras via $aur ..."
            "$aur" -S --noconfirm --needed ${EXTRAS_AUR} || \
                echo ":: WARN: some AUR packages failed to install."
        else
            echo ":: NOTE: no AUR helper (yay/paru) found — install manually: ${EXTRAS_AUR}"
        fi
    fi
}

PM="$(detect_pkg_manager)"

# ── System dependencies ─────────────────────────────────────────────────────
if [ "$SKIP_DEPS" -eq 0 ]; then
    if deps_ok; then
        echo ":: System dependencies present."
    elif [ "$PM" = "none" ]; then
        echo ":: WARN: no supported package manager detected." >&2
        echo ":: Install GTK3 + gtk-layer-shell typelibs manually, then rerun." >&2
    else
        echo ":: Installing system dependencies via $PM ..."
        install_pkgs "$PM" ${DEPS[$PM]:-}
        if is_musl; then
            echo ":: musl libc detected — installing build deps for the venv step ..."
            install_pkgs "$PM" ${BUILD_DEPS[$PM]:-}
        fi
    fi
fi

# ── Optional feature dependencies ─────────────────────────────────────────
if [ "$SKIP_EXTRAS" -eq 0 ] && [ "$SKIP_DEPS" -eq 0 ] && [ "$PM" != "none" ]; then
    install_extras "$PM"
elif [ "$SKIP_EXTRAS" -eq 0 ] && [ "$SKIP_DEPS" -eq 1 ]; then
    echo ":: NOTE: --no-deps implies --no-extras (system packages not managed here)."
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
cp -r "$SCRIPT_DIR/scripts" "$INSTALL_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/"

python3 -m venv "$INSTALL_DIR/venv"

# Install the Python deps (pygobject, pycairo, dbus-next) into the venv.
# If the build fails (no wheel for musl / uncommon arch), install the build
# deps for the detected package manager and retry once.
if ! "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR" --quiet 2>/dev/null; then
    echo ":: pip install failed (no wheel?); retrying with build deps ..."
    if [ "$SKIP_DEPS" -eq 0 ] && [ "$PM" != "none" ] && [ -n "${BUILD_DEPS[$PM]:-}" ]; then
        install_pkgs "$PM" ${BUILD_DEPS[$PM]:-}
    fi
    "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR" --quiet
fi

# Main launcher
cat > "$BIN_DIR/$APP_NAME" << LAUNCHER
#!/bin/bash
exec "$INSTALL_DIR/venv/bin/python3" -m hyprtk_bar "\$@"
LAUNCHER
chmod +x "$BIN_DIR/$APP_NAME"

# Toggle scripts — Hyprland keybindings signal the bar through these
# (SIGUSR1 menu / SIGUSR2 arc menu / SIGHUP clipboard). Installed on PATH so
# a standalone install can bind them directly.
if [ -d "$SCRIPT_DIR/scripts" ]; then
    for script in "$SCRIPT_DIR"/scripts/hyprtk-bar-*-toggle.sh; do
        [ -f "$script" ] || continue
        cp "$script" "$BIN_DIR/"
        chmod +x "$BIN_DIR/$(basename "$script")"
    done
fi

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
