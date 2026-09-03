"""Clock widget: time/date label with a floating calendar popup."""
from __future__ import annotations

import datetime

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .popup import Popup  # noqa: E402
from .widgets import HoverButton  # noqa: E402


class Clock(HoverButton):
    def __init__(self, cfg: dict, ipc):
        super().__init__("clock", vertical=True, spacing=0)
        self._cfg = cfg
        self._clock = cfg.get("clock") or {}
        self._ipc = ipc
        self._popup = None

        self._time = Gtk.Label(label="--:--")
        self._time.get_style_context().add_class("clock-label")
        self._time.set_justify(Gtk.Justification.CENTER)
        self.box.pack_start(self._time, False, False, 0)

        if self._clock.get("date_format"):
            self._date = Gtk.Label(label="")
            self._date.get_style_context().add_class("clock-date")
            self._date.set_justify(Gtk.Justification.CENTER)
            self.box.pack_start(self._date, False, False, 0)
        else:
            self._date = None

        if self._clock.get("calendar"):
            self._build_popup()

        self._update()
        GLib.timeout_add_seconds(1, self._tick)

    def _build_popup(self) -> None:
        self._popup = Popup(self._cfg, self._cfg.get("position", "bottom"))
        cal = Gtk.Calendar()
        cal.set_display_options(
            Gtk.CalendarDisplayOptions.SHOW_HEADING
            | Gtk.CalendarDisplayOptions.SHOW_DAY_NAMES
        )
        self._popup.content.pack_start(cal, False, False, 0)
        self._popup.content.show_all()
        self._popup.set_on_leave(self._popup_hide)

    def _tick(self) -> bool:
        self._update()
        return GLib.SOURCE_CONTINUE

    def _update(self) -> None:
        now = datetime.datetime.now()
        fmt = self._clock.get("format", "%H:%M")
        self._time.set_text(now.strftime(fmt))
        if self._date and self._clock.get("date_format"):
            self._date.set_text(now.strftime(self._clock["date_format"]))

    def _popup_hide(self) -> None:
        if self._popup is not None:
            self._popup.hide_popup()

    def _on_button_press(self, _widget, event):
        if event.button == 1 and self._popup is not None:
            if self._popup.get_visible():
                self._popup.hide_popup()
            else:
                self._popup.show_above(self)
        return True