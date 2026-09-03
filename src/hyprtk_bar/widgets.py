"""Shared widgets for hyprtk-bar."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import Gtk  # noqa: E402


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