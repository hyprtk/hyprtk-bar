# hyprtk-bar GTK3 → GTK4 · end-to-end runbook

How to prove — exhaustively and reproducibly — that **every** setting and surface
of `hyprtk-bar-gtk4` works, and which of them don't. The suite runs in a throwaway
Arch container, drives the real bar classes headlessly, and writes
`tools/e2e/report/e2e-output.html`.

The core idea: the ported tree is **dual-stack** (`compat.py` picks GTK3 or GTK4
from `HYPRTK_GTK`), so every test runs twice on the *same source*. A test that
passes on GTK3 and fails on GTK4 is a **port regression** — that is the signal the
report is built around.

---

## 1. Run it

```bash
tools/e2e/run-e2e.sh                     # both stacks, all layers L0–L5
tools/e2e/run-e2e.sh --build             # force image rebuild (pacman deps changed)
tools/e2e/run-e2e.sh --stack 4           # GTK4 only
tools/e2e/run-e2e.sh --layer 2 -- -k arc # one layer / one test (args after -- go to pytest)
```

Output: `tools/e2e/report/e2e-output.html` (+ `report-gtk3.json`, `report-gtk4.json`).

Requirements: rootless `podman` (vfs storage driver — already configured on this
box), network for the first image build. Nothing touches the live system: HOME is
sandboxed per stack (`/tmp/e2e-home-gtkN`) and a fake `hyprctl` stands in for
Hyprland.

---

## 2. What the environment looks like

* **Arch container** (`tools/e2e/Containerfile`): `gtk3` + `gtk4` +
  `gtk-layer-shell` + `gtk4-layer-shell` + `python-gobject` + `sway` + `grim`.
* **Headless sway** (`WLR_BACKENDS=headless`, pixman, `GSK_RENDERER=cairo`) —
  wlr-layer-shell capable, so the real `BarWindow`/`ArcMenuWindow`/`MenuWindow`/
  settings surfaces actually map.
* **dbus-run-session** so `NotificationController` can own
  `org.freedesktop.Notifications`.
* **fake Hyprland**: `tools/e2e/fake-hyprctl` answers monitors/workspaces/
  clients/layers; `harness/fake_ipc.py` records dispatches.
* **`LD_PRELOAD=libgtk{4-,}layer-shell.so`** per stack (gtk4-layer-shell must be
  linked before libwayland).

---

## 3. The layers (each is a section of `e2e-output.html`)

| Layer | File | What it proves |
|-------|------|----------------|
| **L0 static** | `test_l0_static.py` | every module imports under the active stack; no GTK4-removed API is still called (AST scan) |
| **L1 construct** | `test_l1_construct.py` | the bar, all 9 settings pages, both overlays, all 7 desktop widgets and the themer/monitor/clipboard dialogues build |
| **L2 settings matrix** | `test_l2_settings.py` | **every config-bound control**: perturb → Apply → config changed + live fingerprint; plus targeted cross-surface behaviours (arc/menu/widget toggles, layout show-hide, geometry) |
| **L3 functional** | `test_l3_functional.py` | overlay toggles, bar/tasklist context menus, quicklink picker, clipboard, notifications, widget-move control |
| **L4 visual** | `test_l4_visual.py` | grim a PNG of each surface, embedded for human review (no golden diff) |
| **L5 real-process** | `test_l5_smoke.py` | launches the actual `python -m hyprtk_bar`, drives SIGUSR1/SIGUSR2/SIGHUP, confirms clean SIGTERM exit |

### Coverage, not vibes

* L2 **enumerates controls from the live widget tree** (`harness/controls.py`), so
  a newly added setting is picked up automatically — nothing is hand-listed.
* Each control is perturbed, applied and **restored**, so failures name one switch.
* The arc menu is disabled for the matrix so a single crash there cannot mask
  every other control; its behaviour has dedicated tests.

---

## 4. Manual equivalent (the "runbook" proper)

If you are checking without the container, on a live Hyprland box:

1. Run the GTK4 bar from source (see the session handoff for the exact
   `LD_PRELOAD … -m hyprtk_bar` command) and open Settings (right-click bar →
   *Bar settings…* or `kill -USR1` for the menu, `hyprtk-bar` settings).
2. For **each page** (Bar, Fonts, Themes, Animations, Arc Menu, Menu, Quicklinks,
   Modules, Widgets): change **one** control, press **Apply**, and confirm both
   the config file *and* the live surface changed. Expected pairs:
   * Bar → position/height/gaps/opacity/width/align change the pill geometry.
   * Fonts → size changes module text and glyph size.
   * Themes → source/colours re-theme the bar immediately.
   * Animations → border animation starts/stops.
   * Arc Menu → **enable/disable** shows/hides the overlay (SIGUSR2 to toggle).
   * Menu → **enable/disable** shows/hides the start menu (SIGUSR1).
   * Quicklinks → *Choose…* opens the link picker; Apply rebuilds the links.
   * Modules → show/hide + Left/Center/Right moves a module live.
   * Widgets → enable/place each of the 7 widgets; each appears/disappears live.
3. Exercise the signals: `SIGUSR1` start menu, `SIGUSR2` arc menu, `SIGHUP`
   clipboard.
4. Confirm a **clean restart** (`Reload config` / `hyprctl dispatch exit`).

Every step above is mirrored by an automated test in L2/L3/L5.

---

## 5. Known defects this suite has already surfaced

Populated from the first full run; **fixes are a separate pass** (do not patch
product code just to make the report green — the report is the worklist).

| # | Where | Symptom | Layer |
|---|-------|---------|-------|
| D1 | `arcmenu.py:753` (`reload_from_cfg`) | `ArcMenuWindow.remove()` — GTK4 removed `Gtk.Window.remove`; **Apply crashes on every settings page** when the arc menu is live | L2 |
| D2 | `__main__.py:170` / arc wiring | enabling the arc menu when it was **off at startup** never creates the overlay (window only built at launch) | L2 |
| D3 | `arcmenu.py` `toggle()` | arc overlay opens but does not close on toggle | L3 |
| D4 | `menu/menu_window.py:639` (`_build_win7`) | `.get_child().get_style_context()` — GTK4 has no widget StyleContext; missed by the sweep | L0 |
| D5 | `bar_settings.py:253`, `menu/menu_window.py:1648` | `begin_move_drag` — GTK4 removed it; frameless header drag is dead (needs `Gtk.WindowDragGesture`) | L0 |
| D6 | whole tree | **the GTK3 escape hatch is broken**: `Gtk.CenterBox` is used unconditionally (no GTK3 fallback), so `HYPRTK_GTK=3` cannot even build the bar. Until fixed, the GTK3 column reads as a boot failure | L1 |

---

## 6. Files

```
tools/e2e/
  Containerfile        arch image (both GTK stacks + headless sway)
  run-e2e.sh           host entry point
  in-container.sh      sway + fake hyprctl + orchestrator
  run_e2e.py           runs pytest per stack, merges → output.html
  reporter.py          parity merge + HTML renderer
  conftest.py          fixtures + per-stack JSON reporter
  pytest.ini           --timeout=120 (a hung GTK test can't stall the suite)
  fake-hyprctl         canned Hyprland for the real-process smoke
  sway-headless.conf
  harness/             fake_ipc, runtime builder, control enumeration, apply/digest
  tests/               test_l0..l5
  report/              e2e-output.html + per-stack JSON (gitignored)
```
