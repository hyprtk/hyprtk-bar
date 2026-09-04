"""Quick Settings flyout (Win11-style): wifi/bluetooth toggles, volume/brightness.

Backed by the system session tools: `nmcli`, `bluetoothctl`, `wpctl`
(WirePlumber) and `brightnessctl`. The brightness row only appears when a real
backlight device exists. State is refreshed when the flyout opens and polled
every few seconds while it is visible.
"""
from __future__ import annotations

import logging
import re
import subprocess

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .config import icon_size_for  # noqa: E402
from .popup import Popup  # noqa: E402
from .widgets import HoverButton  # noqa: E402

log = logging.getLogger("hyprtk_bar.quicksettings")

SINK = "@DEFAULT_AUDIO_SINK@"


def _run(args, timeout=3) -> str:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def find_backlight() -> tuple[str, int, int] | None:
    """Return (device, current, max) for the first backlight/kbd class, or None."""
    for line in _run(["brightnessctl", "-m"]).splitlines():
        fields = line.split(",")
        if len(fields) < 5 or fields[1] not in ("backlight", "kbd_backlight"):
            continue
        device = fields[0]
        try:
            current, maxval = int(fields[2]), int(fields[4])
        except ValueError:
            continue
        if maxval > 0:
            return device, current, maxval
    return None


# ── volume ───────────────────────────────────────────────────────

def get_volume() -> tuple[float, bool] | None:
    out = _run(["wpctl", "get-volume", SINK])
    m = re.search(r"Volume:\s+([\d.]+)", out)
    if not m:
        return None
    return float(m.group(1)), "[MUTED]" in out


def set_volume_pct(pct: int) -> None:
    _run(["wpctl", "set-volume", SINK, f"{max(0, min(pct, 100)) / 100:.2f}"])


def toggle_mute() -> None:
    _run(["wpctl", "set-mute", SINK, "toggle"])


# ── wifi ─────────────────────────────────────────────────────────

def get_wifi() -> bool:
    return _run(["nmcli", "radio", "wifi"]).strip() == "enabled"


def set_wifi(on: bool) -> None:
    _run(["nmcli", "radio", "wifi", "on" if on else "off"])


# ── bluetooth ────────────────────────────────────────────────────

def get_bt() -> bool:
    m = re.search(r"Powered:\s+(yes|no)", _run(["bluetoothctl", "show"]))
    return bool(m and m.group(1) == "yes")


def set_bt(on: bool) -> None:
    _run(["bluetoothctl", "power", "on" if on else "off"])


# ── widgets ──────────────────────────────────────────────────────

class ToggleRow(HoverButton):
    """A row with icon, label and a switch; clicking the row also toggles."""

    def __init__(self, icon_name: str, label: str, on_apply):
        super().__init__("qs-row", vertical=False, spacing=10)
        self._on_apply = on_apply

        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.INVALID)
        icon.set_pixel_size(18)
        self.box.pack_start(icon, False, False, 0)

        lbl = Gtk.Label(label=label, xalign=0)
        self.box.pack_start(lbl, True, True, 0)

        self._switch = Gtk.Switch()
        self._switch.get_style_context().add_class("qs-switch")
        self._switch.set_valign(Gtk.Align.CENTER)
        self.box.pack_start(self._switch, False, False, 0)
        self._switch.connect("state-set", self._on_state_set)

    def set_state(self, on: bool) -> None:
        self._switch.set_active(bool(on))

    def _on_state_set(self, _switch, state) -> bool:
        try:
            self._on_apply(state)
        except Exception as exc:
            log.warning("toggle failed: %s", exc)
        return False  # let the switch update its visual state

    def _on_button_press(self, _widget, event):
        if event.button == 1 and not self._switch.get_state():
            self._switch.set_active(True)
        return True


