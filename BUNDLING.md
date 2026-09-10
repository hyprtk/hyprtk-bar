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

> **Status: complete.** Phases 1–4 are done; only the "Not yet audited" closure
> below remains as optional follow-up.

### Phase 1 — vendor the A + B scripts into the bar ✅
- Added `scripts/` to the repo; `install.sh` copies it to
  `~/.local/share/hyprtk-bar/scripts/`.
- Vendored `wallpaper-colors.sh`, `change-icons.sh`, `sync-rofi-theme.sh`,
  `appsmenu.sh`, `updatewal-awww.sh` (+ the 3 toggle scripts + rofi variants +
  `config-apps-menu.rasi` under `scripts/rofi/`). `cliphist.sh` was **replaced**
  by the in-bar clipboard manager rather than vendored.
- Repointed `themer.py` / `config.py` to resolve bundled scripts via
  `SCRIPTS_DIR` / `resolve_script()`, keeping `~/hyprtk` as a runtime fallback.

### Phase 2 — extend install.sh dependency install ✅
- `install.sh` now installs the feature binaries by default (`EXTRAS` map per
  package manager + `EXTRAS_AUR` for `python-pywal16-git`/`papirus-folders` via
  yay/paru), with `--no-extras` to skip and `--no-deps` implying `--no-extras`.

### Phase 3 — decide C scripts explicitly ✅
- `sddm/update.sh`, `updates.sh`, `installupdates.sh`, `ssdetect.sh` (and their
  transitives) stay **dotfiles-owned**. The bar toasts "not found" / shows `?`
  when absent — no crash. Not vendored into the bar.

### Phase 4 — verify + sync ✅
- Verified (headless, simulated no-`~/hyprtk`):
  - bundled scripts + rofi variants resolve via `SCRIPTS_DIR`;
  - `resolve_script()` falls back to `~/hyprtk` when a bundled script is absent;
  - `updates._allowed_script()` rejects an absent `updates.sh` → polling disabled;
  - themer guards (`is_file()` → toast) cover wallpaper / change-icons / sddm /
    papirus-folders / wal absence.
- Synced merged / live / GitHub.

---

## Closure audit (complete)

The full `bash` / `source` / `exec` closure is mapped below. It cleanly
partitions into two disjoint sets — no further bar-bundling is needed.

### Bar-bundled scripts (closed set — no dotfiles deps)

| Script | Reaches |
|--------|---------|
| `wallpaper-colors.sh` | `change-icons.sh` (bundled), `awww`, `wal`, `hyprctl`, `wob` |
| `change-icons.sh` | `papirus-folders.sh` (third-party), `notify-send`, `sed`/`tr` |
| `sync-rofi-theme.sh` | `python3`, `ln` (variants bundled) |
| `appsmenu.sh` | `rofi` (config bundled) |
| `updatewal-awww.sh` | `change-icons.sh` (bundled), `wal`, `awww`, `hyprctl`, `notify-send`, `source ~/.cache/wal/colors.sh` (pywal cache) |
| 3× toggle scripts | `kill` / `cat` / `flock` |

The only non-bundled reference is `~/.cache/wal/colors.sh` — a pywal-generated
cache file, not a dotfiles script.

### Dotfiles-owned C-scripts + their full transitive closure

These are reached only via the C-scripts (never by the bundled set) and stay in
the dotfiles; the bar degrades gracefully when any of them is absent.

| Script | Reaches |
|--------|---------|
| `ssdetect.sh` | `screenshot.sh` + `sshot.sh` |
| `screenshot.sh` | `notification-handler` (sourced), `installer/scripts/settings/*`, `grim`/`slurp`/`hyprpicker`/`rofi`/`notify-send` |
| `sshot.sh` | `hyprquickframe` |
| `installupdates.sh` | `library.sh` (sourced: pacman/yay/sudo helpers), `update-TS-run.sh`, `yay`, `timeshift` |
| `update-TS-run.sh` | `sudo`/`sed`/`tee`/`grub-mkconfig` |
| `sddm/update.sh` | `grub-mkconfig`/`fc-cache`/`sudo`/`sed`/`tee` + `sddm.conf`/`theme.conf` |
| `updates.sh` | `checkupdates`/`trizen` |

### Desktop-wide config the bar reads/writes

| Path | Decision |
|------|----------|
| rofi `variants/` | **bundled** (`scripts/rofi/variants/`) |
| rofi `variant.rasi` symlink + base rofi config | rofi/user responsibility (rofi is a separate app) |
| `~/.config/swaylock/config` | dotfiles (swaylock is a separate app; themer edits if present) |
| `~/.config/matuwall/config.json` | dotfiles (matuwall is a separate app; themer edits if present) |
| `~/.local/share/icons/Papirus-Dark` | install.sh-managed (`papirus-icon-theme` extras) |
| `~/.cache/theme-gui` | bar-owned (auto-generated thumbnail cache) |
