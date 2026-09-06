"""Package-update indicator: polls updates.sh and shows the pending count.

Replaces the old waybar ``custom/updates`` module — a Nerd Font glyph with the
pending-update count, colored by threshold (green/yellow/red), a hover tooltip,
and a left-click that opens the update installer in a floating terminal. The
count, CSS class and tooltip come from the script's waybar-style JSON output.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .config import icon_size_for  # noqa: E402
from .popup import bind_hover_tooltip  # noqa: E402
from .widgets import Glyph, HoverButton, spawn  # noqa: E402

log = logging.getLogger("hyprtk_bar.updates")

_GLYPH = "\uf0ab"  # updates icon


class Updates(HoverButton):
    """Pending-update count with a hover tooltip; click runs the installer."""

    def __init__(self, cfg: dict, ipc=None):
        super().__init__("updates", vertical=False, spacing=6)
        u = cfg.get("updates") or {}
        self._interval = max(5, int(u.get("interval", 60)))
        self._script = os.path.expanduser(
            u.get("script", "~/hyprtk/installer/scripts/updates.sh")
        )
        self._install = u.get(
            "install_command",
            "alacritty -o window.dimensions.lines=45 window.dimensions.columns=90"
            " --class floating -e ~/hyprtk/installer/scripts/installupdates.sh",
        )
        font_cfg = cfg.get("font") or {}
        self._glyph = Glyph(_GLYPH, "accent-icon")
        self._glyph.set_pixel_size(
            icon_size_for(font_cfg.get("size", 16), font_cfg.get("icon_size", 0))
        )
        self.box.pack_start(self._glyph, False, False, 0)

        self._label = Gtk.Label(label="")
        self._label.get_style_context().add_class("updates-value")
        self.box.pack_start(self._label, False, False, 0)

        self._tip = ""
        self._update()
        GLib.timeout_add_seconds(self._interval, self._tick)
        bind_hover_tooltip(self, cfg, lambda: self._tip)

    def apply_font(self, font_size, icon_size=0) -> None:
        self._glyph.set_pixel_size(icon_size_for(font_size, icon_size))

    def _tick(self) -> bool:
        self._update()
        return GLib.SOURCE_CONTINUE

    def _update(self) -> None:
        text, css, tooltip = self._query()
        self._label.set_text(text)
        ctx = self._label.get_style_context()
        if css == "red":
            ctx.add_class("high")
            ctx.remove_class("warn")
        elif css == "yellow":
            ctx.add_class("warn")
            ctx.remove_class("high")
        else:
            ctx.remove_class("high")
            ctx.remove_class("warn")
        self._tip = tooltip or f"{text} update(s)"

    def _query(self) -> tuple[str, str, str]:
        try:
            out = subprocess.run(
                [self._script], capture_output=True, text=True, timeout=30
            ).stdout.strip()
            data = json.loads(out)
            return (
                str(data.get("text", "0")),
                str(data.get("class", "green")),
                str(data.get("tooltip", "")),
            )
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            return "?", "green", ""

    def _on_button_press(self, _widget, event):
        if event.button == 1 and self._install:
            # Wrapped in a shell so the embedded ~/ path expands.
            spawn(f"sh -c {shlex.quote(self._install)}")
        return True