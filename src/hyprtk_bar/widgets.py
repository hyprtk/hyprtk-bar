"""Shared widgets for hyprtk-bar."""
from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gtk, Pango  # noqa: E402

from . import proc  # noqa: E402

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
    """Spawn a command line as argv (see ``proc.spawn_command_line``).

    Kept as a thin wrapper so existing callers don't change; the real work —
    ``~``/binary resolution and quoting-safe argv building — lives in
    ``proc``.
    """
    return proc.spawn_command_line(command)


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