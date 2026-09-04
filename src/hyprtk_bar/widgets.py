"""Shared widgets for hyprtk-bar."""
from __future__ import annotations

import logging
import os
import shlex
import shutil

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import GLib, Gtk, Pango  # noqa: E402

log = logging.getLogger("hyprtk_bar.widgets")

GLYPH_FONT = "Symbols Nerd Font"


class Glyph(Gtk.Label):
    """A Nerd Font glyph rendered at an exact pixel size.

    The bar's system font does not contain the PUA glyphs (and its fallback
    maps them to the wrong characters, e.g. an apps grid showing as "5"), so
    glyphs always render with a dedicated Nerd Font family. The size is set in
    device units (pixels) to match the pixel size used by Gtk.Image icons.
    """

    def __init__(self, codepoint: str, css_class: str = "", font: str = ""):
        super().__init__(label=codepoint)
        self._font = (font or "").strip() or GLYPH_FONT
        if css_class:
            self.get_style_context().add_class(css_class)
        self.set_pixel_size(16)

    def set_pixel_size(self, size: int) -> None:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_family_new(self._font))
        attrs.insert(Pango.attr_size_new_absolute(int(max(size, 10)) * Pango.SCALE))
        self.set_attributes(attrs)


def spawn(command: str) -> bool:
    """Spawn a command line, resolving ``~`` and the binary with ~/.local/bin on PATH.

    The bar process is launched with a minimal PATH that does not include
    ``~/.local/bin``, so bare names of user-installed launchers (hyprtk-menu,
    hyprtk-arc-menu, theme-gui, ...) fail to resolve. Resolve the leading
    executable against an augmented PATH before spawning.
    """
    command = os.path.expanduser(command).strip()
    if not command:
        return False
    path = os.environ.get("PATH", "")
    home_bin = os.path.expanduser("~/.local/bin")
    if home_bin not in path.split(":"):
        path = home_bin + ":" + path
    parts = shlex.split(command)
    if parts:
        resolved = shutil.which(parts[0], path=path)
        if resolved:
            if command.startswith(parts[0]):
                command = resolved + command[len(parts[0]):]
            else:
                command = " ".join([resolved] + parts[1:])
    try:
        GLib.spawn_command_line_async(command)
    except GLib.Error as exc:
        log.warning("Failed to spawn %r: %s", command, exc)
        return False
    return True


class HoverButton(Gtk.EventBox):
    """An EventBox with a styled child box and a hover-highlight CSS class.

    GTK3 EventBoxes with visible_window=False do not reliably paint CSS
    backgrounds themselves, so the hover state is toggled as a class on the
    inner box, which draws through to the transparent toplevel.
    """

    def __init__(self, css_class: str, vertical: bool = True, spacing: int = 3):
        super().__init__()
        self.set_visible_window(False)
        self._box = Gtk.Box(
            orientation=(
                Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL
            ),
            spacing=spacing,
        )
        self._box.get_style_context().add_class(css_class)
        self.add(self._box)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("button-press-event", self._on_button_press)

    @property
    def box(self) -> Gtk.Box:
        return self._box

    def _on_enter(self, *_args):
        self._box.get_style_context().add_class("hover")
        return False

    def _on_leave(self, *_args):
        self._box.get_style_context().remove_class("hover")
        return False

    def _on_button_press(self, _widget, event):
        return False