"""Quick links: a row of launcher buttons rendered as Nerd Font glyphs.

Each link is a small button that runs a command on left-click and — when
configured — an alternate command on right- and middle-click (e.g. wallpaper:
theme-gui on left, re-generate the palette on right; clipboard history:
pick/delete/wipe). The link list lives in the config's ``quicklinks.links``
block and is fully editable without touching the bar code.
"""
from __future__ import annotations

import logging
import shlex
import subprocess

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import Gio, Gtk  # noqa: E402

from .config import DEFAULT_LINKS, icon_size_for  # noqa: E402
from .popup import bind_hover_tooltip  # noqa: E402
from .widgets import Glyph, HoverButton, spawn  # noqa: E402

log = logging.getLogger("hyprtk_bar.quicklinks")

# Shell operators that require the command to run inside a shell (GLib's
# spawn_command_line_async parses but does not evaluate them).
_SHELL_OPS = ("&&", "||", ";")


def default_browser_command() -> str:
    """Resolve the session's default web browser to a launchable command."""
    try:
        out = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        if out.endswith(".desktop"):
            try:
                info = Gio.DesktopAppInfo.new(out)
                line = info.get_commandline() if info is not None else None
            except (TypeError, GLib.Error):
                line = None
            if line:
                cmd = line.split()[0].rsplit("/", 1)[-1]
                if cmd:
                    return cmd
    except (subprocess.SubprocessError, OSError):
        pass
    return "brave"


def _launch(command: str) -> bool:
    """Spawn a quick-link command, wrapping it in a shell when needed."""
    command = command.strip()
    if not command:
        return False
    if any(op in command for op in _SHELL_OPS):
        return spawn(f"sh -c {shlex.quote(command)}")
    return spawn(command)


class QuickLinkButton(HoverButton):
    """One launcher button: a Nerd Font glyph, clickable per mouse button."""

    def __init__(self, cfg: dict, link: dict, icon_size: int):
        super().__init__("task-button", vertical=False, spacing=0)
        self._link = link
        ql = cfg.get("quicklinks") or {}
        self._glyph = Glyph(
            link.get("icon", ""),
            "quicklink-glyph",
            (ql.get("glyph_font") or "").strip(),
        )
        self.box.pack_start(self._glyph, False, False, 0)
        self._glyph.set_pixel_size(icon_size)
        label = link.get("label") or link.get("id") or ""
        bind_hover_tooltip(self, cfg, lambda: label)

    def apply_font(self, font_size, icon_size=0) -> None:
        if icon_size:
            self._glyph.set_pixel_size(max(10, int(icon_size)))
        else:
            self._glyph.set_pixel_size(icon_size_for(font_size, icon_size))

    def _on_button_press(self, _widget, event):
        command = self._link.get(
            {1: "command", 2: "command_middle", 3: "command_right"}.get(event.button, "command")
        ) or ""
        if not command and self._link.get("id") == "web":
            command = default_browser_command()
        if command:
            if not _launch(command):
                log.warning("failed to spawn quick link %r", command)
        return True


class QuickLinks(Gtk.Box):
    """The module: a horizontal row of QuickLinkButtons."""

    def __init__(self, cfg: dict, ipc=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._cfg = cfg
        self._buttons: list[QuickLinkButton] = []
        links = (cfg.get("quicklinks") or {}).get("links") or DEFAULT_LINKS
        for link in links:
            if not isinstance(link, dict) or not link.get("icon"):
                continue
            button = QuickLinkButton(cfg, link, self._glyph_size())
            self._buttons.append(button)
            self.pack_start(button, False, False, 0)

    def _glyph_size(self, font_size=None, icon_size=0) -> int:
        ql = self._cfg.get("quicklinks") or {}
        try:
            override = int(ql.get("icon_size", 0) or 0)
        except (TypeError, ValueError):
            override = 0
        if override > 0:
            return max(10, override)
        if icon_size:
            return max(10, int(icon_size))
        font_size = font_size if font_size else (self._cfg.get("font") or {}).get("size", 16)
        return icon_size_for(font_size, 0)

    def apply_font(self, font_size, icon_size=0) -> None:
        size = self._glyph_size(font_size, icon_size)
        for button in self._buttons:
            button.apply_font(font_size, size)