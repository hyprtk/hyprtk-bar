"""Layer-shell window hosting the taskbar, plus Hyprland event wiring."""
from __future__ import annotations

import cairo
import logging

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

from .bar import Bar  # noqa: E402
from .config import PYWAL_PATH  # noqa: E402
from .ipc import HyprIPC  # noqa: E402
from .theme import build_css, resolve_palette  # noqa: E402

log = logging.getLogger("hyprtk_bar.app")

# Socket events that should trigger a taskbar refresh.
REFRESH_EVENTS = (
    "openwindow",
    "closewindow",
    "movewindow",
    "workspace",
    "workspacev2",
    "activewindow",
    "activewindowv2",
    "fullscreen",
    "changefloatingmode",
    "focusedmon",
    "moveworkspace",
    "windowtitlev2",
    "windowclassv2",
    "urgent",
    "monitoraddedv2",
    "monitorremovedv2",
    "openlayer",
    "closelayer",
)


class BarWindow(Gtk.Window):
    """A transparent, full-width layer-shell surface pinned to an edge."""

    def __init__(self, cfg: dict):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._cfg = cfg
        self._refresh_id: int | None = None
        self._wal_monitor: Gio.FileMonitor | None = None
        self._wal_debounce: int | None = None

        self.set_title("hyprtk-bar")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_accept_focus(False)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self._ipc = HyprIPC()
        self._bar = Bar(cfg, self._ipc)
        self.add(self._bar)
        self._bar.connect("size-allocate", self._on_size_allocate)

        self._provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), self._provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self._apply_theme()

        self._init_layer_shell()

        self._wire_ipc()
        self._ipc.start()
        self._bar.start()

        if cfg.get("use_pywal", True):
            self._setup_wal_monitor()

    # ── theming ───────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        css = build_css(resolve_palette(self._cfg), self._cfg)
        self._provider.load_from_data(css.encode())

    def _setup_wal_monitor(self) -> None:
        """Watch ~/.cache/wal/ so a wallpaper change re-themes the bar live."""
        try:
            self._wal_monitor = Gio.File.new_for_path(
                str(PYWAL_PATH.parent)
            ).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error as exc:
            log.warning("Could not monitor pywal cache: %s", exc)
            return
        self._wal_monitor.connect("changed", self._on_wal_changed)

    def _on_wal_changed(self, _monitor, file, *_args) -> None:
        if file.get_basename() != PYWAL_PATH.name:
            return
        if self._wal_debounce is not None:
            GLib.source_remove(self._wal_debounce)
        self._wal_debounce = GLib.timeout_add(400, self._reload_wal)

    def _reload_wal(self) -> bool:
        self._wal_debounce = None
        self._apply_theme()
        return GLib.SOURCE_REMOVE

    # ── layer shell ───────────────────────────────────────────────

    def _init_layer_shell(self) -> None:
        total_height = self._cfg["height"] + 2 * self._cfg["margin"]
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "hyprtk-bar")
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        if self._cfg["position"] == "top":
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        else:
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_exclusive_zone(self, total_height)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        self.set_size_request(-1, total_height)

    # ── input shape: only the pill and strip are clickable ────────

    def _on_size_allocate(self, *_args) -> None:
        self._apply_input_shape()

    def _apply_input_shape(self) -> None:
        wnd = self.get_window()
        if wnd is None:
            return
        margin = self._cfg["margin"]
        region = cairo.Region()

        def add(widget, inset_x: int, inset_y: int) -> None:
            alloc = widget.get_allocation()
            rect = cairo.RectangleInt(
                alloc.x + inset_x,
                alloc.y + inset_y,
                max(alloc.width - 2 * inset_x, 0),
                max(alloc.height - 2 * inset_y, 0),
            )
            region.union(rect)

        for child in self._bar.get_children():
            if child is self._bar.pill:
                # The pill's CSS margin insets it on all sides.
                add(child, margin, margin)
            elif child is getattr(self._bar, "strip", None):
                # The strip only has top/bottom CSS margins; hug the right edge.
                add(child, 0, margin)
        wnd.input_shape_combine_region(region, 0, 0)

    # ── IPC ───────────────────────────────────────────────────────

    def _wire_ipc(self) -> None:
        self._ipc.on_connect(self._on_connected)
        for event in REFRESH_EVENTS:
            self._ipc.on(event, self._on_ipc_event)

    def _on_connected(self) -> None:
        GLib.idle_add(self._refresh)

    def _on_ipc_event(self, _data) -> None:
        GLib.idle_add(self._schedule_refresh)

    def _schedule_refresh(self) -> bool:
        if self._refresh_id is not None:
            GLib.source_remove(self._refresh_id)
        self._refresh_id = GLib.timeout_add(120, self._refresh)
        return GLib.SOURCE_REMOVE

    def _refresh(self) -> bool:
        self._refresh_id = None
        clients = self._ipc.query("clients")
        if clients is None:
            return GLib.SOURCE_REMOVE
        workspaces = self._ipc.query("workspaces") or []
        active = self._ipc.query("activeworkspace") or {}
        focus = self._ipc.query("activewindow") or {}
        a_id = active.get("id", 1) if isinstance(active.get("id"), int) else 1
        self._bar.update(clients, workspaces, a_id, focus.get("address"))
        return GLib.SOURCE_REMOVE

    # ── shutdown ──────────────────────────────────────────────────

    def shutdown(self) -> None:
        if self._wal_monitor is not None:
            self._wal_monitor.cancel()
        if self._wal_debounce is not None:
            GLib.source_remove(self._wal_debounce)
        if self._refresh_id is not None:
            GLib.source_remove(self._refresh_id)
        self._bar.shutdown()
        self._ipc.stop()