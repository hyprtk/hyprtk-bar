"""hyprtk-bar entry point.

The bar is a plain always-running GTK window (layer-shell surface) driven by
Gtk.main(). A SIGTERM quits it cleanly. Only one instance is allowed — a
flock in $XDG_RUNTIME_DIR prevents duplicate bars stacking (e.g. from
duplicate autostart entries).
"""

# ─────────────────────────────────────────────────────────────────
#   HYPRTK · hyprtk-bar · __main__
#   Part of the Hyprtk desktop suite · github.com/hyprtk
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import signal
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import GLib, GLibUnix, Gtk

from .app import BarWindow, select_monitors
from .arcmenu import ArcMenuWindow  # noqa: E402
from .config import load as load_config
from .ipc import HyprIPC
from .menu.menu_window import MenuWindow  # noqa: E402

_lock_file = None


def _acquire_lock() -> bool:
    """Take an exclusive flock; returns False if another bar is already running."""
    global _lock_file
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = Path(runtime) / "hyprtk-bar.lock"
    try:
        _lock_file = open(path, "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except (OSError, ValueError):
        return False


def _print_config() -> None:
    print(json.dumps(load_config(), indent=2))


def _run_window() -> int:
    if not _acquire_lock():
        logging.warning("another hyprtk-bar is already running; exiting")
        return 1
    cfg = load_config()

    # One Hyprland IPC + event-socket thread shared by all per-monitor bars.
    ipc = HyprIPC()
    monitors = select_monitors(cfg)
    if not monitors:
        logging.warning("no monitors available; giving up")
        return 1

    windows = []
    for i, monitor in enumerate(monitors):
        is_primary = i == 0 or monitor.is_primary()
        win = BarWindow(
            cfg,
            monitor=monitor,
            ipc=ipc,
            is_primary=is_primary,
            start_ipc=(i == 0),
        )
        win.show_all()
        windows.append(win)
    logging.info("started %d bar(s) on %d monitor(s)", len(windows), len(monitors))

    # The arc menu overlay is owned by the bar process: created when the
    # ``arcmenu`` module is enabled, themed with the bar's palette, and toggled
    # by SIGUSR2 (a Hyprland keybinding signals the running bar).
    arc_win = None
    if (cfg.get("arcmenu") or {}).get("enabled", True):
        arc_win = ArcMenuWindow(
            cfg,
            on_settings=lambda: _open_arc_settings(windows),
        )
        arc_win.show_all()
        primary = next((w for w in windows if w.is_primary), windows[0])
        primary.set_theme_extra_callback(arc_win.apply_bar_palette)
        primary._bar.set_arcmenu_callback(lambda _block: arc_win.reload_from_cfg())
        logging.info("started arc menu overlay")

    # The start menu (hyprtk-menu) is likewise owned by the bar process: created
    # when the ``menu`` module is enabled, toggled by SIGUSR1 and by the bar's
    # start button. Its settings open the bar settings dialogue's "Menu" page.
    # Unlike the arc overlay it starts HIDDEN (the start button / keybind
    # reveals it).
    menu_win = None
    if (cfg.get("menu") or {}).get("enabled", True):
        menu_win = MenuWindow(
            bar_cfg=cfg,
            on_settings=lambda: _open_menu_settings(windows),
        )
        primary = next((w for w in windows if w.is_primary), windows[0])
        primary._bar.set_menu_callback(lambda: menu_win.toggle())
        primary._bar.set_menu_reload_callback(lambda _block: menu_win.reload_from_cfg())
        logging.info("started start menu")

    def on_sigterm(*_args):
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    def on_sigusr2(*_args):
        if arc_win is not None:
            arc_win.toggle()
        return GLib.SOURCE_CONTINUE

    def on_sigusr1(*_args):
        if menu_win is not None:
            menu_win.toggle()
        return GLib.SOURCE_CONTINUE

    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, on_sigterm, None)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, on_sigusr2, None)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_sigusr1, None)

    try:
        Gtk.main()
    finally:
        if arc_win is not None:
            arc_win.destroy()
        if menu_win is not None:
            menu_win.destroy()
        for win in windows:
            win.shutdown()
    return 0


def _open_arc_settings(windows) -> None:
    """Open the bar settings dialogue on the Arc Menu tab."""
    primary = next((w for w in windows if w.is_primary), windows[0])
    primary._bar.open_settings("arcmenu")


def _open_menu_settings(windows) -> None:
    """Open the bar settings dialogue on the Menu tab."""
    primary = next((w for w in windows if w.is_primary), windows[0])
    primary._bar.open_settings("menu")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="hyprtk-bar",
        description="Windows 11-style taskbar for Hyprland (GTK3 + layer shell).",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the resolved config as JSON and exit.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.print_config:
        _print_config()
        return 0

    return _run_window()


if __name__ == "__main__":
    sys.exit(main())