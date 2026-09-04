"""Floating popup windows (layer-shell) for previews and the calendar.

Gtk.Popover is unusable near screen edges in GTK3/Wayland — it spams
`gtk_render_frame_gap: assertion 'xy0_gap >= 0' failed` whenever the arrow is
clamped against a corner. Popups are therefore plain layer-shell windows
anchored to the bar's edge and offset with margins, drawn as our own rounded
boxes (which render cleanly, like the bar pill itself).
"""
from __future__ import annotations

import cairo

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

GAP = 6  # vertical gap between the bar and a popup


class Popup(Gtk.Window):
    """A borderless, transparent layer-shell window that floats above the bar."""

    def __init__(self, cfg: dict, bar_edge: str = "bottom"):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._cfg = cfg
        self._bar_edge = bar_edge
        self._close_cb = None
        self._enter_cb = None
        self._leave_cb = None
        self._hide_timer = None
        self._pointer_inside = False

        self.set_title("hyprtk-bar-popup")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_accept_focus(False)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.content.get_style_context().add_class("popup-box")
        self.add(self.content)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "hyprtk-bar-popup")
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        edge = (
            GtkLayerShell.Edge.TOP
            if bar_edge == "top"
            else GtkLayerShell.Edge.BOTTOM
        )
        GtkLayerShell.set_anchor(self, edge, True)

        self.connect("size-allocate", self._on_size_allocate)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("motion-notify-event", self._on_motion)

    # ── callbacks ─────────────────────────────────────────────────

    def set_on_close(self, cb) -> None:
        self._close_cb = cb

    def set_on_enter(self, cb) -> None:
        self._enter_cb = cb

    def set_on_leave(self, cb) -> None:
        self._leave_cb = cb

    # ── positioning ───────────────────────────────────────────────

    def _monitor_geometry(self, bar_win):
        """The bar window's monitor geometry, if the bar targets a monitor.

        With multi-monitor bars the popup must clamp within its own monitor
        rather than the whole screen (layer-shell margins are monitor-local).
        """
        monitor = getattr(bar_win, "monitor", None)
        if monitor is not None:
            geo = monitor.get_geometry()
            return geo.x, geo.y, geo.width, geo.height
        alloc = bar_win.get_allocation()
        screen = Gdk.Screen.get_default()
        return alloc.x, alloc.y, screen.get_width(), screen.get_height()

    def _pill_bounds(self, bar_win, screen_w):
        """Monitor-local (left, right) horizontal bounds of the visible pill.

        The pill is narrower than the monitor (e.g. ``width: 75%``), so popups
        must stay inside it — otherwise they spill past the bar's right edge.
        The pill allocation is relative to the bar window, which spans its
        monitor (origin x=0), so it is already monitor-local.
        """
        pill = getattr(getattr(bar_win, "_bar", None), "pill", None)
        if pill is not None:
            alloc = pill.get_allocation()
            if alloc.width > 0:
                return alloc.x, alloc.x + alloc.width
        return 0, screen_w

    def set_bar_edge(self, edge: str) -> None:
        """Re-anchor the popup to the current bar edge (top/bottom toggle).

        A popup floats from the same edge the bar is on: a bottom bar floats it
        above (anchor BOTTOM), a top bar floats it below (anchor TOP). The old
        edge anchor is dropped and the new one set, so popups reposition when
        the bar's position changes at runtime.
        """
        if edge not in ("top", "bottom") or edge == self._bar_edge:
            return
        old = (
            GtkLayerShell.Edge.TOP
            if self._bar_edge == "top"
            else GtkLayerShell.Edge.BOTTOM
        )
        new = (
            GtkLayerShell.Edge.TOP
            if edge == "top"
            else GtkLayerShell.Edge.BOTTOM
        )
        GtkLayerShell.set_anchor(self, old, False)
        GtkLayerShell.set_anchor(self, new, True)
        self._bar_edge = edge

    def reposition(self) -> None:
        """Re-apply the floating offset on the current bar edge.

        Called when the bar moves top/bottom while this popup is open, so it
        follows the bar instead of staying at the old edge.
        """
        if not self.get_visible():
            return
        edge = (
            GtkLayerShell.Edge.TOP
            if self._bar_edge == "top"
            else GtkLayerShell.Edge.BOTTOM
        )
        offset = (
            self._cfg.get("height", 42)
            + self._cfg.get("gap_in", 6) + self._cfg.get("gap_out", 6)
            + GAP
        )
        GtkLayerShell.set_margin(self, edge, offset)

    def show_above(self, widget) -> None:
        """Size to content and float it just above the given bar widget."""
        nat = self.content.get_preferred_size().natural_size
        min_w, min_h = self.get_size_request()
        width = max(nat.width, min_w if min_w > 0 else 1)
        height = max(nat.height, min_h if min_h > 0 else 1)
        self.set_size_request(width, height)

        # Follow the bar's current edge (position may have changed since build).
        self.set_bar_edge(self._cfg.get("position", "bottom"))

        bar_win = widget.get_toplevel()
        w_alloc = widget.get_allocation()
        _bx, _by, screen_w, _screen_h = self._monitor_geometry(bar_win)
        cx = w_alloc.x + w_alloc.width // 2
        margin = 6
        pill_left, pill_right = self._pill_bounds(bar_win, screen_w)
        left_bound = max(margin, pill_left + margin)
        right_bound = min(screen_w - margin, pill_right - margin)
        x = max(left_bound, min(cx - width // 2, right_bound - width))

        edge = (
            GtkLayerShell.Edge.TOP
            if self._bar_edge == "top"
            else GtkLayerShell.Edge.BOTTOM
        )
        offset = (
            self._cfg.get("height", 42)
            + self._cfg.get("gap_in", 6) + self._cfg.get("gap_out", 6)
            + GAP
        )
        GtkLayerShell.set_margin(self, edge, offset)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, x)

        self.show_all()

    def hide_popup(self) -> None:
        self._cancel_hide()
        if self.get_visible():
            self.hide()
        if self._close_cb:
            cb, self._close_cb = self._close_cb, None
            cb()

    def _on_enter(self, *_args):
        # Pointer is (or is crossing into) the popup: any pending hide is wrong.
        self._pointer_inside = True
        self._cancel_hide()
        if self._enter_cb is not None:
            self._enter_cb()
        return False

    def _on_motion(self, *_args):
        self._pointer_inside = True
        self._cancel_hide()
        return False

    def _on_leave(self, *_args):
        # GTK3/Wayland crossing is unreliable between layer-shell surfaces: a
        # spurious leave can fire while the pointer is still on its way in from
        # the triggering button. Only hide if the pointer had actually been
        # inside the popup, and even then grace briefly so enter/motion can
        # cancel it.
        was_inside = self._pointer_inside
        self._pointer_inside = False
        if was_inside and self._leave_cb is not None and self._hide_timer is None:
            self._hide_timer = GLib.timeout_add(200, self._do_hide)
        return False

    def _cancel_hide(self) -> None:
        if self._hide_timer is not None:
            GLib.source_remove(self._hide_timer)
            self._hide_timer = None

    def _do_hide(self) -> bool:
        self._hide_timer = None
        if self._leave_cb is not None:
            self._leave_cb()
        return GLib.SOURCE_REMOVE

    # ── input shape: only the content box is interactive ──────────

    def _on_size_allocate(self, *_args) -> None:
        wnd = self.get_window()
        if wnd is None:
            return
        region = cairo.Region()
        alloc = self.content.get_allocation()
        region.union(
            cairo.RectangleInt(alloc.x, alloc.y, alloc.width, alloc.height)
        )
        wnd.input_shape_combine_region(region, 0, 0)