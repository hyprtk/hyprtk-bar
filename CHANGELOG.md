# Changelog

All notable changes to hyprtk-bar are documented in this file.
Dates are in YYYY-MM-DD format.

## [Unreleased]

### Added

- **Bundled Nerd Font + AUR helper bootstrap in the installer.** The bar's
  icons are Nerd Font glyphs, so `install.sh` now installs the bundled
  `assets/fonts/SymbolsNerdFont-Regular.ttf` into `~/.local/share/fonts` and
  refreshes the font cache — glyphs render without a system font package. On
  Arch, when no AUR helper is present, it builds `yay` (installing `base-devel`
  + `git`) before installing the AUR extras.
- **`--dry-run` flag** — checks the required typelibs, Python/venv, `PATH` and
  Wayland/Hyprland environment and reports what is missing without changing
  anything.
- **Post-install self-test** — the installer now imports GTK + gtk-layer-shell
  through the venv and fails loudly with the cause if the runtime is unusable,
  instead of installing "successfully" and leaving a bar that cannot launch.
- **Cross-distro installer** — `install.sh` now detects the system package
  manager (pacman, apt, dnf, zypper, xbps, apk, emerge, nix) and installs the
  GTK3 / gtk-layer-shell GObject-Introspection typelibs and Python tooling the
  bar needs, instead of requiring a manual step. It probes for the `Gtk-3.0`
  and `GtkLayerShell-0.1` typelibs first so it skips sudo when they are already
  present.
- **`--no-deps` and `--help` flags** — `--no-deps` installs without touching
  system packages (for Gentoo/Nix or when deps are managed externally);
  `--help` prints usage.
- **musl / source-build handling** — when the libc is musl (Alpine, Void-musl)
  there are no PyGObject/pycairo manylinux wheels, so the installer pre-installs
  the compiler and header build deps; it also retries a failed venv pip build
  with those deps on any distro.
- **Portability documentation** — new `PORTABILITY.md` scopes the dependency
  model (GI typelibs vs. venv Python vs. subprocess tools), the distro support
  matrix, the per-distro package-name mapping, and the remaining Arch /
  `~/hyprtk` assumptions.

### Changed

- **Start menu power/settings icons are now Nerd Font glyphs.** The power
  buttons used bundled PNGs and the settings button a system symbolic icon
  (which rendered as a blank placeholder where the icon theme lacked it). Both
  now use glyphs from the bundled Nerd Font, matching the bar's icon style.

### Fixed

- **Selected/active app text was black and unreadable.** The menu chose the
  selected-text colour by contrasting against the raw accent, but the selected
  background is a *translucent* accent over the panel — so a light accent
  (e.g. the default blue) produced black text on a dark row. The colour is now
  contrasted against the accent blended over the background, so it stays
  readable for light and dark palettes.

- **Menu buttons/entries showed the GTK theme's light background.** The GTK
  theme paints these with its own `background-image` gradient and shadow, which
  sit on top of any `background-color` we set — so pinned tiles, plasma tabs,
  the "All apps"/"More" pills, the power/settings buttons and the search box
  looked light and off-theme. A menu-wide reset (`background-image`/
  `box-shadow`/`text-shadow: none` inside `.menu`) makes only the palette
  colours show.

- **Start menu's settings (cog) button rendered unthemed.** The bar's global
  CSS (loaded at a higher GTK provider priority) defined `.settings-btn` for its
  own settings dialogue, which overrode the menu's `.settings-btn` and left the
  cog button transparent with no border. The menu's classes are now
  `menu-settings-btn` / `menu-settings-icon`, so the two no longer collide.

