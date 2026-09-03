"""hyprtk-bar entry point.

The bar is a plain always-running GTK window (layer-shell surface) driven by
Gtk.main(). A SIGTERM quits it cleanly.
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import GLib, GLibUnix, Gtk

from .app import BarWindow
from .config import load as load_config


def _print_config() -> None:
    print(json.dumps(load_config(), indent=2))


def _run_window() -> int:
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