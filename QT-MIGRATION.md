# GTK4 → Qt migration assessment

**Status:** planned / gated (research complete)
**Owner:** hyprtk (Kori Tk)
**Scope:** assess moving the hyprtk GTK apps to Qt — `hyprtk-bar`, `hyprtk-usb`
  (GUI), `Hyprtk-ISO-Creator` (GUI), plus the `hyprtk-multi-distro` packaging,
  vendoring, theming and test plumbing that carries them.
**Out of scope:** third-party GTK apps the distro installs (Thunar, Mousepad,
  `swappy`, `nwg-look`, xfce4, `gvfs`, `hyprmod`); they keep needing the GTK
  runtime regardless.
**Related:** `GTK4-MIGRATION.md` (the GTK3→GTK4 plan; §13 there already
  considered and rejected a Qt port).

---

## 1. Bottom line

**Not a port — a rewrite, gated on one unresolved problem: layer shell + Python
has no supported path.** The two small GUIs are easy re-skins. The bar is the
dominant cost and cannot be done in Python QtWidgets; the supported Qt route for
a Wayland bar is **QML**.

Recommended sequence:

1. **Port `hyprtk-usb` + `Hyprtk-ISO-Creator` to Qt (PySide6) now** — cheap,
   isolated, de-risks the Qt packaging/theming toolchain.
2. **Leave the GTK4 bar running.** Build the Qt bar separately as QML
   presentation + Python/IPC logic (`hyprtk-bar-qt`), never as PySide6
   QtWidgets.
3. Cut over only at visual + functional parity.

---

## 2. Inventory

| # | Consumer | Kind | Size | Qt verdict | Effort |
|---|----------|------|------|-----------|--------|
| 1 | `hyprtk-bar` (`src/hyprtk_bar/`) | GTK4 app | 27,480 LOC, 51 modules | **hard rewrite; layer-shell blocker** | **months** |
| 2 | `hyprtk-usb-gui` (`python/hyprtk_usb/gui.py`) | GTK4 app | ~580 LOC | re-skin; core stays | **1–3 sessions** |
| 3 | `Hyprtk-ISO-Creator` (`python/hyprtk_isocreator/gui.py`) | GTK4 app | ~565 LOC | re-skin; core stays | **1–3 sessions** |
| 4 | `hyprtk-multi-distro` packaging/theming/CI | shell + config | broad | mechanical churn | **~1 week** |
| 5 | vendored copies under `installer/{hyprtk-bar,hyprtk-usb,hyprtk-iso-creator}/` | vendored trees | — | re-vendor after each port | follows 1–3 |

---

## 3. The blocker: layer shell on Qt

The bar's layer-shell consumers are `app.py`, `popup.py`, `notifications.py`,
`arcmenu.py`, `menu/menu_window.py`, `desktop/base.py`, `clipboard.py`,
`themer.py` — all built on the `Gtk4LayerShell` GI typelib (selected in
`compat.py:48-74`), using `init_for_window`, `set_layer`, `set_anchor`,
`set_exclusive_zone`, `set_margin`, `set_keyboard_mode`, `set_namespace`,
`set_monitor`. The `hyprtk-bar` namespace is load-bearing: the surface watchdog
(`__main__.py:131`) and `hyprctl layers` depend on it.

Qt's equivalent is **`LayerShellQt`** (KDE):

- The C++ API matches the bar's needs (`setAnchors`, `setExclusiveZone`,
  `setKeyboardInteractivity(None/Exclusive/OnDemand)`, `setLayer`, `setMargins`,
  `setScope`, `setScreen`).
- It operates on a **`QWindow`, not a `QWidget`**. QWidget has no direct support
  (needs a `winId()`/`create()` hack).
- It ships a **QML module** (`org.kde.layershell`), packaged on Debian
  (`qml6-module-org-kde-layershell`), Fedora, Arch.
- It has **no official Python binding.** KDE devs (discuss.kde.org, Dec 2024):
  "It's not possible right now, but bindings could be added." The only Python
  wrappers (`thekingsleyr/layershellqt-python`, `cideight/pyside6-layer-shell`)
  are 0-star, unpackaged hobby repos, and require compiling against a system
  PySide6 + layer-shell-qt build.
- `qtwayland` has **no stock layer-shell client shell** (only compositor-side in
  KWin). `tfbogdan/qtlayershell` uses private QtWaylandClient APIs and warns it
  "may break between Qt versions."

**Consequence:** Python QtWidgets is an unsupported hack for a layer-shell bar.
The supported route is **QML** — either KDE Plasma panels, a custom
`org.kde.layershell` shell, or **Quickshell**.

### 3.1 Quickshell

