"""Keyboard state widget: Caps Lock / Num Lock indicators.

Reads the keyboard LED brightness files under /sys/class/leds (the same source
the old waybar keyboard_state.sh polled) so it works on Wayland. Each key is a
short label that dims when the lock is off and lights up (accent + bold) when
it is on.
"""
from __future__ import annotations

import glob
import logging

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .widgets import HoverButton  # noqa: E402

log = logging.getLogger("hyprtk_bar.kbstate")

POLL_MS = 500

_LED_GLOBS = {
    "caps": "/sys/class/leds/*::capslock/brightness",
    "num": "/sys/class/leds/*::numlock/brightness",
}

_LABELS = (("caps", "CAPS"), ("num", "NUM"))


def _led_on(led_class: str) -> bool:
    """True when any keyboard LED of the given class is lit."""
    for path in glob.glob(_LED_GLOBS[led_class]):
        try:
            with open(path, encoding="ascii") as f:
                return f.read(1).strip() == "1"
        except OSError:
            continue
    return False


class KbState(HoverButton):
    def __init__(self, cfg: dict, ipc):
        super().__init__("kbstate", vertical=False, spacing=6)
        self._cfg = cfg
        kb_cfg = cfg.get("kbstate") or {}
        self._interval = max(100, int(kb_cfg.get("poll_ms", POLL_MS)))
        self._labels: dict[str, Gtk.Label] = {}
        for key, text in _LABELS:
            label = Gtk.Label(label=text)
            label.get_style_context().add_class("kbstate-key")
            label.get_style_context().add_class(key)
            self.box.pack_start(label, False, False, 0)
            self._labels[key] = label
        self._update()
        GLib.timeout_add(self._interval, self._tick)

    def _tick(self) -> bool:
        self._update()
        return GLib.SOURCE_CONTINUE

    def _update(self) -> None:
        states = {key: _led_on(key) for key, _label in _LABELS}
        for key, on in states.items():
            ctx = self._labels[key].get_style_context()
            if on:
                ctx.add_class("on")
                ctx.remove_class("off")
            else:
                ctx.add_class("off")
                ctx.remove_class("on")
        self.set_tooltip_text(
            f"Caps Lock: {'on' if states['caps'] else 'off'}\n"
            f"Num Lock: {'on' if states['num'] else 'off'}"
        )