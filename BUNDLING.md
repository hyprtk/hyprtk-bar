# Bundling — merging the external scripts into hyprtk-bar

Goal: make hyprtk-bar a **self-contained** app so it does not depend on the
`~/hyprtk` dotfiles tree (or third-party installs) for its feature scripts. This
document is the working plan; it is intentionally a **first-pass inventory** —
see "Not yet audited" at the bottom.

Two axes are involved:

1. **Scripts** — the `.sh` files the bar shells out to.
2. **Dependencies** — the external binaries those scripts (or the bar) call, and
   the on-disk assets they read.

"Incorporating" therefore means two things: (a) vendor the scripts into the bar,
(b) install the binaries via `install.sh` and repoint the hardcoded paths.

---

## Current inventory

The bar reaches outside itself through three vectors:

- **`themer.py` constants** (`HYPRTK = ~/hyprtk`, plus rofi / swaylock / matuwall /
  papirus / wallpaper paths).
- **`config.py` defaults** (quicklinks commands, `start_command`, `updates.script`).
- **`app.py`** (`ROFI_SYNC_SH` = `~/.config/rofi/scripts/sync-rofi-theme.sh`).

### Directly-called scripts (12)

| # | Script (default path) | Trigger | Category |
|---|------------------------|---------|----------|
| 1 | `~/hyprtk/hypr/scripts/wallpaper-colors.sh` | themer → wallpaper apply | B |
| 2 | `~/hyprtk/configs/papirus-icons/scripts/change-icons.sh` | themer → icons | B (path is stale — see bugs) |
| 3 | `~/hyprtk/configs/rofi/scripts/sync-rofi-theme.sh` | themer → rofi | A |
| 4 | `~/.config/rofi/scripts/sync-rofi-theme.sh` | app.py → on re-theme | A (same file as #3 via symlink) |
| 5 | `~/hyprtk/configs/sddm/update.sh` | themer → SDDM & GRUB (pkexec) | C |
| 6 | `~/.local/share/icons/papirus-folders.sh` | themer → icons | D (third-party) |
| 7 | `~/hyprtk/installer/scripts/updates.sh` | updates module poll | C |
| 8 | `~/hyprtk/installer/scripts/installupdates.sh` | updates module click | C |
| 9 | `~/hyprtk/installer/scripts/appsmenu.sh` | quicklinks → apps | A |
| 10 | `~/hyprtk/installer/scripts/updatewal-awww.sh` | quicklinks → wallpaper (right-click) | B |
| 11 | `~/hyprtk/installer/scripts/cliphist.sh` | quicklinks → clipboard | A |
| 12 | `~/hyprtk/installer/scripts/ssdetect.sh` | quicklinks → screenshot | C |
| 13 | `~/hyprtk/installer/scripts/hyprtk-bar-menu-toggle.sh` | start button (fallback) | A |

(13 call sites; #3 and #4 are the same underlying script.)

### Transitive scripts (called by the 12)

| Script | Called by |
|--------|-----------|
| `change-icons.sh` | wallpaper-colors.sh, updatewal-awww.sh |
| `papirus-folders.sh` | change-icons.sh |
| `screenshot.sh` (286 lines) | ssdetect.sh |
| `sshot.sh` | ssdetect.sh |
| `library.sh` (105 lines) | installupdates.sh (sources it) |
| `update-TS-run.sh` | installupdates.sh |

### Path / asset dependencies (read, not scripts)

| Path | Used by |
|------|---------|
| `~/hyprtk/assets/Wallpapers` | themer wallpaper dirs |
| `~/.config/rofi/variants/*.rasi` (10 variants) | themer rofi page + sync-rofi-theme |
| `~/.config/rofi/config-apps-menu.rasi` | appsmenu.sh |
| `~/.config/rofi/config-cliphist.rasi`, `config-short.rasi` | cliphist.sh |
| `~/.config/swaylock/config` | themer swaylock page (read/write) |
| `~/.config/matuwall/config.json` | themer matuwall page (read/write) |
| `~/.local/share/icons/Papirus-Dark` | change-icons.sh + themer icon previews |
| `~/.cache/wal/*` | pywal cache (colors.sh/colors.json/…), written by `wal` |
| `~/.cache/theme-gui/*` | thumbnail cache (shared with archived theme-gui) |
| `~/.config/hyprtk-bar/themes/` | imported-theme dir |

### Binary dependencies

| Binary | Package (Arch) | Needed for |
|--------|----------------|------------|
| `awww` | `awww` (AUR) | wallpaper set |
| `wal` | `python-pywal` | pywal colors |
| `rofi` | `rofi` | apps menu, clipboard |
| `cliphist` | `cliphist` | clipboard history |
| `wl-copy`/`wl-paste` | `wl-clipboard` | clipboard |
| `wob` | `wob` | volume OSD |
| `notify-send` | `libnotify` | update / icon notifications |
| `checkupdates` | `pacman-contrib` | updates module |
| `trizen` | AUR | updates module |
| `yay` | AUR | installupdates |
| `timeshift` | `timeshift` | installupdates snapshot |
| `nvidia-smi` | `nvidia-utils` | ssdetect GPU branch |
| `papirus-folders` | `papirus-folders` | folder colour |
| `papirus-icon-theme` | `papirus-icon-theme` | Papirus-Dark theme |
| `hyprctl` | (with hyprland) | compositor IPC |
| `sudo`/`pkexec` | `sudo`/`polkit` | SDDM/GRUB, DIMM, system kill |

---

## Categorisation

- **A — bundleable now** (self-contained or only need a binary + a small config):
  `sync-rofi-theme.sh`, `appsmenu.sh`, `cliphist.sh`, `hyprtk-bar-menu-toggle.sh`.
- **B — bundleable with binaries** (thin wrappers over `awww`/`wal`/`wob`):
  `wallpaper-colors.sh`, `updatewal-awww.sh`, `change-icons.sh`.
- **C — stay in dotfiles / optional integration** (system-level, root, or Arch/AUR):
  `sddm/update.sh`, `updates.sh`, `installupdates.sh`, `ssdetect.sh`.
- **D — third-party, install as dep**: `papirus-folders.sh`.

---

## Known issues to fix during the merge

1. **`CHANGE_ICONS_SH` path is stale.** `themer.py` points at
   `~/hyprtk/configs/papirus-icons/scripts/change-icons.sh`, but the file lives at
   `~/hyprtk/assets/papirus-icons/scripts/change-icons.sh`. The icons page
   currently toasts "change-icons.sh not found".
2. **`sync-rofi-theme.sh` is referenced at two paths** (`~/.config/rofi/scripts/…`
   and `~/hyprtk/configs/rofi/scripts/…`). Collapse to one bundled copy.
3. **`start_command` still points at the toggle script** — the bar already has
   in-process menu toggling; the script is only a Hyprland-keybinding fallback.
4. Several defaults hardcode `~/hyprtk/installer/scripts/…` (config.py quicklinks +
   updates). These must become bar-install-dir-relative.

---

## Plan

### Phase 1 — vendor the A + B scripts into the bar
- Add `scripts/` to the repo; `install.sh` copies it to
  `~/.local/share/hyprtk-bar/scripts/`.
- Vendor: `wallpaper-colors.sh`, `updatewal-awww.sh`, `change-icons.sh`,
  `sync-rofi-theme.sh`, `appsmenu.sh`, `cliphist.sh`, `hyprtk-bar-menu-toggle.sh`,
  `hyprtk-bar-arc-toggle.sh`.
- Bundle the 3 rofi configs they need (apps-menu / cliphist / short) under
  `assets/rofi/`.
- Repoint `themer.py` `HYPRTK`-based constants and `config.py` defaults to the
  bar install dir, keeping `~/hyprtk` as a **runtime fallback** (so the bar still
  works when the full dotfiles are present).

### Phase 2 — extend install.sh dependency install
- Add the binary deps as a **feature-gated optional group** (`--with-extras`, or
  auto "install optional tools for theming/clipboard/updates"), installed through
  the existing package-manager detection.
- Install `papirus-folders` + `papirus-icon-theme` (script + theme, no build).
- Keep the core GTK typelibs as the only **required** set (the bar already degrades
  gracefully when a feature tool is missing).

### Phase 3 — decide C scripts explicitly
- Keep `sddm/update.sh`, `updates.sh`, `installupdates.sh`, `ssdetect.sh`
  (and their transitive deps `screenshot.sh`, `sshot.sh`, `library.sh`,
  `update-TS-run.sh`) as **dotfiles-owned integrations**. The bar toasts "not
  found" / shows `?` when they are absent — no crash.
- Optionally vendor them too for a single blob, but they stay Arch/root/dotfiles-coupled.

### Phase 4 — verify + sync
- Dry-run a standalone install into a fresh `$HOME` (no `~/hyprtk`), confirm every
  feature path resolves and degrades gracefully, then sync merged / live / GitHub.

---

## Not yet audited (do before Phase 1)

This inventory covers the scripts the bar calls **directly** plus their first-hop
transitives. A full closure is not done yet:

- `screenshot.sh` (286 lines) and `sshot.sh` likely pull their own deps
  (grim/slurp/swappy/hyprshot, GPU detection).
- `library.sh` (105 lines) defines shared installer functions (`_installSymLink`,
  `_installPackagesPacman`, …) that `installupdates.sh` and others source.
- `installer/scripts/` has **47** scripts and `hypr/scripts/` has **14**; only a
  subset are bar-reachable, but the transitive graph (e.g. `wal-watcher.sh`,
  `wallpaper-restore.sh`, `Volume.sh`, `updatewal.sh`) has not been mapped to the
  bar. A future audit should enumerate the full `bash`/`source`/`exec` closure.

The bar also still reads/writes desktop-wide config it does not own:
`~/.config/rofi`, `~/.config/swaylock`, `~/.config/matuwall`,
`~/.local/share/icons/Papirus-Dark`, and `~/.cache/theme-gui`. Decide whether
those are bundled assets, install.sh-managed, or left as dotfiles responsibilities.