`Quickshell` (outfoxxed) is a QtQuick/QML toolkit for building status bars,
widgets and lockscreens. It provides, out of the box: Wayland/X11, Hyprland/i3/
Sway workspaces, PipeWire, BlueZ, UPower, MPRIS, and an **SNI system tray +
DBusMenu host**. It is packaged in Arch, Debian and NixOS, and is the basis of
many real Hyprland bars (end_4's illogical-impulse, Caelestia, noctalia). Its
presentation layer is QML; logic that QML can't express cleanly can be pushed to
a Python process driven over Quickshell IPC (`qs ipc call/wait/listen`) or a
socket.

---

## 4. The bar — cost breakdown

Measured against `src/hyprtk_bar/`:

- **`compat.py` (1,330 LOC) does not survive.** It is a GTK3↔GTK4 shim, not a
  toolkit abstraction, and every module subclasses GTK widget types directly.
- **Widget/layout code (~60% of source)** is rewritten: `Gtk.Box` 278,
  `Gtk.Label` 240, `Gtk.Button` 79, plus hand-tuned custom measure/allocate in
  `bar.py` (`ClipBox`, `Bar.do_size_allocate`), `window.py`, `app.py`
  (`BarWindow.do_size_allocate` + input-region shaping), `desktop/base.py`.
- **CSS/theming is the dominant cost:** 4,738 hand-written CSS lines
  (`assets/style.css`, layout skins, `themes/*/style.css`) plus every Python
  CSS generator (`theme.py:build_css`, `menu/theme.py:build_css`,
  `desktop/theme.py`, `themer.py`) and the pywal/theme-import pipeline. QSS is a
  **different language** with a different feature set (see §5).
- **Layer shell** (8 modules) — see §3.

What survives unchanged (roughly 17% clean modules + ~20–25% embedded portable
logic):

| Portable module | LOC | Notes |
|---|---:|---|
| `monitor_data.py` | 1,473 | `/proc`/`/sys`/`lsblk`/`dmidecode` (no GI) |
| `config.py` | 1,250 | JSON config + pywal loader (no GI) |
| `theme_import.py` | 637 | GTK-CSS **decoder** → palette (no GI) |
| `ipc.py` | 291 | `hyprctl` + Hyprland socket2 (no GI) |
| `desktop/theme.py` | 274 | CSS string builder (no GI) |
| `hypr_animations.py` | 238 | Lua scanner (no GI) |
| `menu/config.py`, `desktop/placement.py`, `colors.py`, `desktop/clock_theme.py` | ~500 | pure logic |
| `dbus-next` consumers | — | notifications daemon, SNI tray, `dbusmenu.py` — toolkit-agnostic |

---

## 5. Styling: Qt vs GTK CSS

QtWidgets uses **QSS**, a subset of CSS2; QML uses declarative properties (not
CSS at all). What maps:

- `background-color`, `background` with `qlineargradient`/`qradialgradient`,
  `border` + `border-radius` (per-corner), `color`, `font-*`, `padding`/
  `margin`, `min-/max-width/height`, `image`.

What has **no QSS equivalent** (the frosted-glass hits):

- `box-shadow` (workaround: `QGraphicsDropShadowEffect` / border-image)
- `transition` / `animation` (Qt QSS is static; use `QPropertyAnimation`)
- blur / `filter` / `backdrop-filter` (QML `MultiEffect` only)
- CSS variables / `var()` (QSS has only dynamic properties + `unpolish/polish`)
- `@define-color`, `calc()`, `::before/::after`, `pointer-events`,
  `-gtk-icon-*`, `transform`

pywal is easy to re-target (`colors.json` is templated; pywal16 already ships a
`colors.qml`); the issue is the CSS *feature* loss, not the palette.

---

## 6. The two small GUIs

Both are thin, frameless `Gtk.ApplicationWindow` wizards over **toolkit-free
cores** (`hyprtk_usb/core.py` 392 LOC, `hyprtk_isocreator/core.py` 177 LOC — no
`gi` import; tests are GUI-free). No layer shell. Mechanical 1:1 map
(`Box`→`QHBoxLayout`, `ComboBoxText`→`QComboBox`, `Entry`→`QLineEdit`,
`ProgressBar`→`QProgressBar`, `FileChooserDialog`→`QFileDialog`,
`TextView`→`QPlainTextEdit`, `GLib.idle_add`→queued signal). Real friction:
~90 lines of inline CSS each (QSS retune), the `Gtk.WindowHandle` drag →
`startSystemMove()`, and lifting `load_palette` out of the USB app's
`rich`-based `ui.py`. **Both ~1–3 sessions each.**

---

## 7. `hyprtk-multi-distro` impact

Mechanical but wide:

- **Packaging:** swap GTK/GI/typelib names for Qt6 + PySide6 across 6 families
  (`hypr/packages/*.sh`, bar `install.sh` `DEPS`, `packages.hyprtk`, Nix
  `derivation.nix`/`flake.nix`). `qt6ct`/`qt6-wayland` already exist in
  `graphics-card.sh` and `packages.hyprtk`.
- **Layer shell:** Qt needs no GI typelib, so the `gtk4-layer-shell`
  source-build (`srcapps-install.sh:165-181`), the `-Dintrospection=false`
  contradiction, and the bar's `LD_PRELOAD` launcher all retire — but matuwall
  may still want the `.so`.
- **Theming:** replace `gengtk.sh`/oomox and the bar's `@import
  colors-waybar.css` with a pywal→QSS/QPalette (or Kvantum / qt6ct scheme)
  path; add `QT_QPA_PLATFORMTHEME`.
- **Gates:** `container-matrix.sh`, `package-audit.sh`, `output.html`,
  `container-matrix.allow` regenerate with Qt names.
- **Unchanged:** launcher names, keybindings, window titles, `.desktop`
  entries, sudoers — all toolkit-neutral.

---

## 8. Effort estimate

| Track | Estimate |
|---|---|
| `hyprtk-usb` GUI | 1–3 sessions |
| `Hyprtk-ISO-Creator` GUI | 1–3 sessions |
| Qt toolchain: packaging + pywal→QSS theming across distros | ~1 week |
| `hyprtk-bar-qt`: QML shell foundation (layer shell, config, Hyprland IPC) | 1–2 weeks |
| ... simple modules (workspaces/clock/sysmon/graphs) | 1–2 weeks |
| ... complex modules (tasklist/notifications/quicksettings/clipboard/arc/settings) | 2–4 weeks |
| ... SNI tray + dbusmenu host | 1 week |
| ... CSS→QSS/QML retune to visual parity vs `SHOWCASE.md` | 1–2 weeks |
| ... installer/Nix/vendor/docs/gates | ~1 week |
| **Bar total** | **order of 8–14 focused weeks** (before parity), risks in QML retune + tray |

---

## 9. Recommendation / phasing

| Phase | Deliverable | Exit criteria |
|---|---|---|
| Q0 | This assessment; PySide6 chosen (LGPL, distro-packaged) | agreed |
| Q1 | `hyprtk-usb` GUI on PySide6 | GUI flows work; `core.py`/tests untouched; vendored |
| Q2 | `Hyprtk-ISO-Creator` GUI on PySide6 | idem |
| Q3 | pywal→Qt theming path + Qt packaging in multi-distro | T1/T2/audit green with Qt names |
| Q4 | `hyprtk-bar-qt`: QML shell foundation + layer shell + config + IPC | blank bar appears under Hyprland |
| Q5 | Port modules by weight (simple → complex) | feature parity per module |
| Q6 | SNI tray + notifications + dbusmenu host | tray + notifications work |
| Q7 | Theming retune to visual parity | matches `SHOWCASE.md` |
| Q8 | Cutover: vendor `hyprtk-bar-qt`, retire GTK bar | promote to prod |

Rollback: the GTK4 bar keeps shipping until the Qt bar reaches parity. No distro
loses the bar mid-migration.

---

## 10. Options considered

- **Stay on GTK4** — viable; zero work; already parity. Baseline.
- **Qt Widgets via PySide6/PyQt6** — **rejected**: no supported layer-shell
  binding for Python; requires an unsupported `QWindow` hack or an unmaintained
  Shiboken shim.
- **QML shell (Quickshell or custom `org.kde.layershell`)** — the only
  supported Qt route for a Wayland bar. Chosen architecture for the Qt bar:
  QML presentation + Python/IPC logic.
- **Adwaita / `relm4` / webview** — rejected (see `GTK4-MIGRATION.md` §13).

---

## 11. Open questions

1. Bar Qt foundation — **Quickshell** (batteries included: layer shell, Hyprland
   IPC, SNI tray, MPRIS) vs a **minimal custom `org.kde.layershell`** shell
   (more control, more work)?
2. How much bar logic stays in Python behind IPC vs moves into QML/Quickshell
   services?
3. Qt binding — **PySide6** (LGPL, packaged) vs PyQt6 (GPL, pip/AUR-only).
4. Cutover strategy — hard-cut at parity, or ship GTK and Qt bars side by side?
5. Theming target — generated **QSS** vs **Kvantum** theme vs **qt6ct** scheme
   for the pywal palette?
6. Keep a GTK path in the installer during the transition?
