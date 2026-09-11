# Portability

hyprtk-bar targets Hyprland sessions on any Linux distribution. It is **not**
cross-compositor — the bar drives Hyprland through `hyprctl` and the Hyprland
event socket, so it will not run under GNOME/KDE/X11/sway.

This document scopes what it takes to install the bar on a non-Arch distro, and
what still assumes Arch or the full hyprtk dotfiles tree.

## Dependency model

The bar's dependencies split into three layers:

1. **GObject-Introspection typelibs** (system packages, required to run). The
   bar loads GTK through PyGObject's GI, not direct C linking, so the *typelib*
   packages are what matter, not `-dev` headers.
2. **Python packages** — `pygobject` (PyGObject), `pycairo`, `dbus-next`
   (pure-Python). `install.sh` installs all three into a virtualenv. PyGObject
   and pycairo must still find the system typelibs / `libcairo` at runtime.
3. **Subprocess tools** — called on demand; each feature degrades gracefully
   when its tool is missing.

### GI typelibs used

| Typelib            | Used by                        |
|--------------------|--------------------------------|
| `Gtk-3.0`          | everything                     |
| `Gdk-3.0`          | windows / pixbuf               |
| `GtkLayerShell-0.1`| layer-shell anchoring          |
| `GLib-2.0`         | proc / GObject                 |
| `Pango-1.0`        | font + glyph sizing            |
| `GdkPixbuf-2.0`    | themer image handling          |
| `cairo`            | graphs + swaylock preview      |

### Subprocess tools

| Tool             | Feature                          |
|------------------|----------------------------------|
| `hyprctl`        | required (compositor IPC)        |
| `nmcli`          | quick settings network + tray    |
| `bluetoothctl`   | quick settings bluetooth + tray  |
| `wpctl`          | volume / mic (wireplumber)       |
| `brightnessctl`  | brightness (no backlight → hidden)|
| `dmidecode`      | memory DIMM readout (sudo)       |
| `lsblk`/`lspci`  | disks / GPU identity             |
| `rocminfo`       | AMD GPU clocks                  |
| `checkupdates`   | updates module (Arch-only)       |
| `pkexec`         | SDDM/GRUB update, system kill    || `xdg-settings`   | default-browser resolution       |
| `gtk-update-icon-cache` | icon cache refresh         |
| `update-desktop-database` | desktop entry install     |

## Distro support matrix

| Family           | Package manager | Status |
|------------------|-----------------|--------|
| Arch / Manjaro   | pacman          | Supported (baseline) |
| Debian / Ubuntu  | apt             | Supported (needs `python3-venv`) |
| Fedora / RHEL    | dnf             | Supported |
| openSUSE         | zypper          | Supported |
| Void Linux       | xbps            | Supported (musl needs build deps) |
| Alpine           | apk             | Supported (musl needs build deps) |
| Gentoo           | emerge          | Manual (packages listed) |
| NixOS            | nix             | Manual (prefer a flake/derivation) |

## Package mapping

`install.sh` installs these automatically per detected package manager. Manual
reference for the rest:

| Dep                | pacman | Debian/Ubuntu | Fedora | openSUSE | Void | Alpine | Gentoo |
|--------------------|--------|---------------|--------|----------|------|--------|--------|
| GTK3 typelib       | `gtk3` | `gir1.2-gtk-3.0` | `gtk3` | `typelib-1_0-Gtk-3_0` | `gtk+3` | `gtk+3.0` | `x11-libs/gtk+:3` |
| layer-shell        | `gtk-layer-shell` | `gir1.2-gtklayershell-0.1` | `gtk-layer-shell` | `gtk-layer-shell` | `gtk-layer-shell` | `gtk-layer-shell` | `gui-libs/gtk-layer-shell` |
| PyGObject          | `python-gobject` | `python3-gi` + `python3-gi-cairo` | `python3-gobject` | `python3-gobject` + `python3-gobject-Gdk` | `python3-gobject` | `py3-gobject3` | `dev-python/pygobject` |
| GdkPixbuf          | `gdk-pixbuf2` | `gir1.2-gdkpixbuf-2.0` | `gdk-pixbuf2` | `typelib-1_0-GdkPixbuf-2_0` | `gdk-pixbuf` | `gdk-pixbuf` | `x11-libs/gdk-pixbuf` |
| Pango              | `pango` | `gir1.2-pango-1.0` | `pango` | `typelib-1_0-Pango-1_0` | `pango` | `pango` | `x11-libs/pango` |
| cairo              | `cairo` | `gir1.2-cairo-1.0` | `cairo` | `cairo` | `cairo` | `cairo` | `x11-libs/cairo` |
| venv tooling       | built-in | `python3-venv` + `python3-pip` | `python3-pip` | built-in | built-in | `py3-pip` + `py3-virtualenv` | built-in |

## Gotchas

### venv / ensurepip
- Debian & Ubuntu split `ensurepip` out of the base interpreter, so
  `python3 -m venv` fails without `python3-venv`. Most other distros ship venv
  in the base `python3`. Alpine additionally needs `py3-virtualenv`.
- The installer installs `python3-venv`/`python3-pip` on apt systems automatically.

### PyGObject wheels vs. musl
- PyGObject and pycairo publish manylinux wheels for glibc x86_64/aarch64, so
  `pip install` works without a compiler on Arch/Fedora/openSUSE/Debian/Ubuntu.
- There are **no wheels for musl** (Alpine, Void-musl) or uncommon arches, so
  pip falls back to building from source and needs `gcc`, `pkg-config`,
  `gobject-introspection` and `cairo` development headers. `install.sh`
  detects musl and installs those build deps first; it also retries with them
  if a pip build fails on any distro.

### `updates` module is distro-agnostic
- The module's default `updates.sh` and `installupdates.sh` are now **bundled**
  with the bar (`scripts/`), not the pacman-only dotfiles copies. Each script
  detects the package manager (pacman, apt, dnf, zypper, xbps, apk, emerge,
  nix) and runs the matching query/upgrade, so the indicator works standalone
  on any distro.
- Config stays overridable (`updates.script` + `updates.install_command`) for
  anyone who wants a custom updater. `update.sh`/`installupdates.sh` resolve
  bundled-first, dotfiles-copy as fallback.

### `~/hyprtk/...` assumptions
Several paths assume the full hyprtk dotfiles are installed at `~/hyprtk`, not
a standalone bar:
- `themer.py` — `wallpaper-colors.sh`, `change-icons.sh`, `sync-rofi-theme.sh`,
  `sddm/update.sh`, `assets/Wallpapers`.
- `config.py` quicklinks defaults (`updatewal-awww.sh`, `cliphist`, `ssdetect`).
- `menu/hypr_animations.py` — `~/hyprtk/hypr`.
- `center.start_command` — `hyprtk-bar-menu-toggle.sh`.

These must become configurable (or skip gracefully when the tree is absent)
before the bar is a fully standalone install.

### gtk-layer-shell age
Every distro family packages `gtk-layer-shell`, but older LTS releases ship
ancient versions (Debian oldstable 0.5.2, Ubuntu ≤ 22.04 0.7.0). Use a
reasonably current release (≥ 0.9) to avoid missing layer-shell API.

## Remaining work

1. Generalise the `~/hyprtk/...` paths into config, with graceful skips.
2. NixOS: add a flake / derivation rather than runtime `nix-env` installs.
3. `yum` (RHEL/CentOS 7) detection is currently folded into `dnf` — verify the
   older `yum` install flags if those systems matter.