- **Bar width/alignment did not work on smaller displays.** The width was
  applied to the pill, whose minimum width (~the modules' content, ~1388px)
  clamps it — so a percentage/px below that minimum was ignored, and on a small
  monitor the surface grew wider than the screen and ran off the right edge.
  Width is now applied to the layer **surface** via left/right margins
  (percentages measured against the monitor, not the shrinking surface — that
  caused a hover flicker), and the pill is wrapped in a clip container so its
  content minimum no longer forces the surface wider than the monitor. 20%/50%/
  px widths and left/center/right alignment all work; content clips if the
  requested width is smaller than the modules need.

- **Bar could not launch after a clean install on some systems.** Importing
  `Gtk` needs the `xlib-2.0` GObject-Introspection typelib (GDK pulls GdkX11
  into the namespace). On Arch that ships in `gobject-introspection-runtime`,
  which the installer did not install — and the probe only checked
  `Gtk-3.0`/`GtkLayerShell-0.1`, so it skipped the dependency step entirely.
  `gobject-introspection-runtime` is now in the dependency list and
  `xlib-2.0` is part of the probe.

- **`hyprtk-bar: command not found` after install.** `~/.local/bin` is not on
  PATH on a fresh Arch, and Hyprland's `exec-once` does not source shell rc
  files, so the launcher was unreachable. When `~/.local/bin` is off PATH the
  installer now symlinks `hyprtk-bar` and the toggle scripts into
  `/usr/local/bin` (removed on `--uninstall`).

- **Spurious "refusing non-allowlisted script" warning on standalone installs.**
  The updates module warned and disabled polling whenever its configured script
  did not exist — the normal case without the dotfiles. It now stays quiet when
  the script is absent and only warns when a script is present but outside the
  allowlisted locations.

- **Startup crash on a system without a wallpaper palette (`KeyError: 'red'`).**
  `resolve_palette` only defined `red` when pywal colours were available, but
  the CSS always renders the cliphist delete-hover rule, so a fresh install (no
  `~/.cache/wal/colors.json`) crashed on launch. `red` now has a default.

## [0.1.0] - 2026-09-09

### Added

- **About hyprtk-bar** — right-click menu entry that opens a branded, themed
  About window (frameless, popup-box glass + animated border) showing the
  Hyprtk brand, version and the project repo.

### Changed

- **Hyprtk watermark** — every module now carries a branded header
  (`# HYPRTK · hyprtk-bar · <module>` / `Part of the Hyprtk desktop suite ·
  github.com/hyprtk`) after its docstring, unifying the project under the
  Hyprtk brand.

### Fixed

- **Theme colours on slider / option controls** — the GTK theme paints
  `Gtk.Switch`, `Gtk.Scale`, check/radio indicators and the spinbutton up/down
  arrows with its own `background-image` / `-gtk-icon-source` assets, which sat
  on top of the palette colours, so those controls kept the GTK theme's accent
  (e.g. Kripton's teal) instead of the pywal / imported theme. Switches and
  scales now reset the theme image and take the palette accent; check/radio use
  recoloured symbolic indicators; spinbutton entries and arrows follow the
  palette fg/accent. Covers Quick Settings, Bar Settings and the Theme Manager.

## [0.1.0] - 2026-09-09

### Added

- **System monitor Apps page** — four views (User apps / System apps / User
  processes / System processes); "apps" are processes owning a compositor
  window, "processes" are everything owned by that user. Each row shows
  process, CPU and memory; **Kill**, **Force kill** and **Launch** act on the
  selected process (Launch re-runs its command line). Killing a system-owned
  process goes through the scoped `hyprtk-system-kill` sudo helper (installed
  to /usr/local/bin by setup-sudoers.sh alongside dmidecode — never NOPASSWD
  ALL); user-owned processes are killed directly.

### Fixed

- **Memory leaks** — SNI items now detach their D-Bus signal subscriptions on
  unregister (nm-applet resets / name flaps no longer pin zombie items in the
  bus handler registry); DBusMenu icons are dimension-capped and each menu is
  destroyed on dismissal; removed widget rows are now destroyed (not just
  removed) across the menu (app list, favorites, recents, pinned grid, plasma
  browser/trash), themer (theme list, thumbnail/pywal/variant/icon grids), and
  the notification center. Module poll timers (clock, kbstate, updates, sysmon)
  are stopped on shutdown and wired into the bar's teardown.
- **Notification name-owner fight** — the 150 ms retry+pkill loop is bounded
  (5 tries, linear backoff) so an unknown/stubborn daemon can't churn forever.

### Changed

- **Security hardening** — SNI `IconPixmap` dimensions are capped (512px) so a
  remote client can't force huge allocations; SNI `IconThemePath` is validated
  (existing absolute dir under home/system icon locations) before being injected
  into GTK's global icon search path. Imported-theme names are validated against
  a whitelist (`_safe_theme_dir`) before touching the filesystem, and themer
  bar/swaylock config writes are atomic.
- **Responsiveness** — SDDM/GRUB update (pkexec) and the package-update check
  now run on worker threads (no more UI-thread stalls). The Themer and System
  Monitor dialogs build lazily on first open instead of at startup. Border
  animations tick at ~15fps with a color-change skip (arc border only animates
  while open).
- **Menu integration fixes** — `menu.enabled` is honoured at runtime (off hides
  the menu and toggle no-ops); the start button no-ops when the menu is
  disabled; settings Apply preserves `position: "auto"` (new Auto radio); menu
  saves route through the bar's config save (last-good backup); the menu's 2s
  wal-watcher timer is released on destroy.

### Added

- **Start menu merged into the bar** — the standalone hyprtk-menu app is gone;
  the bar now owns the start menu (search, favorites, recents, power bar, four
  layouts: whisker/win7/win11/plasma). New `menu` config block in the bar config
  (legacy `~/.config/hyprtk-menu/config.json` is auto-imported on first run), a
  **Menu** tab in the bar settings dialogue (enabled/layout/position/align/gaps/
  follow), toggling via the start button or `Super+Space` (SIGUSR1 from
  `installer/scripts/hyprtk-bar-menu-toggle.sh`), live re-theme from the bar's
  palette + pywal, and live layout/position reload when settings change.
  Vendored under `src/hyprtk_bar/menu/` with its assets in `assets/`.
- **Follow hyprtk-bar** toggle (`menu.follow_bar`, default on): anchors the menu
  to the bar's edge and aligns it to the bar pill (width + align + gaps) instead
  of the screen edge; off places it at the chosen screen corner. It also controls
  theming — off resolves the menu's own pywal palette rather than the bar's theme.

## [0.1.0] - 2026-09-08

### Added

- **Arc menu overlay merged into the bar** — the standalone hyprtk-arc-menu app
  is gone; the bar now owns the arc menu (a FAB in a screen corner that fans its
  items out on click). New `arcmenu` config block in the bar config (legacy
  `~/.config/hyprtk-arc-menu/config.json` is auto-imported on first run), a
  **Arc Menu** tab in the bar settings dialogue (position/shape/sizes/colours/
  toggles + item editor with installed-app search), toggling via `Super+Ctrl+M`
  (SIGUSR2 from `installer/scripts/hyprtk-bar-arc-toggle.sh`) or the FAB, and
  live theming from the bar's palette + pywal.

## [0.1.0] - 2026-09-08

### Fixed

- **Theme Manager → SDDM & GRUB background preview** — the wallpaper preview is
  now scaled down (contain fit) to fit within the dialogue instead of being
  shown at full image size and overflowing the panel. Aspect ratio is preserved
  and small images are not upscaled.

## [0.1.0] - 2026-09-08

### Changed

- **Theme Manager → Bar Themes applies themes without restarting** — selecting
  a source (pywal / imported / manual) or an imported theme now re-themes the
  bar live instead of closing and reopening it. The Theme Manager uses the same
  in-place re-theme path as the bar settings dialogue (`Bar.apply_theme`), which
  updates the shared config, saves it, and re-themes. "Restart Bar" still
  restarts explicitly.

## [0.1.0] - 2026-09-08

### Changed

- **Theme Manager quick-link tooltip** — the wallpaper glyph's hover tooltip now
  reads **Theme Manager** instead of "Wallpaper", since it opens the Theme
  Manager dialogue.

## [0.1.0] - 2026-09-08

### Changed

- **Theme Manager → Bar Themes page now matches the bar settings Themes tab** —
  it gained a theme **Source** selector (Pywal (dynamic) / Imported theme /
  Manual (config)), a check-list of the imported themes (enabled only when the
  source is "imported"), and an **Import theme…** button that copies a theme
  folder into the bar's themes dir and applies it. Selecting a source or an
  imported theme writes the bar config and restarts the bar, so both the bar
  settings dialogue and the Theme Manager expose the same options and behaviour.

## [0.1.0] - 2026-09-08

### Fixed

- **Pywal palette grid went blank** (Theme Manager → Pywal) — re-rendering the
  colour grid while the dialogue was open (Refresh, or after applying a scheme
  / wallpaper) left every swatch hidden, because GTK3 keeps children added
  after a container is shown invisible. The grid now calls `show_all()` after
  building, and the palette is refreshed each time the Pywal page is opened so
  it always shows the current pywal colours.

## [0.1.0] - 2026-09-08

### Added

- **Wallpaper preview cache build** (Theme Manager → Wallpaper) — a new
  **Build Cache** button regenerates a cover-cropped thumbnail for every image
  in the wallpaper directory, with a live `N/total` progress bar. The cache is
  built incrementally (one image per idle step, so a large directory never
  blocks the UI) and resumes after an interruption, so thumbnails appear on
  first scroll instead of only after a full blocking pass.
- **Directory-aware cache validity** — the cached index is only trusted when it
  belongs to the currently selected wallpaper directory, so switching folders
  no longer briefly shows another folder's thumbnails.

### Fixed

- **Not all wallpapers displayed when scrolling** — the thumbnail grid is now
  driven by the scrollbar adjustment (value-changed near the bottom) in
  addition to the unreliable `edge-reached` signal, and every newly-added
  thumbnail is shown (`show_all`). Previously GTK3 kept every batch after the
  first one hidden, so scrolling stopped partway through a large directory.
- **Cleaner directory switch** — choosing a new wallpaper directory now cancels
  any in-flight cache build and rebuilds for the new folder without double
  triggering.

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