# Changelog

All notable changes to hyprtk-bar are documented in this file.
Dates are in YYYY-MM-DD format.

## [0.1.0] - 2026-09-07

### Changed

- **Waybar theme schema renamed to hyprtk-native** — `theme.source: "waybar"`
  is now `"imported"` and `theme.waybar_theme` is now `theme.theme_name`.
  Old configs auto-migrate (source waybar→imported, `waybar_theme` pops into
  `theme_name`); the `waybar_theme.py` module is now `theme_import.py`.
  All consumers (menu, arc-menu, theme-gui, rofi sync) follow the new schema.
- **Settings dialogue applies the theme's transparency** — the window is now a
  transparent toplevel (`set_app_paintable` + rgba visual, same as the monitor
  popups) and no longer forces an opaque background, so the imported theme /
  pywal opacity shows through to the desktop.
- **Settings header background is transparent** — removed the
  `alpha(currentColor, 0.06)` band behind the "Bar Settings" title (was a grey
  block on light themes).

## [0.1.0] - 2026-09-07

### Added

- **Animated border mirroring Hyprland** — the pill border color loops through
  hues at the same pace as Hyprland's `borderangle` animation. Which speed is
  used is chosen from the bar settings Animations tab: `low`/`high` read the
  matching `animations-<mode>.lua` file from the Hyprland config dir
  (borderangle speed 8 / 30), `custom` uses its own speed independent of
  Hyprland. The active Hyprland config dir is watched, so toggling the
  animations file re-paces the border live.
- **Animations settings tab** — enable/disable the animated border, choose
  Low / High / Custom mode, and set a custom Hyprland-style speed (only
  enabled for Custom). Applies live via the new `set_border_animation` action.
- **Border animation speed fix** — the period now exactly matches Hyprland's
  documented semantics: `speed` is the animation duration in ds (1 ds =
  100 ms), so a full borderangle rotation takes `speed * 100` ms (e.g. speed 30
  → 3000 ms). Previously the bar cycled ~3x too fast.

### Changed

- **GPU page supports all three vendors** — the system monitor's GPU page now
  auto-picks the primary GPU (discrete NVIDIA > discrete AMD > discrete Intel
  Arc > integrated AMD > integrated Intel) and reads from the right vendor
  source:
  - AMD: amdgpu sysfs (`gpu_busy_percent`, `mem_info_vram_*`, `pp_dpm_*`,
    card-scoped hwmon temps/power/fan).
  - NVIDIA: one `nvidia-smi --query-gpu=...` per poll — utilization, VRAM,
    temperature, power, fan%, core/mem clocks; graceful fallback when the
    driver or binary is missing.
  - Intel: pure sysfs (no extra tools/root) — busy% from the GT idle/RC6
    residency delta, clocks from i915 `rps_*` / xe `freq0/*` nodes, hwmon
    temps/power; VRAM shown as "shared (system RAM)".
- Static GPU identity is now pinned to the selected card: `lspci` matches that
  GPU's vendor/device IDs, so multi-GPU systems report the right model.

## [0.1.0] - 2026-09-06

### Added

- **Mission Center-style system monitor dialog** (click the sysmon glyph):
  a fixed 940x640 layer-shell panel with a sidebar of resource pages —
  CPU / Memory / Disks / Network / GPU / Apps — and live cairo graphs.
  - CPU: per-thread multi-series graph + 2-column per-core list, load,
    processes/threads, uptime, current/max frequency, temperature.
  - Memory: RAM + swap graphs, used/available/buffers/cached, and a DIMM slot
    graphic (populated + size) from `dmidecode` via passwordless `sudo -n`
    (cached 24h).
  - Disks: clickable per-drive cards (NVMe/HDD/SSD/USB/reader glyphs); the
    usage/read/write/Total-I/O graphs track the selected drive (default = the
    system drive), per-device rates from `/proc/diskstats`.
  - Network: download/upload graphs + every interface with type glyph, IP and
    live down/up rates.
  - GPU: usage/VRAM graphs, temps/power/fan/clocks (AMD at this point).
  - Apps: top processes by CPU%.
- **Passwordless sudo for the bar** — `setup-sudoers.sh` installs
  `/etc/sudoers.d/hyprtk-bar` (visudo-validated) so the DIMM readout never
  prompts; wired into `1-install.sh` in the merged installer.
- **GPU identity + live clocks** — model/manufacturer/CUs/max-clock via
  `rocminfo` (lspci fallback), cached to `~/.cache/hyprtk-bar/gpu.json`.
