"""hyprtk-bar entry point.

The bar is a plain always-running GTK window (layer-shell surface) driven by
Gtk.main(). A SIGTERM quits it cleanly. Only one instance is allowed — a
flock in $XDG_RUNTIME_DIR prevents duplicate bars stacking (e.g. from
duplicate autostart entries).
"""
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

from .app import BarWindow
from .config import load as load_config

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
    win = BarWindow(cfg)
    win.show_all()

    def on_sigterm(*_args):
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, on_sigterm, None)

    try:
        Gtk.main()
    finally:
        win.shutdown()
    return 0


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