class SliderRow(Gtk.Box):
    """A row with an icon (clickable when mute supported), a scale and a % label."""

    def __init__(
        self,
        icon_name: str,
        icon_on_name: str | None,
        label: str,
        get_pct,
        set_pct,
        muted_get=None,
        mute_toggle=None,
    ):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._get_pct = get_pct
        self._set_pct = set_pct
        self._muted_get = muted_get
        self._mute_toggle = mute_toggle
        self._icon_on = icon_on_name
        self._pending = None

        self._icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.INVALID)
        self._icon.set_pixel_size(18)
        if mute_toggle is not None:
            holder = Gtk.EventBox()
            holder.set_visible_window(False)
            holder.add(self._icon)
            holder.connect("button-press-event", self._on_icon_press)
            holder.set_tooltip_text("Toggle mute")
            self.pack_start(holder, False, False, 0)
        else:
            self.pack_start(self._icon, False, False, 0)

        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_size_request(52, -1)
        self.pack_start(lbl, False, False, 0)

        self._scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._scale.set_size_request(160, -1)
        self._scale.set_hexpand(True)
        self._scale.set_draw_value(False)
        self._scale.get_style_context().add_class("qs-scale")
        self.pack_start(self._scale, True, True, 0)
        self._scale.connect("value-changed", self._on_value_changed)

        self._pct = Gtk.Label(label="100%", xalign=1)
        self._pct.set_width_chars(4)
        self.pack_start(self._pct, False, False, 0)

    def refresh(self) -> None:
        pct = self._get_pct()
        if pct is not None:
            self._scale.handler_block_by_func(self._on_value_changed)
            self._scale.set_value(pct)
            self._scale.handler_unblock_by_func(self._on_value_changed)
            self._pct.set_text(f"{int(round(pct))}%")
        if self._muted_get is not None:
            self._update_icon(self._muted_get())

    def _update_icon(self, muted: bool) -> None:
        if self._icon_on:
            name = self._icon_on if muted else self._icon.get_icon_name()[0]
            self._icon.set_from_icon_name(name, Gtk.IconSize.INVALID)
            self._icon.set_pixel_size(18)

    def _on_icon_press(self, *_args) -> bool:
        if self._mute_toggle:
            try:
                self._mute_toggle()
            except Exception as exc:
                log.warning("mute toggle failed: %s", exc)
            GLib.timeout_add(200, self._apply_mute_refresh)
        return True

    def _apply_mute_refresh(self) -> bool:
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _on_value_changed(self, scale) -> None:
        value = int(round(scale.get_value()))
        self._pct.set_text(f"{value}%")
        if self._pending is not None:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(200, self._apply, value)

    def _apply(self, value: int) -> bool:
        self._pending = None
        try:
            self._set_pct(value)
        except Exception as exc:
            log.warning("set %r failed: %s", self._set_pct, exc)
        return GLib.SOURCE_REMOVE


class QuickSettingsButton(HoverButton):
    """Taskbar button that toggles the Quick Settings flyout."""

    def __init__(self, cfg: dict):
        super().__init__("qs-button", vertical=True, spacing=0)
        icon = Gtk.Image.new_from_icon_name(
            "preferences-system-symbolic", Gtk.IconSize.INVALID
        )
        self._icon = icon
        self._icon.set_pixel_size(icon_size_for((cfg.get("font") or {}).get("size", 16)))
        self._icon.get_style_context().add_class("accent-icon")
        self.box.pack_start(self._icon, True, True, 0)
        self._popup = QuickSettings(cfg)
        self._popup.set_on_leave(self._hide)

    def apply_font(self, font_size) -> None:
        self._icon.set_pixel_size(icon_size_for(font_size))

    def _toggle(self) -> None:
        if self._popup.get_visible():
            self._popup.hide_popup()
        else:
            self._popup.show_above(self)

    def _hide(self) -> None:
        self._popup.hide_popup()

    def shutdown(self) -> None:
        self._popup.hide_popup()

    def _on_button_press(self, _widget, event):
        if event.button == 1:
            self._toggle()
        return True


class QuickSettings(Popup):
    """The flyout panel."""

    def __init__(self, cfg: dict):
        super().__init__(cfg, cfg.get("position", "bottom"))
        self._cfg = cfg
        self._timer = None
        self._brightness_row = None

        title = Gtk.Label(label="Quick Settings", xalign=0)
        title.get_style_context().add_class("qs-title")
        self.content.pack_start(title, False, False, 0)

        self._wifi = ToggleRow("network-wireless-symbolic", "Wi-Fi", set_wifi)
        self.content.pack_start(self._wifi, False, False, 0)

        self._bt = ToggleRow("bluetooth-symbolic", "Bluetooth", set_bt)
        self.content.pack_start(self._bt, False, False, 0)

        self._volume = SliderRow(
            "audio-volume-high-symbolic",
            "audio-volume-muted-symbolic",
            "Volume",
            get_pct=lambda: int(round((get_volume() or (1.0, False))[0] * 100)),
            set_pct=set_volume_pct,
            muted_get=lambda: bool(get_volume() and get_volume()[1]),
            mute_toggle=toggle_mute,
        )
        self.content.pack_start(self._volume, False, False, 0)

        backlight = find_backlight()
        if backlight is not None:
            device, _cur, _mx = backlight

            def get_brightness():
                cur = _run(["brightnessctl", "-d", device, "get"])
                mx = _run(["brightnessctl", "-d", device, "max"])
                try:
                    return int(round(int(cur) / max(int(mx), 1) * 100))
                except ValueError:
                    return 0

            def set_brightness(pct: int) -> None:
                _run(["brightnessctl", "-d", device, "set", f"{pct}%"])

            self._brightness_row = SliderRow(
                "display-brightness-symbolic", None, "Brightness",
                get_brightness, set_brightness,
            )
            self.content.pack_start(self._brightness_row, False, False, 0)

        self.content.show_all()

    # ── lifecycle ─────────────────────────────────────────────────

    def show_above(self, widget) -> None:
        self.refresh()
        self._start_poll()
        super().show_above(widget)

    def hide_popup(self) -> None:
        self._stop_poll()
        super().hide_popup()

    def refresh(self) -> None:
        self._wifi.set_state(get_wifi())
        self._bt.set_state(get_bt())
        self._volume.refresh()
        if self._brightness_row is not None:
            self._brightness_row.refresh()

    def _start_poll(self) -> None:
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(5, self._on_poll)

    def _stop_poll(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _on_poll(self) -> bool:
        self.refresh()
        return GLib.SOURCE_CONTINUE