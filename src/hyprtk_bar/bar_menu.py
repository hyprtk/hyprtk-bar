"""Right-click bar menu.

All settings live in the bar settings window (right-click → "Bar settings…").
The context menu itself is just the entry point plus a config reload utility.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402


def build_bar_menu(cfg: dict, actions: dict) -> Gtk.Menu:
    menu = Gtk.Menu()

    settings = Gtk.MenuItem(label="Bar settings…")
    settings.connect("activate", lambda *_a: actions["open_settings"]())
    menu.append(settings)

    reload = Gtk.MenuItem(label="Reload config")
    reload.connect("activate", lambda *_a: actions["reload_config"]())
    menu.append(reload)

    return menu