- **Package-update indicator module** (`updates`) — glyph + count from the
  installer's `updates.sh`, 60s poll, green/yellow/red thresholds, click opens
  the installer in a floating terminal.
- **Tray DBusMenu positioning** — tray menus anchor to the tray button
  (bar-edge aware) instead of center-screen; applet pixmaps are scaled to the
  icon size (fixes oversized Whatsie icon + a right-click segfault).

### Changed

- Notification center keeps history when toasts close/dismiss (badge clears,
  entries stay for the center); per-row dismiss and Clear all.
- Toasts float from the bar edge (below a top bar / above a bottom bar),
  centered horizontally; the notification daemon reclaims
  `org.freedesktop.Notifications` from competing daemons (`dunst` dropped from
  the kill list).
- Workspaces cluster is truly centered on the bar (homogeneous pill sections).

## [0.1.0] - 2026-09-04

### Added

- **Module icons as Nerd Font glyphs** — shared `Glyph` widget rendered with
  `Symbols Nerd Font` at pixel-accurate size (absolute Pango size), colorized
  with the pywal accent; quicklink glyphs get a configurable color.
- **Quicklinks module** — launcher buttons (apps menu, terminal, file manager,
  web, wallpaper, cliphist, screenshot) with per-button left/right/middle
  commands; empty command resolves the default browser via `xdg-settings`.
- **Keyboard-state module** (`kbstate`) — Caps/Num lock icons polling sysfs LED
  brightness, accent when on, dimmed when off.
- **Themed popup tooltips** on all bar modules (glass `.popup-box`).
- **Quick settings Mic slider** under Volume (`wpctl @DEFAULT_AUDIO_SOURCE@`).
- **Tasklist** — running/active dot on the icon corner (distinct colors),
  right-click a running app to pin/unpin (asks generic symbolic vs actual
  icon), pinned-class matching to running classes, phantom-pinned fix.
- **gap_in / gap_out** replace `margin` — layer height + exclusive zone =
  height + gap_in + gap_out; zero is a valid gap; settings control.
- **Active-window module** — true fixed width so titles never shift neighbors.
- **Clock date hover popup** + calendar; notification badge overlay (numbered
  dot, no bar resize); notification center no longer auto-hides.
- **Multi-monitor bars** — `monitors: primary | all | [names]`, one bar per
  monitor sharing a single HyprIPC, per-monitor active workspace.
- **DBusMenu tray menus** — native `com.canonical.dbusmenu` rendering for SNI
  items (verified against blueman / nm-applet).
- **Built-in notification center** — `org.freedesktop.Notifications` daemon
  (toasts + bell with unread badge + center with actions and Clear all).
- **Imported theme mapping** — waybar themes import border/spacing/padding/
  radius/colors/background alpha/fonts/chip styling, track live pywal colors,
  and apply to popups + right-click menu.
- **Settings window** — frameless floating draggable window (Hyprland rule
  floats+centers it): tabbed Bar/Fonts/Themes/Modules; width as a percentage,
  height, align, position, opacity, gaps, font picker (FontButton) + size +
  icon sizes, theme source + import, per-module show/position/order.
- **Start button** home icon + left spacing; single-instance flock; reload
  config restarts the bar.

### Changed

- Removed the show-desktop strip (not working as designed).
- `hyprtk-*` themes match the pywal theme's font; module icons scale with the
  font; bar border is 2px in the pywal accent.
- Rofi variant syncs to the bar theme on every re-theme.

## [0.1.0] - 2026-09-03

Initial release. A Windows 11-style taskbar for Hyprland (GTK3 +
gtk-layer-shell).

### Added

- Fully modular bar: modules arranged across left/center/right sections,
  show/hide/reorder from the settings window.
- Task list (pinned + running grouped by class, click to focus/minimize,
  middle-click to close, hover window-title preview popup), workspace chips,
  clock + calendar, sysmon (CPU/RAM/disk), quick settings flyout, SNI system
  tray, show-desktop strip.
- Live pywal16 theming (re-themes instantly on wallpaper change); theming
  sources: pywal / imported waybar theme / manual config.
- Layer-shell surface with exclusive zone, input shape (only the pill is
  clickable), per-monitor bars.
- `install.sh` (install / uninstall) to `~/.local/share/hyprtk-bar/` and
  `~/.local/bin/hyprtk-bar`; `--print-config`; single-instance lock.